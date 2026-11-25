"""Offline tests for three-group capped collection and cross-run provider cooldown."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("multi","scripts/collect-nfl-roster-v8-multi.py")
multi=importlib.util.module_from_spec(spec)
spec.loader.exec_module(multi)
plan=multi.plan
NOW=dt.datetime(2026,11,25,3,tzinfo=dt.timezone.utc)

def fixture(team):
    return {"athletes":[{"items":[{"id":str(110000+plan.ALL_TEAMS.index(team)),
        "fullName":"Test Player "+team,"position":{"abbreviation":"RB"}}]}]}

def cache(team,at=NOW):
    return {"schemaVersion":1,"sport":"NFL","type":"roster","source":"ESPN",
       "verification":"unverified","scope":"controlled_batch","team":team,
       "fetchedAt":at.isoformat().replace("+00:00","Z"),"count":1,
       "athletes":[{"espnId":"123456","displayName":"Example Player","position":"RB"}]}


class MultiTests(unittest.TestCase):
    def test_group_selection_bounds(self):
        self.assertEqual(multi.selected_groups(1,3),(1,2,3))
        self.assertEqual(multi.selected_groups(7,3),(7,8,9))
        self.assertEqual(multi.selected_groups(9,1),(9,))
        for a,b in ((0,3),(8,3),(1,4),(1,0),(True,2)):
            with self.assertRaises(ValueError):multi.selected_groups(a,b)

    def test_three_groups_nine_requests_with_global_pacing(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[];sleeps=[]
            def fetch(team):
                calls.append(team)
                return fixture(team)
            report=multi.collect_multiple(1,3,Path(folder),NOW,fetch,sleeps.append)
            self.assertTrue(report["allSuccessful"])
            self.assertEqual(report["requestsAttempted"],9)
            self.assertEqual(len(calls),9)
            self.assertEqual(sleeps,[3]*8)
            self.assertEqual(len(set(calls)),9)
            self.assertEqual(len(list(Path(folder).glob("nfl_roster_*.json"))),9)

    def test_reuse_across_groups_skips_network(self):
        with tempfile.TemporaryDirectory() as folder:
            first=plan.group_teams(1)[0]
            path=Path(folder)/plan.full_manifest()[first]
            path.write_text(json.dumps(cache(first)))
            calls=[]
            report=multi.collect_multiple(1,3,Path(folder),NOW,lambda team:(calls.append(team) or fixture(team)),lambda _:None)
            self.assertEqual(report["requestsAttempted"],8)
            self.assertEqual(len(calls),8)
            self.assertEqual(report["results"][0]["status"],"REUSED")
            self.assertEqual(json.loads(path.read_text()),cache(first))

    def test_per_team_failure_preserves_last_good_and_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            fail=plan.group_teams(2)[0]
            path=Path(folder)/plan.full_manifest()[fail]
            old=cache(fail,NOW-dt.timedelta(hours=40))
            path.write_text(json.dumps(old))
            report=multi.collect_multiple(1,3,Path(folder),NOW,
                lambda team:{"athletes":[]} if team==fail else fixture(team),lambda _:None)
            self.assertFalse(report["allSuccessful"])
            self.assertEqual(report["requestsAttempted"],9)
            self.assertEqual(json.loads(path.read_text()),old)
            self.assertEqual(report["results"][-1]["status"],"PUBLISHED")

    def test_http429_stops_all_groups_and_persists_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[];all_teams=[t for n in (1,2,3) for t in plan.group_teams(n)]
            def fetch(team):
                calls.append(team)
                if len(calls)==4:
                    raise multi.Throttled("HTTP 429",retry_after="3600")
                return fixture(team)
            report=multi.collect_multiple(1,3,Path(folder),NOW,fetch,lambda _:None)
            self.assertFalse(report["allSuccessful"])
            self.assertEqual(report["requestsAttempted"],4)
            self.assertEqual(calls,all_teams[:4])
            self.assertEqual(report["stoppedBecause"],"HTTP_429")
            self.assertEqual(report["results"][-1]["status"],"SKIPPED_RATE_LIMIT")
            cooldown=json.loads((Path(folder)/multi.COOLDOWN_FILE).read_text())
            self.assertEqual(cooldown["blockedUntil"],(NOW+dt.timedelta(hours=1)).isoformat().replace("+00:00","Z"))
            repeated=multi.collect_multiple(4,3,Path(folder),NOW+dt.timedelta(minutes=5),lambda _ : self.fail("No provider calls"),lambda _:None)
            self.assertEqual(repeated["requestsAttempted"],0)
            self.assertEqual(repeated["stoppedBecause"],"ACTIVE_PROVIDER_COOLDOWN")
            resumed=multi.collect_multiple(4,1,Path(folder),NOW+dt.timedelta(hours=2),fixture,lambda _:None)
            self.assertEqual(resumed["requestsAttempted"],3)

    def test_retry_after_date_and_clamp(self):
        self.assertEqual(multi.retry_after_seconds("120",NOW),120)
        self.assertEqual(multi.retry_after_seconds("999999",NOW),6*3600)
        self.assertEqual(multi.retry_after_seconds("bad",NOW),None)
        self.assertEqual(multi.retry_after_seconds("Wed, 25 Nov 2026 04:00:00 GMT",NOW),3600)

    def test_last_group_max_one_request(self):
        with tempfile.TemporaryDirectory() as folder:
            result=multi.collect_multiple(9,1,Path(folder),NOW,fixture,lambda _:None)
            self.assertTrue(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],1)

if __name__=="__main__":unittest.main()
