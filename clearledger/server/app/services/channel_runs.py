"""Владелец итогов и фонового lifecycle прогона канала.

Dispatch, ingest и публикация факта остаются в channel_orchestrator.
Caller создаёт и коммитит running log; этот owner открывает свою сессию.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import Channel, ChannelSyncLog
from app.services.channel_orchestrator import run_channel


def loaded_total(result: dict) -> int:
    by = result.get("by_station")
    if isinstance(by, list):
        return sum(int(r.get("created", 0) or 0) for r in by)
    return int(result.get("created", 0) or 0)

def run_summary(result: dict, *, loaded_total_fn: Callable[[dict], int] | None = None) -> str:
    if loaded_total_fn is None:
        loaded_total_fn = loaded_total
    n = loaded_total_fn(result)
    if result.get("stations_total") is not None:
        base = f"загружено {n}, станций {result.get('stations_ok', '?')}/{result.get('stations_total', '?')}"
    else:
        base = result.get("message") or f"загружено {n}"
    # ошибки табличных источников (сессии ЭЗС / реестр / ЦБ) иначе не видны в UI
    err = int(result.get("errors", 0) or 0)
    if err and "ошиб" not in base:
        base += f", ошибок {err}"
    return base

async def run_channel_background(
    channel_id: uuid.UUID, date_from: str | None, date_to: str | None, log_id: uuid.UUID,
    station_codes: list[int] | None = None, all_period: bool = False,
    mode: str = "append",
    *,
    session_factory: Callable[[], AsyncSession] | None = None,
    orchestrate_channel: Callable[..., Awaitable[dict]] | None = None,
    loaded_total_fn: Callable[[dict], int] | None = None,
    run_summary_fn: Callable[[dict], str] | None = None,
) -> None:
    """Фоновый прогон: своя сессия, поэтапный commit внутри оркестратора.
    Запуск НЕ держит HTTP-запрос — UI поллит статус через /run-status."""
    if session_factory is None:
        session_factory = async_session_factory
    if orchestrate_channel is None:
        orchestrate_channel = run_channel
    if loaded_total_fn is None:
        loaded_total_fn = loaded_total
    if run_summary_fn is None:
        run_summary_fn = run_summary
    async with session_factory() as db:
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
            log.loaded = loaded_total_fn(result)
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
                "message": run_summary_fn(result),
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
            ch2.docs_loaded = (ch2.docs_loaded or 0) + loaded_total_fn(result)
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
                            details={"итог": run_summary_fn(result)})
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
