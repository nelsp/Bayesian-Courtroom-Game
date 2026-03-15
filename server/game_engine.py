"""
Core Bayesian jurisprudence game engine.
Refactored from bayesian_core.py — single source of truth for all game logic.
"""

import math
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


class GamePhase(Enum):
    SETUP = "setup"
    CASE_PRESENTATION = "case_presentation"
    EVIDENCE_PREVIEW = "evidence_preview"
    EVIDENCE_REVIEW = "evidence_review"
    VERDICT = "verdict"
    COMPLETED = "completed"


@dataclass
class PlayerResponse:
    player_id: str
    evidence_index: int
    evidence_name: str
    prob_guilty: float
    prob_innocent: float
    used_rating_scale: bool
    db_update: float
    guilty_rating: Optional[int] = None
    innocent_rating: Optional[int] = None
    reasoning: Optional[str] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


@dataclass
class EvidenceSnapshot:
    evidence_index: int
    evidence_name: str
    db_update: float
    cumulative_db: float
    cumulative_probability: float


@dataclass
class PlayerState:
    player_id: str
    name: str
    guilt_threshold_db: float
    prior_guilt_tolerance: int
    current_evidence_db: float
    responses: List[PlayerResponse]
    use_rating_scale: bool
    player_type: str = "human"
    model_name: Optional[str] = None
    is_connected: bool = True
    running_snapshots: List[EvidenceSnapshot] = field(default_factory=list)

    def add_response(self, response: PlayerResponse):
        self.responses.append(response)
        self.current_evidence_db += response.db_update
        snapshot = EvidenceSnapshot(
            evidence_index=response.evidence_index,
            evidence_name=response.evidence_name,
            db_update=response.db_update,
            cumulative_db=self.current_evidence_db,
            cumulative_probability=BayesianCalculator.decibels_to_probability(self.current_evidence_db),
        )
        self.running_snapshots.append(snapshot)

    def get_current_guilt_probability(self) -> float:
        return BayesianCalculator.decibels_to_probability(self.current_evidence_db) * 100

    def would_convict(self) -> bool:
        return self.current_evidence_db >= self.guilt_threshold_db


class BayesianCalculator:

    RATING_TO_PROBABILITY = {
        0: 0.001,
        1: 0.02,
        2: 0.1,
        3: 0.2,
        4: 0.35,
        5: 0.5,
        6: 0.65,
        7: 0.8,
        8: 0.9,
        9: 0.98,
        10: 0.999,
    }

    @staticmethod
    def decibels_to_probability(db: float) -> float:
        if db == 0:
            return 0.5
        elif db > 0:
            return 1 - (1 / (10 ** (db / 10)))
        else:
            return 1 / (10 ** (abs(db) / 10))

    @staticmethod
    def probability_to_decibels(prob: float) -> float:
        if prob >= 0.5:
            return 10 * math.log10(prob / (1 - prob))
        else:
            return -10 * math.log10((1 - prob) / prob)

    @staticmethod
    def calculate_db_update(prob_guilty: float, prob_innocent: float) -> float:
        return 10 * math.log10(prob_guilty / prob_innocent)

    @staticmethod
    def calculate_guilt_threshold(tolerance: int) -> float:
        return 10 * math.log10(tolerance)

    @staticmethod
    def rating_to_probability(rating: int) -> float:
        return BayesianCalculator.RATING_TO_PROBABILITY.get(rating, 0.5)

    @staticmethod
    def average_evidence_levels(players: List[PlayerState]) -> float:
        if not players:
            return 0.0
        return sum(p.current_evidence_db for p in players) / len(players)

    @staticmethod
    def calculate_group_verdict(players: List[PlayerState]) -> Tuple[str, float, Dict]:
        if not players:
            return "NO PLAYERS", 0.0, {}

        avg_evidence_db = BayesianCalculator.average_evidence_levels(players)
        avg_guilt_prob = BayesianCalculator.decibels_to_probability(avg_evidence_db) * 100

        guilty_votes = sum(1 for p in players if p.would_convict())
        not_guilty_votes = len(players) - guilty_votes

        # Unanimous requirement: GUILTY only if ALL players would convict
        group_verdict = "GUILTY" if guilty_votes == len(players) else "NOT GUILTY"

        stats = {
            "average_evidence_db": avg_evidence_db,
            "average_guilt_probability": avg_guilt_prob,
            "guilty_votes": guilty_votes,
            "not_guilty_votes": not_guilty_votes,
            "total_players": len(players),
            "unanimous": guilty_votes == 0 or not_guilty_votes == 0,
        }

        return group_verdict, avg_evidence_db, stats


