"""Deterministic ATS and generic document adapters."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import JobRecord, ScraperRecipe, LocationAddress
from .normalize import first, make_job, plain_text, normalize_description, parse_date
from .posting_urls import render_template


def _smartrecruiters_description(raw: dict[str, Any]) -> str:
    sections = raw.get("jobAd", {}).get("sections", {})
    return "\n\n".join(
        normalize_description(first(sections, key + ".text"))
        for key in ("jobDescription", "qualifications", "additionalInformation")
    ).strip()


def ashby(data: dict[str, Any], recipe: ScraperRecipe) -> list[JobRecord]:
    jobs = []
    for raw in data.get("jobs", []):
        if raw.get("isListed") is False:
            continue
        locations = [raw.get("location")]
        locations.extend(
            item.get("location") or item.get("name")
            for item in (raw.get("secondaryLocations") or [])
            if isinstance(item, dict)
        )
        location = "; ".join(dict.fromkeys(str(item).strip() for item in locations if item)) or "Unspecified"
        addresses = []
        for item in [raw, *(raw.get("secondaryLocations") or [])]:
            if not isinstance(item, dict):
                continue
            address = item.get("address") or {}
            postal = (address.get("postalAddress") or {}) if isinstance(address, dict) else {}
            if not isinstance(postal, dict):
                continue
            country = plain_text(postal.get("addressCountry")) or None
            city = plain_text(postal.get("addressLocality")) or None
            if country or city:
                address = LocationAddress(country=country, city=city)
                if address not in addresses:
                    addresses.append(address)
        record = make_job(
            company=recipe.company,
            source="ashby",
            source_id=raw.get("id"),
            title=raw.get("title"),
            location=location,
            url=raw.get("jobUrl") or raw.get("applyUrl"),
            base_url=recipe.careers_url,
            description=raw.get("descriptionPlain") or raw.get("descriptionHtml"),
            posted_date=raw.get("publishedAt"),
            employment_type=raw.get("employmentType"),
            salary_min=first(raw, "compensation.min", "salary.min", "salaryRange.min", "compensationTierSummary"),
            salary_max=first(raw, "compensation.max", "salary.max", "salaryRange.max"),
            currency=first(raw, "compensation.currency", "salary.currency", "salaryRange.currency"),
            salary_period=first(raw, "compensation.interval", "salary.interval", "salaryRange.interval"),
            remote_mode="remote" if raw.get("isRemote") is True or raw.get("workplaceType") == "Remote" else raw.get("workplaceType"),
        )
        jobs.append(record.model_copy(update={"location_addresses": addresses}))
    return jobs


def greenhouse(data: dict[str, Any], recipe: ScraperRecipe) -> list[JobRecord]:
    jobs = []
    for raw in data.get("jobs", []):
        location = first(raw, "location.name", "offices.0.name") or "Unspecified"
        metadata = {str(item.get("name", "")).casefold(): item.get("value") for item in raw.get("metadata", []) if isinstance(item, dict)}
        pay_range = first(raw, "pay_input_ranges.0") or {}
        salary_min = pay_range.get("min_cents") / 100 if isinstance(pay_range.get("min_cents"), (int, float)) else first(raw, "salary_range.min")
        salary_max = pay_range.get("max_cents") / 100 if isinstance(pay_range.get("max_cents"), (int, float)) else first(raw, "salary_range.max")
        jobs.append(make_job(company=recipe.company, source="greenhouse", source_id=raw.get("id"), title=raw.get("title"), location=location, url=raw.get("absolute_url"), base_url=recipe.careers_url, description=raw.get("content"), posted_date=raw.get("updated_at"), employment_type=first(raw, "employment_type", "employmentType") or metadata.get("employment type") or metadata.get("job type"), salary_min=salary_min, salary_max=salary_max, currency=pay_range.get("currency_type") or first(raw, "salary_range.currency"), salary_period=pay_range.get("pay_period") or pay_range.get("unit") or first(raw, "salary_range.period")))
    return jobs


def lever(data: list[dict[str, Any]], recipe: ScraperRecipe) -> list[JobRecord]:
    jobs = []
    for raw in data:
        categories = raw.get("categories") or {}
        lists = raw.get("lists") or []
        extra = "\n\n".join(normalize_description(item.get("content")) for item in lists if isinstance(item, dict))
        salary = raw.get("salaryRange") or {}
        jobs.append(make_job(company=recipe.company, source="lever", source_id=raw.get("id"), title=raw.get("text"), location=categories.get("location"), url=raw.get("hostedUrl") or raw.get("applyUrl"), base_url=recipe.careers_url, description=f"{raw.get('descriptionPlain') or raw.get('description') or ''}\n\n{extra}", employment_type=categories.get("commitment"), salary_min=salary.get("min"), salary_max=salary.get("max"), currency=salary.get("currency"), salary_period=salary.get("interval"), remote_mode=raw.get("workplaceType")))
    return jobs


def smartrecruiters(data: dict[str, Any], recipe: ScraperRecipe) -> list[JobRecord]:
    jobs = []
    for raw in data.get("content", data.get("jobs", [])):
        location = raw.get("location") or {}
        location_text = location.get("fullLocation") or ", ".join(filter(None, [location.get("city"), location.get("region"), location.get("country")]))
        description = _smartrecruiters_description(raw)
        jobs.append(make_job(company=recipe.company, source="smartrecruiters", source_id=raw.get("id"), title=raw.get("name") or raw.get("title"), location=location_text, url=raw.get("ref") or raw.get("applyUrl"), base_url=recipe.careers_url, description=description, posted_date=raw.get("releasedDate"), employment_type=first(raw, "typeOfEmployment.label", "typeOfEmployment"), salary_min=first(raw, "compensation.minimum", "compensation.min", "salary.min", "salaryRange.min"), salary_max=first(raw, "compensation.maximum", "compensation.max", "salary.max", "salaryRange.max"), currency=first(raw, "compensation.currency", "salary.currency", "salaryRange.currency"), salary_period=first(raw, "compensation.interval", "compensation.period", "salary.interval", "salaryRange.period"), remote_mode="remote" if location.get("remote") is True else None))
    return jobs


def enrich_smartrecruiters(job: JobRecord, raw: dict[str, Any], recipe: ScraperRecipe) -> JobRecord:
    """Merge one bounded posting-detail response into its list record."""
    location = raw.get("location") or {}
    location_text = location.get("fullLocation") or ", ".join(
        filter(None, [location.get("city"), location.get("region"), location.get("country")])
    )
    return make_job(
        company=job.company, source=job.source, source_id=job.source_id,
        title=raw.get("name") or raw.get("title") or job.title,
        location=location_text or job.location, url=job.source_url, base_url=recipe.careers_url,
        description=_smartrecruiters_description(raw) or job.description,
        posted_date=raw.get("releasedDate") or job.posted_date,
        employment_type=first(raw, "typeOfEmployment.label", "typeOfEmployment") or job.employment_type,
        salary_min=first(raw, "compensation.minimum", "compensation.min", "salary.min", "salaryRange.min") or job.salary_min,
        salary_max=first(raw, "compensation.maximum", "compensation.max", "salary.max", "salaryRange.max") or job.salary_max,
        currency=first(raw, "compensation.currency", "salary.currency", "salaryRange.currency") or job.salary_currency,
        salary_period=first(raw, "compensation.interval", "compensation.period", "salary.interval", "salaryRange.period") or job.salary_period,
        remote_mode="remote" if location.get("remote") is True else job.remote_mode.value,
    )


def workday_public_url(path: str, recipe: ScraperRecipe) -> str:
    """CXS /job paths are relative to the careers board, not the host root."""
    if not path.startswith('/job/'):
        return path
    endpoint = urlsplit(recipe.request.url)
    parts = endpoint.path.split('/')
    if len(parts) < 6 or parts[1:3] != ['wday','cxs']:
        return path
    site = parts[4]
    careers = urlsplit(recipe.careers_url)
    prefix = '/' + site
    if careers.hostname == endpoint.hostname and site in careers.path.split('/'):
        prefix = careers.path.split('/' + site,1)[0] + '/' + site
    return f'{endpoint.scheme}://{endpoint.netloc}{prefix}{path}'


def workday_source_id(raw: dict[str, Any]) -> str:
    """Requisition bullets can follow job category/agency display fields."""
    info = raw.get("jobPostingInfo") or raw
    explicit = first(info, "jobReqId", "jobPostingId")
    if explicit:
        return str(explicit)
    path = raw.get("externalPath") or raw.get("url") or ""
    bullets = raw.get("bulletFields") or []
    if not isinstance(bullets, list):
        bullets = []
    suffix = urlsplit(str(path)).path.rsplit("/", 1)[-1].rsplit("_", 1)
    if len(suffix) == 2 and suffix[1]:
        for value in bullets:
            if isinstance(value, str) and value and (suffix[1] == value or suffix[1].startswith(value + "-")):
                return value
        # The public posting path remains a stable identity when no bullet is
        # evidenced as its requisition ID; never deduplicate by job category.
        return str(path)
    if len(bullets) == 1 and bullets[0]:
        return str(bullets[0])
    return str(path or (bullets[0] if bullets else ""))


def workday(data: dict[str, Any], recipe: ScraperRecipe) -> list[JobRecord]:
    jobs = []
    for raw in data.get("jobPostings", []):
        path = raw.get("externalPath") or raw.get("url")
        info = raw.get("jobPostingInfo") or raw
        if not (info.get("title") or raw.get("title")) or not path:
            continue
        jobs.append(make_job(company=recipe.company, source="workday", source_id=workday_source_id(raw), title=info.get("title") or raw.get("title"), location=info.get("location") or raw.get("locationsText") or raw.get("location"), url=info.get("externalUrl") or workday_public_url(path,recipe), base_url=recipe.careers_url, description=info.get("jobDescription") or raw.get("description"), posted_date=info.get("startDate") or raw.get("postedOn"), employment_type=info.get("timeType") or raw.get("timeType")))
    return jobs


def enrich_workday(job: JobRecord, raw: dict[str, Any], recipe: ScraperRecipe) -> JobRecord:
    """Merge Workday's jobPostingInfo detail payload into its compact list record."""
    info = raw.get("jobPostingInfo") or raw
    return make_job(
        company=job.company, source=job.source, source_id=job.source_id,
        title=info.get("title") or job.title,
        location=info.get("location") or job.location,
        url=info.get("externalUrl") or job.source_url, base_url=recipe.careers_url,
        description=info.get("jobDescription") or info.get("description") or job.description,
        posted_date=info.get("startDate") or job.posted_date,
        employment_type=info.get("timeType") or info.get("workerType") or job.employment_type,
        salary_min=first(info, "salary.min", "salaryRange.min") or job.salary_min,
        salary_max=first(info, "salary.max", "salaryRange.max") or job.salary_max,
        currency=first(info, "salary.currency", "salaryRange.currency") or job.salary_currency,
        salary_period=first(info, "salary.period", "salaryRange.period") or job.salary_period,
        remote_mode=job.remote_mode.value,
    )


