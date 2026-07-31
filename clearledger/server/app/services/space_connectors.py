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
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import App, AppCompanyLink, Channel, Company, Source, SourceSync
from app.services import sso
from app.services.space_projection import _internal_base_url

settings = get_settings()

# Кто инициирует обмен: 'us' — мы ходим во внешнюю систему, 'them' — внешняя
# система стучится к нам (вебхуки, входящие API-ключи). Это ДРУГАЯ ось, чем
# direction (куда текут данные): STS мы опрашиваем сами (initiator=us, данные in),
# а дедуп-нода сама толкает нам данные (initiator=them, данные тоже in).
# Ответ «кто подключён к нам» — это initiator=them (docs/CONNECT.md, В1).
_INITIATOR_BY_PROVIDER: dict[str, str] = {
    "megafon": "them", "telegram": "them", "email": "them",
    "hubex": "us", "msto": "us", "plane": "us", "tradelink": "us", "db": "us",
}

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
        "initiator": "us",
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
        "initiator": "both",
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
            "initiator": it.get("initiator")
                or _INITIATOR_BY_PROVIDER.get(str(it.get("provider") or ""), "us"),
            # Настройка живёт в приложении: витрина только уводит туда.
            "settings_app": app_code,
        })
    return out, None


# Как называется подключение того или иного типа — человеческими словами. Код типа
# («onec_operational», «acquiring_sber») администратору ничего не говорит.
_SOURCE_KIND: dict[str, str] = {
    "sts": "API кассового сервера",
    "sts_transactions": "API кассового сервера",
    "msto": "API агрегаторов",
    "onec_accounting": "Обмен с 1С",
    "onec_operational": "Обмен с 1С",
    "acquiring_sber": "Эквайринг",
    "ofd": "ОФД",
    "chestny_znak": "Честный знак",
}

# Что подключение приносит в пространство — по типу источника.
_SOURCE_BRINGS: dict[str, str] = {
    "sts": "Смены, реализация, резервуары и накладные АЗС",
    "sts_transactions": "Пооперационные наливы (реестр операций)",
    "msto": "Онлайн-заказы агрегаторов",
    "onec_accounting": "Документы и справочники 1С:Бухгалтерии",
    "onec_operational": "Товародвижение сопутки и общепита из ЦБ",
    "acquiring_sber": "Реестры эквайринга",
    "ofd": "Фискальные чеки ОФД",
    "chestny_znak": "Обороты маркированного товара",
}

# Состояние источника → состояние подключения в витрине.
_SOURCE_STATUS: dict[str, str] = {
    "connected": "active", "error": "error",
    "disconnected": "disabled", "draft": "configured",
}


def _source_entry(src: Source, last_sync: datetime | None, records: int | None) -> dict[str, Any]:
    """Живая интеграция как запись витрины.

    Раньше витрина показывала только файловые каналы и платформенные сервисы, и
    настроенные подключения к внешним системам (STS, MSTO, 1С, эквайринг, ОФД,
    «Честный знак») в неё не попадали вовсе — у ГИГ это 7 источников из 11.
    Администратор видел «6 подключений» там, где их одиннадцать.
    """
    kind = _SOURCE_KIND.get(src.source_type, "Внешняя система")
    return {
        "key": f"source:{src.id}",
        "app": "core", "app_name": "Ядро",
        "provider": src.source_type,
        "kind": kind,
        "label": src.name,
        "brings": _brings(src.description) or _SOURCE_BRINGS.get(src.source_type, "Данные внешней системы"),
        "direction": "in",
        "status": _SOURCE_STATUS.get(src.status, "configured"),
        "enabled": src.status == "connected",
        "last_sync_at": last_sync.isoformat() if last_sync else (
            src.last_test_at.isoformat() if src.last_test_at else None),
        "last_error": src.error_message,
        "records": records,
        "files": 0,
        "initiator": "us",
        # Настройка живёт в продукте «Данные» — там же, где заводят коннектор.
        "settings_route": "/connectors",
    }


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

    # ВХОДЯЩИЕ: кто подключён к нам. До В1 этот класс не показывался нигде —
    # администратор не видел, что внешние системы толкают данные в пространство.
    company = await db.get(Company, company_id)
    if company is not None and getattr(company, "cloud_api_key", None):
        items.append({
            "key": "core:cloud-api-key",
            "app": "core", "app_name": "Ядро",
            "provider": "cloud_api_key",
            "kind": "Входящий API-ключ",
            "label": "Приём данных по ключу пространства",
            "brings": "Внешние узлы толкают данные сами (дедуп-нода, аудитор Поддержки). "
                      "Ключ один на всех потребителей — именные ключи с ротацией: В2",
            "direction": "in", "status": "active", "enabled": True,
            "last_sync_at": None, "last_error": None, "records": None, "files": 0,
            "initiator": "them",
            "settings_route": None,
        })
    # HubEx в Ядре подключён глобальным токеном мимо модели источников — до В2
    # хотя бы показываем его как подключение, а не прячем.
    if getattr(settings, "hubex_service_token", None):
        items.append({
            "key": "core:hubex",
            "app": "core", "app_name": "Ядро",
            "provider": "hubex",
            "kind": "FSM подрядчика",
            "label": "HubEx (общий токен стека)",
            "brings": "Задачи и объекты FSM. Токен один на стек — перевод на "
                      "подключение по компаниям: В2",
            "direction": "in", "status": "active", "enabled": True,
            "last_sync_at": None, "last_error": None, "records": None, "files": 0,
            "initiator": "us",
            "settings_route": None,
        })

    # Настроенные подключения к внешним системам. Когда синхронизировались и сколько
    # принесли — из журнала синков, иначе витрина показывает подключение «мёртвым».
    sources = (await db.execute(
        select(Source).where(Source.company_id == company_id).order_by(Source.name)
    )).scalars().all()
    # Журнал синков ведётся по ТИПУ синхронизации, а не по источнику, поэтому
    # сопоставляем по типу: грубее, чем хотелось бы, но честнее, чем показывать
    # живое подключение вообще без отметки о работе.
    sync_by_type: dict[str, tuple[datetime | None, int | None]] = {}
    if sources:
        for stype, finished, processed in (await db.execute(
            select(SourceSync.sync_type, func.max(SourceSync.finished_at),
                   func.sum(SourceSync.items_processed))
            .where(SourceSync.company_id == company_id)
            .group_by(SourceSync.sync_type)
        )).all():
            sync_by_type[str(stype)] = (
                finished, int(processed) if processed is not None else None)
    for src in sources:
        last_sync, records = sync_by_type.get(src.source_type, (None, None))
        items.append(_source_entry(src, last_sync, records))

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
