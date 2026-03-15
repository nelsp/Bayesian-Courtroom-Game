# Multi-Player Bayesian Courtroom Game — Flow & Maintenance Guide

This document describes the end-to-end flow of the multiplayer game for maintainers. It covers server (Flask + Socket.IO), game engine, and frontend behavior.

---

## 1. Architecture Overview

| Layer | Technology | Role |
|-------|------------|------|
| **Server** | Flask + Flask-SocketIO | HTTP (REST + static), WebSockets (Socket.IO) |
| **Engine** | `server/game_engine.py` | Phases, players, evidence, verdict (single source of truth) |
| **Frontend** | Vanilla JS, single-page HTML | Screens, Socket.IO client, REST for case/evidence data |

**Important:** Multiplayer uses **Socket.IO** for real-time sync (lobby, phase advances, evidence submission). Solo play and the AI player use **REST only**; the same `BayesianGame` instance backs both.

- **In-memory state:** `active_games`, `join_codes`, and `player_rooms` live in process memory. Restarting the server drops all games.
- **Player identity (multiplayer):** The Socket.IO session id (`request.sid`) is the `player_id` for browser clients. The engine does not care; it only needs a unique string per player.

---

## 2. Game Phases (Engine)

Defined in `server/game_engine.py` as `GamePhase`:

| Phase | Value | Meaning |
|-------|--------|---------|
| `SETUP` | `"setup"` | Lobby; players can join; host has not started. |
| `CASE_PRESENTATION` | `"case_presentation"` | All see case intro; only host can advance. |
| `EVIDENCE_PREVIEW` | `"evidence_preview"` | List of evidence; only host can advance. |
| `EVIDENCE_REVIEW` | `"evidence_review"` | Each piece of evidence; all submit; advance when all responded. |
| `VERDICT` | `"verdict"` | All evidence done; group verdict computed. |
| `COMPLETED` | `"completed"` | After verdict fetched (e.g. GET `/api/games/<id>/verdict`). |

**Phase transitions (multiplayer):**

- `SETUP` → `CASE_PRESENTATION`: host emits `start_game`.
- `CASE_PRESENTATION` → `EVIDENCE_PREVIEW`: host emits `advance_phase` (first time).
- `EVIDENCE_PREVIEW` → `EVIDENCE_REVIEW`: host emits `advance_phase` (second time); `current_evidence_index` set to 0.
- `EVIDENCE_REVIEW` → next evidence or `VERDICT`: automatic when `all_players_responded()` and `advance_evidence()` is called (inside `submit_evidence` handler).

---

## 3. Server-Side Data Structures

**File:** `server/app.py`

- **`active_games: Dict[str, BayesianGame]`** — `game_id` → game instance.
- **`join_codes: Dict[str, str]`** — 4-letter uppercase code → `game_id`. Used only while game is in SETUP (join by code). Not cleaned up when game starts; safe for typical session length.
- **`player_rooms: Dict[str, str]`** — Socket.IO `sid` → `game_id`. Used to know which room to broadcast to on disconnect and to re-add on `request_state`.

**Join codes:** Generated in `_generate_join_code()`: 4 random uppercase letters, uniqueness checked against `join_codes`. One code per game.

**Host:** `game.host_player_id` is set when the first player creates the room (in `create_room`). Only that `player_id` (the creator’s `sid`) may emit `start_game` or `advance_phase`.

---

## 4. Socket.IO Events (Server → Client)

| Event | When | Payload (typical) |
|-------|------|--------------------|
| `connected` | On connect | `{ sid }` |
| `error` | Invalid action / bad request | `{ message }` |
| `room_created` | After `create_room` (host only) | `game_id`, `join_code`, `player_id`, `game_state` |
| `join_success` | After `join_room_by_code` (joiner only) | `game_id`, `join_code`, `player_id`, `game_state` |
| `player_joined` | Someone joined (others in room) | `player_id`, `player_name`, `game_state` |
| `player_left` | Someone disconnected | `player_id`, `player_name`, `game_state` |
| `game_started` | Host started game (all in room) | `game_state` |
| `phase_advanced` | Host advanced phase (all in room) | `game_state` |
| `player_submitted` | Any player submitted evidence (all in room) | `player_id`, `player_name`, `responses_received`, `total_players` |
| `evidence_advanced` | All responded, more evidence (all in room) | `game_state`, `next_evidence_index` |
| `verdict_ready` | All responded, no more evidence (all in room) | `game_state` |
| `state_restored` | After `request_state` (reconnect) | `game_id`, optional `player_id`, `game_state`, optional `player_state` |

---

## 5. Socket.IO Events (Client → Server)