class CaseData:

    def __init__(self, case_dict: Dict):
        self.data = case_dict
        self._validate()

    def _validate(self):
        for field_name in ("case", "prior", "evidence"):
            if field_name not in self.data:
                raise ValueError(f"Missing required field '{field_name}' in case data")
        for field_name in ("name", "description"):
            if field_name not in self.data["case"]:
                raise ValueError(f"Missing required field 'case.{field_name}'")
        if not isinstance(self.data["evidence"], list) or len(self.data["evidence"]) == 0:
            raise ValueError("Evidence must be a non-empty list")
        for i, ev in enumerate(self.data["evidence"]):
            for field_name in ("name", "description"):
                if field_name not in ev:
                    raise ValueError(f"Missing 'evidence[{i}].{field_name}'")

    @property
    def case_info(self) -> Dict:
        return self.data["case"]

    @property
    def prior_info(self) -> Dict:
        return self.data["prior"]

    @property
    def evidence_list(self) -> List[Dict]:
        return self.data["evidence"]

    @property
    def evidence_count(self) -> int:
        return len(self.data["evidence"])

    @property
    def meta(self) -> Dict:
        return self.data.get("meta", {})

    @property
    def context_sections(self) -> List[Dict]:
        return self.data.get("context_sections", [])

    def get_evidence(self, index: int) -> Dict:
        if 0 <= index < len(self.data["evidence"]):
            return self.data["evidence"][index]
        raise IndexError(f"Evidence index {index} out of range")

    def get_reference_verdict(self, prior_db: float) -> Tuple[float, List[Dict]]:
        """Calculate what the verdict would be using reference probabilities."""
        cumulative_db = prior_db
        evidence_details = []
        for ev in self.data["evidence"]:
            ref = ev.get("reference_probabilities", {})
            pg = ref.get("prob_guilty")
            pi = ref.get("prob_innocent")
            if pg is not None and pi is not None and pi > 0:
                db_update = BayesianCalculator.calculate_db_update(pg, pi)
                cumulative_db += db_update
                evidence_details.append({
                    "name": ev["name"],
                    "db_update": db_update,
                    "cumulative_db": cumulative_db,
                })
        return cumulative_db, evidence_details


