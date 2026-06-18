"""
Probe модели учёта БП ГИГ через COM — как реализована ось контрагент/договор.

Снимает: субконто плана счетов (какие счета несут аналитику Контрагенты+Договоры
vs товарные/результатные разрезы), измерения регистров расчётов, служебного
«Розничного покупателя», склады как «точки». Для проектирования оси в TradeLedger.

Запуск: py -3.13-32 probe_accounting_model.py
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

import pythoncom
import win32com.client

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = r"D:\Users\magsp\GIG Base2"
USR, PWD = "Гайворонская Татьяна", "12345"

# Счета для проверки субконто (типовая БП 3.0)
ACCOUNTS = [
    "60", "60.01", "60.02", "62", "62.01", "62.02", "62.Р",
    "76.05", "76.06", "76.АВ", "76.ВА",
    "41", "41.01", "41.02", "10.03",
    "90", "90.01", "90.01.1", "90.02", "90.02.1", "90.03",
    "50", "51", "57", "19.03", "68.02", "44.01",
]


@contextmanager
def com_init():
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def connect():
    connector = win32com.client.Dispatch("V83.COMConnector")
    return connector.Connect(f'File="{DB_PATH}";Usr="{USR}";Pwd="{PWD}";')


def coll(c):
    out = []
    try:
        for i in range(c.Количество()):
            out.append(c.Получить(i))
    except Exception:
        try:
            for x in c:
                out.append(x)
        except Exception:
            pass
    return out


def account_subconto(v, code: str):
    """Виды субконто счёта + признаки (валютный/количественный/забалансовый)."""
    псч = v.ПланыСчетов.Хозрасчетный
    ссыл = псч.НайтиПоКоду(code)
    try:
        if ссыл.Пустая():
            return None
    except Exception:
        return None
    info = {
        "code": str(ссыл.Код),
        "name": str(ссыл.Наименование),
        "val": bool(getattr(ссыл, "Валютный", False)),
        "qty": bool(getattr(ссыл, "Количественный", False)),
        "offbal": bool(getattr(ссыл, "Забалансовый", False)),
        "subconto": [],
    }
    try:
        for стр in coll(ссыл.ВидыСубконто):
            try:
                vs = стр.ВидСубконто
                nm = str(vs.Наименование)
                only_turn = bool(getattr(стр, "ТолькоОбороты", False))
                info["subconto"].append(nm + (" [об]" if only_turn else ""))
            except Exception as e:
                info["subconto"].append(f"<err:{str(e)[:40]}>")
    except Exception as e:
        info["subconto_err"] = str(e)[:80]
    return info


def registers_with(v, keywords):
    """Регистры накопления, чьё имя содержит ключевые слова — измерения+ресурсы."""
    out = []
    for rmd in coll(v.Метаданные.РегистрыНакопления):
        nm = str(rmd.Имя)
        if not any(k.lower() in nm.lower() for k in keywords):
            continue
        dims = [str(d.Имя) for d in coll(rmd.Измерения)]
        res = [str(r.Имя) for r in coll(rmd.Ресурсы)]
        kind = str(getattr(rmd, "ВидРегистра", ""))
        out.append({"name": nm, "kind": kind, "dims": dims, "res": res})
    return out


def find_retail_customer(v):
    """Служебный контрагент «Розничный покупатель» (шапка ОРП)."""
    rows = []
    try:
        q = v.NewObject("Запрос")
        q.Текст = (
            'ВЫБРАТЬ ПЕРВЫЕ 10 Ссылка КАК С, Наименование КАК Н, ИНН КАК ИНН, '
            'Предопределенный КАК Пред ИЗ Справочник.Контрагенты '
            'ГДЕ Наименование ПОДОБНО "%озничн%" ИЛИ Наименование ПОДОБНО "%еопределен%"'
        )
        sel = q.Выполнить().Выбрать()
        while sel.Следующий():
            ref = ""
            try:
                ref = str(v.XMLСтрока(sel.С.УникальныйИдентификатор()))
            except Exception:
                pass
            rows.append({
                "name": str(sel.Н), "inn": str(sel.ИНН or ""),
                "pre": bool(sel.Пред), "ref": ref,
            })
    except Exception as e:
        rows.append({"error": str(e)[:120]})
    return rows


def warehouses(v):
    """Склады как кандидаты «торговых точек»: тип + счётчик."""
    info = {}
    try:
        q = v.NewObject("Запрос")
        q.Текст = "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Справочник.Склады"
        sel = q.Выполнить().Выбрать(); sel.Следующий()
        info["count"] = int(sel.К)
    except Exception as e:
        info["count_err"] = str(e)[:80]
    examples = []
    try:
        sel = v.Справочники.Склады.Выбрать()
        while sel.Следующий() and len(examples) < 8:
            if getattr(sel, "ЭтоГруппа", False):
                continue
            examples.append({
                "name": str(sel.Наименование),
                "type": str(getattr(sel, "ТипСклада", "") or getattr(sel, "Вид", "")),
            })
    except Exception as e:
        info["ex_err"] = str(e)[:80]
    info["examples"] = examples
    # Виды субконто справочника-аналитики «Склады» используется ли на 41?
    return info


def main():
    print("=== Probe модели учёта БП ГИГ (ось контрагент/договор) ===\n")
    with com_init():
        try:
            v = connect()
        except Exception as e:
            print(f"❌ connect: {str(e)[:160]}")
            return
        print(f"✅ {v.Метаданные.Синоним} (вер. {v.Метаданные.Версия})\n")

        print("=" * 78)
        print("ПЛАН СЧЕТОВ — субконто (аналитика). [об]=только обороты\n")
        print(f"  {'Счёт':<9} {'Вал':<4}{'Кол':<4} Субконто")
        for code in ACCOUNTS:
            a = account_subconto(v, code)
            if a is None:
                continue
            flags = ("В" if a["val"] else "·") + (" К" if a["qty"] else " ·")
            sub = " · ".join(a["subconto"]) or "—"
            print(f"  {a['code']:<9} {flags:<7} {sub}")
            print(f"  {'':<9} {'':<7} «{a['name']}»")

        print("\n" + "=" * 78)
        print("РЕГИСТРЫ НАКОПЛЕНИЯ (расчёты/НДС/партии) — измерения · ресурсы\n")
        for r in registers_with(v, ["Расчет", "Взаимо", "НДС", "Парти", "Реализ"]):
            print(f"  {r['name']} [{r['kind']}]")
            print(f"      Измерения: {', '.join(r['dims']) or '—'}")
            print(f"      Ресурсы:   {', '.join(r['res']) or '—'}")

        print("\n" + "=" * 78)
        print("СЛУЖЕБНЫЙ КОНТРАГЕНТ (Розничный покупатель / Неопределённый):\n")
        for r in find_retail_customer(v):
            if "error" in r:
                print(f"  ⚠ {r['error']}")
            else:
                pre = " [предопределённый]" if r["pre"] else ""
                print(f"  • {r['name']} (ИНН={r['inn'] or '—'}){pre}  Ref={r['ref']}")

        print("\n" + "=" * 78)
        w = warehouses(v)
        print(f"СКЛАДЫ (кандидаты «торговых точек»): всего {w.get('count', '?')}")
        for e in w.get("examples", []):
            print(f"  • {e['name']}  (тип: {e['type'] or '—'})")

        v = None


if __name__ == "__main__":
    main()
