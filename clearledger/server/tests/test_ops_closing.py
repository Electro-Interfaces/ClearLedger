"""Чистая логика контура «Эксплуатация»: периоды, сроки, расчёт, расхождения.

Проверяем то, что легко сломать незаметно: границы месяцев, попадание
квартального договора ровно в один месяц квартала, срок документа в феврале,
пороги расхождения и разность показаний счётчика с коэффициентом трансформации.
"""
from types import SimpleNamespace

from app.services.ops_closing import (
    auto_status,
    classify_variance,
    needs_correction,
)
from app.services.ops_expectations import (
    _due_in_period,
    _due_on,
    _metered_volume,
    _net_gross,
    month_bounds,
    shift_month,
)


def _term(**kw):
    base = {"periodicity": "monthly", "valid_from": "2025-01-01", "doc_due_day": None}
    return SimpleNamespace(**{**base, **kw})


# ── Периоды ────────────────────────────────────────────────────────────────

def test_month_bounds_learns_february():
    assert month_bounds("2026-07-01") == ("2026-07-01", "2026-07-31")
    assert month_bounds("2026-02-01") == ("2026-02-01", "2026-02-28")
    assert month_bounds("2024-02-01") == ("2024-02-01", "2024-02-29")


def test_shift_month_crosses_year():
    assert shift_month("2026-01-01", -1) == "2025-12-01"
    assert shift_month("2025-12-01", 1) == "2026-01-01"
    assert shift_month("2026-07-01", 0) == "2026-07-01"
    assert shift_month("2026-07-01", -12) == "2025-07-01"


# ── Периодичность ──────────────────────────────────────────────────────────

def test_quarterly_expects_once_per_quarter():
    """Квартальный договор даёт одну строку в квартал, а не три.

    Иначе реестр показал бы тройную сумму, а сотрудник искал бы два документа,
    которых не существует.
    """
    term = _term(periodicity="quarterly", valid_from="2025-01-15")
    hits = [p for p in ("2026-01-01", "2026-02-01", "2026-03-01",
                        "2026-04-01", "2026-05-01", "2026-06-01")
            if _due_in_period(term, p)]
    assert hits == ["2026-01-01", "2026-04-01"]


def test_annual_expects_once_per_year():
    term = _term(periodicity="annual", valid_from="2025-05-01")
    assert _due_in_period(term, "2026-05-01")
    assert not _due_in_period(term, "2026-04-01")


def test_one_time_only_in_its_month():
    term = _term(periodicity="one_time", valid_from="2026-03-10")
    assert _due_in_period(term, "2026-03-01")
    assert not _due_in_period(term, "2026-04-01")


def test_monthly_is_always_due():
    assert _due_in_period(_term(), "2026-07-01")


# ── Срок предоставления документа ──────────────────────────────────────────

def test_doc_due_lands_on_next_month():
    assert _due_on("2026-07-01", 10) == "2026-08-10"
    assert _due_on("2026-12-01", 5) == "2027-01-05"


def test_doc_due_clamps_to_short_month():
    """31-е число в феврале — несуществующая дата, по ней просрочка не считается."""
    assert _due_on("2026-01-01", 31) == "2026-02-28"
    assert _due_on("2024-01-01", 31) == "2024-02-29"


def test_doc_due_defaults_when_term_silent():
    assert _due_on("2026-07-01", None) == "2026-08-10"


# ── НДС ────────────────────────────────────────────────────────────────────

def test_net_gross_completes_the_pair():
    assert _net_gross(1200.0, None, 20.0) == (1200.0, 1000.0)
    assert _net_gross(None, 1000.0, 20.0) == (1200.0, 1000.0)


def test_net_gross_never_invents_the_rate():
    """Без явной ставки вторую половину не выводим — цифра была бы придуманной."""
    assert _net_gross(1200.0, None, None) == (1200.0, None)
    assert _net_gross(None, None, 20.0) == (None, None)


def test_net_only_without_rate_yields_no_gross():
    """Сумма без НДС и без ставки не даёт величины «с НДС».

    Ровно этот случай и делал строку лживой: метод возвращал «по договору»,
    а суммы не было. У 115 условий аренды на пилоте графа пустая, у части —
    только сумма без НДС без ставки.
    """
    assert _net_gross(None, 5000.0, None) == (None, 5000.0)


# ── Объём по счётчику ──────────────────────────────────────────────────────

def test_volume_prefers_the_stated_intake():
    row = SimpleNamespace(intake_kwh=420.0, meter_prev=10, meter_curr=20, ktrans=50)
    assert _metered_volume(row) == 420.0


def test_volume_from_meter_readings_with_ratio():
    """279 → 283 при К/Т = 50 дают 200 кВт·ч — так считает заказчик руками."""
    row = SimpleNamespace(intake_kwh=None, meter_prev=279.0, meter_curr=283.0, ktrans=50.0)
    assert _metered_volume(row) == 200.0


def test_volume_without_ratio_is_plain_difference():
    row = SimpleNamespace(intake_kwh=None, meter_prev=100.0, meter_curr=130.0, ktrans=None)
    assert _metered_volume(row) == 30.0


def test_volume_unknown_stays_unknown():
    assert _metered_volume(None) is None
    assert _metered_volume(
        SimpleNamespace(intake_kwh=None, meter_prev=None, meter_curr=283.0, ktrans=50)) is None


# ── Расхождения ────────────────────────────────────────────────────────────

def test_variance_classes():
    assert classify_variance(5000, 5000) == (0.0, "none")
    assert classify_variance(5000, 5000.5) == (0.5, "rounding")
    assert classify_variance(5000, 5060) == (60.0, "minor")       # 1.2%
    assert classify_variance(5000, 5500) == (500.0, "material")   # 10%


def test_variance_keeps_the_sign():
    """Переначислили — минус: корректировка должна уменьшать, а не удваивать."""
    variance, klass = classify_variance(5000, 4500)
    assert variance == -500.0 and klass == "material"


def test_unexpected_document_is_material():
    """Ждали ноль, пришёл счёт — это не округление, это разбирательство."""
    assert classify_variance(None, 3000)[1] == "material"
    assert classify_variance(0, 3000)[1] == "material"


def test_missing_document_is_not_a_variance():
    """Документа нет — работает расчётный метод, а не классификатор расхождений."""
    assert classify_variance(5000, None) == (0.0, "none")


def test_only_real_gaps_deserve_a_correction():
    assert not needs_correction("none")
    assert not needs_correction("rounding")
    assert needs_correction("minor")
    assert needs_correction("material")


# ── Автостатус периода ─────────────────────────────────────────────────────

def test_period_stays_open_while_the_month_runs():
    assert auto_status("2026-07-01", "2026-07-20") == "open"
    assert auto_status("2026-07-01", "2026-07-31") == "open"


def test_period_collects_then_goes_to_review():
    assert auto_status("2026-07-01", "2026-08-05", max_due_day=10) == "collecting"
    assert auto_status("2026-07-01", "2026-08-13", max_due_day=10) == "collecting"
    assert auto_status("2026-07-01", "2026-08-20", max_due_day=10) == "review"
