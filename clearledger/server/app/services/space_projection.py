"""Проекция общих сущностей пространства в приложения-разрезы (docs/SPACE.md §6).

Приложение ведёт свои таблицы и переписывать его ради первого шага дорого, поэтому Ядро
не заставляет его читать реестр, а САМО отправляет туда карточки: «вот объекты этой
компании». Направление одно — из Ядра в приложение; обратная запись не предусмотрена,
иначе появляется второй мастер и вопрос, чья правда.

Ключ отправки — карта соответствия компаний (`eco_app_company_links`): без пары
«наша компания → его компания» проекция невозможна. Это то, что не даёт в
мультикомпанийном контейнере отправить объекты одной компании в пространство другой.

Транспорт: HTTP-вызов приложения со служебным токеном Ядра (RS256, клейм svc=projection),
который приложение проверяет по тому же JWKS, что и единый вход. Общих секретов нет.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, AppCompanyLink, CompanyRole, ServiceLocation, User, UserCompany
from app.services import space_registry, sso

# Куда приложение принимает проекцию каждой сущности. Пути фиксированы контрактом;
# адрес приложения берётся из реестра, а не из хардкода.
SYNC_PATHS: dict[str, dict[str, str]] = {
    "objects": {"support": "/api/v1/eco/objects/sync"},
    "users": {"support": "/api/v1/eco/users/sync"},
    "organizations": {"support": "/api/v1/eco/organizations/sync"},
    "equipment": {"support": "/api/v1/eco/equipment/sync"},
}
# Как называется массив в теле запроса — по имени сущности.
PAYLOAD_KEYS = {"objects": "objects", "users": "users",
                "organizations": "organizations", "equipment": "equipment"}
DEFAULT_TIMEOUT = 30.0
# Записей в одном запросе к приложению. Ограничение не наше: у приёмника свой предел
# размера тела (Express — 100 КБ по умолчанию), а пространство компании его перерастает.
BATCH_SIZE = 100

# Роль в компании (пространство) → роль в приложении. Задаётся на приложение в реестре
# (`App.config.roleMap`), здесь — разумный дефолт для Координатора: администратор остаётся
# администратором, остальные видят заявки своей компании.
DEFAULT_ROLE_MAP = {"support": {"admin": "admin", "user": "company"}}


logger = logging.getLogger(__name__)


class ProjectionError(RuntimeError):
    pass


async def project(
    db: AsyncSession, company_id: uuid.UUID, app_code: str, entity: str,
) -> dict[str, Any]:
    """Отправить сущность компании в приложение. Идемпотентно — повтор не плодит дубли.

    entity: objects | users | organizations | equipment.
    """
    paths = SYNC_PATHS.get(entity)
    if paths is None:
        raise ProjectionError(f"Неизвестная сущность пространства: {entity}")

    app_row, link, token = await _target(db, company_id, app_code)
    path = paths.get(app_code)
    if not path:
        raise ProjectionError(f"Приложение «{app_code}» не принимает «{entity}»")

    items = await _payload(db, company_id, app_row, app_code, entity)

    url = f"{_internal_base_url(app_row, app_code)}{path}"
    created = updated = 0
    skipped: list[Any] = []
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        # Пачками: у приложения свой предел размера тела (Express по умолчанию 100 КБ),
        # и пространство компании его перерастает — 618 объектов пилота уже давали 413.
        # Приём идемпотентен, поэтому дробление ничего не меняет по смыслу.
        for start in range(0, len(items) or 1, BATCH_SIZE):
            chunk = items[start:start + BATCH_SIZE]
            if not chunk and items:
                break
            body = {"companyId": link.external_company_id, PAYLOAD_KEYS[entity]: chunk}
            # Полный состав передаётся только с последней непустой пачкой объектов.
            # Промежуточные пачки не должны архивировать соседние объекты.
            if entity == "objects" and start + BATCH_SIZE >= len(items) and items:
                body["allIds"] = [str(it.get("id")) for it in items if it.get("id")]
            try:
                resp = await client.post(
                    url, json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as e:
                raise ProjectionError(f"Приложение недоступно: {e}") from e
            if resp.status_code >= 400:
                raise ProjectionError(
                    f"Приложение отклонило проекцию (HTTP {resp.status_code}): "
                    f"{_error_text(resp)}")
            result = resp.json()
            created += result.get("created", 0)
            updated += result.get("updated", 0)
            skipped.extend(result.get("skipped", []))

    return {
        "app": app_code,
        "entity": entity,
        "companyId": str(company_id),
        "sent": len(items),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


async def project_object(
    db: AsyncSession, company_id: uuid.UUID, object_id: uuid.UUID,
    app_code: str = "support",
) -> dict[str, Any]:
    """Отправить в приложение ОДИН объект — сразу после того, как его изменили.

    Проекция целиком запускалась кнопкой администратора, и между заведением
    станции и её появлением в приложении лежал человек, который должен вспомнить.
    Пока сеть меняется редко, это терпимо; как только чаще — расхождение
    обнаруживается заявкой, заведённой не на ту станцию.

    Отправляем один объект, а не весь справочник: правка адреса не повод гонять
    шестьсот карточек. Приём идемпотентен — что для пачки, что для одной строки.

    Ошибку НЕ поднимаем наверх: объект уже сохранён, и падать из-за недоступного
    соседа сохранение не должно. Непрошедшая проекция догоняется следующей
    правкой либо кнопкой «отправить всё» — она для того и осталась.
    """
    row = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.id == object_id,
            ServiceLocation.company_id == company_id),
    )).scalar_one_or_none()
    if row is None:
        return {"skipped": "объект не найден"}

    try:
        app_row, link, token = await _target(db, company_id, app_code)
    except ProjectionError as e:
        # Нет пары компаний или приложение не подключено — это не поломка, а
        # состояние настройки: проекции здесь просто нет.
        return {"skipped": str(e)}

    path = SYNC_PATHS["objects"].get(app_code)
    if not path:
        return {"skipped": f"приложение «{app_code}» не принимает объекты"}

    url = f"{_internal_base_url(app_row, app_code)}{path}"
    body = {"companyId": link.external_company_id,
            "objects": [space_registry.to_card(row)]}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=body,
                                     headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            raise ProjectionError(f"HTTP {resp.status_code}: {_error_text(resp)}")
    except (httpx.HTTPError, ProjectionError) as e:
        logger.warning("Проекция объекта %s в «%s» не прошла: %s", object_id, app_code, e)
        return {"failed": str(e)}
    return {"sent": 1, "app": app_code}


async def project_all(
    db: AsyncSession, company_id: uuid.UUID, app_code: str,
) -> dict[str, Any]:
    """Все общие справочники разом, в порядке зависимостей.

    Объекты идут первыми: оборудование в приложении встаёт на площадку, а площадка
    появляется вместе с объектом. Сущность, которую приложение не принимает, пропускаем —
    это не ошибка настройки, а разный состав разрезов.
    """
    out: dict[str, Any] = {}
    for entity in ("objects", "organizations", "equipment", "users"):
        if app_code not in SYNC_PATHS[entity]:
            continue
        out[entity] = await project(db, company_id, app_code, entity)
    return {"app": app_code, "companyId": str(company_id), "results": out}


async def object_tickets(
    db: AsyncSession, company_id: uuid.UUID, object_id: str, app_code: str = "support",
    limit: int = 20,
) -> dict[str, Any]:
    """Заявки приложения по объекту пространства — для карточки объекта в Учёте.

    Ось — тот же `object_id`, который проекция положила в приложение. Данные не копируем:
    спрашиваем разрез в момент показа, иначе в Ядре завелась бы вторая правда о заявках.
    """
    app_row = (await db.execute(select(App).where(App.code == app_code))).scalar_one_or_none()
    if app_row is None:
        raise ProjectionError(f"Приложение не найдено в реестре: {app_code}")

    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app_row.id,
        AppCompanyLink.company_id == company_id))).scalar_one_or_none()
    if link is None:
        # Соответствие не задано — приложение просто ещё не знает об этой компании.
        return {"app": app_code, "linked": False, "total": 0, "open": 0, "tickets": []}

    token = sso.sign_service_token(aud=app_code, scope="projection",
                                   app_company_id=link.external_company_id)
    if not token:
        raise ProjectionError("Единый вход не настроен (нет ключа подписи)")

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/objects/{object_id}/tickets",
                params={"companyId": link.external_company_id, "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e

    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")

    data = resp.json()
    return {
        "app": app_code,
        "linked": True,
        "total": data.get("total", 0),
        "open": data.get("open", 0),
        # Сводка по всем заявкам объекта: приложение считает её у себя, Ядро
        # только доносит — считать второй раз здесь означало бы завести вторую
        # правду о работах.
        "stats": data.get("stats"),
        "tickets": data.get("tickets", []),
    }


async def match_objects(
    db: AsyncSession, company_id: uuid.UUID, *,
    apply: bool = False, app_code: str = "support",
) -> dict[str, Any]:
    """Связать объекты приложения с объектами пространства.

    Проекция идемпотентна по паре (компания, объект пространства): не нашла —
    создала. Объекты, заведённые в приложении своим импортом (HubEx), этой пары
    не имеют, поэтому синхронизация их не узнаёт и плодит рядом вторые такие же.
    Здесь мы отдаём приложению список своих станций с номерами и заводскими
    номерами, а оно сопоставляет их со своими несвязанными карточками.

    Единый разрез учёта держится именно на этом: объект пространства — мастер, и
    все приложения обязаны ссылаться на него, а не вести свой список станций.
    """
    from app.models import ServiceLocation
    from app.services.station_scope import ВИДЫ_СТАНЦИЙ

    app_row, link, token = await _target(db, company_id, app_code)

    станции = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.type.in_(ВИДЫ_СТАНЦИЙ),
        ServiceLocation.is_test.is_(False)))).scalars().all()
    кандидаты = [
        {
            "ecoObjectId": str(s.id),
            "number": (s.station_number or "").strip() or None,
            "serial": (s.serial_number or s.code or "").strip() or None,
            "name": s.name,
        }
        for s in станции
    ]

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/objects/match",
                json={"companyId": link.external_company_id,
                      "candidates": кандидаты, "apply": apply},
                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e
    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
    return {"app": app_code, "candidates": len(кандидаты), **resp.json()}


async def merge_app_objects(
    db: AsyncSession, company_id: uuid.UUID, pairs: list[dict[str, str]], *,
    apply: bool = False, app_code: str = "support",
) -> dict[str, Any]:
    """Слить дубли карточек объекта в приложении.

    Пара — «карточка-дубль → карточка с осью». История переезжает на ту, что
    связана с объектом пространства: её обновляет синхронизация, и обратное
    направление означало бы, что следующий же проход заведёт третью карточку.
    """
    app_row, link, token = await _target(db, company_id, app_code)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT * 4) as client:
        try:
            resp = await client.post(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/objects/merge",
                json={"companyId": link.external_company_id,
                      "pairs": pairs, "apply": apply},
                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e
    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
    return {"app": app_code, **resp.json()}


async def tickets_analytics(
    db: AsyncSession, company_id: uuid.UUID, *,
    days: int = 90, limit: int = 2000, app_code: str = "support",
) -> dict[str, Any]:
    """Срез заявок приложения: сводка, разрезы и строки.

    Данные не копируем — спрашиваем в момент показа. Разрезы приложения считает
    само (статус, вид, стадия, источник), а марку станции и регион добавит Ядро:
    у заявки их нет и быть не должно.
    """
    app_row, link, token = await _target(db, company_id, app_code)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/tickets/analytics",
                params={"companyId": link.external_company_id,
                        "days": days, "limit": limit},
                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e
    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
    return resp.json()


async def network_open_tickets(
    db: AsyncSession, company_id: uuid.UUID, app_code: str = "support",
) -> dict[str, Any]:
    """По каким станциям работа уже идёт — свёрткой на всю сеть.

    Карточка станции отвечает «что было здесь», списку сети нужен обратный
    вопрос: какая беда видна и никем не взята. На пилоте это 291 молчащая
    станция против 11 с открытой заявкой — без свёртки разрыв просто не виден.
    Спрашивать по одной шестьсот раз нельзя, поэтому приложение считает свёртку
    у себя, а Ядро её доносит.
    """
    app_row, link, token = await _target(db, company_id, app_code)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/objects/open-tickets",
                params={"companyId": link.external_company_id},
                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e
    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
    data = resp.json()
    return {"app": app_code, "objects": data.get("objects", []),
            "total": data.get("total", 0)}


async def ticket_kinds(
    db: AsyncSession, company_id: uuid.UUID, app_code: str = "support",
) -> dict[str, Any]:
    """Виды работ приложения: чем человек называет то, что заводит.

    Без вида заявка уходит «инцидентом» по базовому маршруту — мимо процесса
    «Работы на ЭЗС» и мимо службы, которая эти работы выполняет. Список берём у
    приложения: маршруты заводит оно, и свой перечень в Ядре разошёлся бы с ним
    на первой же правке процесса.
    """
    app_row, link, token = await _target(db, company_id, app_code)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{_internal_base_url(app_row, app_code)}/api/v1/eco/ticket-types",
                params={"companyId": link.external_company_id},
                headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e
    if resp.status_code >= 400:
        raise ProjectionError(
            f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
    return {"app": app_code, "types": resp.json().get("types", [])}


async def create_object_ticket(
    db: AsyncSession, company_id: uuid.UUID, object_id: str, *,
    description: str, title: str | None = None, priority: str = "medium",
    type_code: str | None = None,
    author_email: str | None = None, app_code: str = "support",
) -> dict[str, Any]:
    """Завести заявку по объекту, не выходя из карточки Учёта.

    Граница простая: работа меняет состав или положение станции — это проект; работа
    восстанавливает работоспособность (заменить автомат в щите) — это заявка. Ручка
    существует ровно затем, чтобы вторую не заводили проектом: иначе реестр проектов
    перестаёт быть реестром капвложений.
    """
    app_row, link, token = await _target(db, company_id, app_code)
    url = f"{_internal_base_url(app_row, app_code)}/api/v1/eco/objects/{object_id}/tickets"
    body = {
        "companyId": link.external_company_id,
        "title": title or None,
        "description": description,
        "priority": priority,
        "typeCode": type_code,
        "authorEmail": author_email,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=body,
                                     headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 404:
                # Объект завели ПОСЛЕ последней проекции: приложение о нём не знает, а
                # проекция запускается только руками из Центра управления. Человеку в
                # чате или в карточке объекта с этим ничего не сделать, поэтому досылаем
                # справочник и повторяем один раз. Приём идемпотентен — лишнего не создаст.
                await project(db, company_id, app_code, "objects")
                resp = await client.post(url, json=body,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Приложение недоступно: {e}") from e

    if resp.status_code >= 400:
        raise ProjectionError(
            f"Заявку завести не удалось (HTTP {resp.status_code}): {_error_text(resp)}")
    return {"app": app_code, **resp.json()}


async def _target(
    db: AsyncSession, company_id: uuid.UUID, app_code: str,
) -> tuple[App, AppCompanyLink, str]:
    """Приложение, пара компаний и служебный токен — всё, без чего отправлять нельзя."""
    app_row = (await db.execute(select(App).where(App.code == app_code))).scalar_one_or_none()
    if app_row is None:
        raise ProjectionError(f"Приложение не найдено в реестре: {app_code}")

    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app_row.id,
        AppCompanyLink.company_id == company_id))).scalar_one_or_none()
    if link is None:
        raise ProjectionError(
            "Нет соответствия компаний: задайте, какой компании приложения отвечает эта "
            "компания пространства (Центр управления → Приложения)")

    # Карта компаний прочитана строкой выше — ею и задаётся область действия токена.
    # Раньше она попадала только в тело вызова, а удостоверение не называло никого:
    # один токен работал в контуре любого заказчика приложения (B-11, 21.10.2026).
    token = sso.sign_service_token(aud=app_code, scope="projection",
                                   app_company_id=link.external_company_id)
    if not token:
        raise ProjectionError("Единый вход не настроен (нет ключа подписи) — проекция невозможна")
    return app_row, link, token


async def _payload(
    db: AsyncSession, company_id: uuid.UUID, app_row: App, app_code: str, entity: str,
) -> list[dict[str, Any]]:
    if entity == "objects":
        res = await db.execute(
            select(ServiceLocation).where(ServiceLocation.company_id == company_id)
            .order_by(ServiceLocation.code))
        return [space_registry.to_card(l) for l in res.scalars().all()]
    if entity == "organizations":
        return await space_registry.list_organizations(db, company_id)
    if entity == "equipment":
        return await space_registry.list_equipment(db, company_id)
    if entity == "users":
        return await _users_payload(db, company_id, app_row, app_code)
    raise ProjectionError(f"Неизвестная сущность пространства: {entity}")


async def _users_payload(
    db: AsyncSession, company_id: uuid.UUID, app_row: App, app_code: str,
) -> list[dict[str, Any]]:
    """Люди компании с ролью, переведённой в термины приложения.

    Пароли не передаются: вход в приложение — единым входом Ядра. Роль берётся из
    членства в компании, а не из глобального флага: права в пространстве считаются
    по компании (docs/SPACE.md §2).
    """
    cfg = app_row.config or {}
    role_map = cfg.get("roleMap") or DEFAULT_ROLE_MAP.get(app_code, {})
    default_role = cfg.get("defaultRole") or role_map.get("user") or "customer"

    rows = (await db.execute(
        select(User, UserCompany, CompanyRole)
        .join(UserCompany, UserCompany.user_id == User.id)
        .outerjoin(CompanyRole, CompanyRole.id == UserCompany.role_id)
        .where(UserCompany.company_id == company_id)
        .order_by(User.email)
    )).all()

    out: list[dict[str, Any]] = []
    for user, membership, access_role in rows:
        space_role = "admin" if (user.is_superadmin or membership.role == "admin") else membership.role
        # Названная роль в приложении бьёт карту: карта знает только «админ и
        # остальные», а в службе поддержки разработчик и оператор — разные люди
        # с разными рабочими местами. Не названа — считаем по карте, как раньше.
        #
        # Порядок: сначала личное исключение в членстве, затем роль доступа (её
        # носят все операторы смены разом), и только потом карта.
        named = ((membership.app_roles or {}).get(app_code)
                 or (getattr(access_role, "app_roles", None) or {}).get(app_code))
        out.append({
            "ecoUserId": str(user.id),
            "email": user.email,
            "name": user.name or user.email,
            "role": named or role_map.get(space_role, default_role),
            "spaceRole": space_role,
            "isActive": True,
        })
    return out


def _internal_base_url(app_row: App, app_code: str) -> str:
    """Адрес приложения ВНУТРИ стека.

    Наружный адрес (`https://<domain>/support`) для машинного вызова не годится: запрос
    ушёл бы из контейнера в интернет и вернулся через кромку. Поэтому используем
    внутреннее имя сервиса, если оно задано в конфигурации приложения реестра.
    """
    cfg = app_row.config or {}
    internal = cfg.get("internalUrl") or cfg.get("internal_url")
    if internal:
        return str(internal).rstrip("/")
    # Соглашение стека: имя docker-сервиса совпадает с кодом приложения.
    default_ports = {"support": 3003}
    port = default_ports.get(app_code)
    return f"http://{app_code}:{port}" if port else f"http://{app_code}"


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error") or data.get("detail") or data)[:300]
    except Exception:
        return resp.text[:300]


async def monitoring_tickets(db, company_id, *, object_ids, days=90, as_of=None):
    app_row, link, token = await _target(db, company_id, "support")
    rows = []
    offset = 0
    cutoff = as_of.isoformat() if as_of else None
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        while True:
            try:
                resp = await client.post(
                    f"{_internal_base_url(app_row, 'support')}/api/v1/eco/tickets/monitoring",
                    json={"companyId": link.external_company_id, "objectIds": object_ids,
                          "days": days, "asOf": cutoff, "offset": offset},
                    headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as e:
                raise ProjectionError(f"Приложение недоступно: {e}") from e
            if resp.status_code >= 400:
                raise ProjectionError(f"Приложение вернуло ошибку (HTTP {resp.status_code}): {_error_text(resp)}")
            data = resp.json()
            rows.extend(data["rows"])
            if data.get("nextOffset") is None:
                return {**data, "rows": rows}
            offset = data["nextOffset"]
