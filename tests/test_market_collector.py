import datetime as dt
import unittest
from scripts.collect_nfl_markets import extract

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.when = dt.datetime(2026, 11, 21, 14, 0, tzinfo=dt.timezone.utc)
        self.event = {
            'eventID': 'NFL_TEST_1', 'leagueID': 'NFL',
            'status': {'startsAt': '2026-11-22T18:00:00Z', 'started': False},
            'odds': {
                'passing_yards-JOSH_ALLEN-game-ou-over': {
                    'statID': 'passing_yards', 'periodID': 'game',
                    'betTypeID': 'ou', 'sideID': 'over', 'playerID': 'TEST_PLAYER',
                    'byBookmaker': {'draftkings': {'available': True, 'overUnder': '249.5', 'odds': '-110',
                       'lastUpdatedAt': '2026-11-21T13:30:00Z'}}}}}

    def test_accept_verified_shape_as_ungraded_snapshot(self):
        rows = extract({'success': True, 'data': [self.event]}, self.when)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['line'], 249.5)
        self.assertIsNone(rows[0]['graded_outcome'])
        self.assertFalse(rows[0]['verified_player_mapping'])

    def test_reject_started_or_finished_game(self):
        event = dict(self.event, status={'startsAt': '2026-11-20T18:00:00Z', 'started': True})
        self.assertEqual(extract({'success': True, 'data': [event]}, self.when), [])

    def test_reject_missing_explicit_player_id(self):
        event = {**self.event, 'odds': {k: {**v, 'playerID': None} for k, v in self.event['odds'].items()}}
        self.assertEqual(extract({'success': True, 'data': [event]}, self.when), [])

    def test_reject_failed_provider_response(self):
        with self.assertRaises(ValueError):
            extract({'success': False, 'data': [self.event]}, self.when)

    def test_reject_excess_events(self):
        with self.assertRaises(ValueError):
            extract({'success': True, 'data': [self.event] * 3}, self.when)

    def test_reject_quote_updated_after_game_start(self):
        bad = {**self.event, 'odds': {k: {**v, 'byBookmaker': {'draftkings': {
          'available': True, 'overUnder': '249.5', 'odds': '-110', 'lastUpdatedAt': '2026-11-22T18:01:00Z'}}}
          for k, v in self.event['odds'].items()}}
        self.assertEqual(extract({'success': True, 'data': [bad]}, self.when), [])

if __name__ == '__main__':
    unittest.main()
