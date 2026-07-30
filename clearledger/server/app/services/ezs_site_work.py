"""Ведение площадки банка ЗУ: правка карточки, стадии, гейты, история.

Волна 2 разбора раздела (`docs/SITES_LAND_BANK_BLUEPRINT.md`). До неё площадку
можно было только импортировать: ни ответственного, ни следующего шага, ни
истории — вся отработка шла мимо системы.

Два правила, ради которых всё и затевалось:
  • у стадии есть ГЕЙТ — список того, что должно быть закрыто перед переходом.
    Жёстко не блокируем (жизнь сложнее чек-листа), но незакрытые пункты
    показываем и пишем в историю: решение принято, зная о пробеле;
  • всё, что правит человек, помечается в `manual_fields` и больше не
    перетирается импортом из файла.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite, EzsSiteEvent, User
from app.services.ezs_checklist import PHASE_LABELS_DOC, gates_by_stage
from app.services.ezs_sites import (
    STAGE_LABELS, STAGE_ORDER, _site_out, format_project_no, parse_project_seq,
    project_no_prefix,
)

# ── Гейты: что должно быть готово, чтобы уйти с этой стадии дальше ──────────
# Собираются из чек-листа согласования ЗУ (регламент РусГидро, `ezs_checklist`):
# пункт гейта = задача чек-листа со своим номером («3.12») и ответственным.
# До 28.07.2026 здесь лежал наш собственный список — он был короче регламента и
# называл вещи иначе, из-за чего сверить работу с бумагой было нельзя.
#
# Как проверяется пункт: `field`/`fields` — автоматически по заполненным графам,
# `doc` — приложенным документом, `equipment` — поставкой оборудования,
# `manual` — галочкой. `required` держит переход вперёд (обход — с обоснованием).
GATES: dict[str, list[dict[str, Any]]] = gates_by_stage()

# Поля, которые можно править из карточки.
EDITABLE_FIELDS = {
    "region", "city", "address", "full_address", "place_kind", "install_place", "route",
    "lat", "lon", "map_url", "owner", "brand", "area_m2", "ownership", "cadastral_no",
    "free_power_kwt", "free_power_num", "distance_to_tp_m", "tp_cost", "tp_term_months",
    "connection_cost", "rent_cost_month", "rent_rate", "control_form", "land_category",
    "permitted_use", "encumbrances", "contract_start", "contract_end",
    "planned_power_kwt", "planned_ezs_count", "supplier", "contractor", "tu_status",
    "tech_conn_type", "dop_service", "comment", "archive_reason",
    "next_action", "next_action_due", "hold_until", "owner_user_id", "location_id",
    # проект: имя, субсидия, условия площадки
    # `commissioned_on` здесь намеренно НЕТ: дата ввода — основание перевода
    # капвложений со счёта 08 на 01, и правка её руками из паспорта позволяла бы
    # закрыть стройку в учёте, минуя обязательные пункты чек-листа. Ставит её
    # только маршрут, дошедший до стадии ввода при закрытом чек-листе.
    "title", "subsidy_planned", "parking_spots", "access_24x7", "has_lighting",
    "has_internet", "subsidy_amount",
    # графы чек-листа согласования (v2.26)
    "input_price_kwth", "smr_cost", "long_term_contract", "has_video", "has_mobile",
    "owner_contact", "source_company", "source_person",
}
_BOOL = {"subsidy_planned", "access_24x7", "has_lighting", "has_internet",
         "long_term_contract", "has_video", "has_mobile"}
_NUMERIC = {"lat", "lon", "area_m2", "free_power_num", "distance_to_tp_m", "tp_cost",
            "tp_term_months", "connection_cost", "rent_cost_month", "rent_rate",
            "planned_power_kwt", "input_price_kwth", "smr_cost"}
_INT = {"planned_ezs_count", "parking_spots"}
_UUID_FIELDS = {"owner_user_id", "location_id"}


def _field_filled(site: EzsSite, field: str) -> bool:
    if field == "address_any":
        return bool(site.address or site.full_address or site.install_place)
    return getattr(site, field, None) not in (None, "")


def gate_state(site: EzsSite, stage: str | None = None,
               doc_kinds: set[str] | None = None, equipment_supplied: bool | None = None) -> dict[str, Any]:
    """Чек-лист стадии: что закрыто, что нет, что держит переход.

    `doc_kinds` — типы приложенных документов проекта; без них пункты вида
    «скан договора» считать нельзя, поэтому вызывающая сторона их передаёт.
    """
    st = stage or site.stage
    items = GATES.get(st, [])
    marks = (site.gates or {}).get(st, {}) if isinstance(site.gates, dict) else {}
    docs = doc_kinds or set()
    out = []
    for it in items:
        if it.get("manual"):
            done = bool(marks.get(it["key"], {}).get("done"))
        elif it.get("doc"):
            done = it["doc"] in docs
        elif it.get("equipment"):
            # Закрывается не галочкой, а фактом: все нужные позиции поставлены.
            done = bool(equipment_supplied)
        elif it.get("fields"):
            # Задача чек-листа закрывается набором граф («аренда И срок договора»):
            # половина заполненных граф — это невыполненный пункт, а не «почти».
            done = all(_field_filled(site, f) for f in it["fields"])
        else:
            done = _field_filled(site, it["field"])
        out.append({"key": it["key"], "label": it["label"], "manual": bool(it.get("manual")),
                    "doc": it.get("doc"), "equipment": bool(it.get("equipment")),
                    "required": bool(it.get("required")), "done": done,
                    "role": it.get("role"),
                    # Какие графы закрывают пункт: карточка подсвечивает их в паспорте.
                    # Из 55 граф иначе не понять, какие нужны прямо сейчас.
                    "fields": it.get("fields") or ([it["field"]] if it.get("field") else []),
                    "phase": it.get("phase"),
                    "phaseLabel": PHASE_LABELS_DOC.get(it.get("phase", ""), "")})
    blocking = [i["label"] for i in out if i["required"] and not i["done"]]
    return {
        "stage": st, "stageLabel": STAGE_LABELS.get(st, st),
        "items": out,
        "done": sum(1 for i in out if i["done"]),
        "total": len(out),
        "blocking": blocking,          # что держит переход вперёд
        "canAdvance": not blocking,
    }


async def next_project_no(db: AsyncSession, company_id) -> str:
    """Следующий номер проекта в текущем году: ЭЗС-2026-0042.

    Считаем максимум по году, а не количество: удалённые проекты не должны
    возвращать номер в оборот — на него уже могли сослаться в переписке.
    """
    prefix = project_no_prefix()
    last = (await db.execute(
        select(func.max(EzsSite.project_no)).where(
            EzsSite.company_id == company_id, EzsSite.project_no.like(f"{prefix}%")))).scalar()
    return format_project_no(prefix, parse_project_seq(last) + 1)


async def site_doc_kinds(db: AsyncSession, site_id) -> set[str]:
    from app.models import EzsSiteDoc
    rows = (await db.execute(
        select(EzsSiteDoc.kind).where(EzsSiteDoc.site_id == site_id))).scalars().all()
    return set(rows)


async def site_equipment_supplied(db: AsyncSession, site_id) -> bool:
    """Всё ли нужное оборудование приехало — этим закрывается пункт гейта."""
    from app.models import EzsSiteEquipment
    rows = (await db.execute(select(EzsSiteEquipment.status).where(
        EzsSiteEquipment.site_id == site_id,
        EzsSiteEquipment.status != "cancelled"))).scalars().all()
    return bool(rows) and all(s in ("supplied", "installed") for s in rows)


async def log_event(db: AsyncSession, site: EzsSite, kind: str, *, text: str | None = None,
                    from_stage: str | None = None, to_stage: str | None = None,
                    user: User | None = None) -> EzsSiteEvent:
    ev = EzsSiteEvent(
        company_id=site.company_id, site_id=site.id, kind=kind, text=text,
        from_stage=from_stage, to_stage=to_stage,
        author_user_id=user.id if user is not None else None,
    )
    db.add(ev)
    return ev


def _coerce(field: str, value: Any) -> Any:
    if value in ("", None):
        return None
    if field in _NUMERIC:
        try:
            return float(str(value).replace(",", ".").replace(" ", ""))
        except (TypeError, ValueError):
            return None
    if field in _INT:
        try:
            return int(float(str(value).replace(",", ".")))
        except (TypeError, ValueError):
            return None
    if field in _BOOL:
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "да")
    if field in _UUID_FIELDS:
        import uuid as _uuid
        try:
            return _uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None
    return str(value)


async def update_site(db: AsyncSession, site: EzsSite, patch: dict[str, Any],
                      user: User | None) -> dict[str, Any]:
    """Правка карточки. Изменённые поля запоминаются как ручные — импорт их не тронет."""
    changed: list[str] = []
    manual = set(site.manual_fields or [])
    for f, v in patch.items():
        if f not in EDITABLE_FIELDS:
            continue
        new = _coerce(f, v)
        if getattr(site, f, None) == new:
            continue
        setattr(site, f, new)
        changed.append(f)
        manual.add(f)
    if changed:
        site.manual_fields = sorted(manual)
        site.updated_at = datetime.now(timezone.utc)
        site.last_touch_at = datetime.now(timezone.utc)
        await log_event(db, site, "edit", text=", ".join(changed), user=user)
        from app.services.ezs_lifecycle import sync_from_site
        await sync_from_site(db, site.company_id, site)
    return {"changed": changed}


async def bulk_assign(db: AsyncSession, company_id, site_ids: list[Any],
                      owner_user_id: Any, user: User | None) -> dict[str, Any]:
    """Назначить ответственного пачкой.

    По одному это не делается: после первой загрузки банка без владельца сразу
    три сотни проектов, и «кто ведёт» пустует, пока их не раздали. Назначение —
    ручное поле, поэтому попадает в `manual_fields` и импортом не сбивается.
    """
    if not site_ids:
        return {"assigned": 0}
    owner = None
    if owner_user_id not in (None, "", "none"):
        owner = _coerce("owner_user_id", owner_user_id)
        if owner is None:
            return {"assigned": 0, "error": "Пользователь не опознан"}
        member = (await db.execute(select(User.id).where(User.id == owner))).scalar_one_or_none()
        if member is None:
            return {"assigned": 0, "error": "Пользователь не найден"}
    rows = (await db.execute(select(EzsSite).where(
        EzsSite.company_id == company_id, EzsSite.id.in_(site_ids)))).scalars().all()
    now = datetime.now(timezone.utc)
    name = None
    if owner is not None:
        name = (await db.execute(
            select(func.coalesce(User.name, User.email)).where(User.id == owner))).scalar()
    for s in rows:
        if s.owner_user_id == owner:
            continue
        s.owner_user_id = owner
        s.manual_fields = sorted(set(s.manual_fields or []) | {"owner_user_id"})
        s.updated_at = now
        await log_event(db, s, "edit", user=user,
                        text=f"Ответственный: {name}" if name else "Ответственный снят")
    return {"assigned": len(rows)}


async def create_site(db: AsyncSession, company_id, payload: dict[str, Any],
                      user: User | None) -> EzsSite:
    """Новая площадка руками. Лид может прийти не файлом, а звонком."""
    from app.services.ezs_sites import RegionResolver, _addr_key, _dedup_key
    from app.models import Region

    regions = (await db.execute(
        select(Region).where(Region.company_id == company_id))).scalars().all()
    resolver = RegionResolver(list(regions))
    now = datetime.now(timezone.utc)

    # Вид работы задаётся только при заведении: по нему маршрут на входе выбирает
    # ветку. В EDITABLE_FIELDS его нет намеренно — смена вида на полпути увела бы
    # уже идущий проект в чужую ветку.
    from app.services.ezs_lifecycle import KIND_LABELS
    kind = str(payload.get("kind") or "new_build")
    if kind not in KIND_LABELS:
        kind = "new_build"

    site = EzsSite(company_id=company_id, stage=payload.get("stage") or "lead", kind=kind,
                   stage_since=date.today().isoformat(), project_no=await next_project_no(db, company_id),
                   first_seen_at=now, last_seen_at=now, updated_at=now, last_touch_at=now)
    fields = {f: payload.get(f) for f in EDITABLE_FIELDS if f in payload}
    for f, v in fields.items():
        setattr(site, f, _coerce(f, v))
    site.manual_fields = sorted(fields.keys())
    region_norm, region = resolver.resolve(site.region, site.city)
    site.region_norm, site.region_id = region_norm, (region.id if region else None)
    site.dedup_key = _dedup_key(
        site.cadastral_no, site.lat, site.lon,
        _addr_key(site.full_address or site.address, site.city),
        f"{site.region or ''} {site.city or ''} {site.address or ''} {site.owner or ''}".strip(),
    )
    db.add(site)
    await db.flush()
    await log_event(db, site, "note", text="Площадка заведена вручную", user=user)
    # У места сразу появляется первый проект: без него площадка не попадёт ни в
    # историю объекта, ни в реестр проектов.
    from app.services.ezs_lifecycle import sync_from_site
    await sync_from_site(db, site.company_id, site)
    return site


async def set_stage(db: AsyncSession, site: EzsSite, stage: str, *, reason: str | None,
                    user: User | None, may_override: bool = False,
                    override: bool = False) -> dict[str, Any]:
    """Перевод стадии.

    Обязательные пункты гейта **блокируют** движение вперёд. Обход возможен
    только с обоснованием и правами админа компании — и попадает в историю
    отдельным событием. Полный запрет без исключений мы сознательно не делаем:
    процесс встаёт из-за галочки, которую физически некому поставить, и работа
    уходит в почту — туда, откуда мы её и забираем.
    """
    doc_kinds = await site_doc_kinds(db, site.id)
    eq_ok = await site_equipment_supplied(db, site.id)
    if stage == site.stage:
        return {"moved": False, "gate": gate_state(site, doc_kinds=doc_kinds, equipment_supplied=eq_ok)}
    prev = site.stage
    gate = gate_state(site, prev, doc_kinds=doc_kinds, equipment_supplied=eq_ok)
    missing = [i["label"] for i in gate["items"] if not i["done"]]
    forward = (_pos(stage) > _pos(prev)) if _pos(stage) >= 0 and _pos(prev) >= 0 else False

    # Прыжок через стадию не должен обходить их гейты: иначе из «Лида» можно
    # уйти сразу «В эксплуатацию», выполнив только требования лида.
    if forward:
        skipped: list[str] = []
        for st in STAGE_ORDER[_pos(prev):_pos(stage)]:
            g = gate_state(site, st, doc_kinds=doc_kinds, equipment_supplied=eq_ok)
            skipped += [f"{STAGE_LABELS.get(st, st)}: {b}" for b in g["blocking"]]
        gate = {**gate, "blocking": skipped}

    # Архив и заморозка не требуют гейта: отказаться можно на любом шаге.
    if forward and gate["blocking"]:
        if not override:
            return {"moved": False, "blocked": True, "blocking": gate["blocking"],
                    "gate": gate,
                    "message": "Не закрыты обязательные пункты гейта: "
                               + "; ".join(gate["blocking"])}
        if not may_override:
            return {"moved": False, "blocked": True, "blocking": gate["blocking"], "gate": gate,
                    "message": "Обход гейта доступен администратору компании"}
        if not (reason or "").strip():
            return {"moved": False, "blocked": True, "blocking": gate["blocking"], "gate": gate,
                    "message": "Для обхода гейта нужно обоснование"}

    site.prev_stage = prev
    site.stage = stage
    site.stage_since = date.today().isoformat()
    site.last_touch_at = datetime.now(timezone.utc)
    site.updated_at = datetime.now(timezone.utc)
    if stage == "archive" and reason:
        site.archive_reason = reason[:200]
        manual = set(site.manual_fields or []); manual.add("archive_reason")
        site.manual_fields = sorted(manual)

    note = f"{STAGE_LABELS.get(prev, prev)} → {STAGE_LABELS.get(stage, stage)}"
    if reason:
        note += f". {reason}"
    # Пропущенные пункты гейта пишем в историю: через месяц никто не вспомнит,
    # что решение принимали без проверенного права или без сметы.
    if forward and missing:
        note += f". Не закрыто на гейте: {'; '.join(missing)}"
    if forward and gate["blocking"] and override:
        note = "ОБХОД ГЕЙТА. " + note
        await log_event(db, site, "gate", user=user,
                        text=f"Обход обязательных пунктов ({'; '.join(gate['blocking'])}): {reason}")
    await log_event(db, site, "stage", text=note, from_stage=prev, to_stage=stage, user=user)
    from app.services.ezs_lifecycle import sync_from_site
    await sync_from_site(db, site.company_id, site)
    return {"moved": True, "missing": missing, "overridden": bool(forward and gate["blocking"] and override),
            "gate": gate_state(site, doc_kinds=doc_kinds, equipment_supplied=eq_ok)}


def _pos(stage: str) -> int:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else -1


async def set_gate_item(db: AsyncSession, site: EzsSite, key: str, done: bool,
                        user: User | None) -> dict[str, Any]:
    """Отметка пункта гейта, который нельзя вывести из полей (проверка глазами)."""
    items = {i["key"]: i for i in GATES.get(site.stage, []) if i.get("manual")}
    if key not in items:
        return {"ok": False, "message": "пункт не относится к текущей стадии"}
    gates = dict(site.gates or {})
    stage_marks = dict(gates.get(site.stage) or {})
    stage_marks[key] = {
        "done": bool(done),
        "at": datetime.now(timezone.utc).isoformat(),
        "by": str(user.id) if user is not None else None,
    }
    gates[site.stage] = stage_marks
    site.gates = gates
    site.last_touch_at = datetime.now(timezone.utc)
    await log_event(db, site, "gate", user=user,
                    text=f"{'✓' if done else '✗'} {items[key]['label']}")
    return {"ok": True, "gate": gate_state(
        site, doc_kinds=await site_doc_kinds(db, site.id),
        equipment_supplied=await site_equipment_supplied(db, site.id))}


async def add_touch(db: AsyncSession, site: EzsSite, text: str, kind: str,
                    user: User | None) -> dict[str, Any]:
    """Касание (звонок, письмо, встреча) или заметка."""
    site.last_touch_at = datetime.now(timezone.utc)
    ev = await log_event(db, site, "touch" if kind == "touch" else "note", text=text, user=user)
    await db.flush()
    return {"id": str(ev.id)}


async def site_events(db: AsyncSession, company_id, site_id, limit: int = 200) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(EzsSiteEvent, User.name, User.email)
        .outerjoin(User, User.id == EzsSiteEvent.author_user_id)
        .where(EzsSiteEvent.company_id == company_id, EzsSiteEvent.site_id == site_id)
        .order_by(EzsSiteEvent.created_at.desc()).limit(limit))).all()
    return [{
        "id": str(e.id), "kind": e.kind, "text": e.text,
        "fromStage": e.from_stage, "toStage": e.to_stage,
        "fromLabel": STAGE_LABELS.get(e.from_stage or "", e.from_stage),
        "toLabel": STAGE_LABELS.get(e.to_stage or "", e.to_stage),
        "author": name or email, "createdAt": e.created_at.isoformat() if e.created_at else None,
    } for e, name, email in rows]


def site_out_full(site: EzsSite, owner_name: str | None = None,
                  doc_kinds: set[str] | None = None,
                  equipment_supplied: bool | None = None) -> dict[str, Any]:
    """Карточка проекта: паспорт, ведение, гейт, субсидия, связи с учётом."""
    out = _site_out(site)
    out.update({
        "projectNo": site.project_no, "title": site.title,
        "subsidyPlanned": site.subsidy_planned, "parkingSpots": site.parking_spots,
        "access24x7": site.access_24x7, "hasLighting": site.has_lighting,
        "hasInternet": site.has_internet,
        "subsidyAmount": float(site.subsidy_amount) if site.subsidy_amount is not None else None,
        "commissionedOn": site.commissioned_on,
        "contractId": str(site.contract_id) if site.contract_id else None,
        "ownerUserId": str(site.owner_user_id) if site.owner_user_id else None,
        "ownerName": owner_name,
        "nextAction": site.next_action, "nextActionDue": site.next_action_due,
        "lastTouchAt": site.last_touch_at.isoformat() if site.last_touch_at else None,
        "holdUntil": site.hold_until,
        "controlForm": site.control_form, "landCategory": site.land_category,
        "permittedUse": site.permitted_use, "encumbrances": site.encumbrances,
        "rentRate": float(site.rent_rate) if site.rent_rate is not None else None,
        "contractStart": site.contract_start, "contractEnd": site.contract_end,
        "freePowerNum": site.free_power_num, "distanceToTpM": site.distance_to_tp_m,
        "tpCost": float(site.tp_cost) if site.tp_cost is not None else None,
        "tpTermMonths": site.tp_term_months,
        # графы чек-листа согласования (v2.26)
        "inputPriceKwth": float(site.input_price_kwth) if site.input_price_kwth is not None else None,
        "smrCost": float(site.smr_cost) if site.smr_cost is not None else None,
        "longTermContract": site.long_term_contract,
        "hasVideo": site.has_video, "hasMobile": site.has_mobile,
        "ownerContact": site.owner_contact, "sourceCompany": site.source_company,
        "sourcePerson": site.source_person,
        "locationId": str(site.location_id) if site.location_id else None,
        "manualFields": site.manual_fields or [],
        "gate": gate_state(site, doc_kinds=doc_kinds, equipment_supplied=equipment_supplied),
    })
    return out


async def company_members(db: AsyncSession, company_id) -> list[dict[str, str]]:
    """Члены компании для назначения ответственного.

    Отдельно от /api/users: тот требует прав админа компании, а назначать
    ответственного по площадке — обычная работа, а не администрирование.
    """
    from app.models import UserCompany
    rows = (await db.execute(
        select(User.id, User.name, User.email)
        .join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == company_id)
        .order_by(func.coalesce(User.name, User.email)))).all()
    return [{"id": str(i), "name": n or e} for i, n, e in rows]
