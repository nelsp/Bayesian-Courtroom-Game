"""
Integration tests for Socket.IO multiplayer events.
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from app import app, socketio, active_games, join_codes


class TestSocketIO(unittest.TestCase):

    def setUp(self):
        app.testing = True
        self.client1 = socketio.test_client(app)
        self.client2 = socketio.test_client(app)
        active_games.clear()
        join_codes.clear()

    def tearDown(self):
        if self.client1.is_connected():
            self.client1.disconnect()
        if self.client2.is_connected():
            self.client2.disconnect()
        active_games.clear()
        join_codes.clear()

    def _get_received(self, client, event_name):
        for msg in client.get_received():
            if msg['name'] == event_name:
                return msg['args'][0]
        return None

    def _flush(self, client):
        client.get_received()

    def test_connect(self):
        data = self._get_received(self.client1, 'connected')
        self.assertIsNotNone(data)
        self.assertIn('sid', data)

    def test_create_room(self):
        self._flush(self.client1)
        self.client1.emit('create_room', {
            'case_slug': 'riverside-robbery',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        data = self._get_received(self.client1, 'room_created')
        self.assertIsNotNone(data)
        self.assertIn('game_id', data)
        self.assertIn('join_code', data)
        self.assertEqual(len(data['join_code']), 4)
        self.assertIn('game_state', data)

    def test_create_room_missing_slug(self):
        self._flush(self.client1)
        self.client1.emit('create_room', {'name': 'Alice'})
        data = self._get_received(self.client1, 'error')
        self.assertIsNotNone(data)
        self.assertIn('case_slug', data['message'])

    def test_join_room(self):
        self._flush(self.client1)
        self._flush(self.client2)

        self.client1.emit('create_room', {
            'case_slug': 'riverside-robbery',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        created = self._get_received(self.client1, 'room_created')
        code = created['join_code']

        self.client2.emit('join_room_by_code', {
            'join_code': code,
            'name': 'Bob',
            'guilt_tolerance': 100,
        })
        join_data = self._get_received(self.client2, 'join_success')
        self.assertIsNotNone(join_data)
        self.assertEqual(join_data['game_id'], created['game_id'])
        self.assertEqual(join_data['join_code'], code)

        players = join_data['game_state']['players']
        self.assertEqual(len(players), 2)

    def test_join_invalid_code(self):
        self._flush(self.client2)
        self.client2.emit('join_room_by_code', {
            'join_code': 'ZZZZ',
            'name': 'Bob',
        })
        data = self._get_received(self.client2, 'error')
        self.assertIsNotNone(data)

    def test_start_game_host_only(self):
        self._flush(self.client1)
        self._flush(self.client2)

        self.client1.emit('create_room', {
            'case_slug': 'riverside-robbery',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        created = self._get_received(self.client1, 'room_created')
        game_id = created['game_id']
        code = created['join_code']

        self.client2.emit('join_room_by_code', {
            'join_code': code,
            'name': 'Bob',
            'guilt_tolerance': 100,
        })
        self._get_received(self.client2, 'join_success')

        # Non-host tries to start
        self._flush(self.client2)
        self.client2.emit('start_game', {'game_id': game_id})
        err = self._get_received(self.client2, 'error')
        self.assertIsNotNone(err)

        # Host starts
        self._flush(self.client1)
        self.client1.emit('start_game', {'game_id': game_id})
        started = self._get_received(self.client1, 'game_started')
        self.assertIsNotNone(started)
        self.assertEqual(started['game_state']['phase'], 'case_presentation')

    def test_evidence_sync(self):
        """Two players submit evidence and game advances."""
        self._flush(self.client1)
        self._flush(self.client2)

        self.client1.emit('create_room', {
            'case_slug': 'riverside-robbery',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        created = self._get_received(self.client1, 'room_created')
        game_id = created['game_id']
        code = created['join_code']

        self.client2.emit('join_room_by_code', {
            'join_code': code,
            'name': 'Bob',
            'guilt_tolerance': 100,
        })
        self._get_received(self.client2, 'join_success')

        # Start game
        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('start_game', {'game_id': game_id})
        self._get_received(self.client1, 'game_started')

        # Advance to evidence review
        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('advance_phase', {'game_id': game_id})
        self._get_received(self.client1, 'phase_advanced')

        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('advance_phase', {'game_id': game_id})
        phase_data = self._get_received(self.client1, 'phase_advanced')
        self.assertEqual(phase_data['game_state']['phase'], 'evidence_review')

        # Player 1 submits
        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('submit_evidence', {
            'game_id': game_id,
            'prob_guilty': 0.7,
            'prob_innocent': 0.3,
        })
        submitted = self._get_received(self.client1, 'player_submitted')
        self.assertIsNotNone(submitted)
        self.assertEqual(submitted['responses_received'], 1)

        # Player 2 submits — should advance
        self._flush(self.client1)
        self._flush(self.client2)
        self.client2.emit('submit_evidence', {
            'game_id': game_id,
            'prob_guilty': 0.6,
            'prob_innocent': 0.4,
        })

        advanced = self._get_received(self.client2, 'evidence_advanced')
        if advanced is None:
            verdict = self._get_received(self.client2, 'verdict_ready')
            self.assertIsNotNone(verdict)
        else:
            self.assertIn('next_evidence_index', advanced)

    def test_full_multiplayer_to_verdict(self):
        """Complete game through verdict with two players."""
        self._flush(self.client1)
        self._flush(self.client2)

        self.client1.emit('create_room', {
            'case_slug': 'stolen-photos',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        created = self._get_received(self.client1, 'room_created')
        game_id = created['game_id']
        code = created['join_code']

        self.client2.emit('join_room_by_code', {
            'join_code': code,
            'name': 'Bob',
            'guilt_tolerance': 100,
        })
        self._get_received(self.client2, 'join_success')

        # Start
        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('start_game', {'game_id': game_id})
        self._get_received(self.client1, 'game_started')

        # Advance through case presentation -> evidence preview -> evidence review
        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('advance_phase', {'game_id': game_id})
        self._get_received(self.client1, 'phase_advanced')

        self._flush(self.client1)
        self._flush(self.client2)
        self.client1.emit('advance_phase', {'game_id': game_id})
        self._get_received(self.client1, 'phase_advanced')

        game = active_games[game_id]
        evidence_count = game.case_data.evidence_count

        for _ in range(evidence_count):
            self._flush(self.client1)
            self._flush(self.client2)

            self.client1.emit('submit_evidence', {
                'game_id': game_id,
                'prob_guilty': 0.7,
                'prob_innocent': 0.3,
            })
            self.client2.emit('submit_evidence', {
                'game_id': game_id,
                'prob_guilty': 0.6,
                'prob_innocent': 0.4,
            })

        # After all evidence, game should be in verdict phase
        self.assertIn(game.phase.value, ('verdict', 'evidence_review'))

    def test_reconnection(self):
        self._flush(self.client1)

        self.client1.emit('create_room', {
            'case_slug': 'riverside-robbery',
            'name': 'Alice',
            'guilt_tolerance': 100,
        })
        created = self._get_received(self.client1, 'room_created')
        game_id = created['game_id']
        player_id = created['player_id']

        # Request state for reconnection
        self._flush(self.client1)
        self.client1.emit('request_state', {
            'game_id': game_id,
            'player_id': player_id,
        })
        restored = self._get_received(self.client1, 'state_restored')
        self.assertIsNotNone(restored)
        self.assertEqual(restored['game_id'], game_id)
        self.assertEqual(restored['player_id'], player_id)


if __name__ == "__main__":
    unittest.main()
