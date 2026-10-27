"""Public collection, lifecycle, privacy and atomic publication contracts."""
from datetime import datetime, timedelta, timezone
import json
import gzip

import httpx
import pytest

from server.public_jobs.collector import HostLimiter, collect_monitor, normalize_job
from server.public_jobs.lifecycle import apply_results, empty_state
from server.public_jobs.publish import publish, validate_publication
from server.public_jobs.schema import job_id, json_bytes, timestamp
from server.scrapers.models import JobRecord, ScrapeResult, ScraperRecipe

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def test_durable_state_read_is_incremental_and_preserves_values(tmp_path, monkeypatch):
    import tracemalloc
    from pathlib import Path
    from server.public_jobs.__main__ import read_state
    value = {"jobs": {str(i): {"description": '雪 🌍 "quoted" \\ paragraph\n' * 200}
                       for i in range(1000)}, "sources": {}, "number": 1.25,
             "integer": 1234567890123, "null": None, "boolean": True}
    target = tmp_path / "state.json"
    encoded = json_bytes(value)
    target.write_bytes(encoded)
    def no_document_read(*args, **kwargs):
        raise AssertionError("State must not allocate the whole document as text")
    monkeypatch.setattr(Path, "read_text", no_document_read)
    tracemalloc.start()
    try:
        restored = read_state(target)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert restored == value
    # Parsed strings remain resident, but there is no additional full text copy.
    tracemalloc.start()
    try:
        previous_loader = json.loads(encoded.decode("utf-8"))
        _, previous_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert previous_loader == restored
    assert peak < previous_peak * 0.7


@pytest.mark.parametrize("content", [b'{"jobs":', b'{} {}', b'[]'])
def test_durable_state_read_rejects_invalid_or_trailing_content(tmp_path, content):
    from server.public_jobs.__main__ import read_state
    target = tmp_path / "state.json"
    target.write_bytes(content)
    with pytest.raises(ValueError):
        read_state(target)


def test_durable_state_json_is_identical_without_a_whole_document_allocation(tmp_path):
    import tracemalloc
    from server.public_jobs.schema import write_json
    # One large state document, including non-ASCII/escaped descriptions. A
    # whole-document dumps/encode peaks at tens of MB; streaming stays bounded.
    value = {"jobs": [{"description": '雪 "quoted" \\ paragraph\n' * 100} for _ in range(4000)]}
    target = tmp_path / "state.pending.json"
    tracemalloc.start()
    try:
        write_json(target, value)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000
    assert target.read_bytes() == json_bytes(value)


def test_cli_publishes_merged_state_and_persists_only_after_validation(tmp_path, monkeypatch):
    import sys
    from server.public_jobs import __main__ as cli
    lock = {"catalog_commit": "a" * 40, "collections": [], "excluded": []}
    lock_path, state_path, output = tmp_path / "lock.json", tmp_path / "state.json", tmp_path / "site"
    lock_path.write_bytes(json_bytes(lock))
    state_path.write_bytes(json_bytes(empty_state()))
    monkeypatch.setattr(cli, "load_monitors", lambda *args: [(MONITOR, None)])
    monkeypatch.setattr(cli, "collect", lambda *args, **kwargs: [clean_result(result([job()]))])
    monkeypatch.setattr(sys, "argv", ["public-jobs", "build", "--catalog", str(tmp_path), "--lock", str(lock_path),
                                    "--state", str(state_path), "--output", str(output), "--generation", "cli-1"])
    cli.main()
    persisted = state_path.read_bytes()
    assert json.loads(persisted)["last_generation"] == "cli-1"
    assert len(json.loads(persisted)["jobs"]) == 1
    monkeypatch.setattr(sys, "argv", [*sys.argv[:-1], "cli-2"])
    def reject(*args, **kwargs):
        raise ValueError("publication rejected")
    monkeypatch.setattr(cli, "publish", reject)
    with pytest.raises(ValueError, match="publication rejected"):
        cli.main()
    assert state_path.read_bytes() == persisted
    assert not state_path.with_suffix(".pending.json").exists()


