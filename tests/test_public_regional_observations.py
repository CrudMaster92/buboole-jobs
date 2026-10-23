from datetime import datetime, timedelta, timezone

import pytest

from server.public_jobs import regional
from server.public_jobs.lifecycle import apply_results, empty_state
from server.public_jobs.schema import job_id, json_bytes, timestamp
from server.scrapers.models import ScraperRecipe

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
PIN = {"id": "employer", "company_id": "employer", "company_name": "Employer", "revision": 2,
       "sha256": "a" * 64, "collection_ids": ["canada"]}


def recipe(**metadata):
    return ScraperRecipe.model_validate({"company": "Employer", "careers_url": "https://employer.example/jobs",
        "strategy": "generic_json", "allowed_hosts": ["employer.example"],
        "request": {"url": "https://employer.example/jobs"}, "mapping": {"items": "jobs"},
        "metadata": {"public_regional_snapshot": True, "partial_listing": True, **metadata}})


def packet():
    url = "https://employer.example/jobs/123"
    return {"format": "jobhound-regional-observation", "version": 1, "monitor_id": "employer",
        "company_id": "employer", "revision": 2, "recipe_sha256": PIN["sha256"], "observed_at": timestamp(NOW),
        "jobs": [{"id": job_id("employer", url), "company_id": "employer", "company_name": "Employer",
                  "monitor_ids": ["employer"], "collection_ids": ["canada"], "title": "Warehouse associate",
                  "location": "Lachute, Quebec, Canada", "source_url": url, "source_job_id": "123",
                  "first_seen_at": timestamp(NOW), "last_seen_at": timestamp(NOW), "status": "active"}]}


def save(root, value):
    (root / 'employer.json').write_bytes(json_bytes(value))


def test_regional_replay_does_not_make_jobs_or_source_newer_or_prove_absence(tmp_path):
    save(tmp_path, packet())
    result = regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW + timedelta(hours=12), state=empty_state())
    state = apply_results(empty_state(), result, generation="first", now=NOW + timedelta(hours=12))
    result = regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW + timedelta(hours=30), state=state)
    updated = apply_results(state, result, generation="second", now=NOW + timedelta(hours=30))
    assert updated['sources']['employer']['last_success_at'] == timestamp(NOW)
    assert updated['sources']['employer']['last_attempt_at'] == timestamp(NOW)
    assert not updated['sources']['employer']['complete']
    assert next(iter(updated['jobs'].values()))['job']['last_seen_at'] == timestamp(NOW)
    assert regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW + timedelta(hours=37), state=state) == []


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(revision=3),
    lambda p: p.update(recipe_sha256='b' * 64),
    lambda p: p.update(company_id='someone-else'),
    lambda p: p.update(private_criteria={'title': 'secret'}),
    lambda p: p['jobs'][0].update(source_url='https://other.example/jobs/123'),
    lambda p: p['jobs'][0].update(company_name='Other employer'),
    lambda p: p['jobs'][0].update(monitor_ids=['other']),
    lambda p: p['jobs'][0].update(collection_ids=[]),
    lambda p: p['jobs'][0].update(saved=True),
    lambda p: p['jobs'][0].update(last_seen_at=timestamp(NOW + timedelta(hours=1))),
    lambda p: p.update(observed_at=timestamp(NOW + timedelta(hours=1))),
    lambda p: p.update(jobs=[]),
    lambda p: p.update(observed_at='2026-10-23T00:00:00'),
])
def test_regional_tampering_and_private_fields_are_rejected(tmp_path, mutate):
    value = packet(); mutate(value); save(tmp_path, value)
    with pytest.raises(ValueError):
        regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW, state=empty_state())


def test_regional_requires_explicit_source_opt_in_and_does_not_regress_fresher_cloud_data(tmp_path):
    save(tmp_path, packet())
    with pytest.raises(ValueError, match='opt-in'):
        regional.load_observations(tmp_path, [(PIN, recipe(public_regional_snapshot=False))], now=NOW, state=empty_state())
    state = {**empty_state(), 'sources': {'employer': {'last_success_at': timestamp(NOW + timedelta(hours=1))}}}
    assert regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW + timedelta(hours=2), state=state) == []


def test_regional_export_allowlist_excludes_collector_caches_and_execution_state(monkeypatch):
    value = packet()
    result = {'source': {'status': 'partial'}, 'jobs': value['jobs'], 'detail_cache': {'private': 'sentinel'},
              'continuation_ready': True, 'local_path': 'private sentinel'}
    monkeypatch.setattr(regional, 'collect_monitor', lambda *args, **kwargs: result)
    captured = regional.capture_observation(PIN, recipe(), now=NOW)
    assert 'sentinel' not in json_bytes(captured).decode()
    assert set(captured) == set(value)
    result['source']['status'] = 'failed'
    with pytest.raises(ValueError, match='did not yield'):
        regional.capture_observation(PIN, recipe(), now=NOW)


def test_regional_file_size_limit_is_checked_before_parsing(tmp_path):
    (tmp_path / 'employer.json').write_bytes(b' ' * (regional.MAX_BYTES + 1))
    with pytest.raises(ValueError, match='Unsafe'):
        regional.load_observations(tmp_path, [(PIN, recipe())], now=NOW, state=empty_state())


def test_cli_imports_regional_postings_without_recollecting_or_renewing_them(tmp_path, monkeypatch):
    import json
    import sys
    from server.public_jobs import __main__ as cli
    current = datetime.now(timezone.utc)
    observed = current - timedelta(hours=12)
    value = packet()
    value['observed_at'] = timestamp(observed)
    value['jobs'][0].update(first_seen_at=timestamp(observed), last_seen_at=timestamp(observed))
    save(tmp_path, value)
    lock_path, state_path = tmp_path / 'lock.json', tmp_path / 'state.json'
    lock_path.write_bytes(json_bytes({'catalog_commit': 'a' * 40, 'collections': [], 'excluded': []}))
    monkeypatch.setattr(cli, 'load_monitors', lambda *args: [(PIN, recipe())])
    def collect(selected, **kwargs):
        assert selected == []
        return []
    monkeypatch.setattr(cli, 'collect', collect)
    monkeypatch.setattr(sys, 'argv', ['public-jobs', 'build', '--catalog', str(tmp_path),
        '--lock', str(lock_path), '--state', str(state_path), '--output', str(tmp_path / 'site'),
        '--regional-observations', str(tmp_path), '--generation', 'regional-cli'])
    cli.main()
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert state['sources']['employer']['last_success_at'] == timestamp(observed)
    assert next(iter(state['jobs'].values()))['job']['last_seen_at'] == timestamp(observed)
    assert not state['sources']['employer']['complete']
