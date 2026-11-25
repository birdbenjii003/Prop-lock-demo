#!/usr/bin/env python3
"""Read-only, opt-in NFL league injury feed pilot. Not a source of lineup certainty.

Unofficial ESPN interface can change at any time. Rejects unknown/empty response
structures; no missing injury implies health. Never changes research projections.
"""
import argparse
import datetime as dt
import hashlib
import gzip
import io
import importlib.util
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
OUT = Path("data/live/nfl_injuries.json")
MAX_BYTES = 12_000_000  # Upper bound for decoded JSON response; previously 3 MB
MAX_WIRE_BYTES = 12_000_000  # Upper bound on downloaded bytes, compressed or plain
MAX_GROUPS = 40
MAX_RECORDS = 1000
UTC = dt.timezone.utc

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

roster_index = load_module("injury_roster_index", "scripts/build-nfl-roster-index.py")
roster_plan = load_module("injury_roster_plan", "scripts/nfl-roster-plan.py")
pilot = load_module("injury_atomic_writer", "scripts/collect-nfl-roster-pilot.py")

def decode_bounded_response(response):
    """Bound HTTP payload bytes AND decoded JSON bytes, including gzip bombs.

    The ESPN injury endpoint exceeded the original 3 MB cap. Raise the
    hard limit to 12 MB, but never read or decompress without explicit caps.
    """
    encoding = response.headers.get("Content-Encoding", "").strip().lower()
    if encoding not in ("", "identity", "gzip"):
        raise ValueError("Unsupported injury response encoding")
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > MAX_WIRE_BYTES:
                raise ValueError("Injury wire Content-Length exceeds 12 MB cap")
        except (TypeError, ValueError) as exc:
            if str(exc) == "Injury wire Content-Length exceeds 12 MB cap":
                raise
            raise ValueError("Invalid injury Content-Length") from exc
    wire = response.read(MAX_WIRE_BYTES + 1)
    if len(wire) > MAX_WIRE_BYTES:
        raise ValueError("Injury wire payload exceeds 12 MB cap")
    if encoding == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(wire), mode="rb") as stream:
                decoded = stream.read(MAX_BYTES + 1)
                if len(decoded) > MAX_BYTES:
                    raise ValueError("Decoded injury source exceeds 12 MB cap")
                if stream.read(1):
                    raise ValueError("Decoded injury source exceeds 12 MB cap")
        except (EOFError, OSError) as exc:
            raise ValueError("Invalid or truncated injury gzip response") from exc
    else:
        decoded = wire
    if len(decoded) > MAX_BYTES:
        raise ValueError("Decoded injury source exceeds 12 MB cap")
    try:
        return json.loads(decoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid injury JSON response") from exc


def fetch():
    request = urllib.request.Request(URL, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "PropLockResearchInjuryPilot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError("Injury source returned unexpected HTTP status")
            return decode_bounded_response(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Injury source HTTP {exc.code}") from exc

def roster_evidence(folder, now):
    """Only same-team, unique ESPN IDs in non-stale published snapshots count."""
    by_id = {}
    for team, filename in roster_plan.full_manifest().items():
        path = Path(folder) / filename
        if not path.is_file():
            continue
        try:
            item = roster_index.read_roster(path, team, now)
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, json.JSONDecodeError):
            continue
        if item["freshness"] != "CURRENT":
            continue
        for ident, name in item["athletes"]:
            by_id.setdefault(ident, []).append(team)
    return {ident: teams for ident, teams in by_id.items()}

def status_text(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("description") or value.get("displayName")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:70] if 1 <= len(value) <= 70 else None

def group_shape_summary(group, position):
    """Safe shape-only diagnostics: never emit athlete names, IDs or injury details."""
    if not isinstance(group, dict):
        return f"group={position},type={type(group).__name__}"
    keys = sorted(k for k in group if isinstance(k, str))
    team = group.get("team")
    members = group.get("injuries")
    team_keys = sorted(k for k in team if isinstance(k, str)) if isinstance(team, dict) else []
    return (f"group={position},keys={keys[:12]},"
            f"teamType={type(team).__name__},teamKeys={team_keys[:12]},"
            f"teamAbbrPresent={isinstance(team,dict) and isinstance(team.get('abbreviation'),str)},"
            f"injuriesType={type(members).__name__},"
            f"injuriesLength={len(members) if isinstance(members,list) else 'n/a'}")


# Explicit NFL ESPN IDs. Check both ID and franchise display name to avoid misassignment.
ESPN_NFL_TEAMS = {
    "1": ("ATL", "Atlanta Falcons"),
    "2": ("BUF", "Buffalo Bills"),
    "3": ("CHI", "Chicago Bears"),
    "4": ("CIN", "Cincinnati Bengals"),
    "5": ("CLE", "Cleveland Browns"),
    "6": ("DAL", "Dallas Cowboys"),
    "7": ("DEN", "Denver Broncos"),
    "8": ("DET", "Detroit Lions"),
    "9": ("GB", "Green Bay Packers"),
    "10": ("TEN", "Tennessee Titans"),
    "11": ("IND", "Indianapolis Colts"),
    "12": ("KC", "Kansas City Chiefs"),
    "13": ("LV", "Las Vegas Raiders"),
    "14": ("LAR", "Los Angeles Rams"),
    "15": ("MIA", "Miami Dolphins"),
    "16": ("MIN", "Minnesota Vikings"),
    "17": ("NE", "New England Patriots"),
    "18": ("NO", "New Orleans Saints"),
    "19": ("NYG", "New York Giants"),
    "20": ("NYJ", "New York Jets"),
    "21": ("PHI", "Philadelphia Eagles"),
    "22": ("ARI", "Arizona Cardinals"),
    "23": ("PIT", "Pittsburgh Steelers"),
    "24": ("LAC", "Los Angeles Chargers"),
    "25": ("SF", "San Francisco 49ers"),
    "26": ("SEA", "Seattle Seahawks"),
    "27": ("TB", "Tampa Bay Buccaneers"),
    "28": ("WSH", "Washington Commanders"),
    "29": ("CAR", "Carolina Panthers"),
    "30": ("JAX", "Jacksonville Jaguars"),
    "33": ("BAL", "Baltimore Ravens"),
    "34": ("HOU", "Houston Texans"),
}

def injury_group_team_code(group):
    team = group.get("team")
    if isinstance(team, dict):
        code = team.get("abbreviation")
        if team.get("id") is not None:
            matched = ESPN_NFL_TEAMS.get(str(team["id"]))
            if matched is None or matched[0] != code:
                raise ValueError("Conflicting nested NFL injury team ID")
        return code
    if team is not None:
        raise ValueError("Unknown injury team structure")
    team_id, name = group.get("id"), group.get("displayName")
    if isinstance(team_id, bool) or not isinstance(team_id, (str, int)):
        raise ValueError("Missing flat NFL injury team ID")
    matched = ESPN_NFL_TEAMS.get(str(team_id))
    if matched is None:
        raise ValueError("Unknown flat NFL injury team ID")
    if not isinstance(name, str) or name.strip() != matched[1]:
        raise ValueError("Flat NFL injury team ID/name mismatch")
    return matched[0]

def injury_entry_shape_summary(member, group_position, injury_position):
    """Only schema shape, never raw athlete IDs, names or medical details."""
    if not isinstance(member, dict):
        return f"group={group_position},entry={injury_position},type={type(member).__name__}"
    athlete = member.get("athlete")
    status = member.get("status")
    keys = sorted(k for k in member if isinstance(k, str))
    athlete_keys = sorted(k for k in athlete if isinstance(k, str)) if isinstance(athlete, dict) else []
    status_keys = sorted(k for k in status if isinstance(k, str)) if isinstance(status, dict) else []
    return (f"group={group_position},entry={injury_position},keys={keys[:16]},"
            f"athleteType={type(athlete).__name__},athleteKeys={athlete_keys[:16]},"
            f"statusType={type(status).__name__},statusKeys={status_keys[:12]},"
            f"athleteIdPresent={isinstance(athlete,dict) and athlete.get('id') is not None},"
            f"athleteDisplayNamePresent={isinstance(athlete,dict) and bool(athlete.get('displayName'))},"
            f"athleteFullNamePresent={isinstance(athlete,dict) and bool(athlete.get('fullName'))})")


def normalized(payload, now, roster_ids):
    if not isinstance(payload, dict) or not isinstance(payload.get("injuries"), list):
        raise ValueError("Unknown injury source schema: requires injuries array")
    groups = payload["injuries"]
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError("Unknown/empty NFL injury groups: not publishing")
    allowed = set(roster_plan.ALL_TEAMS)
    output, seen, group_teams = [], set(), set()
    for position, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError("Malformed injury team group: " + group_shape_summary(group, position))
        try:
            code = injury_group_team_code(group)
        except ValueError as exc:
            raise ValueError(str(exc) + ": " + group_shape_summary(group, position)) from exc
        members = group.get("injuries")
        if code not in allowed or not isinstance(members, list) or len(members) > 150:
            raise ValueError("Unsupported injury group team or list: " + group_shape_summary(group, position))
        if code in group_teams:
            raise ValueError("Repeated team injury group")
        group_teams.add(code)
        for injury_position, member in enumerate(members):
            if not isinstance(member, dict):
                raise ValueError("Invalid injury entry: " + injury_entry_shape_summary(member, position, injury_position))
            athlete = member.get("athlete")
            athlete_id = str(athlete.get("id") or "") if isinstance(athlete, dict) else ""
            name = athlete.get("displayName") or athlete.get("fullName") if isinstance(athlete, dict) else None
            designation = status_text(member.get("status"))
            if not re.fullmatch(r"\d{1,12}", athlete_id) or not isinstance(name, str) or \
               not 2 <= len(name.strip()) <= 100 or designation is None:
                raise ValueError("Injury entry lacks athlete ID, name or status: " + injury_entry_shape_summary(member, position, injury_position))
            key = (code, athlete_id)
            if key in seen:
                raise ValueError("Repeated team/athlete injury entry")
            seen.add(key)
            matches = roster_ids.get(athlete_id, [])
            evidence = "ROSTER_MATCH" if matches == [code] else (
                "ROSTER_CONFLICT" if len(matches) > 1 else "TEAM_UNVERIFIED")
            # A matching third-party roster snapshot is not official participation proof.
            output.append({"espnId": athlete_id, "displayName": name.strip(),
                           "team": code, "designation": designation,
                           "rosterEvidence": evidence})
            if len(output) > MAX_RECORDS:
                raise ValueError("Injury report exceeds record cap")
    output.sort(key=lambda r: (r["team"], r["espnId"]))
    return {"schemaVersion": 1, "sport": "NFL", "type": "injuries",
            "source": "ESPN", "verification": "unverified",
            "scope": "league_injury_pilot", "fetchedAt": now.isoformat().replace("+00:00", "Z"),
            "teamsReported": sorted(group_teams), "count": len(output),
            "injuries": output,
            "notice": "Third-party injury listings; omission does not mean healthy or active. No matchup or projection adjustments."}

def meaning(record):
    # Exclude collection time from content fingerprint, so an unchanged feed can be reused.
    relevant = {k: v for k, v in record.items() if k not in ("fetchedAt",)}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def publish_if_changed(path, value):
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if meaning(old) == meaning(value):
                return "UNCHANGED"
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    pilot.publish(path, value)
    return "PUBLISHED"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=None, help="Offline fixture for test only")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--roster-dir", default="data/live")
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    if args.fixture:
        blob = Path(args.fixture).read_bytes()
        if len(blob) > MAX_BYTES: raise ValueError("Oversized injury fixture")
        payload = json.loads(blob.decode("utf-8"))
    else:
        payload = fetch()
    normalized_data = normalized(payload, now, roster_evidence(args.roster_dir, now))
    result = publish_if_changed(Path(args.out), normalized_data)
    print(json.dumps({"result": result, "injuries": normalized_data["count"],
                      "teamsWithReports": len(normalized_data["teamsReported"]),
                      "fetchedAtAttempt": normalized_data["fetchedAt"],
                      "sourceVerification": "unverified"}))

if __name__ == "__main__":
    main()
