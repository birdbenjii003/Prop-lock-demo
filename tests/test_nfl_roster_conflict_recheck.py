"""Offline tests: conflict evidence recheck, no automatic team guessing."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("recheck","scripts/recheck-nfl-roster-conflicts.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW=dt.datetime(2026,11,25,12,tzinfo=dt.timezone.utc)

def idx(conflicts):
    return {"sport":"NFL","type":"roster_index","verification":"unverified",
            "identityConflicts":[{"espnId":ident,"listedTeams":teams,
              "status":"TEAM_ID_CONFLICT_UNRESOLVED"} for ident,teams in conflicts]}

def player(team):
    return {"athletes":[{"items":[{"id":str(100000+module.multi.plan.ALL_TEAMS.index(team)),
       "fullName":"Example Athlete","position":{"abbreviation":"QB"}}]}]}

class RecheckTests(unittest.TestCase):
    def test_real_shape_conflicts_select_only_four_teams(self):
        data=idx([("4039034",["BUF","IND"]),("4427843",["BUF","SEA"]),
                  ("5155179",["KC","SEA"])])
        self.assertEqual(module.candidate_teams(data),("BUF","IND","KC","SEA"))

    def test_duplicate_listings_stay_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=idx([("4039034",["BUF","IND"])])
            delay=[]
            report=module.recheck(data,Path(tmp),NOW,player,delay.append)
            self.assertTrue(report["allSuccessful"])
            self.assertEqual(report["requestsAttempted"],2)
            self.assertEqual(delay,[3])
            self.assertNotIn("resolvedTeam",report)
            for team in ("BUF","IND"):
                stored=json.loads((Path(tmp)/f"nfl_roster_{team}.json").read_text())
                self.assertEqual(stored["verification"],"unverified")
                self.assertEqual(stored["scope"],"controlled_batch")

    def test_failed_one_preserves_last_good_and_rechecks_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"nfl_roster_BUF.json"
            path.write_bytes(b'{"old":"snapshot"}\n')
            def provider(team):
                if team=="BUF":return {"athletes":[]}
                return player(team)
            result=module.recheck(idx([("1",["BUF","IND"])]),Path(tmp),NOW,provider,lambda _:None)
            self.assertFalse(result["allSuccessful"])
            self.assertEqual(path.read_bytes(),b'{"old":"snapshot"}\n')
            self.assertEqual(result["results"][1]["status"],"PUBLISHED")

    def test_429_stops_remaining_and_saves_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            def limited(team):
                if team=="IND":raise module.multi.Throttled("HTTP 429",retry_after="5400")
                return player(team)
            data=idx([("1",["BUF","IND"]),("2",["KC","SEA"])])
            report=module.recheck(data,Path(tmp),NOW,limited,lambda _:None)
            self.assertEqual(report["requestsAttempted"],2)
            self.assertEqual(report["results"][2]["status"],"SKIPPED_RATE_LIMIT")
            later=module.recheck(data,Path(tmp),NOW+dt.timedelta(minutes=20),
                                  lambda _:self.fail("No network during cooldown"),lambda _:None)
            self.assertEqual(later["requestsAttempted"],0)
            self.assertEqual(later["status"],"ACTIVE_PROVIDER_COOLDOWN")

    def test_guard_rejects_bad_identity_or_more_than_four_teams(self):
        with self.assertRaises(ValueError):
            module.candidate_teams({"identityConflicts":[]})
        with self.assertRaises(ValueError):
            module.candidate_teams(idx([("1",["BUF","IND","KC","SEA","NYG"])]))
        with self.assertRaises(ValueError):
            module.candidate_teams(idx([("1",["BUF","UNKNOWN"])]))

    def test_no_conflicts_no_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=module.recheck(idx([]),Path(tmp),NOW,
                                  lambda _:self.fail("No network expected"),lambda _:None)
            self.assertEqual(report["requestsAttempted"],0)
            self.assertTrue(report["allSuccessful"])

if __name__=="__main__":
    unittest.main()
