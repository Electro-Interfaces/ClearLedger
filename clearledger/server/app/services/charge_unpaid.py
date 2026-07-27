"""Отпуск энергии без оплаты — разбор для вкладки «Надёжность → Без оплаты».

**Зачем отдельно.** «Сессия без отметки оплаты» на витринах — один ярлык на три
разных факта, и складывать их вместе нельзя:

  1. **Долг розницы** — ФЛ или аноним получил энергию, `paid_at` пуст. Это
     настоящая дыра: электричество ушло, денег нет и не будет.
  2. **Постоплата ЮЛ** — у корпоративных клиентов `paid_at` пуст ШТАТНО: они
     платят по счёту за период, а не за сессию. Это не потеря, а дебиторка;
     её надо контролировать (выставлен ли счёт), но не считать убытком.
     У них же `amount = 0` — реальная сумма живёт в `client_amount`
     (тарифная модель), поэтому выручку берём оттуда.
  3. **Неоплаченные пробы** — `paid_at` пуст и энергии нет. Платить не за что:
     это те же попытки подключения, что и в разборе визитов. В деньгах — ноль,
     но в счётчике «без оплаты» они раздувают долю и пугают зря.

На данных РусГидро разрыв нагляден: у розницы 4 984 сессии без оплаты, но
энергию получили только 30 из них (≈9,5 тыс. ₽) — остальное пробы. У ЮЛ же
7 385 сессий на 171 МВт·ч: это не убыток, а то, что должно превратиться в счёт.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scope import acl_params, acl_sql

from app.services.charge_visits import CHARGED_MIN_KWH, _as_date
from app.services.pii_account import mask_phone

# Сегмент сессии — та же логика, что в overview_service._segments и
# corporate_service (ключ = client_name), чтобы цифры сходились между разделами.
_SEG = """
    CASE WHEN client_name IS NOT NULL THEN 'corp'
         WHEN user_id IS NOT NULL THEN 'retail'
         ELSE 'anon' END
