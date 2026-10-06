"""Журнал движений учёта станций — по дням.

Центр хранил один последний снимок остатков на станцию и не мог ответить ни
«сколько было на конец периода», ни «что было с товаром» (МАГ 07.10.2026:
центр повторяет отчёты станции — остатки на дату, историю товара, оборотку).
Станция шлёт свой журнал движений пакетом на местный день (`stock_moves`).

Журнал станции пересобирает продажи и правит документы задним числом, поэтому
день заменяется целиком. Редакцию дня различает подпись; пакет старше уже
принятой редакции того же дня не применяется — очередь могла его задержать
(неудачная попытка уходит после свежих пакетов, на АЗС 8 это обычное дело).

Движение может переехать в другой день (правка времени события задним числом).
Строку чужого дня снимаем, только если тот день принят в более старой
редакции; иначе строка принадлежит более свежему пакету и остаётся у него.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DDL = (
    """
    CREATE TABLE IF NOT EXISTS store_stock_moves (
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        station_id INTEGER NOT NULL,
        move_id BIGINT NOT NULL,
        day DATE NOT NULL,
        event_time TIMESTAMPTZ NOT NULL,
        recorded_at TIMESTAMPTZ,
        item_uuid VARCHAR(64) NOT NULL DEFAULT '',
        barcode VARCHAR(100) NOT NULL DEFAULT '',
        place VARCHAR(40) NOT NULL DEFAULT '',
        quantity NUMERIC(18,4) NOT NULL,
        doc_kind VARCHAR(40) NOT NULL,
        doc_id VARCHAR(200) NOT NULL DEFAULT '',
        doc_number VARCHAR(200) NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        unit_cost NUMERIC(16,4),
        PRIMARY KEY (company_id, station_id, move_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_store_stock_moves_day "
    "ON store_stock_moves (company_id, station_id, day)",
    "CREATE INDEX IF NOT EXISTS ix_store_stock_moves_item "
    "ON store_stock_moves (company_id, station_id, item_uuid, event_time)",
    """
    CREATE TABLE IF NOT EXISTS store_stock_move_days (
        company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        station_id INTEGER NOT NULL,
        day DATE NOT NULL,
        signature VARCHAR(200) NOT NULL,
        exported_at TIMESTAMPTZ NOT NULL,
        packet_uuid VARCHAR(64) NOT NULL,
        moves INTEGER NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (company_id, station_id, day)
    )
    """,
    # Редакция дня — момент сборки на станции в наносекундах. Секунд времени
    # выгрузки мало: две редакции одного такта неразличимы (ревизия 07.10.2026).
    "ALTER TABLE store_stock_move_days ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0",
    # Поля станции без потолка длины: строка длиннее столбца откатила бы приём
    # дня, и день стоял бы в повторах бесконечно (ревизия 07.10.2026).
    """
    ALTER TABLE store_stock_moves
        ALTER COLUMN item_uuid TYPE TEXT, ALTER COLUMN barcode TYPE TEXT,
        ALTER COLUMN place TYPE TEXT, ALTER COLUMN doc_kind TYPE TEXT,
        ALTER COLUMN doc_id TYPE TEXT, ALTER COLUMN doc_number TYPE TEXT
    """,
    "ALTER TABLE store_stock_move_days ALTER COLUMN signature TYPE TEXT, "
    "ALTER COLUMN packet_uuid TYPE TEXT",
)


def _время(v) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def ingest_stock_moves(db: AsyncSession, company_id, station_id: int,
                             payload: dict, packet_uuid: str) -> dict:
    """Заменить день станции движениями из пакета. Идемпотентно."""
    выгружено = _время(payload.get("ВремяВыгрузки"))
    рев_по_выгрузке = int(выгружено.timestamp() * 1e9) if выгружено else 0
    итог = {"days": 0, "moves": 0, "stale": 0}
    for doc in payload.get("Документы") or []:
        if not isinstance(doc, dict) or doc.get("Тип") != "stock_moves":
            continue
        день = datetime.strptime(str(doc["День"]), "%Y-%m-%d").date()
        p = {"cid": company_id, "st": station_id, "day": день}
        ред = int(doc.get("Редакция") or рев_по_выгрузке)
        принятый = (await db.execute(text("""
            SELECT revision FROM store_stock_move_days
             WHERE company_id = :cid AND station_id = :st AND day = :day
        """), p)).scalar_one_or_none()
        if принятый is not None and ред < принятый:
            итог["stale"] += 1
            continue
        движения = doc.get("Движения") or []
        ids = [int(м["id"]) for м in движения]
        await db.execute(text("""
            DELETE FROM store_stock_moves m
             WHERE m.company_id = :cid AND m.station_id = :st
               AND (m.day = :day OR (m.move_id = ANY(:ids) AND NOT EXISTS (
                    SELECT 1 FROM store_stock_move_days d
                     WHERE d.company_id = m.company_id AND d.station_id = m.station_id
                       AND d.day = m.day AND d.revision > :rev)))
        """), {**p, "ids": ids, "rev": ред})
        if движения:
            await db.execute(text("""
                INSERT INTO store_stock_moves (company_id, station_id, move_id, day,
                    event_time, recorded_at, item_uuid, barcode, place, quantity,
                    doc_kind, doc_id, doc_number, note, unit_cost)
                VALUES (:cid, :st, :id, :day, :event_time, :recorded_at, :item_uuid,
                    :barcode, :place, :qty, :doc_kind, :doc_id, :doc_number, :note, :cost)
                ON CONFLICT (company_id, station_id, move_id) DO NOTHING
            """), [{
                "cid": company_id, "st": station_id, "day": день, "id": int(м["id"]),
                "event_time": _время(м.get("event_time")) or _время(м.get("ts")),
                "recorded_at": _время(м.get("ts")),
                "item_uuid": str(м.get("item_uuid") or ""),
                "barcode": str(м.get("barcode") or ""),
                "place": str(м.get("place") or ""),
                "qty": float(м.get("qty") or 0),
                "doc_kind": str(м.get("doc_kind") or ""),
                "doc_id": str(м.get("doc_id") or ""),
                "doc_number": str(м.get("doc_number") or ""),
                "note": str(м.get("note") or ""),
                "cost": м.get("cost"),
            } for м in движения])
        await db.execute(text("""
            INSERT INTO store_stock_move_days (company_id, station_id, day, signature,
                exported_at, packet_uuid, moves, revision)
            VALUES (:cid, :st, :day, :sig, :exp, :pu, :n, :rev)
            ON CONFLICT (company_id, station_id, day) DO UPDATE SET
                signature = EXCLUDED.signature, exported_at = EXCLUDED.exported_at,
                packet_uuid = EXCLUDED.packet_uuid, moves = EXCLUDED.moves,
                revision = EXCLUDED.revision, received_at = now()
        """), {**p, "sig": str(doc.get("Подпись") or ""),
               "exp": выгружено or datetime.now().astimezone(), "pu": packet_uuid,
               "n": len(движения), "rev": ред})
        итог["days"] += 1
        итог["moves"] += len(движения)
        # Дни, которых в журнале станции больше нет (база восстановлена из
        # копии), снимаются — если центр принял их в более старой редакции.
        дни_станции = doc.get("ДниСтанции")
        if isinstance(дни_станции, list) and дни_станции:
            пропавшие = (await db.execute(text("""
                SELECT day FROM store_stock_move_days
                 WHERE company_id = :cid AND station_id = :st AND revision < :rev
                   AND NOT (day::text = ANY(:days))
            """), {**p, "rev": ред, "days": [str(д) for д in дни_станции]})).scalars().all()
            if пропавшие:
                await db.execute(text("""
                    DELETE FROM store_stock_moves
                     WHERE company_id = :cid AND station_id = :st AND day = ANY(:gone)
                """), {**p, "gone": list(пропавшие)})
                await db.execute(text("""
                    DELETE FROM store_stock_move_days
                     WHERE company_id = :cid AND station_id = :st AND day = ANY(:gone)
                """), {**p, "gone": list(пропавшие)})
                итог["purged_days"] = итог.get("purged_days", 0) + len(пропавшие)
    return итог
