"""
Оркестратор канала: fetch → normalize → save (живая петля сопутки/общепита).

run_channel(db, channel):
  поток onec_operational → его Source → COM-подключение к ЦБ →
  fetch_cb_shifts (пакеты смен) → ingest_packages (normalize + DataEntry L2).

⚠ Транспорт: OneCComClient (subprocess com_worker, 32-бит COM) — работает на
Windows (COM-Agent / dev-машина). В проде на Linux-backend fetch идёт через
COM-Agent (http_agent) — для этого нужен forward fetch_cb_shifts в http-клиенте.
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


async def _onec_source(db: AsyncSession, channel_id) -> Source | None:
    """Source типа onec_operational среди потоков канала."""
    streams = (
        await db.execute(select(ChannelStream).where(ChannelStream.channel_id == channel_id))
    ).scalars().all()
    for s in streams:
        src = await db.get(Source, s.source_id)
        if src is not None and src.source_type == "onec_operational":
            return src
    return None


def _conn_string(src: Source, password: str) -> str:
    """Собрать COM-строку соединения из connection_config + пароль."""
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


async def run_channel(db: AsyncSession, channel: Channel) -> dict[str, Any]:
    """Прогон канала: pull смен из ЦБ → нормализация → L2 (DataEntry)."""
    src = await _onec_source(db, channel.id)
    if src is None:
        return {"status": "skipped",
                "message": "в потоках канала нет источника onec_operational"}

    cr = (
        await db.execute(
            select(SourceCredentials).where(SourceCredentials.source_id == src.id)
        )
    ).scalar_one_or_none()
    enc = (cr.encrypted_values or {}) if cr else {}
    pwd = decrypt_password(enc["password"]) if enc.get("password") else ""

    conn = _conn_string(src, pwd)
    cfg = src.connection_config or {}
    station = str((channel.config or {}).get("station")
                  or cfg.get("default_station") or "208")
    days = int(channel.period_days or 30)
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    pf, pt = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")

    async with OneCComClient(conn) as client:
        packages = await client.fetch_cb_shifts(pf, pt, station=station, limit=200)

    result = await ingest_packages(db, channel.company_id, packages)
    return {"status": "success", "period": [pf, pt], "station": station, **result}
