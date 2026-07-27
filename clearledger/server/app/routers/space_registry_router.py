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
from app.services import space_connectors, space_data_model, space_projection, space_registry

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


@router.patch("/objects/{object_id}")
async def patch_object(
    object_id: str,
    payload: ObjectPatch,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await _admin(company_id, user, db)
    _validate(payload.type, payload.status)
    data = payload.model_dump(exclude_none=True)
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


@router.get("/connectors")
async def list_space_connectors(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    """Подключения пространства: откуда компания получает данные.

    Файловые каналы Учёта + платформенные сервисы + живые интеграции приложений
    (Координатор спрашивается служебным каналом). Витрина: настройка остаётся
    в приложении-владельце, здесь только видно, что где подключено.
    """
    cid = await _member(company_id, user, db)
    data = await space_connectors.list_connectors(db, cid)
    return {"companyId": str(cid), **data, "total": len(data["connectors"])}


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
