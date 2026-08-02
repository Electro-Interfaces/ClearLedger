"""
Раздел «Магазин» — аналитика товароучёта сопутки/общепита.

Пока: «Обзор магазина» (GoodsDashboardService) — выручка/категории/оплаты/НДС/
динамика/станции по продажам из канала ЦБ ЭЛСИ.АЗК (DataEntry clean).
Далее: ABC, маржа/GMROI (FIFO с поступлениями), остатки, инвентаризация.
"""
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
from app.models import EdgeAgent, EdgeDownlink, StoreReceipt, User
from app.services import edge_nsi, edge_service
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

    desired = os.environ.get("EDGE_DESIRED_AGENT_VERSION", "0.35.0")
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
        SELECT i.external_uuid, i.name, i.unit, i.vat_rate, i.deleted
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
                     "price": float(price) if price is not None else None},
            note="НСИ: %s" % card["name"][:60],
        ))
    return len(targets)


@router.post("/nsi/push-recipes/{station_id}")
async def nsi_push_recipes(
    station_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отправить станции техкарты блюд.

    Без них продажа кофе не списывает ни зерно, ни стакан: остаток сырья растёт
    вечно, а каждая инвентаризация даёт недостачу, которую закрывают руками.
    Карт немного (на 208 — 32), поэтому шлём одним заданием целиком: дельтами
    управлять дороже, чем переслать всё.
    """
    cid: uuid.UUID = await scope_company_id(user, db)
    rows = (await db.execute(text("""
        SELECT r.dish_uuid, r.output_qty,
               coalesce(d.name, '')                         AS dish_name,
               json_agg(json_build_object(
                   'item', l.item_uuid, 'qty', l.qty, 'unit', l.unit,
                   'name', coalesce(i.name, '')) ORDER BY l.item_uuid) AS lines
        FROM edge.recipe r
        JOIN edge.recipe_line l ON l.recipe_id = r.id
        LEFT JOIN edge.item d ON d.external_uuid = r.dish_uuid
        LEFT JOIN edge.item i ON i.external_uuid = l.item_uuid
        GROUP BY r.dish_uuid, r.output_qty, d.name
        ORDER BY d.name
    """))).mappings().all()
    if not rows:
        raise HTTPException(404, "Техкарт нет — сначала импортируйте их из пакетов ЦБ")

    карты = [{
        "dish": str(r["dish_uuid"]), "name": r["dish_name"],
        "output": float(r["output_qty"] or 1),
        "lines": [{"item": str(l["item"]), "qty": float(l["qty"]),
                   "unit": l["unit"] or "", "name": l["name"] or ""}
                  for l in r["lines"]],
    } for r in rows]

    db.add(EdgeDownlink(
        company_id=cid, station_id=station_id, kind="recipes",
        payload={"recipes": карты},
        note="техкарты: %d блюд" % len(карты),
    ))
    await db.commit()
    return {"ok": True, "station_id": station_id, "блюд": len(карты),
            "ингредиентов": sum(len(k["lines"]) for k in карты)}


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
    сводка = (await db.execute(text("""
        SELECT s.place,
               coalesce(pl.name, 'место ' || s.place)                    AS name,
               coalesce(pl.is_sales_floor, s.place = s.station_id::text) AS sales_floor,
               count(*)                                                  AS positions,
               sum(s.qty)                                                AS qty,
               max(s.updated_at)                                         AS updated_at
        FROM edge.stock s
        LEFT JOIN edge.place pl ON pl.station_id = s.station_id AND pl.code = s.place
        WHERE s.station_id = :st
        GROUP BY s.place, pl.name, pl.is_sales_floor, s.station_id
        ORDER BY sales_floor DESC, s.place
    """), {"st": station_id})).mappings().all()

    # Товар, лежащий не в зале: он не пробивается кассой, пока его не выложат.
    # Это и есть рабочий список товароведа на смену.
    не_в_зале = (await db.execute(text("""
        SELECT v.place_name, v.item_name, v.barcode, v.qty
        FROM edge.v_stock_by_place v
        WHERE v.station_id = :st AND NOT v.is_sales_floor AND v.qty > 0
        ORDER BY v.qty DESC LIMIT 200
    """), {"st": station_id})).mappings().all()

    return {
        "station_id": station_id,
        "places": [{**dict(r), "qty": float(r["qty"] or 0)} for r in сводка],
        "not_on_floor": [{**dict(r), "qty": float(r["qty"] or 0)} for r in не_в_зале],
    }


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
               kind, sku_class, is_dish, deleted, created_at, updated_at
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
    amount: float = 0


class ReceiptIn(BaseModel):
    station_id: int
    number: str | None = None
    doc_date: str | None = None
    supplier: str | None = None
    contract: str | None = None
    incoming_number: str | None = None
    incoming_date: str | None = None
    comment: str | None = None
    lines: list[ReceiptLine] = []


def _receipt_out(r: StoreReceipt) -> dict:
    lines = r.lines or []
    # Расхождение считаем на сервере: это главная колонка приёмки, и считать её
    # в двух местах нельзя -- разъедется.
    diff = sum(1 for l in lines
               if abs(float(l.get("qty_fact") or 0) - float(l.get("qty_expected") or 0)) > 1e-6)
    return {
        "id": str(r.id), "station_id": r.station_id, "number": r.number,
        "doc_date": r.doc_date, "supplier": r.supplier, "contract": r.contract,
        "incoming_number": r.incoming_number, "incoming_date": r.incoming_date,
        "status": r.status, "origin": r.origin, "comment": r.comment,
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


@router.post("/receipts/from-upd", status_code=201)
async def receipt_from_upd(
    station_id: int = Query(..., description="код АЗС, куда идёт поставка"),
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

    cid: uuid.UUID = await scope_company_id(user, db)
    now = datetime.now(timezone.utc)
    number = "УПД-%d-%s" % (station_id, now.strftime("%y%m%d-%H%M"))
    lines = [{
        "nomenclature_ref": None,
        "name": l["name"], "barcode": l["barcode"] or None,
        "qty_expected": l["qty_expected"], "qty_fact": 0,
        "price": l["price"], "vat_rate": l["vat_rate"] or None,
        "amount": 0,
        "mark_codes": l["mark_codes"], "pack_codes": l["pack_codes"],
    } for l in parsed["lines"]]

    row = StoreReceipt(
        company_id=cid, station_id=station_id, number=number, doc_date=now,
        supplier=parsed["supplier"] or None,
        incoming_number=parsed["incoming_number"] or None,
        # «К поступлению»: товар заявлен, но на складе его ещё нет — ровно
        # смысл ордерной схемы. Приёмщик переведёт в «принят», пересчитав.
        status="expected", origin="edo", lines=lines,
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

    db.add(EdgeDownlink(
        company_id=cid, station_id=row.station_id,
        kind="goods_receipt_expected",
        payload={
            "id": str(row.id), "number": row.number,
            "supplier": row.supplier, "incoming_number": row.incoming_number,
            "doc_date": row.doc_date.isoformat() if row.doc_date else None,
            "lines": row.lines or [],
        },
        note="приёмка %s" % row.number,
    ))
    if row.status == "draft":
        row.status = "expected"
    await db.commit()
    return {"ok": True, "station_id": row.station_id, "number": row.number,
            "lines": len(row.lines or [])}


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
    lines = [l.model_dump() for l in body.lines]
    total = _recalc(lines)
    now = datetime.now(timezone.utc)
    doc_date = datetime.fromisoformat(body.doc_date) if body.doc_date else now
    if doc_date.tzinfo is None:
        doc_date = doc_date.replace(tzinfo=timezone.utc)
    # Номер по умолчанию -- дата и станция: различимый документ нужен сразу,
    # сквозная нумерация появится вместе со справочником поставщиков.
    number = body.number or ("П-%d-%s" % (body.station_id, now.strftime("%y%m%d-%H%M")))

    row = StoreReceipt(
        company_id=cid, station_id=body.station_id, number=number, doc_date=doc_date,
        supplier=body.supplier, contract=body.contract,
        incoming_number=body.incoming_number,
        incoming_date=datetime.fromisoformat(body.incoming_date) if body.incoming_date else None,
        status="draft", origin="center", lines=lines,
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

    lines = [l.model_dump() for l in body.lines]
    row.total_amount = _recalc(lines)
    row.lines = lines
    row.supplier = body.supplier
    row.contract = body.contract
    row.incoming_number = body.incoming_number
    row.incoming_date = datetime.fromisoformat(body.incoming_date) if body.incoming_date else None
    row.comment = body.comment
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
        if not row.lines:
            raise HTTPException(400, "В документе нет позиций")
        if not any(float(l.get("qty_fact") or 0) > 0 for l in row.lines):
            raise HTTPException(400, "Ни одна позиция не посчитана по факту")
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
        raise HTTPException(404, str(e))
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
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Выгрузка в каталог: {e}")

    # След выгрузки: единственное действие раздела, меняющее состояние снаружи —
    # файл ложится в каталог обмена и уходит в БП. Хеш нужен, чтобы потом
    # опознать, какой именно пакет приёмник забрал (идемпотентность по ХешПакета).
    docs = sum(res.get("documents", {}).values())
    log_export(db, cid, user,
               f"Пакет ЦБ→БП, смена {shift_key}: {res.get('file')}, "
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
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сверка: {e}")


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
