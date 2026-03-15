# Case Authoring Guide

## Case File Format

Every case file must be a JSON file in the `cases/` directory conforming to `cases/schema.json`.

### Required Sections

**meta** — Metadata for filtering and display:
- `version`: Schema version (use `"1.0"`)
- `difficulty`: `"beginner"`, `"intermediate"`, or `"advanced"`
- `estimated_minutes`: Expected play time
- `tags`: Array of category strings

**case** — The narrative:
- `name`: Display title
- `summary`: One-sentence hook for the case card (≤120 chars)
- `description`: Full narrative read during case presentation
- `image`: Filename of cover image in `cases/images/`
- `population`: Number of potential suspects (determines prior)
- `setting`: Location and time

**prior** — Base rate probability:
- `db`: Prior probability in decibels
- `odds_description`: Human-readable odds (e.g., "1 in 75,000")
- `odds_numeric`: Float representation
- `reasoning`: Why this base rate was chosen

**evidence** — Array of evidence items, each with:
- `name`: Short title
- `summary`: One-line preview (shown before evaluation)
- `description`: Full description (shown during evaluation)
- `guidance.guilty_prompt`: Natural-language question framing P(E|G)
- `guidance.innocent_prompt`: Natural-language question framing P(E|I)
- `reference_probabilities` (optional): Calibrated reference values with explanation

### Writing Guidance Prompts

The guidance prompts are the most important part of the case file. They reframe abstract probability questions into concrete, natural-language scenarios.

**Bad:** "P(evidence|guilty)"
**Good:** "If the defendant actually committed this robbery, how likely is it that the store clerk would correctly pick them out of a police lineup?"

Tips:
- Start with "If the defendant..." to frame the conditional
- Reference specific details from the evidence description
- Keep to ≤3 lines of text on a phone screen
- Avoid jargon — write for non-statisticians

### Calibrating Reference Probabilities

Reference probabilities are not "correct answers" — they are calibrated benchmarks for post-game comparison. Use published research, base rates, and expert judgment.

### Example

See `cases/riverside-robbery.json` for a complete example.

### Validation

Run case validation:
```bash
cd server
python -c "from case_manager import CaseManager; cm = CaseManager('../cases'); print(cm.validate_all_cases())"
```
