from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_module_access, get_current_user
from app.business_access import (
    ROLE_STATION_ADMINISTRATOR,
    SCOPE_STATION,
    has_network_merchandiser,
)
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    Company,
    CompanyRole,
    EdgePacket,
    SourceFile,
    StoreDocFile,
    StoreDocMeta,
    StoreDocumentProjection,
    StoreDocumentProjectionLine,
    StoreDocumentRelation,
    User,
    UserCompany,
)
from app.services import ops_terms
from app.services.store_document_contract import PROJECTION_DOCUMENT_KINDS
from app.services.store_documents import (
    normalized_document_payload,
    rebuild_store_document_projection,
    safe_document_detail,
)
from app.services.store_document_print import печатная_форма
from app.services.store_document_snapshot import queue_onec_document_snapshot


# Счётчик и фильтр обязаны быть одним выражением: иначе «не готовы к учёту: 12»
# и отобранные по этой кнопке 9 строк расходятся, и верить нельзя ни тому, ни
# другому.
COUNTER_CONDITIONS = {
    # чек и смена неучётные: их карантин не работа для человека, а свойство
    # кассовой ленты. Оставлять их в «требуют внимания» значит утопить в
    # шестистах чеках три накладные, из-за которых счётчик и заведён
    "attention": lambda: (
        StoreDocumentProjection.requires_attention.is_(True),
        StoreDocumentProjection.document_kind.not_in(("fiscal_receipt", "store_shift")),
    ),
    "missing_evidence": lambda: (
        StoreDocumentProjection.document_kind.in_(("purchase", "return_purchase")),
        StoreDocumentProjection.has_files.is_(False),
    ),
    # «pending» — не проблема, а нормальная жизнь документа до выгрузки: пока
    # бухгалтерский канал не запущен, в этом состоянии находится вообще всё.
    # Считая его непорядком, счётчик показывал 664 документа и требовал
    # разобрать то, что разбору не подлежит.
    "not_accounting_ready": lambda: (
        StoreDocumentProjection.document_kind.not_in(("fiscal_receipt", "store_shift")),
        StoreDocumentProjection.accounting_status.in_(
            ("needs_review", "rejected", "blocked")),
    ),
    "onec_mismatch": lambda: (
        StoreDocumentProjection.discrepancy_status.in_(
            ("minor", "material", "critical", "unmatched")),
    ),
}

FILE_ROLES = ("накладная", "упд", "акт", "опись", "фото", "прочее")
FILE_MIME_TYPES = (
    "application/pdf", "image/jpeg", "image/png", "image/webp",
)


async def _require_store_module(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    company_id = await scope_company_id(user, db)
    access = await resolve_document_access(user, db, company_id)
    if access.is_superadmin or access.is_accountant:
        return
    await check_module_access(user, company_id, db, "store")


router = APIRouter(
    prefix="/store/documents",
    tags=["Магазин: документы"],
    dependencies=[Depends(capture_company_header), Depends(_require_store_module)],
)


@dataclass(frozen=True)
class DocumentAccess:
    company_id: uuid.UUID
    is_superadmin: bool
    is_merchandiser: bool
    is_accountant: bool
    station_ids: frozenset[int]

    @property
    def network(self) -> bool:
        return self.is_superadmin or self.is_merchandiser or self.is_accountant

    @property
    def can_raw(self) -> bool:
        return self.is_superadmin or self.is_accountant


async def resolve_document_access(
    user: User, db: AsyncSession, company_id: uuid.UUID | None = None,
) -> DocumentAccess:
    company_id = company_id or await scope_company_id(user, db)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    membership = await db.get(UserCompany, (user.id, company_id))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    station_ids = set()
    for grant in grants:
        if (str((grant or {}).get("role")) != ROLE_STATION_ADMINISTRATOR
                or str((grant or {}).get("scope_type")) != SCOPE_STATION):
            continue
        try:
            station_ids.add(int(grant.get("scope_id")))
        except (TypeError, ValueError):
            continue
    merchandiser = has_network_merchandiser(grants, company.slug)
    accountant = False
    if membership is not None and membership.role_id is not None:
        role = await db.get(CompanyRole, membership.role_id)
        accountant = bool(role and role.name.casefold() == "бухгалтер")
    access = DocumentAccess(
        company_id, bool(user.is_superadmin), merchandiser, accountant,
        frozenset(station_ids),
    )
    if not access.network and not access.station_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к документам магазина")
    return access


def _station_allowed(access: DocumentAccess, station_id: int | None) -> bool:
    if station_id is None:
        return access.network
    return access.network or station_id in access.station_ids


def _file_write_allowed(
    access: DocumentAccess, station_id: int | None, document_kind: str | None = None,
) -> bool:
    if document_kind in {"fiscal_receipt", "store_shift"}:
        return False
    if access.is_superadmin or access.is_merchandiser:
        return True
    return station_id is not None and station_id in access.station_ids


async def _projection(
    db: AsyncSession, access: DocumentAccess, record_id: uuid.UUID,
) -> StoreDocumentProjection:
    row = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.id == record_id,
        StoreDocumentProjection.company_id == access.company_id,
    ))).scalar_one_or_none()
    if row is None or not _station_allowed(access, row.station_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return row


def _brief(row: StoreDocumentProjection) -> dict:
    return {
        "record_id": str(row.id), "document_id": str(row.document_id),
        "kind": row.document_kind, "source": row.source_kind,
        "projection_source": row.projection_source,
        "document_role": row.document_role,
        "accounting_group_id": str(row.accounting_group_id) if row.accounting_group_id else None,
        "shift_no": row.shift_no,
        "station_id": row.station_id, "number": row.number,
        "document_at": row.document_at, "counterparty": row.counterparty_name,
        "counterparty_inn": row.counterparty_inn,
        "amount": float(row.amount or 0),
        "vat_amount": None if row.vat_amount is None else float(row.vat_amount),
        "operational_status": row.operational_status, "sync_status": row.sync_status,
        "accounting_status": row.accounting_status,
        "discrepancy_status": row.discrepancy_status,
        "requires_attention": row.requires_attention,
        "has_files": row.has_files, "has_fuel": row.has_fuel,
        "revision": row.revision,
    }


def _legacy_doc_ref(row: StoreDocumentProjection) -> str | None:
    if row.source_kind == "receipt":
        return f"receipt:{row.source_record_id}"
    if row.source_kind == "edge_document":
        return f"station:{row.source_record_id}"
    return None


async def _file_projection(
    db: AsyncSession, company_id: uuid.UUID, row: StoreDocFile,
) -> StoreDocumentProjection | None:
    if row.record_id is not None:
        return (await db.execute(select(StoreDocumentProjection).where(
            StoreDocumentProjection.company_id == company_id,
            StoreDocumentProjection.id == row.record_id,
        ))).scalar_one_or_none()
    if row.doc_ref.startswith("receipt:"):
        source_kind = "receipt"
        source_record_id = row.doc_ref.removeprefix("receipt:")
    elif row.doc_ref.startswith("station:"):
        source_kind = "edge_document"
        source_record_id = row.doc_ref.removeprefix("station:")
    else:
        return None
    return (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == company_id,
        StoreDocumentProjection.source_kind == source_kind,
        StoreDocumentProjection.source_record_id == source_record_id,
    ))).scalar_one_or_none()


