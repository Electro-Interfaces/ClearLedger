from datetime import date

import pytest

from app.services.accounting_business_date import (
    AccountingBusinessDateConflict,
    resolve_accounting_business_date,
)


def test_business_date_uses_moscow_date_at_utc_midnight_boundary():
    resolved = resolve_accounting_business_date({
        "Закрытие": "2026-08-17T21:30:00+00:00",
        "ОСЭНомер": "208-42",
        "ДатаОСЭ": "2026-08-18",
    })

    assert resolved.value == date(2026, 8, 18)
    assert resolved.closed_date == date(2026, 8, 18)
    assert resolved.ose_date == date(2026, 8, 18)


def test_business_date_falls_back_to_ose_and_not_opening_time():
    resolved = resolve_accounting_business_date({
        "Открыта": "2026-08-17T07:00:00+03:00",
        "ОСЭНомер": "208-42",
        "ДатаОСЭ": "2026-08-18",
    })

    assert resolved.value == date(2026, 8, 18)
    assert resolved.closed_date is None
    assert resolved.ose_date == date(2026, 8, 18)


def test_business_date_missing_close_and_ose_is_needs_review_input():
    with pytest.raises(AccountingBusinessDateConflict, match="нельзя определить"):
        resolve_accounting_business_date({
            "Открыта": "2026-08-17T07:00:00+03:00",
            "ОСЭНомер": "208-42",
        })


def test_business_date_close_and_ose_conflict_is_needs_review_input():
    with pytest.raises(AccountingBusinessDateConflict, match="conflict"):
        resolve_accounting_business_date({
            "Закрытие": "2026-08-18T12:00:00+03:00",
            "ОСЭНомер": "208-42",
            "ДатаОСЭ": "2026-08-17",
        })
