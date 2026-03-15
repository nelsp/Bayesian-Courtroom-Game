"""
Flask app — routes, REST API, Socket.IO for multiplayer, serves the single-page frontend.
"""

import os
import sys
import uuid
import json
import random
import string
import logging
from datetime import datetime
from typing import Dict, Optional

from flask import Flask, request, jsonify, send_from_directory, send_file, session
from flask_socketio import SocketIO, emit, join_room, leave_room

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

socketio = SocketIO(app, cors_allowed_origins="*")

case_manager = CaseManager(CASES_DIR)
active_games: Dict[str, BayesianGame] = {}
join_codes: Dict[str, str] = {}  # join_code -> game_id
player_rooms: Dict[str, str] = {}  # sid -> game_id


def _generate_join_code() -> str:
    while True:
        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        if code not in join_codes:
            return code


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
# REST API — Cases (unchanged)
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
# REST API — Games (kept for AI player / single-player compatibility)
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

    if game.host_player_id is None:
        game.host_player_id = player_id

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

    # Per-player verdicts for jury table
    player_verdicts = []
    for pid, player in game.players.items():
        player_verdicts.append({
            "player_id": pid,
            "name": player.name,
            "final_db": player.current_evidence_db,
            "final_probability": player.get_current_guilt_probability(),
            "threshold_db": player.guilt_threshold_db,
            "would_convict": player.would_convict(),
        })
    state["verdict"]["player_verdicts"] = player_verdicts

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
# Socket.IO — Multiplayer events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    sid = request.sid
    logger.info("Socket connected: %s", sid)
    emit("connected", {"sid": sid})


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    game_id = player_rooms.pop(sid, None)
    if game_id:
        game = active_games.get(game_id)
        if game and sid in game.players:
            game.set_player_connection_status(sid, False)
            emit("player_left", {
                "player_id": sid,
                "player_name": game.players[sid].name,
                "game_state": game.get_game_state(),
            }, room=game_id)
    logger.info("Socket disconnected: %s", sid)


@socketio.on("create_room")
def handle_create_room(data):
    sid = request.sid
    case_slug = data.get("case_slug")
    player_name = data.get("name", "Host")
    guilt_tolerance = data.get("guilt_tolerance", 100)
    use_rating_scale = data.get("use_rating_scale", True)

    if not case_slug:
        emit("error", {"message": "case_slug is required"})
        return

    try:
        case_data_obj = case_manager.load_case_data(case_slug)
    except (FileNotFoundError, ValueError) as e:
        emit("error", {"message": str(e)})
        return

    game_id = f"game_{uuid.uuid4().hex[:8]}"
    game = BayesianGame(case_data_obj, game_id)
    active_games[game_id] = game

    code = _generate_join_code()
    join_codes[code] = game_id

    game.add_player(sid, player_name, guilt_tolerance, use_rating_scale)
    game.host_player_id = sid
    player_rooms[sid] = game_id

    join_room(game_id)

    logger.info("Room created: %s (code=%s) by %s", game_id, code, player_name)
    emit("room_created", {
        "game_id": game_id,
        "join_code": code,
        "player_id": sid,
        "game_state": game.get_game_state(),
    })


@socketio.on("join_room_by_code")
def handle_join_room(data):
    sid = request.sid
    code = (data.get("join_code") or "").upper().strip()
    player_name = data.get("name", "Juror")
    guilt_tolerance = data.get("guilt_tolerance", 100)
    use_rating_scale = data.get("use_rating_scale", True)

    game_id = join_codes.get(code)
    if not game_id:
        emit("error", {"message": "Invalid room code"})
        return

    game = active_games.get(game_id)
    if not game:
        emit("error", {"message": "Game not found"})
        return

    if game.phase != GamePhase.SETUP:
        emit("error", {"message": "Game already started"})
        return

    ok = game.add_player(sid, player_name, guilt_tolerance, use_rating_scale)
    if not ok:
        emit("error", {"message": "Could not join (game full or already joined)"})
        return

    player_rooms[sid] = game_id
    join_room(game_id)

    state = game.get_game_state()
    logger.info("Player %s joined room %s (code=%s)", player_name, game_id, code)

    emit("join_success", {
        "game_id": game_id,
        "join_code": code,
        "player_id": sid,
        "game_state": state,
    })

    emit("player_joined", {
        "player_id": sid,
        "player_name": player_name,
        "game_state": state,
    }, room=game_id, include_self=False)


