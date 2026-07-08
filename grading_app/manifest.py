"""Load and validate assignment manifest files (JSON)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ASSIGNMENT_FILE = Path(__file__).resolve().parent / "active_assignment.json"
DEFAULT_MANIFEST_PATH = ROOT / "assignments" / "technical_assignment_2024" / "assignment_manifest.json"

VALID_COMPARE_MODES = {"text", "csv", "xml", "image", "code", "mixed"}
VALID_MARKING_MODES = {"output_match", "semantic_code", "text_rubric", "legacy_text", "mixed"}
VALID_CORRECTNESS_METHODS = {"behavior_rules", "output_execution"}
VALID_PRACTICE_CHECKS = {
    "comments",
    "no_select_star",
    "uses_aliases",
    "reasonable_length",
    "no_hardcoded_values",
}
VALID_ENGINES = {"ast", "regex"}


@dataclass(frozen=True)
class StructureRule:
    label: str
    rule_type: str
    modules: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    pattern: str | None = None


@dataclass(frozen=True)
class CodeCheckSpec:
    engine: str
    rules: tuple[StructureRule, ...] = ()
    inherit_from: str | None = None


@dataclass(frozen=True)
class MatchRules:
    numeric_tolerance_pct: float = 1.0
    require_column_names: bool = True
    ignore_row_order: bool = True


@dataclass(frozen=True)
class CodeMarkingWeights:
    correctness: float = 0.7
    practice: float = 0.3


@dataclass(frozen=True)
class CodeMarkingCorrectness:
    method: str
    rules: tuple[StructureRule, ...] = ()
    rules_from_code_checks: bool = True
    execution: "CodeExecutionSpec | None" = None


@dataclass(frozen=True)
class CodeMarkingPractice:
    checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionFixture:
    table: str
    path: str


@dataclass(frozen=True)
class CodeExecutionSpec:
    engine: str
    fixtures: tuple[ExecutionFixture, ...] = ()
    ignore_row_order: bool = True
    numeric_tolerance_pct: float = 0.0


@dataclass(frozen=True)
class CodeMarkingSpec:
    weights: CodeMarkingWeights
    correctness: CodeMarkingCorrectness
    practice: CodeMarkingPractice


@dataclass(frozen=True)
class QuestionSpec:
    question_id: str
    label: str
    benchmark_files: tuple[str, ...]
    source_paths: tuple[str | None, ...]
    max_mark: float
    compare_mode: str
    marking_mode: str
    match_rules: MatchRules
    code_marking: CodeMarkingSpec | None
    rubric_file: str | None


@dataclass
class AssignmentManifest:
    assignment_id: str
    title: str
    version: str
    manifest_path: Path
    benchmark_dir: Path
    submissions_dir: Path
    reports_dir: Path
    allowed_extensions: set[str]
    questions: tuple[QuestionSpec, ...]
    submission_aliases: dict[str, tuple[str, ...]]
    code_checks: dict[str, CodeCheckSpec]

    @property
    def total_max_mark(self) -> float:
        return sum(question.max_mark for question in self.questions)

    def code_check_for_suffix(self, suffix: str) -> CodeCheckSpec | None:
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        spec = self.code_checks.get(suffix)
        if spec is None:
            return None
        if spec.inherit_from and not spec.rules:
            return self.code_checks.get(spec.inherit_from)
        return spec


def _optional_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Expected a list of values")
    return tuple(str(item) for item in value)


def _parse_rule(data: dict[str, Any]) -> StructureRule:
    label = str(data.get("label", "")).strip()
    if not label:
        raise ValueError("Each code-check rule requires a label")
    if "pattern" in data:
        return StructureRule(label=label, rule_type="regex", pattern=str(data["pattern"]))
    rule_type = str(data.get("type", "")).strip()
    if not rule_type:
        raise ValueError(f"Rule '{label}' requires a type or pattern")
    return StructureRule(
        label=label,
        rule_type=rule_type,
        modules=_optional_tuple(data.get("modules")),
        tokens=_optional_tuple(data.get("tokens")),
        names=_optional_tuple(data.get("names")),
    )


def _parse_code_checks(raw: dict[str, Any]) -> dict[str, CodeCheckSpec]:
    parsed: dict[str, CodeCheckSpec] = {}
    for suffix, payload in raw.items():
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        if not isinstance(payload, dict):
            raise ValueError(f"code_checks.{suffix} must be an object")
        engine = str(payload.get("engine", "")).strip().lower()
        inherit_from = payload.get("inherit_from")
        if inherit_from:
            inherit_from = str(inherit_from).lower()
            if not inherit_from.startswith("."):
                inherit_from = f".{inherit_from}"
        rules = tuple(_parse_rule(rule) for rule in payload.get("rules", []))
        if not engine and inherit_from:
            engine = parsed[inherit_from].engine if inherit_from in parsed else "regex"
        if engine not in VALID_ENGINES:
            raise ValueError(f"Unsupported code-check engine '{engine}' for {suffix}")
        if not engine and not inherit_from:
            raise ValueError(f"code_checks.{suffix} requires engine or inherit_from")
        parsed[suffix] = CodeCheckSpec(engine=engine, rules=rules, inherit_from=inherit_from)
    return parsed


def _parse_match_rules(raw: dict[str, Any] | None) -> MatchRules:
    if not raw:
        return MatchRules()
    return MatchRules(
        numeric_tolerance_pct=float(raw.get("numeric_tolerance_pct", 1.0)),
        require_column_names=bool(raw.get("require_column_names", True)),
        ignore_row_order=bool(raw.get("ignore_row_order", True)),
    )


def _parse_code_marking(raw: dict[str, Any] | None) -> CodeMarkingSpec | None:
    if not raw:
        return None
    weights_raw = raw.get("weights", {})
    correctness_raw = raw.get("correctness", {})
    practice_raw = raw.get("practice", {})
    method = str(correctness_raw.get("method", "behavior_rules")).strip().lower()
    if method not in VALID_CORRECTNESS_METHODS:
        raise ValueError(f"Unsupported correctness method '{method}'")
    rules = tuple(_parse_rule(rule) for rule in correctness_raw.get("rules", []))
    checks = _optional_tuple(practice_raw.get("checks"))
    for check in checks:
        if check not in VALID_PRACTICE_CHECKS:
            raise ValueError(f"Unsupported practice check '{check}'")
    execution_raw = correctness_raw.get("execution")
    execution = _parse_code_execution(execution_raw) if execution_raw else None
    return CodeMarkingSpec(
        weights=CodeMarkingWeights(
            correctness=float(weights_raw.get("correctness", 0.7)),
            practice=float(weights_raw.get("practice", 0.3)),
        ),
        correctness=CodeMarkingCorrectness(
            method=method,
            rules=rules,
            rules_from_code_checks=bool(correctness_raw.get("rules_from_code_checks", True)),
            execution=execution,
        ),
        practice=CodeMarkingPractice(checks=checks),
    )


def _parse_code_execution(raw: dict[str, Any]) -> CodeExecutionSpec:
    if not isinstance(raw, dict):
        raise ValueError("correctness.execution must be an object")
    engine = str(raw.get("engine", "")).strip().lower()
    if engine not in {"sqlite"}:
        raise ValueError(f"Unsupported execution engine '{engine}'")
    fixtures_raw = raw.get("fixtures", [])
    if not isinstance(fixtures_raw, list):
        raise ValueError("correctness.execution.fixtures must be a list")
    fixtures: list[ExecutionFixture] = []
    for item in fixtures_raw:
        if not isinstance(item, dict):
            raise ValueError("Each execution fixture must be an object")
        table = str(item.get("table", "")).strip()
        path = str(item.get("path", "")).strip()
        if not table or not path:
            raise ValueError("Execution fixture requires table and path")
        fixtures.append(ExecutionFixture(table=table, path=path))
    return CodeExecutionSpec(
        engine=engine,
        fixtures=tuple(fixtures),
        ignore_row_order=bool(raw.get("ignore_row_order", True)),
        numeric_tolerance_pct=float(raw.get("numeric_tolerance_pct", 0.0)),
    )


def infer_marking_mode(compare_mode: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if compare_mode in {"csv", "xml", "image"}:
        return "output_match"
    if compare_mode == "code":
        return "semantic_code"
    if compare_mode == "mixed":
        return "mixed"
    return "legacy_text"


def marking_mode_label(mode: str) -> str:
    labels = {
        "output_match": "Output match",
        "semantic_code": "Semantic code",
        "text_rubric": "Rubric text",
        "legacy_text": "Text similarity",
        "mixed": "Mixed modes",
    }
    return labels.get(mode, mode.replace("_", " ").title())


def marking_mode_for_file(question: QuestionSpec, filename: str) -> str:
    mode = question.marking_mode
    if mode != "mixed":
        return mode
    suffix = Path(filename).suffix.lower() if "." in filename else ""
    if suffix == ".csv" or suffix == ".png":
        return "output_match"
    if suffix == ".xml":
        return "output_match"
    if suffix in {".sql", ".xsl", ".xslt", ".py"}:
        return "semantic_code"
    return "legacy_text"


def _parse_questions(raw: list[dict[str, Any]]) -> tuple[QuestionSpec, ...]:
    questions: list[QuestionSpec] = []
    for item in raw:
        question_id = str(item["id"]).strip()
        label = str(item.get("label", question_id)).strip()
        max_mark = float(item.get("max_mark", 0))
        compare_mode = str(item.get("compare_mode", "text")).strip().lower()
        if compare_mode not in VALID_COMPARE_MODES:
            raise ValueError(f"Question '{question_id}' has invalid compare_mode '{compare_mode}'")
        explicit_marking = item.get("marking_mode")
        marking_mode = infer_marking_mode(
            compare_mode,
            str(explicit_marking).strip().lower() if explicit_marking else None,
        )
        if marking_mode not in VALID_MARKING_MODES:
            raise ValueError(f"Question '{question_id}' has invalid marking_mode '{marking_mode}'")
        match_rules = _parse_match_rules(item.get("match_rules"))
        code_marking = _parse_code_marking(item.get("code_marking"))
        rubric_file = item.get("rubric_file")
        rubric_file = str(rubric_file).strip() if rubric_file else None
        files = item.get("files", [])
        if not files:
            raise ValueError(f"Question '{question_id}' must define at least one file")
        benchmark_files: list[str] = []
        source_paths: list[str | None] = []
        for file_spec in files:
            if isinstance(file_spec, str):
                benchmark_files.append(file_spec)
                source_paths.append(None)
                continue
            benchmark_files.append(str(file_spec["benchmark"]))
            source_paths.append(file_spec.get("seed_from"))
        questions.append(
            QuestionSpec(
                question_id=question_id,
                label=label,
                benchmark_files=tuple(benchmark_files),
                source_paths=tuple(source_paths),
                max_mark=max_mark,
                compare_mode=compare_mode,
                marking_mode=marking_mode,
                match_rules=match_rules,
                code_marking=code_marking,
                rubric_file=rubric_file,
            )
        )
    return tuple(questions)


def _resolve_manifest_path(path: Path | str | None = None) -> Path:
    if path is not None:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else ROOT / candidate

    env_path = os.environ.get("GRADING_MANIFEST_PATH")
    if env_path:
        candidate = Path(env_path)
        return candidate if candidate.is_absolute() else ROOT / candidate

    if ACTIVE_ASSIGNMENT_FILE.exists():
        payload = json.loads(ACTIVE_ASSIGNMENT_FILE.read_text(encoding="utf-8"))
        manifest_path = payload.get("manifest_path")
        if manifest_path:
            candidate = Path(manifest_path)
            return candidate if candidate.is_absolute() else ROOT / candidate

    return DEFAULT_MANIFEST_PATH


def load_manifest(path: Path | str | None = None) -> AssignmentManifest:
    manifest_path = _resolve_manifest_path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Assignment manifest not found: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assignment_id = str(payload.get("assignment_id", manifest_path.parent.name)).strip()
    title = str(payload.get("title", assignment_id)).strip()
    version = str(payload.get("version", "1.0")).strip()

    benchmark_dir = ROOT / str(payload.get("benchmark_dir", "benchmark_files"))
    submissions_dir = ROOT / str(payload.get("submissions_dir", "student_submissions"))
    reports_dir = ROOT / str(payload.get("reports_dir", "outputs/grading_reports"))
    allowed_extensions = {str(ext).lower() for ext in payload.get("allowed_extensions", [])}
    if not allowed_extensions:
        raise ValueError("allowed_extensions must contain at least one extension")

    return AssignmentManifest(
        assignment_id=assignment_id,
        title=title,
        version=version,
        manifest_path=manifest_path,
        benchmark_dir=benchmark_dir,
        submissions_dir=submissions_dir,
        reports_dir=reports_dir,
        allowed_extensions=allowed_extensions,
        questions=_parse_questions(payload.get("questions", [])),
        submission_aliases={
            str(key): tuple(str(value) for value in values)
            for key, values in payload.get("submission_aliases", {}).items()
        },
        code_checks=_parse_code_checks(payload.get("code_checks", {})),
    )


_manifest_cache: AssignmentManifest | None = None
_manifest_cache_path: Path | None = None


def get_manifest(reload: bool = False, path: Path | str | None = None) -> AssignmentManifest:
    global _manifest_cache, _manifest_cache_path
    resolved = _resolve_manifest_path(path)
    if reload or _manifest_cache is None or _manifest_cache_path != resolved:
        _manifest_cache = load_manifest(resolved)
        _manifest_cache_path = resolved
    return _manifest_cache


def set_active_manifest(path: Path | str) -> AssignmentManifest:
    resolved = _resolve_manifest_path(path)
    try:
        relative = str(resolved.relative_to(ROOT))
    except ValueError:
        relative = str(resolved)
    ACTIVE_ASSIGNMENT_FILE.write_text(
        json.dumps({"manifest_path": relative}, indent=2) + "\n",
        encoding="utf-8",
    )
    return get_manifest(reload=True, path=resolved)
