# AI Integration Guide

## Overview

The Bayesian Courtroom Game exposes a REST API that any AI model can use to play through cases. The AI player is treated identically to a human player — it receives the same information and its responses are recorded in the same format.

## REST API Endpoints

```
POST   /api/games                         Create a new game session
GET    /api/games/{game_id}               Get full game state
POST   /api/games/{game_id}/player        Register a player (human or AI)
GET    /api/games/{game_id}/case           Get case presentation data
GET    /api/games/{game_id}/evidence       Get evidence preview list
GET    /api/games/{game_id}/evidence/{i}   Get full details for evidence item i
POST   /api/games/{game_id}/evidence/{i}   Submit probability assessment
GET    /api/games/{game_id}/verdict        Get final verdict and results
POST   /api/games/{game_id}/feedback       Submit AI feedback on the case
GET    /api/cases                          List available cases
GET    /api/cases/{slug}                   Get full case data
```

## Using the AIPlayer Adapter

The `ai_player.py` module provides a Python wrapper:

```python
from ai_player import AIPlayer

player = AIPlayer("claude-sonnet", "your-api-key", "http://localhost:5000")

# Set your model callable — it receives a prompt string and returns the model's response
def call_my_model(prompt):
    # ... call your model API ...
    return response_text

player.set_model_callable(call_my_model)

# Play a case
results = player.play_case("riverside-robbery", guilt_tolerance=100)
print(results["verdict"])
```

## Direct API Usage

If you prefer to use the API directly without the adapter:

```python
import requests

BASE = "http://localhost:5000"

# 1. Create game
game = requests.post(f"{BASE}/api/games", json={"case_slug": "riverside-robbery"}).json()
game_id = game["game_id"]

# 2. Register as AI player
player = requests.post(f"{BASE}/api/games/{game_id}/player", json={
    "name": "My AI Model",
    "guilt_tolerance": 100,
    "player_type": "ai",
    "model_name": "my-model-v1"
}).json()
player_id = player["player_id"]

# 3. Read case
case = requests.get(f"{BASE}/api/games/{game_id}/case").json()

# 4. Get evidence list
evidence = requests.get(f"{BASE}/api/games/{game_id}/evidence").json()

# 5. Evaluate each evidence item
for i in range(evidence["count"]):
    detail = requests.get(f"{BASE}/api/games/{game_id}/evidence/{i}").json()
    # ... run your model to get prob_guilty and prob_innocent ...
    requests.post(f"{BASE}/api/games/{game_id}/evidence/{i}", json={
        "player_id": player_id,
        "prob_guilty": 0.8,
        "prob_innocent": 0.2,
        "reasoning": "Model's explanation"
    })

# 6. Get verdict
verdict = requests.get(f"{BASE}/api/games/{game_id}/verdict").json()
```

## AI Feedback Format

After playing, submit structured feedback:

```json
{
  "model_name": "claude-sonnet",
  "overall_rating": 8,
  "narrative_clarity": 9,
  "evidence_quality": [...],
  "game_flow_feedback": "...",
  "difficulty_assessment": "intermediate",
  "suggested_improvements": ["..."]
}
```
