"""Контекст звонящего: данные ЭЗС в Ядре, заявки у Поддержки.

Ни звук, ни расшифровка здесь не принимаются. Все чтения ограничены компанией;
HTTP к Поддержке идёт с коротким токеном по канонической карте приложений.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import and_, func, or_, select

from app.models import App, AppCompanyLink, ChargeSession, EzsCustomer
from app.services import sso
from app.services.app_registry import company_apps
from app.services.phone_e164 import to_e164
from app.services.space_projection import _internal_base_url

MSK = timezone(timedelta(hours=3))


def _iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=MSK) if value.tzinfo is None else value).isoformat()


def _session(row):
    return {
        "session_ext_id": row.session_ext_id, "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at), "station_code": row.station_code,
        "station": row.station_name or row.station_code, "region": row.region,
        "address": row.address, "connector_no": row.connector_no,
        "connector_type": row.connector_type, "kwh": float(row.energy_kwh or 0),
        "amount": float(row.amount or row.client_amount or 0),
        "duration_min": float(row.duration_min or 0), "result": row.result,
        "charge_type": row.charge_type, "user_type": row.user_type,
    }


async def charging_context(db, company_id, *, phones, ref, limit, detail):
    normalized = list(dict.fromkeys(p for raw in phones if (p := to_e164(raw))))
    customers = (await db.execute(select(EzsCustomer).where(
        EzsCustomer.company_id == company_id, EzsCustomer.phone.in_(normalized),
    ).order_by(EzsCustomer.is_active.desc().nulls_last(), EzsCustomer.registered_at.desc().nulls_last()))).scalars().all()
    ext_ids = list(dict.fromkeys(c.customer_ext_id for c in customers))
    if ref and ref.startswith("ezs:") and ref[4:] not in ext_ids:
        known = await db.scalar(select(EzsCustomer.customer_ext_id).where(
            EzsCustomer.company_id == company_id, EzsCustomer.customer_ext_id == ref[4:],
        ))
        if known:
            ext_ids.append(known)
    where = and_(ChargeSession.company_id == company_id, or_(
        ChargeSession.user_id.in_([*normalized, *ext_ids]),
        ChargeSession.card_owner_ext_id.in_(ext_ids),
    ))
    since = datetime.now(MSK).replace(tzinfo=None) - timedelta(days=30)
    money = func.coalesce(func.nullif(ChargeSession.amount, 0), ChargeSession.client_amount, 0)
    count = func.count(ChargeSession.id)
    agg = (await db.execute(select(
        count.label("sessions"), func.coalesce(func.sum(ChargeSession.energy_kwh), 0).label("kwh"),
        func.coalesce(func.sum(money), 0).label("amount"),
        func.count(func.distinct(ChargeSession.station_code)).label("stations"),
        func.min(ChargeSession.started_at).label("first_at"), func.max(ChargeSession.started_at).label("last_at"),
        count.filter(ChargeSession.result != "Complete").label("failed"),
        count.filter(ChargeSession.started_at > since).label("sessions_30d"),
        func.coalesce(func.sum(ChargeSession.energy_kwh).filter(ChargeSession.started_at > since), 0).label("kwh_30d"),
        count.filter(ChargeSession.charge_type == "RFID").label("rfid"),
        func.max(ChargeSession.client_name).label("org_name"), func.max(ChargeSession.user_type).label("user_type"),
        count.filter(ChargeSession.result.in_(["Complete", "CompleteError"])).label("graded"),
        count.filter(ChargeSession.result == "CompleteError").label("failed_graded"),
    ).where(where))).mappings().one()
    rows = (await db.execute(select(ChargeSession).where(where).order_by(
        ChargeSession.started_at.desc().nulls_last(), ChargeSession.id.desc(),
    ).limit(limit if detail else 5))).scalars().all()
    stations = (await db.execute(select(
        ChargeSession.station_code, func.max(ChargeSession.station_name).label("station"),
        func.max(ChargeSession.region).label("region"), func.max(ChargeSession.address).label("address"),
        count.label("sessions"), count.filter(ChargeSession.result != "Complete").label("failed"),
        func.coalesce(func.sum(ChargeSession.energy_kwh), 0).label("kwh"),
        func.coalesce(func.sum(money), 0).label("amount"), func.max(ChargeSession.started_at).label("last_at"),
    ).where(where).group_by(ChargeSession.station_code).order_by(count.desc(),
        func.sum(ChargeSession.energy_kwh).desc()))).mappings().all()
    station_rows = [{**dict(s), "station": s["station"] or s["station_code"],
                     "kwh": float(s["kwh"]), "amount": float(s["amount"]),
                     "last_at": _iso(s["last_at"])} for s in stations]
    totals = {k: agg[k] for k in ("sessions", "stations", "failed", "sessions_30d", "rfid", "org_name", "user_type")}
    totals.update({k: float(agg[k]) for k in ("kwh", "amount", "kwh_30d")})
    totals.update({k: _iso(agg[k]) for k in ("first_at", "last_at")})
    charging = {**totals, "top_stations": station_rows[:3], "recent": [_session(s) for s in rows[:5]]} if agg["sessions"] else None
    customer = next((c for c in customers if ref == f"ezs:{c.customer_ext_id}"), None) or (customers[0] if customers else None)
    ezs = {"registered_at": _iso(customer.registered_at), "balance": float(customer.balance) if customer.balance is not None else None,
           "is_active": customer.is_active, "sessions": agg["sessions"], "graded": agg["graded"],
           "failed": agg["failed_graded"], "stations": agg["stations"], "last_at": _iso(agg["last_at"]),
           "last_station": rows[0].station_name or rows[0].station_code if rows else None,
           "last_result": rows[0].result if rows else None} if customer else None
    out = {"charging": charging, "ezs": ezs}
    if detail:
        out["details"] = {"sessions": [_session(s) for s in rows], "stations": station_rows,
                          "total": int(agg["sessions"]), "limit": limit}
    return out


async def support_tickets(db, company_id, *, phone, core_party_ref, object_refs, limit):
    apps = await company_apps(db, company_id)
    if not any(a["code"] == "support" and a["enabled"] for a in apps):
        return [], "unavailable"
    row = (await db.execute(select(App, AppCompanyLink).join(
        AppCompanyLink, AppCompanyLink.app_id == App.id,
    ).where(App.code == "support", AppCompanyLink.company_id == company_id))).first()
    if not row:
        return [], "unavailable"
    app, link = row
    token = sso.sign_service_token(aud="support", scope="voice.context", company_id=link.external_company_id)
    if not token:
        return [], "unavailable"
    try:
        async with httpx.AsyncClient(timeout=0.65, follow_redirects=False) as client:
            res = await client.post(f"{_internal_base_url(app, 'support')}/api/v1/eco/voice/context",
                                    headers={"Authorization": f"Bearer {token}"},
                                    json={"phone": phone, "corePartyRef": core_party_ref,
                                          "objectRefs": object_refs, "limit": limit})
        res.raise_for_status()
        body = res.json()
        if not isinstance(body, dict) or body.get("availability") != "available" or not isinstance(body.get("tickets"), list):
            return [], "unavailable"
        fields = ("ref", "number", "title", "status", "priority", "category", "objectRef", "slaDeadline")
        tickets = [{k: t.get(k) for k in fields} for t in body["tickets"][:limit]
                   if isinstance(t, dict) and all(isinstance(t.get(k), str) for k in ("ref", "number", "title", "status"))]
        return tickets, "available"
    except (httpx.HTTPError, ValueError, TypeError):
        return [], "unavailable"
