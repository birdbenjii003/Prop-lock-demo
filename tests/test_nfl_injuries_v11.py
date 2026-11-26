"""No-network regression tests for the optional injury feed pilot."""
import datetime as dt
import importlib.util
import json
import gzip
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("injury_v11","scripts/collect-nfl-injuries-v11.py")
inj=importlib.util.module_from_spec(spec)
spec.loader.exec_module(inj)
NOW=dt.datetime(2026,11,25,14,tzinfo=dt.timezone.utc)

def source():
    return {"injuries":[
        {"team":{"abbreviation":"ATL"},"injuries":[
            {"athlete":{"id":"123456","displayName":"Example Athlete"},"status":"Questionable"}]},
        {"team":{"abbreviation":"BUF"},"injuries":[
            {"athlete":{"id":"777777","displayName":"Another Athlete"},"status":{"name":"Out"}}]}
    ]}

class InjuryPilotTests(unittest.TestCase):
    def test_valid_fixture_and_id_evidence(self):
        result=inj.normalized(source(),NOW,{"123456":["ATL"],"777777":["BUF","KC"]})
        self.assertEqual(result["count"],2)
        self.assertEqual(result["verification"],"unverified")
        self.assertEqual(result["injuries"][0]["rosterEvidence"],"ROSTER_MATCH")
        self.assertEqual(result["injuries"][1]["rosterEvidence"],"ROSTER_CONFLICT")
        self.assertEqual(result["injuries"][1]["designation"],"Out")
        self.assertEqual(result["teamsReported"],["ATL","BUF"])

    def test_schema_fail_closed_and_no_health_assumptions(self):
        for invalid in ({}, {"injuries":[]}, {"injuries":[{}]},
                        {"injuries":[{"team":{"abbreviation":"ATL"}}]}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    inj.normalized(invalid,NOW,{})
        result=inj.normalized({"injuries":[{"team":{"abbreviation":"ATL"},"injuries":[]}]},NOW,{})
        self.assertEqual(result["count"],0)
        self.assertIn("omission does not mean healthy",result["notice"])

    def test_duplicate_and_unmapped_team_rejected(self):
        src=source()
        src["injuries"].append(src["injuries"][0])
        with self.assertRaises(ValueError):inj.normalized(src,NOW,{})
        src=source()
        src["injuries"][1]["team"]["abbreviation"]="NONSENSE"
        with self.assertRaises(ValueError):inj.normalized(src,NOW,{})

    def test_unknown_or_ambiguous_roster_evidence_never_certifies_team(self):
        result=inj.normalized(source(),NOW,{"123456":["KC"],"777777":["SEA"]})
        self.assertEqual([x["rosterEvidence"] for x in result["injuries"]],
                         ["TEAM_UNVERIFIED","TEAM_UNVERIFIED"])
        self.assertTrue(all("verifiedTeam" not in x for x in result["injuries"]))

    def test_unchanged_content_does_not_rewrite_and_failure_preserves_old(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"injuries.json"
            data=inj.normalized(source(),NOW,{})
            self.assertEqual(inj.publish_if_changed(path,data),"PUBLISHED")
            original=path.read_bytes()
            later=inj.normalized(source(),NOW+dt.timedelta(minutes=15),{})
            self.assertEqual(inj.publish_if_changed(path,later),"UNCHANGED")
            self.assertEqual(path.read_bytes(),original)
            with self.assertRaises(ValueError):
                invalid=inj.normalized({},NOW+dt.timedelta(minutes=20),{})
                inj.publish_if_changed(path,invalid)
            self.assertEqual(path.read_bytes(),original)

    def test_expired_roster_not_used_for_identity_matching(self):
        with tempfile.TemporaryDirectory() as td:
            team="ATL"
            file=Path(td)/"nfl_roster_pilot_ATL.json"
            earlier=NOW-dt.timedelta(hours=40)
            file.write_text(json.dumps({"schemaVersion":1,"sport":"NFL","type":"roster",
             "source":"ESPN","verification":"unverified","scope":"single_team_pilot",
             "team":"ATL","fetchedAt":earlier.isoformat().replace("+00:00","Z"),
             "count":1,"athletes":[{"espnId":"123456","displayName":"Example Athlete"}]}))
            ids=inj.roster_evidence(td,NOW)
            self.assertNotIn("123456",ids)
            fresh=json.loads(file.read_text())
            fresh["fetchedAt"]=NOW.isoformat().replace("+00:00","Z")
            file.write_text(json.dumps(fresh))
            self.assertEqual(inj.roster_evidence(td,NOW)["123456"],["ATL"])

    def test_bounded_plain_and_gzip_responses(self):
        class Response:
            def __init__(self, blob, encoding=""):
                self.stream=io.BytesIO(blob)
                self.headers={"Content-Encoding":encoding,"Content-Length":str(len(blob))}
            def read(self,n):
                return self.stream.read(n)
        sample=json.dumps(source()).encode()
        self.assertEqual(inj.decode_bounded_response(Response(sample)),source())
        packed=gzip.compress(sample)
        self.assertEqual(inj.decode_bounded_response(Response(packed,"gzip")),source())
        with self.assertRaises(ValueError):
            inj.decode_bounded_response(Response(b"not-gzip","gzip"))

    def test_wire_size_and_gzip_expansion_fail_closed(self):
        class Response:
            def __init__(self, blob, encoding=""):
                self.stream=io.BytesIO(blob)
                self.headers={"Content-Encoding":encoding,"Content-Length":str(len(blob))}
            def read(self,n):
                return self.stream.read(n)
        with self.assertRaisesRegex(ValueError,"wire"):
            inj.decode_bounded_response(Response(b"z"*(inj.MAX_WIRE_BYTES+1)))
        expanded=gzip.compress(b"x"*(inj.MAX_BYTES+1))
        with self.assertRaisesRegex(ValueError,"Decoded"):
            inj.decode_bounded_response(Response(expanded,"gzip"))
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            inj.decode_bounded_response(Response(b"{}","br"))

    def test_unknown_live_group_shape_is_diagnosed_without_player_details(self):
        payload={"injuries":[{"team":{"id":"1234","name":"Unmapped Club"},
            "items":[{"athlete":{"id":"98765","displayName":"Private Example"}}]}]}
        with self.assertRaisesRegex(ValueError,"teamKeys=.*id.*name") as caught:
            inj.normalized(payload,NOW,{})
        message=str(caught.exception)
        self.assertIn("injuriesType=NoneType",message)
        self.assertNotIn("98765",message)
        self.assertNotIn("Private Example",message)
        self.assertNotIn("Unmapped Club",message)

    def test_malformed_group_shape_has_index_and_no_data_dump(self):
        with self.assertRaisesRegex(ValueError,"group=0,type=str"):
            inj.normalized({"injuries":["unsupported"]},NOW,{})

    def test_observed_flat_espn_team_group_format(self):
        payload={"injuries":[
            {"id":"1","displayName":"Atlanta Falcons","injuries":[
                {"athlete":{"id":"123456","displayName":"Example Athlete"},"status":"Out"}]},
            {"id":"2","displayName":"Buffalo Bills","injuries":[]}
        ]}
        result=inj.normalized(payload,NOW,{"123456":["ATL"]})
        self.assertEqual(result["teamsReported"],["ATL","BUF"])
        self.assertEqual(result["count"],1)
        self.assertEqual(result["injuries"][0]["team"],"ATL")
        self.assertEqual(result["injuries"][0]["rosterEvidence"],"ROSTER_MATCH")

    def test_flat_group_unknown_or_mismatched_team_is_rejected(self):
        for item in [
            {"id":"999","displayName":"Unknown Club","injuries":[]},
            {"id":"1","displayName":"Buffalo Bills","injuries":[]},
            {"id":"1","injuries":[]},
            {"id":True,"displayName":"Atlanta Falcons","injuries":[]}
        ]:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    inj.normalized({"injuries":[item]},NOW,{})

    def test_nested_group_numeric_id_must_agree_with_abbreviation(self):
        data={"injuries":[{"team":{"id":"2","abbreviation":"ATL"},"injuries":[]}]}
        with self.assertRaises(ValueError):
            inj.normalized(data,NOW,{})

    def test_injury_entry_schema_diagnostic_reports_keys_without_values(self):
        payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
          {"athlete":{"uid":"secret-id","name":"Private Player"},
           "status":{"code":"PRIVATE_MEDICAL_STATUS"},
           "details":"PRIVATE_HEALTH_DETAIL"}]}]}
        with self.assertRaisesRegex(ValueError,"Injury entry lacks valid name, status or source identity") as caught:
            inj.normalized(payload,NOW,{})
        message=str(caught.exception)
        self.assertIn("group=0,entry=0",message)
        self.assertIn("athleteKeys=['name', 'uid']",message)
        self.assertIn("statusKeys=['code']",message)
        for private in ("secret-id","Private Player","PRIVATE_MEDICAL_STATUS","PRIVATE_HEALTH_DETAIL"):
            self.assertNotIn(private,message)

    def test_missing_status_reports_structure_without_guessing(self):
        payload={"injuries":[{"id":"2","displayName":"Buffalo Bills","injuries":[
          {"athlete":{"id":"123456","displayName":"Example Athlete"},"status":None}]}]}
        with self.assertRaisesRegex(ValueError,"statusType=NoneType"):
            inj.normalized(payload,NOW,{})

    def test_observed_athlete_without_id_kept_as_unlinked_injury_evidence(self):
        payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
          {"id":"456789","athlete":{"displayName":"Example Runner","firstName":"Example",
            "lastName":"Runner","shortName":"E. Runner","team":{"id":"1"},
            "status":{},"position":{"abbreviation":"RB"},"links":[],"notes":[],
            "headshot":{}},
           "date":"2026-11-25T12:00Z","status":"Questionable","type":{}}
        ]}]}
        result=inj.normalized(payload,NOW,{"456789":["ATL"]})
        self.assertEqual(result["count"],1)
        record=result["injuries"][0]
        self.assertIsNone(record["espnId"])
        self.assertEqual(record["sourceInjuryId"],"sha256:"+hashlib.sha256(b"456789").hexdigest())
        self.assertEqual(record["team"],"ATL")
        self.assertEqual(record["designation"],"Questionable")
        self.assertEqual(record["rosterEvidence"],"TEAM_UNVERIFIED")
        self.assertNotIn("verifiedTeam",record)

    def test_injury_event_id_never_substitutes_for_athlete_id(self):
        payload={"injuries":[{"id":"2","displayName":"Buffalo Bills","injuries":[
          {"id":"123456","athlete":{"displayName":"Example Player"},"status":"Out"}]}]}
        record=inj.normalized(payload,NOW,{"123456":["BUF"]})["injuries"][0]
        self.assertIsNone(record["espnId"])
        self.assertEqual(record["rosterEvidence"],"TEAM_UNVERIFIED")

    def test_missing_both_ids_stays_invalid_and_preserves_prior_data(self):
        payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
          {"athlete":{"displayName":"Example Player"},"status":"Out"}]}]}
        with self.assertRaisesRegex(ValueError,"source identity"):
            inj.normalized(payload,NOW,{})
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"nfl_injuries.json"
            path.write_bytes(b'{"lastGood":"unchanged"}')
            before=path.read_bytes()
            with self.assertRaises(ValueError):
                candidate=inj.normalized(payload,NOW,{})
                inj.publish_if_changed(path,candidate)
            self.assertEqual(path.read_bytes(),before)

    def test_duplicate_injury_event_id_rejected(self):
        entry={"id":"998877","athlete":{"displayName":"Example Player"},"status":"Out"}
        payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[entry,dict(entry)]}]}
        with self.assertRaisesRegex(ValueError,"Repeated injury"):
            inj.normalized(payload,NOW,{})

    def test_identified_athlete_without_injury_event_id_still_supported(self):
        result=inj.normalized(source(),NOW,{"123456":["ATL"]})
        self.assertEqual(result["injuries"][0]["espnId"],"123456")
        self.assertIsNone(result["injuries"][0]["sourceInjuryId"])

    def test_alphanumeric_and_uuid_like_event_ids_remain_unlinked(self):
        for event_id in ("NFL-2026:ATL.22","c14f832e-3f58-4ac5-a019-0ce6d8456923"):
            with self.subTest(event_id=event_id):
                payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
                    {"id":event_id,"athlete":{"displayName":"Example Runner"},"status":"Questionable"}]}]}
                result=inj.normalized(payload,NOW,{event_id:["ATL"]})
                record=result["injuries"][0]
                self.assertEqual(record["sourceInjuryId"],"sha256:"+hashlib.sha256(event_id.encode()).hexdigest())
                self.assertIsNone(record["espnId"])
                self.assertEqual(record["rosterEvidence"],"TEAM_UNVERIFIED")

    def test_unusual_printable_event_ids_are_hashed_not_assumed_to_be_athlete_ids(self):
        for event_id in ("A/B|C?D!", "event id", "<script>", "🚫"):
            with self.subTest(event_id=event_id):
                payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
                    {"id":event_id,"athlete":{"displayName":"Example Runner"},"status":"Out"}]}]}
                record=inj.normalized(payload,NOW,{})["injuries"][0]
                self.assertEqual(record["sourceInjuryId"],
                                 "sha256:"+hashlib.sha256(event_id.encode()).hexdigest())
                self.assertIsNone(record["espnId"])
                self.assertNotIn(event_id, str(record))

    def test_empty_control_or_oversized_event_ids_still_fail_closed(self):
        for event_id in ("", chr(10), chr(0), "X"*129):
            with self.subTest(event_id=event_id):
                payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[
                    {"id":event_id,"athlete":{"displayName":"Example Runner"},"status":"Out"}]}]}
                with self.assertRaises(ValueError):
                    inj.normalized(payload,NOW,{})

    def test_duplicate_opaque_event_ids_are_rejected(self):
        injury={"id":"A-123:report","athlete":{"displayName":"Example Runner"},"status":"Out"}
        payload={"injuries":[{"id":"1","displayName":"Atlanta Falcons","injuries":[injury,dict(injury)]}]}
        with self.assertRaisesRegex(ValueError,"Repeated injury"):
            inj.normalized(payload,NOW,{})

    def test_size_and_count_bounds(self):
        src=source()
        src["injuries"]*=30
        with self.assertRaises(ValueError):inj.normalized(src,NOW,{})

if __name__=="__main__":unittest.main()
