"""Приём событий от приложений пространства: /api/eco/events.

Обратный канал к тому, что уже есть в прямую сторону. Ядро ходит в приложения
служебным токеном, приложения к Ядру — ключом интеграции (`X-Cloud-API-Key`), тем
же, которым к нам стучится почтовый мост.

Ручка намеренно тупая: приняли, записали, ответили. Разбор — фоновым проходом,
потому что отправитель ретраит по коду ответа, и наша внутренняя ошибка не должна
превращаться в бесконечную повторную доставку.
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import App, AppCompanyLink, Company, SpaceConnection
from app.services import inbound_events, raw_intake, space_connection_registry

router = APIRouter(prefix="/eco", tags=["Экосистема: события приложений"])


@router.post("/events")
async def accept_event(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять одно событие приложения.

    Ответы: `accepted` — приняли, `duplicate` — уже было (тоже успех: повторная
    доставка штатна), `rejected` — событию нечем себя опознать. Ретраить имеет
    смысл только на 5xx, и именно поэтому дубль не считается ошибкой.
    """
    event = await request.json()
    provider = str(event.get("source") or request.headers.get("X-Eco-App") or "support")
    outcome, note = await inbound_events.accept(db, provider, event, company.id)
    return {"status": outcome, "note": note}


@router.put("/connections")
async def report_connections(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять доклад приложения о его подключениях.

    Доклад целиком, а не по одному: приложение знает свой список подключений
    полностью, и присылать разницу означало бы держать у себя вторую копию
    того, что мы и так храним.

    Удостоверение то же, что у событий: приложение им уже пользуется, а
    отдельный способ представиться ради учётной записи завёл бы третий.

    Компанию берём иначе, чем у событий, и это существенно. Событие приходит по
    одному, и компания ключа для него верна. Доклад же приходит СРАЗУ ЗА
    НЕСКОЛЬКО компаний: приложение мультикомпанийно, а ключ интеграции у него
    один. Приписать весь доклад компании ключа значило бы сложить подключения
    разных компаний в одну — ровно то нарушение изоляции, ради которого заведена
    карта пар. Поэтому компания каждой строки определяется по
    `companyId` приложения через `AppCompanyLink`; ключ отвечает только за то,
    что докладчику вообще можно верить.
    """
    body = await request.json()
    app_code = str(body.get("app") or request.headers.get("X-Eco-App") or "").strip()
    if not app_code:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                            "Не указано приложение (app)")
    items = body.get("connections")
    if not isinstance(items, list):
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                            "Ожидается список connections")

    app_row = (await db.execute(select(App).where(
        App.code == app_code[:40]))).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND,
                            f"Приложение не найдено в реестре: {app_code}")
    links = {
        str(link.external_company_id): link.company_id
        for link in (await db.execute(select(AppCompanyLink).where(
            AppCompanyLink.app_id == app_row.id))).scalars().all()
    }

    # Строки без пары компаний не теряем молча: докладчик должен узнать, что
    # часть его подключений не принята и почему — иначе витрина будет неполной,
    # а причина невидимой.
    by_company: dict[Any, list[dict[str, Any]]] = {}
    unmapped: set[str] = set()
    for item in items:
        external = str(item.get("companyId") or item.get("company_id") or "").strip()
        target = links.get(external) if external else company.id
        if target is None:
            unmapped.add(external)
            continue
        by_company.setdefault(target, []).append(item)

    total = {"created": 0, "updated": 0}
    for company_id, rows in by_company.items():
        result = await space_connection_registry.report(
            db, company_id, app_code[:40], rows)
        total["created"] += result["created"]
        total["updated"] += result["updated"]
    await db.commit()
    out: dict[str, Any] = {"status": "ok", **total}
    if unmapped:
        out["unmapped_companies"] = sorted(unmapped)
        out["note"] = ("Для этих компаний приложения не задано соответствие "
                       "компании пространства (Центр управления → Приложения)")
    return out


@router.post("/raw")
async def accept_raw_batch(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять сырой пакет от приложения — то, что отдала внешняя система.

    Отдельная ручка, а не событие. Событие несёт ФАКТ и мало весит: «канал привёз
    N записей». Здесь приезжают сами записи, и мерить их тем же приёмником нельзя
    — у него другой размер тела и другая судьба: событие разбирается фоновым
    проходом, а пакет просто ложится и ждёт того, кто его разберёт.

    Смысл слоя не в архиве, а в возможности повторить разбор, не ходя к источнику
    заново. Для внешних систем, где повторный заход стоит дорого или невозможен
    (сессия 1С, лимит запросов ВАТС, перепроведённые документы), это единственный
    способ починить нормализацию задним числом.

    Пакет привязывается к подключению — учётной записи из реестра. Она же
    отвечает на вопрос, чей это пакет: компания берётся из неё, а не из тела,
    ровно по той же причине, по какой ей не верят при приёме событий.

    Подключение можно назвать двумя способами, и второй — основной. Наш
    идентификатор (`connectionId`) знает лишь тот, кто читал реестр; приложение
    же знает СВОЙ (`connectorId`) и код своего приложения. Требовать от него наш
    значило бы заставить каждое приложение сперва вычитать реестр и держать у
    себя карту соответствий — вторую копию того, что мы и так храним.
    """
    body = await request.json()
    connection = None
    connection_id = str(body.get("connectionId") or body.get("connection_id") or "").strip()
    if connection_id:
        try:
            ident = uuid.UUID(connection_id)
        except (ValueError, TypeError):
            raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                                "Неверный connectionId")
        connection = await db.get(SpaceConnection, ident)
    else:
        app_code = str(body.get("app") or request.headers.get("X-Eco-App") or "").strip()
        external_id = str(body.get("connectorId") or body.get("connector_id") or "").strip()
        if not app_code or not external_id:
            raise HTTPException(
                http_status.HTTP_400_BAD_REQUEST,
                "Укажите подключение: connectionId либо пару app + connectorId")
        connection = (await db.execute(select(SpaceConnection).where(
            SpaceConnection.app_code == app_code[:40],
            SpaceConnection.external_id == external_id[:120]))).scalars().first()
    if connection is None:
        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND,
            "Подключение не найдено в реестре: сначала доложите о нём "
            "(PUT /api/eco/connections)")

    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                            "Ожидается список items")
    doc_type = str(body.get("docType") or body.get("doc_type") or "").strip()
    if not doc_type:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                            "Не указан вид пакета (docType)")

    batch_id = await raw_intake.save_raw_batch(
        db, company_id=connection.company_id, connection_id=connection.id,
        doc_type=doc_type[:100], items=items,
        since=body.get("since"), until=body.get("until"),
        meta={"app": connection.app_code, "provider": connection.provider})
    if batch_id is None:
        # Слой сырого никогда не роняет отправителя: не легло — потеря удобства,
        # а не работы. Но и врать «принято» нельзя, иначе на той стороне решат,
        # что разбор можно будет повторить.
        return {"status": "skipped", "note": "пакет не сохранён, подробности в журнале"}
    return {"status": "accepted", "batchId": str(batch_id)}
