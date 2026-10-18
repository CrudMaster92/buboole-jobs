from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from server.scrapers import ScraperRecipe
from server.scrapers.adapters import generic_html


def recipe(**changes):
    base = dict(company="Public employer", careers_url="https://employer.test/jobs",
        strategy="generic_html", allowed_hosts=["employer.test"], request={"url":"https://employer.test/jobs"},
        selectors={"item":"tr", "title":"a", "link":"a"},
        metadata={"closing_date_selector":"td:last-child", "closing_date_timezone":"America/Toronto"})
    base.update(changes)
    return ScraperRecipe.model_validate(base)


def test_expired_and_unknown_deadlines_are_excluded_but_closing_today_is_open():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    dates = [today-timedelta(days=1), today, today+timedelta(days=1)]
    html = ''.join(f'<tr><td><a href="/job/{i}">Role {i}</a></td><td>{date.strftime("%B %d, %Y")}</td></tr>'
                   for i,date in enumerate(dates))
    html += '<tr><td><a href="/job/unknown">No deadline</a></td><td>Unknown</td></tr>'
    jobs = generic_html(html, recipe())
    assert [job.title for job in jobs] == ["Role 1", "Role 2"]


def test_machine_datetime_and_nonbreaking_spaces_are_supported():
    future = datetime.now(ZoneInfo("America/Toronto")).date()+timedelta(days=1)
    html = f'<tr><td><a href="/job/1">Role</a></td><td datetime="{future.isoformat()}">French label</td></tr>'
    assert len(generic_html(html, recipe())) == 1
    html = f'<tr><td><a href="/job/1">Role</a></td><td>{future.strftime("%B %d, %Y").replace(" ",chr(160))}</td></tr>'
    assert len(generic_html(html, recipe())) == 1


def test_explicit_closing_rule_is_not_bypassed_by_page_structured_data():
    import json
    old = datetime.now(ZoneInfo("America/Toronto")).date()-timedelta(days=1)
    structured = {"@type":"JobPosting", "title":"Expired", "url":"https://employer.test/expired"}
    html = '<script type="application/ld+json">'+json.dumps(structured)+'</script>'
    html += f'<tr><td><a href="/expired">Expired</a></td><td>{old.isoformat()}</td></tr>'
    assert generic_html(html, recipe()) == []


@pytest.mark.parametrize("changes", [
    {"strategy":"generic_json"},
    {"metadata":{"closing_date_selector":True}},
    {"metadata":{"closing_date_selector":"td", "closing_date_timezone":"not/a/timezone"}},
])
def test_closing_rule_rejects_unsupported_configuration(changes):
    if "metadata" in changes:
        meta=changes.pop("metadata")
        with pytest.raises(ValidationError):
            base=recipe().model_dump();base.update(changes);base['metadata']=meta;ScraperRecipe.model_validate(base)
    else:
        with pytest.raises(ValidationError):
            recipe(**changes)
