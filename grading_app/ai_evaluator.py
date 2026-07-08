"""Gemini-based semantic evaluator with strict JSON responses."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Flash-Lite has a much higher free-tier daily quota than gemini-2.5-flash.
DEFAULT_MODEL = "gemini-2.5-flash-lite"
MAX_RETRIES = 3


@dataclass
class EvaluationResult:
    score: float
    feedback: str


def _load_api_key() -> str:
    """Load GEMINI_API_KEY from project .env (always overrides stale process env)."""
    try:
        from dotenv import load_dotenv
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "AI dependencies are missing. Run: pip install google-genai python-dotenv pydantic"
        ) from exc

    env_path = ROOT / ".env"
    # Prefer project .env over any older key already in the process environment.
    load_dotenv(env_path, override=True)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError(
            f"GEMINI_API_KEY is missing. Add it to {env_path} as GEMINI_API_KEY=..."
        )
    return api_key


def _resolve_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


def evaluate_with_ai(prompt: str, system_instruction: str) -> EvaluationResult:
    """Evaluate content with Gemini and return structured score + feedback."""
    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel, Field
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "AI dependencies are missing. Run: pip install google-genai python-dotenv pydantic"
        ) from exc

    api_key = _load_api_key()
    model = _resolve_model()

    class _Schema(BaseModel):
        score: float = Field(
            description="A score between 0.0 and 1.0 representing how well the criteria were met."
        )
        feedback: str = Field(
            description="A brief, clear explanation justifying the given score."
        )

    client = genai.Client(api_key=api_key)
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
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
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if _is_rate_limit_error(exc) and attempt < MAX_RETRIES:
                time.sleep(1.5 * attempt)
                continue
            break

    raise RuntimeError(
        f"Gemini API failed for model '{model}'. "
        "If this is a daily free-tier quota error, set GEMINI_MODEL=gemini-2.5-flash-lite "
        "in .env (or wait for reset / enable billing). "
        f"Details: {last_error}"
    ) from last_error
