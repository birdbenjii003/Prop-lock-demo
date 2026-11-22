#!/usr/bin/env python3
"""Stage 3 reproducible historical projection verification; never certifies future probabilities."""
from __future__ import annotations
import importlib.util
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
            'note':'Historical checks only. No independently certified player-specific future interval.'
        }
    return report

def main():
    if not cal.ARCHIVE.exists() or not cal.CURRENT.exists():
        print('Missing historical source files; no verification report generated.')
        raise SystemExit(1)
    rows=cal.load(cal.ARCHIVE)+cal.load(cal.CURRENT)
    result=verify(rows)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Stage 3 verification:',result['status'])
    for stat,item in result['groups'].items():
        print(stat,item['status'],'coverage=',item['2026_coverage'],
              'model_mae=',item['model_mae'],'baseline_mae=',item['prior_5_game_baseline_mae'])
    if result['status']!='REVIEW_REQUIRED':raise SystemExit(1)

if __name__=='__main__':main()
