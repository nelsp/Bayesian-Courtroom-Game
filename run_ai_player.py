"""
Run an AI model through the Bayesian Courtroom Game.

Usage:
  1. Start the server:  cd server && python app.py
  2. Add your API key to the .env file in the project root:
       XAI_API_KEY=xai-...               (for Grok / xAI)
       ANTHROPIC_API_KEY=sk-ant-...       (for Claude)
       OPENAI_API_KEY=sk-...              (for OpenAI)
  3. Run this script:   python run_ai_player.py

The AI will play through each case, provide probability assessments with
reasoning, and submit structured feedback critiquing the game.
"""

import os
import sys
import json

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))
from ai_player import AIPlayer


# ── Pick your model ──────────────────────────────────────────────────

def make_claude_caller(api_key: str):
    """Returns a callable that sends prompts to Claude."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    def call(prompt: str) -> str:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    return call


def make_openai_caller(api_key: str):
    """Returns a callable that sends prompts to GPT-4o."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    def call(prompt: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return response.choices[0].message.content

    return call


def make_xai_caller(api_key: str):
    """Returns a callable that sends prompts to Grok via xAI's OpenAI-compatible API."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    def call(prompt: str) -> str:
        response = client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return response.choices[0].message.content

    return call


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Try Claude first, then xAI, then OpenAI
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    xai_key = os.environ.get("XAI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if anthropic_key:
        print("Using Claude (Anthropic)")
        model_name = "claude-sonnet"
        caller = make_claude_caller(anthropic_key)
    elif xai_key:
        print("Using Grok (xAI)")
        model_name = "grok-4-1-fast-reasoning"
        caller = make_xai_caller(xai_key)
    elif openai_key:
        print("Using GPT-4o (OpenAI)")
        model_name = "gpt-4o"
        caller = make_openai_caller(openai_key)
    else:
        print("ERROR: Set one of these environment variables:")
        print("  $env:ANTHROPIC_API_KEY='sk-ant-...'")
        print("  $env:XAI_API_KEY='xai-...'")
        print("  $env:OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    # Cases to play
    cases = [
        "riverside-robbery",
        "biker-bar-murder",
        "gentlemans-club-murder",
        "manor-murder",
        "jewelry-heist",
        "stolen-photos",
    ]

    player = AIPlayer(model_name, "", "http://localhost:5000")
    player.set_model_callable(caller)

    all_results = []

    for slug in cases:
        print(f"\n{'='*60}")
        print(f"Playing: {slug}")
        print(f"{'='*60}")

        try:
            results = player.play_case(slug, guilt_tolerance=100)

            verdict = results["verdict"].get("group_verdict", "Unknown")
            print(f"  Verdict: {verdict}")

            for r in results["responses"]:
                sign = "+" if r["db_update"] >= 0 else ""
                print(f"  {r['evidence_name']}: P(G)={r['prob_guilty']:.3f}, P(I)={r['prob_innocent']:.3f}, {sign}{r['db_update']:.1f} dB")
                if r.get("reasoning"):
                    print(f"    Reasoning: {r['reasoning'][:120]}...")

            fb = results.get("feedback", {})
            if fb.get("overall_rating"):
                print(f"\n  Feedback:")
                print(f"    Overall rating: {fb.get('overall_rating')}/10")
                print(f"    Narrative clarity: {fb.get('narrative_clarity', 'N/A')}/10")
                if fb.get("suggested_improvements"):
                    print(f"    Suggestions:")
                    for s in fb["suggested_improvements"]:
                        print(f"      - {s}")

            all_results.append(results)

        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    # Save all results
    output_file = os.path.join("results", f"ai_playthrough_{model_name}.json")
    os.makedirs("results", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll results saved to {output_file}")


if __name__ == "__main__":
    main()
