"""Учёт оборудования под 1С:БП: счета по состоянию, средняя, остатки и ОСВ."""
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.services import ezs_accounting as A
from app.services import ezs_equipment_reports as R

LOCS = {
    "wh-a": SimpleNamespace(id="wh-a", name="Склад А", type="warehouse", status="active", extra_metadata=None),
    "wh-b": SimpleNamespace(id="wh-b", name="Склад Б", type="warehouse", status="closed", extra_metadata=None),
    "st-1": SimpleNamespace(id="st-1", name="ЭЗС 1", type="ev_charging", status="active", extra_metadata=None),
}
MODEL = SimpleNamespace(id=uuid.uuid4(), name="Станция Фора 150", kind="station", account=None,
                        unit_code="796", unit_label="шт")
PART = SimpleNamespace(id=uuid.uuid4(), name="Кабель CCS2", kind="spare", account=None,
                       unit_code="006", unit_label="м")
PARTS = {MODEL.id: MODEL, PART.id: PART}
_seq = iter(range(10_000))


def unit(state="in_stock_new", loc="wh-a", cost=1_000_000, **kw):
    base = dict(id=uuid.uuid4(), serial_number="SN", inventory_number=None, vendor="Фора", brand=None, model="150",
                state=state, current_location_id=loc, custodian_name=None, keeper=None,
                purchase_amount=cost, nomenclature_id=MODEL.id, kind="station")
    return SimpleNamespace(**{**base, **kw})


def move(u, op, day, to_loc, to_state, from_loc=None, from_state=None):
    return SimpleNamespace(unit_id=u.id, op=op, occurred_on=day, created_at=next(_seq), to_location_id=to_loc,
                           to_state=to_state, from_location_id=from_loc, from_state=from_state,
                           document_id=None, counterparty=None, basis=None)


def spare(op, day, qty, amount, frm=None, to=None, delta=None):
    return SimpleNamespace(part_id=PART.id, op=op, occurred_on=day, qty=qty, amount=amount, delta=delta,
                           from_location_id=frm, to_location_id=to, created_at=next(_seq))


def test_счёт_следует_за_состоянием_единицы():
    assert A.unit_account("in_stock_new", "07") == "07"
    assert A.unit_account("reserved", "07") == "07"
    assert A.unit_account("in_installation", "07") == "08.03"
    assert A.unit_account("in_operation", "07") == "01.01"
    assert A.unit_account("written_off", "07") is None
    # Оборудование без монтажа до ввода остаётся на своём 08.04.1.
    assert A.unit_account("in_installation", "08.04.1") == "08.04.1"


def test_средняя_и_последнее_списание_забирают_сумму_целиком():
    assert A.avg_cost(3, "100.00", 1) == Decimal("33.33")
    assert A.avg_cost(3, "100.00", 3) == Decimal("100.00")  # копейки округления не остаются на нуле
    assert A.avg_cost(0, "0", 1) == Decimal("0.00")


def test_окей_по_старому_обозначению():
    assert A.okei_code("шт") == "796" and A.okei_code("м.") == "006" and A.okei_code("неведомо") == "796"
    assert A.unit_label("006") == "м" and A.unit_label(None, "компл") == "компл"


def test_осв_станции_приход_монтаж_ввод():
    u = unit(state="in_operation", loc="st-1")
    moves = [move(u, "receipt", "2026-09-01", "wh-a", "in_stock_new"),
             move(u, "to_installation", "2026-10-05", "st-1", "in_installation", "wh-a", "in_stock_new"),
             move(u, "commissioning", "2026-10-10", "st-1", "in_operation", "st-1", "in_installation")]
    out = R.osv_rows([u], moves, LOCS, PARTS, [], "2026-10-01", "2026-10-31")
    rows = {(r["account"], r["place"]): r for r in out["rows"]}
    # На складе было на начало, ушло в монтаж: 07 кредит.
    assert (rows[("07", "wh-a")]["oq"], rows[("07", "wh-a")]["cs"], rows[("07", "wh-a")]["zq"]) == (1, 1_000_000, 0)
    # Монтаж прошёл внутри периода: дебет и кредит 08.03, сальдо ноль.
    assert (rows[("08.03", "st-1")]["dq"], rows[("08.03", "st-1")]["cq"], rows[("08.03", "st-1")]["zq"]) == (1, 1, 0)
    # Введено в эксплуатацию — основное средство на точке.
    assert (rows[("01.01", "st-1")]["zq"], rows[("01.01", "st-1")]["zs"]) == (1, 1_000_000)
    assert [a["account"] for a in out["accounts"]] == ["01.01", "07", "08.03"]


def test_осв_зип_приход_расход_по_средней_и_опись():
    moves = [spare("receipt", "2026-10-01", 10, "1000.00", to="wh-a"),
             spare("issue", "2026-10-02", 4, "400.00", frm="wh-a"),
             spare("correction", "2026-10-03", 1, "-100.00", to="wh-a", delta=-1)]
    out = R.osv_rows([], [], LOCS, PARTS, moves, "2026-10-01", "2026-10-31")
    (row,) = out["rows"]
    assert (row["account"], row["unitLabel"]) == ("10.05", "м")
    assert (row["dq"], row["ds"], row["cq"], row["cs"], row["zq"], row["zs"]) == (10, 1000, 5, 500, 5, 500)


def test_остатки_по_складам_в_количестве_и_сумме():
    on_stock = unit()
    no_cost = unit(cost=None, nomenclature_id=None, vendor="Светозар", model="DC60")
    working = unit(state="in_operation", loc="st-1")
    moves = [spare("receipt", "2026-10-01", 10, "1000.00", to="wh-a")]
    out = R.balance([on_stock, no_cost, working], [], {}, LOCS, PARTS, moves, "2026-10-14")
    a = next(g for g in out["warehouses"] if g["id"] == "wh-a")
    items = {i["name"]: i for i in a["items"]}
    assert (items["Станция Фора 150"]["qty"], items["Станция Фора 150"]["amount"]) == (1, 1_000_000)
    # Единица без номенклатуры — своей строкой по модели, а не в общей куче.
    assert items["Светозар DC60"]["qty"] == 1 and a["noCost"] == 1
    assert (items["Кабель CCS2"]["qty"], items["Кабель CCS2"]["amount"], items["Кабель CCS2"]["unitLabel"]) == (10, 1000, "м")
    assert a["amount"] == 1_001_000 and a["units"] == 2
    # Работающая станция в остаток склада не входит; пустой закрытый склад — в списке последним.
    assert out["warehouses"][-1]["id"] == "wh-b" and out["warehouses"][-1]["status"] == "closed"

def test_cost_details_expense_account():
    """Расход со склада называет счёт затрат, как «Требование-накладная» в 1С."""
    import pytest
    from fastapi import HTTPException
    assert A.cost_details("issue", {}) == {"costAccount": "20.01"}
    assert A.cost_details("write_off", {"costAccount": "94", "costItem": " недостача "}) == {"costAccount": "94", "costItem": "недостача"}
    assert A.cost_details("transfer", {"costAccount": "26"}) == {}
    with pytest.raises(HTTPException):
        A.cost_details("issue", {"costAccount": "60.01"})


def test_vat_amount_by_rate():
    assert A.vat_amount(1000, "20%") == Decimal("200.00")
    assert A.vat_amount(99.99, "10%") == Decimal("10.00")
    assert A.vat_amount(1000, "Без НДС") is None and A.vat_amount(None, "20%") is None
