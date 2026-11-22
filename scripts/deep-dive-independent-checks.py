#!/usr/bin/env python3
"""Additional descriptive checks for Deep Dive 2025→2026 cohort audit.

No claim of prospective independence or calibrated player-level probability.
"""
import importlib.util
import math
import statistics
from collections import defaultdict
from pathlib import Path

PATH=Path(__file__).with_name('deep-dive-calibration.py')
spec=importlib.util.spec_from_file_location('deep_dive_calibration',PATH)
model=importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

def evaluate(rows):
    groups=model.build(rows)
    report={'version':'deep-dive-independent-checks-v1',
            'status':'INSUFFICIENT_EVIDENCE','calibration_year':2025,'evaluation_year':2026,
            'scope':'Retrospective 2026 out-of-time cohort checks; not independent prospective validation',
            'groups':{},
            'limitations':['Player observations are dependent across games and players on the same teams.',
              'The 2026 source provenance and final game results must be independently verified.',
              'Model and dataset were not registered before the evaluation period.',
              'Baseline and coverage comparisons do not establish a bet probability.']}
    eligible=0
    # Separate baseline: prior five game mean, computed strictly prior-only.
    prior=defaultdict(list)
    ordered=sorted(rows,key=lambda r:(int(r['season']),int(r['week'])))
    baseline={}
    for r in ordered:
        pid=r.get('player_id')
        for stat in model.FIELDS:
            raw=(r.get(stat) or '').strip()
            try:value=float(raw)
            except (ValueError,TypeError):continue
            if not math.isfinite(value):continue
            key=(pid,stat,int(r['season']),int(r['week']))
            past=prior[(pid,stat)]
            if len(past)>=model.MIN_HISTORY:
                baseline[key]=statistics.mean(past[-5:])
            past.append(value)
    for stat,parts in groups.items():
        cal=parts['calibration'];test=parts['test']
        players=len({r['player'] for r in test})
        ready=len(cal)>=model.MIN_CALIBRATION and len(test)>=model.MIN_TEST and players>=model.MIN_PLAYERS
        radius=model.quantile_higher([r['absolute_error'] for r in cal],model.COVERAGE_TARGET) if ready else None
        per_week=defaultdict(list)
        base_errors=[]
        for r in test:
            per_week[r['week']].append(r)
            key=(r['player'],stat,r['season'],r['week'])
            if key in baseline:base_errors.append(abs(r['actual']-baseline[key]))
        result={'status':'DESCRIPTIVE_CHECKS' if ready else 'INSUFFICIENT_EVIDENCE',
                'calibration_tests':len(cal),'evaluation_games':len(test),
                'evaluation_players':players,'evaluation_weeks':len(per_week),
                'radius':round(radius,3) if ready else None,
                'model_mae':round(statistics.mean(r['absolute_error'] for r in test),3) if ready else None,
                'last5_baseline_mae':round(statistics.mean(base_errors),3) if ready and len(base_errors)==len(test) else None,
                'baseline_comparable_games':len(base_errors),
                'model_beats_baseline':None,'observed_coverage':None,
                'week_coverage_min':None,'week_coverage_max':None}
        if ready:
            coverage=[sum(r['absolute_error']<=radius for r in games)/len(games) for games in per_week.values()]
            result['observed_coverage']=round(sum(r['absolute_error']<=radius for r in test)/len(test),4)
            result['week_coverage_min']=round(min(coverage),4)
            result['week_coverage_max']=round(max(coverage),4)
            if result['last5_baseline_mae'] is not None:
                result['model_beats_baseline']=result['model_mae']<result['last5_baseline_mae']
            eligible+=1
        report['groups'][stat]=result
    if eligible:report['status']='PARTIAL_DESCRIPTIVE_CHECKS'
    return report

if __name__=='__main__':
    import json
    if not model.ARCHIVE.exists() or not model.CURRENT.exists():
        print('Historical files unavailable; no independent validation claimed.')
    else:
        data=model.load(model.ARCHIVE)+model.load(model.CURRENT)
        result=evaluate(data)
        dest=Path('data/reports/deep_dive_independent_checks.json')
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(result['status'])
