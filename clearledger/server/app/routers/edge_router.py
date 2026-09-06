"""
Приёмник пакетов edge-агентов АЗС (проект Ledger Edge, этап v0).

Агент станции работает за CGNAT, поэтому связь всегда исходящая: агент сам
приносит пакет смены, собранный напрямую из кассы NeftoMS. Аутентификация —
машинная, по X-Cloud-API-Key компании (тот же механизм, что у dedup-ingest).

Идемпотентность: повтор пакета с тем же ИдентификаторПакета получает 409 и
считается агентом успехом. Это единственный корректный ответ на обрыв связи
в момент ответа — иначе смена либо потеряется, либо задвоится.

Сырой пакет остаётся неизменным L1, а бухгалтерские факты идемпотентно
материализуются в канонические документы Ledger L2.
"""
import gzip
import hashlib
import logging
import zlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import (
    Company, Contract, Counterparty, DataEntry, EdgeAgent, EdgeDownlink, EdgeHeartbeat,
    EdgePacket, EdgePacketProcessingIssue, EdgePacketRevision, Organization,
    SpaceInboundKey, StoreReceipt, Warehouse,
)

log = logging.getLogger(__name__)
from app.services.store_document_sync import сверить_документы
from app.services import (edge_nsi, edge_projection, edge_service, edge_stock,
                          edge_transfers, recipe_versions, store_receipts as receipt_rules)
from app.services import store_receipt_accounting
from app.services import sku as sku_pool
from app.services import partner_sync

router = APIRouter(prefix="/edge", tags=["Edge (агенты АЗС)"])

MAX_UNPACKED = 64 * 1024 * 1024   # потолок распаковки: смена ~200 КБ
MAX_BODY = 25 * 1024 * 1024  # смена ~200 КБ; запас на снимки остатков


@dataclass(frozen=True)
class EdgeIdentity:
    company: Company
    station_id: int
    key_id: uuid.UUID


async def get_edge_identity(
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> EdgeIdentity:
    key_hash = hashlib.sha256(x_cloud_api_key.encode()).hexdigest()
    key = (await db.execute(select(SpaceInboundKey).where(
        SpaceInboundKey.key_hash == key_hash,
        SpaceInboundKey.revoked_at.is_(None),
    ))).scalar_one_or_none()
    if key is None or key.station_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Для загрузки пакетов нужен именной ключ, привязанный к станции",
        )
    company = await db.get(Company, key.company_id)
    agent = (await db.execute(select(EdgeAgent.id).where(
        EdgeAgent.company_id == key.company_id,
        EdgeAgent.station_id == key.station_id,
    ))).scalar_one_or_none()
    if company is None or agent is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ключ станции не связан с зарегистрированным EdgeAgent",
        )
    key.last_used_at = datetime.now(timezone.utc)
    return EdgeIdentity(company, int(key.station_id), key.id)


async def станция_ключа(
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> int | None:
    """К какой АЗС привязан ключ, которым пришли: None — ключ компании.

    Телеметрия, очередь заданий и подтверждение брали номер станции из тела
    запроса и верили ему на слово. Внутри одной компании это значит, что ключом
    одной АЗС можно прочитать и погасить очередь другой — включая снимок прав
    (`user_roster`) и заливку НСИ. Пакеты так не проверялись никогда: там номер
    сверяется с ключом (`get_edge_identity`). Здесь делаем то же самое, но мягко:
    легаси-ключ компании станцию не подтверждает и работает как раньше — иначе
    отвалились бы внешние узлы, ещё не переведённые на именные ключи.
    """
    key_hash = hashlib.sha256(x_cloud_api_key.encode()).hexdigest()
    key = (await db.execute(select(SpaceInboundKey).where(
        SpaceInboundKey.key_hash == key_hash,
        SpaceInboundKey.revoked_at.is_(None),
    ))).scalar_one_or_none()
    if key is None or key.station_id is None:
        return None
    return int(key.station_id)


def сверить_станцию(станция_по_ключу: int | None, заявленная: int) -> int:
    if станция_по_ключу is not None and станция_по_ключу != заявленная:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Ключ станции {станция_по_ключу} не имеет права на станцию {заявленная}",
        )
    return заявленная


@router.get("/health")
async def health(company: Company = Depends(get_company_by_api_key)):
    """Проверка доступности мастера агентом (без передачи данных)."""
    return {"status": "ok", "company": company.slug}


# Желаемая версия агента: центр говорит станции, какой код считается текущим.
# Само обновление агент НЕ выполняет автоматически — сначала это должно стать
# осознанной операцией с откатом; пока станция лишь показывает расхождение,
# а «Магазин» видит парк версий.
#
# В переменной окружения, а не константой: номер версии меняется каждым
# релизом агента, и пересобирать ради него образ backend — глупо.
DESIRED_AGENT_VERSION = os.environ.get("EDGE_DESIRED_AGENT_VERSION", "1.99.0")


# Обстоятельства выгрузки, а не её содержание. При каждой пересборке пакета
# агент проставляет новое время и производный хеш конверта — при том, что
# документы внутри те же. Учитывать их в хеше содержимого значит объявлять
# «пакет изменился» на любой повторной отправке: у чеков UUID считается от
# состава документов, поэтому повтор приходил с тем же UUID и другим хешем и
# оседал в needs_review неразобранным. Так на 208 застрял пакет 09.08.
#
# Имён у времени выгрузки два: «ВремяВыгрузки» шлют пакеты смены, «Выгружен» —
# конверт формата 3 (рецептуры станции). Пока знали только первое, рецептуры
# 208 легли в needs_review с идентичным содержимым — 10.08.
_ОБСТОЯТЕЛЬСТВА_ВЫГРУЗКИ = ("ВремяВыгрузки", "Выгружен", "ХешПакета")


def _порядконезависимо(значение):
    """Форма, где перестановка элементов списка ничего не меняет.

    Агент читает свои таблицы без ORDER BY, поэтому один и тот же набор
    приезжает то в одном порядке, то в другом: 32 рецептуры станции 208
    приехали дважды одинаковыми и разошлись только порядком в массиве.
    Сортировка идёт по каноническому тексту элемента — платим лишней
    сериализацией на пакет (раз в час), но не заводим ложных перевыгрузок.
    """
    if isinstance(значение, dict):
        return {k: _порядконезависимо(v) for k, v in значение.items()}
    if isinstance(значение, list):
        return sorted(
            (_порядконезависимо(v) for v in значение),
            key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")),
        )
    return значение


