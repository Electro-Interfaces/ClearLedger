"""
Роутер исполнения сверки (ReconcileEngine).

POST /reconcile/run  — исполнить разрез из справочника над переданными потоками.
POST /reconcile/diff — сверить результат движка с golden (примитив §6.4:
                       byte-for-byte против рабочих императивных движков).

⚠ Потоки (streams) на вход даёт канал (стадия fetch→normalize). Здесь —
движок над уже нормализованными записями. Golden capture (прогон императивных
TS-движков на боевых ГИГ) — операционный шаг, делается на живом стенде.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import DataEntry, User
from app.reconcile_catalog import list_reconcile_rules
from app.selfcheck_catalog import list_selfchecks
from app.services.reconcile import selfcheck
from app.services.reconcile.engine import run_reconcile
from app.services.recon_run import run_rule as run_rule_live

router = APIRouter(prefix="/reconcile", tags=["reconcile"])

_RULES = {r["id"]: r for r in list_reconcile_rules()}


class RunRequest(BaseModel):
    rule_id: str
    streams: dict[str, list[dict[str, Any]]]   # {anchor:[...], external:[...], control:[...]}


@router.post("/run")
async def run(req: RunRequest):
    """Исполнить разрез над потоками → ReconResult."""
    rule = _RULES.get(req.rule_id)
    if not rule:
        raise HTTPException(404, f"Разрез '{req.rule_id}' не найден в справочнике")
    return run_reconcile(rule, req.streams)


class DiffRequest(BaseModel):
    engine: dict[str, Any]   # результат ReconcileEngine
    golden: dict[str, Any]   # результат императивного движка (golden)


class RunRuleRequest(BaseModel):
    rule_id: str                 # corp_fuel | online_fuel
    date_from: str               # YYYY-MM-DD
    date_to: str
    base_url: str = "https://pos.autooplata.ru/tms"
    login: str
    password: str
    system: int = 65
    station_ids: list[Any] | None = None
    company_id: str | None = None   # для канального маппинга топлива/станций
    channel_id: str | None = None


@router.post("/run-rule")
async def run_rule_endpoint(
    req: RunRuleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Backend-исполнение разреза corp/online на живых потоках (КАНДИДАТ, §6.4).

    Тянет TF (STS) + внешний (TradeCorp/MSTO), прогоняет ReconcileEngine с
    канальным маппингом топлива/станций. Сверять с golden (frontend) через
    /reconcile/diff до замены.
    """
    cid = await assert_company_member(req.company_id, current_user, db) if req.company_id else None
    chid = uuid.UUID(req.channel_id) if req.channel_id else None
    return await run_rule_live(
        req.rule_id, req.date_from, req.date_to,
        base_url=req.base_url, login=req.login, password=req.password,
        system=req.system, station_ids=req.station_ids,
        db=db, company_id=cid, channel_id=chid,
    )


@router.get("/selfchecks")
async def list_selfcheck_rules():
    """Справочник правил самосверки L2 (внутренняя ось, без внешних источников)."""
    return list_selfchecks()


class SelfCheckRequest(BaseModel):
    company_id: str
    rule_ids: list[str] | None = None    # None → все правила
    limit: int = 500


@router.post("/selfcheck/run")
async def selfcheck_run(
    req: SelfCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Прогнать самосверку над сохранённым L2 (DataEntry компании) → сводка+нарушения.

    Арифметические инварианты смены (баланс оплаты↔продажи, НДС 22/122, итог
    документа) на наших данных — без TradeCorp/MSTO/ОФД. Ловит ошибки до экспорта.
    """
    cid = await assert_company_member(req.company_id, current_user, db)
    rules = list_selfchecks()
    if req.rule_ids:
        rules = [r for r in rules if r["id"] in set(req.rule_ids)]
    # записи, к которым применима хоть одна выбранная самосверка
    doc_types = sorted({dt for r in rules for dt in (r.get("applies_to", {}).get("doc_type_id") or [])})
    q = select(DataEntry).where(DataEntry.company_id == cid)
    if doc_types:
        q = q.where(DataEntry.doc_type_id.in_(doc_types))
    q = q.order_by(DataEntry.created_at.desc()).limit(req.limit)
    rows = (await db.execute(q)).scalars().all()
    entries = [
        {"source_id": e.source_id, "title": e.title, "doc_type_id": e.doc_type_id,
         "category_id": e.category_id, "meta": e.meta or {}}
        for e in rows
    ]
    report = selfcheck.run_selfchecks(rules, entries)
    return {"company_id": str(cid), "rules": [r["id"] for r in rules],
            "entries": len(entries), **report}


@router.post("/diff")
async def diff(req: DiffRequest):
    """Сверка engine ↔ golden по summary (§6.4). identical=True → можно заменять."""
    e = req.engine.get("summary", {})
    g = req.golden.get("summary", {})
    keys = set(e) | set(g)
    mismatches = {
        k: {"engine": e.get(k), "golden": g.get(k)}
        for k in keys if e.get(k) != g.get(k)
    }
    return {"identical": not mismatches, "mismatches": mismatches}