def test_publication_reports_stages_and_preserves_input_and_contract_defaults(tmp_path, capsys):
    import copy
    state = merge(empty_state(), [clean_result(result([job()]))], 1)
    record = next(iter(state["jobs"].values()))["job"]
    del record["description"], record["status"]
    before = copy.deepcopy(state)
    manifest = publish(state, {"catalog_commit": "a" * 40, "collections": []}, tmp_path,
                       generation="stages", now=NOW, compress_search=True, compress_details=True)
    stages = [json.loads(line)["publication"]["stage"] for line in capsys.readouterr().out.splitlines()]
    assert stages == ["details_started", "details_written", "index_built", "search_written", "validation_started", "validated"]
    assert state == before
    assert manifest["active_jobs"] == manifest["total_jobs"] == 1
    validate_publication(tmp_path / "api/v1", manifest)


def test_company_grouping_preserves_every_field_and_reduces_repeated_text_in_shards(tmp_path):
    from hashlib import sha256
    from server.public_jobs import publish as publisher
    from server.public_jobs.schema import PublicJob
    records = []
    for company in ('zeta', 'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta', 'eta'):
        boilerplate = ''.join(sha256(f'{company}-{index}'.encode()).hexdigest() for index in range(160))
        for index in range(30):
            record = job(url=f"https://{company}.example/jobs/{index}", description=boilerplate + f'\nUnique role {index}.')
            record.update(company_id=company, company_name=company.title(), id=job_id(company, record["source_url"]))
            records.append(record)
    state = merge(empty_state(), [clean_result(result(records))], 1)
    manifest = publish(state, {"catalog_commit": "a" * 40, "collections": []}, tmp_path,
                       generation="grouped", now=NOW, compress_details=True, compress_search=True)
    restored = [job for ref in manifest["detail_pages"]
                for job in json.loads(gzip.decompress((tmp_path / "api/v1" / ref["path"]).read_bytes()))["jobs"]]
    assert [(job["company_id"], job["id"]) for job in restored] == sorted((job["company_id"], job["id"]) for job in records)
    assert {job["id"]: PublicJob.model_validate(job).model_dump(mode="json") for job in restored} == {key: entry["job"] for key, entry in state["jobs"].items()}
    scattered = [state['jobs'][key]['job'] for key in sorted(state['jobs'])]
    scattered_bytes = sum(len(gzip.compress(json_bytes({'generation':'grouped','jobs':[{key:value for key,value in job.items() if value is not None} for job in group]}), compresslevel=6, mtime=0)) for group in publisher._groups(scattered, publisher.DETAIL_PAGE_SIZE))
    grouped_bytes = sum((tmp_path / 'api/v1' / ref['path']).stat().st_size for ref in manifest['detail_pages'])
    assert grouped_bytes < scattered_bytes // 2


