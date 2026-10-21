"""Контекст звонящего: данные ЭЗС в Ядре, заявки у Поддержки.

Ни звук, ни расшифровка здесь не принимаются. Все чтения ограничены компанией;
HTTP к Поддержке идёт с коротким токеном по канонической карте приложений.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
import uuid
import hashlib
import time

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select

from app.models import App, AppCompanyLink, ChargeSession, EzsCustomer
from app.services import sso
from app.services.app_registry import company_apps
from app.services.phone_e164 import to_e164
from app.services.space_projection import _internal_base_url

MSK = timezone(timedelta(hours=3))


def _source_scope(company_id, phones, ref):
    raw = json.dumps([str(company_id), sorted({p for raw in phones if (p := to_e164(raw))}), ref],
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_source_cursor(token, company_id, phones, ref):
    from app.config import get_settings
    try:
        page = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"],
                          audience="core-support-source-cursor",
                          options={"require": ["scope", "asOf", "lastAt", "lastId", "exp", "iat"]})
        if page["scope"] != _source_scope(company_id, phones, ref):
            raise ValueError("selection changed")
        at = datetime.fromisoformat(page["asOf"])
        if at.tzinfo is None or at > datetime.now(MSK):
            raise ValueError("asOf")
        datetime.fromisoformat(page["lastAt"])
        uuid.UUID(page["lastId"])
        return page
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(409, "cursor_stale")


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


async def charging_context(db, company_id, *, phones, ref, limit, detail, strict_ref=False,
                           strict_selection=False, as_of=None, page=None):
    source_scope = _source_scope(company_id, phones, ref)
    normalized = list(dict.fromkeys(p for raw in phones if (p := to_e164(raw))))
    customers = (await db.execute(select(EzsCustomer).where(
        EzsCustomer.company_id == company_id, EzsCustomer.phone.in_(normalized),
    ).order_by(EzsCustomer.is_active.desc().nulls_last(), EzsCustomer.registered_at.desc().nulls_last()))).scalars().all()
    ext_ids = list(dict.fromkeys(c.customer_ext_id for c in customers))
    if strict_ref:
        # При подтверждённом выборе не смешивать историю других кандидатов
        # общего телефона. Без доказанной card-owner связи телефонные строки
        # остаются только в явно обозначенной phone-истории.
        ext_ids = [ref[4:]] if ref and ref.startswith("ezs:") else []
        customers = [c for c in customers if c.customer_ext_id in ext_ids]
        normalized = []
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
    as_of = as_of or datetime.now(MSK)
    if strict_selection:
        where = and_(where, ChargeSession.started_at <= as_of.replace(tzinfo=None),
                     ChargeSession.created_at <= as_of)
    since = as_of.replace(tzinfo=None) - timedelta(days=30)
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
    row_where = where
    if page:
        last_at = datetime.fromisoformat(page["lastAt"])
        row_where = and_(where, or_(ChargeSession.started_at < last_at,
                                   and_(ChargeSession.started_at == last_at,
                                        ChargeSession.id < uuid.UUID(page["lastId"]))))
    page_limit = limit if detail else 5
    rows = (await db.execute(select(ChargeSession).where(row_where).order_by(
        ChargeSession.started_at.desc().nulls_last(), ChargeSession.id.desc(),
    ).limit(page_limit + 1 if strict_selection else page_limit))).scalars().all()
    has_more = strict_selection and len(rows) > page_limit
    rows = rows[:page_limit]
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
    if strict_selection:
        def count(value, *, recent=False, definition):
            return {"value": int(value), "source": "core.charge_sessions",
                    "period": {"from": (as_of - timedelta(days=30)).astimezone(timezone.utc).isoformat() if recent else None,
                               "to": as_of.astimezone(timezone.utc).isoformat(), "timezone": "UTC",
                               "timeField": "started_at (MSK stored, converted to UTC)"},
                    "identity": "core_person" if strict_ref else "phone",
                    "definition": definition, "complete": True}
        out["counts"] = {
            "totalSessions": count(agg["sessions"], definition="Known-start Core sessions up to asOf; no cross-provider deduplication"),
            "failedSessions": count(agg["failed"], definition="Known-start Core sessions with non-null result other than Complete"),
            "sessions30d": count(agg["sessions_30d"], recent=True, definition="Core sessions with since < started_at <= asOf"),
        }
    if detail:
        out["details"] = {"sessions": [_session(s) for s in rows], "stations": station_rows,
                          "total": int(agg["sessions"]), "limit": limit}
        if strict_selection:
            from app.config import get_settings
            next_cursor = None
            if has_more and rows:
                next_cursor = jwt.encode({"aud": "core-support-source-cursor", "scope": source_scope,
                                          "asOf": as_of.isoformat(), "lastAt": rows[-1].started_at.isoformat(),
                                          "lastId": str(rows[-1].id), "iat": int(time.time()),
                                          "exp": int(time.time()) + 86400},
                                         get_settings().secret_key, algorithm="HS256")
            out["details"].update(nextCursor=next_cursor, hasMore=has_more, asOf=as_of.isoformat())
    return out


async def _support_target(db, company_id, scope):
    apps = await company_apps(db, company_id)
    if not any(a["code"] == "support" and a["enabled"] for a in apps):
        return None
    row = (await db.execute(select(App, AppCompanyLink).join(
        AppCompanyLink, AppCompanyLink.app_id == App.id,
    ).where(App.code == "support", AppCompanyLink.company_id == company_id))).first()
    if not row:
        return None
    app, link = row
    token = sso.sign_service_token(aud="support", scope=scope, app_company_id=link.external_company_id)
    if not token:
        return None
    return app, token


async def support_tickets(db, company_id, *, phone, core_party_ref, object_refs, limit):
    target = await _support_target(db, company_id, "voice.context")
    if not target:
        return [], "unavailable"
    app, token = target
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
        return tickets, "available" if len(tickets) == len(body["tickets"][:limit]) else "unavailable"
    except (httpx.HTTPError, ValueError, TypeError):
        return [], "unavailable"


async def support_knowledge(db, company_id, *, topic, limit):
    unavailable = {"availability": "unavailable", "items": []}
    target = await _support_target(db, company_id, "voice.knowledge")
    if not target:
        return unavailable
    app, token = target
    try:
        async with httpx.AsyncClient(timeout=0.65, follow_redirects=False) as client:
            async with client.stream("POST", f"{_internal_base_url(app, 'support')}/api/v1/eco/voice/knowledge",
                                     headers={"Authorization": f"Bearer {token}"},
                                     json={"topic": topic, "limit": limit}) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 384000:
                        return unavailable
                    chunks.append(chunk)
        body = json.loads(b"".join(chunks))
        if not isinstance(body, dict):
            return unavailable
        if body.get("availability") != "available":
            return {**unavailable, "reason": "topic_unconfigured"} if body.get("reason") == "topic_unconfigured" else unavailable
        items = body.get("items")
        if not isinstance(items, list) or len(items) > limit:
            return unavailable
        safe = []
        for item in items:
            if not isinstance(item, dict):
                return unavailable
            ref = item.get("ref")
            if not isinstance(ref, str) or not ref.startswith("support:article:"):
                return unavailable
            article_id = ref.removeprefix("support:article:")
            if str(uuid.UUID(article_id)) != article_id:
                return unavailable
            if (not isinstance(item.get("title"), str) or not 1 <= len(item["title"].strip()) <= 300
                    or not isinstance(item.get("content"), str) or len(item["content"]) > 16000
                    or item.get("visibility") not in ("cc", "public")
                    or type(item.get("version")) is not int or item["version"] < 1):
                return unavailable
            safe.append({field: item[field] for field in ("ref", "title", "content", "visibility", "version")})
        return {"availability": "available", "items": safe}
    except (httpx.HTTPError, ValueError, TypeError):
        return unavailable
