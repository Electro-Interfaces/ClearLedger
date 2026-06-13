"""
ReconcileEngine — единый доменно-агностичный движок сверки (§6.1).

Исполняет ДЕКЛАРАТИВНЫЙ разрез (ReconRule из reconcile_catalog) над потоками
нормализованных записей:

    load_streams → key_partition → match (nearest_time + bonus) →
    field_compare (допуски) → classify (severity) → ReconResult

Движок НЕ знает доменных литералов — всё из правила. Зависимостей нет
(чистый Python) → тестируется на синтетике.

⚠ ДИСЦИПЛИНА §6.4: это ЦЕЛЬ унификации. Рабочие императивные движки
(`src/services/reconciliation`, `mstoReconciliation`) — golden. Перед заменой
их этим движком — сверка byte-for-byte против golden на боевых данных ГИГ.
Пока движок исполняет разрез, но НЕ объявлен заменой golden.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Парсинг допуска времени ("90s" / "30min" / "0")
# ---------------------------------------------------------------------------
def parse_time_tolerance(s: str) -> float:
    """Допуск времени → секунды."""
    s = (s or "0").strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hour)?$", s)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2) or "s"
    mult = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hour": 3600}[unit]
    return val * mult


def _key(rec: dict, fields: list[str]) -> tuple:
    return tuple(str(rec.get(f, "")).strip().lower() for f in fields)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts(rec: dict) -> float | None:
    """occurred_at записи → epoch-секунды (если есть)."""
    v = rec.get("occurred_at") or rec.get("ts") or rec.get("time")
    return _num(v)


# ---------------------------------------------------------------------------
# Матчинг внутри корзины ключа: для каждого anchor — лучший external
# ---------------------------------------------------------------------------
def _score(anchor: dict, ext: dict, match: dict) -> tuple[float, bool]:
    """(score, within_time) — чем выше score, тем лучше пара."""
    tol = parse_time_tolerance(match.get("time_tolerance", "0"))
    ta, te = _ts(anchor), _ts(ext)
    within_time = True
    score = 0.0
    if tol > 0 and ta is not None and te is not None:
        dt = abs(ta - te)
        within_time = dt <= tol
        score += max(0.0, (tol - dt) / tol) * 10  # ближе по времени — выше
    for bf in match.get("bonus_fields", []):
        f = bf["field"]
        av, ev = anchor.get(f), ext.get(f)
        if bf.get("eq"):
            if av is not None and av == ev:
                score += bf.get("weight", 0)
        elif bf.get("tol") is not None:
            an, en = _num(av), _num(ev)
            if an is not None and en is not None and abs(an - en) <= bf["tol"]:
                score += bf.get("weight", 0)
    return score, within_time


def _compare(anchor: dict, ext: dict, compare: list[dict]) -> tuple[bool, list[dict]]:
    """Сравнение полей по допускам → (matched, diffs)."""
    diffs = []
    ok = True
    for c in compare:
        f = c["field"]
        an, en = _num(anchor.get(f)), _num(ext.get(f))
        if an is None or en is None:
            continue
        d = abs(an - en)
        field_ok = d <= c.get("tolerance_abs", 0)
        if not field_ok:
            ok = False
        diffs.append({"field": f, "anchor": an, "external": en,
                      "diff": round(d, 6), "unit": c.get("unit", ""), "ok": field_ok})
    return ok, diffs


def _severity(diffs: list[dict], thresholds: dict) -> str:
    """Классификация тяжести по максимальному отклонению."""
    maxd = max((d["diff"] for d in diffs if not d["ok"]), default=0.0)
    if maxd <= thresholds.get("none", 0):
        return "none"
    for level in ("rounding", "minor", "material"):
        if level in thresholds and maxd <= thresholds[level]:
            return level
    return "critical"


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------
def run_reconcile(rule: dict, streams: dict[str, list[dict]]) -> dict:
    """Исполнить разрез над потоками.

    rule    — сериализованный ReconRule (из reconcile_catalog.list_reconcile_rules()).
    streams — {role: [записи]} как минимум 'anchor' и 'external'.
    Возврат — ReconResult: summary + pairs + provenance.
    """
    key_fields = rule.get("key", [])
    match = rule.get("match", {})
    compare = rule.get("compare", [])
    thresholds = (rule.get("severity") or {}).get("thresholds", {})

    anchors = list(streams.get("anchor", []))
    externals = list(streams.get("external", []))

    # партиционирование external по ключу
    ext_by_key: dict[tuple, list[dict]] = {}
    for e in externals:
        ext_by_key.setdefault(_key(e, key_fields), []).append(e)

    pairs: list[dict] = []
    used_ext: set[int] = set()
    counts = {"matched": 0, "mismatch": 0, "only_anchor": 0, "only_external": 0}

    for a in anchors:
        k = _key(a, key_fields)
        candidates = [(i, e) for i, e in enumerate(ext_by_key.get(k, []))
                      if id(e) not in used_ext]
        best = None
        best_score = -1.0
        for i, e in candidates:
            sc, within = _score(a, e, match)
            if within and sc > best_score:
                best, best_score = e, sc
        if best is None:
            counts["only_anchor"] += 1
            pairs.append({"key": list(k), "status": "only_anchor"})
            continue
        used_ext.add(id(best))
        ok, diffs = _compare(a, best, compare)
        sev = _severity(diffs, thresholds) if not ok else "none"
        status = "matched" if ok else "mismatch"
        counts[status] += 1
        pairs.append({"key": list(k), "status": status, "severity": sev, "diffs": diffs})

    # external без пары
    for e in externals:
        if id(e) not in used_ext:
            counts["only_external"] += 1
            pairs.append({"key": list(_key(e, key_fields)), "status": "only_external"})

    return {
        "rule_id": rule.get("id"),
        "summary": counts,
        "pairs": pairs,
        "provenance": {
            "engine": "ReconcileEngine",
            "anchors": len(anchors),
            "externals": len(externals),
            "key": key_fields,
            "note": "ЦЕЛЬ унификации §6.4; не заменяет golden до byte-for-byte сверки",
        },
    }


# ---------------------------------------------------------------------------
# Само-тест на синтетике
# ---------------------------------------------------------------------------
def _selftest() -> dict:
    rule = {
        "id": "test_fuel", "key": ["station", "fuel"],
        "match": {"time_tolerance": "90s",
                  "bonus_fields": [{"field": "card_last4", "weight": 50, "eq": True}]},
        "compare": [{"field": "volume", "tolerance_abs": 0.01, "unit": "л"}],
        "severity": {"thresholds": {"none": 0.005, "rounding": 0.05, "minor": 1.0, "material": 100.0}},
    }
    streams = {
        "anchor": [
            {"station": "5", "fuel": "АИ-95", "volume": 30.00, "occurred_at": 1000, "card_last4": "1234"},
            {"station": "5", "fuel": "ДТ", "volume": 50.00, "occurred_at": 2000},
            {"station": "8", "fuel": "АИ-95", "volume": 10.00, "occurred_at": 3000},  # only_anchor
        ],
        "external": [
            {"station": "5", "fuel": "АИ-95", "volume": 30.00, "occurred_at": 1010, "card_last4": "1234"},  # matched
            {"station": "5", "fuel": "ДТ", "volume": 50.50, "occurred_at": 2005},   # mismatch (>0.01)
            {"station": "9", "fuel": "АИ-92", "volume": 5.00, "occurred_at": 9000},  # only_external
        ],
    }
    return run_reconcile(rule, streams)


if __name__ == "__main__":
    import json
    print(json.dumps(_selftest(), ensure_ascii=False, indent=2))
