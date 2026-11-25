"""Offline tests for scheduled NFL roster rotation and source protection."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("v10", "scripts/refresh-nfl-rosters-v10.py")
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)
NOW = dt.datetime(2026, 11, 25, 13, 15, tzinfo=dt.timezone.utc)

def sample(team):
    return {"athletes": [{"items": [{
        "id": str(100000 + v10.multi.plan.ALL_TEAMS.index(team)),
        "fullName": "Example Athlete " + team,
        "position": {"abbreviation": "RB"}
    }]}]}

def snapshot(team, fetched_at):
    return {"schemaVersion":1, "sport":"NFL", "type":"roster",
        "source":"ESPN", "verification":"unverified", "scope":"controlled_batch",
        "team":team, "fetchedAt":fetched_at.isoformat().replace("+00:00","Z"),
        "count":1, "athletes":[{"espnId":"123456",
        "displayName":"Existing Athlete", "position":"RB"}]}

class RotationTest(unittest.TestCase):
    def test_all_32_teams_partitioned_into_four_unique_cohorts(self):
        groups=v10.cohorts()
        self.assertEqual(len(groups),4)
        self.assertTrue(all(len(x)==8 for x in groups))
        self.assertEqual(set(team for group in groups for team in group),
                         set(v10.multi.plan.ALL_TEAMS))
        self.assertEqual(len(set(team for group in groups for team in group)),32)

    def test_utc_schedule_selection(self):
        for hour, expected in [(0,4),(1,1),(6,1),(7,2),
                               (12,2),(13,3),(18,3),(19,4),(23,4)]:
            self.assertEqual(v10.choose_cohort(NOW.replace(hour=hour)),expected)
        self.assertEqual(v10.choose_cohort(NOW,2),2)
        for invalid in (0,5,True,1.5):
            with self.assertRaises(ValueError):
                v10.choose_cohort(NOW,invalid)

    def test_delayed_cron_still_selects_original_cohort(self):
        late=NOW.replace(hour=9)
        self.assertEqual(v10.choose_cohort(late,scheduled_cron="23 1 * * *"),1)
        self.assertEqual(v10.choose_cohort(late,scheduled_cron="23 7 * * *"),2)
        self.assertEqual(v10.choose_cohort(late,scheduled_cron="23 13 * * *"),3)
        self.assertEqual(v10.choose_cohort(late,scheduled_cron="23 19 * * *"),4)
        with self.assertRaises(ValueError):
            v10.choose_cohort(late,scheduled_cron="0 * * * *")

    def test_only_missing_or_stale_rosters_requested_and_delay_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            team=v10.cohorts()[2][0]
            existing=Path(folder)/v10.multi.plan.full_manifest()[team]
            existing.write_text(json.dumps(snapshot(team,NOW-dt.timedelta(hours=1))))
            calls=[];sleeps=[]
            result=v10.collect_cohort(Path(folder),NOW,3,
                    lambda team:(calls.append(team) or sample(team)),sleeps.append)
            self.assertTrue(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],7)
            self.assertEqual(result["results"][0]["status"],"REUSED")
            self.assertEqual(sleeps,[3]*6)
            self.assertNotIn(team,calls)
            self.assertEqual(json.loads(existing.read_text())["athletes"][0]["displayName"],
                             "Existing Athlete")

    def test_missing_team_and_stale_unchanged_after_bad_response(self):
        with tempfile.TemporaryDirectory() as folder:
            first=v10.cohorts()[0][0]
            file=Path(folder)/v10.multi.plan.full_manifest()[first]
            old=snapshot(first,NOW-dt.timedelta(hours=48))
            file.write_text(json.dumps(old))
            before=file.read_bytes()
            def fetch(team):
                if team==first:return {"athletes":[]}
                return sample(team)
            result=v10.collect_cohort(Path(folder),NOW,1,fetch,lambda _:None)
            self.assertFalse(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],8)
            self.assertEqual(file.read_bytes(),before)
            self.assertEqual(result["results"][1]["status"],"PUBLISHED")

    def test_429_aborts_cohort_and_persists_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def fetch(team):
                calls.append(team)
                if len(calls)==2:raise v10.multi.Throttled("HTTP 429",retry_after="3600")
                return sample(team)
            result=v10.collect_cohort(Path(folder),NOW,1,fetch,lambda _:None)
            self.assertFalse(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],2)
            self.assertEqual(result["status"],"RATE_LIMITED")
            self.assertEqual(result["results"][2]["status"],"SKIPPED_RATE_LIMIT")
            self.assertTrue((Path(folder)/v10.multi.COOLDOWN_FILE).exists())
            again=v10.collect_cohort(Path(folder),NOW+dt.timedelta(minutes=5),2,
                                    lambda _:self.fail("Provider must not be called"),lambda _:None)
            self.assertEqual(again["requestsAttempted"],0)
            self.assertEqual(again["status"],"ACTIVE_PROVIDER_COOLDOWN")

    def test_full_fresh_cohort_has_zero_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            for team in v10.cohorts()[1]:
                p=Path(folder)/v10.multi.plan.full_manifest()[team]
                p.write_text(json.dumps(snapshot(team,NOW)))
            result=v10.collect_cohort(Path(folder),NOW,2,
                              lambda _:self.fail("No provider requests needed"),lambda _:None)
            self.assertTrue(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],0)
            self.assertTrue(all(x["status"]=="REUSED" for x in result["results"]))

if __name__=="__main__":
    unittest.main()
