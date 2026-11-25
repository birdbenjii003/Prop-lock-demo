"""Offline v8 tests: 32-team manifest, request cap, cache reuse and fail-closed behavior."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

runner=load("runner_v8","scripts/collect-nfl-roster-v8.py")
planner=runner.plan
index=planner.index
NOW=dt.datetime(2026,11,24,20,tzinfo=dt.timezone.utc)


def source(team):
    return {"athletes":[{"items":[
        {"id":str(100000+planner.ALL_TEAMS.index(team)),
         "fullName":"Test Athlete "+team,"position":{"abbreviation":"RB"}}
    ]}]}


def cached(team,age=1):
    return {"schemaVersion":1,"sport":"NFL","type":"roster","source":"ESPN",
        "verification":"unverified","scope":"controlled_batch","team":team,
        "fetchedAt":(NOW-dt.timedelta(hours=age)).isoformat().replace("+00:00","Z"),
        "count":1,"athletes":[{"espnId":"123456","displayName":"Example Runner","position":"RB"}]}


class V8Tests(unittest.TestCase):
    def test_32_team_manifest_and_no_duplicates(self):
        manifest=planner.full_manifest()
        self.assertEqual(len(manifest),32)
        self.assertEqual(len(planner.REMAINING_TEAMS),25)
        self.assertEqual(len(planner.GROUPS),9)
        self.assertEqual(sorted({x for group in planner.GROUPS for x in group}),
                         sorted(planner.REMAINING_TEAMS))
        self.assertEqual(set(planner.INITIAL_TEAMS).intersection(planner.REMAINING_TEAMS),set())
        self.assertTrue(all(len(group)<=3 for group in planner.GROUPS))
        self.assertEqual(manifest["ATL"],"nfl_roster_pilot_ATL.json")
        self.assertEqual(planner.MAX_NETWORK_REQUESTS,3)

    def test_unknown_group_blocked(self):
        for value in (0,10,-1,"1",None):
            with self.assertRaises(ValueError):
                planner.group_teams(value)

    def test_new_batch_bounds_pacing_and_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            sleeps=[]
            result=runner.collect_group(1,Path(tmp),NOW,source,sleeps.append)
            self.assertTrue(result["allSuccessful"])
            self.assertEqual(result["requestsAttempted"],3)
            self.assertEqual(sleeps,[3,3])
            self.assertEqual([x["status"] for x in result["results"]],["PUBLISHED"]*3)
            for team in planner.group_teams(1):
                output=json.loads((Path(tmp)/f"nfl_roster_{team}.json").read_text())
                self.assertEqual(output["team"],team)
                self.assertEqual(output["verification"],"unverified")

    def test_fresh_snapshot_reused_without_provider_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            teams=planner.group_teams(1)
            path=Path(tmp)/f"nfl_roster_{teams[0]}.json"
            path.write_text(json.dumps(cached(teams[0])))
            calls=[]
            def fetch(team):
                calls.append(team)
                return source(team)
            result=runner.collect_group(1,Path(tmp),NOW,fetch,lambda _:None)
            self.assertEqual(result["requestsAttempted"],2)
            self.assertEqual(calls,list(teams[1:]))
            self.assertEqual(result["results"][0]["status"],"REUSED")
            self.assertEqual(json.loads(path.read_text()),cached(teams[0]))

    def test_stale_snapshot_refetched_and_failed_validation_preserves_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            teams=planner.group_teams(2)
            path=Path(tmp)/f"nfl_roster_{teams[0]}.json"
            path.write_text(json.dumps(cached(teams[0],age=40)))
            def invalid(team):
                if team==teams[0]:
                    return {"athletes":[]}
                return source(team)
            result=runner.collect_group(2,Path(tmp),NOW,invalid,lambda _:None)
            self.assertFalse(result["allSuccessful"])
            self.assertEqual(result["results"][0]["status"],"FAILED")
            self.assertEqual(json.loads(path.read_text()),cached(teams[0]))
            self.assertEqual(result["results"][1]["status"],"PUBLISHED")

    def test_rate_limit_stops_remaining_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            teams=planner.group_teams(3)
            def fetch(team):
                calls.append(team)
                if team==teams[1]:
                    raise runner.batch.RateLimited("HTTP 429")
                return source(team)
            result=runner.collect_group(3,Path(tmp),NOW,fetch,lambda _:None)
            self.assertEqual(calls,list(teams[:2]))
            self.assertEqual(result["results"][-1]["status"],"SKIPPED_RATE_LIMIT")
            self.assertFalse(result["allSuccessful"])

    def test_full_manifest_index_keeps_missing_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=planner.full_manifest()
            first,second=planner.group_teams(1)[:2]
            for team in (first,second):
                (Path(tmp)/manifest[team]).write_text(json.dumps(cached(team)))
            result=index.index_snapshots(tmp,NOW,manifest)
            self.assertEqual(result["coverage"]["teamsExpected"],32)
            self.assertEqual(result["coverage"]["teamsTracked"],32)
            self.assertEqual(result["coverage"]["teamsPresent"],2)
            self.assertEqual(result["coverage"]["teamsMissing"],30)
            self.assertEqual(result["coverage"]["unresolvedCrossTeamIds"],1)
            self.assertEqual(result["identityConflicts"][0]["status"],"TEAM_ID_CONFLICT_UNRESOLVED")


if __name__=="__main__":
    unittest.main()
