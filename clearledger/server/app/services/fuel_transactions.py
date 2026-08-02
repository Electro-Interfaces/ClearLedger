"""Ингест пооперационных транзакций STS `/v2/transactions` → `FuelTransaction`.

Грейн — одна реализация на ТРК (в отличие от FuelShiftSale = агрегат смена×канал×топливо).
Даёт счётчик реализаций (как в эталонной системе), реестр операций и точные метрики.
Дедуп по STS `id` через уникальный индекс (ON CONFLICT DO NOTHING) — переигровка
периода не плодит дублей. Креды STS берутся из источника компании (source_type='sts').
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelStation, FuelTransaction, Source, SourceCredentials
from app.services.onec.crypto import decrypt_password
from app.services.payment_normalize import normalize_payment_method
from app.services.sts_client import sts_get_points, sts_get_transactions


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _flt(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def resolve_sts(db: AsyncSession, company_id) -> dict | None:
    """STS-подключение компании из источника source_type='sts' (креды + системы)."""
    src = (await db.execute(select(Source).where(
        Source.company_id == company_id, Source.source_type == "sts"))).scalars().first()
    if src is None:
        return None
    cfg = src.connection_config or {}
    login = str(cfg.get("login") or "")
    base_url = str(cfg.get("base_url") or "https://pos.autooplata.ru/tms")
    sysids = str(cfg.get("default_system_ids") or "65")
    systems = [int(s.strip()) for s in sysids.split(",") if s.strip()] or [65]
    cr = (await db.execute(select(SourceCredentials).where(
        SourceCredentials.source_id == src.id))).scalar_one_or_none()
    enc = (cr.encrypted_values or {}) if cr else {}
    pwd = decrypt_password(enc["password"]) if enc.get("password") else ""
    return {"base_url": base_url, "login": login, "pwd": pwd, "systems": systems}


async def list_stations(db: AsyncSession, company_id, conn: dict) -> list[dict]:
    """Станции сети (код+система) из STS /v1/points + резолв station_id из fuel_stations."""
    id_by_code = {int(s.code): s.id for s in (await db.execute(
        select(FuelStation).where(FuelStation.company_id == company_id))).scalars().all()}
    out: list[dict] = []
    seen: set[int] = set()
    for sysid in conn["systems"]:
        try:
            points = await sts_get_points(conn["base_url"], conn["login"], conn["pwd"], sysid)
        except Exception:  # noqa: BLE001 — STS недоступен по системе → пропускаем
            points = []
        for p in points:
            code = _int(p.get("number") or p.get("id"))
            if code and code not in seen:
                seen.add(code)
                out.append({"code": code, "system": sysid, "station_id": id_by_code.get(code)})
    return out


async def ingest_station_window(db: AsyncSession, company_id, station: dict, conn: dict,
                                df: str, dt: str) -> dict:
    """Загрузить транзакции одной станции за окно [df, dt] (YYYY-MM-DD); дедуп по STS id."""
    rows = await sts_get_transactions(
        conn["base_url"], conn["login"], conn["pwd"], station["system"], df, dt, station["code"])
    seen: set[int] = set()
    mapped: list[dict[str, Any]] = []
    for tx in rows:
        ext = _int(tx.get("id"))
        if ext is None or ext in seen:
            continue
        seen.add(ext)
        card = tx.get("card")
        if isinstance(card, dict):
            card = card.get("number")
        pt = tx.get("pay_type") or {}
        dts = tx.get("dt")
        try:
            dtv = datetime.fromisoformat(dts) if dts else None
        except (ValueError, TypeError):
            dtv = None
        mapped.append({
            "company_id": company_id, "station_id": station.get("station_id"),
            "station_code": _int(tx.get("station")) or station["code"], "ext_id": ext,
            "dt": dtv, "shift_number": _int(tx.get("shift")), "receipt": _int(tx.get("number")),
            "pos": _int(tx.get("pos")), "nozzle": _int(tx.get("nozzle")), "tank": _int(tx.get("tank")),
            "fuel_code": _int(tx.get("fuel")), "fuel_name": tx.get("fuel_name"),
            "pay_type_id": _int(pt.get("id")), "pay_type_name": pt.get("name"),
            "payment_method": normalize_payment_method(pt.get("name")),
            "card": str(card)[:64] if card else None,
            "liters": _flt(tx.get("quantity")), "price": (_flt(tx.get("price")) or None),
            "amount": _flt(tx.get("cost")), "mass": (_flt(tx.get("amount")) or None),
            "density": (_flt(tx.get("density")) or None),
            "order_qty": (_flt(tx.get("order")) or None),
            "order_cost": (_flt(tx.get("order_cost")) or None),
        })
    created = 0
    for i in range(0, len(mapped), 1000):
        chunk = mapped[i:i + 1000]
        # DO UPDATE, а не DO NOTHING: повторная загрузка периода — единственный способ
        # дозаполнить поля, появившиеся позже ингеста (чек, заказ, масса, нормализованная
        # оплата), и подхватить правки STS задним числом. Ключ дедупа прежний.
        stmt = pg_insert(FuelTransaction).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "station_code", "ext_id"],
            set_={c: stmt.excluded[c] for c in (
                "dt", "shift_number", "receipt", "pos", "nozzle", "tank",
                "fuel_code", "fuel_name", "pay_type_id", "pay_type_name", "payment_method",
                "card", "liters", "price", "amount", "mass", "density", "order_qty", "order_cost",
            )},
        ).returning(text("xmax = 0 AS inserted"))  # xmax=0 у строки, вставленной, а не обновлённой
        res = await db.execute(stmt)
        created += sum(1 for r in res.fetchall() if r[0])
    return {"created": created, "fetched": len(rows)}


def month_windows(df: str, dt: str) -> list[tuple[str, str]]:
    """Разбить [df, dt] (YYYY-MM-DD) на помесячные окна — чтобы ответы STS не были
    гигантскими (у крупных станций десятки тысяч транзакций/месяц)."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(df)
    d1 = date.fromisoformat(dt)
    out: list[tuple[str, str]] = []
    cur = d0
    while cur <= d1:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        end = min(d1, nxt - timedelta(days=1))
        out.append((cur.isoformat(), end.isoformat()))
        cur = nxt
    return out
