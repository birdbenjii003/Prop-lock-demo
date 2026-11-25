#!/usr/bin/env python3
"""Deterministic, quota-conscious NFL roster batch planner.

Manual batches only. A current valid snapshot is always reused without a network
request. This is not an authority for roster membership or game availability.
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_SPEC = importlib.util.spec_from_file_location("nfl_index", ROOT / "scripts/build-nfl-roster-index.py")
index = importlib.util.module_from_spec(INDEX_SPEC)
INDEX_SPEC.loader.exec_module(index)

# All 32 teams. These are intended ESPN roster URL abbreviations, not identity assertions.
ALL_TEAMS = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH"
)
# Already collected through pilot and two validated, manual three-team batches.
INITIAL_TEAMS = ("ATL", "BUF", "KC", "PHI", "BAL", "DET", "SF")
REMAINING_TEAMS = tuple(team for team in ALL_TEAMS if team not in INITIAL_TEAMS)
GROUP_SIZE = 3
GROUPS = tuple(REMAINING_TEAMS[i:i + GROUP_SIZE]
               for i in range(0, len(REMAINING_TEAMS), GROUP_SIZE))
MAX_NETWORK_REQUESTS = 3


def full_manifest():
    return {team: ("nfl_roster_pilot_ATL.json" if team == "ATL" else f"nfl_roster_{team}.json")
            for team in ALL_TEAMS}


def group_teams(number):
    if not isinstance(number, int) or not 1 <= number <= len(GROUPS):
        raise ValueError("Invalid controlled batch number")
    return GROUPS[number - 1]


def plan_batch(folder, group_number, now):
    selected = group_teams(group_number)
    manifest = full_manifest()
    decisions = []
    for team in selected:
        path = Path(folder) / manifest[team]
        if not path.is_file():
            decisions.append({"team": team, "action": "FETCH", "reason": "MISSING"})
            continue
        try:
            roster = index.read_roster(path, team, now)
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, json.JSONDecodeError):
            decisions.append({"team": team, "action": "FETCH", "reason": "INVALID"})
            continue
        if roster["freshness"] == "CURRENT":
            decisions.append({"team": team, "action": "REUSE", "reason": "FRESH_SNAPSHOT",
                              "fetchedAt": roster["fetchedAt"]})
        else:
            decisions.append({"team": team, "action": "FETCH", "reason": "STALE",
                              "fetchedAt": roster["fetchedAt"]})
    assert sum(x["action"] == "FETCH" for x in decisions) <= MAX_NETWORK_REQUESTS
    return {"group": group_number, "selectedTeams": list(selected),
            "decisions": decisions, "requestsPlanned": sum(x["action"] == "FETCH" for x in decisions)}
