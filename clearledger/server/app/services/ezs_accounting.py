"""Бухгалтерская модель складского учёта оборудования — под 1С:Бухгалтерию 3.0.

Раздел ведёт складские предметы так, чтобы каждое движение однозначно ложилось
документом БП (`docs/rushydro-equipment-1c-plan-20261014.html` в поставке):

* **Номенклатура** — справочник `ezs_spare_parts`: и запчасти, и модели станций.
  Вид номенклатуры задаёт счёт учёта по умолчанию, как регистр
  «Счета учёта номенклатуры» в БП.
* **Станция или оборудование** — экземпляр с серийным номером (в БП серий нет):
  на складе — оборудование к установке (07), в монтаже — вложения (08.03), после
  ввода — основное средство (01.01). Счёт следует за состоянием единицы.
* **Количественная номенклатура** (ЗИП, материалы, инвентарь, товары) — остаток в
  количестве и сумме по складу, расход по средней стоимости.

Здесь только чистые функции: тесты проверяют их без базы.
"""
from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

# Вид номенклатуры → (название, счёт по умолчанию, учёт по экземплярам).
KINDS: dict[str, tuple[str, str, bool]] = {
    "station": ("Зарядная станция", "07", True),
    "equipment": ("Оборудование", "07", True),
    "spare": ("Запчасти (ЗИП)", "10.05", False),
    "material": ("Материалы", "10.01", False),
    "inventory": ("Инвентарь и хозяйственные принадлежности", "10.09", False),
    "goods": ("Товары", "41.01", False),
}
SERIAL_KINDS = {k for k, (_, _, serial) in KINDS.items() if serial}

# Счета учёта, которые предлагаются в справочнике. Значение — подпись в интерфейсе.
ACCOUNTS: dict[str, str] = {
    "07": "07 — оборудование к установке",
    "08.03": "08.03 — строительство объектов ОС (монтаж)",
    "08.04.1": "08.04.1 — оборудование, не требующее монтажа",
    "01.01": "01.01 — основные средства в организации",
    "10.01": "10.01 — сырьё и материалы",
    "10.05": "10.05 — запасные части",
    "10.09": "10.09 — инвентарь и хозяйственные принадлежности",
    "10.21": "10.21 — активы ниже лимита ОС",
    "41.01": "41.01 — товары на складах",
}

# Единицы измерения по ОКЕИ: код → краткое обозначение (как в классификаторе БП).
OKEI: dict[str, str] = {
    "796": "шт", "839": "компл", "006": "м", "055": "м²", "113": "м³", "166": "кг",
    "168": "т", "112": "л", "778": "упак", "715": "пар", "018": "пог. м",
}
OKEI_BY_LABEL = {v: k for k, v in OKEI.items()}

# Ставки НДС в написании БП.
VAT_RATES = ("20%", "10%", "0%", "Без НДС")

# Состояния единицы, которые дают счёт учёта. Остальное — вне баланса склада
# (возвращена производителю, списана): счёта нет.
_STOCKISH = {"in_stock_new", "in_stock_used", "reserved", "in_repair"}


def default_account(kind: str | None) -> str:
    return KINDS.get(kind or "", KINDS["spare"])[1]


def unit_label(code: str | None, fallback: str | None = None) -> str:
    return OKEI.get(code or "", fallback or "шт")


def okei_code(label: str | None) -> str:
    """Код ОКЕИ по обозначению из старых записей («шт» → 796); неизвестное — штуки."""
    return OKEI_BY_LABEL.get((label or "").strip().lower().rstrip("."), "796")


def unit_account(state: str | None, stock_account: str | None) -> str | None:
    """Счёт единицы в состоянии `state`.

    `stock_account` — счёт номенклатуры, пока единица не смонтирована (07, а для
    оборудования без монтажа — 08.04.1). В монтаже — 08.03, кроме оборудования без
    монтажа: оно до ввода остаётся на своём 08.04.1. В эксплуатации — 01.01.
    """
    if not state:
        return None
    base = stock_account or "07"
    if state in _STOCKISH:
        return base
    if state == "in_installation":
        return base if base.startswith("08") else "08.03"
    if state == "in_operation":
        return "01.01"
    return None


def money(x: Any) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def avg_cost(stock_qty: Any, stock_amount: Any, qty: Any) -> Decimal:
    """Стоимость списания `qty` по средней остатка; весь остаток уходит всей суммой.

    Последнее списание забирает сумму целиком, иначе копейки округлений копятся на
    нулевом остатке и ведомость показывает сумму без количества.
    """
    sq, sa, q = Decimal(str(stock_qty or 0)), money(stock_amount), Decimal(str(qty or 0))
    if sq <= 0 or q <= 0:
        return Decimal("0.00")
    if q >= sq:
        return sa
    return money(sa * q / sq)


