"""Generic manifest-driven code structure checks (AST and regex)."""

from __future__ import annotations

import re
from pathlib import Path

from grading_app.ast_checks import build_python_ast_profile, evaluate_ast_rule
from grading_app.manifest import AssignmentManifest, CodeCheckSpec, StructureRule


def run_regex_rules(text: str, rules: tuple[StructureRule, ...]) -> tuple[float, int, int, str]:
    if not rules:
        return 1.0, 0, 0, "No regex rules configured"
    passed: list[str] = []
    failed: list[str] = []
    for rule in rules:
        pattern = rule.pattern or ""
        if pattern and re.search(pattern, text, flags=re.IGNORECASE):
            passed.append(rule.label)
        else:
            failed.append(rule.label)
    total = len(rules)
    score = len(passed) / total
    details = f"Passed {len(passed)}/{total}: {', '.join(passed) or 'none'}"
    if failed:
        details += f"; missing: {', '.join(failed)}"
    return score, len(passed), total, details


def run_ast_rules(source: str, filename: str, rules: tuple[StructureRule, ...]) -> tuple[bool, float, int, int, str]:
    profile, syntax_error = build_python_ast_profile(source, filename=filename)
    if profile is None:
        return False, 0.0, 0, len(rules), syntax_error or "Syntax error"
    if not rules:
        return True, 1.0, 0, 0, "No AST rules configured"

    passed: list[str] = []
    failed: list[str] = []
    for rule in rules:
        if evaluate_ast_rule(profile, rule):
            passed.append(rule.label)
        else:
            failed.append(rule.label)
    total = len(rules)
    score = len(passed) / total
    details = f"AST checks passed {len(passed)}/{total}: {', '.join(passed) or 'none'}"
    if failed:
        details += f"; missing: {', '.join(failed)}"
    return True, score, len(passed), total, details


def analyze_file_with_spec(path: Path, spec: CodeCheckSpec) -> tuple[bool, float, int, int, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if spec.engine == "ast":
        return run_ast_rules(text, path.name, spec.rules)
    score, passed, total, details = run_regex_rules(text, spec.rules)
    return True, score, passed, total, details


def analyze_file_with_manifest(path: Path, manifest: AssignmentManifest) -> tuple[bool, float, int, int, str] | None:
    spec = manifest.code_check_for_suffix(path.suffix)
    if spec is None:
        return None
    return analyze_file_with_spec(path, spec)