| Event | Who | Payload | Server action |
|-------|-----|---------|----------------|
| `create_room` | Host | `case_slug`, `name`, `guilt_tolerance`, `use_rating_scale` | Create game, join code, add player as host, join room, emit `room_created` |
| `join_room_by_code` | Guest | `join_code`, `name`, `guilt_tolerance`, `use_rating_scale` | Resolve game, add player, join room, emit `join_success` + `player_joined` (to others) |
| `start_game` | Host | `game_id` | Check host, call `game.start_game()`, emit `game_started` to room |
| `advance_phase` | Host | `game_id` | Check host; CASE_PRESENTATION→EVIDENCE_PREVIEW or EVIDENCE_PREVIEW→EVIDENCE_REVIEW; emit `phase_advanced` |
| `submit_evidence` | Any player | `game_id`, `prob_guilty`, `prob_innocent`, optional ratings | Record response; emit `player_submitted`; if all responded, `advance_evidence()`, then emit `evidence_advanced` or `verdict_ready` |
| `request_state` | Reconnecting client | `game_id`, `player_id` (optional) | Re-add to room, set `is_connected` if `player_id` given, emit `state_restored` (and `player_joined` to others if re-join) |

---

## 6. Frontend Screens and Modes

**Screens (HTML sections):**  
`welcome` → `case-select` → `standard` → `lobby` (multi only) → `case-presentation` → `evidence-preview` → `evidence-eval` → `verdict`.

**Modes:**

- **Solo:** `App.isMultiplayer === false`. No Socket.IO. REST only: POST `/api/games`, POST `/api/games/<id>/player`, then GET case/evidence, POST evidence per index, GET verdict.
- **Multiplayer host:** `App.isMultiplayer && App.isHost`. Creates room via `create_room`, shows lobby, starts game via `start_game`, advances phases via `advance_phase`, submits evidence via `submit_evidence`.
- **Multiplayer guest:** `App.isMultiplayer && !App.isHost`. Joins via `join_room_by_code`, waits in lobby for `game_started`, then follows `phase_advanced` and `evidence_advanced`/`verdict_ready`; only submits evidence (no phase control).

**Critical client state:** `gameId`, `playerId`, `caseSlug`, `caseData`, `evidenceList`, `currentEvidenceIdx`, `currentDb`, `thresholdDb`, `tolerance`, `responses`, `isMultiplayer`, `isHost`, `joinCode`, `socket`, `players`.

---

## 7. Multiplayer Flow (Step-by-Step)

### 7.1 Host: From Welcome to Lobby

1. User: Welcome → “Start a New Case” → case-select → pick case → standard.
2. User: Set name, threshold, input method → “Create Multiplayer Room”.
3. `App.createMultiplayerRoom()`: set `isMultiplayer`, `isHost`, connect Socket.IO, emit `create_room` with case_slug, name, tolerance, use_rating_scale.
4. Server: create game, join code, add player with `sid` as player_id, set `host_player_id = sid`, join_room(game_id), emit `room_created`.
5. Client: on `room_created`, set `gameId`, `playerId`, `joinCode`, `_saveSession()`, `_renderLobby(state, code)`, show lobby screen.

### 7.2 Guest: Join to Lobby

1. User: Welcome → “Join a Game” → enter 4-letter code and name → “Join Room”.
2. `App.joinGameByCode()`: set `isMultiplayer`, `isHost = false`, connect Socket.IO, emit `join_room_by_code`.
3. Server: resolve `game_id` from code, add player (sid), join_room(game_id), emit `join_success` to client, emit `player_joined` to rest of room.
4. Client: on `join_success`, set `gameId`, `playerId`, `joinCode`, `_saveSession()`, `_renderLobby(state, code)`, show lobby. Others get `player_joined` and refresh lobby list.

### 7.3 Lobby → Game Start

1. Host clicks “Start Game” → `hostStartGame()` → emit `start_game` with `game_id`.
2. Server: check `is_host(sid)`, call `game.start_game()` (phase → CASE_PRESENTATION), emit `game_started` to room.
3. All clients (including host): on `game_started`, fetch case and evidence via REST (`/api/games/<id>/case`, `/api/games/<id>/evidence`), set `caseData`, `evidenceList`, `priorDb`, `currentDb`, `responses`, `currentEvidenceIdx`, `renderCasePresentation()`, show case-presentation, update sidebar.

### 7.4 Case Presentation → Evidence Preview → Evidence Review

1. Host clicks “Review the Evidence List” → `advanceToEvidencePreview()` → emit `advance_phase`.
2. Server: phase CASE_PRESENTATION → EVIDENCE_PREVIEW, emit `phase_advanced`.
3. All: on `phase_advanced`, if phase is `evidence_preview`, show evidence-preview. Host sees “Begin Evaluation”; guests see “Waiting for host…”.
4. Host clicks “Begin Evaluation” → `beginEvaluation()` → emit `advance_phase`.
5. Server: phase EVIDENCE_PREVIEW → EVIDENCE_REVIEW, `current_evidence_index = 0`, emit `phase_advanced`.
6. All: on `phase_advanced`, if phase is `evidence_review`, `loadEvidence(0)` (REST), show evidence-eval.

### 7.5 Evidence Submission and Advance

