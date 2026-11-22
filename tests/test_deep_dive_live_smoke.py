#!/usr/bin/env python3
"""Test static live-site checks offline without accessing network."""
import importlib.util
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'scripts'/'deep-dive-live-smoke.py'
spec=importlib.util.spec_from_file_location('smoke',path)
smoke=importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

HEADER='player_id,season,week,season_type\n'
def data(years):
    return HEADER+''.join(f'p{i},{y},1,REG\n' for y in years for i in range(101))

def fixtures():
    return {
        'index.html':"""<script src="scripts/deep-dive-views.js"></script>
          <script src="scripts/deep-dive-workspace.js"></script>
          deepDiveSnapSummary deepDiveQualitySummary
          nflSource==='hosted'?'hosted':'unverified'""",
        'scripts/deep-dive-views.js':"""DEEP_DIVE_TABS.map ddCohortEvidenceGate
          sourceContext==='hosted' No certified player-specific future interval""",
        'scripts/deep-dive-workspace.js':'Deep Dive',
        'scripts/deep-dive-snaps.js':'deepDiveSnapSummary',
        'scripts/deep-dive-quality.js':'deepDiveQualitySummary',
        'data/nfl_history_2023_2025.csv':data((2023,2024,2025)),
        'data/nfl_2026.csv':data((2026,)),
        'data/reports/deep_dive_calibration_audit.json':
           '{"version":"deep-dive-cross-season-v2","calibration_year":2025,"test_year":2026,"groups":'+
           '{'+','.join(f'"category_{i}":{{}}' for i in range(6))+'}}'
    }

class Stage4Smoke(unittest.TestCase):
    def test_complete_static_responses_pass(self):
        self.assertEqual(smoke.verify_responses(fixtures()),[])
    def test_missing_hosted_source_gate_detected(self):
        payload=fixtures()
        payload['index.html']=payload['index.html'].replace("nflSource==='hosted'?'hosted':'unverified'",'unverified')
        self.assertTrue(any('Missing live HTML integration' in x for x in smoke.verify_responses(payload)))
    def test_invalid_archive_detected(self):
        payload=fixtures()
        payload['data/nfl_history_2023_2025.csv']=data((2023,2024))
        self.assertIn('Missing live season rows: data/nfl_history_2023_2025.csv',smoke.verify_responses(payload))
    def test_outdated_report_detected(self):
        payload=fixtures()
        payload['data/reports/deep_dive_calibration_audit.json']='{"version":"old"}'
        self.assertIn('Missing or outdated live calibration report',smoke.verify_responses(payload))

if __name__=='__main__':
    unittest.main()
