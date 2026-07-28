"""Жизненный цикл проектов на площадке и объекте сети.

Три сущности (решение 28.07.2026): **площадка** — место, живёт всегда;
**проект** — временное предприятие, закрывается; **объект сети** — актив,
переживающий свои проекты.

Отсюда правила, которых не было, пока проект и площадка были одной строкой:

* у площадки может быть несколько проектов — очередями («вторая очередь на той
  же территории») или во времени (построили → через три года модернизировали);
* **возврат из эксплуатации — это новый проект**, а не откат стадии назад.
  Откат стирал факт ввода и историю: объект оставался связанным, дата ввода
  сохранялась, но проект снова считался стройкой. По ФСБУ 26/2020 модернизация
  действующего объекта — отдельное капвложение со своей датой решения, по FERC
  замена узла = списание старой единицы плюс капитализация новой;
* закрытие проекта различает **приостановку и отмену**: при приостановке
  капвложения остаются на счёте 08, при отмене без перспектив возобновления —
  списываются в периоде принятия решения (Дт 91.02 Кт 08). Поэтому у отмены
  обязательны причина и дата решения.

Мелкий ремонт и ППР проектом не становятся: критерий капитализации — продление
срока службы или изменение функции объекта, остальное — наряд на обслуживание.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsProject, EzsSite, ServiceLocation, User
from app.services.ezs_sites import (
    STAGE_LABELS, format_project_no, parse_project_seq, project_no_prefix,
)

# Типы проектов. Новое строительство приходит из банка площадок, остальные три —
# это работа с уже существующим объектом сети.
PROJECT_KINDS = [
    {"key": "new_build", "label": "Новое строительство",
     "hint": "площадка становится станцией", "startStage": "lead"},
    {"key": "retrofit", "label": "Модернизация",
     "hint": "замена или усиление оборудования действующей станции", "startStage": "decision"},
    {"key": "relocation", "label": "Перенос",
     "hint": "станция переезжает на другое место", "startStage": "decision"},
    {"key": "decommission", "label": "Демонтаж",
     "hint": "вывод объекта из эксплуатации", "startStage": "decision"},
]
KIND_LABELS = {k["key"]: k["label"] for k in PROJECT_KINDS}
KIND_START_STAGE = {k["key"]: k["startStage"] for k in PROJECT_KINDS}

# Чем закрывается проект. Разница между паузой и отменой — бухгалтерская.
CLOSE_MODES = [
    {"key": "on_hold", "label": "Приостановить",
     "hint": "капвложения остаются на счёте 08, проект ждёт решения"},
    {"key": "archive", "label": "Отменить",
     "hint": "перспектив нет: капвложения списываются в периоде решения"},
]


async def next_no(db: AsyncSession, company_id) -> str:
    prefix = project_no_prefix()
    last = (await db.execute(
        select(func.max(EzsProject.project_no)).where(
            EzsProject.company_id == company_id,
            EzsProject.project_no.like(f"{prefix}%")))).scalar()
    return format_project_no(prefix, parse_project_seq(last) + 1)


def _out(p: EzsProject, *, site: EzsSite | None = None,
         location: ServiceLocation | None = None, owner: str | None = None) -> dict[str, Any]:
    return {
        "id": str(p.id), "siteId": str(p.site_id),
        "locationId": p.location_id,
        "kind": p.kind, "kindLabel": KIND_LABELS.get(p.kind, p.kind),
        "projectNo": p.project_no, "title": p.title,
        "stage": p.stage, "stageLabel": STAGE_LABELS.get(p.stage, p.stage),
        "stageSince": p.stage_since, "prevStage": p.prev_stage,
        "closedReason": p.closed_reason, "closedOn": p.closed_on,
        "ownerUserId": str(p.owner_user_id) if p.owner_user_id else None,
        "ownerName": owner,
        "nextAction": p.next_action, "nextActionDue": p.next_action_due,
        "commissionedOn": p.commissioned_on,
        "contractId": str(p.contract_id) if p.contract_id else None,
        "site": None if site is None else {
            "id": str(site.id), "address": site.full_address or site.address,
            "city": site.city, "region": site.region_norm or site.region,
        },
        "location": None if location is None else {
            "id": location.id, "code": location.code, "name": location.name,
        },
        "createdAt": p.created_at.isoformat() if p.created_at else None,
    }


async def list_projects(db: AsyncSession, company_id, *, site_id=None, location_id=None,
                        kind: str | None = None) -> list[dict[str, Any]]:
    """Проекты площадки или объекта — история места и история актива."""
    q = (select(EzsProject, EzsSite, ServiceLocation, func.coalesce(User.name, User.email))
         .join(EzsSite, EzsSite.id == EzsProject.site_id)
         .outerjoin(ServiceLocation, ServiceLocation.id == EzsProject.location_id)
         .outerjoin(User, User.id == EzsProject.owner_user_id)
         .where(EzsProject.company_id == company_id))
    if site_id is not None:
        q = q.where(EzsProject.site_id == site_id)
    if location_id is not None:
        q = q.where(EzsProject.location_id == str(location_id))
    if kind:
        q = q.where(EzsProject.kind == kind)
    rows = (await db.execute(q.order_by(EzsProject.created_at.desc()))).all()
    return [_out(p, site=s, location=loc, owner=owner) for p, s, loc, owner in rows]


async def current_project(db: AsyncSession, company_id, site_id) -> EzsProject | None:
    """Проект площадки, который ведут сейчас: незакрытый и самый свежий."""
    return (await db.execute(
        select(EzsProject)
        .where(EzsProject.company_id == company_id, EzsProject.site_id == site_id)
        .order_by(EzsProject.stage.in_(["archive"]).asc(), EzsProject.created_at.desc())
        .limit(1))).scalars().first()


# Поля, которыми проект-первенец повторяет свою площадку. Переходный период:
# карточку по-прежнему ведут на площадке, а проект обязан быть её зеркалом,
# иначе история объекта и второй проект на месте окажутся мимо данных.
_MIRRORED = (
    "project_no", "title", "stage", "stage_since", "prev_stage", "owner_user_id",
    "next_action", "next_action_due", "last_touch_at", "hold_until", "gates",
    "commissioned_on", "contract_id",
)


async def sync_from_site(db: AsyncSession, company_id, site: EzsSite) -> EzsProject:
    """Создать проект площадки, если его нет, и подтянуть в него поля площадки.

    Зеркалим только ПЕРВЫЙ проект (`new_build`): у ретрофита своя стадия и свой
    ответственный, и правка площадки не должна их переписывать.
    """
    p = (await db.execute(
        select(EzsProject).where(
            EzsProject.company_id == company_id, EzsProject.site_id == site.id,
            EzsProject.kind == "new_build")
        .order_by(EzsProject.created_at).limit(1))).scalars().first()
    if p is None:
        p = EzsProject(company_id=company_id, site_id=site.id, kind="new_build",
                       stage=site.stage or "lead")
        db.add(p)
    for f in _MIRRORED:
        setattr(p, f, getattr(site, f, None))
    p.location_id = site.location_id
    p.updated_at = datetime.now(timezone.utc)
    return p


async def start_project(db: AsyncSession, company_id, *, site: EzsSite, kind: str,
                        title: str | None, location_id: str | None,
                        reason: str | None, user: User | None) -> dict[str, Any]:
    """Завести новый проект на площадке (в том числе на действующем объекте).

    Для ретрофита, переноса и демонтажа объект известен сразу, а стадия
    начинается с решения: подбор площадки уже пройден в прошлой жизни.
    """
    from app.services.ezs_site_work import log_event

    if kind not in KIND_LABELS:
        return {"ok": False, "message": "Неизвестный тип проекта"}
    loc = None
    if location_id:
        loc = (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.id == str(location_id)))).scalar_one_or_none()
        if loc is None:
            return {"ok": False, "message": "Объект сети не найден"}
    if kind != "new_build" and loc is None:
        return {"ok": False, "message": "Для этого типа проекта нужен объект сети"}

    now = datetime.now(timezone.utc)
    p = EzsProject(
        company_id=company_id, site_id=site.id, location_id=loc.id if loc else None,
        kind=kind, project_no=await next_no(db, company_id),
        title=title or (f"{KIND_LABELS[kind]}: {loc.name}" if loc else None),
        stage=KIND_START_STAGE.get(kind, "lead"), stage_since=date.today().isoformat(),
        created_at=now, updated_at=now,
    )
    db.add(p)
    await db.flush()
    await log_event(db, site, "note", user=user,
                    text=f"Заведён проект {p.project_no} — {KIND_LABELS[kind]}"
                         + (f" ({reason})" if reason else ""))
    return {"ok": True, "project": _out(p, site=site, location=loc)}


async def close_project(db: AsyncSession, company_id, project: EzsProject, *, mode: str,
                        reason: str, user: User | None) -> dict[str, Any]:
    """Приостановить или отменить проект.

    Причина обязательна для обоих режимов: для отмены она становится основанием
    списания капвложений, для паузы — объяснением, почему деньги продолжают
    висеть на счёте 08.
    """
    from app.services.ezs_site_work import log_event

    if mode not in ("on_hold", "archive"):
        return {"ok": False, "message": "Неизвестный режим закрытия"}
    if not (reason or "").strip():
        return {"ok": False, "message": "Нужна причина: без неё судьбу затрат не объяснить"}
    site = (await db.execute(select(EzsSite).where(EzsSite.id == project.site_id))).scalar_one()
    project.prev_stage = project.stage
    project.stage = mode
    project.stage_since = date.today().isoformat()
    project.closed_reason = reason.strip()
    project.closed_on = date.today().isoformat()
    project.updated_at = datetime.now(timezone.utc)
    word = "приостановлен" if mode == "on_hold" else "отменён"
    tail = ("капвложения остаются на счёте 08"
            if mode == "on_hold" else "капвложения подлежат списанию")
    await log_event(db, site, "stage", user=user, from_stage=project.prev_stage, to_stage=mode,
                    text=f"Проект {project.project_no} {word}: {reason.strip()} — {tail}")
    return {"ok": True, "project": _out(project, site=site)}


async def reopen_from_operation(db: AsyncSession, company_id, location_id: str, *,
                                kind: str, reason: str, user: User | None) -> dict[str, Any]:
    """Вернуть объект из эксплуатации в проектный контур.

    Заводит НОВЫЙ проект на площадке того объекта — старый проект остаётся
    закрытым со своей датой ввода. Так история объекта читается как список
    работ, а не как один бесконечно переоткрываемый проект.
    """
    loc = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == str(location_id)))).scalar_one_or_none()
    if loc is None:
        return {"ok": False, "message": "Объект сети не найден"}
    if kind not in ("retrofit", "relocation", "decommission"):
        return {"ok": False, "message": "Возврат бывает модернизацией, переносом или демонтажом"}
    # Площадка объекта — та, на которой его построили; если проектов ещё не было
    # (объект завели руками в реестре), работать не с чем: сначала нужна площадка.
    prev = (await db.execute(
        select(EzsProject).where(EzsProject.company_id == company_id,
                                 EzsProject.location_id == loc.id)
        .order_by(EzsProject.created_at.desc()).limit(1))).scalars().first()
    if prev is None:
        return {"ok": False, "message": "У объекта нет проектной истории — заведите площадку"}
    site = (await db.execute(select(EzsSite).where(EzsSite.id == prev.site_id))).scalar_one()
    return await start_project(db, company_id, site=site, kind=kind, title=None,
                               location_id=loc.id, reason=reason, user=user)
