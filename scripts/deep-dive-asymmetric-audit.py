#!/usr/bin/env python3
"""Experimental asymmetric NFL ranges, frozen on 2025 and evaluated in 2026.

Strictly diagnostic. Never replaces the existing symmetric Deep Dive interval.
The signed residual is actual minus forecast. Separate 10th and 90th percentile
offsets permit an asymmetric interval with the same nominal 80% target.
"""
from __future__ import annotations
import importlib.util
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ddcal',ROOT/'scripts/deep-dive-calibration.py')
cal=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)
OUTPUT=ROOT/'data/reports/deep_dive_asymmetric_range_audit.json'

def frozen_offset(values, tail):
    """Conservative order statistics with no interpolation or evaluation leakage."""
    if not values:
        return None
    ordered=sorted(values)
    n=len(ordered)
    rank=(math.floor((n+1)*.10) if tail=='lower' else math.ceil((n+1)*.90))
    return ordered[max(0,min(n-1,rank-1))]

def compare(calibration,evaluation):
    if len(calibration)<cal.MIN_CALIBRATION or len(evaluation)<cal.MIN_TEST or len({x['player'] for x in evaluation})<cal.MIN_PLAYERS:
        return {'status':'INSUFFICIENT_EVIDENCE','calibration_games':len(calibration),'evaluation_games':len(evaluation)}
    signed=[r['actual']-r['prediction'] for r in calibration]
    lower=frozen_offset(signed,'lower')
    upper=frozen_offset(signed,'upper')
    radius=cal.quantile_higher([abs(x) for x in signed],cal.COVERAGE_TARGET)
    if lower is None or upper is None or lower>upper:
        return {'status':'INVALID_CALIBRATION'}
    asymmetric_covered=sum(lower<=r['actual']-r['prediction']<=upper for r in evaluation)
    symmetric_covered=sum(abs(r['actual']-r['prediction'])<=radius for r in evaluation)
    above=sum(r['actual']-r['prediction']>upper for r in evaluation)
    below=sum(r['actual']-r['prediction']<lower for r in evaluation)
    n=len(evaluation)
    return {'status':'RETROSPECTIVE_COMPARISON',
            'calibration_games':len(calibration),'evaluation_games':n,
            'lower_offset':round(lower,4),'upper_offset':round(upper,4),
            'symmetric_radius':round(radius,4),
            'asymmetric_width':round(upper-lower,4),'symmetric_width':round(2*radius,4),
            'asymmetric_coverage':round(asymmetric_covered/n,4),
            'symmetric_coverage':round(symmetric_covered/n,4),
            'asymmetric_misses_above':above,'asymmetric_misses_below':below,
            'asymmetric_covered':asymmetric_covered,
            'symmetric_covered':symmetric_covered,
            'target_coverage':cal.COVERAGE_TARGET,
            'decision':'RESEARCH_ONLY_NO_MODEL_CHANGE'}

def evaluate(rows):
    groups=cal.build(rows)
    result={'version':'deep-dive-asymmetric-audit-v1',
            'calibration_year':2025,'evaluation_year':2026,
            'status':'EXPERIMENTAL_NOT_APPROVED',
            'model_changed':False,'display_changed':False,
            'player_specific_probability_available':False,'groups':{},
            'limitations':['The 2026 cohort has already been examined; it is not an untouched confirmation sample.',
             '2025 calibration observations are dependent; no distribution-free guarantee applies to this retrospective year split.',
             'Comparing widths and coverage is descriptive, not a selection rule for deployment.',
             'A later untouched evaluation period is required before replacing any production intervals.']}
    for stat,parts in groups.items():
        result['groups'][stat]=compare(parts['calibration'],parts['test'])
    return result

def main():
    if not cal.ARCHIVE.exists() or cal.ARCHIVE.stat().st_size==0 or not cal.CURRENT.exists() or cal.CURRENT.stat().st_size==0:
        raise SystemExit('Missing required NFL source archives; no asymmetric audit generated')
    rows=cal.load(cal.ARCHIVE)+cal.load(cal.CURRENT)
    if not {2023,2024,2025,2026}.issubset({int(x['season']) for x in rows}):
        raise SystemExit('Incomplete NFL season coverage; no asymmetric audit generated')
    report=evaluate(rows)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    for stat,row in report['groups'].items():
        print(stat,row['status'],'symmetric=',row.get('symmetric_coverage'),
              'asymmetric=',row.get('asymmetric_coverage'))
    print('EXPERIMENTAL_NOT_APPROVED; no production model changes')

if __name__=='__main__':
    main()
