import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.scrapers import ScraperRecipe
from server.scrapers.adapters import generic_html, generic_json
from server.scrapers.runtime import (
    ScraperExecutionError, _browser_json_matches, _filter_listing_payload, _read_browser_json,
)


def recipe(**changes):
    return ScraperRecipe.model_validate({
        "company": "Employer", "careers_url": "https://employer.test/jobs",
        "strategy": "generic_json", "allowed_hosts": ["employer.test"],
        "request": {"url": "https://employer.test/jobs", "max_response_bytes": 1024},
        "mapping": {"items": "jobs", "source_id": "id", "url": "slug"}, **changes,
    })


def test_card_anchor_selects_itself_without_merging_jobs():
    selected = recipe(strategy="generic_html", selectors={"item": "a", "title": ":scope", "link": ":scope"})
    jobs = generic_html('<a href="/work/1">Engineer</a><a href="/work/2">Teacher</a>', selected)
    assert [job.title for job in jobs] == ["Engineer", "Teacher"]
    assert [job.source_url for job in jobs] == ["https://employer.test/work/1", "https://employer.test/work/2"]


def test_declared_identity_replaces_javascript_with_encoded_public_posting_url():
    selected = recipe(strategy="generic_html", selectors={"item": "a", "title": ":scope", "link": ":scope"},
                      metadata={"source_id_attribute": "data-id", "link_template": "https://employer.test/work/{source_id}"})
    jobs = generic_html('<a data-id="a/b?c=2" href="javascript:void(0)">Teacher</a><a href="javascript:void(0)">Missing ID</a>', selected)
    assert len(jobs) == 1
    assert jobs[0].source_id == "a/b?c=2"
    assert jobs[0].source_url == "https://employer.test/work/a%2Fb%3Fc%3D2"


def test_json_template_encodes_ids_and_slugs_and_skips_missing_values():
    selected = recipe(metadata={"posting_url_template": "https://employer.test/work/{source_id}?slug={url}"})
    jobs = generic_json({"jobs": [{"id": "123", "title": "Teacher", "slug": "//evil.test?x=1#f"},
                                  {"title": "Missing ID", "slug": "test"}, {"id": "4", "title": "Missing slug"}]}, selected)
    assert len(jobs) == 1
    assert jobs[0].source_url == "https://employer.test/work/123?slug=%2F%2Fevil.test%3Fx%3D1%23f"


@pytest.mark.parametrize("template", [
    "https://evil.test/{source_id}", "http://employer.test/{source_id}",
    "https://{source_id}.employer.test/work", "https://u:p@employer.test/{url}",
    "https://employer.test/{url.__class__}", "https://employer.test/{source_id!r}",
    "https://employer.test/{source_id:20}", "https://employer.test/{other}",
])
def test_templates_cannot_change_authority_or_evaluate_attributes(template):
    with pytest.raises(ValidationError):
        recipe(metadata={"posting_url_template": template})


def capture_recipe(**changes):
    return recipe(strategy="playwright", metadata={"browser_json_url": "https://employer.test/api/jobs",
                  "browser_json_method": "POST", "partial_listing": True}, **changes)


def response(**changes):
    values = dict(url="https://employer.test/api/jobs", request=SimpleNamespace(method="POST"), status=200,
                  headers={"content-type": "application/json"}, body=lambda: b'{"jobs":[]}')
    values.update(changes)
    return SimpleNamespace(**values)


def test_capture_only_matches_explicit_endpoint_and_method():
    selected = capture_recipe()
    assert _browser_json_matches(response(), selected)
    assert not _browser_json_matches(response(url="https://employer.test/api/jobs-extra"), selected)
    assert not _browser_json_matches(response(request=SimpleNamespace(method="GET")), selected)
    assert _read_browser_json(response(), selected) == {"jobs": []}


@pytest.mark.parametrize("changes", [
    {"status": 403}, {"headers": {"content-type": "text/html"}},
    {"body": lambda: b"x" * 1025}, {"body": lambda: b"not JSON"},
    {"headers": {"content-type": "application/json", "content-length": "1025"}},
])
def test_capture_rejects_errors_challenges_and_oversized_payloads(changes):
    with pytest.raises(ScraperExecutionError):
        _read_browser_json(response(**changes), capture_recipe())


def test_captured_json_preserves_exact_employer_boundary():
    selected = capture_recipe(source_filter={"predicates": [{"path": "brandname", "values": ["Super C"]}]})
    payload = {"jobs": [{"id": "1", "title": "Clerk", "slug": "/1", "brandname": ["Super C"]},
                        {"id": "2", "title": "Clerk", "slug": "/2", "brandname": ["Metro"]},
                        {"id": "3", "title": "Clerk", "slug": "/3"}]}
    jobs = generic_json(_filter_listing_payload(payload, selected), selected)
    assert [job.source_id for job in jobs] == ["1"]