1. Each player submits on evidence screen → `confirmEvidence()` → emit `submit_evidence` with game_id, prob_guilty, prob_innocent, optional ratings. Client updates local `currentDb` and `responses`, shows “Waiting for other jurors…” overlay.
2. Server: `submit_evidence_response(sid, ...)`, emit `player_submitted` to room (all see “X of Y submitted”).
3. When `all_players_responded()`: call `advance_evidence()`. If more evidence: emit `evidence_advanced` with `next_evidence_index`. If no more: emit `verdict_ready`.
4. Clients: on `evidence_advanced`, hide overlay, `loadEvidence(next_evidence_index)`, update sidebar. On `verdict_ready`, hide overlay, call `showVerdict()`.

### 7.6 Verdict

1. `showVerdict()`: GET `/api/games/<id>/verdict`. Server computes verdict, adds `player_verdicts` and `reference_comparison` to state, saves results, sets phase to COMPLETED, returns JSON.
2. Client: Renders evidence summary, final meter, personal verdict blurb, jury panel table (if `player_verdicts.length > 1`), group verdict banner, reference comparison, detailed JSON. Shows verdict screen.

---

## 8. Reconnection

- **Persistence:** On `room_created` or `join_success`, client calls `_saveSession()` → `sessionStorage.setItem('bcg_gameId', gameId)` and `sessionStorage.setItem('bcg_playerId', playerId)`.
- **On load:** `DOMContentLoaded` runs `App._tryReconnect()`. If both keys exist, `_connectSocket()` then emit `request_state` with `game_id`, `player_id`.
- **Server:** `request_state`: if `player_id` in game, set `is_connected = True`, `player_rooms[sid] = game_id`, `join_room(game_id)`, emit `state_restored` with full `game_state` and that player’s `player_state`; also emit `player_joined` to room (others see re-join). If player_id missing, still emit `state_restored` with game_state only.
- **Client:** On `state_restored`: set `gameId`, `playerId` if present, `isHost` from `state.host_player_id`. If phase is `setup`, show lobby. Otherwise restore case/evidence from REST, restore `currentDb`/`responses` from `player_state.running_snapshots` if present, then show the screen for current phase (case_presentation, evidence_preview, evidence_eval, or verdict).
- **After disconnect:** Socket.IO auto-reconnect triggers `reconnect`; client again emits `request_state` if session keys exist.

---

## 9. REST API (Relevant to Multiplayer)

Multiplayer still uses REST for case and evidence content (and for verdict fetch):

- `GET /api/games/<game_id>/case` — case_info, prior_info, context_sections.
- `GET /api/games/<game_id>/evidence` — list of evidence (index, name, summary).
- `GET /api/games/<game_id>/evidence/<idx>` — full evidence item for current index.
- `GET /api/games/<game_id>/verdict` — full game state including verdict, `player_verdicts`, `reference_comparison`; also saves results and sets phase to COMPLETED.

Solo and AI flows use in addition: POST `/api/games`, POST `/api/games/<id>/player`, POST `/api/games/<id>/evidence/<idx>`.

---

## 10. Engine Details for Maintainers

- **Player id in multiplayer:** Always the Socket.IO `request.sid` (string). Stored in `game.players`, `game.host_player_id`, and `game.responses_for_current_evidence`.
- **all_players_responded():** Counts only players with `is_connected === True`. Equals `len(responses_for_current_evidence) == len(connected_players)`. Disconnected players are not required to submit.
- **Group verdict:** `BayesianCalculator.calculate_group_verdict(players)`. **GUILTY** only if every (connected) player would convict; otherwise **NOT GUILTY**. Stats include guilty_votes, not_guilty_votes, total_players.
- **Verdict endpoint:** Builds `player_verdicts` from `game.players`: each entry has `player_id`, `name`, `final_db`, `final_probability`, `threshold_db`, `would_convict`. Used by frontend for the jury table.

---

## 11. File Reference

| File | Purpose |
|------|---------|
| `server/app.py` | Flask app, REST routes, Socket.IO handlers, join codes, `player_rooms`, `active_games` |
| `server/game_engine.py` | `GamePhase`, `BayesianGame`, `PlayerState`, host, evidence, verdict logic |
| `frontend/index.html` | Screens: welcome, case-select, standard, lobby, case-presentation, evidence-preview, evidence-eval, verdict; sidebar, waiting overlay, jury table |
| `frontend/js/app.js` | App state, screens, REST calls, Socket.IO connect/emit/listeners, lobby, reconnection, verdict/jury table |
| `frontend/css/game.css` | Lobby, sidebar, waiting overlay, jury table, host/waiting messaging |

---

## 12. Common Maintenance Tasks

- **Add a new phase or transition:** Update `GamePhase` and engine methods (e.g. `advance_*`), then add or adjust Socket.IO handler and client listeners (`phase_advanced` / new event).
- **Change max players:** Adjust `max_players` in `BayesianGame` and any UI that shows “X of 12” (e.g. lobby count, sidebar).
- **Persist games:** Replace in-memory `active_games`/`join_codes`/`player_rooms` with a store (e.g. Redis or DB), and restore `BayesianGame` (or equivalent state) on server restart; reconnection already uses `request_state`.
- **Debug “stuck” game:** Check server logs for which events were received; confirm `game.phase` and `all_players_responded()` (and `is_connected` for each player) in the relevant game in `active_games`.
