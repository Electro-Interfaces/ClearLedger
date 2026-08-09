"""Витрина АСУиМ ЭЗС (ClickHouse `ecs`, представления `*_ru`) → Учёт.

Разбор идёт ПО ИМЕНАМ ЗАГОЛОВКОВ, а не по номерам колонок: заказчик обещал
расширять состав полей, и любая вставленная колонка сдвинула бы индексный разбор
(`docs/CHANNEL_ASUIM_EZS.md` §4). Один и тот же маппер обслуживает и файл,
выгруженный из Excel по ODBC, и — позже — прямой запрос к ClickHouse: имена
колонок там одинаковые.

Точка входа — `ingest_asuim_file(db, company, content, ...)`: опознаёт
представление по шапке и ведёт строки в свой приёмник. Файл не витринный →
None, и вызывающий идёт прежним путём (выгрузки админпанели продолжают работать).

Куда что ложится:
  stations_ru     → ServiceLocation (ev_charging), режим «дозаполнить»
  connectors_ru   → паспорт станции: типы разъёмов, мощность, состав (extra_metadata)
  payments_ru     → ChargePayment (эквайринг: холд, списание, возврат, чек)
  organizations_ru→ CorporateClient (реестр ЮЛ)
  users_ru        → EzsCustomer (клиент: ТОЛЬКО телефон, дата регистрации, ЮЛ)
  rfid_cards_ru   → EzsRfidCard (карта → владелец)
  tariffs_ru      → EzsTariff (номинал прайса по типу разъёма)
  brands_ru · chargepoint_groups_ru · cars_ru → EzsReference (малые справочники)

Персональные данные (решение МАГа 08.08.2026): у физлиц берём ТОЛЬКО номер
телефона — он и так ключ связи в модели. ФИО, отчество, e-mail, логин и аватар
не переносим, пока нет отдельного разрешения на обработку. Для юрлиц ограничения
нет: телефон корпоративного аккаунта — идентификатор организации.

Не забираем совсем только `admins_ru`: ФИО и почта сотрудников, потребителя в
учёте нет. Всё остальное из витрины в пространство доезжает — малые справочники
(бренды, группы станций, модели ЭМ) лежат в `ezs_references` и ждут связи:
`id_бренда` и `id_группы` в выгрузке станций пока пусты.
"""
from __future__ import annotations

import io
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChargePayment, CorporateClient, EzsCustomer, EzsReference, EzsRfidCard, EzsTariff,
    ServiceLocation,
)
from app.services.mapping import normalize_default

logger = logging.getLogger("clearledger.asuim")


def _conn_type(raw) -> str | None:
    """Тип разъёма к канону сессий («CCS2» → «CCS Combo 2»).

    Витрина, выгрузки админпанели и прайс называют один разъём по-разному.
    Разрез «факт против номинала» и разбор по типу собираются только на общем
    написании, поэтому канон применяется на входе, а не при чтении."""
    s = _s(raw, 40)
    return normalize_default("connector", s)[:40] if s else None

# Представление → набор заголовков, по которому оно опознаётся однозначно.
VIEW_SIGNATURES: dict[str, set[str]] = {
    "stations": {"id_станции", "серийный_номер", "количество_коннекторов"},
    "connectors": {"id_коннектора", "id_станции", "номер_коннектора"},
    "payments": {"id_платежа", "id_сессии", "сумма_холда_руб."},
    "sessions": {"id_сессии", "дата_начала", "энергия_квтч"},
    "organizations": {"id_организации", "кол_во_пользователей"},
    "tariffs": {"id_тарифа", "тип_тарифа", "цена_круглосуточно"},
    "users": {"id_пользователя", "дата_регистрации", "баланс_руб"},
    "rfid": {"id_карты", "uid", "статус_код"},
    "cars": {"id_модели", "ёмкость_акб_квтч"},
    "brands": {"id_бренда", "иконка"},
    "groups": {"id_группы", "кол_во_станций"},
    "admins": {"id_админа", "организация"},
}

# Представления, у которых приёмника в Учёте нет (см. шапку модуля).
VIEW_LABELS = {
    "stations": "станции", "connectors": "коннекторы", "payments": "платежи",
    "sessions": "сессии", "organizations": "организации", "tariffs": "тарифы",
    "users": "пользователи", "rfid": "RFID-карты", "cars": "модели авто",
    "brands": "бренды", "groups": "группы станций", "admins": "администраторы",
}

