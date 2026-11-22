#!/usr/bin/env python3
import importlib.util, unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/'scripts'/'verify_nfl_snap_ids.py'
spec=importlib.util.spec_from_file_location('verified_snaps',FILE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SnapCrosswalkTests(unittest.TestCase):
 def test_unique_joins_only(self):
  ids=m.crosswalk([{'gsis_id':'G1','pfr_id':'P1'},{'gsis_id':'G2','pfr_id':'P2'},{'gsis_id':'G3','pfr_id':'PX'},{'gsis_id':'G4','pfr_id':'PX'}])
  self.assertEqual(ids,{'P1':'G1','P2':'G2'})
  snaps=[{'pfr_player_id':'P1','season':'2025','week':'7','team':'A','offense_snaps':'60','offense_pct':'0.8'},
         {'pfr_player_id':'P2','season':'2025','week':'7','team':'B','offense_snaps':'58','offense_pct':'0.7'},
         {'pfr_player_id':'PX','season':'2025','week':'7','team':'A','offense_snaps':'22','offense_pct':'0.25'}]
  history=[{'player_id':'G1','season':'2025','week':'7','recent_team':'A'},
           {'player_id':'G2','season':'2025','week':'7','recent_team':'WRONG'}]
  rows,rejected=m.match(snaps,history,ids)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['player_id'],'G1');self.assertEqual(rejected,2)
 def test_duplicate_rejection(self):
  snap={'pfr_player_id':'P1','season':'2024','week':'3','team':'A','offense_snaps':'50','offense_pct':'0.6'}
  history=[{'player_id':'G1','season':'2024','week':'3','recent_team':'A'}]
  records,rejected=m.match([snap,snap],history,{'P1':'G1'})
  self.assertEqual(len(records),1);self.assertEqual(rejected,1)
if __name__=='__main__':unittest.main()
