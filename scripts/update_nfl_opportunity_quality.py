#!/usr/bin/env python3
"""Generate bounded historical player opportunity-quality summaries from free nflverse play-by-play."""
from __future__ import annotations
import csv,gzip,io,sys,urllib.request,math
from collections import defaultdict
from pathlib import Path
YEARS=(2023,2024,2025,2026)
URL='https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.csv.gz'
TARGET=Path('data/nfl_opportunity_quality_2023_2026.csv')
COLS=['player_id','season','week','team','rush_attempts','red_zone_carries','goal_line_carries','targets','red_zone_targets','deep_targets','air_yards']
MAX_BYTES=28*1024*1024
def count(source):
 out=defaultdict(lambda:{c:0 for c in COLS[4:]})
 count_rows=0
 for row in source:
  if (row.get('season_type') or '')!='REG':continue
  try:season=int(row['season']);week=int(row['week'])
  except (ValueError,TypeError,KeyError):continue
  if season not in YEARS or not 1<=week<=22:continue
  team=(row.get('posteam') or '').strip()
  if not team:continue
  try:yard=float(row.get('yardline_100') or 'nan')
  except ValueError:yard=float('nan')
  if not math.isfinite(yard):yard=float('nan')
  try:air=float(row.get('air_yards') or 'nan')
  except ValueError:air=float('nan')
  if (row.get('rush_attempt') or '') in ('1','1.0'):
   pid=(row.get('rusher_player_id') or '').strip()
   if pid:
    x=out[(pid,season,week,team)];x['rush_attempts']+=1
    if yard<=20:x['red_zone_carries']+=1
    if yard<=5:x['goal_line_carries']+=1
  if (row.get('pass_attempt') or '') in ('1','1.0'):
   pid=(row.get('receiver_player_id') or '').strip()
   if pid:
    x=out[(pid,season,week,team)];x['targets']+=1
    if yard<=20:x['red_zone_targets']+=1
    if math.isfinite(air):
     x['air_yards']+=air
     if air>=20:x['deep_targets']+=1
  count_rows+=1
 return out,count_rows
def download_year(year):
 req=urllib.request.Request(URL.format(year),headers={'User-Agent':'PropLock-DeepDive/3.8','Accept':'application/gzip'})
 with urllib.request.urlopen(req,timeout=90) as r:
  compressed=r.read(MAX_BYTES+1)
 if len(compressed)>MAX_BYTES:raise ValueError(f'{year}: compressed play-by-play exceeds cap')
 with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as g:
  text=io.TextIOWrapper(g,encoding='utf-8-sig',newline='')
  reader=csv.DictReader(text)
  required={'season','season_type','week','posteam','rush_attempt','rusher_player_id','pass_attempt','receiver_player_id','yardline_100','air_yards'}
  if not required.issubset(reader.fieldnames or []):raise ValueError(f'{year}: unexpected PBP field schema')
  data,total=count(reader)
 if total<1000:raise ValueError(f'{year}: insufficient valid play rows {total}')
 return data,total
def main():
 combined={}
 for year in YEARS:
  data,n=download_year(year)
  if not data:raise ValueError(f'{year}: no player opportunities')
  combined.update(data);print(f'{year}: {n} plays, {len(data)} player-game opportunity summaries')
 output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=COLS,lineterminator='\n');writer.writeheader()
 for (pid,season,week,team),counts in sorted(combined.items(),key=lambda x:(x[0][1],x[0][2],x[0][0])):
  row={'player_id':pid,'season':season,'week':week,'team':team,**counts}
  row['air_yards']=round(row['air_yards'],2);writer.writerow(row)
 data=output.getvalue()
 if len(data)>10*1024*1024:raise ValueError('Quality summary exceeds static site file limit')
 TARGET.parent.mkdir(parents=True,exist_ok=True)
 temp=TARGET.with_suffix('.tmp');temp.write_text(data,encoding='utf-8');temp.replace(TARGET)
 print(f'Wrote {len(combined)} player-week quality summaries')
if __name__=='__main__':
 try:main()
 except Exception as ex:print('Opportunity quality processing failed; previous file unchanged: '+str(ex),file=sys.stderr);sys.exit(1)