"""

# Выручка сессии: у ЮЛ amount=0 (постоплата), фактическая сумма — client_amount.
_REVENUE = "coalesce(NULLIF(client_amount, 0), amount)"

_BASE = f"""
WITH s AS (
    SELECT id, session_ext_id, started_at, station_code, station_name, region,
           connector_type, user_id, client_name, energy_kwh, tariff, result,
           {_SEG} AS seg,
           {_REVENUE} AS revenue,
           energy_kwh > :charged_min AS has_energy
      FROM charge_sessions
     WHERE company_id = :company_id
       AND paid_at IS NULL
       AND started_at >= CAST(:date_from AS date)
       AND started_at < CAST(:date_to AS date) + 1
       {{station_filter}}
)
"""


def _scoped(sql: str, stations: list[str] | None, regions: list[str] | None = None) -> str:
    # Скоуп участника (app/scope.py) — та же граница, что в списках объектов.
    flt = acl_sql("location_id")
    if stations is not None:
        flt += " AND station_code = ANY(:stations)"
    if regions is not None:
        # Регион — из справочника (Ф1.3): location_id → region_id → regions.name.
        flt += (" AND location_id IN (SELECT sl.id FROM service_locations sl"
                " JOIN regions r ON r.id = sl.region_id"
                " WHERE sl.company_id = :company_id AND r.name = ANY(:regions))")
    return _BASE.format(station_filter=flt) + sql


def _row(r: Any, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    """Строка результата → JSON-безопасный dict. NUMERIC приезжает Decimal и в
    JSON превращается в строку — на фронте такие «числа» молча ломают арифметику
    (сложение даёт склейку, toFixed падает)."""
    from decimal import Decimal

    return {k: (float(v) if isinstance(v, Decimal) else v)
            for k, v in dict(r).items() if k not in drop}


async def unpaid_report(
    db: AsyncSession, company_id, date_from: str, date_to: str,
    stations: list[str] | None = None, top: int = 15,
    regions: list[str] | None = None,
) -> dict[str, Any]:
    """Полный разбор неоплаченного отпуска: категории, станции, клиенты,
    динамика и поимённый реестр случаев розничного долга."""
    p = {"company_id": str(company_id), **acl_params(),
         "date_from": _as_date(date_from), "date_to": _as_date(date_to),
         "charged_min": CHARGED_MIN_KWH, "top": top}
    if stations is not None:
        p["stations"] = stations
    if regions is not None:
        p["regions"] = regions

    async def q(sql: str) -> list[Any]:
        return list((await db.execute(text(_scoped(sql, stations, regions)), p)).mappings().all())

    cats = await q("""
        SELECT seg, has_energy,
               count(*) AS sessions,
               coalesce(sum(energy_kwh), 0) AS kwh,
               coalesce(sum(revenue), 0) AS revenue,
               -- Для ЮЛ, у которых тарифная модель не проставила сумму, оценка
               -- по прайсу сессии — иначе объём молча выпадет из дебиторки.
               coalesce(sum(CASE WHEN revenue = 0 THEN energy_kwh * tariff ELSE 0 END), 0) AS by_tariff
          FROM s GROUP BY seg, has_energy
    """)

    def pick(seg: str, energy: bool) -> dict[str, float]:
        for r in cats:
            if r["seg"] == seg and bool(r["has_energy"]) is energy:
                return {"sessions": int(r["sessions"]), "kwh": float(r["kwh"]),
                        "revenue": float(r["revenue"]), "by_tariff": float(r["by_tariff"])}
        return {"sessions": 0, "kwh": 0.0, "revenue": 0.0, "by_tariff": 0.0}

    retail = pick("retail", True)
    anon = pick("anon", True)
    corp = pick("corp", True)
    probes = {  # без энергии — платить не за что, в деньги не идёт
        "sessions": sum(pick(s, False)["sessions"] for s in ("retail", "anon", "corp")),
    }
    # Долг розницы: ФЛ + аноним. Аноним не отделяем в KPI — взыскать не с кого
    # ни там, ни там, а дробление уводит внимание от суммы.
    debt = {
        "sessions": retail["sessions"] + anon["sessions"],
        "kwh": retail["kwh"] + anon["kwh"],
        "amount": retail["revenue"] + anon["revenue"]
                  + retail["by_tariff"] + anon["by_tariff"],
    }
    postpaid = {
        "sessions": corp["sessions"], "kwh": corp["kwh"],
        # Что должно уйти в счёт: тарифная сумма, а где её нет — оценка по прайсу.
        "amount": corp["revenue"] + corp["by_tariff"],
        "estimated": corp["revenue"] == 0 and corp["by_tariff"] > 0,
    }

    by_station = await q("""
        SELECT station_code,
               coalesce(max(station_name), station_code) || ' (' || station_code || ')' AS label,
               count(*) FILTER (WHERE has_energy AND seg <> 'corp') AS debt_sessions,
               coalesce(sum(CASE WHEN has_energy AND seg <> 'corp'
                                 THEN CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END ELSE 0 END), 0) AS debt_amount,
               count(*) FILTER (WHERE has_energy AND seg = 'corp') AS corp_sessions,
               coalesce(sum(CASE WHEN has_energy AND seg = 'corp' THEN energy_kwh ELSE 0 END), 0) AS corp_kwh,
               count(*) FILTER (WHERE NOT has_energy) AS probe_sessions
          FROM s WHERE station_code IS NOT NULL
         GROUP BY 1 HAVING count(*) FILTER (WHERE has_energy) > 0
         ORDER BY debt_amount DESC, corp_kwh DESC LIMIT :top
    """)

    # Корп-дебиторка по клиентам: кому выставлять счёт и на сколько.
    by_client = await q("""
        SELECT client_name AS label,
               count(*) AS sessions,
               coalesce(sum(energy_kwh), 0) AS kwh,
               coalesce(sum(CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END), 0) AS amount
          FROM s WHERE seg = 'corp' AND has_energy
         GROUP BY 1 ORDER BY amount DESC LIMIT :top
    """)

    # Динамика по месяцам: разовый сбой или систематическая протечка.
    trend = await q("""
        SELECT to_char(started_at, 'YYYY-MM') AS month,
               count(*) FILTER (WHERE has_energy AND seg <> 'corp') AS debt_sessions,
               coalesce(sum(CASE WHEN has_energy AND seg <> 'corp'
                                 THEN CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END ELSE 0 END), 0) AS debt_amount,
               count(*) FILTER (WHERE has_energy AND seg = 'corp') AS corp_sessions,
               coalesce(sum(CASE WHEN has_energy AND seg = 'corp' THEN energy_kwh ELSE 0 END), 0) AS corp_kwh
          FROM s GROUP BY 1 ORDER BY 1
    """)

    # Реестр аккаунтов: разовый сбой оплаты или клиент, который делает так
    # регулярно? Второе — уже не техника, а работа с клиентом, поэтому в списке
    # есть частота, разброс станций и давность.
    accounts = [
        {**_row(r, drop=("user_id",)), "account": mask_phone(r["user_id"]) if r["user_id"] else "без телефона"}
        for r in await q("""
        SELECT user_id,
               count(*) AS cases,
               coalesce(sum(energy_kwh), 0) AS kwh,
               coalesce(sum(CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END), 0) AS amount,
               count(DISTINCT station_code) AS stations,
               min(started_at) AS first_at,
               max(started_at) AS last_at
          FROM s WHERE has_energy AND seg <> 'corp'
         GROUP BY user_id ORDER BY amount DESC LIMIT :top
    """)]

    # Поимённый реестр розничного долга — случаев мало, их разбирают руками.
    cases = [
        {**_row(r, drop=("user_id", "client_name")),
         "client": mask_phone(r["user_id"]) if r["user_id"] else "без телефона"}
        for r in await q("""
        SELECT session_ext_id, started_at, station_name, station_code, region,
               connector_type, user_id, client_name, energy_kwh, tariff, result,
               CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END AS amount
          FROM s WHERE has_energy AND seg <> 'corp'
         ORDER BY amount DESC LIMIT :top
    """)]

    return {
        "totals": {
            "debt": debt,            # реальная дыра: энергия ушла, денег нет
            "postpaid": postpaid,    # дебиторка ЮЛ: ожидаемо, нужен счёт
            "probes": probes,        # без энергии: в деньгах ноль
        },
        "stations": [_row(r) for r in by_station],
        "clients": [_row(r) for r in by_client],
        "trend": [_row(r) for r in trend],
        "accounts": accounts,
        "cases": cases,
    }


async def unpaid_station_detail(
    db: AsyncSession, company_id, date_from: str, date_to: str, station_code: str,
) -> dict[str, Any]:
    """Детали одной станции: кто именно уехал не заплатив и какие ЮЛ ждут счёта.

    Открывается кликом по строке станции: сводная цифра без имён не даёт что
    делать дальше, а разбираются такие случаи поимённо."""
    p = {"company_id": str(company_id), **acl_params(),
         "date_from": _as_date(date_from), "date_to": _as_date(date_to),
         "charged_min": CHARGED_MIN_KWH, "code": station_code}

    async def q(sql: str) -> list[Any]:
        # Сужение задаём кодом станции, а не общим фильтром сети.
        sql_full = _BASE.format(station_filter="AND station_code = :code") + sql
        return list((await db.execute(text(sql_full), p)).mappings().all())

    retail = [
        {**_row(r, drop=("user_id", "client_name")),
         "client": mask_phone(r["user_id"]) if r["user_id"] else "без телефона"}
        for r in await q("""
        SELECT session_ext_id, started_at, connector_type, user_id, client_name,
               energy_kwh, tariff, result,
               CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END AS amount
          FROM s WHERE has_energy AND seg <> 'corp'
         ORDER BY started_at DESC
    """)]
    corp = [_row(r) for r in await q("""
        SELECT client_name AS label, count(*) AS sessions,
               coalesce(sum(energy_kwh), 0) AS kwh,
               coalesce(sum(CASE WHEN revenue > 0 THEN revenue ELSE energy_kwh * tariff END), 0) AS amount
          FROM s WHERE has_energy AND seg = 'corp'
         GROUP BY 1 ORDER BY amount DESC
    """)]
    probes = (await q("SELECT count(*) AS n FROM s WHERE NOT has_energy"))[0]["n"]

    return {
        "station_code": station_code,
        "retail": retail,
        "corp": corp,
        "probes": int(probes or 0),
    }
