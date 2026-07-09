"""Semantic code grading: correctness via behaviour rules and practice heuristics."""

from __future__ import annotations

import re
import sqlite3
import difflib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from lxml import etree

from grading_app.ast_checks import build_python_ast_profile, evaluate_ast_rule
from grading_app.code_checks import run_regex_rules
from grading_app.manifest import AssignmentManifest, ROOT, CodeExecutionSpec, QuestionSpec, StructureRule
from grading_app.ai_evaluator import evaluate_with_ai, format_ai_error


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
    correctness_method: str
    practice_method: str


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


def _score_practice_ai(submitted: Path, benchmark: Path | None) -> tuple[float, str]:
    student_code = submitted.read_text(encoding="utf-8", errors="ignore")
    benchmark_code = (
        benchmark.read_text(encoding="utf-8", errors="ignore") if benchmark and benchmark.exists() else ""
    )
    language = submitted.suffix.lower().lstrip(".") or "code"
    prompt = (
        f"[LANGUAGE]\n{language}\n\n"
        f"[BENCHMARK CODE]\n{benchmark_code or '(not provided)'}\n\n"
        f"[STUDENT CODE]\n{student_code}"
    )
    system_instruction = (
        "You grade coding practice/quality only (not functional correctness). "
        "Score from 0.0 to 1.0 based on clarity, comments/explanation, structure, "
        "naming, and reasonable efficiency. Keep feedback brief."
    )
    result = evaluate_with_ai(prompt, system_instruction)
    return result.score, result.feedback


def _score_practice_hybrid(
    submitted: Path,
    question: QuestionSpec,
    benchmark: Path | None,
) -> tuple[float, int, int, str, str]:
    checks = _resolve_practice_checks(submitted, question)
    rules_score, passed, total, rules_details = _score_practice(submitted, checks)
    practice_cfg = question.code_marking.practice if question.code_marking else None
    method = practice_cfg.method if practice_cfg else "rules"

    if method == "rules":
        return rules_score, passed, total, rules_details, "rules"

    if method == "ai":
        try:
            ai_score, ai_feedback = _score_practice_ai(submitted, benchmark)
            details = f"Practice AI: {ai_feedback}"
            return ai_score, 1 if ai_score >= 0.5 else 0, 1, details, "ai"
        except Exception as exc:  # noqa: BLE001
            details = f"{rules_details}; AI practice unavailable: {format_ai_error(exc)}"
            return rules_score, passed, total, details, "rules-fallback"

    # hybrid
    rules_weight = practice_cfg.rules_weight if practice_cfg else 0.5
    ai_weight = practice_cfg.ai_weight if practice_cfg else 0.5
    try:
        ai_score, ai_feedback = _score_practice_ai(submitted, benchmark)
        combined = rules_score * rules_weight + ai_score * ai_weight
        details = (
            f"Practice hybrid (rules {rules_weight:.0%}/AI {ai_weight:.0%}): "
            f"rules={rules_score:.2f}; AI={ai_score:.2f}; {rules_details}; AI feedback: {ai_feedback}"
        )
        return combined, passed, total, details, "hybrid"
    except Exception as exc:  # noqa: BLE001
        details = f"{rules_details}; AI practice unavailable (used rules only): {format_ai_error(exc)}"
        return rules_score, passed, total, details, "rules-fallback"


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


def _normalize_xml_text(xml_text: str) -> str:
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return " ".join(xml_text.split())

    def local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def walk(element: etree._Element, depth: int = 0) -> list[str]:
        attrs = " ".join(f'{local_name(k)}="{element.attrib[k]}"' for k in sorted(element.attrib))
        text = (element.text or "").strip()
        rows = [f"{'  ' * depth}<{local_name(element.tag)} {attrs}>{text}"]
        for child in element:
            rows.extend(walk(child, depth + 1))
        return rows

    return "\n".join(walk(root))