@pytest.mark.parametrize("url", ["https://other.test/api/jobs", "http://employer.test/api/jobs", "https://u:p@employer.test/api/jobs"])
def test_capture_schema_rejects_unrelated_or_credential_bearing_endpoints(url):
    with pytest.raises(ValidationError, match="browser_json_url"):
        recipe(strategy="playwright", metadata={"browser_json_url": url, "partial_listing": True})


def test_capture_rejects_unverified_detail_only_ownership():
    with pytest.raises(ValidationError, match="listing evidence"):
        capture_recipe(source_filter={"predicates": [{"phase": "detail", "path": "employer", "values": ["Employer"]}]})


def test_browser_capture_uses_normal_navigation_and_shared_ownership_filter(monkeypatch):
    from contextlib import nullcontext
    from playwright import sync_api
    from server.scrapers.runtime import _run_playwright

    selected = capture_recipe(source_filter={"predicates": [{"path": "brandname", "values": ["Super C"]}]})
    observed = []
    captured = response(body=lambda: json.dumps({"jobs": [
        {"id": "1", "title": "Clerk", "slug": "/1", "brandname": ["Super C"]},
        {"id": "2", "title": "Clerk", "slug": "/2", "brandname": ["Metro"]},
    ]}).encode())

    class Page:
        def route(self, pattern, callback):
            observed.append(("route", pattern))

        def expect_response(self, predicate, **kwargs):
            assert predicate(captured)
            return nullcontext(SimpleNamespace(value=captured))

        def goto(self, url, **kwargs):
            observed.append(("goto", url))

    class Browser:
        def new_page(self, **kwargs):
            assert kwargs == {"service_workers": "block"}
            return Page()

        def close(self):
            observed.append(("close",))

    monkeypatch.setattr(sync_api, "sync_playwright", lambda: nullcontext(
        SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))))
    result = _run_playwright(selected)
    assert [job.source_id for job in result.jobs] == ["1"]
    assert not result.complete
    assert observed == [("route", "**/*"), ("goto", "https://employer.test/jobs"), ("close",)]


def test_html_location_attribute_and_source_jurisdiction_are_explicit_and_missing_values_stay_missing():
    selected = recipe(strategy="generic_html", selectors={"item":".role","title":"h2","link":"a","location":":scope"}, metadata={"location_attribute":"data-ville","location_suffix":"Quebec, Canada"})
    jobs = generic_html('<div class="role" data-ville="Lachute"><h2>Accountant</h2><a href="/1">Read</a></div><div class="role"><h2>Unknown</h2><a href="/2">Read</a></div>', selected)
    assert jobs[0].location == "Lachute, Quebec, Canada"
    assert jobs[1].location == "Unspecified"
    for metadata in [{"location_attribute":"onclick"},{"location_suffix":"x"*101},{"location_suffix":"Quebec\nCanada"},{"pagination_page_base":True},{"pagination_page_base":0}]:
        with pytest.raises(ValidationError):
            recipe(metadata=metadata)


def test_explicit_city_attribute_country_produces_structured_location_without_filling_missing_city():
    selected = recipe(strategy="generic_html", selectors={"item":".role","title":"h2","link":"a","location":":scope"}, metadata={"location_attribute":"data-ville","location_country":"Canada"})
    jobs = generic_html('<div class="role" data-ville="Lachute"><h2>Accountant</h2><a href="/1">Read</a></div><div class="role"><h2>Unknown</h2><a href="/2">Read</a></div>', selected)
    assert [a.model_dump() for a in jobs[0].location_addresses] == [{"country":"Canada","city":"Lachute"}]
    assert jobs[1].location_addresses == []
    with pytest.raises(ValidationError):
        recipe(metadata={"location_country":"Canada"})


def test_browser_capture_rejects_initial_unfiltered_response_and_waits_for_declared_query():
    from types import SimpleNamespace
    from server.scrapers.runtime import _browser_json_matches
    selected = recipe(strategy="playwright", mapping={"items":"jobs"}, metadata={"public_browser":True,"partial_listing":True,"browser_json_url":"https://employer.test/jobs","browser_json_method":"POST","browser_json_request_path":"query.filters.*.city","browser_json_request_value":"Lachute"})
    def response(body):
        return SimpleNamespace(url="https://employer.test/jobs",request=SimpleNamespace(method="POST",post_data_json=body))
    assert not _browser_json_matches(response({"query":{"filters":[]}}), selected)
    assert not _browser_json_matches(response({"query":{"filters":[{"city":"Montreal"}]}}), selected)
    assert _browser_json_matches(response({"query":{"filters":[{"city":"Lachute"}]}}), selected)
    assert _browser_json_matches(response({"query":{"filters":[{"brand":"Super C"},{"city":"Lachute"}]}}), selected)
    assert not _browser_json_matches(response(None), selected)
    for values in [{"browser_json_request_path":"city"}, {"browser_json_request_value":"Lachute"}, {"browser_json_request_path":"../city","browser_json_request_value":"Lachute"}]:
        with pytest.raises(ValidationError):
            recipe(metadata=values)
