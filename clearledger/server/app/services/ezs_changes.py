from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsProject, EzsSite, EzsSiteEvent, User


CATEGORY_LABELS = {
    "decision": "Решения",
    "stage": "Стадии",
    "deadline": "Сроки",
    "responsibility": "Ответственность",
    "finance": "Деньги",
    "conditions": "Условия",
    "technical": "Технические данные",
    "object": "Карточка проекта",
    "other": "Прочее",
}

FIELD_META: dict[str, tuple[str, str]] = {
    "stage": ("Стадия", "stage"),
    "archive_reason": ("Причина отклонения", "decision"),
    "control_form": ("Форма контроля", "decision"),
    "subsidy_planned": ("Субсидия предусмотрена", "decision"),
    "subsidy_amount": ("Сумма субсидии", "decision"),
    "commissioned_on": ("Дата ввода", "decision"),
    "contract_id": ("Договор проекта", "decision"),
    "location_id": ("Объект сети", "decision"),
    "next_action": ("Следующий шаг", "deadline"),
    "next_action_due": ("Срок следующего шага", "deadline"),
    "hold_until": ("Пересмотр приостановки", "deadline"),
    "contract_start": ("Начало договора", "deadline"),
    "contract_end": ("Окончание договора", "deadline"),
    "tp_term_months": ("Срок техприсоединения", "deadline"),
    "owner_user_id": ("Ответственный", "responsibility"),
    "supplier": ("Поставщик", "responsibility"),
    "contractor": ("Подрядчик", "responsibility"),
    "source_company": ("Компания-источник", "responsibility"),
    "source_person": ("Контакт источника", "responsibility"),
    "connection_cost": ("Стоимость присоединения", "finance"),
    "tp_cost": ("Стоимость ТУ", "finance"),
    "rent_cost_month": ("Аренда в месяц", "finance"),
    "rent_rate": ("Ставка аренды", "finance"),
    "smr_cost": ("Стоимость СМР", "finance"),
    "input_price_kwth": ("Цена электроэнергии", "finance"),
    "ownership": ("Право на площадку", "conditions"),
    "land_category": ("Категория земли", "conditions"),
    "permitted_use": ("Разрешённое использование", "conditions"),
    "encumbrances": ("Обременения", "conditions"),
    "long_term_contract": ("Долгосрочный договор", "conditions"),
    "access_24x7": ("Круглосуточный доступ", "conditions"),
    "parking_spots": ("Парковочные места", "conditions"),
    "free_power_kwt": ("Свободная мощность", "technical"),
    "free_power_num": ("Свободная мощность, кВт", "technical"),
    "planned_power_kwt": ("Плановая мощность, кВт", "technical"),
    "planned_ezs_count": ("Количество ЭЗС", "technical"),
    "distance_to_tp_m": ("Расстояние до ТП, м", "technical"),
    "tu_status": ("Статус ТУ", "technical"),
    "permit_number": ("Номер разрешения", "decision"),
    "tech_conn_type": ("Тип присоединения", "technical"),
    "has_internet": ("Интернет", "technical"),
    "has_lighting": ("Освещение", "technical"),
    "has_video": ("Видеонаблюдение", "technical"),
    "has_mobile": ("Мобильная связь", "technical"),
    "title": ("Название проекта", "object"),
    "region": ("Регион", "object"),
    "city": ("Город", "object"),
    "address": ("Адрес", "object"),
    "full_address": ("Полный адрес", "object"),
    "install_place": ("Место установки", "object"),
    "place_kind": ("Тип места", "object"),
    "route": ("Трасса", "object"),
    "owner": ("Собственник", "object"),
    "brand": ("Бренд площадки", "object"),
    "cadastral_no": ("Кадастровый номер", "object"),
    "comment": ("Комментарий", "object"),
    "tc.status": ("Статус техприсоединения", "stage"),
    "tc.grid_operator": ("Сетевая организация", "responsibility"),
    "tc.application_no": ("Номер заявки на ТП", "technical"),
    "tc.due_date": ("Срок техприсоединения", "deadline"),
    "tc.done_date": ("Дата исполнения техприсоединения", "deadline"),
    "tc.application_date": ("Дата заявки на ТП", "deadline"),
    "tc.specs_no": ("Номер ТУ", "technical"),
    "tc.specs_date": ("Дата получения ТУ", "deadline"),
    "tc.contract_no": ("Номер договора ТП", "technical"),
    "tc.contract_date": ("Дата договора ТП", "deadline"),
    "tc.cost": ("Стоимость техприсоединения", "finance"),
    "tc.works_cost": ("Стоимость мероприятий ТП", "finance"),
    "tc.total_cost": ("Полная стоимость ТП", "finance"),
    "tc.power_kwt": ("Мощность присоединения", "technical"),
    "tc.voltage": ("Напряжение", "technical"),
    "tc.needs_reconstruction": ("Нужна реконструкция", "technical"),
    "tc.note": ("Комментарий по ТП", "technical"),
    "tc.substation_owner": ("Владелец подстанции", "responsibility"),
    "tc.line_owner": ("Владелец линии", "responsibility"),
    "tc.transformer_kva": ("Мощность трансформатора", "technical"),
    "tc.line_type": ("Тип линии", "technical"),
    "tc.extra_power_possible": ("Дополнительная мощность возможна", "technical"),
    "tc.transformer_swap_possible": ("Замена трансформатора возможна", "technical"),
    "tc.applicant_term_months": ("Срок заявителя, месяцев", "deadline"),
    "equipment.status": ("Статус оборудования", "stage"),
    "equipment.title": ("Оборудование", "technical"),
    "equipment.qty": ("Количество оборудования", "technical"),
    "equipment.manufacturer": ("Производитель оборудования", "technical"),
    "equipment.power_kwt": ("Мощность оборудования", "technical"),
    "equipment.connectors": ("Разъёмы", "technical"),
    "equipment.price": ("Цена оборудования", "finance"),
    "equipment.order_date": ("Дата заказа", "deadline"),
    "equipment.due_date": ("Срок поставки", "deadline"),
    "equipment.supplier": ("Поставщик оборудования", "responsibility"),
    "equipment.supplied_date": ("Дата поставки", "deadline"),
    "equipment.installed_date": ("Дата монтажа", "deadline"),
    "equipment.note": ("Комментарий по оборудованию", "technical"),
    "budget.kind": ("Статья бюджета", "finance"),
    "budget.title": ("Название статьи бюджета", "finance"),
    "budget.doc_ref": ("Документ по статье бюджета", "finance"),
    "budget.note": ("Комментарий к статье бюджета", "finance"),
    "budget.plan": ("План по статье", "finance"),
    "budget.fact": ("Факт по статье", "finance"),
}

