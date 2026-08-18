from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AccountingBusinessDateConflict(ValueError):
    pass


@dataclass(frozen=True)
class AccountingBusinessDate:
    value: date
    closed_date: date | None
    ose_date: date | None


def _station_date(value: object, timezone_name: str, field: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccountingBusinessDateConflict(f"Некорректная дата {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AccountingBusinessDateConflict(f"{field} не содержит timezone")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise AccountingBusinessDateConflict(
            f"Неизвестный timezone станции: {timezone_name}",
        ) from exc
    return parsed.astimezone(zone).date()


def _ose_date(shift: dict, timezone_name: str) -> date | None:
    explicit = (
        shift.get("ДатаОСЭ") or shift.get("ОСЭДата")
        or shift.get("BusinessDate")
    )
    if explicit:
        raw = str(explicit).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return _station_date(raw, timezone_name, "Смена.ДатаОСЭ")
    ose = str(shift.get("ОСЭНомер") or shift.get("НомерСмены") or "").strip()
    digits = re.sub(r"\D", "", ose)
    if len(digits) < 10:
        return None
    encoded = digits[-10:-2]
    try:
        return datetime.strptime(encoded, "%d%m%Y").date()
    except ValueError:
        return None


def resolve_accounting_business_date(
    shift: dict,
    timezone_name: str = "Europe/Moscow",
) -> AccountingBusinessDate:
    closed = _station_date(shift.get("Закрытие"), timezone_name, "Смена.Закрытие")
    ose = _ose_date(shift, timezone_name)
    if closed is not None and ose is not None and closed != ose:
        raise AccountingBusinessDateConflict(
            f"business-date conflict: закрытие={closed.isoformat()}, ОСЭ={ose.isoformat()}",
        )
    value = closed or ose
    if value is None:
        raise AccountingBusinessDateConflict(
            "BusinessDate нельзя определить: нет закрытия с timezone и даты ОСЭ",
        )
    return AccountingBusinessDate(value, closed, ose)
