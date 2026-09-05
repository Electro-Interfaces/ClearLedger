"""Срез документооборота процесса: что запущено, чем кончилось, чего ждём.

ЗАЧЕМ. Проект строительства проходит ключевые точки, и в каждой полагаются свои
бумаги: акт выбора площадки, согласование технических условий, приёмка работ.
Маршрут умеет их запускать, «Трек» умеет их вести — но из карточки проекта не
было видно ничего: ни что уже запущено, ни на чём стоим, ни чего ещё ждать.
Человек открывал два приложения и складывал картину в голове.

Здесь она складывается за него. Источник — просьбы маршрута: каждая помнит свой
процесс, свой документ и то, ждёт ли маршрут исхода.

**Ожидание отличается от необязательности.** Просьба с глаголом возврата держит
процесс: пока документ не согласован, дальше он не пойдёт. Просьба без глагола
заведена «к сведению» — документ живёт своей жизнью, маршрут своей. В срезе это
разные строки, и путать их нельзя: первая отвечает на вопрос «почему стоим»,
вторая — «что ещё делается».
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, DocCard, DocKind

# Как читается состояние документа в срезе. Отдельный словарь, а не показ
# внутреннего кода: в карточке проекта человек ждёт слов о согласовании, а не
# состояний нашей таблицы.
_APPROVAL_STATE = {
    "approved": "согласован",
    "rejected": "отклонён",
    "pending": "на согласовании",
    "none": "без согласования",
}


def _state(doc: DocCard | None, row: ApprovalRequest) -> str:
    if row.outcome == "rejected":
        return "отклонён"
    if row.outcome in ("approved", "done"):
        return "согласован"
    if row.outcome == "cancelled":
        return "снят"
    if doc is None:
        return "документ удалён"
    return _APPROVAL_STATE.get(doc.approval_status or "none", "в работе")


async def listing(db: AsyncSession, company_id: uuid.UUID,
                  process_id: str, *, user=None) -> dict[str, Any]:
    """Документы, запущенные маршрутом этого процесса.

    Порядок — по времени просьбы: срез читают сверху вниз как ход работы, а не
    как справочник.
    """
    rows = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.company_id == company_id,
        ApprovalRequest.process_id == str(process_id),
        ApprovalRequest.kind.in_(("document", "approval"))).order_by(
            ApprovalRequest.created_at))).scalars().all()

    doc_ids = {row.doc_id for row in rows if row.doc_id}
    docs: dict[uuid.UUID, DocCard] = {}
    kinds: dict[uuid.UUID, str] = {}
    if doc_ids:
        conditions = [DocCard.company_id == company_id, DocCard.id.in_(doc_ids)]
        if user is not None:
            from app.routers.docs_router import _readable_doc_clause
            conditions.append(await _readable_doc_clause(db, company_id, user))
        found = (await db.execute(select(DocCard).where(*conditions))).scalars().all()
        docs = {doc.id: doc for doc in found}
        kind_rows = (await db.execute(select(DocKind.id, DocKind.name).where(
            DocKind.company_id == company_id))).all()
        kinds = {key: value for key, value in kind_rows}

    items: list[dict[str, Any]] = []
    blocking = 0
    for row in rows:
        if user is not None and row.doc_id not in docs:
            continue
        doc = docs.get(row.doc_id) if row.doc_id else None
        # Маршрут ждёт исхода — значит эта бумага держит ход работы. Отличаем
        # «ждём» от «ждали»: закрытая просьба уже никого не держит.
        holds = bool(row.on_approved) and row.outcome is None
        if holds:
            blocking += 1
        items.append({
            "request_id": row.request_id,
            "doc_id": str(row.doc_id) if row.doc_id else None,
            "kind": kinds.get(doc.kind_id) if doc else None,
            "title": doc.title if doc else None,
            "reg_number": doc.reg_number if doc else None,
            "state": _state(doc, row),
            "required": bool(row.on_approved),
            "holds_process": holds,
            "round": row.round or None,
            "requested_at": row.created_at.isoformat() if row.created_at else None,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        })
    return {
        "process_id": str(process_id),
        "documents": items,
        "count": len(items),
        # Одно число, ради которого срез и открывают: сколько бумаг держит работу
        # прямо сейчас.
        "blocking": blocking,
    }
