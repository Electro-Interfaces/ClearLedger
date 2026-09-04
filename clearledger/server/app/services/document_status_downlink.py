"""Досыл станции бухгалтерского статуса её СОБСТВЕННЫХ документов (source=edge).

Этап B двусторонней синхронизации (docs/sync-dokumentov-centr-agent.html). Факт
документа принадлежит станции и едет вверх; бухгалтерский статус этого документа
ставит центр (бухгалтер принял / вернул / отправил в бухгалтерию) — и он обязан
доехать обратно на станцию, иначе агент показывает «статус центра недоступен» и
администратор не знает, что с его документом стало в учёте.

Это read-only слой поверх факта: статус не трогает строки документа станции.
"""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Статусы, которые станции интересны: всё, кроме «pending» (ждёт выгрузки — это
# станция и так знает). needs_review — учёт вернул, ready/accepted — принят,
# rejected/blocked — не принят. Плюс отдельно признак «требует внимания».
_ИНТЕРЕСНЫЕ = ("needs_review", "ready", "accepted", "rejected", "blocked")


async def queue_document_status(
    session: AsyncSession, company_id: uuid.UUID, station_id: int,
) -> int:
    """Положить станции снимок бух-статусов её edge-документов. Возвращает число
    документов в снимке.

    Идемпотентно: несёт полный снимок (не «изменилось X»), прежнее невыданное
    задание того же вида снимаем — станции нужна последняя картина, а не история.
    """
    from ..models import EdgeDownlink
    from ..models import StoreDocMeta as M
    from ..models import StoreDocumentProjection as P

    # Бух-надстройка (Этап C) едет тем же снимком, что и статус (Этап B): один
    # слой «как в бухгалтерии» = статус готовности + реквизиты, дописанные
    # бухгалтером (ответственные, рег-номер, примечание). Документ попадает в
    # снимок, если центр что-то с ним сделал: не-pending статус, внимание или
    # заполненная надстройка.
    строки = (await session.execute(
        select(
            P.document_id, P.document_kind, P.number,
            P.accounting_status, P.requires_attention, P.rebuilt_at,
            M.reg_number, M.registered_at, M.responsible_from, M.responsible_to,
            M.note, M.status.label("meta_status"),
        )
        .select_from(P)
        .outerjoin(M, (M.record_id == P.id) & (M.company_id == P.company_id))
        .where(
            P.company_id == company_id,
            P.is_primary.is_(True),
            P.projection_source == "edge",
            P.station_id == station_id,
            or_(
                P.accounting_status.in_(_ИНТЕРЕСНЫЕ),
                P.requires_attention.is_(True),
                M.reg_number.isnot(None),
                M.responsible_from.isnot(None),
                M.responsible_to.isnot(None),
                M.note.isnot(None),
            ),
        )
    )).all()

    items = [{
        "uuid": str(r.document_id),
        "kind": r.document_kind,
        "number": r.number,
        "accounting_status": r.accounting_status,
        "attention": bool(r.requires_attention),
        "at": r.rebuilt_at.isoformat() if r.rebuilt_at else None,
        # Бух-надстройка (Этап C) — реквизиты бухгалтера, read-only для станции.
        "reg_number": r.reg_number,
        "registered_at": r.registered_at.isoformat() if r.registered_at else None,
        "responsible_from": r.responsible_from,
        "responsible_to": r.responsible_to,
        "note": r.note,
        "meta_status": r.meta_status,
    } for r in строки]

    await session.execute(text("""
        DELETE FROM edge_downlink
         WHERE company_id = :c AND station_id = :s AND kind = 'document_status'
           AND delivered_at IS NULL AND acked_at IS NULL AND cancelled_at IS NULL
    """), {"c": str(company_id), "s": station_id})
    session.add(EdgeDownlink(
        company_id=company_id, station_id=station_id,
        kind="document_status", payload={"items": items},
    ))
    return len(items)
