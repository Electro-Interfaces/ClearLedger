"""Отдача файлов выгрузки: MIME и имя файла, в котором кириллица выживает.

Имя собиралось вручную в шести местах и везде было ASCII-транслитом
(«billing_upd_all_2026-06-01.xlsx»), потому что кириллица не кодируется в
latin-1 заголовок Content-Disposition — попытка отдать русское имя роняет
ответ в 500. Из-за этого бухгалтер получал папку одинаковых
«sessions_…xlsx» и разбирался, где какой отчёт.

RFC 5987 решает это парой значений: filename* несёт UTF-8 в percent-encoding,
filename= остаётся ASCII-запасным для клиентов, которые filename* не знают.
Браузеры поддерживают filename* с 2011 года, включая все актуальные.
"""
from __future__ import annotations

import io
from urllib.parse import quote

from fastapi import Response

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv; charset=utf-8"

# Windows не даёт создать файл с этими символами — вырезаем, иначе браузер
# сохранит файл под искажённым именем или откажется сохранять вовсе.
_FORBIDDEN = '\\/:*?"<>|'

# Транслит для ASCII-fallback. Без него запасное имя вырождается в «______.xlsx»
# и клиент, не понимающий filename*, получает папку неразличимых файлов.
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    '·': '-', '—': '-', '–': '-', '×': 'x', '№': 'N',
}


def _to_ascii(name: str) -> str:
    """Транслитерация для запасного имени: кириллица → латиница, прочее → «_»."""
    out: list[str] = []
    for ch in name:
        low = ch.lower()
        if low in _TRANSLIT:
            t = _TRANSLIT[low]
            out.append(t.upper() if ch.isupper() and t else t)
        elif ch.isascii():
            out.append(ch)
        else:
            out.append('_')
    return "".join(out)


def safe_filename(name: str) -> str:
    """Убрать из имени то, что запрещено файловой системой, и схлопнуть пробелы."""
    cleaned = "".join("-" if ch in _FORBIDDEN else ch for ch in name)
    return " ".join(cleaned.split()).strip() or "export"


def content_disposition(filename: str) -> str:
    """Заголовок вложения с именем файла, допускающим кириллицу.

    ASCII-fallback обязателен: без него заголовок с русскими буквами не
    закодируется в latin-1 и ответ упадёт. В fallback идёт транслит, чтобы имя
    оставалось различимым («Реестр сессий» → «Reestr sessiy»).
    """
    name = safe_filename(filename)
    ascii_name = _to_ascii(name).encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def xlsx_response(workbook, filename: str) -> Response:
    """Записать книгу openpyxl в ответ. filename — с расширением и по-русски."""
    buf = io.BytesIO()
    workbook.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": content_disposition(filename)},
    )
