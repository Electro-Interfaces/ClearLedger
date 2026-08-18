from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocAccessGrant, DocCard, DocEvent, DocKind, Task, TaskChecklistItem,
    TaskEvent, TaskTemplate, TaskType, User, UserCompany,
)
from app.services import doc_approvals, task_mail


class ProcessTemplateError(ValueError):
    pass


async def can_launch_kind(
    db: AsyncSession, cid: uuid.UUID, kind_id: uuid.UUID, user: User,
) -> bool:
    if user.is_superadmin:
        return True
    membership = await db.get(UserCompany, (user.id, cid))
    if membership is None:
        return False
    rows = list((await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        DocAccessGrant.scope_type == "kind",
        DocAccessGrant.scope_id == kind_id,
    ))).scalars())
    subjects = {
        "user": user.id,
        "role": membership.role_id,
        "department": membership.department_id,
    }
    matched = [row for row in rows
               if subjects.get(row.subject_type) == row.subject_id]
    if any({"read", "edit"}.intersection(row.denied_permissions or [])
           for row in matched):
        return False
    if membership.role == "admin":
        return True
    edit_rules = [row for row in rows
                  if "edit" in (row.permissions or [])]
    return not edit_rules or any(
        "edit" in (row.permissions or []) for row in matched)


def required_fields(kind: DocKind) -> list[str]:
    return [str(field.get("label") or field.get("code"))
            for field in (kind.fields or []) if field.get("required")]


def document_template_out(tpl: TaskTemplate, kind: DocKind) -> dict[str, Any]:
    missing = required_fields(kind)
    return {
        "id": str(tpl.id),
        "kind": "document",
        "name": tpl.name,
        "title": tpl.title,
        "description": tpl.description,
        "docKindId": str(kind.id),
        "docKindName": kind.name,
        "steps": len(doc_approvals.clean_route(kind.route or [])),
        "requiresPreparation": bool(kind.requires_registration or missing),
        "preparationReason": (
            "нужна регистрация документа" if kind.requires_registration
            else f"нужно заполнить: {', '.join(missing)}" if missing else None
        ),
        "defaultResponsibleId": str(tpl.assignee_id) if tpl.assignee_id else None,
        "dueDays": tpl.due_days,
    }


def _task_route(task_type: TaskType | None) -> list[dict[str, str]]:
    route = task_type.route if task_type and task_type.route else [
        {"code": "new", "name": "Постановка"},
        {"code": "in_progress", "name": "В работе"},
        {"code": "review", "name": "Проверка"},
    ]
    return [
        {"code": str(stage.get("code")), "name": str(stage.get("name"))}
        for stage in route
        if isinstance(stage, dict) and stage.get("code") and stage.get("name")
    ]


def task_template_out(tpl: TaskTemplate, task_type: TaskType | None) -> dict[str, Any]:
    route = _task_route(task_type)
    return {
        "id": str(tpl.id),
        "kind": "task",
        "name": tpl.name,
        "title": tpl.title,
        "description": tpl.description,
        "taskTypeId": str(task_type.id) if task_type else None,
        "taskTypeName": task_type.name if task_type else "Поручение",
        "steps": len(route),
        "requiresPreparation": False,
        "preparationReason": None,
        "defaultResponsibleId": str(tpl.assignee_id) if tpl.assignee_id else None,
        "dueDays": (tpl.due_days if tpl.due_days is not None
                    else task_type.due_days if task_type else None),
        "capabilities": ["assign", "transfer", "comments", "files"],
    }