# Код протокола OCPP в витрине → версия (расшифровка снята с фактических данных:
# 380 станций «0» стоят в Учёте как 1.6, «2» — как 2.0.1).
OCPP_BY_CODE = {"0": "1.6", "1": "2.0", "2": "2.0.1"}

# Код типа разъёма → канон. В `tariffs_ru` название разъёма пусто у ВСЕХ 399
# строк, заполнен только код, — без расшифровки прайс не с чем сопоставлять.
# Соответствие снято с `connectors_ru`, где рядом лежат и код, и название.
CONNECTOR_BY_CODE = {
    0: "CCS Combo 2", 1: "CHAdeMO", 2: "Type 1", 3: "Type 2",
    4: "GB/T DC", 5: "GB/T AC", 6: "SHUKO",
}


def _s(v, maxlen: int | None = None) -> str | None:
    if v is None:
        return None
    out = str(v).strip()
    if not out or out.lower() in ("none", "nan", "null"):
        return None
    return out[:maxlen] if maxlen else out


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        s = str(v).replace(",", ".").strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _int(v) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def _pos(v) -> float | None:
    """Число, но ноль и пустое — это «не заполнено», а не «равно нулю».

    В выгрузке нули стоят там, где данных нет (мощность, рейтинг, процент успеха
    пусты во ВСЕХ 618 строках). Записать такой ноль в паспорт — значит стереть
    накопленное значение и показать станцию как нулевую в разрезах."""
    f = _num(v)
    return f if f else None


def _bool(v) -> bool | None:
    s = str(v).strip().lower() if v is not None else ""
    if not s:
        return None
    if s in ("true", "1", "да", "yes", "y"):
        return True
    if s in ("false", "0", "нет", "no", "n"):
        return False
    return None


def _phone(v) -> str | None:
    """Телефон к виду `+7XXXXXXXXXX`.

    В справочнике клиентов витрина отдаёт «+7(999) 999 99-95», а в сессиях и
    платежах — «+79999999995». Телефон здесь единственный ключ связи клиента,
    поэтому без приведения к одному виду справочник ни с чем не соединяется."""
    s = _s(v)
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    return ("+" + digits)[:20] if digits else None


