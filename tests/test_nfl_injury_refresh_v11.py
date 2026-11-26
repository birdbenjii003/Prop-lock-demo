"""No-network regression for v11 scheduled injury refresh and freshness truthfulness."""
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("injury_refresh","scripts/refresh-nfl-injuries-v11.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
UTC=dt.timezone.utc
NOW=dt.datetime(2026,11,26,15,tzinfo=UTC)

def snapshot(now, marker="same"):
    return {"schemaVersion":1,"sport":"NFL","type":"injuries","fetchedAt":mod.stamp(now),
            "count":1,"teamsReported":["ATL"],"injuries":[{"marker":marker}]}

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.health=self.root/"health.json"
        self.data=self.root/"injuries.json"
        self.calls=0

    def publish(self,path,value):
        old=json.loads(path.read_text()) if path.is_file() else None
        same=old is not None and {k:v for k,v in old.items() if k!="fetchedAt"} == \
             {k:v for k,v in value.items() if k!="fetchedAt"}
        if same:return "UNCHANGED"
        path.write_text(json.dumps(value))
        return "PUBLISHED"

    def run_once(self,now=NOW,force=False,fail=False,marker="same"):
        def fetch():
            self.calls+=1
            if fail:raise ValueError("sensitive upstream patient data")
            return {"example":"provider"}
        def norm(payload,instant,roster):
            self.assertEqual(roster,{})
            return snapshot(instant,marker)
        return mod.refresh(now,self.health,self.data,self.root,fetch,self.publish,
                           lambda folder,instant:{},norm,force=force)

    def test_first_check_writes_snapshot_and_separate_health(self):
        outcome=self.run_once()
        self.assertEqual(outcome["state"],"SUCCESS_CHANGED")
        self.assertEqual(self.calls,1)
        status=json.loads(self.health.read_text())
        self.assertEqual(status["lastSuccessfulCheckAt"],mod.stamp(NOW))
        self.assertEqual(status["lastContentChangedAt"],mod.stamp(NOW))
        self.assertEqual(status["state"],"SUCCESS_CHANGED")

    def test_cooldown_does_not_make_second_provider_request_or_touch_files(self):
        self.run_once()
        before=(self.health.read_bytes(),self.data.read_bytes())
        result=self.run_once(NOW+dt.timedelta(hours=1))
        self.assertEqual(result["state"],"SKIPPED_COOLDOWN")
        self.assertEqual(self.calls,1)
        self.assertEqual((self.health.read_bytes(),self.data.read_bytes()),before)

    def test_unchanged_check_updates_last_success_but_not_content_timestamp(self):
        self.run_once()
        before=self.data.read_bytes()
        result=self.run_once(NOW+dt.timedelta(hours=7))
        self.assertEqual(result["state"],"SUCCESS_UNCHANGED")
        self.assertEqual(self.data.read_bytes(),before)
        health=json.loads(self.health.read_text())
        self.assertEqual(health["lastSuccessfulCheckAt"],mod.stamp(NOW+dt.timedelta(hours=7)))
        self.assertEqual(health["lastContentChangedAt"],mod.stamp(NOW))
        self.assertEqual(self.calls,2)

    def test_failure_preserves_last_good_and_records_safe_error_code(self):
        self.run_once()
        before=self.data.read_bytes()
        outcome=self.run_once(NOW+dt.timedelta(hours=7),fail=True)
        self.assertEqual(outcome["state"],"FAILED")
        self.assertEqual(self.data.read_bytes(),before)
        health=json.loads(self.health.read_text())
        self.assertEqual(health["failureCode"],"INVALID_PROVIDER_SCHEMA_OR_PAYLOAD")
        self.assertNotIn("sensitive",self.health.read_text())
        self.assertEqual(health["lastSuccessfulCheckAt"],mod.stamp(NOW))

    def test_failed_check_does_not_extend_cooldown(self):
        self.run_once()
        self.run_once(NOW+dt.timedelta(hours=7),fail=True)
        self.assertEqual(self.run_once(NOW+dt.timedelta(hours=7,minutes=1))["state"],"SUCCESS_UNCHANGED")
        self.assertEqual(self.calls,3)

    def test_force_and_future_clock_handling(self):
        self.run_once()
        self.assertEqual(self.run_once(NOW+dt.timedelta(minutes=1),force=True)["state"],"SUCCESS_UNCHANGED")
        health=mod.read_health(self.health)
        self.assertFalse(mod.should_check(health,NOW))
        self.assertTrue(mod.should_check(health,NOW,force=True))

    def test_invalid_health_rechecked(self):
        self.health.write_text('{"state":"SUCCESS_CHANGED","sport":"NHL"}')
        self.assertTrue(mod.should_check(mod.read_health(self.health),NOW))

if __name__=="__main__":unittest.main()
