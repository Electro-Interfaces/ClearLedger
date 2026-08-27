"""/api/charge-sessions — импорт и данные зарядных сессий ЭЗС (energy, РусГидро).

Источник — Excel-выгрузка ChargeTransactions (26 колонок). Импорт парсит файл,
нормализует поля, дедуплицирует по «ID сессии» и сохраняет в charge_sessions.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import String, and_ as sa_and, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import ChargePayment, ChargeRejected, ChargeSession, Region, ServiceLocation, User
from app.services.export_audit import log_export
from app.services.export_files import xlsx_response
from app.services.session_scope import session_scope_conds
from app.services.pivot_export import build_sessions_pivot

router = APIRouter(prefix="/charge-sessions", tags=["Зарядные сессии"])


def _day_bounds(date_from: str, date_to: str) -> tuple[datetime, datetime]:
    """«YYYY-MM-DD» × 2 → полуинтервал [начало дня; начало следующего за date_to).
    Верхняя граница исключающая — иначе платежи последней секунды дня теряются."""
    try:
        df = date.fromisoformat(date_from[:10])
        dt = date.fromisoformat(date_to[:10])
    except ValueError as exc:
        raise HTTPException(400, "Неверный формат даты (YYYY-MM-DD)") from exc
    return (datetime.combine(df, datetime.min.time()),
            datetime.combine(dt, datetime.min.time()) + timedelta(days=1))


@router.post("/import")
async def import_sessions(
    company_id: str,
    file: UploadFile = File(...),
    mode: str = "append",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Импорт Excel-выгрузки зарядных сессий.

    mode:
      • 'append'  — подгрузить только новые (дедуп по «ID сессии»);
      • 'replace' — переписать: удалить все сессии компании и загрузить заново.

    Парсинг и нормализация (коннектор/тип клиента, регион, дедуп, режим) — через
    общий сервис ingest_charge_sessions (тот же путь, что и у канала ЭЗС)."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_sessions_normalize import ingest_charge_sessions, parse_sessions_xlsx

    data = await file.read()
    try:
        rows = parse_sessions_xlsx(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {exc}") from exc

    result = await ingest_charge_sessions(db, cid, rows, channel_id=None, mode=mode)
    await db.commit()
    return {"created": result["created"], "skipped": result["skipped"],
            "errors": result["errors"], "deleted": result.get("deleted", 0),
            "mode": result.get("mode", mode),
            # Объекты — источник правды: сессии по станциям вне справочника
            # поднимаются ошибкой (данные загружены с location_id=NULL).
            "unmatched_stations": result.get("unmatched_stations", []),
            "unmatched_sessions": result.get("unmatched_sessions", 0),
            "message": result.get("message", "")}


@router.post("/enrich")
async def enrich_sessions(
    company_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Обогащение сессий справочником «Организации» (xlsx): проставить
    наименование корпоративного клиента (client_name) ЮЛ-сессиям по телефону
    (user_id = телефон организации). Идемпотентно, отдельно от загрузки сессий."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_sessions_normalize import enrich_sessions_with_orgs, parse_orgs_xlsx

    data = await file.read()
    try:
        parsed = parse_orgs_xlsx(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {exc}") from exc
    if not parsed.get("orgs"):
        raise HTTPException(400, "В справочнике не найдено строк «телефон + название»")

    result = await enrich_sessions_with_orgs(db, cid, parsed)
    await db.commit()
    return result


@router.post("/reenrich")
async def reenrich_sessions(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Переприменить обогащение из сохранённого реестра corporate_clients (без файла).
    Нужно после перезагрузки таблицы сессий — восстанавливает распределение по ЮЛ."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_sessions_normalize import enrich_from_registry
    result = await enrich_from_registry(db, cid)
    await db.commit()
    return result


@router.get("/count")
async def count_sessions(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    cid = await assert_company_product(company_id, current_user, db, "sales")
    n = (await db.execute(
        select(func.count()).select_from(ChargeSession).where(ChargeSession.company_id == cid)
    )).scalar_one()
    return {"count": int(n)}


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


def _payment_scope_cond(cid, stations: list[str], regions: list[str]):
    """Сужение платежей контуром рабочей области.

    У `charge_payments` нет своей станции — единственная связь с сетью идёт через
    `session_ext_id`. Поэтому контур применяется отбором сессий, а платёж без
    сессии в сужённый ответ попасть не может: отнести его к станции нечем.
    Возвращает None, если контур не задан."""
    conds = session_scope_conds(cid, stations or None, regions or None)
    if not conds:
        return None
    return ChargePayment.session_ext_id.in_(
        select(ChargeSession.session_ext_id).where(ChargeSession.company_id == cid, *conds))


@router.get("/payments/summary")
async def payments_summary(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = Query(None, description="коды ЭЗС через запятую — контур"),
    regions: str | None = Query(None, description="регионы через запятую — контур"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сводка эквайринга ЭЗС за период — витрина «Платежи и чеки».

    Выручка — это `amount` (фактическое списание). Холд считаем отдельно и НЕ
    суммируем с выручкой: оплата картой трёхтактная (холд → списание → возврат
    остатка), и по холдам сумма втрое больше реальной.

    «Зависший холд» — строка, где деньги заблокированы, но ни списания, ни
    возврата не было: клиент заряжаться не начал, а средства у него удержаны."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    df, dt = _day_bounds(date_from, date_to)
    scope = [ChargePayment.company_id == cid,
             ChargePayment.paid_at >= df, ChargePayment.paid_at < dt]
    scoped = _payment_scope_cond(cid, _csv(stations), _csv(regions))
    if scoped is not None:
        scope.append(scoped)

    t = (await db.execute(select(
        func.count().label("count"),
        func.coalesce(func.sum(ChargePayment.amount), 0).label("amount"),
        func.coalesce(func.sum(ChargePayment.hold_amount), 0).label("hold"),
        func.coalesce(func.sum(ChargePayment.refund_amount), 0).label("refund"),
        func.count(ChargePayment.receipt_url).label("receipts"),
    ).where(*scope))).one()

    stuck = (await db.execute(select(
        func.count().label("count"),
        func.coalesce(func.sum(ChargePayment.hold_amount), 0).label("amount"),
    ).where(*scope, ChargePayment.hold_amount > 0, ChargePayment.refund_amount <= 0,
            ChargePayment.amount <= 0))).one()

    linked = (await db.execute(select(func.count()).where(
        *scope, ChargePayment.session_ext_id.is_not(None),
        select(ChargeSession.id).where(
            ChargeSession.company_id == cid,
            ChargeSession.session_ext_id == ChargePayment.session_ext_id).exists()))).scalar_one()

    month = func.to_char(ChargePayment.paid_at, "YYYY-MM")
    by_month = (await db.execute(select(
        month.label("bucket"), func.count().label("count"),
        func.coalesce(func.sum(ChargePayment.amount), 0).label("amount"),
        func.coalesce(func.sum(ChargePayment.refund_amount), 0).label("refund"),
        func.count(ChargePayment.receipt_url).label("receipts"),
    ).where(*scope).group_by(month).order_by(month))).all()

    by_type = (await db.execute(select(
        ChargePayment.op_type.label("name"), func.count().label("count"),
        func.coalesce(func.sum(ChargePayment.amount), 0).label("amount"),
    ).where(*scope).group_by(ChargePayment.op_type)
     .order_by(func.sum(ChargePayment.amount).desc()))).all()

    cnt = int(t.count or 0)
    return {
        "totals": {
            "count": cnt,
            "amount": float(t.amount or 0),
            "hold": float(t.hold or 0),
            "refund": float(t.refund or 0),
            "receipts": int(t.receipts or 0),
            "avgCheck": round(float(t.amount or 0) / cnt, 2) if cnt else 0,
            "linked": int(linked or 0),
            "orphans": cnt - int(linked or 0),
            "stuckCount": int(stuck.count or 0),
            "stuckAmount": float(stuck.amount or 0),
            # Экран обязан сказать, что при контуре платежи без сессии не видны:
            # иначе итог молча расходится с реестром.
            "scoped": scoped is not None,
        },
        "byMonth": [{"bucket": r.bucket, "count": int(r.count), "amount": float(r.amount),
                     "refund": float(r.refund), "receipts": int(r.receipts)} for r in by_month],
        "byType": [{"name": r.name or "—", "count": int(r.count), "amount": float(r.amount)}
                   for r in by_type],
    }


@router.get("/payments/list")
async def payments_list(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = Query(None, description="коды ЭЗС через запятую — контур"),
    regions: str | None = Query(None, description="регионы через запятую — контур"),
    only: str | None = Query(None, description="orphans | stuck | refunds — фильтр разбора"),
    limit: int = Query(200, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Реестр платежей за период (последние сверху). `only` — срез для разбора."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    df, dt = _day_bounds(date_from, date_to)
    conds = [ChargePayment.company_id == cid,
             ChargePayment.paid_at >= df, ChargePayment.paid_at < dt]
    scoped = _payment_scope_cond(cid, _csv(stations), _csv(regions))
    if scoped is not None:
        conds.append(scoped)
    if only == "orphans":
        conds.append(~select(ChargeSession.id).where(
            ChargeSession.company_id == cid,
            ChargeSession.session_ext_id == ChargePayment.session_ext_id).exists())
    elif only == "stuck":
        conds += [ChargePayment.hold_amount > 0, ChargePayment.refund_amount <= 0,
                  ChargePayment.amount <= 0]
    elif only == "refunds":
        conds.append(ChargePayment.refund_amount > 0)
    rows = (await db.execute(select(ChargePayment).where(*conds)
            .order_by(ChargePayment.paid_at.desc()).limit(limit))).scalars().all()
    return [{
        "id": p.payment_ext_id, "sessionId": p.session_ext_id, "bankTxnId": p.bank_txn_id,
        "paidAt": p.paid_at.isoformat() if p.paid_at else None,
        "amount": float(p.amount or 0), "hold": float(p.hold_amount or 0),
        "refund": float(p.refund_amount or 0), "opType": p.op_type,
        "status": p.status_code, "receiptUrl": p.receipt_url, "phone": p.user_phone,
    } for p in rows]


@router.get("/rejected")
async def rejected_summary(
    company_id: str,
    date_from: str,
    date_to: str,
    stations: str | None = Query(None, description="коды ЭЗС через запятую — контур"),
    regions: str | None = Query(None, description="регионы через запятую — контур"),
    limit: int = Query(500, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отбракованное источником: сколько, на сколько и что именно.

    Эти зарядки в витринах не участвуют — их нет ни в `charge_sessions`, ни в
    `charge_payments` (решение МАГа 27.08.2026: «не показываем вообще»). Но сами
    по себе они материал разбора: где и у кого система сочла транзакцию
    недостоверной. Экран отвечает на это и ни на что больше — денежных итогов
    сети здесь нет и быть не должно.
    """
    cid = await assert_company_product(company_id, current_user, db, "sales")
    df, dt = _day_bounds(date_from, date_to)
    R = ChargeRejected
    conds = [R.company_id == cid, R.occurred_at >= df, R.occurred_at < dt]
    codes, regs = _csv(stations), _csv(regions)
    if codes:
        conds.append(R.station_code.in_(codes))
    if regs:
        # Регион у журнала не хранится: он свойство объекта, а не транзакции.
        # Резолвим через объект той же связкой, что и остальные разрезы.
        conds.append(R.location_id.in_(
            select(cast(ServiceLocation.id, String))
            .join(Region, Region.id == ServiceLocation.region_id)
            .where(ServiceLocation.company_id == cid, Region.name.in_(regs))))

    totals = (await db.execute(select(
        func.count().filter(R.kind == "session").label("sessions"),
        func.count().filter(R.kind == "payment").label("payments"),
        func.coalesce(func.sum(R.energy_kwh).filter(R.kind == "session"), 0).label("kwh"),
        func.coalesce(func.sum(R.amount).filter(R.kind == "session"), 0).label("amount"),
        func.coalesce(func.sum(R.amount).filter(R.kind == "payment"), 0).label("paid"),
        func.count(func.distinct(R.station_code)).label("stations"),
        func.count(func.distinct(R.user_id)).label("users"),
    ).where(*conds))).one()

    month = func.to_char(R.occurred_at, "YYYY-MM")
    by_month = (await db.execute(select(
        month.label("bucket"), func.count().label("count"),
        func.coalesce(func.sum(R.amount), 0).label("amount"),
    ).where(*conds, R.kind == "session").group_by(month).order_by(month))).all()

    by_station = (await db.execute(select(
        R.station_code.label("code"), func.count().label("count"),
        func.coalesce(func.sum(R.amount), 0).label("amount"),
    ).where(*conds, R.kind == "session")
     .group_by(R.station_code).order_by(func.count().desc()).limit(20))).all()

    rows = (await db.execute(select(R).where(*conds, R.kind == "session")
                             .order_by(R.occurred_at.desc()).limit(limit))).scalars().all()
    # Платёж отбракованной зарядки лежит в журнале отдельной строкой — сводим их
    # по сессии, чтобы в реестре зарядка и её деньги стояли рядом.
    pays = {p.session_ext_id: p for p in (await db.execute(
        select(R).where(R.company_id == cid, R.kind == "payment",
                        R.session_ext_id.in_([r.ext_id for r in rows] or ["—"]))
    )).scalars().all()}

    return {
        "totals": {
            "sessions": int(totals.sessions or 0), "payments": int(totals.payments or 0),
            "kwh": float(totals.kwh or 0), "amount": float(totals.amount or 0),
            "paid": float(totals.paid or 0),
            "stations": int(totals.stations or 0), "users": int(totals.users or 0),
        },
        "byMonth": [{"bucket": r.bucket, "count": int(r.count), "amount": float(r.amount)}
                    for r in by_month],
        "byStation": [{"code": r.code or "—", "count": int(r.count), "amount": float(r.amount)}
                      for r in by_station],
        "items": [{
            "id": str(r.id), "sessionId": r.ext_id,
            "occurredAt": r.occurred_at.isoformat() if r.occurred_at else None,
            "stationCode": r.station_code, "userId": r.user_id,
            "energyKwh": float(r.energy_kwh or 0), "amount": float(r.amount or 0),
            "status": r.status, "reason": r.reason,
            "paidAmount": float(pays[r.ext_id].amount or 0) if r.ext_id in pays else None,
        } for r in rows],
    }


