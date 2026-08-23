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

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite, InboundEvent

log = logging.getLogger("clearledger.inbound")

# События, которые Ядро умеет обрабатывать. Остальные принимаем и помечаем
# `skipped`: неизвестное событие — не ошибка отправителя, а наш ещё не написанный
# обработчик, и ретраить его бессмысленно.
HANDLED = {"case.stage_changed", "case.closed", "approval.requested",
           "errand.requested", "document.requested", "acquaint.requested"}


async def accept(db: AsyncSession, provider: str, event: dict[str, Any],
                 company_id: Any = None) -> tuple[str, str]:
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
    # Компания — та, чьим ключом интеграции пришло событие. Полю в теле не верим:
    # у приложения своя нумерация компаний, и его "companyId" — не наш.
    row.company_id = company_id
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
            # Откат обязателен: после сорванной вставки сессия не принимает записи,
            # и без него отметка «разобрано» не легла бы ни на это событие, ни на
            # следующие. Отметка ставится отдельным запросом — объект после отката
            # к сессии уже не привязан.
            await db.rollback()
            await db.execute(update(InboundEvent).where(InboundEvent.id == row.id).values(
                processed_at=datetime.now(timezone.utc), result="failed",
                error=f"{type(exc).__name__}: {exc}"[:500]))
            await db.commit()
            done += 1
            continue
        row.processed_at = datetime.now(timezone.utc)
        row.result = result
        row.error = error
        # Каждое событие — своей транзакцией: разбор одного не должен пропасть
        # из-за соседнего, а обработчик мог уже что-то создать.
        await db.commit()
        done += 1
    return done


async def process_soon() -> int:
    """Разобрать принятое, не дожидаясь тика регламента.

    Регламент ходит раз в пять минут — этого довольно для событий, которые никто
    не ждёт глядя в экран. Но просьбу, заведённую человеком из карточки заявки,
    ждут именно так: нажал «Завести» и смотрит, появилось ли. Пять минут пустого
    списка научат нажимать второй раз.

    Своя сессия и свой отказ: ответ отправителю уже отдан, и наша неудача здесь
    не должна ни превратиться в его ретрай, ни потеряться — регламент подберёт.
    """
    from app.database import async_session_factory

    try:
        async with async_session_factory() as db:
            return await process_pending(db)
    except Exception:  # noqa: BLE001 — фоновая попытка, страхует регламент
        log.exception("Ранний разбор принятых событий не удался")
        return 0


async def _start_approval(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    """Узел маршрута просит собрать визы по документу.

    Отказ запуска (документ не той редакции, вид требует регистрации, маршрут
    пуст) — это `skipped` с текстом причины, а не ошибка доставки: повторять
    доставку бессмысленно, пока человек не поправит документ или маршрут.
    """
    from app.services import approval_requests

    if row.company_id is None:
        return "skipped", "Событие пришло без компании"
    try:
        req = await approval_requests.request(
            db, row.company_id, row.external_id, (row.payload or {}).get("data") or {})
    except approval_requests.RequestError as exc:
        return "skipped", str(exc)[:500]
    return "ok", f"круг {req.round} по документу {req.doc_id}"


async def _start_document(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    """Узел маршрута просит завести документ по заготовке «Трека».

    Третья просьба того же рода. Отличие от круга виз в том, что документа ещё
    нет: раньше маршрут мог попросить согласовать бумагу, но взять её было
    неоткуда — кто-то должен был создать её руками и вовремя.

    Невыполнимая просьба (нет такой заготовки, она не документная, не указан
    процесс) — `skipped` с причиной, а не ошибка доставки: от повтора заготовка
    не появится, а очередь на ней встанет.
    """
    from app.services import document_requests

    if row.company_id is None:
        return "skipped", "Событие пришло без компании"
    try:
        req = await document_requests.request(
            db, row.company_id, row.external_id, (row.payload or {}).get("data") or {})
    except document_requests.DocumentRequestError as exc:
        return "skipped", str(exc)[:500]
    waiting = "ждём исход" if req.on_approved else "без ожидания"
    return "ok", f"документ {req.doc_id} заведён ({waiting})"


async def _start_acquaint(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    """Узел маршрута просит довести документ до людей.

    Четвёртая просьба того же рода. Согласование и утверждение отвечают на
    вопрос «можно ли», ознакомление — на вопрос «а он знал»; приказ, никем не
    прочитанный, не работает, и лист об этом честнее памяти.

    Невыполнимая просьба (некого знакомить, нет документа, подразделение не
    заведено) — `skipped` с причиной: от повтора людей не прибавится.
    """
    from app.services import acquaint_requests

    if row.company_id is None:
        return "skipped", "Событие пришло без компании"
    try:
        req = await acquaint_requests.request(
            db, row.company_id, row.external_id, (row.payload or {}).get("data") or {})
    except acquaint_requests.AcquaintRequestError as exc:
        return "skipped", str(exc)[:500]
    waiting = "ждём исход" if req.on_approved else "без ожидания"
    return "ok", f"ознакомление {req.round} чел. по документу {req.doc_id} ({waiting})"


async def _start_errand(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    """Узел маршрута просит сделать работу по заготовке «Трека».

    Симметрично `_start_approval`: разворачиваем поручение и запоминаем, что процесс
    ждёт его исхода. Невыполнимая просьба помечается `skipped` с причиной, а не
    ретраится: заготовки не станет от повтора, а очередь на ней остановится.
    """
    from app.services import errands

    data = (row.payload or {}).get("data") or {}
    try:
        await errands.request(db, row.company_id, row.external_id, data)
    except errands.ErrandError as exc:
        return "skipped", str(exc)[:500]
    return "ok", None


async def _handle(db: AsyncSession, row: InboundEvent) -> tuple[str, str | None]:
    if row.type == "approval.requested":
        return await _start_approval(db, row)
    if row.type == "errand.requested":
        return await _start_errand(db, row)
    if row.type == "document.requested":
        return await _start_document(db, row)
    if row.type == "acquaint.requested":
        return await _start_acquaint(db, row)

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
