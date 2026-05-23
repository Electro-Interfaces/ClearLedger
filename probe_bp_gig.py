"""
Probe локальной БП ГИГ через COM.

Подключается к каждой кандидат-базе из реестра 1CEStart и собирает
минимальные факты: имя конфигурации, её версия, список организаций,
счёт ОРП/ПТУ за последний месяц.

Запуск:
    py probe_bp_gig.py

ВАЖНО: 1С Предприятие/Конфигуратор не должны быть открыты на той же
файловой БД — иначе COM упрётся в file lock.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timedelta

import pythoncom
import win32com.client

# Используем UTF-8 для вывода в Windows-консоль
sys.stdout.reconfigure(encoding="utf-8")


CANDIDATES = [
    ("GIG (основная)", r"D:\Users\magsp\GIG Base2"),
    ("GIG (отдельная папка)", r"D:\Users\magsp\GIG"),
    ("BP_Stand (стенд v6.0)", r"D:\Users\magsp\GIG Base2_BP_Stand"),
]


@contextmanager
def com_init():
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def connect(path: str, user: str = "", password: str = ""):
    """V83.COMConnector → Connection."""
    conn_str = f'File="{path}";Usr="{user}";Pwd="{password}";'
    connector = win32com.client.Dispatch("V83.COMConnector")
    return connector.Connect(conn_str)


def fmt_dt(dt) -> str:
    """1С COM date → строка."""
    try:
        return dt.Format("yyyy-MM-dd HH:mm:ss") if hasattr(dt, "Format") else str(dt)
    except Exception:
        return str(dt)


def probe_database(name: str, path: str) -> dict:
    """Снять короткую сводку с одной БД."""
    info: dict = {"name": name, "path": path, "ok": False}
    try:
        v = connect(path)
    except Exception as e:
        info["error"] = f"connect: {e}"
        return info

    try:
        # Метаданные конфигурации
        meta = v.Метаданные
        info["config_name"] = meta.Имя
        info["config_synonym"] = meta.Синоним
        info["config_version"] = meta.Версия

        # Платформа
        sys_info = v.СистемнаяИнформация()
        info["platform"] = sys_info.ВерсияПриложения

        # Список организаций (если есть справочник)
        orgs = []
        try:
            orgs_obj = v.Справочники.Организации
            sel = orgs_obj.Выбрать()
            while sel.Следующий():
                orgs.append({
                    "name": sel.Наименование,
                    "inn": getattr(sel, "ИНН", "") or "",
                    "kpp": getattr(sel, "КПП", "") or "",
                    "head": getattr(sel, "ЭтоГруппа", False) if hasattr(sel, "ЭтоГруппа") else False,
                })
        except Exception as e:
            info["orgs_error"] = str(e)
        info["organizations"] = orgs

        # Документы за май 2026
        # Если есть Document.ОтчетОРозничныхПродажах — посчитаем
        from_date = win32com.client.Dispatch("Scripting.FileSystemObject")  # dummy
        # Правильнее через v.Документы.ОтчетОРозничныхПродажах.Выбрать(дата, дата2)
        date_from = v.Eval("Дата('20260501000000')")
        date_to = v.Eval("Дата('20260601000000')")

        for doc_name, key in [
            ("ОтчетОРозничныхПродажах", "orp_may"),
            ("ПоступлениеТоваровУслуг", "ptu_may"),
            ("СчетФактураПолученный", "sf_may"),
        ]:
            try:
                doc_obj = getattr(v.Документы, doc_name)
                sel = doc_obj.Выбрать(date_from, date_to)
                count = 0
                while sel.Следующий():
                    count += 1
                info[key] = count
            except Exception as e:
                info[f"{key}_error"] = str(e)[:120]

        # OData публикация — отдельный признак (через Constants/функц. опции
        # достоверно не определить, но можно проверить расширения)
        try:
            ext_count = v.КонфигурацияРасширения().Количество() \
                if hasattr(v, "КонфигурацияРасширения") else None
            # выше не сработает — нужно через Расширение
            extensions = []
            for ext in v.Метаданные.Расширения:
                extensions.append({
                    "name": ext.Имя,
                    "version": getattr(ext, "Версия", ""),
                    "active": True,
                })
            info["extensions"] = extensions
        except Exception as e:
            info["extensions_error"] = str(e)[:120]

        info["ok"] = True
    except Exception as e:
        info["error"] = f"runtime: {e}"
    finally:
        try:
            v = None
        except Exception:
            pass

    return info


def main():
    print(f"=== Probe БП ГИГ — {datetime.now().isoformat(timespec='seconds')} ===\n")

    with com_init():
        for name, path in CANDIDATES:
            print(f"━━━ {name}: {path}")
            r = probe_database(name, path)
            if not r["ok"]:
                print(f"  ❌ {r.get('error', 'unknown')}")
                print()
                continue

            print(f"  ✅ Платформа:  {r.get('platform', '?')}")
            print(f"     Конфиг:     {r.get('config_synonym', '')} ({r.get('config_name', '')})")
            print(f"     Версия:     {r.get('config_version', '?')}")
            print(f"     Организаций: {len(r.get('organizations', []))}")
            for o in r.get("organizations", []):
                if o.get("head"):
                    print(f"        📁 {o['name']}")
                else:
                    print(f"        • {o['name']} (ИНН {o.get('inn', '?')})")
            print(f"     ОРП май:    {r.get('orp_may', '?')}")
            print(f"     ПТУ май:    {r.get('ptu_may', '?')}")
            print(f"     СФ май:     {r.get('sf_may', '?')}")

            exts = r.get("extensions", [])
            if exts:
                print(f"     Расширения: {len(exts)}")
                for e in exts:
                    print(f"        · {e['name']} ({e.get('version', '?')})")
            elif r.get("extensions_error"):
                print(f"     Расширения: ошибка — {r['extensions_error']}")
            print()


if __name__ == "__main__":
    main()
