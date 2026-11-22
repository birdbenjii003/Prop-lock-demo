#!/usr/bin/env python3
"""Offline tests for the Deep Dive chronological audit."""
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ddcal',ROOT/'scripts'/'deep-dive-calibration.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class CalibrationTests(unittest.TestCase):
    def test_past_only_forecasts(self):
        def make(v):
            rows=[]
            for i,x in enumerate(v):
                rows.append({'player_id':'P','season':str(2023+i//12),'week':str(i%12+1),
                   'rushing_yards':str(x),'carries':'12','season_type':'REG'})
            return rows
        rows=make([10+i for i in range(48)])
        original=mod.build(rows)['rushing_yards']['calibration']
        altered=make([10+i if i<36 else 1000 for i in range(48)])
        changed=mod.build(altered)['rushing_yards']['calibration']
        self.assertEqual(original,changed,'future 2026 outcome must not change any 2025 forecasts')
        self.assertTrue(original)
    def test_order_statistic_and_sample_gates(self):
        self.assertEqual(mod.quantile_higher([1,2,3,4,5],.8),5)
        self.assertIsNone(mod.quantile_higher([],.8))
        report=mod.audit([{'player_id':'A','season':'2025','week':'1','season_type':'REG','rushing_yards':'20'}])
        self.assertEqual(report['status'],'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(report['groups']['rushing_yards']['conformal_radius'])
    def test_negative_yardage_is_preserved(self):
        rows=[{'player_id':'A','season':str(2023+i//12),'week':str(i%12+1),
            'season_type':'REG','carries':'12','rushing_yards':str(-3 if i==3 else 30)} for i in range(48)]
        report=mod.build(rows)
        self.assertEqual(len(report['rushing_yards']['calibration']),12)
    def test_future_2026_does_not_change_2025_radius(self):
        def dataset(final):
            rows=[]
            for n in range(30):
                for year in (2023,2024,2025,2026):
                    for week in range(1,7):
                        v=20+n%4+week
                        if year==2026:v+=final
                        rows.append({'player_id':f'P{n}','season':str(year),'week':str(week),
                                     'season_type':'REG','carries':'12','rushing_yards':str(v)})
            return rows
        first=mod.audit(dataset(0))['groups']['rushing_yards']
        second=mod.audit(dataset(300))['groups']['rushing_yards']
        self.assertEqual(first['conformal_radius'],second['conformal_radius'])
        self.assertNotEqual(first['observed_coverage'],second['observed_coverage'])

if __name__=='__main__':unittest.main()
