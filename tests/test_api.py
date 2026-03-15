"""
Integration tests for the REST API endpoints.
"""

import unittest
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from app import app


class TestAPI(unittest.TestCase):

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_index_page(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Bayesian', res.data)

    def test_list_cases(self):
        res = self.client.get('/api/cases')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertGreaterEqual(len(data['cases']), 6)

    def test_get_case(self):
        res = self.client.get('/api/cases/riverside-robbery')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['case']['case']['name'], 'The Riverside Robbery')

    def test_get_case_not_found(self):
        res = self.client.get('/api/cases/nonexistent')
        self.assertEqual(res.status_code, 404)

    def test_create_game(self):
        res = self.client.post('/api/games', json={'case_slug': 'riverside-robbery'})
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('game_id', data)

    def test_create_game_missing_slug(self):
        res = self.client.post('/api/games', json={})
        self.assertEqual(res.status_code, 400)

    def test_full_game_flow(self):
        """Test a complete game through the API."""
        # Create game
        res = self.client.post('/api/games', json={'case_slug': 'stolen-photos'})
        game_id = res.get_json()['game_id']

        # Register player
        res = self.client.post(f'/api/games/{game_id}/player', json={
            'name': 'Tester',
            'guilt_tolerance': 100,
            'use_rating_scale': True,
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        player_id = data['player_id']

        # Get case info
        res = self.client.get(f'/api/games/{game_id}/case')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('case_info', data)

        # Get evidence list
        res = self.client.get(f'/api/games/{game_id}/evidence')
        data = res.get_json()
        self.assertTrue(data['success'])
        evidence_count = data['count']
        self.assertGreater(evidence_count, 0)

        # Submit evidence for each item
        for i in range(evidence_count):
            res = self.client.get(f'/api/games/{game_id}/evidence/{i}')
            self.assertTrue(res.get_json()['success'])

            res = self.client.post(f'/api/games/{game_id}/evidence/{i}', json={
                'player_id': player_id,
                'prob_guilty': 0.7,
                'prob_innocent': 0.3,
            })
            data = res.get_json()
            self.assertTrue(data['success'])

        # Get verdict
        res = self.client.get(f'/api/games/{game_id}/verdict')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('verdict', data['game_state'])

        # Submit feedback
        res = self.client.post(f'/api/games/{game_id}/feedback', json={
            'overall_rating': 8,
            'feedback': 'Great case!',
        })
        self.assertTrue(res.get_json()['success'])


if __name__ == "__main__":
    unittest.main()
