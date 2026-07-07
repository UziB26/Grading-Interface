"""Flask grading interface for student assignment submissions."""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grading_app.config import (  # noqa: E402
    get_benchmark_dir,
    get_manifest,
    get_report_dir,
    get_submissions_dir,
)
from grading_app.manifest import load_manifest, set_active_manifest  # noqa: E402
from grading_app.grader import (  # noqa: E402
    CodeCheckResult,
    GradeResult,
    StudentSummary,
    build_student_summaries,
    check_student_code,
    grade_student,
    seed_benchmarks as copy_solution_benchmarks,
    write_reports,
)
from grading_app.upload_security import UploadValidationError  # noqa: E402

app = Flask(__name__)
app.secret_key = "assignment-grading-local-dev"


def ensure_directories() -> None:
    manifest = get_manifest()
    for path in [manifest.benchmark_dir, manifest.submissions_dir, manifest.reports_dir]:
        path.mkdir(parents=True, exist_ok=True)


def save_upload(file_storage, target_dir: Path) -> Path:
    from grading_app.upload_security import (
        UploadValidationError,
        safe_extract_zip,
        validate_upload_filename,
    )

    original_name = file_storage.filename or ""
    filename = validate_upload_filename(original_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    file_storage.save(path)
    if path.suffix.lower() == ".zip":
        extract_dir = target_dir / path.stem
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        safe_extract_zip(path, extract_dir)
    return path


def list_available_manifests() -> list[str]:
    manifests = []
    assignments_root = ROOT / "assignments"
    if assignments_root.exists():
        for path in sorted(assignments_root.rglob("assignment_manifest.json")):
            manifests.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return manifests


def save_manifest_upload(file_storage, assignment_slug: str) -> Path:
    filename = secure_filename(file_storage.filename or "")
    if not filename.lower().endswith(".json"):
        raise UploadValidationError("Manifest file must be a .json file.")
    if not assignment_slug:
        raise UploadValidationError("Assignment folder name is required.")
    safe_slug = secure_filename(assignment_slug)
    if not safe_slug:
        raise UploadValidationError("Assignment folder name is invalid.")

    assignment_dir = ROOT / "assignments" / safe_slug
    assignment_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = assignment_dir / "assignment_manifest.json"
    file_storage.save(manifest_path)
    # Validate schema/content before activating.
    load_manifest(manifest_path)
    return manifest_path


def extract_benchmarks_zip(zip_file_storage, benchmark_dir: Path, allowed_extensions: set[str]) -> int:
    zip_name = secure_filename(zip_file_storage.filename or "")
    if not zip_name.lower().endswith(".zip"):
        raise UploadValidationError("Benchmark archive must be a .zip file.")

    temp_zip = benchmark_dir / "_uploaded_benchmarks.zip"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    zip_file_storage.save(temp_zip)
    extracted_count = 0

    try:
        with zipfile.ZipFile(temp_zip) as archive:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                target = (benchmark_dir / member).resolve()
                benchmark_root = benchmark_dir.resolve()
                if benchmark_root not in target.parents and target != benchmark_root:
                    raise UploadValidationError(f"Unsafe path in benchmarks zip: {member}")
                ext = Path(member).suffix.lower()
                if ext and ext not in allowed_extensions:
                    raise UploadValidationError(f"Disallowed file extension in zip: {member}")
            archive.extractall(benchmark_dir)
            extracted_count = sum(1 for name in archive.namelist() if not name.endswith("/"))
    finally:
        if temp_zip.exists():
            temp_zip.unlink()

    return extracted_count


def clear_directory_contents(path: Path) -> int:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
            removed += 1
        elif child.is_file():
            child.unlink()
            removed += 1
    return removed


def load_latest_reports() -> tuple[list[GradeResult], list[StudentSummary], list[CodeCheckResult]]:
    latest_json = get_report_dir() / "summary_report.json"
    if not latest_json.exists():
        return [], [], []
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    results = []
    for item in payload.get("results", []):
        if "status" not in item:
            item["status"] = "missing" if not item.get("submitted_file") else "graded"
        results.append(GradeResult(**item))
    summaries = []
    for item in payload.get("summaries", []):
        item.setdefault("missing_files", "")
        summaries.append(StudentSummary(**item))
    code_checks = [CodeCheckResult(**item) for item in payload.get("code_checks", [])]
    return results, summaries, code_checks


@app.route("/")
def index():
    ensure_directories()
    manifest = get_manifest()
    benchmarks = [
        str(path.relative_to(manifest.benchmark_dir))
        for path in sorted(manifest.benchmark_dir.rglob("*"))
        if path.is_file()
    ]
    students = [path.name for path in sorted(manifest.submissions_dir.iterdir()) if path.is_dir()]
    results, summaries, code_checks = load_latest_reports()
    summary_columns = [
        ("student", "Student"),
        ("total_mark", "Total"),
        ("total_max", "Max"),
        ("percentage", "Percent"),
        ("missing_files", "Missing Files"),
        ("code_structure_avg", "Code Checks"),
    ]
    result_columns = [
        ("student", "Student"),
        ("question", "Question"),
        ("status", "Status"),
        ("similarity", "Similarity"),
        ("mark", "Mark"),
        ("submitted_file", "Submitted File"),
        ("notes", "Notes"),
    ]
    code_check_columns = [
        ("student", "Student"),
        ("file_path", "File"),
        ("compiles", "Syntax OK"),
        ("structure_score", "Structure"),
        ("details", "Details"),
    ]
    available_manifests = list_available_manifests()
    active_manifest_rel = str(manifest.manifest_path.relative_to(ROOT)).replace("\\", "/")
    code_check_rows = []
    for suffix, spec in sorted(manifest.code_checks.items()):
        inherited = spec.inherit_from or "-"
        code_check_rows.append(
            {
                "suffix": suffix,
                "engine": spec.engine,
                "rules": len(spec.rules),
                "inherit_from": inherited,
            }
        )
    manifest_details = {
        "version": manifest.version,
        "manifest_path": active_manifest_rel,
        "benchmark_dir": str(manifest.benchmark_dir.relative_to(ROOT)).replace("\\", "/"),
        "submissions_dir": str(manifest.submissions_dir.relative_to(ROOT)).replace("\\", "/"),
        "reports_dir": str(manifest.reports_dir.relative_to(ROOT)).replace("\\", "/"),
        "allowed_extensions": ", ".join(sorted(manifest.allowed_extensions)),
        "question_count": len(manifest.questions),
        "total_max_mark": manifest.total_max_mark,
        "code_check_rows": code_check_rows,
    }

    return render_template(
        "index.html",
        assignment_title=manifest.title,
        assignment_id=manifest.assignment_id,
        question_count=len(manifest.questions),
        total_max_mark=manifest.total_max_mark,
        question_specs=manifest.questions,
        benchmarks=benchmarks,
        students=students,
        report_exists=(get_report_dir() / "summary_report.csv").exists(),
        results=results,
        summaries=summaries,
        code_checks=code_checks,
        summary_columns=summary_columns,
        result_columns=result_columns,
        code_check_columns=code_check_columns,
        available_manifests=available_manifests,
        active_manifest_rel=active_manifest_rel,
        manifest_details=manifest_details,
    )


@app.post("/benchmarks")
def upload_benchmark():
    ensure_directories()
    question = secure_filename(request.form["question"].strip().lower())
    if not question:
        flash("Question is required.")
        return redirect(url_for("index"))
    try:
        save_upload(request.files["file"], get_benchmark_dir() / question)
    except UploadValidationError as exc:
        flash(str(exc))
        return redirect(url_for("index"))
    flash(f"Benchmark uploaded for {question}.")
    return redirect(url_for("index"))


@app.post("/benchmarks/seed")
def seed_benchmarks_view():
    ensure_directories()
    created = copy_solution_benchmarks()
    flash(f"Loaded {len(created)} benchmark file(s) from the solution outputs.")
    return redirect(url_for("index"))


@app.post("/config/switch-manifest")
def switch_manifest_view():
    selected_manifest = request.form.get("manifest_path", "").strip()
    if not selected_manifest:
        flash("Please choose a manifest to activate.")
        return redirect(url_for("index"))
    try:
        manifest = set_active_manifest(selected_manifest)
        ensure_directories()
        flash(f"Activated manifest: {manifest.title} ({manifest.assignment_id}).")
    except Exception as exc:  # noqa: BLE001
        flash(f"Could not activate manifest: {exc}")
    return redirect(url_for("index"))


@app.post("/config/upload-manifest")
def upload_manifest_view():
    assignment_slug = request.form.get("assignment_slug", "").strip()
    manifest_file = request.files.get("manifest_file")
    benchmarks_zip = request.files.get("benchmarks_zip")

    if manifest_file is None or not manifest_file.filename:
        flash("Manifest file is required.")
        return redirect(url_for("index"))

    try:
        manifest_path = save_manifest_upload(manifest_file, assignment_slug)
        manifest = set_active_manifest(manifest_path)
        ensure_directories()

        imported = 0
        if benchmarks_zip is not None and benchmarks_zip.filename:
            imported = extract_benchmarks_zip(
                benchmarks_zip,
                manifest.benchmark_dir,
                manifest.allowed_extensions,
            )
        if imported:
            flash(
                f"Manifest uploaded and activated ({manifest.assignment_id}). "
                f"Imported {imported} benchmark file(s)."
            )
        else:
            flash(f"Manifest uploaded and activated ({manifest.assignment_id}).")
    except Exception as exc:  # noqa: BLE001
        flash(f"Could not upload manifest: {exc}")
    return redirect(url_for("index"))


@app.post("/config/reset-data")
def reset_data_view():
    ensure_directories()
    scope = request.form.get("scope", "all").strip().lower()
    manifest = get_manifest()

    targets = []
    if scope in {"all", "benchmarks"}:
        targets.append(("benchmarks", manifest.benchmark_dir))
    if scope in {"all", "submissions"}:
        targets.append(("submissions", manifest.submissions_dir))
    if scope in {"all", "reports"}:
        targets.append(("reports", manifest.reports_dir))

    if not targets:
        flash("Invalid reset scope.")
        return redirect(url_for("index"))

    removed_total = 0
    details = []
    for label, target in targets:
        removed = clear_directory_contents(target)
        removed_total += removed
        details.append(f"{label}: {removed}")

    flash(
        f"Reset complete ({scope}). Removed {removed_total} item(s) — "
        + ", ".join(details)
    )
    return redirect(url_for("index"))


@app.post("/submissions")
def upload_submission():
    ensure_directories()
    student = secure_filename(request.form["student"].strip())
    if not student:
        flash("Student name is required.")
        return redirect(url_for("index"))
    student_dir = get_submissions_dir() / student
    if student_dir.exists():
        shutil.rmtree(student_dir)
    student_dir.mkdir(parents=True)
    try:
        for file_storage in request.files.getlist("files"):
            if not file_storage.filename:
                continue
            save_upload(file_storage, student_dir)
    except UploadValidationError as exc:
        shutil.rmtree(student_dir, ignore_errors=True)
        flash(str(exc))
        return redirect(url_for("index"))
    flash(f"Submission stored for {student}.")
    return redirect(url_for("index"))


@app.post("/grade")
def grade():
    ensure_directories()
    mark_scale = float(request.form.get("mark_scale", 1))
    results: list[GradeResult] = []
    code_checks = []
    for student_dir in sorted(path for path in get_submissions_dir().iterdir() if path.is_dir()):
        try:
            results.extend(grade_student(student_dir, mark_scale=mark_scale))
            code_checks.extend(check_student_code(student_dir))
        except Exception as exc:
            flash(f"Grading skipped errors for {student_dir.name}: {exc}")
    summaries = build_student_summaries(results, code_checks)
    write_reports(results, summaries, code_checks)
    flash(f"Graded {len(summaries)} student(s); {len(results)} file comparison(s) recorded.")
    return redirect(url_for("index"))


@app.get("/report/<report_name>")
def download_report(report_name: str):
    allowed = {"summary_report.csv", "student_totals.csv", "code_checks.csv"}
    if report_name not in allowed:
        flash("Unknown report.")
        return redirect(url_for("index"))
    return send_file(get_report_dir() / report_name, as_attachment=True)


if __name__ == "__main__":
    ensure_directories()
    app.run(debug=True)
