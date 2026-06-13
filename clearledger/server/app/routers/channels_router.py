"""
Роутер экземпляров КАНАЛОВ (`Channel`).

Из шаблона справочника (`/channel-templates`) создаётся экземпляр Channel,
привязанный к компании: потоки шаблона → `ChannelStream` (источник компании
по source_type), стадии → `ChannelStage`. Запуск пишет `ChannelSyncLog`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_catalog import get_channel_template
from app.database import get_db
from app.models import Channel, ChannelStage, ChannelStream, ChannelSyncLog, Source
from app.services.cb_intake import ingest_packages
from app.utils import resolve_company_id

router = APIRouter(prefix="/channels", tags=["channels"])


# ---------------------------------------------------------------------------
# Контракты
# ---------------------------------------------------------------------------
class ChannelCreate(BaseModel):
    company_id: str
    name: str
    template_id: str | None = None
    description: str | None = None
    # явная привязка source_type → source_id; иначе автоподбор по company+type
    source_bindings: dict[str, str] = {}


class ChannelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None          # active | paused | draft
    schedule: dict[str, Any] | None = None
    duplicate_policy: str | None = None


class ChannelResponse(BaseModel):
    id: str
    company_id: str
    name: str
    description: str | None
    status: str
    template_id: str | None
    schedule: dict[str, Any]
    duplicate_policy: str
    streams: list[dict]
    stages: list[dict]
    skipped_streams: list[str] = []     # потоки без привязанного источника


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
async def _resolve_source(
    db: AsyncSession, cid: uuid.UUID, source_type: str,
    bindings: dict[str, str],
) -> uuid.UUID | None:
    """source_id для потока: явная привязка или единственный Source типа у компании."""
    if source_type in bindings:
        return uuid.UUID(bindings[source_type])
    res = await db.execute(
        select(Source.id).where(
            Source.company_id == cid, Source.source_type == source_type
        )
    )
    ids = res.scalars().all()
    return ids[0] if len(ids) == 1 else None   # автоподбор только при единственном


async def _streams(db: AsyncSession, channel_id: uuid.UUID) -> list[ChannelStream]:
    res = await db.execute(
        select(ChannelStream).where(ChannelStream.channel_id == channel_id)
    )
    return list(res.scalars().all())


async def _stages(db: AsyncSession, channel_id: uuid.UUID) -> list[ChannelStage]:
    res = await db.execute(
        select(ChannelStage).where(ChannelStage.channel_id == channel_id)
        .order_by(ChannelStage.order_index)
    )
    return list(res.scalars().all())


async def _resp(db: AsyncSession, ch: Channel, skipped: list[str] | None = None) -> ChannelResponse:
    streams = await _streams(db, ch.id)
    stages = await _stages(db, ch.id)
    return ChannelResponse(
        id=str(ch.id), company_id=str(ch.company_id), name=ch.name,
        description=ch.description, status=ch.status, template_id=ch.template_id,
        schedule=ch.schedule or {}, duplicate_policy=ch.duplicate_policy,
        streams=[{
            "id": str(s.id), "source_id": str(s.source_id),
            "doc_type_id": s.doc_type_id, "name": s.name, "enabled": s.enabled,
        } for s in streams],
        stages=[{
            "id": str(st.id), "stage_type": st.stage_type, "name": st.name,
            "order_index": st.order_index, "enabled": st.enabled,
        } for st in stages],
        skipped_streams=skipped or [],
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post("", response_model=ChannelResponse)
async def create_channel(payload: ChannelCreate, db: AsyncSession = Depends(get_db)):
    """Создать канал (из шаблона справочника или пустой) и привязать к компании."""
    cid = await resolve_company_id(payload.company_id, db)
    tpl = get_channel_template(payload.template_id) if payload.template_id else None
    if payload.template_id and not tpl:
        raise HTTPException(404, f"Шаблон канала '{payload.template_id}' не найден")

    ch = Channel(
        company_id=cid,
        name=payload.name,
        description=payload.description,
        status="draft",
        template_id=payload.template_id,
        schedule=(tpl.schedule if tpl else {"mode": "manual"}),
        config={"reconcile_rules": tpl.reconcile_rules} if tpl else {},
    )
    db.add(ch)
    await db.flush()

    skipped: list[str] = []
    if tpl:
        for s in tpl.streams:
            src_id = await _resolve_source(db, cid, s.source_type, payload.source_bindings)
            if src_id is None:
                skipped.append(f"{s.source_type}:{s.doc_type}")
                continue
            db.add(ChannelStream(
                channel_id=ch.id, source_id=src_id,
                doc_type_id=s.doc_type, name=s.label,
            ))
        for i, st in enumerate(tpl.stages):
            db.add(ChannelStage(
                channel_id=ch.id, stage_type=st.stage_type,
                name=st.name, order_index=i,
            ))
    await db.flush()
    return await _resp(db, ch, skipped)


@router.get("", response_model=list[ChannelResponse])
async def list_channels(company_id: str = Query(...), db: AsyncSession = Depends(get_db)):
    cid = await resolve_company_id(company_id, db)
    res = await db.execute(
        select(Channel).where(Channel.company_id == cid).order_by(Channel.created_at)
    )
    return [await _resp(db, ch) for ch in res.scalars().all()]


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ch = await db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Канал не найден")
    return await _resp(db, ch)


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID, payload: ChannelUpdate, db: AsyncSession = Depends(get_db)
):
    ch = await db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Канал не найден")
    if payload.name is not None:
        ch.name = payload.name
    if payload.description is not None:
        ch.description = payload.description
    if payload.status is not None:
        ch.status = payload.status
    if payload.schedule is not None:
        ch.schedule = payload.schedule
    if payload.duplicate_policy is not None:
        ch.duplicate_policy = payload.duplicate_policy
    await db.flush()
    return await _resp(db, ch)


@router.delete("/{channel_id}")
async def delete_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ch = await db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Канал не найден")
    await db.delete(ch)   # streams/stages каскадом (FK ondelete=CASCADE)
    return {"deleted": str(channel_id)}


@router.post("/{channel_id}/run")
async def run_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Запустить прогон канала. Создаёт ChannelSyncLog.

    ⚠ Рантайм-оркестратор (fetch→normalize→reconcile→save) + ReconcileEngine
    пока не подключены — лог создаётся, исполнение помечается как pending.
    """
    ch = await db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Канал не найден")
    log = ChannelSyncLog(
        channel_id=ch.id, status="partial",
        events=[{
            "level": "warn", "event": "engine_pending",
            "message": "Оркестратор/ReconcileEngine не подключены — прогон не исполнен.",
        }],
        finished_at=datetime.now(timezone.utc),
    )
    db.add(log)
    ch.last_sync_at = datetime.now(timezone.utc)
    await db.flush()
    return {"sync_log_id": str(log.id), "status": log.status, "note": "execution pending engine"}


