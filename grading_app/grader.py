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

from grading_app.code_checks import analyze_file_with_manifest
from grading_app.config import ROOT, get_manifest
from grading_app.ai_evaluator import evaluate_with_ai
from grading_app.manifest import QuestionSpec, marking_mode_for_file
from grading_app.semantic_code import grade_semantic_code


@dataclass
class GradeResult:
    student: str
    question: str
    question_label: str
    benchmark_file: str
    submitted_file: str
    status: str
    marking_mode: str
    similarity: float
    correctness_score: float | None
    practice_score: float | None
    correctness_method: str | None
    practice_method: str | None
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
    avg_correctness: float | None
    avg_practice: float | None
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


def numeric_series_similarity(left: pd.Series, right: pd.Series, tolerance_pct: float = 1.0) -> float:
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
    tolerances = right_num[mask].abs().clip(lower=1.0) * (tolerance_pct / 100.0)
    matches = (deltas <= tolerances).mean()
    return float(matches)


def csv_similarity(a: Path, b: Path, tolerance_pct: float = 1.0, ignore_row_order: bool = True) -> tuple[float, str]:
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

    if ignore_row_order:
        left = left.sort_values(by=list(left.columns)).reset_index(drop=True)
        right = right.sort_values(by=list(right.columns)).reset_index(drop=True)
    row_count_score = min(len(left), len(right)) / max(len(left), len(right))
    compare_rows = min(len(left), len(right))
    if compare_rows == 0:
        return 0.0, "; ".join(notes) or "No rows to compare"

    column_scores = [
        numeric_series_similarity(left.iloc[:compare_rows, idx], right.iloc[:compare_rows, idx], tolerance_pct)
        for idx, col in enumerate(left.columns)
    ]
    value_score = sum(column_scores) / len(column_scores)
    score = column_score * 0.2 + row_count_score * 0.2 + value_score * 0.6
    if row_count_score < 1.0:
        notes.append(f"Row count mismatch ({len(left)} vs {len(right)})")
    return score, "; ".join(notes) or "CSV values compared"


def compare_files(
    benchmark: Path,
    submitted: Path,
    mode: str,
    tolerance_pct: float = 1.0,
    ignore_row_order: bool = True,
) -> tuple[float, str]:
    if not benchmark.exists():
        raise FileNotFoundError(f"Benchmark not found: {benchmark}")
    if not submitted.exists():
        raise FileNotFoundError(f"Submitted file not found: {submitted}")

    try:
        suffix = benchmark.suffix.lower()
        if mode == "csv" or suffix == ".csv":
            return csv_similarity(benchmark, submitted, tolerance_pct, ignore_row_order)
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


