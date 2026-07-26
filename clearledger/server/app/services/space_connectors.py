"""Подключения пространства — откуда в компании берутся данные (docs/SPACE.md).

Пространство одно, а источники разбросаны по приложениям: файловые каналы ведёт Учёт,
живые интеграции (HubEx, телефония, мессенджеры) — Координатор, чат и почту — платформа.
Пока каждый показывал только своё, ответа на вопрос «что вообще подключено у компании»
не было ни на одном экране.

Собираем список НА ЛЕТУ, а не храним копию: состояние коннектора меняется каждые
несколько минут (последний синк, ошибка), и любой снимок в Ядре был бы враньём.
Приложение спрашиваем тем же служебным каналом, что и проекцию: RS256-токен с коротким
сроком, внутренний адрес сервиса, приёмник проверяет подпись по JWKS Ядра.

Владелец записи — приложение. Здесь витрина: показать и увести настраивать туда, где
коннектор живёт. Заводить чужие подключения отсюда нельзя — иначе секреты провайдеров
и логика синка разъедутся по двум местам.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import App, AppCompanyLink, Channel
from app.services import sso
from app.services.space_projection import _internal_base_url

settings = get_settings()

# Витрина не должна висеть из-за приложения, которое молчит: лучше показать остальные
# источники и честную отметку «не ответило», чем крутить спиннер.
TIMEOUT = httpx.Timeout(5.0)


def _brings(text: str | None) -> str:
    """Короткая строка «что приносит»: у каналов Учёта описание — целый абзац с
    маршрутом обработки, в общей таблице от него остаётся только первая мысль."""
    if not text:
        return ""
    first = text.strip().split(". ")[0].strip(" .")
    return first if len(first) <= 110 else first[:107].rstrip() + "…"


def _channel_entry(ch: Channel) -> dict[str, Any]:
    """Файловый канал Учёта как источник пространства."""
    cfg = ch.config or {}
    uploads = cfg.get("uploadFiles") or {}
    return {
        "key": f"ledger:{ch.id}",
        "app": "ledger",
        "app_name": "Учёт",
        "provider": ch.template_id or "file",
        "kind": "Файловый канал",
        "label": ch.name,
        "brings": _brings(ch.description),
        "direction": "in",
        "status": ch.status,
        "enabled": ch.status == "active",
        "last_sync_at": ch.last_sync_at.isoformat() if ch.last_sync_at else None,
        "last_error": None,
        "records": ch.docs_loaded or 0,
        "files": len(uploads) if isinstance(uploads, dict) else 0,
        "settings_route": "/data/connectors",
    }


def _service_entry(code: str, name: str, brings: str, enabled: bool) -> dict[str, Any]:
    """Платформенный сервис стека — тоже поставщик данных (сообщения, встречи, письма)."""
    return {
        "key": f"core:{code}",
        "app": "core",
        "app_name": "Платформа",
        "provider": code,
        "kind": "Платформенный сервис",
        "label": name,
        "brings": brings,
        "direction": "both",
        "status": "active" if enabled else "off",
        "enabled": enabled,
        "last_sync_at": None,
        "last_error": None,
        "records": None,
        "files": 0,
        "settings_route": "/admin/eco/overview",
    }


async def _app_connectors(
    app_row: App, link: AppCompanyLink, app_code: str, app_name: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Спросить приложение о его коннекторах. Ошибку возвращаем, а не роняем витрину."""
    token = sso.sign_service_token(aud=app_code, scope="projection")
    if not token:
        return [], "единый вход не настроен (нет ключа подписи)"

    url = f"{_internal_base_url(app_row, app_code)}/api/v1/eco/connectors"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                url,
                params={"companyId": link.external_company_id},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        return [], f"приложение недоступно: {e}"

    if resp.status_code == 404:
        # Старая версия приложения: маршрута ещё нет — это не ошибка компании.
        return [], "приложение не отдаёт список подключений (старая версия)"
    if resp.status_code >= 400:
        return [], f"приложение вернуло HTTP {resp.status_code}"

    items = (resp.json() or {}).get("connectors") or []
    out: list[dict[str, Any]] = []
    for it in items:
        out.append({
            "key": f"{app_code}:{it.get('id') or it.get('provider')}",
            "app": app_code,
            "app_name": app_name,
            "provider": it.get("provider") or "",
            "kind": it.get("kind") or "Интеграция",
            "label": it.get("label") or it.get("provider") or "",
            "brings": it.get("brings") or "",
            "direction": it.get("direction") or "in",
            "status": it.get("status") or "unknown",
            "enabled": bool(it.get("enabled")),
            "last_sync_at": it.get("last_sync_at"),
            "last_error": it.get("last_error"),
            "records": it.get("records"),
            "files": 0,
            # Настройка живёт в приложении: витрина только уводит туда.
            "settings_app": app_code,
        })
    return out, None


async def list_connectors(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Все источники данных компании: файловые каналы, интеграции приложений, сервисы."""
    items: list[dict[str, Any]] = []

    channels = (await db.execute(
        select(Channel).where(Channel.company_id == company_id).order_by(Channel.name)
    )).scalars().all()
    items.extend(_channel_entry(c) for c in channels)

    items.append(_service_entry(
        "chat", "Чат (Matrix)", "Переписка и темы пространства", settings.chat_enabled))
    items.append(_service_entry(
        "mail", "Почта (SMTP)", "Письма приглашений и уведомлений", bool(settings.smtp_host)))

    # Приложения-разрезы: спрашиваем только те, что подключены компании и знают её.
    rows = (await db.execute(
        select(App, AppCompanyLink)
        .join(AppCompanyLink, AppCompanyLink.app_id == App.id)
        .where(AppCompanyLink.company_id == company_id)
    )).all()

    problems: list[dict[str, str]] = []
    for app_row, link in rows:
        entries, err = await _app_connectors(app_row, link, app_row.code, app_row.name)
        items.extend(entries)
        if err:
            problems.append({"app": app_row.code, "app_name": app_row.name, "error": err})

    return {"connectors": items, "problems": problems}
