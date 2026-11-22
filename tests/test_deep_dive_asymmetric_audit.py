#!/usr/bin/env python3
"""Asymmetric range experiment: freeze calibration and never claim deployment."""
import importlib.util
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'scripts'/'deep-dive-asymmetric-audit.py'
spec=importlib.util.spec_from_file_location('asym',path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def fixture(shift=0):
    rows=[]
    for player in range(25):
        for year in (2023,2024,2025,2026):
            for week in range(1,9):
                value=25+player%5+week+(shift if year==2026 else 0)
                rows.append({'player_id':f'P{player}','season':str(year),'week':str(week),
                             'season_type':'REG','carries':'12','rushing_yards':str(value)})
    return rows

class AsymmetricRanges(unittest.TestCase):
    def test_frozen_offsets_unaffected_by_2026(self):
        first=mod.evaluate(fixture())['groups']['rushing_yards']
        changed=mod.evaluate(fixture(200))['groups']['rushing_yards']
        self.assertEqual(first['status'],'RETROSPECTIVE_COMPARISON')
        self.assertEqual((first['lower_offset'],first['upper_offset'],first['symmetric_radius']),
                         (changed['lower_offset'],changed['upper_offset'],changed['symmetric_radius']))
        self.assertNotEqual(first['asymmetric_coverage'],changed['asymmetric_coverage'])
        self.assertEqual(changed['decision'],'RESEARCH_ONLY_NO_MODEL_CHANGE')

    def test_misses_reconcile_to_evaluation_count(self):
        result=mod.evaluate(fixture(200))['groups']['rushing_yards']
        self.assertEqual(result['asymmetric_covered']+result['asymmetric_misses_above']+
                         result['asymmetric_misses_below'],result['evaluation_games'])
        self.assertGreaterEqual(result['asymmetric_width'],0)

    def test_sparse_sample_withheld(self):
        result=mod.evaluate(fixture()[:12])
        self.assertEqual(result['groups']['rushing_yards']['status'],'INSUFFICIENT_EVIDENCE')

    def test_no_production_approval(self):
        result=mod.evaluate(fixture())
        self.assertFalse(result['model_changed'])
        self.assertFalse(result['display_changed'])
        self.assertFalse(result['player_specific_probability_available'])
        self.assertEqual(result['status'],'EXPERIMENTAL_NOT_APPROVED')

if __name__=='__main__':
    unittest.main()
