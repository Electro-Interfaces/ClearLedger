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

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Request,
    status as http_status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import (
    App, AppCompanyLink, ApprovalRequest, Company, DocAcquaint, DocCard,
    SpaceConnection, Task,
)
from app.services import inbound_events, raw_intake, space_connection_registry

router = APIRouter(prefix="/eco", tags=["Экосистема: события приложений"])


@router.post("/events")
async def accept_event(
    request: Request,
    background: BackgroundTasks,
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
    # Разбор остаётся отдельным от приёма — но начинается сразу, а не через тик
    # регламента: просьбу, заведённую человеком из карточки заявки, ждут глядя в
    # экран. Неудача фона ничего не рушит, регламент подберёт непрочитанное.
    if outcome == "accepted":
        background.add_task(inbound_events.process_soon)
    return {"status": outcome, "note": note}


# Состояния предметов «Трека» словами, а не кодами: витрину читает человек в
# карточке заявки, и «Ждём виз» ему говорит больше, чем `pending`.
_DOC_STATE = {
    "draft": "Черновик", "registered": "Зарегистрирован", "in_force": "Действует",
    "executed": "Исполнен", "archived": "В архиве", "cancelled": "Отменён",
}
_TASK_STATE = {"open": "В работе", "done": "Выполнено", "cancelled": "Отменено"}
_KIND_NAME = {
    "approval": "Согласование", "document": "Документ",
    "errand": "Поручение", "acquaint": "Ознакомление",
}


@router.get("/process/{process_id}/work")
async def process_work(
    process_id: str,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что «Трек» завёл по этому процессу и в каком оно состоянии.

    Обратная сторона просьбы. До сих пор в заявку возвращался один глагол:
    процесс двигался, а что именно завелось — номер поручения, чья виза
    задерживает, кто ещё не ознакомился — в Поддержке видно не было. Человек
    спрашивал об этом голосом, потому что спросить систему было нечем.

    Витрина только читает и ничего не решает: право показать её людям —
    у Поддержки, она знает, кто смотрит на заявку.
    """
    rows = (await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.company_id == company.id,
               ApprovalRequest.process_id == str(process_id)[:64])
        .order_by(ApprovalRequest.created_at)
    )).scalars().all()
    if not rows:
        return {"process_id": process_id, "items": []}

    from app.config import get_settings

    base = get_settings().app_public_url.rstrip("/")
    doc_ids = {row.doc_id for row in rows if row.doc_id}
    task_ids = {row.task_id for row in rows if row.task_id}
    docs = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.id.in_(doc_ids)))).scalars().all()} if doc_ids else {}
    tasks = {t.id: t for t in (await db.execute(select(Task).where(
        Task.id.in_(task_ids)))).scalars().all()} if task_ids else {}

    # Лист ознакомления считаем одним запросом на все документы просьбы: по
    # одному на строку витрина стоила бы столько же, сколько сама заявка.
    sheets: dict[uuid.UUID, dict[str, int]] = {}
    if any(row.kind == "acquaint" for row in rows):
        from sqlalchemy import func

        counted = (await db.execute(
            select(DocAcquaint.doc_id, DocAcquaint.status,
                   func.count(DocAcquaint.id))
            .where(DocAcquaint.doc_id.in_(doc_ids))
            .group_by(DocAcquaint.doc_id, DocAcquaint.status))).all()
        for doc_id, state, count in counted:
            entry = sheets.setdefault(doc_id, {"done": 0, "total": 0})
            entry["total"] += int(count)
            if state == "done":
                entry["done"] += int(count)

    items = []
    for row in rows:
        item: dict[str, Any] = {
            "id": str(row.id),
            "kind": row.kind,
            "kind_name": _KIND_NAME.get(row.kind, row.kind),
            "requested_at": row.created_at.isoformat() if row.created_at else None,
            "outcome": row.outcome,
            "waits": bool(row.on_approved) and row.outcome is None,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        }
        doc = docs.get(row.doc_id) if row.doc_id else None
        task = tasks.get(row.task_id) if row.task_id else None
        if doc is not None:
            item.update({
                "subject": "document",
                "number": doc.reg_number or None,
                "title": doc.title,
                "state": _DOC_STATE.get(doc.status, doc.status),
                "url": f"{base}/docs?view=all&doc={doc.id}",
            })
            if row.kind == "acquaint":
                sheet = sheets.get(doc.id, {"done": 0, "total": row.round})
                item["state"] = f"Ознакомились {sheet['done']} из {sheet['total']}"
        elif task is not None:
            item.update({
                "subject": "task",
                "number": f"№{task.number}",
                "title": task.title,
                "state": _TASK_STATE.get(task.status, task.status),
                "url": f"{base}/docs/company?view=errands&task={task.id}",
            })
        else:
            # Предмет исчез (документ удалён, компания пересобрана) — строку
            # всё равно показываем: сам факт просьбы это история процесса.
            item.update({"subject": None, "title": "Предмет недоступен",
                         "state": None, "url": None})
        items.append(item)
    return {"process_id": process_id, "items": items}

@router.get("/track/templates")
async def track_templates(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Заготовки «Трека», по которым можно попросить работу.

    Нужны затем, чтобы менеджер в Поддержке выбирал заготовку списком, а не
    вспоминал её название по памяти: просьба ссылается на заготовку именно
    именем, и опечатка означала бы `skipped` вместо работы.

    Список не сужается по человеку: кто из менеджеров вправе заводить работу,
    решает Поддержка — она знает, кто смотрит на заявку. Здесь же выполняет
    просьбу служебный «Процесс», и пользовательских прав у неё нет.
    """
    from app.models import DocKind, TaskTemplate

    templates = list((await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == company.id).order_by(
            TaskTemplate.name))).scalars().all())
    kind_ids = {tpl.doc_kind_id for tpl in templates if tpl.doc_kind_id}
    kinds = {k.id: k for k in (await db.execute(select(DocKind).where(
        DocKind.id.in_(kind_ids)))).scalars().all()} if kind_ids else {}
    items = []
    for tpl in templates:
        kind = kinds.get(tpl.doc_kind_id) if tpl.doc_kind_id else None
        if tpl.doc_kind_id and (kind is None or not kind.is_active):
            continue
        items.append({
            "id": str(tpl.id), "name": tpl.name,
            "kind": "document" if tpl.doc_kind_id else "errand",
            "kind_name": kind.name if kind is not None else None,
        })
    return {"templates": items}

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
