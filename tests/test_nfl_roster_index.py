"""No-network tests for roster coverage indexing and v7 batch."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

def read_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

index=read_module("index","scripts/build-nfl-roster-index.py")
v7=read_module("v7","scripts/collect-nfl-roster-batch-v7.py")
NOW=dt.datetime(2026,11,24,20,tzinfo=dt.timezone.utc)

def roster(team,athletes,age_hours=1):
    return {"schemaVersion":1,"sport":"NFL","type":"roster","source":"ESPN",
      "verification":"unverified","scope":"controlled_batch","team":team,
      "fetchedAt":(NOW-dt.timedelta(hours=age_hours)).isoformat().replace("+00:00","Z"),
      "count":len(athletes),
      "athletes":[{"espnId":str(ident),"displayName":name,"position":"RB"} for ident,name in athletes]}

def save(folder,team,obj):
    name=index.MANIFEST[team]
    (Path(folder)/name).write_text(json.dumps(obj))

def raw(team):
    return {"athletes":[{"items":[{"id":str(1000+v7.BATCH_TEAMS.index(team)),
      "fullName":"Example Athlete "+team,"position":{"abbreviation":"WR"}}]}]}

class IndexTests(unittest.TestCase):
    def test_empty_coverage_is_not_full_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=index.index_snapshots(tmp,NOW)
            self.assertEqual(result["coverage"]["teamsTracked"],7)
            self.assertEqual(result["coverage"]["teamsExpected"],32)
            self.assertEqual(result["coverage"]["teamsPresent"],0)
            self.assertEqual(result["coverage"]["teamsMissing"],7)
            self.assertEqual(result["identityConflicts"],[])

    def test_duplicate_espn_id_across_teams_is_flagged_not_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            save(tmp,"BUF",roster("BUF",[("12345","Player A")]))
            save(tmp,"KC",roster("KC",[("12345","Player A")]))
            save(tmp,"PHI",roster("PHI",[("77777","Other")],age_hours=45))
            result=index.index_snapshots(tmp,NOW)
            cov=result["coverage"]
            self.assertEqual(cov["teamsPresent"],3)
            self.assertEqual(cov["teamsCurrent"],2)
            self.assertEqual(cov["teamsStale"],1)
            self.assertEqual(cov["unresolvedCrossTeamIds"],1)
            conflict=result["identityConflicts"][0]
            self.assertEqual(conflict["listedTeams"],["BUF","KC"])
            self.assertEqual(conflict["status"],"TEAM_ID_CONFLICT_UNRESOLVED")

    def test_corrupt_team_isolated_and_does_not_influence_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            save(tmp,"BUF",roster("BUF",[("12345","Player A")]))
            save(tmp,"KC",roster("OTHER",[("12345","Player A")]))
            result=index.index_snapshots(tmp,NOW)
            self.assertEqual(result["coverage"]["teamsInvalid"],1)
            self.assertEqual(result["coverage"]["teamsPresent"],1)
            self.assertEqual(result["identityConflicts"],[])

    def test_duplicate_inside_single_team_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            save(tmp,"BUF",roster("BUF",[("12345","Same"),("12345","Same")]))
            self.assertEqual(index.index_snapshots(tmp,NOW)["coverage"]["teamsInvalid"],1)

    def test_new_batch_success_and_failure_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=v7.collect_new_batch(raw,Path(tmp),NOW,lambda _:None)
            self.assertTrue(report["allSuccessful"])
            self.assertEqual(report["requestedTeams"],list(v7.BATCH_TEAMS))
            for team in v7.BATCH_TEAMS:
                self.assertTrue((Path(tmp)/f"nfl_roster_{team}.json").exists())
        with tempfile.TemporaryDirectory() as tmp:
            def failure(team):
                if team=="DET":raise ValueError("broken roster")
                return raw(team)
            report=v7.collect_new_batch(failure,Path(tmp),NOW,lambda _:None)
            self.assertFalse(report["allSuccessful"])
            self.assertEqual([x["status"] for x in report["results"]],["PUBLISHED","FAILED","PUBLISHED"])

    def test_rate_limit_stops_new_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def limited(team):
                calls.append(team)
                if team=="DET":raise v7.batch.RateLimited("HTTP 429")
                return raw(team)
            report=v7.collect_new_batch(limited,Path(tmp),NOW,lambda _:None)
            self.assertEqual(calls,["BAL","DET"])
            self.assertEqual(report["results"][-1]["status"],"SKIPPED_RATE_LIMIT")

if __name__=="__main__":unittest.main()
