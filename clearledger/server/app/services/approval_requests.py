"""Согласование как активность процесса: запуск круга виз и возврат исхода.

Фаза 3а плана (`ecosystem-deploy/audit-process-runtime.md`). До этого «Трек» и
Координатор жили порознь: маршрут стройки доходил до узла «согласовать проект»,
дальше человек шёл в документы, собирал визы и возвращался нажать кнопку. Работа
машины прерывалась человеком-курьером — и рвалась ровно там, где он забывал.

Здесь передача становится машинной, но связь остаётся односторонней по смыслу:
согласование — работа «Трека», и он ничего не знает о стройке. Процесс просит
активность («собери визы по этому документу»), а получает событие исхода.

Две вещи, из-за которых это не сводится к паре вызовов:

1. **Круг нельзя открыть дважды.** Доставка запроса — at-least-once, повтор
   штатен. Ключ `request_id` и частичный уникальный индекс по открытому кругу
   держат правило «живой круг по документу один» даже при гонке.
2. **Исход нельзя потерять.** Круг закрывается независимо от того, доступен ли
   сейчас Координатор. Поэтому исход сначала фиксируется у себя, а доставляется
   фоновым проходом с ретраями: визы собраны один раз, второй раз их не соберут.

Действие процесса задаётся глаголом («согласовано»), а не идентификатором ребра:
граф пересобирают, идентификаторы меняются, глагол остаётся.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, DocCard, DocKind
from app.services import doc_approvals

log = logging.getLogger("clearledger.approvals")

# Сколько раз пытаемся отдать исход, прежде чем перестать долбить Координатор.
# Дальше запись остаётся видимой с текстом ошибки: молчаливая сдача хуже, потому
# что круг виз к этому моменту уже закрыт и его исход существует только у нас.
MAX_ATTEMPTS = 12


class RequestError(Exception):
    """Запрос на согласование невыполним — с причиной для журнала событий."""


async def request(db: AsyncSession, company_id: uuid.UUID, request_id: str,
                  data: dict[str, Any]) -> ApprovalRequest:
    """Запустить круг виз по просьбе узла маршрута.

    Проверки повторяют ручную подачу на согласование: рабочая редакция,
    регистрация, если вид её требует, заполненные обязательные реквизиты. Процесс
    не должен уметь того, чего не умеет человек, — иначе через маршрут в оборот
    попадёт документ, который в ручном режиме отклонили бы на входе.
    """
    doc_id = data.get("doc_id") or data.get("docId")
    process_id = data.get("process_id") or data.get("processId") or data.get("ticket_id")
    if not doc_id or not process_id:
        raise RequestError("В запросе нет документа или процесса")

    try:
        doc_uuid = uuid.UUID(str(doc_id))
    except ValueError as exc:
        raise RequestError("Идентификатор документа непригоден") from exc

    doc = (await db.execute(select(DocCard).where(
        DocCard.id == doc_uuid, DocCard.company_id == company_id))).scalar_one_or_none()
    if doc is None:
        raise RequestError("Документ не найден в этой компании")
    if doc.status not in ("draft", "registered"):
        raise RequestError("Согласовать можно только рабочую редакцию документа")
    if doc.approval_status == "pending":
        raise RequestError("Документ уже на согласовании")

    kind = await db.get(DocKind, doc.kind_id) if doc.kind_id else None
    if kind is None:
        raise RequestError("У документа не задан вид")
    if kind.requires_registration and not doc.reg_number:
        raise RequestError("Документ не зарегистрирован, а вид этого требует")

    route = data.get("route") or kind.route or []

    # Повтор доставки и второй круг ловим заранее, до вставки: сорванная вставка
    # оставляет сессию непригодной для записи, а оба случая штатные, не сбойные.
    if await db.scalar(select(ApprovalRequest.id).where(
            ApprovalRequest.company_id == company_id,
            ApprovalRequest.request_id == request_id)):
        raise RequestError("Запрос уже принят")
    if await db.scalar(select(ApprovalRequest.id).where(
            ApprovalRequest.company_id == company_id,
            ApprovalRequest.doc_id == doc.id,
            ApprovalRequest.outcome.is_(None))):
        raise RequestError("Круг по этому документу уже открыт")

    row = ApprovalRequest(
        company_id=company_id,
        request_id=request_id,
        process_id=str(process_id),
        branch_id=str(data["branch_id"]) if data.get("branch_id") else None,
        doc_id=doc.id,
        on_approved=(data.get("on_approved") or "").strip()[:120] or None,
        on_rejected=(data.get("on_rejected") or "").strip()[:120] or None,
    )
    db.add(row)
    try:
        # Индексы остаются страховкой от гонки — проверки выше снимают штатные
        # случаи, а этот путь на практике не должен срабатывать.
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise RequestError("Круг по этому документу уже открыт") from exc

    res = await doc_approvals.start(db, company_id, doc, route, actor=None)
    if res.get("error"):
        # Круг не пошёл — запись о запросе не нужна: она заняла бы «открытый круг»
        # по документу и не пустила бы следующую, исправленную попытку.
        await db.delete(row)
        await db.flush()
        raise RequestError(res["error"])

    row.round = int(res.get("round") or 0)
    await db.flush()
    return row


async def mark_outcome(db: AsyncSession, doc_id: uuid.UUID, outcome: str) -> None:
    """Записать исход круга. Вызывается из терминальных точек согласования.

    Без сети и без задержек: точка вызова — внутри транзакции, закрывающей круг, и
    именно поэтому исход не может потеряться при обрыве связи. Доставку берёт на
    себя фоновый проход.
    """
    row = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.doc_id == doc_id,
        ApprovalRequest.outcome.is_(None)).limit(1))).scalar_one_or_none()
    if row is None:
        return  # Документ согласуют вручную — процессу нечего сообщать.
    row.outcome = outcome
    row.decided_at = datetime.now(timezone.utc)


async def deliver_pending(db: AsyncSession, limit: int = 20) -> int:
    """Отдать процессам исходы закрытых кругов. Ошибка одного не валит остальные."""
    rows = (await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.outcome.is_not(None),
               ApprovalRequest.delivered_at.is_(None),
               ApprovalRequest.attempts < MAX_ATTEMPTS)
        .order_by(ApprovalRequest.decided_at)
        .limit(limit)
    )).scalars().all()

    done = 0
    for row in rows:
        row.attempts += 1
        try:
            await _deliver(db, row)
            row.delivered_at = datetime.now(timezone.utc)
            row.last_error = None
            done += 1
        except Exception as exc:  # noqa: BLE001 — одна связь не валит проход
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("Исход круга по документу %s не доставлен: %s", row.doc_id, exc)
    return done


async def _deliver(db: AsyncSession, row: ApprovalRequest) -> None:
    verb = row.on_approved if row.outcome == "approved" else row.on_rejected
    if not verb:
        # Маршрут просил только собрать визы, двигать процесс не просил. Это
        # законный случай, а не недоставка: исход виден в карточке документа.
        return

    from app.services import projects_process

    card = await projects_process.call_process(
        db, row.company_id, "GET", f"/api/v1/process/instances/{row.process_id}")
    action = _match_action(card.get("availableActions") or [], verb)
    if action is None:
        raise RequestError(
            f"В процессе нет доступного действия «{verb}» "
            f"(есть: {', '.join(_labels(card.get('availableActions') or [])) or 'нет'})")

    await projects_process.call_process(
        db, row.company_id, "POST",
        f"/api/v1/process/instances/{row.process_id}/actions",
        json={"actionId": action.get("id"), "branchId": row.branch_id,
              "payload": {"approval_round": row.round, "doc_id": str(row.doc_id)}})


def _labels(actions: list[dict[str, Any]]) -> list[str]:
    return [str(a.get("verb") or a.get("name") or a.get("code") or "") for a in actions if a]


def _match_action(actions: list[dict[str, Any]], verb: str) -> dict[str, Any] | None:
    """Найти действие по глаголу — без учёта регистра и лишних пробелов.

    Сравниваем и с кодом: маршруты пишут разные люди, и «approve» рядом с
    «Согласовано» встречается чаще, чем хотелось бы.
    """
    want = verb.strip().casefold()
    for action in actions:
        for field in ("verb", "code", "name"):
            value = str(action.get(field) or "").strip().casefold()
            if value and value == want:
                return action
    return None
