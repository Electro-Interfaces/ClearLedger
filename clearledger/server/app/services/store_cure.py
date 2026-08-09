"""Почему уходим из 1С: её сегодняшние болезни рядом с нашим состоянием.

Раздел «1С до перехода» показывает, чем болен переходный контур. Этот экран
отвечает на следующий вопрос — вылечили ли мы эти болезни у себя, или просто
перенесли их вместе с данными.

Болезни 1С показываются как есть и не гасятся нашей работой: дубль, который мы
у себя разобрали, в 1С никуда не делся и останется там до Дня X. Ровно в этом
довод в пользу перехода, и прятать его за «разобрано 94 из 94» нельзя.

Сравнение честное настолько, насколько позволяют источники, и это сказано на
экране: наш остаток приезжает пакетом раз в час, срез 1С снимается заданием и
на пилоте лежит с 28.07, а снимок цепочки станция делает раз в шесть часов.
Числа из разных моментов не вычитаются молча — у каждого блока стоит своя дата.

Болезни берутся не с потолка: это ровно те дефекты, которые видно на соседних
экранах раздела — дубли карточек, товар под несколькими кодами кассы, карточки
без штрихкода, фантомные строки регистра, минусовые остатки.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import dedup_service


async def compare(db: AsyncSession, cid: uuid.UUID, station_id: int | None = None) -> dict:
    """Состояние нашей базы против 1С по каждой болезни переходного контура."""
    p: dict = {"cid": cid}
    ф_ст = ""
    if station_id is not None:
        p["st"] = station_id
        ф_ст = " AND station_id = :st"

    # ── наш контур ───────────────────────────────────────────────────────────
    наш_остаток = (await db.execute(text(f"""
        SELECT count(*) AS строк, count(DISTINCT item_uuid) AS карточек,
               count(DISTINCT place) AS мест,
               coalesce(sum(quantity), 0) AS итого,
               count(*) FILTER (WHERE quantity < 0) AS минусов,
               coalesce(sum(quantity) FILTER (WHERE quantity < 0), 0) AS минус_единиц,
               max(snapshot_at) AS снято
        FROM store_stock_balances WHERE company_id = :cid{ф_ст}
    """), p)).mappings().first() or {}

    наш_каталог = (await db.execute(text("""
        SELECT (SELECT count(*) FROM edge.item) AS карточек,
               (SELECT count(DISTINCT item_id) FROM edge.barcode) AS со_штрихкодом,
               (SELECT count(*) FROM (
                    SELECT code FROM edge.barcode
                    GROUP BY code HAVING count(DISTINCT item_id) > 1) AS x) AS коллизий_шк,
               (SELECT count(*) FROM (
                    SELECT b.item_id FROM edge.ns_code n
                    JOIN edge.barcode b ON b.id = n.barcode_id
                    WHERE n.status = 'active'
                    GROUP BY b.item_id HAVING count(*) > 1) AS y) AS много_кодов
    """))).mappings().first() or {}

    # ── контур 1С (срез локальной базы станции) ──────────────────────────────
    одинс = (await db.execute(text("""
        SELECT count(*) AS карточек,
               count(*) FILTER (WHERE marked) AS помеченных,
               max(updated_at) AS срез
        FROM dedup_cards WHERE company_id = :cid
    """), {"cid": cid})).mappings().first() or {}

    # Дубли считает тот же сервис, что и экран «Дубли старой 1С»: два счёта
    # одной величины разойдутся на второй же неделе.
    сводка_дублей = await dedup_service.summary(db, cid)
    дубли = {"групп": сводка_дублей.get("dupGroups", 0),
             "лишних": сводка_дублей.get("excessCards", 0),
             "разобрано": сводка_дублей.get("scopedResolved", 0),
             "в_контуре": сводка_дублей.get("scopedGroups", 0)}

    # Последний снимок цепочки — единственный источник, который видит кассу и
    # 1С одновременно: фантомы регистра и лишние коды кассы живут только там.
    снимок = (await db.execute(text(f"""
        SELECT payload->'Документы'->0->'Снимок' AS s, received_at
        FROM edge_packets
        WHERE company_id = :cid AND kind = 'chain'{ф_ст}
        ORDER BY received_at DESC LIMIT 1
    """), p)).mappings().first()
    ц = (снимок or {}).get("s") or {}

    def _и(имя: str) -> int:
        try:
            return int(ц.get(имя) or 0)
        except (TypeError, ValueError):
            return 0

    карточек_1с = int(одинс.get("карточек") or 0)
    карточек_наш = int(наш_каталог.get("карточек") or 0)
    со_шк = int(наш_каталог.get("со_штрихкодом") or 0)

    болезни = [
        {
            "key": "duplicates",
            "name": "Дубли карточек",
            "onec": int(дубли.get("лишних") or 0),
            "onec_hint": f"{int(дубли.get('групп') or 0)} групп; разобрано нами {дубли.get('разобрано', 0)} из {дубли.get('в_контуре', 0)} в контуре 208, но в самой 1С они остаются",
            "ours": int(наш_каталог.get("коллизий_шк") or 0),
            "ours_hint": "штрихкодов, претендующих на две карточки",
            "cured": int(наш_каталог.get("коллизий_шк") or 0) < int(дубли.get("лишних") or 0),
            "how": "Карточка одна на сеть, а сопоставление идёт по штрихкоду, а не по имени: «LD Blue» и «LD Autograph» дедуп по именам считал одним товаром. Остаток разбирают в «Коллизиях ШК».",
            "screen": "barcode-collisions",
        },
        {
            "key": "multi_codes",
            "name": "Товар под несколькими кодами кассы",
            "onec": _и("касса_лишних_кодов"),
            "onec_hint": "лишних строк кассы сверх числа карточек",
            "ours": int(наш_каталог.get("много_кодов") or 0),
            "ours_hint": "карточек с двумя и более активными кодами",
            "cured": False,
            "how": "Пул кодов конечен, и старые привязки живут вместе с новыми. Лечится передачей кода канону — прежняя привязка становится исторической, чтобы вчерашние чеки читались.",
            "screen": "dedup",
        },
        {
            "key": "no_barcode",
            "name": "Карточки без штрихкода",
            "onec": None,
            "onec_hint": "в срезе 1С штрихкод не выгружается",
            "ours": max(карточек_наш - со_шк, 0),
            "ours_hint": f"из {карточек_наш} карточек каталога",
            "cured": None,
            "how": "Черновик со станции без штрихкода не заводится вовсе: неизвестный код при приёмке сам порождает карточку с ним. Замер 04.08.2026: у 76 % справочника 1С штрихкода не было.",
            "screen": "catalog-health",
        },
        {
            "key": "phantoms",
            "name": "Фантомные строки регистра",
            "onec": _и("одинс_фантомов"),
            "onec_hint": "карточек с ненулевыми строками и нулевой суммой",
            "ours": 0,
            "ours_hint": "конструкцией: остаток хранится по паре карточка × место",
            "cured": True,
            "how": "У 1С цена и штрихкод — измерения регистра, поэтому приход по одной цене не гасит списание по другой. У нас измерений два: карточка и место, и такой строки появиться неоткуда.",
            "screen": None,
        },
        {
            "key": "negatives",
            "name": "Минусовые остатки",
            # Минусы 1С отдельным числом не приезжают: их видно только построчно
            # в снимке цепочки. Прочерк честнее нуля — «нет данных» и «их нет»
            # это разные ответы, и весь раздел стоит на этом различии.
            "onec": None,
            "onec_hint": "в срезе 1С отдельным числом не выгружается",
            "ours": int(наш_остаток.get("минусов") or 0),
            "ours_hint": f"{round(float(наш_остаток.get('минус_единиц') or 0))} единиц ниже нуля",
            "cured": False,
            "how": "Наследство стартового переноса: продажи опередили приёмку. Лечится инвентаризацией — она единственный законный способ привести учёт к факту.",
            "screen": "inventory",
        },
    ]

    # ── чем лечим: работа, которая уже сделана ───────────────────────────────
    лечение = (await db.execute(text(f"""
        SELECT
          (SELECT count(*) FROM edge_packets p, LATERAL jsonb_array_elements(
                 coalesce(p.payload->'Документы','[]'::jsonb)) d
            WHERE p.company_id = :cid{ф_ст} AND d->>'Тип' = 'inventory') AS инвентаризаций,
          (SELECT max(coalesce((d->>'Дата')::timestamptz, p.received_at))
             FROM edge_packets p, LATERAL jsonb_array_elements(
                 coalesce(p.payload->'Документы','[]'::jsonb)) d
            WHERE p.company_id = :cid{ф_ст} AND d->>'Тип' = 'inventory') AS последняя_инвентаризация,
          (SELECT count(*) FROM edge.item_draft
            WHERE resolved_item IS NOT NULL AND NOT coalesce(rejected, false)) AS признано_карточек,
          (SELECT count(*) FROM edge.item_draft) AS черновиков_всего
    """), p)).mappings().first() or {}

    return {
        "station_id": station_id,
        "ours": {
            "снято": (наш_остаток.get("снято").isoformat()
                      if наш_остаток.get("снято") else None),
            "карточек_каталога": карточек_наш,
            "карточек_с_остатком": int(наш_остаток.get("карточек") or 0),
            "строк": int(наш_остаток.get("строк") or 0),
            "мест": int(наш_остаток.get("мест") or 0),
            "остаток": round(float(наш_остаток.get("итого") or 0), 3),
        },
        "onec": {
            "срез": (одинс.get("срез").isoformat() if одинс.get("срез") else None),
            "карточек": карточек_1с,
            "помеченных": int(одинс.get("помеченных") or 0),
            "остаток": float(ц.get("одинс_остаток") or 0),
            "снимок_остатка": ц.get("одинс_снято"),
            "карточек_с_остатком": _и("одинс_позиций"),
        },
        "diseases": болезни,
        "treatment": {
            "инвентаризаций": int(лечение.get("инвентаризаций") or 0),
            "последняя_инвентаризация": (
                лечение["последняя_инвентаризация"].isoformat()
                if лечение.get("последняя_инвентаризация") else None),
            "признано_карточек": int(лечение.get("признано_карточек") or 0),
            "черновиков_всего": int(лечение.get("черновиков_всего") or 0),
            # Разобранные группы берутся из той же сводки, что и экран «Дубли»:
            # свой счёт по всем компаниям давал 94 против 91 в контуре 208.
            "разобрано_групп": int(дубли.get("разобрано") or 0),
            "групп_в_контуре": int(дубли.get("в_контуре") or 0),
        },
    }
