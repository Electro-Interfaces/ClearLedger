"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
import hashlib
import json
import math
import uuid
from datetime import date, datetime, timezone

import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_module_access, get_current_user
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    EdgeAgent, EdgeDownlink, StoreAssortmentRule, StoreItemAlias, StoreReceipt,
    StoreRecipeVersion, StoreStockBalance,
    User, UserCompany,
)
from app.services import edge_nsi, edge_projection, edge_service
from app.services import recipe_versions
from app.services.export_audit import log_export
from app.services.edo_upd import parse_upd
from app.services.goods_dashboard import GoodsDashboardService

# Каталог выгрузки пакетов БП — ТОЛЬКО из окружения сервера (не из клиентского
# Query — закрыта directory-injection: раньше любой аутентиф. пользователь мог
# писать в произвольный путь ФС сервера).
BP_EXPORT_DIR = os.environ.get("TL_BP_EXPORT_DIR", r"C:\TL_BP_Export")


async def _require_store_module(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """GAP-1: RBAC-гейт всего раздела «Магазин». Без него любой член компании с
    урезанной ролью читал данные магазина и (что критично) мог эмитить пакет в
    каталог обмена с живой бухгалтерией. Проверяем модуль 'store' для компании,
    выбранной в UI (X-Company-Id), — как analytics-режимы через assert_company_module."""
    cid = await scope_company_id(user, db)   # membership + резолв X-Company-Id
    await check_module_access(user, cid, db, "store")


# capture_company_header кладёт X-Company-Id (выбранная компания) в contextvar;
# scope_company_id ниже резолвит её вместо жёсткой user.company_id (переключение
# компании в UI теперь влияет и на «Магазин»). _require_store_module — RBAC-гейт.
router = APIRouter(prefix="/store", tags=["Магазин"],
                   dependencies=[Depends(capture_company_header),
                                 Depends(_require_store_module)])


# Молчание свыше трёх минут при телеметрии раз в минуту — это уже не «сеть
# моргнула», а обрыв. Час — станция требует внимания человека.
STATION_OFFLINE_AFTER = 180
STATION_STALE_AFTER = 3600


@router.get("/stations")
async def store_stations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Станции компании: связь агента, версия кода, очередь пакетов.

    Тот же разрез, что видит оператор на станции, только по всему парку: центр
    должен понимать состояние каждой АЗС до того, как оттуда придёт письмо.
    Онлайн здесь означает «канал есть и обмен возможен», а не «идёт передача».
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    rows = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == cid).order_by(EdgeAgent.station_id)
    )).scalars().all()

    desired = os.environ.get("EDGE_DESIRED_AGENT_VERSION", "0.58.10")
    now = datetime.now(timezone.utc)
    stations = []
    for r in rows:
        silence = int((now - r.last_seen).total_seconds()) if r.last_seen else None
        if silence is None or silence > STATION_STALE_AFTER:
            state = "молчит"
        elif silence > STATION_OFFLINE_AFTER:
            state = "офлайн"
        else:
            state = "онлайн"
        details = r.payload or {}
        stations.append({
            "station_id": r.station_id,
            "state": state,
            "silence_seconds": silence,
            "version": r.version,
            "version_ok": bool(r.version) and r.version == desired,
            "queue_pending": r.queue_pending,
            "queue_sent": r.queue_sent,
            "last_shift": r.last_shift,
            "snapshot_at": details.get("snapshot_at"),
            "onec_ok": details.get("onec_ok"),
            "ledger_stock_ok": details.get("ledger_stock_ok", False),
            "stock_source": details.get("stock_source"),
            "cash_policy": details.get("cash_policy"),
            # Кто работает на станции прямо сейчас — по её же телеметрии.
            # Открывать рабочее место вслепую, когда там считают склад, значит
            # столкнуться на одном документе и потерять чью-то работу.
            "active_users": details.get("active_users") or [],
            "last_seen": r.last_seen,
            "first_seen": r.first_seen,
        })

    return {
        "desired_version": desired,
        "total": len(stations),
        "online": sum(1 for s in stations if s["state"] == "онлайн"),
        "queue_total": sum(s["queue_pending"] for s in stations),
        "version_mismatch": sum(1 for s in stations if s["version"] and not s["version_ok"]),
        "stations": stations,
    }


# Пакеты приходят пачкой: агент, дождавшись канала, отдаёт всё накопленное
# подряд. Пауза свыше четверти часа — это уже следующий выход на связь, а не
# та же передача. Отдельной истории heartbeat в базе нет, и заводить её ради
# счётчика незачем: сеанс виден по самим пакетам.
EXCHANGE_SESSION_GAP_MIN = 15

PACKET_KIND_LABEL = {
    "shift": "Смена",
    "stock": "Снимок остатков",
    "receipt": "Приёмка",
    "inventory": "Инвентаризация",
    "writeoff": "Списание",
    "transfer": "Перемещение",
    "production": "Производство",
    "return_sale": "Возврат покупателя",
    "station-nsi": "Черновики НСИ",
    "station-recipes": "Рецептуры станции",
    "nsi_delta": "Карточка НСИ",
    "price_update": "Цена",
    "goods_receipt_expected": "Заготовка приёмки",
    "cash_policy": "Политика кассы",
    "command": "Команда",
}


