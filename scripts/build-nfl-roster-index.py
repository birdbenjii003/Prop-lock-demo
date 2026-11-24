#!/usr/bin/env python3
"""Read-only identity-conflict and coverage index of existing NFL roster snapshots.

Never infers a player's true team from a roster listing. Missing, expired and
conflicting snapshots remain visible. Standard library; no provider calls.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import re

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parent.parent
OUT = Path("data/live/nfl_roster_index.json")
MAX_AGE_HOURS = 36
# Explicit source manifest, so unexpected files cannot silently expand the index.
MANIFEST = {
    "ATL": "nfl_roster_pilot_ATL.json",
    "BUF": "nfl_roster_BUF.json",
    "KC": "nfl_roster_KC.json",
    "PHI": "nfl_roster_PHI.json",
    "BAL": "nfl_roster_BAL.json",
    "DET": "nfl_roster_DET.json",
    "SF": "nfl_roster_SF.json",
}


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp absent")
    date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Timestamp missing zone")
    return date.astimezone(UTC)


def read_roster(path, team, now):
    # Treat JSON as external data even when hosted within the repository.
    if path.stat().st_size > 100_000:
        raise ValueError("Snapshot size exceeds expected bound")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or data.get("sport") != "NFL" or \
       data.get("type") != "roster" or data.get("source") != "ESPN" or \
       data.get("verification") != "unverified" or data.get("team") != team or \
       data.get("scope") not in ("single_team_pilot", "controlled_batch"):
        raise ValueError("Snapshot provenance/identity mismatch")
    entries = data.get("athletes")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 125 or data.get("count") != len(entries):
        raise ValueError("Roster count missing or invalid")
    seen = set()
    cleaned = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Malformed athlete record")
        athlete_id = str(item.get("espnId") or "")
        name = item.get("displayName")
        if not re.fullmatch(r"\d{1,12}", athlete_id) or \
           not isinstance(name, str) or not 2 <= len(name.strip()) <= 100 or athlete_id in seen:
            raise ValueError("Missing or repeated ESPN ID/name")
        seen.add(athlete_id)
        cleaned.append((athlete_id, name.strip()))
    at = parse_iso(data.get("fetchedAt"))
    age = (now-at).total_seconds()
    if age < -60:
        raise ValueError("Collection timestamp is in future")
    return {"team": team, "count": len(cleaned),
            "fetchedAt": at.isoformat().replace("+00:00", "Z"),
            "freshness": "CURRENT" if age <= MAX_AGE_HOURS*3600 else "STALE",
            "athletes": cleaned}


def index_snapshots(folder, now):
    teams = []
    identity = {}
    for team, filename in MANIFEST.items():
        path = Path(folder) / filename
        if not path.exists():
            teams.append({"team": team, "state": "MISSING", "count": 0, "fetchedAt": None})
            continue
        try:
            record = read_roster(path, team, now)
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            teams.append({"team": team, "state": "INVALID", "count": 0,
                          "fetchedAt": None, "reason": str(exc)[:120]})
            continue
        teams.append({"team": team, "state": record["freshness"],
                      "count": record["count"], "fetchedAt": record["fetchedAt"]})
        for athlete_id, name in record["athletes"]:
            identity.setdefault(athlete_id, []).append({"team": team, "name": name,
                        "freshness": record["freshness"], "fetchedAt": record["fetchedAt"]})
    collisions = []
    for athlete_id, instances in identity.items():
        if len({item["team"] for item in instances}) > 1:
            collisions.append({"espnId": athlete_id,
                               "listedTeams": sorted({x["team"] for x in instances}),
                               "entries": sorted(instances, key=lambda x: x["team"]),
                               "status": "TEAM_ID_CONFLICT_UNRESOLVED"})
    collisions.sort(key=lambda x: x["espnId"])
    return {
        "schemaVersion": 1, "sport": "NFL", "type": "roster_index",
        "verification": "unverified", "source": "published_ESPN_snapshots",
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "freshnessThresholdHours": MAX_AGE_HOURS,
        "coverage": {
            "teamsExpected": 32,
            "teamsTracked": len(MANIFEST),
            "teamsPresent": sum(x["state"] in ("CURRENT", "STALE") for x in teams),
            "teamsCurrent": sum(x["state"] == "CURRENT" for x in teams),
            "teamsStale": sum(x["state"] == "STALE" for x in teams),
            "teamsMissing": sum(x["state"] == "MISSING" for x in teams),
            "teamsInvalid": sum(x["state"] == "INVALID" for x in teams),
            "unresolvedCrossTeamIds": len(collisions),
        },
        "teams": teams, "identityConflicts": collisions,
        "notice": "Listing conflicts only: no verified player-team assignment or eligibility.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/live")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    result = index_snapshots(args.data_dir, now)
    # Import atomic writer already validated for NFL snapshot publishing.
    spec = importlib.util.spec_from_file_location("pilot", ROOT / "scripts/collect-nfl-roster-pilot.py")
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    pilot.publish(Path(args.out), result)
    print("NFL roster index:", json.dumps(result["coverage"]))
    # Invalid team snapshots are flagged in index; never overwrite their roster files.


if __name__ == "__main__":
    main()