def _dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S",
                "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def read_asuim_xlsx(content: bytes) -> tuple[str | None, list[dict[str, Any]]]:
    """Файл витрины → (имя представления, строки словарями по русским заголовкам).

    Лист ищется перебором: ODBC-выгрузка Excel кладёт данные на второй лист, а
    первый оставляет пустым. Представление не опознано → (None, [])."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            head = next(it, None)
            if not head:
                continue
            hdr = [str(h).strip().lower() if h is not None else "" for h in head]
            hset = set(hdr)
            for view, need in VIEW_SIGNATURES.items():
                if need <= hset:
                    rows = [dict(zip(hdr, r)) for r in it if r and any(c is not None for c in r)]
                    return view, rows
        return None, []
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Станции
# ---------------------------------------------------------------------------
def map_stations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`stations_ru` → строки паспорта в ключах `ingest_stations` (L1).

    Флаг `partial` включает режим «дозаполнить»: витрина отдаёт часть паспорта
    пустой (мощность, даты, рейтинг, id бренда и группы — пусты во всех строках),
    и переписывать ими накопленные значения нельзя.

    Владелец из витрины — ОПЕРАТОР сети (РусГидро / СНК), а в Учёте `owner` — это
    собственник по договору («ООО Доступная энергия»). Поэтому имя оператора едет
    в паспорт-хвост, а `owner` заполняется только там, где он пуст."""
    out: list[dict[str, Any]] = []
    for r in rows:
        ext = _s(r.get("id_станции"), 64)
        if not ext:
            continue
        num = _s(r.get("номер"), 60)
        out.append({
            "partial": True,
            "ext_id": ext,
            "name": _s(r.get("название"), 255),
            "number": num,
            "serial_number": _s(r.get("серийный_номер"), 120),
            # id владельца витрины — свой справочник, в owner_id Учёта живёт чужой
            # (HubEx). Не смешиваем: витринный уходит в паспорт-хвост.
            "owner": _s(r.get("название_владельца"), 200),
            "region": _s(r.get("регион"), 200),
            "city": _s(r.get("город"), 120),
            "street": _s(r.get("улица"), 200),
            "house": _s(r.get("номер_дома"), 40),
            "address": _s(r.get("адрес"), 500),
            "latitude": _num(r.get("широта")),
            "longitude": _num(r.get("долгота")),
            "model": _s(r.get("модель"), 120),
            "brand": _s(r.get("бренд"), 120),
            "connectors_count": _int(r.get("количество_коннекторов")),
            "power_kwt": _pos(r.get("мощность_квт")),
            # Код «0» (= OCPP 1.6) стоит у 380 станций из 385 и он falsy —
            # приводим через _s, а не через `or ""`, иначе протокол теряется.
            "ocpp_protocol": OCPP_BY_CODE.get(_s(r.get("протокол_ocpp")) or ""),
            "firmware": _s(r.get("прошивка"), 80),
            "status_dev": _s(r.get("статус"), 60),
            # «этап» в выгрузке равен «Active» у ВСЕХ строк, включая 59 выведенных
            # из эксплуатации, — жизненный цикл им не описывается. Стадию берём из
            # статуса устройства (см. partial-ветку `ingest_stations`), а не отсюда.
            # «опубликовано», «тип_доступы», «тип_локации» приходят нулями во всех
            # строках — это незаполненные поля витрины, а не значения.
            "is_hidden": _bool(r.get("станция_скрыта")),
            "rating": _pos(r.get("средняя_оценка")),
            "success_pct": _pos(r.get("процент_успеха")),
            # Тест определяется форматом номера («Тест»), как и в выгрузках CPO.
            "is_test": str(num or "").lower().startswith(("тест", "test")),
            "extra": {k: v for k, v in {
                "asuimStationId": ext,
                "asuimOwnerId": _int(r.get("id_владельца")),
                "asuimOwnerName": _s(r.get("название_владельца"), 200),
                "asuimGroupId": _int(r.get("id_группы")),
                "asuimTransferring": _bool(r.get("в_процессе_передачи")),
                "cadastralNumber": _s(r.get("кадастровый_номер"), 60),
                "meterNumber": _s(r.get("номер_счетчика"), 60),
                "ocppUrl": _s(r.get("ocpp_url"), 300),
                "mobileLink": _s(r.get("ссылка_мп"), 500),
                "installedOn": _s(r.get("дата_установки"), 30),
                "startedOn": _s(r.get("дата_начала_работы"), 30),
                "lastActivityAt": _s(r.get("последняя_активность"), 30),
                "timezoneOffset": _int(r.get("смещение_часового_пояса")),
                "source": "asuim_vitrina",
            }.items() if v is not None},
        })
    return out


async def _station_index(db: AsyncSession, company_id) -> dict[str, ServiceLocation]:
    """Ключ (id станции витрины / серийный / код / номер) → объект-станция.

    Ключи разъехались исторически: часть карточек заведена по id станции, часть по
    серийному, часть по номеру. Индекс собирает все три, приоритет — сверху вниз."""
    locs = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.type == "ev_charging"))).scalars().all()
    idx: dict[str, ServiceLocation] = {}
    for key_of in (
        lambda l: (l.extra_metadata or {}).get("asuimStationId"),
        lambda l: l.code,
        lambda l: l.serial_number,
        lambda l: (l.extra_metadata or {}).get("stationId") or (l.extra_metadata or {}).get("ext_id"),
        lambda l: l.station_number,
    ):
        for loc in locs:
            if loc.is_test:
                continue
            k = key_of(loc)
            if k is not None and str(k).strip():
                idx.setdefault(str(k).strip(), loc)
    return idx


