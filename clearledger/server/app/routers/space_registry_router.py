"""ElsyPlus Core — API реестра объектов пространства (docs/SPACE.md §5).

Канонический адрес общей сущности: `/api/registry/objects`. Читать может любой член
компании (объекты нужны всем разрезам), править — только администратор компании или
суперадмин: ведение реестра — админская функция, её место в Центре управления.

Компания в запросе ОБЯЗАТЕЛЬНА. Реестр без компании не имеет смысла: в контейнере может
быть несколько пространств, и «отдать всё» означало бы смешать их (docs/SPACE.md §2).
Прикладной CRUD Ledger (`/api/locations`) продолжает работать над той же таблицей —
реестр не дублирует данные, он задаёт общий контракт.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import App, AppCompanyLink, Company, User, UserCompany
from app.services import space_map as space_map_service
from app.services import (
    managed_connectors, space_connection_registry, space_connectors, space_data_model, space_desk,
    space_links, space_projection, space_registry,
)
from app.services.data_quality import data_quality
from app.services.ezs_reference_link import link_references

router = APIRouter(prefix="/registry", tags=["ElsyPlus Core — реестр объектов"])


class ObjectIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    type: str = "other"
    status: str = "active"
    address: str | None = None
    description: str | None = None
    city: str | None = None
    street: str | None = None
    house: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class ObjectPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = None
    status: str | None = None
    address: str | None = None
    description: str | None = None
    city: str | None = None
    street: str | None = None
    house: str | None = None
    latitude: float | None = None
    longitude: float | None = None


async def _member(company_id: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Чтение реестра: членство в компании (суперадмин — всюду)."""
    return await assert_company_member(company_id, user, db)


