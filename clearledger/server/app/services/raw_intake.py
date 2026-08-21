"""Сырое, как отдал источник: слой L1 для API-каналов.

Этап 2 плана (`ecosystem-deploy/docs/CONNECT-ROADMAP.md`). Таблица `raw_batches`
стояла с самого начала, но писалась ровно из файловой ветки топлива — то есть
схема «коннектор кладёт сырое, обработчик разбирает» была неосуществима
физически: класть было некуда.

Польза слоя не в архиве. Архив — это `DataEntry`, там лежит разобранное и
пригодное к работе. Сырое нужно ровно для одного случая: **разбор оказался
неверным**. Тогда прогон надо повторить, не ходя к источнику заново — потому что
источник за ночь уехал (документ перепровели, смену закрыли, ЦБ отдаёт уже не то,
что отдавал), потому что COM-сессия к 1С стоит минуты, и потому что «сходить ещё
раз» на боевой базе клиента — это не бесплатная операция.

Из этого следуют три решения, которые иначе выглядели бы произволом:

1. **Одна запись на прогон, а не на элемент.** Единица повтора — это то, что
   источник отдал за один поход: разбор (`ingest_packages`) принимает список
   целиком, и «половина пакета» ему бессмысленна. Поэлементная раскладка дала бы
   тысячи строк на прогон и потеряла бы границу «что привёз именно этот заход» —
   а восстанавливают всегда заход, а не отдельную смену.
2. **Сырое коммитится ДО разбора, своей транзакцией.** Если положить его в общую
   транзакцию прогона, то падение нормализации откатит вместе с собой и то, по
   чему её собирались повторять, — слой окажется пустым ровно в тот момент, ради
   которого он заведён.
3. **Запись сырого не имеет права уронить прогон.** Каналы ходят по ночам без
   человека; «не сохранилось сырое» — это потеря удобства, а «не загрузились
   данные» — потеря работы. Поэтому здесь всё под перехватом, и наружу уходит
   `None`, а не исключение.

Срок хранения — см. `keep_days()`: слой рабочий, не архивный, и растёт он
мегабайтами на прогон.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RawBatchRecord

log = logging.getLogger("clearledger.raw")

# Горизонт по умолчанию. Тридцать дней — это цикл закрытия месяца: неверный
# разбор всплывает на сверке за период, а сверка идёт по закрытому месяцу.
# Столько же держит журнал входящих в шине Поддержки (`INBOUND_KEEP_DAYS`), и
# разные горизонты у соседних слоёв пришлось бы каждый раз объяснять.
KEEP_DAYS_DEFAULT = 30

# Потолок одного пакета. Ограничение не от Postgres (там предел на jsonb-значение
# на три порядка выше), а от здравого смысла: пакет месяца по сети АЗС — это
# десятки мегабайт, которые надо сериализовать, передать, разжать при чтении и
# продержать в памяти. Восемь мегабайт — это ещё «посмотреть глазами и повторить
# разбор», а сто — уже дамп, которому место не в оперативной таблице.
MAX_BYTES_DEFAULT = 8 * 1024 * 1024


def keep_days() -> int:
    """Сколько дней держим сырое.

    Настраивается `RAW_BATCH_KEEP_DAYS` — у пилота и у стека с редкими прогонами
    разумные значения разные. Границы жёсткие с обеих сторон: 0 или отрицательное
    значение вычистило бы пакет в тот же миг, когда он лёг (опечатка в окружении
    не должна обнулять слой), а срок больше года превращает рабочий буфер в
    архив, которым он не является и под который не рассчитан размер.
    """
    raw = os.environ.get("RAW_BATCH_KEEP_DAYS")
    try:
        days = int(raw) if raw else KEEP_DAYS_DEFAULT
    except (TypeError, ValueError):
        log.warning("RAW_BATCH_KEEP_DAYS=%r не число — беру %s дн.", raw, KEEP_DAYS_DEFAULT)
        days = KEEP_DAYS_DEFAULT
    return max(1, min(days, 365))


def max_bytes() -> int:
    """Бюджет одного пакета в байтах (`RAW_BATCH_MAX_BYTES`)."""
    raw = os.environ.get("RAW_BATCH_MAX_BYTES")
    try:
        value = int(raw) if raw else MAX_BYTES_DEFAULT
    except (TypeError, ValueError):
        value = MAX_BYTES_DEFAULT
    return max(64 * 1024, value)


def _as_dt(value: Any) -> datetime | None:
    """`YYYY-MM-DD` (период прогона приходит строкой) → datetime, иначе как есть."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19].replace(" ", "T"))
    except ValueError:
        return None


