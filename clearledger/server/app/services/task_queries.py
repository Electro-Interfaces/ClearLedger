"""Пакетная проекция имён и популяция общих списков задач.

Вход names уже отобран caller по tenant/ACL. not_personal — отбор популяции,
не право чтения: неизвестную видимость и чужую компанию закрывает caller ACL.
Порядок и число пакетных запросов сохранены, flush/commit здесь нет.
"""
from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (ServiceLocation, Task, TaskProject, TaskSprint, TaskType,
                        TaskVersion, User)
from app.services import task_routes


async def names(db: AsyncSession, tasks: list[Task], *, route_resolver=None) -> dict[uuid.UUID, dict[str, str | None]]:
    """Имена типов, людей и объектов пачкой: список задач не должен ходить в базу
    построчно."""
    route_resolver = route_resolver if route_resolver is not None else task_routes.route_of
    type_ids = {t.type_id for t in tasks if t.type_id}
    user_ids = {i for t in tasks for i in (t.assignee_id, t.author_id) if i}
    obj_ids = {t.object_id for t in tasks if t.object_id}
    prj_ids = {t.project_id for t in tasks if t.project_id}
    ver_ids = {i for t in tasks for i in (t.fix_version_id, t.found_version_id) if i}
    spr_ids = {t.sprint_id for t in tasks if t.sprint_id}
    prjs = {r.id: r for r in (await db.execute(
        select(TaskProject).where(TaskProject.id.in_(prj_ids)))).scalars()} if prj_ids else {}
    vers = {r.id: r.name for r in (await db.execute(
        select(TaskVersion).where(TaskVersion.id.in_(ver_ids)))).scalars()} if ver_ids else {}
    sprs = {r.id: r.name for r in (await db.execute(
        select(TaskSprint).where(TaskSprint.id.in_(spr_ids)))).scalars()} if spr_ids else {}
    types = {r.id: r for r in (await db.execute(
        select(TaskType).where(TaskType.id.in_(type_ids)))).scalars()} if type_ids else {}
    users = {r.id: r.name for r in (await db.execute(
        select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    objs = {r.id: r.name for r in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.id.in_(obj_ids)))).scalars()} if obj_ids else {}
    return {t.id: {
        "type": types[t.type_id].name if t.type_id in types else None,
        "route": route_resolver(types.get(t.type_id)),
        "assignee": users.get(t.assignee_id),
        "author": users.get(t.author_id),
        "object": objs.get(t.object_id),
        "project": prjs[t.project_id].name if t.project_id in prjs else None,
        "project_code": prjs[t.project_id].code if t.project_id in prjs else None,
        "fix_version": vers.get(t.fix_version_id),
        "found_version": vers.get(t.found_version_id),
        "sprint": sprs.get(t.sprint_id),
    } for t in tasks}


def not_personal():
    """Отбор для общих списков: личные записи в работу компании не входят.

    Права и отбор — разные вещи. Автор своё личное видеть вправе (`_visible_to`),
    но в ленте компании, на доске и в счётчиках ему это не нужно: там он смотрит
    на работу, а не на свою записную книжку. Без этого условия личные заметки
    тихо затопили бы общие списки — это главный способ провалить личный раздел.
    """
    return Task.visibility != "personal"
