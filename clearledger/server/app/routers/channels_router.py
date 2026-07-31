"""
Роутер экземпляров КАНАЛОВ (`Channel`).

Из шаблона справочника (`/channel-templates`) создаётся экземпляр Channel,
привязанный к компании: потоки шаблона → `ChannelStream` (источник компании
по source_type), стадии → `ChannelStage`. Запуск пишет `ChannelSyncLog`.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.channel_catalog import get_channel_template
from app.database import async_session_factory, get_db
from app.deps import CompanyDep, get_owned
from app.models import Channel, ChannelStage, ChannelStream, ChannelSyncLog, Source, User
from app.services.cb_intake import ingest_packages
from app.services.channel_orchestrator import run_channel as orchestrate_channel

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
    config: dict[str, Any] | None = None    # станции, reconcile_rules и пр.
    period_days: int | None = None


class StreamCreate(BaseModel):
    source_id: str
    doc_type_id: str | None = None
    name: str | None = None


class ChannelResponse(BaseModel):
    id: str
    company_id: str
    name: str
    description: str | None
    status: str
    template_id: str | None
    schedule: dict[str, Any]
    duplicate_policy: str
    config: dict[str, Any] = {}
    period_days: int = 30
    last_sync_at: str | None = None
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


async def _resp(db: AsyncSession, ch: Channel, skipped: list[str] | None = None,
                streams: list[ChannelStream] | None = None,
                stages: list[ChannelStage] | None = None) -> ChannelResponse:
    if streams is None:
        streams = await _streams(db, ch.id)
    if stages is None:
        stages = await _stages(db, ch.id)
    return ChannelResponse(
        id=str(ch.id), company_id=str(ch.company_id), name=ch.name,
        description=ch.description, status=ch.status, template_id=ch.template_id,
        schedule=ch.schedule or {}, duplicate_policy=ch.duplicate_policy,
        config=ch.config or {}, period_days=int(ch.period_days or 30),
        last_sync_at=ch.last_sync_at.isoformat() if ch.last_sync_at else None,
        streams=[{
            "id": str(s.id), "source_id": str(s.source_id) if s.source_id else None,
            "doc_type_id": s.doc_type_id, "name": s.name, "enabled": s.enabled,
            "role": s.role,
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
async def create_channel(
    payload: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать канал (из шаблона справочника или пустой) и привязать к компании."""
    cid = await assert_company_member(payload.company_id, current_user, db)
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
            # Разрез предустановлен шаблоном — создаём ВСЕГДА (даже без источника);
            # enabled = источник подключён. Так канал несёт весь свой набор разрезов.
            db.add(ChannelStream(
                channel_id=ch.id, source_id=src_id,
                doc_type_id=s.doc_type, name=s.label, role=s.role,
                enabled=src_id is not None,
            ))
        for i, st in enumerate(tpl.stages):
            db.add(ChannelStage(
                channel_id=ch.id, stage_type=st.stage_type,
                name=st.name, order_index=i,
            ))
    await db.flush()
    return await _resp(db, ch, skipped)


@router.get("", response_model=list[ChannelResponse])
async def list_channels(cid: CompanyDep, db: AsyncSession = Depends(get_db)):
    chs = list((await db.execute(
        select(Channel).where(Channel.company_id == cid).order_by(Channel.created_at)
    )).scalars())
    ch_ids = [c.id for c in chs]
    # Batch-загрузка потоков и стадий ВСЕХ каналов (вместо N+1: 2 запроса на канал).
    from collections import defaultdict
    streams_by: dict = defaultdict(list)
    stages_by: dict = defaultdict(list)
    if ch_ids:
        for s in (await db.execute(
            select(ChannelStream).where(ChannelStream.channel_id.in_(ch_ids)))).scalars():
            streams_by[s.channel_id].append(s)
        for st in (await db.execute(
            select(ChannelStage).where(ChannelStage.channel_id.in_(ch_ids))
            .order_by(ChannelStage.order_index))).scalars():
            stages_by[st.channel_id].append(st)
    return [await _resp(db, ch, streams=streams_by[ch.id], stages=stages_by[ch.id]) for ch in chs]


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await get_owned(Channel, channel_id, current_user, db)
    return await _resp(db, ch)


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await get_owned(Channel, channel_id, current_user, db)
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
    if payload.config is not None:
        ch.config = {**(ch.config or {}), **payload.config}   # мердж (станции/правила)
    if payload.period_days is not None:
        ch.period_days = payload.period_days
    await db.flush()
    return await _resp(db, ch)


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await get_owned(Channel, channel_id, current_user, db)
    await db.delete(ch)   # streams/stages каскадом (FK ondelete=CASCADE)
    return {"deleted": str(channel_id)}


