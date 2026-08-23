"""Регулярное чтение боевой БП: реестр документов 1С не должен устаревать молча.

Срез снимался только по кнопке «Посмотреть в 1С». Пока человек её не нажал,
сверка отвечала по вчерашним данным и выглядела при этом уверенно — худший вид
неправды в учёте.

Такт устроен осторожно, потому что ресурс на той стороне единственный:
**одно COM-соединение на всю компанию**, и лицензий в БП столько же, сколько
людей за работой. Поэтому:

* читаем раз в сутки, в тихий час (по умолчанию 5 утра по Москве);
* берём последние `ОКНО_ДНЕЙ` дней, а не весь месяц: свежие документы меняются
  (их проводят), старые уже лежат;
* повтор в тот же день исключён отметкой в журнале, гонка воркеров — advisory-локом;
* если соединение занято людьми, молча ждём следующего такта: срез не срочен.

Сразу после чтения прогоняем сопоставление — иначе свежие документы попадут в
реестр немыми, со статусом «pending», и человек увидит их как неразобранные.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.database import async_session_factory

log = logging.getLogger("clearledger.onec.read.scheduler")

ТАКТ_СЕКУНД = 300            # час — грубая единица, проверяем раз в пять минут
ЧАС_ПО_УМОЛЧАНИЮ = 5         # до начала рабочего дня: соединение свободно
ОКНО_ДНЕЙ = 14               # свежие документы ещё проводят, старые уже лежат
TZ = ZoneInfo("Europe/Moscow")
ЛОК = 0x314353D0             # свой ключ: чужие регламенты не блокируем
ДЕЙСТВИЕ = "onec.read.snapshot"


async def _строка_соединения(db, company_id: uuid.UUID) -> str | None:
    """Реквизиты подключения к БП компании — те же, что у ручного чтения."""
    from app.models import Source, SourceCredentials
    from app.services.onec.crypto import decrypt_password

    источник = (await db.execute(select(Source).where(
        Source.company_id == company_id, Source.source_type == "onec_accounting",
    ))).scalar_one_or_none()
    if источник is None:
        return None
    cfg = источник.connection_config or {}
    строка = str(cfg.get("connection_string") or "")
    if not строка:
        return None
    if cfg.get("login"):
        строка += f'Usr="{cfg["login"]}";'
    креды = (await db.execute(select(SourceCredentials).where(
        SourceCredentials.source_id == источник.id))).scalar_one_or_none()
    пароль = ((креды.encrypted_values or {}) if креды else {}).get("password")
    if пароль:
        строка += f'Pwd="{decrypt_password(пароль)}";'
    return строка


async def _кому_пора(db) -> list[uuid.UUID]:
    """Компании с подключением к БП, которым сегодня ещё не читали."""
    # Не «ровно в пять», а «в пять и позже»: сервер, перезапущенный в 5:30,
    # иначе пропустил бы сутки целиком и никому об этом не сказал.
    if datetime.now(TZ).hour < ЧАС_ПО_УМОЛЧАНИЮ:
        return []
    строки = (await db.execute(text("""
        SELECT DISTINCT s.company_id
          FROM sources s
         WHERE s.source_type = 'onec_accounting'
           AND NOT EXISTS (
               SELECT 1 FROM audit_events a
                WHERE a.company_id = s.company_id AND a.action = :действие
                  AND a.timestamp >= date_trunc('day', now()))
    """), {"действие": ДЕЙСТВИЕ})).scalars().all()
    return list(строки)


async def прочитать_компанию(db, company_id: uuid.UUID) -> dict:
    """Снять срез за окно и сразу сопоставить его с нашими сменами."""
    from app.services.onec_accounting_read import снять_срез, сохранить_срез
    from app.services.onec_doc_matching import сопоставить_реестр

    строка = await _строка_соединения(db, company_id)
    if not строка:
        return {"Пропущено": "нет подключения к БП"}

    по = date.today()
    с = по - timedelta(days=ОКНО_ДНЕЙ)
    срез = await снять_срез(строка, date_from=с, date_to=по)
    if срез.ошибка:
        # Занятое соединение — не беда: срез не срочен, прочитаем следующим
        # тактом. Отметку в журнал не ставим, иначе день будет считаться закрытым.
        return {"Ошибка": срез.ошибка}

    сохранено = await сохранить_срез(
        db, company_id, срез, период=f"{с.isoformat()}…{по.isoformat()}")
    итог = await сопоставить_реестр(db, company_id)
    await db.execute(text("""
        INSERT INTO audit_events (id, company_id, user_id, user_name,
                                  action, details, timestamp)
        VALUES (gen_random_uuid(), :cid, 'system', 'Чтение БП',
                :действие, :детали, now())
    """), {
        "cid": str(company_id), "действие": ДЕЙСТВИЕ,
        "детали": (
            f"документов {len(срез.документы)}, заведено {сохранено.get('Заведено')}, "
            f"обновлено {сохранено.get('Обновлено')}, связано {итог.связано}"
        ),
    })
    await db.commit()
    return {"Прочитано": len(срез.документы), **сохранено, **итог.как_словарь()}


async def run_once() -> int:
    """Один проход по компаниям. Возвращает число прочитанных баз."""
    прочитано = 0
    async with async_session_factory() as db:
        if not (await db.execute(text(
                "SELECT pg_try_advisory_lock(:k)"), {"k": ЛОК})).scalar_one():
            return 0
        try:
            for cid in await _кому_пора(db):
                итог = await прочитать_компанию(db, cid)
                if "Ошибка" in итог:
                    log.warning("БП компании %s не прочитана: %s", cid, итог["Ошибка"])
                    continue
                log.info("БП компании %s прочитана: %s", cid, итог)
                прочитано += 1
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ЛОК})
            await db.commit()
    return прочитано


async def run_forever() -> None:
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:                      # noqa: BLE001
            log.warning("такт чтения БП не прошёл: %s", e)
        await asyncio.sleep(ТАКТ_СЕКУНД)
