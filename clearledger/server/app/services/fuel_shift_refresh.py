"""Переигровка уже загруженных смен STS — дописать продажи, когда источник их отдал.

Канал приёма (`ingest_fuel_shifts`) пропускает смену, которая уже есть в БД
(защита от дублей). Поэтому смена, снятая в момент, когда STS ещё не отдавал
детализацию (смена была ОТКРЫТА на момент загрузки), навсегда остаётся с нулевой
выручкой — и молча занижает всю аналитику. Этот сервис ходит в STS по
СУЩЕСТВУЮЩИМ сменам и дописывает продажи.

Два железных правила:

1. **Пустой ответ STS не затирает сохранённое.** Обновление только «вверх» —
   из пустого в наполненное. Иначе сбой источника обнулил бы историю.
2. **Смена, по которой STS не отдаёт детализацию, помечается `sales_missing`.**
   Это не ноль выручки, а отсутствие данных: у АЗС 205/207/208/209/210/9008
   продажи до подключения к контуру STS (янв–фев 2026) в источнике отсутствуют
   вовсе, при том что касса (`money`) и ТТН (`receipt`) по этим сменам есть.
   Без признака 721 такая смена считается нулевой выручкой и занижает средние.

Смены закрытого периода (`is_locked`) не трогаются.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DataEntry, FuelCashMovement, FuelPump, FuelShift, FuelShiftSale, FuelStation, FuelTank,
)
from app.services.fuel_mappings import build_sales_agg, load_mapping_context
from app.services.fuel_transactions import resolve_sts
from app.services.sts_client import sts_get_shift_report, sts_get_shifts


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _density(v: Any) -> float | None:
    d = _int_or_none(v)
    if d is None:
        try:
            return round(float(v), 4)
        except (TypeError, ValueError):
            return None
    # STS отдаёт плотность целым (830 = 0.830 г/см³) либо дробным
    return round(d / 1000.0, 4) if d > 10 else round(float(d), 4)


def _report_totals(report: dict) -> tuple[float, float, int]:
    """psm.total → (литры, сумма, число позиций)."""
    rows = ((report.get("psm") or {}).get("total")) or []
    liters = sum(_f((t.get("release") or {}).get("quantity")) for t in rows)
    amount = sum(_f((t.get("release") or {}).get("amount")) for t in rows)
    return liters, amount, len(rows)


def _fuel_breakdown(report: dict) -> list[dict]:
    out: list[dict] = []
    for t in ((report.get("psm") or {}).get("total")) or []:
        svc = t.get("service") or {}
        rel = t.get("release") or {}
        code = str(svc.get("service_code") or "").strip()
        name = str(svc.get("service_name") or "").strip()
        if not code and not name:
            continue
        out.append({
            "fuel_code": code, "fuel_name": name,
            "liters": _f(rel.get("quantity")), "amount": _f(rel.get("amount")),
        })
    return out


async def _rebuild_shift(
    db: AsyncSession, company_id: uuid.UUID, shift: FuelShift,
    station_code: int, system_code: int, report: dict, ctx,
) -> None:
    """Переписать продажи/резервуары/ТРК/кассу смены по свежему отчёту STS."""
    liters, amount, _ = _report_totals(report)
    chan_agg = build_sales_agg(report, ctx)

    cash = sum(a["amount"] for (ch, _), a in chan_agg.items() if ch == "retail_cash")
    card = sum(a["amount"] for (ch, _), a in chan_agg.items() if ch == "retail_card")
    voucher = sum(a["amount"] for (ch, _), a in chan_agg.items()
                  if ch not in ("retail_cash", "retail_card"))

    shift.total_liters = liters
    shift.total_amount = amount
    shift.cash = cash
    shift.card = card
    shift.voucher = voucher
    shift.raw_report = report
    shift.sales_missing = False

    # Дочерние срезы смены пересобираются целиком — источник тот же отчёт.
    # Ручные правки живут в FuelShiftSaleOverride (натуральный ключ) и не страдают.
    for table in (FuelShiftSale, FuelTank, FuelPump, FuelCashMovement):
        await db.execute(delete(table).where(table.shift_id == shift.id))

    for (channel, code), a in chan_agg.items():
        db.add(FuelShiftSale(
            company_id=company_id, shift_id=shift.id,
            payment_channel=channel, fuel_code=code,
            liters=a["liters"], amount=a["amount"], discount=a["discount"],
            warehouse_name=a["warehouse"],
        ))

    for t in report.get("release") or []:
        svc = t.get("service") or {}
        doc_beg = t.get("doc_beg") or {}
        doc_end = t.get("doc_end") or {}
        rel = t.get("release") or {}
        recv = t.get("receipt") or {}
        rest = t.get("rest") or {}
        water = t.get("water") or {}
        db.add(FuelTank(
            shift_id=shift.id,
            tank_number=t.get("tank", 0),
            fuel_type=svc.get("service_name", ""),
            fuel_code=_int_or_none(svc.get("service_code")),
            volume_start=_f(doc_beg.get("volume")),
            volume_end=_f(doc_end.get("volume")),
            sales=_f(rel.get("volume")),
            volume_received=_f(recv.get("volume")),
            fact_volume=_f(rest.get("volume")) or None,
            fact_mass=_f(rest.get("amount")) or None,
            mass_start=_f(doc_beg.get("amount")) or None,
            mass_end=_f(doc_end.get("amount")) or None,
            mass_sales=_f(rel.get("amount")) or None,
            mass_received=_f(recv.get("amount")) or None,
            density=_density(t.get("density_end")),
            density_beg=_density(t.get("density_beg")),
            temp_beg=_f(t.get("temp_beg")) or None,
            temp_end=_f(t.get("temp_end")) or None,
            level_end=_f(t.get("level_end")) or None,
            water_level=_f(water.get("level")) or None,
            water_volume=_f(water.get("volume")) or None,
        ))

    for p in ((report.get("psm") or {}).get("data")) or []:
        svc = p.get("service") or {}
        rel = p.get("release") or {}
        db.add(FuelPump(
            shift_id=shift.id,
            pump_number=p.get("pump", 0),
            nozzle=str(p.get("nozzle", "")),
            fuel_type=svc.get("service_name", ""),
            fuel_code=_int_or_none(svc.get("service_code")),
            tank_number=_int_or_none(p.get("tank")),
            sales_volume=_f(rel.get("volume")),
            amount=_f(rel.get("cost")),
            psm_beg=_f(p.get("psm_beg")) or None,
            psm_end=_f(p.get("psm_end")) or None,
            price=_f(p.get("price")) or None,
            density=_density(p.get("density")),
        ))

    for m in report.get("money") or []:
        op = m.get("operation") or {}
        db.add(FuelCashMovement(
            shift_id=shift.id,
            operation_id=int(op.get("id", 0) or 0),
            operation_name=str(op.get("name", "") or ""),
            amount=_f(m.get("volume")),
            pos_number=_int_or_none(m.get("pos")),
        ))

    # L1-маркер смены: сверка ОРП идёт по meta, а не по FuelShift — обновляем вместе.
    marker = f"sts-shift-{system_code}-{station_code}-{shift.shift_number}"
    entry = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.source_label == marker,
    ).limit(1))).scalar_one_or_none()
    if entry is not None:
        meta = dict(entry.meta or {})
        meta.update({
            "amount": str(amount), "totalAmount": str(amount),
            "totalLiters": str(liters), "cash": str(cash),
            "card": str(card), "voucher": str(voucher),
            "fuel_breakdown": _fuel_breakdown(report),
        })
        entry.meta = meta


async def refresh_shifts(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    station_codes: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    only_zero: bool = True,
    dry_run: bool = False,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Переспросить STS по существующим сменам и дописать продажи.

    only_zero — работать только по сменам с нулевой выручкой (обычный режим:
    дешёвая доводка пробелов). False — переспросить весь отбор (полная сверка
    с источником; тяжело, использовать точечно по периоду).
    """
    conn = await resolve_sts(db, company_id)
    if conn is None:
        return {"error": "Нет подключения STS у компании", "checked": 0}

    q = (
        select(FuelShift, FuelStation.code, FuelStation.sts_system_code)
        .join(FuelStation, FuelStation.id == FuelShift.station_id)
        .where(FuelShift.company_id == company_id, FuelShift.is_locked.is_(False))
        .order_by(FuelShift.opened_at)
    )
    if only_zero:
        q = q.where(FuelShift.total_amount == 0)
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    # Границы периода — datetime, а не строка: asyncpg не приводит текст к timestamptz.
    # Правый край включительно (иначе последний день периода отбрасывается — см. CLAUDE.md).
    if date_from:
        q = q.where(FuelShift.opened_at >= datetime.fromisoformat(f"{date_from}T00:00:00+03:00"))
    if date_to:
        q = q.where(FuelShift.opened_at <= datetime.fromisoformat(f"{date_to}T23:59:59+03:00"))

    rows = (await db.execute(q)).all()
    ctx = await load_mapping_context(db, company_id)

    stats = {
        "checked": 0, "recovered": 0, "recovered_amount": 0.0, "recovered_liters": 0.0,
        "no_data": 0, "true_zero": 0, "errors": 0, "closed_dates": 0,
        "total": len(rows), "dry_run": dry_run,
    }
    details: list[dict] = []

    # Даты закрытия открытых смен — из списка смен станции (в отчёте их нет).
    closed_cache: dict[tuple[int, int], dict] = {}

    for shift, st_code, sys_code in rows:
        system = int(sys_code or conn["systems"][0])
        stats["checked"] += 1
        if progress and stats["checked"] % 10 == 0:
            progress(dict(stats))

        try:
            report = await sts_get_shift_report(
                conn["base_url"], conn["login"], conn["pwd"],
                system, int(st_code), int(shift.shift_number),
            )
        except Exception as e:  # noqa: BLE001 — одна смена не валит прогон
            stats["errors"] += 1
            details.append({"station": st_code, "shift": shift.shift_number,
                            "result": "error", "message": str(e)[:120]})
            continue

        liters, amount, psm_rows = _report_totals(report)
        has_sales = bool(report.get("sales")) or psm_rows > 0

        if amount > 0:
            stats["recovered"] += 1
            stats["recovered_amount"] += amount
            stats["recovered_liters"] += liters
            details.append({"station": st_code, "shift": shift.shift_number,
                            "date": shift.opened_at.date().isoformat() if shift.opened_at else "",
                            "result": "recovered", "amount": round(amount, 2),
                            "liters": round(liters, 2)})
            if not dry_run:
                await _rebuild_shift(db, company_id, shift, int(st_code), system, report, ctx)
        elif has_sales:
            # Смена открывалась, отпуска не было — честный ноль, не пробел.
            stats["true_zero"] += 1
            if not dry_run and shift.sales_missing:
                shift.sales_missing = False
        else:
            stats["no_data"] += 1
            if not dry_run and not shift.sales_missing:
                shift.sales_missing = True

        # Смена, загруженная открытой, не имеет даты закрытия — дотянуть из /v1/shifts.
        if shift.closed_at is None and not dry_run:
            key = (system, int(st_code))
            if key not in closed_cache:
                d = shift.opened_at.date().isoformat() if shift.opened_at else None
                try:
                    lst = await sts_get_shifts(
                        conn["base_url"], conn["login"], conn["pwd"], system, int(st_code), d, None)
                except Exception:  # noqa: BLE001
                    lst = []
                closed_cache[key] = {int(s["shift"]): s for s in lst if s.get("shift") is not None}
            meta = closed_cache[key].get(int(shift.shift_number)) or {}
            if meta.get("dt_close"):
                from app.routers.fuel_router import _parse_dt  # локальный импорт: цикл
                shift.closed_at = _parse_dt(meta["dt_close"])
                stats["closed_dates"] += 1

        if not dry_run and stats["checked"] % 50 == 0:
            await db.commit()

    if not dry_run:
        await db.commit()

    stats["recovered_amount"] = round(stats["recovered_amount"], 2)
    stats["recovered_liters"] = round(stats["recovered_liters"], 2)
    stats["details"] = details[:500]
    return stats


