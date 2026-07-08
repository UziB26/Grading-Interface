"""Semantic code grading: correctness via behaviour rules and practice heuristics."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from grading_app.ast_checks import build_python_ast_profile, evaluate_ast_rule
from grading_app.code_checks import run_regex_rules
from grading_app.manifest import AssignmentManifest, ROOT, CodeExecutionSpec, QuestionSpec, StructureRule


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


def _normalize_sql_for_sqlite(sql_text: str) -> str:
    # Accept common Postgres-style date literals in SQLite fixtures.
    return re.sub(r"DATE\s*'([^']+)'", r"'\1'", sql_text, flags=re.IGNORECASE)


def _resolve_fixture_path(path_value: str) -> Path:
    candidate = Path(path_value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _compare_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    ignore_row_order: bool,
    numeric_tolerance_pct: float,
) -> tuple[float, str]:
    if list(left.columns) != list(right.columns):
        return 0.0, "Execution output columns do not match benchmark output"
    if ignore_row_order and not left.empty and not right.empty:
        sort_cols = list(left.columns)
        left = left.sort_values(by=sort_cols).reset_index(drop=True)
        right = right.sort_values(by=sort_cols).reset_index(drop=True)
    row_score = min(len(left), len(right)) / max(len(left), len(right)) if max(len(left), len(right)) else 1.0
    compare_rows = min(len(left), len(right))
    if compare_rows == 0:
        return row_score, "Execution output rows are empty"

    col_scores: list[float] = []
    for col in left.columns:
        lser = left[col].iloc[:compare_rows]
        rser = right[col].iloc[:compare_rows]
        lnum = pd.to_numeric(lser, errors="coerce")
        rnum = pd.to_numeric(rser, errors="coerce")
        mask = lnum.notna() & rnum.notna()
        if mask.any():
            tol = rnum[mask].abs().clip(lower=1.0) * (numeric_tolerance_pct / 100.0)
            col_scores.append(float(((lnum[mask] - rnum[mask]).abs() <= tol).mean()))
        else:
            ltxt = lser.astype(str).str.strip().str.lower()
            rtxt = rser.astype(str).str.strip().str.lower()
            col_scores.append(float((ltxt == rtxt).mean()))
    value_score = sum(col_scores) / len(col_scores) if col_scores else 1.0
    return (row_score * 0.3 + value_score * 0.7), f"Execution output compared ({len(left)} vs {len(right)} rows)"


def _score_sql_output_execution(
    submitted: Path,
    benchmark: Path | None,
    execution: CodeExecutionSpec,
) -> tuple[float, int, int, str]:
    if benchmark is None:
        return 0.0, 0, 1, "Output execution requires a benchmark query file"
    if not execution.fixtures:
        return 0.0, 0, 1, "No execution fixtures configured"

    submitted_sql = _normalize_sql_for_sqlite(submitted.read_text(encoding="utf-8", errors="ignore"))
    benchmark_sql = _normalize_sql_for_sqlite(benchmark.read_text(encoding="utf-8", errors="ignore"))

    conn = sqlite3.connect(":memory:")
    try:
        for fixture in execution.fixtures:
            fixture_path = _resolve_fixture_path(fixture.path)
            if not fixture_path.exists():
                return 0.0, 0, 1, f"Fixture missing: {fixture.path}"
            frame = pd.read_csv(fixture_path, dtype=str, keep_default_na=False)
            frame.to_sql(fixture.table, conn, if_exists="replace", index=False)

        expected = pd.read_sql_query(benchmark_sql, conn)
        actual = pd.read_sql_query(submitted_sql, conn)
        score, detail = _compare_frames(
            actual,
            expected,
            ignore_row_order=execution.ignore_row_order,
            numeric_tolerance_pct=execution.numeric_tolerance_pct,
        )
        passed = 1 if score >= 0.9999 else 0
        return score, passed, 1, detail
    except Exception as exc:  # noqa: BLE001
        return 0.0, 0, 1, f"Output execution failed: {exc}"
    finally:
        conn.close()


def grade_semantic_code(
    submitted: Path,
    question: QuestionSpec,
    manifest: AssignmentManifest,
    benchmark: Path | None = None,
) -> SemanticCodeScore:
    """Score student code on correctness (behaviour rules) and practice heuristics."""
    rules = _resolve_correctness_rules(submitted, question, manifest)
    practice_checks = _resolve_practice_checks(submitted, question)
    correctness_weight, practice_weight = _resolve_weights(question)

    spec = question.code_marking
    if spec and spec.correctness.method == "output_execution":
        execution = spec.correctness.execution
        if submitted.suffix.lower() == ".sql" and execution and execution.engine == "sqlite":
            correctness, correctness_passed, correctness_total, correctness_details = _score_sql_output_execution(
                submitted, benchmark, execution
            )
        else:
            correctness = 0.0
            correctness_passed = 0
            correctness_total = 1
            correctness_details = "output_execution configured, but no supported execution profile for this file type"
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
