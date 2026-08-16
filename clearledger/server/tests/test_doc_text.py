"""Извлечение текста и безопасная проверка папки обмена без БД."""
import io
import zipfile

import pytest

from app.models import DocExchangeTarget
from app.services import doc_exchange, doc_text


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


def test_несуществующая_папка_не_считается_успешным_пилотом(tmp_path):
    target = DocExchangeTarget(inbox_path=str(tmp_path / "нет-папки"))
    with pytest.raises(FileNotFoundError):
        doc_exchange.scan_inbox(target)