# ---------------------------------------------------------------------------
# Коннекторы
# ---------------------------------------------------------------------------
async def ingest_connectors(db: AsyncSession, company_id, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`connectors_ru` → паспорт станции: типы разъёмов, мощность, состав.

    Отдельной сущности не заводим (`docs/CHANNEL_ASUIM_EZS.md` §7): разрез по типу
    разъёма уже есть в сессиях, а состав нужен как паспорт. Мощность станции —
    МАКСИМУМ по её разъёмам: так же считает Учёт сегодня (345 станций из 351
    совпали с максимумом, ни одна — с суммой).

    Ключ разъёма — (id станции, номер коннектора): `id_коннектора` в витрине
    сквозным НЕ является (на 1596 строк всего 8 значений — это порядковый номер)."""
    idx = await _station_index(db, company_id)
    by_station: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sid = _s(r.get("id_станции"), 64)
        if sid:
            by_station[sid].append(r)

    updated = missing = 0
    unmatched: list[str] = []
    for sid, items in by_station.items():
        loc = idx.get(sid)
        if loc is None:
            missing += 1
            if len(unmatched) < 20:
                unmatched.append(sid)
            continue
        conns = []
        types: list[str] = []
        powers: list[float] = []
        for r in sorted(items, key=lambda x: _int(x.get("номер_коннектора")) or 0):
            t = _conn_type(r.get("тип"))
            p = _pos(r.get("мощность_квт"))
            if t and t not in types:
                types.append(t)
            if p:
                powers.append(p)
            conns.append({k: v for k, v in {
                "no": _int(r.get("номер_коннектора")),
                "evseId": _int(r.get("id_evse")),
                "type": t,
                "powerKw": p,
                "currentA": _pos(r.get("ток_а")),
                "status": _s(r.get("статус"), 40),
                # «формат» (0/1) заполнен у 1305 строк, но расшифровки заказчик не
                # дал: на кабель/розетку раскладывается не полностью (SHUKO — 0,
                # CCS2 — 1, а GBT/AC встречается и так, и так). Храним как код,
                # переименуем, когда придёт ответ.
                "formatCode": _int(r.get("формат")),
                "priceKwh": _pos(r.get("цена_за_квтч")),
                "priceHour": _pos(r.get("цена_за_час")),
            }.items() if v is not None})
        loc.connectors_count = len(items)
        if types:
            loc.connector_types = ", ".join(types)[:200]
        if powers:
            loc.power_kwt = max(powers)
        loc.extra_metadata = {**(loc.extra_metadata or {}), "connectors": conns,
                              "connectorsSource": "asuim_vitrina"}
        updated += 1
    await db.flush()
    msg = f"разъёмы: обновлено станций {updated}, разъёмов {len(rows)}"
    if missing:
        msg += f", станций не найдено {missing}"
    logger.info("asuim connectors: %s; не найдены: %s", msg, unmatched)
    return {"status": "success", "kind": "asuim_connectors", "updated": updated,
            "created": 0, "skipped": missing, "errors": 0,
            "unmatched": unmatched, "message": msg}


# ---------------------------------------------------------------------------
# Платежи
# ---------------------------------------------------------------------------
def map_payments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`payments_ru` → строки платежей (L1)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        ext = _s(r.get("id_платежа"), 64)
        if not ext:
            continue
        out.append({
            "payment_ext_id": ext,
            "bank_txn_id": _s(r.get("id_транзакции_банка"), 64),
            "session_ext_id": _s(r.get("id_сессии"), 64),
            "paid_at": _dt(r.get("дата")),
            "amount": _num(r.get("сумма_руб.")) or 0,
            "hold_amount": _num(r.get("сумма_холда_руб.")) or 0,
            "refund_amount": _num(r.get("сумма_возврата_руб")) or 0,
            "by_card": _bool(r.get("оплата_картой")),
            "op_type_id": _int(r.get("id_типа_операции")),
            "op_type": _s(r.get("тип_операции"), 60),
            "status_code": _int(r.get("статус")),
            "receipt_url": _s(r.get("url_фискального_чека"), 500),
            "user_ext_id": _s(r.get("id_пользователя"), 40),
            "user_phone": _s(r.get("телефон_пользователя"), 40),
        })
    return out


async def ingest_payments(
    db: AsyncSession, company_id, rows: list[dict[str, Any]], channel_id=None,
    mode: str = "append", log_id=None,
) -> dict[str, Any]:
    """Платежи эквайринга → `charge_payments`. Дедуп по (компания, id платежа).

    Повторные и пересекающиеся окна выгрузки безопасны: строка с известным id
    платежа обновляется, а не задваивается — заказчик выгружает окнами по датам,
    и стык недель всегда перекрывается."""
    existing: dict[str, ChargePayment] = {
        p.payment_ext_id: p for p in (await db.execute(select(ChargePayment).where(
            ChargePayment.company_id == company_id))).scalars().all()
    }
    created = updated = errors = 0
    seen: set[str] = set()
    fields = ("bank_txn_id", "session_ext_id", "paid_at", "amount", "hold_amount",
              "refund_amount", "by_card", "op_type_id", "op_type", "status_code",
              "receipt_url", "user_ext_id", "user_phone")
    for idx, row in enumerate(rows):
        try:
            ext = row.get("payment_ext_id")
            if not ext or ext in seen:
                continue
            seen.add(ext)
            cur = existing.get(ext)
            if cur is None:
                db.add(ChargePayment(company_id=company_id, channel_id=channel_id,
                                     payment_ext_id=ext,
                                     **{k: row.get(k) for k in fields}))
                created += 1
            elif mode == "append" and cur.status_code == row.get("status_code"):
                continue   # ничего не поменялось — не трогаем строку
            else:
                for k in fields:
                    setattr(cur, k, row.get(k))
                cur.channel_id = channel_id or cur.channel_id
                updated += 1
            if (idx + 1) % 2000 == 0:
                await db.flush()
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.warning("asuim payments: строка %s (id %s) не загружена: %s: %s",
                           idx + 1, row.get("payment_ext_id"), type(exc).__name__, exc)
    await db.flush()
    return {"status": "success", "kind": "asuim_payments", "created": created,
            "updated": updated, "skipped": len(rows) - created - updated, "errors": errors,
            "message": f"платежи: добавлено {created}, обновлено {updated}"}


# ---------------------------------------------------------------------------
# Организации
# ---------------------------------------------------------------------------
async def ingest_organizations(db: AsyncSession, company_id, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`organizations_ru` → реестр ЮЛ (`corporate_clients`).

    Ключ джойна корп-клиента с сессиями — телефон, а витрина его не отдаёт.
    Поэтому существующие карточки резолвим по имени и проставляем им `ext_id`
    (id организации в АСУиМ) — после этого сессии можно будет цеплять по ключу,
    когда в выгрузке сессий появится `id_организации`. Новые организации заводим
    без телефона: карточка видна в реестре, джойн включится, как только телефон
    заполнят руками."""
    cur = (await db.execute(select(CorporateClient).where(
        CorporateClient.company_id == company_id))).scalars().all()
    by_ext = {c.ext_id: c for c in cur if c.ext_id}
    by_name = {(c.name or "").strip().lower(): c for c in cur}

    created = updated = skipped = 0
    for r in rows:
        ext = _s(r.get("id_организации"), 40)
        name = _s(r.get("название"), 300)
        if not (ext and name):
            continue
        if "тестов" in name.lower():
            skipped += 1
            continue
        obj = by_ext.get(ext) or by_name.get(name.lower())
        users = _int(r.get("кол_во_пользователей"))
        status = "active" if _bool(r.get("активна")) else "inactive"
        start = _s(r.get("дата_начала_договора"), 20)
        if obj is None:
            db.add(CorporateClient(company_id=company_id, name=name, phone="",
                                   ext_id=ext, mode="retail", status=status,
                                   users=users, contract_start=start))
            created += 1
        else:
            obj.ext_id = ext
            obj.status = status
            if users is not None:
                obj.users = users
            if start and not obj.contract_start:
                obj.contract_start = start
            updated += 1
    await db.flush()
    return {"status": "success", "kind": "asuim_organizations", "created": created,
            "updated": updated, "skipped": skipped, "errors": 0,
            "message": f"организации: добавлено {created}, обновлено {updated}"
                       + (f", тестовых пропущено {skipped}" if skipped else "")}


# ---------------------------------------------------------------------------
# Клиенты и карты
# ---------------------------------------------------------------------------
async def ingest_customers(db: AsyncSession, company_id, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`users_ru` → `ezs_customers`. Из ПДн берём ТОЛЬКО номер телефона.

    ФИО, отчество, e-mail, логин и аватар в Учёт не переносятся (решение МАГа
    08.08.2026, до получения отдельного разрешения на обработку). Телефон —
    ключ связи, он и так лежит в сессиях и платежах."""
    cur = {c.customer_ext_id: c for c in (await db.execute(select(EzsCustomer).where(
        EzsCustomer.company_id == company_id))).scalars().all()}
    created = updated = 0
    for r in rows:
        ext = _s(r.get("id_пользователя"), 40)
        if not ext:
            continue
        org = _s(r.get("id_организации"), 40)
        vals = {
            "phone": _phone(r.get("телефон")),
            "organization_ext_id": None if org in (None, "0") else org,
            "registered_at": _dt(r.get("дата_регистрации")),
            "is_active": _bool(r.get("активен")),
            "balance": _num(r.get("баланс_руб")),
        }
        obj = cur.get(ext)
        if obj is None:
            db.add(EzsCustomer(company_id=company_id, customer_ext_id=ext, **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(obj, k, v)
            updated += 1
    await db.flush()

    # Замыкаем реестр ЮЛ. Телефон корпоративного аккаунта — ключ джойна с
    # сессиями (`charge_sessions.user_id`), а `organizations_ru` его не отдаёт:
    # он известен только через клиента этой организации. Заодно считаем число
    # пользователей — в выгрузке организаций эта колонка пуста во всех строках.
    linked = 0
    orgs = (await db.execute(select(CorporateClient).where(
        CorporateClient.company_id == company_id,
        CorporateClient.ext_id.is_not(None)))).scalars().all()
    for org in orgs:
        mates = [c for c in (await db.execute(select(EzsCustomer).where(
            EzsCustomer.company_id == company_id,
            EzsCustomer.organization_ext_id == org.ext_id))).scalars().all()]
        if not mates:
            continue
        org.users = len(mates)
        if not org.phone:
            phone = next((m.phone for m in mates if m.phone), None)
            if phone:
                org.phone = phone
                linked += 1
    await db.flush()
    msg = f"клиенты: добавлено {created}, обновлено {updated} (только телефон, без ФИО и почты)"
    if linked:
        msg += f"; телефон проставлен {linked} организациям"
    return {"status": "success", "kind": "asuim_customers", "created": created,
            "updated": updated, "skipped": 0, "errors": 0, "message": msg}


async def ingest_rfid_cards(db: AsyncSession, company_id, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`rfid_cards_ru` → `ezs_rfid_cards`. UID приводим к верхнему регистру:
    в сессиях он лежит строчными, в витрине — прописными."""
    cur = {c.card_ext_id: c for c in (await db.execute(select(EzsRfidCard).where(
        EzsRfidCard.company_id == company_id))).scalars().all()}
    created = updated = 0
    for r in rows:
        ext = _s(r.get("id_карты"), 40)
        if not ext:
            continue
        uid = _s(r.get("uid"), 60)
        vals = {
            "uid": uid.upper() if uid else None,
            "number": _s(r.get("номер"), 60),
            "status": _s(r.get("статус"), 40),
            "status_code": _int(r.get("статус_код")),
            "customer_ext_id": _s(r.get("id_пользователя"), 40),
            "phone": _phone(r.get("телефон_пользователя")),
        }
        obj = cur.get(ext)
        if obj is None:
            db.add(EzsRfidCard(company_id=company_id, card_ext_id=ext, **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(obj, k, v)
            updated += 1
    await db.flush()
    return {"status": "success", "kind": "asuim_rfid", "created": created,
            "updated": updated, "skipped": 0, "errors": 0,
            "message": f"RFID-карты: добавлено {created}, обновлено {updated}"}


async def ingest_references(db: AsyncSession, company_id, view: str,
                            rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`brands_ru` · `chargepoint_groups_ru` · `cars_ru` → `ezs_references`.

    Справочники маленькие и приходят целиком, поэтому вид перезагружается
    полностью. Связи с объектами сети у них сейчас нет (`id_бренда`/`id_группы`
    в станциях пусты), но данные заказчика мы не выбрасываем: справочник стоит
    заведённым, и связь сядет, как только придёт."""
    from sqlalchemy import delete
    kind = {"brands": "brand", "groups": "group", "cars": "car"}[view]
    await db.execute(delete(EzsReference).where(
        EzsReference.company_id == company_id, EzsReference.kind == kind))
    seen: set[str] = set()
    created = 0
    for r in rows:
        if kind == "brand":
            ext, name = _s(r.get("id_бренда"), 40), _s(r.get("название"), 300)
            payload = {k: v for k, v in {"visible": _bool(r.get("видимый")),
                                         "icon": _s(r.get("иконка"), 300)}.items() if v is not None}
        elif kind == "group":
            ext, name = _s(r.get("id_группы"), 40), _s(r.get("название"), 300)
            payload = {"stationsCount": _int(r.get("кол_во_станций"))}
        else:
            ext = _s(r.get("id_модели"), 40)
            brand, model = _s(r.get("бренд"), 120), _s(r.get("модель"), 200)
            name = " ".join(x for x in (brand, model) if x)
            payload = {k: v for k, v in {"brand": brand, "model": model,
                                         "batteryKwh": _pos(r.get("ёмкость_акб_квтч")),
                                         }.items() if v is not None}
        if not ext or ext in seen:
            continue
        seen.add(ext)
        db.add(EzsReference(company_id=company_id, kind=kind, ext_id=ext,
                            name=name, payload=payload or None))
        created += 1
    await db.flush()
    label = {"brand": "бренды станций", "group": "группы станций", "car": "модели электромобилей"}[kind]
    return {"status": "success", "kind": f"asuim_{kind}", "created": created,
            "updated": 0, "skipped": 0, "errors": 0,
            "message": f"{label}: загружено {created}"}


# ---------------------------------------------------------------------------
# Тарифы
# ---------------------------------------------------------------------------
async def ingest_tariffs(db: AsyncSession, company_id, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`tariffs_ru` → справочник номиналов (`ezs_tariffs`).

    В витрине тариф разложен построчно по типу разъёма, поэтому ключ строки —
    (id тарифа, id типа разъёма). Полная перезагрузка: справочник маленький и
    приходит целиком, инкремент смысла не имеет."""
    from sqlalchemy import delete
    await db.execute(delete(EzsTariff).where(EzsTariff.company_id == company_id))
    seen: set[tuple[str, int | None]] = set()
    created = 0
    for r in rows:
        ext = _s(r.get("id_тарифа"), 40)
        if not ext:
            continue
        conn_id = _int(r.get("тип_коннектора_id"))
        if (ext, conn_id) in seen:
            continue
        seen.add((ext, conn_id))
        db.add(EzsTariff(
            company_id=company_id,
            tariff_ext_id=ext,
            name=_s(r.get("название"), 200),
            owner_name=_s(r.get("владелец"), 200),
            tariff_type=_s(r.get("тип_тарифа"), 20),
            connector_type_id=conn_id,
            connector_type=_conn_type(r.get("тип_коннектора"))
                           or CONNECTOR_BY_CODE.get(conn_id),
            price_all_day=_num(r.get("цена_круглосуточно")),
            price_day=_num(r.get("цена_день")),
            price_night=_num(r.get("цена_ночь")),
            price_halfpeak=_num(r.get("цена_полупик")),
            price_peak=_num(r.get("цена_пик")),
            reservation_cost=_num(r.get("стоимость_бронирования")),
            idle_cost=_num(r.get("стоимость_простоя")),
            valid_from=_s(r.get("дата_начала"), 20),
            valid_to=_s(r.get("дата_окончания"), 20),
            stations=_s(r.get("привязанные_станции"), 2000),
            organizations=_s(r.get("организации"), 2000),
        ))
        created += 1
    await db.flush()
    return {"status": "success", "kind": "asuim_tariffs", "created": created,
            "updated": 0, "skipped": 0, "errors": 0,
            "message": f"тарифы: загружено {created} строк ({len({s[0] for s in seen})} тарифов)"}


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
async def _invalidate(db: AsyncSession, company_id, res: dict[str, Any]) -> dict[str, Any]:
    """Сброс кеша разрезов «Продаж» после загрузки, меняющей паспорт сети.

    Мощность, статус, регион и владелец станции — измерения дашбордов, поэтому
    обновлённый справочник обязан гасить кеш: иначе экраны держат прежние цифры
    до следующей загрузки сессий (та бампает версию сама)."""
    if res.get("status") == "success":
        from app.services.analytics_cache import bump_version
        await bump_version(db, company_id)
    return res


async def ingest_asuim_file(
    db: AsyncSession, company_id, content: bytes, channel_id=None,
    mode: str = "append", log_id=None,
) -> dict[str, Any] | None:
    """Файл витрины → свой приёмник. None — файл не витринный (идти прежним путём)."""
    view, rows = read_asuim_xlsx(content)
    if view is None:
        return None
    if not rows:
        return {"status": "error", "kind": f"asuim_{view}",
                "message": f"витрина «{VIEW_LABELS.get(view, view)}»: в файле нет строк"}

    if view == "stations":
        from app.services.stations_normalize import ingest_stations
        # Справочник = источник истины по составу парка, поэтому режим replace.
        # «Дозаполнить, а не переписать» обеспечивает флаг partial у строк.
        res = await ingest_stations(db, company_id, map_stations(rows),
                                    channel_id=channel_id, mode="replace", log_id=log_id)
        return await _invalidate(db, company_id, res)
    if view == "connectors":
        return await _invalidate(db, company_id, await ingest_connectors(db, company_id, rows))
    if view == "payments":
        return await ingest_payments(db, company_id, map_payments(rows),
                                     channel_id=channel_id, mode=mode, log_id=log_id)
    if view == "organizations":
        return await _invalidate(db, company_id, await ingest_organizations(db, company_id, rows))
    if view == "users":
        return await ingest_customers(db, company_id, rows)
    if view == "rfid":
        return await ingest_rfid_cards(db, company_id, rows)
    if view == "tariffs":
        return await ingest_tariffs(db, company_id, rows)
    if view in ("brands", "groups", "cars"):
        return await ingest_references(db, company_id, view, rows)
    if view == "sessions":
        from app.services.charge_sessions_normalize import ingest_charge_sessions
        return await ingest_charge_sessions(db, company_id, map_sessions(rows),
                                            channel_id=channel_id, mode=mode, log_id=log_id)
    return {"status": "skipped", "kind": f"asuim_{view}",
            "message": f"витрина «{VIEW_LABELS.get(view, view)}»: приёмника в Учёте нет, "
                       f"файл не загружен ({len(rows)} строк)"}


def map_sessions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`charge_sessions_ru` → строки сессий в ключах `ingest_charge_sessions`.

    Представление в пробную выгрузку не попало, поэтому маппер написан по
    приложению 1 постановки и на живых данных НЕ проверен: первую же выгрузку
    сессий гонять с проверкой итогов по периоду."""
    out: list[dict[str, Any]] = []
    for r in rows:
        sid = _s(r.get("id_сессии"), 64)
        if not sid:
            continue
        started, finished = _dt(r.get("дата_начала")), _dt(r.get("дата_окончания"))
        out.append({
            "session_ext_id": sid,
            "station_code": _s(r.get("номер_станции") or r.get("id_станции"), 40),
            "station_name": _s(r.get("название_станции"), 160),
            "region": _s(r.get("регион"), 120),
            "address": _s(r.get("адрес"), 300),
            "connector_no": _s(r.get("номер_коннектора"), 20),
            "connector_type": _s(r.get("тип_коннектора"), 40),
            "started_at": started,
            "finished_at": finished,
            "duration_min": round((finished - started).total_seconds() / 60, 2)
                            if started and finished else 0,
            "result": _s(r.get("результат"), 40),
            "charge_type": _s(r.get("тип_зарядки"), 40),
            "user_type": _s(r.get("тип_пользователя"), 20),
            "user_id": _s(r.get("телефон_пользователя") or r.get("id_пользователя"), 160),
            "rfid": _s(r.get("rfid_карта") or r.get("номер_карты"), 120),
            "energy_kwh": _num(r.get("энергия_квтч")) or 0,
            "amount": _num(r.get("сумма_руб.") or r.get("итоговая_сумма_руб")) or 0,
            "tariff": _num(r.get("цена_тарифа") or r.get("тариф_руб_квтч")) or 0,
            "paid_at": _dt(r.get("дата_оплаты")),
            "payment_id": _s(r.get("id_платежа"), 64),
        })
    return out
