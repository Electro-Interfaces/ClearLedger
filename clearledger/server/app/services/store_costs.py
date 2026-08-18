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

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ориентиры(db: AsyncSession, cid, stations: list[int] | None = None,
                    на_дату=None) -> dict[str, dict]:
    """UUID карточки → {cost, at, source} по последней известной закупке.

    `на_дату` ограничивает поиск моментом: «во что обходился товар тогда».
    Сравнение периодов без этого показывало бы одну и ту же себестоимость в
    обоих окнах, и фактор закупки всегда выходил нулём.

    Источников два, и они не равны по достоверности: приёмка станции (её завёл
    человек на АЗС) и приёмка из выгрузки 1С (исторический контур). Побеждает
    более свежая дата — обе описывают одну и ту же поставку товара.
    """
    p = {"cid": cid}
    ф_p = " AND p.station_id = ANY(:st)" if stations else ""
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    if на_дату is not None:
        p["on"] = на_дату
        ф_p += " AND coalesce((d->>'Дата')::timestamptz, p.received_at) <= :on"
        ф += " AND doc_date <= :on"

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
          AND NOT EXISTS (
              SELECT 1 FROM store_receipts r
               WHERE r.company_id = p.company_id AND r.status = 'accepted'
                 AND (r.source_uuid = d->>'ИсточникUUID'
                      OR r.id::text = d->>'document_id')
          )
    """), p)).mappings().all():
        кол = float(r["qty"] or 0)
        if кол > 0:
            предложить(str(r["uuid"] or ""), float(r["amount"] or 0) / кол, r["at"], "закупка 1С")

    # Неизменяемый ledger хранит фактическую себестоимость, включая услуги,
    # которые поставщик включил в стоимость партии.
    for r in (await db.execute(text(f"""
        SELECT m.item_uuid AS uuid, m.unit_cost AS cost, r.doc_date AS at
          FROM store_receipt_stock_movements m
          JOIN store_receipts r ON r.id = m.receipt_id
         WHERE r.company_id = :cid{ф.replace('station_id', 'r.station_id')}
           AND r.status = 'accepted' AND m.kind = 'receipt_acceptance'
           {"AND r.doc_date <= :on" if на_дату is not None else ""}
    """), p)).mappings().all():
        предложить(str(r["uuid"] or ""), float(r["cost"] or 0), r["at"], "ledger приёмки")

    # Старые принятые документы до появления ledger остаются fallback.
    for r in (await db.execute(text(f"""
        SELECT lines, doc_date FROM store_receipts
        WHERE company_id = :cid{ф} AND status = 'accepted' AND lines IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM store_receipt_stock_movements m
               WHERE m.receipt_id = store_receipts.id AND m.kind = 'receipt_acceptance')
    """), p)).mappings().all():
        for l in r["lines"] or []:
            кол = float(l.get("qty_fact") or l.get("qty_expected") or 0)
            цена = float(l.get("price") or 0)
            if кол > 0 and цена > 0:
                предложить(str(l.get("nomenclature_ref") or ""), цена, r["doc_date"], "приёмка станции")

    # Партии из 1С — стартовая себестоимость товара, который лежал на полке до
    # нас. Закупок по нему в нашей системе нет и не будет: на 208 это 271
    # позиция из 389 с непокрытой себестоимостью. После отключения станционной
    # 1С взять цифру будет неоткуда, поэтому срез партий снимается ДО Дня X и
    # загружается сюда один раз.
    #
    # Дата — дата документа партии, поэтому первая же наша приёмка того же
    # товара перебьёт стартовую цифру как более свежая. Так и задумано.
    for r in (await db.execute(text(f"""
        SELECT nomenclature_ref AS uuid, unit_price AS cost, snapshot_at AS at,
               batch_doc_date AS doc_date
          FROM inventory_batches
         WHERE company_id = :cid AND unit_price > 0
           {"AND snapshot_at <= :on" if на_дату is not None else ""}
    """), {k: v for k, v in p.items() if k != "st"})).mappings().all():
        когда = r["at"]
        if r["doc_date"]:
            # Дата документа партии в выгрузке 1С — строка; если разбирается,
            # она точнее момента снимка.
            try:
                разобрано = datetime.fromisoformat(str(r["doc_date"])[:19])
                когда = (разобрано.replace(tzinfo=timezone.utc)
                         if разобрано.tzinfo is None else разобрано)
            except ValueError:
                когда = r["at"]
        предложить(str(r["uuid"] or ""), float(r["cost"] or 0), когда, "партия 1С")

    return итог
