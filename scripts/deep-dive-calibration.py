#!/usr/bin/env python3
"""Honest zero-cost cross-season Deep Dive interval audit: learn residuals in 2025, test in 2026."""
from __future__ import annotations
import csv, json, math, statistics
from collections import defaultdict
from pathlib import Path

ARCHIVE=Path('data/nfl_history_2023_2025.csv')
CURRENT=Path('data/nfl_2026.csv')
OUTPUT=Path('data/reports/deep_dive_calibration_audit.json')
FIELDS={'rushing_yards':'Rushing Yards','receiving_yards':'Receiving Yards','passing_yards':'Passing Yards','receptions':'Receptions','targets':'Targets','carries':'Carries'}
# Tests only player-stat observations that meet PRIOR-ONLY participation gates.
ACTIVITY={'rushing_yards':('carries',3),'carries':('carries',3),'receiving_yards':('targets',2),'receptions':('targets',2),'targets':('targets',2),'passing_yards':('attempts',10)}
MIN_HISTORY=5
MIN_CALIBRATION=80
MIN_TEST=50
MIN_PLAYERS=15
COVERAGE_TARGET=.80

def load(path):
    if not path.exists() or path.stat().st_size==0:return []
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if not {'player_id','season','week','season_type'}.issubset(reader.fieldnames or []):raise ValueError(f'{path}: missing identity fields')
        rows=[];seen=set()
        for row in reader:
            if row.get('season_type')!='REG':continue
            pid=(row.get('player_id') or '').strip()
            if not pid:continue
            try:year=int(row['season']);week=int(row['week'])
            except ValueError:continue
            if not 2023<=year<=2026 or not 1<=week<=22:continue
            key=(pid,year,week)
            if key in seen:raise ValueError(f'{path}: duplicate player-week {key}')
            seen.add(key);rows.append(row)
        return rows

def predict(prior):
    values=[x for x in prior if math.isfinite(x)]
    if len(values)<MIN_HISTORY:return None
    tail=values[-10:];recent=values[-5:]
    return .55*statistics.mean(tail)+.30*statistics.mean(recent)+.15*statistics.mean(values)

def quantile_higher(errors,level):
    # Split-conformal finite-sample order statistic, calculated solely from past-year errors.
    if not errors:return None
    ordered=sorted(errors)
    k=math.ceil((len(errors)+1)*level)
    return ordered[min(k,len(ordered))-1]

def build(rows):
    history=defaultdict(list)
    for row in rows:
        for col in FIELDS:
            raw=(row.get(col) or '').strip()
            if not raw:continue
            try:value=float(raw)
            except ValueError:continue
            if not math.isfinite(value):continue
            if value<(-100 if col.endswith('_yards') else 0) or value>5000:continue
            history[(row['player_id'],col)].append((int(row['season']),int(row['week']),value,row))
    output={stat:{'calibration':[],'test':[]} for stat in FIELDS}
    for (pid,stat),games in history.items():
        games.sort(key=lambda t:(t[0],t[1]))
        for i,(year,week,actual,row) in enumerate(games):
            if year not in (2025,2026):continue
            prior=[v for y,w,v,r in games[:i]]
            activity_field,minimum=ACTIVITY[stat]
            recent=games[max(0,i-5):i]
            active=0
            for _,_,_,r in recent:
                try:volume=float(r.get(activity_field) or '0')
                except ValueError:volume=0
                active+=int(math.isfinite(volume) and volume>=minimum)
            if active<2:continue
            estimate=predict(prior)
            if estimate is None:continue
            name='calibration' if year==2025 else 'test'
            output[stat][name].append({'player':pid,'season':year,'week':week,'actual':actual,'prediction':estimate,'absolute_error':abs(actual-estimate)})
    return output

def audit(rows):
    groups=build(rows)
    result={'version':'deep-dive-cross-season-v2','method':'One model fixed at 55% last10 / 30% last5 / 15% all-history; 2025 residuals set two-sided split-conformal radius; 2026 tests never influence calibration',
      'calibration_year':2025,'test_year':2026,'coverage_target':COVERAGE_TARGET,'groups':{},'status':'INSUFFICIENT_EVIDENCE',
      'caveats':['2025 calibration examples share player/team/game dependence, so i.i.d. conformal coverage is not guaranteed.',
       'Historical player inclusion is retrospective; no market line or betting probability inferred.',
       'Participation is screened using the prior five games, never current or future workload.',
       'The time-split is not a fully independent prospective experiment. Report observed coverage only after sample gates pass.']}
    eligible=0
    for stat,parts in groups.items():
        cal=parts['calibration'];test=parts['test'];radius=quantile_higher([x['absolute_error'] for x in cal],COVERAGE_TARGET) if len(cal)>=MIN_CALIBRATION else None
        distinct=len({x['player'] for x in test})
        ready=radius is not None and len(test)>=MIN_TEST and distinct>=MIN_PLAYERS
        result['groups'][stat]={'label':FIELDS[stat],'calibration_tests':len(cal),'test_games':len(test),
           'test_players':distinct,'status':'DESCRIPTIVE_COVERAGE_AUDIT' if ready else 'INSUFFICIENT_EVIDENCE',
           'conformal_radius':round(radius,3) if ready else None,
           'test_mae':round(statistics.mean(x['absolute_error'] for x in test),3) if ready else None,
           'observed_coverage':round(sum(x['absolute_error']<=radius for x in test)/len(test),4) if ready else None}
        eligible+=int(ready)
    if eligible:result['status']='PARTIAL_DESCRIPTIVE_AUDIT'
    return result

def main():
    if not ARCHIVE.exists() or ARCHIVE.stat().st_size==0:
        print('Historical archive not yet published. Calibration not claimed; no report overwritten.')
        return
    rows=load(ARCHIVE)+load(CURRENT)
    seasons={int(r['season']) for r in rows}
    if not {2023,2024,2025,2026}.issubset(seasons):
        print('Required 2023–2026 seasons are incomplete; no report overwritten.')
        return
    result=audit(rows)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Deep Dive interval audit: '+result['status'])

if __name__=='__main__':main()