def fit(items: list, budget: int | None = None) -> tuple[list, dict[str, Any]]:
    """Обрезать пакет по бюджету байт. Возвращает (что кладём, отметка в meta).

    Режем ПРЕФИКСОМ: как только очередной элемент не влезает — останавливаемся,
    а не пропускаем его и не берём следующие. Выборочный пропуск дал бы дырку в
    середине, неотличимую при чтении от потери данных источником; префикс же
    честно читается как «первые N из M, дальше не поместилось».

    Меряем настоящим `json.dumps` без `default`: чем нельзя измерить, тем нельзя
    и заполнить jsonb-колонку. Пусть такой пакет упадёт здесь, до вставки, — иначе
    он свалится внутри INSERT и отравит транзакцию прогона.
    """
    budget = max_bytes() if budget is None else budget
    kept: list = []
    used = 0
    for item in items:
        size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if used + size > budget:
            # Если не влез даже первый — кладём пустой пакет с отметкой: «источник
            # ответил громадиной» тоже надо где-то увидеть, а молчание об этом
            # неотличимо от «канал не ходил».
            break
        kept.append(item)
        used += size
    if len(kept) == len(items):
        return kept, {"bytes": used}
    return kept, {"bytes": used, "truncated": True,
                  "kept": len(kept), "total": len(items)}


