"""Semantic code grading: correctness via behaviour rules and practice heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from grading_app.ast_checks import build_python_ast_profile, evaluate_ast_rule
from grading_app.code_checks import run_regex_rules
from grading_app.manifest import AssignmentManifest, QuestionSpec, StructureRule


@dataclass
class SemanticCodeScore:
    correctness: float
    practice: float
    combined: float
    correctness_passed: int
    correctness_total: int
    practice_passed: int
    practice_total: int
    correctness_details: str
    practice_details: str


def _default_practice_checks(suffix: str) -> tuple[str, ...]:
    if suffix == ".sql":
        return ("comments", "no_select_star", "uses_aliases", "reasonable_length")
    if suffix in {".py"}:
        return ("comments", "reasonable_length")
    if suffix in {".xsl", ".xslt"}:
        return ("comments", "reasonable_length")
    return ("comments", "reasonable_length")


def _resolve_correctness_rules(
    path: Path,
    question: QuestionSpec,
    manifest: AssignmentManifest,
) -> tuple[StructureRule, ...]:
    spec = question.code_marking
    if spec and spec.correctness.rules:
        return spec.correctness.rules
    if spec and not spec.correctness.rules_from_code_checks:
        return ()
    code_spec = manifest.code_check_for_suffix(path.suffix)
    if code_spec and code_spec.rules:
        return code_spec.rules
    return ()


def _resolve_practice_checks(path: Path, question: QuestionSpec) -> tuple[str, ...]:
    spec = question.code_marking
    if spec and spec.practice.checks:
        return spec.practice.checks
    return _default_practice_checks(path.suffix.lower())


def _resolve_weights(question: QuestionSpec) -> tuple[float, float]:
    if question.code_marking:
        weights = question.code_marking.weights
        total = weights.correctness + weights.practice
        if total <= 0:
            return 0.7, 0.3
        return weights.correctness / total, weights.practice / total
    return 0.7, 0.3


def _score_behavior_rules(path: Path, rules: tuple[StructureRule, ...]) -> tuple[float, int, int, str]:
    if not rules:
        return 1.0, 0, 0, "No behaviour rules configured; full correctness assumed"

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".py":
        profile, syntax_error = build_python_ast_profile(text, filename=path.name)
        if profile is None:
            return 0.0, 0, len(rules), syntax_error or "Syntax error"
        passed = [rule.label for rule in rules if evaluate_ast_rule(profile, rule)]
        failed = [rule.label for rule in rules if rule.label not in passed]
        total = len(rules)
        score = len(passed) / total
        details = f"Behaviour {len(passed)}/{total}: {', '.join(passed) or 'none'}"
        if failed:
            details += f"; missing: {', '.join(failed)}"
        return score, len(passed), total, details

    score, passed_count, total, details = run_regex_rules(text, rules)
    return score, passed_count, total, f"Behaviour {details}"


def _check_comments(text: str, suffix: str) -> tuple[bool, str]:
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return False, "no content"
    comment_patterns = {
        ".sql": (r"--", r"/\*"),
        ".py": (r"#", r'"""', r"'''"),
        ".xsl": (r"<!--",),
        ".xslt": (r"<!--",),
    }
    patterns = comment_patterns.get(suffix, (r"#", r"--", r"<!--"))
    comment_lines = sum(
        1 for line in non_empty if any(re.search(pat, line) for pat in patterns)
    )
    ratio = comment_lines / len(non_empty)
    if ratio >= 0.05:
        return True, f"{comment_lines} comment line(s)"
    if comment_lines > 0:
        return True, f"{comment_lines} comment line(s) (sparse)"
    return False, "no comments found"


def _check_no_select_star(text: str) -> tuple[bool, str]:
    if re.search(r"SELECT\s+\*", text, flags=re.IGNORECASE):
        return False, "uses SELECT *"
    return True, "no SELECT *"


def _check_uses_aliases(text: str, suffix: str) -> tuple[bool, str]:
    if suffix != ".sql":
        return True, "n/a"
    if re.search(r"\bAS\s+\w+", text, flags=re.IGNORECASE):
        return True, "uses column aliases"
    return False, "no AS aliases"


def _check_reasonable_length(text: str, suffix: str) -> tuple[bool, str]:
    lines = [line for line in text.splitlines() if line.strip()]
    limits = {".sql": 120, ".py": 400, ".xsl": 200, ".xslt": 200}
    limit = limits.get(suffix, 250)
    if len(lines) <= limit:
        return True, f"{len(lines)} lines (limit {limit})"
    return False, f"{len(lines)} lines exceeds {limit}"


def _check_no_hardcoded_values(text: str, suffix: str) -> tuple[bool, str]:
    if suffix != ".sql":
        return True, "n/a"
    literals = re.findall(r"=\s*'[^']+'", text, flags=re.IGNORECASE)
    if len(literals) > 5:
        return False, f"{len(literals)} hardcoded string filters"
    return True, "acceptable literal usage"


PRACTICE_CHECKERS = {
    "comments": lambda text, suffix: _check_comments(text, suffix),
    "no_select_star": lambda text, suffix: _check_no_select_star(text),
    "uses_aliases": lambda text, suffix: _check_uses_aliases(text, suffix),
    "reasonable_length": lambda text, suffix: _check_reasonable_length(text, suffix),
    "no_hardcoded_values": lambda text, suffix: _check_no_hardcoded_values(text, suffix),
}


def _score_practice(path: Path, checks: tuple[str, ...]) -> tuple[float, int, int, str]:
    if not checks:
        return 1.0, 0, 0, "No practice checks configured"

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")
    passed: list[str] = []
    failed: list[str] = []

    for check_name in checks:
        checker = PRACTICE_CHECKERS.get(check_name)
        if checker is None:
            failed.append(check_name)
            continue
        ok, detail = checker(text, suffix)
        label = f"{check_name} ({detail})"
        if ok:
            passed.append(label)
        else:
            failed.append(label)

    total = len(checks)
    score = len(passed) / total if total else 1.0
    details = f"Practice {len(passed)}/{total}: {', '.join(passed) or 'none'}"
    if failed:
        details += f"; issues: {', '.join(failed)}"
    return score, len(passed), total, details


def grade_semantic_code(
    submitted: Path,
    question: QuestionSpec,
    manifest: AssignmentManifest,
    benchmark: Path | None = None,
) -> SemanticCodeScore:
    """Score student code on correctness (behaviour rules) and practice heuristics."""
    del benchmark  # reserved for future output-execution method
    rules = _resolve_correctness_rules(submitted, question, manifest)
    practice_checks = _resolve_practice_checks(submitted, question)
    correctness_weight, practice_weight = _resolve_weights(question)

    spec = question.code_marking
    if spec and spec.correctness.method == "output_execution":
        correctness = 0.0
        correctness_passed = 0
        correctness_total = 0
        correctness_details = "output_execution not yet implemented; configure behaviour_rules"
    else:
        correctness, correctness_passed, correctness_total, correctness_details = _score_behavior_rules(
            submitted, rules
        )

    practice, practice_passed, practice_total, practice_details = _score_practice(
        submitted, practice_checks
    )
    combined = correctness * correctness_weight + practice * practice_weight

    return SemanticCodeScore(
        correctness=round(correctness, 4),
        practice=round(practice, 4),
        combined=round(combined, 4),
        correctness_passed=correctness_passed,
        correctness_total=correctness_total,
        practice_passed=practice_passed,
        practice_total=practice_total,
        correctness_details=correctness_details,
        practice_details=practice_details,
    )