class IngestRequest(BaseModel):
    packages: list[dict[str, Any]]   # пакеты смен ЦБ (контракт .epf v2)


@router.post("/{channel_id}/ingest")
async def ingest_channel(
    channel_id: uuid.UUID, payload: IngestRequest, db: AsyncSession = Depends(get_db)
):
    """Принять пакеты смен ЦБ в L2 (нормализация + идемпотентная запись DataEntry).

    Стадии normalize+save канала сопутки/общепита. Пакеты даёт стадия fetch
    (onec_operational через com_worker) — здесь принимаем готовые пакеты.
    """
    ch = await db.get(Channel, channel_id)
    if not ch:
        raise HTTPException(404, "Канал не найден")
    result = await ingest_packages(db, ch.company_id, payload.packages)
    log = ChannelSyncLog(
        channel_id=ch.id,
        status="success" if not result["skipped_kinds"] else "partial",
        loaded=result["created"],
        duplicates=result["updated"],
        events=[{"level": "info", "event": "ingest",
                 "message": f"смен={result['shifts']} создано={result['created']} "
                            f"обновлено={result['updated']} пропущено_kind={result['skipped_kinds']}"}],
        finished_at=datetime.now(timezone.utc),
    )
    db.add(log)
    ch.last_sync_at = datetime.now(timezone.utc)
    await db.flush()
    return {"sync_log_id": str(log.id), **result}