async def save_raw_batch(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    doc_type: str,
    items: list,
    source_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    sync_log_id: uuid.UUID | None = None,
    since: Any = None,
    until: Any = None,
    meta: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Положить то, что вернул источник, до нормализации. Возвращает id или None.

    **Коммитит сама** — в этом весь смысл (см. решение 2 в шапке модуля), поэтому
    зовётся на границе транзакции: после fetch и до разбора, когда в сессии нет
    чужой незавершённой работы. **Не бросает никогда**: не легло сырое — канал
    обязан отработать, о неудаче узнаёт лог, а не пользователь.

    Привезти пакет может либо наш канал (`source_id`), либо приложение своим
    подключением (`connection_id`). Ровно одна ссылка, не обе: «оба сразу»
    означало бы, что мы не знаем, кто его привёз, и повторить разбор было бы
    некому.
    """
    if bool(source_id) == bool(connection_id):
        log.warning("Сырой пакет '%s' без однозначного владельца: "
                    "укажите либо источник канала, либо подключение", doc_type)
        return None
    items = list(items or [])
    try:
        kept, note = fit(items)
        record = RawBatchRecord(
            company_id=company_id, source_id=source_id,
            connection_id=connection_id,
            channel_id=channel_id, sync_log_id=sync_log_id,
            doc_type=doc_type,
            since=_as_dt(since), until=_as_dt(until),
            items=kept,
            # Счётчик — то, что отдал ИСТОЧНИК, а не то, что поместилось: иначе
            # усечённый пакет выглядел бы как маленький ответ источника.
            items_count=len(items),
            meta={**(meta or {}), "raw": note},
        )
        db.add(record)
        await db.commit()
        batch_id = record.id
    except Exception as exc:  # noqa: BLE001 — сырое не легло, прогон продолжается
        log.warning("Сырой пакет '%s' не сохранён: %s", doc_type, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
    if note.get("truncated"):
        log.warning("Сырой пакет '%s' усечён: %s из %s элементов (бюджет %s Б)",
                    doc_type, note.get("kept"), note.get("total"), max_bytes())
    await purge_expired(db)
    return batch_id


async def note_result(db: AsyncSession, batch_id: uuid.UUID | None,
                      result: dict[str, Any]) -> None:
    """Приписать пакету, чем кончился разбор. Идёт в транзакции вызывающего.

    Отметка нужна не для отчёта, а для поиска: пакет БЕЗ неё — это заход, чей
    разбор не дошёл до конца (упал, оборвался, откатился). Такие и надо
    переигрывать, и найти их иначе нечем.
    """
    if batch_id is None:
        return
    try:
        record = await db.get(RawBatchRecord, batch_id)
        if record is not None:
            record.meta = {**(record.meta or {}), "result": result}
    except Exception as exc:  # noqa: BLE001 — отметка не стоит падения прогона
        log.warning("Итог разбора не записан в пакет %s: %s", batch_id, exc)


async def latest_batch(db: AsyncSession, channel_id: uuid.UUID,
                       doc_type: str | None = None) -> RawBatchRecord | None:
    """Последнее сырое канала — точка входа для повтора разбора без ручного uuid."""
    q = select(RawBatchRecord).where(RawBatchRecord.channel_id == channel_id)
    if doc_type:
        q = q.where(RawBatchRecord.doc_type == doc_type)
    return (await db.execute(
        q.order_by(RawBatchRecord.fetched_at.desc()).limit(1))).scalar_one_or_none()


async def _replay_cb_shifts(db: AsyncSession, record: RawBatchRecord) -> dict[str, Any]:
    """Пакеты смен ЦБ → `ingest_packages`, ровно как в прогоне канала.

    Приём идемпотентен по натуральному ключу `{Номер}:{kind}:{UUID}`, поэтому
    повтор обновляет, а не задваивает — и повторять можно сколько угодно раз.
    """
    from app.services.cb_intake import ingest_packages

    return await ingest_packages(db, record.company_id, list(record.items or []),
                                 channel_id=record.channel_id)


# Что умеем разбирать повторно. Список короткий намеренно: пакет годится для
# повтора, только если нормализация выводится ИЗ НЕГО одного. У STS-веток сырое —
# это перечень смен, а сам отчёт смены тянется отдельным запросом; повтор по
# такому пакету всё равно пошёл бы к источнику, то есть повтором не был бы.
_REPLAY: dict[str, Any] = {"cb_shifts": _replay_cb_shifts}


async def replay_raw_batch(db: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
    """Повторить разбор по сохранённому сырому, не обращаясь к источнику.

    Коммитит сама: повтор — законченная операция, а не заготовка, и вызывают её
    из скрипта или разовой команды, где второго коммита ждать неоткуда.
    """
    record = await db.get(RawBatchRecord, batch_id)
    if record is None:
        return {"status": "error", "message": f"сырой пакет {batch_id} не найден"}
    handler = _REPLAY.get(record.doc_type)
    if handler is None:
        return {"status": "skipped",
                "message": f"разбор пакета '{record.doc_type}' по сырому не повторяется: "
                           "нормализация требует похода к источнику"}
    result = await handler(db, record)
    meta = dict(record.meta or {})
    note = dict(meta.get("raw") or {})
    previous = dict(meta.get("replay") or {})
    meta["replay"] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": int(previous.get("count") or 0) + 1,
        "result": result,
    }
    meta["result"] = result
    record.meta = meta
    await db.commit()
    out = {"status": "success", "doc_type": record.doc_type,
           "items": len(record.items or []), **result}
    if note.get("truncated"):
        # Разбор прошёл, но по неполному пакету: молчать об этом нельзя —
        # человек сравнит числа с прогоном и решит, что потерялись данные.
        out["status"] = "partial"
        out["message"] = (f"пакет усечён при сохранении: разобрано "
                          f"{note.get('kept')} из {note.get('total')}")
    return out


async def purge_expired(db: AsyncSession, days: int | None = None) -> int:
    """Убрать сырое старше горизонта. Возвращает число удалённых пакетов.

    Зовётся из записи пакета, а не по таймеру: канал — единственное, что этот
    слой наполняет, и чистка на его же прогоне идёт с той же частотой, что и рост
    (ночной автозапуск — раз в сутки). Отдельный планировщик пришлось бы заводить
    ради того же самого расписания.
    """
    days = keep_days() if days is None else days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        result = await db.execute(
            delete(RawBatchRecord).where(RawBatchRecord.fetched_at < cutoff))
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — чистка не стоит прогона
        log.warning("Чистка сырых пакетов не прошла: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0
    removed = int(result.rowcount or 0)
    if removed:
        log.info("Сырые пакеты старше %s дн. удалены: %s", days, removed)
    return removed
