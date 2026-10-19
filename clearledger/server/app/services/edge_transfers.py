from datetime import datetime, timezone
import hashlib
import math
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgeAgent, EdgeDownlink


class TransferRoutingError(ValueError):
    pass


CANCELLATION_CAPABILITY = "transfer_cancellation_v1"
CANCELLATION_TASK_KINDS = ("incoming_transfer_cancelled", "transfer_acceptance_cancelled")


def is_deleted(doc):
    return doc.get("ПометкаУдаления") in (True, 1, "true", "True", "1")


def parse_moment(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def revision_at(payload, doc):
    values = [payload.get("ВремяВыгрузки"), doc.get("Дата")]
    if not is_deleted(doc):
        values.insert(0, doc.get("РедакцияДата"))
    for value in values:
        if parsed := parse_moment(value):
            return parsed
    raise TransferRoutingError("у перемещения нет времени редакции")


def transfer_quantity(value):
    try:
        result = float(value or 0)
    except (ValueError, TypeError) as exc:
        raise TransferRoutingError("неверное количество перемещения") from exc
    if not math.isfinite(result) or result < 0:
        raise TransferRoutingError("неверное количество перемещения")
    return result


def transfer_tasks(payload: dict, source_station: int) -> list[dict]:
    tasks = []
    for doc in payload.get("Документы") or []:
        if doc.get("Тип") != "transfer":
            continue
        direction = doc.get("Направление")
        if direction not in {"out", "in"}:
            continue
        if direction == "in" and str(doc.get("ИдентификаторДокумента") or "").startswith("central:"):
            continue
        moment = revision_at(payload, doc).isoformat()
        deleted = is_deleted(doc)
        if direction == "out":
            target = int(doc.get("КодАЗСПолучателя") or 0)
            document_id = str(doc.get("ИдентификаторДокумента") or "")
            source_uuid = str(doc.get("ИсточникUUID") or "")
            if target <= 0 or target == source_station:
                raise TransferRoutingError("неверная станция-получатель")
            if not document_id or not source_uuid:
                raise TransferRoutingError("у перемещения нет идентификатора")
            lines = []
            for line in doc.get("Товары") or []:
                qty = transfer_quantity(line.get("КоличествоОтправлено"))
                if qty <= 0:
                    continue
                lines.append({
                    "item_uuid": str(line.get("Номенклатура") or ""),
                    "name": str(line.get("Наименование") or ""),
                    "unit": str(line.get("Единица") or "шт"),
                    "barcode": str(line.get("ШтрихКод") or ""),
                    "qty_sent": qty,
                    "mark_codes": line.get("КодыМаркировки") or [],
                    "unknown": bool(line.get("КарточкаНеОпознана")),
                })
            if not lines and not deleted:
                raise TransferRoutingError("в перемещении нет отправленных товаров")
            tasks.append({
                "kind": "incoming_transfer_cancelled" if deleted else "incoming_transfer",
                "station_id": target,
                "note": f"transfer:{source_station}:{source_uuid}"[:300],
                "payload": {
                    "id": f"incoming:{source_station}:{document_id}",
                    "sender_document_id": document_id,
                    "source_uuid": source_uuid,
                    "number": str(doc.get("Номер") or ""),
                    "doc_date": str(doc.get("Дата") or ""),
                    "from_station": source_station,
                    "to_station": target,
                    "from_name": str(doc.get("Отправитель") or f"АЗС {source_station}"),
                    "to_name": str(doc.get("Получатель") or f"АЗС {target}"),
                    "from_place": str(doc.get("МестоОтправитель") or ""),
                    "comment": str(doc.get("Комментарий") or ""),
                    "revision_at": moment,
                    "reason": "Отправитель отменил передачу" if deleted else "",
                    "lines": lines,
                },
            })
        elif direction == "in":
            incoming_id = str(doc.get("ИдентификаторДокумента") or "")
            # Центральный склад не является агентом. Приёмка на целевой АЗС
            # уже попала в общий журнал пакетов; подтверждать её станции 0
            # отдельным downlink-заданием некуда и не нужно.
            if incoming_id.startswith("central:"):
                continue
            parts = incoming_id.split(":", 2)
            if len(parts) != 3 or parts[0] != "incoming" or not parts[1].isdigit():
                raise TransferRoutingError("подтверждение не связано с исходящей отправкой")
            sender_station = int(parts[1])
            sender_document_id = parts[2]
            if sender_station <= 0 or sender_station == source_station or not sender_document_id:
                raise TransferRoutingError("неверная станция-отправитель")
            sent = sum(transfer_quantity(line.get("КоличествоОтправлено"))
                       for line in doc.get("Товары") or [])
            accepted = sum(transfer_quantity(line.get("Количество"))
                           for line in doc.get("Товары") or [])
            tasks.append({
                "kind": "transfer_acceptance_cancelled" if deleted else "transfer_accepted",
                "station_id": sender_station,
                "note": f"transfer-accepted:{sender_station}:{sender_document_id}"[:300],
                "payload": {
                    "id": sender_document_id,
                    "accepted_station": source_station,
                    "accepted_at": moment,
                    "sender_revision_at": str(doc.get("РедакцияОтправки") or ""),
                    "accepted_qty": accepted,
                    "difference": accepted - sent,
                    "revision_at": moment,
                    "lines": [{"item_uuid": str(line.get("Номенклатура") or ""),
                               "barcode": str(line.get("ШтрихКод") or ""),
                               "qty_sent": transfer_quantity(line.get("КоличествоОтправлено")),
                               "qty_fact": transfer_quantity(line.get("Количество"))}
                              for line in doc.get("Товары") or []],
                },
            })
    for task in tasks:
        key = f"{task['note']}|{task['kind']}|{task['payload']['revision_at']}"
        task["idempotency_key"] = "transfer-event:" + hashlib.sha256(key.encode()).hexdigest()
    return tasks


async def route_transfer_tasks(
    db: AsyncSession, company_id, source_station: int, payload: dict,
) -> int:
    created = 0
    for task in transfer_tasks(payload, source_station):
        target_exists = (await db.execute(select(EdgeAgent.id).where(
            EdgeAgent.company_id == company_id,
            EdgeAgent.station_id == task["station_id"],
        ))).scalar_one_or_none()
        if target_exists is None:
            raise TransferRoutingError(
                f"АЗС {task['station_id']} не подключена к «Магазину»")
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                         {"key": f"transfer:{company_id}:{task['station_id']}:{task['note']}"})
        previous = (await db.execute(select(EdgeDownlink).where(
            EdgeDownlink.company_id == company_id,
            EdgeDownlink.station_id == task["station_id"],
            EdgeDownlink.note == task["note"],
        ))).scalars().all()
        if any(old.idempotency_key == task["idempotency_key"] for old in previous):
            continue
        revision = parse_moment(task["payload"]["revision_at"])
        if any((parse_moment((old.payload or {}).get("revision_at")) or datetime.min.replace(tzinfo=timezone.utc)) > revision
               or (parse_moment((old.payload or {}).get("revision_at")) == revision
                   and old.kind in CANCELLATION_TASK_KINDS and task["kind"] not in CANCELLATION_TASK_KINDS)
               for old in previous):
            continue
        if task["kind"] in CANCELLATION_TASK_KINDS:
            for old in previous:
                if old.acked_at is None and old.cancelled_at is None:
                    old.cancelled_at = datetime.now(timezone.utc)
        statement = insert(EdgeDownlink).values(
            id=uuid.uuid4(),
            company_id=company_id,
            station_id=task["station_id"],
            kind=task["kind"],
            payload=task["payload"],
            note=task["note"],
            idempotency_key=task["idempotency_key"],
        ).on_conflict_do_nothing()
        result = await db.execute(statement)
        created += result.rowcount or 0
    return created