def grade_file_item(
    student_dir: Path,
    question: QuestionSpec,
    benchmark_name: str,
    benchmark: Path,
    submitted: Path,
    max_mark: float,
    manifest,
    project_root: Path,
) -> GradeResult:
    marking_mode = marking_mode_for_file(question, benchmark_name)
    base = {
        "student": student_dir.name,
        "question": question.question_id,
        "question_label": question.label,
        "benchmark_file": str(benchmark.resolve().relative_to(project_root)),
        "submitted_file": str(submitted.resolve().relative_to(project_root)),
        "max_mark": max_mark,
        "marking_mode": marking_mode,
    }

    if marking_mode == "semantic_code":
        try:
            semantic = grade_semantic_code(submitted, question, manifest, benchmark)
            method_label = semantic.correctness_method
            notes = (
                f"Correctness mode: {method_label}; Practice mode: {semantic.practice_method}; "
                f"{semantic.correctness_details}; {semantic.practice_details}"
            )
            return GradeResult(
                **base,
                status="graded",
                similarity=semantic.combined,
                correctness_score=semantic.correctness,
                practice_score=semantic.practice,
                correctness_method=method_label,
                practice_method=semantic.practice_method,
                mark=round(semantic.combined * max_mark, 2),
                notes=notes,
            )
        except Exception as exc:
            return GradeResult(
                **base,
                status="error",
                similarity=0.0,
                correctness_score=0.0,
                practice_score=0.0,
                correctness_method=None,
                practice_method=None,
                mark=0.0,
                notes=f"Semantic grading failed: {exc}",
            )

    if marking_mode == "semantic_text":
        student_text = read_text(submitted)
        benchmark_text = read_text(benchmark)
        target_points = (
            question.benchmark_points.strip() if question.benchmark_points else benchmark_text
        )
        prompt = (
            f"[TARGET POINTS]\n{target_points}\n\n"
            f"[BENCHMARK ANSWER]\n{benchmark_text}\n\n"
            f"[STUDENT SUBMISSION]\n{student_text}"
        )
        system_instruction = (
            "You are grading semantic coverage. Score from 0.0 to 1.0 based on whether "
            "the student covered the key target points, regardless of exact wording."
        )
        try:
            ai_result = evaluate_with_ai(prompt, system_instruction)
            return GradeResult(
                **base,
                status="graded",
                similarity=ai_result.score,
                correctness_score=ai_result.score,
                practice_score=None,
                correctness_method="ai-semantic",
                practice_method=None,
                mark=round(ai_result.score * max_mark, 2),
                notes=f"Correctness mode: ai-semantic; {ai_result.feedback}",
            )
        except Exception as exc:  # noqa: BLE001
            # Safe fallback: keep grading deterministic if API isn't available.
            fallback = text_similarity(benchmark, submitted)
            return GradeResult(
                **base,
                status="graded",
                similarity=round(fallback, 4),
                correctness_score=round(fallback, 4),
                practice_score=None,
                correctness_method="fallback-text",
                practice_method=None,
                mark=round(fallback * max_mark, 2),
                notes=f"Correctness mode: fallback-text; AI unavailable: {exc}",
            )

    if marking_mode == "text_rubric":
        return GradeResult(
            **base,
            status="graded",
            similarity=0.0,
            correctness_score=None,
            practice_score=None,
            correctness_method=None,
            practice_method=None,
            mark=0.0,
            notes="Rubric text grading not yet implemented; configure legacy_text or add rubric_file",
        )

    mode = compare_mode_for_file(question, benchmark_name)
    rules = question.match_rules
    try:
        score, compare_note = compare_files(
            benchmark,
            submitted,
            mode,
            tolerance_pct=rules.numeric_tolerance_pct,
            ignore_row_order=rules.ignore_row_order,
        )
        status = "graded"
        mode_label = "Output values compared" if marking_mode == "output_match" else compare_note
        notes = mode_label if marking_mode == "output_match" else compare_note
        if marking_mode == "output_match" and compare_note:
            notes = f"{mode_label}; {compare_note}"
        return GradeResult(
            **base,
            status=status,
            similarity=round(score, 4),
            correctness_score=round(score, 4),
            practice_score=None,
            correctness_method="output-match" if marking_mode == "output_match" else None,
            practice_method=None,
            mark=round(score * max_mark, 2),
            notes=notes,
        )
    except FileNotFoundError as exc:
        return GradeResult(
            **base,
            status="missing",
            similarity=0.0,
            correctness_score=0.0,
            practice_score=None,
            correctness_method=None,
            practice_method=None,
            mark=0.0,
            notes=f"Missing: {benchmark_name} ({exc})",
        )
    except Exception as exc:
        return GradeResult(
            **base,
            status="error",
            similarity=0.0,
            correctness_score=0.0,
            practice_score=None,
            correctness_method=None,
            practice_method=None,
            mark=0.0,
            notes=f"Comparison failed: {exc}",
        )


def grade_student(student_dir: Path, mark_scale: float = 1.0) -> list[GradeResult]:
    results: list[GradeResult] = []
    student_dir = student_dir.resolve()
    project_root = ROOT.resolve()
    manifest = get_manifest()
    aliases_map = manifest.submission_aliases

    for question in manifest.questions:
        question_dir = manifest.benchmark_dir / question.question_id
        if not question_dir.exists():
            continue
        max_mark = round(question.max_mark * mark_scale, 2)
        file_count = len(question.benchmark_files)
        per_file_max = round(max_mark / file_count, 2) if file_count else max_mark
        # Keep per-question total exact when split across files (e.g. 25 / 2 = 12.5 + 12.5).
        per_file_marks = [per_file_max] * file_count
        remainder = round(max_mark - sum(per_file_marks), 2)
        if per_file_marks and remainder:
            per_file_marks[-1] = round(per_file_marks[-1] + remainder, 2)
        for file_index, benchmark_name in enumerate(question.benchmark_files):
            file_max_mark = per_file_marks[file_index]
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
                        marking_mode=marking_mode_for_file(question, benchmark_name),
                        similarity=0.0,
                        correctness_score=0.0,
                        practice_score=None,
                        correctness_method=None,
                        practice_method=None,
                        mark=0.0,
                        max_mark=file_max_mark,
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
                        marking_mode=marking_mode_for_file(question, benchmark_name),
                        similarity=0.0,
                        correctness_score=0.0,
                        practice_score=None,
                        correctness_method=None,
                        practice_method=None,
                        mark=0.0,
                        max_mark=file_max_mark,
                        notes=f"Missing: {benchmark_name}",
                    )
                )
                continue

            results.append(
                grade_file_item(
                    student_dir,
                    question,
                    benchmark_name,
                    benchmark,
                    submitted,
                    file_max_mark,
                    manifest,
                    project_root,
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
        correctness_scores = [
            result.correctness_score
            for result in student_results
            if result.correctness_score is not None
        ]
        practice_scores = [
            result.practice_score
            for result in student_results
            if result.practice_score is not None
        ]
        avg_correctness = (
            round(sum(correctness_scores) / len(correctness_scores), 4)
            if correctness_scores
            else None
        )
        avg_practice = (
            round(sum(practice_scores) / len(practice_scores), 4) if practice_scores else None
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
                avg_correctness=avg_correctness,
                avg_practice=avg_practice,
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
