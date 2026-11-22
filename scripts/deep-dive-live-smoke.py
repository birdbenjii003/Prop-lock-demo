#!/usr/bin/env python3
"""Stage 4: check real GitHub Pages responses; does not simulate clicking all 16 tabs.

Run after Pages deployment, not before. Failure must not be called a validated site.
"""
import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL='https://birdbenjii003.github.io/Prop-lock-demo/'
MAX_BYTES=14*1024*1024

def fetch(base, path, max_bytes=MAX_BYTES):
    url=urllib.parse.urljoin(base.rstrip('/')+'/',path)
    request=urllib.request.Request(url,headers={'User-Agent':'PropLock-Stage4-LiveSmoke/1.0','Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=20) as response:
        data=response.read(max_bytes+1)
        if len(data)>max_bytes:
            raise ValueError('Oversized live response: '+path)
        return data.decode('utf-8-sig')

def verify_responses(responses):
    problems=[]
    html=responses['index.html']
    js=responses['scripts/deep-dive-views.js']
    for token in ('scripts/deep-dive-views.js','scripts/deep-dive-workspace.js',
                  'deepDiveSnapSummary','deepDiveQualitySummary',
                  "nflSource==='hosted'?'hosted':'unverified'"):
        if token not in html: problems.append('Missing live HTML integration: '+token)
    for token in ('DEEP_DIVE_TABS.map','ddCohortEvidenceGate','sourceContext===\'hosted\'',
                  'No certified player-specific future interval'):
        if token not in js: problems.append('Missing published renderer safeguard: '+token)
    if 'deepDiveSnapSummary' not in responses['scripts/deep-dive-snaps.js']:
        problems.append('Missing live snap renderer')
    if 'deepDiveQualitySummary' not in responses['scripts/deep-dive-quality.js']:
        problems.append('Missing live quality renderer')
    for path,years in [('data/nfl_history_2023_2025.csv',{2023,2024,2025}),
                       ('data/nfl_2026.csv',{2026})]:
        reader=csv.DictReader(io.StringIO(responses[path]))
        required={'player_id','season','week','season_type'}
        if not required.issubset(reader.fieldnames or []):
            problems.append('Invalid live NFL schema: '+path)
            continue
        found=set()
        count=0
        for row in reader:
            try:year=int(row['season'])
            except (ValueError,TypeError):continue
            if row['season_type']=='REG':
                found.add(year);count+=1
        if not years.issubset(found) or count<100:
            problems.append('Missing live season rows: '+path)
    try:
        audit=json.loads(responses['data/reports/deep_dive_calibration_audit.json'])
        if audit.get('version')!='deep-dive-cross-season-v2' or audit.get('calibration_year')!=2025 or audit.get('test_year')!=2026 or len(audit.get('groups',{}))<6:
            problems.append('Missing or outdated live calibration report')
    except (ValueError,TypeError):
        problems.append('Malformed live calibration JSON')
    return problems

PATHS=('index.html','scripts/deep-dive-views.js','scripts/deep-dive-workspace.js',
       'scripts/deep-dive-snaps.js','scripts/deep-dive-quality.js',
       'data/nfl_history_2023_2025.csv','data/nfl_2026.csv',
       'data/reports/deep_dive_calibration_audit.json')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default=DEFAULT_URL)
    args=parser.parse_args()
    responses={}
    errors=[]
    for path in PATHS:
        try:
            responses[path]=fetch(args.url,path)
            print('FETCH_OK',path,len(responses[path]),'characters')
        except (urllib.error.URLError,ValueError,TimeoutError) as err:
            errors.append(f'{path}: {err}')
    if errors:
        for e in errors:print('LIVE_BLOCKER',e,file=sys.stderr)
        return 1
    problems=verify_responses(responses)
    for problem in problems:print('LIVE_BLOCKER',problem,file=sys.stderr)
    if problems:return 1
    print('LIVE_STATIC_SMOKE_PASS: asset delivery, source gates, historical NFL files and report are present.')
    print('NOT_VERIFIED: browser interactions, device layout, end-to-end selection, and predictive validity.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
