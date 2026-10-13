"""Отчёты складского учёта оборудования: положение на дату, оборотка, держатели, ремонт."""
import uuid
from types import SimpleNamespace

from app.services import ezs_equipment_reports as R

CP = SimpleNamespace(id=uuid.uuid4(), name="ООО Хранитель")
CONTRACT = SimpleNamespace(id=uuid.uuid4(), number="7/26", date="2026-01-10", valid_until="2026-06-30", is_closed=False)
LOCS = {
    "wh-a": SimpleNamespace(id="wh-a", name="Склад А", type="warehouse", extra_metadata=None),
    "wh-b": SimpleNamespace(id="wh-b", name="Склад Б", type="warehouse", extra_metadata={"warehouse": {
        "ownership": "custody", "counterpartyId": str(CP.id), "contractId": str(CONTRACT.id)}}),
    "st-1": SimpleNamespace(id="st-1", name="ЭЗС 1", type="ev_charging", extra_metadata=None),
}
_seq = iter(range(10_000))


def unit(state="in_stock_new", loc="wh-a", **kw):
    base = dict(id=uuid.uuid4(), serial_number="SN", inventory_number=None, vendor="В", brand=None, model="М",
                state=state, current_location_id=loc, custodian_name=None, keeper=None)
    return SimpleNamespace(**{**base, **kw})


def move(u, op, day, to_loc, to_state, from_loc=None, from_state=None, doc=None, counterparty=None):
    return SimpleNamespace(unit_id=u.id, op=op, occurred_on=day, created_at=next(_seq), to_location_id=to_loc,
                           to_state=to_state, from_location_id=from_loc, from_state=from_state,
                           document_id=doc.id if doc else None, counterparty=counterparty, basis=None)


def doc(op, number, status="posted", **kw):
    base = dict(id=uuid.uuid4(), op=op, number=number, status=status, counterparty_id=None, counterparty_name=None,
                contract_id=None, contract_label=None, details=None)
    return SimpleNamespace(**{**base, **kw})


def spare(op, day, qty, frm=None, to=None, part="p1", **kw):
    return SimpleNamespace(part_id=part, op=op, occurred_on=day, qty=qty, from_location_id=frm, to_location_id=to, **kw)


def docs_of(*ds):
    return {d.id: d for d in ds}


def test_положение_на_дату():
    u = unit(state="in_operation", loc="st-1")
    moves = [move(u, "receipt", "2026-09-01", "wh-a", "in_stock_new"),
             move(u, "transfer", "2026-09-10", "wh-b", "in_stock_new", "wh-a", "in_stock_new"),
             move(u, "reserve", "2026-09-12", "wh-b", "reserved", "wh-b", "in_stock_new"),
             move(u, "to_installation", "2026-09-20", "st-1", "in_installation", "wh-b", "reserved"),
             move(u, "commissioning", "2026-09-28", "st-1", "in_operation", "st-1", "in_installation")]
    at = lambda day: R.unit_rows([u], moves, {}, LOCS, day)  # noqa: E731
    assert at("2026-08-31") == []  # карточки ещё не было
    assert (at("2026-09-05")[0]["placeKey"], at("2026-09-05")[0]["since"]) == ("wh-a", "2026-09-01")
    row = at("2026-09-15")[0]
    # Резерв места не меняет: «с какой даты там» остаётся датой перемещения.
    assert (row["placeKey"], row["state"], row["since"]) == ("wh-b", "reserved", "2026-09-10")
    # Монтаж — на учёте, но вне складов; введённая в эксплуатацию со складского учёта выбыла.
    assert (at("2026-09-25")[0]["placeKind"], at("2026-09-25")[0]["place"]) == ("installation", "ЭЗС 1")
    assert at("2026-09-30")[0]["placeKind"] == "operation" and R.SECTIONS["operation"] == "gone"
    assert [h["total"] for h in R.holders(at("2026-09-30"), LOCS, {}, {}, "2026-09-30")] == [0]