STAGE_LABELS = {
    "lead": "Лид",
    "screening": "Скрининг",
    "negotiation": "Переговоры",
    "dd": "Проработка",
    "decision": "Решение",
    "contracting": "Оформление земли",
    "construction": "Реализация",
    "commissioning": "Пусконаладка",
    "live": "В эксплуатации",
    "on_hold": "Приостановлен",
    "archive": "Архив",
    "cancelled": "Отменён",
}

_BOOL_FIELDS = {
    "subsidy_planned", "access_24x7", "has_lighting", "has_internet",
    "long_term_contract", "has_video", "has_mobile", "tc.needs_reconstruction",
    "tc.extra_power_possible", "tc.transformer_swap_possible",
}
_MONEY_FIELDS = {
    "subsidy_amount", "connection_cost", "tp_cost", "rent_cost_month",
    "rent_rate", "smr_cost", "input_price_kwth", "tc.cost", "tc.works_cost",
    "tc.total_cost", "equipment.price", "budget.plan", "budget.fact",
}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _display_value(field: str, value: Any) -> str:
    if value in (None, ""):
        return "не задано"
    if field == "stage":
        return STAGE_LABELS.get(str(value), str(value))
    if field in _BOOL_FIELDS:
        return "да" if bool(value) else "нет"
    if field in _MONEY_FIELDS:
        try:
            amount = float(value)
            return f"{amount:,.2f}".replace(",", " ").replace(".00", "") + " ₽"
        except (TypeError, ValueError):
            pass
    return str(value)


def make_change(
    field: str,
    old: Any,
    new: Any,
    *,
    label: str | None = None,
    category: str | None = None,
    old_display: str | None = None,
    new_display: str | None = None,
) -> dict[str, Any]:
    default_label, default_category = FIELD_META.get(
        field, (field.replace("_", " ").capitalize(), "other")
    )
    return {
        "field": field,
        "label": label or default_label,
        "category": category or default_category,
        "old": _json_value(old),
        "new": _json_value(new),
        "oldDisplay": old_display or _display_value(field, old),
        "newDisplay": new_display or _display_value(field, new),
    }


def _filter_changes(changes: list[dict[str, Any]], category: str | None) -> list[dict[str, Any]]:
    if not category:
        return changes
    return [item for item in changes if item.get("category") == category]


