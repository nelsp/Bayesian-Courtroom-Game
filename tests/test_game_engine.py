"""
Tests for the refactored game engine.
Ports and expands the original test_bayesian_core.py.
"""

import unittest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from game_engine import (
    BayesianCalculator,
    BayesianGame,
    CaseData,
    PlayerState,
    PlayerResponse,
    EvidenceSnapshot,
    GamePhase,
)


def make_case_dict(**overrides):
    base = {
        "meta": {"version": "1.0", "difficulty": "beginner"},
        "case": {
            "name": "Test Case",
            "summary": "A test case",
            "description": "A test criminal case",
            "population": 10000,
        },
        "prior": {
            "db": -40,
            "odds_description": "1 in 10,000",
            "odds_numeric": 0.0001,
        },
        "evidence": [
            {
                "name": "Test Evidence 1",
                "summary": "First evidence summary",
                "description": "First piece of evidence",
                "guidance": {
                    "guilty_prompt": "How likely if guilty?",
                    "innocent_prompt": "How likely if innocent?",
                },
                "reference_probabilities": {
                    "prob_guilty": 0.8,
                    "prob_innocent": 0.2,
                    "explanation": "Test",
                },
            },
            {
                "name": "Test Evidence 2",
                "summary": "Second evidence summary",
                "description": "Second piece of evidence",
                "guidance": {
                    "guilty_prompt": "How likely if guilty?",
                    "innocent_prompt": "How likely if innocent?",
                },
            },
        ],
    }
    base.update(overrides)
    return base


class TestBayesianCalculator(unittest.TestCase):

    def test_decibels_to_probability_positive(self):
        self.assertAlmostEqual(BayesianCalculator.decibels_to_probability(10), 0.9, places=4)
        self.assertAlmostEqual(BayesianCalculator.decibels_to_probability(20), 0.99, places=4)

    def test_decibels_to_probability_negative(self):
        self.assertAlmostEqual(BayesianCalculator.decibels_to_probability(-10), 0.1, places=4)

    def test_decibels_to_probability_zero(self):
        self.assertAlmostEqual(BayesianCalculator.decibels_to_probability(0), 0.5, places=4)

    def test_probability_to_decibels(self):
        self.assertAlmostEqual(BayesianCalculator.probability_to_decibels(0.9), 9.54, places=1)
        self.assertAlmostEqual(BayesianCalculator.probability_to_decibels(0.5), 0, places=1)
        self.assertAlmostEqual(BayesianCalculator.probability_to_decibels(0.1), -9.54, places=1)

    def test_calculate_db_update(self):
        self.assertAlmostEqual(BayesianCalculator.calculate_db_update(0.9, 0.1), 9.54, places=1)
        self.assertAlmostEqual(BayesianCalculator.calculate_db_update(0.1, 0.9), -9.54, places=1)
        self.assertAlmostEqual(BayesianCalculator.calculate_db_update(0.5, 0.5), 0, places=1)

    def test_calculate_guilt_threshold(self):
        self.assertAlmostEqual(BayesianCalculator.calculate_guilt_threshold(100), 20, places=1)
        self.assertAlmostEqual(BayesianCalculator.calculate_guilt_threshold(10), 10, places=1)

    def test_rating_to_probability(self):
        self.assertEqual(BayesianCalculator.rating_to_probability(0), 0.001)
        self.assertEqual(BayesianCalculator.rating_to_probability(5), 0.5)
        self.assertEqual(BayesianCalculator.rating_to_probability(10), 0.999)

    def test_group_verdict_unanimous_required(self):
        """Verify that GUILTY requires unanimous vote (all players convict)."""
        p1 = PlayerState("p1", "Alice", guilt_threshold_db=20, prior_guilt_tolerance=100,
                         current_evidence_db=25, responses=[], use_rating_scale=True)
        p2 = PlayerState("p2", "Bob", guilt_threshold_db=30, prior_guilt_tolerance=1000,
                         current_evidence_db=25, responses=[], use_rating_scale=True)
        # p1 would convict (25 >= 20), p2 would not (25 < 30)
        verdict, _, stats = BayesianCalculator.calculate_group_verdict([p1, p2])
        self.assertEqual(verdict, "NOT GUILTY")
        self.assertFalse(stats["unanimous"])

        # Now both exceed
        p2.current_evidence_db = 35
        verdict, _, stats = BayesianCalculator.calculate_group_verdict([p1, p2])
        self.assertEqual(verdict, "GUILTY")
        self.assertTrue(stats["unanimous"])


