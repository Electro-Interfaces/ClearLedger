# -*- coding: utf-8 -*-
"""Разбор выгрузки первого захода: дамп q1c.ps1 → JSON для загрузчиков.

Usage:
    py parse-first.py <out.json> <каталог запросов>=<файл дампа> [ещё пары ...]

Пример (набор «ядро»):
    py parse-first.py onec-core.json ../queries-first/01-core=core.out.txt

Разделитель пары — «=», а не «:»: в Windows-пути двоеточие уже занято буквой диска.

Каталог указывается явно, а не ищется по имени запроса: имена файлов в разных
наборах повторяются (`03-counterparties` есть и в ядре, и в справочниках), и
автопоиск взял бы колонки из чужого запроса — молча, без ошибки.

Имена колонок берутся из псевдонимов запроса («… КАК Имя»): q1c.ps1 печатает
строки массивами значений, потому что имена колонок COM-коллекции 1С доступны
только через русскоязычные свойства.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Часовой пояс с ИСТОРИЕЙ переходов, а не фиксированные +3: до 26.10.2014 Москва жила
# на UTC+4, и жёсткий сдвиг уводил все документы тех лет на день назад — у компании с
# историей с 2011 года это 566 проводок, не нашедших своего документа.
MSK = ZoneInfo('Europe/Moscow')


def parse_date(v):
    """/Date(ms)/ → ISO до секунд. Момент отсчитан от эпохи UTC, а 1С хранит
    местное московское время. Пояс берём с историей переходов: фиксированные +3
    верны только с 26.10.2014, а до этого было +4."""
    if not isinstance(v, str):
        return v
    m = re.match(r'^/Date\((-?\d+)\)/$', v)
    if not m:
        return v
    try:
        dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=MSK)
    except (OSError, ValueError, OverflowError):
        return None
    # Пустая дата 1С приезжает годом 0100, а не отрицательным таймстампом.
    return None if dt.year < 1900 else dt.isoformat()[:19]


def columns(qfile: Path) -> list[str]:
    # Часть запросов написана английским синтаксисом: у пары объектов русское имя
    # таблицы не резолвится вовсе, и другого способа их прочитать нет.
    text = qfile.read_text(encoding='utf-8')
    head = re.split(r'\bИЗ\b|\bFROM\b', text)[0]
    return re.findall(r'(?:КАК|AS)\s+(\w+)', head)


def load(dump: Path, qdir: Path) -> dict:
    blocks = {}
    for line in dump.read_text(encoding='utf-8-sig', errors='replace').splitlines():
        if not line.startswith('{'):
            continue
        d = json.loads(line)
        names = columns(qdir / ('%s.txt' % d['query']))
        rows = []
        for raw in d['rows']:
            vals = raw['value'] if isinstance(raw, dict) and 'value' in raw else raw
            rows.append({names[i] if i < len(names) else 'col%d' % i: parse_date(v)
                         for i, v in enumerate(vals)})
        blocks[d['query']] = rows
    return blocks


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    out = Path(argv[1])
    blocks = {}
    for pair in argv[2:]:
        qdir, _, dump = pair.partition('=')
        if not qdir or not dump:
            raise SystemExit('пара задаётся как <каталог запросов>=<файл дампа>: ' + pair)
        part = load(Path(dump), Path(qdir))
        for k, v in part.items():
            if k in blocks:
                raise SystemExit('запрос «%s» встретился дважды — наборы пересекаются' % k)
            blocks[k] = v
    out.write_text(json.dumps(blocks, ensure_ascii=False), encoding='utf-8')
    for k, v in sorted(blocks.items()):
        print('%-28s %6d' % (k, len(v)))
    # Без юникодных стрелок: консоль Windows под cp1251 роняет печать на них.
    print('итого ->', out, out.stat().st_size // 1024, 'KB')


def demo():
    """Самопроверка разбора дат: московская полночь не уезжает во вчера."""
    assert parse_date('/Date(1625086800000)/')[:10] == '2021-07-01', parse_date('/Date(1625086800000)/')
    assert parse_date('/Date(-59011459200000)/') is None      # пустая дата 1С
    assert parse_date('текст') == 'текст'
    print('parse-first: разбор дат ок')


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'demo':
        demo()
    else:
        main(sys.argv)
