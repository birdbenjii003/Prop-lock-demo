#!/usr/bin/env python3
"""Stage 3 category status and withholding regression tests."""
import importlib.util
import csv
import tempfile
import unittest
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'scripts'/'deep-dive-stage3-verification.py'
spec=importlib.util.spec_from_file_location('stage3',path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def fixture(shift=0):
    rows=[]
    for player in range(20):
        for year in (2023,2024,2025,2026):
            for week in range(1,9):
                value=25+player%4+week+(shift if year==2026 else 0)
                rows.append({'player_id':str(player),'season':str(year),'week':str(week),
                             'season_type':'REG','carries':'12','rushing_yards':str(value)})
    return rows

class Stage3Verification(unittest.TestCase):
    def test_sparse_data_withheld(self):
        x=mod.verify(fixture()[:8])
        self.assertEqual(x['status'],'INSUFFICIENT_SOURCE_HISTORY')
        self.assertEqual(x['groups']['rushing_yards']['status'],'INSUFFICIENT_EVIDENCE')
        self.assertFalse(x['player_specific_probability_available'])
    def test_coverage_drop_detected(self):
        a=mod.verify(fixture())
        b=mod.verify(fixture(200))
        left=a['groups']['rushing_yards']
        right=b['groups']['rushing_yards']
        self.assertEqual(left['2025_calibration_tests'],right['2025_calibration_tests'])
        self.assertLess(right['2026_coverage'],.8)
        self.assertEqual(right['status'],'BELOW_COVERAGE_TARGET')
        self.assertFalse(b['prospective_validation'])
    def test_archive_csv_quoted_names_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'archive.csv'
            header=['player_id','season','week','season_type','recent_team','opponent_team']
            with archive.open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=header)
                writer.writeheader()
                for year in (2023,2024,2025):
                    for player in range(45):
                        for week in range(1,4):
                            writer.writerow({'player_id':f'Player,{player}','season':year,
                              'week':week,'season_type':'REG','recent_team':'AAA',
                              'opponent_team':'BBB'})
            inspected=mod.inspect_archive(archive)
            self.assertEqual(inspected['identity_check'],'PASSED')
            self.assertEqual(inspected['player_games_by_season']['2023'],135)
            with archive.open('a',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=header)
                writer.writerow({'player_id':'Player,0','season':2023,'week':1,
                                 'season_type':'REG','recent_team':'AAA','opponent_team':'BBB'})
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                mod.inspect_archive(archive)

    def test_category_diagnostics_do_not_claim_probability(self):
        result=mod.category_diagnostics({'observed_coverage':.78,
                    'model_mae':20,'last5_baseline_mae':21})
        self.assertEqual(result['coverage_shortfall_percentage_points'],2.0)
        self.assertGreater(result['historical_mae_improvement_percent'],0)
        self.assertTrue(result['requires_prospective_validation'])

    def test_all_groups_explicit(self):
        x=mod.verify(fixture())
        self.assertEqual(set(x['groups']),set(mod.cal.FIELDS))
        for group in x['groups'].values():
            self.assertNotIn('PROSPECTIVELY_VALIDATED',group['status'])

if __name__=='__main__':unittest.main()