async def available_templates(
    db: AsyncSession, cid: uuid.UUID, user: User,
) -> list[dict[str, Any]]:
    if await db.get(UserCompany, (user.id, cid)) is None and not user.is_superadmin:
        return []
    templates = list((await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == cid).order_by(TaskTemplate.name))).scalars())
    kind_ids = {tpl.doc_kind_id for tpl in templates if tpl.doc_kind_id}
    type_ids = {tpl.type_id for tpl in templates if tpl.type_id}
    kinds = {kind.id: kind for kind in (await db.execute(select(DocKind).where(
        DocKind.id.in_(kind_ids)))).scalars()} if kind_ids else {}
    types = {task_type.id: task_type for task_type in (await db.execute(
        select(TaskType).where(TaskType.id.in_(type_ids)))).scalars()} if type_ids else {}
    result: list[dict[str, Any]] = []
    for tpl in templates:
        if tpl.doc_kind_id:
            kind = kinds.get(tpl.doc_kind_id)
            if (kind is None or kind.company_id != cid or not kind.is_active
                    or not doc_approvals.clean_route(kind.route or [])):
                continue
            if await can_launch_kind(db, cid, kind.id, user):
                result.append(document_template_out(tpl, kind))
            continue
        task_type = types.get(tpl.type_id) if tpl.type_id else None
        if task_type is not None and (
                task_type.company_id != cid or not task_type.is_active):
            continue
        result.append(task_template_out(tpl, task_type))
    return result


async def launch_task(
    db: AsyncSession,
    cid: uuid.UUID,
    tpl: TaskTemplate,
    actor: User,
    *,
    responsible_id: uuid.UUID | None = None,
    title: str | None = None,
    source_ref: str | None = None,
    source_note: str | None = None,
    summary_suffix: str | None = None,
    object_id: str | None = None,
) -> tuple[Task, dict[str, Any]]:
    if tpl.company_id != cid or tpl.doc_kind_id:
        raise ProcessTemplateError("Шаблон процесса не найден")
    if await db.get(UserCompany, (actor.id, cid)) is None and not actor.is_superadmin:
        raise ProcessTemplateError("Недостаточно прав для запуска этого процесса")
    task_type = await db.get(TaskType, tpl.type_id) if tpl.type_id else None
    if task_type is not None and (
            task_type.company_id != cid or not task_type.is_active):
        raise ProcessTemplateError("Тип задачи шаблона недоступен")
    route = _task_route(task_type)
    if not route:
        raise ProcessTemplateError("У шаблона не задан маршрут процесса")

    responsible = responsible_id or tpl.assignee_id or actor.id
    if await db.get(UserCompany, (responsible, cid)) is None:
        raise ProcessTemplateError("Исполнитель не состоит в пространстве")
    person = await db.get(User, responsible)
    summary_parts = [part.strip() for part in (tpl.description, summary_suffix)
                     if part and part.strip()]
    days = (tpl.due_days if tpl.due_days is not None
            else task_type.due_days if task_type else None)
    now = datetime.now(timezone.utc)
    task = Task(
        company_id=cid,
        type_id=tpl.type_id,
        title=((title or tpl.title).strip() or tpl.title)[:300],
        description="\n\n".join(summary_parts) or None,
        priority=tpl.priority or (task_type.default_priority if task_type else "medium"),
        status="open",
        stage_code=route[0]["code"],
        assignee_id=responsible,
        author_id=actor.id,
        object_id=object_id or tpl.object_id,
        due_at=now + timedelta(days=days) if days is not None else None,
        visibility="company",
    )
    db.add(task)
    await db.flush()
    db.add(TaskEvent(
        task_id=task.id,
        kind="created",
        user_id=actor.id,
        actor_name=actor.name or actor.email,
        from_value=source_ref,
        to_value=route[0]["name"],
        note=source_note or f"по шаблону «{tpl.name}»",
    ))
    if person is not None:
        db.add(TaskEvent(
            task_id=task.id,
            kind="assign",
            user_id=actor.id,
            actor_name=actor.name or actor.email,
            to_value=person.name,
        ))
    for index, item in enumerate(tpl.checklist or []):
        text_item = str(item).strip()
        if text_item:
            db.add(TaskChecklistItem(
                task_id=task.id, text=text_item[:500], position=(index + 1) * 10))
    if person is not None and person.id != actor.id and person.email:
        task_mail.send_notice_async(
            [person.email], f"Вам поручена задача №{task.number}: {task.title}",
            f"Поручил: {actor.name or actor.email}\n\n{task.description or ''}".strip(),
        )
    return task, {
        "state": "task",
        "started": True,
        "steps": len(route),
        "stage": route[0]["name"],
        "reason": None,
    }


