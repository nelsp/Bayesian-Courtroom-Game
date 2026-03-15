"""
Flask app — routes, REST API, serves the single-page frontend.
"""

import os
import sys
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, Optional

from flask import Flask, request, jsonify, send_from_directory, send_file

from game_engine import BayesianGame, BayesianCalculator, GamePhase, CaseData
from case_manager import CaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_DIR = os.path.join(BASE_DIR, "cases")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bayesian-courtroom-dev-key")

case_manager = CaseManager(CASES_DIR)
active_games: Dict[str, BayesianGame] = {}


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file(os.path.join(FRONTEND_DIR, "index.html"))


@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)


@app.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "assets"), filename)


@app.route("/cases/images/<path:filename>")
def serve_case_images(filename):
    return send_from_directory(os.path.join(CASES_DIR, "images"), filename)


# ---------------------------------------------------------------------------
# REST API — Cases
# ---------------------------------------------------------------------------

@app.route("/api/cases", methods=["GET"])
def list_cases():
    difficulty = request.args.get("difficulty")
    tag = request.args.get("tag")
    cases = case_manager.list_cases(difficulty=difficulty, tag=tag)
    return jsonify({"success": True, "cases": cases})


@app.route("/api/cases/<slug>", methods=["GET"])
def get_case(slug):
    try:
        data = case_manager.get_full_case(slug)
        return jsonify({"success": True, "case": data})
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Case not found"}), 404


# ---------------------------------------------------------------------------
# REST API — Games
# ---------------------------------------------------------------------------

@app.route("/api/games", methods=["POST"])
def create_game():
    body = request.get_json(silent=True) or {}
    case_slug = body.get("case_slug")
    if not case_slug:
        return jsonify({"success": False, "error": "case_slug is required"}), 400

    try:
        case_data_obj = case_manager.load_case_data(case_slug)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400

    game_id = f"game_{uuid.uuid4().hex[:8]}"
    game = BayesianGame(case_data_obj, game_id)
    active_games[game_id] = game
    logger.info("Created game %s for case %s", game_id, case_slug)
    return jsonify({"success": True, "game_id": game_id})


@app.route("/api/games/<game_id>", methods=["GET"])
def get_game(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404
    return jsonify({"success": True, "game_state": game.get_game_state()})


@app.route("/api/games/<game_id>/player", methods=["POST"])
def register_player(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    body = request.get_json(silent=True) or {}
    name = body.get("name", "Player")
    guilt_tolerance = body.get("guilt_tolerance", 100)
    use_rating_scale = body.get("use_rating_scale", True)
    player_type = body.get("player_type", "human")
    model_name = body.get("model_name")

    player_id = body.get("player_id") or f"player_{uuid.uuid4().hex[:8]}"

    ok = game.add_player(
        player_id, name, guilt_tolerance, use_rating_scale,
        player_type=player_type, model_name=model_name,
    )
    if not ok:
        return jsonify({"success": False, "error": "Could not add player"}), 400

    game.start_game()

    return jsonify({
        "success": True,
        "player_id": player_id,
        "game_state": game.get_game_state(),
    })


@app.route("/api/games/<game_id>/case", methods=["GET"])
def get_game_case(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    return jsonify({
        "success": True,
        "case_info": game.case_data.case_info,
        "prior_info": game.case_data.prior_info,
        "context_sections": game.case_data.context_sections,
    })


@app.route("/api/games/<game_id>/evidence", methods=["GET"])
def get_evidence_list(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    preview = []
    for i, ev in enumerate(game.case_data.evidence_list):
        preview.append({
            "index": i,
            "name": ev["name"],
            "summary": ev.get("summary", ev["description"][:100]),
        })
    return jsonify({"success": True, "evidence": preview, "count": len(preview)})


@app.route("/api/games/<game_id>/evidence/<int:idx>", methods=["GET"])
def get_evidence_detail(game_id, idx):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404
    try:
        ev = game.case_data.get_evidence(idx)
        return jsonify({"success": True, "evidence": ev, "index": idx})
    except IndexError:
        return jsonify({"success": False, "error": "Evidence not found"}), 404


@app.route("/api/games/<game_id>/evidence/<int:idx>", methods=["POST"])
def submit_evidence(game_id, idx):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    if game.phase == GamePhase.CASE_PRESENTATION:
        game.advance_to_evidence_preview()
    if game.phase == GamePhase.EVIDENCE_PREVIEW:
        game.advance_to_evidence_review()

    while game.current_evidence_index < idx and game.phase == GamePhase.EVIDENCE_REVIEW:
        game.advance_evidence()

    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    prob_guilty = body.get("prob_guilty")
    prob_innocent = body.get("prob_innocent")
    guilty_rating = body.get("guilty_rating")
    innocent_rating = body.get("innocent_rating")
    reasoning = body.get("reasoning")

    if not player_id or prob_guilty is None or prob_innocent is None:
        return jsonify({"success": False, "error": "player_id, prob_guilty, and prob_innocent are required"}), 400

    ok = game.submit_evidence_response(
        player_id, prob_guilty, prob_innocent,
        guilty_rating=guilty_rating,
        innocent_rating=innocent_rating,
        reasoning=reasoning,
    )
    if not ok:
        return jsonify({"success": False, "error": "Could not submit response"}), 400

    if game.all_players_responded():
        has_more = game.advance_evidence()

    player_state = game.get_player_state(player_id)
    return jsonify({
        "success": True,
        "game_state": game.get_game_state(),
        "player_state": player_state,
    })


@app.route("/api/games/<game_id>/verdict", methods=["GET"])
def get_verdict(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    if game.phase not in (GamePhase.VERDICT, GamePhase.COMPLETED):
        return jsonify({"success": False, "error": "Game not in verdict phase"}), 400

    state = game.get_game_state()

    ref_db, ref_details = game.case_data.get_reference_verdict(game.case_data.prior_info["db"])
    state["verdict"]["reference_comparison"] = {
        "reference_final_db": ref_db,
        "reference_evidence": ref_details,
    }

    game.save_game_results(RESULTS_DIR)
    game.phase = GamePhase.COMPLETED

    return jsonify({"success": True, "game_state": state})


@app.route("/api/games/<game_id>/feedback", methods=["POST"])
def submit_feedback(game_id):
    game = active_games.get(game_id)
    if not game:
        return jsonify({"success": False, "error": "Game not found"}), 404

    body = request.get_json(silent=True) or {}
    body["submitted_at"] = datetime.now().isoformat()
    game.add_feedback(body)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("Bayesian Courtroom Game Server")
    print(f"  Cases dir:    {CASES_DIR}")
    print(f"  Frontend dir: {FRONTEND_DIR}")
    print(f"  Results dir:  {RESULTS_DIR}")
    print("  http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
