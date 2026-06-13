"""
Самосверка L2 (внутренняя ось) — проверка арифметических инвариантов смены
на НАШИХ данных, без внешних источников/кредов.

Зачем: разрезы reconcile_catalog двухпотоковые (anchor↔external) и требуют
второй источник (TradeCorp/MSTO/ОФД/эквайринг/ЧЗ/инкассация). Самосверка же
ловит ошибки нормализации/выгрузки ВНУТРИ одной записи ДО экспорта в БП:
  • баланс: Σ оплаты == Σ продажи − Σ возвраты (закрытие 62.Р);
  • НДС: СуммаНДС == round(Сумма × ставка/(100+ставка)) — дисциплина fail-fast
    НДС (золотое правило 10: розничный ОРП, Кт 68.02 = round(90.01.1×22/122));
  • итог документа: СуммаДокумента == Σ продажи.

Архитектура «разрез = данные»: доменное знание (имена секций) живёт в
`extract_aggregates`, инварианты — декларативные арифметические отношения над
ИМЕНОВАННЫМИ агрегатами (домен-агностичный исполнитель). Чистый Python, без БД.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Извлечение именованных агрегатов из записи L2 (cb retail с секциями)
# ---------------------------------------------------------------------------
def extract_aggregates(entry: dict) -> dict[str, float]:
    """Записи DataEntry (retail_sale_sidegoods) → именованные суммы для инвариантов.

    Defensive: отсутствующая секция/поле = 0.0. Имена агрегатов — те, на
    которые ссылаются правила (selfcheck_catalog).
    """
    meta = entry.get("meta", {}) or {}
    sections = meta.get("Секции", {}) or {}
    header = meta.get("Документ", {}) or {}

    def _sec_sum(name: str, field: str = "сумма") -> float:
        sec = sections.get(name) or {}
        return round(float(sec.get(field, 0) or 0), 2)

    def _pay_sum() -> float:
        sec = sections.get("оплаты") or {}
        return round(sum(float(r.get("Сумма", 0) or 0) for r in sec.get("строки", [])), 2)

    return {
        "опл": _pay_sum(),
        "прод_сопутка": _sec_sum("продажа_сопутка"),
        "прод_общепит": _sec_sum("продажа_общепит"),
        "возвраты": _sec_sum("возвраты"),
        "ндс_сопутка": _sec_sum("продажа_сопутка", "сумма_ндс"),
        "ндс_общепит": _sec_sum("продажа_общепит", "сумма_ндс"),
        "сумма_документа": round(float(header.get("СуммаДокумента", 0) or 0), 2),
    }


# ---------------------------------------------------------------------------
# Исполнитель инвариантов
# ---------------------------------------------------------------------------
# Разрешённые розничные ставки НДС сети (золотое правило 10: розница = 22;
# часть сопутки социально-значимая = 10; БезНДС = 0). Ставки 18/20 — устаревшие.
STANDARD_RATES = [0.0, 10.0, 22.0]


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_rate(v: Any) -> float | None:
    """СтавкаНДС («22%», «Ставка22», 22) → число. None — не распознано."""
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("Ставка", "").replace("НДС", "").strip()
    if s.lower() in ("безндс", "без", "0", ""):
        return 0.0 if s != "" else None
    n = _num(s)
    return n


def _g(agg: dict[str, float], names: Any) -> float:
    """Σ агрегатов по имени(ам); неизвестное имя = 0."""
    if isinstance(names, str):
        return float(agg.get(names, 0.0))
    return round(sum(float(agg.get(n, 0.0)) for n in (names or [])), 2)


def _section_lines(entry: dict, names: list[str]) -> list[dict]:
    """Строки указанных секций записи L2 (для построчных инвариантов)."""
    secs = (entry.get("meta", {}) or {}).get("Секции", {}) or {}
    out: list[dict] = []
    for n in names:
        out += (secs.get(n) or {}).get("строки", []) or []
    return out


def _expected_vat(amount: float, rate: float) -> float:
    """НДС «в сумме»: round(Сумма × ставка/(100+ставка))."""
    return round(amount * rate / (100.0 + rate), 2) if rate else 0.0


def _eval_vat_lines(inv: dict, entry: dict) -> dict:
    """Построчный НДС: каждая строка должна лечь на разрешённую ставку.

    Если строка несёт СтавкаНДС — берём её; иначе подбираем ближайшую из
    STANDARD_RATES. Строка «плохая», если ни одна разрешённая ставка не даёт
    СуммаНДС в пределах допуска (вероятно ставка 18/20 или ошибка) ИЛИ
    заявленная ставка вне политики. Ловит «18/20 vs 22» без ложных на 10%.
    """
    tol = float(inv.get("tol", 1.0))
    allowed = inv.get("allowed_rates", STANDARD_RATES)
    lines = _section_lines(entry, inv.get("sections", ["продажа_сопутка", "продажа_общепит"]))
    checked = 0
    bad: list[dict] = []
    sum_declared = 0.0
    sum_expected = 0.0
    for ln in lines:
        amt = _num(ln.get("Сумма"))
        vat = _num(ln.get("СуммаНДС"))
        if amt is None or vat is None or amt == 0:
            continue
        checked += 1
        sum_declared += vat
        declared_rate = _parse_rate(ln.get("СтавкаНДС"))
        if declared_rate is not None:
            exp = _expected_vat(amt, declared_rate)
            sum_expected += exp
            if declared_rate not in allowed:
                bad.append({"Номенклатура": ln.get("Номенклатура"), "Сумма": amt,
                            "СуммаНДС": vat, "ставка": declared_rate, "причина": "ставка_вне_политики"})
            elif abs(vat - exp) > tol:
                bad.append({"Номенклатура": ln.get("Номенклатура"), "Сумма": amt,
                            "СуммаНДС": vat, "ожид": exp, "причина": "арифметика_ндс"})
        else:
            best = min(allowed, key=lambda r: abs(vat - _expected_vat(amt, r)))
            resid = abs(vat - _expected_vat(amt, best))
            sum_expected += _expected_vat(amt, best)
            if resid > tol:
                implied = round(vat * 100.0 / (amt - vat), 1) if amt != vat else None
                bad.append({"Номенклатура": ln.get("Номенклатура"), "Сумма": amt,
                            "СуммаНДС": vat, "ставка_подразум": implied, "причина": "ставка_не_стандартная"})
    return {
        "id": inv.get("id"),
        "label": inv.get("label"),
        "ok": not bad,
        "lhs": round(sum_declared, 2),
        "rhs": round(sum_expected, 2),
        "diff": round(abs(sum_declared - sum_expected), 2),
        "tol": tol,
        "строк": checked,
        "плохих": len(bad),
        "строки_плохие": bad[:20],
        "severity": (inv.get("severity", "minor") if bad else "none"),
    }


def _eval_invariant(inv: dict, agg: dict[str, float], entry: dict) -> dict:
    """Один инвариант → {id, ok, lhs, rhs, diff, …}."""
    kind = inv.get("kind")

    if kind == "vat_lines":
        return _eval_vat_lines(inv, entry)

    tol = float(inv.get("tol", 1.0))
    if kind == "vat":   # секционный (устар.): единая ставка на итог
        base = _g(agg, inv["base"])
        rate = float(inv.get("rate", 22.0))
        lhs, rhs = _g(agg, inv["vat"]), _expected_vat(base, rate)
    else:  # "balance" / "equality": lhs == Σ plus − Σ minus
        lhs = _g(agg, inv["lhs"])
        rhs = round(_g(agg, inv.get("plus", [])) - _g(agg, inv.get("minus", [])), 2)

    diff = round(abs(lhs - rhs), 2)
    ok = diff <= tol
    return {
        "id": inv.get("id"),
        "label": inv.get("label"),
        "ok": ok,
        "lhs": round(lhs, 2),
        "rhs": round(rhs, 2),
        "diff": diff,
        "tol": tol,
        "severity": (inv.get("severity", "minor") if not ok else "none"),
    }


def _applies(rule: dict, entry: dict) -> bool:
    """Правило применимо к записи (по doc_type_id/category)."""
    applies = rule.get("applies_to") or {}
    dt = applies.get("doc_type_id")
    if dt and entry.get("doc_type_id") not in dt:
        return False
    cat = applies.get("category_id")
    if cat and entry.get("category_id") not in cat:
        return False
    return True


def run_selfcheck(rule: dict, entry: dict) -> dict:
    """Прогнать самосверку (набор инвариантов) над одной записью L2."""
    if not _applies(rule, entry):
        return {"rule_id": rule.get("id"), "status": "n/a"}
    agg = extract_aggregates(entry)
    invs = [_eval_invariant(i, agg, entry) for i in rule.get("invariants", [])]
    worst = "none"
    order = {"none": 0, "rounding": 1, "minor": 2, "material": 3, "critical": 4}
    for r in invs:
        if order.get(r["severity"], 0) > order.get(worst, 0):
            worst = r["severity"]
    return {
        "rule_id": rule.get("id"),
        "status": "ok" if worst == "none" else "violation",
        "severity": worst,
        "aggregates": agg,
        "invariants": invs,
    }


def run_selfchecks(rules: list[dict], entries: list[dict]) -> dict:
    """Прогнать все применимые правила над списком записей L2 → сводка + нарушения."""
    checked = 0
    ok = 0
    violations: list[dict] = []
    for e in entries:
        for rule in rules:
            res = run_selfcheck(rule, e)
            if res["status"] == "n/a":
                continue
            checked += 1
            if res["status"] == "ok":
                ok += 1
            else:
                violations.append({
                    "source_id": e.get("source_id"),
                    "title": e.get("title"),
                    "rule_id": res["rule_id"],
                    "severity": res["severity"],
                    "bad": [i for i in res["invariants"] if not i["ok"]],
                })
    return {"checked": checked, "ok": ok, "violations": violations}


def verdict_for_entry(rules: list[dict], entry: dict) -> dict | None:
    """Компактный вердикт самосверки для записи (в meta.Самосверка). None — нет применимых."""
    results = [run_selfcheck(r, entry) for r in rules]
    applicable = [r for r in results if r["status"] != "n/a"]
    if not applicable:
        return None
    order = {"none": 0, "rounding": 1, "minor": 2, "material": 3, "critical": 4}
    worst = "none"
    bad: list[dict] = []
    for r in applicable:
        if order.get(r.get("severity", "none"), 0) > order.get(worst, 0):
            worst = r.get("severity", "none")
        bad.extend({"rule": r["rule_id"], **i} for i in r.get("invariants", []) if not i["ok"])
    return {
        "статус": "ok" if worst == "none" else "нарушение",
        "тяжесть": worst,
        "нарушения": bad,
    }


# ---------------------------------------------------------------------------
# Само-тест
# ---------------------------------------------------------------------------
def _selftest() -> dict:
    from app.selfcheck_catalog import list_selfchecks
    rules = list_selfchecks()
    balanced = {
        "doc_type_id": "retail_sale_sidegoods", "category_id": "retail",
        "source_id": "ok:retail:1", "title": "balanced",
        "meta": {"Документ": {"СуммаДокумента": 1000.0}, "Секции": {
            "продажа_сопутка": {"сумма": 600.0, "сумма_ндс": round(400 * 22 / 122 + 200 * 10 / 110, 2),
                                "строки": [{"Сумма": 400.0, "СуммаНДС": round(400 * 22 / 122, 2)},   # 22%
                                           {"Сумма": 200.0, "СуммаНДС": round(200 * 10 / 110, 2)}]},  # 10% (соц-значимое)
            "продажа_общепит": {"сумма": 400.0, "сумма_ндс": round(400 * 22 / 122, 2),
                                "строки": [{"Сумма": 400.0, "СуммаНДС": round(400 * 22 / 122, 2)}]},  # 22%
            "оплаты": {"строки": [{"Сумма": 1000.0}]},
        }},
    }
    broken = {
        "doc_type_id": "retail_sale_sidegoods", "category_id": "retail",
        "source_id": "bad:retail:1", "title": "broken",
        "meta": {"Документ": {"СуммаДокумента": 1000.0}, "Секции": {
            "продажа_сопутка": {"сумма": 600.0, "сумма_ндс": round(600 * 18 / 118, 2),
                                "строки": [{"Сумма": 600.0, "СуммаНДС": round(600 * 18 / 118, 2)}]},  # ставка 18 → нарушение
            "оплаты": {"строки": [{"Сумма": 900.0}]},  # недобор оплат → нарушение баланса
        }},
    }
    return run_selfchecks(rules, [balanced, broken])


if __name__ == "__main__":
    import json
    print(json.dumps(_selftest(), ensure_ascii=False, indent=2))
