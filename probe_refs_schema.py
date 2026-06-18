"""
Probe схемы справочников БП ГИГ через COM (V83.COMConnector).

Снимает ФАКТИЧЕСКУЮ структуру Справочник.Контрагенты и
Справочник.ДоговорыКонтрагентов: реквизиты + типы, стандартные реквизиты,
табличные части, счётчики и несколько реальных строк. Нужен для проектирования
справочника контрагентов/договоров в TradeLedger (что синхронизировать/сверять).

Запуск:  py -3 probe_refs_schema.py
ВАЖНО: 1С Предприятие/Конфигуратор не должны быть открыты на той же файловой БД.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

import pythoncom
import win32com.client

sys.stdout.reconfigure(encoding="utf-8")

CANDIDATES = [
    ("GIG (основная)", r"D:\Users\magsp\GIG Base2"),
    ("BP_Stand (стенд v6.0)", r"D:\Users\magsp\GIG Base2_BP_Stand"),
]

# Какие справочники описываем
TARGETS = ["Контрагенты", "ДоговорыКонтрагентов"]

# Примитивные типы для классификации (имя → 1С Тип())
PRIMITIVES = ["Строка", "Число", "Дата", "Булево", "УникальныйИдентификатор"]


@contextmanager
def com_init():
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def connect(path: str, user: str = "Гайворонская Татьяна", password: str = "12345"):
    conn_str = f'File="{path}";Usr="{user}";Pwd="{password}";'
    connector = win32com.client.Dispatch("V83.COMConnector")
    return connector.Connect(conn_str)


def coll_to_list(coll):
    """Коллекция метаданных 1С → list (через Количество/Получить)."""
    out = []
    try:
        n = coll.Количество()
        for i in range(n):
            out.append(coll.Получить(i))
    except Exception:
        try:
            for x in coll:
                out.append(x)
        except Exception:
            pass
    return out


def type_names(v, описание_типов) -> str:
    """ОписаниеТипов → читаемая строка типов (СправочникСсылка.X / примитивы)."""
    names = []
    try:
        типы = описание_типов.Типы()
        n = типы.Количество()
        for i in range(n):
            t = типы.Получить(i)
            md = None
            try:
                md = v.Метаданные.НайтиПоТипу(t)
            except Exception:
                md = None
            if md is not None:
                try:
                    names.append(str(md.ПолноеИмя()))
                    continue
                except Exception:
                    pass
            # примитив — определим какой
            prim = "?"
            for p in PRIMITIVES:
                try:
                    if описание_типов.СодержитТип(v.Eval(f'Тип("{p}")')):
                        prim = p
                        break
                except Exception:
                    pass
            if prim == "Строка":
                try:
                    L = описание_типов.КвалификаторыСтроки.ДлинаСтроки
                    prim = f"Строка({L})" if L else "Строка"
                except Exception:
                    pass
            names.append(prim)
    except Exception as e:
        names.append(f"<err:{e}>")
    # уникализуем сохраняя порядок
    seen, uniq = set(), []
    for x in names:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return ", ".join(uniq) or "—"


def describe_catalog(v, name: str) -> dict:
    """Снять схему одного справочника."""
    info: dict = {"name": name}
    try:
        md = getattr(v.Метаданные.Справочники, name)
    except Exception as e:
        info["error"] = f"метаданные не найдены: {e}"
        return info

    info["synonym"] = getattr(md, "Синоним", "")
    info["hierarchical"] = bool(getattr(md, "Иерархический", False))
    try:
        info["owners"] = [str(o.Имя) for o in coll_to_list(md.Владельцы)]
    except Exception:
        info["owners"] = []

    # Реквизиты
    reqs = []
    for r in coll_to_list(md.Реквизиты):
        try:
            reqs.append({
                "name": str(r.Имя),
                "synonym": str(getattr(r, "Синоним", "") or ""),
                "type": type_names(v, r.Тип),
            })
        except Exception as e:
            reqs.append({"name": "<err>", "synonym": "", "type": str(e)})
    info["attributes"] = reqs

    # Табличные части
    tabs = []
    for tp in coll_to_list(md.ТабличныеЧасти):
        cols = []
        for c in coll_to_list(tp.Реквизиты):
            try:
                cols.append(f"{c.Имя}: {type_names(v, c.Тип)}")
            except Exception:
                cols.append(str(c.Имя))
        tabs.append({"name": str(tp.Имя), "columns": cols})
    info["tabulars"] = tabs

    # Счётчик через запрос
    try:
        q = v.NewObject("Запрос")
        q.Текст = f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Справочник.{name}"
        sel = q.Выполнить().Выбрать()
        sel.Следующий()
        info["count"] = int(sel.К)
    except Exception as e:
        info["count_error"] = str(e)[:160]

    return info


def read_value(v, val):
    """Значение реквизита → читаемое (ссылка/перечисление → 1С Строка())."""
    if val is None:
        return ""
    if isinstance(val, (str, int, float, bool)):
        return val
    # COM-значение (ссылка/перечисление/дата) → представление через 1С Строка()
    try:
        s = v.Строка(val)
        if s:
            return str(s)
    except Exception:
        pass
    for attr in ("Наименование", "Имя"):
        try:
            x = getattr(val, attr)
            if x:
                return str(x)
        except Exception:
            pass
    return str(val)[:60]


def ref_guid(v, ссылка) -> str:
    """Ссылка элемента → строковый GUID (Ref_Key)."""
    try:
        return str(v.XMLСтрока(ссылка.УникальныйИдентификатор()))
    except Exception:
        try:
            return str(v.Строка(ссылка.УникальныйИдентификатор()))
        except Exception:
            return "?"


def dump_enum(v, name: str):
    """Значения перечисления (Имя + Синоним) — для маппинга в TradeLedger."""
    out = []
    try:
        md = getattr(v.Метаданные.Перечисления, name)
        for z in coll_to_list(md.ЗначенияПеречисления):
            out.append((str(z.Имя), str(getattr(z, "Синоним", "") or "")))
    except Exception as e:
        out.append(("<err>", str(e)[:80]))
    return out


def gig_contracts(v, inn: str = "7839440090", limit: int = 12):
    """Договоры организации ГИГ через запрос (Владелец=контрагент)."""
    rows, total = [], None
    try:
        q = v.NewObject("Запрос")
        q.Текст = (
            "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Справочник.ДоговорыКонтрагентов КАК Д "
            f'ГДЕ Д.Организация.ИНН = "{inn}"'
        )
        sel = q.Выполнить().Выбрать()
        sel.Следующий()
        total = int(sel.К)
    except Exception as e:
        rows.append({"error": f"count: {str(e)[:120]}"})
    try:
        q = v.NewObject("Запрос")
        q.Текст = (
            "ВЫБРАТЬ ПЕРВЫЕ 200 Д.Ссылка КАК С, Д.Номер КАК Номер, Д.Дата КАК Дата,"
            " Д.Владелец КАК Контрагент, Д.ВидДоговора КАК Вид,"
            " Д.ВалютаВзаиморасчетов КАК Валюта, Д.Сумма КАК Сумма,"
            " Д.ДоговорЗакрыт КАК Закрыт, Д.ВидВзаиморасчетов КАК ВидРасч"
            " ИЗ Справочник.ДоговорыКонтрагентов КАК Д"
            f' ГДЕ Д.Организация.ИНН = "{inn}"'
            " УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ"
        )
        sel = q.Выполнить().Выбрать()
        while sel.Следующий() and len(rows) < limit:
            rows.append({
                "Номер": read_value(v, sel.Номер),
                "Дата": read_value(v, sel.Дата),
                "Контрагент": read_value(v, sel.Контрагент),
                "Вид": read_value(v, sel.Вид),
                "ВидРасч": read_value(v, sel.ВидРасч),
                "Валюта": read_value(v, sel.Валюта),
                "Сумма": read_value(v, sel.Сумма),
                "Закрыт": read_value(v, sel.Закрыт),
                "Ref": ref_guid(v, sel.С) if sel.С else "",
            })
    except Exception as e:
        rows.append({"error": f"rows: {str(e)[:120]}"})
    return total, rows


def sample_rows(v, name: str, attr_names: list[str], limit: int = 5) -> list[dict]:
    """Первые N не-групповых элементов с ключевыми реквизитами + Ref_Key."""
    rows = []
    try:
        sel = v.Справочники.__getattr__(name).Выбрать()
    except Exception:
        sel = getattr(v.Справочники, name).Выбрать()
    while sel.Следующий():
        try:
            if getattr(sel, "ЭтоГруппа", False):
                continue
        except Exception:
            pass
        row = {
            "Код": read_value(v, getattr(sel, "Код", "")),
            "Наименование": read_value(v, getattr(sel, "Наименование", "")),
        }
        row["Ref_Key"] = ref_guid(v, sel.Ссылка)
        for a in attr_names:
            try:
                row[a] = read_value(v, getattr(sel, a))
            except Exception:
                row[a] = "—"
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def main():
    print("=== Probe схемы справочников БП ГИГ ===\n")
    with com_init():
        v = None
        used = None
        for name, path in CANDIDATES:
            try:
                v = connect(path)
                used = (name, path)
                break
            except Exception as e:
                print(f"  ⚠ {name} ({path}): {str(e)[:100]}")
        if v is None:
            print("\n❌ Не удалось подключиться ни к одной базе (вероятно file lock — закройте 1С).")
            return

        print(f"\n✅ Подключено: {used[0]} — {used[1]}")
        try:
            print(f"   Конфиг: {v.Метаданные.Синоним} (вер. {v.Метаданные.Версия})\n")
        except Exception:
            print()

        for tname in TARGETS:
            print("=" * 78)
            d = describe_catalog(v, tname)
            print(f"СПРАВОЧНИК.{tname}  «{d.get('synonym','')}»")
            if d.get("error"):
                print(f"  ❌ {d['error']}\n")
                continue
            print(f"  Иерархический: {d['hierarchical']} | Владельцы: {d.get('owners') or '—'}"
                  f" | Элементов: {d.get('count', d.get('count_error','?'))}")
            print(f"\n  РЕКВИЗИТЫ ({len(d['attributes'])}):")
            for a in d["attributes"]:
                syn = f"  «{a['synonym']}»" if a["synonym"] else ""
                print(f"    {a['name']:<32} : {a['type']}{syn}")
            if d["tabulars"]:
                print(f"\n  ТАБЛИЧНЫЕ ЧАСТИ ({len(d['tabulars'])}):")
                for t in d["tabulars"]:
                    print(f"    {t['name']}:")
                    for c in t["columns"]:
                        print(f"        {c}")

            # sample
            attr_pick = [a["name"] for a in d["attributes"]][:12]
            print(f"\n  ПРИМЕРЫ (до 5 строк):")
            try:
                for row in sample_rows(v, tname, attr_pick):
                    print(f"    • {row.get('Наименование','')[:50]}  (Код={row.get('Код','')}, Ref={row.get('Ref_Key','')})")
                    for k, val in row.items():
                        if k in ("Код", "Наименование", "Ref_Key"):
                            continue
                        sval = str(val)[:60]
                        if sval and sval != "—":
                            print(f"        {k} = {sval}")
            except Exception as e:
                print(f"    ⚠ sample error: {str(e)[:120]}")
            print()

        # Значения ключевых перечислений (для маппинга)
        print("=" * 78)
        print("ПЕРЕЧИСЛЕНИЯ (значения для маппинга):")
        for enum_name in ("ЮридическоеФизическоеЛицо", "ВидыДоговоровКонтрагентов",
                          "ВидыВзаиморасчетов"):
            print(f"\n  {enum_name}:")
            for имя, син in dump_enum(v, enum_name):
                print(f"    {имя:<32} «{син}»")

        # Договоры именно ГИГ (организация ИНН 7839440090)
        print("\n" + "=" * 78)
        total, rows = gig_contracts(v)
        print(f"ДОГОВОРЫ ОРГАНИЗАЦИИ ГИГ (ИНН 7839440090): всего {total}")
        for r in rows:
            if "error" in r:
                print(f"  ⚠ {r['error']}")
                continue
            print(f"  • №{r['Номер']} от {r['Дата']} — {r['Контрагент'][:40]}")
            print(f"      Вид={r['Вид']} | Расчёты={r['ВидРасч']} | Валюта={r['Валюта']}"
                  f" | Сумма={r['Сумма']} | Закрыт={r['Закрыт']} | Ref={r['Ref']}")

        v = None


if __name__ == "__main__":
    main()
