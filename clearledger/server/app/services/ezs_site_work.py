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

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsProject, EzsSite, EzsSiteEvent, User
from app.services.ezs_checklist import PHASE_LABELS_DOC, WAIVE_FORBIDDEN, gates_by_stage
from app.services.ezs_sites import (
    STAGE_LABELS, STAGE_ORDER, _site_out, format_project_no, parse_project_seq,
    project_no_prefix,
)
from app.services.ezs_changes import make_change

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

    **Послабление** (`waived`) — обязательный пункт, с которого ответственный снял
    обязательность под свою подпись. Пункт остаётся в списке невыполненным: он не
    отменён и его всё ещё видно. Он просто перестаёт держать переход.
    """
    st = stage or site.stage
    items = GATES.get(st, [])
    marks = (site.gates or {}).get(st, {}) if isinstance(site.gates, dict) else {}
    docs = doc_kinds or set()
    out = []
    for it in items:
        mark = marks.get(it["key"]) or {}
        waived = bool(mark.get("waived"))
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
                    # `required` остаётся истиной и после послабления: по регламенту
                    # пункт обязателен, снята обязательность только в этом проекте
                    # и только под подписью. Разница видна и в карточке, и в отчёте.
                    "required": bool(it.get("required")), "done": done,
                    "waived": waived,
                    "waivedBy": mark.get("waived_by_name") if waived else None,
                    "waivedAt": mark.get("waived_at") if waived else None,
                    "waiveReason": mark.get("waive_reason") if waived else None,
                    # Снимать обязательность имеет смысл только с того, что её имеет
                    # и не выполнено; три пункта не снимаются вовсе (WAIVE_FORBIDDEN).
                    "waivable": bool(it.get("required")) and it["key"] not in WAIVE_FORBIDDEN,
                    "role": it.get("role"),
                    # Какие графы закрывают пункт: карточка подсвечивает их в паспорте.
                    # Из 55 граф иначе не понять, какие нужны прямо сейчас.
                    "fields": it.get("fields") or ([it["field"]] if it.get("field") else []),
                    "phase": it.get("phase"),
                    "phaseLabel": PHASE_LABELS_DOC.get(it.get("phase", ""), "")})
    blocking = [i["label"] for i in out if i["required"] and not i["done"] and not i["waived"]]
    waived = [{"key": i["key"], "label": i["label"], "by": i["waivedBy"],
               "at": i["waivedAt"], "reason": i["waiveReason"]}
              for i in out if i["waived"]]
    return {
        "stage": st, "stageLabel": STAGE_LABELS.get(st, st),
        "items": out,
        "done": sum(1 for i in out if i["done"]),
        "total": len(out),
        "blocking": blocking,          # что держит переход вперёд
        # Пройденное с послаблением называется вслух: иначе «переход открыт»
        # выглядит как «всё собрано», а собрано не всё.
        "waived": waived,
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
    """Чем подтверждены пункты гейта: файлами площадки и документами «Трека».

    Файл, приложенный в карточку, — прежний способ, и он остаётся: не всякую
    бумагу ведут документооборотом. Но акт ввода, прошедший круг виз и
    подписание, до сих пор гейт НЕ закрывал: для гейта требовалось, чтобы
    кто-то отдельно приложил тот же файл в карточку. Два источника правды об
    одном факте — и человек выбирал, какому верить.

    Документ «Трека» засчитывается, когда выполнены три условия: он привязан к
    этому проекту (предметом или связью), его вид объявлен закрывающим пункт
    (`DocKind.gate_key`) и он **согласован**. Черновик не подтверждает ничего:
    иначе гейт закрывался бы намерением, а не результатом.
    """
    from app.models import DocCard, DocKind, DocRelation, EzsSite, EzsSiteDoc

    rows = (await db.execute(
        select(EzsSiteDoc.kind).where(EzsSiteDoc.site_id == site_id))).scalars().all()
    kinds = set(rows)

    site = await db.get(EzsSite, site_id)
    if site is None:
        return kinds
    refs = [f"site:{site.id}"]
    if site.location_id:
        refs.append(f"object:{site.location_id}")
    related = select(DocRelation.doc_id).where(
        DocRelation.company_id == site.company_id,
        DocRelation.doc_id == DocCard.id,
        DocRelation.target_ref.in_(refs)).exists()
    settled = (await db.execute(
        select(DocKind.gate_key)
        .join(DocCard, DocCard.kind_id == DocKind.id)
        .where(
            DocCard.company_id == site.company_id,
            DocKind.gate_key.is_not(None),
            or_(DocCard.subject_ref.in_(refs), related,
                DocCard.object_id == site.location_id if site.location_id else false()),
            or_(DocCard.approval_status == "approved",
                DocCard.status.in_(("in_force", "executed")))))).scalars().all()
    kinds.update(k for k in settled if k)
    return kinds


async def site_equipment_supplied(db: AsyncSession, site_id) -> bool:
    """Всё ли нужное оборудование приехало — этим закрывается пункт гейта."""
    from app.models import EzsSiteEquipment
    rows = (await db.execute(select(EzsSiteEquipment.status).where(
        EzsSiteEquipment.site_id == site_id,
        EzsSiteEquipment.status != "cancelled"))).scalars().all()
    return bool(rows) and all(s in ("supplied", "installed") for s in rows)


async def log_event(db: AsyncSession, site: EzsSite, kind: str, *, text: str | None = None,
                    from_stage: str | None = None, to_stage: str | None = None,
                    user: User | None = None, changes: list[dict[str, Any]] | None = None,
                    source: str = "user", project_id: Any | None = None) -> EzsSiteEvent:
    if changes is None and kind == "stage" and from_stage != to_stage:
        changes = [make_change("stage", from_stage, to_stage)]
    if project_id is None:
        project_id = (await db.execute(
            select(EzsProject.id)
            .where(
                EzsProject.company_id == site.company_id,
                EzsProject.site_id == site.id,
            )
            .order_by(EzsProject.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    ev = EzsSiteEvent(
        company_id=site.company_id, site_id=site.id, project_id=project_id,
        kind=kind, text=text,
        from_stage=from_stage, to_stage=to_stage,
        changes=changes, source=source,
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
    changes: list[dict[str, Any]] = []
    owner_values: tuple[Any, Any] | None = None
    manual = set(site.manual_fields or [])
    for f, v in patch.items():
        if f not in EDITABLE_FIELDS:
            continue
        new = _coerce(f, v)
        old = getattr(site, f, None)
        if old == new:
            continue
        setattr(site, f, new)
        changed.append(f)
        changes.append(make_change(f, old, new))
        if f == "owner_user_id":
            owner_values = (old, new)
        manual.add(f)
    if changed:
        if owner_values is not None:
            owner_ids = {value for value in owner_values if value is not None}
            names = dict((await db.execute(
                select(User.id, func.coalesce(User.name, User.email)).where(
                    User.id.in_(owner_ids))
            )).all()) if owner_ids else {}
            owner_change = next(
                item for item in changes if item["field"] == "owner_user_id")
            owner_change["oldDisplay"] = names.get(owner_values[0]) or "не назначен"
            owner_change["newDisplay"] = names.get(owner_values[1]) or "не назначен"
        site.manual_fields = sorted(manual)
        site.updated_at = datetime.now(timezone.utc)
        site.last_touch_at = datetime.now(timezone.utc)
        await log_event(
            db, site, "edit", text=", ".join(item["label"] for item in changes),
            changes=changes, user=user,
        )
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
    project_rows = (await db.execute(
        select(EzsProject.site_id, EzsProject.id)
        .where(
            EzsProject.company_id == company_id,
            EzsProject.site_id.in_([site.id for site in rows]),
        )
        .order_by(EzsProject.created_at.desc())
    )).all()
    project_by_site = {}
    for site_id, project_id in project_rows:
        project_by_site.setdefault(site_id, project_id)
    now = datetime.now(timezone.utc)
    name = None
    if owner is not None:
        name = (await db.execute(
            select(func.coalesce(User.name, User.email)).where(User.id == owner))).scalar()
    old_owner_ids = {s.owner_user_id for s in rows if s.owner_user_id is not None}
    old_owner_names = {}
    if old_owner_ids:
        old_owner_names = dict((await db.execute(
            select(User.id, func.coalesce(User.name, User.email)).where(
                User.id.in_(old_owner_ids))
        )).all())
    assigned = 0
    for s in rows:
        if s.owner_user_id == owner:
            continue
        old_owner = s.owner_user_id
        s.owner_user_id = owner
        s.manual_fields = sorted(set(s.manual_fields or []) | {"owner_user_id"})
        s.updated_at = now
        await log_event(db, s, "edit", user=user,
                        text=f"Ответственный: {name}" if name else "Ответственный снят",
                        project_id=project_by_site.get(s.id),
                        changes=[make_change(
                            "owner_user_id", old_owner, owner,
                            old_display=old_owner_names.get(old_owner, "не назначен"),
                            new_display=name or "не назначен",
                        )])
        assigned += 1
    return {"assigned": assigned}


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
    # У места сразу появляется первый проект: без него площадка не попадёт ни в
    # историю объекта, ни в реестр проектов.
    from app.services.ezs_lifecycle import sync_from_site
    project = await sync_from_site(db, site.company_id, site)
    await db.flush()
    await log_event(
        db, site, "note", text="Площадка заведена вручную", user=user,
        project_id=project.id,
    )
    return site


async def set_stage(db: AsyncSession, site: EzsSite, stage: str, *, reason: str | None,
                    user: User | None, may_override: bool = False,
                    override: bool = False, source: str = "user") -> dict[str, Any]:
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
        old_archive_reason = site.archive_reason
        site.archive_reason = reason[:200]
        manual = set(site.manual_fields or []); manual.add("archive_reason")
        site.manual_fields = sorted(manual)
    else:
        old_archive_reason = site.archive_reason

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
                        source=source,
                        text=f"Обход обязательных пунктов ({'; '.join(gate['blocking'])}): {reason}")
    changes = [make_change("stage", prev, stage)]
    if old_archive_reason != site.archive_reason:
        changes.append(make_change(
            "archive_reason", old_archive_reason, site.archive_reason))
    await log_event(
        db, site, "stage", text=note, from_stage=prev, to_stage=stage,
        changes=changes, user=user, source=source,
    )
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
    old_done = bool(stage_marks.get(key, {}).get("done"))
    # Отметка и послабление живут в одной записи, поэтому пишем поверх, а не вместо:
    # иначе галочка стирала бы чужую подпись под снятием обязательности.
    stage_marks[key] = {
        **(stage_marks.get(key) or {}),
        "done": bool(done),
        "at": datetime.now(timezone.utc).isoformat(),
        "by": str(user.id) if user is not None else None,
    }
    gates[site.stage] = stage_marks
    site.gates = gates
    site.last_touch_at = datetime.now(timezone.utc)
    await log_event(db, site, "gate", user=user,
                    text=f"{'✓' if done else '✗'} {items[key]['label']}",
                    changes=[make_change(
                        f"gate:{key}", old_done, bool(done),
                        label=items[key]["label"], category="decision",
                        old_display="выполнено" if old_done else "не выполнено",
                        new_display="выполнено" if done else "не выполнено",
                    )] if old_done != bool(done) else None)
    return {"ok": True, "gate": gate_state(
        site, doc_kinds=await site_doc_kinds(db, site.id),
        equipment_supplied=await site_equipment_supplied(db, site.id))}


# Пункт чек-листа по номеру, вместе со стадией, к которой он приписан. Гейты
# разложены по стадиям, а послабление адресуется пункту: «3.12» человек называет
# по номеру, не помня, на какой стадии он закрывается.
_ITEM_BY_KEY: dict[str, tuple[str, dict[str, Any]]] = {
    it["key"]: (st, it) for st, items in GATES.items() for it in items
}


async def set_gate_waiver(db: AsyncSession, site: EzsSite, key: str, waived: bool,
                          reason: str, user: User | None) -> dict[str, Any]:
    """Снять с обязательного пункта обязательность — под ответственность человека.

    Это НЕ отмена пункта и не отметка «выполнено». Пункт остаётся в чек-листе
    невыполненным и видимым, но перестаёт держать переход: ответственный за проект
    заявил, что здесь ждать нечего, и подписался под этим своим именем.

    Зачем отдельно от обхода гейта (`set_stage(override=True)`): обход — событие
    одного перехода, его надо повторять на каждом шаге, и в карточке от него не
    остаётся ничего, кроме строки в истории. Послабление — состояние проекта: его
    видно в чек-листе, у него есть автор и причина, и оно снимается так же явно,
    как ставится.

    Право проверяет вызывающая сторона (роутер): здесь только правила самого
    чек-листа — какой пункт вообще можно ослабить.
    """
    found = _ITEM_BY_KEY.get(key)
    if found is None:
        return {"ok": False, "message": f"Пункт {key} в чек-листе не значится"}
    stage, item = found
    if not item.get("required"):
        return {"ok": False, "message": "Пункт и так не обязателен — снимать нечего"}
    if key in WAIVE_FORBIDDEN:
        return {"ok": False,
                "message": f"Пункт {key} «{item['label']}» обязателен без исключений"}
    reason = (reason or "").strip()
    if waived and not reason:
        return {"ok": False, "message": "Нужно обоснование: под ним будет стоять ваше имя"}

    gates = dict(site.gates or {})
    stage_marks = dict(gates.get(stage) or {})
    mark = dict(stage_marks.get(key) or {})
    was = bool(mark.get("waived"))
    if was == bool(waived):
        return {"ok": True, "unchanged": True, "gate": await gate_now(db, site)}

    now = datetime.now(timezone.utc).isoformat()
    if waived:
        mark.update({
            "waived": True,
            "waived_at": now,
            "waived_by": str(user.id) if user is not None else None,
            # Имя снимком: отчёт и карточка читают его без join, а человек может
            # уволиться — подпись под решением от этого не должна исчезнуть.
            "waived_by_name": (getattr(user, "name", None) or getattr(user, "email", None)
                               if user is not None else None),
            "waive_reason": reason[:500],
        })
    else:
        # Возврат обязательности стирает послабление, но не отметку выполнения:
        # это две разные вещи в одной записи.
        for f in ("waived", "waived_at", "waived_by", "waived_by_name", "waive_reason"):
            mark.pop(f, None)
    stage_marks[key] = mark
    gates[stage] = stage_marks
    site.gates = gates
    site.last_touch_at = datetime.now(timezone.utc)

    text = (f"Снята обязательность пункта {key} «{item['label']}»: {reason}"
            if waived else f"Возвращена обязательность пункта {key} «{item['label']}»")
    await log_event(db, site, "gate", user=user, text=text,
                    changes=[make_change(
                        f"gate:{key}:waived", was, bool(waived),
                        label=f"Обязательность пункта {key}", category="decision",
                        old_display="обязателен" if not was else "не обязателен",
                        new_display="не обязателен" if waived else "обязателен",
                    )])
    return {"ok": True, "gate": await gate_now(db, site)}


async def gate_now(db: AsyncSession, site: EzsSite) -> dict[str, Any]:
    """Чек-лист текущей стадии со всеми фактами, которые считаются из базы."""
    return gate_state(site, doc_kinds=await site_doc_kinds(db, site.id),
                      equipment_supplied=await site_equipment_supplied(db, site.id))


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
        "routeCode": site.route_code,
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
