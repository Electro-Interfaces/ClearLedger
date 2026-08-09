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
import logging
import zlib
import json
import os
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import (
    Company, Contract, Counterparty, DataEntry, EdgeAgent, EdgeDownlink, EdgeHeartbeat,
    EdgePacket, Organization, StoreReceipt,
)

log = logging.getLogger(__name__)
from app.services import (edge_nsi, edge_projection, edge_service, edge_stock,
                          edge_transfers, recipe_versions, store_receipts as receipt_rules)

router = APIRouter(prefix="/edge", tags=["Edge (агенты АЗС)"])

MAX_UNPACKED = 64 * 1024 * 1024   # потолок распаковки: смена ~200 КБ
MAX_BODY = 25 * 1024 * 1024  # смена ~200 КБ; запас на снимки остатков


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
DESIRED_AGENT_VERSION = os.environ.get("EDGE_DESIRED_AGENT_VERSION", "1.39.0")


def desired_version(company: Company | None) -> str:
    """Целевая версия агента для компании.

    Объявляется в интерфейсе и хранится в настройках компании: раньше её знала
    только переменная окружения бэкенда, и «объявить новую версию» означало
    передеплоить стек. Переменная осталась значением по умолчанию — для
    компании, которая ничего не объявляла.
    """
    edge = ((company.customization or {}).get("edge") or {}) if company else {}
    return str(edge.get("desired_agent_version") or "").strip() or DESIRED_AGENT_VERSION


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
        raw_document_id = str(doc.get("document_id") or "").strip()
        if format_version == "3" and not raw_document_id:
            raise HTTPException(422, "purchase пакета формата 3 не содержит document_id")
        document_id = None
        if raw_document_id:
            try:
                document_id = uuid.UUID(raw_document_id)
            except ValueError as exc:
                raise HTTPException(422, "purchase.document_id должен быть UUID") from exc

        lock_value = f"{company_id}:{document_id or source_uuid}"
        advisory_key = int.from_bytes(
            __import__("hashlib").sha256(lock_value.encode()).digest()[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(advisory_key)))

        existing = None
        if document_id is not None:
            existing = (await db.execute(select(StoreReceipt).where(
                StoreReceipt.company_id == company_id,
                StoreReceipt.id == document_id,
            ).with_for_update())).scalar_one_or_none()
        if existing is None:
            existing = (await db.execute(select(StoreReceipt).where(
                StoreReceipt.company_id == company_id,
                StoreReceipt.source_uuid == str(source_uuid),
            ).with_for_update())).scalar_one_or_none()

        lines = []
        for item in doc.get("Товары") or []:
            lines.append({
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
                # Станция не опознала штрихкод — карточку заводит центр.
                "no_card": bool(item.get("КарточкаНеОпознана")),
            })
        services = [{
            "name": item.get("Наименование") or "",
            "amount": item.get("Сумма") or 0,
            "vat_rate": item.get("СтавкаНДС"),
            "vat_amount": item.get("СуммаНДС") or 0,
            "into_cost": bool(item.get("ВСебестоимость")),
        } for item in doc.get("Услуги") or []]
        try:
            lines = receipt_rules.normalize_lines(lines)
            services = receipt_rules.normalize_services(services)
        except receipt_rules.ReceiptValidationError as exc:
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
        except receipt_rules.ReceiptValidationError as exc:
            raise HTTPException(422, f"purchase: {exc}") from exc
        supplier = str(doc.get("Контрагент") or "").strip() or None
        incoming_number = str(doc.get("НомерВходящегоДокумента") or "").strip() or None
        raw_supplier_id = str(doc.get("supplier_id") or "").strip()
        if format_version == "3" and (not supplier or not incoming_number or incoming_date is None):
            raise HTTPException(422, "purchase: не заполнено основание накладной поставщика")
        business_key = receipt_rules.receipt_dedup_key(
            raw_supplier_id or None, supplier, incoming_number, incoming_date)
        if business_key:
            business_lock = int.from_bytes(
                __import__("hashlib").sha256(
                    f"{company_id}:receipt-basis:{business_key}".encode()).digest()[:8],
                "big", signed=True)
            await db.execute(select(func.pg_advisory_xact_lock(business_lock)))
        if existing is None and business_key:
            existing = (await db.execute(select(StoreReceipt).where(
                StoreReceipt.company_id == company_id,
                StoreReceipt.dedup_key == business_key,
            ).with_for_update())).scalar_one_or_none()

        mchd_until = None
        try:
            if doc.get("МЧДДействительнаДо"):
                mchd_until = date.fromisoformat(str(doc["МЧДДействительнаДо"]))
        except ValueError:
            mchd_until = None
        signed_at = None
        try:
            if doc.get("ДатаПодписания"):
                signed_at = datetime.fromisoformat(str(doc["ДатаПодписания"]))
        except ValueError:
            signed_at = None

        evidence = {
            **((existing.evidence or {}) if existing else {}),
            "document_id": str(document_id) if document_id else None,
            "packet_uuid": str(payload.get("ИдентификаторПакета") or ""),
            "packet_hash": payload.get("ХешПакета"),
            "organization_id": doc.get("Организация"), "warehouse_id": doc.get("Склад"),
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
            "declared_total": doc.get("СуммаДокумента"),
            "legacy_basis": format_version != "3" and business_key is None,
        }
        evidence = {key: value for key, value in evidence.items() if value is not None}
        supplier_id = existing.supplier_id if existing else None
        contract_id = existing.contract_id if existing else None
        if raw_supplier_id:
            try:
                parsed_supplier_id = uuid.UUID(raw_supplier_id)
            except ValueError as exc:
                raise HTTPException(422, "purchase.supplier_id должен быть UUID") from exc
            supplier_row = (await db.execute(select(Counterparty).where(
                Counterparty.id == parsed_supplier_id,
                Counterparty.company_id == company_id,
                Counterparty.kind == "external",
            ))).scalar_one_or_none()
            if supplier_row is None:
                raise HTTPException(422, "purchase.supplier_id не принадлежит организации")
            supplier_id = supplier_row.id
            supplier = supplier_row.name
        raw_contract_id = str(doc.get("contract_id") or "").strip()
        if raw_contract_id:
            if supplier_id is None:
                raise HTTPException(422, "purchase.contract_id передан без supplier_id")
            try:
                parsed_contract_id = uuid.UUID(raw_contract_id)
            except ValueError as exc:
                raise HTTPException(422, "purchase.contract_id должен быть UUID") from exc
            contract_row = (await db.execute(select(Contract).where(
                Contract.id == parsed_contract_id,
                Contract.company_id == company_id,
            ))).scalar_one_or_none()
            if contract_row is None:
                raise HTTPException(422, "purchase.contract_id не принадлежит организации")
            supplier_ref = (await db.execute(select(Counterparty).where(
                Counterparty.id == supplier_id,
                Counterparty.company_id == company_id,
            ))).scalar_one()
            supplier_keys = {str(supplier_id)}
            if supplier_ref.external_ref:
                supplier_keys.add(str(supplier_ref.external_ref))
            if str(contract_row.counterparty_id) not in supplier_keys:
                raise HTTPException(422, "purchase.contract_id принадлежит другому поставщику")
            contract_kind = str(contract_row.kind or contract_row.type or "").casefold().replace(" ", "")
            if "споставщик" not in contract_kind:
                raise HTTPException(422, "purchase.contract_id не является договором с поставщиком")
            organization_key = str(contract_row.organization_id or "")
            try:
                organization_uuid = uuid.UUID(organization_key)
            except ValueError:
                organization_uuid = None
            organization_row = None
            if organization_uuid:
                organization_row = (await db.execute(select(Organization).where(
                    Organization.company_id == company_id,
                    Organization.id == organization_uuid,
                ))).scalar_one_or_none()
            if organization_row is None and organization_key:
                organization_row = (await db.execute(select(Organization).where(
                    Organization.company_id == company_id,
                    Organization.external_ref == organization_key,
                ))).scalar_one_or_none()
            organization_ids = ({str(organization_row.id), str(organization_row.external_ref or "")}
                                if organization_row else set())
            if not organization_row or str(doc.get("Организация") or "") not in organization_ids:
                raise HTTPException(422, "purchase относится не к организации договора")
            contract_id = contract_row.id
        business_key = receipt_rules.receipt_dedup_key(
            supplier_id, supplier, incoming_number, incoming_date)
        if format_version == "3" and (supplier_id is None or contract_id is None):
            raise HTTPException(
                422, "purchase: окончательная приёмка требует canonical supplier_id и contract_id")
        values = {
            "station_id": station_id,
            "number": str(doc.get("Номер") or "")[:40] or "б/н",
            "doc_date": parsed,
            "supplier": supplier,
            "supplier_id": supplier_id,
            "contract": (existing.contract if existing and existing.contract_id
                         else doc.get("ДоговорКонтрагента") or None),
            "contract_id": contract_id,
            "incoming_number": incoming_number,
            "incoming_date": incoming_date,
            "status": "accepted",
            "origin": "station",
            "delivery_scheme": doc.get("СхемаДоставки") or "supplier_to_station",
            "receiving_warehouse": doc.get("СкладПриемки") or None,
            "signing_mode": doc.get("СхемаПодписания") or "office_director",
            "signer_name": doc.get("Подписант") or None,
            # Кто принял товар. Сверке важно не только что приняли, но и кто:
            # приёмка, проведённая кнопкой из центра, коробок не открывала.
            "author": doc.get("Автор") or None,
            "mchd_guid": doc.get("ИдентификаторМЧД") or None,
            "mchd_registry": doc.get("РеестрМЧД") or None,
            "mchd_valid_until": mchd_until,
            "signature_status": doc.get("СтатусЭП") or "pending",
            "signature_ref": doc.get("ИдентификаторЭП") or None,
            "signed_at": signed_at,
            "lines": lines,
            "services": services,
            "evidence": evidence,
            "dedup_key": business_key,
            "total_amount": total_amount,
            "vat_amount": vat_amount,
            "accepted_at": datetime.now(timezone.utc),
        }
        if existing is None:
            row = StoreReceipt(
                id=document_id or uuid.uuid4(),
                company_id=company_id,
                source_uuid=str(source_uuid)[:64],
                **values,
            )
            db.add(row)
        else:
            if existing.source_uuid is None:
                existing.source_uuid = str(source_uuid)[:64]
            existing.evidence = evidence
            if existing.status == "accepted":
                await receipt_rules.record_acceptance(db, existing)
                continue
            for key, value in values.items():
                setattr(existing, key, value)
            existing.origin = existing.origin if existing.origin in ("center", "edo") else "station"
            existing.version = int(existing.version or 0) + 1
            row = existing
        await db.flush()
        await receipt_rules.record_acceptance(db, row)


