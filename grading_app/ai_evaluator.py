"""Gemini-based semantic evaluator with strict JSON responses."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EvaluationResult:
    score: float
    feedback: str


def evaluate_with_ai(prompt: str, system_instruction: str) -> EvaluationResult:
    """Evaluate content with Gemini and return structured score + feedback."""
    try:
        from dotenv import load_dotenv
        from google import genai
        from google.genai import types
        from pydantic import BaseModel, Field
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "AI dependencies are missing. Run: pip install google-genai python-dotenv pydantic"
        ) from exc

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env.")

    class _Schema(BaseModel):
        score: float = Field(
            description="A score between 0.0 and 1.0 representing how well the criteria were met."
        )
        feedback: str = Field(
            description="A brief, clear explanation justifying the given score."
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=_Schema,
            temperature=0.1,
        ),
    )
    parsed = response.parsed
    if parsed is None:
        raise RuntimeError("Gemini returned no parsed payload.")
    # Keep output safe even if model drifts.
    score = max(0.0, min(1.0, float(parsed.score)))
    feedback = str(parsed.feedback or "").strip() or "No feedback returned."
    return EvaluationResult(score=score, feedback=feedback)
