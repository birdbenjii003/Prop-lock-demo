#!/usr/bin/env python3
"""Only link archived PFR snap counts to GSIS weekly stats through nflverse players IDs."""
from __future__ import annotations
import csv, io, sys, urllib.request
from collections import defaultdict
from pathlib import Path

SNAPS=Path('data/nfl_snap_counts_2023_2025.csv')
HISTORY=Path('data/nfl_history_2023_2025.csv')
TARGET=Path('data/nfl_verified_snaps_2023_2025.csv')
PLAYERS='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'
COLS=['player_id','season','week','team','offense_snaps','offense_pct','pfr_player_id']

def fetch_ids():
 req=urllib.request.Request(PLAYERS,headers={'User-Agent':'PropLockResearch/3.5','Accept':'text/csv'})
 with urllib.request.urlopen(req,timeout=80) as r:payload=r.read(15*1024*1024+1)
 if len(payload)>15*1024*1024:raise ValueError('Players crosswalk too large')
 return list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))

def crosswalk(players):
 if not players or not {'gsis_id','pfr_id'}.issubset(players[0]):raise ValueError('Player crosswalk schema mismatch')
 pfr_to_gsis=defaultdict(set);gsis_to_pfr=defaultdict(set)
 for p in players:
  gsis=(p.get('gsis_id') or '').strip();pfr=(p.get('pfr_id') or '').strip()
  if gsis and pfr:pfr_to_gsis[pfr].add(gsis);gsis_to_pfr[gsis].add(pfr)
 return {pfr:next(iter(gsis)) for pfr,gsis in pfr_to_gsis.items()
         if len(gsis)==1 and len(gsis_to_pfr[next(iter(gsis))])==1}

def match(snaps,history,ids):
 index=set()
 for r in history:
  pid=(r.get('player_id') or '').strip()
  if pid:index.add((pid,r.get('season'),r.get('week'),r.get('recent_team')))
 out=[];seen=set();bad=0
 for r in snaps:
  pfr=(r.get('pfr_player_id') or '').strip();gsis=ids.get(pfr)
  if not gsis:bad+=1;continue
  key=(gsis,r.get('season'),r.get('week'),r.get('team'))
  if key not in index or key in seen:bad+=1;continue
  try:snaps_num=float(r.get('offense_snaps',''));pct=float(r.get('offense_pct',''))
  except ValueError:bad+=1;continue
  if not 0<=snaps_num<=200 or not 0<=pct<=1.001:bad+=1;continue
  seen.add(key)
  out.append(dict(player_id=gsis,season=key[1],week=key[2],team=key[3],offense_snaps=str(snaps_num),offense_pct=str(pct),pfr_player_id=pfr))
 return out,bad

def main():
 if not SNAPS.exists() or SNAPS.stat().st_size==0 or not HISTORY.exists() or HISTORY.stat().st_size==0:
  print('Source archives unavailable; no crosswalk published');return
 with SNAPS.open(newline='',encoding='utf-8-sig') as f:snaps=list(csv.DictReader(f))
 with HISTORY.open(newline='',encoding='utf-8-sig') as f:history=list(csv.DictReader(f))
 ids=crosswalk(fetch_ids());rows,rejected=match(snaps,history,ids)
 if len(rows)<500 or len({r['player_id'] for r in rows})<80:
  raise ValueError(f'Insufficient safely matched participation records ({len(rows)}, rejected {rejected})')
 out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=COLS,lineterminator='\n')
 writer.writeheader();writer.writerows(rows);content=out.getvalue()
 if len(content)>8*1024*1024:raise ValueError('Matched file exceeds 8 MB')
 TARGET.parent.mkdir(parents=True,exist_ok=True);temp=TARGET.with_suffix('.tmp')
 temp.write_text(content,encoding='utf-8');temp.replace(TARGET)
 print(f'Verified {len(rows)} GSIS/PFR player-week participation matches; excluded {rejected} unmatched or ambiguous rows')

if __name__=='__main__':
 try:main()
 except Exception as e:print('Snap identity verification failed: '+str(e),file=sys.stderr);sys.exit(1)
