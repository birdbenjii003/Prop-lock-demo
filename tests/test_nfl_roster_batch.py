"""Offline tests for bounded roster batch, failure isolation, and throttling."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("roster_batch","scripts/collect-nfl-roster-batch.py")
batch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
NOW=dt.datetime(2026,11,24,12,tzinfo=dt.timezone.utc)

def payload(team):
    return {"athletes":[{"items":[{"id":str(100001+batch.BATCH.index(team)),
       "fullName":"Sample Player "+team,"position":{"abbreviation":"RB"}}]}]}

class BatchTests(unittest.TestCase):
    def test_all_three_succeed_and_are_separate(self):
        times=[]
        with tempfile.TemporaryDirectory() as tmp:
            r=batch.collect(payload,Path(tmp),NOW,sleep=times.append)
            self.assertTrue(r["allSuccessful"])
            self.assertEqual([x["status"] for x in r["results"]],["PUBLISHED"]*3)
            self.assertEqual(times,[3,3])
            for team in batch.BATCH:
                snapshot=json.loads((Path(tmp)/f"nfl_roster_{team}.json").read_text())
                self.assertEqual(snapshot["scope"],"controlled_batch")
                self.assertEqual(snapshot["team"],team)
                self.assertEqual(snapshot["verification"],"unverified")
                self.assertEqual(snapshot["athletes"][0]["displayName"],"Sample Player "+team)

    def test_failed_team_preserves_old_file_but_other_teams_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"nfl_roster_KC.json"
            path.write_text('{"lastGood":true}\n')
            def fail_kc(team):
                if team=="KC": return {"athletes":[]}
                return payload(team)
            r=batch.collect(fail_kc,Path(tmp),NOW,sleep=lambda _:None)
            self.assertFalse(r["allSuccessful"])
            self.assertEqual([x["status"] for x in r["results"]],["PUBLISHED","FAILED","PUBLISHED"])
            self.assertEqual(json.loads(path.read_text()),{"lastGood":True})
            self.assertTrue((Path(tmp)/"nfl_roster_PHI.json").exists())

    def test_rate_limit_stops_remaining_teams(self):
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            def limited(team):
                calls.append(team)
                if team=="KC":raise batch.RateLimited("HTTP 429")
                return payload(team)
            r=batch.collect(limited,Path(tmp),NOW,sleep=lambda _:None)
            self.assertEqual(calls,["BUF","KC"])
            self.assertEqual([x["status"] for x in r["results"]],
                ["PUBLISHED","RATE_LIMITED","SKIPPED_RATE_LIMIT"])
            self.assertFalse((Path(tmp)/"nfl_roster_PHI.json").exists())

    def test_boundaries_and_urls(self):
        self.assertEqual(batch.BATCH,("BUF","KC","PHI"))
        with self.assertRaises(ValueError):batch.team_url("ATL")
        self.assertTrue(batch.team_url("BUF").endswith("/teams/buf/roster"))
        with tempfile.TemporaryDirectory() as tmp:
            r=batch.collect(lambda _:{"athletes":[{"items":[]}]},Path(tmp),NOW,sleep=lambda _:None)
            self.assertTrue(all(x["status"]=="FAILED" for x in r["results"]))
            self.assertFalse(list(Path(tmp).glob("*.json")))

if __name__=="__main__":unittest.main()
