#!/usr/bin/env python3
"""Controlled read-only NFL injury refresh and independently labeled health check.

One provider request per eligible invocation. Status is not a player's health.
The data snapshot is preserved unchanged when a source fails or content is identical.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTC = dt.timezone.utc
MIN_CHECK_HOURS = 6
HEALTH_PATH = Path("data/live/nfl_injury_health.json")
SNAPSHOT_PATH = Path("data/live/nfl_injuries.json")
ALLOWED_STATUS = {"SUCCESS_CHANGED", "SUCCESS_UNCHANGED", "FAILED", "SKIPPED_COOLDOWN"}

def load_collector():
    spec = importlib.util.spec_from_file_location("nfl_injury_refresh_collector", ROOT / "scripts/collect-nfl-injuries-v11.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def as_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    except ValueError:
        return None

def stamp(now):
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def read_health(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (data.get("schemaVersion") != 1 or data.get("sport") != "NFL" or
            data.get("type") != "injury_refresh_health" or
            data.get("state") not in ALLOWED_STATUS):
            return None
        return data
    except (OSError, ValueError, AttributeError, TypeError):
        return None

def last_success_time(health):
    if not health:
        return None
    return as_utc(health.get("lastSuccessfulCheckAt"))

def should_check(health, now, force=False):
    if force:
        return True
    last = last_success_time(health)
    if last is None:
        return True
    elapsed = (now - last).total_seconds()
    # Clock skew or a future timestamp cannot authorize repeated upstream calls.
    return elapsed >= MIN_CHECK_HOURS * 3600

def source_timestamp(snapshot_path):
    try:
        data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 1 or data.get("sport") != "NFL" or data.get("type") != "injuries":
            return None
        return stamp(as_utc(data["fetchedAt"])) if as_utc(data.get("fetchedAt")) else None
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None

def status_error(exc):
    # Deliberately omit provider payloads, injury values and exception strings.
    if isinstance(exc, ValueError):
        return "INVALID_PROVIDER_SCHEMA_OR_PAYLOAD"
    if isinstance(exc, (TimeoutError, OSError)):
        return "UPSTREAM_NETWORK_FAILURE"
    return "COLLECTION_FAILED"

def refresh(now, health_path, snapshot_path, roster_dir, fetcher, publisher,
            roster_loader, normalizer, force=False):
    prior = read_health(health_path)
    if not should_check(prior, now, force):
        return {"state": "SKIPPED_COOLDOWN", "healthUpdated": False,
                "nextEligibleAt": stamp(last_success_time(prior) + dt.timedelta(hours=MIN_CHECK_HOURS))}
    checked_at = stamp(now)
    previous_success = prior.get("lastSuccessfulCheckAt") if prior else None
    try:
        payload = fetcher()
        result = normalizer(payload, now, roster_loader(roster_dir, now))
        state = "SUCCESS_CHANGED" if publisher(snapshot_path, result) == "PUBLISHED" else "SUCCESS_UNCHANGED"
        previous_success = checked_at
        count = result["count"]
        groups = len(result["teamsReported"])
    except Exception as exc:
        # No successful source fetch is claimed, and no failed data is published.
        state = "FAILED"
        count = None
        groups = None
        error_code = status_error(exc)
    health = {
        "schemaVersion": 1, "sport": "NFL", "type": "injury_refresh_health",
        "source": "ESPN", "verification": "unverified",
        "state": state, "lastAttemptAt": checked_at,
        "lastSuccessfulCheckAt": previous_success,
        "lastContentChangedAt": source_timestamp(snapshot_path),
        "countAtLastAttempt": count, "teamGroupsAtLastAttempt": groups,
        "notice": "Successful check is not an injury change, player identity verification or proof of availability."
    }
    if state == "FAILED":
        health["failureCode"] = error_code
    # Write only when a check was actually attempted.
    publisher(health_path, health)
    return {"state": state, "healthUpdated": True, "failureCode": health.get("failureCode")}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", default=str(HEALTH_PATH))
    parser.add_argument("--snapshot", default=str(SNAPSHOT_PATH))
    parser.add_argument("--roster-dir", default="data/live")
    parser.add_argument("--force", action="store_true", help="Manual probe; bypass 6h cooldown")
    args = parser.parse_args()
    collector = load_collector()
    now = dt.datetime.now(UTC).replace(microsecond=0)
    outcome = refresh(now, Path(args.health), Path(args.snapshot), Path(args.roster_dir),
                      collector.fetch, collector.publish_if_changed, collector.roster_evidence,
                      collector.normalized, args.force)
    print(json.dumps(outcome, sort_keys=True))
    if outcome["state"] == "FAILED":
        raise SystemExit("Injury collection failed; last-good snapshot preserved and failure recorded")

if __name__ == "__main__":
    main()
