"""Grading logic: file comparison, code checks, and report building."""

from __future__ import annotations

import csv
import difflib
import json
import shutil
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from grading_app.ast_checks import analyze_python_file
from grading_app.code_checks import analyze_file_with_manifest
from grading_app.config import ROOT, get_manifest
from grading_app.manifest import QuestionSpec


@dataclass
class GradeResult:
    student: str
    question: str
    question_label: str
    benchmark_file: str
    submitted_file: str
    status: str
    similarity: float
    mark: float
    max_mark: float
    notes: str


@dataclass
class CodeCheckResult:
    student: str
    file_path: str
    compiles: bool
    structure_score: float
    checks_passed: int
    checks_total: int
    details: str


@dataclass
class StudentSummary:
    student: str
    total_mark: float
    total_max: float
    percentage: float
    questions_graded: int
    questions_missing: int
    missing_files: str
    code_structure_avg: float | None


def read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def text_similarity(a: Path, b: Path) -> float:
    try:
        return difflib.SequenceMatcher(None, normalize_text(read_text(a)), normalize_text(read_text(b))).ratio()
    except OSError as exc:
        raise FileNotFoundError(str(exc)) from exc


def normalize_xml(path: Path) -> str:
    try:
        root = ET.fromstring(read_text(path))
    except ET.ParseError:
        return normalize_text(read_text(path))

    def local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def walk(element: ET.Element, depth: int = 0) -> list[str]:
        attrs = " ".join(f'{local_name(k)}="{element.attrib[k]}"' for k in sorted(element.attrib))
        text = (element.text or "").strip()
        line = f"{'  ' * depth}<{local_name(element.tag)} {attrs}>{text}"
        rows = [line]
        for child in list(element):
            rows.extend(walk(child, depth + 1))
        return rows

    return "\n".join(walk(root))


def xml_similarity(a: Path, b: Path) -> float:
    return difflib.SequenceMatcher(None, normalize_xml(a), normalize_xml(b)).ratio()


