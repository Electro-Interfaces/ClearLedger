"""Шаги техприсоединения: набор по способу, срок по Правилам, статус по факту."""
from datetime import date
from types import SimpleNamespace

from app.models import EzsTechConnection
from app.services.ezs_checklist import TASKS
from app.services.ezs_tp_steps import KIT, STEPS, STEP_BY_KEY, derived_status, kit_for, steps_for, steps_out


def _tc(**kw):
    base = dict(method="direct", steps={}, application_date=None, contract_date=None, done_date=None)
    return SimpleNamespace(**{**base, **kw})


def test_steps_refer_to_real_columns_and_steps():
    for s in STEPS:
        if s.get("field"):
            assert hasattr(EzsTechConnection, s["field"]), s["key"]
        if s.get("after"):
            assert s["after"] in STEP_BY_KEY and s.get("norm"), s["key"]
        if s.get("gate"):
            # шаг закрывает только ручной пункт: остальные закрываются графой или документом
            assert next(t for t in TASKS if t["key"] == s["gate"]).get("manual"), s["key"]


def test_kit_follows_method_and_docs():
    from app.services.ezs_project import DOC_LABELS
    assert all(d["kind"] in DOC_LABELS for d in KIT)
    assert kit_for("landlord", set()) == [] and kit_for(None, set()) == []
    assert "tp_indirect" not in [d["kind"] for d in kit_for("direct", set())]
    kit = {d["kind"]: d for d in kit_for("indirect", {"contract"})}
    assert kit["contract"]["present"] and not kit["tp_indirect"]["present"] and kit["poa"]["optional"]


def test_method_selects_steps():
    assert steps_for(None) == [] and steps_for("landlord") == []
    assert "indirect_agreement" not in [s["key"] for s in steps_for("direct")]
    assert steps_for("indirect")[0]["key"] == "indirect_agreement"


def test_deadline_counts_from_previous_step():
    tc = _tc(application_date="2026-10-01")
    accepted = next(s for s in steps_out(tc, date(2026, 10, 10)) if s["key"] == "accepted")
    assert accepted["plannedDate"] == "2026-10-04" and accepted["overdue"]
    tc.steps = {"accepted": {"date": "2026-10-03"}}
    out = {s["key"]: s for s in steps_out(tc, date(2026, 10, 10))}
    assert not out["accepted"]["overdue"]
    assert out["contract"]["plannedDate"] == "2026-11-02" and not out["contract"]["overdue"]
    assert out["atp"]["plannedDate"] is None


def test_status_follows_furthest_closed_step():
    assert derived_status(_tc()) is None
    assert derived_status(_tc(application_date="2026-10-01")) == "applied"
    assert derived_status(_tc(application_date="2026-10-01", contract_date="2026-10-20",
                              steps={"notified": {"date": "2026-11-01"}})) == "in_progress"
    assert derived_status(_tc(done_date="2026-12-01")) == "done"
    # ветка электроснабжения статус присоединения не двигает
    assert derived_status(_tc(steps={"supply_contract": {"date": "2026-12-01"}})) is None
    assert derived_status(_tc(method="landlord", done_date="2026-12-01")) is None


def test_step_marks_manual_checklist_item_and_keeps_human_tick():
    from app.services.ezs_project import _gate_from_step
    site = SimpleNamespace(kind=None, gates={})
    assert _gate_from_step(site, "5.1", True, None)["field"] == "gate:5.1"
    assert site.gates["construction"]["5.1"]["done"] and _gate_from_step(site, "5.1", True, None) is None
    assert _gate_from_step(site, "5.1", False, None) and not site.gates["construction"]["5.1"]["done"]
    # галочку человека стёртая дата шага не снимает; пункт, закрываемый документом, шаг не трогает
    site.gates = {"construction": {"5.2": {"done": True}}}
    assert _gate_from_step(site, "5.2", False, None) is None and site.gates["construction"]["5.2"]["done"]
    assert _gate_from_step(site, "5.3", True, None) is None
    assert _gate_from_step(SimpleNamespace(kind="integration", gates={}), "5.1", True, None) is None
