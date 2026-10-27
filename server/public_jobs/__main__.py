"""CLI for pinned public builds; never reads personal JobHound state."""
from __future__ import annotations

import argparse
import gc
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import ijson

from .catalog import build_lock, load_monitors, read_json
from .collector import collect
from .lifecycle import apply_results, empty_state
from .publish import publish, retain_generations
from .schema import json_bytes, write_json


def read_state(path: Path) -> dict:
    """Parse durable state without allocating a whole UTF-8/Unicode document."""
    try:
        with path.open("rb") as source:
            documents = ijson.items(source, "", use_float=True)
            value = next(documents)
            # Exhaust the parser so trailing content cannot be silently accepted.
            if next(documents, None) is not None or not isinstance(value, dict):
                raise ValueError("Public state must be one JSON object")
            return value
    except (ijson.JSONError, StopIteration) as exc:
        raise ValueError("Invalid public state JSON") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    lock_parser = commands.add_parser("lock", help="Explicitly select and pin current verified eligible catalog monitors")
    lock_parser.add_argument("--catalog", type=Path, required=True)
    lock_parser.add_argument("--output", type=Path, required=True)
    regional = commands.add_parser("regional-snapshot", help="Collect public reviewed pins on the real regional host without personal state")
    regional.add_argument("--catalog", type=Path, required=True)
    regional.add_argument("--lock", type=Path, required=True)
    regional.add_argument("--monitor", action="append", required=True)
    regional.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build", help="Collect selected pins and atomically publish a static feed")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--lock", type=Path, required=True)
    build.add_argument("--state", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--generation")
    build.add_argument("--monitor", action="append", default=[], help="Restrict a local smoke run; never use to update production state")
    build.add_argument("--minutes", type=int, default=40)
    build.add_argument("--compress-details", action="store_true", help="Store full details as hash-checked gzip pages; requires updated feed readers")
    build.add_argument("--compress-search", action="store_true", help="Losslessly gzip search pages; expanded reader and stored hosting limits both apply")
    build.add_argument("--regional-observations", type=Path, help="Reviewed public observation files; never personal monitor exports")
    args = parser.parse_args()
    if args.command == "lock":
        lock = build_lock(args.catalog.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(json_bytes(lock))
        print(json.dumps({"catalog_commit": lock["catalog_commit"], "eligible": len(lock["monitors"]), "excluded": len(lock["excluded"])}))
        return
    if args.command == "regional-snapshot":
        from .regional import capture_observation
        lock = read_json(args.lock)
        wanted = set(args.monitor)
        selected = [entry for entry in lock["monitors"] if entry["id"] in wanted]
        if len(selected) != len(wanted):
            parser.error("Regional snapshots require exact reviewed pinned monitor IDs")
        monitors = load_monitors(args.catalog.resolve(), {**lock, "monitors": selected})
        args.output.mkdir(parents=True, exist_ok=True)
        for monitor, recipe in monitors:
            now = datetime.now(timezone.utc)
            value = capture_observation(monitor, recipe, now=now)
            target = args.output / (monitor["id"] + ".json")
            pending = target.with_suffix(".pending.json")
            write_json(pending, value)
            os.replace(pending, target)
            print(json.dumps({"id": monitor["id"], "observed_at": value["observed_at"], "jobs": len(value["jobs"])}))
        return
    if args.minutes < 1 or args.minutes > 45:
        parser.error("--minutes must be between 1 and 45")
    lock = read_json(args.lock)
    monitors = load_monitors(args.catalog.resolve(), lock)
    print(json.dumps({"stage": "loading_state", "state_bytes": args.state.stat().st_size if args.state.exists() else 0}), flush=True)
    state = read_state(args.state) if args.state.exists() else empty_state()
    print(json.dumps({"stage": "state_loaded", "jobs": len(state.get("jobs", {}))}), flush=True)
    if args.monitor:
        if args.state.exists():
            parser.error("Restricted smoke runs require a new isolated state file")
        wanted = set(args.monitor)
        monitors = [(entry, recipe) for entry, recipe in monitors if entry["id"] in wanted]
        if len(monitors) != len(wanted):
            parser.error("--monitor must name eligible pinned IDs")
    now = datetime.now(timezone.utc)
    # Refresh newly reviewed revisions first, then use oldest actual attempt.
    # Sources not reached before the deadline retain priority for the next run.
    def collection_priority(item):
        entry = item[0]
        previous = state.get("sources", {}).get(entry["id"], {})
        changed = previous.get("revision") != entry["revision"]
        return (0 if changed else 1, previous.get("last_attempt_at") or "", entry["id"])
    monitors.sort(key=collection_priority)
    generation = args.generation or now.strftime("%Y%m%dT%H%M%S")
    regional_results = []
    if args.regional_observations:
        from .regional import load_observations
        regional_results = load_observations(args.regional_observations, monitors, now=now, state=state)
    regional_ids = {result["source"]["id"] for result in regional_results}
    results = regional_results + collect([item for item in monitors if item[0]["id"] not in regional_ids], now=now, minutes=args.minutes,
                      source_caches=state.get("source_caches", {}),
                      progress=lambda source: print(json.dumps({key: source[key] for key in ("id", "status", "job_count")}), flush=True))
    if not any(result["source"]["status"] in {"complete", "partial"} for result in results):
        raise SystemExit("No sources succeeded; previous state and published generation preserved")
    updated = apply_results(state, results, generation=generation, now=now)
    successful_sources = sum(result["source"]["status"] in {"complete", "partial"} for result in results)
    # Publication needs only the merged state. Drop old caches and collection
    # results before allocating search rows or serializing durable state.
    del state, results, monitors
    gc.collect()
    updated["catalog_lock"] = lock
    for source in lock["excluded"]:
        updated["sources"][source["id"]] = {key: source[key] for key in ("id", "company_id", "company_name", "revision")}
        updated["sources"][source["id"]].update(status="excluded", complete=False, job_count=0,
                                                       last_attempt_at=None, last_success_at=None, warnings=[source["reason"]])
    manifest = publish(updated, lock, args.output, generation=generation, now=now,
                       compress_details=args.compress_details, compress_search=args.compress_search)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    pending = args.state.with_suffix(".pending.json")
    write_json(pending, updated)
    os.replace(pending, args.state)
    retain_generations(args.output)
    print(json.dumps({"generation": generation, "total_jobs": manifest["total_jobs"], "active_jobs": manifest["active_jobs"],
                      "successful_sources": successful_sources}))


if __name__ == "__main__":
    main()