async def changes_overview(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    days: int = 30,
    category: str | None = None,
    source: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = 60,
) -> dict[str, Any]:
    days = days if days in {7, 30, 90, 365} else 30
    category = category if category in CATEGORY_LABELS else None
    source = source if source in {"user", "import", "system"} else None
    limit = max(20, min(limit, 100))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    base = [
        EzsSiteEvent.company_id == company_id,
        EzsSiteEvent.created_at >= since,
        EzsSiteEvent.changes.is_not(None),
        func.jsonb_array_length(EzsSiteEvent.changes) > 0,
    ]
    if source:
        base.append(EzsSiteEvent.source == source)
    if category:
        base.append(EzsSiteEvent.changes.contains([{"category": category}]))

    summary_rows = (await db.execute(
        select(
            EzsSiteEvent.site_id,
            EzsSiteEvent.changes,
            EzsSiteEvent.source,
            EzsSiteEvent.created_at,
        ).where(*base)
    )).all()

    projects: set[uuid.UUID] = set()
    categories: Counter[str] = Counter()
    fields: Counter[tuple[str, str, str]] = Counter()
    change_count = 0
    decision_count = 0
    for site_id, raw_changes, _event_source, _created_at in summary_rows:
        event_changes = _filter_changes(list(raw_changes or []), category)
        if not event_changes:
            continue
        projects.add(site_id)
        change_count += len(event_changes)
        for item in event_changes:
            cat = str(item.get("category") or "other")
            fld = str(item.get("field") or "other")
            label = str(item.get("label") or fld)
            categories[cat] += 1
            fields[(fld, label, cat)] += 1
            if cat in {"decision", "stage"}:
                decision_count += 1

    cursor_created: datetime | None = None
    if cursor is not None:
        cursor_created = (await db.execute(
            select(EzsSiteEvent.created_at).where(
                EzsSiteEvent.company_id == company_id,
                EzsSiteEvent.id == cursor,
            )
        )).scalar_one_or_none()

    item_filters = list(base)
    item_filters.append(EzsSite.company_id == company_id)
    if cursor is not None and cursor_created is not None:
        item_filters.append(
            (EzsSiteEvent.created_at < cursor_created)
            | (
                (EzsSiteEvent.created_at == cursor_created)
                & (EzsSiteEvent.id < cursor)
            )
        )

    item_rows = (await db.execute(
        select(
            EzsSiteEvent,
            func.coalesce(EzsProject.project_no, EzsSite.project_no),
            func.coalesce(EzsProject.title, EzsSite.title),
            EzsSite.address,
            EzsSite.full_address,
            EzsSite.city,
            func.coalesce(User.name, User.email),
        )
        .join(EzsSite, EzsSite.id == EzsSiteEvent.site_id)
        .outerjoin(
            EzsProject,
            (EzsProject.id == EzsSiteEvent.project_id)
            & (EzsProject.company_id == company_id),
        )
        .outerjoin(User, User.id == EzsSiteEvent.author_user_id)
        .where(*item_filters)
        .order_by(EzsSiteEvent.created_at.desc(), EzsSiteEvent.id.desc())
        .limit(limit + 1)
    )).all()
    has_more = len(item_rows) > limit
    item_rows = item_rows[:limit]

    items = []
    for event, project_no, title, address, full_address, city, author in item_rows:
        event_changes = _filter_changes(list(event.changes or []), category)
        if not event_changes:
            continue
        items.append({
            "id": str(event.id),
            "siteId": str(event.site_id),
            "projectId": str(event.project_id) if event.project_id else None,
            "projectNo": project_no,
            "title": title or full_address or address or city or "Проект без названия",
            "kind": event.kind,
            "source": event.source,
            "text": event.text,
            "author": author or ("Импорт" if event.source == "import" else "Система"),
            "createdAt": event.created_at.isoformat() if event.created_at else None,
            "changes": event_changes,
        })

    legacy_events = int((await db.execute(
        select(func.count()).select_from(EzsSiteEvent).where(
            EzsSiteEvent.company_id == company_id,
            EzsSiteEvent.created_at >= since,
            EzsSiteEvent.kind.in_(("edit", "stage")),
            EzsSiteEvent.changes.is_(None),
        )
    )).scalar_one() or 0)
    tracking_started = (await db.execute(
        select(func.min(EzsSiteEvent.created_at)).where(
            EzsSiteEvent.company_id == company_id,
            EzsSiteEvent.changes.is_not(None),
            func.jsonb_array_length(EzsSiteEvent.changes) > 0,
        )
    )).scalar_one_or_none()

    by_category = [
        {
            "category": key,
            "label": CATEGORY_LABELS.get(key, key),
            "count": count,
        }
        for key, count in sorted(categories.items(), key=lambda item: (-item[1], item[0]))
    ]
    by_field = [
        {"field": field, "label": label, "category": cat, "count": count}
        for (field, label, cat), count in sorted(
            fields.items(), key=lambda item: (-item[1], item[0][1])
        )[:12]
    ]
    next_cursor = str(item_rows[-1][0].id) if has_more and item_rows else None

    return {
        "period": {"days": days, "from": since.isoformat()},
        "summary": {
            "events": len(summary_rows),
            "projects": len(projects),
            "fields": change_count,
            "decisions": decision_count,
        },
        "tracking": {
            "startedAt": tracking_started.isoformat() if tracking_started else None,
            "legacyEvents": legacy_events,
        },
        "byCategory": by_category,
        "byField": by_field,
        "items": items,
        "nextCursor": next_cursor,
    }