class BayesianGame:

    def __init__(self, case_data: CaseData, game_id: str = None):
        self.game_id = game_id or self._generate_game_id()
        self.case_data = case_data
        self.players: Dict[str, PlayerState] = {}
        self.phase = GamePhase.SETUP
        self.current_evidence_index = 0
        self.created_at = datetime.now()
        self.max_players = 12
        self.responses_for_current_evidence: Dict[str, PlayerResponse] = {}
        self.feedback: List[Dict] = []

    def _generate_game_id(self) -> str:
        return f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def add_player(
        self,
        player_id: str,
        name: str,
        guilt_tolerance: int,
        use_rating_scale: bool = True,
        player_type: str = "human",
        model_name: Optional[str] = None,
    ) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if player_id in self.players:
            return False

        guilt_threshold_db = BayesianCalculator.calculate_guilt_threshold(guilt_tolerance)

        player_state = PlayerState(
            player_id=player_id,
            name=name,
            guilt_threshold_db=guilt_threshold_db,
            prior_guilt_tolerance=guilt_tolerance,
            current_evidence_db=self.case_data.prior_info["db"],
            responses=[],
            use_rating_scale=use_rating_scale,
            player_type=player_type,
            model_name=model_name,
        )

        self.players[player_id] = player_state
        return True

    def remove_player(self, player_id: str) -> bool:
        if player_id in self.players:
            del self.players[player_id]
            self.responses_for_current_evidence.pop(player_id, None)
            return True
        return False

    def set_player_connection_status(self, player_id: str, is_connected: bool):
        if player_id in self.players:
            self.players[player_id].is_connected = is_connected

    def can_start_game(self) -> bool:
        return len(self.players) >= 1 and self.phase == GamePhase.SETUP

    def start_game(self) -> bool:
        if self.can_start_game():
            self.phase = GamePhase.CASE_PRESENTATION
            return True
        return False

    def advance_to_evidence_preview(self):
        if self.phase == GamePhase.CASE_PRESENTATION:
            self.phase = GamePhase.EVIDENCE_PREVIEW

    def advance_to_evidence_review(self):
        if self.phase in (GamePhase.CASE_PRESENTATION, GamePhase.EVIDENCE_PREVIEW):
            self.phase = GamePhase.EVIDENCE_REVIEW
            self.current_evidence_index = 0

    def submit_evidence_response(
        self,
        player_id: str,
        prob_guilty: float,
        prob_innocent: float,
        guilty_rating: int = None,
        innocent_rating: int = None,
        reasoning: str = None,
    ) -> bool:
        if self.phase != GamePhase.EVIDENCE_REVIEW:
            return False
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        db_update = BayesianCalculator.calculate_db_update(prob_guilty, prob_innocent)

        response = PlayerResponse(
            player_id=player_id,
            evidence_index=self.current_evidence_index,
            evidence_name=self.case_data.get_evidence(self.current_evidence_index)["name"],
            prob_guilty=prob_guilty,
            prob_innocent=prob_innocent,
            used_rating_scale=player.use_rating_scale,
            db_update=db_update,
            guilty_rating=guilty_rating,
            innocent_rating=innocent_rating,
            reasoning=reasoning,
        )

        self.responses_for_current_evidence[player_id] = response
        return True

    def all_players_responded(self) -> bool:
        connected = [pid for pid, p in self.players.items() if p.is_connected]
        return len(self.responses_for_current_evidence) == len(connected)

    def advance_evidence(self) -> bool:
        if self.phase != GamePhase.EVIDENCE_REVIEW:
            return False

        for player_id, response in self.responses_for_current_evidence.items():
            if player_id in self.players:
                self.players[player_id].add_response(response)

        self.responses_for_current_evidence.clear()

        if self.current_evidence_index < self.case_data.evidence_count - 1:
            self.current_evidence_index += 1
            return True
        else:
            self.phase = GamePhase.VERDICT
            return False

    def add_feedback(self, feedback_data: Dict):
        self.feedback.append(feedback_data)

    def get_game_state(self) -> Dict:
        state = {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "case_info": self.case_data.case_info,
            "prior_info": self.case_data.prior_info,
            "current_evidence_index": self.current_evidence_index,
            "total_evidence_count": self.case_data.evidence_count,
            "players": {
                pid: {
                    "name": player.name,
                    "is_connected": player.is_connected,
                    "player_type": player.type if hasattr(player, "type") else player.player_type,
                    "current_guilt_probability": player.get_current_guilt_probability(),
                    "current_evidence_db": player.current_evidence_db,
                    "responses_count": len(player.responses),
                    "running_snapshots": [asdict(s) for s in player.running_snapshots],
                }
                for pid, player in self.players.items()
            },
            "responses_received": len(self.responses_for_current_evidence),
            "waiting_for_responses": not self.all_players_responded(),
        }

        if self.phase == GamePhase.EVIDENCE_REVIEW:
            state["current_evidence"] = self.case_data.get_evidence(self.current_evidence_index)

        if self.phase in (GamePhase.VERDICT, GamePhase.COMPLETED):
            verdict, avg_db, stats = BayesianCalculator.calculate_group_verdict(
                list(self.players.values())
            )
            state["verdict"] = {
                "group_verdict": verdict,
                "average_evidence_db": avg_db,
                "statistics": stats,
            }

        return state

    def get_player_state(self, player_id: str) -> Optional[Dict]:
        if player_id not in self.players:
            return None

        player = self.players[player_id]
        return {
            "player_id": player_id,
            "name": player.name,
            "guilt_threshold_db": player.guilt_threshold_db,
            "prior_guilt_tolerance": player.prior_guilt_tolerance,
            "current_evidence_db": player.current_evidence_db,
            "current_guilt_probability": player.get_current_guilt_probability(),
            "would_convict": player.would_convict(),
            "use_rating_scale": player.use_rating_scale,
            "player_type": player.player_type,
            "model_name": player.model_name,
            "responses": [asdict(r) for r in player.responses],
            "running_snapshots": [asdict(s) for s in player.running_snapshots],
            "is_connected": player.is_connected,
        }

    def save_game_results(self, results_dir: str = "results") -> str:
        os.makedirs(results_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(results_dir, f"{self.game_id}_{timestamp}.json")

        verdict, avg_db, stats = BayesianCalculator.calculate_group_verdict(
            list(self.players.values())
        )

        results = {
            "game_id": self.game_id,
            "created_at": self.created_at.isoformat(),
            "completed_at": datetime.now().isoformat(),
            "case_data": self.case_data.data,
            "final_verdict": verdict,
            "final_statistics": stats,
            "players": {pid: asdict(player) for pid, player in self.players.items()},
            "feedback": self.feedback,
        }

        with open(filename, "w") as f:
            json.dump(results, f, indent=2, default=str)
        return filename
