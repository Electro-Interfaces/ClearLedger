"""Входящие назначения и их просмотр: одна версия передачи, личный курсор."""
import asyncio
import logging
import uuid

from sqlalchemy import and_, event, func, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import TaskAssignmentRead, Task


def assign(task: Task, assignee_id: uuid.UUID | None, actor_id: uuid.UUID) -> None:
    if task.assignee_id != assignee_id:
        task._assignment_actor_id = actor_id
        task.assignee_id = assignee_id


async def counts(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    # Агрегат по всем данным, без лимита страницы и загрузки карточек.
    new = and_(
        Task.assignment_by_id.is_distinct_from(user_id),
        TaskAssignmentRead.assignment_revision.is_distinct_from(Task.assignment_revision),
    )
    row = (await db.execute(select(
        func.count().filter(new).label("new"),
        func.count().filter(Task.due_at < func.now()).label("overdue"),
    ).select_from(Task).outerjoin(TaskAssignmentRead, and_(
        TaskAssignmentRead.company_id == Task.company_id,
        TaskAssignmentRead.user_id == user_id,
        TaskAssignmentRead.task_id == Task.id,
    )).where(
        Task.company_id == company_id, Task.assignee_id == user_id,
        Task.status == "open", Task.visibility != "personal",
        or_(Task.waiting_for.is_(None), Task.waiting_for != "external"),
    ))).one()
    return {"new": row.new, "overdue": row.overdue}


async def acknowledge(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID,
                      task_id: uuid.UUID, revision: uuid.UUID) -> bool:
    # Блокируем передачу до коммита: запоздалый ответ старой карточки не может
    # погасить новое назначение. Чужой просмотр никогда не пишет отметку исполнителя.
    task = (await db.execute(select(Task).where(
        Task.id == task_id, Task.company_id == company_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if task.assignee_id != user_id or task.assignment_revision != revision:
        return False
    stmt = insert(TaskAssignmentRead).values(
        company_id=company_id, user_id=user_id, task_id=task_id,
        assignment_revision=revision,
    )
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["company_id", "user_id", "task_id"],
        set_={"assignment_revision": revision, "seen_at": func.now()},
    ))
    db.sync_session.info.setdefault(_SIGNAL_KEY, set()).add((company_id, user_id))
    return True


# Один post-commit сигнал для всех ORM-источников поручения, включая процесс,
# документ, чат и повторение. Событие содержит только команду перечитать агрегат.
_pending_deliveries: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)
_SIGNAL_KEY = "task_assignment_refresh"


@event.listens_for(Session, "before_flush")
def _collect_refresh(session, flush_context, instances):
    people = session.info.setdefault(_SIGNAL_KEY, set())
    for task in session.new | session.dirty | session.deleted:
        if not isinstance(task, Task):
            continue
        state = inspect(task)
        if task not in session.new and task not in session.deleted and not any(
            state.attrs[key].history.has_changes()
            for key in ("assignee_id", "status", "due_at", "waiting_for", "visibility")
        ):
            continue
        ids = {task.assignee_id, *state.attrs.assignee_id.history.deleted}
        people.update((task.company_id, person) for person in ids if person)


async def _deliver_refresh(people):
    from app.services.chat_ws import manager

    for company_id, user_id in people:
        try:
            await manager.broadcast(f"user:{user_id}", {
                "type": "task:assignments-changed", "companyId": str(company_id),
            })
        except Exception:
            _logger.exception("Не удалось обновить счётчик поручений")


@event.listens_for(Session, "after_commit")
def _send_refresh(session):
    # RELEASE SAVEPOINT — ещё не коммит внешней транзакции.
    if session.in_nested_transaction():
        return
    people = session.info.pop(_SIGNAL_KEY, set())
    if people:
        task = asyncio.get_running_loop().create_task(_deliver_refresh(people))
        _pending_deliveries.add(task)
        task.add_done_callback(_pending_deliveries.discard)


@event.listens_for(Session, "after_soft_rollback")
def _discard_refresh(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_SIGNAL_KEY, None)
