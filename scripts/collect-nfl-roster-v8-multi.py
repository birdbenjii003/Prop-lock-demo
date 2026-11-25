#!/usr/bin/env python3
"""Run up to three adjacent NFL roster groups with a nine-request ceiling.

Manual-only. Reuses valid snapshots, spaces *all* actual provider calls, and
stops the entire batch on HTTP 429. Every successfully validated team is saved
atomically, even if a later team fails. No live data is used to make picks.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
UTC = dt.timezone.utc
MAX_GROUPS = 3
MAX_REQUESTS = 9
MIN_GAP_SECONDS = 3
COOLDOWN_FILE = "nfl_roster_cooldown.json"
BASE_COOLDOWN_SECONDS = 30 * 60
MAX_COOLDOWN_SECONDS = 6 * 60 * 60


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("roster_v8_multi_dependency", "collect-nfl-roster-v8.py")
plan = runner.plan
batch = runner.batch


def selected_groups(start_group, groups):
    if not isinstance(start_group, int) or isinstance(start_group, bool):
        raise ValueError("Invalid start group")
    if not isinstance(groups, int) or isinstance(groups, bool) or not 1 <= groups <= MAX_GROUPS:
        raise ValueError("Select between one and three groups")
    if start_group < 1 or start_group + groups - 1 > len(plan.GROUPS):
        raise ValueError("Requested group range exceeds defined teams")
    return tuple(range(start_group, start_group + groups))


def read_cooldown(folder, now):
    path = Path(folder) / COOLDOWN_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 1 or data.get("reason") != "HTTP_429":
            return None
        until = dt.datetime.fromisoformat(data["blockedUntil"].replace("Z", "+00:00"))
        if until.tzinfo is None:
            return None
        return until.astimezone(UTC) if until > now else None
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError):
        return None


def retry_after_seconds(raw, now):
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
        return min(MAX_COOLDOWN_SECONDS, max(0, seconds))
    except (ValueError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        until = parsedate_to_datetime(raw)
        if until.tzinfo is None:
            return None
        return min(MAX_COOLDOWN_SECONDS, max(0, int((until - now).total_seconds())))
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_team(team):
    # Use exactly the existing allowlisted endpoint; preserve Retry-After metadata.
    req = urllib.request.Request(batch.team_url(team), headers={
        "User-Agent": "PropLockResearchRosterBatch/1.0",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=batch.pilot.TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"Roster HTTP {response.status}")
            raw = response.read(batch.pilot.MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise Throttled("HTTP 429", retry_after=exc.headers.get("Retry-After")) from exc
        raise RuntimeError(f"Roster HTTP {exc.code}") from exc
    if len(raw) > batch.pilot.MAX_BYTES:
        raise ValueError("Roster exceeds source size cap")
    return json.loads(raw.decode("utf-8"))


class Throttled(Exception):
    def __init__(self, detail, retry_after=None):
        super().__init__(detail)
        self.retry_after = retry_after


def collect_multiple(start_group, groups, folder, now, fetcher=None, sleep=time.sleep):
    numbers = selected_groups(start_group, groups)
    teams = tuple(team for n in numbers for team in plan.group_teams(n))
    if len(teams) > MAX_REQUESTS or len(set(teams)) != len(teams):
        raise ValueError("Request limit or duplicate team selection")
    initial_block = read_cooldown(folder, now)
    if initial_block is not None:
        return {
            "schemaVersion": 1, "groupNumbers": list(numbers),
            "selectedTeams": list(teams), "requestsAttempted": 0,
            "results": [{"team": t, "status": "SKIPPED_COOLDOWN"} for t in teams],
            "allSuccessful": False, "stoppedBecause": "ACTIVE_PROVIDER_COOLDOWN",
            "blockedUntil": initial_block.isoformat().replace("+00:00", "Z")
        }

    batch.BATCH = teams
    fetcher = fetcher or fetch_team
    decisions = {
        item["team"]: item for number in numbers
        for item in plan.plan_batch(folder, number, now)["decisions"]
    }
    records = []
    attempted = 0
    last_attempted = False
    throttled = None
    for team in teams:
        item = decisions[team]
        if item["action"] == "REUSE":
            records.append({"team": team, "status": "REUSED", "reason": "FRESH_SNAPSHOT"})
            continue
        if throttled is not None:
            records.append({"team": team, "status": "SKIPPED_RATE_LIMIT"})
            continue
        if attempted >= MAX_REQUESTS:
            records.append({"team": team, "status": "SKIPPED_REQUEST_CAP"})
            continue
        if last_attempted:
            sleep(MIN_GAP_SECONDS)
        attempted += 1
        last_attempted = True
        try:
            payload = fetcher(team)
            roster = batch.pilot.normalize(payload, team, now)
            roster["scope"] = "controlled_batch"
            roster["notice"] = ("Third-party roster listing, not a verified active team or game-status record.")
            dest = Path(folder) / plan.full_manifest()[team]
            batch.pilot.publish(dest, roster)
            records.append({"team": team, "status": "PUBLISHED",
                            "count": roster["count"], "file": str(dest)})
        except (Throttled, batch.RateLimited) as exc:
            throttled = exc
            records.append({"team": team, "status": "RATE_LIMITED", "reason": str(exc)[:160]})
        except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError) as exc:
            records.append({"team": team, "status": "FAILED", "reason": str(exc)[:160]})

    blocked_until = None
    if throttled is not None:
        server_seconds = retry_after_seconds(getattr(throttled, "retry_after", None), now)
        wait = min(MAX_COOLDOWN_SECONDS, max(BASE_COOLDOWN_SECONDS, server_seconds or 0))
        blocked_until = (now + dt.timedelta(seconds=wait)).isoformat().replace("+00:00", "Z")
        batch.pilot.publish(Path(folder) / COOLDOWN_FILE, {
            "schemaVersion": 1, "reason": "HTTP_429", "blockedUntil": blocked_until,
            "source": "ESPN", "verification": "unverified"})
    return {
        "schemaVersion": 1, "sport": "NFL", "source": "ESPN",
        "verification": "unverified", "scope": "manual_multi_group",
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "groupNumbers": list(numbers), "selectedTeams": list(teams),
        "requestsAttempted": attempted, "requestCap": MAX_REQUESTS,
        "results": records,
        "allSuccessful": all(x["status"] in ("PUBLISHED", "REUSED") for x in records),
        "stoppedBecause": "HTTP_429" if throttled is not None else None,
        "blockedUntil": blocked_until,
        "notice": "Third-party roster evidence only, not independently verified player-team identity."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-group", required=True, type=int)
    parser.add_argument("--groups", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--data-dir", default="data/live")
    parser.add_argument("--report", default="test-results/nfl-roster-v8-multi-report.json")
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    report = collect_multiple(args.start_group, args.groups, Path(args.data_dir), now)
    batch.pilot.publish(Path(args.report), report)
    print(json.dumps({"requestsAttempted": report["requestsAttempted"],
                      "allSuccessful": report["allSuccessful"],
                      "results": report["results"],
                      "blockedUntil": report.get("blockedUntil")}))


if __name__ == "__main__":
    main()