def _json_ld_nodes(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _json_ld_nodes(item)
    elif isinstance(data, dict):
        if data.get("@type") == "JobPosting" or "JobPosting" in (data.get("@type") or []):
            yield data
        for key in ("@graph", "itemListElement"):
            if key in data:
                yield from _json_ld_nodes(data[key])


def json_ld(html: str, recipe: ScraperRecipe) -> list[JobRecord]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for raw in _json_ld_nodes(payload):
            location_data = raw.get("jobLocation") or raw.get("applicantLocationRequirements") or {}
            if isinstance(location_data, list):
                location_data = location_data[0] if location_data else {}
            address = first(location_data, "address") or location_data
            if isinstance(address, dict):
                location = ", ".join(filter(None, [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]))
            else:
                location = address
            identifier = raw.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            salary = raw.get("baseSalary") or {}
            salary_value = first(salary, "value")
            salary_min = salary_value.get("minValue") if isinstance(salary_value, dict) else salary_value
            salary_max = salary_value.get("maxValue") if isinstance(salary_value, dict) else salary_value
            jobs.append(make_job(company=recipe.company, source="json_ld", source_id=identifier, title=raw.get("title"), location=location, url=raw.get("url") or recipe.careers_url, base_url=recipe.careers_url, description=raw.get("description"), posted_date=raw.get("datePosted"), employment_type=raw.get("employmentType"), salary_min=salary_min, salary_max=salary_max, currency=salary.get("currency"), salary_period=salary_value.get("unitText") if isinstance(salary_value, dict) else salary.get("unitText"), remote_mode="remote" if raw.get("jobLocationType") == "TELECOMMUTE" else None))
    return jobs


def generic_html(html: str, recipe: ScraperRecipe, *, source: str = "generic_html") -> list[JobRecord]:
    # Prefer standards-based structured data even for pages reached through a generic recipe.
    structured = [] if recipe.metadata.get("closing_date_selector") else json_ld(html, recipe)
    if structured:
        return structured
    soup = BeautifulSoup(html, "html.parser")
    selectors = recipe.selectors
    jobs = []

    def selected(item, field: str):
        selector = selectors.get(field)
        return item if selector == ":scope" else item.select_one(selector) if selector else None

    def node_value(node, *, attribute: str | None = None):
        if not node:
            return None
        return node.get(attribute) or node.get_text(" ", strip=True) if attribute else node.get_text(" ", strip=True)

    for index, item in enumerate(soup.select(selectors.get("item", ".job"))):
        closing_selector = recipe.metadata.get("closing_date_selector")
        if isinstance(closing_selector, str):
            closing_node = item.select_one(closing_selector)
            raw_closing = node_value(closing_node, attribute="datetime")
            deadline = parse_date(raw_closing)
            if deadline is None and raw_closing:
                try:
                    deadline = datetime.strptime(" ".join(raw_closing.split()), "%B %d, %Y").date()
                except ValueError:
                    pass
            today = datetime.now(ZoneInfo(str(recipe.metadata.get("closing_date_timezone", "UTC")))).date()
            # An explicit closing-date rule fails closed when evidence is missing.
            if deadline is None or deadline < today:
                continue
        title_node = selected(item, "title") if "title" in selectors else item.select_one("h2, h3, .title")
        link_node = selected(item, "link") if "link" in selectors else item.select_one("a[href]")
        location_node = selected(item, "location") if "location" in selectors else item.select_one(".location")
        location_attribute = recipe.metadata.get("location_attribute")
        location_text = (location_node.get(location_attribute) if location_node else None) if location_attribute else node_value(location_node)
        source_city = str(location_text).strip() if location_text else None
        if location_text and recipe.metadata.get("location_suffix"):
            location_text = str(location_text).rstrip(" ,") + ", " + recipe.metadata["location_suffix"].strip()
        description_node = item.select_one(selectors.get("description", ".description"))
        employment_node = selected(item, "employment_type")
        salary_node = selected(item, "salary")
        attribute = recipe.metadata.get("source_id_attribute")
        source_id = item.get(attribute) if isinstance(attribute, str) else item.get("data-job-id") or item.get("id")
        link = link_node.get("href") if link_node else None
        if link and urlsplit(urljoin(recipe.careers_url, link)).scheme not in {"http", "https"}:
            link = None
        if link and recipe.metadata.get("strip_link_session_id") is True:
            parts = urlsplit(link)
            path = re.sub(r";jsessionid=[^/;?]*", "", parts.path, flags=re.I)
            link = parts._replace(path=path).geturl()
            careers_host = (urlsplit(recipe.careers_url).hostname or "").lower()
            link_host = (urlsplit(urljoin(recipe.careers_url, link)).hostname or "").lower()
            if careers_host.endswith(".njoyn.com") and link_host == careers_host:
                parts = urlsplit(link)
                query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                         if key.lower() not in {"tbtoken", "chk"}]
                link = parts._replace(query=urlencode(query)).geturl()
        template = recipe.metadata.get("link_template")
        if not link and isinstance(template, str):
            link = render_template(template, recipe.allowed_hosts, source_id=source_id)
        if not title_node or not link:
            continue
        salary_text = node_value(salary_node)
        posted_node = selected(item, "posted_date")
        jobs.append(make_job(
            company=recipe.company, source=source, source_id=source_id,
            title=title_node.get_text(" ", strip=True),
            location=location_text or "Unspecified",
            url=urljoin(recipe.careers_url, link), base_url=recipe.careers_url,
            description=str(description_node) if description_node else "",
            employment_type=node_value(employment_node),
            posted_date=node_value(posted_node, attribute="datetime"),
            remote_mode=node_value(selected(item, "remote_mode")),
            salary_min=node_value(selected(item, "salary_min")) or salary_text,
            salary_max=node_value(selected(item, "salary_max")),
            currency=node_value(selected(item, "salary_currency")),
            salary_period=node_value(selected(item, "salary_period")) or salary_text,
        ))
        if source_city and recipe.metadata.get("location_country"):
            jobs[-1].location_addresses = [LocationAddress(country=recipe.metadata["location_country"], city=source_city)]
    return jobs


