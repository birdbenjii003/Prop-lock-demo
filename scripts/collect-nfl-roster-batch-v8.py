#!/usr/bin/env python3
"""Run one manually selected, bounded NFL roster group and rebuild the coverage index.

Never auto-advance to another group. No provider requests for recent valid data.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import time
import urllib.error

ROOT=Path(__file__).resolve().parent.parent
def load_module(name,rel):
    spec=importlib.util.spec_from_file_location(name,ROOT/rel)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

planner=load_module("nfl_roster_plan","scripts/nfl-roster-plan.py")
batch=load_module("nfl_roster_fetch","scripts/collect-nfl-roster-batch.py")
indexer=load_module("nfl_roster_index","scripts/build-nfl-roster-index.py")
UTC=dt.timezone.utc

def run_group(folder,group,now,fetcher=None,sleep=time.sleep):
    plan=planner.plan_batch(folder,group,now)
    # Use the exact allowlist for the selected group. Never request other teams.
    batch.BATCH=tuple(plan["selectedTeams"])
    fetcher=fetcher or batch.fetch_team
    results=[]
    calls=0
    blocked=False
    for item in plan["decisions"]:
        team=item["team"]
        if item["action"]=="REUSE":
            results.append({"team":team,"status":"REUSED","reason":"FRESH_SNAPSHOT"})
            continue
        if blocked:
            results.append({"team":team,"status":"SKIPPED_RATE_LIMIT"})
            continue
        if calls:
            sleep(batch.MIN_DELAY_SECONDS)
        calls+=1
        try:
            data=batch.pilot.normalize(fetcher(team),team,now)
            data["scope"]="controlled_batch"
            data["notice"]="Third-party roster, no verified current team assignment, availability or eligibility."
            batch.pilot.publish(Path(folder)/f"nfl_roster_{team}.json",data)
            results.append({"team":team,"status":"PUBLISHED","count":data["count"]})
        except batch.RateLimited as exc:
            blocked=True
            results.append({"team":team,"status":"RATE_LIMITED","reason":str(exc)})
        except (OSError,ValueError,RuntimeError,urllib.error.URLError,TimeoutError,TypeError,json.JSONDecodeError) as exc:
            results.append({"team":team,"status":"FAILED","reason":str(exc)[:160]})
    coverage=indexer.index_snapshots(folder,now,manifest=planner.full_manifest())
    report={"schemaVersion":1,"group":group,"selectedTeams":plan["selectedTeams"],
        "plannedRequests":plan["requestsPlanned"],"actualRequests":calls,
        "at":now.isoformat().replace("+00:00","Z"),"results":results,
        "allSuccessful":all(x["status"] in ("PUBLISHED","REUSED") for x in results),
        "coverage":coverage["coverage"]}
    return report,coverage

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--group",type=int,required=True)
    p.add_argument("--data-dir",default="data/live")
    p.add_argument("--report",default="test-results/nfl-roster-v8-report.json")
    p.add_argument("--fixture-dir",help="Offline tests only, not used by production workflow")
    args=p.parse_args()
    # Validate group before any network attempt.
    planner.group_teams(args.group)
    now=dt.datetime.now(UTC).replace(microsecond=0)
    fetcher=None
    if args.fixture_dir:
        def fixture(team):
            raw=(Path(args.fixture_dir)/f"{team}.json").read_bytes()
            if len(raw)>batch.pilot.MAX_BYTES:raise ValueError("Fixture too large")
            return json.loads(raw)
        fetcher=fixture
    report,coverage=run_group(args.data_dir,args.group,now,fetcher=fetcher,
                               sleep=(lambda _:None) if args.fixture_dir else time.sleep)
    batch.pilot.publish(Path(args.report),report)
    batch.pilot.publish(Path(args.data_dir)/"nfl_roster_index.json",coverage)
    print(json.dumps({"group":args.group,"results":report["results"],"coverage":report["coverage"]}))
    # Partial failures are surfaced by workflow after successful files are committed.

if __name__=="__main__":
    main()
