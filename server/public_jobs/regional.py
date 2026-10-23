"""Public-only observations collected on an ordinary regional host, never a proxy."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from pydantic import Field

from .collector import HostLimiter, collect_monitor
from .schema import Contract, PublicJob, job_id, json_bytes, parse_time, timestamp

MAX_BYTES = 5_000_000
MAX_AGE = timedelta(hours=36)


class RegionalObservation(Contract):
    format: str = "jobhound-regional-observation"
    version: int = 1
    monitor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    company_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    revision: int
    recipe_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: str
    jobs: list[PublicJob] = Field(min_length=1, max_length=5000)


def _document(value, monitor, recipe, now):
    packet = RegionalObservation.model_validate(value)
    if packet.format != "jobhound-regional-observation" or packet.version != 1:
        raise ValueError("Unsupported regional observation format")
    if recipe.metadata.get("public_regional_snapshot") is not True:
        raise ValueError("Regional observations require an explicitly reviewed source opt-in")
    if (packet.monitor_id, packet.company_id, packet.revision, packet.recipe_sha256) != (
            monitor["id"], monitor["company_id"], monitor["revision"], monitor["sha256"]):
        raise ValueError("Regional observation does not match the reviewed source pin")
    observed = parse_time(packet.observed_at)
    if not packet.observed_at.endswith("Z"):
        raise ValueError("Regional observation requires an explicit UTC timestamp")
    if observed > now + timedelta(minutes=5):
        raise ValueError("Regional observation has a future timestamp")
    if now - observed > MAX_AGE:
        return None
    rows = []
    for job in packet.jobs:
        if (job.company_id != monitor["company_id"] or job.company_name != monitor["company_name"]
                or job.id != job_id(job.company_id, job.source_url)
                or job.monitor_ids != [monitor["id"]]
                or sorted(job.collection_ids) != sorted(monitor["collection_ids"])
                or job.status != "active"
                or urlsplit(job.source_url).hostname not in recipe.allowed_hosts
                or parse_time(job.first_seen_at) != observed or parse_time(job.last_seen_at) != observed):
            raise ValueError("Regional observation contains inconsistent public posting evidence")
        rows.append(job.model_dump(mode="json"))
    return {"source": {**{key: monitor[key] for key in ("id", "company_id", "company_name", "revision")},
                       "status": "partial", "complete": False, "job_count": len(rows),
                       "warnings": ["Regional public observation; unseen roles are not confirmed closed.",
                                    "Source observed at " + timestamp(observed) + "; publication does not refresh this timestamp."]},
            "source_observed_at": timestamp(observed), "jobs": rows,
            "observed_at": {job["id"]: timestamp(observed) for job in rows}}


def capture_observation(monitor, recipe, *, now: datetime, runner=None):
    if recipe.metadata.get("public_regional_snapshot") is not True:
        raise ValueError("Regional observations require an explicitly reviewed source opt-in")
    kwargs = {"runner": runner} if runner else {}
    result = collect_monitor(monitor, recipe, now=now, limiter=HostLimiter(),
                             deadline=time.monotonic() + 180, **kwargs)
    if result["source"]["status"] not in {"complete", "partial"} or not result["jobs"]:
        raise ValueError("Regional source did not yield any verified public postings")
    value = RegionalObservation(monitor_id=monitor["id"], company_id=monitor["company_id"],
        revision=monitor["revision"], recipe_sha256=monitor["sha256"], observed_at=timestamp(now),
        jobs=result["jobs"]).model_dump(mode="json")
    _document(value, monitor, recipe, now)
    if len(json_bytes(value)) > MAX_BYTES:
        raise ValueError("Regional observation exceeds its public data budget")
    return value


def load_observations(directory: Path, monitors, *, now: datetime, state: dict):
    results = []
    root = directory.resolve()
    for monitor, recipe in monitors:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", monitor["id"]):
            raise ValueError("Invalid regional source identity")
        path = root / (monitor["id"] + ".json")
        if not path.exists():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > MAX_BYTES:
            raise ValueError("Unsafe regional observation file")
        result = _document(json.loads(path.read_text(encoding="utf-8")), monitor, recipe, now)
        if result is None:
            continue
        previous = state.get("sources", {}).get(monitor["id"], {})
        if previous.get("last_success_at") and parse_time(previous["last_success_at"]) > parse_time(result["source_observed_at"]):
            continue
        results.append(result)
    return results
