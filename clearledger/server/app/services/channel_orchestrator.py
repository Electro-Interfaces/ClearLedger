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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelStream, Source, SourceCredentials
from app.services.cb_intake import ingest_packages
from app.services.onec.com_client import OneCComClient
from app.services.onec.crypto import decrypt_password


async def _channel_source(db: AsyncSession, channel_id, source_type: str | None = None) -> Source | None:
    """Первый Source среди потоков канала (опц. фильтр по source_type)."""
    streams = (
        await db.execute(select(ChannelStream).where(ChannelStream.channel_id == channel_id))
    ).scalars().all()
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


def _period(channel: Channel) -> tuple[str, str]:
    """Период прогона: явный диапазон config.dateFrom/dateTo (UI «Период загрузки»)
    в приоритете; иначе фолбэк к period_days как глубине от сегодня."""
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
async def _run_cb(db: AsyncSession, channel: Channel, src: Source) -> dict[str, Any]:
    conn = _conn_string(src, await _decrypt_pwd(db, src.id))
    cfg = src.connection_config or {}
    station = str((channel.config or {}).get("station") or cfg.get("default_station") or "208")
    pf, pt = _period(channel)
    async with OneCComClient(conn) as client:
        packages = await client.fetch_cb_shifts(pf, pt, station=station, limit=200)
    result = await ingest_packages(db, channel.company_id, packages, channel_id=channel.id)
    return {"status": "success", "kind": "cb", "period": [pf, pt], "station": station, **result}


# ---------------------------------------------------------------------------
# Ветка STS (топливо). Раздельно, как в расширении БП: продажи (ОбработатьСмену)
# и приём ТТН (ОбработатьТТН) — это РАЗНЫЕ каналы с разными разрезами.
#   • fuel_shift    → shift_report → FuelShift (продажи), без ТТН.
#   • fuel_delivery → receipts     → FuelReceipt + L1 ТТН (приём).
# ---------------------------------------------------------------------------
async def _fuel_context(db: AsyncSession, channel: Channel, src: Source):
    """Общий контекст STS-прогона: креды, период, станции канала."""
    cfg = src.connection_config or {}
    pwd = await _decrypt_pwd(db, src.id)
    login = str(cfg.get("login") or "")
    base_url = str(cfg.get("base_url") or "https://pos.autooplata.ru/tms")
    sysids = str(cfg.get("default_system_ids") or "65")
    default_system = int((sysids.split(",")[0].strip() or "65"))
    pf, pt = _period(channel)  # период канала — НЕ грузить всю историю

    # Станции канала: список config.stations [{code, systemId}] ИЛИ единственная config.station
    ch_cfg = channel.config or {}
    stations = list(ch_cfg.get("stations") or [])
    if not stations:
        single = ch_cfg.get("station") or cfg.get("default_station")
        if single:
            stations = [{"code": single, "systemId": default_system}]
    return login, pwd, base_url, default_system, pf, pt, stations


async def _run_sts_stations(db, channel, src, ingest_fn, kind: str) -> dict[str, Any]:
    """Перебор станций канала с per-станционным savepoint; ingest_fn — ветка."""
    from app.routers.fuel_router import NormalizeRequest

    login, pwd, base_url, default_system, pf, pt, stations = await _fuel_context(db, channel, src)
    by_station: list[dict[str, Any]] = []
    for st in stations:
        code = int(st.get("code") or st.get("station") or 0)
        if not code:
            continue
        system_code = int(st.get("systemId") or st.get("system_id") or default_system)
        body = NormalizeRequest(
            station_code=code, base_url=base_url, login=login,
            password=pwd, system_code=system_code,
            date_from=pf, date_to=pt,
        )
        try:
            # savepoint: сбой одной станции откатывается локально и НЕ отравляет
            # общую сессию (иначе PendingRollbackError валит все следующие станции)
            async with db.begin_nested():
                r = await ingest_fn(body, channel.company_id, db)
            by_station.append({"station": code, **r})
        except Exception as e:  # одна станция не валит весь прогон
            by_station.append({"station": code, "error": str(e)[:200]})

    ok = sum(1 for r in by_station if "error" not in r)
    return {"status": "success", "kind": kind,
            "stations_total": len(stations), "stations_ok": ok,
            "by_station": by_station}


async def _run_fuel(db: AsyncSession, channel: Channel, src: Source) -> dict[str, Any]:
    """Канал продаж (fuel_shift): shift_report → FuelShift, БЕЗ ТТН."""
    from app.routers.fuel_router import ingest_fuel_shifts

    async def _ingest(body, cid, db):
        return await ingest_fuel_shifts(body, cid, db, with_receipts=False)

    return await _run_sts_stations(db, channel, src, _ingest, "fuel_shift")


async def _run_fuel_delivery(db: AsyncSession, channel: Channel, src: Source) -> dict[str, Any]:
    """Канал приёма (fuel_delivery): receipts → FuelReceipt + L1 ТТН."""
    from app.routers.fuel_router import ingest_fuel_deliveries

    return await _run_sts_stations(db, channel, src, ingest_fuel_deliveries, "fuel_delivery")


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
async def run_channel(db: AsyncSession, channel: Channel) -> dict[str, Any]:
    """Прогон канала: fetch→normalize→save, ветка по типу источника и шаблону."""
    src = await _channel_source(db, channel.id)
    if src is None:
        return {"status": "skipped", "message": "в потоках канала нет источника"}
    if src.source_type == "onec_operational":
        return await _run_cb(db, channel, src)
    if src.source_type == "sts":
        if (channel.template_id or "") == "fuel_delivery":
            return await _run_fuel_delivery(db, channel, src)
        return await _run_fuel(db, channel, src)
    return {"status": "skipped",
            "message": f"тип источника '{src.source_type}' оркестратором пока не исполняется"}