def test_отменённый_документ_не_влияет_на_остаток():
    u = unit()
    d = doc("to_repair", "РМ-2026-0001", status="cancelled", counterparty_id=CP.id, counterparty_name=CP.name)
    moves = [move(u, "receipt", "2026-09-01", "wh-a", "in_stock_new"),
             move(u, "to_repair", "2026-09-10", None, "in_repair", "wh-a", "in_stock_new", doc=d),
             move(u, "cancel", "2026-09-10", "wh-a", "in_stock_new", None, "in_repair", doc=d)]
    row = R.unit_rows([u], moves, docs_of(d), LOCS, "2026-09-30")[0]
    assert (row["placeKey"], row["state"], row["docNumber"], row["counterpartyId"]) == ("wh-a", "in_stock_new", None, None)
    assert R.repairs([u], moves, docs_of(d), "2026-09-30") == []
    # Отбор по контрагенту отменённого документа единицу не находит.
    assert R.filter_rows([row], LOCS, counterparty_id=str(CP.id)) == []
    t = R.units_turnover([u], moves, LOCS, "2026-09-05", "2026-09-30")["wh-a"]
    assert (t["opening"], t["closing"]) == (1, 1) and t["income"] == {"cancel": 1} and t["outcome"] == {"to_repair": 1}


def test_единица_без_движений():
    u = unit(state="in_stock_used", loc="wh-b")
    for day in ("2020-01-01", "2026-09-30"):
        row = R.unit_rows([u], [], {}, LOCS, day)[0]
        assert (row["placeKey"], row["state"], row["noHistory"], row["since"]) == ("wh-b", "in_stock_used", True, None)
    t = R.units_turnover([u], [], LOCS, "2026-09-01", "2026-09-30")["wh-b"]
    assert (t["opening"], t["closing"], t["noHistory"]) == (1, 1, 1) and not t["income"] and not t["outcome"]


def test_оборотка_сходится():
    a, b, c, old = unit(), unit(), unit(), unit(loc="wh-b")
    back = unit()
    # Работающие станции без истории в остаток склада не входят — даже если место указано складом.
    working = [unit(state="in_operation", loc="st-1"), unit(state="in_operation", loc="wh-a")]
    rep = doc("to_repair", "РМ-2026-0002", counterparty_id=CP.id, counterparty_name=CP.name)
    moves = [move(a, "receipt", "2026-08-01", "wh-a", "in_stock_new"),
             move(a, "transfer", "2026-09-05", "wh-b", "in_stock_new", "wh-a", "in_stock_new"),
             move(a, "to_installation", "2026-09-20", "st-1", "in_installation", "wh-b", "in_stock_new"),
             move(a, "commissioning", "2026-09-22", "st-1", "in_operation", "st-1", "in_installation"),
             # Демонтаж возвращает станцию из эксплуатации на склад — это приход.
             move(back, "dismantle", "2026-09-18", "wh-a", "in_stock_used", "st-1", "in_operation"),
             move(b, "receipt", "2026-09-03", "wh-a", "in_stock_new"),
             move(b, "to_repair", "2026-09-15", None, "in_repair", "wh-a", "in_stock_new", doc=rep),
             move(b, "from_repair", "2026-10-02", "wh-a", "in_stock_used", None, "in_repair"),
             # Единица из импорта: первое движение — перемещение, до него лежала на складе А.
             move(c, "transfer", "2026-09-25", "wh-b", "in_stock_new", "wh-a", "in_stock_new")]
    units = [a, b, c, old, back, *working]
    turn = R.units_turnover(units, moves, LOCS, "2026-09-01", "2026-09-30")
    for wh, t in turn.items():
        assert t["opening"] + sum(t["income"].values()) - sum(t["outcome"].values()) == t["closing"], wh
        # Остатки ведомости совпадают с отчётом «остатки на дату», посчитанным независимо.
        on = lambda day: sum(r["placeKey"] == wh for r in R.unit_rows(units, moves, docs_of(rep), LOCS, day))  # noqa: E731
        assert (t["opening"], t["closing"]) == (on("2026-08-31"), on("2026-09-30")), wh
    assert turn["wh-a"]["income"] == {"receipt": 1, "dismantle": 1} and turn["wh-a"]["outcome"] == {"transfer": 2, "to_repair": 1}
    assert (turn["wh-a"]["opening"], turn["wh-a"]["closing"]) == (2, 1)
    assert turn["wh-b"]["income"] == {"transfer": 2} and turn["wh-b"]["outcome"] == {"to_installation": 1}
    out = R._turn_out(turn["wh-a"])
    assert (out["income"], out["outcome"]) == (2, 3) and out["incomeByOp"][0]["label"] == "Возвращено из эксплуатации"
    assert R._turn_out(turn["wh-b"])["outcomeByOp"] == [{"label": "Выбыло в монтаж / в эксплуатацию", "qty": 1}]


