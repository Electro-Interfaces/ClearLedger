"""Шаги техприсоединения: набор по способу, срок по Правилам, статус по факту."""
from datetime import date
from types import SimpleNamespace

from app.models import EzsTechConnection
from app.services.ezs_tp_steps import STEPS, STEP_BY_KEY, derived_status, steps_for, steps_out


def _tc(**kw):
    base = dict(method="direct", steps={}, application_date=None, contract_date=None, done_date=None)
    return SimpleNamespace(**{**base, **kw})


def test_steps_refer_to_real_columns_and_steps():
    for s in STEPS:
        if s.get("field"):
            assert hasattr(EzsTechConnection, s["field"]), s["key"]
        if s.get("after"):
            assert s["after"] in STEP_BY_KEY and s.get("norm"), s["key"]


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