async def _ingest_cheques(db: AsyncSession, company_id, station_id: int,
                          payload: dict, packet_uuid: str) -> int:
    """Разложить пакет чеков смены в реестр.

    Идемпотентно по (станция, смена, номер чека): агент повторяет отправку при
    любой неопределённости, и повтор обязан обновлять чек, а не плодить второй.
    """
    from app.models import StoreCheque

    смена = payload.get("Смена") or {}
    номер_смены = int(смена.get("НомерСменыВнутр") or смена.get("НомерСмены") or 0)
    принято = 0
    for doc in payload.get("Документы") or []:
        if not isinstance(doc, dict) or doc.get("Тип") != "fiscal_receipts":
            continue
        for чек in doc.get("Чеки") or []:
            номер = int(чек.get("Номер") or 0)
            if номер <= 0:
                continue
            строки = []
            for line in чек.get("Товары") or []:
                строки.append({
                    "item_uuid": line.get("Номенклатура") or "",
                    "name": line.get("Наименование") or "",
                    "ns_code": line.get("КодНС"),
                    "qty": float(line.get("Количество") or 0),
                    "price": float(line.get("Цена") or 0),
                    "amount": float(line.get("Сумма") or 0),
                    "section": line.get("Секция"),
                })
            момент = чек.get("Время")
            try:
                когда = (datetime.fromisoformat(момент) if момент
                         else datetime.now(timezone.utc))
            except ValueError:
                когда = datetime.now(timezone.utc)
            if когда.tzinfo is None:
                когда = когда.replace(tzinfo=timezone.utc)

            существующий = (await db.execute(select(StoreCheque).where(
                StoreCheque.company_id == company_id,
                StoreCheque.station_id == station_id,
                StoreCheque.shift_number == номер_смены,
                StoreCheque.number == номер))).scalar_one_or_none()
            значения = {
                "fiscal_number": чек.get("ФН"),
                "at": когда,
                "is_return": bool(чек.get("Возврат")),
                "had_fuel": bool(чек.get("БылоТопливо")),
                "pay_type": чек.get("ВидОплаты"),
                "pay_name": (чек.get("ВидОплатыНазвание") or "")[:60] or None,
                "total": float(чек.get("Сумма") or 0),
                "positions": len(строки),
                "lines": строки,
                "packet_uuid": packet_uuid,
            }
            if существующий is None:
                db.add(StoreCheque(company_id=company_id, station_id=station_id,
                                   shift_number=номер_смены, number=номер, **значения))
            else:
                for k, v in значения.items():
                    setattr(существующий, k, v)
            принято += 1
    return принято


