# Smoke-тест подключения к стенду БП ГИГ (GIG Base2) через COM.
# Запуск: py -3.13-32 smoke_com_gigbase2.py
# Цель: убедиться что V83.COMConnector видит файловую БД GIG Base2,
# аутентификация Гайворонская Татьяна/12345 проходит, и можно прочитать
# 10 контрагентов (deliverable #2 из PROMPT_подключение_к_БП_ГИГ.md).
from __future__ import annotations

import sys
import time
from typing import Any

import win32com.client


DB_PATH = r"D:\Users\magsp\GIG Base2"
USR = "Гайворонская Татьяна"
PWD = "12345"


def _val(obj: Any) -> Any:
    """Геттер для полей COM-выборки: значение приходит как bound-method, унифицируем."""
    if callable(obj):
        try:
            return obj()
        except Exception:
            return obj
    return obj


def main() -> int:
    t0 = time.time()
    print(f"[1/4] Dispatch V83.COMConnector ...", flush=True)
    conn = win32com.client.Dispatch("V83.COMConnector")
    print(f"      OK ({time.time() - t0:.2f}s)")

    t0 = time.time()
    print(f"[2/4] Connect File=\"{DB_PATH}\" Usr=\"{USR}\" ...", flush=True)
    ib = conn.Connect(f'File="{DB_PATH}";Usr="{USR}";Pwd="{PWD}";')
    print(f"      OK ({time.time() - t0:.2f}s)")

    t0 = time.time()
    print("[3/4] Метаданные конфигурации ...", flush=True)
    md = ib.Метаданные
    cfg_name = _val(md.Имя)
    cfg_synonym = _val(md.Синоним)
    cfg_version = _val(md.Версия)
    print(f"      Имя:    {cfg_name}")
    print(f"      Синоним: {cfg_synonym}")
    print(f"      Версия: {cfg_version}")
    print(f"      OK ({time.time() - t0:.2f}s)")

    t0 = time.time()
    print("[4/4] Запрос: ВЫБРАТЬ ПЕРВЫЕ 10 К.Наименование, К.ИНН ИЗ Справочник.Контрагенты ...", flush=True)
    q = ib.NewObject("Запрос")
    q.Текст = (
        "ВЫБРАТЬ ПЕРВЫЕ 10 "
        "К.Наименование КАК Наименование, "
        "К.ИНН КАК ИНН, "
        "К.КПП КАК КПП "
        "ИЗ Справочник.Контрагенты КАК К "
        "ГДЕ НЕ К.ПометкаУдаления "
        "УПОРЯДОЧИТЬ ПО К.Наименование"
    )
    sel = q.Выполнить().Выбрать()
    rows = []
    while sel.Следующий():
        rows.append({
            "Наименование": _val(sel.Наименование),
            "ИНН":         _val(sel.ИНН),
            "КПП":         _val(sel.КПП),
        })
    print(f"      OK ({time.time() - t0:.2f}s) — получено {len(rows)} строк")
    print()
    for i, r in enumerate(rows, 1):
        print(f"  {i:2d}. {r['Наименование']!s:<60} ИНН={r['ИНН']!s:<12} КПП={r['КПП']!s}")

    print()
    print("=" * 60)
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