# ── Оборотно-сальдовая ведомость ─────────────────────────────────────────────

def _cell() -> dict[str, Decimal]:
    z = Decimal(0)
    return {"oq": z, "os": z, "dq": z, "ds": z, "cq": z, "cs": z}


def osv(flows: Iterable[tuple[str, str | None, str | None, Any, Decimal, Decimal]],
        date_from: str, date_to: str) -> dict[tuple[str, str | None, Any], dict[str, Decimal]]:
    """Сальдо и обороты по ключу (счёт, место, номенклатура).

    `flows` — знаковые изменения: (дата, счёт, место, номенклатура, количество,
    сумма). Плюс — дебет (приход на счёт и место), минус — кредит. Сальдо на
    начало — всё, что раньше `date_from`; конечное = начальное + дебет − кредит.
    """
    out: dict[tuple[str, str | None, Any], dict[str, Decimal]] = {}
    for day, account, place, item, qty, amount in flows:
        if not account or day > date_to:
            continue
        c = out.setdefault((account, place, item), _cell())
        q, s = Decimal(str(qty)), money(amount)
        if day < date_from:
            c["oq"] += q
            c["os"] += s
        elif q > 0 or (q == 0 and s > 0):
            c["dq"] += q
            c["ds"] += s
        else:
            c["cq"] -= q
            c["cs"] -= s
    for c in out.values():
        c["zq"] = c["oq"] + c["dq"] - c["cq"]
        c["zs"] = c["os"] + c["ds"] - c["cs"]
    return out


def unit_flows(units, by_unit: dict[Any, list], stock_account, place_of, cost_of, item_of) -> list[tuple]:
    """Движения единиц как изменения сальдо (счёт, место).

    Единица числится на счёте и месте, которые даёт её состояние; движение,
    меняющее пару (счёт, место), кредитует прежнюю и дебетует новую. Единица без
    единого движения (разовый импорт) лежит в сальдо с самого начала.
    """
    out: list[tuple] = []
    for u in units:
        acc = stock_account(u)
        item, cost = item_of(u), cost_of(u)
        own = by_unit.get(u.id, [])
        if not own:
            a = unit_account(u.state, acc)
            if a:
                out.append(("0000-00-00", a, place_of(u.state, u.current_location_id), item, 1, cost))
            continue
        cur = None
        first = own[0]
        if first.from_state:  # до первого движения единица уже была на учёте
            a = unit_account(first.from_state, acc)
            cur = (a, place_of(first.from_state, first.from_location_id)) if a else None
            if cur:
                out.append(("0000-00-00", cur[0], cur[1], item, 1, cost))
        state = first.from_state
        for m in own:
            state = m.to_state or state
            a = unit_account(state, acc)
            new = (a, place_of(state, m.to_location_id)) if a else None
            if new == cur:
                continue
            if cur:
                out.append((m.occurred_on, cur[0], cur[1], item, -1, -cost))
            if new:
                out.append((m.occurred_on, new[0], new[1], item, 1, cost))
            cur = new
    return out


def spare_value_flows(moves, account_of) -> list[tuple]:
    """Движения количественной номенклатуры как изменения сальдо (счёт, склад).

    Сумма берётся из движения (`amount`); у старых движений её нет — тогда в
    оборот идёт только количество.
    """
    out: list[tuple] = []
    for m in moves:
        acc = account_of(m.part_id)
        qty, amount = Decimal(str(m.qty)), money(getattr(m, "amount", None))
        if m.op == "correction":
            delta = getattr(m, "delta", None)
            if delta is not None and m.to_location_id:
                out.append((m.occurred_on, acc, m.to_location_id, m.part_id, Decimal(str(delta)), amount))
            continue
        if m.op != "receipt" and m.from_location_id:
            out.append((m.occurred_on, acc, m.from_location_id, m.part_id, -qty, -amount))
        if m.op in ("receipt", "transfer") and m.to_location_id:
            out.append((m.occurred_on, acc, m.to_location_id, m.part_id, qty, amount))
    return out


def totals(cells: Iterable[dict[str, Decimal]]) -> dict[str, Decimal]:
    t: Counter = Counter()
    for c in cells:
        for k, v in c.items():
            t[k] += v
    return {k: t[k] for k in ("oq", "os", "dq", "ds", "cq", "cs", "zq", "zs")}
