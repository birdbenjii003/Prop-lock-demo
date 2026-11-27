#!/usr/bin/env python3
"""Phase 12 offline, fail-closed cross-source NFL injury identity evidence audit.

Exact ESPN athlete IDs only. No names, injury event fingerprints, or team listing
are accepted as identity joins. A successful join is evidence, not eligibility.
No external HTTP calls; reads published snapshot files with bounded size.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
UTC = dt.timezone.utc
OUT = Path("data/live/nfl_injury_identity_audit.json")
MAX_REPORT_AGE_HOURS = 12

def module(label, path):
    spec = importlib.util.spec_from_file_location(label, ROOT / path)
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance

rosters = module("phase12_roster", "scripts/build-nfl-roster-index.py")
plan = module("phase12_plan", "scripts/nfl-roster-plan.py")
collector = module("phase12_collector", "scripts/collect-nfl-roster-pilot.py")

def read_json(path, max_bytes):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("Source exceeds audit bounds")
    return json.loads(path.read_text(encoding="utf-8"))

def load_rosters(folder, now, manifest=None):
    manifest = plan.full_manifest() if manifest is None else manifest
    by_id, team_status = {}, {}
    for team, file in manifest.items():
        try:
            item = rosters.read_roster(Path(folder)/file, team, now)
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, json.JSONDecodeError):
            team_status[team] = "INVALID_OR_MISSING"
            continue
        team_status[team] = item["freshness"]
        for ident, name in item["athletes"]:
            by_id.setdefault(ident, []).append({"team": team,
               "freshness": item["freshness"], "name": name})
    return by_id, team_status

def audit(injuries, by_id, team_status, now):
    if not isinstance(injuries, dict) or injuries.get("schemaVersion") != 1 or \
       injuries.get("sport") != "NFL" or injuries.get("type") != "injuries" or \
       injuries.get("source") != "ESPN" or injuries.get("verification") != "unverified" or \
       injuries.get("scope") != "league_injury_pilot":
        raise ValueError("Invalid injury snapshot provenance")
    entries = injuries.get("injuries")
    reported = injuries.get("teamsReported")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 1000 or \
       injuries.get("count") != len(entries) or not isinstance(reported, list):
        raise ValueError("Invalid injury snapshot bounds")
    fetched = rosters.parse_iso(injuries.get("fetchedAt"))
    age = (now-fetched).total_seconds()/3600
    if age < -1/60:
        raise ValueError("Injury snapshot timestamp in future")
    report_current = age <= MAX_REPORT_AGE_HOURS
    # Snapshot may be old; never count old data as an actionable player match.
    statuses = {
        "UNLINKED_NO_ATHLETE_ID": 0, "STALE_INJURY_REPORT": 0,
        "TEAM_ROSTER_STALE_OR_MISSING": 0, "ATHLETE_NOT_IN_ROSTER": 0,
        "CROSS_TEAM_ID_CONFLICT": 0, "TEAM_ID_MISMATCH": 0,
        "ID_NAME_MISMATCH": 0, "ID_CROSS_SOURCE_MATCH_UNVERIFIED": 0
    }
    records, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid injury report entry")
        team = entry.get("team")
        name = entry.get("displayName")
        athlete_id = entry.get("espnId")
        source_id = entry.get("sourceInjuryId")
        designation = entry.get("designation")
        if team not in plan.ALL_TEAMS or not isinstance(name, str) or not name.strip() or \
           not isinstance(designation, str) or not designation.strip() or \
           (source_id is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(source_id))) or \
           (athlete_id is not None and not re.fullmatch(r"\d{1,12}", str(athlete_id))):
            raise ValueError("Invalid injury evidence fields")
        unique_key = (team, str(athlete_id), source_id)
        if unique_key in seen:
            raise ValueError("Duplicate published injury evidence")
        seen.add(unique_key)
        listing = by_id.get(str(athlete_id), []) if athlete_id is not None else []
        if athlete_id is None:
            status = "UNLINKED_NO_ATHLETE_ID"
        elif not report_current:
            status = "STALE_INJURY_REPORT"
        elif team_status.get(team) != "CURRENT":
            status = "TEAM_ROSTER_STALE_OR_MISSING"
        elif not listing:
            status = "ATHLETE_NOT_IN_ROSTER"
        elif len({r["team"] for r in listing}) != 1:
            status = "CROSS_TEAM_ID_CONFLICT"
        elif listing[0]["team"] != team:
            status = "TEAM_ID_MISMATCH"
        elif listing[0]["freshness"] != "CURRENT":
            status = "TEAM_ROSTER_STALE_OR_MISSING"
        elif listing[0]["name"].strip().casefold() != name.strip().casefold():
            status = "ID_NAME_MISMATCH"
        else:
            status = "ID_CROSS_SOURCE_MATCH_UNVERIFIED"
        statuses[status] += 1
        # Never publish raw source fingerprints, player names or injury statuses
        # from the audit. The existing injury feed owns those listings.
        records.append({"team": team, "identityStatus": status,
                        "athleteIdPresent": athlete_id is not None})
    return {
        "schemaVersion": 1, "sport": "NFL", "type": "injury_identity_audit",
        "verification": "unverified", "source": "published_ESPN_snapshots",
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "injuryFetchedAt": injuries["fetchedAt"],
        "injuryReportCurrent": report_current,
        "totals": {"entries": len(entries), "teamsReported": len(set(reported)),
                   "rosterTeamsCurrent": sum(x == "CURRENT" for x in team_status.values()),
                   "rosterTeamsStaleOrMissing": len(plan.ALL_TEAMS)-sum(x == "CURRENT" for x in team_status.values()),
                   **statuses},
        "records": records,
        "notice": "Read-only identity evidence. Exact athlete ESPN ID + same current team + same name required. No name-only match; no injury-based projections, health or eligibility claims."
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--injuries", default="data/live/nfl_injuries.json")
    parser.add_argument("--roster-dir", default="data/live")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    roster_ids, team_status = load_rosters(args.roster_dir, now)
    injury_snapshot = read_json(args.injuries, 1_500_000)
    result = audit(injury_snapshot, roster_ids, team_status, now)
    collector.publish(Path(args.out), result)
    print(json.dumps({"outcome": "AUDITED", "totals": result["totals"],
                      "playerProjectionChanges": 0}, sort_keys=True))

if __name__ == "__main__":
    main()