@socketio.on("start_game")
def handle_start_game(data):
    sid = request.sid
    game_id = data.get("game_id")
    game = active_games.get(game_id)

    if not game:
        emit("error", {"message": "Game not found"})
        return
    if not game.is_host(sid):
        emit("error", {"message": "Only the host can start the game"})
        return

    if game.start_game():
        state = game.get_game_state()
        socketio.emit("game_started", {"game_state": state}, room=game_id)
        logger.info("Game %s started by host", game_id)
    else:
        emit("error", {"message": "Cannot start game"})


@socketio.on("advance_phase")
def handle_advance_phase(data):
    sid = request.sid
    game_id = data.get("game_id")
    game = active_games.get(game_id)

    if not game:
        emit("error", {"message": "Game not found"})
        return
    if not game.is_host(sid):
        emit("error", {"message": "Only the host can advance phases"})
        return

    if game.phase == GamePhase.CASE_PRESENTATION:
        game.advance_to_evidence_preview()
        socketio.emit("phase_advanced", {"game_state": game.get_game_state()}, room=game_id)
    elif game.phase == GamePhase.EVIDENCE_PREVIEW:
        game.advance_to_evidence_review()
        socketio.emit("phase_advanced", {"game_state": game.get_game_state()}, room=game_id)


@socketio.on("submit_evidence")
def handle_submit_evidence(data):
    sid = request.sid
    game_id = data.get("game_id")
    game = active_games.get(game_id)

    if not game:
        emit("error", {"message": "Game not found"})
        return

    prob_guilty = data.get("prob_guilty")
    prob_innocent = data.get("prob_innocent")
    guilty_rating = data.get("guilty_rating")
    innocent_rating = data.get("innocent_rating")

    ok = game.submit_evidence_response(
        sid, prob_guilty, prob_innocent,
        guilty_rating=guilty_rating,
        innocent_rating=innocent_rating,
    )
    if not ok:
        emit("error", {"message": "Could not submit response"})
        return

    socketio.emit("player_submitted", {
        "player_id": sid,
        "player_name": game.players[sid].name,
        "responses_received": len(game.responses_for_current_evidence),
        "total_players": len([p for p in game.players.values() if p.is_connected]),
    }, room=game_id)

    if game.all_players_responded():
        has_more = game.advance_evidence()
        state = game.get_game_state()
        if has_more:
            socketio.emit("evidence_advanced", {
                "game_state": state,
                "next_evidence_index": game.current_evidence_index,
            }, room=game_id)
        else:
            socketio.emit("verdict_ready", {
                "game_state": state,
            }, room=game_id)


@socketio.on("request_state")
def handle_request_state(data):
    sid = request.sid
    game_id = data.get("game_id")
    player_id = data.get("player_id")
    game = active_games.get(game_id)

    if not game:
        emit("error", {"message": "Game not found"})
        return

    if player_id and player_id in game.players:
        game.set_player_connection_status(player_id, True)
        player_rooms[sid] = game_id
        join_room(game_id)

        emit("state_restored", {
            "game_id": game_id,
            "player_id": player_id,
            "game_state": game.get_game_state(),
            "player_state": game.get_player_state(player_id),
        })

        emit("player_joined", {
            "player_id": player_id,
            "player_name": game.players[player_id].name,
            "game_state": game.get_game_state(),
        }, room=game_id, include_self=False)
    else:
        emit("state_restored", {
            "game_id": game_id,
            "game_state": game.get_game_state(),
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("Bayesian Courtroom Game Server (Multiplayer)")
    print(f"  Cases dir:    {CASES_DIR}")
    print(f"  Frontend dir: {FRONTEND_DIR}")
    print(f"  Results dir:  {RESULTS_DIR}")
    print("  http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