class TestCaseData(unittest.TestCase):

    def test_load_valid(self):
        cd = CaseData(make_case_dict())
        self.assertEqual(cd.case_info["name"], "Test Case")
        self.assertEqual(cd.evidence_count, 2)
        self.assertEqual(cd.prior_info["db"], -40)

    def test_get_evidence(self):
        cd = CaseData(make_case_dict())
        self.assertEqual(cd.get_evidence(0)["name"], "Test Evidence 1")
        with self.assertRaises(IndexError):
            cd.get_evidence(10)

    def test_missing_fields(self):
        with self.assertRaises(ValueError):
            CaseData({"case": {"name": "X"}})

    def test_empty_evidence(self):
        d = make_case_dict()
        d["evidence"] = []
        with self.assertRaises(ValueError):
            CaseData(d)

    def test_reference_verdict(self):
        cd = CaseData(make_case_dict())
        ref_db, details = cd.get_reference_verdict(-40)
        self.assertEqual(len(details), 1)  # only first evidence has reference probs
        self.assertGreater(ref_db, -40)


class TestPlayerState(unittest.TestCase):

    def setUp(self):
        self.player = PlayerState(
            player_id="p1", name="Alice", guilt_threshold_db=20,
            prior_guilt_tolerance=100, current_evidence_db=-40,
            responses=[], use_rating_scale=True,
        )

    def test_add_response_creates_snapshot(self):
        resp = PlayerResponse("p1", 0, "Ev1", 0.8, 0.2, True, 6.02)
        self.player.add_response(resp)
        self.assertEqual(len(self.player.responses), 1)
        self.assertEqual(len(self.player.running_snapshots), 1)
        snap = self.player.running_snapshots[0]
        self.assertAlmostEqual(snap.cumulative_db, -40 + 6.02, places=1)

    def test_would_convict(self):
        self.assertFalse(self.player.would_convict())
        self.player.current_evidence_db = 25
        self.assertTrue(self.player.would_convict())