@router.post("/{channel_id}/streams", response_model=ChannelResponse)
async def add_stream(
    channel_id: uuid.UUID,
    payload: StreamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Привязать источник (поток) к каналу."""
    ch = await get_owned(Channel, channel_id, current_user, db)
    # Источник должен принадлежать той же компании (защита от кросс-привязки).
    src = await get_owned(Source, uuid.UUID(payload.source_id), current_user, db)
    if src.company_id != ch.company_id:
        raise HTTPException(400, "Источник принадлежит другой компании")
    db.add(ChannelStream(
        channel_id=ch.id, source_id=src.id,
        doc_type_id=payload.doc_type_id, name=payload.name or src.name,
    ))
    await db.flush()
    return await _resp(db, ch)


@router.delete("/{channel_id}/streams/{stream_id}", response_model=ChannelResponse)
async def remove_stream(
    channel_id: uuid.UUID,
    stream_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отвязать поток от канала."""
    ch = await get_owned(Channel, channel_id, current_user, db)
    st = await db.get(ChannelStream, stream_id)
    if st and st.channel_id == ch.id:
        await db.delete(st)
        await db.flush()
    return await _resp(db, ch)


class RunRequest(BaseModel):
    """Явный период загрузки (YYYY-MM-DD). Указывается перед запуском.
    station_codes — подмножество станций канала (UI «Обновить с выбором точек»);
    None/пусто → все станции канала."""
    date_from: str | None = None
    date_to: str | None = None
    station_codes: list[int] | None = None
    all_period: bool = False   # вся история (игнорировать даты)
    mode: str = "append"       # режим табличной загрузки: append | replace (сессии/станции) | all (реестры: переобработать все файлы-слоты)


def _loaded_total(result: dict) -> int:
    by = result.get("by_station")
    if isinstance(by, list):
        return sum(int(r.get("created", 0) or 0) for r in by)
    return int(result.get("created", 0) or 0)


def _run_summary(result: dict) -> str:
    n = _loaded_total(result)
    if result.get("stations_total") is not None:
        base = f"загружено {n}, станций {result.get('stations_ok', '?')}/{result.get('stations_total', '?')}"
    else:
        base = result.get("message") or f"загружено {n}"
    # ошибки табличных источников (сессии ЭЗС / реестр / ЦБ) иначе не видны в UI
    err = int(result.get("errors", 0) or 0)
    if err and "ошиб" not in base:
        base += f", ошибок {err}"
    return base


async def _run_channel_background(
    channel_id: uuid.UUID, date_from: str | None, date_to: str | None, log_id: uuid.UUID,
    station_codes: list[int] | None = None, all_period: bool = False,
    mode: str = "append",
) -> None:
    """Фоновый прогон: своя сессия, поэтапный commit внутри оркестратора.
    Запуск НЕ держит HTTP-запрос — UI поллит статус через /run-status."""
    async with async_session_factory() as db:
        ch = await db.get(Channel, channel_id)
        if ch is None:
            return
        result: dict = {}
        status = "success"
        try:
            result = await orchestrate_channel(
                db, ch, date_from=date_from, date_to=date_to, log_id=log_id,
                station_codes=station_codes, all_period=all_period, mode=mode)
            status = result.get("status", "success")
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("clearledger.channel").exception("Фоновый прогон канала упал")
            status = "error"
            result = {"message": f"{type(exc).__name__}: {exc}"}
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
        # обновить лог-запись (созданную синхронно при запуске)
        log = await db.get(ChannelSyncLog, log_id)
        if log is not None:
            log.status = "success" if status == "success" else (
                "partial" if status == "skipped" else "error")
            # Сессии по станциям вне справочника «Объекты» — данные загружены, но
            # это ошибка (сессия без объекта недопустима) → жёлтый статус прогона.
            if result.get("unmatched_sessions"):
                log.status = "partial"
            log.loaded = _loaded_total(result)
            # Счётчики и per-station детали для строки прогона в кокпите.
            by = result.get("by_station") if isinstance(result.get("by_station"), list) else []
            if by:
                log.skipped = sum(int(r.get("skipped", 0) or 0) for r in by)
                log.duplicates = sum(int(r.get("duplicates", 0) or 0) for r in by)
                log.errors = sum(1 for r in by if "error" in r)
            else:
                # Табличные источники (сессии ЭЗС / реестр / ЦБ) не имеют by_station —
                # берём счётчики с верхнего уровня result, иначе errors/skipped теряются
                # (лог показывал 0 ошибок при молча дропнутых строках).
                log.skipped = int(result.get("skipped", 0) or 0)
                log.duplicates = int(result.get("duplicates", 0) or 0)
                log.errors = int(result.get("errors", 0) or 0)
            st_total = result.get("stations_total")
            log.events = [{
                "level": ("error" if result.get("unmatched_sessions")
                          else "info" if status in ("success", "skipped") else "error"),
                "event": "run",
                "message": _run_summary(result),
                "stations_done": len(by),
                "stations_total": st_total if isinstance(st_total, int) else len(by),
                "loaded": log.loaded,
                "by_station": by,
            }]
            log.finished_at = datetime.now(timezone.utc)
        ch2 = await db.get(Channel, channel_id)
        cid = ch2.company_id if ch2 is not None else None
        if ch2 is not None:
            ch2.last_sync_at = datetime.now(timezone.utc)
            ch2.docs_loaded = (ch2.docs_loaded or 0) + _loaded_total(result)
        # Итог прогона — событие журнала: на него навешаны подписки «Сбои загрузок» /
        # «Загрузки данных» (notify_catalog), доставку делает dispatch_async внутри
        # log_audit. Это минимальная шина событий загрузок (docs/CONNECT.md, В3).
        if cid is not None:
            final = log.status if log is not None else status
            action = {"success": "channel.run.finished",
                      "skipped": "channel.run.finished",
                      "partial": "channel.run.partial"}.get(final, "channel.run.failed")
            from app.audit import log_audit
            await log_audit(db, actor=None, company_id=cid, action=action,
                            target=ch2.name if ch2 is not None else None,
                            details={"итог": _run_summary(result)})
        await db.commit()

    # Доводка канала продаж топлива — вне сессии прогона, своим соединением.
    # Приём дедуплицирует смену по натуральному ключу, поэтому смена, снятая
    # ОТКРЫТОЙ (ночной прогон попадает ровно в неё), навсегда остаётся с нулевой
    # выручкой; реализации же вообще не имели расписания. Без этого шага дырка в конце
    # периода появляется снова каждую ночь — при живой сети и «успешных» прогонах.
    if cid is not None and status != "error" and result.get("kind") == "fuel_shift" \
            and date_from and date_to:
        try:
            from app.services.fuel_shift_refresh import followup_fuel_sales
            fu = await followup_fuel_sales(cid, date_from, date_to)
            logging.getLogger("clearledger.channel").info(
                "Доводка продаж %s…%s: смен дописано %s, реализаций добавлено %s",
                date_from, date_to, (fu.get("shifts") or {}).get("recovered"), fu.get("tx_created"))
        except Exception:  # noqa: BLE001 — доводка не меняет статус прогона
            logging.getLogger("clearledger.channel").exception("Доводка продаж не удалась")


@router.post("/{channel_id}/run")
async def run_channel(
    channel_id: uuid.UUID,
    payload: RunRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Запустить прогон канала В ФОНЕ и сразу вернуть управление.

    Прогон (12 станций × период смен) длится минуты — синхронно он блокировал бы
    UI и рвался по таймауту. Поэтому создаём лог status='running', запускаем фоновую
    задачу и возвращаем sync_log_id. UI поллит GET /{id}/run-status.
    Период берётся из payload.date_from/date_to (UI требует указать перед запуском).
    """
    ch = await get_owned(Channel, channel_id, current_user, db)
    df = payload.date_from if payload else None
    dt = payload.date_to if payload else None
    sc = payload.station_codes if payload else None
    ap = bool(payload.all_period) if payload else False
    md = (payload.mode if payload else None) or "append"
    _scn = f", станций {len(sc)}" if sc else ""
    _mdn = " · переписать" if md == "replace" else ""
    _per = "вся история" if ap else f"{df or '—'}…{dt or '—'}"
    log = ChannelSyncLog(
        channel_id=ch.id, status="running", finished_at=None,
        date_from=None if ap else df, date_to=None if ap else dt,
        events=[{"level": "info", "event": "run",
                 "message": f"загрузка запущена ({_per}{_scn}{_mdn})"}],
    )
    db.add(log)
    await db.flush()
    log_id = log.id
    await db.commit()  # зафиксировать лог до старта фоновой задачи
    asyncio.create_task(_run_channel_background(ch.id, df, dt, log_id, sc, ap, md))
    return {"sync_log_id": str(log_id), "status": "running",
            "message": "Загрузка запущена в фоне"}


@router.get("/{channel_id}/run-status")
async def run_status(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Статус последнего прогона канала (для поллинга прогресса в UI)."""
    ch = await get_owned(Channel, channel_id, current_user, db)
    log = (await db.execute(
        select(ChannelSyncLog).where(ChannelSyncLog.channel_id == ch.id)
        .order_by(ChannelSyncLog.started_at.desc()).limit(1)
    )).scalar_one_or_none()
    if log is None:
        return {"status": "idle", "running": False, "loaded": 0, "stations_done": 0,
                "stations_total": 0, "docs_loaded": ch.docs_loaded or 0, "message": ""}
    ev = (log.events[-1] if log.events else {}) or {}
    return {
        "status": log.status,
        "running": log.status == "running",
        "loaded": log.loaded,
        "stations_done": ev.get("stations_done", 0),
        "stations_total": ev.get("stations_total", 0),
        "message": ev.get("message", ""),
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "docs_loaded": ch.docs_loaded or 0,
        "last_sync_at": ch.last_sync_at.isoformat() if ch.last_sync_at else None,
    }


@router.get("/{channel_id}/logs")
async def channel_logs(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """История прогонов канала (ChannelSyncLog) — для вкладки «Лог».
    Одна запись = один прогон (последний событийный итог)."""
    ch = await get_owned(Channel, channel_id, current_user, db)
    # сортировка по ОТОБРАЖАЕМОЙ метке (finished_at, для running — started_at),
    # чтобы видимый timestamp строго убывал даже при пересекающихся прогонах.
    logs = (await db.execute(
        select(ChannelSyncLog).where(ChannelSyncLog.channel_id == ch.id)
        .order_by(func.coalesce(ChannelSyncLog.finished_at, ChannelSyncLog.started_at).desc())
        .limit(100)
    )).scalars().all()
    level_map = {"success": "success", "error": "error", "partial": "warn", "running": "info"}
    event_map = {"success": "DONE", "error": "ERROR", "partial": "SYNC", "running": "SYNC"}
    out = []
    for lg in logs:
        ev = (lg.events[-1] if lg.events else {}) or {}
        ts = lg.finished_at or lg.started_at
        out.append({
            "timestamp": ts.isoformat() if ts else None,
            "level": level_map.get(lg.status, "info"),
            "event": event_map.get(lg.status, "SYNC"),
            "message": ev.get("message") or f"загружено {lg.loaded or 0}",
        })
    return out


@router.get("/{channel_id}/runs")
async def channel_runs(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Лента прогонов канала (кокпит): структурные строки — период, объём,
    станции, ошибки + per-station детали для раскрытия. Новые сверху."""
    ch = await get_owned(Channel, channel_id, current_user, db)
    logs = (await db.execute(
        select(ChannelSyncLog).where(ChannelSyncLog.channel_id == ch.id)
        .order_by(func.coalesce(ChannelSyncLog.finished_at, ChannelSyncLog.started_at).desc())
        .limit(100)
    )).scalars().all()
    out = []
    for lg in logs:
        ev = (lg.events[-1] if lg.events else {}) or {}
        out.append({
            "id": str(lg.id),
            "status": lg.status,
            "started_at": lg.started_at.isoformat() if lg.started_at else None,
            "finished_at": lg.finished_at.isoformat() if lg.finished_at else None,
            "date_from": lg.date_from,
            "date_to": lg.date_to,
            "loaded": lg.loaded or 0,
            "skipped": lg.skipped or 0,
            "duplicates": lg.duplicates or 0,
            "errors": lg.errors or 0,
            "stations_done": ev.get("stations_done", 0),
            "stations_total": ev.get("stations_total", 0),
            "message": ev.get("message") or f"загружено {lg.loaded or 0}",
            "by_station": ev.get("by_station") or [],
        })
    return out


class IngestRequest(BaseModel):
    packages: list[dict[str, Any]]   # пакеты смен ЦБ (контракт .epf v2)


@router.post("/{channel_id}/ingest")
async def ingest_channel(
    channel_id: uuid.UUID,
    payload: IngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Принять пакеты смен ЦБ в L2 (нормализация + идемпотентная запись DataEntry).

    Стадии normalize+save канала сопутки/общепита. Пакеты даёт стадия fetch
    (onec_operational через com_worker) — здесь принимаем готовые пакеты.
    """
    ch = await get_owned(Channel, channel_id, current_user, db)
    result = await ingest_packages(db, ch.company_id, payload.packages, channel_id=ch.id)
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
