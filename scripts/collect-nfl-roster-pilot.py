#!/usr/bin/env python3
"""Manual NFL roster PILOT for one explicit team, not a league-wide roster feed.
Unverified ESPN third-party data; never make current-team or eligibility assertions.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request

UTC = dt.timezone.utc
MAX_BYTES = 1_000_000
TIMEOUT_SECONDS = 15
TEAM_ALLOWLIST = ("ATL",)  # Only sample team until API coverage is validated.
OUTPUT = Path("data/live/nfl_roster_pilot_ATL.json")


def roster_url(team):
    if team not in TEAM_ALLOWLIST:
        raise ValueError("Team not enabled for initial roster pilot")
    return f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team.lower()}/roster"


def normalize(payload, team, now):
    if not isinstance(payload, dict) or not isinstance(payload.get("athletes"), list):
        raise ValueError("Roster response missing athletes groups")
    groups = payload["athletes"]
    players = []
    seen = set()
    for group in groups:
        members = group.get("items") if isinstance(group, dict) else None
        if not isinstance(members, list):
            raise ValueError("Roster group missing items")
        for player in members:
            if not isinstance(player, dict):
                raise ValueError("Invalid roster player")
            ident = str(player.get("id") or "")
            name = player.get("fullName") or player.get("displayName")
            position = (player.get("position") or {}).get("abbreviation")
            if not re.fullmatch(r"\d{1,12}", ident) or not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
                raise ValueError("Roster athlete missing stable ESPN ID or name")
            if ident in seen:
                raise ValueError("Duplicate ESPN roster player ID")
            seen.add(ident)
            players.append({"espnId": ident, "displayName": name.strip(),
                            "position": position if isinstance(position, str) and len(position) <= 8 else None})
    if not 1 <= len(players) <= 125:
        raise ValueError("Incomplete or oversized roster: no snapshot published")
    # Team path is a requested source, not a verified up-to-date athlete/team assignment.
    players.sort(key=lambda x: x["espnId"])
    return {"schemaVersion": 1, "sport": "NFL", "type": "roster",
            "source": "ESPN", "verification": "unverified",
            "scope": "single_team_pilot", "team": team,
            "fetchedAt": now.isoformat().replace("+00:00", "Z"),
            "count": len(players), "athletes": players,
            "notice": "Roster listing from third party. Current-team identity, eligibility and game participation are not independently verified."}


def fetch(team):
    req = urllib.request.Request(roster_url(team), headers={
        "User-Agent": "PropLockResearchRosterPilot/1.0",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"Roster provider HTTP {response.status}")
            blob = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Roster provider HTTP {exc.code}") from exc
    if len(blob) > MAX_BYTES:
        raise ValueError("Roster payload exceeds 1 MB")
    return json.loads(blob.decode("utf-8"))


def publish(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".roster-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=None, help="Unit-test only: local roster payload")
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    if args.fixture:
        blob = Path(args.fixture).read_bytes()
        if len(blob) > MAX_BYTES:
            raise ValueError("Roster fixture exceeds size limit")
        payload = json.loads(blob.decode("utf-8"))
    else:
        payload = fetch("ATL")
    data = normalize(payload, "ATL", now)
    publish(OUTPUT, data)
    print(f"Roster PILOT for ATL published: {data['count']} athletes; unverified; at {data['fetchedAt']}")


if __name__ == "__main__":
    main()
