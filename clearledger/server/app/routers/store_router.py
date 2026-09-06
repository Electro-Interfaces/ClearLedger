"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
import hashlib
import httpx
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, case, cast, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_module_access, get_company_by_api_key, get_current_user
from app.business_access import (
    OWNER_SHARED,
    OWNER_STATION,
    ROLE_STATION_ADMINISTRATOR,
    SCOPE_STATION,
    STORE_POLICY_KEY,
    has_network_merchandiser,
    store_policy as resolve_store_policy,
)
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    Company, Contract, Counterparty, EdgeAgent, EdgeDownlink, EdgePacket, MarkingIntegration,
    Organization, StoreCheque, StoreDocFile, StoreDocMeta, StoreAssortmentRule, StoreItemAlias, StoreReceipt,
    StoreReceiptStockMovement, StoreRecipeVersion, StoreStockBalance,
    User, UserCompany, Warehouse,
)
from app.routers import edge_router
from app.routers.store_documents_router import (
    DocumentAccess,
    _station_allowed,
    resolve_document_access,
)
from app.services import (edge_nsi, edge_projection, edge_service, store_baskets,
                          store_costs, store_cure, store_dynamics,
                          store_mrc_prices, store_price_plans, store_repricing,
                          store_reports)
from app.services.store_goods_report_print import лист_товарного_отчёта
from app.services import recipe_versions, store_receipts as receipt_rules
from app.services import store_receipt_accounting
from app.services import matrix
from app.services import item_group_guess
from app.services import partner_sync
from app.services.export_audit import log_export
from app.services.edo_upd import parse_upd
from app.services.goods_dashboard import GoodsDashboardService
from app.services.onec.crypto import encrypt_password
from app.services.closing_date import get_closing_date, set_closing_date
from app.services.store_document_contract import PROJECTION_DOCUMENT_KINDS
from app.services.store_documents import (
    cheque_lines_from_catalog,
    cheque_lines_with_legacy_provenance,
    goods_only_cheque_totals,
    load_item_catalog,
    sanitize_edge_document,
)

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


async def _require_central_commercial_control(user: User, db: AsyncSession) -> uuid.UUID:
    """Запись коммерческих решений из центра.

    Открыта в режиме «shared»: правят обе стороны — товаровед сети из центра и
    администратор АЗС на месте. Спор разрешается временем: чья версия пришла
    последней, та и действует.

    В режиме «station» центр остаётся витриной, и это умолчание — станция ближе
    к товару, молча включать запись центра нельзя.

    Роль «Товаровед сети» проверяется в обоих режимах. Раньше до неё просто не
    доходило: режим был жёстко «station», и отказ случался строкой выше.
    """
    cid = await scope_company_id(user, db)
    company = await db.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    policy = resolve_store_policy(company.customization)
    if policy["commercial_owner"] == OWNER_STATION:
        raise HTTPException(
            409,
            "Коммерческие решения принадлежат администратору АЗС: центр "
            "показывает аналитику и предложения, но не перезаписывает станцию. "
            "Чтобы править и из центра, включите совместный режим политики "
            "«Магазина».",
        )
    membership = await db.get(UserCompany, (user.id, cid))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    if not has_network_merchandiser(grants, company.slug):
        raise HTTPException(403, "Требуется роль «Товаровед сети»")
    return cid


async def _require_network_merchandiser(user: User, db: AsyncSession) -> uuid.UUID:
    """Изменение канона сети: карточки, штрихкоды и разрешение дублей."""
    cid = await scope_company_id(user, db)
    company = await db.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    membership = await db.get(UserCompany, (user.id, cid))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    if not has_network_merchandiser(grants, company.slug):
        raise HTTPException(403, "Требуется роль «Товаровед сети»")
    return cid


@dataclass(frozen=True)
class ReceiptAccess:
    company_id: uuid.UUID
    network: bool
    station_ids: frozenset[int]


def _receipt_grant_scope(
    *, is_superadmin: bool, grants: list[dict], network_id: str,
) -> tuple[bool, frozenset[int]]:
    station_ids: set[int] = set()
    for grant in grants:
        if (str((grant or {}).get("role") or "") != ROLE_STATION_ADMINISTRATOR
                or str((grant or {}).get("scope_type") or "") != SCOPE_STATION):
            continue
        try:
            station_ids.add(int(grant.get("scope_id")))
        except (TypeError, ValueError):
            continue
    network = is_superadmin or has_network_merchandiser(grants, network_id)
    return network, frozenset(station_ids)


async def _receipt_access(user: User, db: AsyncSession) -> ReceiptAccess:
    cid = await scope_company_id(user, db)
    company = await db.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    membership = await db.get(UserCompany, (user.id, cid))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    network, station_ids = _receipt_grant_scope(
        is_superadmin=bool(user.is_superadmin), grants=grants, network_id=company.slug)
    if not network and not station_ids:
        raise HTTPException(403, "Требуется роль товароведа сети или администратора АЗС")
    return ReceiptAccess(cid, network, station_ids)


def _require_receipt_station(access: ReceiptAccess, station_id: int | None) -> None:
    if station_id is None:
        if not access.network:
            raise HTTPException(403, "Центральный склад доступен только товароведу сети")
        return
    if not access.network and station_id not in access.station_ids:
        raise HTTPException(403, "Нет полномочий на эту АЗС")


def _require_receipt_row(access: ReceiptAccess, row: StoreReceipt) -> None:
    _require_receipt_station(access, row.station_id)


def _receipt_list_scope(
    access: ReceiptAccess, requested: set[int],
) -> tuple[set[int], bool]:
    if access.network:
        return requested, True
    if requested and not requested.issubset(access.station_ids):
        raise HTTPException(403, "Нет полномочий на одну из запрошенных АЗС")
    return requested or set(access.station_ids), False


# Молчание свыше трёх минут при телеметрии раз в минуту — это уже не «сеть
# моргнула», а обрыв. Час — станция требует внимания человека.
STATION_OFFLINE_AFTER = 180
STATION_STALE_AFTER = 3600


def _station_state(silence: int | None) -> str:
    """Единая шкала свежести телеметрии для всех экранов станции."""
    if silence is None or silence > STATION_STALE_AFTER:
        return "молчит"
    if silence > STATION_OFFLINE_AFTER:
        return "офлайн"
    return "онлайн"


def _int_metric(details: dict, key: str) -> int:
    try:
        return max(0, int(details.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _queue_metrics(details: dict) -> dict:
    return {
        "queue_bytes": _int_metric(details, "queue_bytes"),
        "queue_wire_bytes": _int_metric(details, "queue_wire_bytes"),
        "queue_oldest_at": details.get("queue_oldest_at"),
        "queue_failing": _int_metric(details, "queue_failing"),
        "queue_sent_24": _int_metric(details, "queue_sent_24"),
        "sent_24_bytes": _int_metric(details, "sent_24_bytes"),
        "sent_24_wire_bytes": _int_metric(details, "sent_24_wire_bytes"),
        "last_sent_at": details.get("last_sent_at"),
        "last_attempt_at": details.get("last_attempt_at"),
        "last_error": details.get("last_error"),
    }


def _clock_skew_seconds(details: dict, received_at: datetime | None) -> int | None:
    raw = details.get("client_time")
    if not raw or received_at is None:
        return None
    try:
        client_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if client_at.tzinfo is None:
        client_at = client_at.replace(tzinfo=timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    return round((client_at - received_at).total_seconds())


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

    # Целевая версия — одна на компанию и объявляется в «Версиях агента»:
    # два разных ответа на «какой код текущий» рассинхронизировали бы экраны.
    desired = await edge_router.desired_version(db, await db.get(Company, cid))
    now = datetime.now(timezone.utc)
    stations = []
    for r in rows:
        silence = int((now - r.last_seen).total_seconds()) if r.last_seen else None
        state = _station_state(silence)
        details = r.payload or {}
        stations.append({
            "station_id": r.station_id,
            "state": state,
            "silence_seconds": silence,
            "version": r.version,
            "version_ok": not r.version or (
                edge_router._номер_версии(r.version)
                >= edge_router._номер_версии(desired)),
            "queue_pending": r.queue_pending,
            "queue_sent": r.queue_sent,
            "last_shift": r.last_shift,
            "snapshot_at": details.get("snapshot_at"),
            "onec_ok": details.get("onec_ok"),
            "ledger_stock_ok": details.get("ledger_stock_ok", False),
            "stock_source": details.get("stock_source"),
            "cash_policy": details.get("cash_policy"),
            **_queue_metrics(details),
            "clock_skew_seconds": _clock_skew_seconds(details, r.last_seen),
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
# та же передача. Heartbeat показывает доступность станции, а сеанс обмена
# считаем отдельно по самим пакетам.
EXCHANGE_SESSION_GAP_MIN = 15

PACKET_KIND_LABEL = {
    "shift": "Смена",
    "stock": "Снимок остатков",
    "receipt": "Приёмка",
    "inventory": "Инвентаризация",
    "writeoff": "Списание",
    "transfer": "Перемещение",
    "production": "Производство",
    "cheques": "Чеки",
    "return_sale": "Возврат покупателя",
    "return_purchase": "Возврат поставщику",
    "gain": "Оприходование",
    "chain": "Снимок цепочки учёта",
    "station-nsi": "Черновики НСИ",
    "station-recipes": "Рецептуры станции",
    "station-mrc": "МРЦ станции",
    "station-catalog": "Сводка каталога станции",
    "nsi_delta": "Карточка НСИ",
    "nsi_bulk": "Пакет НСИ",
    "user_roster": "Пользователи станции",
    "partners": "Поставщики",
    "price_update": "Цена",
    "goods_receipt_expected": "Заготовка приёмки",
    "inventory_expected": "Пересчёт из центра",
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
               coalesce(sum(wire_size_bytes), 0) AS wire_bytes,
               count(wire_size_bytes) AS wire_packets,
               max(received_at) AS last_at
        FROM edge_packets WHERE company_id = :cid AND {period}
        GROUP BY kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for k in by_kind:
        k["label"] = PACKET_KIND_LABEL.get(k["kind"], k["kind"])

    by_day = [dict(r) for r in (await db.execute(text(f"""
        SELECT received_at::date AS day, count(*) AS packets,
               coalesce(sum(size_bytes), 0) AS bytes,
               coalesce(sum(wire_size_bytes), 0) AS wire_bytes,
               count(wire_size_bytes) AS wire_packets
        FROM edge_packets WHERE company_id = :cid AND {period}
        GROUP BY 1 ORDER BY 1
    """), p)).mappings().all()]

    # Сеанс = серия пакетов без паузы больше EXCHANGE_SESSION_GAP_MIN. Разрыв
    # ищется оконной функцией по станции: считать это в Python значило бы
    # тащить сюда все пакеты периода ради одного числа.
    by_station = {r["station_id"]: dict(r) for r in (await db.execute(text(f"""
        SELECT station_id, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               coalesce(sum(wire_size_bytes), 0) AS wire_bytes,
               count(wire_size_bytes) AS wire_packets,
               max(received_at) AS last_at,
               count(*) FILTER (
                   WHERE prev IS NULL
                      OR received_at - prev > make_interval(mins => :gap)) AS sessions
        FROM (
            SELECT station_id, received_at, size_bytes, wire_size_bytes,
                   lag(received_at) OVER (
                       PARTITION BY station_id ORDER BY received_at) AS prev
            FROM edge_packets WHERE company_id = :cid AND {period}
        ) t GROUP BY station_id
    """), p)).mappings().all()}

    # Отменённые задания не ждут станцию и не считаются недоставленными: их
    # сняли осознанно, и в счётчике тревоги им не место.
    down = {r["station_id"]: dict(r) for r in (await db.execute(text("""
        SELECT station_id,
               count(*) FILTER (WHERE delivered_at IS NULL AND cancelled_at IS NULL) AS waiting,
               count(*) FILTER (WHERE delivered_at IS NOT NULL AND acked_at IS NULL
                                  AND cancelled_at IS NULL) AS unacked,
               count(*) FILTER (WHERE acked_at IS NOT NULL) AS acked,
               coalesce(sum(octet_length(payload::text)) FILTER (
                   WHERE acked_at IS NULL AND cancelled_at IS NULL), 0) AS pending_bytes,
               min(created_at) FILTER (
                   WHERE acked_at IS NULL AND cancelled_at IS NULL) AS oldest_pending_at,
               round(avg(EXTRACT(epoch FROM acked_at - created_at)) FILTER (
                   WHERE acked_at IS NOT NULL)) AS avg_ack_seconds,
               round(max(EXTRACT(epoch FROM acked_at - created_at)) FILTER (
                   WHERE acked_at IS NOT NULL)) AS max_ack_seconds
        FROM edge_downlink WHERE company_id = :cid GROUP BY station_id
    """), {"cid": cid})).mappings().all()}

    # Лента последних обменов в обе стороны: она объясняет цифры выше — видно,
    # чем именно занят канал и когда станция выходила на связь последний раз.
    recent = [dict(r) for r in (await db.execute(text("""
        SELECT received_at AS at, station_id, kind, size_bytes, wire_size_bytes,
               'вверх' AS direction,
               shift_number AS note
        FROM edge_packets WHERE company_id = :cid
        UNION ALL
        SELECT coalesce(acked_at, delivered_at, created_at) AS at, station_id, kind,
               octet_length(payload::text) AS size_bytes,
               octet_length(payload::text) AS wire_size_bytes, 'вниз' AS direction,
               CASE WHEN cancelled_at IS NOT NULL THEN 'отменено'
                    WHEN acked_at IS NOT NULL THEN 'применено'
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
        -- Разбор пакетов: сколько пришло и сколько из них стало учётом.
        --
        -- Две свёртки вместо перебора. Раньше на каждый пакет выполнялся
        -- подзапрос по всем записям учёта, а условие «по пакету ИЛИ по смене»
        -- не давало планировщику соединить таблицы хешем: полторы тысячи
        -- пакетов против восьми тысяч записей, с разбором JSON на каждой паре.
        -- Экран «Парк станций» открывался 65 секунд — человек успевал решить,
        -- что он сломан, и уйти. Те же цифры теперь считаются за 0,12 секунды.
        WITH по_пакету AS (
            SELECT d.metadata->'Edge'->>'packet_uuid' AS packet_uuid, count(*) AS n
              FROM data_entries d
             WHERE d.company_id = :cid AND d.source = 'edge'
               AND d.metadata->'Edge'->>'packet_uuid' IS NOT NULL
             GROUP BY 1
        ),
        по_смене AS (
            -- Запасная привязка: перевыгрузка даёт второй пакет с теми же
            -- документами, и по packet_uuid он выглядел бы неразобранным.
            SELECT d.metadata->'Смена'->>'НомерСменыВнутр' AS внутр,
                   d.metadata->'Смена'->>'КодАЗС' AS азс, count(*) AS n
              FROM data_entries d
             WHERE d.company_id = :cid AND d.source = 'edge'
               AND d.metadata->'Смена'->>'НомерСменыВнутр' IS NOT NULL
             GROUP BY 1, 2
        )
        SELECT p.kind, count(*) AS packets,
               count(*) FILTER (WHERE coalesce(пп.n, пс.n, 0) > 0) AS projected,
               -- Пакет без документов породить их не может: пустую смену ЦБ
               -- нельзя записывать в «не разобрано», это не дефект разбора.
               count(*) FILTER (
                   WHERE coalesce(jsonb_array_length(p.payload->'Документы'), 0) = 0) AS empty,
               coalesce(sum(coalesce(пп.n, пс.n, 0)), 0) AS entries
        FROM edge_packets p
        LEFT JOIN по_пакету пп ON пп.packet_uuid = p.packet_uuid
        LEFT JOIN по_смене пс ON p.shift_internal_no IS NOT NULL
             AND пс.внутр = p.shift_internal_no::text
             AND пс.азс = p.station_id::text
        WHERE p.company_id = :cid AND {period}
        GROUP BY p.kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for i in ingest:
        i["label"] = PACKET_KIND_LABEL.get(i["kind"], i["kind"])
        # Снимки, черновики НСИ и рецептуры документов учёта не порождают —
        # у них своя дорога, и «не разобрано» для них не дефект.
        # Служебные виды документов учёта не порождают: снимок остатков,
        # черновики НСИ, рецептуры и чеки живут своими таблицами.
        i["projects_docs"] = i["kind"] not in (
            "stock", "station-nsi", "station-recipes", "cheques")
        i["unprojected"] = max(0, int(i["packets"]) - int(i["projected"])
                               - int(i["empty"] or 0))

    # Доступность = время наблюдения минус обрывы длиннее трёх минут. Последний
    # heartbeat до периода нужен, чтобы не терять обрыв на его левой границе.
    uptime = {r["station_id"]: dict(r) for r in (await db.execute(text("""
        WITH bounds AS (
            SELECT station_id,
                   greatest(first_seen, CAST(:d1 AS date)::timestamptz) AS start_at,
                   least(:now, (CAST(:d2 AS date) + 1)::timestamptz) AS end_at
            FROM edge_agents WHERE company_id = :cid
        ), points AS (
            SELECT b.station_id, b.start_at, b.end_at, h.at
            FROM bounds b
            JOIN LATERAL (
                SELECT at FROM edge_heartbeats
                WHERE company_id = :cid AND station_id = b.station_id
                  AND at >= b.start_at AND at <= b.end_at
                UNION ALL
                SELECT max(at) FROM edge_heartbeats
                WHERE company_id = :cid AND station_id = b.station_id
                  AND at < b.start_at
            ) h ON h.at IS NOT NULL
        ), seq AS (
            SELECT *, lag(at) OVER (PARTITION BY station_id ORDER BY at) AS prev
            FROM points
        ), gaps AS (
            SELECT station_id,
                   coalesce(sum(EXTRACT(epoch FROM least(at, end_at) -
                       greatest(prev, start_at))) FILTER (
                       WHERE prev IS NOT NULL
                         AND at - prev > make_interval(secs => 180)
                         AND at > start_at AND prev < end_at), 0) AS seconds
            FROM seq GROUP BY station_id
        ), last_points AS (
            SELECT station_id, max(at) AS last_at FROM points GROUP BY station_id
        )
        SELECT b.station_id,
               (lp.last_at IS NOT NULL) AS has_heartbeat,
               greatest(0, EXTRACT(epoch FROM b.end_at - b.start_at)) AS window_seconds,
               coalesce(g.seconds, 0) + CASE
                   WHEN lp.last_at IS NOT NULL
                    AND b.end_at - lp.last_at > make_interval(secs => 180)
                   THEN EXTRACT(epoch FROM b.end_at - greatest(lp.last_at, b.start_at))
                   ELSE 0 END AS outage_seconds
        FROM bounds b
        LEFT JOIN gaps g USING (station_id)
        LEFT JOIN last_points lp USING (station_id)
    """), {**p, "now": datetime.now(timezone.utc)})).mappings().all()}

    # Что станции прислали на решение центра: карточки и поставщики, заведённые
    # при мёртвой связи, заявки об ошибке в сетевой карточке, цены, назначенные
    # на месте. Сами экраны живут в «Каталоге» — здесь сигнал, что там ждут.
    нси = {r["вид"]: int(r["n"]) for r in (await db.execute(text("""
        SELECT 'карточки' AS вид, count(*) AS n FROM edge.item_draft
          WHERE company_id = :cid AND resolved_at IS NULL
        UNION ALL
        SELECT 'поставщики', count(*) FROM edge.partner_draft
          WHERE company_id = :cid AND resolved_at IS NULL
        UNION ALL
        SELECT 'заявки', count(*) FROM edge.nsi_proposal
          WHERE company_id = :cid AND resolved_at IS NULL
        UNION ALL
        SELECT 'цены станций', count(*) FROM edge.station_price_change
          WHERE company_id = :cid
            AND changed_at >= :d1 AND changed_at < (CAST(:d2 AS date) + 1)
    """), {"cid": cid, "d1": d1, "d2": d2})).mappings().all()}

    agents = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == cid).order_by(EdgeAgent.station_id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    stations = []
    for a in agents:
        silence = int((now - a.last_seen).total_seconds()) if a.last_seen else None
        ex = by_station.get(a.station_id, {})
        d = down.get(a.station_id, {})
        details = a.payload or {}
        stations.append({
            "station_id": a.station_id,
            "state": _station_state(silence),
            "silence_seconds": silence,
            "last_seen": a.last_seen,
            "version": a.version,
            "queue_pending": a.queue_pending,
            "queue_sent": a.queue_sent,
            **_queue_metrics(details),
            "clock_skew_seconds": _clock_skew_seconds(details, a.last_seen),
            "last_shift": a.last_shift,
            "snapshot_at": details.get("snapshot_at"),
            # Кто работает на станции прямо сейчас — по её же телеметрии.
            # Открывать рабочее место вслепую, когда там считают склад, значит
            # столкнуться на одном документе и потерять чью-то работу.
            "active_users": details.get("active_users") or [],
            "packets": int(ex.get("packets") or 0),
            "bytes": int(ex.get("bytes") or 0),
            "wire_bytes": int(ex.get("wire_bytes") or 0),
            "wire_packets": int(ex.get("wire_packets") or 0),
            "sessions": int(ex.get("sessions") or 0),
            "last_packet_at": ex.get("last_at"),
            "down_waiting": int(d.get("waiting") or 0),
            "down_unacked": int(d.get("unacked") or 0),
            "down_acked": int(d.get("acked") or 0),
            "down_pending_bytes": int(d.get("pending_bytes") or 0),
            "down_oldest_pending_at": d.get("oldest_pending_at"),
            "down_avg_ack_seconds": (int(d["avg_ack_seconds"])
                                     if d.get("avg_ack_seconds") is not None else None),
            "down_max_ack_seconds": (int(d["max_ack_seconds"])
                                     if d.get("max_ack_seconds") is not None else None),
            "uptime_pct": _uptime_pct(uptime.get(a.station_id), d1, d2, now),
        })

    # Станции, чьи пакеты в базе есть, а телеметрии нет: так выглядит АЗС, с
    # которой обмен шёл до появления таблицы агентов, или разовая заливка. Без
    # этих строк сумма по таблице не сходилась бы с итогом сверху.
    #
    # Но только для станций, которые в сети ЕСТЬ. Пакет с кодом, которого нет
    # ни среди агентов, ни в справочнике станций, — мусор канала: на 210 так
    # появилась строка «агент не зарегистрирован, никогда не выходила на связь»
    # из двух проб 01.08, и в парке она выглядела забытой АЗС.
    известные = {r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL"
    ), {"c": cid})).all()}
    for sid in sorted((set(by_station) & известные)
                      - {s["station_id"] for s in stations}):
        ex, d = by_station[sid], down.get(sid, {})
        stations.append({
            "station_id": sid, "state": "нет агента", "silence_seconds": None,
            "last_seen": None,
            "version": None, "queue_pending": 0, "queue_sent": 0, "last_shift": None,
            "snapshot_at": None,
            "queue_bytes": 0, "queue_wire_bytes": 0, "queue_oldest_at": None,
            "queue_failing": 0, "queue_sent_24": 0,
            "sent_24_bytes": 0, "sent_24_wire_bytes": 0,
            "last_sent_at": None, "last_attempt_at": None, "last_error": None,
            "clock_skew_seconds": None,
            "packets": int(ex.get("packets") or 0), "bytes": int(ex.get("bytes") or 0),
            "wire_bytes": int(ex.get("wire_bytes") or 0),
            "wire_packets": int(ex.get("wire_packets") or 0),
            "sessions": int(ex.get("sessions") or 0), "last_packet_at": ex.get("last_at"),
            "down_waiting": int(d.get("waiting") or 0),
            "down_unacked": int(d.get("unacked") or 0),
            "down_acked": int(d.get("acked") or 0),
            "down_pending_bytes": int(d.get("pending_bytes") or 0),
            "down_oldest_pending_at": d.get("oldest_pending_at"),
            "down_avg_ack_seconds": (int(d["avg_ack_seconds"])
                                     if d.get("avg_ack_seconds") is not None else None),
            "down_max_ack_seconds": (int(d["max_ack_seconds"])
                                     if d.get("max_ack_seconds") is not None else None),
            "uptime_pct": None,
        })

    return {
        "from": d1, "to": d2,
        "session_gap_minutes": EXCHANGE_SESSION_GAP_MIN,
        "totals": {
            "packets": sum(k["packets"] for k in by_kind),
            "bytes": sum(int(k["bytes"]) for k in by_kind),
            "wire_bytes": sum(int(k["wire_bytes"]) for k in by_kind),
            "wire_packets": sum(int(k["wire_packets"]) for k in by_kind),
            "sessions": sum(s["sessions"] for s in stations),
            "online": sum(1 for s in stations if s["state"] == "онлайн"),
            # Знаменатель «на связи X из Y» — только станции с агентом: строки
            # без телеметрии не станции парка, а следы старого обмена.
            "stations": len(agents),
            "queue_pending": sum(s["queue_pending"] for s in stations),
            "queue_bytes": sum(s["queue_bytes"] for s in stations),
            "queue_wire_bytes": sum(s["queue_wire_bytes"] for s in stations),
            "queue_failing": sum(s["queue_failing"] for s in stations),
            "down_waiting": sum(s["down_waiting"] for s in stations),
            "down_unacked": sum(s["down_unacked"] for s in stations),
            "down_pending_bytes": sum(s["down_pending_bytes"] for s in stations),
            "last_packet_at": max((s["last_packet_at"] for s in stations
                                   if s["last_packet_at"]), default=None),
        },
        "by_kind": by_kind,
        "by_day": by_day,
        "stations": stations,
        "recent": recent,
        "ingest": ingest,
        "nsi": нси,
    }


def _uptime_pct(строка, _d1: date, _d2: date, _now: datetime) -> float | None:
    """Доступность станции за период по длительности обрывов, %."""
    if not строка or not строка.get("has_heartbeat"):
        return None
    всего = float(строка.get("window_seconds") or 0)
    if всего <= 0:
        return None
    простой = min(всего, float(строка.get("outage_seconds") or 0))
    return round((всего - простой) / всего * 100, 1)


def _tail_outage(last_at: datetime | None, d2: date,
                 now: datetime) -> dict | None:
    """Незакрытый хвост после последнего heartbeat в выбранном периоде."""
    if last_at is None:
        return None
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    конец_периода = min(now, datetime.combine(d2, time.max, tzinfo=timezone.utc))
    seconds = (конец_периода - last_at).total_seconds()
    if seconds <= STATION_OFFLINE_AFTER:
        return None
    ongoing = конец_периода == now
    return {
        "started": last_at,
        "ended": None if ongoing else конец_периода,
        "minutes": round(seconds / 60),
        "ongoing": ongoing,
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
            SELECT received_at, size_bytes, wire_size_bytes, kind,
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
               coalesce(sum(wire_size_bytes), 0) AS wire_bytes,
               count(wire_size_bytes) AS wire_packets,
               string_agg(DISTINCT kind, ', ') AS kinds,
               max(пауза) FILTER (WHERE новый) AS silence_before_min
        FROM пронумерованные GROUP BY session_no ORDER BY started DESC
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
               coalesce(sum(wire_size_bytes), 0) AS wire_bytes,
               count(wire_size_bytes) AS wire_packets,
               max(received_at) AS last_at
        FROM edge_packets
        WHERE company_id = :cid AND station_id = :st AND {period}
        GROUP BY kind ORDER BY count(*) DESC
    """), p)).mappings().all()]
    for k in by_kind:
        k["label"] = PACKET_KIND_LABEL.get(k["kind"], k["kind"])

    downlink = [dict(r) for r in (await db.execute(text("""
        SELECT id, kind, note, created_at, delivered_at, acked_at, cancelled_at,
               octet_length(payload::text) AS size_bytes
        FROM edge_downlink WHERE company_id = :cid AND station_id = :st
        ORDER BY created_at DESC
    """), {"cid": cid, "st": station_id})).mappings().all()]
    for d in downlink:
        d["id"] = str(d["id"])
        d["label"] = PACKET_KIND_LABEL.get(d["kind"], d["kind"])
        d["state"] = ("отменено" if d["cancelled_at"] else
                      "применено" if d["acked_at"] else
                      "доставлено" if d["delivered_at"] else "ждёт станции")
        d["delivery_seconds"] = (round((d["delivered_at"] - d["created_at"]).total_seconds())
                                 if d["delivered_at"] else None)
        d["ack_seconds"] = (round((d["acked_at"] - d["created_at"]).total_seconds())
                            if d["acked_at"] else None)
    down_stats = (await db.execute(text("""
        SELECT count(*) FILTER (
                   WHERE delivered_at IS NULL AND cancelled_at IS NULL) AS waiting,
               count(*) FILTER (
                   WHERE delivered_at IS NOT NULL AND acked_at IS NULL
                     AND cancelled_at IS NULL) AS unacked,
               count(*) FILTER (WHERE acked_at IS NOT NULL) AS acked,
               coalesce(sum(octet_length(payload::text)) FILTER (
                   WHERE cancelled_at IS NULL), 0) AS bytes,
               round(avg(EXTRACT(epoch FROM acked_at - created_at)) FILTER (
                   WHERE acked_at IS NOT NULL)) AS avg_ack_seconds
        FROM edge_downlink WHERE company_id = :cid AND station_id = :st
    """), {"cid": cid, "st": station_id})).mappings().first() or {}

    agent = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == station_id
    ))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    начало_периода = datetime.combine(d1, time.min, tzinfo=timezone.utc)
    конец_периода = min(now, datetime.combine(d2, time.max, tzinfo=timezone.utc))
    начало_наблюдения = начало_периода
    if agent and agent.first_seen:
        first_seen = agent.first_seen
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        начало_наблюдения = max(начало_наблюдения, first_seen)
    hp = {"cid": cid, "st": station_id,
          "start": начало_наблюдения, "end": конец_периода}

    # Пульс нужен для числа наблюдений, а доступность считаем по длительности
    # обрывов: пропущенная минута сама по себе ещё не авария.
    доступность = (await db.execute(text("""
        SELECT count(DISTINCT date_trunc('minute', at)) AS minutes,
               min(at) AS first_at, max(at) AS last_at
        FROM edge_heartbeats
        WHERE company_id = :cid AND station_id = :st
          AND at >= :start AND at <= :end
    """), hp)).mappings().first()

    # Берём последний heartbeat ДО начала окна: иначе обрыв, который начался
    # вчера и закончился сегодня, исчезает ровно на границе выбранного периода.
    обрывы = [dict(r) for r in (await db.execute(text(f"""
        WITH points AS (
            SELECT at
            FROM edge_heartbeats
            WHERE company_id = :cid AND station_id = :st
              AND at >= :start AND at <= :end
            UNION ALL
            SELECT max(at) AS at
            FROM edge_heartbeats
            WHERE company_id = :cid AND station_id = :st AND at < :start
        ), gaps AS (
            SELECT at, lag(at) OVER (ORDER BY at) AS prev
            FROM points WHERE at IS NOT NULL
        )
        SELECT greatest(prev, :start) AS started, least(at, :end) AS ended,
               round(EXTRACT(epoch FROM least(at, :end) - greatest(prev, :start)) / 60)
                   AS minutes
        FROM gaps
        WHERE prev IS NOT NULL
          AND at - prev > make_interval(secs => {STATION_OFFLINE_AFTER})
          AND at > :start AND prev < :end
        ORDER BY at - prev DESC
    """), hp)).mappings().all()]
    for о in обрывы:
        о["minutes"] = int(о["minutes"] or 0)
        о["ongoing"] = False

    последний = (await db.execute(text("""
        SELECT max(at) FROM edge_heartbeats
        WHERE company_id = :cid AND station_id = :st AND at <= :end
    """), hp)).scalar_one_or_none()
    хвост = _tail_outage(последний, d2, now)
    if хвост:
        if хвост["started"] < начало_наблюдения:
            хвост["started"] = начало_наблюдения
            граница = хвост["ended"] or now
            хвост["minutes"] = round(
                (граница - начало_наблюдения).total_seconds() / 60)
        обрывы.insert(0, хвост)

    silence = (int((now - agent.last_seen).total_seconds())
               if agent and agent.last_seen else None)
    details = (agent.payload or {}) if agent else {}
    паузы = [s["silence_before_min"] for s in sessions
             if s["silence_before_min"] is not None]
    всего_минут = max(0, round((конец_периода - начало_наблюдения).total_seconds() / 60))
    простой_минут = sum(о["minutes"] for о in обрывы)
    availability_pct = None
    if agent and последний is not None and всего_минут > 0:
        availability_pct = round(
            max(0, всего_минут - простой_минут) / всего_минут * 100, 1)

    return {
        "station_id": station_id,
        "from": d1, "to": d2,
        "session_gap_minutes": EXCHANGE_SESSION_GAP_MIN,
        "agent": None if agent is None else {
            "state": _station_state(silence),
            "silence_seconds": silence,
            "version": agent.version,
            "version_ok": not agent.version or (
                edge_router._номер_версии(agent.version)
                >= edge_router._номер_версии(desired)),
            "queue_pending": agent.queue_pending,
            "queue_sent": agent.queue_sent,
            **_queue_metrics(details),
            "clock_skew_seconds": _clock_skew_seconds(details, agent.last_seen),
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
            "wire_bytes": sum(int(s["wire_bytes"]) for s in sessions),
            "wire_packets": sum(int(s["wire_packets"]) for s in sessions),
            # Средняя и худшая пауза между выходами на связь: экран про канал, а
            # длина молчания и есть его качество.
            "avg_silence_min": round(sum(паузы) / len(паузы)) if паузы else None,
            "max_silence_min": max(паузы) if паузы else None,
            "down_waiting": int(down_stats.get("waiting") or 0),
            "down_unacked": int(down_stats.get("unacked") or 0),
            "down_acked": int(down_stats.get("acked") or 0),
            "down_bytes": int(down_stats.get("bytes") or 0),
            "down_avg_ack_seconds": (int(down_stats["avg_ack_seconds"])
                                     if down_stats.get("avg_ack_seconds") is not None else None),
        },
        # Доля минут периода, в которые агент выходил на связь. Считается от
        # первого heartbeat станции: до него канала не было не потому, что
        # связь падала, а потому, что агента ещё не поставили.
        "availability": {
            "minutes_seen": int(доступность["minutes"] or 0) if доступность else 0,
            "minutes_total": всего_минут,
            "pct": availability_pct,
            "first_at": начало_наблюдения if agent else None,
            "last_at": доступность["last_at"] if доступность else None,
            "outages": обрывы,
            "outage_minutes": простой_минут,
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
    # Классификация
    group_id: int | None = None
    purpose: str | None = None
    # Регуляторика: за это штрафуют, поэтому поля отдельные, а не в описании
    gtin: str | None = None
    marked: bool | None = None
    mark_group: str | None = None
    adult_only: bool | None = None
    mrc: float | None = None
    shelf_life_days: int | None = None
    storage_mode: str | None = None
    # Товарные свойства и обогащение
    brand: str | None = None
    manufacturer: str | None = None
    country: str | None = None
    net_qty: float | None = None
    net_unit: str | None = None
    pack_qty: float | None = None
    photo_url: str | None = None
    composition: str | None = None
    allergens: str | None = None
    kcal: float | None = None
    description: str | None = None


class ItemGroupIn(BaseModel):
    name: str
    parent_id: int | None = None
    marked_default: bool | None = None
    adult_default: bool | None = None
    price_owner_default: str | None = None
    note: str | None = None


class NsiPriceIn(BaseModel):
    station_id: int
    price: float


class NsiBarcodeIn(BaseModel):
    code: str


def _оценка_себестоимости(оценки: dict, uuid: str) -> dict:
    """Поля себестоимости для карточки, едущей вниз.

    Пусто, когда закупок по карточке не было: станция отличает «оценки нет» от
    «оценка ноль», и затирать чужую цифру пустотой нельзя.
    """
    о = оценки.get(uuid)
    if not о:
        return {}
    return {"cost_hint": float(о["cost"]),
            "cost_hint_at": о["at"].isoformat() if hasattr(о["at"], "isoformat") else str(о["at"]),
            "cost_hint_src": о["source"]}


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
               coalesce(i.price_owner, 'master') AS price_owner,
               g.path AS group_path, i.sku_class, i.marked, i.mark_group,
               i.adult_only, i.mrc, i.brand, i.photo_url, i.sku
        FROM edge.item i
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        WHERE i.id = :id
    """), {"id": item_id})).mappings().first()
    if card is None:
        return 0

    # Реестр станций — агенты, а не только строки edge.station.
    #
    # Их два, и они расходятся: станция, чей агент жив, но строки в edge.station
    # нет, не получала заданий вовсе — молча. Объединение честнее: лишнее
    # задание безвредно, пропущенное оставляет АЗС со старым справочником.
    targets = [station_id] if station_id else [
        r[0] for r in (await db.execute(text("""
            SELECT id FROM edge.station
            UNION
            SELECT station_id FROM edge_agents WHERE company_id = :c AND station_id IS NOT NULL
        """), {"c": cid})).all()]

    # Коды карточки для КАЖДОЙ станции свои: сетевые (настоящие EAN) плюс её
    # внутренние. Чужой внутренний код вниз не едет — на этой АЗС он означал
    # бы другой товар.
    коды_по_станциям: dict[int, list[str]] = {}
    for st in targets:
        коды_по_станциям[st] = [r[0] for r in (await db.execute(text("""
            SELECT code FROM edge.barcode
             WHERE item_id = :id AND status = 'active'
               AND (station_id IS NULL OR station_id = :s)
             ORDER BY code"""), {"id": item_id, "s": st})).all()]

    for st in targets:
        codes = коды_по_станциям[st]
        # Не копим версии одной карточки в очереди.
        #
        # Задание несёт снимок карточки целиком, поэтому держать в очереди две
        # её версии бессмысленно: станции нужна последняя. Раньше каждое
        # нажатие в центре клало новое задание — на семи с половиной тысячах
        # карточек это гнало по каналу LTE один и тот же справочник пачками.
        # Снимаем только НЕ выданные: доставленное станция уже применяет.
        await db.execute(text("""
            DELETE FROM edge_downlink
            WHERE company_id = :c AND station_id = :s AND kind = 'nsi_delta'
              AND delivered_at IS NULL AND acked_at IS NULL AND cancelled_at IS NULL
              AND payload->>'uuid' = :u
        """), {"c": cid, "s": st, "u": str(card["external_uuid"])})
        price = (await db.execute(text("""
            SELECT price FROM edge.price
            WHERE item_id = :id AND station_id = :s AND valid_to IS NULL
        """), {"id": item_id, "s": st})).scalar_one_or_none()
        применяется = (await matrix.разрешить(
            db, cid, matrix.ASSORTMENT, station_id=st, item_id=item_id)).allow
        db.add(EdgeDownlink(
            company_id=cid, station_id=st, kind="nsi_delta",
            payload={"uuid": str(card["external_uuid"]), "name": card["name"],
                     "unit": card["unit"], "vat_rate": card["vat_rate"],
                     "deleted": bool(card["deleted"]), "barcodes": codes,
                     # Закрытая матрицей позиция едет без цены — в кассу она не
                     # попадёт, а карточка на станции останется (история смен).
                     "price": (float(price) if price is not None
                               and применяется else None),
                     "assortment": bool(применяется),
                     # Право на цену едет из матрицы, а не из колонки карточки:
                     # правило товароведа обязано доезжать до станции тем же
                     # тактом, что и сама карточка.
                     "price_owner": "station" if await matrix.цену_ведёт_станция(
                         db, cid, st, item_id) else "master",
                     # Свойства товара едут вниз вместе с ним: приёмка обязана
                     # требовать DataMatrix у маркируемого, а касса — паспорт
                     # у 18+, и решаться это должно на станции, офлайн.
                     "group_path": card["group_path"], "sku_class": card["sku_class"],
                     "marked": bool(card["marked"]), "mark_group": card["mark_group"],
                     "adult_only": bool(card["adult_only"]),
                     "mrc": float(card["mrc"]) if card["mrc"] is not None else None,
                     "brand": card["brand"], "photo_url": card["photo_url"],
                     # Артикул сети — тем же снимком, что и остальная карточка:
                     # человеку у полки он нужен офлайн, а не в вебе центра.
                     "sku": card["sku"],
                     **_оценка_себестоимости(
                         await store_costs.ориентиры(db, cid, [st]),
                         str(card["external_uuid"]))},
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
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    # Станции уезжает ЕЁ набор: своя карта там, где она есть, сетевая норма —
    # там, где своей нет.
    bundle = recipe_versions.build_bundle(
        await recipe_versions.active_versions(db, cid, station_id=station_id))
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

    # ⚠ ВСЕ ЯРУСЫ, а не свёртка по одной станции.
    #
    # Раньше здесь звалось `active_versions(db, cid)` без station_id, и это
    # молча означало «только сетевые карты»: при station_id=None условие
    # `station_id == None` компилируется в `IS NULL`. На ГИГ сетевых карт нет ни
    # одной — все 58 действующих принадлежат станциям (33 на 208, 25 на АЗС 8),
    # поэтому список выходил пустым, у каждого блюда «действующая» становилась
    # None, и экран показывал «0 из 65» при полностью живой кухне. Набор
    # доставки по той же причине не собирался вовсе.
    #
    # Центру нужны именно все ярусы: он смотрит сеть целиком и обязан показать,
    # где норма сетевая, а где станция её переопределила.
    active = await recipe_versions.active_versions(db, cid, все_ярусы=True)
    active_ids = {row.id for row in active}
    for item in grouped.values():
        item["active"] = next(
            (version for version in item["history"]
             if uuid.UUID(version["id"]) in active_ids), None)
        # Все действующие ярусы блюда: сетевой и станционные. Товаровед сети
        # должен видеть, что латте на 208 и на 8 готовят по разным картам, —
        # одной строки «действующая» для этого мало.
        item["ярусы"] = [
            {"station_id": row.station_id, "id": str(row.id), "version": row.version}
            for row in active if row.dish_uuid == item["dish_uuid"]
        ]
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
    # Набор доставки собирается ПО СТАНЦИИ: у каждой кухни своя свёртка
    # (её карта, а где своей нет — сетевая норма). Общий набор «на сеть» смысла
    # не имеет — станция получает свой.
    наборы: dict[int, dict] = {}
    for station_id in station_ids:
        свои = await recipe_versions.active_versions(db, cid, station_id=station_id)
        if not свои:
            continue
        b = recipe_versions.build_bundle(свои)
        наборы[station_id] = {"bundle_id": b["bundle_id"], "dishes": len(свои)}
    bundle = None
    if наборы:
        первый = наборы[sorted(наборы)[0]]
        bundle = {"bundle_id": первый["bundle_id"], "dishes": первый["dishes"]}

    # ⚠ У каждой станции СВОЙ ожидаемый набор.
    #
    # Пока сравнивали с одним общим, состояние доставки для второй кухни было
    # заведомо ложным: ей приписывался набор первой, и она всегда выглядела
    # отставшей. При одной станции это не проявлялось, при двух — сразу «2 из 2
    # требуют внимания».
    deliveries = [_delivery_state(latest_by_station.get(station_id),
                                  agent_by_station.get(station_id),
                                  наборы.get(station_id, {}).get("bundle_id"))
                  for station_id in station_ids]


    legacy_available = 0
    if not rows:
        try:
            legacy_available = int((await db.execute(text(
                "SELECT count(*) FROM edge.recipe"))).scalar() or 0)
        except Exception:
            await db.rollback()
    # Сырьё в минусе — главный сигнал кухни, и его негде было увидеть.
    #
    # Списание идёт по техкарте: каждая чашка снимает зерно, молоко и сахар.
    # Если приход сырья не заводят, остаток уходит в минус и растёт молча —
    # на 208 так набралось 19 210 мл молока и 3 467 г кофе за две недели.
    # Станция это видит строкой в замечаниях, среди прочих; товаровед сети не
    # видел вовсе — в разделе «Общепит» центра сигнала не было ни одного.
    # Поэтому считаем здесь, рядом с картами: минус — прямое следствие того,
    # что карта списывает, а приход не оформлен.
    минусы = {r["station_id"]: r for r in (await db.execute(text("""
        SELECT s.station_id,
               count(*) AS позиций,
               round(sum(-s.qty * coalesce(p.price, 0))::numeric, 2) AS деньги,
               min(i.name) AS первая
          FROM edge.stock s
          JOIN edge.barcode b ON b.id = s.barcode_id
          JOIN edge.item i ON i.id = b.item_id
          JOIN edge.item_group g ON g.id = i.group_id
          LEFT JOIN edge.price p ON p.item_id = i.id AND p.station_id = s.station_id
                                AND p.valid_to IS NULL
         WHERE g.path = 'Кухня / Сырьё' AND NOT i.deleted AND s.qty < 0
           AND (i.company_id IS NULL OR i.company_id = :cid)
         GROUP BY s.station_id
    """), {"cid": cid})).mappings().all()}

    # Разрез по станциям: сколько карт действует на каждой кухне и где кухня
    # уже «съела» несуществующее сырьё.
    по_станциям = [{
        "station_id": station_id,
        "recipes": наборы.get(station_id, {}).get("dishes", 0),
        "bundle_id": наборы.get(station_id, {}).get("bundle_id"),
        "сырьё_в_минусе": int(минусы.get(station_id, {}).get("позиций", 0)),
        "минус_денег": float(минусы.get(station_id, {}).get("деньги", 0) or 0),
    } for station_id in station_ids]

    return {
        "bundle": bundle, "legacy_available": legacy_available,
        "summary": {
            "recipes": len(grouped),
            "active": sum(1 for item in grouped.values() if item["active"]),
            "drafts": sum(1 for item in grouped.values() if item["draft"]),
            # Сетевых карт на ГИГ пока нет вовсе: кухня ведёт свои на каждой
            # АЗС. Показываем это явно, иначе «действующих 58» читается как
            # 58 блюд, а их 57 на двух кухнях.
            "station_versions": sum(1 for row in active if row.station_id is not None),
            "network_versions": sum(1 for row in active if row.station_id is None),
            # Сырьё в минусе по всей сети: сколько позиций и на сколько денег
            # кухня списала того, чего в учёте нет.
            "сырьё_в_минусе": sum(int(r["позиций"]) for r in минусы.values()),
            "минус_денег": round(sum(float(r["деньги"] or 0) for r in минусы.values()), 2),
        },
        "по_станциям": по_станциям,
        "recipes": list(grouped.values()), "deliveries": deliveries,
    }


@router.post("/recipes/bootstrap")
async def recipe_versions_bootstrap(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = await _require_central_commercial_control(user, db)
    count = await recipe_versions.bootstrap_legacy(db, cid, user.id)
    return {"ok": True, "created": count}


@router.post("/recipes/draft")
async def recipe_create_draft(
    body: RecipeDraftIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await recipe_versions.create_draft(
        db, await _require_central_commercial_control(user, db), user.id,
        body.model_dump(exclude_none=True))
    return recipe_versions.row_dict(row)


@router.put("/recipes/{version_id}")
async def recipe_update_draft(
    version_id: uuid.UUID,
    body: RecipeUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await recipe_versions.update_draft(
        db, await _require_central_commercial_control(user, db), version_id,
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
        db, await _require_central_commercial_control(user, db), version_id,
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


@router.get("/chain")
async def store_chain(
    station_id: int = Query(208),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Контрольный снимок цепочки станции: касса, наш учёт, старая 1С, обмен.

    Снимок делает агент АЗС одним заходом и присылает как есть. Центр его не
    пересчитывает: касса NeftoMS и локальная 1С видны только со станции, а
    сравнение источников, снятых в разные моменты, даёт расхождение там, где
    его нет, — на этом уже обжигались.
    """
    cid = await scope_company_id(user, db)
    return await edge_service.chain_report(db, cid, station_id)


@router.get("/cure")
async def store_cure_report(
    station_id: int | None = Query(None, description="код АЗС; пусто — вся сеть"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Болезни старой 1С рядом с состоянием нашей базы.

    Отвечает на вопрос, ради которого переход и затевался: что в 1С сломано
    сегодня и что из этого у нас вылечено. Наши разобранные дубли болезнь 1С не
    гасят — она остаётся там до Дня X, и экран показывает обе величины.
    """
    cid = await scope_company_id(user, db)
    return await store_cure.compare(db, cid, station_id)


@router.get("/kkt")
async def store_kkt(
    station_id: int = Query(208),
    limit: int = Query(30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Фискальные итоги кассовых смен станции: чем подтверждена её выручка.

    Итог пишет сам аппарат при закрытии смены, и он уже за вычетом возвратов.
    Разница с лентой продаж — норма: корпоративные отпуски чеком не пробиваются
    и в фискальную память не попадают.
    """
    cid = await scope_company_id(user, db)
    return await edge_service.kkt_report(db, cid, station_id, limit)


class AgentVersionIn(BaseModel):
    version: str


class StorageCleanupIn(BaseModel):
    """Правило прореживания сырья. Значения по умолчанию — рабочие."""
    thin_after_days: int = 14
    heartbeat_days: int = 90
    dry_run: bool = True


class ReprojectIn(BaseModel):
    """Что достраивать и правда ли выполнять."""
    date_from: str | None = None
    date_to: str | None = None
    station_id: int | None = None
    limit: int = 500
    dry_run: bool = True
    # Приёмка живёт двумя жизнями: строкой учёта (L2) и документом с
    # поставщиком и подписантом. Второй разворачивается отдельно, потому что
    # пакет мог получить документы учёта и всё равно не отдать приёмку —
    # ровно так и вышло с бэкфиллом.
    receipts_only: bool = False


@router.post("/storage/reproject")
async def store_reproject(
    body: ReprojectIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Построить документы Ledger по пакетам, которые их не получили.

    Приём и разбор — разные события: пакет ложится сырьём (L1), документы
    рождает проекция (L2). Пакеты, залитые до появления разбора — исторический
    бэкфилл, — остались сырьём: смены есть, а продаж в учёте нет.

    Операция идемпотентна по построению: проекция ищет свои документы по
    происхождению и переписывает их, а не плодит вторые. Поэтому повтор
    безопасен, а «достроить» никогда не значит «задвоить».

    По умолчанию это предпросмотр: сначала показать, сколько пакетов будет
    разобрано, и лишь потом трогать учёт.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    if not user.is_superadmin:
        m = (await db.execute(select(UserCompany).where(
            UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if m is None or m.role != "admin":
            raise HTTPException(403, "Достройку учёта выполняет администратор компании")

    p: dict = {"cid": cid, "lim": max(1, min(body.limit, 5000))}
    условия = ["p.company_id = :cid",
               "p.kind IN ('shift', 'purchase', 'writeoff', 'inventory', 'transfer',"
               " 'return_sale', 'production')",
               # Служебный документ станции в учёт не идёт.
               #
               # Так помечен пересчёт, за которым НЕ стояло физического счёта
               # товара: проверка приёмника, тестовый прогон, оформление правки
               # сопровождения при рассогласовании кассы и учёта. Выпустить по
               # нему списание недостачи или оприходование излишка значит
               # завести в бухгалтерию документ о том, чего никто не считал —
               # а суммы там нешуточные: у одного такого «пересчёта зала» 130
               # тысяч недостачи и 590 тысяч излишка. Станция такие документы
               # прячет у себя (agent doc-service), сюда признак приезжает
               # полем «СлужебныйДокумент» в пакете.
               """NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) sd
             WHERE (sd->>'СлужебныйДокумент') IN ('true', 'True', '1'))"""]
    if body.station_id is not None:
        условия.append("p.station_id = :st")
        p["st"] = body.station_id
    if body.date_from:
        условия.append("p.received_at >= :d1")
        p["d1"] = date.fromisoformat(body.date_from)
    if body.date_to:
        условия.append("p.received_at < (CAST(:d2 AS date) + 1)")
        p["d2"] = date.fromisoformat(body.date_to)

    if body.receipts_only:
        условия.append("""EXISTS (
            SELECT 1 FROM jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d
            WHERE d->>'Тип' = 'purchase')""")
        сироты = [dict(r) for r in (await db.execute(text(f"""
            SELECT p.packet_uuid, p.station_id, p.kind, p.received_at
            FROM edge_packets p
            WHERE {' AND '.join(условия)}
            ORDER BY p.received_at
            LIMIT :lim
        """), p)).mappings().all()]
        итог = {"dry_run": body.dry_run, "packets": len(сироты),
                "by_kind": {}, "projected": 0, "receipts": 0, "errors": []}
        for с in сироты:
            итог["by_kind"][с["kind"]] = итог["by_kind"].get(с["kind"], 0) + 1
        if body.dry_run:
            return итог
        for с in сироты:
            пакет = (await db.execute(select(EdgePacket).where(
                EdgePacket.company_id == cid,
                EdgePacket.packet_uuid == с["packet_uuid"]))).scalar_one_or_none()
            if пакет is None:
                continue
            try:
                было = (await db.execute(select(func.count()).select_from(StoreReceipt)
                                         .where(StoreReceipt.company_id == cid))).scalar() or 0
                await edge_router._ingest_receipts(
                    db, cid, пакет.station_id, пакет.payload,
                    (пакет.payload or {}).get("Документы") or [])
                await db.commit()
                стало = (await db.execute(select(func.count()).select_from(StoreReceipt)
                                          .where(StoreReceipt.company_id == cid))).scalar() or 0
                итог["receipts"] += max(0, стало - было)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                итог["errors"].append(f"{с['packet_uuid'][:8]}: {str(exc)[:200]}")
        return итог

    сироты = [dict(r) for r in (await db.execute(text(f"""
        SELECT p.packet_uuid, p.station_id, p.kind, p.received_at
        FROM edge_packets p
        LEFT JOIN LATERAL (
            SELECT 1 FROM data_entries d
            WHERE d.company_id = p.company_id AND d.source = 'edge'
              AND d.metadata->'Edge'->>'packet_uuid' = p.packet_uuid
            LIMIT 1
        ) есть ON true
        WHERE {' AND '.join(условия)} AND есть IS NULL
        ORDER BY p.received_at
        LIMIT :lim
    """), p)).mappings().all()]

    итог = {"dry_run": body.dry_run, "packets": len(сироты),
            "by_kind": {}, "projected": 0, "receipts": 0, "errors": []}
    for с in сироты:
        итог["by_kind"][с["kind"]] = итог["by_kind"].get(с["kind"], 0) + 1
    if body.dry_run:
        return итог

    for с in сироты:
        пакет = (await db.execute(select(EdgePacket).where(
            EdgePacket.company_id == cid,
            EdgePacket.packet_uuid == с["packet_uuid"]))).scalar_one_or_none()
        if пакет is None:
            continue
        try:
            результат = await edge_projection.project_packet(
                db, cid, пакет.packet_uuid, пакет.station_id, пакет.payload)
            итог["projected"] += int(результат.get("created", 0)) + int(результат.get("updated", 0))
            # Приёмка станции — не только строка учёта, но и документ с
            # поставщиком и подписантом: разворачиваем тем же путём, каким её
            # принимает живой пакет.
            docs = (пакет.payload or {}).get("Документы") or []
            было = (await db.execute(select(func.count()).select_from(StoreReceipt)
                                     .where(StoreReceipt.company_id == cid))).scalar() or 0
            await edge_router._ingest_receipts(db, cid, пакет.station_id, пакет.payload, docs)
            стало = (await db.execute(select(func.count()).select_from(StoreReceipt)
                                      .where(StoreReceipt.company_id == cid))).scalar() or 0
            итог["receipts"] += max(0, стало - было)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            итог["errors"].append(f"{с['packet_uuid'][:8]} ({с['kind']}): {str(exc)[:200]}")
    return итог


# ── Отложенные перевыгрузки ────────────────────────────────────────────────
#
# Станция вправе прислать пакет заново с исправленным содержимым под тем же
# идентификатором: так было со ставкой НДС, взятой у чужого кода нефтесервера.
# Приёмник такой пакет не применяет молча — он откладывает его как ревизию и
# отвечает 409, потому что переписать уже разобранную смену без ведома человека
# нельзя. Но дальше ревизия попадала в тупик: её никто не читал и применить её
# было нечем. Обещание «исправление не потеряется» держалось на одной записи в
# таблицу. Здесь ревизия становится решением: принять новую версию или
# отклонить, оставив принятую.


@router.get("/packet-revisions")
async def store_packet_revisions(
    station_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Перевыгрузки, ждущие решения: чем новая версия отличается от принятой."""
    cid: uuid.UUID = await scope_company_id(user, db)
    p: dict = {"cid": cid}
    условия = ["r.company_id = :cid", "r.status = 'needs_review'",
               # Решение живёт отдельным фактом: сама ревизия неизменяема.
               "NOT EXISTS (SELECT 1 FROM edge_packet_revision_decisions d"
               "             WHERE d.revision_id = r.id)"]
    if station_id is not None:
        условия.append("p.station_id = :st")
        p["st"] = station_id
    строки = [dict(r) for r in (await db.execute(text(f"""
        SELECT r.id::text AS id, r.packet_uuid, r.error,
               r.received_at AS created_at,
               p.kind, p.station_id, p.received_at AS принят,
               -- Два имени у одного факта: смены шлют «ВремяВыгрузки»,
               -- конверт формата 3 (рецептуры станции) — «Выгружен».
               coalesce(p.payload->>'ВремяВыгрузки', p.payload->>'Выгружен') AS выгружен_принятый,
               coalesce(r.payload->>'ВремяВыгрузки', r.payload->>'Выгружен') AS выгружен_новый,
               jsonb_array_length(coalesce(p.payload->'Документы','[]'::jsonb)) AS документов_принято,
               jsonb_array_length(coalesce(r.payload->'Документы','[]'::jsonb)) AS документов_ново,
               p.payload#>>'{{Смена,НомерСменыВнутр}}' AS смена
          FROM edge_packet_revisions r
          JOIN edge_packets p ON p.id = r.edge_packet_id
         WHERE {' AND '.join(условия)}
         ORDER BY r.received_at DESC
         LIMIT 200
    """), p)).mappings().all()]
    return {"revisions": строки, "count": len(строки)}


@router.post("/packet-revisions/{revision_id}/{decision}")
async def store_packet_revision_resolve(
    revision_id: uuid.UUID,
    decision: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принять исправленную версию пакета или отклонить её.

    «Принять» — заменить сырьё принятого пакета новой версией и разобрать его
    заново теми же руками, какими разбирается живая доставка. Разбор идемпотентен
    по происхождению: документы ищутся по пакету и переписываются, а не плодятся.
    """
    if decision not in ("apply", "reject"):
        raise HTTPException(400, "Решение: apply или reject")
    cid: uuid.UUID = await scope_company_id(user, db)
    if not user.is_superadmin:
        m = (await db.execute(select(UserCompany).where(
            UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if m is None or m.role != "admin":
            raise HTTPException(403, "Перевыгрузки разбирает администратор компании")

    ревизия = (await db.execute(select(edge_router.EdgePacketRevision).where(
        edge_router.EdgePacketRevision.id == revision_id,
        edge_router.EdgePacketRevision.company_id == cid,
    ))).scalar_one_or_none()
    if ревизия is None:
        raise HTTPException(404, "Перевыгрузка не найдена")
    if ревизия.status != "needs_review":
        raise HTTPException(409, f"Это не отложенная перевыгрузка: {ревизия.status}")
    принято_ранее = (await db.execute(text(
        "SELECT decision FROM edge_packet_revision_decisions WHERE revision_id = :r"
    ), {"r": revision_id})).scalar_one_or_none()
    if принято_ранее is not None:
        raise HTTPException(409, f"Перевыгрузка уже разобрана: {принято_ранее}")

    async def записать_решение(исход: str, note: str = "") -> None:
        await db.execute(text("""
            INSERT INTO edge_packet_revision_decisions
                (id, company_id, revision_id, decision, decided_by, note)
            VALUES (:id, :cid, :r, :d, :by, :note)
        """), {"id": uuid.uuid4(), "cid": cid, "r": revision_id, "d": исход,
               "by": user.email or "", "note": note})

    if decision == "reject":
        await записать_решение("rejected")
        await db.commit()
        return {"ok": True, "status": "rejected"}

    пакет = await db.get(EdgePacket, ревизия.edge_packet_id)
    if пакет is None:
        raise HTTPException(404, "Пакет перевыгрузки не найден")

    # Прежнюю версию сохраняем ревизией, а не затираем: сырьё пакета — это
    # доказательство доставки, и «принять новую» не должно быть операцией без
    # обратного хода. Статус у неё «received» — она и была принятой доставкой.
    прежний_хеш = edge_router._raw_payload_hash(пакет.payload or {})
    уже_есть = (await db.execute(select(edge_router.EdgePacketRevision.id).where(
        edge_router.EdgePacketRevision.company_id == cid,
        edge_router.EdgePacketRevision.packet_uuid == str(пакет.packet_uuid),
        edge_router.EdgePacketRevision.content_hash == прежний_хеш,
    ))).scalar_one_or_none()
    if уже_есть is None:
        db.add(edge_router.EdgePacketRevision(
            id=uuid.uuid4(), company_id=cid, edge_packet_id=пакет.id,
            packet_uuid=str(пакет.packet_uuid), content_hash=прежний_хеш,
            payload=пакет.payload, size_bytes=пакет.size_bytes,
            wire_size_bytes=пакет.wire_size_bytes, status="received",
            error=f"версия, заменённая перевыгрузкой: {user.email}",
        ))

    payload = ревизия.payload or {}
    docs = payload.get("Документы") or []
    пакет.payload = payload
    пакет.size_bytes = ревизия.size_bytes
    пакет.wire_size_bytes = ревизия.wire_size_bytes
    try:
        if пакет.kind == "transfer":
            await edge_router._route_transfer_packet(db, cid, пакет.station_id, payload)
        await edge_router._ingest_receipts(db, cid, пакет.station_id, payload, docs)
        if пакет.kind == "cheques":
            await edge_router._ingest_cheques(
                db, cid, пакет.station_id, payload, str(пакет.packet_uuid))
        if пакет.kind in ("station-nsi", "station-mrc"):
            await edge_nsi.ingest_station_nsi(db, cid, пакет.station_id, docs)
        if пакет.kind == "station-catalog":
            await edge_nsi.ingest_station_catalog(db, cid, пакет.station_id, docs)
        if пакет.kind == "stock":
            await edge_router._sync_stock_packet(db, cid, пакет.station_id, payload)
        await edge_projection.project_packet(
            db, cid, str(пакет.packet_uuid), пакет.station_id, payload)
        await записать_решение("applied", f"вид {пакет.kind}, АЗС {пакет.station_id}")
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(422, f"Перевыгрузка не разобрана: {str(exc)[:300]}") from exc
    return {"ok": True, "status": "applied", "kind": пакет.kind,
            "station_id": пакет.station_id}


# ── Сводная: тот же конструктор разрезов, что в «Топливе» ───────────────────
#
# Экран собирает разрез сам: уровни переставляются мышью, дерево и подытоги
# считает браузер. Сервер отдаёт только листья — агрегаты по НАБОРУ измерений,
# поэтому перестановка уровней в сеть не идёт: «АЗС → место» и «место → АЗС» —
# один и тот же запрос.
#
# Источники разведены намеренно: у остатков метрики в штуках и рублях запаса, у
# чеков — сумма покупки и средний чек. Смешать их в одну сводную значит получить
# итог, который не сойдётся ни с одним экраном.
_PIVOT_SOURCES = {"store_stock": StoreStockBalance, "store_cheques": StoreCheque}


@router.get("/pivot/dims")
async def store_pivot_dims(
    source: str = Query("store_stock", description="store_stock | store_cheques"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Справочник измерений и метрик источника — тот же, что режет SQL."""
    await scope_company_id(user, db)
    from app.services.pivot_dims import dims_catalog, metrics_catalog
    if source not in _PIVOT_SOURCES:
        raise HTTPException(400, f"Неизвестный источник сводной: {source}")
    return {"dims": dims_catalog(source), "metrics": metrics_catalog(source)}


@router.get("/pivot")
async def store_pivot(
    source: str = Query("store_stock"),
    dims: str = Query(..., description="ключи измерений через запятую, например station,place"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    limit: int = Query(20000, le=50000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Листья сводной магазина: GROUP BY по выбранным измерениям."""
    from app.services.pivot_dims import (
        dim_label, dim_select, metric_selects, metrics_catalog, parse_dims,
    )

    cid: uuid.UUID = await scope_company_id(user, db)
    модель = _PIVOT_SOURCES.get(source)
    if модель is None:
        raise HTTPException(400, f"Неизвестный источник сводной: {source}")
    try:
        keys = parse_dims(dims, source)
    except ValueError as e:
        raise HTTPException(400, str(e))

    conds = [модель.company_id == cid]
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    if коды:
        conds.append(модель.station_id.in_(коды))
    # Период есть только у чеков: остаток — это срез на момент снимка, и
    # фильтровать его датами значило бы показывать пустоту за прошлый месяц.
    if source == "store_cheques":
        if date_from:
            conds.append(модель.at >= date.fromisoformat(date_from))
        if date_to:
            conds.append(модель.at < date.fromisoformat(date_to) + timedelta(days=1))

    cols = [dim_select(k, source).label(f"d{i}") for i, k in enumerate(keys)]
    metrics = metric_selects(source)
    mcols = [expr.label(f"m{i}") for i, (_, expr, _) in enumerate(metrics)]
    res = (await db.execute(select(*cols, *mcols).where(*conds)
                            .group_by(*cols).limit(limit + 1))).all()
    truncated = len(res) > limit
    rows = res[:limit]

    return {
        "dims": keys,
        "labels": [dim_label(k, source) for k in keys],
        "metrics": metrics_catalog(source),
        "stationNames": {},
        "rows": [{
            "keys": [r[i] for i in range(len(keys))],
            "m": {k: round(float(r[len(keys) + j]), d) for j, (k, _, d) in enumerate(metrics)},
        } for r in rows],
        "truncated": truncated,
    }


@router.get("/reports")
async def store_network_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Витрина отчётов сети: что есть и о чём каждый.

    На станции такой раздел уже работает в рабочем месте агента. Здесь те же
    вопросы, заданные сети: не «что на моей полке», а «что по всем АЗС и чем
    одна отличается от другой».
    """
    await scope_company_id(user, db)
    # Разделы отдаются вместе с витриной: каталог отчётов повторяет меню, и
    # порядок разделов задаёт сервер — иначе фронт заведёт свой второй список.
    return {"groups": store_reports.GROUPS,
            "reports": [{"key": k, **{f: v for f, v in r.items() if f != "fields"}}
                        for k, r in store_reports.REPORTS.items()]}


@router.get("/dynamics")
async def store_dynamics_compare(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую; пусто — вся сеть"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Период против равного предыдущего с раскладкой изменения маржи.

    Та же раскладка, что считает станция у себя: центр и АЗС обязаны объяснять
    одну разницу одинаково, иначе разбор месяца превращается в спор отчётов.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_dynamics.compare(db, cid, date_from, date_to, коды or None)


@router.get("/baskets")
async def store_baskets_analysis(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую; пусто — вся сеть"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Как покупают: средний чек, глубина, часы, оплаты, связки — по сети.

    Тот же разбор, что станция делает у себя, но с разрезом по АЗС: сравнить
    корзину двух точек можно только отсюда. Топливной части у центра нет —
    приёмник хранит только товарные строки чека, — поэтому «прицеп к топливу»
    здесь заменён долей товарных чеков, купленных вместе с заправкой.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_baskets.analyze(db, cid, date_from, date_to, коды or None)


class _MrcAccept(BaseModel):
    """Приём цен, продиктованных маркой. Пустой items — все объяснённые маркой."""
    date_from: str | None = None
    date_to: str | None = None
    stations: list[int] | None = None
    items: list[str] | None = None      # ключи «станция:карточка» из таблицы


@router.get("/price-mrc")
async def store_price_mrc(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую; пусто — вся сеть"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Где по сети наша цена отстала от марки и сколько выручки на этом теряется.

    Цену маркированного табака задаёт пачка, а не справочник: касса читает МРЦ
    из кода и пробивает по ней. Подорожание приходит ко всем станциям одной
    волной — поэтому смотреть его надо отсюда, а не по одной АЗС.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_mrc_prices.rows(db, cid, date_from, date_to, коды or None)


@router.post("/price-mrc/accept")
async def store_price_mrc_accept(
    body: _MrcAccept,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принять цену марки: наша цена догоняет ту, по которой пробила касса.

    Тот же гейт, что у массовой переоценки: коммерческое решение из центра
    пишется только в совместном режиме политики «Магазина» и только товароведом
    сети. Автор берётся из сессии — цена это деньги, подписать её чужим именем
    нельзя.
    """
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    автор = getattr(user, "full_name", None) or getattr(user, "email", "") or "центр"
    return await store_mrc_prices.accept(db, cid, автор, body.date_from, body.date_to,
                                         body.stations, body.items)


@router.get("/price-response")
async def store_price_response(
    window: int = Query(14, ge=3, le=60, description="дней наблюдения до и после"),
    limit: int = Query(30, ge=1, le=100),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Как спрос ответил на цену: подняли — и что стало.

    Наблюдение, а не «настоящая» эластичность: контрольной группы и очищенного
    от сезонности ряда у розницы АЗС нет. Поэтому ответ всегда идёт вместе с
    числом дней, на которых он построен.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_dynamics.отклики(db, cid, окно=window, лимит=limit,
                                        stations=коды or None)


@router.get("/baskets/item")
async def store_baskets_item(
    name: str = Query(..., description="название позиции как в чеке"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """«Взяли кофе — что ещё положат в корзину»: разбор вокруг одной позиции.

    Общая таблица связок отвечает, какие пары есть в сети; этот разбор — с чем
    берут ИМЕННО эту позицию и в какие часы. Из первого делают выкладку по сети,
    из второго — перестановку у кассы.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_baskets.по_товару(db, cid, date_from, date_to, name,
                                         коды or None)


@router.get("/price-log")
async def store_price_log(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Журнал цен сети: кто и когда двигал цену, было → стало."""
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_dynamics.price_log(
        db, cid, date_from, date_to, коды or None, offset=offset, limit=limit)


class _RepricingRule(BaseModel):
    """Правило и отбор массовой переоценки — те же поля, что у станции."""
    mode: str = "процент"
    value: float = 0
    round: str = ""
    floor: float = 5          # пол маржи, %
    step: float = 15          # потолок разового шага, %
    kvi: bool = False         # трогать ли ключевые позиции
    group: str = ""
    q: str = ""
    sold: bool = False
    date_from: str | None = None
    date_to: str | None = None
    stations: list[int] | None = None
    items: list[str] | None = None   # только эти карточки (галочки в таблице)


def _правило_и_отбор(r: _RepricingRule) -> tuple[dict, dict]:
    правило = {"mode": r.mode, "value": r.value, "round": r.round,
               "floor": r.floor, "step": r.step, "kvi": r.kvi}
    отбор = {"group": r.group, "q": r.q, "sold": r.sold,
             "date_from": r.date_from, "date_to": r.date_to}
    return правило, отбор


@router.post("/repricing/preview")
async def store_repricing_preview(
    body: _RepricingRule,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Что станет с ценами сети по этому правилу. Ничего не меняет."""
    cid: uuid.UUID = await scope_company_id(user, db)
    правило, отбор = _правило_и_отбор(body)
    return await store_repricing.preview(db, cid, правило, отбор, body.stations)


class _PlanPut(_RepricingRule):
    """Положить результат правила в корзину. Те же поля, что у предпросмотра."""
    reason: str = ""


class _PlanEdit(BaseModel):
    price: float


class _PlanApply(BaseModel):
    """Когда применять корзину: сейчас · через N минут · к дате и времени."""
    mode: str = "now"                 # now | delay | scheduled
    delay: int | None = None          # минут, для mode=delay
    effective: str | None = None      # ISO-время в поясе сети, для mode=scheduled
    items: list[str] | None = None    # id строк корзины; пусто — вся корзина


@router.get("/price-plan")
async def store_price_plan(
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Корзина цен: что накоплено, что запланировано и что уже применено.

    Пока изменение лежит здесь, на полке и в кассе прежняя цена — это намерение,
    а не факт.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    return await store_price_plans.список(db, cid, коды or None)


@router.post("/price-plan")
async def store_price_plan_put(
    body: _PlanPut,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Посчитать правило и положить результат в корзину. Цены не меняет.

    Пересчёт делается здесь заново, а не берётся из присланной таблицы: цена
    могла уехать, пока человек смотрел предпросмотр.
    """
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    правило, отбор = _правило_и_отбор(body)
    расчёт = await store_repricing.preview(db, cid, правило, отбор, body.stations)
    отмечены = set(body.items or [])
    поедут = [r for r in расчёт["rows"]
              if not r["reject"] and (not отмечены or r["item_uuid"] in отмечены)]
    автор = getattr(user, "full_name", None) or getattr(user, "email", "") or "центр"
    причина = body.reason or store_repricing.описание_правила(правило)
    return await store_price_plans.положить(db, cid, поедут, автор, причина)


@router.put("/price-plan/{plan_id}")
async def store_price_plan_edit(
    plan_id: str,
    body: _PlanEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Исправить цену строки прямо в корзине."""
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    автор = getattr(user, "full_name", None) or getattr(user, "email", "") or "центр"
    try:
        return await store_price_plans.править(db, cid, plan_id, body.price, автор)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/price-plan/{plan_id}")
async def store_price_plan_cancel(
    plan_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Снять позицию из корзины или отменить запланированное до применения."""
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    try:
        return await store_price_plans.снять(db, cid, plan_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/price-plan/apply")
async def store_price_plan_apply(
    body: _PlanApply,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Применить корзину сейчас или отложить до указанного времени.

    Отложенное исполняет фоновый воркер: обещание «сменить к открытию смены» не
    должно зависеть от того, открыт ли у кого-то браузер.
    """
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    автор = getattr(user, "full_name", None) or getattr(user, "email", "") or "центр"
    try:
        return await store_price_plans.применить(
            db, cid, автор, mode=body.mode, delay=body.delay,
            effective=body.effective, только=body.items)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/repricing/apply")
async def store_repricing_apply(
    body: _RepricingRule,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Применить правило: история цен центра + задания станциям.

    Автор берётся из сессии, а не из формы: цена — это деньги, и подписать
    чужим именем её нельзя.
    """
    cid: uuid.UUID = await _require_central_commercial_control(user, db)
    правило, отбор = _правило_и_отбор(body)
    автор = getattr(user, "full_name", None) or getattr(user, "email", "") or "центр"
    return await store_repricing.apply(db, cid, правило, отбор, автор,
                                       body.stations, body.items)


@router.get("/reports/goods-report/print", response_class=HTMLResponse)
async def store_goods_report_print(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Товарный отчёт листом офиса — та же бумага, что печатает станция.

    Подразделение подписывается кодом АЗС, когда выбрана одна: лист сдают за
    конкретную точку. Выбрано несколько или вся сеть — так и печатаем, врать
    названием одной станции нельзя.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    данные = await store_reports.BUILDERS["goods-report"](
        db, cid, date_from, date_to, коды or None)
    company = await db.get(Company, cid)
    подразделение = (f"АЗС №{коды[0]}" if len(коды) == 1
                     else (f"АЗС: {', '.join(map(str, коды))}" if коды else "вся сеть"))
    return HTMLResponse(лист_товарного_отчёта(
        данные, организация=getattr(company, "name", "") or "",
        подразделение=подразделение))


@router.get("/reports/{kind}")
async def store_network_report(
    kind: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую; пусто — вся сеть"),
    format: str = Query("json", description="json | csv"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёт сети по видам. CSV открывается Excel двойным кликом."""
    cid: uuid.UUID = await scope_company_id(user, db)
    схема = store_reports.REPORTS.get(kind)
    строитель = store_reports.BUILDERS.get(kind)
    if схема is None or строитель is None:
        raise HTTPException(404, f"Неизвестный отчёт: {kind}")

    коды = [int(s) for s in (stations or "").replace(" ", "").split(",") if s.isdigit()]
    данные = await строитель(db, cid, date_from, date_to, коды or None)

    if format not in ("csv", "xlsx"):
        return {"kind": kind, "title": схема["title"], "about": схема["about"],
                "columns": схема["columns"], "fields": схема["fields"],
                "stations": коды, "date_from": date_from, "date_to": date_to,
                **данные}

    from fastapi.responses import Response as FileResponse
    from app.services.export_files import XLSX_MIME, content_disposition

    def ячейка(r: dict, f: str):
        v = r.get(f)
        if v is None:
            # Пусто честнее слова «None»: раньше пустая дата смены печаталась
            # в файле буквально этими четырьмя буквами.
            return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if v is True:
            return "да"
        if v is False:
            return "нет"
        if f.endswith("date") or f == "doc_date":
            return str(v)[:19]
        return v

    строки = [[ячейка(r, f) for f in схема["fields"]] for r in данные["rows"]]

    if format == "xlsx":
        # Книга — основная выгрузка: шапка с периодом и отбором, закреплённые
        # заголовки, автофильтр, денежный формат, коды текстом. В CSV ничего
        # этого нет, а отчёт открывают, чтобы отобрать и посчитать.
        мета = [("Область", "вся сеть" if not коды else
                 ", ".join(f"АЗС №{c}" for c in коды))]
        if date_from:
            мета.append(("С", date_from))
        if date_to:
            мета.append(("По", date_to))
        мета += [
            ("Строк в отчёте", str(len(строки))),
            ("Сформирован", datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")),
            ("Источник", "Магазин · отчёты сети"),
        ]
        # Вид строки бланка (итог/раздел/остаток/сноска) отдают только
        # отчёты-бланки; выборки его не несут, и книга у них прежняя.
        виды = [str(r.get("kind") or "") for r in данные["rows"]]
        книга = store_reports.xlsx_bytes(схема["columns"], строки, мета,
                                         схема["title"], схема.get("about", ""),
                                         kinds=виды if any(виды) else None)
        имяКниги = f"{kind}-{date_from or 'все'}_{date_to or 'все'}.xlsx"
        return FileResponse(content=книга, media_type=XLSX_MIME,
                            headers={"Content-Disposition": content_disposition(имяКниги),
                                     "Cache-Control": "private, no-store"})

    тело = store_reports.csv_bytes(схема["columns"], строки)
    имя = f"{kind}-{date_from or 'все'}_{date_to or 'все'}.csv"
    # Имя файла — в заголовок по RFC 5987, а не в самодельный X-Report-Name:
    # его браузер не читает, и все шестнадцать отчётов сохранялись как
    # «report.csv», затирая друг друга.
    return FileResponse(content=тело, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": content_disposition(имя),
                                 "Cache-Control": "private, no-store"})


@router.get("/storage")
async def store_storage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сколько занимает сырьё станций и что можно проредить.

    Снимок остатков приходит каждый час и весит около полумегабайта: за месяц
    одна станция откладывает треть гигабайта. Документы и смены — первичка,
    из них строится учёт, их не трогаем; снимок же нужен свежий, а история
    снимков нужна только для разбирательств, и одного за день хватает.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    виды = [dict(r) for r in (await db.execute(text("""
        SELECT kind, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes,
               min(received_at) AS oldest, max(received_at) AS newest
        FROM edge_packets WHERE company_id = :cid
        GROUP BY kind ORDER BY sum(size_bytes) DESC NULLS LAST
    """), {"cid": cid})).mappings().all()]
    for v in виды:
        v["label"] = PACKET_KIND_LABEL.get(v["kind"], v["kind"])
        v["keep"] = v["kind"] != "stock"

    станции = [dict(r) for r in (await db.execute(text("""
        SELECT station_id, count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes
        FROM edge_packets WHERE company_id = :cid
        GROUP BY station_id ORDER BY station_id
    """), {"cid": cid})).mappings().all()]

    heartbeats = (await db.execute(text("""
        SELECT count(*) AS rows, min(at) AS oldest FROM edge_heartbeats
        WHERE company_id = :cid
    """), {"cid": cid})).mappings().first()

    return {
        "kinds": виды,
        "stations": станции,
        "total_bytes": sum(int(v["bytes"]) for v in виды),
        "heartbeats": {"rows": int(heartbeats["rows"] or 0),
                       "oldest": heartbeats["oldest"] if heartbeats else None},
    }


@router.post("/storage/cleanup")
async def store_storage_cleanup(
    body: StorageCleanupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проредить историю снимков и след телеметрии.

    Снимок остатков документов учёта не порождает — его проекция ничего не
    строит, поэтому лишние снимки удаляются без последствий для отчётов.
    Остаётся самый свежий снимок каждой станции за каждый день; свежее
    указанного возраста не трогаем вовсе.

    По умолчанию это предпросмотр: сначала показать, сколько уйдёт, и только
    потом удалять — данные станции восстановить неоткуда.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    if not user.is_superadmin:
        m = (await db.execute(select(UserCompany).where(
            UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if m is None or m.role != "admin":
            raise HTTPException(403, "Чистку хранилища выполняет администратор компании")
    if body.thin_after_days < 3 or body.heartbeat_days < 7:
        raise HTTPException(400, "Слишком короткое хранение: минимум 3 дня для снимков "
                                 "и 7 дней для телеметрии")

    p = {"cid": cid, "thin": body.thin_after_days, "hb": body.heartbeat_days}
    лишние = """
        SELECT id, size_bytes FROM (
            SELECT id, size_bytes, row_number() OVER (
                       PARTITION BY station_id, received_at::date
                       ORDER BY received_at DESC) AS n
            FROM edge_packets
            WHERE company_id = :cid AND kind = 'stock'
              AND received_at < now() - make_interval(days => :thin)
        ) t WHERE n > 1
    """
    оценка = (await db.execute(text(f"""
        SELECT count(*) AS packets, coalesce(sum(size_bytes), 0) AS bytes FROM ({лишние}) x
    """), p)).mappings().first()
    hb = (await db.execute(text("""
        SELECT count(*) AS rows FROM edge_heartbeats
        WHERE company_id = :cid AND at < now() - make_interval(days => :hb)
    """), p)).mappings().first()

    итог = {
        "dry_run": body.dry_run,
        "snapshots": int(оценка["packets"] or 0),
        "bytes": int(оценка["bytes"] or 0),
        "heartbeats": int(hb["rows"] or 0),
        "thin_after_days": body.thin_after_days,
        "heartbeat_days": body.heartbeat_days,
    }
    if body.dry_run:
        return итог

    await db.execute(text(f"DELETE FROM edge_packets WHERE id IN (SELECT id FROM ({лишние}) d)"), p)
    await db.execute(text("""
        DELETE FROM edge_heartbeats
        WHERE company_id = :cid AND at < now() - make_interval(days => :hb)
    """), p)
    await db.commit()
    return итог


# Товарные группы ИСМП, до которых нам есть дело сейчас или в обозримом
# будущем: правила и сроки у них разные, поэтому группа — справочник, а не флаг.
# Товарные группы «Честного знака». Источник правды — таблица
# `edge.mark_group` (заполняется миграцией v2.46): группы добавляются каждый
# год, и держать их списком в коде значит выкатывать релиз ради строки
# справочника. Здесь остаётся отступление на случай, до которого миграция ещё
# не дошла, — экран не должен падать из-за пустой таблицы.
MARK_GROUPS = {
    "tobacco": "Табачная продукция",
    "nicotine": "Никотинсодержащая продукция",
    "water": "Упакованная вода",
    "beer": "Пиво и слабоалкогольные напитки",
    "milk": "Молочная продукция",
}


async def _mark_groups(db: AsyncSession) -> list[dict]:
    """Справочник групп с числом карточек в каждой.

    Число рядом с названием отвечает на вопрос, ради которого справочник и
    заводился: «что у нас лежит в этой группе» — раньше ответ был «236 штук
    в корзине „по данным 1С"», то есть никакой.
    """
    try:
        строки = (await db.execute(text("""
            SELECT g.code, g.name, g.cash_code, g.since, g.note,
                   count(i.id) FILTER (WHERE NOT i.deleted) AS items
              FROM edge.mark_group g
              LEFT JOIN edge.item i ON i.mark_group = g.name
             GROUP BY g.code, g.name, g.cash_code, g.since, g.note
             ORDER BY count(i.id) FILTER (WHERE NOT i.deleted) DESC, g.name
        """))).mappings().all()
    except Exception:  # noqa: BLE001 — таблицы ещё нет, миграция не дошла
        return [{"code": code, "name": name, "cash_code": None,
                 "since": None, "note": None, "items": 0}
                for code, name in MARK_GROUPS.items()]
    return [{"code": r["code"], "name": r["name"], "cash_code": r["cash_code"],
             "since": r["since"].isoformat() if r["since"] else None,
             "note": r["note"], "items": int(r["items"])} for r in строки]


async def _marked_without_group(db: AsyncSession) -> dict:
    """Маркируемые карточки, которым группа не назначена.

    Это и есть работа товароведа: у каждой группы свои правила приёмки и свой
    срок обязательности, и «маркируется, а чем — неизвестно» на тридцати точках
    превращается в остановленную приёмку.
    """
    try:
        строки = (await db.execute(text("""
            SELECT i.sku, i.name, coalesce(g.path, '') AS group_path
              FROM edge.item i
              LEFT JOIN edge.item_group g ON g.id = i.group_id
             WHERE i.marked AND NOT i.deleted
               AND coalesce(i.mark_group, '') IN ('', 'Требует маркировки (по данным 1С)')
             ORDER BY i.name
             LIMIT 200
        """))).mappings().all()
        всего = (await db.execute(text("""
            SELECT count(*) FROM edge.item i
             WHERE i.marked AND NOT i.deleted
               AND coalesce(i.mark_group, '') IN ('', 'Требует маркировки (по данным 1С)')
        """))).scalar() or 0
    except Exception:  # noqa: BLE001
        return {"total": 0, "items": []}
    return {"total": int(всего),
            "items": [{"sku": r["sku"] or "", "name": r["name"],
                       "group_path": r["group_path"]} for r in строки]}


# Виды документов станции, которые ведёт агент. Ключ — тип в пакете, значение —
# как это называется на экране: «writeoff» человеку ничего не говорит.
STATION_DOC_KINDS = {
    "writeoff": "Списание",
    "transfer": "Перемещение",
    "inventory": "Инвентаризация",
    "purchase": "Приёмка",
    # Возврат поставщику агент шлёт видом return_purchase (BuildReturn в
    # packet.go). Здесь стояло return_supplier — вид, которого станция никогда
    # не присылала, и такой возврат в реестре центра не появлялся вовсе.
    "return_purchase": "Возврат поставщику",
    "return_sale": "Возврат покупателя",
    # Оприходование: 49 документов станции лежали в пакетах и не показывались
    # нигде — вида просто не было в списке.
    "gain": "Оприходование",
    "production_release": "Производство",
    "revaluation": "Переоценка",
}
STATION_DOC_ALLOWED_KINDS = tuple(
    kind for kind in STATION_DOC_KINDS if kind in PROJECTION_DOCUMENT_KINDS)


def _legacy_station_scope(
    access: DocumentAccess, requested: set[int] | None,
) -> tuple[int, ...] | None:
    if access.network:
        return tuple(sorted(requested)) if requested else None
    allowed = set(access.station_ids)
    if requested is not None:
        allowed.intersection_update(requested)
    return tuple(sorted(allowed))


@router.get("/station-docs")
async def store_station_docs(
    kind: str | None = Query(None, description="вид документа; пусто — все"),
    station_id: int | None = Query(None, description="код АЗС; пусто — все"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=20000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Документы, заведённые НА СТАНЦИИ, — то, что сделал агент, а не 1С.

    Реестры склада исторически читают документы ЦБ: их полтора десятка тысяч и
    они кончаются датой, когда 1С перестанет вести станцию. Документы агента
    живут в пакетах, и без этого разреза работа станции в разделе не видна
    вовсе — а именно она и остаётся, когда 1С уходит.

    Источник — сырой пакет: разбор в документы Ledger идёт своим путём, но
    реестр обязан показывать то, что станция реально прислала.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    access = await resolve_document_access(user, db, cid)
    p: dict = {"cid": cid, "lim": limit}
    условия = ["p.company_id = :cid"]
    station_scope = _legacy_station_scope(
        access, {station_id} if station_id is not None else None)
    if station_scope == ():
        условия.append("FALSE")
    elif station_scope is not None:
        условия.append("p.station_id = ANY(CAST(:stations AS integer[]))")
        p["stations"] = list(station_scope)
    if kind:
        if kind not in STATION_DOC_ALLOWED_KINDS:
            raise HTTPException(400, "Неизвестный или запрещённый вид документа")
        условия.append("d->>'Тип' = :kind")
        p["kind"] = kind
    else:
        условия.append("d->>'Тип' = ANY(:kinds)")
        p["kinds"] = list(STATION_DOC_ALLOWED_KINDS)
    if date_from:
        условия.append("coalesce((d->>'Дата')::timestamptz, p.received_at) >= :d1")
        p["d1"] = date.fromisoformat(date_from)
    if date_to:
        условия.append("coalesce((d->>'Дата')::timestamptz, p.received_at) < (CAST(:d2 AS date) + 1)")
        p["d2"] = date.fromisoformat(date_to)

    rows = [dict(r) for r in (await db.execute(text(f"""
        SELECT p.station_id,
               -- Порядковый номер документа в пакете: карточка открывается по
               -- нему, другого устойчивого ключа у документа станции нет.
               (d_idx - 1) AS doc_index,
               d->>'Тип' AS kind,
               d->>'Номер' AS number,
               coalesce((d->>'Дата')::timestamptz, p.received_at) AS doc_date,
               coalesce(d->>'Склад', d->>'СкладОтправитель', '') AS place_from,
               coalesce(d->>'СкладПолучатель', '') AS place_to,
               coalesce(d->>'Причина', d->>'Комментарий', '') AS note,
               coalesce(d->>'Автор', '') AS author,
               d AS document_payload,
               p.received_at, p.packet_uuid, p.shift_number
        FROM edge_packets p,
             LATERAL jsonb_array_elements(coalesce(p.payload->'Документы', '[]'::jsonb))
                     WITH ORDINALITY AS t(d, d_idx)
        WHERE {' AND '.join(условия)}
        -- Сортировка по имени колонки, а не по номеру: номер сдвигается от
        -- любой новой колонки, и реестр молча начинает сортироваться по чужому.
        ORDER BY coalesce((d->>'Дата')::timestamptz, p.received_at) DESC
        LIMIT :lim
    """), p)).mappings().all()]
    ссылки = [f"station:{r['packet_uuid']}:{r['doc_index']}" for r in rows]
    мета = {m.doc_ref: m for m in (await db.execute(select(StoreDocMeta).where(
        StoreDocMeta.company_id == cid,
        StoreDocMeta.doc_ref.in_(ссылки or [""])))).scalars().all()} if ссылки else {}
    safe_rows = []
    for r in rows:
        sanitized = sanitize_edge_document(
            r.pop("document_payload", {}) or {}, trusted_station_packet=True)
        if sanitized["pure_fuel"]:
            continue
        r["label"] = STATION_DOC_KINDS.get(r["kind"], r["kind"])
        r["positions"] = len(sanitized["lines"]) + len(sanitized["services"])
        r["amount"] = float(sanitized["amount"])
        r["vat_amount"] = (None if sanitized["vat_amount"] is None
                           else float(sanitized["vat_amount"]))
        r["accounting_status"] = (
            "needs_review" if sanitized["quarantined"] else "ready")
        r["classification_error"] = sanitized["reason"]
        m = мета.get(f"station:{r['packet_uuid']}:{r['doc_index']}")
        r["status"] = m.status if m else "принят"
        r["reg_number"] = m.reg_number if m else None
        r["has_files"] = False
        safe_rows.append(r)
    rows = safe_rows

    свод: dict[str, dict] = {}
    станции: dict[int, int] = {}
    for r in rows:
        узел = свод.setdefault(r["kind"], {
            "kind": r["kind"], "label": r["label"], "docs": 0,
            "positions": 0, "amount": 0.0, "last_at": None})
        узел["docs"] += 1
        узел["positions"] += int(r["positions"] or 0)
        узел["amount"] += r["amount"]
        if узел["last_at"] is None or r["doc_date"] > узел["last_at"]:
            узел["last_at"] = r["doc_date"]
        станции[r["station_id"]] = станции.get(r["station_id"], 0) + 1

    return {
        "docs": rows,
        "total": len(rows),
        "by_kind": sorted(свод.values(), key=lambda x: -x["docs"]),
        "by_station": [{"station_id": sid, "docs": n} for sid, n in sorted(станции.items())],
        "kinds": STATION_DOC_KINDS,
        "truncated": len(rows) >= limit,
    }


@router.get("/cheques")
async def store_cheques(
    date_from: str = Query(...),
    date_to: str = Query(...),
    station_id: int | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    shift_number: int | None = Query(None),
    q: str | None = Query(None, description="товар, номер чека или фискальный номер"),
    only_returns: bool = Query(False),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Продажи на уровне чека, а не смены.

    Отчёт о розничных продажах закрывает смену сводом — этого хватает
    бухгалтерии, но не разбору: спорная продажа, возврат, проверка
    маркированного товара и жалоба покупателя разбираются по конкретному чеку.

    Топлива здесь нет: оно живёт в своём контуре. Смешанный чек (заправка плюс
    кофе) помечен признаком «было топливо» — иначе показанная сумма выглядела
    бы как весь чек, а это не так.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    access = await resolve_document_access(user, db, cid)
    d1, d2 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    условия = [StoreCheque.company_id == cid,
               StoreCheque.at >= datetime.combine(d1, time.min, tzinfo=timezone.utc),
               StoreCheque.at < datetime.combine(d2 + timedelta(days=1), time.min, tzinfo=timezone.utc)]
    коды = {int(s.strip()) for s in stations.split(",")
            if s.strip().isdigit()} if stations else set()
    if station_id is not None:
        коды.add(station_id)
    station_scope = _legacy_station_scope(access, коды or None)
    if station_scope is not None:
        условия.append(StoreCheque.station_id.in_(station_scope))
    if shift_number is not None:
        условия.append(StoreCheque.shift_number == shift_number)
    if only_returns:
        условия.append(StoreCheque.is_return.is_(True))

    # Поиск идёт в SQL, а не по уже отобранной тысяче.
    #
    # Раньше лимит применялся первым, и фильтр работал по хвосту выборки: за
    # месяц брались последние 1000 чеков, и «Camel», проданный в начале месяца,
    # не находился вовсе. Товаровед при этом видел «показаны первые N» и решал,
    # что чеков просто мало. Ищем по названию позиции, номеру чека и номеру ФД —
    # по тем трём полям, которыми чек и опознают.
    игла = (q or "").strip()
    if игла:
        шаблон = f"%{игла}%"
        условия.append(or_(
            cast(StoreCheque.number, String).ilike(шаблон),
            cast(StoreCheque.fiscal_number, String).ilike(шаблон),
            text("EXISTS (SELECT 1 FROM jsonb_array_elements(store_cheques.lines) AS поз"
                 " WHERE поз->>'name' ILIKE :игла)").bindparams(игла=шаблон),
        ))

    rows = (await db.execute(select(StoreCheque).where(*условия)
                             .order_by(StoreCheque.at.desc(), StoreCheque.id.desc())
                             )).scalars().all()
    packet_uuids = sorted({str(row.packet_uuid) for row in rows if row.packet_uuid})
    packet_rows = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == cid,
        EdgePacket.packet_uuid.in_(packet_uuids),
    ))).scalars().all() if packet_uuids else []
    packets = {str(row.packet_uuid): row for row in packet_rows}

    catalog = await load_item_catalog(db)

    safe_rows = []
    for r in rows:
        totals = goods_only_cheque_totals(
            cheque_lines_from_catalog(
                cheque_lines_with_legacy_provenance(
                    r, packets.get(str(r.packet_uuid))),
                catalog),
            bool(r.had_fuel),
        )
        if ((r.had_fuel and not r.lines)
                or (r.lines and totals["fuel_lines"] == len(r.lines))):
            continue
        safe_rows.append((r, totals))

    всего = len(safe_rows)
    продаж = sum(1 for r, _ in safe_rows if not r.is_return)
    возвратов = sum(1 for r, _ in safe_rows if r.is_return)
    сумма = sum((totals["amount"] for r, totals in safe_rows
                 if not r.is_return), Decimal("0"))
    сумма_возвратов = sum((totals["amount"] for r, totals in safe_rows
                            if r.is_return), Decimal("0"))
    средний = (сумма / продаж) if продаж else None
    с_топливом = sum(1 for r, _ in safe_rows if r.had_fuel)

    чеки = []
    for r, totals in safe_rows[offset:offset + limit]:
        чеки.append({
            "id": str(r.id), "station_id": r.station_id, "shift_number": r.shift_number,
            "number": r.number, "fiscal_number": r.fiscal_number, "at": r.at,
            "is_return": r.is_return, "had_fuel": r.had_fuel,
            "pay_type": r.pay_type, "pay_name": r.pay_name,
            "total": float(totals["amount"]), "positions": len(totals["lines"]),
            "vat_amount": (None if totals["vat_amount"] is None
                           else float(totals["vat_amount"])),
            "accounting_status": "needs_review" if totals["quarantined"] else "ready",
            "classification_error": totals["reason"],
            "lines": totals["lines"],
        })

    return {
        "cheques": чеки,
        "total": всего,
        "offset": offset,
        "limit": limit,
        "summary": {
            "sales": продаж,
            "returns": возвратов,
            "amount": round(float(сумма or 0), 2),
            "returns_amount": round(float(сумма_возвратов or 0), 2),
            # Средний чек считается по продажам без возвратов: возврат — это не
            # покупка, и включать его в среднее значит занижать его дважды.
            "avg": round(float(средний), 2) if средний is not None else None,
            "with_fuel": с_топливом,
        },
        "truncated": offset + len(чеки) < всего,
    }


@router.get("/transfers-between")
async def store_transfers_between(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    station_id: int | None = Query(None, description="АЗС с любой стороны передачи"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Передачи товара между АЗС: кто отправил, кто принял и что не сошлось.

    Перемещение внутри станции (склад ↔ торговый зал) — внутреннее дело
    товароведа. Передача между станциями — смена материально ответственного:
    один сдал, другой принял, и до подтверждения товар в пути, то есть
    физически нигде. Механика двусторонняя с самого начала (агент отправителя
    ставит получателю заготовку приёмки, тот отвечает подтверждением), но в
    центре её не было видно — а именно центр и разбирает, если не сошлось.

    Пары сводятся по идентификатору документа отправителя: подтверждение
    получателя несёт его в виде «incoming:<АЗС отправителя>:<документ>».
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    p: dict = {"cid": cid}
    период_out, период_in = "", ""
    if date_from:
        p["d1"] = date.fromisoformat(date_from)
        период_out += " AND coalesce((d->>'Дата')::timestamptz, p.received_at) >= :d1"
    if date_to:
        p["d2"] = date.fromisoformat(date_to)
        период_out += " AND coalesce((d->>'Дата')::timestamptz, p.received_at) < (CAST(:d2 AS date) + 1)"

    rows = [dict(r) for r in (await db.execute(text(f"""
        WITH отправки AS (
            SELECT p.station_id AS from_station,
                   d->>'ИдентификаторДокумента' AS doc_id,
                   d->>'Номер' AS number,
                   coalesce((d->>'Дата')::timestamptz, p.received_at) AS doc_date,
                   coalesce((d->>'КодАЗСПолучателя')::int, 0) AS to_station,
                   coalesce(d->>'МестоОтправитель', '') AS from_place,
                   coalesce(d->>'Комментарий', '') AS comment,
                   coalesce(jsonb_array_length(d->'Товары'), 0) AS positions,
                   (SELECT coalesce(sum((t->>'КоличествоОтправлено')::numeric), 0)
                      FROM jsonb_array_elements(coalesce(d->'Товары', '[]'::jsonb)) t) AS qty_sent,
                   p.packet_uuid, p.received_at
            FROM edge_packets p,
                 LATERAL jsonb_array_elements(coalesce(p.payload->'Документы', '[]'::jsonb)) d
            WHERE p.company_id = :cid AND d->>'Тип' = 'transfer'
              AND d->>'Направление' = 'out'{период_out}
        ), приёмы AS (
            SELECT p.station_id AS accepted_station,
                   d->>'ИдентификаторДокумента' AS incoming_id,
                   coalesce((d->>'Дата')::timestamptz, p.received_at) AS accepted_at,
                   (SELECT coalesce(sum((t->>'Количество')::numeric), 0)
                      FROM jsonb_array_elements(coalesce(d->'Товары', '[]'::jsonb)) t) AS qty_accepted,
                   p.packet_uuid AS accept_packet
            FROM edge_packets p,
                 LATERAL jsonb_array_elements(coalesce(p.payload->'Документы', '[]'::jsonb)) d
            WHERE p.company_id = :cid AND d->>'Тип' = 'transfer'
              AND d->>'Направление' = 'in'
        )
        SELECT о.*, пр.accepted_station, пр.accepted_at, пр.qty_accepted, пр.accept_packet,
               dl.delivered_at AS task_delivered_at, dl.acked_at AS task_acked_at,
               dl.cancelled_at AS task_cancelled_at
        FROM отправки о
        LEFT JOIN приёмы пр
               ON пр.incoming_id = 'incoming:' || о.from_station || ':' || о.doc_id
        LEFT JOIN edge_downlink dl
               ON dl.company_id = :cid AND dl.station_id = о.to_station
              AND dl.kind = 'incoming_transfer'
              AND dl.note = 'transfer:' || о.from_station || ':' || (
                    SELECT coalesce(d2->>'ИсточникUUID', '')
                    FROM edge_packets p2,
                         LATERAL jsonb_array_elements(coalesce(p2.payload->'Документы','[]'::jsonb)) d2
                    WHERE p2.packet_uuid = о.packet_uuid
                      AND d2->>'ИдентификаторДокумента' = о.doc_id
                    LIMIT 1)
        ORDER BY о.doc_date DESC
        -- Потолок высокий и осознанный: передач между АЗС в сети немного, а
        -- обрезать реестр молча нельзя — «в пути» не должно теряться за краем.
        LIMIT 5000
    """), p)).mappings().all()]

    now = datetime.now(timezone.utc)
    итог = {"в пути": 0, "принято": 0, "расхождение": 0}
    передачи = []
    for r in rows:
        if station_id is not None and station_id not in (r["from_station"], r["to_station"]):
            continue
        отправлено = float(r["qty_sent"] or 0)
        принято = float(r["qty_accepted"]) if r["qty_accepted"] is not None else None
        разница = None if принято is None else round(принято - отправлено, 3)
        состояние = ("расхождение" if разница not in (None, 0)
                     else "принято" if принято is not None else "в пути")
        итог[состояние] += 1
        в_пути_часов = (None if принято is not None
                        else round((now - r["doc_date"]).total_seconds() / 3600))
        передачи.append({
            "from_station": r["from_station"], "to_station": r["to_station"],
            "number": r["number"], "doc_date": r["doc_date"], "doc_id": r["doc_id"],
            "from_place": r["from_place"], "comment": r["comment"],
            "positions": r["positions"],
            "qty_sent": round(отправлено, 3), "qty_accepted": принято,
            "difference": разница, "state": состояние,
            "accepted_at": r["accepted_at"], "hours_in_transit": в_пути_часов,
            # Судьба заготовки приёмки у получателя: доставлена ли она агенту.
            # «В пути» при недоставленном задании — это не потерянный товар, а
            # молчащая станция, и лечится это разными способами.
            "task_delivered": bool(r["task_delivered_at"]),
            "task_acked": bool(r["task_acked_at"]),
            "packet_uuid": r["packet_uuid"],
        })

    return {
        "transfers": передачи,
        "total": len(передачи),
        "by_state": итог,
        # Дольше суток в пути — повод спросить: столько занимает доставка между
        # соседними АЗС, а не приём товара с машины.
        "stuck": [t for t in передачи
                  if t["state"] == "в пути" and (t["hours_in_transit"] or 0) >= 24],
    }


@router.get("/station-doc")
async def store_station_doc(
    packet_uuid: str = Query(..., description="UUID пакета, в котором приехал документ"),
    index: int = Query(..., ge=0, description="номер документа внутри пакета"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Первичный документ станции целиком: шапка, стороны, строки, основание.

    Реестр отвечает «что было», карточка — «на основании чего и с чем именно».
    Строки берутся из сырого пакета: разбор в документы Ledger идёт своим
    путём, но предъявлять при разборе полётов нужно то, что прислала станция.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    access = await resolve_document_access(user, db, cid)
    пакет = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == cid,
        EdgePacket.packet_uuid == packet_uuid))).scalar_one_or_none()
    if пакет is None or not _station_allowed(access, пакет.station_id):
        raise HTTPException(404, "Документ не найден")
    документы = (пакет.payload or {}).get("Документы") or []
    if index >= len(документы):
        raise HTTPException(404, "Документ не найден в пакете")
    d = документы[index]
    if (not isinstance(d, dict)
            or str(d.get("Тип") or "") not in STATION_DOC_ALLOWED_KINDS):
        raise HTTPException(404, "Документ не найден")
    sanitized = sanitize_edge_document(d, trusted_station_packet=True)
    if sanitized["pure_fuel"]:
        raise HTTPException(404, "Документ не найден")

    строки = []
    for row in sanitized["lines"]:
        строки.append({
            "name": row.get("Наименование") or row.get("Номенклатура") or "",
            "barcode": row.get("ШтрихКод"),
            "qty": float(row.get("Количество") or 0),
            "qty_expected": (float(row["КоличествоЗаявлено"])
                             if row.get("КоличествоЗаявлено") is not None else None),
            "qty_book": (float(row["КоличествоУчет"])
                         if row.get("КоличествоУчет") is not None else None),
            "price": float(row.get("Цена") or 0) or None,
            "amount": float(row.get("Сумма") or 0) or None,
            "vat_rate": row.get("СтавкаНДС"),
            "unit": row.get("Единица"),
            "marks": len(row.get("КодыМаркировки") or []),
        })

    meta = (await db.execute(select(StoreDocMeta).where(
        StoreDocMeta.company_id == cid,
        StoreDocMeta.doc_ref == f"station:{packet_uuid}:{index}"))).scalar_one_or_none()
    company = await db.get(Company, cid)

    return {
        "packet_uuid": packet_uuid,
        "index": index,
        "station_id": пакет.station_id,
        # Реквизиты для печатной формы: без организации бумага не документ.
        "org": {"name": company.name if company else "",
                "inn": (company.customization or {}).get("inn") if company else None},
        "responsible_from": meta.responsible_from if meta else None,
        "responsible_to": meta.responsible_to if meta else None,
        "meta_note": meta.note if meta else None,
        "status": meta.status if meta else "принят",
        "reg_number": meta.reg_number if meta else None,
        "registered_at": meta.registered_at if meta else None,
        "statuses": list(DOC_STATUSES),
        "kind": d.get("Тип"),
        "label": STATION_DOC_KINDS.get(d.get("Тип"), d.get("Тип")),
        "number": d.get("Номер"),
        "doc_date": d.get("Дата"),
        "place_from": d.get("Склад") or d.get("СкладОтправитель"),
        "place_to": d.get("СкладПолучатель"),
        "counterparty": d.get("Контрагент"),
        "contract": d.get("ДоговорКонтрагента"),
        "incoming_number": d.get("НомерВходящегоДокумента"),
        "reason": d.get("Причина") or d.get("Комментарий"),
        "author": d.get("Автор"),
        "responsible": d.get("Ответственный") or d.get("МОЛ"),
        "basis": d.get("Основание"),
        "source_uuid": d.get("ИсточникUUID"),
        "amount": float(sanitized["amount"]),
        "vat_amount": (None if sanitized["vat_amount"] is None
                       else float(sanitized["vat_amount"])),
        "accounting_status": (
            "needs_review" if sanitized["quarantined"] else "ready"),
        "classification_error": sanitized["reason"],
        "shift_number": пакет.shift_number,
        "received_at": пакет.received_at,
        "lines": строки,
        "services": [
            {
                "name": row.get("Наименование") or "",
                "amount": float(row.get("Сумма") or 0),
                "vat_rate": row.get("СтавкаНДС"),
                "vat_amount": (float(row["СуммаНДС"])
                               if row.get("СуммаНДС") is not None else None),
            }
            for row in sanitized["services"]
        ],
        "doc_ref": f"station:{packet_uuid}:{index}",
    }


# Что с документом сделали в центре. «Принят» ставится сразу: документ уже
# существует, отрицать это бессмысленно. Дальше — работа человека.
DOC_STATUSES = ("принят", "проверен", "спорный", "закрыт")


class DocMetaIn(BaseModel):
    responsible_from: str | None = None
    responsible_to: str | None = None
    note: str | None = None
    status: str | None = None
    # Присвоить регистрационный номер центра, если его ещё нет. Имя не
    # `register`: так называется метод самой BaseModel, и pydantic ругается.
    assign_number: bool = False


@router.put("/doc-meta")
async def store_doc_meta_save(
    doc_ref: str = Query(...),
    body: DocMetaIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Записать стороны документа: кто сдал имущество и кто принял.

    Пишем в отдельную таблицу, а не в пакет: сырьё станции по канону проекта
    неизменно, и дописывать в него центр не вправе — иначе через месяц никто не
    скажет, что прислала станция, а что дорисовали в офисе.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    if doc_ref.startswith("projection:"):
        raise HTTPException(409, "Метаданные проекции изменяются только через документный API")
    from app.routers.store_documents_router import authorize_legacy_document_ref
    _, document = await authorize_legacy_document_ref(
        db, user, cid, doc_ref, write=True)
    row = (await db.execute(select(StoreDocMeta).where(
        StoreDocMeta.company_id == cid,
        StoreDocMeta.doc_ref == doc_ref))).scalar_one_or_none()
    if row is None:
        row = StoreDocMeta(company_id=cid, doc_ref=doc_ref)
        db.add(row)
    if document is not None:
        row.record_id = document.id
        row.document_id = document.document_id
        row.revision = document.revision
    if body.responsible_from is not None:
        row.responsible_from = body.responsible_from.strip() or None
    if body.responsible_to is not None:
        row.responsible_to = body.responsible_to.strip() or None
    if body.note is not None:
        row.note = body.note.strip() or None
    if body.status is not None:
        if body.status not in DOC_STATUSES:
            raise HTTPException(400, f"Неизвестный статус: {body.status}")
        row.status = body.status
    if body.assign_number and not row.reg_number:
        # Номер сквозной по компании и году: год в номере отвечает на вопрос
        # «за какой период искать», а не заставляет помнить нумерацию сети.
        год = datetime.now(timezone.utc).year
        последний = (await db.execute(text("""
            SELECT max(NULLIF(regexp_replace(reg_number, '^.*-', ''), '')::int)
            FROM store_doc_meta
            WHERE company_id = :cid AND reg_number LIKE :маска
        """), {"cid": cid, "маска": f"Д-{год}-%"})).scalar()
        row.reg_number = f"Д-{год}-{(последний or 0) + 1:05d}"
        row.registered_at = datetime.now(timezone.utc)
    row.updated_by = user.id
    await db.commit()
    return {"ok": True, "doc_ref": doc_ref,
            "responsible_from": row.responsible_from,
            "responsible_to": row.responsible_to, "note": row.note,
            "status": row.status, "reg_number": row.reg_number,
            "registered_at": row.registered_at}


class DocFileIn(BaseModel):
    doc_ref: str
    kind: str = "накладная"
    note: str | None = None


@router.get("/doc-files")
async def store_doc_files(
    doc_ref: str = Query(..., description="ссылка на документ: receipt:<id> | station:<uuid>:<i>"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Образы, приложенные к документу: накладная, УПД, акт, опись, фото."""
    cid: uuid.UUID = await scope_company_id(user, db)
    from app.routers.store_documents_router import authorize_legacy_document_ref
    await authorize_legacy_document_ref(db, user, cid, doc_ref, write=False)
    rows = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.company_id == cid, StoreDocFile.doc_ref == doc_ref,
        StoreDocFile.tombstoned_at.is_(None),
    ).order_by(StoreDocFile.uploaded_at.desc()))).scalars().all()
    return {"files": [{
        "id": str(r.id), "kind": r.kind, "file_id": str(r.file_id),
        "file_name": r.file_name, "mime": r.mime, "size_bytes": r.size_bytes,
        "note": r.note, "uploaded_at": r.uploaded_at,
        "url": f"/api/files/{r.file_id}",
    } for r in rows], "total": len(rows)}


@router.post("/doc-files", status_code=201)
async def store_doc_file_upload(
    doc_ref: str = Query(...),
    kind: str = Query("накладная"),
    note: str | None = Query(None),
    station_id: int | None = Query(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Приложить образ первичного документа.

    Учётная запись документа и его бумажное основание — разные вещи: приёмка
    может быть проведена, а накладной поставщика в системе нет, и предъявлять
    при проверке нечего. Файл ложится в общее хранилище пространства, потому
    что второй способ хранить одно и то же расходится с первым сразу.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    if doc_ref.startswith("projection:"):
        raise HTTPException(409, "Файлы проекции добавляются только через документный API")
    from app.routers.store_documents_router import authorize_legacy_document_ref
    _, document = await authorize_legacy_document_ref(db, user, cid, doc_ref, write=True)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "Файл больше 25 МБ — приложите скан меньшего разрешения")
    checksum = hashlib.sha256(content).hexdigest()
    if document is not None:
        await db.execute(text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
        ), {"scope_key": f"store-document-file:{cid}:{document.id}"})
        existing = (await db.execute(select(StoreDocFile).where(
            StoreDocFile.company_id == cid,
            StoreDocFile.record_id == document.id,
            StoreDocFile.revision == document.revision,
            StoreDocFile.role == kind,
            StoreDocFile.sha256 == checksum,
        ))).scalar_one_or_none()
        if existing is not None:
            return {"ok": True, "id": str(existing.id),
                    "file_id": str(existing.file_id), "created": False,
                    "url": f"/api/files/{existing.file_id}"}

    from app.services import ops_terms
    file_id = await ops_terms.store_file(db, cid, file.filename, file.content_type, content)
    row = StoreDocFile(
        company_id=cid, doc_ref=doc_ref,
        record_id=document.id if document else None,
        document_id=document.document_id if document else None,
        station_id=document.station_id if document else None, kind=kind, role=kind,
        sha256=checksum,
        revision=document.revision if document else 1,
        file_id=file_id, file_name=file.filename or "документ",
        mime=file.content_type, size_bytes=len(content), note=note,
        uploaded_by=user.id, author_id=user.id,
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "id": str(row.id), "file_id": str(file_id), "created": True,
            "url": f"/api/files/{file_id}"}


@router.get("/doc-files/archive")
async def store_doc_files_archive(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    station_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить образы пачкой: zip с файлами и описью.

    Первичка хранится пять лет (ФЗ-402), и запрашивают её не по одному
    документу, а за период: налоговая просит подтверждения к декларации,
    аудитор — к месяцу. Скачивать по одному файлу через интерфейс — это часы.

    В архив кладётся опись CSV: без неё пачка из ста сканов не отвечает на
    вопрос, к какому документу относится каждый.
    """
    import csv
    import io as _io
    import os
    import zipfile
    from pathlib import Path

    from fastapi.responses import StreamingResponse

    from app.models import SourceFile

    cid: uuid.UUID = await scope_company_id(user, db)
    from app.routers.store_documents_router import resolve_document_access
    access = await resolve_document_access(user, db, cid)
    if not access.network:
        raise HTTPException(403, "Архив первички доступен только центру")
    условия = [StoreDocFile.company_id == cid]
    условия.append(StoreDocFile.tombstoned_at.is_(None))
    if station_id is not None:
        условия.append(StoreDocFile.station_id == station_id)
    if date_from:
        условия.append(StoreDocFile.uploaded_at >= datetime.combine(
            date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
    if date_to:
        условия.append(StoreDocFile.uploaded_at < datetime.combine(
            date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))

    rows = (await db.execute(select(StoreDocFile).where(*условия)
                             .order_by(StoreDocFile.uploaded_at))).scalars().all()
    if not rows:
        raise HTTPException(404, "За период образов нет")

    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    буфер = _io.BytesIO()
    опись = _io.StringIO()
    писатель = csv.writer(опись, delimiter=";")
    писатель.writerow(["Файл", "Роль", "Документ", "АЗС", "Загружен", "Размер, байт", "Примечание"])

    with zipfile.ZipFile(буфер, "w", zipfile.ZIP_DEFLATED) as архив:
        for i, r in enumerate(rows, 1):
            путь = (await db.execute(select(SourceFile.storage_path).where(
                SourceFile.id == r.file_id))).scalar_one_or_none()
            имя = f"{i:04d}_{r.kind}_{r.file_name}".replace("/", "_")
            писатель.writerow([имя, r.kind, r.doc_ref, r.station_id or "",
                               r.uploaded_at.strftime("%d.%m.%Y %H:%M"),
                               r.size_bytes, r.note or ""])
            файл = Path(путь) if путь else (upload_dir / str(r.file_id))
            if файл.exists():
                архив.write(файл, имя)
            else:
                # Запись есть, файла нет: молчать нельзя — при проверке это
                # обнаружится, и лучше знать заранее.
                архив.writestr(f"{имя}.ОТСУТСТВУЕТ.txt",
                               "Файл не найден в хранилище\n")
        архив.writestr("опись.csv", "\ufeff" + опись.getvalue())

    буфер.seek(0)
    имя_архива = f"образы-{date_from or 'все'}-{date_to or 'все'}.zip"
    return StreamingResponse(
        буфер, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="documents.zip"',
                 "X-Archive-Name": имя_архива, "X-Files-Count": str(len(rows))})


@router.get("/doc-files/summary")
async def store_doc_files_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сколько образов хранится, каких и с какого времени.

    Первичка обязана храниться пять лет, поэтому в блоке хранения она стоит
    отдельно от сырья станции: сырьё прореживают, образы — нет.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    from app.routers.store_documents_router import resolve_document_access
    access = await resolve_document_access(user, db, cid)
    if not access.network:
        raise HTTPException(403, "Сводка первички доступна только центру")
    виды = [dict(r) for r in (await db.execute(text("""
        SELECT kind, count(*) AS files, coalesce(sum(size_bytes), 0) AS bytes,
               min(uploaded_at) AS oldest, max(uploaded_at) AS newest
        FROM store_doc_files WHERE company_id = :cid
          AND tombstoned_at IS NULL
        GROUP BY kind ORDER BY count(*) DESC
    """), {"cid": cid})).mappings().all()]
    итог = (await db.execute(text("""
        SELECT count(*) AS files, coalesce(sum(size_bytes), 0) AS bytes,
               count(DISTINCT doc_ref) AS docs, min(uploaded_at) AS oldest
        FROM store_doc_files WHERE company_id = :cid
          AND tombstoned_at IS NULL
    """), {"cid": cid})).mappings().first()
    return {"kinds": виды, "total": dict(итог) if итог else {},
            "retention_years": 5}


@router.delete("/doc-files/{file_row_id}")
async def store_doc_file_delete(
    file_row_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отвязать образ от документа.

    Сам файл в хранилище остаётся: он мог быть приложен к другому документу —
    один PDF со счётом и накладной внутри дело обычное.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.id == file_row_id, StoreDocFile.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Образ не найден")
    if row.record_id is not None:
        raise HTTPException(409, "Файл проекции удаляется только логическим tombstone")
    from app.routers.store_documents_router import authorize_legacy_document_ref
    await authorize_legacy_document_ref(db, user, cid, row.doc_ref, write=True)
    if row.tombstoned_at is None:
        row.tombstoned_at = datetime.now(timezone.utc)
        row.tombstoned_by = user.id
        row.tombstone_reason = "Удалено через совместимый API"
    await db.commit()
    return {"ok": True, "tombstoned": True}


@router.get("/marking/codes")
async def store_marking_codes(
    station_id: int | None = Query(None, description="код АЗС; пусто — все"),
    q: str | None = Query(None, description="поиск по коду, GTIN или товару"),
    status: str | None = Query(None, description="в обороте | выбыл"),
    limit: int = Query(1000, ge=1, le=50000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Коды маркировки, которыми мы владеем: откуда пришёл каждый и куда ушёл.

    Наша сторона правды. Приход берётся из приёмок (сканы DataMatrix на
    станции и коды из УПД), выбытие — из документов станции, где код указан:
    списание, возврат поставщику, перемещение. Продажа сюда не попадает: её
    закрывает касса через ОФД, и дублировать это выбытие нельзя.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    p = {"cid": cid, "lim": limit}
    where_station = ""
    if station_id is not None:
        where_station = " AND r.station_id = :st"
        p["st"] = station_id

    приход = f"""
        SELECT DISTINCT ON (код)
               код, r.station_id, r.doc_date AS at, r.number AS doc,
               l->>'name' AS name, l->>'barcode' AS barcode,
               CASE WHEN l->'mark_codes' ? код THEN 'скан' ELSE 'УПД' END AS источник
        FROM store_receipts r,
             LATERAL jsonb_array_elements(r.lines) l,
             LATERAL jsonb_array_elements_text(
                 coalesce(l->'mark_codes', '[]'::jsonb)
                 || coalesce(l->'upd_codes', '[]'::jsonb)) AS код
        WHERE r.company_id = :cid{where_station}
        ORDER BY код, r.doc_date DESC
    """

    # Выбытие ищем в сыром пакете станции: документ списания несёт коды в тех
    # же строках, и отдельного реестра для этого заводить не нужно.
    выбытие = """
        SELECT DISTINCT ON (код)
               код, p.station_id, p.received_at AS at,
               d->>'Тип' AS kind, d->>'Номер' AS doc
        FROM edge_packets p,
             LATERAL jsonb_array_elements(coalesce(p.payload->'Документы', '[]'::jsonb)) d,
             LATERAL jsonb_array_elements(coalesce(d->'Товары', '[]'::jsonb)) t,
             LATERAL jsonb_array_elements_text(
                 coalesce(t->'КодыМаркировки', '[]'::jsonb)) AS код
        WHERE p.company_id = :cid
          AND d->>'Тип' IN ('writeoff', 'return_supplier', 'transfer', 'production_release')
        ORDER BY код, p.received_at DESC
    """

    rows = [dict(r) for r in (await db.execute(text(f"""
        WITH пришли AS ({приход}), ушли AS ({выбытие})
        SELECT пришли.код, пришли.station_id, пришли.name, пришли.barcode,
               пришли.at AS received_at, пришли.doc AS receipt_doc, пришли.источник,
               ушли.at AS gone_at, ушли.kind AS gone_kind, ушли.doc AS gone_doc
        FROM пришли LEFT JOIN ушли USING (код)
        ORDER BY пришли.at DESC NULLS LAST
        LIMIT :lim
    """), p)).mappings().all()]

    for r in rows:
        r["status"] = "выбыл" if r["gone_at"] else "в обороте"
        # GTIN лежит в самом коде: AI 01 — первые 16 символов «01» + 14 цифр.
        код = r["код"] or ""
        r["gtin"] = код[2:16] if код.startswith("01") and len(код) >= 16 else None
    if status:
        rows = [r for r in rows if r["status"] == status]
    if q:
        игла = q.strip().lower()
        rows = [r for r in rows
                if игла in (r["код"] or "").lower()
                or игла in (r["name"] or "").lower()
                or игла in (r["gtin"] or "")]

    итог = {"в обороте": 0, "выбыл": 0}
    for r in rows:
        итог[r["status"]] += 1
    return {"total": len(rows), "by_status": итог, "codes": rows,
            "limit": limit, "truncated": len(rows) >= limit}


# Системы маркировки и их реквизиты. Схема живёт на сервере, а форма ввода
# рисуется по ней: добавить систему — значит дописать сюда запись, а не
# править экран. Поле с secret=True шифруется и наружу уходит только маской.
MARKING_SYSTEMS: list[dict] = [
    {
        "key": "gismt", "name": "ГИС МТ (Честный ЗНАК)",
        "gives": "Статус и история кода, остатки за участником, ввод и вывод из оборота, приёмка и отгрузка",
        "needs": "УКЭП организации, договор с ЦРПТ, доступ к True API",
        "limits": "Токен живёт ≤ 10 часов; 50 запросов в секунду; до 30 000 кодов и 30 МБ в документе",
        "fields": [
            {"key": "base_url", "label": "Адрес API", "type": "url", "required": True,
             "default": "https://markirovka.crpt.ru/api/v3/true-api",
             "help": "Боевой контур ЦРПТ. Для проверки интеграции есть песочница demo.crpt.tech."},
            {"key": "inn", "label": "ИНН участника оборота", "type": "text", "required": True,
             "help": "ИНН организации, от имени которой работаем в ГИС МТ."},
            {"key": "product_groups", "label": "Товарные группы", "type": "text",
             "placeholder": "tobacco, beer, water",
             "help": "Группы, по которым оформлен доступ: у каждой свой набор методов."},
            {"key": "cert_thumbprint", "label": "Отпечаток сертификата УКЭП", "type": "text",
             "help": "Каким сертификатом подписываем запрос авторизации (auth/key → auth/simpleSignIn)."},
            {"key": "sign_service_url", "label": "Сервис подписи", "type": "url",
             "help": "Адрес крипто-сервиса, если подпись выполняется не на этом сервере "
                     "(КриптоПро DSS, сервис оператора ЭДО). Пусто — подписываем локально."},
            {"key": "token", "label": "Готовый токен (если выдан)", "type": "password", "secret": True,
             "help": "Обычно не нужен: токен берётся по УКЭП и живёт 10 часов. Заполняется, "
                     "только если доступ выдан статическим ключом."},
        ],
    },
    {
        "key": "edo", "name": "Оператор ЭДО",
        "gives": "Входящие УПД с кодами маркировки от поставщика и подтверждение приёмки",
        "needs": "Договор с оператором ЭДО либо ЭДО Лайт внутри ГИС МТ",
        "limits": "УПД приходит XML 5.03; подпись — УКЭП организации",
        "fields": [
            {"key": "provider", "label": "Оператор", "type": "text",
             "placeholder": "СБИС / Диадок / Такском / ЭДО Лайт"},
            {"key": "base_url", "label": "Адрес API", "type": "url"},
            {"key": "login", "label": "Логин", "type": "text"},
            {"key": "password", "label": "Пароль", "type": "password", "secret": True},
            {"key": "api_key", "label": "Ключ API", "type": "password", "secret": True},
        ],
    },
    {
        "key": "ofd", "name": "ОФД",
        "gives": "Чеки с кодами маркировки: подтверждение выбытия продажей, которое мы не заявляем сами",
        "needs": "Договор с ОФД и ключ к его API",
        "limits": "Код есть только в электронном чеке, в печатном его нет",
        "fields": [
            {"key": "provider", "label": "Оператор", "type": "text",
             "placeholder": "ОФД.ру / Платформа ОФД / Такском"},
            {"key": "base_url", "label": "Адрес API", "type": "url",
             "default": "https://ofd-api.ofd.ru"},
            {"key": "inn", "label": "ИНН", "type": "text"},
            {"key": "api_key", "label": "Ключ API", "type": "password", "secret": True},
        ],
    },
    {
        "key": "nk", "name": "Национальный каталог",
        "gives": "Карточки товаров по GTIN: наименование, упаковка, признак маркируемости",
        "needs": "Тот же доступ, что к ГИС МТ",
        "limits": "Заполняет справочник, но не заменяет наш учёт",
        "fields": [
            {"key": "base_url", "label": "Адрес API", "type": "url",
             "default": "https://апи.национальный-каталог.рф"},
            {"key": "api_key", "label": "Ключ API", "type": "password", "secret": True},
        ],
    },
    {
        "key": "egais", "name": "ЕГАИС",
        "gives": "Пиво и слабый алкоголь: приёмка ТТН и журнал розничных продаж",
        "needs": "УТМ на станции и ключ РСА (JaCarta) в её кассовой машине",
        "limits": "УТМ живёт на станции — центр обращается к нему через overlay",
        "fields": [
            {"key": "utm_url", "label": "Адрес УТМ", "type": "url",
             "placeholder": "http://127.0.0.1:8080"},
            {"key": "fsrar_id", "label": "FSRAR ID", "type": "text"},
        ],
    },
    {
        "key": "mercury", "name": "ФГИС «Меркурий» (ВетИС)",
        "gives": "Ветеринарные документы на молочную продукцию",
        "needs": "Учётная запись ВетИС и ключ API",
        "limits": "Нужна только при появлении молочки в ассортименте",
        "fields": [
            {"key": "base_url", "label": "Адрес API", "type": "url"},
            {"key": "issuer_id", "label": "Issuer ID", "type": "text"},
            {"key": "login", "label": "Логин", "type": "text"},
            {"key": "password", "label": "Пароль", "type": "password", "secret": True},
            {"key": "api_key", "label": "Ключ API", "type": "password", "secret": True},
        ],
    },
    {
        "key": "local_module", "name": "Локальный модуль ЧЗ на станциях",
        "gives": "Разрешение на продажу маркированного без интернета — требование ПП РФ №1944",
        "needs": "Модуль установлен на кассовой машине; агент знает его адрес",
        "limits": "База блокировок обновляется, когда у станции есть канал",
        "fields": [
            {"key": "default_url", "label": "Адрес модуля по умолчанию", "type": "url",
             "placeholder": "http://127.0.0.1:5995/api/v1/status",
             "help": "Справочное значение для настройки станций: агент берёт адрес из своего "
                     "конфига (mark_module_url) — до localhost станции центр не дотянется."},
        ],
    },
]

MARKING_BY_KEY = {с["key"]: с for с in MARKING_SYSTEMS}


class MarkingIntegrationIn(BaseModel):
    enabled: bool | None = None
    settings: dict = {}
    # Пустая строка в секрете означает «не менять»: форма не знает значения и
    # не должна его стирать простым сохранением. Явная очистка — clear_secrets.
    secrets: dict = {}
    clear_secrets: list[str] = []


async def _интеграции(db: AsyncSession, cid: uuid.UUID) -> dict[str, MarkingIntegration]:
    rows = (await db.execute(select(MarkingIntegration).where(
        MarkingIntegration.company_id == cid))).scalars().all()
    return {r.system: r for r in rows}


@router.get("/marking/integrations")
async def store_marking_integrations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Чем мы подключены к внешним системам маркировки и что каждая даёт.

    Экран честности: пока доступа нет, ГИС МТ ничего не расскажет, и цифры
    раздела — наш собственный учёт. Реквизиты вводятся здесь же; секреты
    возвращаются маской, расшифровка живёт только на сервере.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    сохранённые = await _интеграции(db, cid)

    agents = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == cid).order_by(EdgeAgent.station_id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    модули = []
    for a in agents:
        м = ((a.payload or {}).get("mark_module") or {})
        silence = int((now - a.last_seen).total_seconds()) if a.last_seen else None
        модули.append({
            "station_id": a.station_id,
            "station_online": silence is not None and silence <= STATION_OFFLINE_AFTER,
            "configured": bool(м),
            "ok": bool(м.get("ok")),
            "status": м.get("status"),
            "version": м.get("version"),
            "checked_at": м.get("checked_at"),
            "error": м.get("error"),
            "url": м.get("url"),
        })

    маркированных = (await db.execute(text(
        "SELECT count(*) FROM edge.item WHERE marked = true"))).scalar() or 0

    системы = []
    for схема in MARKING_SYSTEMS:
        строка = сохранённые.get(схема["key"])
        значения = dict((строка.settings or {}) if строка else {})
        секреты = (строка.secrets or {}) if строка else {}
        поля = []
        for f in схема["fields"]:
            поле = dict(f)
            if f.get("secret"):
                # Наружу отдаём факт наличия и хвост, а не сам секрет.
                поле["filled"] = bool(секреты.get(f["key"]))
                поле["value"] = ""
                поле["masked"] = "••••" if секреты.get(f["key"]) else ""
            else:
                поле["value"] = значения.get(f["key"], f.get("default", ""))
            поля.append(поле)

        подключено = bool(строка and строка.enabled)
        if схема["key"] == "local_module":
            # Тут «подключено» решает не форма, а станция: модуль либо
            # отвечает кассе, либо нет, и настройка центра этого не меняет.
            подключено = any(m["ok"] for m in модули)
        системы.append({
            "key": схема["key"], "name": схема["name"],
            "gives": схема["gives"], "needs": схема["needs"], "limits": схема["limits"],
            "connected": подключено,
            "enabled": bool(строка and строка.enabled),
            "fields": поля,
            "last_check_at": строка.last_check_at if строка else None,
            "last_check_ok": строка.last_check_ok if строка else None,
            "last_check_note": строка.last_check_note if строка else None,
            "updated_at": строка.updated_at if строка else None,
        })

    справочник = await _mark_groups(db)
    без_группы = await _marked_without_group(db)
    return {
        "systems": системы,
        "modules": модули,
        "marked_skus": int(маркированных),
        # Плоский словарь оставлен ради совместимости с экраном; разбор по
        # группам с числами — в `group_stats`.
        "groups": {г["code"]: г["name"] for г in справочник},
        "group_stats": справочник,
        "unassigned": без_группы,
    }


@router.put("/marking/integrations/{system}")
async def store_marking_integration_save(
    system: str,
    body: MarkingIntegrationIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить реквизиты подключения.

    Секреты шифруются Fernet тем же ключом, что пароли подключений к 1С.
    Пустая строка в секретном поле означает «оставить как было»: форма не
    знает текущего значения и не должна стирать ключ обычным сохранением.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    схема = MARKING_BY_KEY.get(system)
    if схема is None:
        raise HTTPException(404, "Неизвестная система")
    if not user.is_superadmin:
        m = (await db.execute(select(UserCompany).where(
            UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if m is None or m.role != "admin":
            raise HTTPException(403, "Реквизиты подключения вводит администратор компании")

    строка = (await db.execute(select(MarkingIntegration).where(
        MarkingIntegration.company_id == cid,
        MarkingIntegration.system == system))).scalar_one_or_none()
    if строка is None:
        строка = MarkingIntegration(company_id=cid, system=system, settings={}, secrets={})
        db.add(строка)

    открытые = {f["key"] for f in схема["fields"] if not f.get("secret")}
    секретные = {f["key"] for f in схема["fields"] if f.get("secret")}

    настройки = dict(строка.settings or {})
    for k, v in (body.settings or {}).items():
        if k in открытые:
            настройки[k] = ("" if v is None else str(v)).strip()
    строка.settings = настройки

    секреты = dict(строка.secrets or {})
    for k, v in (body.secrets or {}).items():
        if k not in секретные:
            continue
        значение = ("" if v is None else str(v)).strip()
        if значение:
            секреты[k] = encrypt_password(значение)
    for k in body.clear_secrets or []:
        секреты.pop(k, None)
    строка.secrets = секреты

    if body.enabled is not None:
        строка.enabled = bool(body.enabled)
    строка.updated_by = user.id
    await db.commit()
    return {"ok": True, "system": system, "enabled": строка.enabled}


@router.post("/marking/integrations/{system}/check")
async def store_marking_integration_check(
    system: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проверить, отвечает ли система по заданному адресу.

    Это проверка связи, а не полномочий: без УКЭП ГИС МТ всё равно не пустит
    дальше авторизации, и делать вид, что интеграция готова, нельзя. Ответ
    сервера (пусть даже 401) доказывает ровно одно — адрес верный и канал есть.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    схема = MARKING_BY_KEY.get(system)
    if схема is None:
        raise HTTPException(404, "Неизвестная система")

    строка = (await db.execute(select(MarkingIntegration).where(
        MarkingIntegration.company_id == cid,
        MarkingIntegration.system == system))).scalar_one_or_none()
    настройки = (строка.settings or {}) if строка else {}
    адрес = (настройки.get("base_url") or настройки.get("utm_url")
             or настройки.get("default_url") or "").strip()
    if not адрес:
        raise HTTPException(400, "Адрес системы не задан")

    ok, заметка = False, ""
    try:
        async with httpx.AsyncClient(timeout=10, verify=True) as client:
            r = await client.get(адрес)
        ok = r.status_code < 500
        заметка = f"HTTP {r.status_code}"
        if r.status_code in (401, 403):
            заметка += " — адрес отвечает, но доступ не оформлен"
    except Exception as exc:  # noqa: BLE001
        заметка = str(exc)[:400]

    if строка is None:
        строка = MarkingIntegration(company_id=cid, system=system, settings={}, secrets={})
        db.add(строка)
    строка.last_check_at = datetime.now(timezone.utc)
    строка.last_check_ok = ok
    строка.last_check_note = заметка[:500]
    await db.commit()
    return {"ok": ok, "note": заметка, "checked_at": строка.last_check_at}


@router.get("/agent-versions")
async def store_agent_versions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Парк версий агента: что реально стоит на станциях и кто отстал.

    Текущей считается версия, которая РАБОТАЕТ в парке, — максимальная из
    версий живых агентов. Ручное объявление убрано (решение МАГа 31.08.2026):
    оно устаревало на следующий же день после выкатки, и станция писала в
    журнал «центр ожидает другую версию» каждую минуту, хотя расхождение
    ничему не мешает — обмен и рабочее место работают на любой версии.

    Обновление агента остаётся осознанной операцией с окном и откатом: экран
    отвечает на вопрос «кого пора обновить», а выкат выполняет деплой.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    company = await db.get(Company, cid)
    желаемая = await edge_router.desired_version(db, company)

    rows = (await db.execute(
        select(EdgeAgent).where(EdgeAgent.company_id == cid).order_by(EdgeAgent.station_id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    stations = []
    versions: dict[str, int] = {}
    for r in rows:
        silence = int((now - r.last_seen).total_seconds()) if r.last_seen else None
        versions[r.version or "неизвестна"] = versions.get(r.version or "неизвестна", 0) + 1
        stations.append({
            "station_id": r.station_id,
            "version": r.version,
            # Отставшей считается станция НИЖЕ парка, а не «любая другая»:
            # та, что первой получила новую сборку, отставшей не является.
            "version_ok": not r.version or (
                edge_router._номер_версии(r.version)
                >= edge_router._номер_версии(желаемая)),
            "state": _station_state(silence),
            "silence_seconds": silence,
            "last_seen": r.last_seen,
            "first_seen": r.first_seen,
        })
    return {
        "desired_version": желаемая,
        # Версия больше не объявляется руками — она считается по парку.
        # Поле оставлено, чтобы экран прежней сборки не падал.
        "declared": False,
        "fallback_version": edge_router.DESIRED_AGENT_VERSION,
        "total": len(stations),
        "outdated": sum(1 for s in stations if s["version"] and not s["version_ok"]),
        "versions": [{"version": v, "stations": n}
                     for v, n in sorted(versions.items(), key=lambda x: -x[1])],
        "stations": stations,
    }


def _downlink_state(r: EdgeDownlink) -> str:
    if r.cancelled_at:
        return "отменено"
    if r.acked_at:
        return "применено"
    if r.delivered_at:
        return "доставлено"
    return "ждёт станции"


@router.get("/downlink")
async def store_downlink(
    station_id: int | None = Query(None, description="код АЗС; пусто — все"),
    state: str | None = Query(None, description="ждёт станции | доставлено | применено | отменено"),
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Очередь заданий центра станциям: НСИ, цены, заготовки приёмки, команды.

    Станция за CGNAT и забирает задания сама, поэтому «отправлено» здесь не
    значит «доехало»: между созданием и подтверждением может пройти сколько
    угодно, и зависшее задание видно только отсюда.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    q = select(EdgeDownlink).where(EdgeDownlink.company_id == cid)
    if station_id is not None:
        q = q.where(EdgeDownlink.station_id == station_id)
    rows = (await db.execute(
        q.order_by(EdgeDownlink.created_at.desc()).limit(limit))).scalars().all()

    tasks = [{
        "id": str(r.id), "station_id": r.station_id, "kind": r.kind,
        "label": PACKET_KIND_LABEL.get(r.kind, r.kind),
        "note": r.note, "state": _downlink_state(r),
        "created_at": r.created_at, "delivered_at": r.delivered_at,
        "acked_at": r.acked_at, "cancelled_at": r.cancelled_at,
    } for r in rows]
    if state:
        tasks = [t for t in tasks if t["state"] == state]

    свод = {"ждёт станции": 0, "доставлено": 0, "применено": 0, "отменено": 0}
    for r in rows:
        свод[_downlink_state(r)] += 1
    return {"total": len(rows), "by_state": свод, "tasks": tasks}


@router.post("/downlink/{task_id}/resend")
async def store_downlink_resend(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить задание станции заново.

    Снимаем отметки доставки и применения — станция заберёт его следующим
    тактом. Повтор безопасен: приёмная сторона идемпотентна, и то же задание
    уже приходило дважды при обрыве связи до подтверждения.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.id == task_id, EdgeDownlink.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Задание не найдено")
    row.delivered_at = None
    row.acked_at = None
    row.cancelled_at = None
    row.cancelled_by = None
    await db.commit()
    return {"ok": True, "state": _downlink_state(row)}


@router.post("/downlink/resend-stuck")
async def store_downlink_resend_stuck(
    station_id: int | None = Query(None, description="код АЗС; пусто — все станции"),
    older_than_minutes: int = Query(30, ge=1, le=1440,
                                    description="сколько задание уже висит доставленным"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Переслать разом всё, что зависло между доставкой и подтверждением.

    Ночь 13.08.2026 на 208: канал лёг на девять часов, задания успели уйти
    станции, но подтверждения не вернулись. Разбирать такое поштучно —
    занятие на десятки нажатий, а ответ на вопрос «мы уверены, что дошло»
    нужен сразу.

    Берём только доставленные без подтверждения и старше порога: свежие
    трогать нельзя — станция могла забрать задание минуту назад и как раз его
    применять. Повтор безопасен, приёмная сторона идемпотентна.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    рубеж = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    условия = [
        EdgeDownlink.company_id == cid,
        EdgeDownlink.delivered_at.isnot(None),
        EdgeDownlink.delivered_at < рубеж,
        EdgeDownlink.acked_at.is_(None),
        EdgeDownlink.cancelled_at.is_(None),
    ]
    if station_id is not None:
        условия.append(EdgeDownlink.station_id == station_id)
    rows = (await db.execute(select(EdgeDownlink).where(*условия))).scalars().all()
    for row in rows:
        row.delivered_at = None
    await db.commit()
    return {"ok": True, "resent": len(rows),
            "stations": sorted({r.station_id for r in rows})}


@router.post("/downlink/{task_id}/cancel")
async def store_downlink_cancel(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Снять задание с очереди станции.

    Отмена не притворяется применением: у неё своё время и автор, и станция
    больше не получит это задание.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    row = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.id == task_id, EdgeDownlink.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Задание не найдено")
    if row.acked_at:
        raise HTTPException(409, "Станция уже применила задание — отменять нечего")
    row.cancelled_at = datetime.now(timezone.utc)
    row.cancelled_by = user.id
    await db.commit()
    return {"ok": True, "state": _downlink_state(row)}


class SameItemIn(BaseModel):
    """Две карточки — один товар: кассовая и та, что ведёт 1С."""
    alias_uuid: str
    canonical_uuid: str
    reason: str = "сверка: один товар в двух справочниках"


@router.post("/reconcile/same-item")
async def store_reconcile_same_item(
    body: SameItemIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Объявить, что касса и 1С зовут один товар разными карточками.

    Это не слияние справочника: обе карточки остаются живыми, потому что 1С
    ведёт свою и переименовать её мы не можем. Пара нужна сверке — иначе
    «Американо 200 мл» против «Американо 200 мл.» каждый день выглядит как
    расхождение, и критерий чистых дней не наберётся никогда.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    if body.alias_uuid == body.canonical_uuid:
        raise HTTPException(400, "Это одна и та же карточка")
    есть = (await db.execute(select(StoreItemAlias.id).where(
        StoreItemAlias.company_id == cid,
        StoreItemAlias.alias_uuid == body.alias_uuid))).scalar_one_or_none()
    if есть is not None:
        return {"ok": True, "already": True}
    db.add(StoreItemAlias(company_id=cid, alias_uuid=body.alias_uuid,
                          canonical_uuid=body.canonical_uuid,
                          reason=body.reason[:200], created_by=user.id))
    await db.commit()
    return {"ok": True}


@router.get("/network-overview")
async def store_network_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Вся сеть одним взглядом: где встала очередь, где справочник разошёлся.

    Ходить по тридцати рабочим местам не масштабируется, а «Состояние станций»
    отвечает про одну АЗС. Здесь по строке на станцию: связь, версия, очередь
    в обе стороны, свежесть данных, расхождение справочника и запас номеров —
    артикулов и кодов кассы.

    Строка отвечает на один вопрос: нужен ли человек этой станции сегодня.
    """
    cid = await scope_company_id(user, db)
    желаемая = await edge_router.desired_version(db, await db.get(Company, cid))

    агенты = (await db.execute(text("""
        SELECT a.station_id, a.version, a.last_seen, a.first_seen,
               a.queue_pending, a.queue_sent, a.last_shift, a.payload,
               coalesce(s.name, 'АЗС ' || a.station_id::text) AS name
          FROM edge_agents a
          LEFT JOIN edge.station s ON s.id = a.station_id
         WHERE a.company_id = :cid
         ORDER BY a.station_id
    """), {"cid": cid})).mappings().all()

    задания = {r["station_id"]: r for r in (await db.execute(text("""
        SELECT station_id,
               count(*) FILTER (WHERE acked_at IS NULL AND cancelled_at IS NULL) AS ждут,
               min(created_at) FILTER (WHERE acked_at IS NULL AND cancelled_at IS NULL)
                   AS самое_старое
          FROM edge_downlink WHERE company_id = :cid GROUP BY station_id
    """), {"cid": cid})).mappings().all()}

    try:
        сверка = {r["station_id"]: r for r in (await db.execute(text("""
            SELECT station_id, checked_at, taken_at, station_items, center_items,
                   drafts_pending,
                   jsonb_array_length(missing_in_center)  AS нет_в_центре,
                   jsonb_array_length(missing_on_station) AS нет_на_станции,
                   missing_in_center
              FROM edge_catalog_check WHERE company_id = :cid
        """), {"cid": cid})).mappings().all()}
    except Exception:  # noqa: BLE001 — таблицы ещё нет, миграция не дошла
        сверка = {}

    пакеты = {r["station_id"]: r["last_at"] for r in (await db.execute(text("""
        SELECT station_id, max(received_at) AS last_at
          FROM edge_packets WHERE company_id = :cid GROUP BY station_id
    """), {"cid": cid})).mappings().all()}

    now = datetime.now(timezone.utc)
    станции = []
    for a in агенты:
        молчит = (now - a["last_seen"]).total_seconds() if a["last_seen"] else None
        телеметрия = a["payload"] or {}
        строка_сверки = сверка.get(a["station_id"])
        задание = задания.get(a["station_id"])
        последний_пакет = пакеты.get(a["station_id"])
        станции.append({
            "station_id": a["station_id"],
            "name": a["name"],
            "state": "офлайн" if молчит is None or молчит > 180 else "онлайн",
            "silence_seconds": int(молчит) if молчит is not None else None,
            "version": a["version"],
            "version_ok": not a["version"] or (
                edge_router._номер_версии(a["version"])
                >= edge_router._номер_версии(желаемая)),
            "queue_pending": a["queue_pending"] or 0,
            "downlink_waiting": int(задание["ждут"]) if задание else 0,
            "downlink_oldest": задание["самое_старое"] if задание else None,
            "last_packet_at": последний_пакет,
            "last_shift": a["last_shift"],
            # Запас номеров: кончится — станция не заведёт карточку и не выдаст
            # код кассе, то есть перестанет принимать товар.
            "sku_left": телеметрия.get("sku_left"),
            "ns_code_left": телеметрия.get("ns_code_left"),
            "catalog": {
                "checked_at": строка_сверки["checked_at"] if строка_сверки else None,
                "station_items": строка_сверки["station_items"] if строка_сверки else None,
                "center_items": строка_сверки["center_items"] if строка_сверки else None,
                "missing_in_center": строка_сверки["нет_в_центре"] if строка_сверки else None,
                "missing_on_station": строка_сверки["нет_на_станции"] if строка_сверки else None,
                "drafts_pending": строка_сверки["drafts_pending"] if строка_сверки else None,
                "examples": list(строка_сверки["missing_in_center"] or [])[:5]
                            if строка_сверки else [],
            } if строка_сверки else None,
        })

    # Что требует человека прямо сейчас — тем же порядком, что читает товаровед:
    # сначала молчащие станции, потом разошедшийся справочник, потом запасы.
    тревоги = []
    for с in станции:
        if с["state"] == "офлайн":
            тревоги.append({"station_id": с["station_id"], "level": "critical",
                            "text": "станция не выходит на связь"})
        if (с["catalog"] or {}).get("missing_in_center"):
            тревоги.append({"station_id": с["station_id"], "level": "warning",
                            "text": f"карточек нет в центре: {с['catalog']['missing_in_center']}"})
        if с["ns_code_left"] is not None and с["ns_code_left"] < 50:
            тревоги.append({"station_id": с["station_id"], "level": "warning",
                            "text": f"свободных кодов кассы осталось {с['ns_code_left']}"})
        if с["sku_left"] is not None and с["sku_left"] < 100:
            тревоги.append({"station_id": с["station_id"], "level": "warning",
                            "text": f"артикулов в блоке осталось {с['sku_left']}"})
        if с["downlink_waiting"] > 20:
            тревоги.append({"station_id": с["station_id"], "level": "warning",
                            "text": f"заданий вниз ждёт {с['downlink_waiting']}"})
    return {"stations": станции, "alerts": тревоги,
            "desired_version": желаемая,
            "online": sum(1 for с in станции if с["state"] == "онлайн"),
            "total": len(станции)}


@router.get("/cash-sync")
async def store_cash_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Канал справочника в кассу: у какой станции касса отстала от учёта.

    Монитор доставки, а не действие. Короткий файл количество только прибавляет
    (и вычитает минусом с 31.08.2026), а полный перелив, который правит справочник
    целиком, делает человек на станции. Центр в кассу не пишет никогда — здесь
    видно, где «мало товара» при живом остатке, и откуда перейти на рабочее место.

    Три источника, и путать их нельзя:
      * телеметрия агента — очередь наверх, отставание, жив ли канал кассы;
      * снимок сверки (`cash_state`) — разошлись ли остатки и на сколько;
      * наш справочник — карточки, которые в кассу не уедут вовсе, потому что у
        них нет штрихкода или кода кассы. Такая позиция лежит на полке и не
        пробивается, сколько её ни досылай.
    """
    cid = await scope_company_id(user, db)
    строки = [dict(r) for r in (await db.execute(text("""
        WITH позиции AS (
            -- Позиция станции: у неё есть цена, код кассы или остаток на этой АЗС.
            -- Считаем по станции, а не по сети: код кассы локален, и «нет кода»
            -- у товара на 208 ничего не говорит про АЗС 8.
            SELECT s.id AS station_id, i.id AS item_id,
                   EXISTS (SELECT 1 FROM edge.barcode b
                            WHERE b.item_id = i.id AND b.status = 'active') AS есть_шк,
                   EXISTS (SELECT 1 FROM edge.price p
                            WHERE p.item_id = i.id AND p.station_id = s.id
                              AND p.valid_to IS NULL AND p.price > 0)        AS есть_цена,
                   EXISTS (SELECT 1 FROM edge.ns_code n
                             JOIN edge.barcode b2 ON b2.id = n.barcode_id
                            WHERE b2.item_id = i.id AND n.station_id = s.id
                              AND n.status = 'active')                       AS есть_код
              FROM edge.station s
              JOIN edge.item i ON NOT i.deleted
                              AND coalesce(i.sku_class, '') <> 'Сырьё'
                              AND (i.company_id IS NULL OR i.company_id = :cid)
             WHERE (s.company_id = :cid OR s.company_id IS NULL)
               AND (EXISTS (SELECT 1 FROM edge.price p2
                             WHERE p2.item_id = i.id AND p2.station_id = s.id
                               AND p2.valid_to IS NULL)
                 OR EXISTS (SELECT 1 FROM edge.ns_code n2
                              JOIN edge.barcode b3 ON b3.id = n2.barcode_id
                             WHERE b3.item_id = i.id AND n2.station_id = s.id
                               AND n2.status = 'active')
                 OR EXISTS (SELECT 1 FROM edge.stock st
                              JOIN edge.barcode b4 ON b4.id = st.barcode_id
                             WHERE b4.item_id = i.id AND st.station_id = s.id
                               AND st.qty <> 0))
        )
        SELECT s.id AS station_id,
               coalesce(s.name, 'АЗС ' || s.id::text) AS name,
               a.version, a.last_seen,
               a.queue_pending,
               coalesce((a.payload::jsonb->>'queue_failing')::int, 0)  AS queue_failing,
               coalesce((a.payload::jsonb->>'cash_ok')::bool, false)   AS cash_ok,
               a.payload::jsonb->>'last_sent_at'                       AS last_sent_at,
               a.payload::jsonb->>'snapshot_at'                        AS snapshot_at,
               c.checked_at, c.in_cash, c.should_be, c.matched,
               c.above, c.below, c.not_in_cash, c.no_card,
               (SELECT count(*) FROM позиции z WHERE z.station_id = s.id)     AS позиций,
               (SELECT count(*) FROM позиции z
                 WHERE z.station_id = s.id AND NOT z.есть_шк)                 AS без_штрихкода,
               (SELECT count(*) FROM позиции z
                 WHERE z.station_id = s.id AND NOT z.есть_цена)               AS без_цены,
               (SELECT count(*) FROM позиции z
                 WHERE z.station_id = s.id AND NOT z.есть_код)                AS без_кода_кассы
          FROM edge.station s
          LEFT JOIN core.edge_agents a ON a.station_id = s.id AND a.company_id = :cid
          LEFT JOIN core.edge_cash_check c ON c.station_id = s.id AND c.company_id = :cid
         WHERE s.company_id = :cid OR s.company_id IS NULL
         ORDER BY s.id
    """), {"cid": cid})).mappings().all()]

    return {"stations": строки,
            # Заявок на перелив агент пока не шлёт: в телеметрии такого поля нет.
            # Честно говорим об этом на экране, а не рисуем пустой блок.
            "заявки_на_перелив": None}


@router.get("/cash-codes")
async def store_cash_codes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Коды нефтесервера по сети: сколько номеров занято и сколько осталось.

    Код кассы — расходник связки станция × штрихкод, а не свойство товара: он
    переиспользуется и живёт в границах, которые нарезает центр
    (`edge.station.ns_code_min/max`). Кончится пул — станция не сможет завести
    новую позицию, и товар с полки не пробьётся. Поэтому запас смотрят до того,
    как он кончился, а не после.

    Спящий код здесь считается ТАК ЖЕ, как на станции: активная привязка есть,
    а товара за ней нет — ни остатка, ни цены. Такой код держит номер и мешает
    продать вторую упаковку того же товара; на 208 их гасили пачкой 31.07.2026.

    ⚠ Экран показывает состояние, а не действие: снять или перевесить код может
    только станция — центр в кассу не пишет никогда.
    """
    cid = await scope_company_id(user, db)
    строки = [dict(r) for r in (await db.execute(text("""
        SELECT s.id AS station_id,
               coalesce(s.name, 'АЗС ' || s.id::text) AS name,
               s.ns_code_min, s.ns_code_max,
               count(c.id) FILTER (WHERE c.status = 'active')      AS занято,
               count(c.id) FILTER (WHERE c.status <> 'active')     AS погашено,
               min(c.ns_code) FILTER (WHERE c.status = 'active')   AS первый,
               max(c.ns_code) FILTER (WHERE c.status = 'active')   AS последний,
               -- За границей пула: код выдан вне нарезки центра. На 208 такие
               -- есть (5207 при потолке 5199) — наследие 1С, которое станция
               -- получила до того, как пул стал нарезаться заданием.
               count(c.id) FILTER (WHERE c.status = 'active'
                                     AND (c.ns_code < s.ns_code_min
                                       OR c.ns_code > s.ns_code_max))
                                                                   AS вне_пула,
               -- Спящий: привязка активна, а товара за ней нет.
               count(c.id) FILTER (WHERE c.status = 'active' AND NOT EXISTS (
                   SELECT 1 FROM edge.stock st
                    WHERE st.barcode_id = c.barcode_id AND st.qty <> 0)
                 AND NOT EXISTS (
                   SELECT 1 FROM edge.price pr
                     JOIN edge.barcode bb ON bb.id = c.barcode_id
                    WHERE pr.item_id = bb.item_id AND pr.station_id = s.id
                      AND pr.valid_to IS NULL))                    AS спящих
          FROM edge.station s
          LEFT JOIN edge.ns_code c ON c.station_id = s.id
         WHERE s.company_id = :cid OR s.company_id IS NULL
         GROUP BY s.id, s.name, s.ns_code_min, s.ns_code_max
         ORDER BY s.id
    """), {"cid": cid})).mappings().all()]

    for р in строки:
        всего = (р["ns_code_max"] or 0) - (р["ns_code_min"] or 0) + 1
        р["всего_в_пуле"] = max(всего, 0)
        р["свободно"] = max(всего - (р["занято"] or 0), 0)
        р["занято_долей"] = round((р["занято"] or 0) / всего * 100) if всего else 0

    return {"stations": строки}


@router.get("/cash-check")
async def store_cash_check(
    station_id: int | None = Query(None, description="код АЗС; пусто — вся сеть"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сверка «касса ↔ учёт» по сети: где касса разошлась с учётом.

    Центр остаток кассы NeftoMS сам не видит — станция шлёт снимок сверки
    пакетом cash_state своим тактом (edge_cash_check, одна строка на станцию).
    Читается по НАПРАВЛЕНИЮ: касса выше учёта — разбор, ниже — окно разнесения
    (уйдёт за такт), сырьё общепита — норма. Само выравнивание делает станция;
    здесь надзор и приоритет.

    Без station_id — строка на каждую АЗС для свода; с ним — плюс список
    позиций «касса выше учёта» этой станции для разбора.
    """
    cid = await scope_company_id(user, db)

    строки = (await db.execute(text("""
        SELECT c.station_id, c.checked_at, c.taken_at, c.in_cash, c.should_be,
               c.matched, c.above, c.below, c.raw_material, c.not_in_cash, c.no_card,
               coalesce(s.name, 'АЗС ' || c.station_id::text) AS name
          FROM edge_cash_check c
          LEFT JOIN edge.station s ON s.id = c.station_id
         WHERE c.company_id = :cid
           -- ⚠ Приведение типа обязательно: у пустого параметра asyncpg не
           -- может вывести тип и роняет запрос («could not determine data type
           -- of parameter $2») — вся сеть без station_id падала с 500.
           -- ⚠ CAST, а не `::int`: в SQLAlchemy text() двойное двоеточие читается
           -- как начало ещё одного параметра, и запрос падает синтаксической
           -- ошибкой. А без приведения типа вовсе asyncpg не выводит тип пустого
           -- параметра — «could not determine data type of parameter $2».
           AND (CAST(:st AS integer) IS NULL OR c.station_id = CAST(:st AS integer))
         ORDER BY c.above DESC, c.not_in_cash DESC, c.station_id
    """), {"cid": cid, "st": station_id})).mappings().all()

    станции = [{
        "station_id": r["station_id"],
        "name": r["name"],
        "checked_at": r["checked_at"],
        "taken_at": r["taken_at"],
        "in_cash": r["in_cash"],
        "should_be": r["should_be"],
        "matched": r["matched"],
        # Направление — главный разрез: разбор, окно разнесения, норма.
        "above": r["above"],           # касса выше учёта — разбор обязателен
        "below": r["below"],           # касса ниже — окно разнесения
        "raw_material": r["raw_material"],  # сырьё общепита — норма
        # Наша карточка есть, а в кассе её нет — товар не пробивается («мало
        # товара»). Это тоже разбор: справочник не доехал, а не сходится.
        "not_in_cash": r["not_in_cash"],
        "no_card": r["no_card"],       # строки кассы без нашей карточки
        # Цвет строки по худшей графе. «Не в кассе» — разбор наравне с «выше»:
        # покупателю всё равно, товар не продаётся. Иначе станция с недоехавшим
        # справочником зеленела бы как сходящаяся.
        "state": ("разбор" if r["above"] > 0 or r["not_in_cash"] > 0
                  else "разнесение" if r["below"] > 0
                  else "сходится"),
    } for r in строки]

    result = {
        "stations": станции,
        "total": len(станции),
        "with_above": sum(1 for s in станции if s["above"] > 0),
        "with_gap": sum(1 for s in станции if s["above"] > 0 or s["not_in_cash"] > 0),
    }

    # Список разбора — только для одной станции: тащить позиции всей сети незачем.
    if station_id is not None and строки:
        предметы = (await db.execute(text("""
            SELECT above_items FROM edge_cash_check
             WHERE company_id = :cid AND station_id = :st
        """), {"cid": cid, "st": station_id})).scalar_one_or_none()
        result["above_items"] = предметы or []

    return result



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
    отчёт = await edge_service.alerts(db, cid, station_id)

    # Ушедшие находки — тоже ответ: «касса не пробьёт» пропало вчера значит,
    # что кто-то нажал «Загрузить ККМ», и повторять письмо не нужно.
    отчёт["resolved"] = [dict(r) for r in (await db.execute(text("""
        SELECT topic, level, text, first_seen, last_seen, resolved_at
        FROM store_station_alerts
        WHERE company_id = :cid AND station_id = :st
          AND resolved_at IS NOT NULL
          AND resolved_at > now() - interval '14 days'
        ORDER BY resolved_at DESC
    """), {"cid": cid, "st": station_id})).mappings().all()]
    return отчёт


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
        "not_on_floor": не_в_зале,
    }


class MatrixRuleIn(BaseModel):
    """Новое правило матрицы. Причина обязательна: через полгода спросят «почему так»."""
    subject: str                      # price | assortment
    allow: bool
    reason: str
    station_id: int | None = None     # None — правило всей сети
    group_id: int | None = None       # либо группа, либо позиция
    item_id: int | None = None
    hard: bool = False                # жёсткий запрет — только сетевой
    valid_from: datetime | None = None
    valid_to: datetime | None = None


@router.get("/matrix")
async def store_matrix(
    subject: str = Query("", description="price | assortment; пусто — оба"),
    include_closed: bool = Query(False, description="показать историю закрытых правил"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Матрица: кто что вправе делать по каждой позиции на каждой станции.

    Экран товароведа. Позиция заводится один раз; всё, что различается между
    станциями, описано правилами к ней, а не второй карточкой. Вместе с
    правилами отдаём станции и группы — без них форму заведения не построить,
    а лишний запрос на каждый экран не нужен.
    """
    cid = await scope_company_id(user, db)
    правила = await matrix.правила_компании(
        db, cid, subject=subject or None, включая_закрытые=include_closed)

    станции = [dict(r) for r in (await db.execute(text("""
        SELECT s.id AS station_id, s.name,
               EXISTS (SELECT 1 FROM core.edge_agents a
                        WHERE a.company_id = :cid AND a.station_id = s.id) AS on_air
          FROM edge.station s
         WHERE s.company_id IS NULL OR s.company_id = :cid
         ORDER BY s.id
    """), {"cid": cid})).mappings().all()]

    группы = [dict(r) for r in (await db.execute(text("""
        SELECT g.id AS group_id, g.path,
               count(i.id) FILTER (WHERE NOT i.deleted) AS items
          FROM edge.item_group g
          LEFT JOIN edge.item i ON i.group_id = g.id
         GROUP BY g.id, g.path ORDER BY g.path
    """))).mappings().all()]

    # Умолчания показываем рядом с правилами: без них список правил читается
    # как полная картина, а он — только исключения из умолчаний.
    return {
        "rules": правила,
        "stations": станции,
        "groups": группы,
        "defaults": {
            "price": {"allow": matrix.УМОЛЧАНИЯ[matrix.PRICE],
                      "text": "цена сетевая: право станции назначается явно, с причиной"},
            "assortment": {"allow": matrix.УМОЛЧАНИЯ[matrix.ASSORTMENT],
                           "text": "позиция доступна всем станциям; правило нужно, чтобы исключить"},
        },
    }


@router.post("/matrix")
async def store_matrix_rule_add(
    body: MatrixRuleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести правило. Существующее на ту же четвёрку закрывается, не правится."""
    cid = await _require_network_merchandiser(user, db)
    try:
        правило = await matrix.завести_правило(
            db, cid, subject=body.subject, allow=body.allow, reason=body.reason,
            station_id=body.station_id, group_id=body.group_id, item_id=body.item_id,
            hard=body.hard, valid_from=body.valid_from, valid_to=body.valid_to,
            author_id=user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return правило


@router.delete("/matrix/{rule_id}")
async def store_matrix_rule_close(
    rule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Закрыть правило. История остаётся: «почему в июле было иначе» обязано иметь ответ."""
    cid = await _require_network_merchandiser(user, db)
    if not await matrix.закрыть_правило(db, cid, rule_id, author_id=user.id):
        raise HTTPException(404, "Правило не найдено или уже закрыто")
    await db.commit()
    return {"ok": True, "rule_id": rule_id}


@router.get("/matrix/explain")
async def store_matrix_explain(
    station_id: int = Query(..., description="код АЗС"),
    item_id: int = Query(..., description="позиция каталога"),
    subject: str = Query("price", description="price | assortment"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """«Почему так»: какое правило решило и какие оно перебило.

    Без этого ответа матрица непрозрачна: станция говорит «не могу поменять
    цену», товаровед смотрит на список правил и гадает.
    """
    cid = await scope_company_id(user, db)
    if subject not in (matrix.PRICE, matrix.ASSORTMENT):
        raise HTTPException(400, f"неизвестный предмет правила: {subject}")
    решение = await matrix.разрешить(db, cid, subject, station_id, item_id)

    def как(п):
        if п is None:
            return None
        return {"id": п.id, "station_id": п.station_id, "group_path": п.group_path,
                "item_id": п.item_id, "allow": п.allow, "hard": п.hard,
                "reason": п.reason, "text": п.как_текст()}

    return {
        "allow": решение.allow, "subject": subject,
        "station_id": station_id, "item_id": item_id,
        "by_default": решение.по_умолчанию,
        "explanation": решение.объяснение(),
        "rule": как(решение.сработало),
        "overridden": [как(п) for п in решение.перебиты],
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
    cid = await _require_central_commercial_control(user, db)
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
    cid = await _require_central_commercial_control(user, db)
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


@router.get("/item-locations")
async def store_item_locations(
    q: str = Query("", description="имя, артикул или штрихкод"),
    station: int | None = Query(None, description="только карточки этой станции"),
    scope: str = Query("all", description="all | shared | single | none"),
    sku_class: str = Query("", description="Сопутка | Блюдо | Сырьё"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Товар × станции: где карточка применяется и на каких условиях.

    Отраслевой аналог — item/location в Oracle Retail: у карточки есть сетевая
    часть (имя, артикул, штрихкоды, группа) и часть, своя у каждой площадки
    (цена, право на цену, применение, код кассы, остаток). Без такого разреза
    вопрос «где этот товар продаётся и почём» решается обходом рабочих мест.

    `scope`: shared — позиции больше чем одной станции, single — ровно одной,
    none — сетевые карточки, которых не применяет никто (кандидаты в архив).
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    станции = [r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL ORDER BY id"
    ), {"c": cid})).all()]

    условия = ["NOT i.deleted"]
    параметры: dict = {"limit": limit, "offset": offset}
    if q.strip():
        условия.append("(i.name ILIKE :q OR i.sku = :точно"
                       " OR EXISTS (SELECT 1 FROM edge.barcode b"
                       "             WHERE b.item_id = i.id AND b.code = :точно))")
        параметры["q"] = "%" + q.strip() + "%"
        параметры["точно"] = q.strip()
    if sku_class.strip():
        условия.append("i.sku_class = :класс")
        параметры["класс"] = sku_class.strip()
    if station is not None:
        условия.append("EXISTS (SELECT 1 FROM edge.price p"
                       "         WHERE p.item_id = i.id AND p.station_id = :станция"
                       "           AND p.valid_to IS NULL)")
        параметры["станция"] = station

    имеющие = ("(SELECT count(DISTINCT p.station_id) FROM edge.price p"
               "  WHERE p.item_id = i.id AND p.valid_to IS NULL)")
    if scope == "shared":
        условия.append(имеющие + " > 1")
    elif scope == "single":
        условия.append(имеющие + " = 1")
    elif scope == "none":
        условия.append(имеющие + " = 0")

    где = " AND ".join(условия)
    всего = (await db.execute(text(
        "SELECT count(*) FROM edge.item i WHERE " + где), параметры)).scalar() or 0
    rows = (await db.execute(text(
        "SELECT i.id, i.sku, i.name, i.unit, i.sku_class, i.source,"
        " i.external_uuid::text AS guid,"
        "       g.path AS group_path,"
        "       coalesce((SELECT array_agg(b.code ORDER BY b.code) FROM edge.barcode b"
        "                  WHERE b.item_id = i.id AND b.status = 'active'), ARRAY[]::text[])"
        "         AS barcodes,"
        "       " + имеющие + " AS станций"
        "  FROM edge.item i"
        "  LEFT JOIN edge.item_group g ON g.id = i.group_id"
        " WHERE " + где +
        " ORDER BY i.name LIMIT :limit OFFSET :offset"), параметры)).mappings().all()
    ids = [r["id"] for r in rows]

    цены, коды, остатки = {}, {}, {}
    if ids:
        for r in (await db.execute(text(
            "SELECT item_id, station_id, price FROM edge.price"
            " WHERE item_id = ANY(:ids) AND valid_to IS NULL"
        ), {"ids": ids})).mappings().all():
            цены[(r["item_id"], r["station_id"])] = float(r["price"])
        for r in (await db.execute(text(
            "SELECT b.item_id, n.station_id, count(*) AS кодов"
            "  FROM edge.ns_code n JOIN edge.barcode b ON b.id = n.barcode_id"
            " WHERE b.item_id = ANY(:ids) AND n.status = 'active'"
            " GROUP BY 1, 2"
        ), {"ids": ids})).mappings().all():
            коды[(r["item_id"], r["station_id"])] = int(r["кодов"])
        for r in (await db.execute(text(
            "SELECT b.item_id, s.station_id, sum(s.qty) AS qty"
            "  FROM edge.stock s JOIN edge.barcode b ON b.id = s.barcode_id"
            " WHERE b.item_id = ANY(:ids)"
            " GROUP BY 1, 2"
        ), {"ids": ids})).mappings().all():
            остатки[(r["item_id"], r["station_id"])] = float(r["qty"] or 0)

    # Матрица считается пачкой на станцию: правил единицы, позиций сотни.
    пары = [(r["id"], r["group_path"] or "") for r in rows]
    матрица = {}
    for st in станции:
        матрица[st] = (
            await matrix.применение(db, cid, st, пары),
            await matrix.владельцы_цены(db, cid, st, пары),
        )

    items = []
    for r in rows:
        по_станциям = []
        for st in станции:
            применяется, владельцы = матрица[st]
            цена = цены.get((r["id"], st))
            разрешена = bool(применяется.get(r["id"], True))
            по_станциям.append({
                "station_id": st,
                "price": цена,
                "price_owner": "station" if владельцы.get(r["id"]) else "master",
                "assortment": разрешена,
                "ns_codes": коды.get((r["id"], st), 0),
                "stock": остатки.get((r["id"], st)),
                # Позиция живёт на станции, когда у неё там есть цена и матрица
                # её не закрыла: ровно эта пара решает, уедет ли товар в кассу.
                "живёт": bool(цена is not None and разрешена),
            })
        items.append({
            "id": r["id"], "sku": r["sku"], "name": r["name"], "unit": r["unit"],
            "sku_class": r["sku_class"], "group_path": r["group_path"],
            "barcodes": list(r["barcodes"] or []),
            "источник": r["source"],
            # GUID нужен экрану, чтобы открыть карточку товара по строке:
            # модалка карточки адресуется внешним идентификатором, а не нашим id.
            "guid": r["guid"],
            "станций": int(r["станций"] or 0),
            "stations": по_станциям,
        })
    return {"stations": станции, "total": всего, "items": items,
            "limit": limit, "offset": offset}


@router.get("/catalog/item-passport/{guid}")
async def catalog_item_passport(
    guid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Паспорт карточки: чем она является в сети и на каждой станции.

    Отвечает на четыре вопроса, которых не было в карточке товара:
    какие коды у неё сетевые, а какие принадлежат одной АЗС; на каких условиях
    она живёт на каждой станции; чья рецептура по ней действует; откуда она
    вообще взялась и что в неё слито.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    карточка = (await db.execute(text("""
        SELECT i.id, i.external_uuid::text AS uuid, i.sku, i.name, i.unit, i.vat_rate,
               i.sku_class, i.source, i.deleted, i.marked, i.mark_group, i.adult_only,
               i.mrc, i.brand, i.price_owner, i.created_at, i.updated_at,
               g.path AS group_path, g.cash_section
          FROM edge.item i
          LEFT JOIN edge.item_group g ON g.id = i.group_id
         WHERE i.external_uuid::text = :g OR i.sku = :g
         LIMIT 1
    """), {"g": guid})).mappings().first()
    if карточка is None:
        raise HTTPException(404, "Карточка не найдена")
    item_id = карточка["id"]

    станции = [r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL ORDER BY id"
    ), {"c": cid})).all()]

    # Штрихкоды с ярусом: сетевой EAN против внутреннего кода одной АЗС.
    коды = [dict(r) for r in (await db.execute(text("""
        SELECT b.code, b.status::text AS status, b.station_id, b.first_seen,
               b.last_sold, b.note,
               (SELECT array_agg(DISTINCT n.station_id ORDER BY n.station_id)
                  FROM edge.ns_code n
                 WHERE n.barcode_id = b.id AND n.status = 'active') AS кассы
          FROM edge.barcode b WHERE b.item_id = :i
         ORDER BY (b.status = 'active') DESC, b.code
    """), {"i": item_id})).mappings().all()]

    # Условия станции: цена, её владелец, применение, код кассы, остаток.
    цены = {r["station_id"]: r for r in (await db.execute(text("""
        SELECT station_id, price, author, valid_from FROM edge.price
         WHERE item_id = :i AND valid_to IS NULL
    """), {"i": item_id})).mappings().all()}
    остатки = {r["station_id"]: float(r["qty"] or 0) for r in (await db.execute(text("""
        SELECT s.station_id, sum(s.qty) AS qty FROM edge.stock s
          JOIN edge.barcode b ON b.id = s.barcode_id
         WHERE b.item_id = :i GROUP BY 1
    """), {"i": item_id})).mappings().all()}
    коды_кассы = {}
    for r in (await db.execute(text("""
        SELECT n.station_id, n.ns_code AS code, b.code AS barcode FROM edge.ns_code n
          JOIN edge.barcode b ON b.id = n.barcode_id
         WHERE b.item_id = :i AND n.status = 'active'
    """), {"i": item_id})).mappings().all():
        коды_кассы.setdefault(r["station_id"], []).append(
            {"code": r["code"], "barcode": r["barcode"]})

    пары = [(item_id, карточка["group_path"] or "")]
    условия = []
    for st in станции:
        применение = await matrix.применение(db, cid, st, пары)
        владелец = await matrix.владельцы_цены(db, cid, st, пары)
        цена = цены.get(st)
        разрешена = bool(применение.get(item_id, True))
        условия.append({
            "station_id": st,
            "price": float(цена["price"]) if цена else None,
            "price_author": цена["author"] if цена else None,
            "price_since": цена["valid_from"] if цена else None,
            "price_owner": "station" if владелец.get(item_id) else "master",
            "assortment": разрешена,
            "ns_codes": коды_кассы.get(st, []),
            "stock": остатки.get(st),
            "живёт": bool(цена is not None and разрешена),
        })

    # Правила матрицы, которые касаются именно этой карточки.
    правила = [dict(r) for r in (await db.execute(text("""
        SELECT subject, station_id, allow, reason, valid_from, created_at
          FROM edge.matrix_rule
         WHERE item_id = :i AND valid_to IS NULL AND closed_at IS NULL
         ORDER BY subject, station_id NULLS FIRST
    """), {"i": item_id})).mappings().all()]

    # Рецептура: чья карта действует. Ярус станции перебивает сетевую норму.
    карты = [dict(r) for r in (await db.execute(text("""
        SELECT station_id, version, status, output_qty, output_unit,
               jsonb_array_length(coalesce(lines, '[]'::jsonb)) AS строк,
               source, source_station_id, valid_from, change_note
          FROM store_recipe_versions
         WHERE company_id = :cid AND dish_uuid = :u
           AND status = 'active' AND valid_to IS NULL
         ORDER BY station_id NULLS FIRST
    """), {"cid": cid, "u": карточка["uuid"]})).mappings().all()]
    действует = {}
    сетевая = next((к for к in карты if к["station_id"] is None), None)
    for st in станции:
        своя = next((к for к in карты if к["station_id"] == st), None)
        выбор = своя or сетевая
        действует[st] = {
            "ярус": None if выбор is None else ("сеть" if выбор["station_id"] is None
                                                else f"АЗС {выбор['station_id']}"),
            "version": выбор["version"] if выбор else None,
            "строк": выбор["строк"] if выбор else None,
        }

    # Происхождение: заявка станции и всё, что слито в эту карточку.
    заявка = (await db.execute(text("""
        SELECT station_id, author, created_at, resolved_at, sku, barcodes, note
          FROM edge.item_draft
         WHERE resolved_item = :item_id
            OR (sku IS NOT NULL AND sku = :sku)
         ORDER BY created_at LIMIT 1
    """), {"item_id": item_id, "sku": карточка["sku"]})).mappings().first()
    слито = [dict(r) for r in (await db.execute(text("""
        SELECT a.alias_uuid, a.reason, a.created_at, d.name, d.sku
          FROM store_item_aliases a
          LEFT JOIN edge.item d ON d.external_uuid::text = a.alias_uuid
         WHERE a.canonical_uuid = :u AND a.company_id = :cid
         ORDER BY a.created_at DESC
    """), {"u": карточка["uuid"], "cid": cid})).mappings().all()]
    прежние = [dict(r) for r in (await db.execute(text("""
        SELECT code, kind, note FROM edge.item_code WHERE item_id = :i ORDER BY kind, code
    """), {"i": item_id})).mappings().all()]

    return {
        "item": dict(карточка),
        "stations": станции,
        "barcodes": коды,
        "conditions": условия,
        "matrix_rules": правила,
        "recipes": {"active": карты, "effective": действует},
        "origin": {"draft": dict(заявка) if заявка else None,
                   "merged": слито, "aliases": прежние},
    }


@router.get("/catalog/station-pulse")
async def catalog_station_pulse(
    days: int = Query(7, ge=1, le=90, description="глубина по правкам станций"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Что происходит со справочником на станциях — одним экраном из центра.

    Товаровед сети не сидит на АЗС и узнаёт о её работе с карточками только тогда,
    когда что-то сломалось. Здесь собрано то, что станция делает со справочником
    сама: заводит карточки, меняет цены, накапливает позиции, которые в кассу не
    уедут. Каждая цифра — отбор, который можно открыть и разобрать.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    станции = [r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL ORDER BY id"
    ), {"c": cid})).all()]

    рядом = (await db.execute(text("""
        SELECT s.id AS station_id, s.name,
               (SELECT count(*) FROM edge.item_draft d
                 WHERE d.station_id = s.id AND d.resolved_at IS NULL) AS заявок_ждёт,
               (SELECT count(*) FROM edge.item_draft d
                 WHERE d.station_id = s.id AND d.resolved_at IS NULL
                   AND NOT EXISTS (SELECT 1 FROM edge.barcode b
                                    WHERE b.item_id IS NOT NULL AND b.code = ANY(d.barcodes)))
                                                                        AS заявок_новых,
               (SELECT count(*) FROM edge.station_price_change c
                 WHERE c.station_id = s.id
                   AND c.changed_at > now() - make_interval(days => :days)) AS правок_цен,
               (SELECT count(*) FROM edge.price p JOIN edge.item i ON i.id = p.item_id
                 WHERE p.station_id = s.id AND p.valid_to IS NULL AND NOT i.deleted)
                                                                        AS позиций,
               (SELECT count(*) FROM edge.matrix_rule r
                 WHERE r.station_id = s.id AND r.subject = 'assortment'
                   AND NOT r.allow AND r.valid_to IS NULL AND r.closed_at IS NULL)
                                                                        AS закрыто_матрицей,
               (SELECT count(*) FROM edge.matrix_rule r
                 WHERE r.station_id = s.id AND r.subject = 'price'
                   AND r.valid_to IS NULL AND r.closed_at IS NULL)       AS правил_цены,
               (SELECT count(*) FROM edge.barcode b
                 WHERE b.station_id = s.id AND b.status = 'active')      AS своих_кодов
          FROM edge.station s
         WHERE s.company_id = :cid OR s.company_id IS NULL
         ORDER BY s.id
    """), {"cid": cid, "days": days})).mappings().all()

    # Позиции, которые в кассу не уедут: цена есть, а кода кассы нет. Это не
    # авария, а работа — товар заведён, но пробить его на этой АЗС нельзя.
    без_кода = {r["station_id"]: r["сколько"] for r in (await db.execute(text("""
        SELECT p.station_id, count(*) AS сколько
          FROM edge.price p JOIN edge.item i ON i.id = p.item_id
         WHERE p.valid_to IS NULL AND NOT i.deleted
           AND NOT EXISTS (
               SELECT 1 FROM edge.ns_code n JOIN edge.barcode b ON b.id = n.barcode_id
                WHERE b.item_id = i.id AND n.station_id = p.station_id
                  AND n.status = 'active')
         GROUP BY 1
    """))).mappings().all()}

    # Блюда без действующей карты: продаются, а сырьё под них не списывается.
    без_ттк = {r["station_id"]: r["сколько"] for r in (await db.execute(text("""
        SELECT p.station_id, count(*) AS сколько
          FROM edge.price p JOIN edge.item i ON i.id = p.item_id
         WHERE p.valid_to IS NULL AND NOT i.deleted AND i.sku_class = 'Блюдо'
           AND NOT EXISTS (
               SELECT 1 FROM store_recipe_versions v
                WHERE v.company_id = :cid AND v.dish_uuid = i.external_uuid::text
                  AND v.status = 'active' AND v.valid_to IS NULL
                  AND (v.station_id IS NULL OR v.station_id = p.station_id))
         GROUP BY 1
    """), {"cid": cid})).mappings().all()}

    # Карты рецептур по ярусам: сколько блюд станция ведёт по-своему.
    карты = {}
    for r in (await db.execute(text("""
        SELECT station_id, count(DISTINCT dish_uuid) AS блюд
          FROM store_recipe_versions
         WHERE company_id = :cid AND status = 'active' AND valid_to IS NULL
         GROUP BY 1
    """), {"cid": cid})).mappings().all():
        карты[r["station_id"]] = r["блюд"]

    сверка = {r["station_id"]: dict(r) for r in (await db.execute(text("""
        SELECT DISTINCT ON (station_id) station_id, checked_at, station_items,
               center_items,
               coalesce(jsonb_array_length(missing_in_center), 0) AS нет_в_центре,
               coalesce(jsonb_array_length(missing_on_station), 0) AS нет_на_станции,
               drafts_pending
          FROM core.edge_catalog_check
         WHERE company_id = :cid
         ORDER BY station_id, checked_at DESC
    """), {"cid": cid})).mappings().all()}

    строки = []
    for r in рядом:
        st = r["station_id"]
        c = сверка.get(st) or {}
        строки.append({
            "station_id": st, "name": r["name"],
            "позиций": r["позиций"],
            "заявок_ждёт": r["заявок_ждёт"],
            "правок_цен": r["правок_цен"],
            "закрыто_матрицей": r["закрыто_матрицей"],
            "правил_цены": r["правил_цены"],
            "своих_кодов": r["своих_кодов"],
            "без_кода_кассы": без_кода.get(st, 0),
            "блюд_без_ттк": без_ттк.get(st, 0),
            "своих_карт": карты.get(st, 0),
            "сетевых_карт": карты.get(None, 0),
            "сверка": {
                "момент": c.get("checked_at"),
                "на_станции": c.get("station_items"),
                "в_центре": c.get("center_items"),
                "нет_в_центре": c.get("нет_в_центре"),
                "нет_на_станции": c.get("нет_на_станции"),
            } if c else None,
        })
    # Справочники контрагентов: станция без поставщика и договора приёмку не
    # проведёт, а рассинхрон виден только отсюда — на самой АЗС «список пуст»
    # неотличим от «поставщиков ещё не заводили».
    справочники = await partner_sync.сводка(db, cid)
    for строка in строки:
        строка["справочники"] = справочники.get(строка["station_id"])
    return {"days": days, "stations": станции, "rows": строки}


@router.get("/item-locations/summary")
async def store_item_locations_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сводка каталога: сколько позиций общих для сети, сколько своих у станции."""
    cid: uuid.UUID = await scope_company_id(user, db)
    станции = [r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL ORDER BY id"
    ), {"c": cid})).all()]
    сводка = (await db.execute(text(
        "WITH ц AS (SELECT p.item_id, count(DISTINCT p.station_id) AS станций"
        "             FROM edge.price p JOIN edge.item i ON i.id = p.item_id"
        "            WHERE p.valid_to IS NULL AND NOT i.deleted"
        "            GROUP BY 1)"
        " SELECT count(*) FILTER (WHERE станций > 1) AS общих,"
        "        count(*) FILTER (WHERE станций = 1) AS своих,"
        "        (SELECT count(*) FROM edge.item WHERE NOT deleted) AS всего_карточек,"
        "        (SELECT count(*) FROM edge.item i WHERE NOT i.deleted"
        "           AND NOT EXISTS (SELECT 1 FROM edge.price p"
        "                            WHERE p.item_id = i.id AND p.valid_to IS NULL))"
        "          AS без_станций"
        "   FROM ц"))).mappings().first()
    по_станциям = (await db.execute(text(
        "SELECT p.station_id, count(*) AS позиций,"
        "       count(*) FILTER (WHERE i.sku_class = 'Блюдо') AS блюд,"
        "       count(*) FILTER (WHERE i.sku_class = 'Сырьё') AS сырья"
        "  FROM edge.price p JOIN edge.item i ON i.id = p.item_id"
        " WHERE p.valid_to IS NULL AND NOT i.deleted"
        " GROUP BY 1 ORDER BY 1"))).mappings().all()
    закрыто = (await db.execute(text(
        "SELECT station_id, count(*) AS позиций FROM edge.matrix_rule"
        " WHERE subject = 'assortment' AND NOT allow AND valid_to IS NULL"
        "   AND closed_at IS NULL AND item_id IS NOT NULL"
        " GROUP BY 1"))).mappings().all()
    return {"stations": станции, "итого": dict(сводка or {}),
            "по_станциям": [dict(r) for r in по_станциям],
            "закрыто_матрицей": {r["station_id"]: r["позиций"] for r in закрыто}}


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
        SELECT i.id, i.external_uuid, i.sku, i.name, i.unit, i.vat_rate, i.deleted,
               coalesce(i.price_owner, 'master') AS price_owner,
               g.path AS group_path, g.cash_section, i.sku_class, i.marked, i.mark_group,
               i.adult_only, i.mrc, i.brand, i.photo_url,
               (SELECT price FROM edge.price p
                 WHERE p.item_id = i.id AND p.station_id = :s AND p.valid_to IS NULL) AS price,
               coalesce((SELECT array_agg(b.code ORDER BY b.code) FROM edge.barcode b
                          WHERE b.item_id = i.id AND b.status = 'active'
                            AND (b.station_id IS NULL OR b.station_id = :s)),
                        '{{}}') AS codes
        FROM edge.item i
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        WHERE NOT i.deleted {фильтр}
        ORDER BY i.name
    """), {"s": station_id})).mappings().all()

    # Себестоимость станция знает только по своим приходам, а начинала она со
    # снимка остатков 1С — там закупочной цены нет. Ориентир по последней
    # закупке едет вместе с карточкой: без него рабочее место честно, но
    # бесполезно показывает «стоимость запаса 0,00» при полных полках.
    оценки = await store_costs.ориентиры(db, cid, [station_id])

    # Владельца цены считает МАТРИЦА, а не колонка карточки.
    #
    # Право станции менять цену описано правилом («АЗС 208 · все позиции ·
    # разрешение»), а вниз оно едет единственным полем, которое станция про это
    # понимает, — `price_owner`. Пока поле возили из колонки, выданное
    # товароведом право до станции не доезжало вовсе: 30.08.2026 его пришлось
    # переносить руками по 1290 карточкам.
    пары = [(r["id"], r["group_path"] or "") for r in rows]
    владельцы = await matrix.владельцы_цены(db, cid, station_id, пары)
    # Применение — это листинг: позиция, закрытая товароведом для станции,
    # уезжает БЕЗ ЦЕНЫ и потому не попадает в кассу. Саму карточку шлём: она
    # встречается в сменах прошлых дней, и ставку по ней брать неоткуда.
    применяется = await matrix.применение(db, cid, station_id, пары)

    items = [{"uuid": str(r["external_uuid"]), "sku": r["sku"],
              "name": r["name"], "unit": r["unit"],
              "vat_rate": r["vat_rate"], "deleted": bool(r["deleted"]),
              "price": (float(r["price"]) if r["price"] is not None
                        and применяется.get(r["id"], True) else None),
              "price_owner": "station" if владельцы.get(r["id"]) else "master",
              "assortment": bool(применяется.get(r["id"], True)),
              "group_path": r["group_path"], "sku_class": r["sku_class"],
              # Отдел кассы — свойство группы, а не догадка станции: у новой
              # АЗС в кассе нет ни одной нашей позиции, и выводить его по
              # соседям не из чего.
              "cash_section": r["cash_section"],
              "marked": bool(r["marked"]), "mark_group": r["mark_group"],
              "adult_only": bool(r["adult_only"]),
              "mrc": float(r["mrc"]) if r["mrc"] is not None else None,
              "brand": r["brand"], "photo_url": r["photo_url"],
              "barcodes": list(r["codes"] or []),
              **_оценка_себестоимости(оценки, str(r["external_uuid"]))} for r in rows]
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
    group_path: str = Query("", description="ветка дерева групп, например «Табак»"),
    sku_class: str = Query("", description="Сопутка | Блюдо | Сырьё | Архив"),
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр карточек мастер-НСИ с ценой, штрихкодами и остатком станции."""
    cid = await scope_company_id(user, db)
    sql = """
        SELECT i.id, i.external_uuid, i.code_1c, i.name, i.unit, i.vat_rate,
               i.kind, i.sku_class, i.is_dish, i.deleted,
               i.group_id, g.path AS group_path, i.marked, i.adult_only,
               i.photo_url IS NOT NULL AS has_photo,
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
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        -- Карточки только своей компании. Строка без владельца видна всем:
        -- до миграции company_id его не было ни у одной, и прятать весь
        -- справочник ради строгости значит показать товароведу пустой экран.
        WHERE (i.company_id IS NULL OR i.company_id = :cid)
          AND (:q = '' OR i.name ILIKE :like OR coalesce(i.code_1c,'') ILIKE :like
               OR EXISTS (SELECT 1 FROM edge.barcode b3
                           WHERE b3.item_id = i.id AND b3.code ILIKE :like))
    """
    # Отбор по ветке дерева, а не по одной группе: «Табак» должен показывать и
    # сигареты, и стики — иначе группировкой невозможно пользоваться.
    if group_path:
        sql += " AND (g.path = :gpath OR g.path LIKE :gpath_like)"
    if sku_class:
        sql += " AND coalesce(i.sku_class, '') = :sku_class"
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
        "q": q, "like": f"%{q}%", "st": station_id, "lim": limit, "cid": cid,
        "gpath": group_path, "gpath_like": f"{group_path} / %",
        "sku_class": sku_class})).mappings().all()
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
        SELECT i.id, i.external_uuid, i.code_1c, i.name, i.name_full, i.unit, i.vat_rate,
               i.kind, i.sku_class, i.is_dish,
               coalesce(i.price_owner, 'master') AS price_owner,
               i.deleted, i.created_at, i.updated_at,
               i.group_id, g.path AS group_path, i.purpose, i.classified_by,
               i.gtin, i.marked, i.mark_group, i.adult_only, i.mrc,
               i.shelf_life_days, i.storage_mode,
               i.brand, i.manufacturer, i.country, i.net_qty, i.net_unit, i.pack_qty,
               i.photo_url, i.composition, i.allergens, i.kcal, i.description,
               i.enriched_from, i.enriched_at
        FROM edge.item i
        LEFT JOIN edge.item_group g ON g.id = i.group_id
        WHERE i.id = :id
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
        ORDER BY valid_from DESC
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
    cid = await _require_network_merchandiser(user, db)
    item_id = await _nsi_item_id(db, item_id)
    if body.vat_rate is not None and body.vat_rate not in VAT_CODES:
        raise HTTPException(400, f"Неизвестная ставка НДС: {body.vat_rate}")
    if body.price_owner is not None and body.price_owner not in PRICE_OWNERS:
        raise HTTPException(400, f"Неизвестный владелец цены: {body.price_owner}")
    if body.price_owner not in (None, "station"):
        raise HTTPException(409, "В политике v1 владелец цены — АЗС")

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Нечего менять")
    # Классификация, тронутая человеком, перестаёт быть автоматической: иначе
    # следующий прогон 008_catalog_classify.sql вернёт карточку в ту группу,
    # из которой её только что забрали.
    if {"group_id", "sku_class", "purpose"} & set(fields):
        fields["classified_by"] = "manual"
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = item_id
    await db.execute(
        text(f"UPDATE edge.item SET {sets}, updated_at = now() WHERE id = :id"), fields)
    sent = await _queue_nsi_delta(db, cid, item_id)
    await db.commit()
    return {"ok": True, "changed": [k for k in fields if k != "id"], "станций": sent}


class ClosingDateIn(BaseModel):
    """Дата запрета изменения: та же, что стоит в БП ГИГ."""

    closing_date: date | None = None
    note: str = ""


@router.get("/accounting/closing-date")
async def accounting_closing_date_get(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Действующая граница закрытого периода."""
    cid = await scope_company_id(user, db)
    closing = await get_closing_date(db, cid)
    return {"closing_date": closing.isoformat() if closing else None}


@router.put("/accounting/closing-date")
async def accounting_closing_date_set(
    body: ClosingDateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить или снять дату запрета и разослать её станциям.

    Пустая дата снимает запрет: так бухгалтерия открывает период обратно.
    Отдельного сигнала об этом станциям не нужно — задание несёт саму дату.
    """
    cid = await _require_central_commercial_control(user, db)
    станций = await set_closing_date(
        db, cid, body.closing_date,
        author=getattr(user, "email", None) or "центр", note=body.note)
    await db.commit()
    return {
        "ok": True,
        "closing_date": body.closing_date.isoformat() if body.closing_date else None,
        "станций": станций,
    }


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
    cid = await _require_central_commercial_control(user, db)
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
    await _queue_nsi_delta(db, cid, item_id, body.station_id)
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
    cid = await _require_network_merchandiser(user, db)
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
    await _queue_nsi_delta(db, cid, item_id)
    await db.commit()
    return {"ok": True}


@router.post("/nsi/barcodes/{barcode_id}/retire")
async def nsi_retire_barcode(
    barcode_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Перевести штрихкод в исторические: выпуск сменился, код больше не нужен."""
    cid = await _require_network_merchandiser(user, db)
    res = await db.execute(text("""
        UPDATE edge.barcode SET status = 'historical'
        WHERE id = :id AND status = 'active'
    """), {"id": barcode_id})
    if res.rowcount == 0:
        raise HTTPException(404, "Активный штрихкод не найден")
    owner = (await db.execute(text("SELECT item_id FROM edge.barcode WHERE id = :id"),
                              {"id": barcode_id})).scalar_one()
    await _queue_nsi_delta(db, cid, int(owner))
    await db.commit()
    return {"ok": True}


# -- Приёмка ---------------------------------------------------------------
# Первый документ, который Ledger порождает сам. Две точки ввода: центр заводит
# накладную (в т.ч. из ЭДО), станция принимает товар физически. Ордерная схема
# 1С:Розница: expected -- «к поступлению», accepted -- «принят». Пока документ
# не принят, остатки не двигаются.


class ReceiptLine(BaseModel):
    line_id: str | None = None
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
    upd_codes: list[str] = Field(default_factory=list)
    mark_codes: list[str] = Field(default_factory=list)
    pack_codes: list[str] = Field(default_factory=list)
    requires_mark: bool = False
    no_card: bool = False


class ReceiptIn(BaseModel):
    station_id: int | None = None
    supplier_id: uuid.UUID | None = None
    contract_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    number: str | None = None
    doc_date: str | None = None
    supplier: str | None = None
    contract: str | None = None
    incoming_number: str | None = None
    incoming_date: str | None = None
    comment: str | None = None
    delivery_scheme: str | None = None
    receiving_warehouse: str | None = None
    signing_mode: str | None = None
    signer_name: str | None = None
    mchd_guid: str | None = None
    mchd_registry: str | None = None
    mchd_valid_until: str | None = None
    signature_status: str | None = None
    signature_ref: str | None = None
    lines: list[ReceiptLine] | None = None
    services: list[dict] | None = None
    place: str | None = None
    purpose: str | None = None
    invoice_kind: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    currency: str | None = None
    vat_included: bool | None = None
    vat_deductible: bool | None = None
    declared_goods_total: float | None = None
    declared_services_total: float | None = None
    declared_vat_total: float | None = None
    declared_total: float | None = None
    source_kind: str | None = None
    purchased_by: str | None = None
    payment_kind: str | None = None
    version: int | None = None


class ReceiptSignatureIn(BaseModel):
    signature_status: str
    signature_ref: str | None = None
    signer_name: str | None = None
    mchd_guid: str | None = None
    mchd_registry: str | None = None
    mchd_valid_until: str | None = None
    version: int | None = None


class InventorySheetLine(BaseModel):
    """Строка заполненной ведомости пересчёта.

    Учётного количества здесь нет намеренно: его станция берёт из своего
    журнала в момент проведения. Прислать своё значило бы считать разницу от
    цифры, устаревшей на всё время, пока ведомость была на руках.
    """
    item_uuid: uuid.UUID
    name: str = ""
    barcode: str = ""
    ns_code: int | None = None
    qty_fact: float
    price: float | None = None


class InventorySheetIn(BaseModel):
    document_id: uuid.UUID
    number: str
    place: str
    doc_date: str | None = None
    # Пересчёт считают по местам: излишек зала не должен гасить недостачу склада.
    scope: str = "partial"
    comment: str = ""
    author: str = ""
    # Провести сразу. Без этого лист ложится на станции черновиком, и человек
    # проводит его сам, посмотрев глазами.
    post: bool = True
    lines: list[InventorySheetLine] = []


class ReceiptDistributionLine(BaseModel):
    line_index: int | None = None
    line_id: uuid.UUID | None = None
    qty: float


class ReceiptDistributionIn(BaseModel):
    station_id: int
    lines: list[ReceiptDistributionLine]
    version: int | None = None


class ReceiptScanIn(BaseModel):
    barcode: str | None = None
    delta: float | None = None
    code: str | None = None
    qty: float | None = None
    lines: list[dict] | None = None
    version: int | None = None


class ReceiptAccountingIn(BaseModel):
    version: int | None = None
    note: str | None = None


class ReceiptCanonicalLinkIn(BaseModel):
    supplier_id: uuid.UUID
    contract_id: uuid.UUID
    organization_id: uuid.UUID
    warehouse_id: uuid.UUID
    version: int | None = None
    note: str | None = None


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
        "supplier_id": str(r.supplier_id) if r.supplier_id else None,
        "contract_id": str(r.contract_id) if r.contract_id else None,
        "organization_id": str(r.organization_id) if r.organization_id else None,
        "warehouse_id": str(r.warehouse_id) if r.warehouse_id else None,
        "incoming_number": r.incoming_number, "incoming_date": r.incoming_date,
        "status": r.status, "origin": r.origin, "comment": r.comment,
        "delivery_scheme": r.delivery_scheme,
        "receiving_warehouse": r.receiving_warehouse,
        "signing_mode": r.signing_mode, "signer_name": r.signer_name,
        "author": r.author,
        "mchd_guid": r.mchd_guid, "mchd_registry": r.mchd_registry,
        "mchd_valid_until": r.mchd_valid_until,
        "signature_status": r.signature_status, "signature_ref": r.signature_ref,
        "signed_at": r.signed_at, "distribution": r.distribution or [],
        "lines": lines, "lines_count": len(lines), "diff_count": diff,
        "services": r.services or [], "evidence": r.evidence or {}, "version": r.version,
        "supplier_snapshot": r.supplier_snapshot,
        "contract_snapshot": r.contract_snapshot,
        "organization_snapshot": r.organization_snapshot,
        "warehouse_snapshot": r.warehouse_snapshot,
        "accounting_status": r.accounting_status,
        "accounting_error": r.accounting_error,
        "accounting_revision": r.accounting_revision,
        "content_hash": r.content_hash,
        "total_amount": float(r.total_amount or 0), "vat_amount": float(r.vat_amount or 0),
        "created_at": r.created_at, "updated_at": r.updated_at, "accepted_at": r.accepted_at,
    }


def _recalc(
    lines: list[dict], services: list[dict] | None = None, *, require_lines: bool = True,
) -> tuple[float, float]:
    """Сумма документа по ФАКТУ: платим за принятое, а не за заявленное."""
    try:
        if require_lines or lines:
            normalized_lines = receipt_rules.normalize_lines(lines)
        else:
            normalized_lines = []
        normalized_services = receipt_rules.normalize_services(services)
    except receipt_rules.ReceiptValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    lines[:] = normalized_lines
    if services is not None:
        services[:] = normalized_services
    return receipt_rules.totals(normalized_lines, normalized_services)


def _check_receipt_version(row: StoreReceipt, expected: int | None) -> None:
    if expected is not None and expected != row.version:
        raise HTTPException(409, "Документ изменён другим пользователем; обновите данные")


def _require_receipt_canonical(row: StoreReceipt) -> None:
    if any(value is None for value in (
        row.supplier_id, row.contract_id, row.organization_id, row.warehouse_id,
    )):
        raise HTTPException(
            400, "Для принятия выберите поставщика, договор, организацию и склад")


def _touch_receipt(row: StoreReceipt) -> None:
    row.version = int(row.version or 0) + 1


async def _set_receipt_basis(
    db: AsyncSession, row: StoreReceipt, supplier, incoming_number, incoming_date,
    *, required: bool = True,
) -> None:
    if not required and not (supplier and incoming_number and incoming_date):
        row.supplier = str(supplier or "").strip() or None
        row.incoming_number = str(incoming_number or "").strip() or None
        try:
            row.incoming_date = receipt_rules.parse_datetime(
                incoming_date, "Дата входящего документа")
        except receipt_rules.ReceiptValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
        row.dedup_key = None
        return
    try:
        supplier_value, number_value, date_value = receipt_rules.require_basis(
            supplier, incoming_number, incoming_date)
    except receipt_rules.ReceiptValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    key = receipt_rules.receipt_dedup_key(
        row.supplier_id, supplier_value, number_value, date_value)
    duplicate = (await db.execute(select(StoreReceipt.id).where(
        StoreReceipt.company_id == row.company_id,
        StoreReceipt.dedup_key == key,
        StoreReceipt.id != row.id,
    ).limit(1))).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            409,
            "Накладная этого поставщика с тем же входящим номером и датой уже существует",
        )
    row.supplier = supplier_value
    row.incoming_number = number_value
    row.incoming_date = date_value
    row.dedup_key = key


async def _set_receipt_party(
    db: AsyncSession, row: StoreReceipt, supplier_id: uuid.UUID | None,
    contract_id: uuid.UUID | None, *, required: bool,
    organization_id: uuid.UUID | None = None,
) -> None:
    if supplier_id is None:
        if contract_id is not None:
            raise HTTPException(400, "Договор нельзя выбрать без канонического поставщика")
        if required:
            raise HTTPException(400, "Выберите поставщика из справочника")
        row.supplier_id = None
        row.contract_id = None
        row.organization_id = None
        return
    supplier = (await db.execute(select(Counterparty).where(
        Counterparty.id == supplier_id,
        Counterparty.company_id == row.company_id,
        Counterparty.kind == "external",
    ))).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(400, "Поставщик не найден в этой организации")
    row.supplier_id = supplier.id
    row.supplier = supplier.name
    row.contract_id = None
    if contract_id is None:
        return
    contract = (await db.execute(select(Contract).where(
        Contract.id == contract_id,
        Contract.company_id == row.company_id,
    ))).scalar_one_or_none()
    if contract is None:
        raise HTTPException(400, "Договор не найден в этой организации")
    supplier_keys = {str(supplier.id)}
    if supplier.external_ref:
        supplier_keys.add(str(supplier.external_ref))
    if str(contract.counterparty_id) not in supplier_keys:
        raise HTTPException(400, "Договор принадлежит другому контрагенту")
    contract_kind = str(contract.kind or contract.type or "").casefold().replace(" ", "")
    if "споставщик" not in contract_kind:
        raise HTTPException(400, "Для приёмки нужен договор вида «С поставщиком»")
    organization_key = str(contract.organization_id or "").strip()
    organization = None
    try:
        organization_uuid = uuid.UUID(organization_key)
    except ValueError:
        organization_uuid = None
    if organization_uuid:
        organization = (await db.execute(select(Organization).where(
            Organization.company_id == row.company_id,
            Organization.id == organization_uuid,
        ))).scalar_one_or_none()
    if organization is None and organization_key:
        organization = (await db.execute(select(Organization).where(
            Organization.company_id == row.company_id,
            Organization.external_ref == organization_key,
        ))).scalar_one_or_none()
    if organization is None:
        raise HTTPException(400, "Организация договора не найдена в справочнике")
    if organization_id is not None and organization.id != organization_id:
        raise HTTPException(400, "Выбранная организация не совпадает с договором")
    row.contract_id = contract.id
    row.contract = contract.number
    row.organization_id = organization.id
    row.evidence = {**(row.evidence or {}), "organization_id": str(organization.id)}


async def _set_receipt_warehouse(
    db: AsyncSession, row: StoreReceipt, warehouse_id: uuid.UUID | None,
    *, required: bool,
) -> None:
    if warehouse_id is None:
        if required:
            raise HTTPException(400, "Выберите канонический склад")
        row.warehouse_id = None
        return
    warehouse = (await db.execute(select(Warehouse).where(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == row.company_id,
    ))).scalar_one_or_none()
    if warehouse is None:
        raise HTTPException(400, "Склад не найден в этой организации")
    row.warehouse_id = warehouse.id
    row.receiving_warehouse = warehouse.name


def _movement_item_key(line: dict, index: int) -> str:
    return receipt_rules.movement_item_key(line, index)


async def _record_receipt_acceptance(
    db: AsyncSession, row: StoreReceipt, user_id: uuid.UUID,
) -> None:
    await receipt_rules.record_acceptance(db, row, user_id)


async def _record_receipt_distribution(
    db: AsyncSession, row: StoreReceipt, allocation_id: str,
    allocation_lines: list[dict], user_id: uuid.UUID,
) -> None:
    movements = (await db.execute(select(StoreReceiptStockMovement).where(
        StoreReceiptStockMovement.company_id == row.company_id,
        StoreReceiptStockMovement.receipt_id == row.id,
    ))).scalars().all()
    existing = {movement.idempotency_key for movement in movements}
    acceptance = {str(movement.line_id): movement for movement in movements
                  if movement.kind == "receipt_acceptance" and movement.line_id}
    warehouse = str(row.receiving_warehouse or "").strip()
    for item in allocation_lines:
        index = int(item["line_index"])
        line = (row.lines or [])[index]
        line_id = uuid.UUID(str(line["line_id"]))
        key = f"receipt:{row.id}:distribution:{allocation_id}:{line_id}"
        if key in existing:
            continue
        quantity = float(item["qty"])
        unit_cost = float(acceptance[str(line_id)].unit_cost) if str(line_id) in acceptance else float(
            line.get("price") or 0)
        db.add(StoreReceiptStockMovement(
            company_id=row.company_id, receipt_id=row.id, allocation_id=allocation_id,
            line_id=line_id, line_index=index, station_id=None,
            warehouse_id=row.warehouse_id, warehouse=warehouse,
            item_key=_movement_item_key(line, index),
            item_uuid=str(line.get("nomenclature_ref") or "") or None,
            barcode=str(line.get("barcode") or "") or None,
            quantity=-quantity, unit_cost=unit_cost,
            amount=-round(quantity * unit_cost, 2),
            kind="central_distribution", idempotency_key=key, created_by=user_id,
        ))


async def _reverse_receipt_acceptance(
    db: AsyncSession, row: StoreReceipt, user_id: uuid.UUID,
) -> None:
    movements = (await db.execute(select(StoreReceiptStockMovement).where(
        StoreReceiptStockMovement.company_id == row.company_id,
        StoreReceiptStockMovement.receipt_id == row.id,
    ).with_for_update())).scalars().all()
    if any(m.kind == "central_distribution" for m in movements):
        raise HTTPException(409, "Сначала отмените распределение по станциям")
    existing = {m.idempotency_key for m in movements}
    for movement in movements:
        if movement.kind != "receipt_acceptance":
            continue
        key = f"receipt:{row.id}:reverse:{movement.id}"
        if key in existing:
            continue
        db.add(StoreReceiptStockMovement(
            company_id=row.company_id, receipt_id=row.id, reversal_of_id=movement.id,
            line_id=movement.line_id, line_index=movement.line_index,
            station_id=movement.station_id, warehouse_id=movement.warehouse_id,
            warehouse=movement.warehouse, item_key=movement.item_key,
            item_uuid=movement.item_uuid, barcode=movement.barcode,
            quantity=-float(movement.quantity), unit_cost=float(movement.unit_cost),
            amount=-float(movement.amount), kind="receipt_reversal",
            idempotency_key=key, created_by=user_id,
        ))


def _дата_накладной(value) -> str | None:
    """Дата бумажного документа — календарная дата станции, без времени.

    Центр хранит моменты в UTC, станция живёт по Москве и ждёт «ГГГГ-ММ-ДД»
    (`ValidateReceipt` другой формат не принимает). Полный ISO с временем ронял
    проверку черновика: «дата входящего документа должна быть в формате
    ГГГГ-ММ-ДД» — оператор видел красную строку на документе, к которому мы его
    и позвали. А `.date()` от UTC съезжает на день назад: накладная от 31.08
    хранится как 2026-08-30T21:00Z и стала бы тридцатым.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/Moscow")).date().isoformat()


def _receipt_downlink_payload(row: StoreReceipt) -> dict:
    evidence = row.evidence or {}
    lines = _normalized_receipt_lines(row)
    purposes = {str(line.get("purpose") or "") for line in lines if line.get("purpose")}
    return {
        "id": str(row.id), "document_id": str(row.id), "number": row.number,
        "supplier": row.supplier,
        "supplier_id": str(row.supplier_id) if row.supplier_id else None,
        "contract": row.contract,
        "contract_id": str(row.contract_id) if row.contract_id else None,
        "organization_id": (str(row.organization_id)
                            if getattr(row, "organization_id", None) else None),
        "warehouse_id": (str(row.warehouse_id)
                         if getattr(row, "warehouse_id", None) else None),
        "incoming_number": row.incoming_number,
        "incoming_date": _дата_накладной(row.incoming_date),
        "doc_date": row.doc_date.isoformat() if row.doc_date else None,
        "place": evidence.get("place") or "",
        "purpose": evidence.get("purpose") or (next(iter(purposes)) if len(purposes) == 1 else ""),
        "invoice_kind": evidence.get("invoice_kind") or "",
        "invoice_number": evidence.get("invoice_number") or row.incoming_number or "",
        "invoice_date": evidence.get("invoice_date")
                        or _дата_накладной(row.incoming_date) or "",
        "currency": evidence.get("currency") or "",
        "vat_included": evidence.get("vat_included"),
        "vat_deductible": evidence.get("vat_deductible"),
        "services": [{
            "line_id": service.get("line_id") or "",
            "key": service.get("key") or "",
            "name": service.get("name") or "",
            "sum": float(service.get("amount") or service.get("sum") or 0),
            "vat_rate": service.get("vat_rate") or "",
            "into_cost": bool(service.get("into_cost")),
        } for service in row.services or []],
        # Транспортная накладная, принявший и три итога из подвала бумаги.
        # Станция сверяет свой расчёт с этими числами: разошлись на копейку —
        # видно сразу, а не после выгрузки в бухгалтерию.
        "waybill": evidence.get("waybill") or "",
        "responsible": evidence.get("responsible") or "",
        "paper_net": float(evidence.get("paper_net") or 0),
        "paper_vat": float(evidence.get("paper_vat") or 0),
        "paper_gross": float(evidence.get("paper_gross") or 0),
        "source_kind": evidence.get("source_kind") or "paper_invoice",
        "purchased_by": evidence.get("purchased_by") or "",
        "payment_kind": evidence.get("payment_kind") or "",
        "comment": row.comment or "",
        "delivery_scheme": row.delivery_scheme,
        "receiving_warehouse": row.receiving_warehouse,
        "signing_mode": row.signing_mode, "signer_name": row.signer_name,
        "mchd_guid": row.mchd_guid, "mchd_registry": row.mchd_registry,
        "mchd_valid_until": row.mchd_valid_until.isoformat() if row.mchd_valid_until else None,
        "signature_status": row.signature_status, "signature_ref": row.signature_ref,
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "lines": [{
            "line_id": line.get("line_id") or "",
            "item_uuid": line.get("nomenclature_ref") or "",
            "name": line.get("name") or "", "barcode": line.get("barcode") or "",
            "qty_expected": float(line.get("qty_expected") or 0),
            "price": float(line.get("price") or 0), "vat_rate": line.get("vat_rate") or "",
            # Стоимость строки и налог как в бумаге: цена там округлена до
            # копеек, а стоимость посчитана от неокруглённой — перемножение
            # цены на количество расходится с накладной.
            "sum": float(line.get("sum") or line.get("amount") or 0),
            "vat_set": float(line.get("vat_set") or line.get("vat_amount") or 0),
            "unit": line.get("unit") or "", "pack_factor": float(line.get("pack_factor") or 0),
            "purpose": line.get("purpose") or "", "series": line.get("series") or "",
            "expiry": line.get("expiry") or "",
            "retail_price": float(line.get("retail_price") or 0),
            "markup": float(line.get("markup") or 0),
            "mark_codes": line.get("upd_codes") or line.get("mark_codes") or [],
            "requires_mark": bool(line.get("requires_mark")),
        } for line in lines],
    }


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
    supplier_id: uuid.UUID | None = Query(None, description="канонический поставщик"),
    contract_id: uuid.UUID | None = Query(None, description="канонический договор"),
    organization_id: uuid.UUID | None = Query(None, description="каноническая организация"),
    warehouse_id: uuid.UUID | None = Query(None, description="канонический склад"),
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
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
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

    cid = access.company_id
    now = datetime.now(timezone.utc)
    destination = str(station_id) if station_id else "ЦС"
    number = "УПД-%s-%s" % (destination, now.strftime("%y%m%d-%H%M"))
    lines = [{
        "nomenclature_ref": None,
        "name": l["name"], "barcode": l["barcode"] or None,
        "supplier_article": l.get("supplier_article") or None,
        "qty_expected": l["qty_expected"], "qty_fact": 0,
        "price": l["price"], "vat_rate": l["vat_rate"] or None,
        "vat_amount": l.get("vat_amount") or 0, "amount": 0,
        "upd_codes": l["mark_codes"], "mark_codes": [], "pack_codes": l["pack_codes"],
        "requires_mark": bool(l["mark_codes"]),
    } for l in parsed["lines"]]

    # Сопоставляем строки УПД с карточками каталога по штрихкоду СРАЗУ при
    # загрузке. Иначе приход уедет на станцию под пустой карточкой и разъедется
    # с продажами кассы, которые несут реальный GUID — именно на маркированной
    # высокооборотке (табак, вода), ради которой ЭДО и вводят. Что не нашлось —
    # опознает станция при скане (карточка приезжает к ней репликой).
    коды_строк = [l["barcode"] for l in lines if l["barcode"]]
    if коды_строк:
        нашлось = (await db.execute(text("""
            SELECT b.code, i.external_uuid::text
            FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
            WHERE b.status = 'active' AND b.code = ANY(:codes)
        """), {"codes": коды_строк})).all()
        по_коду = {c: u for c, u in нашлось}
        for l in lines:
            if l["barcode"] and l["barcode"] in по_коду:
                l["nomenclature_ref"] = по_коду[l["barcode"]]

    _recalc(lines)
    lines, services = receipt_rules.assign_document_line_ids(lines, [])
    row = StoreReceipt(
        id=uuid.uuid4(),
        company_id=cid, station_id=station_id, number=number, doc_date=now,
        supplier=parsed["supplier"] or None,
        incoming_number=parsed["incoming_number"] or None,
        # «К поступлению»: товар заявлен, но на складе его ещё нет — ровно
        # смысл ордерной схемы. Приёмщик переведёт в «принят», пересчитав.
        status="expected", origin="edo", lines=lines, services=services,
        delivery_scheme=delivery_scheme, receiving_warehouse=receiving_warehouse,
        signing_mode=signing_mode, signer_name=signer_name,
        mchd_guid=mchd_guid, mchd_registry=mchd_registry,
        mchd_valid_until=valid_until, signature_status="pending",
        total_amount=0, vat_amount=0,
        evidence={
            "upd_sha256": hashlib.sha256(raw).hexdigest(),
            "file_name": file.filename,
            "invoice_kind": "УПД",
            "invoice_number": parsed.get("incoming_number"),
            "invoice_date": parsed.get("incoming_date"),
        },
        comment="Загружен из УПД поставщика",
    )
    await _set_receipt_party(
        db, row, supplier_id, contract_id, required=False,
        organization_id=organization_id)
    await _set_receipt_warehouse(db, row, warehouse_id, required=False)
    await _set_receipt_basis(
        db, row, row.supplier, parsed.get("incoming_number"),
        parsed.get("incoming_date"),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Такая накладная уже загружена") from exc
    await db.refresh(row)

    out = _receipt_out(row)
    out["parsed"] = {"marked_lines": parsed["marked_lines"],
                     "total_codes": parsed["total_codes"]}
    return out


@router.post("/receipts/{receipt_id}/send-to-station")
async def send_receipt_to_station(
    receipt_id: uuid.UUID,
    version: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить заготовку приёмки на станцию.

    Станция за CGNAT — постучаться к ней нельзя, поэтому кладём задание в
    очередь: агент заберёт его своим тактом и создаст документ у себя. Пока не
    заберёт, задание висит и будет предложено снова.
    """
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, version)
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят — отправлять нечего")
    if row.delivery_scheme != "supplier_to_station" or row.station_id is None:
        raise HTTPException(409, "Центральный приход не отправляется как поставка на АЗС")
    try:
        _require_receipt_canonical(row)
    except HTTPException as exc:
        raise HTTPException(
            409, "Перед отправкой выберите поставщика, договор, организацию и склад") from exc

    await _set_receipt_party(
        db, row, row.supplier_id, row.contract_id, required=True,
        organization_id=row.organization_id)
    await _set_receipt_warehouse(db, row, row.warehouse_id, required=True)
    await _set_receipt_basis(db, row, row.supplier, row.incoming_number, row.incoming_date)
    lines = _normalized_receipt_lines(row)
    _recalc(lines, list(row.services or []))
    payload = _receipt_downlink_payload(row)
    idempotency_key = f"receipt:{row.id}:expected"
    task = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == cid,
        EdgeDownlink.idempotency_key == idempotency_key,
    ).with_for_update())).scalar_one_or_none()
    if task is None:
        task = (await db.execute(select(EdgeDownlink).where(
            EdgeDownlink.company_id == cid,
            EdgeDownlink.station_id == row.station_id,
            EdgeDownlink.kind == "goods_receipt_expected",
            EdgeDownlink.payload["id"].astext == str(row.id),
        ).order_by(EdgeDownlink.created_at).limit(1).with_for_update())).scalar_one_or_none()
        if task is not None:
            task.idempotency_key = idempotency_key
    repeated = task is not None
    if task is None:
        task = EdgeDownlink(
            company_id=cid, station_id=row.station_id,
            kind="goods_receipt_expected", payload=payload,
            note="приёмка %s" % row.number, idempotency_key=idempotency_key,
        )
        db.add(task)
    elif task.payload != payload:
        task.station_id = row.station_id
        task.payload = payload
        task.delivered_at = None
        task.acked_at = None
        task.cancelled_at = None
        task.cancelled_by = None
    if row.status == "draft":
        row.status = "expected"
        _touch_receipt(row)
    await db.commit()
    return {"ok": True, "task_id": str(task.id), "idempotent": repeated,
            "station_id": row.station_id, "number": row.number, "lines": len(lines)}


@router.post("/stations/{station_id}/inventory-sheet")
async def send_inventory_sheet_to_station(
    station_id: int,
    body: InventorySheetIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить на станцию заполненную ведомость пересчёта.

    Остаток станции ведёт агент: раз в час он присылает снимок своего журнала, и
    центр этот снимок зеркалит. Поэтому исправить остаток запросом к базе центра
    нельзя — до ближайшего снимка, который вернёт всё как было.

    Пересчёт же часто идёт на бумаге: ведомость печатают здесь, человек обходит
    зал и вписывает фактическое количество, лист возвращается в центр. Эта ручка
    отдаёт заполненный лист станции заданием — она примет его своим обычным
    документом пересчёта, проведёт и пришлёт результат наверх пакетом.

    Учётное количество в задание не кладём: пока лист ходил туда-обратно, шли
    продажи, и разницу станция считает от того, что у неё есть сейчас.
    """
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    if not body.lines:
        raise HTTPException(422, "В ведомости нет строк")
    без_карточки = [l.name for l in body.lines if not l.item_uuid]
    if без_карточки:
        # Проведение на станции считает остаток по карточке. Строка без неё
        # уронила бы применение целиком уже на станции — скажем об этом здесь,
        # пока ведомость можно поправить.
        raise HTTPException(422, "Строки без карточки товара: " + ", ".join(без_карточки[:5]))

    payload = {
        "id": str(body.document_id),
        "number": body.number,
        "doc_date": body.doc_date,
        "place": body.place,
        "scope": body.scope,
        "comment": body.comment,
        "author": body.author,
        "post": body.post,
        "lines": [{"item_uuid": str(l.item_uuid), "name": l.name, "barcode": l.barcode,
                   "ns_code": l.ns_code, "qty_fact": float(l.qty_fact),
                   "price": float(l.price or 0)} for l in body.lines],
    }
    # Ключ идемпотентности — сам документ: повтор отправки правит одно задание,
    # а не плодит второй пересчёт того же листа.
    idempotency_key = f"inventory:{body.document_id}"
    task = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == access.company_id,
        EdgeDownlink.idempotency_key == idempotency_key,
    ).with_for_update())).scalar_one_or_none()
    repeated = task is not None
    if task is None:
        task = EdgeDownlink(
            company_id=access.company_id, station_id=station_id,
            kind="inventory_expected", payload=payload,
            note="пересчёт %s (%s)" % (body.number, body.place),
            idempotency_key=idempotency_key,
        )
        db.add(task)
    elif task.payload != payload:
        task.station_id = station_id
        task.payload = payload
        task.delivered_at = None
        task.acked_at = None
        task.cancelled_at = None
        task.cancelled_by = None
    await db.commit()
    return {"ok": True, "task_id": str(task.id), "idempotent": repeated,
            "station_id": station_id, "number": body.number,
            "place": body.place, "lines": len(body.lines)}


@router.post("/receipts/{receipt_id}/signature")
async def record_receipt_signature(
    receipt_id: uuid.UUID,
    body: ReceiptSignatureIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Зафиксировать уже выполненную подпись оператора ЭДО и полномочие МЧД."""
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, body.version)
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
    _touch_receipt(row)
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
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, body.version)
    if row.delivery_scheme != "central_warehouse" or row.status != "accepted":
        raise HTTPException(409, "Распределять можно только принятый центральный приход")
    agent = (await db.execute(select(EdgeAgent.id).where(
        EdgeAgent.company_id == cid, EdgeAgent.station_id == body.station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(400, "АЗС не подключена к «Магазину»")

    lines = row.lines or []
    line_indexes = {
        str(line.get("line_id")): index
        for index, line in enumerate(lines)
        if line.get("line_id")
    }
    distribution = list(row.distribution or [])
    allocation_lines = []
    seen = set()
    for requested in body.lines:
        requested_line_id = str(requested.line_id) if requested.line_id else None
        idx = requested.line_index
        if requested_line_id:
            resolved = line_indexes.get(requested_line_id)
            if resolved is None or (idx is not None and idx != resolved):
                raise HTTPException(400, "Некорректный line_id распределения")
            idx = resolved
        if idx is None:
            raise HTTPException(400, "Укажите line_id строки распределения")
        qty = float(requested.qty)
        if (idx < 0 or idx >= len(lines) or not math.isfinite(qty)
                or qty <= 0 or qty > 1_000_000):
            raise HTTPException(400, "Некорректные строки распределения")
        line_id = str(lines[idx].get("line_id") or "")
        if not line_id or line_id in seen:
            raise HTTPException(400, "Некорректные строки распределения")
        seen.add(line_id)
        allocation_lines.append({
            "line_id": line_id, "line_index": idx, "qty": round(qty, 3),
        })
    if not allocation_lines:
        raise HTTPException(400, "Укажите количество хотя бы по одной позиции")
    allocation_id, _ = receipt_rules.allocation_identity(
        row.id, body.station_id, allocation_lines)
    def canonical_allocation(items):
        result = []
        for item in items or []:
            idx = int(item.get("line_index", -1))
            line_id = str(item.get("line_id") or "")
            if not line_id and 0 <= idx < len(lines):
                line_id = str(lines[idx].get("line_id") or "")
            result.append((line_id, round(float(item.get("qty") or 0), 3)))
        return sorted(result)

    previous = next((item for item in distribution
                     if int(item.get("station_id") or 0) == body.station_id
                     and canonical_allocation(item.get("lines"))
                     == canonical_allocation(allocation_lines)), None)
    if previous is not None:
        allocation_id = str(previous.get("id") or allocation_id)
    idempotency_key = f"receipt:{row.id}:distribution:{allocation_id}"
    if previous is not None:
        task = (await db.execute(select(EdgeDownlink).where(
            EdgeDownlink.company_id == cid,
            EdgeDownlink.idempotency_key == idempotency_key,
        ))).scalar_one_or_none()
        if task is None:
            task = (await db.execute(select(EdgeDownlink).where(
                EdgeDownlink.company_id == cid,
                EdgeDownlink.kind == "incoming_transfer",
                EdgeDownlink.note == f"central-distribution:{row.id}:{allocation_id}"[:300],
            ).limit(1))).scalar_one_or_none()
            if task is not None:
                task.idempotency_key = idempotency_key
        return {"ok": True, "idempotent": True,
                "task_id": str(task.id) if task else f"central:{row.id}:{allocation_id}",
                "station_id": body.station_id, "lines": len(allocation_lines)}

    used: dict[str, float] = {}
    for allocation in distribution:
        for item in allocation.get("lines") or []:
            idx = int(item.get("line_index", -1))
            line_id = str(item.get("line_id") or "")
            if not line_id and 0 <= idx < len(lines):
                line_id = str(lines[idx].get("line_id") or "")
            if line_id:
                used[line_id] = used.get(line_id, 0) + float(item.get("qty") or 0)

    ledger_rows = (await db.execute(select(
        StoreReceiptStockMovement.line_id,
        func.sum(-StoreReceiptStockMovement.quantity),
    ).where(
        StoreReceiptStockMovement.company_id == cid,
        StoreReceiptStockMovement.receipt_id == row.id,
        StoreReceiptStockMovement.kind == "central_distribution",
    ).group_by(StoreReceiptStockMovement.line_id))).all()
    for line_id, quantity in ledger_rows:
        key = str(line_id)
        used[key] = max(used.get(key, 0), float(quantity or 0))

    task_lines = []
    for requested in allocation_lines:
        idx, qty = requested["line_index"], requested["qty"]
        source = lines[idx]
        line_id = str(source["line_id"])
        available = float(source.get("qty_fact") or 0) - used.get(line_id, 0)
        if qty > available + 1e-6:
            raise HTTPException(400, f"По строке {idx + 1} доступно только {available:g}")
        marks = source.get("mark_codes") or []
        selected_marks = []
        if source.get("requires_mark") or marks:
            if abs(qty - round(qty)) > 1e-6:
                raise HTTPException(400, "Маркированный товар распределяется поштучно")
            offset = int(round(used.get(line_id, 0)))
            selected_marks = marks[offset:offset + int(round(qty))]
            if len(selected_marks) != int(round(qty)):
                raise HTTPException(400, f"По строке {idx + 1} недостаточно кодов маркировки")
        task_lines.append({
            "line_id": line_id,
            "item_uuid": source.get("nomenclature_ref") or "",
            "name": source.get("name") or "", "barcode": source.get("barcode") or "",
            "qty_sent": qty, "mark_codes": selected_marks,
            "unknown": not bool(source.get("nomenclature_ref")),
        })
    task_id = f"central:{row.id}:{allocation_id}"
    now = datetime.now(timezone.utc)
    task = EdgeDownlink(
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
        idempotency_key=idempotency_key,
    )
    db.add(task)
    await _record_receipt_distribution(db, row, allocation_id, allocation_lines, user.id)
    distribution.append({
        "id": allocation_id, "station_id": body.station_id,
        "created_at": now.isoformat(), "lines": allocation_lines,
    })
    row.distribution = distribution
    _touch_receipt(row)
    await db.commit()
    return {"ok": True, "idempotent": False, "task_id": task_id,
            "station_id": body.station_id,
            "lines": len(task_lines)}


@router.post("/receipts/{receipt_id}/scan")
async def scan_receipt_barcode(
    receipt_id: uuid.UUID,
    body: ReceiptScanIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Атомарно принять один скан USB/радиосканера в центральном складе."""
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, body.version)
    if row.status == "accepted":
        raise HTTPException(409, "Документ уже принят — сканирование закрыто")
    if row.delivery_scheme != "central_warehouse":
        raise HTTPException(409, "Прямую поставку сканируют на агенте АЗС")

    code = body.barcode or body.code
    product_barcode, mark_code, scan_type = _parse_scanned_product(code)
    requested_delta = body.delta if body.delta is not None else body.qty
    delta = float(requested_delta if requested_delta is not None else 1)
    if not math.isfinite(delta) or delta == 0 or abs(delta) > 100000:
        raise HTTPException(400, "Дельта сканирования должна быть ненулевой")
    if mark_code and abs(delta) != 1:
        raise HTTPException(400, "Код маркировки добавляется или снимается по одной штуке")
    lines = _normalized_receipt_lines(row)
    if body.lines is not None and body.lines != lines:
        raise HTTPException(409, "Снимок строк устарел; обновите документ и повторите скан")

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
        current_codes = list(line.get("mark_codes") or [])
        existing_index = next((index for index, existing in enumerate(current_codes)
                               if canonical == _canonical_mark_code(existing)), None)
        if delta > 0:
            if any(canonical == _canonical_mark_code(existing)
                   for candidate in lines for existing in candidate.get("mark_codes") or []):
                raise HTTPException(409, "Этот код маркировки уже отсканирован — количество не изменено")
            expected = {_canonical_mark_code(value) for value in line.get("upd_codes") or []}
            if expected and canonical not in expected:
                raise HTTPException(409, "Кода маркировки нет в УПД поставщика — товар не принят")
            current_codes.append(mark_code)
        elif existing_index is None:
            raise HTTPException(409, "Этот код маркировки не был отсканирован")
        else:
            current_codes.pop(existing_index)
        line["mark_codes"] = current_codes
        line["requires_mark"] = True
    new_quantity = round(float(line.get("qty_fact") or 0) + delta, 3)
    if new_quantity < 0:
        raise HTTPException(409, "Фактическое количество не может стать отрицательным")
    line["qty_fact"] = new_quantity
    total, vat = _recalc(lines, list(row.services or []))
    row.lines = lines
    row.total_amount = total
    row.vat_amount = vat
    _touch_receipt(row)
    await db.commit()
    await db.refresh(row)
    result = _receipt_out(row)
    result["scan"] = {
        "type": scan_type, "barcode": product_barcode,
        "line_index": line_index, "qty_added": delta,
        "name": line.get("name") or "",
    }
    return result


@router.get("/receipts-report")
async def store_receipts_report(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отчёт «Приёмка» за период: реестр накладных со составом.

    Отдельный путь, а не `/receipts`: тот занят журналом документов приёмки, и
    FastAPI отдавал отчёту его ответ — экран падал на отсутствующем периоде.
    Один путь на два разных ресурса не работает, как бы ни хотелось.
    """
    access = await _receipt_access(user, db)
    selected = _stations(stations)
    if not access.network:
        try:
            requested = {int(value) for value in selected or []}
        except ValueError as exc:
            raise HTTPException(400, "stations должен содержать коды АЗС") from exc
        if requested and not requested.issubset(access.station_ids):
            raise HTTPException(403, "Нет полномочий на одну из запрошенных АЗС")
        selected = [str(value) for value in sorted(requested or access.station_ids)]
    svc = GoodsDashboardService(db, access.company_id)
    return await svc.receipts(date.fromisoformat(date_from), date.fromisoformat(date_to), selected)


@router.get("/receipts")
async def list_receipts(
    station_id: int | None = Query(None),
    station_ids: str | None = Query(None, description="коды АЗС через запятую"),
    status: str | None = Query(None, description="draft|expected|accepted"),
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Журнал приёмок -- то же окно, что у товароведа в 1С."""
    access = await _receipt_access(user, db)
    cid = access.company_id
    requested: set[int] = set()
    if station_id is not None:
        requested.add(station_id)
    if station_ids:
        try:
            requested.update(int(value.strip()) for value in station_ids.split(",") if value.strip())
        except ValueError as exc:
            raise HTTPException(400, "station_ids должен содержать коды АЗС через запятую") from exc
    requested, include_central = _receipt_list_scope(access, requested)
    q = select(StoreReceipt).where(StoreReceipt.company_id == cid)
    if requested:
        station_scope = StoreReceipt.station_id.in_(requested)
        if include_central:
            station_scope = or_(station_scope, StoreReceipt.station_id.is_(None))
        q = q.where(station_scope)
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
    access = await _receipt_access(user, db)
    cid = access.company_id
    delivery_scheme = body.delivery_scheme or "supplier_to_station"
    signing_mode = body.signing_mode or "office_director"
    signature_status = body.signature_status or "pending"
    _require_receipt_station(access, body.station_id)
    valid_until = _parse_mchd_date(body.mchd_valid_until)
    _validate_receipt_route(
        delivery_scheme, body.station_id, body.receiving_warehouse,
        signing_mode, body.signer_name, body.mchd_guid, body.mchd_registry,
        valid_until, signature_status, body.signature_ref)
    lines = [line.model_dump() for line in body.lines or []]
    services = list(body.services or [])
    total, vat = _recalc(lines, services, require_lines=False)
    try:
        lines, services = receipt_rules.assign_document_line_ids(lines, services)
    except receipt_rules.ReceiptValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    now = datetime.now(timezone.utc)
    try:
        doc_date = receipt_rules.parse_datetime(body.doc_date, "Дата документа") or now
    except receipt_rules.ReceiptValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Номер по умолчанию -- дата и станция: различимый документ нужен сразу,
    # сквозная нумерация появится вместе со справочником поставщиков.
    destination = str(body.station_id) if body.station_id else "ЦС"
    number = body.number or ("П-%s-%s" % (destination, now.strftime("%y%m%d-%H%M")))

    row = StoreReceipt(
        id=uuid.uuid4(), company_id=cid, station_id=body.station_id,
        number=number, doc_date=doc_date,
        supplier=body.supplier, contract=body.contract, incoming_number=body.incoming_number,
        status="draft", origin="center", lines=lines, services=services,
        delivery_scheme=delivery_scheme,
        receiving_warehouse=body.receiving_warehouse,
        signing_mode=signing_mode, signer_name=body.signer_name,
        mchd_guid=body.mchd_guid, mchd_registry=body.mchd_registry,
        mchd_valid_until=valid_until, signature_status=signature_status,
        signature_ref=body.signature_ref,
        signed_at=now if signature_status == "signed" else None,
        total_amount=total, vat_amount=vat, comment=body.comment,
        evidence={key: value for key, value in {
            "place": body.place, "purpose": body.purpose,
            "invoice_kind": body.invoice_kind, "invoice_number": body.invoice_number,
            "invoice_date": body.invoice_date, "currency": body.currency,
            "vat_included": body.vat_included, "vat_deductible": body.vat_deductible,
            "declared_goods_total": body.declared_goods_total,
            "declared_services_total": body.declared_services_total,
            "declared_vat_total": body.declared_vat_total,
            "declared_total": body.declared_total, "source_kind": body.source_kind,
            "purchased_by": body.purchased_by, "payment_kind": body.payment_kind,
        }.items() if value is not None},
    )
    await _set_receipt_party(
        db, row, body.supplier_id, body.contract_id, required=False,
        organization_id=body.organization_id)
    await _set_receipt_warehouse(db, row, body.warehouse_id, required=False)
    await _set_receipt_basis(
        db, row, row.supplier, body.incoming_number, body.incoming_date, required=False)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Такая накладная уже существует") from exc
    await db.refresh(row)
    return _receipt_out(row)


@router.get("/receipts/duplicate-audit")
async def receipt_duplicate_audit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Только dry-run: сомнительные пары не сливаются без решения человека."""
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Аудит дублей доступен товароведу сети")
    rows = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.company_id == access.company_id,
    ))).scalars().all()
    plan = receipt_rules.duplicate_plan(rows)
    return {"mode": "dry-run", "apply_supported": False, "candidates": plan,
            "total": len(plan)}


@router.get("/receipts/orphan-audit")
async def receipt_orphan_audit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Приёмки, принятые в центре, о которых станция не знает.

    Схема «поставщик → станция» означает, что товар физически принимает
    приёмщик на АЗС, и остаток ведёт станция. Документ такой схемы, отмеченный
    принятым в центре, — разрыв: движения записаны здесь, а на станции прихода
    нет, и её остаток уходит в минус при первой же продаже.

    Случай не выдуманный: 208, август 2026 — тринадцать накладных на 270 570 ₽
    были приняты в центре в обход правила, заготовки на станцию сняты, и товар
    оказался нигде. Экран разбора смены при этом честно показывал «у нас ноль,
    на полке есть», но причину назвать не мог.

    Только чтение: что делать с каждым документом — решение человека. Слепая
    переотправка задвоит остаток там, где товар успел прийти другим путём.
    """
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Аудит приёмок доступен товароведу сети")
    строки = (await db.execute(text("""
        SELECT r.id, r.number, r.station_id, left(r.doc_date::text, 10) AS doc_date,
               r.total_amount, r.author,
               (SELECT count(*) FROM store_receipt_stock_movements m
                 WHERE m.receipt_id = r.id) AS movements,
               (SELECT count(*) FROM edge_downlink d
                 WHERE d.company_id = r.company_id
                   AND d.kind = 'goods_receipt_expected'
                   AND d.payload->>'id' = r.id::text
                   AND d.cancelled_at IS NULL) AS live_tasks
          FROM store_receipts r
         WHERE r.company_id = :c
           AND r.delivery_scheme = 'supplier_to_station'
           AND r.status = 'accepted'
           AND r.origin = 'station'
           AND NOT EXISTS (
               SELECT 1 FROM edge_downlink d
                WHERE d.company_id = r.company_id
                  AND d.kind = 'goods_receipt_expected'
                  AND d.payload->>'id' = r.id::text
                  AND d.acked_at IS NOT NULL AND d.cancelled_at IS NULL)
           AND r.author IS DISTINCT FROM 'АдминистраторАЗК'
         ORDER BY r.doc_date
    """), {"c": str(access.company_id)})).mappings().all()
    итог = [dict(р) | {"id": str(р["id"]),
                       "total_amount": float(р["total_amount"] or 0)}
            for р in строки]
    return {
        "mode": "dry-run",
        "total": len(итог),
        "amount": round(sum(р["total_amount"] for р in итог), 2),
        "rows": итог,
        "about": (
            "Документы приняты в центре, но станция о них не знает. Прежде чем "
            "передавать их вниз, сверьте построчно: товар, успевший прийти "
            "другим путём, задвоится."
        ),
    }


@router.get("/receipts/{receipt_id}")
async def get_receipt(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    return _receipt_out(row)


@router.put("/receipts/{receipt_id}")
async def update_receipt(
    receipt_id: uuid.UUID,
    body: ReceiptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Правка документа. Принятый не редактируется: это уже движение остатков."""
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, body.version)
    if row.status in ("accepted", "reversed"):
        raise HTTPException(409, "Документ уже принят -- правка запрещена")

    fields = body.model_fields_set
    station_id = body.station_id if "station_id" in fields else row.station_id
    delivery_scheme = body.delivery_scheme if "delivery_scheme" in fields else row.delivery_scheme
    receiving_warehouse = (body.receiving_warehouse if "receiving_warehouse" in fields
                           else row.receiving_warehouse)
    signing_mode = body.signing_mode if "signing_mode" in fields else row.signing_mode
    signer_name = body.signer_name if "signer_name" in fields else row.signer_name
    mchd_guid = body.mchd_guid if "mchd_guid" in fields else row.mchd_guid
    mchd_registry = body.mchd_registry if "mchd_registry" in fields else row.mchd_registry
    valid_until = (_parse_mchd_date(body.mchd_valid_until)
                   if "mchd_valid_until" in fields else row.mchd_valid_until)
    signature_status = (body.signature_status if "signature_status" in fields
                        else row.signature_status)
    signature_ref = body.signature_ref if "signature_ref" in fields else row.signature_ref
    _require_receipt_station(access, station_id)
    _validate_receipt_route(
        delivery_scheme, station_id, receiving_warehouse,
        signing_mode, signer_name, mchd_guid, mchd_registry,
        valid_until, signature_status, signature_ref)
    lines = ([line.model_dump() for line in body.lines or []]
             if "lines" in fields else _normalized_receipt_lines(row))
    services = list(body.services or []) if "services" in fields else list(row.services or [])
    total, vat = _recalc(lines, services, require_lines=False)
    try:
        lines, services = receipt_rules.assign_document_line_ids(
            lines, services,
            existing_lines=_normalized_receipt_lines(row),
            existing_services=list(row.services or []),
        )
    except receipt_rules.ReceiptValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    row.lines = lines
    row.services = services
    row.total_amount = total
    row.vat_amount = vat
    row.station_id = station_id
    row.delivery_scheme = delivery_scheme
    row.receiving_warehouse = receiving_warehouse
    row.signing_mode = signing_mode
    row.signer_name = signer_name
    row.mchd_guid = mchd_guid
    row.mchd_registry = mchd_registry
    row.mchd_valid_until = valid_until
    row.signature_status = signature_status
    row.signature_ref = signature_ref
    row.signed_at = (datetime.now(timezone.utc) if signature_status == "signed"
                     and row.signed_at is None else row.signed_at)
    if "comment" in fields:
        row.comment = body.comment
    if "number" in fields and body.number:
        row.number = body.number
    if "doc_date" in fields:
        try:
            row.doc_date = receipt_rules.parse_datetime(body.doc_date, "Дата документа")
        except receipt_rules.ReceiptValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
        if row.doc_date is None:
            raise HTTPException(400, "Укажите дату документа")
    supplier_id = body.supplier_id if "supplier_id" in fields else row.supplier_id
    contract_id = body.contract_id if "contract_id" in fields else row.contract_id
    if supplier_id is None and "supplier" in fields:
        row.supplier = body.supplier
    if contract_id is None and "contract" in fields:
        row.contract = body.contract
    organization_id = (
        body.organization_id if "organization_id" in fields else row.organization_id)
    await _set_receipt_party(
        db, row, supplier_id, contract_id, required=False,
        organization_id=organization_id)
    warehouse_id = body.warehouse_id if "warehouse_id" in fields else row.warehouse_id
    await _set_receipt_warehouse(db, row, warehouse_id, required=False)
    incoming_number = body.incoming_number if "incoming_number" in fields else row.incoming_number
    incoming_date = body.incoming_date if "incoming_date" in fields else row.incoming_date
    await _set_receipt_basis(
        db, row, row.supplier, incoming_number, incoming_date, required=False)
    evidence = dict(row.evidence or {})
    for field in ("place", "purpose", "invoice_kind", "invoice_number", "invoice_date",
                  "currency", "vat_included", "vat_deductible",
                  "declared_goods_total", "declared_services_total",
                  "declared_vat_total", "declared_total",
                  "source_kind", "purchased_by", "payment_kind"):
        if field in fields:
            value = getattr(body, field)
            if value is None:
                evidence.pop(field, None)
            else:
                evidence[field] = value
    row.evidence = evidence
    _touch_receipt(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Такая накладная уже существует") from exc
    await db.refresh(row)
    return _receipt_out(row)


@router.post("/receipts/{receipt_id}/accounting-ready")
async def set_receipt_accounting_ready(
    receipt_id: uuid.UUID,
    body: ReceiptAccountingIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Бухгалтерскую канонизацию подтверждает центр")
    current = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id,
        StoreReceipt.company_id == access.company_id,
    ))).scalar_one_or_none()
    if current is None:
        raise HTTPException(404, "Документ не найден")
    _check_receipt_version(current, body.version)
    try:
        row = await store_receipt_accounting.canonicalize_receipt(
            db, access.company_id, receipt_id, user.id, body.note)
    except store_receipt_accounting.ReceiptAccountingError as exc:
        await db.commit()
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.post("/receipts/{receipt_id}/canonical-link")
async def link_accepted_receipt_canonical_refs(
    receipt_id: uuid.UUID,
    body: ReceiptCanonicalLinkIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Позднее связывание НСИ выполняет центр")
    try:
        row = await store_receipt_accounting.link_receipt_canonical_refs(
            db, access.company_id, receipt_id,
            supplier_id=body.supplier_id,
            contract_id=body.contract_id,
            organization_id=body.organization_id,
            warehouse_id=body.warehouse_id,
            confirmed_by=user.id,
            expected_version=body.version,
            note=body.note,
        )
    except store_receipt_accounting.ReceiptAccountingError as exc:
        await db.commit()
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.post("/receipts/{receipt_id}/status")
async def set_receipt_status(
    receipt_id: uuid.UUID,
    status: str = Query(..., description="expected|accepted|reversed"),
    version: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ордерная схема: «к поступлению» -> «принят».

    Принять документ без единой посчитанной позиции нельзя: это верный признак,
    что кнопку нажали раньше, чем пересчитали товар.
    """
    if status not in ("expected", "accepted", "reversed"):
        raise HTTPException(400, "Допустимы expected, accepted и reversed")
    access = await _receipt_access(user, db)
    cid = access.company_id
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id, StoreReceipt.company_id == cid
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    _check_receipt_version(row, version)
    if row.status == status:
        if status == "accepted" and row.delivery_scheme == "central_warehouse":
            await _record_receipt_acceptance(db, row, user.id)
            await db.commit()
        return _receipt_out(row)
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
        await _set_receipt_party(
            db, row, row.supplier_id, row.contract_id, required=True,
            organization_id=row.organization_id)
        await _set_receipt_warehouse(db, row, row.warehouse_id, required=True)
        _require_receipt_canonical(row)
        await _set_receipt_basis(db, row, row.supplier, row.incoming_number, row.incoming_date)
        lines = _normalized_receipt_lines(row)
        total, vat = _recalc(lines, list(row.services or []))
        _validate_scanned_marks(lines)
        row.lines = lines
        row.total_amount = total
        row.vat_amount = vat
        await _record_receipt_acceptance(db, row, user.id)
        row.accepted_at = datetime.now(timezone.utc)
    elif status == "reversed":
        if row.status != "accepted" or row.delivery_scheme != "central_warehouse":
            raise HTTPException(409, "Отменить можно только центральную принятую приёмку")
        await _reverse_receipt_acceptance(db, row, user.id)
    elif row.status == "accepted":
        raise HTTPException(409, "Принятый документ меняется только обратной проводкой")
    row.status = status
    _touch_receipt(row)
    await db.commit()
    await db.refresh(row)
    return _receipt_out(row)


@router.get("/receipts/{receipt_id}/ledger")
async def get_receipt_ledger(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await _receipt_access(user, db)
    row = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id,
        StoreReceipt.company_id == access.company_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Документ не найден")
    _require_receipt_row(access, row)
    movements = (await db.execute(select(StoreReceiptStockMovement).where(
        StoreReceiptStockMovement.company_id == access.company_id,
        StoreReceiptStockMovement.receipt_id == receipt_id,
    ).order_by(StoreReceiptStockMovement.created_at, StoreReceiptStockMovement.id))).scalars().all()
    balances: dict[str, float] = {}
    for movement in movements:
        balances[movement.item_key] = round(
            balances.get(movement.item_key, 0) + float(movement.quantity), 3)
    return {
        "receipt_id": str(receipt_id),
        "movements": [{
            "id": str(movement.id), "kind": movement.kind,
            "reversal_of_id": str(movement.reversal_of_id) if movement.reversal_of_id else None,
            "allocation_id": movement.allocation_id, "line_index": movement.line_index,
            "station_id": movement.station_id, "warehouse": movement.warehouse,
            "item_key": movement.item_key, "quantity": float(movement.quantity),
            "unit_cost": float(movement.unit_cost), "amount": float(movement.amount),
            "created_at": movement.created_at,
        } for movement in movements],
        "balance": balances,
    }


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


@router.get("/visits")
async def store_visits(
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поток посетителей и конверсия без повторного расчёта всего обзора."""
    cid: uuid.UUID = await scope_company_id(user, db)
    st = [s.strip() for s in stations.split(",") if s.strip()] if stations else None
    return await GoodsDashboardService(db, cid).visits(
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


@router.get("/suppliers/card")
async def supplier_card(
    name: str = Query(..., description="наименование контрагента"),
    date_from: str = Query(...),
    date_to: str = Query(...),
    stations: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Карточка поставщика: поставки, что возит, как менялись цены, возвраты.

    Имя, а не идентификатор: документы 1С ссылаются на контрагента ссылкой, но
    на экране и в отчётах он живёт наименованием, и переход из списка должен
    работать без второго справочника.
    """
    return await GoodsDashboardService(db, await scope_company_id(user, db)).supplier_card(
        name, date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations),
    )


@router.get("/catalog/health")
async def catalog_health(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Здоровье каталога: чего в справочнике не хватает и где он врёт.

    Не витрина, а список работы: каждая цифра — отбор, который можно открыть и
    разобрать. Считается по живому ассортименту отдельно от всего справочника —
    иначе шеститысячный архив хоронит любую метрику: «фото нет у 7 500 карточек»
    звучит безнадёжно, «нет у 865 торгуемых» это работа на неделю.
    """
    cid = await scope_company_id(user, db)
    # Здоровье считаем по своему справочнику: чужая компания в том же
    # пространстве не должна ни добавлять работы, ни прятать её. Карточка без
    # владельца — своя: до миграции company_id его не было ни у одной.
    строка = (await db.execute(text("""
        WITH мои AS (
            SELECT i.* FROM edge.item i
            WHERE i.company_id IS NULL OR i.company_id = :cid
        ), живой AS (
            -- Живой ассортимент — то, что ТОРГУЕТСЯ, а не всё с товарным классом.
            -- Позиция считается торгуемой, когда у неё есть цена станции, код
            -- кассы или остаток: без этого она лежит в справочнике и в работу
            -- не входит. Пока условием был один класс, в знаменателе процентов
            -- стояли 229 карточек, которых нет ни на одной полке, и «заполнено
            -- 77 %» означало не то, что написано под цифрой.
            SELECT i.* FROM мои i
            WHERE NOT i.deleted AND coalesce(i.sku_class, '') <> 'Сырьё'
              AND (EXISTS (SELECT 1 FROM edge.price p
                            WHERE p.item_id = i.id AND p.valid_to IS NULL)
                OR EXISTS (SELECT 1 FROM edge.ns_code n
                             JOIN edge.barcode b ON b.id = n.barcode_id
                            WHERE b.item_id = i.id AND n.status = 'active')
                OR EXISTS (SELECT 1 FROM edge.stock st
                             JOIN edge.barcode b2 ON b2.id = st.barcode_id
                            WHERE b2.item_id = i.id AND st.qty <> 0))
        )
        SELECT
          (SELECT count(*) FROM мои WHERE NOT deleted)              AS всего,
          (SELECT count(*) FROM живой)                                    AS живых,
          (SELECT count(*) FROM мои WHERE sku_class IS NULL AND NOT deleted) AS без_класса,
          (SELECT count(*) FROM живой WHERE group_id IS NULL)             AS без_группы,
          -- «Прочее» — настоящая группа, и матрица по ней работает. Но это
          -- корзина: пока позиция там, отчёт по категориям о ней не расскажет.
          (SELECT count(*) FROM живой
            WHERE group_id IN (SELECT id FROM edge.item_group WHERE path = 'Прочее'))
                                                                          AS в_прочем,
          (SELECT count(*) FROM живой i WHERE NOT EXISTS
              (SELECT 1 FROM edge.barcode b WHERE b.item_id = i.id AND b.status = 'active'))
                                                                          AS без_штрихкода,
          (SELECT count(*) FROM живой i WHERE NOT EXISTS
              (SELECT 1 FROM edge.price p WHERE p.item_id = i.id AND p.valid_to IS NULL))
                                                                          AS без_цены,
          (SELECT count(*) FROM живой WHERE photo_url IS NULL)            AS без_фото,
          (SELECT count(*) FROM живой WHERE brand IS NULL)                AS без_бренда,
          (SELECT count(*) FROM живой WHERE composition IS NULL)          AS без_состава,
          -- По ЖИВОМУ ассортименту, как и всё остальное на этой странице.
          -- Пока считалось по всему справочнику, в цифре сидела архивная
          -- карточка, по которой работы нет: 8 против 7 (01.09.2026).
          (SELECT count(*) FROM живой WHERE vat_rate NOT IN ('НДС22', 'БезНДС'))
                                                                          AS ставка_устарела,
          (SELECT count(*) FROM мои WHERE NOT deleted
             AND vat_rate NOT IN ('НДС22', 'БезНДС'))                     AS ставка_устарела_всего,
          (SELECT count(*) FROM живой WHERE marked)                       AS маркируемых_всего,
          (SELECT count(*) FROM живой WHERE marked AND gtin IS NULL)      AS маркируемые_без_gtin,
          -- У большинства GTIN не надо добывать: он и есть штрихкод товара.
          -- Разделяем, иначе работа выглядит втрое больше, чем она есть.
          (SELECT count(*) FROM живой i WHERE i.marked AND i.gtin IS NULL
             AND EXISTS (SELECT 1 FROM edge.barcode b
                          WHERE b.item_id = i.id AND b.status = 'active'
                            AND length(b.code) IN (8, 12, 13, 14)))
                                                                          AS gtin_из_шк,
          (SELECT count(*) FROM живой i
             WHERE i.group_id IN (SELECT id FROM edge.item_group
                                   WHERE path IN ('Табак / Сигареты',
                                                  'Табак / Стики и капсулы'))
               AND i.mrc IS NULL)                                         AS табак_без_мрц,
          -- Готовая еда «Честным знаком» не маркируется: у бургера и хот-дога
          -- DataMatrix не бывает. Признак, стоящий у блюда, — ошибка справочника,
          -- и она мешает дважды: раздувает счётчик GTIN и уезжает в кассу.
          (SELECT count(*) FROM живой WHERE marked AND sku_class = 'Блюдо')
                                                                          AS блюда_маркируемые,
          -- Действующая коллизия — это когда один код активен у двух карточек
          -- В ОДНОМ ЯРУСЕ: сетевой EAN у двух позиций либо внутренний код одной
          -- станции у двух её товаров. Именно тогда касса продаёт ту строку,
          -- что выгрузилась последней.
          (SELECT count(*) FROM (
              SELECT b.code FROM edge.barcode b JOIN мои i ON i.id = b.item_id
               WHERE b.status = 'active'
               GROUP BY b.code, coalesce(b.station_id, -1)
              HAVING count(*) > 1) t)                                     AS коллизии_шк,
          -- Отклонённая привязка — не авария, а сработавшая защита: центр не дал
          -- перевесить код, который уже работает у другой карточки.
          (SELECT count(*) FROM edge.barcode b
             JOIN мои i ON i.id = b.item_id
            WHERE b.status = 'rejected' AND NOT i.deleted)                AS привязок_отклонено,
          -- по «живой», а не по всей таблице: удалённые дубли карточек
          -- («Американо 200 мл» против «Американо 200 мл.») давали восемь
          -- несуществующих блюд без техкарты, и счётчик врал месяцами
          -- Блюдо без карты считаем ПАРАМИ «блюдо × станция»: с ярусами карта
          -- может быть на одной АЗС и отсутствовать на другой, и общая цифра
          -- «у блюда нет ТТК» такую дыру не показывает.
          -- Считаем только то, что МОЖЕТ БЫТЬ ПРОДАНО прямо сейчас: у блюда на
          -- этой станции есть код кассы и матрица его не закрыла. Иначе счётчик
          -- набирает вес станцией, которая ещё не запущена: на АЗС 8 карт не
          -- было у 45 блюд, но ни одно из них не стояло в кассе, а двадцать были
          -- закрыты товароведом — работы там ноль, а плитка горела красным.
          (SELECT count(*) FROM живой i
             JOIN edge.price p ON p.item_id = i.id AND p.valid_to IS NULL
            WHERE i.sku_class = 'Блюдо'
              AND EXISTS (SELECT 1 FROM edge.ns_code n
                            JOIN edge.barcode b ON b.id = n.barcode_id
                           WHERE b.item_id = i.id AND n.station_id = p.station_id
                             AND n.status = 'active')
              AND NOT EXISTS (SELECT 1 FROM edge.matrix_rule r
                               WHERE r.item_id = i.id AND r.station_id = p.station_id
                                 AND r.subject = 'assortment' AND NOT r.allow
                                 AND r.valid_to IS NULL AND r.closed_at IS NULL)
              AND NOT EXISTS (SELECT 1 FROM store_recipe_versions v
                               WHERE v.dish_uuid = i.external_uuid::text
                                 AND v.status = 'active' AND v.valid_to IS NULL
                                 AND (v.station_id IS NULL OR v.station_id = p.station_id)))
                                                                          AS блюда_без_ттк,
          -- Отдельно — те, у кого карты нет, но и продать их сейчас нельзя:
          -- станция не запущена или позиция закрыта. Это не работа, а состояние.
          (SELECT count(*) FROM живой i
             JOIN edge.price p ON p.item_id = i.id AND p.valid_to IS NULL
            WHERE i.sku_class = 'Блюдо'
              AND NOT EXISTS (SELECT 1 FROM store_recipe_versions v
                               WHERE v.dish_uuid = i.external_uuid::text
                                 AND v.status = 'active' AND v.valid_to IS NULL
                                 AND (v.station_id IS NULL OR v.station_id = p.station_id)))
                                                                          AS блюда_без_ттк_всего,
          (SELECT count(*) FROM edge.item_enrichment e
             JOIN мои i ON i.id = e.item_id
            WHERE e.resolved_at IS NULL AND NOT i.deleted)
                                                                          AS предложений_ждёт
    """), {"cid": cid})).mappings().first()

    # Дубли считаем нормализованным именем — тем же способом, что и раздел
    # «Дубли»: пока карточки не сведены, обогащать их бессмысленно, обогатим
    # не ту из пары.
    # Тёзки делятся на живых и архивных, и путать их нельзя.
    #
    # Живая пара — обе карточки чем-то заняты (штрихкод, цена, код кассы): это
    # работа, её надо свести. Архивная — наследие 1С, товара за ней нет, и
    # сводить нечего. 31.08.2026 сплошная сверка после импорта АЗС 8 дала 89
    # пар, из которых живых оказалось одиннадцать: без такого деления счётчик
    # показывал бы 89 и не значил ничего.
    дубли = (await db.execute(text("""
        WITH n AS (
            SELECT i.id,
                   -- ⚠ lower ДО regexp: класс [a-zа-я0-9] строчный, и при
                   -- обратном порядке вырезались ВСЕ заглавные буквы — ключ
                   -- искажался у 1591 карточки из 1595 (01.09.2026). Тёзок
                   -- насчитывалось 85 при настоящих 82, а имя капсом целиком
                   -- («ДВОЙНОЙ ЭСПРЕССО») давало пустой ключ и выпадало вовсе.
                   regexp_replace(lower(translate(i.name,'ёЁ','ее')),
                                  '[^a-zа-я0-9]', '', 'g') k,
                   (EXISTS (SELECT 1 FROM edge.barcode b
                             WHERE b.item_id = i.id AND b.status = 'active')
                    OR EXISTS (SELECT 1 FROM edge.price p
                                WHERE p.item_id = i.id AND p.valid_to IS NULL)) AS живая
            FROM edge.item i WHERE NOT i.deleted
        ), g AS (
            SELECT k, count(*) c, count(*) FILTER (WHERE живая) живых
              FROM n WHERE k <> '' GROUP BY k HAVING count(*) > 1
        )
        SELECT count(*) AS групп,
               coalesce(sum(c) - count(*), 0) AS лишних,
               count(*) FILTER (WHERE живых > 1) AS живых_пар,
               count(*) FILTER (WHERE живых <= 1) AS архивных
          FROM g
    """))).mappings().first()

    # Цена — величина станции, и «без цены» тоже станционное. Общая цифра
    # («нет цены ни на одной АЗС») благополучна ровно до вопроса «а что не
    # продать на 208»: там таких позиций в полтора раза больше.
    по_станциям_цена = [dict(r) for r in (await db.execute(text("""
        SELECT s.id AS station_id,
               (SELECT count(*) FROM edge.item i
                 WHERE NOT i.deleted AND i.sku_class IN ('Сопутка','Блюдо')
                   AND (i.company_id IS NULL OR i.company_id = :cid)
                   AND EXISTS (SELECT 1 FROM edge.price p
                                WHERE p.item_id = i.id AND p.station_id = s.id
                                  AND p.valid_to IS NULL)) AS с_ценой,
               (SELECT count(*) FROM edge.item i
                 WHERE NOT i.deleted AND i.sku_class IN ('Сопутка','Блюдо')
                   AND (i.company_id IS NULL OR i.company_id = :cid)
                   AND EXISTS (SELECT 1 FROM edge.ns_code n
                                 JOIN edge.barcode b ON b.id = n.barcode_id
                                WHERE b.item_id = i.id AND n.station_id = s.id
                                  AND n.status = 'active')) AS с_кодом_кассы
          FROM edge.station s
         WHERE s.company_id = :cid OR s.company_id IS NULL
         ORDER BY s.id
    """), {"cid": cid})).mappings().all()]

    # «Из них торгуются» обязано считать ТОРГУЕМОСТЬ — цену станции, код кассы
    # или остаток, — а не класс SKU. Пока считался класс, колонка повторяла
    # первую цифру у каждой строки («Автохимия 59 / 59») и не значила ничего:
    # на деле из 187 сигарет торгуются 167, из 158 газированных — 123.
    # МРЦ станционен ровно так же, как цена: сигарета продаётся на конкретной
    # АЗС, и там же нарушается ст. 13 ФЗ-15. Общая цифра 79 не говорит, где
    # работа, — на 208 таких 38, на 8 их 51.
    мрц_по_станциям = [dict(r) for r in (await db.execute(text("""
        SELECT p.station_id, count(DISTINCT i.id) AS без_мрц
          FROM edge.item i
          JOIN edge.price p ON p.item_id = i.id AND p.valid_to IS NULL
         WHERE NOT i.deleted AND i.mrc IS NULL
           AND (i.company_id IS NULL OR i.company_id = :cid)
           AND i.group_id IN (SELECT id FROM edge.item_group
                               WHERE path IN ('Табак / Сигареты',
                                              'Табак / Стики и капсулы'))
         GROUP BY p.station_id ORDER BY p.station_id
    """), {"cid": cid})).mappings().all()]

    группы = (await db.execute(text("""
        WITH торгуемые AS (
            SELECT i.id FROM edge.item i
             WHERE NOT i.deleted AND coalesce(i.sku_class, '') <> 'Сырьё'
               AND (EXISTS (SELECT 1 FROM edge.price p
                             WHERE p.item_id = i.id AND p.valid_to IS NULL)
                 OR EXISTS (SELECT 1 FROM edge.ns_code n
                              JOIN edge.barcode b ON b.id = n.barcode_id
                             WHERE b.item_id = i.id AND n.status = 'active')
                 OR EXISTS (SELECT 1 FROM edge.stock st
                              JOIN edge.barcode b2 ON b2.id = st.barcode_id
                             WHERE b2.item_id = i.id AND st.qty <> 0))
        )
        SELECT g.path, count(i.id) AS карточек,
               count(i.id) FILTER (WHERE i.id IN (SELECT id FROM торгуемые)) AS живых
        FROM edge.item_group g
        LEFT JOIN edge.item i ON i.group_id = g.id AND NOT i.deleted
        GROUP BY g.path ORDER BY g.path
    """))).mappings().all()

    классы = (await db.execute(text("""
        SELECT coalesce(sku_class, '— не разобрано') AS класс, count(*) AS карточек
        FROM edge.item WHERE NOT deleted GROUP BY 1 ORDER BY 2 DESC
    """))).mappings().all()

    return {"итого": dict(строка), "дубли": dict(дубли),
            "по_группам": [dict(g) for g in группы],
            "по_классам": [dict(k) for k in классы],
            "по_станциям": по_станциям_цена,
            "мрц_по_станциям": мрц_по_станциям}


@router.get("/catalog/twins")
async def catalog_twins(
    only_live: bool = Query(True, description="только пары, где занята не одна карточка"),
    вид: str | None = Query(None, alias="kind",
                            description="наследие | ассортимент | дубль сети"),
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Карточки-тёзки: кто с кем и где применяется.

    Дубль в сетевом каталоге ломает сводный отчёт молча — цифры расходятся по
    двум строкам с одинаковым именем. Ловить его глазами нельзя: при импорте
    справочника новой станции пар набирается десятками (АЗС 8, 31.08.2026 — 89),
    и появляются они не поодиночке, а пачкой в день подключения.

    Пара живая, когда занята больше чем одна карточка (штрихкод, цена или код
    кассы): такую надо свести. Остальные — архив 1С, товара за ними нет.

    ⚠ Ключ сравнения строится ПОСЛЕ приведения к строчным. Пока `lower` стоял
    снаружи `regexp_replace`, класс `[a-zа-я0-9]` вырезал все заглавные буквы, и
    сравнивался огрызок имени — 1591 карточка из 1595 (01.09.2026). «СТИКИ HEETS
    from Parliament AMBER SELECTION» превращалась в `fromarliament`: четыре вкуса
    стиков объявлялись одним товаром. А имя, набранное капсом целиком («ДВОЙНОЙ
    ЭСПРЕССО» с АЗС 8), давало пустой ключ и не попадало сюда вовсе — ровно те
    карточки, что задвоились при импорте новой станции.

    Вид группы отделяет беду от шума: списком в 82 строки, где 66 строк норма,
    не пользуется никто.
      * `наследие` — карточка со штрихкодом всего одна, рядом пустышка с ценой
        из справочника 1С. Товара за ней нет, торговле не мешает;
      * `ассортимент` — несколько живых карточек, у каждой свой штрихкод. Это не
        дубль, а неразличимое имя: «Жев. конф. Love is в ассортименте» — четыре
        вкуса, «Чай Рич в ассорт. 1 л.» — три. Лечится именем, а не слиянием:
        сольёшь — пропадёт вкус, который кассир пробивает отдельным кодом;
      * `дубль сети` — один товар заведён карточкой на каждой станции. Вот это
        настоящая беда: артикул сети обязан быть один (кофе 208 и 8, 01.09.2026).
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    отбор = ["g.живых > 1"] if only_live else []
    if вид:
        отбор.append("g.вид = :вид")
    условие = ("WHERE " + " AND ".join(отбор)) if отбор else ""
    rows = (await db.execute(text(f"""
        WITH n AS (
            SELECT i.id, i.name, i.sku, i.sku_class,
                   regexp_replace(lower(translate(i.name,'ёЁ','ее')),
                                  '[^a-zа-я0-9]', '', 'g') k,
                   (SELECT count(*) FROM edge.barcode b
                     WHERE b.item_id = i.id AND b.status = 'active') AS шк,
                   (SELECT array_agg(DISTINCT p.station_id) FROM edge.price p
                     WHERE p.item_id = i.id AND p.valid_to IS NULL) AS станции,
                   (SELECT count(*) FROM edge.ns_code c
                      JOIN edge.barcode b2 ON b2.id = c.barcode_id
                     WHERE b2.item_id = i.id AND c.status = 'active') AS кодов,
                   (SELECT coalesce(sum(s.qty), 0) FROM edge.stock s
                      JOIN edge.barcode b3 ON b3.id = s.barcode_id
                     WHERE b3.item_id = i.id) AS остаток
              FROM edge.item i
             WHERE NOT i.deleted AND (i.company_id IS NULL OR i.company_id = :cid)
        ), m AS (
            SELECT *, (шк > 0 OR станции IS NOT NULL) AS живая FROM n
        ), g AS (
            SELECT k, count(*) c, count(*) FILTER (WHERE живая) живых,
                   CASE
                     WHEN count(*) FILTER (WHERE шк > 0) <= 1 THEN 'наследие'
                     WHEN count(DISTINCT coalesce(станции::text, '')) > 1
                       THEN 'дубль сети'
                     ELSE 'ассортимент'
                   END AS вид
              FROM m WHERE k <> '' GROUP BY k HAVING count(*) > 1
        ), взяли AS (
            SELECT * FROM g {условие}
             ORDER BY (вид = 'дубль сети') DESC, живых DESC, k
             LIMIT :limit
        )
        SELECT взяли.k, взяли.живых, взяли.вид,
               m.id, m.name, m.sku, m.sku_class, m.живая, m.станции, m.шк,
               m.кодов, m.остаток
          FROM взяли JOIN m ON m.k = взяли.k
         ORDER BY (взяли.вид = 'дубль сети') DESC, взяли.живых DESC,
                  взяли.k, m.шк DESC, m.id
    """), {"cid": cid, "limit": limit, "вид": вид})).mappings().all()

    группы: dict[str, dict] = {}
    for r in rows:
        группа = группы.setdefault(r["k"], {"ключ": r["k"], "живых": r["живых"],
                                            "вид": r["вид"], "карточки": []})
        группа["карточки"].append({
            "id": r["id"], "name": r["name"], "sku": r["sku"],
            "sku_class": r["sku_class"], "живая": bool(r["живая"]),
            "станции": sorted(r["станции"] or []), "штрихкодов": int(r["шк"] or 0),
            "кодов_кассы": int(r["кодов"] or 0), "остаток": float(r["остаток"] or 0),
        })
    список = list(группы.values())
    сводка: dict[str, int] = {}
    for г in список:
        сводка[г["вид"]] = сводка.get(г["вид"], 0) + 1
    return {"пар": len(список), "только_живые": only_live, "вид": вид,
            "по_видам": сводка, "группы": список}


@router.get("/catalog/enrichment")
async def catalog_enrichment(
    field: str = Query("brand"),
    limit: int = Query(300, le=2000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Предложения к заполнению карточки, ждущие решения человека.

    Источник — внешний или разбор наименования — карточку не правит. Он кладёт
    предложение, а канон подтверждает человек: чужой состав, молча записанный в
    справочник, потом не отличить от нашего.

    Группируем по значению, а не по карточке: подтверждать «Winston» двадцать
    три раза подряд — работа ни о чём, решение принимается один раз на марку.
    """
    await scope_company_id(user, db)
    строки = (await db.execute(text("""
        SELECT e.value, e.source, max(e.confidence) AS confidence,
               count(*) AS позиций,
               (array_agg(i.name ORDER BY i.name))[1:5] AS примеры,
               array_agg(e.id) AS ids
        FROM edge.item_enrichment e
        JOIN edge.item i ON i.id = e.item_id
        WHERE e.field = :f AND e.resolved_at IS NULL AND NOT i.deleted
        GROUP BY e.value, e.source
        ORDER BY count(*) DESC, e.value
        LIMIT :lim
    """), {"f": field, "lim": limit})).mappings().all()
    всего = (await db.execute(text("""
        SELECT count(*) FROM edge.item_enrichment e
        JOIN edge.item i ON i.id = e.item_id
        WHERE e.field = :f AND e.resolved_at IS NULL AND NOT i.deleted
    """), {"f": field})).scalar_one()
    return {"поле": field, "всего_предложений": int(всего),
            "значения": [dict(r) for r in строки]}


class EnrichmentDecisionIn(BaseModel):
    ids: list[int] = []
    accepted: bool
    author: str = ""


@router.post("/catalog/enrichment/decide")
async def catalog_enrichment_decide(
    body: EnrichmentDecisionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принять или отклонить предложения — пачкой, по одной марке разом.

    Принятое значение ложится в карточку и уезжает на станции обычным
    обновлением справочника. Отклонённое остаётся в журнале: источник повторит
    догадку, и без записи об отказе человек будет разбирать её снова и снова.
    """
    cid = await _require_network_merchandiser(user, db)
    if not body.ids:
        raise HTTPException(422, "Не выбрано ни одного предложения")
    автор = (body.author or user.email or "").strip()[:120]
    поля = (await db.execute(text("""
        UPDATE edge.item_enrichment
        SET resolved_at = now(), accepted = :ok, author = :a
        WHERE id = ANY(:ids) AND resolved_at IS NULL
        RETURNING item_id, field, value
    """), {"ok": body.accepted, "a": автор, "ids": body.ids})).mappings().all()
    if body.accepted:
        for r in поля:
            if r["field"] != "brand":
                # Пока подтверждаем только бренд: остальные поля придут из
                # внешнего источника, и у них своя проверка.
                continue
            await db.execute(text("""
                UPDATE edge.item SET brand = :v, enriched_from = 'name_parse',
                       enriched_at = now(), updated_at = now()
                WHERE id = :id
            """), {"v": r["value"], "id": r["item_id"]})
            await _queue_nsi_delta(db, cid, int(r["item_id"]))
    await db.commit()
    return {"ok": True, "решено": len(поля), "принято": bool(body.accepted)}


@router.get("/catalog/groups")
async def catalog_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Дерево групп номенклатуры со счётчиками."""
    await scope_company_id(user, db)
    rows = (await db.execute(text("""
        SELECT g.id, g.parent_id, g.name, g.path, g.sort,
               g.marked_default, g.adult_default, g.price_owner_default, g.note,
               count(i.id) AS карточек,
               count(i.id) FILTER (WHERE i.sku_class IN ('Сопутка','Блюдо')) AS живых
        FROM edge.item_group g
        LEFT JOIN edge.item i ON i.group_id = g.id AND NOT i.deleted
        GROUP BY g.id ORDER BY g.sort, g.path
    """))).mappings().all()
    return {"groups": [dict(r) for r in rows]}


@router.post("/catalog/groups")
async def catalog_group_create(
    body: ItemGroupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести группу. Путь строится от родителя — руками его не задают."""
    await _require_network_merchandiser(user, db)
    путь = body.name.strip()
    if not путь:
        raise HTTPException(400, "Имя группы пустое")
    if body.parent_id:
        родитель = (await db.execute(text(
            "SELECT path FROM edge.item_group WHERE id = :id"), {"id": body.parent_id})).scalar()
        if родитель is None:
            raise HTTPException(404, "Родительская группа не найдена")
        путь = f"{родитель} / {путь}"
    new_id = (await db.execute(text("""
        INSERT INTO edge.item_group (parent_id, name, path, marked_default,
                                     adult_default, price_owner_default, note)
        VALUES (:p, :n, :path, :m, :a, :po, :note)
        ON CONFLICT (parent_id, name) DO UPDATE SET note = excluded.note
        RETURNING id
    """), {"p": body.parent_id, "n": body.name.strip(), "path": путь,
           "m": body.marked_default, "a": body.adult_default,
           "po": body.price_owner_default, "note": body.note})).scalar()
    await db.commit()
    return {"ok": True, "id": new_id, "path": путь}


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
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Достоверный остаток товара (снимок регистров ЦБ ТоварыНаАЗК+Партии), не оценка."""
    station_codes = [s for s in (stations or "").replace(" ", "").split(",") if s]
    return await GoodsDashboardService(db, await scope_company_id(user, db)).stock_onhand(
        warehouse=warehouse, q=q, marked=marked, only_negative=only_negative,
        stations=station_codes or None)


def _od(s: str | None):
    return date.fromisoformat(s) if s else None


@router.get("/inventory")
async def store_inventory(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    only_dev: bool = Query(False, description="только документы с отклонениями"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр инвентаризаций ЦБ + недостачи/излишки (shrinkage) с drill-down по строкам."""
    station_codes = [s for s in (stations or "").replace(" ", "").split(",") if s]
    return await GoodsDashboardService(db, await scope_company_id(user, db)).inventory(
        warehouse=warehouse, only_dev=only_dev, date_from=_od(date_from), date_to=_od(date_to),
        stations=station_codes or None)


@router.get("/writeoffs")
async def store_writeoffs(
    warehouse: str | None = Query(None, description="код склада (по умолч. — все склады магазина)"),
    reason: str | None = Query(None, description="фильтр по причине"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр списаний ЦБ (СписаниеТоваров) + причины + топ списанных SKU."""
    station_codes = [s for s in (stations or "").replace(" ", "").split(",") if s]
    return await GoodsDashboardService(db, await scope_company_id(user, db)).writeoffs(
        warehouse=warehouse, reason=reason, date_from=_od(date_from), date_to=_od(date_to),
        stations=station_codes or None)


@router.get("/transfers")
async def store_transfers(
    direction: str | None = Query(None, description="фильтр по направлению"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр перемещений ЦБ (ПеремещениеТоваров) откуда→куда + направления."""
    station_codes = [s for s in (stations or "").replace(" ", "").split(",") if s]
    return await GoodsDashboardService(db, await scope_company_id(user, db)).transfers(
        direction=direction, date_from=_od(date_from), date_to=_od(date_to),
        stations=station_codes or None)


@router.get("/revaluation")
async def store_revaluation(
    reason: str | None = Query(None, description="фильтр направления (Подорожание/Удешевление/Смешанная)"),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    stations: str | None = Query(None, description="коды АЗС через запятую"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая цена, Δ%, влияние."""
    station_codes = [s for s in (stations or "").replace(" ", "").split(",") if s]
    return await GoodsDashboardService(db, await scope_company_id(user, db)).revaluation(
        reason=reason, date_from=_od(date_from), date_to=_od(date_to),
        stations=station_codes or None)


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
    access = await _receipt_access(user, db)
    emitter = BpPackageEmitter(db, access.company_id)
    try:
        station_id = await emitter.resolve_shift_station(shift_key)
    except ValueError as e:
        raise HTTPException(404 if str(e).startswith("смена не найдена") else 409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Определение станции: {e}")
    _require_receipt_station(access, station_id)
    try:
        return await emitter.build_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сборка пакета: {e}")


@router.post("/bp-package/emit")
async def store_bp_package_emit(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    manifest_hash: str | None = Query(
        None, description="SHA-256 exact effective CutoverManifest",
    ),
    review_override: str | None = Query(
        None,
        description=(
            "Осознанная загрузка невыверенной смены: кто и почему. "
            "Без него смена со статусом needs_review в бухгалтерию не уходит"
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проверить пакет и поставить его в guarded queue без записи файла."""
    from collections import Counter

    from app.services.bp_export import BpPackageEmitter
    from app.services.accounting_egress import (
        AccountingEgressGuard,
    )

    access = await _receipt_access(user, db)
    cid = access.company_id
    guard = AccountingEgressGuard(db, cid)
    try:
        emitter = BpPackageEmitter(db, cid)
        station_id = await emitter.resolve_shift_station(shift_key)
    except ValueError as e:
        if str(e).startswith("смена не найдена"):
            raise HTTPException(404, "Смена не найдена")
        raise HTTPException(409, "Не удалось определить станцию пакета")
    except Exception:
        raise HTTPException(400, "Не удалось определить станцию пакета")

    _require_receipt_station(access, station_id)
    try:
        await emitter.select_accounting_source(shift_key, manifest_hash)
        raw_packet = await emitter.build_shift_package(shift_key)
        verification = await emitter.verify_shift_package(
            shift_key, packet=raw_packet,
        )
        if not verification["ok"]:
            failed = [
                check["Проверка"] for check in verification["checks"]
                if not check["ok"]
            ]
            raise ValueError(
                "Пакет не прошёл обязательную сверку: " + "; ".join(failed)
            )
        packet = await emitter.prepare_accounting_packet(
            shift_key, manifest_hash, raw_packet=raw_packet,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Постановка пакета в очередь: {e}")

    try:
        # Роутер зовут и напрямую (тесты, внутренние вызовы) — тогда сюда
        # приезжает сам объект Query, а не строка.
        решение = review_override.strip() if isinstance(review_override, str) else ""
        if решение:
            решение = f"{решение} (загрузил {user.email or user.id})"
        queued = await guard.queue_packet(packet, manifest_hash, решение or None)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Постановка пакета в очередь: {e}")

    documents = dict(Counter(doc["Тип"] for doc in packet["Документы"]))
    log_export(db, cid, user,
               f"Пакет Ledger→БП поставлен в guarded queue, смена {shift_key}: "
               f"{queued.packet.id}, {sum(documents.values())} документов, "
               f"НСИ {len(packet['НСИ'])}, хеш {packet['ХешПакета']}")
    return {
        "status": queued.packet.status,
        "packet_id": str(queued.packet.id),
        "packet_uuid": str(queued.packet.packet_uuid),
        "revision": queued.packet.revision,
        "contract_version": queued.packet.contract_version,
        "content_hash": queued.packet.content_hash,
        "created": queued.created,
        "kind": queued.packet.kind,
        "hash": packet["ХешПакета"],
        "manifest_hash": queued.decision.manifest_hash,
        "policy_id": str(queued.decision.policy_id),
        "policy_revision": queued.decision.revision,
        "documents": documents,
        "nsi": len(packet["НСИ"]),
    }


class BatchRowIn(BaseModel):
    """Строка среза партий из центральной базы 1С."""
    nomenclature_ref: str
    quantity_remaining: float
    amount_remaining: float
    warehouse_ref: str | None = None
    warehouse_name: str | None = None
    nomenclature_name: str | None = None
    organization_ref: str | None = None
    batch_doc_type: str | None = None
    batch_doc_ref: str | None = None
    batch_doc_number: str | None = None
    batch_doc_date: str | None = None


@router.post("/stock/batches/import")
async def store_stock_batches_import(
    rows: list[BatchRowIn] = Body(...),
    source: str = Query("1c_partii", description="откуда снят срез"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Загрузить срез партий из 1С — стартовую себестоимость запаса.

    Единственный источник цифры по товару, который лежал на полке до нас:
    закупок по нему в нашей системе нет и после отключения станционной 1С уже
    не появится. Срез снимается ДО Дня X, иначе восстанавливать будет не из
    чего.

    Загрузка идемпотентна: повторная заливка того же среза обновляет строки,
    а не удваивает их. Ключ — документ партии плюс товар и склад.
    """
    from app.models import InventoryBatch

    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Срез партий загружает товаровед сети")
    cid = access.company_id
    момент = datetime.now(timezone.utc)
    принято, пропущено = 0, 0
    for строка in rows:
        кол = float(строка.quantity_remaining or 0)
        сумма = float(строка.amount_remaining or 0)
        if not строка.nomenclature_ref or кол <= 0 or сумма <= 0:
            # Партия без остатка или без суммы себестоимости не несёт;
            # молча писать ноль значит выдать «товар бесплатный».
            пропущено += 1
            continue
        ключ = строка.batch_doc_ref or f"{строка.batch_doc_type}|{строка.batch_doc_number}"
        существующая = (await db.execute(
            select(InventoryBatch).where(
                InventoryBatch.company_id == cid,
                InventoryBatch.batch_doc_ref == ключ,
                InventoryBatch.nomenclature_ref == строка.nomenclature_ref,
                InventoryBatch.warehouse_ref == (строка.warehouse_ref or ""),
            ))).scalars().first()
        цена = round(сумма / кол, 4)
        if существующая is not None:
            существующая.quantity_remaining = кол
            существующая.amount_remaining = сумма
            существующая.unit_price = цена
            существующая.snapshot_at = момент
            существующая.source = source
        else:
            db.add(InventoryBatch(
                company_id=cid,
                batch_doc_type=строка.batch_doc_type or "",
                batch_doc_ref=ключ,
                batch_doc_number=строка.batch_doc_number or "",
                batch_doc_date=строка.batch_doc_date or "",
                nomenclature_ref=строка.nomenclature_ref,
                nomenclature_name=строка.nomenclature_name or "",
                warehouse_ref=строка.warehouse_ref or "",
                warehouse_name=строка.warehouse_name or "",
                organization_ref=строка.organization_ref or "",
                quantity_remaining=кол, amount_remaining=сумма,
                unit_price=цена, source=source, snapshot_at=момент,
            ))
        принято += 1
    log_export(db, cid, user,
               f"Загружен срез партий 1С: {принято} строк, пропущено {пропущено}")
    await db.commit()
    return {"accepted": принято, "skipped": пропущено, "source": source,
            "snapshot_at": момент.isoformat()}


@router.get("/bp-package/cutover")
async def store_bp_package_cutover_state(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Кто везёт первичку в бухгалтерию по каждой станции и с какого момента."""
    from app.models import AccountingSourcePolicy, CutoverManifest

    access = await _receipt_access(user, db)
    условия = [AccountingSourcePolicy.company_id == access.company_id]
    if not access.network:
        условия.append(AccountingSourcePolicy.station_id.in_(access.station_ids))
    политики = (await db.execute(
        select(AccountingSourcePolicy)
        .where(*условия)
        .order_by(AccountingSourcePolicy.station_id,
                  AccountingSourcePolicy.effective_from)
    )).scalars().all()
    манифесты = {
        m.policy_id: m for m in (await db.execute(
            select(CutoverManifest)
            .where(CutoverManifest.company_id == access.company_id)
        )).scalars().all()
    }
    return {
        "policies": [{
            "policy_id": str(p.id), "station_id": p.station_id,
            "policy_group": p.policy_group, "revision": p.revision,
            "state": p.state,
            "fact_cutover_business_date": p.fact_cutover_business_date.isoformat(),
            "station_timezone": p.station_timezone,
            "fact_rule": {
                "before": p.fact_origin_before,
                "on_or_after": p.fact_origin_after,
            },
            "effective_from": p.effective_from.isoformat(),
            "effective_to": p.effective_to.isoformat() if p.effective_to else None,
            "transport_producer": p.transport_producer,
            "transport_producer_before": p.transport_producer_before,
            "transport_cutover_at": p.transport_cutover_at.isoformat(),
            "shadow_validation_enabled": p.shadow_validation_enabled,
            "manifest_state": (манифесты.get(p.id).state
                               if манифесты.get(p.id) else None),
            "manifest_hash": (манифесты.get(p.id).manifest_hash
                              if манифесты.get(p.id) else None),
        } for p in политики],
    }


class CutoverPrepareRequest(BaseModel):
    station_id: int = Field(gt=0)
    fact_cutover_business_date: date
    transport_cutover_at: datetime
    station_timezone: str = Field(default="Europe/Moscow", min_length=1, max_length=80)
    arm_deadline: datetime | None = None
    shadow_validation_enabled: bool = True


class CutoverHashRequest(BaseModel):
    manifest_hash: str = Field(min_length=64, max_length=64)


def _cutover_http_error(exc) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


@router.post("/bp-package/cutover/prepare")
async def store_bp_package_cutover_prepare(
    body: CutoverPrepareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.cutover_policy import CutoverPolicyError, CutoverPolicyService
    access = await _receipt_access(user, db)
    _require_receipt_station(access, body.station_id)
    service = CutoverPolicyService(db, access.company_id)
    try:
        policy, manifest = await service.prepare(
            station_id=body.station_id,
            fact_cutover_business_date=body.fact_cutover_business_date,
            transport_cutover_at=body.transport_cutover_at,
            station_timezone=body.station_timezone,
            arm_deadline=body.arm_deadline,
            shadow_validation_enabled=body.shadow_validation_enabled,
        )
    except CutoverPolicyError as exc:
        raise _cutover_http_error(exc) from exc
    log_export(
        db, access.company_id, user,
        f"Подготовлен cutover станции {body.station_id}, revision {policy.revision}",
    )
    await db.commit()
    return {
        "policy_id": str(policy.id),
        "manifest_id": str(manifest.id),
        "station_id": body.station_id,
        "revision": policy.revision,
        "state": manifest.state,
        "manifest_hash": manifest.manifest_hash,
        "policy": manifest.canonical_payload,
        "activated": False,
    }


@router.post("/bp-package/cutover/{manifest_id}/approve")
async def store_bp_package_cutover_approve(
    manifest_id: uuid.UUID,
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.cutover_policy import CutoverPolicyError, CutoverPolicyService
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    service = CutoverPolicyService(db, access.company_id)
    try:
        manifest, approvals, created = await service.approve(
            manifest_id, user.id, datetime.now(timezone.utc), station_id=station_id,
        )
    except CutoverPolicyError as exc:
        raise _cutover_http_error(exc) from exc
    if created:
        log_export(db, access.company_id, user,
                   f"Согласован cutover станции {station_id}: {manifest_id}")
    await db.commit()
    return {
        "manifest_id": str(manifest.id), "state": manifest.state,
        "approval_count": len({row.user_id for row in approvals}),
        "approval_created": created, "activated": False,
    }


@router.post("/bp-package/cutover/{manifest_id}/arm")
async def store_bp_package_cutover_arm(
    manifest_id: uuid.UUID,
    body: CutoverHashRequest,
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.cutover_policy import CutoverPolicyError, CutoverPolicyService
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    service = CutoverPolicyService(db, access.company_id)
    try:
        _, manifest, approvals = await service.arm(
            manifest_id, body.manifest_hash, datetime.now(timezone.utc),
            station_id=station_id,
        )
    except CutoverPolicyError as exc:
        raise _cutover_http_error(exc) from exc
    log_export(db, access.company_id, user,
               f"Cutover станции {station_id} переведён в armed: {manifest_id}")
    await db.commit()
    return {"manifest_id": str(manifest.id), "state": manifest.state,
            "approval_count": len({row.user_id for row in approvals}),
            "activated": False}


@router.post("/bp-package/cutover/{manifest_id}/effective")
async def store_bp_package_cutover_effective(
    manifest_id: uuid.UUID,
    body: CutoverHashRequest,
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.cutover_policy import CutoverPolicyError, CutoverPolicyService
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    service = CutoverPolicyService(db, access.company_id)
    try:
        policy, manifest, approvals = await service.make_effective(
            manifest_id, body.manifest_hash, datetime.now(timezone.utc),
            station_id=station_id,
        )
    except CutoverPolicyError as exc:
        raise _cutover_http_error(exc) from exc
    log_export(db, access.company_id, user,
               f"Cutover станции {station_id} effective: revision {policy.revision}")
    await db.commit()
    return {"manifest_id": str(manifest.id), "state": manifest.state,
            "approval_count": len({row.user_id for row in approvals}),
            "activated": True, "effective_at": manifest.effective_at.isoformat()}


@router.get("/bp-package/cutover/{manifest_id}/manifest")
async def store_bp_package_cutover_manifest(
    manifest_id: uuid.UUID,
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.cutover_policy import CutoverPolicyError, CutoverPolicyService
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    try:
        _, _, exported = await CutoverPolicyService(
            db, access.company_id
        ).export_manifest(manifest_id, station_id=station_id)
    except CutoverPolicyError as exc:
        raise _cutover_http_error(exc) from exc
    return exported


@router.post("/bp-package/claim")
async def store_bp_package_claim(
    lease_seconds: int = Query(1800, ge=60, le=7200),
    claim_body: dict | None = Body(None),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Забрать очередной пакет для доставки в бухгалтерию.

    Ходит сюда доставщик — программа на машине с 1С, а не человек, поэтому
    авторизация ключом компании, а не сессией.

    Пакет выдаётся под аренду: если доставщик умрёт, не подтвердив отправку,
    аренда истечёт и пакет вернётся в очередь сам. Умолчание 30 минут — столько
    занимает одно COM-соединение с боевой бухгалтерией ГИГ (замер 15.08.2026:
    16 минут только на подключение).
    """
    from app.services.accounting_outbox import (
        AccountingOutboxService,
        AccountingRevisionConflict,
    )

    svc = AccountingOutboxService(db, company.id)
    if not isinstance(claim_body, dict):
        claim_body = None
    # Сначала возвращаем в очередь то, что зависло: доставщик перезапускается
    # чаще, чем истекает аренда, и без этого очередь встанет на первом же сбое.
    await svc.recover_expired_leases()
    if claim_body is not None:
        if (
            claim_body.get("ТипСообщения") != "claim_request"
            or claim_body.get("ВерсияКонтракта") != "3.0.0"
        ):
            raise HTTPException(409, "Claim должен соответствовать контракту 3.0.0")
        try:
            request_id = uuid.UUID(str(claim_body.get("ClaimRequestID") or ""))
            requested_lease = int(claim_body.get("LeaseSeconds"))
            result = await svc.claim_request(
                consumer_id=str(claim_body.get("ConsumerID") or ""),
                claim_request_id=request_id,
                lease_seconds=requested_lease,
            )
        except (ValueError, TypeError, AccountingRevisionConflict) as e:
            raise HTTPException(409, str(e))
        await db.commit()
        return {
            "ТипСообщения": "claim_response",
            "ВерсияКонтракта": "3.0.0",
            "ConsumerID": result.consumer_id,
            "ClaimRequestID": str(result.claim_request_id),
            "AttemptID": str(result.attempt_id) if result.attempt_id else None,
            "PacketID": str(result.packet.id) if result.packet else None,
            "LeaseUntil": (
                result.lease_until.isoformat().replace("+00:00", "Z")
                if result.lease_until else None
            ),
            "Пакет": result.packet.payload if result.packet else None,
        }
    packet = await svc.claim_next(lease_seconds=lease_seconds)
    if packet is None:
        await db.commit()
        return {"packet": None}
    await db.commit()
    return {
        "packet": {
            "packet_id": str(packet.id),
            "attempt_id": str(packet.attempt_id),
            "packet_uuid": str(packet.packet_uuid),
            "kind": packet.kind,
            "revision": packet.revision,
            "content_hash": packet.content_hash,
            "contract_version": packet.contract_version,
            "lease_until": packet.lease_until.isoformat() if packet.lease_until else None,
            "payload": packet.payload,
        }
    }


@router.post("/bp-package/ack")
async def store_bp_package_ack(
    packet_id: uuid.UUID | None = Query(None),
    attempt_id: uuid.UUID | None = Query(None),
    content_hash: str | None = Query(None, description="хеш принятого пакета"),
    result: str | None = Query(None, description="accepted | rejected"),
    stage: str = Query("ack", description="sent — отправлен, ack — есть ответ"),
    error_code: str | None = Query(None),
    error_detail: str | None = Query(None),
    ack_payload: dict | None = Body(None),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить доставку пакета в бухгалтерию.

    Два шага, а не один: `stage=sent` отмечает, что пакет ушёл в приёмник,
    `stage=ack` — что приёмник ответил. Между ними может пройти час, и пакет,
    отмеченный только как отправленный, повторно уже не выдаётся: загрузить
    одну смену дважды значит удвоить выручку в бухгалтерии.
    """
    from app.services.accounting_outbox import (
        AccountingOutboxService,
        AccountingRevisionConflict,
    )

    svc = AccountingOutboxService(db, company.id)
    if not isinstance(ack_payload, dict):
        ack_payload = None
    try:
        if ack_payload and ack_payload.get("ТипСообщения") == "ack":
            packet = await svc.apply_ack_contract(ack_payload)
        elif packet_id is None or attempt_id is None or content_hash is None or result is None:
            raise AccountingRevisionConflict("Legacy ACK не содержит обязательные query-поля")
        elif stage == "sent":
            packet = await svc.mark_sent(packet_id, attempt_id)
        elif result == "rejected" and stage == "retry":
            packet = await svc.fail_attempt(
                packet_id, attempt_id,
                retry_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                error_code=error_code or "delivery_failed",
                error_detail=error_detail)
        else:
            packet = await svc.apply_ack(
                packet_id, attempt_id=attempt_id, content_hash=content_hash,
                result=result, ack_payload=ack_payload or {},
                error_code=error_code, error_detail=error_detail)
    except AccountingRevisionConflict as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return {
        "status": packet.status,
        "packet_id": str(packet.id),
        "business_shift_id": (
            ack_payload.get("BusinessShiftID")
            if ack_payload and ack_payload.get("ТипСообщения") == "ack" else None
        ),
        "revision": packet.revision,
        "components": packet.component_result or [],
    }


@router.get("/bp-package/identity/{business_shift_id}")
async def store_bp_package_identity(
    business_shift_id: uuid.UUID,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    from app.models import (
        AccountingBusinessGroup,
        AccountingSourceDecision,
        BusinessShift,
        BusinessShiftAlias,
        ExportPacket,
    )

    shift = (await db.execute(select(BusinessShift).where(
        BusinessShift.company_id == company.id,
        BusinessShift.id == business_shift_id,
    ))).scalars().first()
    if shift is None:
        raise HTTPException(404, "BusinessShift не найден")
    aliases = (await db.execute(select(BusinessShiftAlias).where(
        BusinessShiftAlias.company_id == company.id,
        BusinessShiftAlias.business_shift_id == shift.id,
    ).order_by(BusinessShiftAlias.algorithm, BusinessShiftAlias.alias_hash))).scalars().all()
    group = (await db.execute(select(AccountingBusinessGroup).where(
        AccountingBusinessGroup.company_id == company.id,
        AccountingBusinessGroup.business_shift_id == shift.id,
    ))).scalars().first()
    decision = (await db.execute(select(AccountingSourceDecision).where(
        AccountingSourceDecision.company_id == company.id,
        AccountingSourceDecision.business_shift_id == shift.id,
    ).order_by(AccountingSourceDecision.created_at.desc()).limit(1))).scalars().first()
    packet = None
    if group is not None and group.current_packet_id is not None:
        packet = (await db.execute(select(ExportPacket).where(
            ExportPacket.company_id == company.id,
            ExportPacket.id == group.current_packet_id,
        ))).scalars().first()
    return {
        "identity": {
            "BusinessShiftID": str(shift.id),
            "CompanyID": shift.company_key,
            "StationID": shift.station_id,
            "BusinessDate": shift.business_date.isoformat(),
            "status": shift.status,
            "aliases": [{
                "Algorithm": row.algorithm,
                "AliasHash": row.alias_hash,
                "Attributes": row.attributes,
            } for row in aliases],
        },
        "decision": ({
            "status": decision.status,
            "winner_fact_id": decision.winner_fact_id,
            "loser_fact_ids": decision.loser_fact_ids,
            "fact_origin": decision.fact_origin,
            "reason": decision.reason,
            "shadow_status": decision.shadow_status,
        } if decision else None),
        "current_revision": ({
            "revision": group.current_revision,
            "content_hash": group.current_content_hash,
            "packet_id": str(group.current_packet_id) if group.current_packet_id else None,
            "status": packet.status if packet else None,
            "components": packet.component_result if packet else None,
        } if group else None),
    }


@router.get("/bp-package/verify")
async def store_bp_package_verify(
    shift_key: str = Query(..., description="GUID смены или 'дата|станция'"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сверка сопутки: самосогласованность пакета + готовность к загрузке (балансы,
    полнота НСИ, fail-fast НДС, хеш). Список проверок ok/детали."""
    from app.services.bp_export import BpPackageEmitter
    access = await _receipt_access(user, db)
    emitter = BpPackageEmitter(db, access.company_id)
    try:
        station_id = await emitter.resolve_shift_station(shift_key)
    except ValueError as e:
        raise HTTPException(404 if str(e).startswith("смена не найдена") else 409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сверка: {e}")
    _require_receipt_station(access, station_id)
    try:
        return await emitter.verify_shift_package(shift_key)
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
    очередь = await edge_nsi.station_drafts(db, cid, station_id)
    # Подсказка группы к каждой заявке и справочник групп для формы:
    # карточка без группы не уезжает в кассу, а пустое поле в форме —
    # самый верный способ её такой и оставить.
    очередь["groups"] = [dict(r) for r in (await db.execute(text(
        "SELECT id AS group_id, path, cash_section FROM edge.item_group ORDER BY path"
    ))).mappings().all()]
    for заявка in очередь.get("items", []):
        заявка["group_hint"] = await item_group_guess.предложить(
            db, заявка.get("name") or "")
    return очередь


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
    cid: uuid.UUID = await _require_network_merchandiser(user, db)
    try:
        # ⚠ group_id передаётся ИМЕНОВАННО и обязательно (03.09.2026). Пять
        # позиционных аргументов молча теряли выбор товароведа: интерфейс группу
        # требует и везёт в теле, а роутер её выбрасывал — карточка сети
        # рождалась с group_id = NULL. Из группы наследуется отдел кассы, без
        # отдела строка в кассу не встаёт, и товар не пробивается на полке.
        res = await edge_nsi.resolve_item_draft(
            db, cid, draft_id, str(body.get("action") or ""),
            body.get("item_id"), body.get("note"),
            group_id=body.get("group_id"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if res["action"] in ("link", "create"):
        # Признанная карточка едет ВСЕЙ сети, а не только станции-источнику.
        #
        # Раньше задание уходило по res["station_id"], и товар, признанный по
        # заявке одной АЗС, для остальных попросту не существовал: там он
        # заводился заново своим черновиком — то есть ровно тем дублем, ради
        # борьбы с которым признание и делается. Ставит задания общий
        # _queue_nsi_delta: карточка целиком, всем станциям, без накопления
        # версий в очереди.
        pushed = await _queue_nsi_delta(db, cid, res["item_id"])
        await db.commit()
        res["pushed"] = pushed > 0
        res["stations"] = pushed
    elif res["action"] == "reject":
        # Отказ обязан доехать до станции.
        #
        # Иначе она не узнаёт о нём никогда: черновик остаётся в её базе и
        # уезжает наверх каждый такт до скончания времён, а товаровед видит
        # вечно висящую заявку и заводит карточку второй раз.
        db.add(EdgeDownlink(
            company_id=cid, station_id=res["station_id"], kind="item_draft_rejected",
            payload={"draft_id": draft_id, "source_uuid": res.get("source_uuid") or "",
                     "reason": (body.get("note") or "").strip()},
            note="отказ по черновику карточки",
            idempotency_key=f"draft-reject:{res['station_id']}:{draft_id}",
        ))
        await db.commit()
        res["pushed"] = True
    return res


@router.post("/station-drafts/partner", status_code=201)
async def store_create_partner_draft(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать станционный pending-черновик поставщика без обхода канона."""
    access = await _receipt_access(user, db)
    try:
        station_id = int(body.get("station_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Укажите station_id") from exc
    _require_receipt_station(access, station_id)
    name = str(body.get("name") or "").strip()
    inn = "".join(char for char in str(body.get("inn") or "") if char.isdigit())
    role = str(body.get("role") or "supplier").strip()
    if not name:
        raise HTTPException(400, "Укажите наименование поставщика")
    if len(inn) not in (10, 12):
        raise HTTPException(400, "ИНН должен содержать 10 или 12 цифр")
    if role != "supplier":
        raise HTTPException(400, "В приёмке можно заявить только поставщика")
    draft_lock = int.from_bytes(hashlib.sha256(
        f"partner-draft:{access.company_id}:{station_id}:{inn}".encode()
    ).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(draft_lock)))
    existing = (await db.execute(text("""
        SELECT id, source_uuid, station_id, name, inn, kpp, role, comment, created_at
          FROM edge.partner_draft
         WHERE company_id = :cid AND station_id = :station AND resolved_at IS NULL
           AND regexp_replace(coalesce(inn, ''), '\\D', '', 'g') = :inn
         FOR UPDATE
    """), {"cid": access.company_id, "station": station_id, "inn": inn})).mappings().first()
    if existing is None:
        source_uuid = str(uuid.uuid4())
        existing = (await db.execute(text("""
            INSERT INTO edge.partner_draft
                (company_id, station_id, source_uuid, name, inn, kpp, role, comment)
            VALUES (:cid, :station, :source, :name, :inn, :kpp, :role, :comment)
            RETURNING id, source_uuid, station_id, name, inn, kpp, role, comment, created_at
        """), {"cid": access.company_id, "station": station_id, "source": source_uuid,
                 "name": name, "inn": inn, "kpp": str(body.get("kpp") or "").strip(),
                 "role": role, "comment": str(body.get("comment") or "").strip()})).mappings().one()
        await db.commit()
    result = dict(existing)
    result["created_at"] = result["created_at"].isoformat()
    result["status"] = "pending"
    return result


@router.post("/station-drafts/partner/{draft_id}")
async def store_resolve_partner_draft(
    draft_id: int,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Решение по контрагенту станции: принять в справочник сети или отклонить."""
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Решение по поставщику принимает товаровед сети")
    try:
        return await edge_nsi.resolve_partner_draft(
            db, access.company_id, draft_id, str(body.get("action") or ""), body.get("note"))
    except ValueError as exc:
        code = 409 if "несколько" in str(exc) or "другим" in str(exc) else 400
        raise HTTPException(code, str(exc)) from exc


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
    cid: uuid.UUID = await _require_network_merchandiser(user, db)
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
    cid = await _require_network_merchandiser(user, db)
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
        # Карточка без остатка — самый безопасный случай слияния, а не запрещённый:
        # сливать нечего, кроме имени и штрихкодов. Прежнее условие запрещало
        # ровно то, ради чего слияние и нужно на новой станции: импорт справочника
        # АЗС 8 (31.08.2026) дал 37 карточек-тёзок 208 — те же сигареты с другим
        # EAN партии, те же перчатки, тот же кофе, — и слить их было нечем.
        # Проверяем лишь, что дубль принадлежит компании товароведа.
        свой = (await db.execute(text("""
            SELECT 1 FROM edge.item WHERE id = :id AND (company_id = :cid OR company_id IS NULL)
        """), {"id": body.alias_id, "cid": cid})).scalar_one_or_none()
        if свой is None:
            raise HTTPException(409, "Дубль не принадлежит выбранной компании")
    exists = (await db.execute(select(StoreItemAlias.id).where(
        StoreItemAlias.company_id == cid,
        StoreItemAlias.alias_uuid == alias["uuid"],
    ))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "Карточка уже была слита")

    stats = {"barcodes": 0, "prices": 0, "stock_rows": 0, "recipes": 0,
             "assortment": 0, "matrix_rules": 0}
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

    # Станции берём из справочника, а не по наличию агента: станция заводится
    # в центре ДО первого запуска агента, и её цены слияние обязано перенести.
    # 31.08.2026 на АЗС 8 (агента ещё нет) цены остались на слитых карточках —
    # то есть на удалённых, и позиция теряла цену молча.
    stations = (await db.execute(text("""
        SELECT id FROM edge.station WHERE company_id = :cid OR company_id IS NULL
    """), {"cid": cid})).scalars().all()
    stations = sorted(set(stations) | set((await db.execute(select(EdgeAgent.station_id).where(
        EdgeAgent.company_id == cid))).scalars().all()))
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

    # Правила матрицы ходят за карточкой: правило смотрит на item_id, и после
    # слияния оно осиротело бы вместе с дублем. 31.08.2026 так снова открылся
    # «ХОТ ДОГ XL», закрытый на АЗС 8 за отсутствием продаж, — молча.
    matrix_moved = await db.execute(text("""
        UPDATE edge.matrix_rule r SET item_id = :canon
         WHERE r.item_id = :alias
           AND NOT EXISTS (
               SELECT 1 FROM edge.matrix_rule x
                WHERE x.item_id = :canon AND x.subject = r.subject
                  AND x.station_id IS NOT DISTINCT FROM r.station_id
                  AND x.valid_to IS NULL)
    """), {"canon": body.canonical_id, "alias": body.alias_id})
    stats["matrix_rules"] = matrix_moved.rowcount or 0
    await db.execute(text("""
        UPDATE edge.matrix_rule SET valid_to = now()
         WHERE item_id = :alias AND valid_to IS NULL
    """), {"alias": body.alias_id})

    # ⚠ Техкарты разложены ПО СТАНЦИЯМ: у одного блюда своя карта на каждой АЗС
    # (сырьё у станций разное — у «Двойного Эспрессо» на 208 пять строк, на
    # 8 три). Поэтому занятость версии проверяется по тройке
    # «блюдо + станция + версия», а не по паре без станции.
    #
    # Без станции в ключе слияние теряло карту дубля молча: у канона и у дубля
    # версия одна и та же (v1), условие «у канона такой версии нет» не
    # выполнялось, и карта оставалась висеть на удалённой карточке. Станция,
    # чей справочник только что импортировали, оказывалась без техкарт —
    # блюдо продаётся, а расход сырья не считается. Видно это не сразу, а на
    # первой сверке остатков.
    recipes = (await db.execute(select(StoreRecipeVersion).where(
        StoreRecipeVersion.company_id == cid))).scalars().all()
    recipe_keys = {(recipe.dish_uuid, recipe.station_id, recipe.version)
                   for recipe in recipes}
    for recipe in recipes:
        changed = False
        if (recipe.dish_uuid == alias["uuid"] and
                (canonical["uuid"], recipe.station_id, recipe.version) not in recipe_keys):
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

    # Артикул слитой карточки живёт дальше алиасом канона: человек помнит
    # старый номер, он напечатан на прошлогоднем ценнике и стоит в уже
    # проведённых документах. У самого дубля номер снимаем — иначе он ищется
    # в двух местах сразу и приводит к удалённой карточке.
    await db.execute(text("""
        INSERT INTO edge.item_code (item_id, code, kind, note)
        SELECT :canon, i.sku, 'sku', :note FROM edge.item i
         WHERE i.id = :alias AND i.sku IS NOT NULL
        ON CONFLICT DO NOTHING
    """), {"canon": body.canonical_id, "alias": body.alias_id,
           "note": f"артикул слитой карточки «{alias['name']}»"})
    await db.execute(text("""
        UPDATE edge.item SET deleted = true, sku = NULL, updated_at = now() WHERE id = :id
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
    cid: uuid.UUID = await _require_network_merchandiser(user, db)
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


@router.post("/partners")
async def store_partner_create(
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести контрагента-поставщика в центре.

    Реквизиты — те, без которых его не создать в бухгалтерии: наименование
    обязательно, ИНН и КПП желательны. Без ИНН тоже можно: техконтрагенты
    (наличная закупка в соседнем магазине — «Агроторг» и подобные) в учёте
    ведутся без реквизитов принципиально, и приёмник БП такого контрагента
    создаёт по одному наименованию.

    Юрлицо или ИП определяется длиной ИНН (12 знаков — физлицо/ИП): так же
    решает приёмник, и расхождения между центром и бухгалтерией не будет.
    """
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Контрагентов сети ведёт товаровед сети")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "наименование обязательно")
    inn = "".join(c for c in str(payload.get("inn") or "") if c.isdigit())
    kpp = str(payload.get("kpp") or "").strip()
    if inn and len(inn) not in (10, 12):
        raise HTTPException(400, "ИНН бывает 10 знаков у юрлица и 12 у ИП")
    cid = access.company_id

    # Тот же контрагент уже может быть заведён — тогда возвращаем его, а не
    # плодим двойника: справочник сети один на все станции, и дубли по ИНН
    # разбираются потом руками.
    if inn:
        было = (await db.execute(text(r"""
            SELECT id, name FROM edge.partner
             WHERE company_id = :cid
               AND regexp_replace(coalesce(inn,''), '\D', '', 'g') = :inn
             LIMIT 1
        """), {"cid": cid, "inn": inn})).mappings().first()
        if было:
            return {"id": было["id"], "name": было["name"], "created": False}

    канон = Counterparty(
        id=uuid.uuid4(), company_id=cid, inn=inn or None, kpp=kpp or None,
        name=name, full_name=str(payload.get("name_full") or "").strip() or name,
        type="ИП" if len(inn) == 12 else "ЮЛ", aliases=[], kind="external",
        raw={"source": "center_manual"},
    )
    db.add(канон)
    await db.flush()
    partner_id = (await db.execute(text("""
        INSERT INTO edge.partner
            (company_id, external_uuid, name, name_full, inn, kpp, role, source, comment)
        VALUES (:cid, :uuid, :name, :full, :inn, :kpp, :role, 'master', :comment)
        RETURNING id
    """), {"cid": cid, "uuid": канон.id, "name": name,
           "full": канон.full_name, "inn": inn, "kpp": kpp,
           "role": str(payload.get("role") or "supplier"),
           "comment": str(payload.get("comment") or "").strip()})).scalar_one()

    # Станции, с которыми он работает: без этой связи справочник ему не уедет
    # (обычная отправка шлёт только «своих»).
    for st in payload.get("stations") or []:
        await db.execute(text("""
            INSERT INTO edge.partner_station (partner_id, station_id)
            VALUES (:p, :s) ON CONFLICT DO NOTHING
        """), {"p": partner_id, "s": int(st)})

    # Договор заводится тем же движением: поставщик без договора бесполезен —
    # приход по нему станция всё равно не проведёт. Пишем в канонический слой
    # (`contracts`), из которого договор берёт выгрузка в бухгалтерию: вторая
    # таблица договоров означала бы, что документ уедет с UUID, которого в БП
    # никто не найдёт.
    договор = payload.get("contract") or {}
    contract_id = None
    if договор:
        organization_id = договор.get("organization_id")
        if not organization_id:
            raise HTTPException(400, "у договора должна быть организация")
        имя = str(договор.get("name") or договор.get("title") or "Основной договор").strip()
        номер = str(договор.get("number") or "").strip()
        contract_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO contracts
                (id, company_id, number, date, title, counterparty_id, organization_id,
                 type, kind, currency, raw)
            VALUES (:id, :cid, :number, :date, :title, :cp, :org,
                    'поставка', 'СПоставщиком', 'RUB',
                    jsonb_build_object('source', 'center_manual', 'name', :title))
        """), {"id": contract_id, "cid": cid, "number": номер or имя,
               "date": str(договор.get("signed_on") or договор.get("date") or "")[:10],
               "title": имя, "cp": канон.id, "org": organization_id})
    await db.commit()
    return {"id": partner_id, "supplier_id": str(канон.id), "name": name,
            "created": True, "contract_id": contract_id}


@router.get("/contracts")
async def store_contracts(
    partner_id: int | None = Query(None, description="только договоры этого контрагента edge.partner"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Справочник договоров с поставщиками.

    Договор живёт в каноническом слое Ledger (`contracts`) — том самом, из
    которого его берёт выгрузка в бухгалтерию: у документа стоит UUID договора,
    и если канонической записи нет, документ в БП не уходит вовсе. Поэтому
    второй, «станционной», таблицы договоров нет и быть не должно.
    """
    access = await _receipt_access(user, db)
    где = ["c.company_id = :cid"]
    args: dict = {"cid": access.company_id}
    if partner_id is not None:
        где.append("""c.counterparty_id = (
            SELECT p.external_uuid FROM edge.partner p WHERE p.id = :pid)""")
        args["pid"] = partner_id
    rows = (await db.execute(text(f"""
        SELECT c.id, c.number, c.date, c.title, c.kind, c.currency,
               c.counterparty_id, cp.name AS counterparty_name, cp.inn,
               c.organization_id, o.name AS organization_name, c.is_closed
          FROM contracts c
          JOIN counterparties cp ON cp.id = c.counterparty_id
          LEFT JOIN organizations o ON o.id = c.organization_id
         WHERE {" AND ".join(где)}
         ORDER BY cp.name, c.number
    """), args)).mappings().all()
    return {"contracts": [dict(r) for r in rows]}


@router.post("/contracts")
async def store_contract_save(
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завести договор с поставщиком.

    Реквизиты — те, без которых договор не создать в бухгалтерии (см.
    `TL_МаппингЦБ.ПолучитьДоговорПоUUID`): контрагент обязателен, дальше нужно
    хотя бы одно из «наименование» или «номер», плюс дата и вид договора.
    Валюту приёмник ставит сам рублёвую, если её не передали.
    """
    access = await _receipt_access(user, db)
    if not access.network:
        raise HTTPException(403, "Договоры ведёт товаровед сети")
    counterparty_id = payload.get("counterparty_id")
    organization_id = payload.get("organization_id")
    title = str(payload.get("title") or payload.get("name") or "").strip()
    number = str(payload.get("number") or "").strip()
    if not counterparty_id or not organization_id:
        raise HTTPException(400, "нужны контрагент и организация")
    if not title and not number:
        raise HTTPException(400, "нужно наименование договора или его номер")
    args = {
        "cid": access.company_id, "cp": counterparty_id, "org": organization_id,
        "number": number or title, "date": str(payload.get("date") or "")[:10],
        "title": title or f"Договор {number}",
        "kind": str(payload.get("kind") or "СПоставщиком"),
        "currency": str(payload.get("currency") or "RUB"),
        "type": str(payload.get("type") or "поставка"),
        "comment": str(payload.get("comment") or "").strip() or None,
    }
    if payload.get("id"):
        args["id"] = payload["id"]
        await db.execute(text("""
            UPDATE contracts
               SET number = :number, date = :date, title = :title, kind = :kind,
                   currency = :currency, comment = :comment
             WHERE id = :id AND company_id = :cid
        """), args)
        новый = payload["id"]
    else:
        новый = str(uuid.uuid4())
        args["id"] = новый
        await db.execute(text("""
            INSERT INTO contracts
                (id, company_id, number, date, title, counterparty_id, organization_id,
                 type, kind, currency, comment, raw)
            VALUES (:id, :cid, :number, :date, :title, :cp, :org,
                    :type, :kind, :currency, :comment,
                    jsonb_build_object('source', 'center_manual', 'name', :title))
        """), args)
    await db.commit()
    return {"id": str(новый), "title": args["title"], "number": args["number"]}


@router.post("/contracts/push/{station_id}")
async def store_push_contracts(
    station_id: int,
    all_network: bool = Query(False, description="слать все договоры сети, а не только своих поставщиков"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить станции справочник договоров.

    По умолчанию — только по поставщикам этой станции. Станция без договора
    приёмку не проводит, поэтому пустую посылку не отправляем: пусть лучше
    останется прежний справочник, чем станция встанет.
    """
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    cid = access.company_id
    договоры = await partner_sync.договоры_payload(db, cid, station_id,
                                                   вся_сеть=all_network)
    if not договоры:
        raise HTTPException(404, "Для станции нет ни одного договора")
    db.add(EdgeDownlink(
        company_id=cid, station_id=station_id, kind="contracts",
        payload={"contracts": договоры}, note=f"договоров {len(договоры)}"))
    await db.commit()
    return {"station_id": station_id, "contracts": len(договоры)}


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
    access = await _receipt_access(user, db)
    _require_receipt_station(access, station_id)
    if all_network and not access.network:
        raise HTTPException(403, "Весь справочник сети доступен только товароведу сети")
    cid = access.company_id
    поставщики = await partner_sync.поставщики_payload(db, cid, station_id,
                                                       вся_сеть=all_network)
    if not поставщики:
        raise HTTPException(404, "Для станции нет ни одного контрагента")
    db.add(EdgeDownlink(
        company_id=cid, station_id=station_id, kind="partners",
        payload={"partners": поставщики}, note=f"поставщиков {len(поставщики)}"))
    await db.commit()
    return {"station_id": station_id, "partners": len(поставщики),
            "с_историей": sum(1 for p in поставщики if p.get("docs_1c"))}


# ─────────────────────── Отчёты по периоду (ПОСЛЕДНИМИ) ─────────────────────
#
# Маршрут с одним подставляемым сегментом обязан стоять В КОНЦЕ файла: FastAPI
# перебирает пути в порядке объявления, и «/{report}» съедает любой конкретный
# односегментный путь, объявленный после него. Так и случилось — «Признание со
# станций» и «Коллизии ШК» отвечали «query.date_from: Field required», хотя
# периода у них нет и в помине: запрос уходил не в свой обработчик.
#
# Ниже этой строки конкретные маршруты не добавлять.
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
        raise HTTPException(404, f"Неизвестный отчёт: {report}")
    return await method(date.fromisoformat(date_from), date.fromisoformat(date_to), _stations(stations))
