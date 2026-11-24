"""Offline roster pilot regression tests: no external calls."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
from unittest.mock import patch
import urllib.error

spec = spec_from_file_location("pilot", "scripts/collect-nfl-roster-pilot.py")
pilot = module_from_spec(spec)
spec.loader.exec_module(pilot)
NOW = dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc)

def payload():
    return {"athletes":[{"position":"Offense","items":[
        {"id":"123456","fullName":"Sample Athlete","position":{"abbreviation":"RB"}},
        {"id":"987654","displayName":"Another Athlete","position":{"abbreviation":"QB"}}]}]}

class PilotTests(unittest.TestCase):
    def test_roster_normalization(self):
        result=pilot.normalize(payload(),"ATL",NOW)
        self.assertEqual(result["count"],2)
        self.assertEqual(result["scope"],"single_team_pilot")
        self.assertEqual(result["verification"],"unverified")
        self.assertEqual(result["athletes"][0]["espnId"],"123456")

    def test_invalid_roster_never_published(self):
        for bad in ({}, {"athletes":[]}, {"athletes":[{}]}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pilot.normalize(bad,"ATL",NOW)

    def test_duplicate_ids_blocked(self):
        data=payload()
        data["athletes"][0]["items"].append({"id":"123456","fullName":"Other","position":{}})
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            pilot.normalize(data,"ATL",NOW)

    def test_other_teams_blocked(self):
        with self.assertRaises(ValueError):
            pilot.roster_url("BUF")
        self.assertTrue(pilot.roster_url("ATL").endswith("/teams/atl/roster"))

    def test_oversize_blocked(self):
        data=payload()
        data["athletes"][0]["items"] *= 75
        with self.assertRaises(ValueError):
            pilot.normalize(data,"ATL",NOW)

    def test_atomic_success_and_preserve_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"data/live/nfl_roster_pilot_ATL.json"
            good=pilot.normalize(payload(),"ATL",NOW)
            pilot.publish(path,good)
            before=path.read_bytes()
            with self.assertRaises(ValueError):
                invalid=pilot.normalize({}, "ATL",NOW)
                pilot.publish(path,invalid)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(json.loads(before)["team"],"ATL")

    def test_provider_http_failure(self):
        e=urllib.error.HTTPError(pilot.roster_url("ATL"),503,"unavailable",{},None)
        with patch.object(pilot.urllib.request,"urlopen",side_effect=e):
            with self.assertRaisesRegex(RuntimeError,"HTTP 503"):
                pilot.fetch("ATL")

if __name__=="__main__":
    unittest.main()