async def _admin(company_id: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Правки реестра: администратор компании или суперадмин."""
    cid = await assert_company_member(company_id, user, db)
    if user.is_superadmin:
        return cid
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора компании")
    return cid


def _validate(type_: str | None, status_: str | None) -> None:
    if type_ is not None and type_ not in space_registry.OBJECT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Неизвестный тип объекта: {type_}")
    if status_ is not None and status_ not in space_registry.OBJECT_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Неизвестный статус объекта: {status_}")


@router.get("/objects")
async def list_objects(
    company_id: str = Query(..., description="компания пространства (UUID или slug)"),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    q: str | None = Query(None, description="поиск по коду и наименованию"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Объекты компании — паспорта пространства (без прикладных атрибутов разрезов)."""
    cid = await _member(company_id, user, db)
    objects = await space_registry.list_objects(
        db, cid, status=status_filter, type_=type_filter, query=q)
    return {"companyId": str(cid), "objects": objects, "total": len(objects)}


@router.get("/objects/{object_id}")
async def get_object(
    object_id: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await _member(company_id, user, db)
    card = await space_registry.get_object(db, cid, object_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден в этой компании")
    return card


@router.post("/objects", status_code=status.HTTP_201_CREATED)
async def create_object(
    payload: ObjectIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await _admin(company_id, user, db)
    _validate(payload.type, payload.status)
    if await space_registry.code_taken(db, cid, payload.code.strip()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Код «{payload.code}» уже занят в этой компании")
    return await space_registry.create_object(
        db, cid, payload.model_dump(exclude_none=True), actor=user)


@router.get("/objects/{object_id}/impact")
async def object_impact(
    object_id: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Что потянет за собой вывод объекта из эксплуатации.

    Состав объектов приложений задаёт этот реестр: чего здесь нет, того нет и у
    них. Значит снятие станции с эксплуатации закрывает и работу по ней — и
    человек обязан увидеть, сколько именно работы, до того как нажмёт.
    """
    cid = await _member(company_id, user, db)
    return await _impact(db, cid, object_id)


async def _impact(db: AsyncSession, cid: uuid.UUID, object_id: str) -> dict:
    # Приложение может быть не подключено или лежать — это не повод запретить
    # правку реестра, но повод честно сказать, что последствия неизвестны.
    try:
        res = await space_projection.object_tickets(db, cid, object_id, "support")
        return {"support": {"known": True, "total": res.get("total", 0),
                            "open": res.get("open", 0), "tickets": res.get("tickets", [])}}
    except space_projection.ProjectionError as e:
        return {"support": {"known": False, "reason": str(e)}}


@router.patch("/objects/{object_id}")
async def patch_object(
    object_id: str,
    payload: ObjectPatch,
    company_id: str = Query(...),
    confirm: bool = Query(False, description="согласие на вывод объекта из эксплуатации"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await _admin(company_id, user, db)
    _validate(payload.type, payload.status)
    data = payload.model_dump(exclude_none=True)

    # Вывод из эксплуатации — не рядовая правка поля. Объект уходит из состава
    # приложений, и открытая по нему работа уходит вместе с ним. Без явного
    # подтверждения такой переход не проводим и возвращаем, что именно закроется.
    if data.get("status") and data["status"] != "active":
        current = await space_registry.get_object(db, cid, object_id)
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден в этой компании")
        if current.get("status") == "active" and not confirm:
            impact = await _impact(db, cid, object_id)
            support = impact.get("support", {})
            raise HTTPException(status.HTTP_409_CONFLICT, detail={
                "code": "object_leaves_operation",
                "message": (
                    f"Объект уходит из эксплуатации в состояние «{data['status']}». "
                    "Он пропадёт из состава объектов приложений."
                ),
                "willArchive": support,
                "hint": "Повторите запрос с confirm=true, если это и требуется.",
            })
    if "code" in data and await space_registry.code_taken(
            db, cid, data["code"].strip(), except_id=object_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Код «{data['code']}» уже занят в этой компании")
    card = await space_registry.update_object(db, cid, object_id, data, actor=user)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден в этой компании")
    return card


@router.post("/project/{entity}")
async def project_entity(
    entity: str,
    company_id: str = Query(...),
    app: str = Query("support", description="код приложения-получателя"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Отправить общую сущность компании в приложение-разрез (docs/SPACE.md §6).

    entity: objects | organizations | equipment | users | all. Идемпотентно: повтор
    обновляет карточки, а не плодит дубли. Требует заданного соответствия компаний —
    без него неясно, в чьё пространство отправлять.
    """
    cid = await _admin(company_id, user, db)
    try:
        if entity == "all":
            return await space_projection.project_all(db, cid, app)
        return await space_projection.project(db, cid, app, entity)
    except space_projection.ProjectionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.get("/space-map")
async def space_map(
    company_id: str | None = Query(None, description="одна компания; без него — все доступные"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Карта пространства: кто здесь, куда допущен, кто активен, что происходило.

    Суперадмин без `company_id` видит весь контейнер (все пространства), админ компании —
    только свою. Только чтение: карта нужна для анализа, а не для правок.
    """
    if company_id:
        cids = [await _admin(company_id, user, db)]
    elif user.is_superadmin:
        cids = list((await db.execute(select(Company.id).order_by(Company.name))).scalars().all())
    else:
        rows = (await db.execute(select(UserCompany.company_id).where(
            UserCompany.user_id == user.id, UserCompany.role == "admin"))).scalars().all()
        if not rows:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора компании")
        cids = list(rows)
    return await space_map_service.space_map(db, cids)


@router.get("/desk")
async def desk(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Показатели продуктов для рабочего стола: что живёт за каждой плиткой.

    Читает любой член компании — стол видят все, и цифры те же, что человек и так
    увидит внутри продукта; какие плитки ему показать, решает каталог `/api/sso/apps`.
    """
    cid = await _member(company_id, user, db)
    return await space_desk.desk_summary(db, cid)


@router.get("/organizations")
async def list_organizations(
    company_id: str = Query(...),
    q: str | None = Query(None, description="поиск по названию и ИНН"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Организации компании — общие карточки юрлиц (реквизиты без прикладных ролей)."""
    cid = await _member(company_id, user, db)
    orgs = await space_registry.list_organizations(db, cid, query=q)
    return {"companyId": str(cid), "organizations": orgs, "total": len(orgs)}


@router.get("/contracts")
async def list_space_contracts(
    company_id: str = Query(...),
    q: str | None = Query(None, description="поиск по номеру и типу договора"),
    direction: str | None = Query(None, description="in — платит компания, out — платят ей"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Договоры компании — общий взгляд пространства: кто, о чём, на какие объекты."""
    cid = await _member(company_id, user, db)
    items = await space_registry.list_contracts(db, cid, query=q, direction=direction)
    return {"companyId": str(cid), "contracts": items, "total": len(items)}


@router.get("/data-model")
async def data_model(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Состав нормализованной базы пространства: сущности, объёмы, незакрытые связи."""
    cid = await _member(company_id, user, db)
    data = await space_data_model.data_model(db, cid)
    return {"companyId": str(cid), **data}


@router.get("/data-quality")
async def data_quality_report(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Качество данных пространства: именованные проверки с числом и подсказкой.

    Отвечает на вопрос «что сейчас не в порядке и что с этим делать». Часть
    проверок никогда не станет нулём (например, платежи за период, за который
    сессий у нас нет вовсе) — у каждой указано, сколько считается нормой."""
    cid = await _member(company_id, user, db)
    data = await data_quality(db, cid)
    return {"companyId": str(cid), **data}


@router.post("/link-counterparties")
async def link_counterparties(
    company_id: str = Query(...),
    apply: bool = Query(False, description="false — только отчёт, в базу ничего не пишем"),
    only: str | None = Query(None, description="ключи ролей через запятую; пусто — все"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Свести текстовые роли (собственник, подрядчик, поставщик) с карточками контрагентов.

    Пишет только при apply=true и только администратору: операция заводит карточки в
    общем справочнике пространства, её последствия видят все продукты. Отчёт всегда
    полный — `only` ограничивает запись, а не подсчёт.
    """
    cid = await (_admin if apply else _member)(company_id, user, db)
    keys = {k.strip() for k in only.split(",") if k.strip()} if only else None
    data = await space_links.link_counterparties(db, cid, apply=apply, only=keys)
    return {"companyId": str(cid), **data}


@router.post("/link-ezs-references")
async def link_ezs_references(
    company_id: str = Query(...),
    apply: bool = Query(False, description="false — только отчёт, в базу ничего не пишем"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Связать станции с брендами и группами витрины АСУиМ.

    В выгрузке станций колонки `id_бренда` и `id_группы` пусты во всех строках,
    поэтому связь восстанавливается по содержимому: бренд — по названию без
    страны и регистра, группа — по владельцу, адресу или паре «регион + класс
    размещения». Группа применяется только если число станций совпало с тем,
    которое сама витрина указала для этой группы; в отчёт попадает и то, что не
    подтвердилось, — там связь остаётся незакрытой сознательно.
    """
    cid = await (_admin if apply else _member)(company_id, user, db)
    data = await link_references(db, cid, apply=apply)
    return {"companyId": str(cid), **data}


@router.get("/connectors")
async def list_space_connectors(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Подключения пространства: откуда компания получает данные.

    Файловые каналы Учёта + платформенные сервисы + живые интеграции приложений
    (Координатор спрашивается служебным каналом). Поддерживаемые провайдеры
    настраиваются здесь через API владельца; он хранит настройки и выполняет обмен.
    """
    cid = await _member(company_id, user, db)
    data = await space_connectors.list_connectors(db, cid)
    return {"companyId": str(cid), **data, "total": len(data["connectors"])}


@router.get("/connectors/catalog")
async def connector_catalog(company_id: str = Query(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    cid = await _admin(company_id, user, db)
    return await managed_connectors.catalog(db, cid, user.id)


@router.get("/connectors/managed/{app_code}/{connector_id}")
async def managed_connector_get(app_code: str, connector_id: uuid.UUID, company_id: str = Query(...),
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    cid = await _admin(company_id, user, db)
    return await managed_connectors.owner_request(db, cid, user.id, app_code, "GET", f"/{connector_id}")


@router.post("/connectors/managed/{app_code}")
async def managed_connector_create(app_code: str, body: dict = Body(...), company_id: str = Query(...),
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    cid = await _admin(company_id, user, db)
    return await managed_connectors.owner_request(db, cid, user.id, app_code, "POST", "", body)


@router.patch("/connectors/managed/{app_code}/{connector_id}")
async def managed_connector_update(app_code: str, connector_id: uuid.UUID, body: dict = Body(...), company_id: str = Query(...),
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    cid = await _admin(company_id, user, db)
    return await managed_connectors.owner_request(db, cid, user.id, app_code, "PATCH", f"/{connector_id}", body)


@router.post("/connectors/managed/{app_code}/{connector_id}/actions/{action}")
async def managed_connector_action(app_code: str, connector_id: uuid.UUID, action: str, company_id: str = Query(...),
                                   body: dict = Body(default={}),
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    cid = await _admin(company_id, user, db)
    if action not in {"test", "sync", "directory", "bind-operator"}:
        raise HTTPException(404, "Действие не поддерживается")
    return await managed_connectors.owner_request(db, cid, user.id, app_code, "POST", f"/{connector_id}/actions/{action}", body)


@router.get("/connections")
async def list_space_connections(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Учёт подключений компании — из реестра, а не опросом приложений.

    Отличие от `/connectors` существенное. Та витрина собирается в момент показа:
    ходит в приложения служебным каналом и склеивает ответы. Приложение молчит —
    подключений «нет»; интеграция настроена переменными окружения и приложение о
    ней не рассказывает — её не видно вовсе.

    Здесь читается то, о чём владельцы доложили сами. Запись, о которой давно не
    сообщали, помечена `stale`: её состояние давнее, но она не исчезает с экрана,
    потому что молчание приложения — это не «подключения больше нет».

    Обе витрины пока живут рядом: старая остаётся, пока приложения не начнут
    докладывать; переключать её, не имея данных, значило бы оставить
    администратора с пустым экраном.
    """
    cid = await _member(company_id, user, db)
    data = await space_connection_registry.listing(db, cid)
    return {"companyId": str(cid), **data}


@router.get("/equipment")
async def list_equipment(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Единицы оборудования компании — паспорт (что за железо и где стоит)."""
    cid = await _member(company_id, user, db)
    units = await space_registry.list_equipment(db, cid)
    return {"companyId": str(cid), "equipment": units, "total": len(units)}


@router.get("/objects/{object_id}/tickets")
async def object_tickets(
    object_id: str,
    company_id: str = Query(...),
    app: str = Query("support"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Заявки приложения по этому объекту — сводка для карточки объекта в Учёте.

    Читает любой член компании: видеть, что по объекту происходит в соседнем разрезе, —
    рабочая потребность, а не админская.
    """
    cid = await _member(company_id, user, db)
    if await space_registry.get_object(db, cid, object_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден в этой компании")
    try:
        return await space_projection.object_tickets(db, cid, object_id, app, limit)
    except space_projection.ProjectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e


class ObjectTicketIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)
    title: str | None = Field(default=None, max_length=300)
    priority: str = "medium"


@router.post("/objects/{object_id}/tickets", status_code=status.HTTP_201_CREATED)
async def create_object_ticket(
    object_id: str,
    body: ObjectTicketIn,
    company_id: str = Query(...),
    app: str = Query("support"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Завести заявку по объекту прямо из карточки — не заводя проект.

    Автором в приложении встаёт тот же человек: люди пространства уже спроецированы,
    сопоставление идёт по почте. Заводит любой член компании — как и в самом разрезе
    поддержки, где заявку подаёт заказчик, а не администратор.
    """
    cid = await _member(company_id, user, db)
    if await space_registry.get_object(db, cid, object_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден в этой компании")
    try:
        return await space_projection.create_object_ticket(
            db, cid, object_id,
            description=body.description, title=body.title, priority=body.priority,
            author_email=user.email, app_code=app,
        )
    except space_projection.ProjectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e


@router.get("/object-types")
async def object_types(user: User = Depends(get_current_user)) -> dict:
    """Словари для форм Центра управления."""
    return {
        "types": sorted(space_registry.OBJECT_TYPES),
        "statuses": sorted(space_registry.OBJECT_STATUSES),
    }


# ── Карта соответствия компаний (docs/SPACE.md §6) ──────────────────────────────
# Проекция общих сущностей в приложение возможна только по паре «наша компания —
# его компания». Ведение карты — суперадмин: это уровень контейнера.
@router.get("/company-links")
async def list_links(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права суперадминистратора экосистемы")
    return {"links": await _links(db)}


async def _links(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(
        select(AppCompanyLink, App, Company)
        .join(App, App.id == AppCompanyLink.app_id)
        .join(Company, Company.id == AppCompanyLink.company_id)
        .order_by(App.code, Company.name)
    )).all()
    return [{
        "id": str(link.id),
        "appCode": app.code,
        "appName": app.name,
        "companyId": str(company.id),
        "companyName": company.name,
        "externalCompanyId": link.external_company_id,
        "externalCode": link.external_code,
    } for link, app, company in rows]


@router.put("/company-links")
async def put_link(
    app_code: str = Body(..., embed=True, alias="appCode"),
    company_id: str = Body(..., embed=True, alias="companyId"),
    external_company_id: str = Body(..., embed=True, alias="externalCompanyId"),
    external_code: str | None = Body(None, embed=True, alias="externalCode"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Задать/обновить соответствие компании пространства и компании в приложении."""
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права суперадминистратора экосистемы")

    app_row = (await db.execute(select(App).where(App.code == app_code))).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Приложение не найдено: {app_code}")
    cid = await assert_company_member(company_id, user, db)

    link = (await db.execute(select(AppCompanyLink).where(
        AppCompanyLink.app_id == app_row.id, AppCompanyLink.company_id == cid))).scalar_one_or_none()
    if link is None:
        link = AppCompanyLink(app_id=app_row.id, company_id=cid,
                              external_company_id=external_company_id, external_code=external_code)
        db.add(link)
    else:
        link.external_company_id = external_company_id
        link.external_code = external_code
    await db.commit()
    return {"ok": True, "appCode": app_code, "companyId": str(cid),
            "externalCompanyId": external_company_id}
