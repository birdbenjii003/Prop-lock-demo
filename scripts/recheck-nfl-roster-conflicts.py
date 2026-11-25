#!/usr/bin/env python3
"""Manual recheck for NFL roster IDs listed on multiple teams.

Never resolves a player's actual team by newest timestamp. Refreshes a bounded
set of source team snapshots, then rebuilds the existing conflict index.
No automatic or recurring provider requests.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import time
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("multi_v9", ROOT / "scripts/collect-nfl-roster-v8-multi.py")
multi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(multi)
UTC = dt.timezone.utc
MAX_TEAMS = 4
MIN_GAP_SECONDS = 3


def candidate_teams(index_record):
    if not isinstance(index_record, dict) or index_record.get("sport") != "NFL" or \
       index_record.get("type") != "roster_index" or index_record.get("verification") != "unverified":
        raise ValueError("Invalid roster index provenance")
    conflicts = index_record.get("identityConflicts")
    if not isinstance(conflicts, list) or len(conflicts) > 50:
        raise ValueError("Invalid conflict list")
    allowed = set(multi.plan.ALL_TEAMS)
    unique = set()
    for entry in conflicts:
        if not isinstance(entry, dict) or entry.get("status") != "TEAM_ID_CONFLICT_UNRESOLVED":
            raise ValueError("Unsupported conflict status")
        teams = entry.get("listedTeams")
        if not isinstance(teams, list) or len(teams) < 2 or not set(teams).issubset(allowed):
            raise ValueError("Invalid conflict team list")
        unique.update(teams)
    if len(unique) > MAX_TEAMS:
        raise ValueError("Conflict recheck exceeds four-team cap; split into smaller reviews")
    return tuple(sorted(unique))


def recheck(index_record, folder, now, fetcher=None, sleep=time.sleep):
    teams = candidate_teams(index_record)
    blocked = multi.read_cooldown(folder, now)
    if blocked is not None:
        return {"teams": list(teams), "requestsAttempted": 0, "allSuccessful": False,
                "status": "ACTIVE_PROVIDER_COOLDOWN", "results": [],
                "blockedUntil": blocked.isoformat().replace("+00:00", "Z")}
    multi.batch.BATCH = teams
    fetcher = fetcher or multi.fetch_team
    results = []
    requests = 0
    throttle = None
    for team in teams:
        if throttle is not None:
            results.append({"team": team, "status": "SKIPPED_RATE_LIMIT"})
            continue
        if requests:
            sleep(MIN_GAP_SECONDS)
        requests += 1
        try:
            raw = fetcher(team)
            record = multi.batch.pilot.normalize(raw, team, now)
            record["scope"] = "controlled_batch"
            record["notice"] = "Rechecked team roster listing; does not certify athlete's current team."
            path = Path(folder) / multi.plan.full_manifest()[team]
            multi.batch.pilot.publish(path, record)
            results.append({"team": team, "status": "PUBLISHED", "count": record["count"]})
        except (multi.Throttled, multi.batch.RateLimited) as exc:
            throttle = exc
            results.append({"team": team, "status": "RATE_LIMITED", "reason": str(exc)[:120]})
        except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError,
                OSError, json.JSONDecodeError) as exc:
            results.append({"team": team, "status": "FAILED", "reason": str(exc)[:120]})
    until = None
    if throttle is not None:
        server = multi.retry_after_seconds(getattr(throttle, "retry_after", None), now)
        seconds = min(multi.MAX_COOLDOWN_SECONDS, max(multi.BASE_COOLDOWN_SECONDS, server or 0))
        until = (now + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
        multi.batch.pilot.publish(Path(folder) / multi.COOLDOWN_FILE, {
            "schemaVersion": 1, "reason": "HTTP_429", "blockedUntil": until,
            "source": "ESPN", "verification": "unverified"})
    return {"schemaVersion": 1, "scope": "manual_conflict_recheck",
            "source": "ESPN", "verification": "unverified",
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "teams": list(teams), "requestsAttempted": requests,
            "allSuccessful": all(x["status"] == "PUBLISHED" for x in results),
            "results": results, "blockedUntil": until,
            "notice": "Rechecking duplicate listings does not establish a player's official current team."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default="data/live/nfl_roster_index.json")
    parser.add_argument("--data-dir", default="data/live")
    parser.add_argument("--report", default="test-results/nfl-conflict-recheck.json")
    args = parser.parse_args()
    source = json.loads(Path(args.index).read_text(encoding="utf-8"))
    now = dt.datetime.now(UTC).replace(microsecond=0)
    result = recheck(source, Path(args.data_dir), now)
    multi.batch.pilot.publish(Path(args.report), result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