def generic_json(data: Any, recipe: ScraperRecipe) -> list[JobRecord]:
    def at_path(value: Any, path: str | None) -> Any:
        if not path:
            return value
        return first(value, path)
    records = at_path(data, recipe.mapping.get("items"))
    if not isinstance(records, list):
        return []
    jobs = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        get = lambda field: at_path(raw, recipe.mapping.get(field, field))
        original_get = get
        if isinstance(recipe.metadata.get("title_prefix"), str):
            get = lambda field: (recipe.metadata["title_prefix"].rstrip() + " " + str(original_get(field) or "")) if field == "title" else original_get(field)
        url = get("url")
        template = recipe.metadata.get("posting_url_template")
        if isinstance(template, str):
            url = render_template(template, recipe.allowed_hosts, source_id=get("source_id"), url=url)
            if not url:
                continue
        prefix = recipe.metadata.get("posting_url_prefix")
        if isinstance(prefix, str) and prefix and url:
            # A public listing may return a slug rather than a posting URL.
            # Encode it as one path component, including any query/fragment.
            url = prefix.rstrip("/") + "/" + quote(str(url), safe="")
        location = get("location")
        if location and recipe.metadata.get("location_suffix"):
            location = str(location).rstrip(" ,") + ", " + recipe.metadata["location_suffix"].strip()
        country = get("location_country") if "location_country" in recipe.mapping else None
        region = get("location_region") if "location_region" in recipe.mapping else None
        city = str(location).strip() if location else None
        if city and isinstance(country, str) and country.strip():
            location = ", ".join(str(value).strip() for value in (city, region, country) if value)
        jobs.append(make_job(company=recipe.company, source="generic_json", source_id=get("source_id"), title=get("title"), location=location, url=url, base_url=recipe.careers_url, description=get("description"), posted_date=get("posted_date"), employment_type=get("employment_type"), salary_min=get("salary_min"), salary_max=get("salary_max"), currency=get("salary_currency"), salary_period=get("salary_period"), remote_mode=get("remote_mode")))
        if city and isinstance(country, str) and country.strip():
            jobs[-1].location_addresses = [LocationAddress(country=country.strip(), city=city)]
    return jobs