def _raw_payload_hash(payload: dict) -> str:
    содержимое = {k: _порядконезависимо(v) for k, v in (payload or {}).items()
                  if k not in _ОБСТОЯТЕЛЬСТВА_ВЫГРУЗКИ}
    canonical = json.dumps(
        содержимое, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _derived_error(exc: Exception) -> str:
    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return f"{type(exc).__name__}: {detail}"[:4000]


def _manual_receipt_candidate_pending(receipt: StoreReceipt) -> bool:
    evidence = receipt.evidence or {}
    error = str(receipt.accounting_error or "").casefold()
    return bool(evidence.get("manual_candidate_ids")) or (
        receipt.accounting_status == "needs_review"
        and ("ручн" in error or "другим документом" in error)
    )


async def _persist_edge_revision_error(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    edge_packet_id: uuid.UUID,
    packet_uuid: str,
    content_hash: str,
    payload: dict,
    size_bytes: int,
    wire_size_bytes: int | None,
    error: str,
) -> None:
    await db.rollback()
    error_hash = hashlib.sha256(error.encode("utf-8")).hexdigest()
    revision = (await db.execute(select(EdgePacketRevision).where(
        EdgePacketRevision.company_id == company_id,
        EdgePacketRevision.packet_uuid == packet_uuid,
        EdgePacketRevision.content_hash == content_hash,
    ).with_for_update())).scalar_one_or_none()
    if revision is None:
        revision = EdgePacketRevision(
            id=uuid.uuid4(), company_id=company_id, edge_packet_id=edge_packet_id,
            packet_uuid=packet_uuid, content_hash=content_hash, payload=payload,
            size_bytes=size_bytes, wire_size_bytes=wire_size_bytes,
            status="needs_review", error=error,
        )
        db.add(revision)
        await db.flush()
    await db.execute(pg_insert(EdgePacketProcessingIssue).values(
        id=uuid.uuid4(), company_id=company_id,
        edge_packet_id=edge_packet_id, revision_id=revision.id,
        packet_uuid=packet_uuid, content_hash=content_hash,
        phase="derived", status="needs_review",
        error=error, error_hash=error_hash,
    ).on_conflict_do_nothing(
        index_elements=["company_id", "packet_uuid", "content_hash", "error_hash"],
    ))
    await db.commit()


def _номер_версии(версия: str | None) -> tuple[int, ...]:
    """Версия в сравнимый вид: «1.263.0» → (1, 263, 0).

    Строкой сравнивать нельзя: «1.9.0» тогда больше «1.263.0», и отставшей
    объявляется самая свежая станция.
    """
    части = []
    for кусок in str(версия or "").split("."):
        цифры = "".join(c for c in кусок if c.isdigit())
        части.append(int(цифры) if цифры else 0)
    return tuple(части) if части else (0,)


async def desired_version(db: AsyncSession, company: Company | None) -> str:
    """Какая версия агента считается текущей.

    Раньше её объявлял человек в интерфейсе, и она немедленно устаревала: агента
    выкатывали, а объявление забывали — станция начинала писать в журнал
    «центр ожидает другую версию» каждую минуту, хотя расхождение ничему не
    мешает (решение МАГа 31.08.2026, ручное объявление убрано).

    Теперь текущая — **та, что реально работает в парке**: максимальная из
    версий живых агентов. Отставшей считается станция ниже неё, и это
    единственный вопрос, ради которого версия вообще нужна: «кого пора
    обновить». Пока агентов нет вовсе — значение из окружения, чтобы первой
    станции было с чем сравниться.
    """
    if company is None:
        return DESIRED_AGENT_VERSION
    версии = (await db.execute(
        select(EdgeAgent.version).where(
            EdgeAgent.company_id == company.id,
            EdgeAgent.version.isnot(None),
        )
    )).scalars().all()
    живые = [v for v in версии if str(v).strip()]
    if not живые:
        return DESIRED_AGENT_VERSION
    return max(живые, key=_номер_версии)


async def _ingest_receipts(db: AsyncSession, company_id, station_id: int,
                           payload: dict, docs: list) -> None:
    """Развернуть документы `purchase` пакета в документы приёмки центра.

    Сначала ищем единый document_id, затем ИсточникUUID старого пакета и только
    затем бизнес-ключ накладной. Строка блокируется до конца транзакции.
    """
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("Тип") != "purchase":
            continue
        source_uuid = doc.get("ИсточникUUID") or payload.get("ИдентификаторПакета")
        if not source_uuid:
            continue
        format_version = str(payload.get("ВерсияФормата") or "2")
        canonical_errors: list[str] = []
        raw_document_id = str(doc.get("document_id") or "").strip()
        try:
            document_id = uuid.UUID(raw_document_id) if raw_document_id else None
        except ValueError:
            document_id = None
            canonical_errors.append("purchase.document_id должен быть UUID")
        if document_id is None:
            if format_version == "3":
                canonical_errors.append("purchase v3 не содержит canonical document_id")
            document_id = uuid.uuid5(
                uuid.UUID(str(company_id)), f"edge-purchase:{source_uuid}")

        advisory_key = int.from_bytes(hashlib.sha256(
            f"{company_id}:{document_id}".encode()).digest()[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(advisory_key)))
        existing = (await db.execute(select(StoreReceipt).where(
            StoreReceipt.company_id == company_id,
            StoreReceipt.id == document_id,
        ).with_for_update())).scalar_one_or_none()
        if existing is None:
            existing = (await db.execute(select(StoreReceipt).where(
                StoreReceipt.company_id == company_id,
                StoreReceipt.source_uuid == str(source_uuid),
            ).with_for_update())).scalar_one_or_none()

        lines = [{
            "line_id": item.get("line_id") or item.get("ИдентификаторСтроки"),
            "Key": item.get("Key"),
            "НомерСтроки": item.get("НомерСтроки"),
            "nomenclature_ref": item.get("Номенклатура") or None,
            "name": item.get("Наименование") or "",
            "barcode": item.get("ШтрихКод") or None,
            "qty_expected": float(item.get("КоличествоЗаявлено") or 0),
            "qty_fact": float(item.get("Количество") or 0),
            "price": float(item.get("Цена") or 0),
            "vat_rate": item.get("СтавкаНДС"),
            "vat_amount": float(item.get("СуммаНДС") or 0),
            "amount": float(item.get("Сумма") or 0),
            "unit": item.get("Единица") or "",
            "series": item.get("Серия") or None,
            "expiry": item.get("ГоденДо") or None,
            "mark_codes": item.get("КодыМаркировки") or [],
            "retail_price": float(item.get("ЦенаРозничная") or 0),
            "markup": float(item.get("ПроцентНаценки") or 0),
            "pack_factor": float(item.get("КоэффициентУпаковки") or 0),
            "purpose": item.get("МестоОприходования") or None,
            "no_card": bool(item.get("КарточкаНеОпознана")),
        } for item in doc.get("Товары") or []]
        services = [{
            "line_id": item.get("line_id") or item.get("ИдентификаторСтроки"),
            "Key": item.get("Key"),
            "НомерСтроки": item.get("НомерСтроки"),
            "name": item.get("Наименование") or "",
            "amount": item.get("Сумма") or 0,
            "vat_rate": item.get("СтавкаНДС"),
            "vat_amount": item.get("СуммаНДС") or 0,
            "into_cost": bool(item.get("ВСебестоимость")),
        } for item in doc.get("Услуги") or []]
        try:
            lines = receipt_rules.normalize_lines(lines)
            services = receipt_rules.normalize_services(services)
            lines, services = receipt_rules.ensure_line_ids(document_id, lines, services)
        except receipt_rules.ReceiptValidationError as exc:
            if "Неразличимые legacy-строки" in str(exc):
                lines, services = receipt_rules.assign_provisional_ambiguous_line_ids(
                    document_id, lines, services,
                )
                canonical_errors.append(str(exc))
                canonical_errors.append("Требуется подтверждение постоянных line_id")
            else:
                raise HTTPException(422, f"purchase: {exc}") from exc
        total_amount, vat_amount = receipt_rules.totals(lines, services)

        doc_date = doc.get("Дата")
        try:
            parsed = datetime.fromisoformat(doc_date) if doc_date else datetime.now(timezone.utc)
        except ValueError:
            parsed = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        incoming_raw = doc.get("ДатаВходящегоДокумента") or doc.get("incoming_date")
        if not incoming_raw and format_version != "3":
            incoming_raw = doc_date
        try:
            incoming_date = receipt_rules.parse_datetime(
                incoming_raw, "Дата входящего документа")
        except receipt_rules.ReceiptValidationError:
            incoming_date = None
            canonical_errors.append("Некорректна дата входящего документа")
        supplier = str(doc.get("Контрагент") or "").strip() or None
        incoming_number = str(doc.get("НомерВходящегоДокумента") or "").strip() or None
        if not supplier or not incoming_number or incoming_date is None:
            canonical_errors.append("Не заполнено основание накладной поставщика")

        async def exact_reference(model, raw_value, label, *, external=False):
            raw_value = str(raw_value or "").strip()
            if not raw_value:
                canonical_errors.append(f"Не заполнен canonical {label}")
                return None
            try:
                reference_id = uuid.UUID(raw_value)
            except ValueError:
                if format_version == "3" or not external:
                    canonical_errors.append(f"{label} должен быть UUID")
                    return None
                reference_id = None
            conditions = [model.id == reference_id] if reference_id else []
            if external:
                conditions.append(model.external_ref == raw_value)
            rows = (await db.execute(select(model).where(
                model.company_id == company_id,
                or_(*conditions),
            ).limit(2))).scalars().all()
            if len(rows) != 1:
                canonical_errors.append(
                    f"{label} не найден в компании" if not rows
                    else f"{label} сопоставлен неоднозначно")
                return None
            return rows[0]

        supplier_row = await exact_reference(
            Counterparty, doc.get("supplier_id"), "supplier_id")
        # Поставщик — внешний контрагент. В базе такие помечены и «external»,
        # и «supplier»: второе пришло импортом поставщиков ЭДО. Требовать
        # только «external» значило отвергать как раз тех, кто помечен
        # поставщиком явно, — на этом застряла первая же накладная СИНТЕЗа.
        if supplier_row is not None and supplier_row.kind not in ("external", "supplier"):
            canonical_errors.append("supplier_id не является внешним контрагентом")
            supplier_row = None
        contract_row = await exact_reference(Contract, doc.get("contract_id"), "contract_id")
        organization_row = await exact_reference(
            Organization, doc.get("organization_id") or doc.get("Организация"),
            "organization_id", external=True)
        warehouse_row = await exact_reference(
            Warehouse, doc.get("warehouse_id") or doc.get("Склад"),
            "warehouse_id", external=True)
        if supplier_row is not None:
            supplier = supplier_row.name
        if contract_row is not None and supplier_row is not None:
            supplier_keys = {str(supplier_row.id), str(supplier_row.external_ref or "")}
            if str(contract_row.counterparty_id) not in supplier_keys:
                canonical_errors.append("Договор принадлежит другому поставщику")
            kind = str(contract_row.kind or contract_row.type or "").casefold().replace(" ", "")
            if "споставщик" not in kind:
                canonical_errors.append("Договор не является договором с поставщиком")
        if contract_row is not None and organization_row is not None:
            organization_keys = {str(organization_row.id), str(organization_row.external_ref or "")}
            if str(contract_row.organization_id) not in organization_keys:
                canonical_errors.append("Организация не совпадает с договором")

        business_key = receipt_rules.receipt_dedup_key(
            supplier_row.id if supplier_row else None, supplier, incoming_number, incoming_date)
        if business_key:
            business_lock = int.from_bytes(hashlib.sha256(
                f"{company_id}:receipt-basis:{business_key}".encode()).digest()[:8],
                "big", signed=True)
            await db.execute(select(func.pg_advisory_xact_lock(business_lock)))
        manual_candidate_ids: list[str] = []
        if existing is None and business_key:
            candidates = (await db.execute(select(StoreReceipt).where(
                StoreReceipt.company_id == company_id,
                StoreReceipt.dedup_key == business_key,
            ).limit(2).with_for_update())).scalars().all()
            if candidates:
                manual_candidate_ids = [str(candidate.id) for candidate in candidates]
                canonical_errors.append(
                    "Основание накладной совпало с другим документом; требуется ручное решение"
                )
                business_key = None

        mchd_until = None
        signed_at = None
        try:
            if doc.get("МЧДДействительнаДо"):
                mchd_until = date.fromisoformat(str(doc["МЧДДействительнаДо"]))
        except ValueError:
            canonical_errors.append("Некорректен срок МЧД")
        try:
            if doc.get("ДатаПодписания"):
                signed_at = datetime.fromisoformat(str(doc["ДатаПодписания"]))
        except ValueError:
            canonical_errors.append("Некорректна дата подписания")

        evidence = {
            "document_id": raw_document_id or None,
            "packet_uuid": str(payload.get("ИдентификаторПакета") or ""),
            "packet_hash": payload.get("ХешПакета"),
            "organization_id": doc.get("organization_id") or doc.get("Организация"),
            "warehouse_id": doc.get("warehouse_id") or doc.get("Склад"),
            "currency": doc.get("ВалютаДокумента"),
            "vat_included": doc.get("СуммаВключаетНДС"),
            "invoice_kind": doc.get("ВидДокументаНДС"),
            "invoice_number": doc.get("НомерСчетаФактуры"),
            "invoice_date": doc.get("ДатаСчетаФактуры"),
            "vat_deductible": doc.get("НДСКВычету"),
            "source_kind": doc.get("СхемаПриобретения"),
            "purchased_by": doc.get("ПодотчетноеЛицо"),
            "payment_kind": doc.get("СпособОплаты"),
            "fiscal_receipt": doc.get("ФискальныйЧек"),
            "purpose": doc.get("МестоОприходования"),
            "declared_goods_total": doc.get("ИтогоТоваров"),
            "declared_services_total": doc.get("ИтогоУслуг"),
            "declared_vat_total": doc.get("СуммаНДС"),
            "declared_total": doc.get("СуммаДокумента"),
            "legacy_basis": format_version != "3" and business_key is None,
            "line_identity_needs_review": any(
                "line_id" in error for error in canonical_errors
            ),
            "manual_candidate_ids": manual_candidate_ids or None,
        }
        evidence = {key: value for key, value in evidence.items() if value is not None}
        values = {
            "station_id": station_id, "number": str(doc.get("Номер") or "")[:40] or "б/н",
            "doc_date": parsed, "supplier": supplier,
            "supplier_id": supplier_row.id if supplier_row else None,
            "contract": contract_row.number if contract_row else doc.get("ДоговорКонтрагента") or None,
            "contract_id": contract_row.id if contract_row else None,
            "organization_id": organization_row.id if organization_row else None,
            "warehouse_id": warehouse_row.id if warehouse_row else None,
            "incoming_number": incoming_number, "incoming_date": incoming_date,
            "status": "accepted", "origin": "station",
            "delivery_scheme": doc.get("СхемаДоставки") or "supplier_to_station",
            "receiving_warehouse": (
                warehouse_row.name if warehouse_row else doc.get("СкладПриемки") or None),
            "signing_mode": doc.get("СхемаПодписания") or "office_director",
            "signer_name": doc.get("Подписант") or None,
            "author": doc.get("Автор") or None,
            "mchd_guid": doc.get("ИдентификаторМЧД") or None,
            "mchd_registry": doc.get("РеестрМЧД") or None,
            "mchd_valid_until": mchd_until,
            "signature_status": doc.get("СтатусЭП") or "pending",
            "signature_ref": doc.get("ИдентификаторЭП") or None,
            "signed_at": signed_at, "lines": lines, "services": services,
            "evidence": evidence, "dedup_key": business_key,
            "total_amount": total_amount, "vat_amount": vat_amount,
            "accepted_at": datetime.now(timezone.utc),
            "accounting_status": "needs_review" if canonical_errors else "pending",
            "accounting_error": "; ".join(dict.fromkeys(canonical_errors)) or None,
        }
        if existing is None:
            row = StoreReceipt(
                id=document_id, company_id=company_id,
                source_uuid=str(source_uuid)[:64], **values)
            db.add(row)
        else:
            if existing.status == "accepted":
                # Проведённый документ неизменяем — и это защита уровня базы
                # («accepted store receipt evidence is immutable»), а не
                # соглашение приёмника. Исправление со станции сюда не
                # применяется: сначала документ распроводят, и только потом он
                # принимает новую редакцию. Здесь остаётся отметить, что
                # редакция разошлась с принятой.
                if canonical_errors and existing.accounting_status != "ready":
                    store_receipt_accounting.mark_needs_review(existing, canonical_errors)
                if not _manual_receipt_candidate_pending(existing):
                    await receipt_rules.record_acceptance(db, existing)
                continue
            if existing.source_uuid is None:
                existing.source_uuid = str(source_uuid)[:64]
            # Происхождение читается ДО перезаписи полей: цикл ниже ставит
            # «station» всем подряд, и проверка после него смотрела бы на уже
            # затёртое значение — то есть всегда видела бы «station». Документ,
            # заведённый центром или пришедший по ЭДО, при первой же выгрузке со
            # станции переставал быть таковым, и разрез «кто завёл приёмку» врал.
            was_from = existing.origin
            for key, value in values.items():
                setattr(existing, key, value)
            existing.origin = was_from if was_from in ("center", "edo") else "station"
            existing.version = int(existing.version or 0) + 1
            row = existing
        await db.flush()
        if not _manual_receipt_candidate_pending(row):
            await receipt_rules.record_acceptance(db, row)


def _cheque_business_state(values: dict) -> dict:
    state = {key: value for key, value in values.items() if key != "packet_uuid"}
    moment = state.get("at")
    state["at"] = moment.isoformat() if isinstance(moment, datetime) else str(moment or "")
    try:
        state["total"] = format(
            Decimal(str(state.get("total") or 0)).quantize(Decimal("0.01")), "f")
    except (InvalidOperation, TypeError, ValueError):
        state["total"] = "0.00"
    return state


async def _ingest_cheques(db: AsyncSession, company_id, station_id: int,
                          payload: dict, packet_uuid: str) -> int:
    """Разложить пакет чеков смены в реестр.

    Идемпотентно по (станция, смена, ключ чека). Номер чека нумеруется отдельно
    на каждом посту; пакет считается полным снимком чеков смены, поэтому
    отсутствующие в новой ревизии старые строки удаляются.
    """
    from app.models import StoreCheque

    смена = payload.get("Смена") or {}
    номер_смены = int(смена.get("НомерСменыВнутр") or смена.get("НомерСмены") or 0)
    входящие = []
    есть_реестр = False
    for doc in payload.get("Документы") or []:
        if not isinstance(doc, dict) or doc.get("Тип") != "fiscal_receipts":
            continue
        есть_реестр = True
        входящие.extend(чек for чек in (doc.get("Чеки") or []) if isinstance(чек, dict))
    if not есть_реестр:
        return 0

    if not входящие:
        await db.execute(delete(StoreCheque).where(
            StoreCheque.company_id == company_id,
            StoreCheque.station_id == station_id,
            StoreCheque.shift_number == номер_смены,
        ))
        return 0

    существующие = (await db.execute(select(StoreCheque).where(
        StoreCheque.company_id == company_id,
        StoreCheque.station_id == station_id,
        StoreCheque.shift_number == номер_смены,
    ).with_for_update())).scalars().all()
    по_ключу = {
        str(getattr(row, "cash_key", "") or
            f"{int(getattr(row, 'cash_no', 0) or 0)}:{int(row.number)}"): row
        for row in существующие
    }
    принятые_ключи: set[str] = set()
    принято = 0
    for чек in входящие:
        номер = int(чек.get("Номер") or 0)
        if номер < 0:
            continue
        строки = []
        for line in чек.get("Товары") or []:
            incoming_scope = line.get("scope") or line.get("Контур")
            строки.append({
                "item_uuid": line.get("Номенклатура") or "",
                "name": line.get("Наименование") or "",
                "ns_code": line.get("КодНС"),
                "qty": float(line.get("Количество") or 0),
                "price": float(line.get("Цена") or 0),
                "amount": float(line.get("Сумма") or 0),
                "section": line.get("Секция"),
                "scope": incoming_scope or "store",
                "scope_source": (
                    line.get("scope_source")
                    or ("edge_explicit" if incoming_scope
                        else "edge_fiscal_receipts_filtered_v1")),
                "vat_rate": line.get("СтавкаНДС"),
                "vat_amount": (float(line.get("СуммаНДС"))
                               if line.get("СуммаНДС") is not None else None),
            })
        if not строки:
            continue
        момент = чек.get("Время")
        try:
            когда = (datetime.fromisoformat(момент) if момент
                     else datetime.now(timezone.utc))
        except ValueError:
            когда = datetime.now(timezone.utc)
        if когда.tzinfo is None:
            когда = когда.replace(tzinfo=timezone.utc)

        пост = int(чек.get("Пост") or 0)
        ключ = str(чек.get("КлючЧека") or "").strip() or f"{пост}:{номер}"
        существующий = по_ключу.get(ключ)
        значения = {
            "number": номер,
            "cash_no": пост,
            "cash_key": ключ,
            "fiscal_number": чек.get("ФН"),
            "at": когда,
            "is_return": bool(чек.get("Возврат")),
            "had_fuel": bool(чек.get("БылоТопливо")),
            "pay_type": чек.get("ВидОплаты"),
            "pay_name": (чек.get("ВидОплатыНазвание") or "")[:60] or None,
            "total": float(sum(
                (Decimal(str(line.get("amount") or 0)) for line in строки),
                Decimal("0"),
            )),
            "positions": len(строки),
            "lines": строки,
            "packet_uuid": packet_uuid,
        }
        if существующий is None:
            db.add(StoreCheque(company_id=company_id, station_id=station_id,
                               shift_number=номер_смены,
                               version=1, **значения))
        else:
            текущее = {
                "number": существующий.number,
                "cash_no": существующий.cash_no,
                "cash_key": существующий.cash_key,
                "fiscal_number": существующий.fiscal_number,
                "at": существующий.at,
                "is_return": существующий.is_return,
                "had_fuel": существующий.had_fuel,
                "pay_type": существующий.pay_type,
                "pay_name": существующий.pay_name,
                "total": существующий.total,
                "positions": существующий.positions,
                "lines": существующий.lines,
                "packet_uuid": существующий.packet_uuid,
            }
            if _cheque_business_state(текущее) != _cheque_business_state(значения):
                for k, v in значения.items():
                    setattr(существующий, k, v)
                существующий.version = int(существующий.version or 0) + 1
        принятые_ключи.add(ключ)
        принято += 1

    if принятые_ключи:
        await db.execute(delete(StoreCheque).where(
            StoreCheque.company_id == company_id,
            StoreCheque.station_id == station_id,
            StoreCheque.shift_number == номер_смены,
            StoreCheque.cash_key.not_in(принятые_ключи),
        ))
    return принято


async def _sync_stock_packet(db: AsyncSession, company_id, station_id: int,
                             payload: dict) -> dict:
    """Сохранить остаток независимо от старой общей проекции каталога.

    Сначала каталог, потом остаток — порядок здесь содержательный, а не
    оформительский. Проекция `edge.stock` кладёт строку через
    `INSERT … SELECT FROM edge.barcode WHERE code = …`: штрихкода нет — строки
    нет, и молча, без ошибки. Пока каталог синхронизировался вторым, ПЕРВЫЙ
    снимок с новым штрихкодом всегда терял по нему остаток: 11.08.2026 так
    пропали 3 автолампы, заведённые на станции часом раньше.
    """
    каталог = None
    try:
        каталог = await edge_nsi.sync_from_snapshot(db, station_id, payload)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.warning("станция %s: каталог снимка не синхронизирован: %s", station_id, exc)
        каталог = {"error": str(exc)[:200]}

    stock = await edge_stock.sync_from_snapshot(db, company_id, station_id, payload)
    await db.commit()
    # Снимок — момент, когда находки по станции меняются: касса, выгрузка,
    # минусы, ставки. Запоминаем их здесь, а не только когда кто-то откроет
    # экран, иначе история «появилось — ушло» зависела бы от чужого внимания.
    try:
        отчёт = await edge_service.stock_report(db, company_id, station_id)
        await edge_service.sync_alerts(
            db, company_id, station_id,
            edge_service.build_alerts(отчёт), edge_service.STOCK_TOPICS)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.warning("станция %s: находки не сохранены: %s", station_id, exc)
    if isinstance(каталог, dict) and "error" in каталог:
        return {"stock": stock, "catalog_error": каталог["error"]}
    return {"stock": stock, "catalog": каталог}


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    станция_ключа_: int | None = Depends(станция_ключа),
    db: AsyncSession = Depends(get_db),
):
    """Телеметрия агента станции: раз в минуту, тело маленькое.

    Отвечает тем, что станции нужно знать о центре: серверное время (у станций
    часы уходят), какая версия кода считается текущей. Это же делает индикатор
    у оператора честным: связь подтверждена не «пингом до роутера», а ответом
    мастера.
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, f"Тело не разобрано: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Ожидался объект телеметрии")

    station_id = body.get("station_id")
    if not isinstance(station_id, int):
        header = request.headers.get("X-Station-Id", "")
        if not header.isdigit():
            raise HTTPException(400, "Не определён код АЗС")
        station_id = int(header)
    station_id = сверить_станцию(станция_ключа_, int(station_id))

    row = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == company.id,
                                EdgeAgent.station_id == station_id)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = EdgeAgent(company_id=company.id, station_id=station_id, first_seen=now)
        db.add(row)
    row.version = str(body.get("version") or "")[:40] or None
    row.queue_pending = int(body.get("queue_pending") or 0)
    row.queue_sent = int(body.get("queue_sent") or 0)
    row.last_shift = body.get("last_shift") if isinstance(body.get("last_shift"), int) else None
    row.payload = body
    row.last_seen = now
    # След телеметрии: `edge_agents` помнит только последнее состояние, а
    # «сколько станция была недоступна за месяц» читается лишь по истории.
    db.add(EdgeHeartbeat(company_id=company.id, station_id=station_id, at=now,
                         version=row.version, queue_pending=row.queue_pending))
    await db.commit()

    # Артикулы: станция чеканит их из блока, нарезанного заранее. Момент для
    # нарезки — именно здесь: связь подтверждена, остаток номеров станция
    # только что сообщила. Ждать, пока номера кончатся у полки, нельзя —
    # к тому времени связи может не быть неделю.
    осталось_артикулов = body.get("sku_left")
    if not isinstance(осталось_артикулов, int):
        осталось_артикулов = None
    новый_блок = await sku_pool.обеспечить_блок(db, company.id, station_id, осталось_артикулов)
    if новый_блок is not None:
        db.add(EdgeDownlink(
            company_id=company.id, station_id=station_id, kind="sku_block",
            payload={"block_id": новый_блок["block_id"],
                     "from": новый_блок["from"], "to": новый_блок["to"]},
            note=f"артикулы {новый_блок['from_sku']}…{новый_блок['to_sku']}",
            idempotency_key=f"sku_block:{новый_блок['block_id']}"))
        await db.commit()
        log.info("АЗС %s: нарезан блок артикулов %s…%s (у станции оставалось %s)",
                 station_id, новый_блок["from_sku"], новый_блок["to_sku"],
                 осталось_артикулов if осталось_артикулов is not None else "неизвестно")

    # Границы кодов кассы станция получает от центра, а не держит в своём
    # конфиге: тридцать конфигов — это тридцать мест, где никто не видит, у кого
    # сколько номеров осталось. Задание идемпотентно по самим границам, поэтому
    # уходит один раз, а при их изменении — заново.
    пул = (await db.execute(text("""
        SELECT ns_code_min, ns_code_max FROM edge.station WHERE id = :st
    """), {"st": station_id})).first()
    # Границы обязаны лежать в товарном диапазоне нефтесервера: код ≥ 5200 касса
    # считает УСЛУГОЙ и ставит количество 1000 (подтверждено вендором). Отдать
    # станции max=5207 значило бы разрешить назначить товару код услуги — и
    # потом полный файл эту позицию молча выкинет. Не отдаём кривой пул вовсе,
    # чем отдать опасный: пусть станция работает на прежних границах.
    if пул is not None and пул.ns_code_min and пул.ns_code_max and (
            int(пул.ns_code_min) < 302 or int(пул.ns_code_max) > 5199
            or int(пул.ns_code_min) > int(пул.ns_code_max)):
        log.error("АЗС %s: пул кодов кассы вне товарного диапазона 302..5199 "
                  "(%s..%s) — задание не отправлено",
                  station_id, пул.ns_code_min, пул.ns_code_max)
        пул = None
    if пул is not None and пул.ns_code_min and пул.ns_code_max:
        ключ = f"ns_code_pool:{station_id}:{пул.ns_code_min}:{пул.ns_code_max}"
        уже = (await db.execute(select(EdgeDownlink.id).where(
            EdgeDownlink.company_id == company.id,
            EdgeDownlink.idempotency_key == ключ))).scalar_one_or_none()
        if уже is None:
            db.add(EdgeDownlink(
                company_id=company.id, station_id=station_id, kind="ns_code_pool",
                payload={"min": int(пул.ns_code_min), "max": int(пул.ns_code_max)},
                note=f"пул кодов кассы {пул.ns_code_min}…{пул.ns_code_max}",
                idempotency_key=ключ))
            await db.commit()

    # Справочники контрагентов — тем же приёмом, что артикулы и коды кассы:
    # состав сворачивается в отпечаток, отпечаток лежит в ключе задания. Не
    # менялось — не поедет; завели поставщика в центре — станция получит его
    # ближайшим тактом, не дожидаясь, пока кто-то вспомнит нажать «отправить».
    try:
        await partner_sync.обеспечить(db, company.id, station_id)
    except Exception as exc:  # noqa: BLE001
        # Телеметрия важнее справочника: станция не должна терять связь из-за
        # того, что у нас не собрался список поставщиков.
        await db.rollback()
        log.warning("АЗС %s: справочники контрагентов не досланы: %s", station_id, exc)

    pending = (await db.execute(
        select(func.count()).select_from(EdgeDownlink).where(
            EdgeDownlink.company_id == company.id,
            EdgeDownlink.station_id == station_id,
            EdgeDownlink.acked_at.is_(None),
            EdgeDownlink.cancelled_at.is_(None)))).scalar() or 0

    peers = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == company.id,
        EdgeAgent.station_id != station_id,
    ).order_by(EdgeAgent.station_id))).scalars().all()
    stations = []
    for peer in peers:
        silence = (now - peer.last_seen).total_seconds() if peer.last_seen else None
        details = peer.payload or {}
        stations.append({
            "station_id": peer.station_id,
            "name": details.get("station_name") or f"АЗС {peer.station_id}",
            "state": "онлайн" if silence is not None and silence <= 180 else "офлайн",
        })

    # Одним запросом на такт: версия парка нужна дважды, а heartbeat приходит
    # от каждой станции ежеминутно.
    текущая = await desired_version(db, company)
    return {
        "server_time": now.isoformat(),
        "desired_version": текущая,
        # Сколько заданий ждёт станцию: агент пойдёт за ними только если есть
        # что забирать — лишний запрос в минуту по LTE не нужен.
        "downlink_pending": int(pending),
        "stations": stations,
        # Отставшей считается станция НИЖЕ версии парка, а не «любая другая»:
        # та, что первой получила новую сборку, отставшей не является.
        "update_required": bool(
            row.version and _номер_версии(row.version) < _номер_версии(текущая)),
    }


@router.get("/downlink")
async def downlink(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    станция_ключа_: int | None = Depends(станция_ключа),
    db: AsyncSession = Depends(get_db),
):
    """Задания станции: то, что центр приготовил для неё.

    Агент забирает очередь сам — постучаться к станции за CGNAT нельзя.
    Отдаём неподтверждённые задания целиком: пакет, полученный, но не
    применённый (агент потерял связь до подтверждения), придёт повторно, и это
    нормально — приёмная сторона идемпотентна.
    """
    header = request.headers.get("X-Station-Id", "")
    if not header.isdigit():
        raise HTTPException(400, "Не определён код АЗС")
    station_id = сверить_станцию(станция_ключа_, int(header))

    # Идентификатор забираем ДО сверки: внутри неё есть commit, после которого
    # объект company истекает, и следующее обращение к `company.id` уходит в
    # ленивую подгрузку уже вне живой сессии — запрос падает с 500, а станция
    # остаётся без заданий молча: в её логе только «мастер ответил 500».
    company_id = company.id

    # Станция на связи — это и есть момент сверки: реестр документов освежается
    # и свежий снимок заголовков ложится в эту же очередь заданий. Иначе центр
    # и станция расходятся молча, пока человек не нажмёт кнопку.
    await сверить_документы(db, company_id, station_id)

    rows = (await db.execute(
        select(EdgeDownlink)
        .where(EdgeDownlink.company_id == company_id,
               EdgeDownlink.station_id == station_id,
               EdgeDownlink.acked_at.is_(None),
               # Отменённое центром станции не отдаём — иначе отмена
               # существовала бы только на экране.
               EdgeDownlink.cancelled_at.is_(None))
        .order_by(EdgeDownlink.created_at).limit(20)
    )).scalars().all()

    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        if r.delivered_at is None:
            r.delivered_at = now
        out.append({"id": str(r.id), "kind": r.kind, "payload": r.payload,
                    "created_at": r.created_at})
    await db.commit()
    return {"tasks": out, "count": len(out)}


@router.post("/downlink/{task_id}/ack")
async def downlink_ack(
    task_id: uuid.UUID,
    company: Company = Depends(get_company_by_api_key),
    станция_ключа_: int | None = Depends(станция_ключа),
    db: AsyncSession = Depends(get_db),
):
    """Станция применила задание. До этого момента оно будет приходить снова."""
    условия = [EdgeDownlink.id == task_id, EdgeDownlink.company_id == company.id]
    if станция_ключа_ is not None:
        # Гасить можно только своё: иначе задание чужой АЗС закрывается
        # неприменённым и центр считает его доставленным.
        условия.append(EdgeDownlink.station_id == станция_ключа_)
    row = (await db.execute(select(EdgeDownlink).where(*условия))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Задание не найдено")
    if row.acked_at is None:
        row.acked_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True}


@router.get("/agents")
async def agents(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Парк станций для «Магазина»: кто на связи, какой код, что в очереди."""
    желаемая = await desired_version(db, company)
    rows = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == company.id)
        .order_by(EdgeAgent.station_id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        silence = (now - r.last_seen).total_seconds() if r.last_seen else None
        # Три минуты молчания при heartbeat раз в минуту — это уже не «сеть
        # моргнула», а «связи нет». Час — станция явно требует внимания.
        state = "офлайн" if silence is None or silence > 180 else "онлайн"
        out.append({
            "station_id": r.station_id,
            "state": state,
            "silence_seconds": int(silence) if silence is not None else None,
            "version": r.version,
            "version_ok": r.version == желаемая,
            "desired_version": желаемая,
            "queue_pending": r.queue_pending,
            "queue_sent": r.queue_sent,
            "last_shift": r.last_shift,
            "last_seen": r.last_seen,
            "first_seen": r.first_seen,
            "details": r.payload,
        })
    return {"desired_version": желаемая, "agents": out,
            "online": sum(1 for a in out if a["state"] == "онлайн"), "total": len(out)}


async def _route_transfer_packet(
    db: AsyncSession, company_id, station_id: int, payload: dict,
) -> int:
    try:
        return await edge_transfers.route_transfer_tasks(
            db, company_id, station_id, payload)
    except edge_transfers.TransferRoutingError as exc:
        raise HTTPException(422, f"Перемещение не маршрутизировано: {exc}") from exc


# Этап D двусторонней синхронизации (docs/sync-dokumentov-centr-agent.html).
# Станция — владелец факта; изменённый ею документ (тот же packet_uuid, другой
# content_hash — дописана смена, поправлена приёмка) должен применяться сам, а
# не парковаться на ручной разбор. За флагом, по умолчанию ВЫКЛЮЧЕН: трогает
# боевой приёмный конвейер, включаем осознанно после проверки на 208.
AUTO_APPLY_REVISIONS = os.environ.get("EDGE_AUTO_APPLY_REVISIONS", "0") == "1"


async def _replay_edge_derived(
    db: AsyncSession, company_id, station_id: int,
    packet_kind: str, payload: dict, packet_uuid: str,
) -> None:
    """Переиграть derived-проекции (L2) пакета: снимки заменяют срез, документы
    UPSERT'ятся, project_packet детерминирован по source_id — всё идемпотентно,
    поэтому годится и для повторной доставки, и для новой ревизии станции."""
    payload = payload or {}
    docs = payload.get("Документы") or []
    if packet_kind == "station-recipes":
        await recipe_versions.ingest_station_bundle(
            db, company_id, station_id, payload.get("recipe_bundle") or {})
    if packet_kind == "transfer":
        await _route_transfer_packet(db, company_id, station_id, payload)
    await _ingest_receipts(db, company_id, station_id, payload, docs)
    if packet_kind == "cheques":
        await _ingest_cheques(db, company_id, station_id, payload, packet_uuid)
    if packet_kind == "station-catalog":
        await edge_nsi.ingest_station_catalog(db, company_id, station_id, docs)
    if packet_kind == "cash_state":
        await edge_nsi.ingest_cash_check(db, company_id, station_id, docs)
    if packet_kind in ("station-nsi", "station-mrc"):
        await edge_nsi.ingest_station_nsi(db, company_id, station_id, docs)
    if packet_kind == "stock":
        await _sync_stock_packet(db, company_id, station_id, payload)
    await edge_projection.project_packet(
        db, company_id, packet_uuid, station_id, payload)


@router.post("/packets", status_code=status.HTTP_201_CREATED)
async def receive_packet(
    request: Request,
    identity: EdgeIdentity = Depends(get_edge_identity),
    db: AsyncSession = Depends(get_db),
):
    """Принять пакет от агента станции. Тело — JSON, при Content-Encoding: gzip
    приходит сжатым (смена ~200 КБ → ~30 КБ, важно для LTE)."""
    company = identity.company
    # Идентификатор компании — ДО первой возможной ошибки: объект ORM истекает
    # после отката, и обращение к `company.id` из обработчика ошибки уходит в
    # ленивую подгрузку вне живой сессии. Приёмник отвечал 500, настоящая
    # причина терялась, а станция копила пакет в очереди (АЗС 8, 01.09.2026).
    company_id = company.id
    raw = await request.body()
    wire_size = len(raw)
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Пакет слишком большой")
    if request.headers.get("content-encoding", "").lower() == "gzip":
        # Распаковываем порциями с потолком. gzip.decompress() развернул бы
        # 25 МБ нулей в десятки гигабайт прямо в память процесса — ключа агента
        # (он лежит открытым текстом в config.json на машине в торговом зале)
        # для этого достаточно.
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = d.decompress(raw, MAX_UNPACKED)
            if d.unconsumed_tail:
                raise HTTPException(413, "Распакованный пакет слишком большой")
        except zlib.error as exc:
            raise HTTPException(400, f"Не удалось распаковать пакет: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Пакет не является корректным JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Ожидался объект пакета")

    packet_uuid = payload.get("ИдентификаторПакета") or request.headers.get("X-Packet-Uuid")
    if not packet_uuid:
        raise HTTPException(400, "В пакете нет ИдентификаторПакета")

    shift = payload.get("Смена") or {}
    station_id = shift.get("КодАЗС")
    if station_id is None:
        header_station = request.headers.get("X-Station-Id")
        if not header_station or not header_station.isdigit():
            raise HTTPException(400, "Не определён код АЗС")
        station_id = int(header_station)
    if int(station_id) != identity.station_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ключ EdgeAgent не имеет права отправлять данные этой станции",
        )
    packet_kind = request.headers.get("X-Packet-Kind") or "shift"
    raw_content_hash = _raw_payload_hash(payload)

    # Идемпотентность: повтор — не ошибка агента, а штатный исход обрыва связи.
    #
    # Но повтор бывает двух видов, и различает их хеш. Тот же UUID с тем же
    # хешем — дубль доставки, отвечаем 409 и на этом всё. Тот же UUID с ДРУГИМ
    # хешем — перевыгрузка: агент пересобрал смену после исправления (так было
    # со ставкой НДС, которую он брал у чужого кода нефтесервера). Отвергать её
    # значит навсегда оставить в мастере данные, о которых уже известно, что они
    # неверны — и никакая починка агента не долетит до сверки.
    existing = (await db.execute(
        select(EdgePacket).where(
            EdgePacket.company_id == company_id,
            EdgePacket.packet_uuid == packet_uuid,
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.station_id != int(station_id):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Пакет с таким идентификатором принадлежит другой станции")
        packet_kind = request.headers.get("X-Packet-Kind") or existing.kind
        previous_raw_hash = _raw_payload_hash(existing.payload or {})
        if raw_content_hash == previous_raw_hash:
            try:
                if packet_kind == "station-recipes":
                    await recipe_versions.ingest_station_bundle(
                        db, company_id, int(station_id),
                        (existing.payload or {}).get("recipe_bundle") or {})
                if packet_kind == "transfer":
                    await _route_transfer_packet(
                        db, company_id, int(station_id), existing.payload)
                await _ingest_receipts(
                    db, company_id, int(station_id), existing.payload,
                    (existing.payload or {}).get("Документы") or [],
                )
                if packet_kind == "cheques":
                    await _ingest_cheques(
                        db, company_id, int(station_id), existing.payload, str(packet_uuid))
                # Справочники переигрываем на повторе наравне с документами.
                # Их первый разбор ошибку только логирует (пакет уже принят), и
                # без этого повтор той же доставки ничего бы не починил: агент
                # шлёт снимок и черновики заново, а центр отвечал 409, не
                # прикоснувшись к мастер-НСИ. Оба разбора идемпотентны — снимок
                # заменяет срез целиком, черновики идут UPSERT'ом.
                # Значения объекта снимаем ДО разбора: внутри есть commit,
                # после которого `existing` истекает, и чтение его полей из
                # обработчика ошибки уходит в ленивую подгрузку вне сессии.
                existing_id = existing.id
                existing_payload = existing.payload or {}
                existing_size = existing.size_bytes
                existing_wire = existing.wire_size_bytes
                if packet_kind == "station-catalog":
                    await edge_nsi.ingest_station_catalog(
                        db, company_id, int(station_id),
                        existing_payload.get("Документы") or [])
                if packet_kind == "cash_state":
                    await edge_nsi.ingest_cash_check(
                        db, company_id, int(station_id),
                        existing_payload.get("Документы") or [])
                if packet_kind in ("station-nsi", "station-mrc"):
                    await edge_nsi.ingest_station_nsi(
                        db, company_id, int(station_id),
                        existing_payload.get("Документы") or [])
                if packet_kind == "stock":
                    await _sync_stock_packet(
                        db, company_id, int(station_id), existing_payload)
                уже_есть = (await db.execute(
                    select(func.count(DataEntry.id)).where(
                        DataEntry.company_id == company_id,
                        DataEntry.source == "edge",
                        DataEntry.meta["Edge"]["packet_uuid"].astext == str(packet_uuid),
                    )
                )).scalar_one()
                if not уже_есть:
                    await edge_projection.project_packet(
                        db, company_id, str(packet_uuid), int(station_id), existing_payload)
                await db.commit()
            except Exception as exc:
                await _persist_edge_revision_error(
                    db, company_id=company_id, edge_packet_id=existing_id,
                    packet_uuid=str(packet_uuid), content_hash=previous_raw_hash,
                    payload=existing_payload, size_bytes=existing_size,
                    wire_size_bytes=existing_wire, error=_derived_error(exc),
                )
                raise
            raise HTTPException(status.HTTP_409_CONFLICT, "Пакет уже принят ранее")
        revision = (await db.execute(select(EdgePacketRevision).where(
            EdgePacketRevision.company_id == company_id,
            EdgePacketRevision.packet_uuid == str(packet_uuid),
            EdgePacketRevision.content_hash == raw_content_hash,
        ))).scalar_one_or_none()
        if revision is None:
            db.add(EdgePacketRevision(
                id=uuid.uuid4(), company_id=company_id, edge_packet_id=existing.id,
                packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                # Статус ограничен CHECK ('received' | 'needs_review'), поэтому
                # факт автоприменения пишем пояснением, а не новым состоянием.
                status="needs_review",
                error=("новая ревизия станции применена к производному слою"
                       if AUTO_APPLY_REVISIONS
                       else "packet UUID повторён с другим raw content hash"),
            ))
        if AUTO_APPLY_REVISIONS:
            # Станция переписала свой документ (дописала смену, поправила приёмку).
            # Она владелец факта — новая версия истина, и её надо ДОВЕСТИ ДО L2.
            # Но сырьё доставки (L1) неприкосновенно: edge_packets и ревизии
            # append-only, переписывать существующий пакет нельзя (это ловит тест
            # test_stage3_ddl_and_raw_path_are_fail_closed_and_append_only).
            # Поэтому применяем новую версию только к производному слою, а сама
            # она остаётся в EdgePacketRevision(applied) как доказательство.
            # ⚠ НЕЗАВЕРШЕНО: полная пересборка реестра читает L1 и вернёт первую
            # версию — чтобы применённое пережило rebuild, адаптеру нужно брать
            # последнюю applied-ревизию. Пока флаг выключен, это не в бою.
            existing_id = existing.id
            await db.commit()
            try:
                await _replay_edge_derived(
                    db, company_id, int(station_id), packet_kind, payload, str(packet_uuid))
                await db.commit()
            except Exception as exc:
                await _persist_edge_revision_error(
                    db, company_id=company_id, edge_packet_id=existing_id,
                    packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                    payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                    error=_derived_error(exc),
                )
                raise
            return {
                "accepted": True, "packet_uuid": packet_uuid,
                "station_id": int(station_id), "applied_revision": True,
            }
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Пакет с тем же UUID и другим содержимым сохранён как needs_review",
        )

    packet_row = EdgePacket(
        id=uuid.uuid4(),
        company_id=company_id,
        packet_uuid=packet_uuid,
        station_id=int(station_id),
        kind=packet_kind,
        shift_number=str(shift.get("НомерСмены") or "") or None,
        shift_internal_no=shift.get("НомерСменыВнутр"),
        payload=payload,
        size_bytes=len(raw),
        wire_size_bytes=wire_size,
        source=str(payload.get("Источник") or "") or None,
    )
    db.add(packet_row)
    await db.flush()
    db.add(EdgePacketRevision(
        id=uuid.uuid4(), company_id=company_id, edge_packet_id=packet_row.id,
        packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
        payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
        status="received",
    ))
    # L1 фиксируется отдельной транзакцией. Ошибка любой derived-проекции ниже
    # не может откатить сырое доказательство доставки.
    await db.commit()
    try:
        routed = 0
        if packet_kind == "transfer":
            routed = await _route_transfer_packet(
                db, company_id, int(station_id), payload)
        docs = payload.get("Документы") or []
        await _ingest_receipts(db, company_id, int(station_id), payload, docs)
        if packet_kind == "cheques":
            await _ingest_cheques(
                db, company_id, int(station_id), payload, str(packet_uuid))
        # Сверка касса↔учёт — в общем derived-блоке, а НЕ отдельным try с
        # проглатыванием: снимок-состояние возвращается тем же UUID, и если
        # ошибку разбора проглотить (accepted), агент снимет пакет с повтора
        # (Enqueue дедупит по UUID), а неизменившееся состояние больше не
        # пришлёт — центр навсегда остался бы без этой сверки. Здесь ошибка
        # ведёт к revision_error и повтору, как у чеков.
        if packet_kind == "cash_state":
            await edge_nsi.ingest_cash_check(db, company_id, int(station_id), docs)
        projection = await edge_projection.project_packet(
            db, company_id, str(packet_uuid), int(station_id), payload)
        await db.commit()
    except Exception as exc:
        await _persist_edge_revision_error(
            db, company_id=company_id, edge_packet_id=packet_row.id,
            packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
            payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
            error=_derived_error(exc),
        )
        raise

    # Снимок наполняет мастер-НСИ: справочника штрихкодов в 1С не существует
    # (ШК там — измерение регистра), поэтому поток снимков со станции остаётся
    # единственным источником связи «карточка ↔ штрихкод ↔ код кассы».
    # Сбой синхронизации не должен отвергать пакет: данные уже приняты, а НСИ
    # догонит следующим снимком.
    # Черновики справочников и цены, назначенные станцией. Это не документы
    # учёта — они ничего не проводят; это заявка на признание, и разбирает её
    # человек в центре.
    # МРЦ станции идут своим видом пакета, но тем же разбором: документ у них
    # один (mrc_fact) и он не заявка — станция сообщает то, что напечатано на
    # пачке. Отдельный вид нужен, чтобы состояние справочника не смешивалось с
    # потоком событий и могло приезжать повторно без вреда.
    if packet_kind == "station-catalog":
        # Сверка каталога станции с сетевым: карточка, о которой центр не знает,
        # продаётся на полке и не попадает ни в один сетевой отчёт.
        try:
            await edge_nsi.ingest_station_catalog(db, company_id, int(station_id), docs)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning("станция %s: сводка каталога не разобрана: %s", station_id, exc)

    if packet_kind in ("station-nsi", "station-mrc"):
        try:
            await edge_nsi.ingest_station_nsi(db, company_id, int(station_id), docs)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning("станция %s: черновики не приняты: %s", station_id, exc)
            await _persist_edge_revision_error(
                db, company_id=company_id, edge_packet_id=packet_row.id,
                packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                error=_derived_error(exc),
            )

    recipe_stats = None
    if packet_kind == "station-recipes":
        try:
            recipe_stats = await recipe_versions.ingest_station_bundle(
                db, company_id, int(station_id), payload.get("recipe_bundle") or {})
        except Exception as exc:
            await _persist_edge_revision_error(
                db, company_id=company_id, edge_packet_id=packet_row.id,
                packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                error=_derived_error(exc),
            )
            raise

    nsi_stats = None
    if packet_kind == "stock":
        try:
            nsi_stats = await _sync_stock_packet(
                db, company_id, int(station_id), payload)
            if isinstance(nsi_stats, dict) and (
                nsi_stats.get("error") or nsi_stats.get("catalog_error")
            ):
                await _persist_edge_revision_error(
                    db, company_id=company_id, edge_packet_id=packet_row.id,
                    packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                    payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                    error=f"stock derived: {nsi_stats.get('error') or nsi_stats.get('catalog_error')}"[:4000],
                )
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            nsi_stats = {"error": str(exc)[:200]}
            await _persist_edge_revision_error(
                db, company_id=company_id, edge_packet_id=packet_row.id,
                packet_uuid=str(packet_uuid), content_hash=raw_content_hash,
                payload=payload, size_bytes=len(raw), wire_size_bytes=wire_size,
                error=_derived_error(exc),
            )

    return {
        "accepted": True,
        "packet_uuid": packet_uuid,
        "station_id": int(station_id),
        "shift": shift.get("НомерСмены"),
        "documents": len(docs),
        "recipes": recipe_stats,
        "size_bytes": len(raw),
        "wire_size_bytes": wire_size,
        "projection": projection,
        "nsi": nsi_stats,
        "routed_transfers": routed,
    }


@router.get("/packets")
async def list_packets(
    station_id: int | None = None,
    limit: int = 50,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Что уже принято — для сверки и диагностики."""
    q = select(EdgePacket).where(EdgePacket.company_id == company.id)
    if station_id is not None:
        q = q.where(EdgePacket.station_id == station_id)
    rows = (await db.execute(
        q.order_by(EdgePacket.received_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    return [{
        "packet_uuid": r.packet_uuid,
        "station_id": r.station_id,
        "shift": r.shift_number,
        "shift_internal_no": r.shift_internal_no,
        "kind": r.kind,
        "size_bytes": r.size_bytes,
        "wire_size_bytes": r.wire_size_bytes,
        "source": r.source,
        "received_at": r.received_at,
        "documents": len(r.payload.get("Документы") or []),
    } for r in rows]


@router.get("/reconcile")
async def reconcile(
    station_id: int | None = None,
    limit: int = 60,   # потолок ниже: см. min()
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Теневая сверка: пакет агента против пакета ЦБ по каждой смене.

    Критерий этапа v0 — `clean: true` четырнадцать дней подряд.
    """
    return await edge_service.reconcile(db, company.id, station_id,
                                        max(1, min(limit, 500)))


@router.get("/stock-report")
async def stock_report(
    station_id: int,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Сверка «касса ↔ учёт» по свежему снимку станции.

    Заменяет ручной разбор писем оператора: что лежит на складе, но не
    пробивается; чего нет в кассе вовсе; где разошлись количества; минусы
    физики; позиции без цены; устаревшие ставки НДС в карточках.
    """
    return await edge_service.stock_report(db, company.id, station_id)


@router.get("/alerts")
async def alerts(
    station_id: int,
    as_text: bool = False,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Что требует внимания по станции: касса, выгрузка, учёт, коды, сверка смен.

    `as_text=true` — готовый текст для письма или сообщения.
    """
    report = await edge_service.alerts(db, company.id, station_id)
    if as_text:
        return Response(content=edge_service.alerts_as_text(report),
                        media_type="text/plain; charset=utf-8")
    return report
