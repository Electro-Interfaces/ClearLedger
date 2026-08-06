from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgeAgent, EdgeDownlink


class TransferRoutingError(ValueError):
    pass


def transfer_tasks(payload: dict, source_station: int) -> list[dict]:
    tasks = []
    for doc in payload.get("Документы") or []:
        if doc.get("Тип") != "transfer":
            continue
        direction = doc.get("Направление")
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
                qty = float(line.get("КоличествоОтправлено") or 0)
                if qty <= 0:
                    continue
                lines.append({
                    "item_uuid": str(line.get("Номенклатура") or ""),
                    "name": str(line.get("Наименование") or ""),
                    "barcode": str(line.get("ШтрихКод") or ""),
                    "qty_sent": qty,
                    "mark_codes": line.get("КодыМаркировки") or [],
                    "unknown": bool(line.get("КарточкаНеОпознана")),
                })
            if not lines:
                raise TransferRoutingError("в перемещении нет отправленных товаров")
            tasks.append({
                "kind": "incoming_transfer",
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
            sent = sum(float(line.get("КоличествоОтправлено") or 0)
                       for line in doc.get("Товары") or [])
            accepted = sum(float(line.get("Количество") or 0)
                           for line in doc.get("Товары") or [])
            tasks.append({
                "kind": "transfer_accepted",
                "station_id": sender_station,
                "note": f"transfer-accepted:{sender_station}:{sender_document_id}"[:300],
                "payload": {
                    "id": sender_document_id,
                    "accepted_station": source_station,
                    "accepted_at": str(payload.get("Выгружено") or datetime.now(timezone.utc).isoformat()),
                    "accepted_qty": accepted,
                    "difference": accepted - sent,
                },
            })
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
        exists = (await db.execute(select(EdgeDownlink.id).where(
            EdgeDownlink.company_id == company_id,
            EdgeDownlink.station_id == task["station_id"],
            EdgeDownlink.kind == task["kind"],
            EdgeDownlink.note == task["note"],
        ))).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(EdgeDownlink(
            company_id=company_id,
            station_id=task["station_id"],
            kind=task["kind"],
            payload=task["payload"],
            note=task["note"],
        ))
        created += 1
    return created