async def launch(
    db: AsyncSession,
    cid: uuid.UUID,
    tpl: TaskTemplate,
    actor: User,
    *,
    responsible_id: uuid.UUID | None = None,
    source: str = "api",
    source_ref: str | None = None,
    source_note: str | None = None,
    summary_suffix: str | None = None,
    object_id: str | None = None,
) -> tuple[DocCard, dict[str, Any]]:
    if tpl.company_id != cid or not tpl.doc_kind_id:
        raise ProcessTemplateError("Шаблон процесса не найден")
    kind = await db.get(DocKind, tpl.doc_kind_id)
    if kind is None or kind.company_id != cid or not kind.is_active:
        raise ProcessTemplateError("Вид документа шаблона недоступен")
    if not await can_launch_kind(db, cid, kind.id, actor):
        raise ProcessTemplateError("Недостаточно прав для запуска этого процесса")
    route = doc_approvals.clean_route(kind.route or [])
    if not route:
        raise ProcessTemplateError("У шаблона не задан маршрут процесса")

    responsible = responsible_id or tpl.assignee_id or actor.id
    if await db.get(UserCompany, (responsible, cid)) is None:
        raise ProcessTemplateError("Ответственный не состоит в пространстве")
    summary_parts = [part.strip() for part in (tpl.description, summary_suffix) if part and part.strip()]
    now = datetime.now(timezone.utc)
    d = DocCard(
        company_id=cid,
        kind_id=kind.id,
        kind_code=kind.code,
        family=kind.family,
        direction=kind.direction,
        title=tpl.title,
        summary="\n\n".join(summary_parts) or None,
        author_id=actor.id,
        responsible_id=responsible,
        object_id=object_id or tpl.object_id,
        source=source,
        source_ref=source_ref,
        due_at=(now + timedelta(days=tpl.due_days)
                if tpl.due_days is not None else None),
    )
    db.add(d)
    await db.flush()
    db.add(DocEvent(
        doc_id=d.id,
        kind="created",
        user_id=actor.id,
        actor_name=actor.name or actor.email,
        to_value=kind.name,
        note=source_note or f"по шаблону «{tpl.name}»",
    ))

    missing = required_fields(kind)
    if kind.requires_registration or missing:
        reason = (
            "Документ нужно зарегистрировать перед согласованием"
            if kind.requires_registration
            else f"Перед согласованием заполните: {', '.join(missing)}"
        )
        db.add(DocEvent(
            doc_id=d.id,
            kind="process",
            user_id=actor.id,
            actor_name=actor.name or actor.email,
            to_value="Подготовка",
            note=reason,
        ))
        return d, {
            "state": "preparation",
            "started": False,
            "steps": len(route),
            "reason": reason,
        }

    approval = await doc_approvals.start(db, cid, d, route, actor)
    if "error" in approval:
        raise ProcessTemplateError(str(approval["error"]))
    return d, {
        "state": "approval",
        "started": True,
        "steps": approval["steps"],
        "round": approval["round"],
        "approvals": approval["approvals"],
        "reason": None,
    }


def launch_out(d: DocCard, tpl: TaskTemplate, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "document",
        "docId": str(d.id),
        "title": d.title,
        "templateId": str(tpl.id),
        "templateName": tpl.name,
        **result,
    }


def task_launch_out(task: Task, tpl: TaskTemplate, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "task",
        "taskId": str(task.id),
        "taskNumber": task.number,
        "title": task.title,
        "templateId": str(tpl.id),
        "templateName": tpl.name,
        **result,
    }
