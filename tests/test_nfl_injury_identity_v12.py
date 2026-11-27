"""No-network Phase 12 exact-ID injury cross-source audit regression tests."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("phase12","scripts/audit-nfl-injury-identity-v12.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW=dt.datetime(2026,11,27,11,30,tzinfo=dt.timezone.utc)

def feed(*entries, fetched_at="2026-11-27T11:00:00Z"):
    return {
        "schemaVersion":1,"sport":"NFL","type":"injuries","source":"ESPN",
        "verification":"unverified","scope":"league_injury_pilot","fetchedAt":fetched_at,
        "teamsReported":["ATL"],"count":len(entries),"injuries":list(entries)
    }

def record(espn_id, name="Example Runner", team="ATL", source="sha256:"+"a"*64):
    return {"espnId":espn_id,"sourceInjuryId":source,"displayName":name,
            "team":team,"designation":"Questionable","rosterEvidence":"TEAM_UNVERIFIED"}

class InjuryAuditTests(unittest.TestCase):
    def test_missing_id_never_matches_same_name(self):
        result=mod.audit(feed(record(None)),{"123456":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"}]},
                         {"ATL":"CURRENT"},NOW)
        self.assertEqual(result["totals"]["UNLINKED_NO_ATHLETE_ID"],1)
        self.assertEqual(result["totals"]["ID_CROSS_SOURCE_MATCH_UNVERIFIED"],0)
        self.assertNotIn("Example Runner",json.dumps(result))
        self.assertNotIn("Questionable",json.dumps(result))

    def test_exact_id_team_name_freshness_only(self):
        roster={"123456":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"}]}
        result=mod.audit(feed(record("123456")),roster,{"ATL":"CURRENT"},NOW)
        self.assertEqual(result["totals"]["ID_CROSS_SOURCE_MATCH_UNVERIFIED"],1)
        self.assertIn("unverified",result["notice"].lower())
        self.assertNotIn("verifiedPlayer",json.dumps(result))

    def test_wrong_name_and_wrong_team_block(self):
        roster={"123456":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"}]}
        bad_name=mod.audit(feed(record("123456",name="Different Runner")),roster,{"ATL":"CURRENT"},NOW)
        self.assertEqual(bad_name["totals"]["ID_NAME_MISMATCH"],1)
        bad_team=mod.audit(feed(record("123456",team="BUF")),roster,{"BUF":"CURRENT"},NOW)
        self.assertEqual(bad_team["totals"]["TEAM_ID_MISMATCH"],1)

    def test_conflicted_id_and_stale_team_block(self):
        roster={"123456":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"},
                          {"team":"BUF","freshness":"CURRENT","name":"Example Runner"}]}
        self.assertEqual(mod.audit(feed(record("123456")),roster,{"ATL":"CURRENT"},NOW)
                         ["totals"]["CROSS_TEAM_ID_CONFLICT"],1)
        only={"123456":[roster["123456"][0]]}
        self.assertEqual(mod.audit(feed(record("123456")),only,{"ATL":"STALE"},NOW)
                         ["totals"]["TEAM_ROSTER_STALE_OR_MISSING"],1)

    def test_stale_injury_stays_blocked(self):
        roster={"123456":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"}]}
        result=mod.audit(feed(record("123456"),fetched_at="2026-11-26T11:00:00Z"),roster,{"ATL":"CURRENT"},NOW)
        self.assertEqual(result["totals"]["STALE_INJURY_REPORT"],1)
        self.assertFalse(result["injuryReportCurrent"])

    def test_source_event_hash_is_not_identity(self):
        roster={"999":[{"team":"ATL","freshness":"CURRENT","name":"Example Runner"}]}
        entry=record(None,source="sha256:"+"9"*64)
        self.assertEqual(mod.audit(feed(entry),roster,{"ATL":"CURRENT"},NOW)
                         ["totals"]["UNLINKED_NO_ATHLETE_ID"],1)

    def test_bad_timestamp_duplicate_and_oversized_rejected(self):
        with self.assertRaises(ValueError):
            mod.audit(feed(record(None),fetched_at="2026-11-28T12:00:00Z"),{},{},NOW)
        item=record(None)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            mod.audit(feed(item,item),{},{},NOW)
        with self.assertRaises(ValueError):
            mod.audit(feed(record(None,source="unsafe")),{},{},NOW)

    def test_roster_manifest_missing_and_stale_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as td:
            by_id,state=mod.load_rosters(td,NOW,manifest={"ATL":"missing.json","BUF":"other.json"})
            self.assertEqual(by_id,{})
            self.assertEqual(state["ATL"],"INVALID_OR_MISSING")

    def test_bad_origin_and_future_report_are_rejected(self):
        bad=feed(record(None));bad["source"]="untrusted"
        with self.assertRaises(ValueError):
            mod.audit(bad,{},{},NOW)
        data=feed(record(None));data["injuries"][0]["team"]="FAKE"
        with self.assertRaises(ValueError):
            mod.audit(data,{},{},NOW)

if __name__=="__main__":
    unittest.main()