def test_зип_с_перемещением_между_складами():
    moves = [spare("receipt", "2026-08-10", 10, to="wh-a"),
             spare("transfer", "2026-09-05", 4, frm="wh-a", to="wh-b"),
             spare("issue", "2026-09-07", 1, frm="wh-b"),
             spare("correction", "2026-09-08", 5, to="wh-a", delta=-1),
             spare("correction", "2026-09-09", 3, to="wh-b"),  # старая запись без величины изменения
             spare("write_off", "2026-10-01", 2, frm="wh-a")]
    stock, unknown = R.spare_stock(moves, "2026-09-30")
    assert stock == {("p1", "wh-a"): 5, ("p1", "wh-b"): 3} and unknown == 1
    assert R.spare_stock(moves, "2026-08-31")[0] == {("p1", "wh-a"): 10}
    turn, _ = R.spare_turnover(moves, "2026-09-01", "2026-09-30")
    for key, t in turn.items():
        assert t["opening"] + sum(t["income"].values()) - sum(t["outcome"].values()) == t["closing"] == stock[key]
    assert turn[("p1", "wh-a")]["outcome"] == {"transfer": 4, "correction": 1}
    assert turn[("p1", "wh-b")]["income"] == {"transfer": 4}


def test_что_числится_за_контрагентом():
    stored, repaired, texted = unit(), unit(), unit(keeper="ИП Петров")
    rep = doc("to_repair", "РМ-2026-0003", counterparty_id=CP.id, counterparty_name=CP.name)
    moves = [move(stored, "receipt", "2026-05-01", "wh-b", "in_stock_new"),
             move(repaired, "receipt", "2026-05-01", "wh-a", "in_stock_new"),
             move(repaired, "to_repair", "2026-06-10", None, "in_repair", "wh-a", "in_stock_new", doc=rep)]
    rows = R.unit_rows([stored, repaired, texted], moves, docs_of(rep), LOCS, "2026-07-15")
    linked, text = R.holders(rows, LOCS, {str(CONTRACT.id): CONTRACT}, {str(CP.id): CP}, "2026-07-15")
    wh = linked["warehouses"][0]
    assert (linked["name"], linked["total"], wh["contract"]["status"]) == ("ООО Хранитель", 2, "expired")
    assert [r["id"] for r in wh["units"]] == [str(stored.id)] and [r["id"] for r in linked["units"]] == [str(repaired.id)]
    assert (text["name"], text["linked"], text["total"]) == ("ИП Петров", False, 1)
    # Статус договора — на дату отчёта: в мае он ещё действовал.
    assert R.contract_info(CONTRACT, "2026-05-31")["status"] == "active"
    assert R.contract_info(None, "2026-05-31")["status"] == "missing"
    # Отбор остатков по контрагенту: склад из карточки плюс единица по документу ремонта.
    assert len(R.filter_rows(rows, LOCS, counterparty_id=str(CP.id))) == 2


def test_ремонт_срок_и_просрочка():
    u, legacy = unit(state="in_repair", loc=None), unit(state="in_repair", loc=None, custodian_name="ООО Старый")
    d = doc("to_repair", "РМ-2026-0004", counterparty_id=CP.id, counterparty_name=CP.name,
            details={"plannedReturn": "2026-09-20", "repairKind": "warranty"})
    moves = [move(u, "receipt", "2026-08-01", "wh-a", "in_stock_new"),
             move(u, "to_repair", "2026-09-01", None, "in_repair", "wh-a", "in_stock_new", doc=d)]
    late, old = R.repairs([u, legacy], moves, docs_of(d), "2026-09-30")
    assert (late["holder"], late["docNumber"], late["days"], late["overdueDays"], late["repairKind"]) == (
        "ООО Хранитель", "РМ-2026-0004", 29, 10, "Гарантийный")
    assert (old["holder"], old["noHistory"], old["sentOn"], old["overdueDays"]) == ("ООО Старый", True, None, 0)
