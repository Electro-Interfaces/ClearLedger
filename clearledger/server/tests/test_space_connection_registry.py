"""Реестр подключений: разбор доклада приложения и признак устаревания.

Ловим то, из-за чего витрина снова начнёт врать: принятый мусор вместо
подключения, чужое значение в разрезе (по ним строятся отборы) и запись, о
которой давно не докладывали, показанная как свежая.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models import SpaceConnection
from app.services.space_connection_registry import STALE_AFTER, _pick, entry

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = dict(
        id=uuid.uuid4(), company_id=uuid.uuid4(), app_code="support",
        external_id="c-1", provider="mango", kind="channel", name="",
        direction="in", initiator="us", engagement_mode="own",
        status="active", configured=True, secret_ref=None, endpoint=None,
        last_sync_at=None, last_error=None, reported_at=_NOW,
    )
    base.update(kw)
    return SpaceConnection(**base)


def test_чужое_значение_разреза_заменяется_известным():
    # По этим полям строятся отборы витрины. Пропустить произвольную строку —
    # значит получить разрез, в котором подключение не находится ни по одному
    # фильтру и потому невидимо.
    assert _pick("them", ("us", "them"), "us") == "them"
    assert _pick("ОНИ", ("us", "them"), "us") == "us"
    assert _pick(None, ("us", "them"), "us") == "us"
    assert _pick("  BOTH  ", ("in", "out", "both"), "in") == "both"


def test_запись_без_доклада_дольше_срока_помечается_устаревшей():
    fresh = entry(_row(reported_at=_NOW - timedelta(hours=1)), _NOW)
    old = entry(_row(reported_at=_NOW - STALE_AFTER - timedelta(minutes=1)), _NOW)
    assert fresh["stale"] is False
    # Устаревшая не исчезает с экрана: молчание приложения не означает, что
    # подключения больше нет.
    assert old["stale"] is True
    assert old["status"] == "active"


def test_имя_подставляется_из_провайдера_если_пусто():
    assert entry(_row(name=""), _NOW)["name"] == "mango"
    assert entry(_row(name="Манго ВАТС"), _NOW)["name"] == "Манго ВАТС"


def test_в_витрину_не_попадает_значение_секрета():
    # `secret_ref` — ссылка, а не секрет; проверяем, что модель не отдаёт ничего,
    # кроме неё, даже если владелец пришлёт лишнее.
    out = entry(_row(secret_ref="HUBEX_RUSHYDRO"), _NOW)
    assert out["secret_ref"] == "HUBEX_RUSHYDRO"
    assert not any("pass" in key or "token" in key or "key" in key for key in out)
