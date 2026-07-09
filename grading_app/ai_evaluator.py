"""Gemini-based semantic evaluator with strict JSON responses."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Flash-Lite has a much higher free-tier daily quota than gemini-2.5-flash.
DEFAULT_MODEL = "gemini-2.5-flash-lite"
MAX_RETRIES = 3
DEFAULT_AI_MAX_CONCURRENCY = 2
DEFAULT_AI_REQUEST_TIMEOUT_SECONDS = 30.0

_sync_call_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="gemini-sync",
)

_async_ai_semaphore: asyncio.Semaphore | None = None
_async_ai_limit: int | None = None
_sync_ai_semaphore: threading.BoundedSemaphore | None = None
_sync_ai_limit: int | None = None


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
    load_dotenv(env_path, override=True)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError(
            f"GEMINI_API_KEY is missing. Add it to {env_path} as GEMINI_API_KEY=..."
        )
    return api_key


def _resolve_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _max_ai_concurrency() -> int:
    raw = os.environ.get("AI_MAX_CONCURRENCY", str(DEFAULT_AI_MAX_CONCURRENCY)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_AI_MAX_CONCURRENCY


def _request_timeout_seconds() -> float:
    raw = os.environ.get(
        "AI_REQUEST_TIMEOUT_SECONDS",
        str(DEFAULT_AI_REQUEST_TIMEOUT_SECONDS),
    ).strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return DEFAULT_AI_REQUEST_TIMEOUT_SECONDS


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, concurrent.futures.TimeoutError)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _get_async_ai_semaphore() -> asyncio.Semaphore:
    global _async_ai_semaphore, _async_ai_limit
    limit = _max_ai_concurrency()
    if _async_ai_semaphore is None or _async_ai_limit != limit:
        _async_ai_semaphore = asyncio.Semaphore(limit)
        _async_ai_limit = limit
    return _async_ai_semaphore


def _sync_ai_slot() -> threading.BoundedSemaphore:
    global _sync_ai_semaphore, _sync_ai_limit
    limit = _max_ai_concurrency()
    if _sync_ai_semaphore is None or _sync_ai_limit != limit:
        _sync_ai_semaphore = threading.BoundedSemaphore(limit)
        _sync_ai_limit = limit
    return _sync_ai_semaphore


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


def _retry_delay_seconds(exc: Exception) -> float | None:
    text = str(exc)
    for pattern in (
        r"Please retry in ([\d.]+)s",
        r"'retryDelay': '(\d+)s'",
        r"retry in ([\d.]+)ms",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        value = float(match.group(1))
        if "ms" in pattern:
            return max(0.5, value / 1000.0)
        return max(0.5, value)
    return None


def format_ai_error(exc: Exception, *, model: str | None = None) -> str:
    """Return a short, UI-friendly AI failure message."""
    resolved_model = model or _resolve_model()
    text = str(exc)
    if _is_rate_limit_error(exc):
        if "perday" in text.lower() or "per day" in text.lower() or "daily" in text.lower():
            return (
                f"Gemini daily quota exceeded for model '{resolved_model}'. "
                "Wait for reset, enable billing, or grade with rules/text fallback."
            )
        return (
            f"Gemini rate limit hit for model '{resolved_model}'. "
            "Reduce AI_MAX_CONCURRENCY or retry shortly."
        )
    if "401" in text or "unauthenticated" in text.lower():
        return "Gemini authentication failed. Check GEMINI_API_KEY in .env."
    if _is_timeout_error(exc):
        return (
            f"Gemini request timed out after {_request_timeout_seconds():.0f}s "
            f"for model '{resolved_model}'. Check API key/network or increase "
            "AI_REQUEST_TIMEOUT_SECONDS."
        )
    compact = " ".join(text.split())
    if len(compact) > 220:
        compact = compact[:217] + "..."
    return f"Gemini API failed for model '{resolved_model}': {compact}"


def _call_gemini(
    client,
    types,
    schema,
    *,
    model: str,
    prompt: str,
    system_instruction: str,
):
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1,
        ),
    )


async def _call_gemini_async(
    client,
    types,
    schema,
    *,
    model: str,
    prompt: str,
    system_instruction: str,
):
    return await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1,
        ),
    )


def _parse_gemini_response(response) -> EvaluationResult:
    parsed = response.parsed
    if parsed is None:
        raise RuntimeError("Gemini returned no parsed payload.")
    score = max(0.0, min(1.0, float(parsed.score)))
    feedback = str(parsed.feedback or "").strip() or "No feedback returned."
    return EvaluationResult(score=score, feedback=feedback)


def _call_gemini_timed(
    client,
    types,
    schema,
    *,
    model: str,
    prompt: str,
    system_instruction: str,
):
    timeout = _request_timeout_seconds()
    future = _sync_call_executor.submit(
        _call_gemini,
        client,
        types,
        schema,
        model=model,
        prompt=prompt,
        system_instruction=system_instruction,
    )
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"Gemini request timed out after {timeout:.0f}s") from exc


async def _call_gemini_timed_async(
    client,
    types,
    schema,
    *,
    model: str,
    prompt: str,
    system_instruction: str,
):
    timeout = _request_timeout_seconds()
    try:
        return await asyncio.wait_for(
            _call_gemini_async(
                client,
                types,
                schema,
                model=model,
                prompt=prompt,
                system_instruction=system_instruction,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"Gemini request timed out after {timeout:.0f}s") from exc


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

    with _sync_ai_slot():
        client = genai.Client(api_key=api_key)
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = _call_gemini_timed(
                    client,
                    types,
                    _Schema,
                    model=model,
                    prompt=prompt,
                    system_instruction=system_instruction,
                )
                return _parse_gemini_response(response)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _is_rate_limit_error(exc) and not _is_timeout_error(exc) and attempt < MAX_RETRIES:
                    delay = _retry_delay_seconds(exc) or (1.5 * attempt)
                    time.sleep(delay)
                    continue
                break

    raise RuntimeError(format_ai_error(last_error or RuntimeError("unknown error"), model=model)) from last_error


async def async_evaluate_with_ai(prompt: str, system_instruction: str) -> EvaluationResult:
    """Async Gemini evaluation for concurrent grading workloads."""
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

    semaphore = _get_async_ai_semaphore()
    async with semaphore:
        client = genai.Client(api_key=api_key)
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await _call_gemini_timed_async(
                    client,
                    types,
                    _Schema,
                    model=model,
                    prompt=prompt,
                    system_instruction=system_instruction,
                )
                return _parse_gemini_response(response)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _is_rate_limit_error(exc) and not _is_timeout_error(exc) and attempt < MAX_RETRIES:
                    delay = _retry_delay_seconds(exc) or (1.5 * attempt)
                    await asyncio.sleep(delay)
                    continue
                break

    raise RuntimeError(format_ai_error(last_error or RuntimeError("unknown error"), model=model)) from last_error
