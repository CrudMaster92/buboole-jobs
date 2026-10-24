import httpx
import pytest
from pydantic import ValidationError

from server.scrapers import ScraperRecipe, run_scraper


@pytest.mark.parametrize("strategy", ["generic_json", "ashby"])
def test_invalid_salary_range_keeps_posting_and_valid_sibling(strategy):
    bad = {"id": "bad", "title": "Engineer", "url": "/jobs/bad",
           "jobUrl": "https://employer.test/jobs/bad", "location": "Remote",
           "descriptionHtml": "Salary: $200,000 - $100,000 per year.",
           "description": "Salary: $200,000 - $100,000 per year."}
    good = {**bad, "id": "good", "url": "/jobs/good",
            "jobUrl": "https://employer.test/jobs/good",
            "descriptionHtml": "Salary: $100,000 - $200,000 per year.",
            "description": "Salary: $100,000 - $200,000 per year."}
    selected = recipe(strategy=strategy, mapping={"items": "jobs", "source_id": "id", "title": "title", "url": "url"})
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": [bad, good]}, request=request)))
    result = run_scraper(selected, client=client)
    assert len(result.jobs) == 2
    assert result.jobs[0].salary_min is None and result.jobs[0].salary_max is None
    assert "$200,000 - $100,000" in result.jobs[0].description
    assert (result.jobs[1].salary_min, result.jobs[1].salary_max) == (100000, 200000)


def recipe(**updates):
    return ScraperRecipe.model_validate({
        "company": "Public employer", "careers_url": "https://employer.test/jobs",
        "strategy": "generic_json", "allowed_hosts": ["employer.test"],
        "request": {"url": "https://employer.test/api/jobs", "method": "POST"},
        "mapping": {"items": "Results.Jobs", "source_id": "id", "title": "title", "url": "slug"},
        "metadata": {"detail_fetch_limit": 0}, **updates,
    })


def test_nested_mapped_listing_continues_and_stops_at_short_page():
    pages = []
    def respond(request):
        import json
        page = json.loads(request.content)["Page"]
        pages.append(page)
        jobs = [{"id": str(page), "title": "Engineer", "slug": f"/job/{page}"}] if page < 3 else []
        return httpx.Response(200, json={"Results": {"Jobs": jobs}}, request=request)
    result = run_scraper(recipe(pagination={"kind": "page", "parameter": "Page", "page_size": 1, "max_pages": 4}),
                         client=httpx.Client(transport=httpx.MockTransport(respond)))
    assert pages == [1, 2, 3]
    assert [job.source_id for job in result.jobs] == ["1", "2"]
    assert result.complete


def test_posting_slug_prefix_produces_direct_url_and_encodes_path_controls():
    raw = {"Results": {"Jobs": [{"id": "1", "title": "Nurse", "slug": "1-nurse?x=/other#fragment"}]}}
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw, request=request)))
    result = run_scraper(recipe(metadata={"posting_url_prefix": "https://employer.test/fr/annonce/", "detail_fetch_limit": 0}), client=client)
    assert result.jobs[0].source_url == "https://employer.test/fr/annonce/1-nurse%3Fx%3D%2Fother%23fragment"


@pytest.mark.parametrize("prefix", ["https://outside.test/jobs", "http://employer.test/jobs", "https://user:pass@employer.test/jobs", "https://employer.test/jobs?x=1", 42])
def test_posting_prefix_cannot_escape_recipe_host_boundary(prefix):
    with pytest.raises(ValidationError, match="posting_url_prefix"):
        recipe(metadata={"posting_url_prefix": prefix})


def test_html_employer_filter_fails_closed_and_removes_session_urls():
    html = '''<article id="1"><h3>Nurse</h3><b class="employer">Public Employer</b>
      <a href="/posting/1;jsessionid=anonymous-session?source=search">Apply</a></article>
      <article id="2"><h3>Nurse</h3><b class="employer">Public Employer Agency</b><a href="/posting/2">Apply</a></article>
      <article id="3"><h3>Nurse</h3><a href="/posting/3">Apply</a></article>
      <script type="application/ld+json">{"@type":"JobPosting","title":"Other employer recommendation",
      "url":"https://employer.test/posting/unrelated","hiringOrganization":{"name":"Other employer"}}</script>'''
    selected = recipe(strategy="generic_html", request={"url": "https://employer.test/jobs"}, mapping={},
                      selectors={"item": "article", "title": "h3", "link": "a"},
                      source_filter={"predicates": [{"path": "employer", "values": ["public employer"]}]},
                      metadata={"listing_employer_selector": ".employer", "strip_link_session_id": True,
                                "detail_fetch_limit": 0, "partial_listing": True})
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html, request=request)))
    result = run_scraper(selected, client=client)
    assert [job.source_id for job in result.jobs] == ["1"]
    assert result.jobs[0].source_url == "https://employer.test/posting/1?source=search"
    assert not result.complete


def test_html_ownership_predicate_requires_explicit_evidence_selector():
    from server.scrapers.runtime import ScraperExecutionError
    selected = recipe(strategy="generic_html", request={"url": "https://employer.test/jobs"}, mapping={},
                      selectors={"item": "article", "title": "h3", "link": "a"},
                      source_filter={"predicates": [{"path": "employer", "values": ["public employer"]}]})
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<article></article>", request=request)))
    with pytest.raises(ScraperExecutionError, match="listing_employer_selector"):
        run_scraper(selected, client=client)
