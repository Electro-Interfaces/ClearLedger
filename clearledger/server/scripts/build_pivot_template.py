"""Сборка «тощего» шаблона сводной из живой выгрузки Excel.

Зачем: openpyxl не умеет создавать PivotTable с нуля (официально: «it is not
intended that client code should be able to create pivot tables»), но умеет
сохранять и править существующие. Поэтому сводная рисуется один раз руками в
Excel, а сервер подставляет в шаблон свежие данные и просит Excel пересчитать
кэш при открытии (refreshOnLoad).

Исходник тащит с собой данные и кэш — 14,7 МБ, и openpyxl грузит его 80 секунд,
что для эндпоинта неприемлемо. Скрипт вырезает данные и кэш, оставляя саму
сводную: 1,1 МБ и 1,8 с на загрузку.

Запуск (разово, при обновлении раскладки сводной):
    py -3.13 scripts/build_pivot_template.py <исходник.xlsx> [выход.xlsx]
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

EMPTY_RECORDS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    f'<pivotCacheRecords xmlns="{NS}" xmlns:r="{NS_R}" count="0"/>'
)

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "templates", "pivot_charge_sessions.xlsx",
)


def _slim_sheet(xml: bytes) -> bytes:
    """Оставить на листе-источнике только строку заголовков."""
    text = xml.decode("utf-8")
    m = re.search(r"<sheetData>(.*?)</sheetData>", text, re.S)
    if not m:
        return xml
    first = re.search(r"<row[^>]*r=\"1\"[^>]*>.*?</row>", m.group(1), re.S)
    keep = first.group(0) if first else ""
    return text.replace(m.group(0), f"<sheetData>{keep}</sheetData>").encode("utf-8")


def _clean_cache_definition(xml: bytes) -> bytes:
    """Обнулить счётчик записей, включить пересчёт и вычистить значения-призраки.

    sharedItems — список «известных значений поля», унаследованный от исходной
    выгрузки. Если его оставить, в фильтрах сводной будут висеть станции и
    коннекторы, которых в новых данных нет: пользователь выберет такую строку и
    получит пустоту, не поняв почему. Для отчётности это недопустимо.
    """
    text = xml.decode("utf-8")

    text = re.sub(r'\srecordCount="\d+"', ' recordCount="0"', text)
    if "refreshOnLoad=" in text:
        text = re.sub(r'\srefreshOnLoad="[^"]*"', ' refreshOnLoad="1"', text)
    else:
        text = text.replace("<pivotCacheDefinition ",
                            '<pivotCacheDefinition refreshOnLoad="1" ', 1)

    # <sharedItems …>…</sharedItems> → пустой самозакрывающийся тег.
    text = re.sub(r"<sharedItems[^>]*>.*?</sharedItems>", "<sharedItems/>", text, flags=re.S)
    # Одиночные <sharedItems … /> с перечнем атрибутов-диапазонов тоже сбрасываем:
    # containsSemiMixedTypes и пр. Excel вычислит заново при обновлении кэша.
    text = re.sub(r"<sharedItems[^>]*/>", "<sharedItems/>", text)
    return text.encode("utf-8")


def _fix_tariff_aggregation(xml: bytes) -> bytes:
    """Тариф ₽/кВтч суммировать нельзя — только среднее.

    Сумма тарифов по группе строк не значит ничего: 12 + 14 + 13 = 39 ₽/кВтч —
    цифра, которой не существует. Она при этом выглядит настоящей и уходит в
    отчёт, поэтому меняем на среднее.
    """
    text = xml.decode("utf-8")

    def repl(m: re.Match) -> str:
        tag = m.group(0)
        if "Тариф" not in tag:
            return tag
        if 'subtotal="' in tag:
            return re.sub(r'subtotal="[^"]*"', 'subtotal="average"', tag)
        return tag.replace("<dataField ", '<dataField subtotal="average" ', 1)

    return re.sub(r"<dataField [^>]*/>", repl, text).encode("utf-8")


def build(src_path: str, out_path: str) -> None:
    src = zipfile.ZipFile(src_path)
    sizes_before = {n: src.getinfo(n).file_size for n in src.namelist()}

    # Лист-источник сводной определяем по cacheSource, а не по номеру файла:
    # порядок листов в архиве не гарантирован.
    cache_def = src.read("xl/pivotCache/pivotCacheDefinition1.xml").decode("utf-8")
    m = re.search(r'<worksheetSource[^>]*sheet="([^"]+)"', cache_def)
    source_sheet = m.group(1) if m else None
    if not source_sheet:
        raise SystemExit("не нашёл worksheetSource в pivotCacheDefinition — шаблон не тот?")

    wb_xml = src.read("xl/workbook.xml").decode("utf-8")
    rels = src.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rid = None
    for mm in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb_xml):
        if mm.group(1) == source_sheet:
            rid = mm.group(2)
    target = None
    for mm in re.finditer(r'Id="(rId\d+)"[^>]*Target="(worksheets/sheet\d+\.xml)"', rels):
        if mm.group(1) == rid:
            target = mm.group(2)
    if not target:
        raise SystemExit(f"не нашёл файл листа «{source_sheet}»")

    print(f"лист-источник: «{source_sheet}» → xl/{target}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out:
        for name in src.namelist():
            raw = src.read(name)
            if name == "xl/pivotCache/pivotCacheRecords1.xml":
                raw = EMPTY_RECORDS.encode("utf-8")
            elif name == "xl/pivotCache/pivotCacheDefinition1.xml":
                raw = _clean_cache_definition(raw)
            elif name == "xl/pivotTables/pivotTable1.xml":
                raw = _fix_tariff_aggregation(raw)
            elif name == f"xl/{target}":
                raw = _slim_sheet(raw)
            if sizes_before[name] != len(raw):
                print(f"  {name}: {sizes_before[name]:,} → {len(raw):,} б")
            out.writestr(name, raw)

    print(f"\nшаблон: {out_path}")
    print(f"размер: {os.path.getsize(src_path):,} → {os.path.getsize(out_path):,} б")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT)