async def _sync_stock_packet(db: AsyncSession, company_id, station_id: int,
                             payload: dict) -> dict:
    """Сохранить остаток независимо от старой общей проекции каталога."""
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
    try:
        catalog = await edge_nsi.sync_from_snapshot(db, station_id, payload)
        await db.commit()
        return {"stock": stock, "catalog": catalog}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.warning("станция %s: каталог снимка не синхронизирован: %s", station_id, exc)
        return {"stock": stock, "catalog_error": str(exc)[:200]}


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
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

    return {
        "server_time": now.isoformat(),
        "desired_version": desired_version(company),
        # Сколько заданий ждёт станцию: агент пойдёт за ними только если есть
        # что забирать — лишний запрос в минуту по LTE не нужен.
        "downlink_pending": int(pending),
        "stations": stations,
        "update_required": bool(row.version
                               and row.version != desired_version(company)),
    }


@router.get("/downlink")
async def downlink(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
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
    station_id = int(header)

    rows = (await db.execute(
        select(EdgeDownlink)
        .where(EdgeDownlink.company_id == company.id,
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
    db: AsyncSession = Depends(get_db),
):
    """Станция применила задание. До этого момента оно будет приходить снова."""
    row = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.id == task_id,
        EdgeDownlink.company_id == company.id))).scalar_one_or_none()
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
    желаемая = desired_version(company)
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


