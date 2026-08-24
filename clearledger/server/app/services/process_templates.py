from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract, Counterparty, DocAccessGrant, DocCard, DocEvent, DocKind,
    Organization, ServiceLocation, Task, TaskChecklistItem, TaskEvent,
    TaskTemplate, TaskType, User, UserCompany,
)
from app.services import doc_approvals, task_mail, work_state


class ProcessTemplateError(ValueError):
    pass


# Подстановка данных пространства в заголовок и содержание шаблона. Скобки
# одинарные — те же, что в шаблоне номера (`doc_numbers.render`): человек,
# настроивший нумерацию, не должен учить второй синтаксис ради текста.
_SLOT = re.compile(r"\{([а-яёa-z_]{2,30})\}", re.IGNORECASE)


def fill(text: str | None, values: dict[str, str]) -> str | None:
    """Подставить значения в текст шаблона.

    Незаполненное имя остаётся в тексте как есть — ровно как в номере. Молча
    подставленная пустота даёт «Акт по договору  от », и замечают это уже у
    контрагента; оставшееся `{договор}` видно своему же человеку до отправки.
    """
    if not text:
        return text

    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1).lower())
        return value if value else match.group(0)

    return _SLOT.sub(replace, text)


async def compose_values(db: AsyncSession, cid: uuid.UUID, doc: DocCard,
                         actor: User) -> dict[str, str]:
    """Что доступно шаблону: реквизиты сторон, предмет, объект, дата.

    Берём только то, что уже стоит в карточке. Догадываться о договоре по
    названию или искать «похожего» контрагента нельзя: документ уходит наружу,
    и подставленная не та сторона хуже, чем незаполненное место.
    """
    today = datetime.now(timezone.utc).date()
    values: dict[str, str] = {
        "дата": today.strftime("%d.%m.%Y"),
        "год": str(today.year),
        "автор": actor.name or actor.email or "",
    }
    if doc.counterparty_id:
        name = await db.scalar(select(Counterparty.name).where(
            Counterparty.id == doc.counterparty_id,
            Counterparty.company_id == cid))
        values["контрагент"] = name or doc.counterparty_name or ""
    elif doc.counterparty_name:
        values["контрагент"] = doc.counterparty_name
    if doc.organization_id:
        values["организация"] = await db.scalar(select(Organization.name).where(
            Organization.id == doc.organization_id)) or ""
    if doc.object_id:
        values["объект"] = await db.scalar(select(ServiceLocation.name).where(
            ServiceLocation.id == doc.object_id,
            ServiceLocation.company_id == cid)) or ""
    if doc.subject_ref and doc.subject_ref.startswith("contract:"):
        try:
            contract_id = uuid.UUID(doc.subject_ref.split(":", 1)[1])
        except (ValueError, TypeError):
            contract_id = None
        if contract_id is not None:
            row = (await db.execute(select(Contract).where(
                Contract.id == contract_id,
                Contract.company_id == cid))).scalar_one_or_none()
            if row is not None:
                values["договор"] = row.number
                values["дата_договора"] = row.date or ""
                values["предмет"] = row.title or ""
    return values


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
    # Предмет работы — тот же механизм, что у документа. Из карточки проекта
    # это сам проект: объекта сети у площадки может ещё не быть.
    subject_ref: str | None = None,
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
        stage_column=work_state.stage_column_of(route, route[0]["code"]),
        assignee_id=responsible,
        author_id=actor.id,
        object_id=object_id or tpl.object_id,
        subject_ref=subject_ref,
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
    counterparty_id: uuid.UUID | None = None,
    subject_ref: str | None = None,
    # Связь «много к одному». По проекту документов десяток — договор аренды,
    # договор ТП, акт ввода; предметом их не привязать, он уникален на компанию
    # и описывает отношение один к одному («карточка ЭТОГО договора»).
    relate_to: str | None = None,
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
        counterparty_id=counterparty_id,
        subject_ref=subject_ref,
        source=source,
        source_ref=source_ref,
        due_at=(now + timedelta(days=tpl.due_days)
                if tpl.due_days is not None else None),
    )
    # Подстановку делаем после сборки карточки и до записи: значения берутся из
    # её же полей, а в базу должен попасть готовый текст, а не шаблон. Иначе
    # `{контрагент}` уедет в реестр, в поиск и в печатную форму.
    values = await compose_values(db, cid, d, actor)
    d.title = fill(d.title, values) or d.title
    d.summary = fill(d.summary, values)
    db.add(d)
    await db.flush()
    if relate_to:
        from app.models import DocRelation

        db.add(DocRelation(company_id=cid, doc_id=d.id, kind="basis",
                           target_ref=relate_to[:200]))
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
