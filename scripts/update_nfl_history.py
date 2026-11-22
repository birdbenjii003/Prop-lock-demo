#!/usr/bin/env python3
"""Build a small multi-season nflverse player-stat archive; fail closed on missing seasons."""
from __future__ import annotations
import csv
import io
import os
from pathlib import Path
import urllib.request

YEARS=(2023,2024,2025)
BASE='https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{}.csv'
COLS=['player_display_name','player_id','recent_team','opponent_team','season','week','season_type','attempts','passing_yards','rushing_yards','receiving_yards','receptions','targets','passing_tds','rushing_tds','receiving_tds','passing_interceptions','carries']
TARGET=Path('data/nfl_history_2023_2025.csv')
MAX_DOWNLOAD=18*1024*1024

def parse_season(content, year):
    reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    cols=set(reader.fieldnames or [])
    required={'player_display_name','player_id','season','week','season_type','receiving_yards','rushing_yards','passing_yards'}
    if not required.issubset(cols) or not ({'recent_team','team'} & cols) or 'opponent_team' not in cols:
        raise ValueError(f'NFL {year}: missing required source fields; no archive published')
    rows=[]; seen=set();players=set()
    for entry in reader:
        if entry.get('season')!=str(year) or entry.get('season_type')!='REG':continue
        name=(entry.get('player_display_name') or '').strip()
        pid=(entry.get('player_id') or '').strip()
        team=(entry.get('recent_team') or entry.get('team') or '').strip()
        opp=(entry.get('opponent_team') or '').strip()
        try:week=int(entry.get('week') or '')
        except ValueError:continue
        if not pid or not name or not team or not opp or not 1<=week<=22:continue
        key=(pid,year,week)
        if key in seen:continue
        seen.add(key);players.add(pid)
        clean={k:(entry.get(k) or '').strip() for k in COLS}
        clean.update({'recent_team':team,'opponent_team':opp,'season':str(year),'week':str(week),'season_type':'REG'})
        for field in COLS[7:]:
            if clean[field]:
                try:
                    value=float(clean[field])
                    if not 0<=value<=5000:raise ValueError('out of range')
                except ValueError:raise ValueError(f'Invalid {field} for {year} week {week}')
        rows.append(clean)
    if len(rows)<100 or len(players)<40:
        raise ValueError(f'NFL {year}: insufficient data ({len(rows)} rows, {len(players)} players)')
    return rows

def main():
    all_rows=[]
    for year in YEARS:
        req=urllib.request.Request(BASE.format(year),headers={'User-Agent':'PropLockResearch/3.3','Accept':'text/csv'})
        with urllib.request.urlopen(req,timeout=60) as response:
            payload=response.read(MAX_DOWNLOAD+1)
        if len(payload)>MAX_DOWNLOAD:raise ValueError(f'NFL {year}: exceeds bounded download limit')
        chunk=parse_season(payload,year)
        all_rows.extend(chunk)
        print(f'Validated {year}: {len(chunk)} regular-season player-games')
    output=io.StringIO(newline='')
    writer=csv.DictWriter(output,fieldnames=COLS,lineterminator='\n')
    writer.writeheader();writer.writerows(all_rows)
    raw=output.getvalue()
    if len(raw)>12*1024*1024:raise ValueError('Archive exceeds 12 MB static file cap')
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    tmp=TARGET.with_suffix('.tmp');tmp.write_text(raw,encoding='utf-8');tmp.replace(TARGET)
    print(f'Published {len(all_rows)} player-week records across {YEARS}')

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('History download failed safely; published archive unchanged: '+str(e),file=__import__('sys').stderr)
        raise SystemExit(1)
