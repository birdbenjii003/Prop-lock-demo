#!/usr/bin/env python3
"""Conservative NFL schedule snapshot collector. Python standard library only.

Writes data/live/nfl_schedule.json atomically only after strict basic validation.
Not a verified player matchup, odds feed, or guaranteed real-time game service.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

DEFAULT_OUT = Path("data/live/nfl_schedule.json")
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 15
MAX_EVENTS = 100
UTC = dt.timezone.utc


def iso_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z") if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def endpoint(now):
    # ESPN's default NFL scoreboard is a provider-selected game window.
    # Do not assume a custom multi-day dates range is supported for this league.
    return "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?limit=100"


def convert(payload, now):
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("Schedule response lacks events list")
    raw_events = payload["events"]
    if len(raw_events) > MAX_EVENTS:
        raise ValueError("Schedule response exceeds bounded event count")
    items = []
    seen = set()
    for event in raw_events:
        if not isinstance(event, dict):
            raise ValueError("Invalid schedule event")
        game_id = str(event.get("id") or "")
        kickoff = iso_utc(event.get("date"))
        competition = (event.get("competitions") or [None])[0]
        if not game_id.isdigit() or not kickoff or not isinstance(competition, dict):
            raise ValueError("Missing stable event ID, time or competition")
        if game_id in seen:
            raise ValueError("Duplicate event ID")
        seen.add(game_id)
        competitors = competition.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            raise ValueError("Invalid NFL opponents")
        teams = []
        for competitor in competitors:
            if not isinstance(competitor, dict):
                raise ValueError("Invalid competitor")
            team = competitor.get("team") or {}
            code = team.get("abbreviation")
            home_away = competitor.get("homeAway")
            if not isinstance(code, str) or not 2 <= len(code) <= 3 or not code.isalpha() or home_away not in ("home", "away"):
                raise ValueError("Invalid team identity")
            teams.append({"abbreviation": code.upper(), "homeAway": home_away})
        if {x["homeAway"] for x in teams} != {"home", "away"}:
            raise ValueError("Home and away sides do not match")
        status = (event.get("status") or {}).get("type") or {}
        state = status.get("state", "unknown")
        if state not in ("pre", "in", "post", "unknown"):
            state = "unknown"
        items.append({"id": game_id, "kickoff": kickoff, "teams": teams, "state": state})
    items.sort(key=lambda x: (x["kickoff"], x["id"]))
    return {
        "schemaVersion": 1,
        "sport": "NFL",
        "type": "schedule",
        "source": "ESPN",
        "verification": "unverified",
        "fetchedAt": now.isoformat().replace("+00:00", "Z"),
        "windowDays": None,
        "scope": "provider_default_scoreboard",
        "count": len(items),
        "events": items,
        "notice": "Third-party schedule snapshot, not independently verified, no guaranteed refresh time or player matchup.",
    }


def read_json_bytes(blob):
    if len(blob) > MAX_BYTES:
        raise ValueError("Response exceeds 2 MB limit")
    return json.loads(blob.decode("utf-8"))


def fetch(now, fixture=None):
    if fixture is not None:
        return read_json_bytes(Path(fixture).read_bytes())
    request = urllib.request.Request(
        endpoint(now),
        headers={"User-Agent": "PropLockResearchSnapshot/1.0", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP {response.status}")
            blob = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # Report only a short redacted body for debugging unsupported query formats.
        detail = exc.read(512).decode("utf-8", errors="replace")
        detail = "".join(c if c.isprintable() else " " for c in detail)[:250]
        raise RuntimeError(f"ESPN scoreboard HTTP {exc.code}; provider detail: {detail}") from exc
    return read_json_bytes(blob)


def save_atomic(path, snapshot):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=".nfl_schedule-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Test-only local JSON fixture; never use for scheduled production runs")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    snapshot = convert(fetch(now, args.fixture), now)
    # No fallback to mock values and no overwrite on failed downloads or validation.
    save_atomic(Path(args.out), snapshot)
    print(f"NFL schedule snapshot saved: {snapshot['count']} events; collected {snapshot['fetchedAt']}; unverified third-party data")


if __name__ == "__main__":
    main()
