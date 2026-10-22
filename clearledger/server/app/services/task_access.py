"""Единый круг чтения поручения и его файлов; членство/продукт проверяет caller."""
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product
from app.models import Task, TaskAttachment, TaskParticipant, TaskWatcher, User, UserCompany


async def is_admin(db: AsyncSession, cid: uuid.UUID, user: User) -> bool:
    if user.is_superadmin:
        return True
    member = await db.get(UserCompany, (user.id, cid))
    return member is not None and member.role == "admin"


def visible_to(user: User, admin: bool):
    """SQL-предикат: company — все, private — причастные/админ, personal — автор.

    Неизвестный уровень закрыт. Ограничение компании caller добавляет отдельно,
    включая join соседнего поручения: сама связь не переносит права между ними.
    """
    involved = or_(
        Task.author_id == user.id, Task.assignee_id == user.id,
        Task.id.in_(select(TaskWatcher.task_id).where(TaskWatcher.user_id == user.id)),
        Task.id.in_(select(TaskParticipant.task_id).where(TaskParticipant.user_id == user.id)))
    return or_(Task.visibility == "company",
               and_(Task.visibility == "private", True if admin else involved),
               and_(Task.visibility == "personal", Task.author_id == user.id))


async def can_view_task(db: AsyncSession, cid: uuid.UUID, user: User, task: Task) -> bool:
    """Одиночное чтение использует тот же SQL, что список и вложенные проекции."""
    if task.company_id != cid:
        return False
    return await db.scalar(select(Task.id).where(
        Task.id == task.id, Task.company_id == cid,
        visible_to(user, await is_admin(db, cid, user)))) is not None


async def assert_view_task(db: AsyncSession, cid: uuid.UUID, user: User, task: Task) -> None:
    if not await can_view_task(db, cid, user, task):
        raise HTTPException(404, "Задача не найдена")


async def assert_task_room(db: AsyncSession, room, user: User) -> None:
    """Старое участие в обсуждении не заменяет актуальное чтение поручения.

    Продукт комнаты и прочие права чата здесь не требуются: обсуждение открывают
    из карточки поручения с теми же docs/legacy plan, что и саму карточку.
    Членство комнаты проверяет caller отдельно.
    """
    if not room.is_active or room.company_id is None:
        raise HTTPException(404, "Чат не найден")
    task = await db.get(Task, room.scope_task_id)
    if task is None or not await can_view_task(db, room.company_id, user, task):
        raise HTTPException(404, "Чат не найден")
    try:
        await assert_company_product(str(room.company_id), user, db, "docs")
    except HTTPException:
        await assert_company_product(str(room.company_id), user, db, "plan")


async def authorize_task_file_download(db: AsyncSession, user: User, file_id: uuid.UUID,
                                       cid: uuid.UUID) -> None:
    """Task-only файл с несколькими привязками читается через любую доступную.

    Для файлов других продуктов без task-привязки эта проверка ничего не меняет.
    Остальные guards `/files` выполняются независимо, разрешение здесь их не отменяет.
    """
    bound = await db.scalar(select(TaskAttachment.id).where(
        TaskAttachment.file_id == file_id).limit(1))
    if bound is None:
        return
    allowed = await db.scalar(select(Task.id).join(
        TaskAttachment, TaskAttachment.task_id == Task.id).where(
        TaskAttachment.file_id == file_id, Task.company_id == cid,
        visible_to(user, await is_admin(db, cid, user))).limit(1))
    if allowed is None:
        raise HTTPException(404, "Файл не найден")
    try:
        await assert_company_product(str(cid), user, db, "docs")
    except HTTPException:
        await assert_company_product(str(cid), user, db, "plan")
