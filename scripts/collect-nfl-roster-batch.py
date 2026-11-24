#!/usr/bin/env python3
"""Controlled NFL roster batch: three explicitly permitted teams, no automatic scheduling.

Uses the existing single-team roster validator and atomic writer. A failed team
never replaces its last good snapshot. The report distinguishes partial success.
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
SPEC = importlib.util.spec_from_file_location("roster_pilot", ROOT / "scripts/collect-nfl-roster-pilot.py")
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)

BATCH = ("BUF", "KC", "PHI")
MIN_DELAY_SECONDS = 3
REPORT_DEFAULT = Path("test-results/nfl-roster-batch-report.json")
OUTPUT_DEFAULT = Path("data/live")
UTC = dt.timezone.utc


def team_url(team):
    if team not in BATCH:
        raise ValueError("Team is not enabled for controlled batch")
    return f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team.lower()}/roster"


def fetch_team(team):
    req = urllib.request.Request(team_url(team), headers={
        "User-Agent": "PropLockResearchRosterBatch/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=pilot.TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            raw = response.read(pilot.MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited("HTTP 429: pause remaining requests") from exc
        raise RuntimeError(f"HTTP {exc.code}") from exc
    if len(raw) > pilot.MAX_BYTES:
        raise ValueError("Roster exceeds source size cap")
    return json.loads(raw.decode("utf-8"))


class RateLimited(Exception):
    pass


def collect(fetcher, publish_dir, now, sleep=time.sleep):
    """Purely ordered batch orchestration with injectable network and sleep."""
    results = []
    for index, team in enumerate(BATCH):
        if index:
            sleep(MIN_DELAY_SECONDS)
        try:
            payload = fetcher(team)
            snapshot = pilot.normalize(payload, team, now)
            snapshot["scope"] = "controlled_batch"
            snapshot["notice"] = (
                "Third-party team roster. Player identities, current-team assignment, "
                "health and game eligibility are not independently verified.")
            dest = Path(publish_dir) / f"nfl_roster_{team}.json"
            pilot.publish(dest, snapshot)
            results.append({"team": team, "status": "PUBLISHED",
                            "count": snapshot["count"], "file": str(dest)})
        except RateLimited as exc:
            results.append({"team": team, "status": "RATE_LIMITED", "reason": str(exc)})
            for remaining in BATCH[index + 1:]:
                results.append({"team": remaining, "status": "SKIPPED_RATE_LIMIT"})
            break
        except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            results.append({"team": team, "status": "FAILED",
                            "reason": str(exc)[:160]})
            # Continue after a non-rate-limit failure; valid other teams are independent.
    return {
        "schemaVersion": 1, "sport": "NFL", "scope": "controlled_batch",
        "fetchedAt": now.isoformat().replace("+00:00", "Z"),
        "provider": "ESPN", "verification": "unverified",
        "requestedTeams": list(BATCH), "results": results,
        "allSuccessful": len(results) == len(BATCH) and all(x["status"] == "PUBLISHED" for x in results),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", help="Offline tests only; disabled in scheduled workflow")
    parser.add_argument("--out-dir", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--report", default=str(REPORT_DEFAULT))
    args = parser.parse_args()
    if args.fixture_dir:
        def load_fixture(team):
            path = Path(args.fixture_dir) / f"{team}.json"
            blob = path.read_bytes()
            if len(blob) > pilot.MAX_BYTES:
                raise ValueError("Fixture exceeds size bound")
            return json.loads(blob)
        fetcher = load_fixture
    else:
        fetcher = fetch_team
    now = dt.datetime.now(UTC).replace(microsecond=0)
    report = collect(fetcher, Path(args.out_dir), now, sleep=lambda sec: None if args.fixture_dir else time.sleep(sec))
    path = Path(args.report)
    pilot.publish(path, report)
    print(json.dumps({"allSuccessful": report["allSuccessful"], "results": report["results"]}))
    # Report is inspected by workflow after committing validated successes.
    # Each failed team's previous snapshot, if any, remains untouched.


if __name__ == "__main__":
    main()
