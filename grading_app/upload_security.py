"""Upload validation helpers shared by Flask routes."""

from __future__ import annotations

import zipfile
from pathlib import Path

from werkzeug.utils import secure_filename

from grading_app.config import get_allowed_extensions


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails extension or safety checks."""


def allowed_extensions() -> set[str]:
    return get_allowed_extensions()


def file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_allowed_extension(filename: str) -> bool:
    ext = file_extension(filename)
    return bool(ext) and ext in allowed_extensions()


def validate_upload_filename(filename: str) -> str:
    if not filename or not filename.strip():
        raise UploadValidationError("No filename provided.")

    original_ext = file_extension(filename)
    extensions = allowed_extensions()
    if not is_allowed_extension(filename):
        allowed = ", ".join(sorted(extensions))
        raise UploadValidationError(
            f"File type '{original_ext or '(none)'}' is not allowed. Allowed extensions: {allowed}"
        )

    secured = secure_filename(filename)
    if not secured:
        raise UploadValidationError(f"Invalid or unsafe filename: {filename}")

    secured_ext = file_extension(secured)
    if secured_ext and secured_ext not in extensions:
        raise UploadValidationError(f"Sanitised filename has disallowed type: {secured}")

    if not secured_ext:
        secured = f"{secured}{original_ext}"

    return secured


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    extract_root = extract_dir.resolve()
    extract_root.mkdir(parents=True, exist_ok=True)
    extensions = allowed_extensions()

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            if member.endswith("/"):
                continue
            member_name = Path(member).name
            if not member_name:
                continue
            if not is_allowed_extension(member_name):
                raise UploadValidationError(
                    f"Zip archive contains disallowed file type: {member_name}"
                )
            target = (extract_root / member).resolve()
            if extract_root not in target.parents and target != extract_root:
                raise UploadValidationError(f"Zip archive contains unsafe path: {member}")

        archive.extractall(extract_root)

    for path in extract_root.rglob("*"):
        if path.is_file() and not is_allowed_extension(path.name):
            raise UploadValidationError(f"Extracted disallowed file type: {path.name}")
