#!/usr/bin/env python3
"""Manual second three-team roster batch. Reuses validated v6 safety controls."""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location("roster_batch", ROOT/"scripts/collect-nfl-roster-batch.py")
batch=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)
BATCH_TEAMS=("BAL","DET","SF")


def collect_new_batch(fetcher, publish_dir, now, sleep):
    # The v6 collector's team URL, sequencing and 429 stop behavior consult BATCH.
    # Only this imported module instance is modified, never the existing v6 workflow.
    batch.BATCH=BATCH_TEAMS
    return batch.collect(fetcher,publish_dir,now,sleep=sleep)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixture-dir",help="Local test data only")
    parser.add_argument("--out-dir",default="data/live")
    parser.add_argument("--report",default="test-results/nfl-roster-batch-v7-report.json")
    args=parser.parse_args()
    now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if args.fixture_dir:
        def fetcher(team):
            return json.loads((Path(args.fixture_dir)/f"{team}.json").read_text())
        sleeper=lambda _:None
    else:
        fetcher=batch.fetch_team
        sleeper=batch.time.sleep
    result=collect_new_batch(fetcher,Path(args.out_dir),now,sleeper)
    batch.pilot.publish(Path(args.report),result)
    print(json.dumps({"allSuccessful":result["allSuccessful"],"results":result["results"]}))


if __name__=="__main__":
    main()
