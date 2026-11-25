#!/usr/bin/env python3
"""Best-effort scheduled refresh of NFL roster snapshots, eight teams per cohort.

Four deterministic cohorts, one selected per scheduled run; 36h freshness,
three-second spacing, global 429 cooldown, individual atomic commits and
no verified-team or injury claims. Runs from GitHub Actions, not from browser.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import time
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("v8multi_v10", ROOT / "scripts/collect-nfl-roster-v8-multi.py")
multi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(multi)
UTC = dt.timezone.utc
COHORT_COUNT = 4
MAX_CALLS = 8
MIN_GAP_SECONDS = multi.MIN_GAP_SECONDS
# Four cron hours UTC, each assigned one non-overlapping cohort.
CRON_HOURS = (1, 7, 13, 19)


def cohorts():
    teams = multi.plan.ALL_TEAMS
    assert len(teams) == 32 and len(set(teams)) == 32
    return tuple(tuple(teams[i:i + MAX_CALLS]) for i in range(0, 32, MAX_CALLS))


def choose_cohort(now, requested=None, scheduled_cron=None):
    if requested is not None:
        if not isinstance(requested, int) or isinstance(requested, bool) or not 1 <= requested <= COHORT_COUNT:
            raise ValueError("Manual cohort must be 1–4")
        return requested
    if scheduled_cron is not None:
        # GitHub provides the original cron trigger, which is stable when the run starts late.
        if scheduled_cron != '23 1,7,13,19 * * *':
            raise ValueError('Unexpected scheduled trigger')
        # A single cron expression does not identify which of its four hours
        # fired; use GitHub run timestamp as a best-effort UTC selector.
    if now.tzinfo is None:
        raise ValueError("Run time requires timezone")
    hour = now.astimezone(UTC).hour
    # Scheduled jobs may start late. Use nearest preceding scheduled UTC hour,
    # including previous day's final slot.
    eligible = [i for i, start in enumerate(CRON_HOURS) if hour >= start]
    return eligible[-1] + 1 if eligible else COHORT_COUNT


def collect_cohort(folder, now, cohort, fetcher=None, sleeper=time.sleep):
    selected = cohorts()[cohort - 1] if isinstance(cohort, int) and not isinstance(cohort, bool) and 1 <= cohort <= 4 else None
    if selected is None:
        raise ValueError("Invalid cohort")
    block = multi.read_cooldown(folder, now)
    if block is not None:
        return {"schemaVersion": 1, "cohort": cohort, "selectedTeams": list(selected),
                "requestsAttempted": 0, "allSuccessful": False, "status": "ACTIVE_PROVIDER_COOLDOWN",
                "blockedUntil": block.isoformat().replace("+00:00", "Z"),
                "results": [{"team": team, "status": "SKIPPED_COOLDOWN"} for team in selected]}
    multi.batch.BATCH = selected
    fetcher = fetcher or multi.fetch_team
    results = []
    requests = 0
    throttled = None
    manifest = multi.plan.full_manifest()
    for team in selected:
        if throttled is not None:
            results.append({"team": team, "status": "SKIPPED_RATE_LIMIT"})
            continue
        path = Path(folder) / manifest[team]
        try:
            previous = multi.plan.index.read_roster(path, team, now) if path.is_file() else None
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, json.JSONDecodeError):
            previous = None
        if previous is not None and previous["freshness"] == "CURRENT":
            results.append({"team": team, "status": "REUSED", "fetchedAt": previous["fetchedAt"]})
            continue
        if requests >= MAX_CALLS:
            results.append({"team": team, "status": "SKIPPED_CAP"})
            continue
        if requests > 0:
            sleeper(MIN_GAP_SECONDS)
        requests += 1
        try:
            payload = fetcher(team)
            record = multi.batch.pilot.normalize(payload, team, now)
            record["scope"] = "controlled_batch"
            record["notice"] = "Unverified third-party roster listing; not a player eligibility or team identity confirmation."
            multi.batch.pilot.publish(path, record)
            results.append({"team": team, "status": "PUBLISHED", "count": record["count"]})
        except (multi.Throttled, multi.batch.RateLimited) as exc:
            throttled = exc
            results.append({"team": team, "status": "RATE_LIMITED", "reason": str(exc)[:120]})
        except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError,
                OSError, json.JSONDecodeError) as exc:
            results.append({"team": team, "status": "FAILED", "reason": str(exc)[:120]})
    blocked_until = None
    if throttled is not None:
        retry = multi.retry_after_seconds(getattr(throttled, "retry_after", None), now)
        seconds = min(multi.MAX_COOLDOWN_SECONDS, max(multi.BASE_COOLDOWN_SECONDS, retry or 0))
        blocked_until = (now + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
        multi.batch.pilot.publish(Path(folder) / multi.COOLDOWN_FILE, {
            "schemaVersion": 1, "reason": "HTTP_429", "blockedUntil": blocked_until,
            "source": "ESPN", "verification": "unverified"})
    return {"schemaVersion": 1, "source": "ESPN", "sport": "NFL",
            "scope": "scheduled_roster_cohort", "verification": "unverified",
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "cohort": cohort, "selectedTeams": list(selected), "requestsAttempted": requests,
            "requestCap": MAX_CALLS, "results": results,
            "allSuccessful": all(r["status"] in ("PUBLISHED", "REUSED") for r in results),
            "blockedUntil": blocked_until,
            "status": "RATE_LIMITED" if throttled else "COMPLETED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=int, choices=range(1, 5), default=None,
                        help="Optional explicit cohort. Scheduled runs select by UTC hour.")
    parser.add_argument("--data-dir", default="data/live")
    parser.add_argument("--report", default="test-results/nfl-roster-v10-report.json")
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    cohort = choose_cohort(now, args.cohort, os.environ.get('GITHUB_SCHEDULE_CRON') or None)
    result = collect_cohort(Path(args.data_dir), now, cohort)
    multi.batch.pilot.publish(Path(args.report), result)
    print(json.dumps({"cohort": cohort, "requestsAttempted": result["requestsAttempted"],
                      "status": result["status"], "allSuccessful": result["allSuccessful"],
                      "results": result["results"]}))


if __name__ == "__main__":
    main()
