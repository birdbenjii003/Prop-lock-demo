#!/usr/bin/env python3
"""Manually selected NFL roster batches with hard network cap, pacing and re-use.

Preserves the current valid roster when a network request fails; does not make
player-team assertions. No automatic 24/7 roster scheduling enabled.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import time
import urllib.error

ROOT = Path(__file__).resolve().parent.parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


plan = module("roster_plan_v8", "nfl-roster-plan.py")
batch = module("roster_batch_v8", "collect-nfl-roster-batch.py")
UTC = dt.timezone.utc


def collect_group(group_number, folder, now, fetcher=None, sleep=time.sleep):
    decision = plan.plan_batch(folder, group_number, now)
    selected = tuple(decision["selectedTeams"])
    batch.BATCH = selected  # Restricts source endpoint to this selected manual group only.
    fetcher = fetcher or batch.fetch_team
    results = []
    attempted = 0
    throttled = False
    for entry in decision["decisions"]:
        team = entry["team"]
        if entry["action"] == "REUSE":
            results.append({"team": team, "status": "REUSED", "reason": "FRESH_SNAPSHOT"})
            continue
        if throttled:
            results.append({"team": team, "status": "SKIPPED_RATE_LIMIT"})
            continue
        if attempted >= plan.MAX_NETWORK_REQUESTS:
            results.append({"team": team, "status": "SKIPPED_REQUEST_CAP"})
            continue
        if attempted:
            sleep(batch.MIN_DELAY_SECONDS)
        attempted += 1
        try:
            raw = fetcher(team)
            roster = batch.pilot.normalize(raw, team, now)
            roster["scope"] = "controlled_batch"
            roster["notice"] = (
                "Third-party team roster listing only; athlete team assignment, "
                "injury status, and eligibility not independently verified."
            )
            dest = Path(folder) / plan.full_manifest()[team]
            batch.pilot.publish(dest, roster)
            results.append({"team": team, "status": "PUBLISHED", "count": roster["count"],
                            "file": str(dest)})
        except batch.RateLimited as exc:
            throttled = True
            results.append({"team": team, "status": "RATE_LIMITED",
                            "reason": str(exc)[:160]})
        except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError,
                OSError, json.JSONDecodeError) as exc:
            results.append({"team": team, "status": "FAILED", "reason": str(exc)[:160]})
    return {
        "schemaVersion": 1, "sport": "NFL", "source": "ESPN",
        "verification": "unverified", "scope": "manual_batch",
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "group": group_number, "selectedTeams": list(selected), "requestsAttempted": attempted,
        "results": results,
        "allSuccessful": all(x["status"] in ("PUBLISHED", "REUSED") for x in results),
        "notice": "Data source is not verified; IDs are not final team assignments."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True, type=int, choices=range(1, len(plan.GROUPS) + 1))
    parser.add_argument("--data-dir", default="data/live")
    parser.add_argument("--report", default="test-results/nfl-roster-v8-report.json")
    parser.add_argument("--fixture-dir", help="Tests only: no real requests")
    args = parser.parse_args()
    if args.fixture_dir:
        def fixture(team):
            blob = (Path(args.fixture_dir) / f"{team}.json").read_bytes()
            if len(blob) > batch.pilot.MAX_BYTES:
                raise ValueError("Oversized roster fixture")
            return json.loads(blob)
        fetcher, sleeper = fixture, lambda _: None
    else:
        fetcher, sleeper = None, time.sleep
    now = dt.datetime.now(UTC).replace(microsecond=0)
    report = collect_group(args.group, Path(args.data_dir), now, fetcher, sleeper)
    batch.pilot.publish(Path(args.report), report)
    print(json.dumps({"group": report["group"],
                      "requestsAttempted": report["requestsAttempted"],
                      "results": report["results"],
                      "allSuccessful": report["allSuccessful"]}))


if __name__ == "__main__":
    main()
