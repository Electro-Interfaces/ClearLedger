"""Читаем факты внешней ВАТС из Поддержки, отдельно от событий узла ContactHub."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Схема приложения фиксирована; параметров SQL от пользователя в именах таблиц нет.
_SCHEMA = "public"


def period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start, end = start or now - timedelta(days=7), end or now
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "Период должен содержать часовой пояс")
    if start >= end or end - start > timedelta(days=93):
        raise HTTPException(422, "Выберите период от одного момента до 93 дней")
    return start, end


async def ready(db: AsyncSession) -> None:
    found = await db.scalar(text("""SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema=:schema AND table_name='call_records' AND column_name='group_name')"""), {"schema": _SCHEMA})
    if not found:
        raise HTTPException(503, "Журнал МегаФона ещё не подготовлен к обогащению")


def _columns() -> str:
    return """c.id, c.callid AS call_id, c.direction, c.missed, c.client_phone,
        c.operator AS operator_name, c.operator_login, c.operator_user_id,
        NULLIF(c.group_name,'') AS group_name, c.via_number AS line_number,
        c.via_name AS line_name, c.started_at, c.wait_sec, c.duration_sec,
        (NULLIF(c.recording_url,'') IS NOT NULL OR c.recording_external_id IS NOT NULL) AS has_recording,
        c.source, c.thread_id"""


def _base() -> str:
    return "c.company_id=CAST(:cid AS uuid) AND c.source IN ('megafon','megafon_api')"


def _where(start: datetime, end: datetime, cid: str, *, operator: str | None,
           group: str | None, line: str | None, missed: bool | None,
           direction: str | None, search: str | None) -> tuple[str, dict]:
    params: dict[str, Any] = {"cid": cid, "start": start, "end": end}
    where = _base() + " AND c.started_at>=:start AND c.started_at<:end"
    for key, column, value in (("operator", "c.operator", operator), ("group", "c.group_name", group),
                               ("line", "c.via_number", line), ("direction", "c.direction", direction)):
        if value is not None:
            # Пустая строка выбирает явно неизвестную группу/оператора.
            where += f" AND COALESCE({column},'')=:{key}"
            params[key] = value
    if missed is not None:
        where += " AND c.missed=:missed"
        params["missed"] = missed
    if search:
        digits = "".join(c for c in search if c.isascii() and c.isdigit())
        if len(digits) < 4:
            raise HTTPException(422, "Для поиска номера введите хотя бы четыре цифры")
        where += " AND regexp_replace(COALESCE(c.client_phone,''),'[^0-9]','','g') LIKE :search"
        params["search"] = "%" + digits + "%"
    return where, params


async def overview(db: AsyncSession, support_cid: str, core_cid: uuid.UUID, *,
                   start: datetime, end: datetime, operator: str | None = None,
                   group: str | None = None, line: str | None = None,
                   missed: bool | None = None, direction: str | None = None,
                   search: str | None = None, page: int = 1, page_size: int = 25) -> dict:
    await ready(db)
    where, params = _where(start, end, support_cid, operator=operator, group=group,
                           line=line, missed=missed, direction=direction, search=search)
    table = f"{_SCHEMA}.call_records c"
    connector = (await db.execute(text(f"""SELECT id,label,endpoint,status,enabled,last_sync_at,
        (NULLIF(last_error,'') IS NOT NULL) AS has_error, config->'line_context' AS line_context
        FROM {_SCHEMA}.connectors WHERE company_id=CAST(:cid AS uuid) AND provider='megafon'
        AND type='channel' AND enabled=true ORDER BY last_sync_at DESC NULLS LAST, id LIMIT 1"""),
        {"cid": support_cid})).mappings().first()
    summary = dict((await db.execute(text(f"""SELECT count(*)::int total,
        count(*) FILTER(WHERE c.direction='inbound')::int inbound,
        count(*) FILTER(WHERE c.direction='outbound')::int outbound,
        count(*) FILTER(WHERE c.direction='inbound' AND NOT c.missed)::int answered,
        count(*) FILTER(WHERE c.direction='inbound' AND c.missed)::int missed,
        round(avg(c.wait_sec) FILTER(WHERE c.direction='inbound' AND NOT c.missed))::int avg_wait_sec,
        round(avg(c.duration_sec) FILTER(WHERE c.duration_sec>0))::int avg_talk_sec,
        count(*) FILTER(WHERE NULLIF(c.recording_url,'') IS NOT NULL OR c.recording_external_id IS NOT NULL)::int recordings,
        count(DISTINCT c.operator) FILTER(WHERE NULLIF(c.operator,'') IS NOT NULL)::int operator_count
        FROM {table} WHERE {where}"""), params)).mappings().one())
    operators = (await db.execute(text(f"""SELECT COALESCE(c.operator,'') AS key,
        COALESCE(NULLIF(c.operator,''),'Без оператора') AS name,
        CASE WHEN count(DISTINCT c.operator_login)=1 THEN min(c.operator_login) ELSE NULL END AS login,
        CASE WHEN count(DISTINCT c.operator_user_id)=1 THEN min(c.operator_user_id::text) ELSE NULL END AS user_id,
        NULL::text AS extension, count(*)::int total,
        count(*) FILTER(WHERE c.direction='inbound' AND NOT c.missed)::int inbound_answered,
        count(*) FILTER(WHERE c.direction='outbound')::int outbound,
        count(*) FILTER(WHERE c.direction='inbound' AND c.missed)::int missed,
        round(avg(c.duration_sec) FILTER(WHERE c.duration_sec>0))::int avg_talk_sec,
        round(avg(c.wait_sec) FILTER(WHERE c.direction='inbound' AND NOT c.missed))::int avg_wait_sec
        FROM {table} WHERE {where} GROUP BY c.operator ORDER BY total DESC, name"""), params)).mappings().all()
    groups = (await db.execute(text(f"""SELECT COALESCE(c.group_name,'') name,count(*)::int total,
        count(*) FILTER(WHERE c.direction='inbound' AND NOT c.missed)::int answered,
        count(*) FILTER(WHERE c.direction='inbound' AND c.missed)::int missed
        FROM {table} WHERE {where} GROUP BY c.group_name ORDER BY total DESC,name"""), params)).mappings().all()
    rows = (await db.execute(text(f"""SELECT {_columns()} FROM {table} WHERE {where}
        ORDER BY c.started_at DESC,c.id DESC LIMIT :limit OFFSET :offset"""),
        {**params, "limit": page_size, "offset": (page - 1) * page_size})).mappings().all()
    # Справочники фильтров берём до текущих фильтров, но внутри выбранного периода/компании.
    facets = (await db.execute(text(f"""SELECT DISTINCT c.operator,c.group_name,c.via_number,c.via_name
        FROM {table} WHERE {_base()} AND c.started_at>=:start AND c.started_at<:end
        ORDER BY c.operator,c.group_name,c.via_number,c.via_name"""),
        {"cid": support_cid, "start": start, "end": end})).mappings().all()
    ops: dict[str, str] = {}
    grps: dict[str, str] = {}
    lines: dict[str, str] = {}
    for f in facets:
        ops[f["operator"] or ""] = f["operator"] or "Без оператора"
        grps[f["group_name"] or ""] = f["group_name"] or "Группа не указана"
        if f["via_number"]:
            lines[f["via_number"]] = f["via_name"] or f["via_number"]
    context = (connector["line_context"] or {}) if connector else {}
    if not isinstance(context, dict):
        context = {}
    return {"provider": "megafon", "company_id": str(core_cid),
            "period": {"from": start, "to": end},
            "connection": {"configured": bool(connector and connector["endpoint"]),
                           "status": connector["status"] if connector else "not_configured",
                           "last_sync_at": connector["last_sync_at"] if connector else None,
                           "last_error": "Ошибка обмена с МегаФоном" if connector and connector["has_error"] else None,
                           "mode": "history", "poll_interval_seconds": 300},
            "line": {"name": context.get("name") or (next(iter(lines.values())) if len(lines) == 1 else None),
                     "public_number": context.get("public_number"),
                     "forwarding_number": context.get("forwarding_number"),
                     "origin_verified_per_call": False},
            "summary": summary, "operators": [dict(x) for x in operators], "groups": [dict(x) for x in groups],
            "filters": {"operators": [{"key": k, "name": v} for k, v in ops.items()],
                        "groups": [{"key": k, "name": v} for k, v in grps.items()],
                        "lines": [{"key": k, "name": v, "number": k} for k, v in lines.items()]},
            "calls": {"items": [dict(x) for x in rows], "total": summary["total"], "page": page, "page_size": page_size}}


async def call_detail(db: AsyncSession, support_cid: str, call_id: uuid.UUID) -> dict:
    await ready(db)
    row = (await db.execute(text(f"""SELECT {_columns()} FROM {_SCHEMA}.call_records c
        WHERE {_base()} AND c.id=:id"""), {"cid": support_cid, "id": call_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Звонок не найден")
    return dict(row)
