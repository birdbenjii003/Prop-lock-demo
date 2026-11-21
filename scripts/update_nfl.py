#!/usr/bin/env python3
"""Fetch and validate the public nflverse weekly stats release for Prop Lock."""
from __future__ import annotations
import csv
import io
from pathlib import Path
import urllib.request
import sys

YEAR = 2026
URL = f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{YEAR}.csv'
COLUMNS = ['player_display_name','player_id','recent_team','opponent_team','season','week','season_type','attempts','passing_yards','rushing_yards','receiving_yards','receptions','targets','passing_tds','rushing_tds','receiving_tds','passing_interceptions','carries']
TARGET = Path('data') / f'nfl_{YEAR}.csv'

def main() -> int:
    req=urllib.request.Request(URL,headers={'User-Agent':'PropLockPersonalResearch/1.4','Accept':'text/csv,application/octet-stream'})
    with urllib.request.urlopen(req,timeout=90) as response:
        payload=response.read(25*1024*1024+1)
    if len(payload)>25*1024*1024: raise ValueError('Source CSV too large; refusing unbounded download')
    decoded=payload.decode('utf-8-sig')
    reader=csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames: raise ValueError('Source has no header')
    required={'player_display_name','season','week'}
    if not required.issubset(reader.fieldnames): raise ValueError(f'Missing source columns: {required-set(reader.fieldnames)}; actual columns: {reader.fieldnames[:25]}')
    if not ({'team','recent_team'} & set(reader.fieldnames)): raise ValueError(f'Missing both team and recent_team columns; actual columns: {reader.fieldnames[:25]}')
    if not {'receiving_yards','rushing_yards','passing_yards'}.issubset(reader.fieldnames): raise ValueError('Missing core stat columns')
    output=io.StringIO(newline='')
    writer=csv.DictWriter(output,fieldnames=COLUMNS,lineterminator='\n')
    writer.writeheader()
    count=0;unique=set();players=set()
    for row in reader:
        if row.get('season_type') not in ('REG',None,''):continue
        if row.get('season')!=str(YEAR):continue
        name=row.get('player_display_name','').strip();team=(row.get('recent_team') or row.get('team') or '').strip();pid=(row.get('player_id') or '').strip()
        try: week=int(row.get('week',''))
        except ValueError: continue
        if not name or not team or not 1<=week<=22:continue
        identity=pid or (name+'|'+team)
        key=(identity,week)
        if key in unique:continue
        unique.add(key);players.add(identity)
        clean={k:row.get(k,'') for k in COLUMNS}
        clean['recent_team']=team
        # nflverse calls QB pass-attempt opportunities 'attempts'.
        # Preserve unavailable values as blank rather than guessing zero.
        clean['attempts']=row.get('attempts','') if 'attempts' in reader.fieldnames else ''
        writer.writerow(clean)
        count+=1
    if count<100 or len(players)<30:raise ValueError(f'Source dataset incomplete: {count} rows, {len(players)} players. Keep previous published version.')
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(output.getvalue(),encoding='utf-8')
    print(f'Wrote {TARGET}: {count} weekly rows, {len(players)} players, {TARGET.stat().st_size} bytes')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(f'NFL DATA UPDATE FAILED (existing published snapshot unchanged): {exc}',file=sys.stderr)
        sys.exit(1)
