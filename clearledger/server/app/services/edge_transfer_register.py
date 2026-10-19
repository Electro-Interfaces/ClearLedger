from copy import deepcopy
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import EdgeDownlink, EdgePacket
from app.services.edge_transfers import is_deleted, parse_moment, revision_at, transfer_quantity


async def latest_documents(db, company_id, kind="transfer"):
    rows = (await db.execute(select(
        EdgePacket.station_id, EdgePacket.packet_uuid, EdgePacket.received_at, EdgePacket.payload,
        EdgePacket.shift_number,
    ).where(EdgePacket.company_id == company_id, EdgePacket.kind == kind))).all()
    latest = {}
    for station, packet_uuid, received, payload, shift_number in rows:
        for index, doc in enumerate((payload or {}).get("Документы") or []):
            if doc.get("Тип") != kind or not doc.get("ИсточникUUID"):
                continue
            try:
                event = revision_at(payload, doc)
            except ValueError:
                event = received
            key = (station, str(doc["ИсточникUUID"]))
            row = {"station": station, "source_uuid": str(doc["ИсточникUUID"]), "doc": doc,
                   "packet_uuid": packet_uuid, "received_at": received, "revision_at": event,
                   "doc_index": index, "shift_number": shift_number}
            previous = latest.get(key)
            if previous is None or (event, is_deleted(doc), received, packet_uuid) > (previous["revision_at"], is_deleted(previous["doc"]), previous["received_at"], previous["packet_uuid"]):
                latest[key] = row
    return list(latest.values())


def line_quantities(lines, field):
    result = {}
    for line in lines:
        key = (str(line.get("Номенклатура") or ""), str(line.get("ШтрихКод") or ""))
        result[key] = result.get(key, 0) + transfer_quantity(line.get(field))
    return result


def received_document(outgoing, documents):
    doc = outgoing["doc"]
    identity = f"incoming:{outgoing['station']}:{doc.get('ИдентификаторДокумента')}"
    target = int(doc.get("КодАЗСПолучателя") or 0)
    return next((row for row in documents if row["station"] == target
                 and row["doc"].get("Направление") == "in"
                 and row["doc"].get("ИдентификаторДокумента") == identity
                 and not is_deleted(row["doc"])
                 and (not doc.get("РедакцияДата") or
                      parse_moment(row["doc"].get("РедакцияОтправки")) == parse_moment(doc.get("РедакцияДата")))), None)


def canonical_document(document, documents):
    direction = document.get("Направление")
    identity = str(document.get("ИдентификаторДокумента") or "")
    if direction == "internal" or identity.startswith("central:"):
        return deepcopy(document), None
    if direction == "in":
        parts = identity.split(":", 2)
        sender = int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else 0
        sender_id = parts[2] if len(parts) == 3 else ""
        outgoing = next((row for row in documents if row["station"] == sender
                         and row["doc"].get("ИдентификаторДокумента") == sender_id
                         and row["doc"].get("Направление") == "out"), None)
    else:
        outgoing = next((row for row in documents if row["source_uuid"] == document.get("ИсточникUUID")
                         and row["doc"].get("Направление") == "out"), None)
    if outgoing is None or is_deleted(outgoing["doc"]):
        return None, "Исходящая передача отсутствует или отменена"
    incoming = received_document(outgoing, documents)
    if incoming is None:
        return None, "Ожидается подтверждение приёмки получателем"
    expected = line_quantities(outgoing["doc"].get("Товары") or [], "КоличествоОтправлено")
    actual = line_quantities(incoming["doc"].get("Товары") or [], "Количество")
    if expected.keys() != actual.keys() or any(abs(expected[key] - actual[key]) > .0005 for key in expected):
        return None, "Расхождение отправки и приёмки требует разбора"
    result = deepcopy(outgoing["doc"])
    for line in result.get("Товары") or []:
        line["Количество"] = transfer_quantity(line.get("КоличествоОтправлено"))
    result["МестоПолучатель"] = incoming["doc"].get("МестоПолучатель") or ""
    result["ПриемкаПодтверждена"] = True
    result["ИсточникПриемкиUUID"] = incoming["source_uuid"]
    return result, None


