"""Группировки реестра сессий ЭЗС — один срез данных в разных разрезах.

Реестр отдаёт 117 тыс. строк за год: глазами в них ничего не найти, а
браузеру такую выборку группировать нечем. Поэтому агрегация живёт здесь:
БД сворачивает выборку до десятков строк, наружу уходят только итоги.

Разрезы (`GROUPS`) отвечают на разные вопросы:

  • сеть      — станция, регион, коннектор: где заряжаются;
  • клиент    — тип, организация, карта/телефон: кто заряжается;
  • процесс   — канал запуска, исход, оплата: как прошло;
  • время     — день, неделя, месяц, день недели, час: когда;
  • визит     — склейка попыток одного клиента на станции (charge_visits.py):
                группа = один приезд, а не одно касание разъёма.

Фильтры реестра (регион, коннектор, исход, оплата, тип, поиск) применяются
до группировки — иначе итоги группы не сойдутся с тем, что видно в списке.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.analytics_cache import cached_report

S = ChargeSession


@dataclass(frozen=True)
class GroupDef:
    """Разрез: чем группируем и как подписываем строку."""
    key: str
    label: str
    family: str          # сеть | клиент | процесс | время | визит
    #: SQL-выражение группировки; label_expr — что показать в первой колонке.
    def expr(self):       # noqa: ANN201 — SQLAlchemy-выражение
        raise NotImplementedError


def _month(col):
    return func.to_char(func.date_trunc("month", col), "YYYY-MM")


def _week(col):
    # ISO-неделя: «2026-W03». Понедельник — начало, как в отчётности.
    return func.to_char(func.date_trunc("week", col), "IYYY-\"W\"IW")


#: Определения разрезов. label_expr = None → подпись равна значению группы.
GROUPS: dict[str, dict[str, Any]] = {
    # ── сеть ───────────────────────────────────────────────────────────
    "station": {"label": "Станция", "family": "сеть",
                "expr": S.station_code,
                "label_expr": func.coalesce(S.station_name, S.station_code)},
    "region": {"label": "Регион", "family": "сеть", "expr": S.region},
    "connector": {"label": "Коннектор", "family": "сеть", "expr": S.connector_type},
    # ── клиент ─────────────────────────────────────────────────────────
    "user_type": {"label": "Тип клиента (ФЛ/ЮЛ)", "family": "клиент", "expr": S.user_type},
    "client": {"label": "Клиент (ЮЛ)", "family": "клиент", "expr": S.client_name},
    # user_id у розницы — номер телефона, у корпората — идентификатор карты.
    "user": {"label": "Карта / телефон", "family": "клиент", "expr": S.user_id},
    # ── процесс ────────────────────────────────────────────────────────
    "channel": {"label": "Канал запуска", "family": "процесс", "expr": S.charge_type},
    "result": {"label": "Исход", "family": "процесс", "expr": S.result},
    "paid": {"label": "Оплата", "family": "процесс",
             "expr": case((S.paid_at.is_not(None), "Оплачено"), else_="Без оплаты")},
    # ── время ──────────────────────────────────────────────────────────
    "day": {"label": "День", "family": "время",
            "expr": func.to_char(S.started_at, "YYYY-MM-DD")},
    "week": {"label": "Неделя", "family": "время", "expr": _week(S.started_at)},
    "month": {"label": "Месяц", "family": "время", "expr": _month(S.started_at)},
    "weekday": {"label": "День недели", "family": "время",
                "expr": func.to_char(S.started_at, "ID"),
                "label_expr": func.to_char(S.started_at, "ID")},
    "hour": {"label": "Час суток", "family": "время",
             "expr": func.to_char(S.started_at, "HH24")},
    # ── визит ──────────────────────────────────────────────────────────
    # Группа = один приезд клиента (склейка смежных попыток), а не строка CPO.
    # Ключ визита — хеш, поэтому подписываем станцией: разбирают такие строки
    # по «где и когда», а не по идентификатору.
    "visit": {"label": "Визит (приезд клиента)", "family": "визит", "expr": S.visit_key,
              "label_expr": func.coalesce(S.station_name, S.station_code)},
}

WEEKDAY_RU = {"1": "Понедельник", "2": "Вторник", "3": "Среда", "4": "Четверг",
              "5": "Пятница", "6": "Суббота", "7": "Воскресенье"}

#: Коды CPO → человеческие подписи (в реестре показаны так же).
CHANNEL_RU = {"USER": "Приложение", "RFID": "Карта RFID", "AUTO": "Автостарт"}

#: Разрезы, у которых осмысленная сортировка по умолчанию — не выручка.
#: Визиты разбирают с самых тяжёлых: 6 попыток подряд — это жалоба, а не строка.
DEFAULT_SORT = {"visit": ("sessions", "desc"), "day": ("label", "asc"),
                "week": ("label", "asc"), "month": ("label", "asc"),
                "weekday": ("label", "asc"), "hour": ("label", "asc")}


def _apply_filters(stmt: Select, *, user_type: str | None, region: str | None,
                   connector: str | None, result: str | None, paid: str | None,
                   search: str | None) -> Select:
    """Те же фильтры, что в списке реестра: иначе итоги не сойдутся со списком."""
    if user_type:
        stmt = stmt.where(S.user_type == user_type)
    if region:
        stmt = stmt.where(S.region == region)
    if connector:
        stmt = stmt.where(S.connector_type == connector)
    if result:
        stmt = stmt.where(S.result == result)
    if paid == "paid":
        stmt = stmt.where(S.paid_at.is_not(None))
    elif paid == "unpaid":
        stmt = stmt.where(S.paid_at.is_(None))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(
            func.lower(func.coalesce(S.session_ext_id, "")).like(like),
            func.lower(func.coalesce(S.station_name, "")).like(like),
            func.lower(func.coalesce(S.station_code, "")).like(like),
            func.lower(func.coalesce(S.client_name, "")).like(like),
        ))
    return stmt


class ChargeGroupingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @cached_report("cs:grouped")
    async def grouped(
        self, company_id, date_from: date, date_to: date, group_by: str,
        *, station_codes: list[str] | None = None,
        user_type: str | None = None, region: str | None = None,
        connector: str | None = None, result: str | None = None,
        paid: str | None = None, search: str | None = None,
        sort: str | None = None, sort_dir: str | None = None, limit: int = 500,
    ) -> dict[str, Any]:
        """Свернуть выборку реестра в выбранный разрез с итогами по каждой группе."""
        g = GROUPS.get(group_by)
        if g is None:
            raise ValueError(f"Неизвестный разрез: {group_by}")

        d_sort, d_dir = DEFAULT_SORT.get(group_by, ("revenue", "desc"))
        sort = sort or d_sort
        sort_dir = sort_dir or d_dir

        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())
        expr = g["expr"]
        label_expr = g.get("label_expr", expr)

        success = case((S.result == "Complete", 1), else_=0)
        # «Зарядилась» = отпущена энергия. Флаг CPO отвечает на другой вопрос:
        # часть Complete отдала 0 кВтч, часть CompleteError — отдала (charge_visits).
        charged = case((S.energy_kwh > 0, 1), else_=0)

        cols = [
            expr.label("key"),
            func.min(label_expr).label("label"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy_kwh"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.avg(S.duration_min), 0).label("avg_duration"),
            func.coalesce(func.sum(success), 0).label("success"),
            func.coalesce(func.sum(charged), 0).label("charged"),
            func.count(func.distinct(S.station_code)).label("stations"),
            func.count(func.distinct(S.user_id)).label("users"),
            func.min(S.started_at).label("first_at"),
            func.max(S.started_at).label("last_at"),
        ]
        stmt = select(*cols).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            stmt = stmt.where(S.station_code.in_(station_codes))
        # Разрез по визитам без ключа бессмыслен: строки без visit_key — это
        # сессии без клиента, каждая сама себе визит, склеивать их не с чем.
        if group_by == "visit":
            stmt = stmt.where(S.visit_key.is_not(None))
        stmt = _apply_filters(stmt, user_type=user_type, region=region,
                              connector=connector, result=result, paid=paid,
                              search=search).group_by(expr)

        SORTS = {
            "revenue": func.coalesce(func.sum(S.amount), 0),
            "energy_kwh": func.coalesce(func.sum(S.energy_kwh), 0),
            "sessions": func.count(),
            "label": func.min(label_expr),
            "first_at": func.min(S.started_at),
            "last_at": func.max(S.started_at),
        }
        # Время читается по порядку, а не по величине: у разрезов времени
        # «по подписи» = хронология (ключи YYYY-MM, HH — лексикографически
        # совпадают с ней), иначе часы идут «03, 17, 09» вместо суток подряд.
        order = expr if sort == "label" and g["family"] == "время" else SORTS.get(sort, SORTS["revenue"])
        stmt = stmt.order_by(order.desc() if sort_dir == "desc" else order.asc())

        rows = (await self.db.execute(stmt.limit(limit))).all()

        groups: list[dict[str, Any]] = []
        for r in rows:
            sessions = int(r.sessions or 0)
            energy = float(r.energy_kwh or 0)
            revenue = float(r.revenue or 0)
            key = "" if r.key is None else str(r.key)
            label = "" if r.label is None else str(r.label)
            if group_by == "weekday":
                label = WEEKDAY_RU.get(key, key)
            elif group_by == "hour":
                label = f"{key}:00"
            elif group_by == "channel":
                label = CHANNEL_RU.get(key, key)
            elif group_by == "client" and not label:
                label = "— (розница)"
            elif group_by == "visit" and r.first_at:
                # «Гоголя 1 · 14.03 09:21» — визит опознают по месту и времени.
                label = f"{label or '—'} · {r.first_at.strftime('%d.%m %H:%M')}"
            groups.append({
                "key": key,
                "label": label or "— не заполнено",
                "sessions": sessions,
                "energy_kwh": round(energy, 1),
                "revenue": round(revenue, 2),
                "avg_tariff": round(revenue / energy, 2) if energy else 0.0,
                "avg_check": round(revenue / sessions, 2) if sessions else 0.0,
                "avg_duration": round(float(r.avg_duration or 0), 1),
                "success_pct": round(int(r.success or 0) / sessions * 100, 1) if sessions else 0.0,
                "charged_pct": round(int(r.charged or 0) / sessions * 100, 1) if sessions else 0.0,
                "stations": int(r.stations or 0),
                "users": int(r.users or 0),
                "first_at": r.first_at.isoformat() if r.first_at else None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
            })

        # Итог считаем отдельным запросом по всей выборке, а не суммой строк:
        # при limit сумма показанных групп не равна итогу, и цифра бы врала.
        tot_stmt = select(
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy_kwh"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.sum(success), 0).label("success"),
            func.count(func.distinct(expr)).label("groups"),
        ).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            tot_stmt = tot_stmt.where(S.station_code.in_(station_codes))
        if group_by == "visit":
            tot_stmt = tot_stmt.where(S.visit_key.is_not(None))
        tot = (await self.db.execute(_apply_filters(
            tot_stmt, user_type=user_type, region=region, connector=connector,
            result=result, paid=paid, search=search))).one()

        t_sessions = int(tot.sessions or 0)
        t_energy = float(tot.energy_kwh or 0)
        t_revenue = float(tot.revenue or 0)
        return {
            "group_by": group_by,
            "label": g["label"],
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "groups": groups,
            "shown": len(groups),
            "truncated": int(tot.groups or 0) > len(groups),
            "totals": {
                "groups": int(tot.groups or 0),
                "sessions": t_sessions,
                "energy_kwh": round(t_energy, 1),
                "revenue": round(t_revenue, 2),
                "avg_tariff": round(t_revenue / t_energy, 2) if t_energy else 0.0,
                "avg_check": round(t_revenue / t_sessions, 2) if t_sessions else 0.0,
                "success_pct": round(int(tot.success or 0) / t_sessions * 100, 1) if t_sessions else 0.0,
            },
        }


    async def group_detail(
        self, company_id, date_from: date, date_to: date, group_by: str, key: str,
        *, station_codes: list[str] | None = None,
        user_type: str | None = None, region: str | None = None,
        connector: str | None = None, result: str | None = None,
        paid: str | None = None, search: str | None = None, limit: int = 100,
    ) -> dict[str, Any]:
        """Сессии внутри одной группы — чтобы строку итога можно было разобрать.

        Без этого группировка отвечает «где просело», но не «что именно там
        произошло»: визит со 189 попытками на 0 ₽ разбирается только построчно.
        """
        g = GROUPS.get(group_by)
        if g is None:
            raise ValueError(f"Неизвестный разрез: {group_by}")

        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())
        stmt = select(
            S.session_ext_id, S.started_at, S.station_code, S.station_name, S.region,
            S.connector_type, S.user_type, S.client_name, S.user_id, S.charge_type,
            S.energy_kwh, S.duration_min, S.tariff, S.amount, S.result, S.paid_at,
            S.visit_seq, S.visit_size,
        ).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            stmt = stmt.where(S.station_code.in_(station_codes))
        # Пустой ключ = группа «не заполнено»: сравнение с '' её не найдёт.
        expr = g["expr"]
        stmt = stmt.where(expr.is_(None) if key == "" else expr == key)
        stmt = _apply_filters(stmt, user_type=user_type, region=region,
                              connector=connector, result=result, paid=paid,
                              search=search).order_by(S.started_at)

        rows = (await self.db.execute(stmt.limit(limit))).all()
        return {"group_by": group_by, "key": key, "rows": [{
            "session_ext_id": r.session_ext_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "station_code": r.station_code, "station_name": r.station_name,
            "region": r.region, "connector_type": r.connector_type,
            "user_type": r.user_type, "client_name": r.client_name,
            "user_id": r.user_id, "charge_type": r.charge_type,
            "energy_kwh": float(r.energy_kwh or 0), "duration_min": r.duration_min,
            "tariff": float(r.tariff or 0), "revenue": float(r.amount or 0),
            "result": r.result, "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "visit_seq": r.visit_seq, "visit_size": r.visit_size,
        } for r in rows]}


def group_catalog() -> list[dict[str, str]]:
    """Список разрезов для селектора в UI (порядок = порядок в меню)."""
    return [{"key": k, "label": v["label"], "family": v["family"]} for k, v in GROUPS.items()]
