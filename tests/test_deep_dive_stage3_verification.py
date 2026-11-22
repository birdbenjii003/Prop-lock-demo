#!/usr/bin/env python3
"""Stage 3 category status and withholding regression tests."""
import importlib.util
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
    def test_all_groups_explicit(self):
        x=mod.verify(fixture())
        self.assertEqual(set(x['groups']),set(mod.cal.FIELDS))
        for group in x['groups'].values():
            self.assertNotIn('PROSPECTIVELY_VALIDATED',group['status'])

if __name__=='__main__':unittest.main()