@router.get("/reconciliation")
async def charge_reconciliation_summary(
    company_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сверка «сессия ↔ платёж ↔ чек»: где данные о зарядках расходятся с деньгами."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_reconciliation import reconciliation
    df, dt = _day_bounds(date_from, date_to)
    return await reconciliation(db, cid, df.date(), (dt - timedelta(days=1)).date())


@router.get("/reconciliation/list")
async def charge_reconciliation_rows(
    company_id: str,
    date_from: str,
    date_to: str,
    kind: str = Query(..., pattern="^(impossible|double|underpaid|overpaid|no_payment|no_receipt|orphan|refund_full|hold_rule|receipt_no_txn|not_card)$"),
    limit: int = Query(200, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Строки одного расхождения — то, с чем идут разбираться."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_reconciliation import reconciliation_list
    df, dt = _day_bounds(date_from, date_to)
    return await reconciliation_list(db, cid, df.date(), (dt - timedelta(days=1)).date(),
                                     kind, limit)


@router.get("/reconciliation/by")
async def charge_reconciliation_by(
    company_id: str,
    date_from: str,
    date_to: str,
    by: str = Query("station",
                    pattern="^(station|region|month|connector|charge_type|client|card_status)$"),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Где копятся расхождения: разрез сверки по станции или региону."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.services.charge_reconciliation import reconciliation_by
    df, dt = _day_bounds(date_from, date_to)
    return await reconciliation_by(db, cid, df.date(), (dt - timedelta(days=1)).date(), by, limit)


@router.get("/station-sales")
async def station_sales(
    company_id: str,
    location_id: str,
    months: int = Query(12, ge=1, le=60, description="глубина помесячной разбивки"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Реализация одной точки: сессии + деньги + чеки — вкладка «Реализация» карточки.

    Разрез объекта, а не сети: сессии берутся по материализованной связи
    `location_id`, платежи — те, что сцепились со своими сессиями по
    `session_ext_id`. Платёж без сессии объекта не имеет и в карточку не
    попадает: у него нет станции — это разбор сетевого уровня («Платежи и чеки»).

    «Сессия без платежа» тут — не потеря денег, а либо постоплата ЮЛ, либо
    период, за который платежи ещё не выгружены; поэтому считается и
    показывается отдельно от выручки.
    """
    cid = await assert_company_product(company_id, current_user, db, "sales")
    # Скоуп данных участника: у кого выдано пять станций, чужой объект по прямой
    # ссылке не открывается — id объекта приходит из запроса, а не из его списка.
    from app.scope import current_object_scope
    allowed = current_object_scope()
    if allowed and location_id not in allowed:
        raise HTTPException(403, "Объект вне вашего доступа")

    S, P = ChargeSession, ChargePayment
    scope = [S.company_id == cid, S.location_id == location_id]

    t = (await db.execute(select(
        func.count().label("count"),
        func.coalesce(func.sum(S.energy_kwh), 0).label("kwh"),
        # Канон выручки раздела: у ЮЛ amount = 0 (постоплата), сумма в client_amount.
        func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
        func.min(S.started_at).label("first_at"),
        func.max(S.started_at).label("last_at"),
        func.count(func.distinct(S.user_id)).label("clients"),
    ).where(*scope))).one()

    # Платежи объекта: join по внешнему id сессии (FK нет — платежи обгоняют сессии).
    pay_join = P.company_id == cid, P.session_ext_id == S.session_ext_id
    p = (await db.execute(select(
        func.count().label("count"),
        func.coalesce(func.sum(P.amount), 0).label("amount"),
        func.coalesce(func.sum(P.hold_amount), 0).label("hold"),
        func.coalesce(func.sum(P.refund_amount), 0).label("refund"),
        func.count(P.receipt_url).label("receipts"),
    ).select_from(S).join(P, sa_and(*pay_join)).where(*scope))).one()

    unpaid = (await db.execute(select(func.count()).select_from(S).where(
        *scope, S.amount > 0,
        ~select(P.id).where(P.company_id == cid,
                            P.session_ext_id == S.session_ext_id).exists()))).scalar_one()

    month = func.to_char(S.started_at, "YYYY-MM")
    by_month = (await db.execute(select(
        month.label("bucket"),
        func.count().label("sessions"),
        func.coalesce(func.sum(S.energy_kwh), 0).label("kwh"),
        func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
    ).where(*scope, S.started_at.is_not(None))
     .group_by(month).order_by(month.desc()).limit(months))).all()

    pay_month = func.to_char(S.started_at, "YYYY-MM")
    by_month_pay = {r.bucket: r for r in (await db.execute(select(
        pay_month.label("bucket"),
        func.count().label("payments"),
        func.coalesce(func.sum(P.amount), 0).label("paid"),
        func.count(P.receipt_url).label("receipts"),
    ).select_from(S).join(P, sa_and(*pay_join))
     .where(*scope, S.started_at.is_not(None))
     .group_by(pay_month))).all()}

    cnt = int(t.count or 0)
    return {
        "totals": {
            "sessions": cnt,
            "kwh": float(t.kwh or 0),
            "amount": float(t.amount or 0),
            "avgCheck": round(float(t.amount or 0) / cnt, 2) if cnt else 0,
            "clients": int(t.clients or 0),
            "firstAt": t.first_at.isoformat() if t.first_at else None,
            "lastAt": t.last_at.isoformat() if t.last_at else None,
            "payments": int(p.count or 0),
            "paid": float(p.amount or 0),
            "hold": float(p.hold or 0),
            "refund": float(p.refund or 0),
            "receipts": int(p.receipts or 0),
            "unpaidSessions": int(unpaid or 0),
        },
        "byMonth": _fill_months(by_month, by_month_pay),
    }


def _fill_months(rows, pay_by_bucket) -> list[dict[str, Any]]:
    """Помесячный ряд без дыр: месяц простоя показывается нулём, а не пропадает.

    Раньше строки без сессий просто отсутствовали, и в таблице реализации рядом
    вставали месяцы с разрывом в полгода — простой станции выглядел как отсутствие
    данных (замечание И. Н. Ступина 13.08.2026)."""
    have = {r.bucket: r for r in rows}
    if not have:
        return []
    def _key(b: str) -> tuple[int, int]:
        y, m = b.split("-")
        return int(y), int(m)
    (y, m), (ly, lm) = min(map(_key, have)), max(map(_key, have))
    out: list[dict[str, Any]] = []
    while (y, m) <= (ly, lm):
        b = f"{y:04d}-{m:02d}"
        r = have.get(b)
        pay = pay_by_bucket.get(b)
        out.append({
            "bucket": b,
            "sessions": int(r.sessions) if r else 0,
            "kwh": float(r.kwh) if r else 0.0,
            "amount": float(r.amount) if r else 0.0,
            "payments": int(getattr(pay, "payments", 0) or 0),
            "paid": float(getattr(pay, "paid", 0) or 0),
            "receipts": int(getattr(pay, "receipts", 0) or 0),
        })
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(out, key=lambda x: x["bucket"], reverse=True)


@router.get("/station-energy")
async def station_energy(
    company_id: str,
    location_id: str,
    date_from: str,
    date_to: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отпуск электроэнергии одной станцией за произвольный период — вкладка
    «Энергия» карточки. Отвечает на вопрос эксплуатации «сколько эта станция
    отпустила с … по …», не требуя доступа к деньгам («Реализация» — разрез
    продаж, у эксплуатации его нет).

    Канон цифр раздела соблюдён: средние считаются по СОСТОЯВШИМСЯ заправкам
    (`energy_kwh > 0`) — треть сессий не даёт тока и занижает среднее; «клиенты
    зарядились» — доля ВИЗИТОВ с отпуском, а не доля `result='Complete'`.

    Шаг ряда выбирается по длине периода: до 62 дней — по дням, дальше — по
    месяцам (иначе таблица за год превращается в 365 строк).
    """
    cid = await assert_company_product(company_id, current_user, db, "sales")
    from app.scope import current_object_scope
    allowed = current_object_scope()
    if allowed and location_id not in allowed:
        raise HTTPException(403, "Объект вне вашего доступа")

    dt_from, dt_to = _day_bounds(date_from, date_to)
    S = ChargeSession
    scope = [S.company_id == cid, S.location_id == location_id,
             S.started_at >= dt_from, S.started_at < dt_to]
    charged = S.energy_kwh > 0

    t = (await db.execute(select(
        func.count().label("sessions"),
        func.count().filter(charged).label("charged"),
        func.coalesce(func.sum(S.energy_kwh), 0).label("kwh"),
        func.coalesce(func.avg(S.energy_kwh).filter(charged), 0).label("avg_kwh"),
        func.coalesce(func.avg(S.duration_min).filter(charged), 0).label("avg_min"),
        func.count(func.distinct(S.user_id)).label("clients"),
        func.count(func.distinct(S.visit_key)).label("visits"),
        func.count(func.distinct(S.visit_key)).filter(S.visit_charged.is_(True)).label("visits_charged"),
        func.max(S.started_at).label("last_at"),
    ).where(*scope))).one()

    by_day = (dt_to - dt_from).days <= 62
    bucket = func.to_char(S.started_at, "YYYY-MM-DD" if by_day else "YYYY-MM")
    series = (await db.execute(select(
        bucket.label("bucket"),
        func.count().label("sessions"),
        func.count().filter(charged).label("charged"),
        func.coalesce(func.sum(S.energy_kwh), 0).label("kwh"),
    ).where(*scope).group_by(bucket).order_by(bucket))).all()

    conns = (await db.execute(select(
        S.connector_no.label("no"),
        func.max(S.connector_type).label("type"),
        func.count().label("sessions"),
        func.coalesce(func.sum(S.energy_kwh), 0).label("kwh"),
    ).where(*scope).group_by(S.connector_no).order_by(func.sum(S.energy_kwh).desc()))).all()

    # Ряд достраивается по КАЛЕНДАРЮ периода: месяц (или день) без единой зарядки
    # обязан стоять нулём, а не выпадать. Пропуск тихо «сжимал» простой станции —
    # на графике два соседних столбца оказывались с разрывом в полгода
    # (замечание И. Н. Ступина 13.08.2026).
    have = {r.bucket: r for r in series}
    slots: list[str] = []
    if by_day:
        cur = dt_from.date()
        while cur < dt_to.date():
            slots.append(cur.isoformat())
            cur += timedelta(days=1)
    else:
        y, m = dt_from.year, dt_from.month
        last = (dt_to - timedelta(days=1)).date()
        while (y, m) <= (last.year, last.month):
            slots.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    months = max(1, len({s[:7] for s in slots}))

    return {
        "bucket": "day" if by_day else "month",
        "totals": {
            "sessions": int(t.sessions or 0), "charged": int(t.charged or 0),
            "kwh": float(t.kwh or 0), "avgKwh": float(t.avg_kwh or 0),
            "avgMin": float(t.avg_min or 0), "clients": int(t.clients or 0),
            "visits": int(t.visits or 0), "visitsCharged": int(t.visits_charged or 0),
            # Среднемесячный отпуск за выбранный период — по календарным месяцам,
            # включая те, где станция молчала.
            "avgMonthKwh": float(t.kwh or 0) / months, "months": months,
            "lastAt": t.last_at.isoformat() if t.last_at else None,
        },
        "series": [{
            "bucket": b,
            "sessions": int(have[b].sessions) if b in have else 0,
            "charged": int(have[b].charged) if b in have else 0,
            "kwh": float(have[b].kwh) if b in have else 0.0,
        } for b in slots],
        "byConnector": [{"no": r.no or "—", "type": r.type or "", "sessions": int(r.sessions),
                         "kwh": float(r.kwh)} for r in conns],
    }


@router.get("/export")
async def export_sessions(
    company_id: str,
    date_from: str,
    date_to: str,
    user_type: str | None = None,
    client: str | None = None,
    stations: str | None = None,
    regions: str | None = None,
    limit: int = Query(60000, ge=1, le=200000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Построчная выгрузка сессий в xlsx с ОБЕИМИ ценами: тариф станции (розница)
    и договорной тариф ЮЛ + обе выручки + разница. Фильтры: период (обяз.),
    опц. тип клиента (ФЛ/ЮЛ), конкретный клиент (client_name), сужение по
    станциям/регионам (контур рабочей области)."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    try:
        df = date.fromisoformat(date_from[:10])
        dt = date.fromisoformat(date_to[:10])
    except ValueError as exc:
        raise HTTPException(400, "Неверный формат даты (YYYY-MM-DD)") from exc
    lo = datetime.combine(df, datetime.min.time())
    hi = datetime.combine(dt, datetime.max.time())

    st_codes = [x.strip() for x in stations.split(",") if x.strip()] if stations else None
    regs = [x.strip() for x in regions.split(",") if x.strip()] if regions else None
    S = ChargeSession
    q = select(S).where(S.company_id == cid, S.started_at.is_not(None),
                        S.started_at >= lo, S.started_at <= hi,
                        *session_scope_conds(cid, st_codes, regs))
    if user_type:
        q = q.where(S.user_type == user_type)
    if client:
        q = q.where(S.client_name == client)
    rows = (await db.execute(q.order_by(S.started_at).limit(limit))).scalars().all()

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sessions"
    ws.append(["ID сессии", "Станция", "Регион", "Коннектор", "Начало", "Энергия кВтч",
               "Тип клиента", "Клиент (ЮЛ)",
               "Тариф станции ₽/кВтч", "Выручка по рознице ₽",
               "Тариф ЮЛ ₽/кВтч", "Выручка ЮЛ ₽", "Разница ЮЛ−розница ₽"])
    for s in rows:
        energy = float(s.energy_kwh or 0)
        retail_tariff = float(s.tariff or 0)
        retail_rev = round(energy * retail_tariff, 2)   # розница-эквивалент (что было бы по станции)
        corp_amount = float(s.client_amount) if s.client_amount is not None else None
        diff = round(corp_amount - retail_rev, 2) if corp_amount is not None else None
        ws.append([
            s.session_ext_id, s.station_code, s.region, s.connector_type,
            s.started_at.strftime("%d.%m.%Y %H:%M") if s.started_at else "",
            round(energy, 3), s.user_type, s.client_name,
            retail_tariff, retail_rev,
            float(s.client_tariff) if s.client_tariff is not None else None,
            corp_amount, diff,
        ])
    buf = io.BytesIO()
    wb.save(buf)

    # След выгрузки: в файле — персональные данные клиентов и обе выручки.
    scope = f"{date_from[:10]}…{date_to[:10]}"
    if user_type:
        scope += f", тип {user_type}"
    if client:
        scope += f", клиент «{client}»"
    if regs:
        scope += f", регионов {len(regs)}"
    if st_codes:
        scope += f", станций {len(st_codes)}"
    log_export(db, cid, current_user,
               f"Реестр сессий ЭЗС (xlsx): {len(rows)} строк, период {scope}")

    fname = f"Реестр сессий ЭЗС {date_from[:10]} — {date_to[:10]}"
    if client:
        fname += f" · {client}"
    return xlsx_response(wb, f"{fname}.xlsx")


@router.get("/export/pivot")
async def export_sessions_pivot(
    company_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200000, ge=1, le=500000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Сессии + ГОТОВАЯ сводная таблица Excel (станция × коннектор).

    Сводная пересчитывается при открытии файла средствами Excel. В других
    редакторах (LibreOffice, Google Sheets, веб-Excel) она останется пустой —
    там работает лист «Транзакции» с полными данными."""
    cid = await assert_company_product(company_id, current_user, db, "sales")
    wb, stats = await build_sessions_pivot(db, cid, date_from, date_to, limit)

    span = (f"{date_from[:10]} — {date_to[:10]}" if date_from and date_to
            else "весь период")
    log_export(db, cid, current_user,
               f"Сессии ЭЗС со сводной (xlsx): {stats['rows']} строк, период {span}"
               + (" ⚠ обрезано по лимиту" if stats["truncated"] else ""))

    return xlsx_response(wb, f"Сессии ЭЗС со сводной {span}.xlsx")


@router.get("/export/monthly-matrix")
async def export_monthly_matrix(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Матрица «станция × месяц» (кВт·ч) в формате привычного свода «ОБЩАЯ»:
    паспортные колонки + месяцы за весь горизонт. Отпуск = сводная контрагента
    (station_dispense_periods) до точки склейки, далее — зарядные сессии (то же
    правило, что в «Динамике 2024+»). Прямая замена ручного Excel-свода."""
    from sqlalchemy import text as sa_text

    from app.models import ServiceLocation
    cid = await assert_company_product(company_id, current_user, db, "sales")

    file_rows = (await db.execute(sa_text(
        "SELECT location_id, period, SUM(dispense_kwh) AS kwh "
        "FROM station_dispense_periods "
        "WHERE company_id = :cid AND dispense_kwh IS NOT NULL "
        "GROUP BY location_id, period"), {"cid": str(cid)})).all()
    sess_rows = (await db.execute(sa_text(
        "SELECT location_id, to_char(date_trunc('month', started_at), 'YYYY-MM-01') AS period, "
        "       SUM(energy_kwh) AS kwh "
        "FROM charge_sessions "
        "WHERE company_id = :cid AND location_id IS NOT NULL AND energy_kwh IS NOT NULL "
        "GROUP BY location_id, 2"), {"cid": str(cid)})).all()

    # точка склейки: первый месяц, где сессии дают ≥80% сводной (см. long-trend)
    f_tot: dict[str, float] = {}
    for r in file_rows:
        f_tot[r.period] = f_tot.get(r.period, 0.0) + float(r.kwh or 0)
    s_tot: dict[str, float] = {}
    for r in sess_rows:
        s_tot[r.period] = s_tot.get(r.period, 0.0) + float(r.kwh or 0)
    cutoff = None
    for p in sorted(set(f_tot) | set(s_tot)):
        sk, fk = s_tot.get(p, 0.0), f_tot.get(p)
        if sk > 0 and (fk is None or sk >= fk * 0.8):
            cutoff = p
            break
    cutoff = cutoff or "9999-99"

    cell: dict[tuple[str, str], float] = {}
    for r in file_rows:
        if r.period < cutoff:
            cell[(r.location_id, r.period)] = cell.get((r.location_id, r.period), 0.0) + float(r.kwh or 0)
    for r in sess_rows:
        if r.period >= cutoff:
            cell[(r.location_id, r.period)] = cell.get((r.location_id, r.period), 0.0) + float(r.kwh or 0)
    months = sorted({p for (_, p) in cell})
    loc_ids = {lid for (lid, _) in cell}

    locs = {l.id: l for l in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == cid)
    )).scalars().all() if l.id in loc_ids}

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Станция × месяц"
    loc_cls = {"city": "город", "highway": "трасса"}
    spd_cls = {"fast": "Быстрая", "slow": "Медленная"}
    ws.append(["Б/У", "№ ZOI-1", "Регион", "Город", "Адрес", "трасса/город",
               "Быстрая/медленная", "Марка", "Мощность", "Инвентарный номер",
               "Дата установки", "Дата вывода"]
              + [f"{m[5:7]}.{m[:4]}" for m in months] + ["Итого, кВт·ч"])
    order = sorted(loc_ids, key=lambda lid: (
        (locs.get(lid).extra_metadata or {}).get("federalSubject") or "" if locs.get(lid) else "",
        locs.get(lid).name if locs.get(lid) else ""))
    for lid in order:
        l = locs.get(lid)
        md = (l.extra_metadata or {}) if l else {}
        row_vals = [round(cell.get((lid, m), 0.0), 1) or None for m in months]
        ws.append([
            md.get("buNumber") or md.get("number") or (l.station_number if l else None),
            md.get("zoi1"),
            md.get("federalSubject") or (l.city if l else None),
            (l.city if l else None) or md.get("cityName"),
            (l.address if l else None),
            loc_cls.get(getattr(l, "location_class", None) or ""),
            spd_cls.get(getattr(l, "speed_class", None) or ""),
            getattr(l, "brand", None),
            getattr(l, "power_kwt", None),
            getattr(l, "inventory_number", None),
            getattr(l, "installed_on", None),
            getattr(l, "decommissioned_on", None),
        ] + row_vals + [round(sum(v for v in (cell.get((lid, m), 0.0) for m in months)), 1)])
    # итоговая строка сети
    ws.append(["", "", "ИТОГО по сети", "", "", "", "", "", "", "", "", ""]
              + [round(sum(cell.get((lid, m), 0.0) for lid in loc_ids), 1) for m in months]
              + [round(sum(cell.values()), 1)])

    buf = io.BytesIO()
    wb.save(buf)

    # След выгрузки: свод по всей сети — заменяет ручной Excel и уходит наружу.
    span = f"{months[0]}…{months[-1]}" if months else "нет данных"
    log_export(db, cid, current_user,
               f"Матрица «станция × месяц» (xlsx): {len(order)} станций, "
               f"{len(months)} мес. ({span}), склейка с {cutoff}")

    period = f" {months[0][:7]} — {months[-1][:7]}" if months else ""
    return xlsx_response(wb, f"Матрица станция-месяц{period}.xlsx")
