"""Offline tests for conservative NFL schedule snapshot collector."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location("collector", "scripts/collect-nfl-schedule.py")
collector = module_from_spec(spec)
spec.loader.exec_module(collector)

NOW = dt.datetime(2026, 11, 24, 12, 0, 0, tzinfo=dt.timezone.utc)


def event(game_id="401772222"):
    return {
        "id": game_id, "date": "2026-11-25T18:00:00Z",
        "status": {"type": {"state": "pre"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"abbreviation": "ATL"}},
            {"homeAway": "away", "team": {"abbreviation": "NO"}},
        ]}]
    }


class CollectorTest(unittest.TestCase):
    def test_valid(self):
        snapshot = collector.convert({"events": [event()]}, NOW)
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["verification"], "unverified")
        self.assertEqual(snapshot["events"][0]["teams"][0]["abbreviation"], "ATL")
        self.assertEqual(snapshot["events"][0]["id"], "401772222")
        self.assertEqual(snapshot["fetchedAt"], "2026-11-24T12:00:00Z")

    def test_empty_is_valid(self):
        self.assertEqual(collector.convert({"events": []}, NOW)["count"], 0)

    def test_duplicate_and_bad_team(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            collector.convert({"events": [event(), event()]}, NOW)
        item = event()
        item["competitions"][0]["competitors"][0]["homeAway"] = "away"
        with self.assertRaisesRegex(ValueError, "Home and away"):
            collector.convert({"events": [item]}, NOW)

    def test_missing_and_oversized(self):
        with self.assertRaises(ValueError):
            collector.convert({"noEvents": []}, NOW)
        with self.assertRaises(ValueError):
            collector.read_json_bytes(b"a" * (collector.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            collector.convert({"events": [event(str(i + 1)) for i in range(101)]}, NOW)

    def test_atomic_update_and_failed_validation_preserves_last_good(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "data/live/nfl_schedule.json"
            good = collector.convert({"events": [event()]}, NOW)
            collector.save_atomic(path, good)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                bad = collector.convert({"events": [dict(event(), date="bad date")]}, NOW)
                collector.save_atomic(path, bad)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(json.loads(original)["count"], 1)

    def test_fixture_only_when_opted(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / "schedule.json"
            fixture.write_text(json.dumps({"events": [event()]}))
            self.assertEqual(collector.convert(collector.fetch(NOW, fixture), NOW)["count"], 1)
            self.assertTrue(collector.endpoint(NOW).startswith(
                "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates="
            ))


if __name__ == "__main__":
    unittest.main()
