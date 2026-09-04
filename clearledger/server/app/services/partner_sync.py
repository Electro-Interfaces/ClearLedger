# -*- coding: utf-8 -*-
"""Справочники контрагентов на станциях: держатся свежими сами.

Станция без поставщика и договора накладную не проведёт — приход просто некому
и не по чему оформить. Отправка при этом была только ручной (`POST
/store/partners/push/{station}`), кнопки в интерфейсе нет вовсе, и АЗС 8 в день
пуска обнаружила пустой список: контрагенты 208-й ей не полагались, а своих
она ещё не нажила.

Поэтому состав справочника сворачивается в отпечаток, а отпечаток кладётся в
ключ идемпотентности задания. Дальше всё делает такт: heartbeat раз в минуту
спрашивает «этот состав у станции уже есть?» — и, если справочник изменился,
задание встаёт в очередь само. Ключ считается от содержания, а не от часа: не
менялось — не поедет.
"""
import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EdgeDownlink

log = logging.getLogger(__name__)

# Что отдаём станции: весь неархивный справочник сети, а не только «своих».
#
# Раньше по умолчанию слали контрагентов, с которыми станция уже работала, —
# чтобы товаровед не искал своего среди сотни чужих юрлиц. Для сети из одной
# АЗС это одно и то же, для второй — пустой список: связь «поставщик × станция»
# заводится ПОСЛЕ первой поставки, а принять её не от кого. Справочник сети
# один; если он разрастётся настолько, что мешает, сузим отбор здесь.
ВСЯ_СЕТЬ = True

# Поля, по которым считается отпечаток. История поставок в него не входит:
# она меняется от каждой накладной, и справочник уезжал бы на станцию по
# нескольку раз в день без единой правки в самом справочнике.
ПОЛЯ_ПОСТАВЩИКА = ("id", "name", "name_full", "inn", "kpp", "role", "archived")
ПОЛЯ_ДОГОВОРА = ("id", "partner_id", "name", "number", "signed_on", "org_uuid")