@router.get("/exchange")
async def store_exchange(
    date_from: str = Query(..., description="начало периода, ISO"),
    date_to: str = Query(..., description="конец периода, ISO (включительно)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обмен станций с центром: сеансы, пакеты, объёмы, очередь вниз.

    Экран парка отвечает на один вопрос — доехало ли то, что станция насчитала,
    и дошло ли вниз то, что центр решил. Онлайн-индикатор его не заменяет:
    канал может быть живым, а пакеты не уходить, и наоборот — станция может
    сутки быть офлайн и отдать всё разом одним сеансом.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    d1, d2 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    p = {"cid": cid, "d1": d1, "d2": d2, "gap": EXCHANGE_SESSION_GAP_MIN}
    # CAST, а не `:d2::date`: двойное двоеточие в именованном параметре
    # SQLAlchemy разбирает как продолжение имени и валит запрос синтаксисом.
    period = "received_at >= :d1 AND received_at < (CAST(:d2 AS date) + 1)"

    by_kind = [dict(r) for r in (await db.execute(text(f"""
        SELECT kind, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               max(received_at) AS last_at
        FROM edge_packets WHERE company_id = :cid AND {period}
        GROUP BY kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for k in by_kind:
        k["label"] = PACKET_KIND_LABEL.get(k["kind"], k["kind"])

    by_day = [dict(r) for r in (await db.execute(text(f"""
        SELECT received_at::date AS day, count(*) AS packets,
               coalesce(sum(size_bytes), 0) AS bytes
        FROM edge_packets WHERE company_id = :cid AND {period}
        GROUP BY 1 ORDER BY 1
    """), p)).mappings().all()]

    # Сеанс = серия пакетов без паузы больше EXCHANGE_SESSION_GAP_MIN. Разрыв
    # ищется оконной функцией по станции: считать это в Python значило бы
    # тащить сюда все пакеты периода ради одного числа.
    by_station = {r["station_id"]: dict(r) for r in (await db.execute(text(f"""
        SELECT station_id, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               max(received_at) AS last_at,
               count(*) FILTER (
                   WHERE prev IS NULL
                      OR received_at - prev > make_interval(mins => :gap)) AS sessions
        FROM (
            SELECT station_id, received_at, size_bytes,
                   lag(received_at) OVER (
                       PARTITION BY station_id ORDER BY received_at) AS prev
            FROM edge_packets WHERE company_id = :cid AND {period}
        ) t GROUP BY station_id
    """), p)).mappings().all()}

    down = {r["station_id"]: dict(r) for r in (await db.execute(text("""
        SELECT station_id,
               count(*) FILTER (WHERE delivered_at IS NULL) AS waiting,
               count(*) FILTER (WHERE delivered_at IS NOT NULL AND acked_at IS NULL) AS unacked,
               count(*) FILTER (WHERE acked_at IS NOT NULL) AS acked
        FROM edge_downlink WHERE company_id = :cid GROUP BY station_id
    """), {"cid": cid})).mappings().all()}

    # Лента последних обменов в обе стороны: она объясняет цифры выше — видно,
    # чем именно занят канал и когда станция выходила на связь последний раз.
    recent = [dict(r) for r in (await db.execute(text("""
        SELECT received_at AS at, station_id, kind, size_bytes, 'вверх' AS direction,
               shift_number AS note
        FROM edge_packets WHERE company_id = :cid
        UNION ALL
        SELECT coalesce(acked_at, delivered_at, created_at) AS at, station_id, kind,
               0 AS size_bytes, 'вниз' AS direction,
               CASE WHEN acked_at IS NOT NULL THEN 'применено'
                    WHEN delivered_at IS NOT NULL THEN 'доставлено'
                    ELSE 'ждёт станции' END AS note
        FROM edge_downlink WHERE company_id = :cid
        ORDER BY at DESC LIMIT 30
    """), {"cid": cid})).mappings().all()]
    for r in recent:
        r["label"] = PACKET_KIND_LABEL.get(r["kind"], r["kind"])

    # Приём и разбор — разные события. Пакет ложится сырьём (L1), документы
    # Ledger рождает проекция (L2); если она упала, пакет так и останется
    # принятым, но неусвоенным, и в отчётах его не будет. Связь ищется по
    # происхождению, которое проекция кладёт в metadata документа, — отдельного
    # журнала для этого заводить не пришлось.
    ingest = [dict(r) for r in (await db.execute(text(f"""
        SELECT p.kind, count(*) AS packets,
               count(*) FILTER (WHERE de.n > 0) AS projected,
               coalesce(sum(de.n), 0) AS entries
        FROM edge_packets p
        LEFT JOIN LATERAL (
            SELECT count(*) AS n FROM data_entries d
            WHERE d.company_id = p.company_id AND d.source = 'edge'
              AND d.metadata->'Edge'->>'packet_uuid' = p.packet_uuid
        ) de ON true
        WHERE p.company_id = :cid AND {period}
        GROUP BY p.kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for i in ingest:
        i["label"] = PACKET_KIND_LABEL.get(i["kind"], i["kind"])
        # Снимки, черновики НСИ и рецептуры документов учёта не порождают —
        # у них своя дорога, и «не разобрано» для них не дефект.
        i["projects_docs"] = i["kind"] not in ("stock", "station-nsi", "station-recipes")
        i["unprojected"] = int(i["packets"]) - int(i["projected"])

    agents = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == cid).order_by(EdgeAgent.station_id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    stations = []
    for a in agents:
        silence = int((now - a.last_seen).total_seconds()) if a.last_seen else None
        ex = by_station.get(a.station_id, {})
        d = down.get(a.station_id, {})
        stations.append({
            "station_id": a.station_id,
            "state": ("молчит" if silence is None or silence > STATION_STALE_AFTER
                      else "офлайн" if silence > STATION_OFFLINE_AFTER else "онлайн"),
            "silence_seconds": silence,
            "version": a.version,
            "queue_pending": a.queue_pending,
            "queue_sent": a.queue_sent,
            "last_shift": a.last_shift,
            "snapshot_at": (a.payload or {}).get("snapshot_at"),
            # Кто работает на станции прямо сейчас — по её же телеметрии.
            # Открывать рабочее место вслепую, когда там считают склад, значит
            # столкнуться на одном документе и потерять чью-то работу.
            "active_users": (a.payload or {}).get("active_users") or [],
            "packets": int(ex.get("packets") or 0),
            "bytes": int(ex.get("bytes") or 0),
            "sessions": int(ex.get("sessions") or 0),
            "last_packet_at": ex.get("last_at"),
            "down_waiting": int(d.get("waiting") or 0),
            "down_unacked": int(d.get("unacked") or 0),
            "down_acked": int(d.get("acked") or 0),
        })

    # Станции, чьи пакеты в базе есть, а телеметрии нет: так выглядит АЗС, с
    # которой обмен шёл до появления таблицы агентов, или разовая заливка. Без
    # этих строк сумма по таблице не сходилась бы с итогом сверху.
    for sid in sorted(set(by_station) - {s["station_id"] for s in stations}):
        ex, d = by_station[sid], down.get(sid, {})
        stations.append({
            "station_id": sid, "state": "нет агента", "silence_seconds": None,
            "version": None, "queue_pending": 0, "queue_sent": 0, "last_shift": None,
            "snapshot_at": None,
            "packets": int(ex.get("packets") or 0), "bytes": int(ex.get("bytes") or 0),
            "sessions": int(ex.get("sessions") or 0), "last_packet_at": ex.get("last_at"),
            "down_waiting": int(d.get("waiting") or 0),
            "down_unacked": int(d.get("unacked") or 0),
            "down_acked": int(d.get("acked") or 0),
        })

    return {
        "from": d1, "to": d2,
        "session_gap_minutes": EXCHANGE_SESSION_GAP_MIN,
        "totals": {
            "packets": sum(k["packets"] for k in by_kind),
            "bytes": sum(int(k["bytes"]) for k in by_kind),
            "sessions": sum(s["sessions"] for s in stations),
            "online": sum(1 for s in stations if s["state"] == "онлайн"),
            # Знаменатель «на связи X из Y» — только станции с агентом: строки
            # без телеметрии не станции парка, а следы старого обмена.
            "stations": len(agents),
            "queue_pending": sum(s["queue_pending"] for s in stations),
            "down_waiting": sum(s["down_waiting"] for s in stations),
            "down_unacked": sum(s["down_unacked"] for s in stations),
            "last_packet_at": max((s["last_packet_at"] for s in stations
                                   if s["last_packet_at"]), default=None),
        },
        "by_kind": by_kind,
        "by_day": by_day,
        "stations": stations,
        "recent": recent,
        "ingest": ingest,
    }


@router.get("/exchange/{station_id}")
async def store_exchange_station(
    station_id: int,
    date_from: str = Query(..., description="начало периода, ISO"),
    date_to: str = Query(..., description="конец периода, ISO (включительно)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обмен ОДНОЙ станции: её сеансы поимённо, состав и канал вниз.

    Сводка по парку отвечает «где плохо», карточка станции — «что именно там
    произошло»: когда АЗС выходила на связь, сколько молчала перед этим, что
    привезла в каждый выход и какие задания центра до неё ещё не дошли.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    d1, d2 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    p = {"cid": cid, "st": station_id, "d1": d1, "d2": d2,
         "gap": EXCHANGE_SESSION_GAP_MIN}
    period = "received_at >= :d1 AND received_at < (CAST(:d2 AS date) + 1)"

    # Сеанс собирается нарастающей суммой признака «новый выход на связь»:
    # такая нумерация даёт границы серии без временных таблиц и второго запроса.
    sessions = [dict(r) for r in (await db.execute(text(f"""
        WITH шаги AS (
            SELECT received_at, size_bytes, kind,
                   lag(received_at) OVER (ORDER BY received_at) AS prev
            FROM edge_packets
            WHERE company_id = :cid AND station_id = :st AND {period}
        ), помеченные AS (
            SELECT *,
                   (prev IS NULL
                    OR received_at - prev > make_interval(mins => :gap)) AS новый,
                   EXTRACT(epoch FROM received_at - prev) / 60 AS пауза
            FROM шаги
        ), пронумерованные AS (
            SELECT *, sum(CASE WHEN новый THEN 1 ELSE 0 END)
                        OVER (ORDER BY received_at) AS session_no
            FROM помеченные
        )
        SELECT session_no, min(received_at) AS started, max(received_at) AS finished,
               count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               string_agg(DISTINCT kind, ', ') AS kinds,
               max(пауза) FILTER (WHERE новый) AS silence_before_min
        FROM пронумерованные GROUP BY session_no ORDER BY started DESC LIMIT 100
    """), p)).mappings().all()]
    for s in sessions:
        s["kinds"] = [PACKET_KIND_LABEL.get(k.strip(), k.strip())
                      for k in (s["kinds"] or "").split(",") if k.strip()]
        s["silence_before_min"] = (round(float(s["silence_before_min"]))
                                   if s["silence_before_min"] is not None else None)
        s["duration_min"] = round(
            (s["finished"] - s["started"]).total_seconds() / 60)

    by_kind = [dict(r) for r in (await db.execute(text(f"""
        SELECT kind, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               max(received_at) AS last_at
        FROM edge_packets
        WHERE company_id = :cid AND station_id = :st AND {period}
        GROUP BY kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for k in by_kind:
        k["label"] = PACKET_KIND_LABEL.get(k["kind"], k["kind"])

    downlink = [dict(r) for r in (await db.execute(text("""
        SELECT kind, note, created_at, delivered_at, acked_at
        FROM edge_downlink WHERE company_id = :cid AND station_id = :st
        ORDER BY created_at DESC LIMIT 50
    """), {"cid": cid, "st": station_id})).mappings().all()]
    for d in downlink:
        d["label"] = PACKET_KIND_LABEL.get(d["kind"], d["kind"])
        d["state"] = ("применено" if d["acked_at"] else
                      "доставлено" if d["delivered_at"] else "ждёт станции")

    agent = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id
    ))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    silence = (int((now - agent.last_seen).total_seconds())
               if agent and agent.last_seen else None)
    details = (agent.payload or {}) if agent else {}
    паузы = [s["silence_before_min"] for s in sessions
             if s["silence_before_min"] is not None]

    return {
        "station_id": station_id,
        "from": d1, "to": d2,
        "session_gap_minutes": EXCHANGE_SESSION_GAP_MIN,
        "agent": None if agent is None else {
            "state": ("молчит" if silence is None or silence > STATION_STALE_AFTER
                      else "офлайн" if silence > STATION_OFFLINE_AFTER else "онлайн"),
            "silence_seconds": silence,
            "version": agent.version,
            "version_ok": bool(agent.version) and agent.version == os.environ.get(
                "EDGE_DESIRED_AGENT_VERSION", "0.58.10"),
            "queue_pending": agent.queue_pending,
            "queue_sent": agent.queue_sent,
            "last_shift": agent.last_shift,
            "snapshot_at": details.get("snapshot_at"),
            "onec_ok": details.get("onec_ok"),
            "stock_source": details.get("stock_source"),
            "first_seen": agent.first_seen,
            "last_seen": agent.last_seen,
        },
        "totals": {
            "sessions": len(sessions),
            "packets": sum(s["packets"] for s in sessions),
            "bytes": sum(int(s["bytes"]) for s in sessions),
            # Средняя и худшая пауза между выходами на связь: экран про канал, а
            # длина молчания и есть его качество.
            "avg_silence_min": round(sum(паузы) / len(паузы)) if паузы else None,
            "max_silence_min": max(паузы) if паузы else None,
            "down_waiting": sum(1 for d in downlink if d["state"] == "ждёт станции"),
            "down_unacked": sum(1 for d in downlink if d["state"] == "доставлено"),
            "down_acked": sum(1 for d in downlink if d["state"] == "применено"),
        },
        "sessions": sessions,
        "by_kind": by_kind,
        "downlink": downlink,
    }


# -- Мастер-НСИ ------------------------------------------------------------
# Карточки, штрихкоды и цены Ledger — не зеркало 1С, а собственный справочник.
# Он наполняется потоком снимков со станции (справочника ШК в 1С не существует)
# и правится здесь: станция карточки не заводит, это правило владения данными.

class NsiItemIn(BaseModel):
    name: str | None = None
    name_full: str | None = None
    unit: str | None = None
    vat_rate: str | None = None
    kind: str | None = None
    sku_class: str | None = None
    is_dish: bool | None = None
    price_owner: str | None = None
    deleted: bool | None = None


class NsiPriceIn(BaseModel):
    station_id: int
    price: float


class NsiBarcodeIn(BaseModel):
    code: str


async def _queue_nsi_delta(db: AsyncSession, cid, item_id: int, station_id: int | None = None) -> int:
    """Положить карточку в очередь заданий станции.

    Правка в центре сама по себе ничего не меняет на АЗС: станция за CGNAT, и
    достучаться до неё нельзя — она забирает задания своим тактом. Поэтому цена
    и карточка едут вниз тем же каналом, что и заготовки приёмки.

    Едет карточка ЦЕЛИКОМ, а не изменённое поле: станция могла пропустить
    предыдущую правку (не было связи), и дельта «только новая цена» оставила бы
    её со старым названием и старой ставкой. Полный снимок карточки
    идемпотентен — применить его дважды безопасно.
    """
    card = (await db.execute(text("""
        SELECT i.external_uuid, i.name, i.unit, i.vat_rate, i.deleted,
               coalesce(i.price_owner, 'master') AS price_owner
        FROM edge.item i WHERE i.id = :id
    """), {"id": item_id})).mappings().first()
    if card is None:
        return 0

    targets = [station_id] if station_id else [
        r[0] for r in (await db.execute(text("SELECT id FROM edge.station"))).all()]

    codes = [r[0] for r in (await db.execute(text(
        "SELECT code FROM edge.barcode WHERE item_id = :id AND status = 'active' ORDER BY code"
    ), {"id": item_id})).all()]

    for st in targets:
        price = (await db.execute(text("""
            SELECT price FROM edge.price
            WHERE item_id = :id AND station_id = :s AND valid_to IS NULL
        """), {"id": item_id, "s": st})).scalar_one_or_none()
        db.add(EdgeDownlink(
            company_id=cid, station_id=st, kind="nsi_delta",
            payload={"uuid": str(card["external_uuid"]), "name": card["name"],
                     "unit": card["unit"], "vat_rate": card["vat_rate"],
                     "deleted": bool(card["deleted"]), "barcodes": codes,
                     "price": float(price) if price is not None else None,
                     "price_owner": card["price_owner"]},
            note="НСИ: %s" % card["name"][:60],
        ))
    return len(targets)


@router.post("/nsi/push-recipes/{station_id}")
async def nsi_push_recipes(
    station_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить станции атомарный набор действующих версий ТТК."""
    cid: uuid.UUID = await scope_company_id(user, db)
    bundle = recipe_versions.build_bundle(await recipe_versions.active_versions(db, cid))
    agent = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id
    ))).scalar_one_or_none()
    applied = ((agent.payload or {}).get("recipe_bundle") or {}).get("bundle_id") if agent else None
    if applied == bundle["bundle_id"]:
        return {"ok": True, "already_current": True, "station_id": station_id,
                "bundle_id": bundle["bundle_id"], "блюд": len(bundle["recipes"])}

    pending = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == cid, EdgeDownlink.station_id == station_id,
        EdgeDownlink.kind == "recipes", EdgeDownlink.acked_at.is_(None),
    ).order_by(EdgeDownlink.created_at.desc()))).scalars().first()
    if pending and (pending.payload or {}).get("bundle_id") == bundle["bundle_id"]:
        return {"ok": True, "already_queued": True, "station_id": station_id,
                "bundle_id": bundle["bundle_id"], "task_id": str(pending.id),
                "блюд": len(bundle["recipes"])}

    task = EdgeDownlink(
        company_id=cid, station_id=station_id, kind="recipes",
        payload=bundle,
        note="ТТК %s: %d карт" % (bundle["bundle_id"], len(bundle["recipes"])),
    )
    db.add(task)
    await db.commit()
    return {"ok": True, "station_id": station_id, "bundle_id": bundle["bundle_id"],
            "task_id": str(task.id), "блюд": len(bundle["recipes"]),
            "ингредиентов": sum(len(recipe["lines"]) for recipe in bundle["recipes"])}


class RecipeDraftIn(BaseModel):
    dish_uuid: str
    dish_name: str | None = None
    recipe_kind: str | None = None
    output_qty: float | None = None
    output_unit: str | None = None
    lines: list[dict] | None = None


class RecipeUpdateIn(BaseModel):
    dish_name: str | None = None
    recipe_kind: str | None = None
    output_qty: float | None = None
    output_unit: str | None = None
    lines: list[dict] | None = None


class RecipeActivateIn(BaseModel):
    valid_from: datetime | None = None


def _delivery_state(latest: EdgeDownlink | None, agent: EdgeAgent | None,
                    current_bundle: str | None) -> dict:
    payload = latest.payload if latest else {}
    queued_bundle = payload.get("bundle_id")
    details = agent.payload if agent else {}
    applied_info = details.get("recipe_bundle") or {}
    applied = applied_info.get("bundle_id")
    latest_is_current = queued_bundle == current_bundle
    if current_bundle and current_bundle == applied:
        state = "applied"
    elif latest is None or not latest_is_current:
        state = "outdated" if applied else "not_sent"
    elif latest.acked_at is not None:
        state = "mismatch"
    elif latest.delivered_at is not None:
        state = "delivered"
    else:
        state = "queued"
    return {
        "station_id": latest.station_id if latest else agent.station_id,
        "state": state, "desired_bundle": current_bundle,
        "queued_bundle": queued_bundle, "applied_bundle": applied,
        "created_at": latest.created_at if latest else None,
        "delivered_at": latest.delivered_at if latest else None,
        "acked_at": latest.acked_at if latest else None,
        "agent_last_seen": agent.last_seen if agent else None,
        "recipe_bundle": applied_info,
        "readiness": details.get("catering_readiness"),
    }


@router.get("/recipes/versions")
async def recipe_versions_workspace(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    rows = list((await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == cid
    ).order_by(StoreRecipeVersion.dish_name, StoreRecipeVersion.version.desc()))).scalars().all())
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(row.dish_uuid, {
            "dish_uuid": row.dish_uuid, "dish_name": row.dish_name,
            "recipe_kind": row.recipe_kind, "active": None, "draft": None, "history": [],
        })
        data = recipe_versions.row_dict(row)
        item["history"].append(data)
        if row.status == "draft" and item["draft"] is None:
            item["draft"] = data
        if row.status == "active" and row.valid_to is None and item["active"] is None:
            item["active"] = data

    active = await recipe_versions.active_versions(db, cid)
    bundle = recipe_versions.build_bundle(active) if active else None
    active_ids = {row.id for row in active}
    for item in grouped.values():
        item["active"] = next(
            (version for version in item["history"]
             if uuid.UUID(version["id"]) in active_ids), None)
    agents = list((await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == cid))).scalars().all())
    tasks = list((await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == cid, EdgeDownlink.kind == "recipes",
    ).order_by(EdgeDownlink.station_id, EdgeDownlink.created_at.desc()))).scalars().all())
    latest_by_station: dict[int, EdgeDownlink] = {}
    for task in tasks:
        latest_by_station.setdefault(task.station_id, task)
    agent_by_station = {agent.station_id: agent for agent in agents}
    station_ids = sorted(set(latest_by_station) | set(agent_by_station))
    current_bundle = bundle["bundle_id"] if bundle else None
    deliveries = [_delivery_state(latest_by_station.get(station_id),
                                  agent_by_station.get(station_id), current_bundle)
                  for station_id in station_ids]

    legacy_available = 0
    if not rows:
        try:
            legacy_available = int((await db.execute(text(
                "SELECT count(*) FROM edge.recipe"))).scalar() or 0)
        except Exception:
            await db.rollback()
    return {
        "bundle": bundle, "legacy_available": legacy_available,
        "summary": {
            "recipes": len(grouped),
            "active": sum(1 for item in grouped.values() if item["active"]),
            "drafts": sum(1 for item in grouped.values() if item["draft"]),
        },
        "recipes": list(grouped.values()), "deliveries": deliveries,
    }


@router.post("/recipes/bootstrap")
async def recipe_versions_bootstrap(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    count = await recipe_versions.bootstrap_legacy(db, cid, user.id)
    return {"ok": True, "created": count}


@router.post("/recipes/draft")
async def recipe_create_draft(
    body: RecipeDraftIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await recipe_versions.create_draft(
        db, await scope_company_id(user, db), user.id, body.model_dump(exclude_none=True))
    return recipe_versions.row_dict(row)


@router.put("/recipes/{version_id}")
async def recipe_update_draft(
    version_id: uuid.UUID,
    body: RecipeUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await recipe_versions.update_draft(
        db, await scope_company_id(user, db), version_id,
        body.model_dump(exclude_none=True))
    return recipe_versions.row_dict(row)


@router.post("/recipes/{version_id}/activate")
async def recipe_activate(
    version_id: uuid.UUID,
    body: RecipeActivateIn | None = Body(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await recipe_versions.activate(
        db, await scope_company_id(user, db), version_id,
        body.valid_from if body else None)
    return recipe_versions.row_dict(row)


@router.get("/parity")
async def store_parity(
    station_id: int = Query(208),
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Паритет с 1С: что она делает и что за то же время делаем мы.

    Нужен на весь период параллельной работы. Пока 1С ведёт учёт станции, её
    пакеты приходят тем же каналом — и по ним видно, каких видов документов мы
    ещё не создаём. Это вопрос охвата, а не точности: сходимость сумм проверяет
    сверка смен.
    """
    cid = await scope_company_id(user, db)
    return await edge_service.parity(db, cid, station_id, days)


@router.get("/station-health")
async def store_station_health(
    station_id: int = Query(..., description="код АЗС"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Что на станции требует человека: касса, выгрузка, учёт, коды, сверка.

    Тот же отчёт, что агент забирает по api-key, — но для менеджера в
    «Магазине». Раньше эти находки существовали только в машинном контуре и
    доезжали до людей письмом; экран снимает посредника.
    """
    cid = await scope_company_id(user, db)
    return await edge_service.alerts(db, cid, station_id)


@router.get("/reconcile")
async def store_reconcile(
    station_id: int | None = Query(None, description="код АЗС; пусто — все"),
    limit: int = Query(60, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Теневая сверка смен: пакет агента против пакета 1С.

    Пока 1С ведёт учёт станции параллельно, сходимость по каждой смене — это
    единственное доказательство, что агент считает правильно. Критерий этапа —
    четырнадцать чистых дней ПОДРЯД и свежих, а не «столько-то совпало».
    """
    cid = await scope_company_id(user, db)
    return await edge_service.reconcile(db, cid, station_id, limit)


@router.get("/places")
async def store_places(
    station_id: int = Query(208),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Остатки станции в разрезе мест хранения.

    Отвечает на вопрос «где лежит товар», который у 1С был, а у Ledger — нет:
    остаток хранился одной цифрой на станцию, и склад с торговым залом
    складывались в кучу. Источник — снимок агента, а не выгрузка ЦБ: он
    приходит каждый час, а не раз в три недели.
    """
    cid = await scope_company_id(user, db)
    agent = (await db.execute(select(EdgeAgent.id).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(404, "Станция не принадлежит выбранной компании")
    rows = (await db.execute(select(StoreStockBalance).where(
        StoreStockBalance.company_id == cid,
        StoreStockBalance.station_id == station_id,
    ))).scalars().all()
    по_местам: dict[str, dict] = {}
    for row in rows:
        place = по_местам.setdefault(row.place, {
            "place": row.place,
            "name": row.place_name or f"место {row.place}",
            "sales_floor": row.place == str(station_id),
            "positions": 0,
            "qty": 0.0,
            "updated_at": row.snapshot_at,
        })
        place["positions"] += 1
        place["qty"] += float(row.quantity or 0)
        if row.snapshot_at > place["updated_at"]:
            place["updated_at"] = row.snapshot_at
    сводка = sorted(по_местам.values(), key=lambda row: (
        not row["sales_floor"], row["place"]))

    не_в_зале = [{
        "place_name": row.place_name or f"место {row.place}",
        "item_name": row.name,
        "barcode": row.barcode,
        "qty": float(row.quantity or 0),
    } for row in rows if row.place != str(station_id) and float(row.quantity or 0) > 0]
    не_в_зале.sort(key=lambda row: -row["qty"])

    return {
        "station_id": station_id,
        "source": "edge_agent",
        "places": сводка,
        "not_on_floor": не_в_зале[:200],
    }


class AssortmentRuleIn(BaseModel):
    active: bool = True
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    reason: str | None = None


@router.get("/assortment/{station_id}")
async def assortment_rules(
    station_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Явные включения и стопы ассортиментной матрицы станции."""
    cid = await scope_company_id(user, db)
    rows = (await db.execute(text("""
        SELECT r.item_uuid, coalesce(i.name, r.item_uuid) AS name, r.active,
               r.valid_from, r.valid_to, r.reason, r.updated_at
        FROM store_assortment_rules r
        LEFT JOIN edge.item i ON i.external_uuid::text = r.item_uuid
        WHERE r.company_id = :cid AND r.station_id = :st
        ORDER BY r.active, coalesce(i.name, r.item_uuid)
    """), {"cid": cid, "st": station_id})).mappings().all()
    return {"station_id": station_id, "rules": [dict(row) for row in rows]}


@router.put("/assortment/{station_id}/{item_uuid}")
async def assortment_rule_set(
    station_id: int,
    item_uuid: str,
    body: AssortmentRuleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    if body.valid_from and body.valid_to and body.valid_to <= body.valid_from:
        raise HTTPException(400, "Дата окончания должна быть позже даты начала")
    agent = (await db.execute(select(EdgeAgent.id).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(404, "Станция не принадлежит выбранной компании")
    row = (await db.execute(select(StoreAssortmentRule).where(
        StoreAssortmentRule.company_id == cid,
        StoreAssortmentRule.station_id == station_id,
        StoreAssortmentRule.item_uuid == item_uuid,
    ))).scalar_one_or_none()
    if row is None:
        row = StoreAssortmentRule(
            company_id=cid, station_id=station_id, item_uuid=item_uuid)
        db.add(row)
    row.active = body.active
    row.valid_from = body.valid_from
    row.valid_to = body.valid_to
    row.reason = body.reason
    row.updated_by = user.id
    await db.commit()
    return {"ok": True, "station_id": station_id, "item_uuid": item_uuid,
            "active": row.active}


@router.post("/assortment/{station_id}/publish")
async def assortment_publish(
    station_id: int,
    default_active: bool = Query(
        True, description="товары без явного правила остаются разрешены"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить матрицу агенту для проверки против NeftoMS без записи в кассу."""
    cid = await scope_company_id(user, db)
    agent = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(404, "Станция не принадлежит выбранной компании")
    rules = (await db.execute(select(StoreAssortmentRule).where(
        StoreAssortmentRule.company_id == cid,
        StoreAssortmentRule.station_id == station_id,
    ).order_by(StoreAssortmentRule.item_uuid))).scalars().all()
    payload_rules = [{
        "item_uuid": row.item_uuid,
        "active": row.active,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "reason": row.reason,
    } for row in rules]
    content = json.dumps({"default_active": default_active, "rules": payload_rules},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    policy_id = hashlib.sha256(content.encode("utf-8")).hexdigest()
    pending = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == cid,
        EdgeDownlink.station_id == station_id,
        EdgeDownlink.kind == "cash_policy",
        EdgeDownlink.acked_at.is_(None),
    ).order_by(EdgeDownlink.created_at.desc()))).scalars().first()
    if pending and (pending.payload or {}).get("policy_id") == policy_id:
        return {"ok": True, "already_queued": True, "task_id": str(pending.id),
                "policy_id": policy_id}
    task = EdgeDownlink(
        company_id=cid,
        station_id=station_id,
        kind="cash_policy",
        payload={"policy_id": policy_id, "default_active": default_active,
                 "prepared_food_vat": "НДС22", "rules": payload_rules},
        note=f"Ассортимент: {len(payload_rules)} правил; только dry-run кассы",
    )
    db.add(task)
    await db.commit()
    return {"ok": True, "task_id": str(task.id), "policy_id": policy_id,
            "rules": len(payload_rules), "mode": "dry-run"}


@router.get("/assortment/{station_id}/publications")
async def assortment_publications(
    station_id: int,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    rows = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == cid,
        EdgeDownlink.station_id == station_id,
        EdgeDownlink.kind == "cash_policy",
    ).order_by(EdgeDownlink.created_at.desc()).limit(limit))).scalars().all()
    return {"station_id": station_id, "publications": [{
        "id": str(row.id),
        "policy_id": (row.payload or {}).get("policy_id"),
        "created_at": row.created_at,
        "delivered_at": row.delivered_at,
        "acked_at": row.acked_at,
        "mode": "dry-run",
    } for row in rows]}


@router.post("/nsi/push/{station_id}")
async def nsi_push(
    station_id: int,
    only_known: bool = Query(False, description="только карточки, связанные со станцией"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Залить станции весь её справочник одним заданием.

    Правки едут по одной, но первый раз реплика пуста, и рассылать 7 500
    карточек поштучно бессмысленно. Одно задание с массивом — станция получает
    справочник целиком и дальше живёт офлайн.

    По умолчанию шлём справочник целиком. Сначала фильтровали по связи со
    станцией (цена, остаток, код кассы), но это отсекало ровно те карточки,
    из-за которых всё и затевалось: распроданный товар связей не имеет, а в
    сменах прошлых дней встречается — и ставку по нему брать неоткуда. Семь
    тысяч карточек это около мегабайта, для машины станции ничто.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    фильтр = """
        AND (EXISTS (SELECT 1 FROM edge.price p
                      WHERE p.item_id = i.id AND p.station_id = :s AND p.valid_to IS NULL)
          OR EXISTS (SELECT 1 FROM edge.stock st JOIN edge.barcode b2 ON b2.id = st.barcode_id
                      WHERE b2.item_id = i.id AND st.station_id = :s)
          OR EXISTS (SELECT 1 FROM edge.ns_code n JOIN edge.barcode b3 ON b3.id = n.barcode_id
                      WHERE b3.item_id = i.id AND n.station_id = :s AND n.status = 'active'))
    """ if only_known else ""

    rows = (await db.execute(text(f"""
        SELECT i.external_uuid, i.name, i.unit, i.vat_rate, i.deleted,
               coalesce(i.price_owner, 'master') AS price_owner,
               (SELECT price FROM edge.price p
                 WHERE p.item_id = i.id AND p.station_id = :s AND p.valid_to IS NULL) AS price,
               coalesce((SELECT array_agg(b.code ORDER BY b.code) FROM edge.barcode b
                          WHERE b.item_id = i.id AND b.status = 'active'), '{{}}') AS codes
        FROM edge.item i
        WHERE NOT i.deleted {фильтр}
        ORDER BY i.name
    """), {"s": station_id})).mappings().all()

    items = [{"uuid": str(r["external_uuid"]), "name": r["name"], "unit": r["unit"],
              "vat_rate": r["vat_rate"], "deleted": bool(r["deleted"]),
              "price": float(r["price"]) if r["price"] is not None else None,
              "price_owner": r["price_owner"],
              "barcodes": list(r["codes"] or [])} for r in rows]
    if not items:
        raise HTTPException(404, "Для станции нет ни одной связанной карточки")

    # Пачками: задание уходит по HTTP целиком, и пакет на 7 500 карточек по
    # мобильному каналу станции — это отправка, которая не доедет.
    ПАЧКА = 500
    пачек = 0
    for i in range(0, len(items), ПАЧКА):
        часть = items[i:i + ПАЧКА]
        пачек += 1
        db.add(EdgeDownlink(
            company_id=cid, station_id=station_id, kind="nsi_bulk",
            payload={"items": часть, "часть": пачек,
                     "всего_частей": (len(items) + ПАЧКА - 1) // ПАЧКА},
            note="справочник: %d карточек (часть %d)" % (len(часть), пачек),
        ))
    await db.commit()
    return {"ok": True, "station_id": station_id, "карточек": len(items), "заданий": пачек}


VAT_CODES = ("НДС22", "НДС20", "НДС10", "НДС5", "НДС18_118", "БезНДС")
PRICE_OWNERS = ("master", "station")


async def _nsi_item_id(db: AsyncSession, ident: str) -> int:
    """Резолв карточки по id мастера или по GUID 1С: карточку открывают из
    справочника, где ключ — GUID, а внутри мастера ключ свой."""
    if len(ident) == 36 and "-" in ident:
        row = (await db.execute(text(
            "SELECT id FROM edge.item WHERE external_uuid = CAST(:u AS uuid)"
        ), {"u": ident})).scalar_one_or_none()
    else:
        row = (await db.execute(text("SELECT id FROM edge.item WHERE id = :i"),
                                {"i": int(ident) if ident.isdigit() else -1})).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Карточка не найдена в мастер-НСИ")
    return int(row)


@router.get("/nsi/items")
async def nsi_items(
    q: str = Query("", description="часть наименования, штрихкода или кода 1С"),
    station_id: int = Query(208),
    only_problem: bool = Query(False, description="только с дефектами НСИ"),
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр карточек мастер-НСИ с ценой, штрихкодами и остатком станции."""
    sql = """
        SELECT i.id, i.external_uuid, i.code_1c, i.name, i.unit, i.vat_rate,
               i.kind, i.sku_class, i.is_dish, i.deleted,
               (SELECT count(*) FROM edge.barcode b
                 WHERE b.item_id = i.id AND b.status = 'active')      AS barcodes,
               (SELECT count(*) FROM edge.barcode b
                 WHERE b.item_id = i.id AND b.status = 'rejected')    AS collisions,
               (SELECT p.price FROM edge.price p
                 WHERE p.item_id = i.id AND p.station_id = :st
                   AND p.valid_to IS NULL)                            AS price,
               (SELECT coalesce(sum(s.qty), 0) FROM edge.stock s
                  JOIN edge.barcode b2 ON b2.id = s.barcode_id
                 WHERE b2.item_id = i.id AND s.station_id = :st)      AS qty
        FROM edge.item i
        WHERE (:q = '' OR i.name ILIKE :like OR coalesce(i.code_1c,'') ILIKE :like
               OR EXISTS (SELECT 1 FROM edge.barcode b3
                           WHERE b3.item_id = i.id AND b3.code ILIKE :like))
    """
    if only_problem:
        # Дефект НСИ — то, из-за чего товар не пробьётся или уедет с неверным
        # налогом: устаревшая ставка, коллизия ШК, остаток без цены.
        sql += """
          AND (i.vat_rate IN ('НДС18_118','НДС20','НДС5')
               OR EXISTS (SELECT 1 FROM edge.barcode b4
                           WHERE b4.item_id = i.id AND b4.status = 'rejected')
               OR (EXISTS (SELECT 1 FROM edge.stock s2 JOIN edge.barcode b5 ON b5.id = s2.barcode_id
                            WHERE b5.item_id = i.id AND s2.station_id = :st AND s2.qty > 0)
                   AND NOT EXISTS (SELECT 1 FROM edge.price p2
                                    WHERE p2.item_id = i.id AND p2.station_id = :st
                                      AND p2.valid_to IS NULL)))
        """
    sql += " ORDER BY i.name LIMIT :lim"
    rows = (await db.execute(text(sql), {
        "q": q, "like": f"%{q}%", "st": station_id, "lim": limit})).mappings().all()
    return {"items": [dict(r) for r in rows], "total": len(rows), "station_id": station_id}


def _barcode_candidates(raw: str) -> list[str]:
    code = raw.strip(" \t\r\n\x00\x02\x03")
    if len(code) >= 3 and code[0] == "]" and code[1].isalpha() and code[2].isalnum():
        code = code[3:]
    result = [code]
    if code.isascii() and code.isdigit():
        if len(code) == 12:
            result.append("0" + code)
        elif len(code) in (13, 14) and code.startswith("0"):
            result.append(code[1:])
    return list(dict.fromkeys(value for value in result if value))


@router.get("/nsi/resolve-barcode")
async def nsi_resolve_barcode(
    code: str = Query(...),
    station_id: int = Query(208),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Точное сопоставление скана с карточкой, включая UPC↔EAN и GTIN-14."""
    candidates = _barcode_candidates(code)
    if not candidates:
        raise HTTPException(400, "Штрихкод пуст")
    rows = (await db.execute(text("""
        SELECT i.id, i.external_uuid, i.name, i.unit, i.vat_rate, b.code,
               (SELECT p.price FROM edge.price p
                 WHERE p.item_id = i.id AND p.station_id = :st
                   AND p.valid_to IS NULL) AS price
          FROM edge.barcode b
          JOIN edge.item i ON i.id = b.item_id
         WHERE b.status = 'active' AND b.code = ANY(CAST(:codes AS text[]))
           AND NOT i.deleted
         ORDER BY array_position(CAST(:codes AS text[]), b.code)
    """), {"codes": candidates, "st": station_id})).mappings().all()
    item_ids = {int(row["id"]) for row in rows}
    if not rows:
        raise HTTPException(404, "Штрихкод не найден в мастер-НСИ")
    if len(item_ids) > 1:
        raise HTTPException(409, "Штрихкод связан с несколькими карточками — нужна проверка НСИ")
    row = rows[0]
    return {
        "item_uuid": str(row["external_uuid"]), "name": row["name"],
        "unit": row["unit"], "vat_rate": row["vat_rate"],
        "barcode": row["code"],
        "retail_price": float(row["price"]) if row["price"] is not None else None,
    }


@router.get("/nsi/items/{item_id}")
async def nsi_item(
    item_id: str,
    station_id: int = Query(208),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Карточка целиком: поля, штрихкоды, история цен, коды кассы, остаток."""
    item_id = await _nsi_item_id(db, item_id)
    item = (await db.execute(text("""
        SELECT id, external_uuid, code_1c, name, name_full, unit, vat_rate,
               kind, sku_class, is_dish, coalesce(price_owner, 'master') AS price_owner,
               deleted, created_at, updated_at
        FROM edge.item WHERE id = :id
    """), {"id": item_id})).mappings().first()
    if item is None:
        raise HTTPException(404, "Карточка не найдена")

    barcodes = (await db.execute(text("""
        SELECT b.id, b.code, b.status, b.note, b.first_seen,
               (SELECT n.ns_code FROM edge.ns_code n
                 WHERE n.barcode_id = b.id AND n.station_id = :st
                   AND n.status = 'active') AS ns_code,
               (SELECT s.qty FROM edge.stock s
                 WHERE s.barcode_id = b.id AND s.station_id = :st) AS qty
        FROM edge.barcode b WHERE b.item_id = :id
        ORDER BY b.status, b.code
    """), {"id": item_id, "st": station_id})).mappings().all()

    prices = (await db.execute(text("""
        SELECT id, station_id, price, valid_from, valid_to, author
        FROM edge.price WHERE item_id = :id AND station_id = :st
        ORDER BY valid_from DESC LIMIT 20
    """), {"id": item_id, "st": station_id})).mappings().all()

    return {"item": dict(item), "barcodes": [dict(b) for b in barcodes],
            "prices": [dict(p) for p in prices], "station_id": station_id}


@router.put("/nsi/items/{item_id}")
async def nsi_item_update(
    item_id: str,
    body: NsiItemIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Правка карточки. UUID и код 1С не меняются: по ним держится связь с БП."""
    item_id = await _nsi_item_id(db, item_id)
    if body.vat_rate is not None and body.vat_rate not in VAT_CODES:
        raise HTTPException(400, f"Неизвестная ставка НДС: {body.vat_rate}")
    if body.price_owner is not None and body.price_owner not in PRICE_OWNERS:
        raise HTTPException(400, f"Неизвестный владелец цены: {body.price_owner}")

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Нечего менять")
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = item_id
    await db.execute(
        text(f"UPDATE edge.item SET {sets}, updated_at = now() WHERE id = :id"), fields)
    sent = await _queue_nsi_delta(db, await scope_company_id(user, db), item_id)
    await db.commit()
    return {"ok": True, "changed": [k for k in fields if k != "id"], "станций": sent}


@router.post("/nsi/items/{item_id}/price")
async def nsi_set_price(
    item_id: str,
    body: NsiPriceIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Установить цену на станции.

    Прежняя запись закрывается, новая открывается — цена ведётся историей, а не
    перезаписью: по какой цене продавали вчера, нужно знать для разбора продаж.
    """
    if body.price < 0:
        raise HTTPException(400, "Цена не может быть отрицательной")
    item_id = await _nsi_item_id(db, item_id)
    owner = (await db.execute(text(
        "SELECT coalesce(price_owner, 'master') FROM edge.item WHERE id = :id"
    ), {"id": item_id})).scalar_one()
    if owner == "station":
        raise HTTPException(
            409,
            "Право на цену передано станции: измените её на рабочем месте станции "
            "или сначала верните владельца цены центру",
        )

    await db.execute(text("""
        UPDATE edge.price SET valid_to = now()
        WHERE item_id = :id AND station_id = :st AND valid_to IS NULL
    """), {"id": item_id, "st": body.station_id})
    await db.execute(text("""
        INSERT INTO edge.price (item_id, station_id, price, author)
        VALUES (:id, :st, :p, :who)
    """), {"id": item_id, "st": body.station_id, "p": body.price,
            "who": getattr(user, "email", None) or "центр"})
    await _queue_nsi_delta(db, await scope_company_id(user, db), item_id, body.station_id)
    await db.commit()
    return {"ok": True, "price": body.price, "station_id": body.station_id,
            "note": "цена ушла на станцию; агент применит её своим тактом"}


@router.post("/nsi/items/{item_id}/barcode")
async def nsi_add_barcode(
    item_id: str,
    body: NsiBarcodeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Добавить штрихкод карточке.

    Если код уже активен у другой карточки — отказ, а не молчаливый перевес:
    перевесить значит сломать кассу тому товару, который сейчас по нему
    пробивается.
    """
    item_id = await _nsi_item_id(db, item_id)
    code = (body.code or "").strip()
    if not code:
        raise HTTPException(400, "Пустой штрихкод")
    owner = (await db.execute(text("""
        SELECT b.item_id, i.name FROM edge.barcode b
        JOIN edge.item i ON i.id = b.item_id
        WHERE b.code = :c AND b.status = 'active'
    """), {"c": code})).first()
    if owner is not None:
        if owner.item_id == item_id:
            return {"ok": True, "already": True}
        raise HTTPException(409, f"Штрихкод уже активен у карточки «{owner.name}»")
    await db.execute(text("""
        INSERT INTO edge.barcode (item_id, code, status) VALUES (:id, :c, 'active')
    """), {"id": item_id, "c": code})
    await _queue_nsi_delta(db, await scope_company_id(user, db), item_id)
    await db.commit()
    return {"ok": True}


@router.post("/nsi/barcodes/{barcode_id}/retire")
async def nsi_retire_barcode(
    barcode_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Перевести штрихкод в исторические: выпуск сменился, код больше не нужен."""
    res = await db.execute(text("""
        UPDATE edge.barcode SET status = 'historical'
        WHERE id = :id AND status = 'active'
    """), {"id": barcode_id})
    if res.rowcount == 0:
        raise HTTPException(404, "Активный штрихкод не найден")
    owner = (await db.execute(text("SELECT item_id FROM edge.barcode WHERE id = :id"),
                              {"id": barcode_id})).scalar_one()
    await _queue_nsi_delta(db, await scope_company_id(user, db), int(owner))
    await db.commit()
    return {"ok": True}


# -- Приёмка ---------------------------------------------------------------
# Первый документ, который Ledger порождает сам. Две точки ввода: центр заводит
# накладную (в т.ч. из ЭДО), станция принимает товар физически. Ордерная схема
# 1С:Розница: expected -- «к поступлению», accepted -- «принят». Пока документ
# не принят, остатки не двигаются.


class ReceiptLine(BaseModel):
    nomenclature_ref: str | None = None
    name: str
    barcode: str | None = None
    qty_expected: float = 0      # заявлено накладной
    qty_fact: float = 0          # посчитано по факту
    price: float = 0
    vat_rate: str | None = None
    vat_amount: float = 0
    amount: float = 0
    unit: str | None = None
    retail_price: float = 0
    markup: float = 0
    pack_factor: float = 0
    purpose: str | None = None
    series: str | None = None
    expiry: str | None = None
    upd_codes: list[str] = []
    mark_codes: list[str] = []
    pack_codes: list[str] = []
    requires_mark: bool = False
    no_card: bool = False


class ReceiptIn(BaseModel):
    station_id: int | None = None
    number: str | None = None
    doc_date: str | None = None
    supplier: str | None = None
    contract: str | None = None
    incoming_number: str | None = None
    incoming_date: str | None = None
    comment: str | None = None
    delivery_scheme: str = "supplier_to_station"
    receiving_warehouse: str | None = None
    signing_mode: str = "office_director"
    signer_name: str | None = None
    mchd_guid: str | None = None
    mchd_registry: str | None = None
    mchd_valid_until: str | None = None
    signature_status: str = "pending"
    signature_ref: str | None = None
    lines: list[ReceiptLine] = []


class ReceiptSignatureIn(BaseModel):
    signature_status: str
    signature_ref: str | None = None
    signer_name: str | None = None
    mchd_guid: str | None = None
    mchd_registry: str | None = None
    mchd_valid_until: str | None = None


class ReceiptDistributionLine(BaseModel):
    line_index: int
    qty: float


class ReceiptDistributionIn(BaseModel):
    station_id: int
    lines: list[ReceiptDistributionLine]


class ReceiptScanIn(BaseModel):
    code: str
    qty: float = 1
    lines: list[ReceiptLine] | None = None


def _parse_mchd_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Срок МЧД должен быть датой") from exc


def _validate_receipt_route(
    delivery_scheme: str, station_id: int | None, receiving_warehouse: str | None,
    signing_mode: str, signer_name: str | None, mchd_guid: str | None,
    mchd_registry: str | None, mchd_valid_until, signature_status: str,
    signature_ref: str | None, require_signature: bool = False,
) -> None:
    if delivery_scheme not in ("supplier_to_station", "central_warehouse"):
        raise HTTPException(400, "Неизвестная схема доставки")
    if delivery_scheme == "supplier_to_station" and not station_id:
        raise HTTPException(400, "Для прямой поставки выберите АЗС")
    if delivery_scheme == "central_warehouse" and not (receiving_warehouse or "").strip():
        raise HTTPException(400, "Укажите центральный или промежуточный склад")
    if signing_mode not in ("office_director", "station_mchd"):
        raise HTTPException(400, "Неизвестная схема подписания")
    if delivery_scheme == "central_warehouse" and signing_mode != "office_director":
        raise HTTPException(400, "Центральный приход подписывает офис")
    if signature_status not in ("pending", "signed"):
        raise HTTPException(400, "Неизвестный статус подписи")
    if signature_status == "signed" and not (signature_ref or "").strip():
        raise HTTPException(400, "Укажите идентификатор подписи из оператора ЭДО")
    if signing_mode == "station_mchd":
        if not all((signer_name, mchd_guid, mchd_registry, mchd_valid_until)):
            raise HTTPException(400, "Для подписания на АЗС заполните представителя и МЧД")
        if mchd_valid_until < date.today():
            raise HTTPException(400, "Срок действия МЧД истёк")
        if require_signature and signature_status != "signed":
            raise HTTPException(400, "Администратор должен подписать УПД личной УКЭП по МЧД")
    if require_signature and delivery_scheme == "central_warehouse" and signature_status != "signed":
        raise HTTPException(400, "Перед центральной приёмкой офис должен подписать УПД")


def _normalized_receipt_lines(r: StoreReceipt) -> list[dict]:
    lines = []
    for source in r.lines or []:
        line = dict(source)
        # До разделения кодов УПД и фактических сканов входящие коды лежали в
        # mark_codes. Старые ожидаемые документы нормализуем при чтении.
        if r.origin == "edo" and "upd_codes" not in line:
            line["upd_codes"] = list(line.get("mark_codes") or [])
            line["mark_codes"] = []
        lines.append(line)
    return lines


def _receipt_out(r: StoreReceipt) -> dict:
    lines = _normalized_receipt_lines(r)
    # Расхождение считаем на сервере: это главная колонка приёмки, и считать её
    # в двух местах нельзя -- разъедется.
    diff = sum(1 for l in lines
               if abs(float(l.get("qty_fact") or 0) - float(l.get("qty_expected") or 0)) > 1e-6)
    return {
        "id": str(r.id), "station_id": r.station_id, "number": r.number,
        "doc_date": r.doc_date, "supplier": r.supplier, "contract": r.contract,
        "incoming_number": r.incoming_number, "incoming_date": r.incoming_date,
        "status": r.status, "origin": r.origin, "comment": r.comment,
        "delivery_scheme": r.delivery_scheme,
        "receiving_warehouse": r.receiving_warehouse,
        "signing_mode": r.signing_mode, "signer_name": r.signer_name,
        "mchd_guid": r.mchd_guid, "mchd_registry": r.mchd_registry,
        "mchd_valid_until": r.mchd_valid_until,
        "signature_status": r.signature_status, "signature_ref": r.signature_ref,
        "signed_at": r.signed_at, "distribution": r.distribution or [],
        "lines": lines, "lines_count": len(lines), "diff_count": diff,
        "total_amount": float(r.total_amount or 0), "vat_amount": float(r.vat_amount or 0),
        "created_at": r.created_at, "updated_at": r.updated_at, "accepted_at": r.accepted_at,
    }


def _recalc(lines: list[dict]) -> float:
    """Сумма документа по ФАКТУ: платим за принятое, а не за заявленное."""
    total = 0.0
    for l in lines:
        amount = float(l.get("qty_fact") or 0) * float(l.get("price") or 0)
        l["amount"] = round(amount, 2)
        total += amount
    return round(total, 2)


def _canonical_mark_code(raw: str) -> str:
    code = str(raw or "").strip(" \t\r\n\x00\x02\x03")
    if len(code) >= 3 and code[0] == "]" and code[1].isalpha() and code[2].isalnum():
        code = code[3:]
    return code.replace("<GS>", "\x1d")


def _valid_gtin(code: str) -> bool | None:
    if len(code) not in (8, 12, 13, 14) or not code.isascii() or not code.isdigit():
        return None
    total = 0
    for position, digit in enumerate(reversed(code[:-1])):
        total += int(digit) * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10 == int(code[-1])


def _parse_scanned_product(raw: str) -> tuple[str, str | None, str]:
    code = str(raw or "").strip(" \t\r\n\x00\x02\x03")
    aim = code[:3] if len(code) >= 3 and code[0] == "]" else ""
    if aim and aim[1].isalpha() and aim[2].isalnum():
        code = code[3:]
    if not code:
        raise HTTPException(400, "Сканер не передал код")
    if len(code) > 512:
        raise HTTPException(400, "Код со сканера длиннее 512 символов")
    gs1 = code.replace("<GS>", "\x1d")
    mark_code = None
    label = "Code 128 / внутренний"
    if len(gs1) >= 16 and gs1.startswith("01") and gs1[2:16].isdigit():
        product = gs1[2:16]
        mark_code = code
        label = "GS1-128" if aim == "]C1" else "GS1 DataMatrix"
    elif len(gs1) >= 21 and gs1[:14].isdigit():
        product = gs1[:14]
        mark_code = code
        label = "табачная маркировка"
    else:
        product = code
        labels = {8: "EAN-8", 12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}
        if product.isdigit():
            label = labels.get(len(product), label)
    if _valid_gtin(product) is False:
        raise HTTPException(400, f"{label}: контрольная цифра не сходится — повторите сканирование")
    if len(product) == 14 and product.startswith("0"):
        product = product[1:]
    return product, mark_code, label


def _validate_scanned_marks(lines: list[dict]) -> None:
    all_codes: set[str] = set()
    for index, line in enumerate(lines, 1):
        scanned = [_canonical_mark_code(code) for code in line.get("mark_codes") or []]
        if len(scanned) != len(set(scanned)):
            raise HTTPException(400, f"В строке {index} один код маркировки отсканирован дважды")
        if any(code in all_codes for code in scanned):
            raise HTTPException(400, "Один код маркировки попал в несколько строк")
        all_codes.update(scanned)
        if not (line.get("requires_mark") or scanned or line.get("upd_codes")):
            continue
        qty = float(line.get("qty_fact") or 0)
        if abs(qty - round(qty)) > 1e-6:
            raise HTTPException(400, f"Строка {index}: маркированный товар принимается поштучно")
        if len(scanned) != int(round(qty)):
            raise HTTPException(
                400, f"Строка {index}: факт {qty:g}, отсканировано кодов {len(scanned)}")
        expected = {_canonical_mark_code(code) for code in line.get("upd_codes") or []}
        extra = [code for code in scanned if expected and code not in expected]
        if extra:
            raise HTTPException(400, f"Строка {index}: отсканирован код, которого нет в УПД")


@router.post("/receipts/from-upd", status_code=201)
async def receipt_from_upd(
    station_id: int | None = Query(None, description="код АЗС для прямой поставки"),
    delivery_scheme: str = Query("supplier_to_station"),
    receiving_warehouse: str | None = Query(None),
    signing_mode: str = Query("office_director"),
    signer_name: str | None = Query(None),
    mchd_guid: str | None = Query(None),
    mchd_registry: str | None = Query(None),
    mchd_valid_until: str | None = Query(None),
    file: UploadFile = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести приёмку из входящего УПД поставщика.

    Смысл всей затеи: строки, цены и коды маркировки поставщик уже прислал —
    набивать их заново некому и незачем. Приёмщик на станции только пересчитает
    товар по факту, а документ и коды уже готовы.

    Фактическое количество из УПД НЕ берём никогда: заявленное — это то, что
    обещали привезти, а принимаем мы то, что реально стоит на полу.
    """
    if file is None:
        raise HTTPException(400, "Файл УПД не передан")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Файл пуст")
    try:
        parsed = parse_upd(raw)
    except Exception as exc:  # noqa: BLE001 — показываем человеку, что не так
        raise HTTPException(400, f"УПД не разобран: {exc}") from exc
    if not parsed["lines"]:
        raise HTTPException(400, "В документе не найдено ни одной строки товара")

    valid_until = _parse_mchd_date(mchd_valid_until)
    _validate_receipt_route(
        delivery_scheme, station_id, receiving_warehouse, signing_mode,
        signer_name, mchd_guid, mchd_registry, valid_until, "pending", None)

    cid: uuid.UUID = await scope_company_id(user, db)
    now = datetime.now(timezone.utc)
    destination = str(station_id) if station_id else "ЦС"
    number = "УПД-%s-%s" % (destination, now.strftime("%y%m%d-%H%M"))
    lines = [{
        "nomenclature_ref": None,
        "name": l["name"], "barcode": l["barcode"] or None,
        "qty_expected": l["qty_expected"], "qty_fact": 0,
        "price": l["price"], "vat_rate": l["vat_rate"] or None,
        "amount": 0,
        "upd_codes": l["mark_codes"], "mark_codes": [], "pack_codes": l["pack_codes"],
        "requires_mark": bool(l["mark_codes"]),
    } for l in parsed["lines"]]

    row = StoreReceipt(
        company_id=cid, station_id=station_id, number=number, doc_date=now,
        supplier=parsed["supplier"] or None,
        incoming_number=parsed["incoming_number"] or None,
        # «К поступлению»: товар заявлен, но на складе его ещё нет — ровно
        # смысл ордерной схемы. Приёмщик переведёт в «принят», пересчитав.
        status="expected", origin="edo", lines=lines,
        delivery_scheme=delivery_scheme, receiving_warehouse=receiving_warehouse,
        signing_mode=signing_mode, signer_name=signer_name,
        mchd_guid=mchd_guid, mchd_registry=mchd_registry,
        mchd_valid_until=valid_until, signature_status="pending",
        total_amount=0, vat_amount=0,
        comment="Загружен из УПД поставщика",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    out = _receipt_out(row)
    out["parsed"] = {"marked_lines": parsed["marked_lines"],
                     "total_codes": parsed["total_codes"]}
    return out


@router.post("/receipts/{receipt_id}/send-to-station")
async def send_receipt_to_station(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить заготовку приёмки на станцию.

    Станция за CGNAT — постучаться к ней нельзя, поэтому кладём задание в
    очередь: агент заберёт его своим тактом и создаст документ у себя. Пока не
    заберёт, задание висит и будет предложено снова.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят — отправлять нечего")
    if row.delivery_scheme != "supplier_to_station" or row.station_id is None:
        raise HTTPException(409, "Центральный приход не отправляется как поставка на АЗС")

    db.add(EdgeDownlink(
        company_id=cid, station_id=row.station_id,
        kind="goods_receipt_expected",
        payload={
            "id": str(row.id), "number": row.number,
            "supplier": row.supplier, "incoming_number": row.incoming_number,
            "doc_date": row.doc_date.isoformat() if row.doc_date else None,
            "delivery_scheme": row.delivery_scheme,
            "receiving_warehouse": row.receiving_warehouse,
            "signing_mode": row.signing_mode, "signer_name": row.signer_name,
            "mchd_guid": row.mchd_guid, "mchd_registry": row.mchd_registry,
            "mchd_valid_until": row.mchd_valid_until.isoformat() if row.mchd_valid_until else None,
            "signature_status": row.signature_status, "signature_ref": row.signature_ref,
            "signed_at": row.signed_at.isoformat() if row.signed_at else None,
            "lines": [{
                **line,
                # Агент ожидает в mark_codes именно коды поставщика из УПД;
                # физические сканы на станции он ведёт отдельно.
                "mark_codes": line.get("upd_codes") or line.get("mark_codes") or [],
            } for line in row.lines or []],
        },
        note="приёмка %s" % row.number,
    ))
    if row.status == "draft":
        row.status = "expected"
    await db.commit()
    return {"ok": True, "station_id": row.station_id, "number": row.number,
            "lines": len(row.lines or [])}


@router.post("/receipts/{receipt_id}/signature")
async def record_receipt_signature(
    receipt_id: uuid.UUID,
    body: ReceiptSignatureIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Зафиксировать уже выполненную подпись оператора ЭДО и полномочие МЧД."""
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    valid_until = _parse_mchd_date(body.mchd_valid_until)
    signer_name = body.signer_name if row.signing_mode == "station_mchd" else row.signer_name
    mchd_guid = body.mchd_guid if row.signing_mode == "station_mchd" else row.mchd_guid
    mchd_registry = body.mchd_registry if row.signing_mode == "station_mchd" else row.mchd_registry
    mchd_until = valid_until if row.signing_mode == "station_mchd" else row.mchd_valid_until
    _validate_receipt_route(
        row.delivery_scheme, row.station_id, row.receiving_warehouse,
        row.signing_mode, signer_name, mchd_guid, mchd_registry, mchd_until,
        body.signature_status, body.signature_ref)
    row.signer_name = signer_name
    row.mchd_guid = mchd_guid
    row.mchd_registry = mchd_registry
    row.mchd_valid_until = mchd_until
    row.signature_status = body.signature_status
    row.signature_ref = body.signature_ref
    row.signed_at = datetime.now(timezone.utc) if body.signature_status == "signed" else None
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.post("/receipts/{receipt_id}/distribute", status_code=201)
async def distribute_central_receipt(
    receipt_id: uuid.UUID,
    body: ReceiptDistributionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Передать часть центрального прихода на АЗС внутренним перемещением."""
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    if row.delivery_scheme != "central_warehouse" or row.status != "accepted":
        raise HTTPException(409, "Распределять можно только принятый центральный приход")
    agent = (await db.execute(select(EdgeAgent.id).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == body.station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(400, "АЗС не подключена к «Магазину»")

    lines = row.lines or []
    distribution = list(row.distribution or [])
    used: dict[int, float] = {}
    for allocation in distribution:
        for item in allocation.get("lines") or []:
            idx = int(item.get("line_index", -1))
            used[idx] = used.get(idx, 0) + float(item.get("qty") or 0)

    task_lines = []
    allocation_lines = []
    seen = set()
    for requested in body.lines:
        idx, qty = requested.line_index, requested.qty
        if idx in seen or idx < 0 or idx >= len(lines) or qty <= 0:
            raise HTTPException(400, "Некорректные строки распределения")
        seen.add(idx)
        source = lines[idx]
        available = float(source.get("qty_fact") or 0) - used.get(idx, 0)
        if qty > available + 1e-6:
            raise HTTPException(400, f"По строке {idx + 1} доступно только {available:g}")
        marks = source.get("mark_codes") or []
        selected_marks = []
        if source.get("requires_mark") or marks:
            if abs(qty - round(qty)) > 1e-6:
                raise HTTPException(400, "Маркированный товар распределяется поштучно")
            offset = int(round(used.get(idx, 0)))
            selected_marks = marks[offset:offset + int(round(qty))]
            if len(selected_marks) != int(round(qty)):
                raise HTTPException(400, f"По строке {idx + 1} недостаточно кодов маркировки")
        task_lines.append({
            "item_uuid": source.get("nomenclature_ref") or "",
            "name": source.get("name") or "", "barcode": source.get("barcode") or "",
            "qty_sent": qty, "mark_codes": selected_marks,
            "unknown": not bool(source.get("nomenclature_ref")),
        })
        allocation_lines.append({"line_index": idx, "qty": qty})
    if not task_lines:
        raise HTTPException(400, "Укажите количество хотя бы по одной позиции")

    allocation_id = str(uuid.uuid4())
    task_id = f"central:{row.id}:{allocation_id}"
    now = datetime.now(timezone.utc)
    db.add(EdgeDownlink(
        company_id=cid, station_id=body.station_id, kind="incoming_transfer",
        payload={
            "id": task_id, "number": f"ЦР-{row.number}", "doc_date": now.isoformat(),
            "from_station": 0, "to_station": body.station_id,
            "from_name": row.receiving_warehouse, "to_name": f"АЗС {body.station_id}",
            "from_place": "warehouse",
            "comment": f"Распределение центральной приёмки {row.number}",
            "lines": task_lines,
        },
        note=f"central-distribution:{row.id}:{allocation_id}"[:300],
    ))
    distribution.append({
        "id": allocation_id, "station_id": body.station_id,
        "created_at": now.isoformat(), "lines": allocation_lines,
    })
    row.distribution = distribution
    await db.commit()
    return {"ok": True, "task_id": task_id, "station_id": body.station_id,
            "lines": len(task_lines)}


@router.post("/receipts/{receipt_id}/scan")
async def scan_receipt_barcode(
    receipt_id: uuid.UUID,
    body: ReceiptScanIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Атомарно принять один скан USB/радиосканера в центральном складе."""
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят — сканирование закрыто")
    if row.delivery_scheme != "central_warehouse":
        raise HTTPException(409, "Прямую поставку сканируют на агенте АЗС")

    product_barcode, mark_code, scan_type = _parse_scanned_product(body.code)
    qty = 1.0 if mark_code else float(body.qty)
    if not math.isfinite(qty) or qty <= 0 or qty > 100000:
        raise HTTPException(400, "Количество за один скан должно быть больше нуля")
    lines = ([line.model_dump() for line in body.lines]
             if body.lines is not None else _normalized_receipt_lines(row))

    def matches(stored: str | None) -> bool:
        return bool(set(_barcode_candidates(stored or "")) &
                    set(_barcode_candidates(product_barcode)))

    line_index = next((index for index, line in enumerate(lines)
                       if matches(line.get("barcode"))), None)
    if line_index is None:
        candidates = _barcode_candidates(product_barcode)
        found = (await db.execute(text("""
            SELECT i.id, i.external_uuid, i.name, i.unit, i.vat_rate, b.code
              FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
             WHERE b.status = 'active' AND NOT i.deleted
               AND b.code = ANY(CAST(:codes AS text[]))
             ORDER BY array_position(CAST(:codes AS text[]), b.code)
        """), {"codes": candidates})).mappings().all()
        item_ids = {int(item["id"]) for item in found}
        if len(item_ids) > 1:
            raise HTTPException(409, "Штрихкод связан с несколькими карточками — исправьте коллизию НСИ")
        if not found:
            raise HTTPException(404, "Штрихкод не найден в мастер-НСИ; товар не добавлен")
        item = found[0]
        lines.append({
            "nomenclature_ref": str(item["external_uuid"]), "name": item["name"],
            "barcode": item["code"], "qty_expected": 0, "qty_fact": 0,
            "price": 0, "vat_rate": item["vat_rate"], "amount": 0,
            "unit": item["unit"], "upd_codes": [], "mark_codes": [],
            "pack_codes": [], "requires_mark": bool(mark_code), "no_card": False,
        })
        line_index = len(lines) - 1

    line = lines[line_index]
    if mark_code:
        canonical = _canonical_mark_code(mark_code)
        if any(canonical == _canonical_mark_code(existing)
               for candidate in lines for existing in candidate.get("mark_codes") or []):
            raise HTTPException(409, "Этот код маркировки уже отсканирован — количество не изменено")
        expected = {_canonical_mark_code(code) for code in line.get("upd_codes") or []}
        if expected and canonical not in expected:
            raise HTTPException(409, "Кода маркировки нет в УПД поставщика — товар не принят")
        line["mark_codes"] = [*(line.get("mark_codes") or []), mark_code]
        line["requires_mark"] = True
    line["qty_fact"] = round(float(line.get("qty_fact") or 0) + qty, 3)
    row.lines = lines
    row.total_amount = _recalc(lines)
    await db.commit()
    await db.refresh(row)
    result = _receipt_out(row)
    result["scan"] = {
        "type": scan_type, "barcode": product_barcode,
        "line_index": line_index, "qty_added": qty,
        "name": line.get("name") or "",
    }
    return result


@router.get("/receipts")
async def list_receipts(
    station_id: int | None = Query(None),
    status: str | None = Query(None, description="draft|expected|accepted"),
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Журнал приёмок -- то же окно, что у товароведа в 1С."""
    cid: uuid.UUID = await scope_company_id(user, db)
    q = select(StoreReceipt).where(StoreReceipt.company_id == cid)
    if station_id is not None:
        q = q.where(StoreReceipt.station_id == station_id)
    if status:
        q = q.where(StoreReceipt.status == status)
    rows = (await db.execute(
        q.order_by(StoreReceipt.doc_date.desc(), StoreReceipt.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"receipts": [_receipt_out(r) for r in rows], "total": len(rows)}


@router.post("/receipts", status_code=201)
async def create_receipt(
    body: ReceiptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести приёмку в центре: накладная поставщика на конкретную станцию."""
    cid: uuid.UUID = await scope_company_id(user, db)
    valid_until = _parse_mchd_date(body.mchd_valid_until)
    _validate_receipt_route(
        body.delivery_scheme, body.station_id, body.receiving_warehouse,
        body.signing_mode, body.signer_name, body.mchd_guid, body.mchd_registry,
        valid_until, body.signature_status, body.signature_ref)
    lines = [l.model_dump() for l in body.lines]
    total = _recalc(lines)
    now = datetime.now(timezone.utc)
    doc_date = datetime.fromisoformat(body.doc_date) if body.doc_date else now
    if doc_date.tzinfo is None:
        doc_date = doc_date.replace(tzinfo=timezone.utc)
    # Номер по умолчанию -- дата и станция: различимый документ нужен сразу,
    # сквозная нумерация появится вместе со справочником поставщиков.
    destination = str(body.station_id) if body.station_id else "ЦС"
    number = body.number or ("П-%s-%s" % (destination, now.strftime("%y%m%d-%H%M")))

    row = StoreReceipt(
        company_id=cid, station_id=body.station_id, number=number, doc_date=doc_date,
        supplier=body.supplier, contract=body.contract,
        incoming_number=body.incoming_number,
        incoming_date=datetime.fromisoformat(body.incoming_date) if body.incoming_date else None,
        status="draft", origin="center", lines=lines,
        delivery_scheme=body.delivery_scheme,
        receiving_warehouse=body.receiving_warehouse,
        signing_mode=body.signing_mode, signer_name=body.signer_name,
        mchd_guid=body.mchd_guid, mchd_registry=body.mchd_registry,
        mchd_valid_until=valid_until, signature_status=body.signature_status,
        signature_ref=body.signature_ref,
        signed_at=now if body.signature_status == "signed" else None,
        total_amount=total, vat_amount=0, comment=body.comment,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.get("/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    return _receipt_out(row)


@router.put("/receipts/{receipt_id}")
async def update_receipt(
    receipt_id: uuid.UUID,
    body: ReceiptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Правка документа. Принятый не редактируется: это уже движение остатков."""
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят -- правка запрещена")

    valid_until = _parse_mchd_date(body.mchd_valid_until)
    _validate_receipt_route(
        body.delivery_scheme, body.station_id, body.receiving_warehouse,
        body.signing_mode, body.signer_name, body.mchd_guid, body.mchd_registry,
        valid_until, body.signature_status, body.signature_ref)
    lines = [l.model_dump() for l in body.lines]
    row.total_amount = _recalc(lines)
    row.lines = lines
    row.supplier = body.supplier
    row.contract = body.contract
    row.incoming_number = body.incoming_number
    row.incoming_date = datetime.fromisoformat(body.incoming_date) if body.incoming_date else None
    row.comment = body.comment
    row.station_id = body.station_id
    row.delivery_scheme = body.delivery_scheme
    row.receiving_warehouse = body.receiving_warehouse
    row.signing_mode = body.signing_mode
    row.signer_name = body.signer_name
    row.mchd_guid = body.mchd_guid
    row.mchd_registry = body.mchd_registry
    row.mchd_valid_until = valid_until
    row.signature_status = body.signature_status
    row.signature_ref = body.signature_ref
    row.signed_at = (datetime.now(timezone.utc) if body.signature_status == "signed"
                     and row.signed_at is None else row.signed_at)
    if body.number:
        row.number = body.number
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.post("/receipts/{receipt_id}/status")
async def set_receipt_status(
    receipt_id: uuid.UUID,
    status: str = Query(..., description="expected|accepted"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ордерная схема: «к поступлению» -> «принят».

    Принять документ без единой посчитанной позиции нельзя: это верный признак,
    что кнопку нажали раньше, чем пересчитали товар.
    """
    if status not in ("expected", "accepted"):
        raise HTTPException(400, "Допустимы только expected и accepted")
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят")
    if status == "accepted":
        if row.delivery_scheme == "supplier_to_station":
            raise HTTPException(409, "Прямую поставку принимает агент на станции")
        _validate_receipt_route(
            row.delivery_scheme, row.station_id, row.receiving_warehouse,
            row.signing_mode, row.signer_name, row.mchd_guid, row.mchd_registry,
            row.mchd_valid_until, row.signature_status, row.signature_ref,
            require_signature=True)
        if not row.lines:
            raise HTTPException(400, "В документе нет позиций")
        if not any(float(l.get("qty_fact") or 0) > 0 for l in row.lines):
            raise HTTPException(400, "Ни одна позиция не посчитана по факту")
        _validate_scanned_marks(row.lines or [])
        row.accepted_at = datetime.now(timezone.utc)
    row.status = status
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.get("/overview")
async def store_overview(
    date_from: str = Query(..., description="ISO дата начала периода"),
    date_to: str = Query(..., description="ISO дата конца периода"),
    stations: str | None = Query(None, description="коды АЗС через запятую (опц.)"),
    compare: bool = Query(False, description="сравнить с предыдущим периодом (Δ%)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """KPI обзора магазина за период (продажи сопутки/общепита)."""
    cid: uuid.UUID = await scope_company_id(user, db)
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).compute(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st, compare,
    )


@router.get("/skus")
async def store_skus(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр SKU с маржой и ABC (питает Ассортимент / Цены-маржа / Номенклатуру)."""
    cid: uuid.UUID = await scope_company_id(user, db)
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).sku_analytics(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/sales")
async def store_sales(
    date_from: str = Query(...),
    date_to: str = Query(...),
    group_by: str = Query("sku", description="sku|category|kind|marking|vat|day|payment"),
    category: str = Query("all", description="all|soputka|obshepit"),
    marked: str = Query("all", description="all|marked|plain"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Анализ продаж с гибкой группировкой и фильтрами (инструмент менеджера)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sales_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        group_by=group_by, category=category, marked=marked, q=q, stations=st,
    )


@router.get("/nomenclature")
async def store_nomenclature(
    date_from: str = Query(...),
    date_to: str = Query(...),
    kind: str = Query("all"),
    marked: str = Query("all"),
    weighed: str = Query("all"),
    has_sales: str = Query("all"),
    q: str = Query(""),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полный справочник номенклатуры + обогащение продажами/ШК + фильтры (мастер-НСИ)."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).nomenclature_catalog(
        date.fromisoformat(date_from), date.fromisoformat(date_to),
        kind=kind, marked=marked, weighed=weighed, has_sales=has_sales, q=q, stations=st,
    )


@router.get("/stock")
async def store_stock(
    warehouse: str | None = Query(None, description="код склада (по умолч. — с макс. SKU, обычно 208)"),
    q: str = Query(""),
    marked: str = Query("all", description="all|marked|plain"),
    only_negative: bool = Query(False, description="только отрицательные остатки"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Достоверный остаток товара (снимок регистров ЦБ ТоварыНаАЗК+Партии), не оценка."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).stock_onhand(
        warehouse=warehouse, q=q, marked=marked, only_negative=only_negative,
    )


def _od(s: str | None):
    return date.fromisoformat(s) if s else None


@router.get("/inventory")
async def store_inventory(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    only_dev: bool = Query(False, description="только документы с отклонениями"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр инвентаризаций ЦБ + недостачи/излишки (shrinkage) с drill-down по строкам."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).inventory(
        warehouse=warehouse, only_dev=only_dev, date_from=_od(date_from), date_to=_od(date_to),
    )


@router.get("/writeoffs")
async def store_writeoffs(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    reason: str | None = Query(None, description="фильтр по причине"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр списаний ЦБ (СписаниеТоваров) + причины + топ списанных SKU."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).writeoffs(
        warehouse=warehouse, reason=reason, date_from=_od(date_from), date_to=_od(date_to),
    )


@router.get("/transfers")
async def store_transfers(
    direction: str | None = Query(None, description="фильтр по направлению"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр перемещений ЦБ (ПеремещениеТоваров) откуда→куда + направления."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).transfers(
        direction=direction, date_from=_od(date_from), date_to=_od(date_to))


@router.get("/revaluation")
async def store_revaluation(
    reason: str | None = Query(None, description="фильтр направления (Подорожание/Удешевление/Смешанная)"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая цена, Δ%, влияние."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).revaluation(
        reason=reason, date_from=_od(date_from), date_to=_od(date_to))


@router.get("/catering")
async def store_catering(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Инжиниринг меню общепита: блюда + фудкост/маржа + класс меню + состав ТТК + динамика."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).catering_menu(
        date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/pricing")
async def store_pricing(
    date_from: str = Query(...),
    date_to: str = Query(...),
    category: str = Query("all", description="all|soputka|obshepit"),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Цены и маржа: сегмент (сопутка/общепит/всё) + группы + реестр SKU."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).pricing_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to), category=category, stations=st,
    )


@router.get("/assortment")
async def store_assortment(
    date_from: str = Query(...),
    date_to: str = Query(...),
    category: str = Query("all", description="all|soputka|obshepit"),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ассортимент: ABC×XYZ + оборачиваемость/запасы + GMROI + дефицит/неликвиды + action-list."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).assortment_analysis(
        date.fromisoformat(date_from), date.fromisoformat(date_to), category=category, stations=st,
    )


@router.get("/sku/{guid}")
async def store_sku_detail(
    guid: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Детализация товара (модалка): метрики + история цен + продажи + закупки + остаток."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sku_detail(
        guid, date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


@router.get("/sku-card/{guid}")
async def store_sku_card(
    guid: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полная карточка номенклатуры (товаровед): паспорт + ШК + цена/остаток +
    продажи + поставщики + движение + рецептура ТТК + МРЦ."""
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, await scope_company_id(user, db)).sku_card(
        guid, date.fromisoformat(date_from), date.fromisoformat(date_to), st,
    )


def _stations(stations: str | None) -> list[str] | None:
    return [s.strip() for s in stations.split(",") if s.strip()] if stations else None


# ── Слой политик: план продаж + план-факт-светофор (О-1) ──
# Регистрируются ДО catch-all /{report}, иначе /plan перехватится как отчёт.

class _PlanItem(BaseModel):
    scope_kind: str = "total"       # total | category | station
    scope_key: str = "*"            # имя категории / код АЗС / '*'
    metric: str = "revenue"         # revenue | qty
    plan_value: float = 0


class _PlanSave(BaseModel):
    period: str                     # 'YYYY-MM'
    items: list[_PlanItem] = []


@router.get("/plan")
async def store_get_plan(
    period: str = Query(..., description="Месяц плана 'YYYY-MM'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """План продаж магазина на месяц (сырьё для формы редактирования)."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).get_plans(period)


@router.put("/plan")
async def store_save_plan(
    body: _PlanSave,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить план (ручной ввод руководителя). Значение ≤0 удаляет строку."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).save_plans(
        body.period, [i.model_dump() for i in body.items],
    )


@router.get("/plan-facts")
async def store_plan_facts(
    period: str = Query(..., description="Месяц 'YYYY-MM'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """План-факт-светофор за месяц: карты факт/план/%/🟢🟡🔴 + спарклайн."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).plan_facts(period)


# ── МРЦ табака: регуляторный контроль «продажа выше МРЦ» (О-3) ──

class _MrcRow(BaseModel):
    barcode: str | None = None
    article: str | None = None
    name: str | None = None
    mrc: float | str | None = None


class _MrcImport(BaseModel):
    rows: list[_MrcRow] = []


@router.get("/mrc")
async def store_mrc(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Контроль МРЦ табака: розница vs МРЦ (нарушения) + табак без МРЦ."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).mrc_control()


@router.post("/mrc/import")
async def store_mrc_import(
    body: _MrcImport,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Импорт справочника МРЦ (CSV → строки). Матч по штрихкоду/артикулу."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).import_mrc(
        [r.model_dump() for r in body.rows],
    )


@router.get("/shifts")
async def store_shifts(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смены как составной документ: продажи + приходы/инвентаризации/списания/возвраты за смену."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).shifts_composite(
        date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations),
    )


@router.get("/shift")
async def store_shift_detail(
    key: str = Query(..., description="shift_key (GUID смены или 'дата|станция')"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Смена-детализация (модалка): строки продаж + касса + приходы/инвентаризации/списания дня."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).shift_detail(key)


@router.get("/bp-package")
async def store_bp_package(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview пакета «смена→БП» (эмиттер Ledger): все типы документов + НСИ + хеш."""
    from app.services.bp_export import BpPackageEmitter
    try:
        return await BpPackageEmitter(db, await scope_company_id(user, db)).build_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(404 if str(e).startswith("смена не найдена") else 409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сборка пакета: {e}")


@router.post("/bp-package/emit")
async def store_bp_package_emit(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить пакет в серверный каталог BP_EXPORT_DIR (клиент путь НЕ задаёт).
    Файл АЗС{код}_{дата}_смена-{номер}_{uuid}.json."""
    from app.services.bp_export import BpPackageEmitter
    cid = await scope_company_id(user, db)
    try:
        res = await BpPackageEmitter(db, cid).emit_to_dir(shift_key, BP_EXPORT_DIR)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Выгрузка в каталог: {e}")

    # След выгрузки: единственное действие раздела, меняющее состояние снаружи —
    # файл ложится в каталог обмена и уходит в БП. Хеш нужен, чтобы потом
    # опознать, какой именно пакет приёмник забрал (идемпотентность по ХешПакета).
    docs = sum(res.get("documents", {}).values())
    log_export(db, cid, user,
               f"Пакет Ledger→БП, смена {shift_key}: {res.get('file')}, "
               f"{docs} документов, НСИ {res.get('nsi')}, хеш {res.get('hash')}")
    return res


@router.get("/bp-package/verify")
async def store_bp_package_verify(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сверка сопутки: самосогласованность пакета + готовность к загрузке (балансы,
    полнота НСИ, fail-fast НДС, хеш). Список проверок ok/детали."""
    from app.services.bp_export import BpPackageEmitter
    try:
        return await BpPackageEmitter(db, await scope_company_id(user, db)).verify_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(404 if str(e).startswith("смена не найдена") else 409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сверка: {e}")


@router.post("/edge/reproject")
async def store_edge_reproject(
    station_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пересобрать канонические документы Ledger из ранее принятых EdgePacket."""
    cid = await scope_company_id(user, db)
    if not user.is_superadmin:
        membership = await db.get(UserCompany, (user.id, cid))
        if membership is None or membership.role != "admin":
            raise HTTPException(403, "Пересборка Edge доступна только администратору компании")
    result = await edge_projection.reproject_packets(db, cid, station_id)
    await db.commit()
    return result


@router.get("/barcodes")
async def store_barcodes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Справочник штрихкодов — снимок НСИ. Периода/станций у сущности нет, поэтому
    и параметров нет (раньше требовались роутером и молча игнорировались)."""
    return await GoodsDashboardService(db, await scope_company_id(user, db)).barcodes()


@router.get("/{report}")
async def store_report(
    report: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёты раздела по периоду: receipts · suppliers · catering · categories · recipes.
    barcodes — отдельный маршрут выше (справочник вне периода)."""
    svc = GoodsDashboardService(db, await scope_company_id(user, db))
    method = {"receipts": svc.receipts, "suppliers": svc.suppliers,
              "catering": svc.catering, "categories": svc.categories,
              "recipes": svc.recipes}.get(report)
    if method is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Неизвестный отчёт: {report}")
    return await method(date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations))


# ─────────────────────────── Контроль дублей ────────────────────────────────
# Анализ дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ.
from app.services import dedup_service


@router.get("/dedup/summary")
async def dedup_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.summary(db, await scope_company_id(user, db))


@router.get("/dedup/groups")
async def dedup_groups(
    q: str | None = Query(None),
    include_assortment: bool = Query(False),
    only_live: bool = Query(False),
    price_desync: bool = Query(False),
    only_scope_208: bool = Query(True),
    status: str | None = Query(None),
    era: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await scope_company_id(user, db)
    return await dedup_service.groups(db, cid, q=q, include_assortment=include_assortment,
                                      only_live=only_live, status=status, price_desync=price_desync,
                                      only_scope_208=only_scope_208, era=era)


@router.post("/dedup/reload")
async def dedup_reload(
    file: UploadFile,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Обновить срез: загрузить свежий дамп 208 (probe-раннер) + склейка ЦБ."""
    cid = await scope_company_id(user, db)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Дамп слишком большой")
    text = raw.decode("utf-8", "replace")
    if "#CARDS" not in text:
        raise HTTPException(400, "Не похоже на дамп 208 (нет секции #CARDS)")
    return await dedup_service.load_dump(db, cid, text)


@router.post("/dedup/facts")
async def dedup_facts(
    file: UploadFile,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Загрузить факты эры продаж (День X 11.06.2026) + остаток по карточкам 208.
    Файл: секции #GIG / #NEVER / #OST(guid|остаток) / #END."""
    cid = await scope_company_id(user, db)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Файл слишком большой")
    text = raw.decode("utf-8", "replace")
    if "#GIG" not in text and "#NEVER" not in text and "#OST" not in text:
        raise HTTPException(400, "Не похоже на файл фактов (нет секций #GIG/#NEVER/#OST)")
    return await dedup_service.load_facts(db, cid, text)


@router.get("/dedup/bridge")
async def dedup_bridge(
    kind: str = Query("on_marked", pattern="^(on_marked|multi|price_split)$"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await dedup_service.bridge(db, await scope_company_id(user, db), kind=kind)


class DedupStatusBody(BaseModel):
    entityType: str            # group | card
    entityKey: str
    status: str | None = None
    canonGuid: str | None = None
    note: str | None = None


@router.post("/dedup/status")
async def dedup_set_status(
    body: DedupStatusBody,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if body.entityType not in ("group", "card"):
        raise HTTPException(400, "entityType: group|card")
    cid = await scope_company_id(user, db)
    row = await dedup_service.set_status(
        db, cid, entity_type=body.entityType, entity_key=body.entityKey,
        status=body.status, canon_guid=body.canonGuid, note=body.note, user=user.name or user.email)
    return {"status": row.status, "canonGuid": row.canon_guid, "note": row.note,
            "history": row.history}


@router.get("/dedup/export")
async def dedup_export(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.export_plan(db, await scope_company_id(user, db))


# ── корректировки по команде менеджера ───────────────────────────────────────
class CorrectBody(BaseModel):
    groupKeys: list[str]
    dryRun: bool = False


@router.post("/dedup/correct")
async def dedup_correct(
    body: CorrectBody,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Команда менеджера: создать задание перецепа кодов НС на канон по выбранным
    группам (нода 208 выполнит). dryRun=true — пробный прогон (план без записи)."""
    if not body.groupKeys:
        raise HTTPException(400, "Не выбраны группы")
    cid = await scope_company_id(user, db)
    return await dedup_service.create_repoint_job(
        db, cid, group_keys=body.groupKeys, dry_run=body.dryRun, user=user.name or user.email)


@router.post("/dedup/refresh")
async def dedup_refresh(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Команда менеджера: станция снимет свежий срез с локальной 1С и зальёт сюда
    (бэкенд в сеть станции не ходит — идём через очередь заданий)."""
    cid = await scope_company_id(user, db)
    return await dedup_service.create_refresh_job(db, cid, user=user.name or user.email)


@router.get("/dedup/jobs")
async def dedup_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await dedup_service.list_jobs(db, await scope_company_id(user, db))


@router.post("/dedup/jobs/{job_id}/cancel")
async def dedup_job_cancel(
    job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        jid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Невалидный ID")
    ok = await dedup_service.cancel_job(db, await scope_company_id(user, db), jid)
    if not ok:
        raise HTTPException(404, "Задание не найдено или уже выполнено")
    return {"ok": True}


@router.get("/dedup/merge-map")
async def dedup_merge_map(
    group_keys: str | None = Query(None, description="ключи групп через | (опц.)"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Карта слияния дубль→канон для .epf (ЗаменитьСсылки — запуск руками в тихое окно)."""
    keys = [k for k in group_keys.split("|") if k] if group_keys else None
    return await dedup_service.merge_map(db, await scope_company_id(user, db), group_keys=keys)


@router.get("/dedup/deactivation-plan")
async def dedup_deactivation_plan(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """План «снять с продажи»: активные коды кассы 208 на карточках архивных групп
    (status=not_used) — на деактивацию. НЕ удаление (карточка/история остаются)."""
    return await dedup_service.deactivation_plan(db, await scope_company_id(user, db))


@router.get("/station-drafts")
async def store_station_drafts(
    station_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Что станции решили сами и что ждёт признания центром.

    Карточки и контрагенты, заведённые на местах, плюс цены, назначенные
    станциями. Первые два — очередь на разбор: каноном карточку делает человек
    здесь, сопоставляя её по штрихкоду с сетевой (дедуп возможен только там,
    где виден справочник всей сети). Цены — журнал: их не подтверждают, но по
    ним видно, кто и почему поменял цену на полке.
    """
    cid = await scope_company_id(user, db)
    return await edge_nsi.station_drafts(db, cid, station_id)


@router.post("/station-drafts/item/{draft_id}")
async def store_resolve_item_draft(
    draft_id: int,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по черновику карточки: привязать, завести новую или отклонить.

    После признания станции уходит задание НСИ: она заменит свой черновик
    каноном, переклеив на него движения и журнал цен. Без этого шага на станции
    остались бы две карточки на один штрихкод — то, ради чего очередь и
    заведена.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    try:
        res = await edge_nsi.resolve_item_draft(
            db, cid, draft_id, str(body.get("action") or ""),
            body.get("item_id"), body.get("note"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if res["action"] in ("link", "create"):
        row = (await db.execute(text("""
            SELECT i.external_uuid, i.name, i.unit, i.vat_rate,
                   coalesce((SELECT array_agg(b.code ORDER BY b.code) FROM edge.barcode b
                              WHERE b.item_id = i.id AND b.status = 'active'), '{}') AS codes,
                   (SELECT price FROM edge.price p
                     WHERE p.item_id = i.id AND p.station_id = :s AND p.valid_to IS NULL) AS price,
                   i.price_owner
            FROM edge.item i WHERE i.id = :id
        """), {"id": res["item_id"], "s": res["station_id"]})).mappings().first()
        if row is not None:
            db.add(EdgeDownlink(
                # nsi_delta — вид, который агент умеет разбирать. Первая версия
                # ставила «nsi_item», и станция честно писала «неизвестное
                # задание центра», а признанная карточка до неё не доезжала.
                company_id=cid, station_id=res["station_id"], kind="nsi_delta",
                payload={"uuid": str(row["external_uuid"]), "name": row["name"],
                         "unit": row["unit"], "vat_rate": row["vat_rate"],
                         "barcodes": list(row["codes"] or []),
                         "price": float(row["price"]) if row["price"] is not None else None,
                         "price_owner": row["price_owner"], "deleted": False},
            ))
            await db.commit()
            res["pushed"] = True
    return res


@router.post("/station-drafts/partner/{draft_id}")
async def store_resolve_partner_draft(
    draft_id: int,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по контрагенту станции: принять в справочник сети или отклонить."""
    cid: uuid.UUID = await scope_company_id(user, db)
    try:
        return await edge_nsi.resolve_partner_draft(
            db, cid, draft_id, str(body.get("action") or ""), body.get("note"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/station-drafts/proposal/{proposal_id}")
async def store_resolve_nsi_proposal(
    proposal_id: int,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по заявке станции об ошибке в сетевой карточке.

    Принять — правка применяется к канону: на станции она всё это время не
    применялась, карточка там оставалась прежней. Отклонить — заявка
    закрывается с пояснением, чтобы её не слали снова.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    try:
        return await edge_nsi.resolve_nsi_proposal(
            db, cid, proposal_id, str(body.get("action") or ""), body.get("note"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/station-drafts/candidates")
async def store_draft_candidates(
    barcodes: str = Query(..., description="штрихкоды через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Карточки сети, на которые похож черновик — по штрихкоду."""
    cid: uuid.UUID = await scope_company_id(user, db)
    codes = [c.strip() for c in barcodes.split(",") if c.strip()]
    return {"candidates": await edge_nsi.draft_candidates(db, cid, codes)}


@router.get("/barcode-collisions")
async def store_barcode_collisions(
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Штрихкоды, на которые претендуют две карточки.

    Один код не может быть активен у двух позиций: касса ищет товар по нему, и
    при двойной привязке продаётся та карточка, что выгрузилась последней, —
    вторая «исчезает с полки», хотя товар лежит. Претензии копятся из снимков
    станций и из признания черновиков; решает человек.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    return {"collisions": await edge_nsi.barcode_collisions(db, cid, limit)}


class EdgeItemMergeIn(BaseModel):
    alias_id: int
    canonical_id: int
    reason: str | None = None


@router.post("/nsi/merge-items")
async def edge_merge_items(
    body: EdgeItemMergeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Слить дубль в канон внутри Ledger и отправить результат агентам.

    Операция не вызывает 1С и не строит карту для обработки ссылок БП.
    """
    if body.alias_id == body.canonical_id:
        raise HTTPException(400, "Дубль и канон совпадают")
    cid = await scope_company_id(user, db)
    cards = (await db.execute(text("""
        SELECT id, external_uuid::text AS uuid, name, deleted
        FROM edge.item WHERE id = ANY(:ids)
    """), {"ids": [body.alias_id, body.canonical_id]})).mappings().all()
    by_id = {row["id"]: row for row in cards}
    alias = by_id.get(body.alias_id)
    canonical = by_id.get(body.canonical_id)
    if alias is None or canonical is None:
        raise HTTPException(404, "Карточка дубля или канона не найдена")
    linked = (await db.execute(select(StoreStockBalance.id).where(
        StoreStockBalance.company_id == cid,
        StoreStockBalance.item_uuid == alias["uuid"],
    ).limit(1))).scalar_one_or_none()
    if linked is None:
        raise HTTPException(409, "Дубль не связан с остатком выбранной компании")
    exists = (await db.execute(select(StoreItemAlias.id).where(
        StoreItemAlias.company_id == cid,
        StoreItemAlias.alias_uuid == alias["uuid"],
    ))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "Карточка уже была слита")

    stats = {"barcodes": 0, "prices": 0, "stock_rows": 0, "recipes": 0,
             "assortment": 0}
    canonical_codes = set((await db.execute(text("""
        SELECT code FROM edge.barcode WHERE item_id = :id AND status = 'active'
    """), {"id": body.canonical_id})).scalars().all())
    alias_barcodes = (await db.execute(text("""
        SELECT id, code, status::text AS status FROM edge.barcode WHERE item_id = :id
    """), {"id": body.alias_id})).mappings().all()
    for barcode in alias_barcodes:
        if barcode["code"] in canonical_codes:
            await db.execute(text("""
                UPDATE edge.barcode SET status = 'historical',
                    note = coalesce(note || ' · ', '') || :note WHERE id = :id
            """), {"id": barcode["id"], "note": "карточка слита в канон"})
        else:
            await db.execute(text(
                "UPDATE edge.barcode SET item_id = :canon WHERE id = :id"),
                {"canon": body.canonical_id, "id": barcode["id"]})
            if barcode["status"] == "active":
                canonical_codes.add(barcode["code"])
        stats["barcodes"] += 1

    stations = (await db.execute(select(EdgeAgent.station_id).where(
        EdgeAgent.company_id == cid))).scalars().all()
    for station_id in stations:
        canonical_price = (await db.execute(text("""
            SELECT id FROM edge.price WHERE item_id = :id AND station_id = :st
              AND valid_to IS NULL
        """), {"id": body.canonical_id, "st": station_id})).scalar_one_or_none()
        if canonical_price is not None:
            result = await db.execute(text("""
                UPDATE edge.price SET valid_to = now()
                WHERE item_id = :alias AND station_id = :st AND valid_to IS NULL
            """), {"alias": body.alias_id, "st": station_id})
        else:
            result = await db.execute(text("""
                UPDATE edge.price SET item_id = :canon
                WHERE item_id = :alias AND station_id = :st AND valid_to IS NULL
            """), {"alias": body.alias_id, "canon": body.canonical_id,
                     "st": station_id})
        stats["prices"] += result.rowcount or 0

    balances = (await db.execute(select(StoreStockBalance).where(
        StoreStockBalance.company_id == cid,
        StoreStockBalance.item_uuid == alias["uuid"],
    ))).scalars().all()
    for balance in balances:
        target = (await db.execute(select(StoreStockBalance).where(
            StoreStockBalance.company_id == cid,
            StoreStockBalance.station_id == balance.station_id,
            StoreStockBalance.place == balance.place,
            StoreStockBalance.item_uuid == canonical["uuid"],
            StoreStockBalance.barcode == balance.barcode,
        ))).scalar_one_or_none()
        if target is not None:
            target.quantity = float(target.quantity or 0) + float(balance.quantity or 0)
            await db.delete(balance)
        else:
            balance.item_uuid = canonical["uuid"]
            balance.name = canonical["name"]
            balance.balance_key = hashlib.sha256(
                f"{canonical['uuid']}|{balance.barcode}".encode("utf-8")).hexdigest()
        stats["stock_rows"] += 1

    alias_rules = (await db.execute(select(StoreAssortmentRule).where(
        StoreAssortmentRule.company_id == cid,
        StoreAssortmentRule.item_uuid == alias["uuid"],
    ))).scalars().all()
    for rule in alias_rules:
        target_rule = (await db.execute(select(StoreAssortmentRule).where(
            StoreAssortmentRule.company_id == cid,
            StoreAssortmentRule.station_id == rule.station_id,
            StoreAssortmentRule.item_uuid == canonical["uuid"],
        ))).scalar_one_or_none()
        if target_rule is None:
            rule.item_uuid = canonical["uuid"]
        else:
            await db.delete(rule)
        stats["assortment"] += 1

    recipes = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == cid))).scalars().all()
    recipe_keys = {(recipe.dish_uuid, recipe.version) for recipe in recipes}
    for recipe in recipes:
        changed = False
        if (recipe.dish_uuid == alias["uuid"] and
                (canonical["uuid"], recipe.version) not in recipe_keys):
            recipe.dish_uuid = canonical["uuid"]
            recipe.dish_name = canonical["name"]
            changed = True
        lines = []
        for line in recipe.lines or []:
            line = dict(line)
            for key in ("item_uuid", "ingredient_uuid", "Номенклатура"):
                if str(line.get(key) or "") == alias["uuid"]:
                    line[key] = canonical["uuid"]
                    changed = True
            lines.append(line)
        if changed:
            recipe.lines = lines
            stats["recipes"] += 1

    await db.execute(text("""
        UPDATE edge.item SET deleted = true, updated_at = now() WHERE id = :id
    """), {"id": body.alias_id})
    db.add(StoreItemAlias(
        company_id=cid, alias_uuid=alias["uuid"], canonical_uuid=canonical["uuid"],
        reason=body.reason, created_by=user.id,
    ))
    for station_id in stations:
        card = (await db.execute(text("""
            SELECT i.external_uuid, i.name, i.unit, i.vat_rate, i.deleted,
                   coalesce(i.price_owner, 'master') AS price_owner,
                   coalesce((SELECT array_agg(b.code ORDER BY b.code)
                             FROM edge.barcode b WHERE b.item_id = i.id
                               AND b.status = 'active'), '{}') AS codes,
                   (SELECT p.price FROM edge.price p
                     WHERE p.item_id = i.id AND p.station_id = :st
                       AND p.valid_to IS NULL) AS price
            FROM edge.item i WHERE i.id = :id
        """), {"id": body.canonical_id, "st": station_id})).mappings().first()
        db.add(EdgeDownlink(
            company_id=cid, station_id=station_id, kind="item_alias",
            payload={
                "alias_uuid": alias["uuid"],
                "canonical": {
                    "uuid": str(card["external_uuid"]), "name": card["name"],
                    "unit": card["unit"], "vat_rate": card["vat_rate"],
                    "deleted": bool(card["deleted"]),
                    "price_owner": card["price_owner"],
                    "price": float(card["price"]) if card["price"] is not None else None,
                    "barcodes": list(card["codes"] or []),
                },
            },
            note=f"Слияние {alias['name']} → {canonical['name']}",
        ))
    await db.commit()
    return {"ok": True, "alias_uuid": alias["uuid"],
            "canonical_uuid": canonical["uuid"], "stats": stats,
            "stations_queued": len(stations)}


@router.post("/barcode-collisions/{claim_id}")
async def store_resolve_collision(
    claim_id: int,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по коллизии: передать код претенденту либо снять претензию.

    После передачи обе карточки уезжают на станции заданием НСИ: то, чем товар
    пробивается в кассе, изменилось, и станция обязана об этом узнать — иначе
    на полке останется старая привязка до ближайшей полной выгрузки.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    try:
        res = await edge_nsi.resolve_collision(
            db, cid, claim_id, str(body.get("action") or ""), body.get("note"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if res["action"] == "move":
        stations = (await db.execute(text(
            "SELECT id FROM edge.station"))).scalars().all()
        for item_id in (res["claimant_id"], res["holder_id"]):
            for st in stations:
                # Цена берётся ПО СТАНЦИИ, а не общая: они разные, и задание с
                # пустой ценой стёрло бы её в реплике станции — товар остался бы
                # на полке без цены. Право на цену едет вместе с карточкой.
                row = (await db.execute(text("""
                    SELECT i.external_uuid, i.name, i.unit, i.vat_rate, i.price_owner,
                           coalesce((SELECT array_agg(b.code ORDER BY b.code) FROM edge.barcode b
                                      WHERE b.item_id = i.id AND b.status = 'active'), '{}') AS codes,
                           (SELECT p.price FROM edge.price p
                             WHERE p.item_id = i.id AND p.station_id = :s
                               AND p.valid_to IS NULL) AS price
                    FROM edge.item i WHERE i.id = :id
                """), {"id": item_id, "s": st})).mappings().first()
                if row is None:
                    continue
                db.add(EdgeDownlink(
                    company_id=cid, station_id=st, kind="nsi_delta",
                    payload={"uuid": str(row["external_uuid"]), "name": row["name"],
                             "unit": row["unit"], "vat_rate": row["vat_rate"],
                             "barcodes": list(row["codes"] or []),
                             "price": float(row["price"]) if row["price"] is not None else None,
                             "price_owner": row["price_owner"], "deleted": False},
                ))
        await db.commit()
        res["pushed_to_stations"] = len(stations)
    return res


@router.post("/partners/push/{station_id}")
async def store_push_partners(
    station_id: int,
    all_network: bool = Query(False, description="слать весь справочник сети, а не только своих"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить станции её справочник поставщиков.

    По умолчанию — только тех, кто с этой станцией работал: товароведу 208-й
    незачем сотня юрлиц с других АЗС, он будет искать своего среди чужих.
    Флагом можно отдать весь справочник сети — например, когда станция новая и
    истории поставок у неё ещё нет.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    фильтр = "" if all_network else """
        AND EXISTS (SELECT 1 FROM edge.partner_station ps
                     WHERE ps.partner_id = p.id AND ps.station_id = :s)
    """
    rows = (await db.execute(text(f"""
        SELECT p.id, p.name, p.inn, p.kpp, p.role, p.comment, p.archived
        FROM edge.partner p
        WHERE p.company_id = :cid AND NOT p.archived {фильтр}
        ORDER BY p.name
    """), {"cid": cid, "s": station_id})).mappings().all()
    if not rows:
        raise HTTPException(404, "Для станции нет ни одного контрагента")

    db.add(EdgeDownlink(
        company_id=cid, station_id=station_id, kind="partners",
        payload={"partners": [
            {"id": f"m{r['id']}", "name": r["name"], "inn": r["inn"] or "",
             "kpp": r["kpp"] or "", "role": r["role"], "comment": r["comment"] or "",
             "archived": r["archived"]} for r in rows]},
    ))
    await db.commit()
    return {"station_id": station_id, "partners": len(rows)}
