#!/usr/bin/env python3
"""No-leakage and evidence-gate tests for cohort comparison."""
import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'scripts'/'deep-dive-independent-checks.py'
spec=importlib.util.spec_from_file_location('ddchecks',p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def fixture(shift=0):
    rows=[]
    for pid in range(20):
        for year in (2023,2024,2025,2026):
            for week in range(1,9):
                actual=30+pid%6+week+(shift if year==2026 else 0)
                rows.append({'player_id':f'P{pid}','season':str(year),'week':str(week),
                             'season_type':'REG','carries':'12','rushing_yards':str(actual)})
    return rows

class IndependentChecks(unittest.TestCase):
    def test_no_cross_season_calibration_leakage(self):
        a=mod.evaluate(fixture())
        b=mod.evaluate(fixture(180))
        x=a['groups']['rushing_yards'];y=b['groups']['rushing_yards']
        self.assertEqual(x['status'],'DESCRIPTIVE_CHECKS')
        self.assertEqual(x['radius'],y['radius'])
        self.assertNotEqual(x['observed_coverage'],y['observed_coverage'])
        self.assertEqual(x['evaluation_players'],20)
        self.assertEqual(x['evaluation_weeks'],8)
        self.assertIsNotNone(x['last5_baseline_mae'])
        self.assertEqual(x['baseline_comparable_games'],x['evaluation_games'])
        self.assertIsInstance(x['model_beats_baseline'],bool)

    def test_sparse_data_withheld(self):
        result=mod.evaluate(fixture()[:9])
        row=result['groups']['rushing_yards']
        self.assertEqual(row['status'],'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(row['observed_coverage'])
        self.assertIsNone(row['model_beats_baseline'])

    def test_never_claims_certified_interval(self):
        report=mod.evaluate(fixture())
        self.assertIn('not independent prospective validation',report['scope'])
        self.assertNotIn('CERTIFIED',str(report))

if __name__=='__main__':
    unittest.main()
