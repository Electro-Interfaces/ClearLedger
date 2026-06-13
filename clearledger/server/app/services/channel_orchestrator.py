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
    result = await ingest_packages(db, channel.company_id, packages)
    return {"status": "success", "kind": "cb", "period": [pf, pt], "station": station, **result}


# ---------------------------------------------------------------------------
# Ветка STS (топливо + ТТН)
# ---------------------------------------------------------------------------
async def _run_fuel(db: AsyncSession, channel: Channel, src: Source) -> dict[str, Any]:
    from app.routers.fuel_router import NormalizeRequest, ingest_fuel_shifts

    cfg = src.connection_config or {}
    pwd = await _decrypt_pwd(db, src.id)
    station = str((channel.config or {}).get("station") or cfg.get("default_station") or "").strip()
    sysids = str(cfg.get("default_system_ids") or "65")
    system_code = int((sysids.split(",")[0].strip() or "65"))
    body = NormalizeRequest(
        station_code=int(station or 0),
        base_url=str(cfg.get("base_url") or "https://pos.autooplata.ru/tms"),
        login=str(cfg.get("login") or ""),
        password=pwd,
        system_code=system_code,
    )
    result = await ingest_fuel_shifts(body, channel.company_id, db)
    return {"status": "success", "kind": "fuel", "station": station, **result}


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
async def run_channel(db: AsyncSession, channel: Channel) -> dict[str, Any]:
    """Прогон канала: fetch→normalize→save, ветка по типу источника."""
    src = await _channel_source(db, channel.id)
    if src is None:
        return {"status": "skipped", "message": "в потоках канала нет источника"}
    if src.source_type == "onec_operational":
        return await _run_cb(db, channel, src)
    if src.source_type == "sts":
        return await _run_fuel(db, channel, src)
    return {"status": "skipped",
            "message": f"тип источника '{src.source_type}' оркестратором пока не исполняется"}
