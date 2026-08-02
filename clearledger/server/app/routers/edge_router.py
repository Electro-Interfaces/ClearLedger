"""
Приёмник пакетов edge-агентов АЗС (проект Ledger Edge, этап v0).

Агент станции работает за CGNAT, поэтому связь всегда исходящая: агент сам
приносит пакет смены, собранный напрямую из кассы NeftoMS. Аутентификация —
машинная, по X-Cloud-API-Key компании (тот же механизм, что у dedup-ingest).

Идемпотентность: повтор пакета с тем же ИдентификаторПакета получает 409 и
считается агентом успехом. Это единственный корректный ответ на обрыв связи
в момент ответа — иначе смена либо потеряется, либо задвоится.

v0 — теневой режим: пакеты складываются сырьём и сверяются с данными 1С;
документы из них не создаются.
"""
import gzip
import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import Company, EdgeAgent, EdgeDownlink, EdgePacket, StoreReceipt
from app.services import edge_nsi, edge_service

router = APIRouter(prefix="/edge", tags=["Edge (агенты АЗС)"])

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
DESIRED_AGENT_VERSION = os.environ.get("EDGE_DESIRED_AGENT_VERSION", "0.22.0")


async def _ingest_receipts(db: AsyncSession, company_id, station_id: int,
                           payload: dict, docs: list) -> None:
    """Развернуть документы `purchase` пакета в документы приёмки центра.

    Идемпотентность по ИсточникUUID документа: станция повторяет отправку при
    любой неопределённости, и повтор не должен плодить приёмки. Документ
    приходит уже принятым — на станции его приняли физически, и переигрывать
    это решение в центре нельзя.
    """
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("Тип") != "purchase":
            continue
        source_uuid = doc.get("ИсточникUUID") or payload.get("ИдентификаторПакета")
        if not source_uuid:
            continue
        exists = (await db.execute(select(StoreReceipt.id).where(
            StoreReceipt.source_uuid == source_uuid))).scalar_one_or_none()
        if exists:
            continue

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
                "amount": float(item.get("Сумма") or 0),
                # Станция не опознала штрихкод — карточку заводит центр.
                "no_card": bool(item.get("КарточкаНеОпознана")),
            })

        doc_date = doc.get("Дата")
        try:
            parsed = datetime.fromisoformat(doc_date) if doc_date else datetime.now(timezone.utc)
        except ValueError:
            parsed = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        db.add(StoreReceipt(
            company_id=company_id, station_id=station_id,
            number=str(doc.get("Номер") or "")[:40] or "б/н",
            doc_date=parsed,
            supplier=(doc.get("Контрагент") or None),
            incoming_number=(doc.get("НомерВходящегоДокумента") or None),
            status="accepted", origin="station", lines=lines,
            total_amount=float(doc.get("СуммаДокумента") or 0), vat_amount=0,
            accepted_at=datetime.now(timezone.utc), source_uuid=str(source_uuid)[:64],
        ))


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
    await db.commit()

    pending = (await db.execute(
        select(func.count()).select_from(EdgeDownlink).where(
            EdgeDownlink.company_id == company.id,
            EdgeDownlink.station_id == station_id,
            EdgeDownlink.acked_at.is_(None)))).scalar() or 0

    return {
        "server_time": now.isoformat(),
        "desired_version": DESIRED_AGENT_VERSION,
        # Сколько заданий ждёт станцию: агент пойдёт за ними только если есть
        # что забирать — лишний запрос в минуту по LTE не нужен.
        "downlink_pending": int(pending),
        "update_required": bool(row.version and row.version != DESIRED_AGENT_VERSION),
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
               EdgeDownlink.acked_at.is_(None))
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
            "version_ok": r.version == DESIRED_AGENT_VERSION,
            "desired_version": DESIRED_AGENT_VERSION,
            "queue_pending": r.queue_pending,
            "queue_sent": r.queue_sent,
            "last_shift": r.last_shift,
            "last_seen": r.last_seen,
            "first_seen": r.first_seen,
            "details": r.payload,
        })
    return {"desired_version": DESIRED_AGENT_VERSION, "agents": out,
            "online": sum(1 for a in out if a["state"] == "онлайн"), "total": len(out)}


