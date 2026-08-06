"""Себестоимость товара для сети: факт станции и ориентир по закупкам.

Почему это отдельный слой. Станция знает себестоимость только по тому, что
приняла сама: приход кладёт цену в журнал движений, и дальше остаток считается
по ней. Но переход на edge-учёт начался со снимка остатков 1С, а снимок несёт
розничную цену и не несёт закупочной — поэтому 208 показывает «себестоимость
известна 0 %» при живом остатке в 68 тысяч единиц.

При этом закупочная цена в системе ЕСТЬ: она лежит в приёмках, которые 1С уже
выгрузила пакетами (`purchase`), и в реестре приёмок станции. По ним считается
ОРИЕНТИР — цена последней закупки карточки. Это оценка, а не факт, и смешивать
её с фактом нельзя: отчёт обязан показывать, чем посчитана строка, иначе
«стоимость запаса» превращается в число без происхождения.

Берётся именно последняя закупка, а не средняя за всё время: запас оценивается
по тому, во что обойдётся его замещение сегодня, а прошлогодняя цена сигарет к
сегодняшней полке отношения не имеет.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ориентиры(db: AsyncSession, cid, stations: list[int] | None = None) -> dict[str, dict]:
    """UUID карточки → {cost, at, source} по последней известной закупке.

    Источников два, и они не равны по достоверности: приёмка станции (её завёл
    человек на АЗС) и приёмка из выгрузки 1С (исторический контур). Побеждает
    более свежая дата — обе описывают одну и ту же поставку товара.
    """
    p = {"cid": cid}
    ф_p = " AND p.station_id = ANY(:st)" if stations else ""
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations

    итог: dict[str, dict] = {}

    def предложить(uuid: str, цена: float, когда, источник: str) -> None:
        if not uuid or цена <= 0 or когда is None:
            return
        было = итог.get(uuid)
        if было is None or было["at"] < когда:
            итог[uuid] = {"cost": round(цена, 4), "at": когда, "source": источник}

    # Документы приёмки из пакетов: цена строки — без НДС, как её ведёт 1С.
    for r in (await db.execute(text(f"""
        SELECT l->>'Номенклатура' AS uuid,
               (l->>'Сумма')::numeric AS amount,
               (l->>'Количество')::numeric AS qty,
               coalesce((d->>'Дата')::timestamptz, p.received_at) AS at
        FROM edge_packets p,
             LATERAL jsonb_array_elements(coalesce(p.payload->'Документы','[]'::jsonb)) d,
             LATERAL jsonb_array_elements(coalesce(d->'Товары','[]'::jsonb)) l
        WHERE p.company_id = :cid{ф_p} AND d->>'Тип' = 'purchase'
          AND coalesce((l->>'Количество')::numeric, 0) > 0
    """), p)).mappings().all():
        кол = float(r["qty"] or 0)
        if кол > 0:
            предложить(str(r["uuid"] or ""), float(r["amount"] or 0) / кол, r["at"], "закупка 1С")

    # Реестр приёмок станции: сюда попадает то, что принял человек на АЗС.
    for r in (await db.execute(text(f"""
        SELECT lines, doc_date FROM store_receipts
        WHERE company_id = :cid{ф} AND lines IS NOT NULL
    """), p)).mappings().all():
        for l in r["lines"] or []:
            кол = float(l.get("qty_fact") or l.get("qty_expected") or 0)
            цена = float(l.get("price") or 0)
            if кол > 0 and цена > 0:
                предложить(str(l.get("nomenclature_ref") or ""), цена, r["doc_date"], "приёмка станции")

    return итог