def test_search_gzip_is_lossless_and_expanded_index_limit_is_still_enforced(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    records = [job(url=f"https://acme.example/jobs/{i}", description="Full original description. " * 1000) for i in range(12)]
    state = merge(empty_state(), [clean_result(result(records))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    plain = publisher.publish(state, lock, tmp_path / "plain", generation="lossless", now=NOW, compress_details=True)
    packed = publisher.publish(state, lock, tmp_path / "packed", generation="lossless", now=NOW,
                               compress_details=True, compress_search=True)
    plain_api, packed_api = tmp_path / "plain/api/v1", tmp_path / "packed/api/v1"
    expanded_size = 0
    for original, compressed in zip(plain["search_pages"], packed["search_pages"], strict=True):
        assert compressed["path"].endswith(".json.gz")
        expanded = gzip.decompress((packed_api / compressed["path"]).read_bytes())
        assert expanded == (plain_api / original["path"]).read_bytes()
        expanded_size += len(expanded)
    assert packed["total_jobs"] == len(records)
    assert packed["detail_pages"] == plain["detail_pages"]
    report = json.loads((tmp_path / "packed/build-report.json").read_bytes())
    assert report["stored_search_bytes"] < expanded_size // 2
    assert report["search_index_bytes"] == expanded_size
    monkeypatch.setattr(publisher, "MAX_INDEX_BYTES", expanded_size - 1)
    with pytest.raises(ValueError, match="Search index exceeds"):
        publisher.validate_publication(packed_api, packed)

def test_compressed_publication_preserves_every_job_and_full_description(tmp_path):
    records = [job(url=f"https://acme.example/jobs/{i}", description="Long public paragraph. " * 1000) for i in range(101)]
    state = merge(empty_state(), [clean_result(result(records))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": [{"id": "technology", "name": "Technology"}]}
    manifest = publish(state, lock, tmp_path, generation="compressed", now=NOW, compress_details=True)
    api = tmp_path / "api/v1"
    validate_publication(api, manifest)
    details = [job for ref in manifest["detail_pages"] for job in json.loads(gzip.decompress((api / ref["path"]).read_bytes()))["jobs"]]
    assert len(details) == manifest["total_jobs"] == 101
    assert {r["id"] for r in details} == {r["id"] for r in records}
    assert all(r["description"] == records[0]["description"] for r in details)
    assert sum((api / ref["path"]).stat().st_size for ref in manifest["detail_pages"]) < len(json.dumps(details).encode()) // 10

def test_public_json_listing_traverses_beyond_pinned_page_limit_without_mutating_recipe():
    import time
    from server.scrapers.runtime import run_scraper
    recipe = ScraperRecipe.model_validate({**RECIPE, 'pagination': {'kind': 'offset', 'parameter': 'offset', 'page_size': 2, 'max_pages': 1}, 'metadata': {'detail_fetch_limit': 0, 'partial_listing': True}})
    offsets = []
    def handler(request):
        offset = int(request.url.params.get('offset', 0)); offsets.append(offset)
        return httpx.Response(200, json={'total': 6, 'jobs': [{'id': str(i), 'title': 'Engineer', 'url': f'https://acme.example/jobs/{i}'} for i in range(offset, min(offset+2, 6))]})
    def runner(selected, *, client, detail_cache):
        with httpx.Client(transport=httpx.MockTransport(handler)) as mock:
            return run_scraper(selected, client=mock, detail_cache=detail_cache)
    value = collect_monitor(MONITOR, recipe, now=NOW, limiter=HostLimiter(), deadline=time.monotonic()+10, runner=runner)
    assert offsets == [0, 2, 4]
    assert len(value['jobs']) == 6
    assert value['source']['status'] == 'partial'
    assert recipe.coverage_mode == 'bounded' and recipe.pagination.max_pages == 1
MONITOR = {"id": "acme", "company_id": "acme", "company_name": "Acme", "revision": 1, "collection_ids": ["technology"]}
RECIPE = {"version": 1, "company": "Acme", "careers_url": "https://acme.example/careers", "strategy": "generic_json",
          "allowed_hosts": ["acme.example"], "request": {"url": "https://acme.example/jobs"},
          "mapping": {"items": "jobs", "title": "title", "url": "url", "source_id": "id"}}


def test_public_feed_preserves_description_paragraphs():
    assert job(description='<p>First <b>paragraph</b>.</p><p>Second paragraph.</p>')['description'] == 'First paragraph.\n\nSecond paragraph.'


def job(url="https://acme.example/jobs/1", **changes):
    values = dict(company="Acme", source_id="1", title="Engineer", location="Toronto", canonical_url=url,
                  source_url=url, source="generic_json", description="<p>A role</p><script>bad()</script>")
    values.update(changes)
    return normalize_job(JobRecord(**values), MONITOR, NOW)


def result(jobs=None, *, complete=True, status=None, monitor="acme"):
    return {"source": {**MONITOR, "id": monitor, "status": status or ("complete" if complete else "partial"),
                       "complete": complete, "job_count": len(jobs or []), "warnings": []}, "jobs": jobs or []}


def merge(state, results, n, days=0):
    return apply_results(state, results, generation=f"run-{n}", now=NOW + timedelta(days=days))


def clean_result(value):
    value["source"].pop("collection_ids", None)
    return value


def test_two_complete_misses_partial_failure_and_retry_are_safe():
    record = job()
    state = merge(empty_state(), [result([record])], 1)
    state = merge(state, [result()], 2)
    assert state["jobs"][record["id"]]["job"]["status"] == "active"
    state = merge(state, [result([], complete=False), result([], complete=False, status="failed")], 3)
    assert state["jobs"][record["id"]]["observations"]["acme"]["miss_count"] == 1
    assert merge(state, [result()], 3) == state
    state = merge(state, [result()], 4)
    assert state["jobs"][record["id"]]["job"]["status"] == "closed"
    state = merge(state, [result([record])], 5, days=1)
    assert state["jobs"][record["id"]]["job"]["status"] == "active"
    assert state["jobs"][record["id"]]["job"]["first_seen_at"] == timestamp(NOW)


def test_partial_and_failed_sources_expire_without_claiming_closed():
    record = job()
    state = merge(empty_state(), [result([record], complete=False)], 1)
    state = merge(state, [result([], complete=False)], 2, days=3)
    state = merge(state, [result([], complete=False, status="failed")], 3, days=8)
    assert state["jobs"][record["id"]]["job"]["status"] == "expired"
    assert state["jobs"][record["id"]]["job"]["last_seen_at"] == timestamp(NOW)
    assert state["sources"]["acme"]["last_success_at"] == timestamp(NOW + timedelta(days=3))


def test_overlapping_monitors_need_all_observations_closed():
    record = job()
    state = merge(empty_state(), [result([record]), result([record], monitor="acme-other")], 1)
    for run in (2, 3):
        state = merge(state, [result(), result([record], monitor="acme-other")], run)
    assert len(state["jobs"]) == 1
    assert state["jobs"][record["id"]]["job"]["status"] == "active"
    assert state["jobs"][record["id"]]["job"]["monitor_ids"] == ["acme", "acme-other"]


def test_identity_and_normalization_only_publish_allowlisted_public_fields():
    record = job()
    assert "bad()" not in record["description"] and "<" not in record["description"]
    assert job_id("acme", record["source_url"] + "#fragment") == record["id"]
    assert job_id("other", record["source_url"]) != record["id"]
    assert not {"criteria", "resume", "notes", "headers", "recipe"} & record.keys()
    from server.public_jobs.schema import public_url
    with pytest.raises(ValueError):
        public_url("https://user:secret@acme.example/jobs/1")


def test_collector_uses_shared_runtime_and_rejects_invalid_complete_results():
    import time
    received = {}
    def runner(recipe, *, client, detail_cache):
        received.update(limit=recipe.metadata["detail_fetch_limit"], dns=client._jobhound_resolve_dns)
        return ScrapeResult(strategy="generic_json", complete=False, jobs=[JobRecord(company="Acme", source_id="1",
            title="Engineer", canonical_url="https://acme.example/1", source_url="https://acme.example/1", source="generic_json")])
    value = collect_monitor(MONITOR, ScraperRecipe.model_validate(RECIPE), now=NOW, limiter=HostLimiter(),
                            deadline=time.monotonic() + 10, runner=runner)
    assert value["source"]["status"] == "partial" and len(value["jobs"]) == 1
    assert received == {"limit": 20, "dns": True}


def test_publisher_validates_before_pointer_switch_and_has_hashed_lazy_details(tmp_path):
    state = merge(empty_state(), [clean_result(result([job()]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": [{"id": "technology", "name": "Technology"}]}
    manifest = publish(state, lock, tmp_path, generation="20260926-1", now=NOW)
    api = tmp_path / "api/v1"
    validate_publication(api, manifest)
    search = json.loads((api / manifest["search_pages"][0]["path"]).read_text())
    assert "description" not in search["jobs"][0]
    assert "salary_min" not in search["jobs"][0]
    details = json.loads((api / manifest["detail_pages"][0]["path"]).read_text())
    from server.public_jobs.schema import PublicJob
    assert PublicJob.model_validate(details["jobs"][0]).salary_min is None
    assert search["jobs"][0]["detail_ref"]["sha256"] == manifest["detail_pages"][0]["sha256"]
    before = (api / "manifest.json").read_bytes()
    state["jobs"][job()["id"]]["job"]["private_data"] = "must never leak"
    with pytest.raises(ValueError):
        publish(state, lock, tmp_path, generation="20260926-2", now=NOW)
    assert (api / "manifest.json").read_bytes() == before
    (api / manifest["search_pages"][0]["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="hash"):
        validate_publication(api, manifest)


def test_catalog_requires_exact_commit_and_recipe_hash(tmp_path, monkeypatch):
    from server.public_jobs import catalog
    monitor = {"id": "acme", "company_id": "acme", "revision": 1,
               "verification": {"status": "verified"}, "recipe": RECIPE}
    path = tmp_path / "recipe.json"
    path.write_bytes(json_bytes(monitor))
    from server.public_jobs.schema import digest
    lock = {"repository": "CrudMaster92/job-hound-presets", "catalog_commit": "a" * 40,
            "monitors": [{**MONITOR, "path": "recipe.json", "sha256": digest(path.read_bytes())}]}
    monkeypatch.setattr(catalog, "source_commit", lambda root: "b" * 40)
    with pytest.raises(ValueError, match="checkout"):
        catalog.load_monitors(tmp_path, lock)
    monkeypatch.setattr(catalog, "source_commit", lambda root: "a" * 40)
    assert len(catalog.load_monitors(tmp_path, lock)) == 1
    path.write_text("{}")
    with pytest.raises(ValueError, match="content"):
        catalog.load_monitors(tmp_path, lock)

def test_coverage_reports_missing_collections_stale_pins_and_bounded_sources(tmp_path):
    from server.public_jobs.coverage import catalog_coverage
    from server.public_jobs.schema import digest
    root = tmp_path / 'catalog'
    path = root / 'companies/acme/monitors/acme.json'
    path.parent.mkdir(parents=True)
    old = {'id': 'acme', 'company_id': 'acme', 'revision': 1, 'recipe': {**RECIPE, 'pagination': {'kind': 'offset', 'max_pages': 10, 'page_size': 20}}}
    pin = {'id': 'acme', 'revision': 1, 'sha256': digest(json_bytes(old))}
    path.write_bytes(json_bytes({**old, 'revision': 2}))
    extra = path.with_name('new-source.json')
    extra.write_bytes(json_bytes({**old, 'id': 'new-source'}))
    (root / 'collections').mkdir()
    (root / 'collections/science.json').write_bytes(json_bytes({'id': 'science', 'companies': [{'company_id': 'acme', 'monitor_ids': ['acme', 'new-source']}]}))
    report = catalog_coverage(root, {'monitors': [pin], 'excluded': [], 'collections': []})
    assert report['not_pinned'] == ['new-source']
    assert report['outdated_pins'] == [{'id': 'acme', 'pinned_revision': 1, 'catalog_revision': 2}]
    assert report['collections'][0]['present_in_feed'] is False
    assert report['collections'][0]['admitted'] == 1
    assert report['bounded_pagination'][0]['max_pages'] == 10


def test_detail_cache_advances_bounded_batches_and_only_refetches_changed_listings():
    from server.scrapers.detection import build_recipe
    from server.scrapers.runtime import run_scraper
    recipe = build_recipe("Acme", "https://careers.smartrecruiters.com/Acme")
    recipe.metadata["detail_fetch_limit"] = 1
    postings = [{"id": name, "name": name, "ref": f"https://jobs.smartrecruiters.com/Acme/{name}"} for name in ("one", "two")]
    requests = []
    def handler(request):
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"totalFound": 2, "content": postings})
        requests.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"jobAd": {"sections": {"jobDescription": {"text": "Role details"}}}})
    cache = {}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run_scraper(recipe, client=client, detail_cache=cache)
        assert requests == ["one"]
        run_scraper(recipe, client=client, detail_cache=cache)
        assert requests == ["one", "two"]
        third = run_scraper(recipe, client=client, detail_cache=cache)
        assert requests == ["one", "two"] and all(job.description for job in third.jobs)
        postings[0]["name"] = "Changed role"
        run_scraper(recipe, client=client, detail_cache=cache)
        assert requests == ["one", "two", "one"]


def test_retention_removes_unseen_public_records_after_thirty_days():
    record = job()
    state = merge(empty_state(), [result([record])], 1)
    state = merge(state, [result([], complete=False)], 2, days=31)
    assert state["jobs"] == {}


def test_details_split_by_bytes_before_the_count_limit(tmp_path):
    records = [job(f"https://acme.example/jobs/{index}", source_id=str(index), description="x" * 100_000) for index in range(100)]
    state = merge(empty_state(), [clean_result(result(records))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    manifest = publish(state, lock, tmp_path, generation="large", now=NOW)
    assert len(manifest["detail_pages"]) == 2
    assert all((tmp_path / 'api/v1' / ref['path']).stat().st_size <= 7_000_000 for ref in manifest['detail_pages'])


def test_salary_inference_does_not_turn_million_dollar_sales_quotas_into_pay():
    from server.scrapers.normalize import infer_salary
    assert infer_salary("Track record closing $2M+ annual quotas. Lunch stipend $75.") == (None, None, None)
    assert infer_salary("Managed $5M annual revenue. Salary: USD $120,000 to $150,000 per year.")[:2] == (120000, 150000)


def test_runtime_export_is_portable_between_windows_and_linux(tmp_path, monkeypatch):
    import server.public_jobs.export as exporter
    source, destination = tmp_path / "source", tmp_path / "export"
    source.mkdir()
    (source / "module.py").write_bytes(b"value = 1\r\n")
    monkeypatch.setattr(exporter, "EXPORT_PATHS", ["module.py"])
    exporter.export_runtime(source, destination)
    assert (destination / "module.py").read_bytes() == b"value = 1\n"
    exporter.export_runtime(source, destination, check=True)
    exporter.export_runtime(destination, destination, check=True)

def test_publication_adapts_search_text_without_losing_jobs_or_full_descriptions(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    monkeypatch.setattr(publisher, "MAX_INDEX_BYTES", 18_000)
    description = ('"quoted" \\ 雪\n' * 700)
    records = [job(f"https://acme.example/jobs/{index}", source_id=str(index), description=description)
               for index in range(8)]
    state = merge(empty_state(), [clean_result(result(records))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    manifest = publisher.publish(state, lock, tmp_path, generation="enriched", now=NOW)
    api = tmp_path / "api/v1"
    index_bytes = sum((api / ref["path"]).stat().st_size for ref in manifest["search_pages"])
    search = [item for ref in manifest["search_pages"]
              for item in json.loads((api / ref["path"]).read_text(encoding="utf-8"))["jobs"]]
    details = [item for ref in manifest["detail_pages"]
               for item in json.loads((api / ref["path"]).read_text(encoding="utf-8"))["jobs"]]
    assert index_bytes <= 18_000
    assert {item["id"] for item in search} == {item["id"] for item in records}
    assert {item["id"] for item in details} == {item["id"] for item in records}
    assert all(item["description"] == records[0]["description"] for item in details)
    assert all(0 < len(item["search_text"]) < 2000 for item in search)
    report = json.loads((tmp_path / "build-report.json").read_text())
    assert report["stage"] == "validated"
    assert report["search_index_bytes"] == index_bytes
    assert report["jobs_with_descriptions"] == 8
    assert all(len(item["search_text"]) == report["search_text_max_chars"] for item in search)


def test_search_metadata_above_previous_200_mb_budget_is_accepted():
    from server.public_jobs import publish as publisher
    rows = [{"title": "x" * 3000, "search_text": ""} for _ in range(70_000)]
    snippet_chars, size = publisher._fit_search_text(rows, "large-board")
    assert publisher.MAX_INDEX_BYTES == 350_000_000
    assert 200_000_000 < size <= publisher.MAX_INDEX_BYTES
    assert snippet_chars == publisher.MAX_SEARCH_TEXT_CHARS
    assert len(rows) == 70_000


def test_ashby_preserves_secondary_address_evidence_through_publication(tmp_path):
    from server.scrapers.adapters import ashby
    from server.public_jobs.schema import PublicJob
    recipe = ScraperRecipe.model_validate({"version": 1, "company": "Acme", "strategy": "ashby",
        "careers_url": "https://jobs.ashbyhq.com/acme", "allowed_hosts": ["jobs.ashbyhq.com", "api.ashbyhq.com"],
        "request": {"url": "https://api.ashbyhq.com/posting-api/job-board/acme"}})
    raw = {"id": "one", "title": "Engineer", "location": "London", "jobUrl": "https://jobs.ashbyhq.com/acme/one",
        "descriptionPlain": "Complete description", "isListed": True,
        "address": {"postalAddress": {"addressCountry": "United Kingdom", "addressLocality": "London"}},
        "secondaryLocations": [{"location": "Toronto", "address": {"postalAddress": {"addressCountry": "Canada", "addressLocality": "Toronto"}}},
                               {"location": "Canada", "address": {"postalAddress": {"addressCountry": "Canada"}}}]}
    record = normalize_job(ashby({"jobs": [raw]}, recipe)[0], MONITOR, NOW)
    assert record["location"] == "London; Toronto; Canada"
    assert record["location_addresses"] == [{"country": "United Kingdom", "city": "London"}, {"country": "Canada", "city": "Toronto"}, {"country": "Canada", "city": None}]
    state = merge(empty_state(), [clean_result(result([record]))], 1)
    manifest = publish(state, {"catalog_commit": "a" * 40, "collections": []}, tmp_path, generation="addresses", now=NOW, compress_details=True)
    api = tmp_path / "api/v1"
    search = json.loads((api / manifest["search_pages"][0]["path"]).read_bytes())["jobs"][0]
    detail = json.loads(gzip.decompress((api / manifest["detail_pages"][0]["path"]).read_bytes()))["jobs"][0]
    assert search["location_addresses"] == record["location_addresses"]
    assert PublicJob.model_validate(detail).model_dump(mode="json") == state["jobs"][record["id"]]["job"]


def test_required_metadata_overflow_preserves_previous_generation(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    state = merge(empty_state(), [clean_result(result([job()]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    publisher.publish(state, lock, tmp_path, generation="before", now=NOW)
    previous = (tmp_path / "api/v1/manifest.json").read_bytes()
    monkeypatch.setattr(publisher, "MAX_INDEX_BYTES", 1)
    with pytest.raises(ValueError, match="Required search metadata alone"):
        publisher.publish(state, lock, tmp_path, generation="after", now=NOW)
    assert (tmp_path / "api/v1/manifest.json").read_bytes() == previous


def test_publication_budget_counts_retained_generations_without_early_deletion(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    state = merge(empty_state(), [clean_result(result([job()]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    for number in range(1, 4):
        publisher.publish(state, lock, tmp_path, generation=f"20260926-{number}", now=NOW)
    api = tmp_path / "api/v1"
    size = sum(p.stat().st_size for p in api.rglob("*") if p.is_file())
    monkeypatch.setattr(publisher, "MAX_PUBLISHED_BYTES", size + 500)
    publisher.publish(state, lock, tmp_path, generation="20260926-4", now=NOW)
    assert (api / "snapshots/20260926-1").exists()
    assert sum(p.stat().st_size for p in api.rglob("*") if p.is_file()) > publisher.MAX_PUBLISHED_BYTES
    publisher.retain_generations(tmp_path)
    assert not (api / "snapshots/20260926-1").exists()
    assert not (api / "snapshots/20260926-2").exists()
    assert (api / "snapshots/20260926-3").exists()
    assert (api / "snapshots/20260926-4").exists()
    assert sum(p.stat().st_size for p in api.rglob("*") if p.is_file()) <= publisher.MAX_PUBLISHED_BYTES


def test_publication_fits_snippets_to_shared_snapshot_budget_without_losing_details(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    record = job()
    record["description"] = "Full description. " * 1000
    state = merge(empty_state(), [clean_result(result([record]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    first = publisher.publish(state, lock, tmp_path, generation="20261003-01", now=NOW)
    api = tmp_path / "api/v1"
    prior = api / "snapshots/20261003-01"
    prior_contents = {p.name: p.read_bytes() for p in prior.iterdir()}
    prior_bytes = sum(len(content) for content in prior_contents.values())
    budget = 2 * prior_bytes + (api / "manifest.json").stat().st_size - 500
    monkeypatch.setattr(publisher, "MAX_PUBLISHED_BYTES", budget)
    second = publisher.publish(state, lock, tmp_path, generation="20261003-02", now=NOW)
    assert {p.name: p.read_bytes() for p in prior.iterdir()} == prior_contents
    search = json.loads((api / second["search_pages"][0]["path"]).read_bytes())["jobs"]
    details = json.loads((api / second["detail_pages"][0]["path"]).read_bytes())["jobs"]
    assert len(search) == len(details) == first["total_jobs"] == 1
    assert len(search[0]["search_text"]) < publisher.MAX_SEARCH_TEXT_CHARS
    assert details[0]["description"] == record["description"]
    publisher.retain_generations(tmp_path)
    assert sum(p.stat().st_size for p in api.rglob("*") if p.is_file()) <= budget
    publisher.validate_publication(api, second)


def test_repeated_publications_reserve_space_for_next_snapshot(tmp_path, monkeypatch):
    from server.public_jobs import publish as publisher
    monkeypatch.setattr(publisher, "MAX_PUBLISHED_BYTES", 42_000)
    record = job(description="Full description. " * 1000)
    state = merge(empty_state(), [clean_result(result([record]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    previous = None
    for number in range(4):
        manifest = publisher.publish(state, lock, tmp_path, generation=f"capacity-{number}", now=NOW)
        api = tmp_path / "api/v1"
        snapshot = api / "snapshots" / manifest["generation"]
        assert sum(p.stat().st_size for p in snapshot.iterdir()) <= 21_000
        if previous:
            path, contents = previous
            assert {p.name: p.read_bytes() for p in path.iterdir()} == contents
        details = json.loads((api / manifest["detail_pages"][0]["path"]).read_bytes())["jobs"]
        assert details[0]["description"] == record["description"]
        assert manifest["total_jobs"] == 1
        publisher.retain_generations(tmp_path)
        publisher.validate_publication(api, manifest)
        previous = snapshot, {p.name: p.read_bytes() for p in snapshot.iterdir()}


def test_compact_details_round_trip_every_public_field(tmp_path):
    from server.public_jobs.schema import PublicJob
    record = job(description="Full description. " * 1000, employment_type="Full-time", salary_min=0)
    state = merge(empty_state(), [clean_result(result([record]))], 1)
    lock = {"catalog_commit": "a" * 40, "collections": []}
    manifest = publish(state, lock, tmp_path, generation="compact", now=NOW)
    data = json.loads((tmp_path / "api/v1" / manifest["detail_pages"][0]["path"]).read_bytes())["jobs"][0]
    assert not any(value is None for value in data.values())
    assert data["salary_min"] == 0
    assert PublicJob.model_validate(data).model_dump(mode="json") == state["jobs"][record["id"]]["job"]
    validate_publication(tmp_path / "api/v1", manifest)


def test_budget_exhaustion_during_details_preserves_listing_and_retry_cache():
    from server.public_jobs.collector import CollectionBudgetError
    from server.scrapers.runtime import run_scraper
    from server.scrapers import build_recipe
    import httpx
    recipe = build_recipe("Acme", "https://careers.smartrecruiters.com/Acme")
    cache = {}
    def handler(request):
        if request.url.path.endswith("/postings"):
            return httpx.Response(200, json={"content": [{"id": "1", "name": "Engineer",
                "ref": "https://api.smartrecruiters.com/v1/companies/Acme/postings/1"}]})
        raise CollectionBudgetError("Source request/time budget exhausted")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        value = run_scraper(recipe, client=client, detail_cache=cache)
    assert len(value.jobs) == 1 and value.complete
    assert cache["1"]["failures"] == 1
    assert "description detail enrichment was incomplete for 1 jobs" in value.warnings


def test_collector_preserves_withheld_listing_retry_state():
    import time
    def runner(recipe, *, client, detail_cache):
        detail_cache["withheld"] = {"signature": "same", "failures": 1, "next_attempt_at": 100}
        return ScrapeResult(strategy="generic_json", complete=False, jobs=[],
                            warnings=["source ownership could not be verified for 1 jobs"])
    value = collect_monitor(MONITOR, ScraperRecipe.model_validate(RECIPE), now=NOW,
                            limiter=HostLimiter(), deadline=time.monotonic() + 10, runner=runner)
    assert not value["jobs"] and value["source"]["status"] == "partial"
    assert value["detail_cache"]["withheld"]["failures"] == 1


def test_same_application_url_keeps_all_current_explicit_offices_without_carrying_old_offices_forward():
    first = job(location="Lachute, Canada", location_addresses=[{"country":"Canada","city":"Lachute"}])
    second = job(location="Terrebonne, Canada", location_addresses=[{"country":"Canada","city":"Terrebonne"}])
    state = merge(empty_state(), [result([first, second, first])], 1)
    assert len(state["jobs"]) == 1
    posting = next(iter(state["jobs"].values()))["job"]
    assert posting["location"] == "Multiple locations"
    assert {a["city"] for a in posting["location_addresses"]} == {"Lachute", "Terrebonne"}
    next_state = merge(state, [result([second])], 2)
    assert next(iter(next_state["jobs"].values()))["job"]["location_addresses"] == second["location_addresses"]


def test_cli_prioritizes_changed_reviewed_revision_before_older_unchanged_source(tmp_path, monkeypatch):
    import sys
    from server.public_jobs import __main__ as cli
    lock_path, state_path = tmp_path / "lock.json", tmp_path / "state.json"
    lock_path.write_bytes(json_bytes({"catalog_commit":"a"*40,"collections":[],"excluded":[]}))
    state = empty_state()
    base = {key:value for key,value in MONITOR.items() if key != "collection_ids"}
    state["sources"] = {name:{**base,"id":name,"status":"partial","complete":False,"job_count":0,"warnings":[],"last_success_at":None,"last_attempt_at":attempt} for name,attempt in [("changed","2026-09-26T11:00:00Z"),("old","2026-09-20T00:00:00Z")]}
    state_path.write_bytes(json_bytes(state))
    monkeypatch.setattr(cli, "load_monitors", lambda *args: [({**MONITOR,"id":"old"},None),({**MONITOR,"id":"changed","revision":2},None)])
    observed = []
    def collect(selected, **kwargs):
        observed.extend(entry["id"] for entry, recipe in selected)
        return [clean_result(result([job()]))]
    monkeypatch.setattr(cli, "collect", collect)
    monkeypatch.setattr(sys,"argv",["public-jobs","build","--catalog",str(tmp_path),"--lock",str(lock_path),"--state",str(state_path),"--output",str(tmp_path/"site"),"--generation","priority-test"])
    cli.main()
    assert observed == ["changed","old"]
