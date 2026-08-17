"""Извлечение текста и безопасная проверка папки обмена без БД."""
import io
import os
import time
import uuid
import zipfile

import pytest

from app.models import DocExchangeTarget
from app.services import doc_exchange, doc_text, file_safety


def test_подменённый_pdf_и_eicar_отклоняются():
    with pytest.raises(ValueError):
        file_safety.validate(b"MZ" + b"0" * 100, "invoice.pdf", "application/pdf")
    with pytest.raises(ValueError):
        file_safety.validate(b"not a pdf", "invoice.pdf")
    with pytest.raises(ValueError):
        file_safety.validate(b"plain text", "invoice.pdf", "text/plain")
    with pytest.raises(ValueError):
        file_safety.validate(b"not a pdf", "invoice.pdf", "application/x-msdownload")
    with pytest.raises(ValueError):
        file_safety.validate(b"echo unsafe", "invoice.cmd ", "text/plain")
    with pytest.raises(ValueError):
        file_safety.validate(b"<script/>", "invoice.hta", "text/plain")
    with pytest.raises(ValueError):
        file_safety.validate(
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
            "invoice.txt",
            "text/plain",
        )


def test_office_zip_не_может_скрыть_exe():
    with pytest.raises(ValueError):
        file_safety.validate(b"not a zip", "invoice.docx")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("payload.cmd ", b"echo unsafe")
    with pytest.raises(ValueError):
        file_safety.validate(
            stream.getvalue(),
            "invoice.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_зашифрованный_zip_отклоняется_как_файл_а_не_роняет_приём():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("safe.txt", "content")
    encrypted = bytearray(stream.getvalue())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = encrypted.find(signature)
        assert position >= 0
        flags = int.from_bytes(encrypted[position + flag_offset:position + flag_offset + 2], "little")
        encrypted[position + flag_offset:position + flag_offset + 2] = (flags | 1).to_bytes(2, "little")
    with pytest.raises(ValueError):
        file_safety.validate(bytes(encrypted), "incoming.zip")


@pytest.mark.asyncio
async def test_извлекает_текст_из_docx():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Исполнительская дисциплина</w:t></w:r></w:p></w:body>
            </w:document>""",
        )

    value = await doc_text.extract(
        stream.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "отчёт.docx",
    )
    assert value == "Исполнительская дисциплина"


def test_несуществующая_папка_не_считается_успешным_пилотом(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(tmp_path))
    cid = uuid.uuid4()
    target = DocExchangeTarget(
        company_id=cid, inbox_path=str(tmp_path / str(cid) / "нет-папки"))
    with pytest.raises(FileNotFoundError):
        doc_exchange.scan_inbox(target)


def test_папка_обмена_ограничена_разрешённым_корнем(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    cid = uuid.uuid4()
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(allowed))
    with pytest.raises(ValueError, match="папке компании"):
        doc_exchange.scan_inbox(DocExchangeTarget(
            company_id=cid, inbox_path=str(outside)))


def test_компания_не_читает_папку_соседнего_пространства(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(tmp_path))
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    foreign = tmp_path / str(company_b)
    foreign.mkdir()
    with pytest.raises(ValueError, match="папке компании"):
        doc_exchange.scan_inbox(DocExchangeTarget(
            company_id=company_a, inbox_path=str(foreign)))


def test_сканер_берёт_только_стабильный_ограниченный_файл(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(tmp_path))
    monkeypatch.setattr(doc_exchange, "MAX_INBOX_FILE_BYTES", 8)
    cid = uuid.uuid4()
    folder = tmp_path / str(cid)
    folder.mkdir()
    stable = folder / "stable.xml"
    stable.write_bytes(b"<x/>")
    os.utime(stable, (time.time() - 10, time.time() - 10))
    fresh = folder / "fresh.xml"
    fresh.write_bytes(b"<y/>")
    large = folder / "large.bin"
    large.write_bytes(b"123456789")
    os.utime(large, (time.time() - 10, time.time() - 10))

    rows = doc_exchange.scan_inbox(DocExchangeTarget(
        company_id=cid, inbox_path=str(folder)))
    assert [row["file_name"] for row in rows] == ["stable.xml"]


def test_большая_папка_продвигается_страницами(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(tmp_path))
    monkeypatch.setattr(doc_exchange, "MAX_INBOX_FILES", 2)
    monkeypatch.setattr(doc_exchange, "MIN_STABLE_AGE_SECONDS", 0)
    cid = uuid.uuid4()
    folder = tmp_path / str(cid)
    folder.mkdir()
    for index in range(1001):
        (folder / f"{index:04d}.txt").write_text("x", encoding="utf-8")
    target = DocExchangeTarget(
        company_id=cid, inbox_path=str(folder), scan_cursor="0999.txt")
    rows = doc_exchange.scan_inbox(target)
    assert [row["file_name"] for row in rows] == ["1000.txt", "0000.txt"]
