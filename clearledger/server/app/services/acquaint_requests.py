"""Ознакомление как активность процесса: маршрут доводит документ до людей.

Четвёртая просьба того же рода, что круг виз (`approval_requests`), поручение
(`errands`) и заведение документа (`document_requests`). Разница в том, чего
процесс ждёт: там решения («согласовано»), здесь — осведомлённости («прочитал»).

Ради чего это нужно. Согласование и утверждение — половина делопроизводства;
вторая половина в том, чтобы решение доехало до тех, кого оно касается. Приказ,
подписанный директором и не доведённый до смены, не работает, и вопрос «а он
знал» должен решаться листом, а не памятью. До сих пор просить об этом маршрут
не мог: он умел завести документ и собрать по нему визы, а дальше упирался в
человека, который помнит, кого положено ознакомить.

Документ можно не называть. Типовая цепочка — «заведи документ по заготовке →
собери визы → ознакомь смену» — рождает документ уже внутри процесса, и его
идентификатор маршруту неоткуда взять: он появился после того, как маршрут был
написан. Поэтому без явного `doc_id` берётся последний документ, заведённый по
этому же процессу.

Ожидание исхода выражается глаголом `on_done`, как и у остальных просьб: задан —
процесс ждёт, пока лист закроется, и только тогда идёт дальше; не задан —
документ разослан, а маршрут продолжает своей дорогой.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalRequest, Department, DocAcquaint, DocCard, DocEvent, UserCompany,
)

log = logging.getLogger("clearledger.acquaint")


class AcquaintRequestError(ValueError):
    """Просьбу выполнить нельзя, и повтор доставки этого не изменит."""


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _document(db: AsyncSession, company_id: uuid.UUID, process_id: str,
                    data: dict[str, Any]) -> DocCard:
    """Какой документ доводим: названный явно или заведённый этим же процессом."""
    raw = _uuid_or_none(data.get("doc_id") or data.get("docId"))
    if raw is not None:
        doc = (await db.execute(select(DocCard).where(
            DocCard.id == raw, DocCard.company_id == company_id))).scalar_one_or_none()
        if doc is None:
            raise AcquaintRequestError("Документ не найден в этой компании")
        return doc

    doc_id = (await db.execute(
        select(ApprovalRequest.doc_id)
        .where(ApprovalRequest.company_id == company_id,
               ApprovalRequest.process_id == str(process_id)[:64],
               ApprovalRequest.doc_id.is_not(None))
        .order_by(ApprovalRequest.created_at.desc()).limit(1))).scalar_one_or_none()
    if doc_id is None:
        raise AcquaintRequestError(
            "В просьбе не назван документ, а процесс ни одного не заводил")
    doc = await db.get(DocCard, doc_id)
    if doc is None:
        raise AcquaintRequestError("Документ процесса больше не существует")
    return doc


async def _people(db: AsyncSession, company_id: uuid.UUID,
                  data: dict[str, Any]) -> tuple[set[uuid.UUID], Department | None,
                                                 set[uuid.UUID]]:
    """Кого знакомим: поимённо и/или подразделением.

    Подразделение называется именем, а не идентификатором, по той же причине, по
    которой так называются заготовки: маршруты пишут люди, а идентификатор при
    пересборке пространства меняется — «Служба эксплуатации» остаётся.

    Отбор идёт через тот же фильтр, что и у ручного направления: человек, который
    не может открыть «Трек», в лист не попадает — иначе лист врал бы о том, что
    документ доведён.
    """
    from app.routers.docs_router import _docs_members  # локальный импорт: цикл

    named = {u for u in (_uuid_or_none(x) for x in (
        data.get("user_ids") or data.get("userIds") or [])) if u is not None}
    people: set[uuid.UUID] = set(await _docs_members(db, company_id, named)) if named else set()

    department: Department | None = None
    from_department: set[uuid.UUID] = set()
    dep_id = _uuid_or_none(data.get("department_id") or data.get("departmentId"))
    dep_name = str(data.get("department") or data.get("departmentName") or "").strip()
    if dep_id is not None or dep_name:
        statement = select(Department).where(Department.company_id == company_id)
        statement = (statement.where(Department.id == dep_id) if dep_id is not None
                     else statement.where(Department.name == dep_name))
        department = (await db.execute(statement.limit(1))).scalar_one_or_none()
        if department is None:
            raise AcquaintRequestError(
                f"Подразделение «{dep_name or dep_id}» не заведено")
        members = set((await db.execute(select(UserCompany.user_id).where(
            UserCompany.company_id == company_id,
            UserCompany.department_id == department.id))).scalars().all())
        from_department = set(await _docs_members(db, company_id, members, department.id))
        people |= from_department

    if not people:
        raise AcquaintRequestError("Некого знакомить: получатели не заданы или "
                                   "не могут открыть «Трек»")
    return people, department, from_department


def _due(data: dict[str, Any]) -> datetime | None:
    """Срок ознакомления: датой или числом дней от сегодня.

    Дни допускаются потому, что маршрут пишется один раз, а срабатывает много:
    «три дня» осмысленно всегда, конкретная дата — ровно один раз.
    """
    raw = data.get("due_at") or data.get("dueAt")
    if raw:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise AcquaintRequestError("Срок ознакомления непригоден") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    days = data.get("due_days") or data.get("dueDays")
    if days in (None, ""):
        return None
    try:
        return datetime.now(timezone.utc) + timedelta(days=int(days))
    except (TypeError, ValueError) as exc:
        raise AcquaintRequestError("Срок ознакомления непригоден") from exc


async def request(db: AsyncSession, company_id: uuid.UUID, request_id: str,
                  data: dict[str, Any]) -> ApprovalRequest:
    """Направить документ на ознакомление и запомнить, ждёт ли процесс исхода."""
    from app.routers.docs_router import _acquaint_snapshot  # локальный импорт: цикл

    if company_id is None:
        raise AcquaintRequestError("Событие пришло без компании")
    process_id = (data.get("process_id") or data.get("processId")
                  or data.get("ticket_id"))
    if not process_id:
        raise AcquaintRequestError("В просьбе не указан процесс")

    doc = await _document(db, company_id, str(process_id), data)
    people, department, from_department = await _people(db, company_id, data)
    due_at = _due(data)

    snapshot, snapshot_hash = await _acquaint_snapshot(db, doc)
    existing = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == doc.id,
        DocAcquaint.user_id.in_(people)))).scalars().all()
    have = {row.user_id for row in existing if row.snapshot_sha256 == snapshot_hash}
    for row in existing:
        if row.status == "pending" and row.snapshot_sha256 != snapshot_hash:
            row.status = "superseded"
    for uid in people - have:
        db.add(DocAcquaint(
            company_id=company_id, doc_id=doc.id, user_id=uid,
            reason="department" if uid in from_department else "manual",
            reason_ref=(department.id if department and uid in from_department else None),
            reason_name=(department.name if department and uid in from_department else None),
            due_at=due_at, created_by=None,
            document_snapshot=snapshot, snapshot_sha256=snapshot_hash))
    db.add(DocEvent(doc_id=doc.id, kind="field", user_id=None, actor_name="Процесс",
                    to_value=f"ознакомление: {len(people)} чел.",
                    note=f"направлено маршрутом (процесс {process_id})"))

    verb = (data.get("on_done") or data.get("onDone") or "").strip()
    row = ApprovalRequest(
        company_id=company_id,
        request_id=str(request_id)[:120],
        kind="acquaint",
        process_id=str(process_id)[:64],
        branch_id=(str(data.get("branch_id") or data.get("branchId"))[:64]
                   if data.get("branch_id") or data.get("branchId") else None),
        doc_id=doc.id,
        round=len(people),
        on_approved=verb[:120] or None,
        on_rejected=(data.get("on_overdue") or data.get("onOverdue") or "").strip()[:120] or None,
    )
    # Ждать нечего — закрываем просьбу сразу. Открытая запись держала бы документ
    # занятым (частичный индекс «одна живая просьба на документ») и не пустила бы
    # следующий круг виз по той же бумаге.
    if not verb:
        row.outcome = "done"
        row.decided_at = datetime.now(timezone.utc)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AcquaintRequestError(
            "По этому документу уже открыта просьба процесса") from exc
    # Все получатели уже читали эту редакцию — ждать нечего, и просьба, повисшая
    # в ожидании, остановила бы процесс навсегда: новых отметок не будет.
    if verb:
        await close_if_done(db, doc.id)
    log.info("документ %s направлен на ознакомление %s чел. по просьбе процесса %s",
             doc.id, len(people), process_id)
    return row


async def close_if_done(db: AsyncSession, doc_id: uuid.UUID) -> ApprovalRequest | None:
    """Лист закрылся — зафиксировать исход для процесса, который его ждёт.

    Зовётся из отметки об ознакомлении, внутри её транзакции: доставка пойдёт
    фоном, но потерять исход нельзя — человек уже прочитал, второй раз не прочтёт.
    """
    row = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.doc_id == doc_id,
        ApprovalRequest.kind == "acquaint",
        ApprovalRequest.outcome.is_(None)).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    left = await db.scalar(select(DocAcquaint.id).where(
        DocAcquaint.doc_id == doc_id, DocAcquaint.status == "pending").limit(1))
    if left is not None:
        return None
    row.outcome = "done"
    row.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return row
