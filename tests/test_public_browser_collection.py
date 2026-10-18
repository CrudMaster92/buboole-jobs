import time
from types import SimpleNamespace

import pytest

from server.public_jobs import browser
from server.scrapers import ScraperRecipe
from server.scrapers.adapters import generic_json


def recipe(**metadata):
    return ScraperRecipe.model_validate(dict(company="CAF", careers_url="https://employer.test/careers",
        strategy="playwright",allowed_hosts=["employer.test"],request={"url":"https://employer.test/careers"},
        pagination={"kind":"none","max_pages":1},metadata=metadata))


def test_public_browser_needs_explicit_review_and_partial_bounds():
    assert not browser.eligible(recipe())
    assert not browser.eligible(recipe(public_browser=True))
    assert browser.eligible(recipe(public_browser=True, partial_listing=True))
    r=recipe(public_browser=True, partial_listing=True);r.pagination.max_pages=6
    assert not browser.eligible(r)


def test_public_browser_request_time_and_response_budgets(monkeypatch):
    b=browser.BrowserBudget(10)
    with pytest.raises(RuntimeError):b.request("http://employer.test/jobs")
    b=browser.BrowserBudget(10);b.requests=browser.MAX_REQUESTS
    with pytest.raises(RuntimeError):b.request("https://employer.test/jobs")
    b=browser.BrowserBudget(10);b.deadline=time.monotonic()-1
    with pytest.raises(RuntimeError):b.check()
    monkeypatch.setattr(browser,"MAX_BYTES",2)
    b=browser.BrowserBudget(10)
    b.finished(SimpleNamespace(response=lambda:SimpleNamespace(status=200,body=lambda:b'123')))
    with pytest.raises(RuntimeError):b.check()


def test_career_profile_label_is_part_of_shared_normalization():
    r=recipe(title_prefix="Recruitment career profile: ")
    r.mapping={"items":"data","source_id":"id","title":"name","url":"url"}
    jobs=generic_json({"data":[{"id":"1","name":"Pilot","url":"https://employer.test/pilot"}]},r)
    assert jobs[0].title=="Recruitment career profile: Pilot"


def test_isolated_worker_filters_secrets_and_kills_its_process_tree(monkeypatch):
    calls={};monkeypatch.setenv("GITHUB_TOKEN","must-not-leave-parent")
    class Process:
        pid=123;returncode=None
        def communicate(self,*args,**kwargs):raise browser.subprocess.TimeoutExpired("worker",1)
        def poll(self):return None
        def wait(self):self.returncode=-1
    def popen(*args,**kwargs):calls.update(kwargs);return Process()
    monkeypatch.setattr(browser.subprocess,"Popen",popen)
    monkeypatch.setattr(browser.subprocess,"run",lambda *args,**kwargs:calls.update(killed=True))
    monkeypatch.setattr(browser.os,"killpg",lambda *args:calls.update(killed=True),raising=False)
    class Guard:
        def release(self):calls['released']=True
    limiter=SimpleNamespace(acquire=lambda *args:Guard(),last={})
    with pytest.raises(browser.subprocess.TimeoutExpired):
        browser.collect_browser(recipe(public_browser=True,partial_listing=True),deadline=time.monotonic()+1,limiter=limiter)
    assert "GITHUB_TOKEN" not in calls['env']
    assert calls['killed'] and calls['released']


def test_runtime_passes_public_policy_to_browser(monkeypatch):
    from server.scrapers import runtime
    from server.scrapers.models import ScrapeResult
    policy = object()
    seen = {}
    def collect(selected, *, browser_policy=None):
        seen["policy"] = browser_policy
        return ScrapeResult(strategy="playwright", jobs=[])
    monkeypatch.setattr(runtime, "_run_playwright", collect)
    runtime.run_scraper(recipe(), browser_policy=policy)
    assert seen["policy"] is policy