async def followup_fuel_sales(company_id: uuid.UUID, date_from: str, date_to: str) -> dict:
    """Доводка после прогона канала продаж: дописать смены и догрузить реализации.

    Зачем отдельный шаг. Приём смен дедуплицирует по натуральному ключу, поэтому
    смена, снятая в момент, когда она ещё ОТКРЫТА, остаётся с нулевой выручкой
    навсегда: следующий прогон видит её как уже загруженную и пропускает. Ночной
    прогон в 03:00 попадает ровно в открытую суточную смену — и у ГИГ так молча
    пропали 23–26 и 28–29 июля, при живой сети и работающем расписании.

    Реализации (`fuel_transactions`) вторая половина проблемы: у них не было расписания
    вообще — только кнопка «Синхронизировать» в реестре операций. У ГИГ они встали
    11 июля, потому что в этот день их последний раз загрузили руками.

    Обе операции идемпотентны: `refresh_shifts` обновляет смену только «вверх»
    (пустой ответ источника сохранённое не затирает), приём реализаций дедуплицирует
    по STS id. Ошибка доводки не должна влиять на статус самого прогона — вызывающий
    ловит её и пишет в лог.
    """
    from app.database import async_session_factory
    from app.services.fuel_transactions import (
        ingest_station_window, list_stations, month_windows, resolve_sts,
    )

    out: dict = {"shifts": {}, "tx_created": 0, "tx_errors": 0}
    async with async_session_factory() as db:
        out["shifts"] = await refresh_shifts(
            db, company_id, date_from=date_from, date_to=date_to, only_zero=True)

        conn = await resolve_sts(db, company_id)
        if conn is None:
            return out
        stations = await list_stations(db, company_id, conn)
        for st in stations:
            for wf, wt in month_windows(date_from, date_to):
                try:
                    r = await ingest_station_window(db, company_id, st, conn, wf, wt)
                    # Коммит обязателен здесь: ingest только пишет в транзакцию, и без
                    # коммита всё вставленное откатится на выходе из сессии.
                    await db.commit()
                    out["tx_created"] += int(r.get("created") or 0)
                except Exception:  # noqa: BLE001 — одна станция не валит доводку
                    await db.rollback()
                    out["tx_errors"] += 1
    return out