def _score_xslt_output_execution(
    submitted: Path,
    benchmark: Path | None,
    execution: CodeExecutionSpec,
) -> tuple[float, int, int, str]:
    if benchmark is None:
        return 0.0, 0, 1, "Output execution requires a benchmark transform file"
    if not execution.input_path:
        return 0.0, 0, 1, "XSLT output execution requires execution.input_path"

    input_path = _resolve_fixture_path(execution.input_path)
    if not input_path.exists():
        return 0.0, 0, 1, f"XSLT input fixture missing: {execution.input_path}"

    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    access_control = etree.XSLTAccessControl(
        read_file=False,
        write_file=False,
        create_dir=False,
        read_network=False,
        write_network=False,
    )
    try:
        input_doc_expected = etree.parse(str(input_path), parser)
        input_doc_actual = etree.parse(str(input_path), parser)
        benchmark_xslt = etree.XSLT(etree.parse(str(benchmark), parser), access_control=access_control)
        submitted_xslt = etree.XSLT(etree.parse(str(submitted), parser), access_control=access_control)
        expected_xml = str(benchmark_xslt(input_doc_expected))
        actual_xml = str(submitted_xslt(input_doc_actual))
        expected_norm = _normalize_xml_text(expected_xml)
        actual_norm = _normalize_xml_text(actual_xml)
        similarity = difflib.SequenceMatcher(None, actual_norm, expected_norm).ratio()
        passed = 1 if similarity >= 0.9999 else 0
        return float(similarity), passed, 1, f"XSLT output compared ({similarity * 100:.1f}% similarity)"
    except Exception as exc:  # noqa: BLE001
        return 0.0, 0, 1, f"XSLT output execution failed: {exc}"


def _run_python_file(script_path: Path, stdin_text: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
            cwd=str(script_path.parent),
        )
    except subprocess.TimeoutExpired:
        return False, "Python execution timed out after 8s"
    except Exception as exc:  # noqa: BLE001
        return False, f"Python execution failed: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        return False, f"Python script exited with code {proc.returncode}: {err or 'no stderr output'}"
    return True, (proc.stdout or "").strip()


def _score_python_output_execution(
    submitted: Path,
    benchmark: Path | None,
    execution: CodeExecutionSpec,
) -> tuple[float, int, int, str]:
    if benchmark is None:
        return 0.0, 0, 1, "Output execution requires a benchmark Python file"
    if benchmark.suffix.lower() != ".py":
        return 0.0, 0, 1, f"Benchmark for python execution must be .py, got {benchmark.suffix or '(none)'}"

    stdin_text = ""
    if execution.input_path:
        input_path = _resolve_fixture_path(execution.input_path)
        if not input_path.exists():
            return 0.0, 0, 1, f"Python input fixture missing: {execution.input_path}"
        stdin_text = input_path.read_text(encoding="utf-8", errors="ignore")

    ok_expected, expected = _run_python_file(benchmark, stdin_text)
    if not ok_expected:
        return 0.0, 0, 1, f"Benchmark python execution failed: {expected}"

    ok_actual, actual = _run_python_file(submitted, stdin_text)
    if not ok_actual:
        return 0.0, 0, 1, f"Student python execution failed: {actual}"

    ratio = difflib.SequenceMatcher(None, actual, expected).ratio()
    passed = 1 if ratio >= 0.9999 else 0
    detail = f"Python output compared ({ratio * 100:.1f}% similarity)"
    return float(ratio), passed, 1, detail


def grade_semantic_code(
    submitted: Path,
    question: QuestionSpec,
    manifest: AssignmentManifest,
    benchmark: Path | None = None,
) -> SemanticCodeScore:
    """Score student code on correctness (behaviour rules) and practice heuristics."""
    rules = _resolve_correctness_rules(submitted, question, manifest)
    correctness_weight, practice_weight = _resolve_weights(question)

    spec = question.code_marking
    if spec and spec.correctness.method == "output_execution":
        execution = spec.correctness.execution
        correctness_method = "execution-based"
        if submitted.suffix.lower() == ".sql" and execution and execution.engine == "sqlite":
            correctness, correctness_passed, correctness_total, correctness_details = _score_sql_output_execution(
                submitted, benchmark, execution
            )
        elif submitted.suffix.lower() in {".xsl", ".xslt"} and execution and execution.engine == "xslt":
            correctness, correctness_passed, correctness_total, correctness_details = _score_xslt_output_execution(
                submitted, benchmark, execution
            )
        elif submitted.suffix.lower() == ".py" and execution and execution.engine == "python":
            correctness, correctness_passed, correctness_total, correctness_details = _score_python_output_execution(
                submitted, benchmark, execution
            )
        else:
            correctness = 0.0
            correctness_passed = 0
            correctness_total = 1
            correctness_details = "output_execution configured, but no supported execution profile for this file type"
    else:
        correctness_method = "rule-based"
        correctness, correctness_passed, correctness_total, correctness_details = _score_behavior_rules(
            submitted, rules
        )

    practice, practice_passed, practice_total, practice_details, practice_method = _score_practice_hybrid(
        submitted, question, benchmark
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
        correctness_method=correctness_method,
        practice_method=practice_method,
    )
