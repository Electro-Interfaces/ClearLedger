"""Подключения пространства — откуда в компании берутся данные (docs/SPACE.md).

Пространство одно, а источники разбросаны по приложениям: файловые каналы ведёт Учёт,
живые интеграции (HubEx, телефония, мессенджеры) — Координатор, чат и почту — платформа.
Пока каждый показывал только своё, ответа на вопрос «что вообще подключено у компании»
не было ни на одном экране.

Собираем список НА ЛЕТУ, а не храним копию: состояние коннектора меняется каждые
несколько минут (последний синк, ошибка), и любой снимок в Ядре был бы враньём.
Приложение спрашиваем тем же служебным каналом, что и проекцию: RS256-токен с коротким
сроком, внутренний адрес сервиса, приёмник проверяет подпись по JWKS Ядра.

Владелец записи — приложение. Для провайдеров с контрактом управления настройка
открывается здесь, а запись и исполнение делегируются владельцу. Секреты не дублируются.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import App, AppCompanyLink, Channel, Company, Source
from app.services import sso
from app.services.space_projection import _internal_base_url

settings = get_settings()
logger = logging.getLogger("clearledger.connectors")

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
        # `enabled` — «включён ли», а не «здоров ли»: канал в ошибке или на паузе
        # включён. Раньше здесь стояло `status == "active"`, и три разных состояния
        # канала схлопывались на витрине в одно «Выключен».
        "enabled": ch.status != "draft",
        "last_sync_at": ch.last_sync_at.isoformat() if ch.last_sync_at else None,
        "last_error": ch.last_error if getattr(ch, "last_error", None) else None,
        "records": ch.docs_loaded or 0,
        "files": len(uploads) if isinstance(uploads, dict) else 0,
        "initiator": "us",
        # Маршрута /data/connectors не существует — кнопка настройки у каждого
        # файлового канала вела на страницу «не найдено». У ГИГ и РусГидро это
        # большинство строк витрины.
        "settings_route": f"/connectors/{ch.id}",  # карточка канала — отдельный экран
    }


def _service_entry(code: str, name: str, brings: str, enabled: bool,
                   status: str | None = None) -> dict[str, Any]:
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
        "status": status or ("active" if enabled else "off"),
        "enabled": enabled,
        "last_sync_at": None,
        "last_error": None,
        "records": None,
        "files": 0,
        "initiator": "both",
        # Настройка платформенных сервисов живёт на уровне контейнера и открыта
        # только суперадмину — администратора компании прежняя кнопка молча
        # выбрасывала на чужой раздел. Компания их и не настраивает.
        "settings_route": None,
    }


async def _chat_alive() -> str | None:
    """Живой ли Matrix: «настроен в стеке» и «отвечает» — разные ответы.

    Проверку раньше делало только `/core/status`, а оно закрыто суперадмином:
    администратор компании видел на «Состоянии» пустую карточку сервисов и решал,
    что раздел показывает подключения выборочно. Витрине проверка нужнее — она
    и так ходит по HTTP к приложениям.
    """
    if not settings.synapse_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(settings.synapse_url.rstrip("/") + "/health")
            return "active" if r.status_code == 200 else "error"
    except httpx.HTTPError:
        return "error"


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
        logger.warning("коннекторы %s не получены: %s", app_code, e)
        # Текст исключения httpx несёт внутренний адрес сервиса
        # (`http://support:3003/...`) — топология стека не дело участника компании.
        return [], "приложение не ответило"

    if resp.status_code == 404:
        # Старая версия приложения: маршрута ещё нет — это не ошибка компании.
        return [], "приложение не отдаёт список подключений (старая версия)"
    if resp.status_code >= 400:
        return [], f"приложение вернуло HTTP {resp.status_code}"

    try:
        items = (resp.json() or {}).get("connectors") or []
    except ValueError:
        # Приложение за кромкой отдало HTML с кодом 200. Раньше это исключение
        # уходило наружу, и администратор не видел НИ ОДНОГО подключения компании.
        return [], "приложение ответило не по контракту (не JSON)"
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
            "last_test_at": it.get("last_test_at"),
            "management": it.get("management"),
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
    # Способ получить внешние данные — это и есть коннектор, независимо от того,
    # живой ли это обмен или файл. Выгрузка информационной базы 1С отличается от
    # прямого обмена только тем, КАК данные доехали, а не тем, чем они являются.
    "onec_dt": "Выгрузка 1С",
    "onec_com": "Обмен с 1С",
    "edo": "ЭДО",
    "email_inbox": "Почтовый ящик",
    "bank_statement": "Банковская выписка",
    "acquiring": "Эквайринг",
    "file_rule": "Файлы по правилу",
}

# Что подключение приносит в пространство — по типу источника.
_SOURCE_BRINGS: dict[str, str] = {
    "sts": "Смены, реализация, резервуары и накладные АЗС",
    "sts_transactions": "Пооперационные наливы (реестр операций)",
    "msto": "Онлайн-заказы агрегаторов",
    "onec_accounting": "Документы и справочники 1С:Бухгалтерии",
    "onec_dt": "Проводки, документы и справочники из выгрузки информационной базы",
    "onec_com": "Документы и справочники живой базы 1С",
    "edo": "Входящие и исходящие документы оператора ЭДО",
    "email_inbox": "Документы и письма из почтового ящика",
    "bank_statement": "Поступления и списания по расчётному счёту",
    "acquiring": "Операции эквайринга",
    "file_rule": "Файлы, разобранные по правилу коннектора",
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


def _source_entry(src: Source) -> dict[str, Any]:
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
        # «Подключён» у источника означает «реквизиты приняты проверкой», а не
        # «данные идут»: обмен ведут каналы поверх него. Поэтому обмена нет, а
        # проверка — отдельным полем, со своей подписью на витрине.
        "enabled": src.status != "disconnected",
        "last_sync_at": None,
        "last_test_at": src.last_test_at.isoformat() if src.last_test_at else None,
        "last_error": src.error_message,
        "records": None,
        "files": 0,
        "initiator": "us",
        # Внутрь приложения, а не на голый маршрут: страницы «Подключений» больше
        # не числятся в карте продукта, и прямой /sources открылся бы с чужим меню.
        "settings_route": "/connect?mode=connect&sub=sources",
    }


async def list_connectors(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Все источники данных компании: файловые каналы, интеграции приложений, сервисы."""
    items: list[dict[str, Any]] = []

    channels = (await db.execute(
        select(Channel).where(Channel.company_id == company_id).order_by(Channel.name)
    )).scalars().all()
    items.extend(_channel_entry(c) for c in channels)

    items.append(_service_entry(
        "chat", "Чат (Matrix)", "Переписка и темы пространства", settings.chat_enabled,
        status=await _chat_alive() if settings.chat_enabled else None))
    # Конференции были только в карточке «Каналы связи пространства» и в витрину не
    # попадали: на одном экране получалось два разных состава платформенных сервисов.
    items.append(_service_entry(
        "conf", "Конференции (Jitsi)", "Встречи в браузере: ссылка-приглашение без регистрации",
        bool(getattr(settings, "jitsi_signing_key", None))))
    items.append(_service_entry(
        "mail", "Почта платформы (SMTP)", "Служебные письма: приглашения и уведомления",
        bool(settings.smtp_host)))

    # Почтовые ящики КОМПАНИИ — не то же, что служебный SMTP платформы выше: там
    # уходят приглашения, здесь идёт деловая переписка с контрагентами. Пока ящики
    # были видны только в «Загрузке», администратор не находил их там, где ищет все
    # подключения пространства, и считал, что почта в контейнере одна.
    from app.models import MailAccount
    accounts = (await db.execute(
        select(MailAccount).where(MailAccount.company_id == company_id)
        .order_by(MailAccount.address))).scalars().all()
    # Сколько через ящик реально прошло: у остальных коннекторов в витрине стоит
    # объём, и без него почта выглядела подключением «на бумаге».
    # Таблица есть не в каждом пространстве (на gig схема почты не накатана), а
    # витрина подключений не должна падать целиком из-за одной колонки.
    mail_stat: dict[Any, tuple[int, int]] = {}
    if (await db.execute(text("select to_regclass('mail_messages')"))).scalar():
        mail_stat = {r.account_id: (r.n, r.files) for r in (await db.execute(text("""
        select m.account_id, count(*) as n,
               count(*) filter (where a.id is not null) as files
          from mail_messages m
          left join lateral (select id from mail_attachments x
                              where x.message_id = m.id limit 1) a on true
         where m.company_id = :cid
         group by m.account_id
    """), {"cid": str(company_id)})).all()}
    if not accounts:
        # Пока ящиков нет, коннектора не было в списке ВООБЩЕ — и выходило, что почта
        # компании не считается подключением наравне с остальными. Показываем его как
        # платформенные сервисы: ненастроенный виден и уводит настраивать.
        items.append({
            "key": "core:mail:company",
            "app": "core", "app_name": "Ядро",
            "provider": "mailbox",
            "kind": "Почта компании",
            "label": "Почта компании — ящики не заведены",
            # Ящики привязаны к компании: у соседней компании пространства они могут
            # быть заведены, и «не заведены» здесь означает ровно эту компанию.
            "brings": "Деловая переписка: письма контрагентов, вложения-документы, "
                      "ответы из пространства. Ящики у каждой компании свои — "
                      "заведите первый, и приём пойдёт сам",
            "direction": "both", "status": "off", "enabled": False,
            "last_sync_at": None, "last_error": None, "records": None, "files": 0,
            "initiator": "both",
            "settings_route": "/connect?mode=connect&sub=connectors",
        })
    for a in accounts:
        ready = bool(a.imap_host) and bool(a.password_enc or a.secret_env)
        items.append({
            "key": f"core:mail:{a.id}",
            "app": "core", "app_name": "Ядро",
            "provider": "mailbox",
            "kind": "Почтовый ящик",
            "label": f"{a.title or 'Почта'} · {a.address}",
            "brings": a.purpose or "Деловая переписка компании: письма контрагентов, "
                                   "вложения-документы, ответы из пространства",
            "direction": "in" if a.mode == "in" else ("out" if a.mode == "out" else "both"),
            # Ящик мы опрашиваем сами, а письма приходят когда угодно — обе стороны.
            "initiator": "both",
            "status": ("error" if a.last_error else "ok" if ready else "setup"),
            "enabled": a.is_active,
            "last_sync_at": a.last_sync_at.isoformat() if a.last_sync_at else None,
            "last_error": a.last_error,
            "records": mail_stat.get(a.id, (0, 0))[0],
            "files": mail_stat.get(a.id, (0, 0))[1],
            # Настройка живёт там, где заводят все подключения пространства
            # (решение МАГа 13.08.2026): «Подключения» → «Коннекторы» → «Почта
            # компании». В «Загрузке» осталась только работа с самими письмами.
            "settings_route": "/connect?mode=connect&sub=connectors",
        })

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
            "brings": "Общий ключ компании: по нему ходят узлы, заведённые до именных "
                      "ключей. Новым потребителям выдавайте именной — его видно поимённо "
                      "и можно отозвать",
            "direction": "in", "status": "active", "enabled": True,
            "last_sync_at": None, "last_error": None, "records": None, "files": 0,
            "initiator": "them",
            # Именные ключи с отзывом живут на «Состоянии» — там же карточка.
            "settings_route": "/connect?mode=connect&sub=connections",
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

    # Настроенные подключения к внешним системам.
    #
    # Журнал синхронизаций (`SourceSync`) здесь раньше читался, но писать его
    # некому: конструктора этой модели нет во всём сервере, а ключи не сходятся по
    # построению — в журнале `catalogs|closed_periods|full`, у источника
    # `sts|onec_dt`. Поэтому «Последний обмен» ВСЕГДА показывал `last_test_at` —
    # момент, когда инженер нажал «Проверить подключение», — выдавая проверку за
    # обмен данными. Проверку показываем отдельным полем и отдельными словами.
    sources = (await db.execute(
        select(Source).where(Source.company_id == company_id).order_by(Source.name)
    )).scalars().all()
    for src in sources:
        items.append(_source_entry(src))

    # ── Классы подключений, которых витрина не знала вовсе ──────────────────
    #
    # Каждый из них живёт своей моделью и своим экраном, поэтому на вопрос «что
    # вообще подключено у компании» список отвечал неполно: у пилота ГИГ мимо него
    # проходили агенты станций и обмен с 1С, а счётчик «Работают: N из M» занижал
    # состав. Владелец записи остаётся прежним — здесь только показать и увести.
    from app.models import (
        Connector, EdgeAgent, MarkingIntegration, MetrikaConnection,
        OneCConnection, SpaceInboundKey,
    )

    # Именные входящие ключи: кто подключён К НАМ. Легаси-ключ компании витрина
    # показывала одной строкой с обещанием «именные ключи: В2» — а они уже сделаны,
    # со своим экраном и отзывом.
    for k in (await db.execute(select(SpaceInboundKey).where(
            SpaceInboundKey.company_id == company_id)
            .order_by(SpaceInboundKey.consumer))).scalars().all():
        revoked = k.revoked_at is not None
        items.append({
            "key": f"core:inbound:{k.id}",
            "app": "core", "app_name": "Ядро",
            "provider": "inbound_key",
            "kind": "Входящий ключ",
            "label": f"{k.consumer} · {k.key_prefix}…",
            "brings": "Внешняя система присылает данные сама, ключом пространства"
                      + (f"; станция {k.station_id}" if k.station_id else ""),
            "direction": "in",
            "status": "off" if revoked else ("active" if k.last_used_at else "configured"),
            "enabled": not revoked,
            "last_sync_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "last_error": "ключ отозван" if revoked else None,
            "records": None, "files": 0,
            "initiator": "them",
            "settings_route": "/connect?mode=connect&sub=connections",
        })

    # Агенты станций: собственный канал данных объекта. «Свежий last_seen» — это
    # «агент на связи», а не «данные идут», поэтому очередь показываем отдельно.
    for a in (await db.execute(select(EdgeAgent).where(
            EdgeAgent.company_id == company_id)
            .order_by(EdgeAgent.station_id))).scalars().all():
        items.append({
            "key": f"core:edge:{a.station_id}",
            "app": "core", "app_name": "Ядро",
            "provider": "edge_agent",
            "kind": "Агент станции",
            "label": f"Станция {a.station_id}" + (f" · версия {a.version}" if a.version else ""),
            "brings": "Смены, продажи и остатки прямо со станции"
                      + (f"; в очереди {a.queue_pending}" if a.queue_pending else ""),
            "direction": "in",
            "status": "active",
            "enabled": True,
            "last_sync_at": a.last_seen.isoformat() if a.last_seen else None,
            "last_error": None,
            "records": a.queue_sent or None, "files": 0,
            "initiator": "them",
            "settings_route": None,
        })

    # Обмен с 1С: отдельная модель со своим экраном подключения.
    for c in (await db.execute(select(OneCConnection).where(
            OneCConnection.company_id == company_id)
            .order_by(OneCConnection.name))).scalars().all():
        items.append({
            "key": f"core:onec:{c.id}",
            "app": "core", "app_name": "Ядро",
            "provider": "onec",
            "kind": "Обмен с 1С",
            "label": c.name,
            "brings": ("Документы и справочники живой базы 1С"
                       + (" (COM)" if c.mode == "com" else " (OData)")),
            "direction": "both",
            "status": "active" if c.status == "active" else (
                "error" if c.status == "error" else "configured"),
            "enabled": c.status != "disabled",
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "last_error": None,
            "records": None, "files": 0,
            "initiator": "us",
            "settings_route": "/1c/connection",
        })

    # Яндекс.Метрика: у модели статус и ошибка ровно в контракте витрины.
    for m in (await db.execute(select(MetrikaConnection).where(
            MetrikaConnection.company_id == company_id))).scalars().all():
        items.append({
            "key": f"core:metrika:{m.id}",
            "app": "core", "app_name": "Ядро",
            "provider": "metrika",
            "kind": "Веб-аналитика",
            "label": m.counter_name or "Яндекс.Метрика",
            "brings": "Посещаемость и источники трафика сайта компании",
            "direction": "in",
            "status": ("error" if m.status == "error" else
                       "active" if m.status == "ok" else "unknown"),
            "enabled": bool(m.enabled),
            "last_sync_at": None,
            "last_error": m.last_error,
            "records": None, "files": 0,
            "initiator": "us",
            "settings_route": "/metrika",
        })

    # Маркировка и фискальные системы: ГИС МТ, ОФД, ЕГАИС, «Меркурий».
    _MARK_LABEL = {"gismt": "Честный знак (ГИС МТ)", "ofd": "ОФД",
                   "nk": "Национальный каталог", "egais": "ЕГАИС",
                   "mercury": "Меркурий", "local_module": "Локальный модуль"}
    for mi in (await db.execute(select(MarkingIntegration).where(
            MarkingIntegration.company_id == company_id)
            .order_by(MarkingIntegration.system))).scalars().all():
        items.append({
            "key": f"core:marking:{mi.id}",
            "app": "core", "app_name": "Ядро",
            "provider": f"marking_{mi.system}",
            "kind": "Маркировка и фискальные",
            "label": _MARK_LABEL.get(mi.system, mi.system),
            "brings": "Обороты маркированного товара и фискальные данные",
            "direction": "both",
            "status": ("off" if not mi.enabled else
                       "active" if mi.last_check_ok else
                       "error" if mi.last_check_ok is False else "configured"),
            "enabled": bool(mi.enabled),
            "last_sync_at": mi.last_check_at.isoformat() if mi.last_check_at else None,
            "last_error": None if mi.last_check_ok is not False else (mi.last_check_note or "проверка не прошла"),
            "records": None, "files": 0,
            "initiator": "us",
            "settings_route": None,
        })

    # Таблица `connectors` — отдельная от каналов модель, ею живут 1С-коннекторы
    # офисного профиля.
    for cn in (await db.execute(select(Connector).where(
            Connector.company_id == company_id).order_by(Connector.name))).scalars().all():
        items.append({
            "key": f"core:connector:{cn.id}",
            "app": "core", "app_name": "Ядро",
            "provider": cn.type,
            "kind": "Коннектор",
            "label": cn.name,
            "brings": cn.url or "",
            "direction": "in",
            "status": ("error" if cn.status == "error" else
                       "off" if cn.status == "disabled" else "active"),
            "enabled": cn.status != "disabled",
            "last_sync_at": cn.last_sync_at.isoformat() if cn.last_sync_at else None,
            "last_error": None,
            "records": cn.records_count or None, "files": 0,
            "initiator": "us",
            "settings_route": "/connect?mode=connect&sub=connectors",
        })

    # Приложения-разрезы: спрашиваем только те, что подключены компании и знают её.
    rows = (await db.execute(
        select(App, AppCompanyLink)
        .join(AppCompanyLink, AppCompanyLink.app_id == App.id)
        .where(AppCompanyLink.company_id == company_id)
    )).all()

    # Приложения опрашиваем разом: последовательный цикл складывал таймауты, и два
    # молчащих приложения плюс мёртвый Matrix держали ответ витрины 15 секунд —
    # всё это время занята сессия БД, а фронт перезапрашивает список раз в минуту.
    problems: list[dict[str, str]] = []
    if rows:
        got = await asyncio.gather(*[
            _app_connectors(a, l, a.code, a.name) for a, l in rows])
        for (app_row, _), (entries, err) in zip(rows, got):
            items.extend(entries)
            if err:
                problems.append({"app": app_row.code, "app_name": app_row.name,
                                 "error": err})

    return {"connectors": items, "problems": problems}


