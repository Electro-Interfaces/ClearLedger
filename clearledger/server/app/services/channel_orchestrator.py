"""
Оркестратор канала: ЕДИНАЯ точка прогона любого канала (fetch→normalize→save).

run_channel(db, channel) диспетчеризует по типу источника потока:
  • onec_operational → ЦБ ЭЛСИ.АЗК: fetch_cb_shifts → cb_normalize → DataEntry (сопутка/общепит).
  • sts             → STS: ingest_fuel_shifts → FuelShift/FuelReceipt (топливо+ТТН).

Так /channels/{id}/run работает для ВСЕХ каналов единообразно (топливо больше
не идёт мимо оркестратора через отдельный /fuel/normalize — тот стал тонкой
обёрткой над общим ingest_fuel_shifts).

⚠ Транспорт ЦБ: OneCComClient (subprocess com_worker, 32-бит COM) — Windows
(COM-Agent/dev). В проде на Linux — через COM-Agent (http_agent).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelStream, ChannelSyncLog, Source, SourceCredentials, SourceFile
from app.services.cb_intake import ingest_packages
from app.services.onec.com_client import OneCComClient
from app.services.onec.crypto import decrypt_password
from app.services.sts_client import sts_get_points


_STREAM_ROLE_RANK = {"anchor": 0, "control": 1, "reference": 2, "external": 3}


async def _channel_source(db: AsyncSession, channel_id, source_type: str | None = None) -> Source | None:
    """Source канала среди потоков (опц. фильтр по source_type).

    ДЕТЕРМИНИРОВАННО: учитываем только включённые потоки с подключённым источником,
    приоритет по роли (anchor → control → reference → external), затем стабильный
    порядок (имя, id). Иначе (без ORDER BY) многопоточный канал недетерминированно
    выбирал бы источник — и мог уйти в не ту ветку оркестратора или в skipped."""
    streams = (
        await db.execute(select(ChannelStream).where(ChannelStream.channel_id == channel_id))
    ).scalars().all()
    streams = sorted(
        (s for s in streams if s.enabled and s.source_id is not None),
        key=lambda s: (_STREAM_ROLE_RANK.get(s.role, 9), s.name or "", str(s.id)),
    )
    for s in streams:
        src = await db.get(Source, s.source_id)
        if src is not None and (source_type is None or src.source_type == source_type):
            return src
    return None


async def _decrypt_pwd(db: AsyncSession, source_id) -> str:
    cr = (
        await db.execute(select(SourceCredentials).where(SourceCredentials.source_id == source_id))
    ).scalar_one_or_none()
    enc = (cr.encrypted_values or {}) if cr else {}
    return decrypt_password(enc["password"]) if enc.get("password") else ""


def _conn_string(src: Source, password: str) -> str:
    """COM-строка соединения из connection_config + пароль."""
    cfg = src.connection_config or {}
    base = str(cfg.get("connection_string", "") or "")
    login = str(cfg.get("login", "") or "")
    extra = ""
    if login:
        extra += f'Usr="{login}";'
    if password:
        extra += f'Pwd="{password}";'
    if extra and base and not base.endswith(";"):
        base += ";"
    return base + extra


def _period(
    channel: Channel,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, str]:
    """Период прогона. Приоритет: явный параметр запуска (UI «Период загрузки»)
    → config.dateFrom/dateTo канала → фолбэк period_days от сегодня."""
    if date_from and date_to:
        return str(date_from)[:10], str(date_to)[:10]
    cfg = channel.config or {}
    df = cfg.get("dateFrom") or cfg.get("date_from")
    dt = cfg.get("dateTo") or cfg.get("date_to")
    if df and dt:
        return str(df)[:10], str(dt)[:10]
    days = int(channel.period_days or 30)
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    return since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Ветка ЦБ (сопутка/общепит)
# ---------------------------------------------------------------------------
async def _run_cb(db: AsyncSession, channel: Channel, src: Source,
                  date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    conn = _conn_string(src, await _decrypt_pwd(db, src.id))
    cfg = src.connection_config or {}
    station = str((channel.config or {}).get("station") or cfg.get("default_station") or "208")
    pf, pt = _period(channel, date_from, date_to)
    # F7: лимит поднят с 200 до 3000 (месяц ≈ 30–60 смен на АЗС; обрезка теперь
    # практически невозможна, а при ней COM отбрасывает СТАРЕЙШИЕ, не новейшие —
    # см. op_fetch_cb_shifts УПОРЯДОЧИТЬ ПО Дата УБЫВ). truncated сигналим в UI.
    _LIMIT = 3000
    async with OneCComClient(conn) as client:
        packages = await client.fetch_cb_shifts(pf, pt, station=station, limit=_LIMIT)
    result = await ingest_packages(db, channel.company_id, packages, channel_id=channel.id)
    truncated = len(packages) >= _LIMIT
    msg = result.get("message") or ""
    if truncated:
        msg = (msg + "; ⚠ достигнут лимит выборки смен — сузьте период").strip("; ")
    return {"status": "success", "kind": "cb", "period": [pf, pt], "station": station,
            "truncated": truncated, **{k: v for k, v in result.items() if k != "message"},
            "message": msg}


# ---------------------------------------------------------------------------
# Ветка STS (топливо). Раздельно, как в расширении БП: продажи (ОбработатьСмену)
# и приём ТТН (ОбработатьТТН) — это РАЗНЫЕ каналы с разными разрезами.
#   • fuel_shift    → shift_report → FuelShift (продажи), без ТТН.
#   • fuel_delivery → receipts     → FuelReceipt + L1 ТТН (приём).
# ---------------------------------------------------------------------------
async def _fuel_context(db: AsyncSession, channel: Channel, src: Source,
                        date_from: str | None = None, date_to: str | None = None,
                        all_period: bool = False):
    """Общий контекст STS-прогона: креды, период, станции.

    Станции — ВСЯ сеть системы(систем) из STS `/v1/points` (канал работает со
    всеми станциями, а не с зашитым подмножеством). config.stations больше НЕ
    ограничивает прогон — точечный отбор делается параметром station_codes
    (диалог «Обновить»). Фолбэк на config.stations — только если /v1/points
    недоступен. all_period=True → без ограничения по датам (вся история)."""
    cfg = src.connection_config or {}
    pwd = await _decrypt_pwd(db, src.id)
    login = str(cfg.get("login") or "")
    base_url = str(cfg.get("base_url") or "https://pos.autooplata.ru/tms")
    sysids = str(cfg.get("default_system_ids") or "65")
    systems = [int(s.strip()) for s in sysids.split(",") if s.strip()] or [65]
    default_system = systems[0]
    pf, pt = (None, None) if all_period else _period(channel, date_from, date_to)

    # ВСЕ станции систем источника из STS /v1/points (авто-discovery сети).
    stations: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for sysid in systems:
        try:
            points = await sts_get_points(base_url, login, pwd, sysid)
        except Exception:  # noqa: BLE001 — STS недоступен → фолбэк ниже
            points = []
        for p in points:
            try:
                code = int(p.get("number") or p.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if code and (sysid, code) not in seen:
                seen.add((sysid, code))
                stations.append({"code": code, "systemId": sysid, "name": p.get("name")})

    # Фолбэк: /v1/points не дал станций → берём из конфигурации канала.
    if not stations:
        ch_cfg = channel.config or {}
        stations = list(ch_cfg.get("stations") or [])
        if not stations:
            single = ch_cfg.get("station") or cfg.get("default_station")
            if single:
                stations = [{"code": single, "systemId": default_system}]
    return login, pwd, base_url, default_system, pf, pt, stations


async def _bump_progress(db, log_id, by_station, total: int = 0,
                         working: int | None = None) -> None:
    """Обновить прогресс ChannelSyncLog. working — индекс станции (1-based),
    которая СЕЙЧАС обрабатывается (показываем «Станция X/N: загрузка смен…»,
    пока станция качается из STS — иначе долго висит «Подключение»). Без
    working — станция завершена («станция X/N · загружено N»)."""
    if log_id is None:
        return
    log = await db.get(ChannelSyncLog, log_id)
    if log is None:
        return
    loaded = sum(int(r.get("created", 0) or 0) for r in by_station)
    done = len(by_station)
    log.loaded = loaded
    if working is not None:
        msg = f"Станция {working}/{total}: загрузка смен из STS…"
        sd = working - 1
    else:
        msg = f"станция {done}/{total} · загружено {loaded}"
        sd = done
    log.events = [{
        "level": "info", "event": "run", "message": msg,
        "stations_done": sd, "stations_total": total, "loaded": loaded,
    }]


async def _run_sts_stations(db, channel, src, ingest_fn, kind: str,
                            date_from: str | None = None, date_to: str | None = None,
                            log_id=None, station_codes: list[int] | None = None,
                            all_period: bool = False) -> dict[str, Any]:
    """Перебор ВСЕХ станций системы (STS /v1/points) с per-станционным savepoint.
    station_codes — точечный отбор станций (UI «Обновить»); None → вся сеть.
    all_period=True → без ограничения по датам (вся история)."""
    from app.routers.fuel_router import NormalizeRequest

    login, pwd, base_url, default_system, pf, pt, stations = await _fuel_context(
        db, channel, src, date_from, date_to, all_period)
    if station_codes:
        wanted = {int(c) for c in station_codes}
        stations = [s for s in stations
                    if int(s.get("code") or s.get("station") or 0) in wanted]
    by_station: list[dict[str, Any]] = []
    for idx, st in enumerate(stations):
        code = int(st.get("code") or st.get("station") or 0)
        if not code:
            continue
        system_code = int(st.get("systemId") or st.get("system_id") or default_system)
        body = NormalizeRequest(
            station_code=code, base_url=base_url, login=login,
            password=pwd, system_code=system_code,
            date_from=pf, date_to=pt,
        )
        # промежуточный статус: станция началась (пока качается из STS — это
        # самая долгая фаза станции, без этого UI висит «Подключение»)
        await _bump_progress(db, log_id, by_station, len(stations), working=idx + 1)
        await db.commit()
        try:
            # savepoint: сбой одной станции откатывается локально и НЕ отравляет
            # общую сессию (иначе PendingRollbackError валит все следующие станции)
            async with db.begin_nested():
                r = await ingest_fn(body, channel.company_id, db)
            by_station.append({"station": code, **r})
            # Прогресс в лог + поэтапный commit: данные станции сохраняются СРАЗУ,
            # а UI-поллинг видит растущее «загружено N» (иначе минуты висит 0 и
            # выглядит как «ничего не грузится»).
            await _bump_progress(db, log_id, by_station, len(stations))
            await db.commit()
        except Exception as e:  # одна станция не валит весь прогон
            await db.rollback()
            by_station.append({"station": code, "error": str(e)[:200]})

    ok = sum(1 for r in by_station if "error" not in r)
    return {"status": "success", "kind": kind,
            "stations_total": len(stations), "stations_ok": ok,
            "by_station": by_station}


async def _run_fuel(db: AsyncSession, channel: Channel, src: Source,
                    date_from: str | None = None, date_to: str | None = None,
                    log_id=None, station_codes: list[int] | None = None,
                    all_period: bool = False) -> dict[str, Any]:
    """Канал продаж (fuel_shift): shift_report → FuelShift, БЕЗ ТТН."""
    from app.routers.fuel_router import ingest_fuel_shifts

    async def _ingest(body, cid, db):
        return await ingest_fuel_shifts(body, cid, db, with_receipts=False)

    return await _run_sts_stations(db, channel, src, _ingest, "fuel_shift",
                                   date_from, date_to, log_id, station_codes, all_period)


async def _run_fuel_delivery(db: AsyncSession, channel: Channel, src: Source,
                             date_from: str | None = None, date_to: str | None = None,
                             log_id=None, station_codes: list[int] | None = None,
                             all_period: bool = False) -> dict[str, Any]:
    """Канал приёма (fuel_delivery): receipts → FuelReceipt + L1 ТТН."""
    from app.routers.fuel_router import ingest_fuel_deliveries

    return await _run_sts_stations(db, channel, src, ingest_fuel_deliveries, "fuel_delivery",
                                   date_from, date_to, log_id, station_codes, all_period)


# ---------------------------------------------------------------------------
# Ветка MSTO — онлайн-заказы агрегаторов (внешний источник сверки онлайн-канала)
# ---------------------------------------------------------------------------
async def _run_msto(db: AsyncSession, channel: Channel, src: Source,
                    date_from: str | None = None, date_to: str | None = None,
                    all_period: bool = False) -> dict[str, Any]:
    """Канал онлайн-заказов MSTO: транзакции агрегаторов → OnlineOrder.
    Креды MSTO — в settings (через reconciliation_proxy). servicePointId станций
    берём из config.stations[].mstoServicePointId; пусто → вся сеть MSTO."""
    from app.routers.online_orders_router import ingest_online_orders

    pf, pt = (None, None) if all_period else _period(channel, date_from, date_to)
    spids: list[int] = []
    for st in ((channel.config or {}).get("stations") or []):
        v = st.get("mstoServicePointId") or st.get("msto_service_point_id") or st.get("servicePointId")
        try:
            if v:
                spids.append(int(v))
        except (ValueError, TypeError):
            pass
    r = await ingest_online_orders(db, channel.company_id, pf, pt, spids or None)
    return {"status": "success", "kind": "msto", "period": [pf, pt],
            "created": r.get("created", 0), "skipped": r.get("skipped", 0),
            "fetched": r.get("fetched", 0),
            "message": f"загружено {r.get('created', 0)} (из {r.get('fetched', 0)})"}


# ---------------------------------------------------------------------------
# Ветка ручной таблицы (реестр «Договоры и оплаты ЭЗС») — server-side L1→L2
# ---------------------------------------------------------------------------
async def _run_reestr(db: AsyncSession, channel: Channel, src: Source,
                      mode: str = "append") -> dict[str, Any]:
    """Реестры «Энергоснабжение и аренда ЭЗС» — ОДИН канал, НЕСКОЛЬКО файлов-слотов.

    Формат загруженного xlsx определяется автоматически (detect_reestr_format):
    старый «Общий свод» либо «Сводная» / «Договоры_Аренда» / «Тарифы
    Электроэнергия_Входящие». Обработанный файл запоминается в слоте
    config.uploadFiles[<формат>] — по слоту на формат.

    mode='append' (обычная загрузка) — обработать свежезагруженный файл
    (config.uploadFileId) и обновить его слот; mode='all' — переобработать ВСЕ
    сохранённые слоты в порядке каскада (Сводная прописывает станциям
    buNumber/zoi1, затем аренда и тарифы резолвятся по ним) — полезно после
    обновления справочника станций."""
    from app.services.reestr_rushydro import (
        REESTR_SLOT_LABEL, REESTR_SLOT_ORDER, run_reestr_file,
    )
    cfg = dict(channel.config or {})
    slots = dict(cfg.get("uploadFiles") or {})

    async def _read_file(file_id) -> tuple[SourceFile | None, bytes | None]:
        try:
            sf = await db.get(SourceFile, _uuid.UUID(str(file_id)))
        except (ValueError, TypeError):
            sf = None
        if sf is None:
            return None, None
        with open(sf.storage_path, "rb") as fh:
            return sf, fh.read()

    def _fix_name(s: str | None) -> str | None:
        """Имя файла из multipart может прийти mojibake: байты UTF-8 или CP1251,
        прочитанные как latin-1 (загрузка curl'ом/сторонним клиентом; браузер шлёт
        корректный UTF-8). Если перекодировка даёт кириллицу — чиним."""
        if not s:
            return s

        def cyr(t: str) -> int:
            return sum(1 for ch in t if "а" <= ch.lower() <= "я" or ch.lower() == "ё")

        if cyr(s):
            return s
        try:
            raw = s.encode("latin-1")
        except UnicodeEncodeError:
            return s
        for enc in ("utf-8", "cp1251"):
            try:
                fixed = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if cyr(fixed):
                return fixed
        return s

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if mode == "all":
        if not slots:
            return {"status": "skipped",
                    "message": "нет сохранённых файлов реестров: сначала загрузите таблицы"}
        parts: list[str] = []
        totals = {"shifts": 0, "created": 0, "unmatched": 0}
        for fmt in REESTR_SLOT_ORDER:
            slot = slots.get(fmt)
            if not slot:
                continue
            sf, content = await _read_file(slot.get("fileId"))
            if content is None:
                parts.append(f"{REESTR_SLOT_LABEL.get(fmt, fmt)}: файл не найден")
                continue
            res = await run_reestr_file(db, channel.company_id, content)
            slots[fmt] = {**slot, "processedAt": now,
                          "fileName": _fix_name(slot.get("fileName")),
                          "rows": res.get("shifts"), "unmatched": res.get("unmatched")}
            for k in totals:
                totals[k] += int(res.get(k) or 0)
            parts.append(res.get("message") or f"{fmt}: ok")
        cfg["uploadFiles"] = slots
        channel.config = cfg
        return {"status": "success", "kind": "reestr_all",
                "shifts": totals["shifts"], "created": totals["created"],
                "updated": 0, "skipped_kinds": [],
                "unmatched": totals["unmatched"],
                "message": "Полный прогон реестров — " + "; ".join(parts)}

    file_id = cfg.get("uploadFileId") or cfg.get("upload_file_id")
    if not file_id:
        return {"status": "skipped",
                "message": "не загружена таблица: сначала «Загрузить таблицу» (config.uploadFileId пуст)"}
    sf, content = await _read_file(file_id)
    if content is None:
        return {"status": "error", "message": f"файл {file_id} не найден"}
    res = await run_reestr_file(db, channel.company_id, content)
    fmt = res.get("format") or "svod"
    slots[fmt] = {
        "fileId": str(file_id), "fileName": _fix_name(sf.file_name) if sf else None,
        "uploadedAt": now, "processedAt": now,
        "rows": res.get("shifts"), "unmatched": res.get("unmatched"),
    }
    cfg["uploadFiles"] = slots
    channel.config = cfg
    return res


# ---------------------------------------------------------------------------
# Ветка зарядных сессий ЭЗС (Excel) — server-side L1→L2 (ChargeSession)
# ---------------------------------------------------------------------------
async def _run_charge_sessions(db: AsyncSession, channel: Channel, src: Source,
                               mode: str = "append", log_id=None) -> dict[str, Any]:
    """Загруженный xlsx сессий ЭЗС (SourceFile из config.uploadFileId) → L1 RAW →
    нормализация (connector/user_type) → L2 (ChargeSession с channel_id).

    mode: 'append' (подгрузить новые) | 'replace' (переписать весь датасет компании)."""
    cfg = channel.config or {}
    file_id = cfg.get("uploadFileId") or cfg.get("upload_file_id")
    if not file_id:
        return {"status": "skipped",
                "message": "не загружена таблица сессий: сначала «Загрузить таблицу» (config.uploadFileId пуст)"}
    try:
        sf = await db.get(SourceFile, _uuid.UUID(str(file_id)))
    except (ValueError, TypeError):
        sf = None
    if sf is None:
        return {"status": "error", "message": f"файл {file_id} не найден"}
    with open(sf.storage_path, "rb") as fh:
        content = fh.read()
    from app.services.charge_sessions_normalize import (
        enrich_from_registry, ingest_charge_sessions, parse_sessions_xlsx,
    )
    rows = parse_sessions_xlsx(content)
    res = await ingest_charge_sessions(db, channel.company_id, rows, channel_id=channel.id,
                                       mode=mode, log_id=log_id)
    # Автопереобогащение ЮЛ из сохранённого реестра: без него свежезагруженные
    # корп-сессии висят с выручкой 0 (amount=0, client_amount ещё не рассчитан)
    # до ручного «Переприменить» — занижение во всех панелях.
    if res.get("status") == "success":
        try:
            enr = await enrich_from_registry(db, channel.company_id, channel_id=channel.id)
            if enr.get("status") == "success" and enr.get("updated"):
                res["message"] = (res.get("message") or "") + f"; авто-обогащение ЮЛ: {enr['message']}"
        except Exception as exc:  # обогащение — не повод ронять загрузку
            res["message"] = (res.get("message") or "") + f"; авто-обогащение ЮЛ не удалось: {exc}"
    return res


async def _run_stations(db: AsyncSession, channel: Channel, src: Source,
                        mode: str = "append", log_id=None) -> dict[str, Any]:
    """Загруженный xlsx справочника станций (SourceFile из config.uploadFileId) → L1 →
    нормализация паспорта → L2 (ServiceLocation type='charge_station' с region_id).

    mode: 'append' (только новые) | 'replace' (обновить существующие + добавить новые)."""
    cfg = channel.config or {}
    file_id = cfg.get("uploadFileId") or cfg.get("upload_file_id")
    if not file_id:
        return {"status": "skipped",
                "message": "не загружен справочник станций: сначала «Загрузить таблицу» (config.uploadFileId пуст)"}
    try:
        sf = await db.get(SourceFile, _uuid.UUID(str(file_id)))
    except (ValueError, TypeError):
        sf = None
    if sf is None:
        return {"status": "error", "message": f"файл {file_id} не найден"}
    with open(sf.storage_path, "rb") as fh:
        content = fh.read()
    from app.services.stations_normalize import ingest_stations, parse_stations_xlsx
    rows = parse_stations_xlsx(content)
    return await ingest_stations(db, channel.company_id, rows, channel_id=channel.id,
                                 mode=mode, log_id=log_id)


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
async def run_channel(
    db: AsyncSession,
    channel: Channel,
    date_from: str | None = None,
    date_to: str | None = None,
    log_id=None,
    station_codes: list[int] | None = None,
    all_period: bool = False,
    mode: str = "append",
) -> dict[str, Any]:
    """Прогон канала: fetch→normalize→save, ветка по типу источника и шаблону.

    date_from/date_to (YYYY-MM-DD) — явный период загрузки из запроса (UI).
    Приоритетнее config канала и period_days. log_id — ChannelSyncLog для
    обновления прогресса по ходу (живое «загружено N» в UI-поллинге).
    station_codes — точечный отбор станций (UI «Обновить»); None → вся сеть STS.
    all_period — вся история (без ограничения по датам).
    mode — режим загрузки табличных источников (сессии ЭЗС): 'append' подгрузить
    новые / 'replace' переписать весь датасет компании."""
    src = await _channel_source(db, channel.id)
    if src is None:
        return {"status": "skipped", "message": "в потоках канала нет источника"}
    if src.source_type == "onec_operational":
        return await _run_cb(db, channel, src, date_from, date_to)
    if src.source_type == "manual_table":
        return await _run_reestr(db, channel, src, mode=mode)
    if src.source_type == "charge_sessions_excel":
        return await _run_charge_sessions(db, channel, src, mode=mode, log_id=log_id)
    if src.source_type == "stations_excel":
        return await _run_stations(db, channel, src, mode=mode, log_id=log_id)
    if src.source_type == "sts":
        if (channel.template_id or "") == "fuel_delivery":
            return await _run_fuel_delivery(db, channel, src, date_from, date_to, log_id, station_codes, all_period)
        return await _run_fuel(db, channel, src, date_from, date_to, log_id, station_codes, all_period)
    if src.source_type == "msto":
        return await _run_msto(db, channel, src, date_from, date_to, all_period)
    return {"status": "skipped",
            "message": f"тип источника '{src.source_type}' оркестратором пока не исполняется"}
