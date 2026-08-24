"""Документ как активность процесса: маршрут запускает шаблон и ждёт исхода.

Третья просьба того же рода, что круг виз (`approval_requests`) и поручение
(`errands`). Разница в предмете: там маршрут просил собрать визы по уже
существующему документу или сделать работу, здесь — **завести документ по
заготовке**. До сих пор это оставалось дырой: узел маршрута мог попросить
согласовать документ, но взять его было неоткуда — кто-то должен был создать
документ руками и вовремя.

Ради чего это нужно. Проект строительства проходит ключевые точки, в каждой из
которых полагаются свои бумаги: акт выбора площадки, согласование ТУ, приёмка
работ. Часть из них обязательна — без подписанного акта дальше идти нельзя;
часть заводится «на всякий случай» и хода не держит. Маршрут знает, где какая, и
теперь может сказать это вслух.

**Обязательность выражается глаголом возврата, а не отдельным флагом.** Задан
`on_approved` — процесс ждёт исхода и без него дальше не пойдёт. Не задан —
документ заведён, процесс идёт своей дорогой. Это не экономия на поле: флаг
«обязательно» пришлось бы держать согласованным с наличием ребра, по которому
процесс двинется, и первое же расхождение дало бы либо вечное ожидание, либо
молча пропущенное согласование.

Документ связывается с предметом процесса типизированной ссылкой — по ней
собирается срез «что по этому проекту запущено и чего ждём».
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, DocRelation, TaskTemplate
from app.services import process_templates
from app.services.errands import service_actor

log = logging.getLogger("clearledger.documents")


class DocumentRequestError(ValueError):
    """Просьбу выполнить нельзя, и повтор доставки этого не изменит."""


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _template(db: AsyncSession, company_id: uuid.UUID,
                    data: dict[str, Any]) -> TaskTemplate:
    """Заготовка документа: по идентификатору или по имени.

    Имя допускается по той же причине, что и у поручений: маршруты пишут люди, а
    идентификатор заготовки при пересборке пространства меняется — имя остаётся.

    Заготовка обязана быть документной (`doc_kind_id`). Иначе маршрут просил бы
    документ, а получал поручение — и разница вскрылась бы через неделю, когда
    подписывать оказалось бы нечего.
    """
    raw_id = _uuid_or_none(data.get("template_id") or data.get("templateId"))
    if raw_id is not None:
        tpl = await db.get(TaskTemplate, raw_id)
        if tpl is not None and tpl.company_id == company_id and tpl.doc_kind_id:
            return tpl
        raise DocumentRequestError("Заготовка документа не найдена")

    name = str(data.get("template") or data.get("templateName") or "").strip()
    if not name:
        raise DocumentRequestError("В просьбе не названа заготовка документа")
    tpl = (await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == company_id,
        TaskTemplate.name == name,
        TaskTemplate.doc_kind_id.is_not(None)))).scalars().first()
    # Условие «документная» стоит и в отборе, и здесь. Не перестраховка: отбор
    # отвечает за то, что мы не возьмём чужую заготовку, а эта проверка — за то,
    # что отказ прозвучит здесь и по делу. Без неё поручение, найденное по имени,
    # дошло бы до запуска документа и упало там с посторонней причиной.
    if tpl is None or not tpl.doc_kind_id:
        raise DocumentRequestError(f"Заготовка документа «{name}» не найдена")
    return tpl


async def request(db: AsyncSession, company_id: uuid.UUID, request_id: str,
                  data: dict[str, Any]) -> ApprovalRequest:
    """Завести документ по заготовке и запомнить, ждёт ли процесс его исхода."""
    process_id = (data.get("process_id") or data.get("processId")
                  or data.get("ticket_id"))
    if not process_id:
        raise DocumentRequestError("В просьбе не указан процесс")

    template = await _template(db, company_id, data)
    actor = await service_actor(db, company_id)
    subject_ref = str(data.get("subject_ref") or data.get("subjectRef") or "").strip()
    object_id = data.get("object_id") or data.get("objectId") or None

    doc, result = await process_templates.launch(
        db, company_id, template, actor,
        object_id=(str(object_id) if object_id else None),
        subject_ref=subject_ref[:120] or None,
        source="api",
        source_ref=str(process_id),
        # Тем же правилом, что и у поручения: заведённое с рабочего места не
        # должно числиться запрошенным маршрутом.
        source_note=(str(data.get("source_note") or data.get("sourceNote") or "").strip()[:200]
                     or f"запрошен маршрутом (процесс {process_id})"),
    )

    # Связь с предметом процесса. Без неё документ существует, но из проекта его
    # не видно: срез «что по проекту идёт» строится именно по этой ссылке, а
    # `source_ref` — строка, по которой не пройти.
    if subject_ref:
        db.add(DocRelation(
            company_id=company_id, doc_id=doc.id, kind="basis",
            target_ref=subject_ref[:200]))

    row = ApprovalRequest(
        company_id=company_id,
        request_id=str(request_id)[:120],
        kind="document",
        process_id=str(process_id)[:64],
        branch_id=(str(data.get("branch_id") or data.get("branchId"))[:64]
                   if data.get("branch_id") or data.get("branchId") else None),
        doc_id=doc.id,
        round=result.get("round") or 0,
        # Глагол возврата и есть признак обязательности: задан — процесс ждёт
        # исхода, не задан — документ заведён, а маршрут идёт дальше сам.
        on_approved=(data.get("on_approved") or data.get("onApproved")
                     or "").strip()[:120] or None,
        on_rejected=(data.get("on_rejected") or data.get("onRejected")
                     or "").strip()[:120] or None,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Повторная доставка той же просьбы — штатный режим at-least-once, а не
        # ошибка отправителя. Документ при этом уже заведён первой попыткой.
        await db.rollback()
        raise DocumentRequestError(
            "Документ по этой просьбе уже заведён") from exc
    log.info("документ %s заведён по просьбе процесса %s (%s)",
             doc.id, process_id, "ждём исход" if row.on_approved else "без ожидания")
    return row