async def authorize_legacy_document_ref(
    db: AsyncSession, user: User, company_id: uuid.UUID, doc_ref: str, *, write: bool,
) -> tuple[DocumentAccess, StoreDocumentProjection | None]:
    access = await resolve_document_access(user, db, company_id)
    probe = SimpleNamespace(record_id=None, doc_ref=doc_ref)
    document = await _file_projection(db, company_id, probe)
    if document is None:
        if not access.network:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
        if write and not (access.is_superadmin or access.is_merchandiser):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
        return access, None
    await _projection(db, access, document.id)
    if write and not _file_write_allowed(
            access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    return access, document


@router.post("/rebuild")
async def rebuild_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    if not (access.is_superadmin or access.is_merchandiser):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Пересборка доступна товароведу сети")
    result = await rebuild_store_document_projection(db, access.company_id)
    await db.commit()
    return result


@router.get("/triage")
async def documents_triage(
    stations: str | None = Query(None, description="Коды АЗС через запятую"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Очереди работы: что разобрать и почему, а не сколько всего документов.

    Счётчик «54 требуют внимания» говорит, что работа есть, но не говорит,
    какая. Здесь каждая очередь названа своей причиной и своей суммой: поставка
    без накладной — это риск для вычета НДС, а смена с оценочной себестоимостью
    просто не уйдёт в бухгалтерию.
    """
    access = await resolve_document_access(user, db)
    базовые = [
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.document_kind.in_(PROJECTION_DOCUMENT_KINDS),
    ]
    if stations:
        коды = [value.strip() for value in stations.split(",") if value.strip()]
        if any(not value.isdigit() for value in коды):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Коды АЗС должны быть целыми числами")
        базовые.append(StoreDocumentProjection.station_id.in_([int(v) for v in коды]))
    if not access.network and access.station_ids:
        базовые.append(StoreDocumentProjection.station_id.in_(sorted(access.station_ids)))
    if date_from is not None:
        базовые.append(StoreDocumentProjection.document_at >= datetime.combine(
            date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        базовые.append(StoreDocumentProjection.document_at < datetime.combine(
            date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    ОЧЕРЕДИ = (
        ("waiting_receipt", "Поставки ждут приёмки",
         "Товар привезли, но приёмка не проведена — остаток и себестоимость станции неверны",
         "Открыть и принять", (
             StoreDocumentProjection.document_kind == "purchase",
             # «in_baseline» сюда не берём: этот приход уже внутри стартового
             # остатка, и звать человека принять его — звать задвоить товар.
             StoreDocumentProjection.operational_status.in_(("expected", "draft")),
         )),
        ("missing_evidence", "Поставки без накладной",
         "К документу не приложен файл-подтверждение: без него бухгалтерия не примет вычет НДС",
         "Приложить накладную или УПД", COUNTER_CONDITIONS["missing_evidence"]()),
        ("attention", "Документы с ошибкой разбора",
         "Станция прислала документ, который не разобрался до конца",
         "Открыть и разобрать причину", COUNTER_CONDITIONS["attention"]()),
        ("onec_mismatch", "Расхождения с 1С",
         "Наш документ и документ 1С не сошлись",
         "Сверить построчно", COUNTER_CONDITIONS["onec_mismatch"]()),
        ("not_accounting_ready", "Учёт вернул документ",
         "Бухгалтерия не приняла документ или он ждёт решения по реквизитам",
         "Проверить реквизиты и статус", COUNTER_CONDITIONS["not_accounting_ready"]()),
    )

    очереди: list[dict] = []
    for код, заголовок, причина, действие, условия in ОЧЕРЕДИ:
        строка = (await db.execute(select(
            func.count().label("шт"),
            func.coalesce(func.sum(StoreDocumentProjection.amount), 0).label("сумма"),
            func.min(StoreDocumentProjection.document_at).label("самый_старый"),
        ).where(*базовые, *условия))).one()
        if not строка.шт:
            continue
        очереди.append({
            "code": код, "title": заголовок, "reason": причина, "action": действие,
            "count": int(строка.шт), "amount": float(строка.сумма or 0),
            "oldest_at": строка.самый_старый.isoformat() if строка.самый_старый else None,
        })

    # Смены — отдельная очередь, и берём её по светофору, который поставила
    # станция, а не по признаку «требует внимания» у ОРП. Последний стоит почти
    # у каждой смены: две одинаковых позиции в чеке дают строки без своего
    # ключа, и для розницы это норма. Такая очередь показывала бы 142 смены из
    # 145 и не значила бы ничего.
    смены_условия = [
        EdgePacket.company_id == access.company_id,
        EdgePacket.kind == "shift",
        EdgePacket.shift_internal_no.isnot(None),
        EdgePacket.payload["ShiftCompleteness"]["status"].astext == "needs_review",
    ]
    if stations:
        смены_условия.append(EdgePacket.station_id.in_(
            [int(v.strip()) for v in stations.split(",") if v.strip()]))
    if not access.network and access.station_ids:
        смены_условия.append(EdgePacket.station_id.in_(sorted(access.station_ids)))
    смены = (await db.execute(select(
        func.count(func.distinct(func.concat(
            EdgePacket.station_id, ":", EdgePacket.shift_internal_no))).label("шт"),
    ).where(*смены_условия))).one()
    if смены.шт:
        очереди.append({
            "code": "shifts_review", "title": "Смены ждут выверки",
            "reason": ("Себестоимость посчитана по оценке центра, а не по своим приходам — "
                       "в бухгалтерию такая смена не уйдёт без решения"),
            "action": "Открыть паспорт смены",
            "count": int(смены.шт), "amount": 0.0, "oldest_at": None,
        })

    очереди.sort(key=lambda q: -q["count"])
    return {"queues": очереди, "total": sum(q["count"] for q in очереди)}


@router.get("/shifts")
async def list_document_shifts(
    stations: str | None = Query(None, description="Коды АЗС через запятую"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр смен: то же самое, что реестр документов, но одной строкой на смену.

    Смена — главный разрез товарного контура станции: продажи, выпуск блюд и
    чеки порождены ею, и разбирать их поодиночке бессмысленно. Документы,
    которые смене не принадлежат (приёмка, инвентаризация, перемещение), сюда
    не попадают: у них shift_no пуст, и они влияют на смену через остаток, а не
    входят в её состав.
    """
    access = await resolve_document_access(user, db)
    conditions = [
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.shift_no.isnot(None),
    ]
    if stations:
        коды = [value.strip() for value in stations.split(",") if value.strip()]
        if any(not value.isdigit() for value in коды):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Коды АЗС должны быть целыми числами")
        conditions.append(StoreDocumentProjection.station_id.in_([int(v) for v in коды]))
    if not access.network and access.station_ids:
        conditions.append(StoreDocumentProjection.station_id.in_(sorted(access.station_ids)))
    if date_from is not None:
        conditions.append(StoreDocumentProjection.document_at >= datetime.combine(
            date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        conditions.append(StoreDocumentProjection.document_at < datetime.combine(
            date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    строки = (await db.execute(
        select(
            StoreDocumentProjection.station_id,
            StoreDocumentProjection.shift_no,
            StoreDocumentProjection.document_kind,
            func.count().label("шт"),
            func.sum(StoreDocumentProjection.amount).label("сумма"),
            func.min(StoreDocumentProjection.document_at).label("начало"),
            func.max(StoreDocumentProjection.document_at).label("конец"),
            func.bool_or(StoreDocumentProjection.requires_attention).label("внимание"),
        ).where(*conditions).group_by(
            StoreDocumentProjection.station_id,
            StoreDocumentProjection.shift_no,
            StoreDocumentProjection.document_kind,
        )
    )).all()

    смены: dict[tuple[int | None, int], dict] = {}
    for row in строки:
        ключ = (row.station_id, row.shift_no)
        смена = смены.setdefault(ключ, {
            "station_id": row.station_id, "shift_no": row.shift_no,
            "documents": 0, "revenue": 0.0, "started_at": None, "finished_at": None,
            "requires_attention": False, "kinds": {},
        })
        смена["documents"] += int(row.шт)
        смена["kinds"][row.document_kind] = int(row.шт)
        # Выручка смены — это её отчёт о розничных продажах, а не сумма всех
        # документов: чеки и выпуск блюд повторяют те же деньги в других
        # разрезах, и сложение дало бы тройной оборот.
        if row.document_kind == "retail_sale_sidegoods":
            смена["revenue"] += float(row.сумма or 0)
        if row.внимание:
            смена["requires_attention"] = True
        for поле, значение in (("started_at", row.начало), ("finished_at", row.конец)):
            текущее = смена[поле]
            if значение is None:
                continue
            if текущее is None or (значение < текущее if поле == "started_at" else значение > текущее):
                смена[поле] = значение

    итог = sorted(смены.values(),
                  key=lambda s: (s["finished_at"] or datetime.min.replace(tzinfo=timezone.utc),
                                 s["shift_no"]), reverse=True)
    for смена in итог:
        for поле in ("started_at", "finished_at"):
            смена[поле] = смена[поле].isoformat() if смена[поле] else None
    return {"shifts": итог[:limit], "total": len(итог)}


@router.get("/shifts/{station_id}/{shift_no}")
async def shift_passport(
    station_id: int,
    shift_no: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Паспорт смены: одно место, где видно состояние всех разрезов учёта.

    Не журнал ошибок, а карточка состояния: из чего смена состоит, что на неё
    повлияло, что мешает уйти в бухгалтерию и что для этого сделать.
    """
    access = await resolve_document_access(user, db)
    if not access.network and station_id not in access.station_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Станция вне вашего доступа")

    документы = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.station_id == station_id,
        StoreDocumentProjection.shift_no == shift_no,
    ).order_by(StoreDocumentProjection.document_at))).scalars().all()
    if not документы:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Смена {shift_no} на АЗС {station_id} не найдена")

    состав: dict[str, dict] = {}
    for row in документы:
        узел = состав.setdefault(row.document_kind, {"count": 0, "amount": 0.0, "attention": 0})
        узел["count"] += 1
        узел["amount"] += float(row.amount or 0)
        узел["attention"] += 1 if row.requires_attention else 0

    орп = next((row for row in документы
                if row.document_kind == "retail_sale_sidegoods"), None)
    смена_док = next((row for row in документы if row.document_kind == "store_shift"), None)
    начало = min((row.document_at for row in документы if row.document_at), default=None)
    конец = max((row.document_at for row in документы if row.document_at), default=None)

    # Последний пакет смены несёт светофор и доказательство себестоимости:
    # по нему видно, какие ингредиенты посчитаны по оценке центра, а не по
    # собственной закупке.
    пакет = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == access.company_id,
        EdgePacket.station_id == station_id,
        EdgePacket.shift_internal_no == shift_no,
        EdgePacket.kind == "shift",
    ).order_by(EdgePacket.received_at.desc()).limit(1))).scalars().first()
    payload = (пакет.payload if пакет else None) or {}
    completeness = payload.get("ShiftCompleteness") or {}
    светофор = str(completeness.get("status") or "").strip() or "unknown"
    evidence = payload.get("CostEvidence") or {}
    ингредиенты = evidence.get("ingredients") or []
    оценочные = [row for row in ингредиенты if str(row.get("status")) != "known"]

    # Влияние: документы того же дня и станции, которые смене не принадлежат,
    # но меняют её остаток. Приёмка не часть смены — она её условие.
    влияние: list[dict] = []
    if начало and конец:
        соседи = (await db.execute(select(StoreDocumentProjection).where(
            StoreDocumentProjection.company_id == access.company_id,
            StoreDocumentProjection.is_primary.is_(True),
            StoreDocumentProjection.station_id == station_id,
            StoreDocumentProjection.shift_no.is_(None),
            StoreDocumentProjection.document_at >= начало - timedelta(days=1),
            StoreDocumentProjection.document_at <= конец + timedelta(days=1),
        ).order_by(StoreDocumentProjection.document_at).limit(50))).scalars().all()
        влияние = [{
            "record_id": str(row.id), "kind": row.document_kind, "number": row.number,
            "document_at": row.document_at.isoformat() if row.document_at else None,
            "amount": float(row.amount or 0), "counterparty": row.counterparty_name,
            "operational_status": row.operational_status,
        } for row in соседи]

    действия: list[dict] = []
    if светофор == "needs_review":
        действия.append({
            "code": "cost_hint",
            "text": (f"Себестоимость {len(оценочные)} ингредиентов взята по оценке центра, "
                     "а не по собственным приходам — смена не уйдёт в бухгалтерию"),
            "hint": "Завести приходы по кухне или загрузить смену осознанно, указав причину",
        })
    ожидают = [row for row in влияние if row["operational_status"] in ("expected", "draft")]
    if ожидают:
        действия.append({
            "code": "receipts_pending",
            "text": f"Рядом со сменой {len(ожидают)} непринятых документов поставки",
            "hint": "Принять их — тогда остаток и себестоимость смены станут своими",
        })
    внимание = [row for row in документы if row.requires_attention]
    if внимание:
        действия.append({
            "code": "attention",
            "text": f"{len(внимание)} документов смены помечены «требует внимания»",
            "hint": "Открыть их из состава смены и разобрать причину",
        })

    # Границы смены — из её шапки, а не по документам: рецептуры и выпуск
    # создаются в момент сборки, и по ним «смена» тянулась бы до сегодняшнего
    # дня.
    шапка_смены = payload.get("Смена") or {}
    открытие = str(шапка_смены.get("Открытие") or "").strip()
    закрытие = str(шапка_смены.get("Закрытие") or "").strip()

    return {
        "station_id": station_id,
        "shift_no": shift_no,
        "started_at": открытие or (начало.isoformat() if начало else None),
        "finished_at": закрытие or (конец.isoformat() if конец else None),
        "status": светофор,
        "revenue": float(орп.amount or 0) if орп is not None else 0.0,
        "vat": float(орп.vat_amount or 0) if орп is not None and орп.vat_amount is not None else None,
        "cheques": int((смена_док.header or {}).get("cheques") or 0) if смена_док is not None else 0,
        "documents": len(документы),
        "composition": [
            {"kind": вид, **значения} for вид, значения in sorted(состав.items())
        ],
        "cost_estimated": [
            {"item_uuid": row.get("item_uuid"), "status": row.get("status"),
             "quantity_millis": row.get("required_quantity_millis"),
             "amount_micros": row.get("required_amount_micros")}
            for row in оценочные
        ],
        "influenced_by": влияние,
        "actions": действия,
        "packet_uuid": (пакет.packet_uuid if пакет else None),
    }


@router.get("")
async def list_documents(
    station_id: int | None = Query(None),
    stations: str | None = Query(None, description="Коды АЗС через запятую"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    kind: str | None = Query(None),
    q: str | None = Query(None),
    supplier: str | None = Query(None),
    operational_status: str | None = Query(None),
    sync_status: str | None = Query(None),
    accounting_status: str | None = Query(None),
    discrepancy_status: str | None = Query(None),
    source: str | None = Query(None),
    warehouse: str | None = Query(None, description="UUID склада или его название"),
    attention: bool | None = Query(None),
    has_files: bool | None = Query(None),
    shift_no: int | None = Query(
        None, description="Документы одной кассовой смены станции"),
    counter: str | None = Query(
        None, description="Отобрать ровно то, что посчитал счётчик реестра"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    base_conditions = [
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.document_kind.in_(PROJECTION_DOCUMENT_KINDS),
    ]
    # Чек и кассовая смена — доказательство продажи, а не учётный документ, и у
    # них есть свой раздел «Касса». В реестре документов они только топят
    # накладные: полторы тысячи чеков против сотни документов учёта. Достать их
    # по-прежнему можно, запросив вид явно.
    if not kind:
        base_conditions.append(
            StoreDocumentProjection.document_kind.not_in(("fiscal_receipt", "store_shift")))
    requested_stations: set[int] = set()
    if stations:
        raw_stations = [value.strip() for value in stations.split(",") if value.strip()]
        if any(not value.isdigit() for value in raw_stations):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Коды АЗС должны быть целыми числами")
        requested_stations.update(int(value) for value in raw_stations)
    if station_id is not None:
        requested_stations.add(station_id)
    if access.network:
        if requested_stations:
            base_conditions.append(or_(
                StoreDocumentProjection.station_id.in_(sorted(requested_stations)),
                StoreDocumentProjection.station_id.is_(None),
            ))
    else:
        allowed = set(access.station_ids)
        if requested_stations:
            allowed.intersection_update(requested_stations)
        base_conditions.append(StoreDocumentProjection.station_id.in_(sorted(allowed)))
    if date_from is not None:
        base_conditions.append(StoreDocumentProjection.document_at >= datetime.combine(
            date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        base_conditions.append(StoreDocumentProjection.document_at < datetime.combine(
            date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    filter_conditions = []
    if kind:
        # Раздел документооборота — это несколько видов сразу: «изменения
        # остатка» складываются из пересчёта, оприходования и списания, и
        # человек работает с ними как с одним разделом.
        виды = [значение.strip() for значение in kind.split(",") if значение.strip()]
        неизвестные = [значение for значение in виды if значение not in PROJECTION_DOCUMENT_KINDS]
        if неизвестные:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Неизвестный вид документа: {', '.join(неизвестные)}")
        filter_conditions.append(StoreDocumentProjection.document_kind.in_(виды))
    if operational_status:
        filter_conditions.append(
            StoreDocumentProjection.operational_status == operational_status)
    if sync_status:
        filter_conditions.append(StoreDocumentProjection.sync_status == sync_status)
    if source:
        filter_conditions.append(StoreDocumentProjection.projection_source == source)
    if supplier and supplier.strip():
        supplier_pattern = f"%{supplier.strip()}%"
        filter_conditions.append(or_(
            StoreDocumentProjection.counterparty_name.ilike(supplier_pattern),
            StoreDocumentProjection.counterparty_inn.ilike(supplier_pattern),
        ))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filter_conditions.append(or_(
            StoreDocumentProjection.number.ilike(pattern),
            StoreDocumentProjection.counterparty_name.ilike(pattern),
            StoreDocumentProjection.counterparty_inn.ilike(pattern),
        ))
    if warehouse and warehouse.strip():
        raw_warehouse = warehouse.strip()
        try:
            filter_conditions.append(
                StoreDocumentProjection.warehouse_id == uuid.UUID(raw_warehouse))
        except ValueError:
            # у документа станции канонического склада может ещё не быть —
            # тогда единственное, что о нём известно, это название в шапке
            warehouse_pattern = f"%{raw_warehouse}%"
            filter_conditions.append(or_(
                StoreDocumentProjection.header["warehouse"].astext.ilike(
                    warehouse_pattern),
                StoreDocumentProjection.header["warehouse_to"].astext.ilike(
                    warehouse_pattern),
            ))

    counter_conditions = []
    if counter:
        if counter not in COUNTER_CONDITIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный счётчик")
        counter_conditions.extend(COUNTER_CONDITIONS[counter]())
    if attention is not None:
        counter_conditions.append(StoreDocumentProjection.requires_attention.is_(attention))
    if has_files is not None:
        counter_conditions.append(StoreDocumentProjection.has_files.is_(has_files))
    if shift_no is not None:
        counter_conditions.append(StoreDocumentProjection.shift_no == shift_no)
    if accounting_status:
        counter_conditions.append(
            StoreDocumentProjection.accounting_status == accounting_status)
    if discrepancy_status:
        counter_conditions.append(
            StoreDocumentProjection.discrepancy_status == discrepancy_status)

    stats_conditions = [*base_conditions, *filter_conditions]
    counter_names = tuple(COUNTER_CONDITIONS)
    stats_row = (await db.execute(select(
        *[func.count().filter(*COUNTER_CONDITIONS[name]()) for name in counter_names],
        # реестр — проекция, и человек должен видеть, на какой момент она собрана
        func.max(StoreDocumentProjection.rebuilt_at),
    ).select_from(StoreDocumentProjection).where(*stats_conditions))).one()

    conditions = [*stats_conditions, *counter_conditions]
    total = (await db.execute(select(func.count()).select_from(
        StoreDocumentProjection).where(*conditions))).scalar() or 0
    rows = (await db.execute(select(StoreDocumentProjection).where(*conditions)
                             .order_by(StoreDocumentProjection.document_at.desc().nullslast(),
                                       StoreDocumentProjection.id)
                             .offset(offset).limit(limit))).scalars().all()
    return {
        "documents": [_brief(row) for row in rows], "total": int(total),
        "limit": limit, "offset": offset,
        "stats": {name: int(stats_row[index] or 0)
                  for index, name in enumerate(counter_names)},
        "rebuilt_at": stats_row[len(counter_names)],
        "rebuild_allowed": access.is_superadmin or access.is_merchandiser,
    }


@router.post("/snapshot/queue")
async def queue_document_snapshot(
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    if not access.network:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуется сетевая роль")
    try:
        task, created = await queue_onec_document_snapshot(
            db, access.company_id, station_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return {
        "task_id": str(task.id), "created": created,
        "kind": task.kind, "station_id": task.station_id,
        "revision": int((task.payload or {}).get("revision") or 0),
        "content_hash": (task.payload or {}).get("content_hash"),
        "headers": len((task.payload or {}).get("headers") or []),
    }


@router.get("/{record_id}")
async def document_detail(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    line_refs = (await db.execute(select(StoreDocumentProjectionLine).where(
        StoreDocumentProjectionLine.company_id == access.company_id,
        StoreDocumentProjectionLine.record_id == row.id,
    ).order_by(StoreDocumentProjectionLine.ordinal))).scalars().all()
    payload = await normalized_document_payload(db, row)
    safe_payload = safe_document_detail(row, payload)
    result = _brief(row)
    result.update({
        "header": row.header,
        "issues": _document_issues(row),
        "timeline": _document_timeline(row),
        "file_write_allowed": _file_write_allowed(
            access, row.station_id, row.document_kind),
        "line_refs": [{"section": item.source_section,
                       "line_id": item.source_line_id, "ordinal": item.ordinal}
                      for item in line_refs],
        "document": safe_payload,
    })
    return result


def _document_issues(row: StoreDocumentProjection) -> list[dict]:
    """Что с документом не так — словами, а не набором бейджей.

    До сих пор человек читал карточку как ребус: «нужна проверка», «строки без
    ключа», «на карантине» — и сам догадывался, чинить это ему, нам, или не
    чинить вовсе. Здесь у каждой проблемы есть причина и адресат.
    """
    проблемы: list[dict] = []
    if row.document_kind in ("purchase", "return_purchase") and not row.has_files:
        проблемы.append({
            "code": "no_evidence", "owner": "человек",
            "text": "Нет файла-подтверждения",
            "hint": "Приложите накладную или УПД: без документа бухгалтерия не примет вычет НДС",
        })
    if row.operational_status in ("expected", "draft"):
        проблемы.append({
            "code": "not_accepted", "owner": "человек",
            "text": "Поставка не принята",
            "hint": "Пока приёмка не проведена, остаток и себестоимость станции считаются без неё",
        })
    if row.accounting_status == "needs_review":
        проблемы.append({
            "code": "accounting_review", "owner": "человек",
            "text": "Учёт ждёт решения",
            "hint": "Проверьте реквизиты: поставщика, договор, склад, ставки НДС",
        })
    if row.accounting_status == "rejected":
        проблемы.append({
            "code": "accounting_rejected", "owner": "человек",
            "text": "Бухгалтерия вернула документ",
            "hint": "Причина — в ответе приёмника; исправьте и отправьте заново",
        })
    if row.discrepancy_status == "quarantined":
        причина = (row.header or {}).get("classification_error")
        проблемы.append({
            "code": "quarantined", "owner": "разработка",
            "text": "Документ не разобрался до конца",
            "hint": причина or "Строки не удалось отнести к товарному контуру станции",
        })
    if row.discrepancy_status == "line_identity_ambiguous":
        проблемы.append({
            "code": "line_identity", "owner": "никто",
            "text": "Строки без собственного ключа",
            "hint": ("Свойство данных, а не ошибка: документ собран версией агента, "
                     "которая не присваивала строкам идентификаторы. Действий не требует"),
        })
    if row.discrepancy_status in ("minor", "material", "critical", "unmatched"):
        проблемы.append({
            "code": "onec_diff", "owner": "человек",
            "text": "Расходится с документом 1С",
            "hint": "Сверьте построчно: количество, цены и ставки",
        })
    return проблемы


def _document_timeline(row: StoreDocumentProjection) -> list[dict]:
    """Что с документом происходило: путь, а не только текущее состояние.

    Состояние отвечает «где документ сейчас», но не отвечает «почему он тут
    застрял». Путь собираем из того, что реестр знает точно, и не выдумываем
    шагов, которых не было.
    """
    шаги: list[dict] = []
    источник = {
        "edge": "Создан на станции", "store": "Заведён в приёмке",
        "cash": "Пробит кассой", "onec": "Пришёл из 1С",
        "accounting": "Создан бухгалтерским каналом",
    }.get(row.projection_source, "Создан")
    шаги.append({"code": "created", "text": источник,
                 "at": row.document_at.isoformat() if row.document_at else None,
                 "done": True})
    шаги.append({"code": "delivered", "text": "Доставлен в центр",
                 "at": row.rebuilt_at.isoformat() if row.rebuilt_at else None,
                 "done": row.sync_status in ("received", "accepted", "queued")})
    if row.document_kind in ("purchase", "return_purchase"):
        шаги.append({"code": "accepted", "text": "Принят на станции", "at": None,
                     "done": row.operational_status == "accepted"})
        шаги.append({"code": "evidence", "text": "Приложен подтверждающий файл",
                     "at": None, "done": bool(row.has_files)})
    шаги.append({"code": "accounting", "text": "Передан в бухгалтерию", "at": None,
                 "done": row.accounting_status in ("accepted", "ready")})
    return шаги


@router.get("/{record_id}/print", response_class=HTMLResponse)
async def document_print_form(
    record_id: uuid.UUID,
    variant: str = Query("main", pattern="^(main|diff)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Печатная форма документа на привычном бланке (ТОРГ-12, ИНВ-3, ТОРГ-2, …)."""
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    payload = safe_document_detail(row, await normalized_document_payload(db, row))
    company = await db.get(Company, access.company_id)
    form = печатная_форма(
        row, payload, компания=getattr(company, "name", "") or "", вариант=variant)
    if form is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Расхождений в документе нет — акт не печатается пустым"
            if variant == "diff" else
            "У этого вида документа нет печатной формы: чек печатает касса, "
            "смена — архив продаж, переоценка оформляется приказом по ценам",
        )
    return HTMLResponse(form)


@router.get("/{record_id}/relations")
async def document_relations(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    await _projection(db, access, record_id)
    relations = (await db.execute(select(StoreDocumentRelation).where(
        StoreDocumentRelation.company_id == access.company_id,
        StoreDocumentRelation.record_id == record_id,
    ))).scalars().all()
    result = []
    for relation in relations:
        if relation.related_record_id is None:
            if relation.relation_kind == "stock_movement":
                metadata = relation.metadata_json or {}
                movement_id = metadata.get("id")
                movement_kind = metadata.get("kind")
                if movement_id and movement_kind:
                    result.append({
                        "kind": "stock_movement",
                        "movement": {
                            "id": str(movement_id), "kind": str(movement_kind),
                            "count": 1,
                        },
                    })
            continue
        try:
            related = await _projection(db, access, relation.related_record_id)
        except HTTPException:
            continue
        result.append({"kind": relation.relation_kind, "related": _brief(related)})
    return {"relations": result, "total": len(result)}


@router.get("/{record_id}/payload")
async def document_payload(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    if not access.can_raw:
        return {
            "available": bool(row.raw_payload_available),
            "status": row.accounting_status,
            "detail": "Полезная нагрузка доступна бухгалтеру",
        }
    return {"available": bool(row.raw_payload_available),
            "payload": await normalized_document_payload(db, row)}


@router.get("/{record_id}/files")
async def document_files(
    record_id: uuid.UUID,
    include_tombstones: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    legacy_ref = _legacy_doc_ref(document)
    file_scope = StoreDocFile.record_id == record_id
    if legacy_ref:
        file_scope = or_(file_scope, StoreDocFile.doc_ref == legacy_ref)
    conditions = [StoreDocFile.company_id == access.company_id, file_scope]
    if not include_tombstones:
        conditions.append(StoreDocFile.tombstoned_at.is_(None))
    rows = (await db.execute(select(StoreDocFile).where(*conditions)
                             .order_by(StoreDocFile.uploaded_at.desc()))).scalars().all()
    return {"files": [{
        "id": str(row.id), "role": row.role or row.kind,
        "file_name": row.file_name, "mime": row.mime, "size_bytes": row.size_bytes,
        "sha256": row.sha256, "revision": row.revision,
        "uploaded_at": row.uploaded_at, "tombstoned_at": row.tombstoned_at,
        "download_url": f"/api/store/documents/{record_id}/files/{row.id}/download",
    } for row in rows], "total": len(rows)}


@router.post("/{record_id}/files", status_code=201)
async def document_file_upload(
    record_id: uuid.UUID,
    role: str = Query("накладная"),
    note: str | None = Query(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    if not _file_write_allowed(access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    if role not in FILE_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная роль файла")
    if (file.content_type or "") not in FILE_MIME_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Разрешены PDF, JPEG, PNG и WebP")
    content = await file.read()
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пуст или больше 25 МБ")
    checksum = hashlib.sha256(content).hexdigest()
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
    ), {"scope_key": f"store-document-file:{access.company_id}:{record_id}"})
    existing = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.company_id == access.company_id,
        StoreDocFile.record_id == record_id,
        StoreDocFile.revision == document.revision,
        StoreDocFile.role == role,
        StoreDocFile.sha256 == checksum,
    ))).scalar_one_or_none()
    if existing is not None:
        return {"id": str(existing.id), "created": False, "sha256": checksum}
    file_id = uuid.uuid4()
    file_path = Path(os.environ.get("UPLOAD_DIR", "/app/uploads")) / (
        f"{file_id}{Path(file.filename or 'file').suffix}"
    )
    try:
        await ops_terms.store_file(
            db, access.company_id, file.filename, file.content_type, content,
            file_id=file_id)
        row = StoreDocFile(
            company_id=access.company_id,
            doc_ref=f"projection:{record_id}",
            record_id=record_id,
            document_id=document.document_id,
            station_id=document.station_id,
            kind=role,
            role=role,
            sha256=checksum,
            revision=document.revision,
            file_id=file_id,
            file_name=file.filename or "документ",
            mime=file.content_type,
            size_bytes=len(content),
            note=note,
            uploaded_by=user.id,
            author_id=user.id,
        )
        db.add(row)
        document.has_files = True
        meta = (await db.execute(select(StoreDocMeta).where(
            StoreDocMeta.company_id == access.company_id,
            StoreDocMeta.record_id == record_id,
        ))).scalar_one_or_none()
        if meta is None:
            db.add(StoreDocMeta(
                company_id=access.company_id, doc_ref=f"projection:{record_id}",
                record_id=record_id, document_id=document.document_id,
                revision=document.revision, updated_by=user.id,
            ))
        await db.commit()
    except Exception:
        await db.rollback()
        file_path.unlink(missing_ok=True)
        raise
    return {"id": str(row.id), "created": True, "sha256": checksum}


@router.delete("/{record_id}/files/{file_row_id}")
async def document_file_tombstone(
    record_id: uuid.UUID,
    file_row_id: uuid.UUID,
    reason: str = Query(..., min_length=3, max_length=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    if not _file_write_allowed(access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    row = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.id == file_row_id,
        StoreDocFile.company_id == access.company_id,
        or_(StoreDocFile.record_id == record_id,
            StoreDocFile.doc_ref == (_legacy_doc_ref(document) or "")),
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    if row.tombstoned_at is None:
        row.tombstoned_at = datetime.now(timezone.utc)
        row.tombstoned_by = user.id
        row.tombstone_reason = reason.strip()
    remaining_scope = StoreDocFile.record_id == record_id
    legacy_ref = _legacy_doc_ref(document)
    if legacy_ref:
        remaining_scope = or_(remaining_scope, StoreDocFile.doc_ref == legacy_ref)
    remaining = (await db.execute(select(func.count()).select_from(StoreDocFile).where(
        StoreDocFile.company_id == access.company_id,
        remaining_scope,
        StoreDocFile.id != file_row_id,
        StoreDocFile.tombstoned_at.is_(None),
    ))).scalar() or 0
    document.has_files = bool(remaining)
    await db.commit()
    return {"ok": True, "tombstoned": True}


@router.get("/{record_id}/files/{file_row_id}/download")
async def document_file_download(
    record_id: uuid.UUID,
    file_row_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    row = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.id == file_row_id,
        StoreDocFile.company_id == access.company_id,
        or_(StoreDocFile.record_id == record_id,
            StoreDocFile.doc_ref == (_legacy_doc_ref(document) or "")),
        StoreDocFile.tombstoned_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    source = await db.get(SourceFile, row.file_id)
    if source is None or source.company_id != access.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    path = Path(source.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return FileResponse(str(path), media_type=source.mime_type, filename=source.file_name)


async def authorize_store_file_download(
    db: AsyncSession, user: User, file_id: uuid.UUID,
) -> None:
    rows = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.file_id == file_id,
    ))).scalars().all()
    if not rows:
        return
    for row in rows:
        if row.tombstoned_at is not None:
            continue
        try:
            access = await resolve_document_access(user, db, row.company_id)
            document = await _file_projection(db, row.company_id, row)
            if document is None:
                continue
            await _projection(db, access, document.id)
            return
        except HTTPException:
            continue
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