def read_csv_frame(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def numeric_series_similarity(left: pd.Series, right: pd.Series) -> float:
    left_num = pd.to_numeric(left, errors="coerce")
    right_num = pd.to_numeric(right, errors="coerce")
    if left_num.notna().sum() == 0 and right_num.notna().sum() == 0:
        left_text = left.astype(str).str.strip().str.lower()
        right_text = right.astype(str).str.strip().str.lower()
        if left_text.equals(right_text):
            return 1.0
        return difflib.SequenceMatcher(None, "\n".join(left_text), "\n".join(right_text)).ratio()

    mask = left_num.notna() & right_num.notna()
    if not mask.any():
        return 0.0
    deltas = (left_num[mask] - right_num[mask]).abs()
    tolerances = right_num[mask].abs().clip(lower=1.0) * 0.01
    matches = (deltas <= tolerances).mean()
    return float(matches)


def csv_similarity(a: Path, b: Path) -> tuple[float, str]:
    try:
        left = read_csv_frame(a)
        right = read_csv_frame(b)
    except Exception as exc:
        return text_similarity(a, b), f"CSV parse fallback: {exc}"

    notes: list[str] = []
    if list(left.columns) != list(right.columns):
        left_cols = list(left.columns)
        right_cols = list(right.columns)
        overlap = [col for col in left_cols if col in right_cols]
        if not overlap:
            return 0.0, "No matching CSV columns"
        notes.append(f"Column mismatch; comparing overlap: {', '.join(overlap)}")
        left = left[overlap]
        right = right[overlap]
        column_score = len(overlap) / max(len(left_cols), len(right_cols))
    else:
        column_score = 1.0

    if left.empty or right.empty:
        empty_score = 1.0 if left.empty and right.empty else 0.0
        return empty_score * column_score, "; ".join(notes) or "Empty CSV comparison"

    left = left.sort_values(by=list(left.columns)).reset_index(drop=True)
    right = right.sort_values(by=list(right.columns)).reset_index(drop=True)
    row_count_score = min(len(left), len(right)) / max(len(left), len(right))
    compare_rows = min(len(left), len(right))
    if compare_rows == 0:
        return 0.0, "; ".join(notes) or "No rows to compare"

    column_scores = [
        numeric_series_similarity(left.iloc[:compare_rows, idx], right.iloc[:compare_rows, idx])
        for idx, col in enumerate(left.columns)
    ]
    value_score = sum(column_scores) / len(column_scores)
    score = column_score * 0.2 + row_count_score * 0.2 + value_score * 0.6
    if row_count_score < 1.0:
        notes.append(f"Row count mismatch ({len(left)} vs {len(right)})")
    return score, "; ".join(notes) or "CSV values compared"


def compare_files(benchmark: Path, submitted: Path, mode: str) -> tuple[float, str]:
    if not benchmark.exists():
        raise FileNotFoundError(f"Benchmark not found: {benchmark}")
    if not submitted.exists():
        raise FileNotFoundError(f"Submitted file not found: {submitted}")

    try:
        suffix = benchmark.suffix.lower()
        if mode == "csv" or suffix == ".csv":
            return csv_similarity(benchmark, submitted)
        if mode == "xml" or suffix == ".xml":
            return xml_similarity(benchmark, submitted), "XML structure compared"
        if mode == "code" and suffix in {".sql", ".xsl", ".xslt"}:
            return text_similarity(benchmark, submitted), "Code/text compared"
        if mode == "image" or suffix == ".png":
            same_bytes = benchmark.read_bytes() == submitted.read_bytes()
            return (1.0 if same_bytes else 0.0), "Binary image compare"
        return text_similarity(benchmark, submitted), "Text compared"
    except FileNotFoundError:
        raise
    except Exception as exc:
        return 0.0, f"Comparison error: {exc}"


def compare_mode_for_file(question: QuestionSpec, filename: str) -> str:
    if question.compare_mode == "mixed":
        if filename.endswith(".xml"):
            return "xml"
        if filename.endswith((".xsl", ".xslt", ".sql")):
            return "code"
        return "text"
    return question.compare_mode


def find_submission_file(student_dir: Path, benchmark_name: str, aliases_map: dict[str, tuple[str, ...]]) -> Path | None:
    aliases = aliases_map.get(benchmark_name, (benchmark_name,))
    allowed_suffix = Path(benchmark_name).suffix.lower()
    candidates = [
        path
        for path in student_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == allowed_suffix
    ]
    for alias in aliases:
        alias_lower = alias.lower()
        exact = [path for path in candidates if path.name.lower() == alias_lower]
        if exact:
            return exact[0]
    stem = Path(benchmark_name).stem.lower()
    partial = [path for path in candidates if stem in path.stem.lower() and path.suffix.lower() == Path(benchmark_name).suffix.lower()]
    if partial:
        return partial[0]
    return None


def analyze_python_files(student_dir: Path, manifest) -> tuple[bool, str]:
    python_files = list(student_dir.rglob("*.py"))
    if not python_files:
        return False, "No Python files found"
    spec = manifest.code_check_for_suffix(".py")
    rules = spec.rules if spec else ()
    invalid = []
    for path in python_files:
        syntax_ok, _, _, _, details = analyze_python_file(path, rules)
        if not syntax_ok:
            invalid.append(f"{path.name}: {details}")
    if invalid:
        return False, "; ".join(invalid[:3])
    return True, f"{len(python_files)} Python file(s) parsed with AST"


def check_student_code(student_dir: Path) -> list[CodeCheckResult]:
    results: list[CodeCheckResult] = []
    student_dir = student_dir.resolve()
    project_root = ROOT.resolve()
    manifest = get_manifest()
    for path in sorted(student_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            analysis = analyze_file_with_manifest(path, manifest)
            if analysis is None:
                continue
            syntax_ok, score, passed, total, details = analysis
            results.append(
                CodeCheckResult(
                    student=student_dir.name,
                    file_path=str(path.resolve().relative_to(project_root)),
                    compiles=syntax_ok,
                    structure_score=score,
                    checks_passed=passed,
                    checks_total=total,
                    details=details,
                )
            )
        except OSError as exc:
            results.append(
                CodeCheckResult(
                    student=student_dir.name,
                    file_path=str(path),
                    compiles=False,
                    structure_score=0.0,
                    checks_passed=0,
                    checks_total=0,
                    details=f"Could not read file: {exc}",
                )
            )
    return results


def seed_benchmarks() -> list[str]:
    manifest = get_manifest()
    created: list[str] = []
    for question in manifest.questions:
        target_dir = manifest.benchmark_dir / question.question_id
        target_dir.mkdir(parents=True, exist_ok=True)
        for benchmark_name, source_rel in zip(question.benchmark_files, question.source_paths):
            if not source_rel:
                continue
            source = ROOT / source_rel
            if not source.exists():
                continue
            target = target_dir / benchmark_name
            shutil.copy2(source, target)
            created.append(str(target.relative_to(ROOT)))
    return created


def grade_student(student_dir: Path, mark_scale: float = 1.0) -> list[GradeResult]:
    results: list[GradeResult] = []
    student_dir = student_dir.resolve()
    project_root = ROOT.resolve()
    manifest = get_manifest()
    aliases_map = manifest.submission_aliases
    python_ok, python_note = analyze_python_files(student_dir, manifest)

    for question in manifest.questions:
        question_dir = manifest.benchmark_dir / question.question_id
        if not question_dir.exists():
            continue
        max_mark = round(question.max_mark * mark_scale, 2)
        for benchmark_name in question.benchmark_files:
            benchmark = question_dir / benchmark_name
            if not benchmark.exists():
                continue
            submitted = find_submission_file(student_dir, benchmark_name, aliases_map)
            if submitted is None:
                results.append(
                    GradeResult(
                        student=student_dir.name,
                        question=question.question_id,
                        question_label=question.label,
                        benchmark_file=str(benchmark.resolve().relative_to(project_root)),
                        submitted_file="",
                        status="missing",
                        similarity=0.0,
                        mark=0.0,
                        max_mark=max_mark,
                        notes=f"Missing: {benchmark_name}",
                    )
                )
                continue

            if not submitted.exists():
                results.append(
                    GradeResult(
                        student=student_dir.name,
                        question=question.question_id,
                        question_label=question.label,
                        benchmark_file=str(benchmark.resolve().relative_to(project_root)),
                        submitted_file=str(submitted.resolve().relative_to(project_root)),
                        status="missing",
                        similarity=0.0,
                        mark=0.0,
                        max_mark=max_mark,
                        notes=f"Missing: {benchmark_name}",
                    )
                )
                continue

            mode = compare_mode_for_file(question, benchmark_name)
            try:
                score, compare_note = compare_files(benchmark, submitted, mode)
                status = "graded"
                notes = compare_note
            except FileNotFoundError as exc:
                score = 0.0
                status = "missing"
                notes = f"Missing: {benchmark_name} ({exc})"
            except Exception as exc:
                score = 0.0
                status = "error"
                notes = f"Comparison failed: {exc}"

            mark = round(score * max_mark, 2)
            if status == "graded" and (benchmark.suffix.lower() == ".py" or submitted.suffix.lower() == ".py"):
                notes = f"{notes}; {python_note}"
                if not python_ok:
                    mark = min(mark, max_mark * 0.5)
            results.append(
                GradeResult(
                    student=student_dir.name,
                    question=question.question_id,
                    question_label=question.label,
                    benchmark_file=str(benchmark.resolve().relative_to(project_root)),
                    submitted_file=str(submitted.resolve().relative_to(project_root)),
                    status=status,
                    similarity=round(score, 4),
                    mark=mark,
                    max_mark=max_mark,
                    notes=notes,
                )
            )
    return results


def build_student_summaries(
    results: list[GradeResult],
    code_checks: list[CodeCheckResult],
) -> list[StudentSummary]:
    summaries: list[StudentSummary] = []
    students = sorted({result.student for result in results} | {check.student for check in code_checks})
    for student in students:
        student_results = [result for result in results if result.student == student]
        total_mark = round(sum(result.mark for result in student_results), 2)
        total_max = round(sum(result.max_mark for result in student_results), 2)
        percentage = round((total_mark / total_max) * 100, 2) if total_max else 0.0
        missing = sum(1 for result in student_results if result.status == "missing")
        missing_files = ", ".join(
            Path(result.benchmark_file).name
            for result in student_results
            if result.status == "missing"
        )
        student_code = [check for check in code_checks if check.student == student]
        code_avg = (
            round(sum(check.structure_score for check in student_code) / len(student_code), 4)
            if student_code
            else None
        )
        summaries.append(
            StudentSummary(
                student=student,
                total_mark=total_mark,
                total_max=total_max,
                percentage=percentage,
                questions_graded=len(student_results),
                questions_missing=missing,
                missing_files=missing_files,
                code_structure_avg=code_avg,
            )
        )
    return summaries


def write_reports(
    results: list[GradeResult],
    summaries: list[StudentSummary],
    code_checks: list[CodeCheckResult],
) -> dict[str, Path]:
    manifest = get_manifest()
    report_dir = manifest.reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    detail_csv = report_dir / "summary_report.csv"
    totals_csv = report_dir / "student_totals.csv"
    code_csv = report_dir / "code_checks.csv"
    detail_json = report_dir / "summary_report.json"

    with detail_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(GradeResult.__dataclass_fields__.keys()))
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)

    with totals_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(StudentSummary.__dataclass_fields__.keys()))
        writer.writeheader()
        writer.writerows(asdict(summary) for summary in summaries)

    with code_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CodeCheckResult.__dataclass_fields__.keys()))
        writer.writeheader()
        writer.writerows(asdict(check) for check in code_checks)

    detail_json.write_text(
        json.dumps(
            {
                "assignment": {
                    "id": manifest.assignment_id,
                    "title": manifest.title,
                    "version": manifest.version,
                    "manifest_path": str(manifest.manifest_path.relative_to(ROOT))
                    if manifest.manifest_path.is_relative_to(ROOT)
                    else str(manifest.manifest_path),
                    "total_max_mark": manifest.total_max_mark,
                },
                "results": [asdict(result) for result in results],
                "summaries": [asdict(summary) for summary in summaries],
                "code_checks": [asdict(check) for check in code_checks],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "detail_csv": detail_csv,
        "totals_csv": totals_csv,
        "code_csv": code_csv,
        "detail_json": detail_json,
    }
