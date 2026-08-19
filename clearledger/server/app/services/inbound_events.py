"""Приём и обработка событий от приложений пространства.

Фаза 3 плана (`ecosystem-deploy/audit-process-runtime.md`). Прежде ход процесса и
состояние проекта связывались синхронной парой вызовов: Координатор коммитил
переход, Ядро следом двигало воронку. Обрыв между этими точками оставлял маршрут
впереди, а проект позади — навсегда, потому что повторить шаг нельзя: второй раз
ребро не срабатывает.

Теперь Координатор кладёт событие в свой outbox и доставляет с ретраями, а Ядро
принимает его в `inbound_events` и обрабатывает отдельно. Приём и обработка
разделены намеренно: приём обязан быть быстрым и почти всегда успешным, иначе
отправитель начнёт ретраить из-за нашей внутренней ошибки и копить очередь.

Идемпотентность — ключ `(provider, external_id)`. Повторная доставка при такой
схеме штатна, и второе появление того же события отвечает «уже принято», а не
обрабатывается заново.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite, InboundEvent

log = logging.getLogger("clearledger.inbound")

# События, которые Ядро умеет обрабатывать. Остальные принимаем и помечаем
# `skipped`: неизвестное событие — не ошибка отправителя, а наш ещё не написанный
# обработчик, и ретраить его бессмысленно.
HANDLED = {"case.stage_changed", "case.closed"}


async def accept(db: AsyncSession, provider: str, event: dict[str, Any]) -> tuple[str, str]:
    """Принять событие. Возвращает (статус, пояснение) для ответа отправителю."""
    external_id = str(event.get("id") or "").strip()
    if not external_id:
        return "rejected", "У события нет идентификатора"

    row = InboundEvent(
        provider=provider,
        external_id=external_id,
        type=str(event.get("type") or "")[:80],
        payload=event,
    )
    company = event.get("companyId") or (event.get("data") or {}).get("company_id")
    if company:
        # Компания приложения ≠ компания Ядра, поэтому в поле кладём только то,
        # что удалось сопоставить; иначе оставляем пустым и разбираем при обработке.
        row.company_id = None
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return "duplicate", "Событие уже принято"
    return "accepted", "Принято"


async def process_pending(db: AsyncSession, limit: int = 50) -> int:
    """Обработать принятые события. Ошибка одного не отменяет остальные."""
    rows = (await db.execute(
        select(InboundEvent)
        .where(InboundEvent.processed_at.is_(None))
        .order_by(InboundEvent.received_at)
        .limit(limit)
    )).scalars().all()

    done = 0
    for row in rows:
        try:
            result, error = await _handle(db, row)
        except Exception as exc:  # noqa: BLE001 — одно событие не валит проход
            log.exception("Событие %s (%s) не обработано", row.external_id, row.type)
            result, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        row.processed_at = datetime.now(timezone.utc)
        row.result = result
        row.error = error
        done += 1
    return done


async def _handle(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    if row.type not in HANDLED:
        return "skipped", None

    data = (row.payload or {}).get("data") or {}
    ticket_id = data.get("ticket_id") or (row.payload or {}).get("subject")
    if not ticket_id:
        return "skipped", "В событии нет ссылки на процесс"

    # Проект находим через тот же процесс: Ядро читает витрину Поддержки прямым
    # SQL — базы сведены, — и это дешевле, чем гонять идентификатор проекта в
    # каждом событии и надеяться, что отправитель его положил.
    project_id = await db.scalar(text(
        "select eco_project_id from public.tickets where id = :tid"), {"tid": str(ticket_id)})
    if not project_id:
        return "skipped", "Процесс не связан с проектом"

    site = (await db.execute(
        select(EzsSite).where(EzsSite.id == project_id).limit(1)
    )).scalar_one_or_none()
    if site is None:
        return "skipped", "Проект не найден"

    # Отражаем исход тем же кодом, что и явная сверка: одна логика на два входа —
    # человек нажал «Сверить» и событие пришло само.
    from app.services import projects_process

    await projects_process.reconcile(db, site.company_id, site, user=None)
    # Шаг доигран — отметка намерения больше не нужна.
    site.pending_link_id = None
    site.pending_at = None
    return "ok", None
