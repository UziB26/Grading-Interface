"""Dynamic configuration loaded from the active assignment manifest."""

from __future__ import annotations

from pathlib import Path

from grading_app.manifest import (
    AssignmentManifest,
    CodeCheckSpec,
    QuestionSpec,
    StructureRule,
    get_manifest,
    load_manifest,
    set_active_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def get_allowed_extensions() -> set[str]:
    return get_manifest().allowed_extensions


def get_benchmark_dir() -> Path:
    return get_manifest().benchmark_dir


def get_submissions_dir() -> Path:
    return get_manifest().submissions_dir


def get_report_dir() -> Path:
    return get_manifest().reports_dir


def get_questions() -> tuple[QuestionSpec, ...]:
    return get_manifest().questions


def get_submission_aliases() -> dict[str, tuple[str, ...]]:
    return get_manifest().submission_aliases


__all__ = [
    "ROOT",
    "AssignmentManifest",
    "QuestionSpec",
    "StructureRule",
    "CodeCheckSpec",
    "get_manifest",
    "load_manifest",
    "set_active_manifest",
    "get_allowed_extensions",
    "get_benchmark_dir",
    "get_submissions_dir",
    "get_report_dir",
    "get_questions",
    "get_submission_aliases",
]
