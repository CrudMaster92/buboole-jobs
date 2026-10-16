from urllib.parse import parse_qs, urlsplit

from server.scrapers import ScraperRecipe
from server.scrapers.adapters import generic_html


def _job(token="first", *, enabled=True, host="employer.njoyn.com", link_host=None):
    base = f"https://{host}/xweb.asp"
    target = f"https://{link_host}/xweb.asp" if link_host else "xweb.asp"
    link = f"{target}?tbtoken={token}&CHK=changing&clid=12&Page=JobDetails&Jobid=J1026-001&BRID=42&lang=1&empty="
    recipe = ScraperRecipe.model_validate({
        "company": "Employer", "careers_url": base, "strategy": "generic_html",
        "allowed_hosts": [host], "request": {"url": base},
        "selectors": {"item": "tr", "title": "td.title", "link": "a"},
        "metadata": {"strip_link_session_id": enabled},
    })
    html = f'<table><tr><td><a href="{link}">J1026-001</a></td><td class="title">Engineer</td></tr></table>'
    return generic_html(html, recipe)[0]


def test_njoyn_anonymous_tokens_do_not_change_job_identity():
    first, second = _job("first"), _job("second")
    assert first.source_url == second.source_url
    assert first.source_id == second.source_id
    assert parse_qs(urlsplit(first.source_url).query, keep_blank_values=True) == {
        "clid": ["12"], "Page": ["JobDetails"], "Jobid": ["J1026-001"],
        "BRID": ["42"], "lang": ["1"], "empty": [""],
    }


def test_njoyn_token_stripping_requires_existing_opt_in():
    assert "tbtoken=" in _job(enabled=False).source_url


def test_other_careers_hosts_keep_their_query_parameters():
    assert "tbtoken=" in _job(host="jobs.example.com").source_url


def test_njoyn_recipe_does_not_rewrite_external_link_tokens():
    assert "tbtoken=" in _job(link_host="other.example.com").source_url
