#!/usr/bin/env python3
"""Stage NFL snap counts separately. PFR IDs are NOT GSIS IDs: no implicit player join."""
from __future__ import annotations
import csv, io, math, sys, urllib.request
from pathlib import Path
YEARS=(2023,2024,2025)
URL='https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{}.csv'
FIELDS=['season','week','team','opponent','pfr_player_id','player','position','offense_snaps','offense_pct','game_id']
TARGET=Path('data/nfl_snap_counts_2023_2025.csv')
def parse(payload,year):
 reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
 cols=set(reader.fieldnames or [])
 required={'season','week','team','pfr_player_id','offense_snaps','offense_pct'}
 if not required.issubset(cols):raise ValueError(f'NFL snaps {year}: fields missing: {required-cols}')
 rows=[];seen=set()
 for row in reader:
  if row.get('game_type','REG') not in ('REG','REGULAR','regular',''):continue
  if str(row.get('season'))!=str(year):continue
  try:
   week=int(row.get('week') or '')
   snaps=float(row.get('offense_snaps') or '')
   pct=float(row.get('offense_pct') or '')
  except ValueError:continue
  if not (1<=week<=22 and math.isfinite(snaps) and 0<=snaps<=200 and math.isfinite(pct) and 0<=pct<=1.001):continue
  pid=(row.get('pfr_player_id') or '').strip();team=(row.get('team') or '').strip()
  if not pid or not team:continue
  key=(year,week,pid,team)
  if key in seen:continue
  seen.add(key)
  clean={field:(row.get(field) or '').strip() for field in FIELDS}
  clean['season']=str(year);clean['week']=str(week)
  rows.append(clean)
 if len(rows)<100:raise ValueError(f'NFL snaps {year}: too few rows')
 return rows
def main():
 rows=[]
 for year in YEARS:
  req=urllib.request.Request(URL.format(year),headers={'User-Agent':'PropLockResearch/3.3','Accept':'text/csv'})
  with urllib.request.urlopen(req,timeout=65) as response:data=response.read(16*1024*1024+1)
  if len(data)>16*1024*1024:raise ValueError('Snap source too large')
  chunk=parse(data,year);rows.extend(chunk)
  print(f'Validated raw PFR snap rows: {year}: {len(chunk)}')
 output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=FIELDS,lineterminator='\n')
 writer.writeheader();writer.writerows(rows)
 value=output.getvalue()
 if len(value)>12*1024*1024:raise ValueError('Staged snap file too large')
 TARGET.parent.mkdir(parents=True,exist_ok=True)
 tmp=TARGET.with_suffix('.tmp');tmp.write_text(value,encoding='utf-8');tmp.replace(TARGET)
 print('Snap archive staged. No PFR-to-GSIS crosswalk, so per-player snap view must remain unavailable.')
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print('Snap staging failed safely: '+str(exc),file=sys.stderr);sys.exit(1)
