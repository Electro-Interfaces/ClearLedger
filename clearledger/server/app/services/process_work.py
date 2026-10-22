"""Работа «Трека», заведённая процессом заявки, — одно место сборки.

Просьба процесса («соберите визы», «заведите документ», «сделайте поручение»)
живёт в `eco_approval_requests`, а её предмет — в карточке документа или в
поручении. Собрать из этих трёх таблиц одну строку витрины можно было в любом
месте, и до сих пор это делалось прямо в маршрутах: `/api/eco/process/{id}/work`
собирал строку для одной заявки, `/api/eco/work` — для всего контура. Второй
сборщик понадобился бы сводке клиента (кластер R11), и три копии разошлись бы на
первой же правке состояния.

Здесь сборка одна, и отсюда же берётся **состояние доставки исхода**. Для
оператора КЦ это отдельный вопрос разговора: решение по работе может быть
принято, но процесс о нём ещё не знает — `eco_approval_requests` хранит и то, и
другое (`outcome`/`decided_at` против `delivered_at`/`attempts`/`last_error`), а
витрина до сих пор отдавала только первое.

Текст ошибки доставки наружу не уходит: в нём бывает адрес внутреннего узла и
ответ чужого сервиса. Признак `error` — булев, как в `project_work.listing`.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, DocAcquaint, DocCard, Task

# Состояния предметов «Трека» словами, а не кодами: витрину читает человек в
# карточке заявки, и «Ждём виз» ему говорит больше, чем `pending`.
DOC_STATE = {
    "draft": "Черновик", "registered": "Зарегистрирован", "in_force": "Действует",
    "executed": "Исполнен", "archived": "В архиве", "cancelled": "Отменён",
}
TASK_STATE = {"open": "В работе", "done": "Выполнено", "cancelled": "Отменено"}
KIND_NAME = {
    "approval": "Согласование", "document": "Документ",
    "errand": "Поручение", "acquaint": "Ознакомление",
}
# Исходы, означающие «работа сделана». Остальные — отказ или отмена.
DONE_OUTCOMES = ("approved", "done")


def delivery_state(row: ApprovalRequest) -> str:
    """Где сейчас исход работы на пути к процессу.

    Словарь тот же, что у карточки оператора в Поддержке
    (`scripts/lib/operator-answers.js`, `SYNC_WORD`), чтобы обе стороны
    подписывали одно состояние одним словом:

    * `accepted` — работа заведена, решения по ней ещё нет;
    * `pending`  — решение есть, исход едет в процесс;
    * `applied`  — исход доставлен, процесс его принял;
    * `error`    — доставка не удалась;
    * `none`     — процесс исхода не ждёт (глагола нет ни на один исход),
      доставлять нечего: исход только фиксируется в карточке предмета.

    Глагола два — `on_approved` и `on_rejected`, — и смотреть надо на оба:
    маршрут, который двигает процесс только при отказе, исход всё равно
    доставляет (`approval_requests._deliver`).
    """
    from app.services.approval_requests import MAX_ATTEMPTS

    if not (row.on_approved or row.on_rejected):
        return "none"
    if row.outcome is None:
        return "accepted"
    if row.delivered_at is not None:
        return "applied"
    if row.last_error or row.attempts >= MAX_ATTEMPTS:
        return "error"
    return "pending"


async def requests_by_process(
    db: AsyncSession, company_id: uuid.UUID, process_ids,
) -> dict[str, list[ApprovalRequest]]:
    """Просьбы процессов по их идентификаторам, в порядке появления."""
    keys = [str(p)[:64] for p in dict.fromkeys(process_ids) if p]
    if not keys:
        return {}
    rows = (await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.company_id == company_id,
               ApprovalRequest.process_id.in_(keys))
        .order_by(ApprovalRequest.created_at)
    )).scalars().all()
    out: dict[str, list[ApprovalRequest]] = {}
    for row in rows:
        out.setdefault(row.process_id, []).append(row)
    return out


async def items_by_process(
    db: AsyncSession, company_id: uuid.UUID, process_ids,
) -> dict[str, list[dict[str, Any]]]:
    """Строки витрины по каждому процессу: что заведено и в каком оно состоянии."""
    by_process = await requests_by_process(db, company_id, process_ids)
    if not by_process:
        return {}
    rows = [row for group in by_process.values() for row in group]

    from app.config import get_settings

    base = get_settings().app_public_url.rstrip("/")
    doc_ids = {row.doc_id for row in rows if row.doc_id}
    task_ids = {row.task_id for row in rows if row.task_id}
    docs = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.id.in_(doc_ids)))).scalars().all()} if doc_ids else {}
    tasks = {t.id: t for t in (await db.execute(select(Task).where(
        Task.id.in_(task_ids)))).scalars().all()} if task_ids else {}

    # Лист ознакомления считаем одним запросом на все документы просьбы: по
    # одному на строку витрина стоила бы столько же, сколько сама заявка.
    sheets: dict[uuid.UUID, dict[str, int]] = {}
    if any(row.kind == "acquaint" for row in rows) and doc_ids:
        counted = (await db.execute(
            select(DocAcquaint.doc_id, DocAcquaint.status, func.count(DocAcquaint.id))
            .where(DocAcquaint.doc_id.in_(doc_ids))
            .group_by(DocAcquaint.doc_id, DocAcquaint.status))).all()
        for doc_id, state, count in counted:
            entry = sheets.setdefault(doc_id, {"done": 0, "total": 0})
            entry["total"] += int(count)
            if state == "done":
                entry["done"] += int(count)

    out: dict[str, list[dict[str, Any]]] = {}
    for process_id, group in by_process.items():
        out[process_id] = [_item(row, docs, tasks, sheets, base) for row in group]
    return out


def _item(row: ApprovalRequest, docs, tasks, sheets, base: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": str(row.id),
        "kind": row.kind,
        "kind_name": KIND_NAME.get(row.kind, row.kind),
        "requested_at": row.created_at.isoformat() if row.created_at else None,
        "outcome": row.outcome,
        "waits": bool(row.on_approved) and row.outcome is None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        # Доставка исхода — отдельный от исхода факт: решение может быть принято,
        # а процесс о нём ещё не знать.
        "delivery": {
            "state": delivery_state(row),
            "awaited": bool(row.on_approved or row.on_rejected),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "attempts": int(row.attempts or 0),
            "error": bool(row.last_error),
        },
    }
    doc = docs.get(row.doc_id) if row.doc_id else None
    task = tasks.get(row.task_id) if row.task_id else None
    if doc is not None:
        item.update({
            "subject": "document",
            "number": doc.reg_number or None,
            "title": doc.title,
            "state": DOC_STATE.get(doc.status, doc.status),
            "url": f"{base}/docs?view=all&doc={doc.id}",
        })
        if row.kind == "acquaint":
            sheet = sheets.get(doc.id, {"done": 0, "total": row.round})
            item["state"] = f"Ознакомились {sheet['done']} из {sheet['total']}"
    elif task is not None:
        item.update({
            "subject": "task",
            "number": f"№{task.number}",
            "title": task.title,
            "state": TASK_STATE.get(task.status, task.status),
            "url": f"{base}/docs/company?view=errands&task={task.id}",
        })
    else:
        # Предмет исчез (документ удалён, компания пересобрана) — строку
        # всё равно показываем: сам факт просьбы это история процесса.
        item.update({"subject": None, "title": "Предмет недоступен",
                     "state": None, "url": None})
    return item