async def between_stations(db, company_id, date_from=None, date_to=None, station_scope=None):
    documents = await latest_documents(db, company_id)
    tasks = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == company_id,
        EdgeDownlink.kind.in_(("incoming_transfer", "incoming_transfer_cancelled",
                               "transfer_accepted", "transfer_acceptance_cancelled")),
    ))).scalars().all()
    moscow = ZoneInfo("Europe/Moscow")
    first = date.fromisoformat(date_from) if date_from else None
    last = date.fromisoformat(date_to) if date_to else None
    now = datetime.now(timezone.utc)
    transfers, conflicts = [], []
    by_state = {"в пути": 0, "принято": 0, "расхождение": 0}
    for outgoing in documents:
        doc = outgoing["doc"]
        if doc.get("Направление") != "out":
            continue
        sender, target = outgoing["station"], int(doc.get("КодАЗСПолучателя") or 0)
        if station_scope is not None and not set(station_scope).intersection((sender, target)):
            continue
        moment = parse_moment(doc.get("Дата")) or outgoing["received_at"]
        day = moment.astimezone(moscow).date()
        if (first and day < first) or (last and day > last):
            continue
        related = [task for task in tasks if task.note == f"transfer:{sender}:{outgoing['source_uuid']}"]
        incoming = received_document(outgoing, documents)
        cancellations = [task for task in related if task.kind == "incoming_transfer_cancelled"]
        latest_cancellation = max(cancellations, key=lambda task: task.created_at, default=None)
        result = ((latest_cancellation.payload or {}).get("_delivery_result") or {}) if latest_cancellation else {}
        if result.get("status") == "conflict" and (is_deleted(doc) or incoming is None):
            conflicts.append({"from_station": sender, "to_station": target,
                              "number": doc.get("Номер"), "doc_id": doc.get("ИдентификаторДокумента"),
                              "reason": result.get("reason") or "Получатель уже принял товар",
                              "task_id": str(latest_cancellation.id)})
        if is_deleted(doc):
            continue
        sent_lines = line_quantities(doc.get("Товары") or [], "КоличествоОтправлено")
        accepted_lines = line_quantities(incoming["doc"].get("Товары") or [], "Количество") if incoming else None
        sent = sum(sent_lines.values())
        accepted = sum(accepted_lines.values()) if accepted_lines is not None else None
        difference = None if accepted is None else round(accepted - sent, 3)
        mismatch = accepted_lines is not None and (sent_lines.keys() != accepted_lines.keys()
                    or any(abs(sent_lines[key] - accepted_lines[key]) > .0005 for key in sent_lines))
        state = "расхождение" if mismatch else "принято" if incoming else "в пути"
        by_state[state] += 1
        delivered = [task for task in related if task.kind == "incoming_transfer"]
        latest_task = max(delivered, key=lambda task: task.created_at, default=None)
        transfers.append({
            "from_station": sender, "to_station": target, "number": doc.get("Номер"),
            "doc_date": moment, "doc_id": doc.get("ИдентификаторДокумента"),
            "from_place": doc.get("МестоОтправитель") or "", "comment": doc.get("Комментарий") or "",
            "positions": len(doc.get("Товары") or []), "qty_sent": round(sent, 3),
            "qty_accepted": round(accepted, 3) if accepted is not None else None,
            "difference": difference, "state": state,
            "accepted_at": incoming["revision_at"] if incoming else None,
            "hours_in_transit": None if incoming else round((now - moment).total_seconds() / 3600),
            "task_delivered": bool(latest_task and latest_task.delivered_at),
            "task_acked": bool(latest_task and latest_task.acked_at),
            "packet_uuid": outgoing["packet_uuid"],
        })
    transfers.sort(key=lambda row: row["doc_date"], reverse=True)
    return {"transfers": transfers, "total": len(transfers), "by_state": by_state,
            "stuck": [row for row in transfers if row["hours_in_transit"] is not None and row["hours_in_transit"] > 24],
            "cancellation_conflicts": conflicts, "read_at": now.isoformat()}
