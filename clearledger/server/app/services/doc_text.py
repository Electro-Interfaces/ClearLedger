"""Извлечение текста редакции документа для полнотекстового поиска."""
from __future__ import annotations

import asyncio
import io
import tempfile
import zipfile
import os
from pathlib import Path
from xml.etree import ElementTree

from app.config import get_settings

MAX_TEXT = 1_000_000
IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp",
}


def _clean(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split())[:MAX_TEXT]


def _docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""
    return _clean(" ".join(node.text or "" for node in root.iter() if node.text))


def _xlsx(content: bytes) -> str:
    import openpyxl

    try:
        book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        return ""
    parts: list[str] = []
    length = 0
    try:
        for sheet in book.worksheets:
            parts.append(sheet.title)
            length += len(sheet.title)
            for row in sheet.iter_rows(values_only=True):
                values = [str(value) for value in row if value not in (None, "")]
                parts.extend(values)
                length += sum(map(len, values))
                if length >= MAX_TEXT:
                    return _clean(" ".join(parts))
    finally:
        book.close()
    return _clean(" ".join(parts))


async def _command(*args: str, timeout: int, input_data: bytes | None = None) -> bytes:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return b""
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(input_data), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return b""
    return stdout if proc.returncode == 0 else b""


async def _image(path: Path, timeout: int) -> str:
    data = await _command(
        "tesseract", str(path), "stdout", "-l", "rus+eng", "--oem", "3", "--psm", "3",
        timeout=timeout)
    return _clean(data.decode(errors="replace"))


async def _pdf(path: Path, folder: Path, timeout: int) -> str:
    embedded = await _command("pdftotext", "-layout", str(path), "-", timeout=timeout)
    text = _clean(embedded.decode(errors="replace"))
    if text:
        return text

    # Распознавание — дорогая ветка: она включается только когда во вложении нет
    # встроенного текста (скан). Предел страниц есть, потому что OCR идёт секунды
    # на страницу, а загрузка не должна висеть; но двадцать страниц — это меньше
    # обычного договора, и его вторая половина в поиск не попадала. Предел
    # поднят и вынесен в окружение: у сканов приложений к тендеру он свой.
    limit = max(1, int(os.environ.get("DOC_OCR_PAGE_LIMIT", "60")))
    prefix = folder / "page"
    await _command(
        "pdftoppm", "-f", "1", "-l", str(limit), "-r", "160", "-png",
        str(path), str(prefix), timeout=timeout)
    parts: list[str] = []
    for image in sorted(folder.glob("page-*.png")):
        value = await _image(image, timeout)
        if value:
            parts.append(value)
    text = _clean(" ".join(parts))
    if len(sorted(folder.glob("page-*.png"))) >= limit:
        # Честная отметка: иначе «нашлось не всё» выглядит как «в документе
        # этого нет», и человек делает вывод по половине бумаги.
        text = f"{text} [распознаны первые {limit} страниц]".strip()
    return text


async def extract(content: bytes, mime: str, file_name: str) -> str | None:
    """Вернуть текст или ``None``, если формат не поддержан/не распознан."""
    if mime == "text/plain":
        return _clean(content.decode("utf-8", errors="replace")) or None
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _docx(content) or None
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return await asyncio.to_thread(_xlsx, content) or None

    settings = get_settings()
    if not settings.ocr_enabled or (mime not in IMAGE_MIMES and mime != "application/pdf"):
        return None

    suffix = Path(file_name or "file").suffix or {
        "image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tiff",
        "image/bmp": ".bmp", "image/webp": ".webp", "application/pdf": ".pdf",
    }.get(mime, ".bin")
    with tempfile.TemporaryDirectory(prefix="doc-text-") as tmp:
        folder = Path(tmp)
        path = folder / f"source{suffix}"
        path.write_bytes(content)
        timeout = int(settings.ocr_timeout)
        value = (await _pdf(path, folder, timeout) if mime == "application/pdf"
                 else await _image(path, timeout))
    return value or None
