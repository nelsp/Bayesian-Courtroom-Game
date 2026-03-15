"""
AI player adapter — orchestrates a full game session with an AI model via the REST API.
Any model that can make HTTP requests can play through this interface.
"""

import json
import requests
from typing import Dict, Optional


class AIPlayer:

    def __init__(self, model_name: str, api_key: str, server_url: str = "http://localhost:5000"):
        self.model_name = model_name
        self.api_key = api_key
        self.server_url = server_url.rstrip("/")
        self._model_call = self._default_model_call

    def set_model_callable(self, fn):
        """Override the default model call with a custom function.
        fn(prompt: str) -> str
        """
        self._model_call = fn

    def play_case(self, case_slug: str, guilt_tolerance: int = 100) -> dict:
        """
        Play through an entire case and return full results.

        1. Create game
        2. Register as AI player
        3. Read case presentation
        4. Preview all evidence
        5. Evaluate each evidence item
        6. Get verdict
        7. Submit feedback
        """
        # 1. Create game
        res = self._post("/api/games", {"case_slug": case_slug})
        game_id = res["game_id"]

        # 2. Register as AI player
        res = self._post(f"/api/games/{game_id}/player", {
            "name": f"AI-{self.model_name}",
            "guilt_tolerance": guilt_tolerance,
            "use_rating_scale": False,
            "player_type": "ai",
            "model_name": self.model_name,
        })
        player_id = res["player_id"]

        # 3. Read case
        case_res = self._get(f"/api/games/{game_id}/case")
        case_info = case_res["case_info"]
        prior_info = case_res["prior_info"]

        # 4. Preview evidence
        ev_res = self._get(f"/api/games/{game_id}/evidence")
        evidence_preview = ev_res["evidence"]

        # 5. Evaluate each evidence item
        all_responses = []
        running_db = prior_info["db"]

        for i, ev_preview in enumerate(evidence_preview):
            ev_detail = self._get(f"/api/games/{game_id}/evidence/{i}")["evidence"]

            prompt = self._build_evidence_prompt(
                case_info, prior_info, ev_detail, i,
                evidence_preview, all_responses, running_db
            )

            model_response = self._model_call(prompt)
            parsed = self._parse_model_response(model_response)

            pg = parsed.get("prob_guilty", 0.5)
            pi = parsed.get("prob_innocent", 0.5)
            reasoning = parsed.get("reasoning", "")

            submit_res = self._post(f"/api/games/{game_id}/evidence/{i}", {
                "player_id": player_id,
                "prob_guilty": pg,
                "prob_innocent": pi,
                "reasoning": reasoning,
            })

            import math
            db_update = 10 * math.log10(pg / pi) if pi > 0 else 30
            running_db += db_update

            all_responses.append({
                "evidence_name": ev_detail["name"],
                "prob_guilty": pg,
                "prob_innocent": pi,
                "db_update": db_update,
                "reasoning": reasoning,
            })

        # 6. Get verdict
        verdict_res = self._get(f"/api/games/{game_id}/verdict")

        # 7. Submit feedback
        feedback_prompt = self._build_feedback_prompt(case_info, all_responses, verdict_res)
        feedback_text = self._model_call(feedback_prompt)
        feedback_data = self._parse_feedback(feedback_text)
        feedback_data["model_name"] = self.model_name
        feedback_data["game_id"] = game_id
        feedback_data["case_slug"] = case_slug

        self._post(f"/api/games/{game_id}/feedback", feedback_data)

        return {
            "game_id": game_id,
            "case_slug": case_slug,
            "model_name": self.model_name,
            "responses": all_responses,
            "verdict": verdict_res.get("game_state", {}).get("verdict", {}),
            "feedback": feedback_data,
        }

    def _build_evidence_prompt(self, case_info, prior_info, evidence, idx,
                                all_evidence, prior_responses, running_db) -> str:
        context = f"""You are an AI juror analyzing evidence in a criminal case.

CASE: {case_info['name']}
{case_info['description']}

PRIOR PROBABILITY: {prior_info.get('odds_description', '')} ({prior_info['db']} dB)
{prior_info.get('reasoning', '')}

EVIDENCE EVALUATED SO FAR:
"""
        for r in prior_responses:
            context += f"  - {r['evidence_name']}: P(E|G)={r['prob_guilty']:.3f}, P(E|I)={r['prob_innocent']:.3f}, dB={r['db_update']:.1f}\n"

        context += f"\nCurrent running total: {running_db:.1f} dB\n"

        guidance = evidence.get("guidance", {})
        guilty_q = guidance.get("guilty_prompt", "How likely is this evidence if the defendant is guilty?")
        innocent_q = guidance.get("innocent_prompt", "How likely is this evidence if the defendant is innocent?")

        context += f"""
NOW EVALUATE EVIDENCE {idx + 1} of {len(all_evidence)}:
Name: {evidence['name']}
Description: {evidence['description']}

Questions to consider:
1. {guilty_q}
2. {innocent_q}

Respond with ONLY a JSON object:
{{"prob_guilty": <float 0.001-0.999>, "prob_innocent": <float 0.001-0.999>, "reasoning": "<brief explanation>"}}
"""
        return context

    def _build_feedback_prompt(self, case_info, all_responses, verdict_data) -> str:
        return f"""You just played through the Bayesian Courtroom Game as an AI juror.

Case: {case_info['name']}
Your evidence assessments:
{json.dumps(all_responses, indent=2)}

Verdict data: {json.dumps(verdict_data.get('game_state', {}).get('verdict', {}), indent=2)}

Provide structured feedback as a JSON object:
{{
  "overall_rating": <1-10>,
  "narrative_clarity": <1-10>,
  "evidence_quality": [
    {{"evidence_name": "...", "clarity_rating": <1-10>, "guidance_helpfulness": <1-10>, "issues": "...", "suggestion": "..."}}
  ],
  "game_flow_feedback": "...",
  "difficulty_assessment": "beginner|intermediate|advanced",
  "suggested_improvements": ["...", "..."]
}}
"""

    def _parse_model_response(self, text: str) -> dict:
        text = text.strip()
        # Try to extract JSON from the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"prob_guilty": 0.5, "prob_innocent": 0.5, "reasoning": text}

    def _parse_feedback(self, text: str) -> dict:
        parsed = self._parse_model_response(text)
        if "overall_rating" not in parsed:
            return {
                "overall_rating": 5,
                "game_flow_feedback": text,
                "suggested_improvements": [],
            }
        return parsed

    def _default_model_call(self, prompt: str) -> str:
        """Placeholder — override with set_model_callable() or subclass."""
        raise NotImplementedError(
            "Set a model callable with set_model_callable(fn) before calling play_case(). "
            "fn should accept a prompt string and return the model's response string."
        )

    def _get(self, path: str) -> dict:
        r = requests.get(self.server_url + path)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = requests.post(self.server_url + path, json=data)
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    print("AI Player adapter ready.")
    print("Usage:")
    print("  player = AIPlayer('claude-sonnet', 'your-api-key')")
    print("  player.set_model_callable(your_model_function)")
    print("  results = player.play_case('riverside-robbery')")