@router.post("/packets", status_code=status.HTTP_201_CREATED)
async def receive_packet(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Принять пакет от агента станции. Тело — JSON, при Content-Encoding: gzip
    приходит сжатым (смена ~200 КБ → ~30 КБ, важно для LTE)."""
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
    packet_kind = request.headers.get("X-Packet-Kind") or "shift"

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
            EdgePacket.company_id == company.id,
            EdgePacket.packet_uuid == packet_uuid,
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.station_id != int(station_id):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Пакет с таким идентификатором принадлежит другой станции")
        packet_kind = request.headers.get("X-Packet-Kind") or existing.kind
        прежний = (existing.payload or {}).get("ХешПакета")
        новый = payload.get("ХешПакета")
        if not новый or новый == прежний:
            existing.wire_size_bytes = wire_size
            if packet_kind == "station-recipes":
                await recipe_versions.ingest_station_bundle(
                    db, company.id, int(station_id),
                    (existing.payload or {}).get("recipe_bundle") or {})
            routed = 0
            if packet_kind == "transfer":
                routed = await _route_transfer_packet(
                    db, company.id, int(station_id), existing.payload)
            await _ingest_receipts(
                db, company.id, int(station_id), existing.payload,
                (existing.payload or {}).get("Документы") or [],
            )
            if packet_kind == "cheques":
                await _ingest_cheques(
                    db, company.id, int(station_id), existing.payload, str(packet_uuid))
            # Старые пакеты могли быть приняты ещё в теневом режиме, поэтому повтор
            # достраивает L2. Но достраивает ТОЛЬКО недостающее: раньше здесь шла
            # безусловная перепроекция сохранённого payload, и повторная доставка
            # старого пакета затирала документ, уже обновлённый более свежим
            # (инвентаризация теряла 55 строк и 81 053 ₽, откатываясь к нулю).
            уже_есть = (await db.execute(
                select(func.count(DataEntry.id)).where(
                    DataEntry.company_id == company.id,
                    DataEntry.source == "edge",
                    DataEntry.meta["Edge"]["packet_uuid"].astext == str(packet_uuid),
                )
            )).scalar_one()
            if not уже_есть:
                await edge_projection.project_packet(
                    db, company.id, str(packet_uuid), int(station_id), existing.payload)
            await db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, "Пакет уже принят ранее")
        existing.payload = payload
        existing.size_bytes = len(raw)
        existing.wire_size_bytes = wire_size
        existing.source = str(payload.get("Источник") or "") or existing.source
        existing.received_at = datetime.now(timezone.utc)
        docs = payload.get("Документы") or []
        routed = 0
        if packet_kind == "transfer":
            routed = await _route_transfer_packet(
                db, company.id, int(station_id), payload)
        projection = await edge_projection.project_packet(
            db, company.id, str(packet_uuid), int(station_id), payload)
        await _ingest_receipts(db, company.id, int(station_id), payload, docs)
        if packet_kind == "cheques":
            await _ingest_cheques(db, company.id, int(station_id), payload, str(packet_uuid))
        await db.commit()
        if packet_kind == "station-nsi":
            try:
                await edge_nsi.ingest_station_nsi(db, company.id, int(station_id), docs)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                log.warning("станция %s: черновики не приняты: %s", station_id, exc)
        nsi = None
        if packet_kind == "stock":
            try:
                nsi = await _sync_stock_packet(
                    db, company.id, int(station_id), payload)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                nsi = {"error": str(exc)[:200]}
        if packet_kind == "station-recipes":
            nsi = await recipe_versions.ingest_station_bundle(
                db, company.id, int(station_id), payload.get("recipe_bundle") or {})
        return {"ok": True, "перевыгрузка": True, "packet_uuid": packet_uuid,
                "projection": projection, "nsi": nsi, "routed_transfers": routed}

    db.add(EdgePacket(
        company_id=company.id,
        packet_uuid=packet_uuid,
        station_id=int(station_id),
        kind=packet_kind,
        shift_number=str(shift.get("НомерСмены") or "") or None,
        shift_internal_no=shift.get("НомерСменыВнутр"),
        payload=payload,
        size_bytes=len(raw),
        wire_size_bytes=wire_size,
        source=str(payload.get("Источник") or "") or None,
    ))
    routed = 0
    if packet_kind == "transfer":
        routed = await _route_transfer_packet(
            db, company.id, int(station_id), payload)
    docs = payload.get("Документы") or []

    # Приёмка со станции — не сырьё, а документ: тот же самый, что ведут в
    # центре. Иначе фактическое поступление осталось бы в пакетах, а товаровед
    # в «Магазине» его не увидел бы.
    await _ingest_receipts(db, company.id, int(station_id), payload, docs)
    if packet_kind == "cheques":
        await _ingest_cheques(db, company.id, int(station_id), payload, str(packet_uuid))
    projection = await edge_projection.project_packet(
        db, company.id, str(packet_uuid), int(station_id), payload)
    await db.commit()

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
    if (request.headers.get("X-Packet-Kind") or "") in ("station-nsi", "station-mrc"):
        try:
            await edge_nsi.ingest_station_nsi(db, company.id, int(station_id), docs)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning("станция %s: черновики не приняты: %s", station_id, exc)

    recipe_stats = None
    if (request.headers.get("X-Packet-Kind") or "") == "station-recipes":
        recipe_stats = await recipe_versions.ingest_station_bundle(
            db, company.id, int(station_id), payload.get("recipe_bundle") or {})

    nsi_stats = None
    if (request.headers.get("X-Packet-Kind") or "") == "stock":
        try:
            nsi_stats = await _sync_stock_packet(
                db, company.id, int(station_id), payload)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            nsi_stats = {"error": str(exc)[:200]}

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
