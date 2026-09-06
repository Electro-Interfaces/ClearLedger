from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
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
    Period,
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
import re as _re
_re_цифры = _re.compile(r"\d{6,}")
from app.services.bp_export import _код_для_сравнения
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
    # «Поставки ждут приёмки» — тот же критерий, что и очередь Разбора, чтобы
    # переход «Открыть и принять» показывал ровно те документы, что она посчитала
    # (иначе очередь пишет 7, а список draft-поставок пуст под фильтром expected).
    "waiting_receipt": lambda: (
        StoreDocumentProjection.document_kind == "purchase",
        StoreDocumentProjection.operational_status.in_(("expected", "draft")),
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


def _transfer_route(row: StoreDocumentProjection) -> str | None:
    """Читаемое направление перемещения для реестра: зал↔склад станции или между
    станциями сети. Данные — в header (обогащается при сборке проекции; для старых
    документов появится после «Пересобрать реестр»)."""
    if row.document_kind != "transfer":
        return None
    h = row.header or {}
    напр = str(h.get("direction") or "").strip()
    отпр, получ = h.get("sender"), h.get("receiver")
    ст_получ = h.get("receiver_station")
    if напр == "external" or (ст_получ and str(ст_получ) != str(row.station_id)):
        return f"АЗС {row.station_id or '?'} → АЗС {ст_получ or '?'} · между станциями сети"
    if отпр or получ:
        return f"{отпр or '—'} → {получ or '—'} · внутри станции"
    return None


def _revaluation(row: StoreDocumentProjection) -> dict | None:
    """Переоценка меняет цену одной позиции — её суть (было → стало, причина,
    штрихкод) лежит в header, товарных строк у неё нет. Иначе карточка рисует
    пустую таблицу строк и «странную переоценку на 0 ₽»."""
    if row.document_kind != "revaluation":
        return None
    h = row.header or {}
    return {
        "from": h.get("old_price"), "to": h.get("new_price"),
        "barcode": h.get("barcode"), "reason": h.get("reason"),
        "item": h.get("item_uuid"), "name": None,  # имя дорезолвится в списке/карточке
    }


def _brief(row: StoreDocumentProjection) -> dict:
    return {
        "record_id": str(row.id), "document_id": str(row.document_id),
        "transfer_route": _transfer_route(row),
        "revaluation": _revaluation(row),
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
         "Открыть и принять", COUNTER_CONDITIONS["waiting_receipt"]()),
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


async def _блокеры_смен(
    db: AsyncSession, company_id, ключи: set[tuple[int | None, int | None]],
) -> tuple[dict[tuple[int | None, int | None], list[str]],
           dict[tuple[int | None, int | None], list[str]]]:
    """Что помешает смене уехать в бухгалтерию. Пусто — уедет.

    Считаем ровно то, на чём спотыкается сборщик пакета (`BpPackageEmitter`):
    позицию, которой нет в каталоге, и проданное блюдо без выпуска. Раньше
    светофор смотрел только на `ShiftCompleteness.status`, поэтому смены 7092 и
    7096 висели «можно грузить», хотя канал их не собирал вовсе, — а все
    остальные были жёлтыми из-за оценочной себестоимости, которая выгрузке не
    мешает.

    Три запроса на все смены разом: каталог, строки продаж, выпуски. Полную
    сборку пакета не гоняем — реестр открывают часто.
    """
    if not ключи:
        return {}, {}
    станции = {s for s, _ in ключи if s is not None}
    номера = {str(n) for _, n in ключи if n is not None}
    if not станции or not номера:
        return {}, {}

    известные: set[str] = set()
    по_коду: dict[str, str] = {}
    for uid, коды in (await db.execute(text("""
        SELECT i.external_uuid::text AS uid,
               coalesce(array_agg(b.code) FILTER (WHERE b.code IS NOT NULL), '{}') AS коды
        FROM edge.item i LEFT JOIN edge.barcode b ON b.item_id = i.id
        GROUP BY i.external_uuid
    """))).all():
        известные.add(uid)
        for код in (коды or []):
            ключ = _код_для_сравнения(код)
            if ключ and ключ not in по_коду:
                по_коду[ключ] = uid

    # Тот же запасной индекс, что у сборщика пакета: код станционной карточки
    # из журналов центра. Без него светофор строже канала — смена 7095 горела
    # красным, хотя пакет собирался (у PEPSI код есть в журнале цен, но не в
    # строке продажи).
    запасной: dict[str, str] = {}
    for row in (await db.execute(text("""
        SELECT item_uuid::text AS uid, barcode::text AS коды
        FROM edge.station_price_change WHERE barcode IS NOT NULL
        UNION ALL
        SELECT source_uuid::text, barcodes::text
        FROM edge.item_draft WHERE barcodes IS NOT NULL
    """))).mappings().all():
        uid = str(row["uid"] or "")
        коды = _re_цифры.findall(str(row["коды"] or ""))
        if uid and коды:
            запасной.setdefault(uid, коды[0])

    # Позиции берём из ВСЕХ документов смены, а не только из продаж.
    #
    # Карточка нужна и приёмке, и списанию, и пересчёту — сборщик пакета
    # спотыкается о любую строку без неё. Пока светофор смотрел одни продажи,
    # он занижал счёт: у смены 7099 показывал 3 позиции вместо 11, у 7096 —
    # одну вместо двух, и человек шёл разбирать не тот объём.
    продажи = (await db.execute(text("""
        SELECT (e.metadata->'Смена'->>'КодАЗС')::int AS станция,
               (e.metadata->'Смена'->>'НомерСменыВнутр')::int AS смена,
               src.секция, t->>'Номенклатура' AS uid, t->>'ШтрихКод' AS шк,
               t->>'Наименование' AS имя
        FROM data_entries e
        CROSS JOIN LATERAL (
            -- секции отчёта о продажах
            SELECT 'продажа_сопутка' AS секция,
                   e.metadata->'Секции'->'продажа_сопутка'->'строки' AS строки
            UNION ALL
            SELECT 'продажа_общепит',
                   e.metadata->'Секции'->'продажа_общепит'->'строки'
            UNION ALL
            -- табличные части прочих документов смены
            SELECT 'документ', e.metadata->'Документ'->'Товары'
            UNION ALL
            SELECT 'документ', e.metadata->'Документ'->'ВыпускБлюд'
            UNION ALL
            SELECT 'документ', e.metadata->'Документ'->'ВозвращенныеТовары'
        ) AS src(секция, строки)
        CROSS JOIN LATERAL jsonb_array_elements(
            coalesce(src.строки, '[]'::jsonb)) t
        WHERE e.company_id = :c AND e.source = 'edge'
          AND (e.metadata->'Смена'->>'КодАЗС') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'НомерСменыВнутр') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'КодАЗС')::int = ANY(:st)
          AND (e.metadata->'Смена'->>'НомерСменыВнутр')::int = ANY(:sh)
    """), {"c": company_id, "st": list(станции),
           "sh": [int(n) for n in номера if n.isdigit()]})).mappings().all()

    # Документы БЕЗ номера смены — приёмки, списания, пересчёты — привязываются
    # к смене по времени, ровно как в сборщике пакета. Без этого светофор
    # занижал счёт: у смены 7099 показывал 3 позиции вместо 11, потому что
    # восемь из них лежат в приёмках того дня, а номера смены у приёмки нет.
    интервалы = (await db.execute(text("""
        SELECT (e.metadata->'Смена'->>'КодАЗС')::int AS станция,
               (e.metadata->'Смена'->>'НомерСменыВнутр')::int AS смена,
               e.metadata->'Смена'->>'Открытие' AS откр,
               e.metadata->'Смена'->>'Закрытие' AS закр
        FROM data_entries e
        WHERE e.company_id = :c AND e.source = 'edge'
          AND e.doc_type_id = 'retail_sale_sidegoods'
          AND (e.metadata->'Смена'->>'КодАЗС') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'НомерСменыВнутр') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'КодАЗС')::int = ANY(:st)
          AND (e.metadata->'Смена'->>'НомерСменыВнутр')::int = ANY(:sh)
    """), {"c": company_id, "st": list(станции),
           "sh": [int(n) for n in номера if n.isdigit()]})).mappings().all()
    окна: dict[int, list[tuple[str, str, int]]] = {}
    for row in интервалы:
        if row["откр"] and row["закр"]:
            окна.setdefault(row["станция"], []).append(
                (row["откр"], row["закр"], row["смена"]))

    вне_смен = (await db.execute(text("""
        SELECT (e.metadata->'Смена'->>'КодАЗС')::int AS станция,
               coalesce(e.metadata->'Документ'->>'Дата',
                        e.metadata->'Смена'->>'Открытие') AS момент,
               t->>'Номенклатура' AS uid, t->>'ШтрихКод' AS шк,
               t->>'Наименование' AS имя
        FROM data_entries e
        CROSS JOIN LATERAL (
            SELECT e.metadata->'Документ'->'Товары' AS строки
            UNION ALL SELECT e.metadata->'Документ'->'ВыпускБлюд'
            UNION ALL SELECT e.metadata->'Документ'->'ВозвращенныеТовары'
        ) AS src(строки)
        CROSS JOIN LATERAL jsonb_array_elements(
            coalesce(src.строки, '[]'::jsonb)) t
        WHERE e.company_id = :c AND e.source = 'edge'
          AND e.doc_type_id <> 'retail_sale_sidegoods'
          AND (e.metadata->'Смена'->>'КодАЗС') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'КодАЗС')::int = ANY(:st)
          AND coalesce(e.metadata->'Смена'->>'НомерСменыВнутр', '') !~ '^[1-9]'
    """), {"c": company_id, "st": list(станции)})).mappings().all()

    выпущено: dict[tuple[int, int], set[str]] = {}
    for row in (await db.execute(text("""
        SELECT (e.metadata->'Смена'->>'КодАЗС')::int AS станция,
               (e.metadata->'Смена'->>'НомерСменыВнутр')::int AS смена,
               t->>'Номенклатура' AS uid
        FROM data_entries e
        CROSS JOIN LATERAL jsonb_array_elements(
            coalesce(e.metadata->'Документ'->'ВыпускБлюд', '[]'::jsonb)) t
        WHERE e.company_id = :c AND e.source = 'edge'
          AND e.doc_type_id = 'production_release'
          AND (e.metadata->'Смена'->>'КодАЗС') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'НомерСменыВнутр') ~ '^[0-9]+$'
          AND (e.metadata->'Смена'->>'КодАЗС')::int = ANY(:st)
          AND (e.metadata->'Смена'->>'НомерСменыВнутр')::int = ANY(:sh)
    """), {"c": company_id, "st": list(станции),
           "sh": [int(n) for n in номера if n.isdigit()]})).mappings().all():
        выпущено.setdefault((row["станция"], row["смена"]), set()).add(str(row["uid"] or ""))

    нет_карточки: dict[tuple[int, int], set[str]] = {}
    блюда: dict[tuple[int, int], set[str]] = {}
    for row in продажи:
        ключ = (row["станция"], row["смена"])
        uid = str(row["uid"] or "")
        код = row["шк"] or запасной.get(uid, "")
        if not uid or (uid not in известные
                       and not по_коду.get(_код_для_сравнения(код))):
            нет_карточки.setdefault(ключ, set()).add(
                str(row["имя"] or row["шк"] or uid or "?")[:40])
        if row["секция"] == "продажа_общепит" and uid:
            блюда.setdefault(ключ, set()).add(uid)

    # Склад-документ со строкой без карточки пакет НЕ валит: сборщик откладывает
    # его одного («не разложено»), а смена уезжает. Поэтому такие позиции — не
    # блокер, а предупреждение: работа для товароведа есть, но загрузка идёт.
    # Смешать их с блокерами значит красить смену 7063 красным при том, что она
    # прекрасно собирается.
    отложится: dict[tuple[int, int], set[str]] = {}
    for row in вне_смен:
        момент = str(row["момент"] or "")
        if not момент:
            continue
        for откр, закр, смена_но in окна.get(row["станция"], []):
            if not (откр <= момент <= закр):
                continue
            uid = str(row["uid"] or "")
            код = row["шк"] or запасной.get(uid, "")
            if not uid or (uid not in известные
                           and not по_коду.get(_код_для_сравнения(код))):
                отложится.setdefault((row["станция"], смена_но), set()).add(
                    str(row["имя"] or row["шк"] or uid or "?")[:40])
            break

    итог: dict[tuple[int | None, int | None], list[str]] = {}
    for ключ, имена in нет_карточки.items():
        итог.setdefault(ключ, []).append(
            f"нет карточки в каталоге: {len(имена)} поз. — "
            + ", ".join(sorted(имена)[:3]))
    # Предупреждения возвращаем ОТДЕЛЬНО: они не красят смену красным.
    предупреждения: dict[tuple[int | None, int | None], list[str]] = {}
    for ключ, имена in отложится.items():
        предупреждения.setdefault(ключ, []).append(
            f"документ смены не уедет, нет карточки: {len(имена)} поз. — "
            + ", ".join(sorted(имена)[:3]))
    # Блюдо без выпуска смены блокером НЕ считается: в модели учёта B (умолчание
    # у ГИГ, подтверждено 04.09.2026 — в бухгалтерии 0 выпусков и 1364
    # комплектации) приёмник выпуск пропускает штатно, себестоимость уходит при
    # продаже через ТТК. Держать смену из-за него значило останавливать её
    # приёмки: у 7092 так стояло 209 тыс. из-за чашки кофе на 190 ₽.
    return итог, предупреждения


def _readiness(completeness_status: str | None) -> str:
    """Единый светофор смены для реестра и листа. Источник истины один —
    ShiftCompleteness.status последнего пакета смены: needs_review не уходит в
    бухгалтерию (жёлтый), всё прочее — готова (зелёный). Красный (расхождение
    по сверке) подключится позже. Раньше реестр красил по requires_attention, а
    лист — по completeness, и одна смена была зелёной в списке и жёлтой внутри."""
    return "y" if str(completeness_status or "").strip() == "needs_review" else "g"


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
    чеки порождены ею, и разбирать их поодиночке бессмысленно. Склад-документы
    (приёмка, инвентаризация, перемещение) у которых shift_no пуст, отдельной
    строкой в реестре не встают, но приписываются к смене того же дня — так же,
    как их показывает лист смены (таб «Склад»), чтобы чипы разрезов совпадали.
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

    # Склад-документы смене не принадлежат (shift_no пуст), но лист смены
    # показывает их по дате дня — приписываем к смене того же дня и здесь,
    # иначе чипы «Поступления/Инвентаризации/…» в реестре стоят в нуле, хотя
    # в самом ОРП (таб «Склад») эти документы есть.
    СКЛАД_ВИДЫ = [
        "purchase", "return_purchase", "inventory",
        "transfer", "gain", "writeoff", "revaluation",
    ]
    if смены:
        склад_условия = [
            StoreDocumentProjection.company_id == access.company_id,
            StoreDocumentProjection.is_primary.is_(True),
            StoreDocumentProjection.shift_no.is_(None),
            StoreDocumentProjection.document_kind.in_(СКЛАД_ВИДЫ),
        ]
        if stations:
            склад_условия.append(StoreDocumentProjection.station_id.in_([int(v) for v in коды]))
        if not access.network and access.station_ids:
            склад_условия.append(StoreDocumentProjection.station_id.in_(sorted(access.station_ids)))
        if date_from is not None:
            склад_условия.append(StoreDocumentProjection.document_at >= datetime.combine(
                date_from, time.min, tzinfo=timezone.utc))
        if date_to is not None:
            склад_условия.append(StoreDocumentProjection.document_at < datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
        склад_строки = (await db.execute(
            select(
                StoreDocumentProjection.station_id,
                StoreDocumentProjection.document_at,
                StoreDocumentProjection.document_kind,
            ).where(*склад_условия)
        )).all()
        # День смены — по её закрытию в московской зоне (как в листе смены),
        # иначе UTC-сдвиг увёл бы открытие ночной смены на прошлые сутки.
        мск = ZoneInfo("Europe/Moscow")
        по_дню: dict[tuple[int | None, date], dict] = {}
        for смена in смены.values():
            день = смена["finished_at"] or смена["started_at"]
            if день:
                по_дню[(смена["station_id"], день.astimezone(мск).date())] = смена
        for row in склад_строки:
            if row.document_at is None:
                continue
            смена = по_дню.get((row.station_id, row.document_at.astimezone(мск).date()))
            if смена is not None:
                смена["kinds"][row.document_kind] = смена["kinds"].get(row.document_kind, 0) + 1
                смена["documents"] += 1

    # Светофор смены — по последнему пакету смены (ShiftCompleteness.status),
    # тем же источником, что и лист смены, иначе цвет в списке и внутри расходится.
    for смена in смены.values():
        смена["readiness"] = "g"
    if смены:
        станции_см = {s["station_id"] for s in смены.values()}
        номера_см = {s["shift_no"] for s in смены.values()}
        пакеты_см = (await db.execute(
            select(
                EdgePacket.station_id, EdgePacket.shift_internal_no,
                EdgePacket.payload["ShiftCompleteness"]["status"].astext.label("st"),
            ).where(
                EdgePacket.company_id == access.company_id,
                EdgePacket.kind == "shift",
                EdgePacket.station_id.in_(станции_см),
                EdgePacket.shift_internal_no.in_(номера_см),
            ).order_by(EdgePacket.received_at.desc())
        )).all()
        статус_см: dict[tuple[int | None, int | None], str | None] = {}
        for p in пакеты_см:
            k = (p.station_id, p.shift_internal_no)
            if k not in статус_см:  # первый по desc = последний пакет смены
                статус_см[k] = p.st
        for смена in смены.values():
            смена["readiness"] = _readiness(статус_см.get((смена["station_id"], смена["shift_no"])))

        # Красный — смена не уедет в бухгалтерию, как её ни перезагружай.
        # Считается по тем же правилам, что валят сборку пакета.
        блокеры, предупреждения_см = await _блокеры_смен(
            db, access.company_id,
            {(с["station_id"], с["shift_no"]) for с in смены.values()})
        for смена in смены.values():
            причины = блокеры.get((смена["station_id"], смена["shift_no"])) or []
            смена["blockers"] = причины
            смена["warnings"] = предупреждения_см.get(
                (смена["station_id"], смена["shift_no"])) or []
            if причины:
                смена["readiness"] = "r"

    итог = sorted(смены.values(),
                  key=lambda s: (s["finished_at"] or datetime.min.replace(tzinfo=timezone.utc),
                                 s["shift_no"]), reverse=True)
    for смена in итог:
        for поле in ("started_at", "finished_at"):
            смена[поле] = смена[поле].isoformat() if смена[поле] else None
    return {"shifts": итог[:limit], "total": len(итог)}


@router.get("/recompute")
async def recompute_status(
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пересчёт документов: какие смены сети ждут пересборки представления —
    станция прислала новый пакет ПОСЛЕ того, как реестр был собран (документ
    задним числом), поэтому себестоимость/остаток в центре устарели. Плюс дата
    запрета (последний закрытый период). Полный пересчёт себестоимости делает
    агент станции; кнопка «Пересобрать реестр» подтягивает его результат."""
    access = await resolve_document_access(user, db)
    охват = [
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.shift_no.isnot(None),
    ]
    станции_фильтр: list[int] | None = None
    if stations:
        коды = [v.strip() for v in stations.split(",") if v.strip()]
        if any(not v.isdigit() for v in коды):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Коды АЗС должны быть целыми числами")
        станции_фильтр = [int(v) for v in коды]
    elif not access.network and access.station_ids:
        станции_фильтр = sorted(access.station_ids)
    if станции_фильтр is not None:
        охват.append(StoreDocumentProjection.station_id.in_(станции_фильтр))

    # Последняя сборка проекции и состав по каждой смене.
    сборка = (await db.execute(select(
        StoreDocumentProjection.station_id, StoreDocumentProjection.shift_no,
        func.max(StoreDocumentProjection.rebuilt_at).label("built"),
        func.count().label("docs"),
        func.sum(StoreDocumentProjection.amount).label("amount"),
        func.max(StoreDocumentProjection.document_at).label("closed"),
    ).where(*охват).group_by(
        StoreDocumentProjection.station_id, StoreDocumentProjection.shift_no,
    ))).all()
    свод = {(r.station_id, r.shift_no): r for r in сборка}

    # Последний приезд пакета по смене (новее сборки = данные изменились после).
    pk_conds = [EdgePacket.company_id == access.company_id,
                EdgePacket.shift_internal_no.isnot(None)]
    if станции_фильтр is not None:
        pk_conds.append(EdgePacket.station_id.in_(станции_фильтр))
    приезды = (await db.execute(select(
        EdgePacket.station_id, EdgePacket.shift_internal_no,
        func.max(EdgePacket.received_at).label("arr"),
    ).where(*pk_conds).group_by(
        EdgePacket.station_id, EdgePacket.shift_internal_no,
    ))).all()

    ждут: list[dict] = []
    for p in приезды:
        r = свод.get((p.station_id, p.shift_internal_no))
        if r is None or r.built is None or p.arr is None or p.arr <= r.built:
            continue
        ждут.append({
            "station_id": p.station_id, "shift_no": p.shift_internal_no,
            "documents": int(r.docs), "amount": float(r.amount or 0),
            "closed_at": r.closed.isoformat() if r.closed else None,
            "built_at": r.built.isoformat(),
            "arrived_at": p.arr.isoformat(),
        })
    ждут.sort(key=lambda x: x["arrived_at"], reverse=True)

    # Дата запрета — последний закрытый период компании (правки до неё запрещены).
    закрытый = (await db.execute(select(Period.year, Period.month).where(
        Period.company_id == access.company_id, Period.status == "closed",
    ).order_by((Period.year * 12 + Period.month).desc()).limit(1))).first()
    запрет = f"{закрытый.year}-{закрытый.month:02d}" if закрытый else None

    последняя_сборка = max((r.built for r in сборка if r.built), default=None)
    return {
        "rebuilt_at": последняя_сборка.isoformat() if последняя_сборка else None,
        "freeze_period": запрет,
        "shifts_total": len(свод),
        "waiting": ждут,
    }


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

    # Товарная часть смены — из первичных edge-пакетов (проекции хранят лишь
    # ссылки на строки, а shift_detail собирает данные ЦБ и станцию 208 не
    # покрывает). Продажи и оплаты лежат в пакете смены (retail_sale_sidegoods),
    # выпуск блюд и рецептура — в пакете production. Имена номенклатуры (UUID)
    # резолвим справочником ЦБ.
    from app.services.goods_dashboard import GoodsDashboardService
    nom = await GoodsDashboardService(db, access.company_id)._names()

    def _имя(guid, запас=""):
        n = nom.get(guid)
        return n.name if n else (запас or "—")

    продажи: list[dict] = []
    оплаты: list[dict] = []
    for док in (payload.get("Документы") or []):
        if док.get("Тип") != "retail_sale_sidegoods":
            continue
        for стр in (док.get("Товары") or []):
            продажи.append({
                # GUID номенклатуры — по нему сопутка раскрывается карточкой товара.
                "guid": стр.get("Номенклатура"),
                "name": _имя(стр.get("Номенклатура"), стр.get("ШтрихКод")),
                "cls": стр.get("КлассSKU"),
                "qty": float(стр.get("Количество") or 0),
                "price": float(стр.get("Цена") or 0),
                "amount": float(стр.get("Сумма") or 0),
                "vat": float(стр.get("СуммаНДС") or 0),
            })
        for опл in (док.get("Оплаты") or []):
            оплаты.append({"form": опл.get("ВидОплаты") or "—",
                           "amount": float(опл.get("Сумма") or 0)})
    продажи.sort(key=lambda x: -x["amount"])
    оплаты.sort(key=lambda x: -x["amount"])

    блюда: list[dict] = []
    prod_пакет = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == access.company_id,
        EdgePacket.station_id == station_id,
        EdgePacket.shift_internal_no == shift_no,
        EdgePacket.kind == "production",
    ).order_by(EdgePacket.received_at.desc()).limit(1))).scalars().first()
    if prod_пакет and prod_пакет.payload:
        ингр_по_блюду: dict[str, list] = {}
        for док in (prod_пакет.payload.get("Документы") or []):
            if док.get("Тип") != "production_release":
                continue
            for ингр in (док.get("Ингредиенты") or []):
                did = str(ингр.get("ИдентификаторПродукция") or "")
                ингр_по_блюду.setdefault(did, []).append({
                    "name": _имя(ингр.get("Номенклатура")),
                    "qty": float(ингр.get("Количество") or 0),
                    "unit": ингр.get("Единица"),
                })
            for бл in (док.get("ВыпускБлюд") or []):
                did = str(бл.get("Идентификатор") or "")
                блюда.append({
                    # GUID блюда — ключ сопоставления с проданной позицией. По имени
                    # сопоставлять нельзя: у общепита 208 живут тёзки, различающиеся
                    # точкой в конце («Капучино 400 мл» и «Капучино 400 мл.»), и у них
                    # РАЗНЫЕ составы — по имени рецептура подменялась бы чужой.
                    # Сам агент связывает карту с блюдом по dish_uuid, а не по имени.
                    "guid": бл.get("Номенклатура"),
                    "name": бл.get("Наименование") or _имя(бл.get("Номенклатура")),
                    "qty": float(бл.get("Количество") or 0),
                    "amount": float(бл.get("Сумма") or 0),
                    "recipe": ингр_по_блюду.get(did, []),
                })

    # Склад-документы дня: поступления, инвентаризации, списания, перемещения,
    # оприходования — с товарными строками, из edge-пакетов станции за дату смены.
    # Их выносим отдельным табом «Склад», чтобы не листать вниз (решение МАГа).
    склад: list[dict] = []
    _шапка_дня = payload.get("Смена") or {}
    день_смены = str(
        _шапка_дня.get("Закрытие") or _шапка_дня.get("Открытие")
        or (конец.isoformat() if конец else "")
    )[:10]
    if день_смены:
        склад_пакеты = (await db.execute(select(EdgePacket).where(
            EdgePacket.company_id == access.company_id,
            EdgePacket.station_id == station_id,
            EdgePacket.kind.in_(["receipt", "inventory", "gain", "writeoff", "transfer"]),
        ).order_by(EdgePacket.received_at.desc()).limit(80))).scalars().all()
        видано: set = set()
        for пак in склад_пакеты:
            for док in ((пак.payload or {}).get("Документы") or []):
                тип = док.get("Тип")
                if тип not in ("purchase", "inventory", "writeoff", "transfer", "gain"):
                    continue
                if str(док.get("Дата") or "")[:10] not in ("", день_смены):
                    continue
                ключ = str(док.get("ИсточникUUID") or док.get("Номер") or "")
                if ключ and ключ in видано:
                    continue
                видано.add(ключ)
                строки = []
                for стр in (док.get("Товары") or []):
                    строки.append({
                        "name": стр.get("Наименование") or _имя(стр.get("Номенклатура"), стр.get("ШтрихКод")),
                        "qty": float(стр.get("Количество") or 0),
                        "price": float(стр.get("Цена") or 0),
                        "amount": float(стр.get("Сумма") or 0),
                        "uchet": стр.get("КоличествоУчет"),
                        "dev": стр.get("Отклонение"),
                    })
                номер = str(док.get("Номер") or "")
                причина = str(док.get("Причина") or "")
                # Служебный документ — наше выравнивание остатка, не приход человека:
                # номер без номера (…-0000) или причина «привезли без документов» /
                # «исправление учёта» (baseline, перенос Дня X). Стоимости у него нет.
                служебный = номер.endswith("-0000") or причина in ("no_docs", "correction")
                склад.append({
                    "kind": тип, "number": док.get("Номер"),
                    "meta": str(док.get("ПричинаНаименование") or док.get("Комментарий") or ""),
                    "amount": float(док.get("СуммаДокумента") or 0),
                    "service": служебный,
                    "src_uuid": str(док.get("ИсточникUUID") or ""),
                    "record_id": None,
                    "lines": строки,
                })
        # Разрешаем клик по складскому документу: сопоставляем его ИсточникUUID с
        # проекцией (там живёт запись, которую открывает карточка документа).
        uuids = [d["src_uuid"] for d in склад if d["src_uuid"]]
        if uuids:
            пров = (await db.execute(select(
                StoreDocumentProjection.document_id, StoreDocumentProjection.id,
            ).where(
                StoreDocumentProjection.company_id == access.company_id,
                StoreDocumentProjection.is_primary.is_(True),
                StoreDocumentProjection.document_id.in_(uuids),
            ))).all()
            по_uuid = {str(r.document_id): str(r.id) for r in пров}
            for d in склад:
                d["record_id"] = по_uuid.get(d["src_uuid"])

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
    _бл, _пред = await _блокеры_смен(
        db, access.company_id, {(station_id, shift_no)})
    блокеры_смены = _бл.get((station_id, shift_no)) or []
    предупреждения_смены = _пред.get((station_id, shift_no)) or []

    return {
        "station_id": station_id,
        "shift_no": shift_no,
        "started_at": открытие or (начало.isoformat() if начало else None),
        "finished_at": закрытие or (конец.isoformat() if конец else None),
        "status": светофор,
        # Светофор листа и реестра — один источник, иначе смена зелёная в
        # списке и красная внутри. Блокеры перекрывают needs_review: смена с
        # непроведённой карточкой не уедет, сколько её ни перезагружай.
        "readiness": "r" if блокеры_смены else _readiness(светофор),
        "blockers": блокеры_смены,
        "warnings": предупреждения_смены,
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
        # Товарная часть смены, собранная из первичных пакетов: продажи по SKU,
        # свод оплат, выпуск блюд с рецептурой. Поступления/инвентаризации того
        # же дня — в «Повлияло» (они смене не принадлежат).
        "sales": продажи,
        "payments": оплаты,
        "dishes": блюда,
        "stock": склад,
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
    # Карточки-счётчики наверху — четыре из StoreDocumentStats. waiting_receipt
    # живёт в COUNTER_CONDITIONS только как фильтр-переход из Разбора, своей
    # карточки-числа не имеет — в статистику его не берём (иначе столбцы stats
    # разъезжаются с фронтом и с тестовым мок-рядом).
    counter_names = tuple(k for k in COUNTER_CONDITIONS if k != "waiting_receipt")
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
    briefs = [_brief(row) for row in rows]
    # Имя переоценённого товара — чтобы в реестре было видно, О ЧЁМ переоценка,
    # а не только «199 → 189 ₽». Резолвим одним справочником на страницу.
    if any(b.get("revaluation") and b["revaluation"].get("item") for b in briefs):
        from app.services.goods_dashboard import GoodsDashboardService
        имена = await GoodsDashboardService(db, access.company_id)._names()
        for b in briefs:
            рев = b.get("revaluation")
            if рев and рев.get("item"):
                карта = имена.get(рев["item"])
                if карта is not None:
                    рев["name"] = карта.name
    return {
        "documents": briefs, "total": int(total),
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
    # Строки приезжают с номенклатурой-UUID и без наименования (выпуск блюд,
    # ингредиенты) — резолвим GUID в имя, иначе карточка показывает GUID «что
    # это за блюда?». Имя проставляем, только если своего наименования нет.
    from app.services.goods_dashboard import GoodsDashboardService
    имена = await GoodsDashboardService(db, access.company_id)._names()

    def _подставить_имена(строки: object) -> None:
        for стр in строки if isinstance(строки, list) else []:
            if not isinstance(стр, dict) or стр.get("Наименование") or стр.get("name"):
                continue
            guid = стр.get("Номенклатура") or стр.get("НоменклатураUUID") or стр.get("item_uuid")
            карта = имена.get(guid) if guid else None
            if карта is not None:
                стр["Наименование"] = карта.name

    _подставить_имена(safe_payload.get("lines"))
    _подставить_имена(safe_payload.get("services"))
    result = _brief(row)
    if result.get("revaluation") and result["revaluation"].get("item"):
        карта = имена.get(result["revaluation"]["item"])
        if карта is not None:
            result["revaluation"]["name"] = карта.name
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