async def fetch_external_work(
    db: AsyncSession, company_id: uuid.UUID, connector_key: str, external_ref: str | None,
) -> dict[str, Any]:
    """Состояние чужой работы у приложения-владельца коннектора.

    Ключ строки витрины — «<приложение>:<коннектор>», поэтому владелец известен из
    самого ключа: второго справочника «кто чей коннектор» здесь не появляется.

    Приложение может такой ручки не отдавать — тогда возвращаем причину, а НЕ
    выдуманный статус. Неверная отметка о чужой работе хуже отсутствующей: по ней
    принимают решения («у них уже сделано»), которых никто не проверял.
    """
    app_code = (connector_key or "").split(":", 1)[0]
    if not app_code or not external_ref:
        return {"ok": False, "reason": "не указан коннектор или номер работы"}
    if app_code in ("ledger", "core"):
        return {"ok": False, "reason": "это канал самого пространства, чужой работы за ним нет"}

    row = (await db.execute(
        select(App, AppCompanyLink)
        .join(AppCompanyLink, AppCompanyLink.app_id == App.id)
        .where(AppCompanyLink.company_id == company_id, App.code == app_code)
    )).first()
    if row is None:
        return {"ok": False, "reason": f"приложение «{app_code}» компании не подключено"}
    app_row, link = row

    token = sso.sign_service_token(aud=app_code, scope="projection")
    if not token:
        return {"ok": False, "reason": "единый вход не настроен (нет ключа подписи)"}

    conn_id = connector_key.split(":", 1)[1] if ":" in connector_key else ""
    url = (f"{_internal_base_url(app_row, app_code)}"
           f"/api/v1/eco/connectors/{conn_id}/work/{external_ref}")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params={"companyId": link.external_company_id},
                                    headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"приложение недоступно: {e}"}

    if resp.status_code == 404:
        # Штатный случай на сегодня: ручки ещё нет. Говорим как есть — человек
        # ведёт номер и статус руками, пока владелец коннектора её не отдаст.
        return {"ok": False, "reason": "приложение не отдаёт состояние чужой работы "
                                       "(ручки нет — состояние ведётся вручную)"}
    if resp.status_code >= 400:
        return {"ok": False, "reason": f"приложение вернуло HTTP {resp.status_code}"}

    data = resp.json() or {}
    return {
        "ok": True,
        "status": data.get("status"),
        "url": data.get("url"),
        "closed": bool(data.get("closed")),
        "stages": data.get("stages") or [],
    }