@router.post("/packets", status_code=status.HTTP_201_CREATED)
async def receive_packet(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Принять пакет от агента станции. Тело — JSON, при Content-Encoding: gzip
    приходит сжатым (смена ~200 КБ → ~30 КБ, важно для LTE)."""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Пакет слишком большой")
    if request.headers.get("content-encoding", "").lower() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
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

    # Идемпотентность: повтор — не ошибка агента, а штатный исход обрыва связи.
    #
    # Но повтор бывает двух видов, и различает их хеш. Тот же UUID с тем же
    # хешем — дубль доставки, отвечаем 409 и на этом всё. Тот же UUID с ДРУГИМ
    # хешем — перевыгрузка: агент пересобрал смену после исправления (так было
    # со ставкой НДС, которую он брал у чужого кода нефтесервера). Отвергать её
    # значит навсегда оставить в мастере данные, о которых уже известно, что они
    # неверны — и никакая починка агента не долетит до сверки.
    existing = (await db.execute(
        select(EdgePacket).where(EdgePacket.packet_uuid == packet_uuid)
    )).scalar_one_or_none()
    if existing is not None:
        прежний = (existing.payload or {}).get("ХешПакета")
        новый = payload.get("ХешПакета")
        if not новый or новый == прежний:
            raise HTTPException(status.HTTP_409_CONFLICT, "Пакет уже принят ранее")
        existing.payload = payload
        existing.size_bytes = len(raw)
        existing.source = str(payload.get("Источник") or "") or existing.source
        existing.received_at = datetime.now(timezone.utc)
        await db.commit()
        return {"ok": True, "перевыгрузка": True, "packet_uuid": packet_uuid}

    db.add(EdgePacket(
        company_id=company.id,
        packet_uuid=packet_uuid,
        station_id=int(station_id),
        kind=request.headers.get("X-Packet-Kind") or "shift",
        shift_number=str(shift.get("НомерСмены") or "") or None,
        shift_internal_no=shift.get("НомерСменыВнутр"),
        payload=payload,
        size_bytes=len(raw),
        source=str(payload.get("Источник") or "") or None,
    ))
    await db.commit()

    docs = payload.get("Документы") or []

    # Приёмка со станции — не сырьё, а документ: тот же самый, что ведут в
    # центре. Иначе фактическое поступление осталось бы в пакетах, а товаровед
    # в «Магазине» его не увидел бы.
    await _ingest_receipts(db, company.id, int(station_id), payload, docs)

    # Снимок наполняет мастер-НСИ: справочника штрихкодов в 1С не существует
    # (ШК там — измерение регистра), поэтому поток снимков со станции остаётся
    # единственным источником связи «карточка ↔ штрихкод ↔ код кассы».
    # Сбой синхронизации не должен отвергать пакет: данные уже приняты, а НСИ
    # догонит следующим снимком.
    nsi_stats = None
    if (request.headers.get("X-Packet-Kind") or "") == "stock":
        try:
            nsi_stats = await edge_nsi.sync_from_snapshot(db, int(station_id), payload)
        except Exception as exc:  # noqa: BLE001
            nsi_stats = {"error": str(exc)[:200]}

    return {
        "accepted": True,
        "packet_uuid": packet_uuid,
        "station_id": int(station_id),
        "shift": shift.get("НомерСмены"),
        "documents": len(docs),
        "size_bytes": len(raw),
        "nsi": nsi_stats,
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
        "source": r.source,
        "received_at": r.received_at,
        "documents": len(r.payload.get("Документы") or []),
    } for r in rows]


@router.get("/reconcile")
async def reconcile(
    station_id: int | None = None,
    limit: int = 60,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Теневая сверка: пакет агента против пакета ЦБ по каждой смене.

    Критерий этапа v0 — `clean: true` четырнадцать дней подряд.
    """
    return await edge_service.reconcile(db, company.id, station_id, limit)


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
