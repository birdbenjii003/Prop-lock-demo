#!/usr/bin/env python3
"""Stage 3 reproducible historical projection verification; never certifies future probabilities."""
from __future__ import annotations
import importlib.util
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

cal=load_module(ROOT/'scripts/deep-dive-calibration.py','dd_cal')
checks=load_module(ROOT/'scripts/deep-dive-independent-checks.py','dd_checks')
OUTPUT=ROOT/'data/reports/deep_dive_stage3_verification.json'

def inspect_archive(path):
    """Parse the actual CSV (including quoted commas); refuse incomplete source archives."""
    if not path.is_file() or path.stat().st_size==0:
        raise ValueError('Historical archive is missing or empty')
    seasons={2023:set(),2024:set(),2025:set()}
    counts={2023:0,2024:0,2025:0}
    seen=set()
    with path.open(encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(handle)
        required={'player_id','season','week','season_type','recent_team','opponent_team'}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError('Historical archive schema is missing required identity columns')
        for row in reader:
            try:
                season=int(row['season'])
                week=int(row['week'])
            except (ValueError,TypeError):
                raise ValueError('Historical archive contains invalid season/week') from None
            pid=(row['player_id'] or '').strip()
            if season not in seasons or not (1<=week<=22) or not pid or not (row['recent_team'] or '').strip() or not (row['opponent_team'] or '').strip() or row['season_type']!='REG':
                raise ValueError('Historical archive contains invalid player-game identity')
            key=(pid,season,week)
            if key in seen:
                raise ValueError('Duplicate historical player-game identity')
            seen.add(key)
            seasons[season].add(pid)
            counts[season]+=1
    if any(counts[y]<100 or len(seasons[y])<40 for y in seasons):
        raise ValueError('Historical source archive does not meet minimum per-season depth')
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'byte_size':path.stat().st_size,
            'player_games_by_season':{str(y):counts[y] for y in sorted(counts)},
            'unique_players_by_season':{str(y):len(seasons[y]) for y in sorted(seasons)},
            'identity_check':'PASSED'}

def category_diagnostics(g):
    """Only describe observed historic checks, never assert future hit probabilities."""
    coverage=g.get('observed_coverage')
    model_mae=g.get('model_mae')
    baseline_mae=g.get('last5_baseline_mae')
    shortfall=round(max(0.0,.8-coverage)*100,2) if coverage is not None else None
    gain=round(100*(baseline_mae-model_mae)/baseline_mae,2) if model_mae is not None and baseline_mae is not None and baseline_mae>0 else None
    return {'coverage_shortfall_percentage_points':shortfall,
            'historical_mae_improvement_percent':gain,
            'needs_coverage_review':shortfall is not None and shortfall>0,
            'requires_prospective_validation':True}

def verify(rows):
    evidence=checks.evaluate(rows)
    seasons=sorted({int(r['season']) for r in rows})
    complete=set((2023,2024,2025,2026)).issubset(seasons)
    report={'version':'deep-dive-stage3-verification-v1',
            'status':'REVIEW_REQUIRED' if complete else 'INSUFFICIENT_SOURCE_HISTORY',
            'seasons':seasons,'historical_only':True,'prospective_validation':False,
            'player_specific_probability_available':False,'groups':{},
            'warnings':['Data provenance and 2026 game-final status require independent verification.',
                        'Cohort observations are dependent; retrospective coverage does not certify next-game coverage.',
                        'This verification never selects bets or estimates Over/Under probability.']}
    for key,g in evidence['groups'].items():
        if not complete or g['status']!='DESCRIPTIVE_CHECKS':
            state='INSUFFICIENT_EVIDENCE'
        elif g['observed_coverage'] is None or g['observed_coverage']<.8:
            state='BELOW_COVERAGE_TARGET'
        elif g['model_beats_baseline'] is not True:
            state='BASELINE_NOT_BEATEN'
        else:
            state='HISTORICAL_CHECKS_MET'
        report['groups'][key]={
            'status':state,
            '2025_calibration_tests':g['calibration_tests'],
            '2026_evaluation_games':g['evaluation_games'],
            '2026_evaluation_players':g['evaluation_players'],
            '2026_evaluation_weeks':g['evaluation_weeks'],
            '2026_coverage':g['observed_coverage'],
            'target_coverage':.8,
            'weekly_coverage_min':g['week_coverage_min'],
            'weekly_coverage_max':g['week_coverage_max'],
            'model_mae':g['model_mae'],
            'prior_5_game_baseline_mae':g['last5_baseline_mae'],
            'model_beats_baseline':g['model_beats_baseline'],
            **category_diagnostics(g),
            'note':'Historical checks only. No independently certified player-specific future interval.'
        }
    return report

def main():
    if not cal.ARCHIVE.exists() or cal.ARCHIVE.stat().st_size==0 or not cal.CURRENT.exists() or cal.CURRENT.stat().st_size==0:
        print('STAGE3_BLOCKED: historical NFL archive is missing or empty; no real-data verification claimed.')
        return
    try:
        archive_evidence=inspect_archive(cal.ARCHIVE)
    except ValueError as error:
        print('STAGE3_BLOCKED: '+str(error))
        raise SystemExit(1) from error
    rows=cal.load(cal.ARCHIVE)+cal.load(cal.CURRENT)
    result=verify(rows)
    result['historical_archive_evidence']=archive_evidence
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Stage 3 verification:',result['status'])
    for stat,item in result['groups'].items():
        print(stat,item['status'],'coverage=',item['2026_coverage'],
              'model_mae=',item['model_mae'],'baseline_mae=',item['prior_5_game_baseline_mae'])
    if result['status']!='REVIEW_REQUIRED':raise SystemExit(1)

if __name__=='__main__':main()
