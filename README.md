# Bayesian Courtroom Game

A mobile-first web application that teaches Bayesian reasoning through criminal cases. Players act as jurors, evaluating evidence and updating their beliefs using the decibel (dB) framework for probability.

## Quick Start

```bash
pip install -r requirements.txt
cd server
python app.py
```

Open `http://localhost:5000` on your phone or browser.

## How It Works

1. **Choose a case** from the selection screen
2. **Set your conviction standard** (how certain you need to be to convict)
3. **Read the case narrative** and understand the prior probability
4. **Preview all evidence** items before evaluation
5. **Evaluate each piece of evidence** by estimating:
   - P(evidence | guilty) — how likely is this evidence if the defendant is guilty?
   - P(evidence | innocent) — how likely if they're innocent?
6. **See the verdict** based on your cumulative assessment

Evidence strength is measured in **decibels (dB)**, a logarithmic scale that makes it easy to accumulate evidence. Positive dB = evidence toward guilt; negative dB = evidence toward innocence.

## Project Structure

```
├── server/
│   ├── app.py              # Flask server and REST API
│   ├── game_engine.py       # Core Bayesian game logic
│   ├── case_manager.py      # Case file loading and validation
│   └── ai_player.py         # AI player adapter
├── frontend/
│   ├── index.html           # Single-page app (all 7 screens)
│   ├── css/game.css         # Mobile-first responsive styles
│   └── js/
│       ├── app.js           # Screen navigation, API calls
│       ├── evidence-input.js # Slider and probability controls
│       └── visualizations.js # Probability meter, dB calculations
├── cases/
│   ├── schema.json          # JSON Schema for case validation
│   └── *.json               # 6 case files
├── tests/
│   ├── test_game_engine.py  # Engine unit tests
│   ├── test_case_manager.py # Case loading/validation tests
│   └── test_api.py          # API integration tests
├── results/                 # Saved game results (gitignored)
└── docs/
    ├── case-authoring-guide.md
    └── ai-integration-guide.md
```

## Cases

| Case | Difficulty | Evidence Items | Description |
|------|-----------|---------------|-------------|
| The Riverside Robbery | Beginner | 7 | Convenience store robbery with eyewitness testimony |
| The Stolen Intimate Photos | Beginner | 5 | Photo theft with multiple suspects and digital clues |
| The Roadhouse Murder | Intermediate | 6 | Biker bar murder with forensic evidence |
| The Diamond Lounge Murder | Intermediate | 5 | VIP room strangulation with DNA and motive |
| The Riverside Manor Murder | Advanced | 7 | Novelist poisoned at a literary gala |
| The Diamond District Heist | Advanced | 5 | $2M diamond heist by a security expert |

## AI Player Integration

Any AI model that can make HTTP requests can play through the same API the browser uses:

```python
from ai_player import AIPlayer

player = AIPlayer("claude-sonnet", "your-api-key")
player.set_model_callable(your_model_function)
results = player.play_case("riverside-robbery")
```

See `docs/ai-integration-guide.md` for details.

## Testing

```bash
python -m pytest tests/ -v
```

## Adding New Cases

See `docs/case-authoring-guide.md` for the case file format and writing guidelines.
