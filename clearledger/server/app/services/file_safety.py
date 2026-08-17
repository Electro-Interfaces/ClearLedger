"""Быстрая проверка типа и очевидно опасного содержимого входящих файлов."""
from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path

DENY_EXTENSIONS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs",
    ".msi", ".jar", ".ps1", ".lnk", ".hta", ".html", ".htm", ".svg",
}
ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".xls",
    ".docx", ".xlsx", ".txt", ".zip", ".xml",
}
EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
MAX_ARCHIVE_ENTRIES = 2000
MAX_ARCHIVE_UNPACKED = 250 * 1024 * 1024


def _safe_name(value: str) -> str:
    return unicodedata.normalize(
        "NFKC", value or "file").replace("\\", "/").rsplit("/", 1)[-1].rstrip(" .")


def _is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF-")


def _is_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _is_ole(data: bytes) -> bool:
    return data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _inspect_zip(data: bytes, *, office_kind: str | None = None) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("Слишком много файлов внутри архива")
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_UNPACKED:
                raise ValueError("Архив слишком велик после распаковки")
            names = {info.filename.replace("\\", "/").lower() for info in infos}
            if any(Path(_safe_name(name)).suffix.lower() in DENY_EXTENSIONS
                   for name in names):
                raise ValueError("Архив содержит исполняемый файл")
            for info in infos:
                if info.file_size <= 1024 * 1024 and EICAR_MARKER in archive.read(info):
                    raise ValueError("Файл отклонён антивирусной проверкой")
            if office_kind == "docx" and "word/document.xml" not in names:
                raise ValueError("Содержимое не соответствует DOCX")
            if office_kind == "xlsx" and "xl/workbook.xml" not in names:
                raise ValueError("Содержимое не соответствует XLSX")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("Повреждённый или подменённый ZIP/Office-файл") from exc


def validate(data: bytes, file_name: str, mime: str | None = None) -> None:
    """Отклонить исполняемый файл, zip-bomb и несоответствие заявленному MIME."""
    normalized_name = _safe_name(file_name)
    suffix = Path(normalized_name).suffix.lower()
    inferred_mime = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".doc": "application/msword",
        ".xls": "application/vnd.ms-excel",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".txt": "text/plain",
        ".zip": "application/zip",
        ".xml": "application/xml",
    }.get(suffix)
    known_mimes = {
        "application/pdf", "image/jpeg", "image/png", "image/webp",
        "application/msword", "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
    }
    if inferred_mime and mime in known_mimes and mime != inferred_mime:
        raise ValueError("Расширение файла не соответствует заявленному типу")
    if inferred_mime:
        mime = inferred_mime
    if suffix in DENY_EXTENSIONS:
        raise ValueError("Исполняемые файлы не принимаются")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Этот формат файла не принимается")
    if EICAR_MARKER in data or data.startswith((b"MZ", b"\x7fELF")):
        raise ValueError("Файл отклонён проверкой безопасности")

    office_kind = None
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        office_kind = "docx"
    elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        office_kind = "xlsx"
    is_zip = zipfile.is_zipfile(io.BytesIO(data))
    if office_kind and not is_zip:
        raise ValueError(f"Содержимое не соответствует {office_kind.upper()}")
    if mime == "application/zip" and not is_zip:
        raise ValueError("Содержимое не соответствует ZIP")
    if is_zip:
        _inspect_zip(data, office_kind=office_kind)

    if not mime:
        return
    checks = {
        "application/pdf": _is_pdf,
        "image/jpeg": _is_jpeg,
        "image/png": _is_png,
        "image/webp": _is_webp,
        "application/msword": _is_ole,
        "application/vnd.ms-excel": _is_ole,
    }
    check = checks.get(mime)
    if check is not None and not check(data):
        raise ValueError(f"Содержимое не соответствует типу {mime}")
    if mime == "text/plain" and b"\x00" in data:
        raise ValueError("Бинарный файл нельзя загрузить как текст")