class TestBayesianGame(unittest.TestCase):

    def setUp(self):
        self.case_dict = make_case_dict()
        self.case_data = CaseData(self.case_dict)
        self.game = BayesianGame(self.case_data, "test_game")

    def test_add_players(self):
        self.assertTrue(self.game.add_player("p1", "Alice", 100, True))
        self.assertTrue(self.game.add_player("p2", "Bob", 200, False))
        self.assertFalse(self.game.add_player("p1", "Alice Again", 100, True))
        self.assertEqual(len(self.game.players), 2)

    def test_ai_player(self):
        self.assertTrue(self.game.add_player("ai1", "Claude", 100, False,
                                              player_type="ai", model_name="claude-sonnet"))
        p = self.game.players["ai1"]
        self.assertEqual(p.player_type, "ai")
        self.assertEqual(p.model_name, "claude-sonnet")

    def test_game_phases(self):
        self.assertEqual(self.game.phase, GamePhase.SETUP)
        self.assertFalse(self.game.can_start_game())

        self.game.add_player("p1", "Alice", 100, True)
        self.assertTrue(self.game.start_game())
        self.assertEqual(self.game.phase, GamePhase.CASE_PRESENTATION)

        self.game.advance_to_evidence_preview()
        self.assertEqual(self.game.phase, GamePhase.EVIDENCE_PREVIEW)

        self.game.advance_to_evidence_review()
        self.assertEqual(self.game.phase, GamePhase.EVIDENCE_REVIEW)

    def test_evidence_submission(self):
        self.game.add_player("p1", "Alice", 100, True)
        self.game.add_player("p2", "Bob", 200, False)
        self.game.start_game()
        self.game.advance_to_evidence_review()

        self.assertTrue(self.game.submit_evidence_response("p1", 0.8, 0.2, 8, 2))
        self.assertFalse(self.game.all_players_responded())

        self.assertTrue(self.game.submit_evidence_response("p2", 0.7, 0.3))
        self.assertTrue(self.game.all_players_responded())

    def test_advance_evidence(self):
        self.game.add_player("p1", "Alice", 100, True)
        self.game.start_game()
        self.game.advance_to_evidence_review()

        self.game.submit_evidence_response("p1", 0.8, 0.2)
        self.assertTrue(self.game.advance_evidence())
        self.assertEqual(self.game.current_evidence_index, 1)

        self.game.submit_evidence_response("p1", 0.6, 0.4)
        self.assertFalse(self.game.advance_evidence())
        self.assertEqual(self.game.phase, GamePhase.VERDICT)

    def test_running_snapshots(self):
        self.game.add_player("p1", "Alice", 100, True)
        self.game.start_game()
        self.game.advance_to_evidence_review()

        self.game.submit_evidence_response("p1", 0.9, 0.1)
        self.game.advance_evidence()

        player = self.game.players["p1"]
        self.assertEqual(len(player.running_snapshots), 1)
        self.assertAlmostEqual(player.running_snapshots[0].db_update, 9.54, places=1)

    def test_save_game_results(self):
        self.game.add_player("p1", "Alice", 100, True)
        self.game.start_game()
        self.game.advance_to_evidence_review()

        for i in range(self.game.case_data.evidence_count):
            self.game.submit_evidence_response("p1", 0.8, 0.2)
            self.game.advance_evidence()

        with tempfile.TemporaryDirectory() as td:
            filename = self.game.save_game_results(td)
            self.assertTrue(os.path.exists(filename))
            with open(filename) as f:
                data = json.load(f)
            self.assertEqual(data["game_id"], "test_game")
            self.assertIn("final_verdict", data)

    def test_feedback(self):
        self.game.add_feedback({"model_name": "test", "rating": 8})
        self.assertEqual(len(self.game.feedback), 1)

    def test_get_game_state(self):
        self.game.add_player("p1", "Alice", 100, True)
        self.game.start_game()
        state = self.game.get_game_state()
        self.assertEqual(state["phase"], "case_presentation")
        self.assertIn("p1", state["players"])

    def test_get_player_state(self):
        self.game.add_player("p1", "Alice", 100, True)
        ps = self.game.get_player_state("p1")
        self.assertEqual(ps["name"], "Alice")
        self.assertEqual(ps["player_type"], "human")
        self.assertIsNone(self.game.get_player_state("nonexistent"))


class TestCompleteGameFlow(unittest.TestCase):

    def test_full_game(self):
        case_dict = make_case_dict()
        case_dict["evidence"].append({
            "name": "Test Evidence 3",
            "summary": "Third",
            "description": "Alibi evidence",
            "guidance": {
                "guilty_prompt": "If guilty?",
                "innocent_prompt": "If innocent?",
            },
            "reference_probabilities": {
                "prob_guilty": 0.2,
                "prob_innocent": 0.8,
            },
        })
        cd = CaseData(case_dict)
        game = BayesianGame(cd, "flow_test")

        game.add_player("alice", "Alice", 100, True)
        game.add_player("bob", "Bob", 1000, False)
        game.add_player("charlie", "Charlie", 20, True)
        self.assertTrue(game.start_game())
        game.advance_to_evidence_preview()
        game.advance_to_evidence_review()

        responses = [
            [("alice", 0.95, 0.001), ("bob", 0.98, 0.002), ("charlie", 0.90, 0.005)],
            [("alice", 0.70, 0.30), ("bob", 0.60, 0.40), ("charlie", 0.80, 0.20)],
            [("alice", 0.20, 0.80), ("bob", 0.15, 0.85), ("charlie", 0.25, 0.75)],
        ]

        for ev_idx, ev_responses in enumerate(responses):
            for pid, pg, pi in ev_responses:
                self.assertTrue(game.submit_evidence_response(pid, pg, pi))
            self.assertTrue(game.all_players_responded())
            has_more = game.advance_evidence()
            self.assertEqual(has_more, ev_idx < len(responses) - 1)

        self.assertEqual(game.phase, GamePhase.VERDICT)

        state = game.get_game_state()
        self.assertIn("verdict", state)

        for pid in ("alice", "bob", "charlie"):
            ps = game.get_player_state(pid)
            self.assertEqual(len(ps["responses"]), 3)
            self.assertEqual(len(ps["running_snapshots"]), 3)


if __name__ == "__main__":
    unittest.main()