def _отпечаток(строки: list[dict], поля: tuple[str, ...]) -> str:
    основа = json.dumps([[str(с.get(п, "")) for п in поля] for с in строки],
                        ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(основа.encode("utf-8")).hexdigest()[:12]


async def поставщики_payload(db: AsyncSession, cid: uuid.UUID, station_id: int,
                             вся_сеть: bool = ВСЯ_СЕТЬ,
                             с_историей: bool = True) -> list[dict]:
    """Справочник поставщиков в том виде, в каком его получает станция."""
    фильтр = "" if вся_сеть else """
        AND EXISTS (SELECT 1 FROM edge.partner_station ps
                     WHERE ps.partner_id = p.id AND ps.station_id = :s)
    """
    rows = (await db.execute(text(f"""
        SELECT p.id, p.external_uuid, p.name, p.name_full, p.inn, p.kpp,
               p.role, p.comment, p.archived
        FROM edge.partner p
        WHERE p.company_id = :cid AND NOT p.archived {фильтр}
        ORDER BY p.name
    """), {"cid": cid, "s": station_id})).mappings().all()
    if not rows:
        return []

    # История работы — из документов 1С, а не только из локальных приёмок:
    # станция видит лишь то, что принимала сама, а поставки за годы лежат в ЦБ.
    история: dict[str, dict] = {}
    if с_историей:
        from .goods_dashboard import GoodsDashboardService
        try:
            история = await GoodsDashboardService(db, cid).supplier_history(str(station_id))
        except Exception as exc:  # noqa: BLE001
            # Без истории справочник рабочий, без справочника станция стоит.
            log.warning("АЗС %s: история поставок не собрана: %s", station_id, exc)
    return [{"id": str(r["external_uuid"]) if r["external_uuid"] else f"m{r['id']}",
             "name": r["name"], "name_full": r["name_full"] or "",
             "inn": r["inn"] or "", "kpp": r["kpp"] or "", "role": r["role"],
             "comment": r["comment"] or "", "archived": r["archived"],
             **(история.get(r["name"]) or {})} for r in rows]


async def договоры_payload(db: AsyncSession, cid: uuid.UUID, station_id: int,
                           вся_сеть: bool = ВСЯ_СЕТЬ) -> list[dict]:
    """Справочник договоров в том виде, в каком его получает станция."""
    фильтр = "" if вся_сеть else """
        AND EXISTS (SELECT 1 FROM edge.partner p
                     JOIN edge.partner_station ps ON ps.partner_id = p.id
                    WHERE p.external_uuid = c.counterparty_id AND ps.station_id = :s)
    """
    rows = (await db.execute(text(f"""
        SELECT c.id, c.number, c.date, c.title, c.kind,
               c.counterparty_id, cp.name AS counterparty_name,
               c.organization_id, o.name AS organization_name
          FROM contracts c
          JOIN counterparties cp ON cp.id = c.counterparty_id
          LEFT JOIN organizations o ON o.id = c.organization_id
         WHERE c.company_id = :cid AND NOT coalesce(c.is_closed, false) {фильтр}
         ORDER BY cp.name, c.number
    """), {"cid": cid, "s": station_id})).mappings().all()
    return [{"id": str(r["id"]), "partner_id": str(r["counterparty_id"]),
             "partner_name": r["counterparty_name"],
             "name": r["title"] or r["number"],
             # Номер, дословно повторяющий наименование, — след импорта из 1С:
             # отдать его значит показать «Основной договор №Основной договор».
             "number": "" if (r["number"] or "").strip().casefold()
                             == (r["title"] or "").strip().casefold()
                       else (r["number"] or ""),
             "signed_on": str(r["date"] or "")[:10],
             "org_name": r["organization_name"] or "",
             "org_uuid": str(r["organization_id"]) if r["organization_id"] else "",
             "kind": "supplier", "archived": False} for r in rows]


async def _уже_ставили(db: AsyncSession, cid: uuid.UUID, ключ: str) -> bool:
    return (await db.execute(select(EdgeDownlink.id).where(
        EdgeDownlink.company_id == cid,
        EdgeDownlink.idempotency_key == ключ))).scalar_one_or_none() is not None


async def обеспечить(db: AsyncSession, cid: uuid.UUID, station_id: int) -> list[str]:
    """Досылает станции справочники, если их состав изменился.

    Возвращает список поставленных заданий — для журнала. Ничего не изменилось
    — не пишет в базу вовсе.
    """
    поставлено: list[str] = []

    # Отпечаток считаем по справочной части: история поставок дорогая (обход
    # документов ЦБ) и в ключ не входит — собираем её, только когда шлём.
    краткие = await поставщики_payload(db, cid, station_id, с_историей=False)
    if краткие:
        ключ = f"partners:{station_id}:{_отпечаток(краткие, ПОЛЯ_ПОСТАВЩИКА)}"
        if not await _уже_ставили(db, cid, ключ):
            полные = await поставщики_payload(db, cid, station_id)
            db.add(EdgeDownlink(
                company_id=cid, station_id=station_id, kind="partners",
                payload={"partners": полные}, idempotency_key=ключ,
                note=f"поставщиков {len(полные)}"))
            поставлено.append(f"partners:{len(полные)}")

    договоры = await договоры_payload(db, cid, station_id)
    if договоры:
        ключ = f"contracts:{station_id}:{_отпечаток(договоры, ПОЛЯ_ДОГОВОРА)}"
        if not await _уже_ставили(db, cid, ключ):
            db.add(EdgeDownlink(
                company_id=cid, station_id=station_id, kind="contracts",
                payload={"contracts": договоры}, idempotency_key=ключ,
                note=f"договоров {len(договоры)}"))
            поставлено.append(f"contracts:{len(договоры)}")

    if поставлено:
        await db.commit()
        log.info("АЗС %s: справочники контрагентов досланы (%s)",
                 station_id, ", ".join(поставлено))
    return поставлено


async def сводка(db: AsyncSession, cid: uuid.UUID) -> dict[int, dict]:
    """Синхронны ли справочники по каждой станции — для экрана центра.

    Станция «в ногу», когда доставленное задание несёт тот самый отпечаток,
    что даёт справочник сейчас. Задание в очереди — «в пути»: канал вниз
    забирает сама станция, и минута задержки это норма, а не авария.
    """
    доставлено = {(r["station_id"], r["kind"]): r for r in (await db.execute(text("""
        SELECT DISTINCT ON (station_id, kind) station_id, kind, idempotency_key,
               delivered_at,
               coalesce(jsonb_array_length(payload->'partners'),
                        jsonb_array_length(payload->'contracts'), 0) AS строк
          FROM core.edge_downlink
         WHERE company_id = :cid AND kind IN ('partners', 'contracts')
               AND delivered_at IS NOT NULL AND cancelled_at IS NULL
         ORDER BY station_id, kind, delivered_at DESC
    """), {"cid": cid})).mappings().all()}
    в_пути = {(r["station_id"], r["kind"]) for r in (await db.execute(text("""
        SELECT DISTINCT station_id, kind FROM core.edge_downlink
         WHERE company_id = :cid AND kind IN ('partners', 'contracts')
               AND delivered_at IS NULL AND cancelled_at IS NULL
    """), {"cid": cid})).mappings().all()}

    станции = [r[0] for r in (await db.execute(text(
        "SELECT id FROM edge.station WHERE company_id = :c OR company_id IS NULL ORDER BY id"
    ), {"c": cid})).all()]

    итог: dict[int, dict] = {}
    for st in станции:
        краткие = await поставщики_payload(db, cid, st, с_историей=False)
        договоры = await договоры_payload(db, cid, st)
        ожидаем = {"partners": (len(краткие), _отпечаток(краткие, ПОЛЯ_ПОСТАВЩИКА)),
                   "contracts": (len(договоры), _отпечаток(договоры, ПОЛЯ_ДОГОВОРА))}
        строка: dict[str, Any] = {}
        for kind, (сколько, отп) in ожидаем.items():
            было = доставлено.get((st, kind))
            строка[kind] = {
                "в_центре": сколько,
                "на_станции": было["строк"] if было else 0,
                "доставлено": было["delivered_at"] if было else None,
                "синхронно": bool(было and было["idempotency_key"] == f"{kind}:{st}:{отп}"),
                "в_пути": (st, kind) in в_пути,
            }
        итог[st] = строка
    return итог
