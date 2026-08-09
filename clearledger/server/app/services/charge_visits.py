"""Визиты ЭЗС — склейка смежных попыток зарядки одного клиента в одно событие.

**Зачем.** CPO отдаёт каждую попытку подключения отдельной строкой сессии. Живой
случай: клиент подъехал, разъём не схватился, он вынул и вставил заново — три
строки, две с «CompleteError», третья реально заряжает. По сырым сессиям это
выглядит как 31% брака; по факту человек зарядился, просто не с первого раза.

Отсюда два РАЗНЫХ показателя, которые раньше сливались в один:

  • **Успех визита** — «человек уехал заряженным?» Это метрика для бизнеса и
    отчётности: 88,9% против 69% по сырым сессиям.
  • **Составные визиты** — «сколько раз ему пришлось тыкать?» Это метрика
    качества сети: 16 658 визитов, где зарядка получилась не сразу. Именно они
    и есть проблемный массив — он не исчезает при склейке, а наконец становится
    измеримым и адресным (станция, коннектор, клиент).

**Граница визита.** Разрыв между концом предыдущей сессии и началом следующей
у того же клиента на той же станции ≤ VISIT_GAP_MIN. Порог выбран по данным
прода (122 тыс. сессий): до 3 мин — 36 898 повторов, до 10 мин — 43 548, а
после 20 мин кривая выходит на ровный фон отдельных визитов. 15 мин лежит в
провале между этими режимами.

**Успех визита = отпущена энергия**, а не result='Complete'. Флаг CPO отвечает
на другой вопрос: 12 749 сессий Complete отпустили 0 кВтч, а 5 768 CompleteError
энергию всё-таки отдали.

Поля (visit_key/visit_seq/visit_size/visit_charged) пересчитываются целиком для
компании после каждой загрузки — инкрементально нельзя: новая сессия может
примкнуть к визиту, уже лежащему в базе, и изменить его размер и исход.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scope import acl_params, acl_sql

from app.services.pii_account import mask_phone

# Порог склейки, мин. Меняя — пересчитать визиты по всем компаниям: показатели
# надёжности сдвинутся, а старые значения останутся в кеше дашбордов.
VISIT_GAP_MIN = 15

# Сессия считается «зарядившей» при отпуске энергии выше этого порога, кВтч.
# 0 отсекает пробы подключения; поднимать до 0,5 не стали — на медленных AC
# короткая, но настоящая зарядка даёт десятые доли и клиентом воспринимается
# как состоявшаяся.
CHARGED_MIN_KWH = 0.0


_RECOMPUTE_SQL = text("""
WITH base AS (
    SELECT id, user_id, station_code, started_at, energy_kwh,
           CASE
               -- Сессии без клиента склеивать не с кем: у CPO это агрегатные или
               -- служебные записи, каждая сама себе визит.
               WHEN user_id IS NULL THEN 1
               WHEN lag(finished_at) OVER w IS NULL THEN 1
               -- Перекрытие по времени (разъём переподключён до закрытия сессии).
               WHEN started_at < lag(finished_at) OVER w THEN 0
               WHEN EXTRACT(EPOCH FROM (started_at - lag(finished_at) OVER w)) / 60.0
                    <= :gap_min THEN 0
               ELSE 1
           END AS is_new
    FROM charge_sessions
    WHERE company_id = :company_id
    WINDOW w AS (PARTITION BY user_id, station_code ORDER BY started_at, id)
),
grp AS (
    SELECT id, user_id, station_code, started_at, energy_kwh,
           sum(is_new) OVER (PARTITION BY user_id, station_code
                             ORDER BY started_at, id
                             ROWS UNBOUNDED PRECEDING) AS vno
    FROM base
),
fin AS (
    SELECT id,
           md5(coalesce(user_id, '-') || '|' || coalesce(station_code, '-')
               || '|' || CAST(vno AS text) || '|'
               || CAST(min(started_at) OVER p AS text)) AS vkey,
           row_number() OVER (PARTITION BY user_id, station_code, vno
                              ORDER BY started_at, id) AS vseq,
           count(*) OVER p AS vsize,
           bool_or(energy_kwh > :charged_min) OVER p AS vcharged
    FROM grp
    WINDOW p AS (PARTITION BY user_id, station_code, vno)
)
UPDATE charge_sessions cs
   SET visit_key     = fin.vkey,
       visit_seq     = fin.vseq,
       visit_size    = fin.vsize,
       visit_charged = fin.vcharged
  FROM fin
 WHERE cs.id = fin.id
   AND (cs.visit_key     IS DISTINCT FROM fin.vkey
     OR cs.visit_seq     IS DISTINCT FROM fin.vseq
     OR cs.visit_size    IS DISTINCT FROM fin.vsize
     OR cs.visit_charged IS DISTINCT FROM fin.vcharged)
""")


_STATS_SQL = text("""
SELECT count(*)                                              AS visits,
       count(*) FILTER (WHERE charged)                       AS charged,
       count(*) FILTER (WHERE charged AND size > 1)          AS retried,
       count(*) FILTER (WHERE NOT charged)                    AS failed,
       coalesce(sum(size), 0)                                AS sessions
  FROM (SELECT visit_key, max(visit_size) AS size, bool_or(visit_charged) AS charged
          FROM charge_sessions
         WHERE company_id = :company_id AND visit_key IS NOT NULL
         GROUP BY visit_key) v
""")


# Визит как единица отчёта. Станция/клиент/коннектор в визите одни и те же
# (они входят в ключ склейки либо не меняются), поэтому агрегаты по ним берутся
# как min/max — это не «случайное значение из группы», а единственное.
_VISIT_CTE = """
WITH v AS (
    SELECT visit_key,
           min(started_at)                        AS first_at,
           max(visit_size)                        AS attempts,
           bool_or(visit_charged)                 AS charged,
           min(station_code)                      AS station_code,
           max(station_name)                      AS station_name,
           min(region)                            AS region,
           min(user_id)                           AS user_id,
           max(client_name)                       AS client_name,
           max(connector_type)                    AS connector_type,
           sum(energy_kwh)                        AS kwh,
           -- Выручка по канону раздела: у ЮЛ amount = 0 (постоплата), реальная
           -- сумма лежит в client_amount. Пока тут стоял голый amount,
           -- «Надёжность» показывала за июль 5,18 млн ₽ против 5,53 млн ₽ на
           -- «Обзоре» — терялась вся корпоративная выручка.
           sum(coalesce(client_amount, amount))   AS amount,
           sum(duration_min)                      AS duration_min,
           bool_or(paid_at IS NOT NULL)           AS paid,
           -- Сессии-попытки, не давшие энергии: чистые потери времени клиента
           -- и занятости коннектора.
           count(*) FILTER (WHERE energy_kwh <= :charged_min) AS wasted
      FROM charge_sessions
     WHERE company_id = :company_id
       AND visit_key IS NOT NULL
       -- Верхняя граница включительно: date_to — это «по такое-то число»,
       -- а не «до полуночи такого-то», иначе теряется весь последний день.
       -- CAST, а не «::» — SQLAlchemy принимает двойное двоеточие за параметр.
       AND started_at >= CAST(:date_from AS date)
       AND started_at < CAST(:date_to AS date) + 1
       {station_filter}
     GROUP BY visit_key
)
"""


def _as_date(v: str | date) -> date:
    """'YYYY-MM-DD' → date. Дата-время режем до дня: границы периода в отчёте
    суточные, время в них смысла не несёт."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _scoped(sql: str, stations: list[str] | None, regions: list[str] | None = None) -> str:
    """Подставить сужение по сети. Пустой список ≠ None: пустой означает «контур
    выбран, но станций в нём нет» — тогда отчёт обязан быть пустым, а не сетевым.
    Регион — из справочника (Ф1.3): через location_id → region_id → regions.name.
    Скоуп участника (app/scope.py) — та же граница, что в списках объектов."""
    flt = acl_sql("location_id")
    if stations is not None:
        flt += " AND station_code = ANY(:stations)"
    if regions is not None:
        flt += (" AND location_id IN (SELECT sl.id FROM service_locations sl"
                " JOIN regions r ON r.id = sl.region_id"
                " WHERE sl.company_id = :company_id AND r.name = ANY(:regions))")
    return (_VISIT_CTE.format(station_filter=flt)) + sql


async def visits_report(
    db: AsyncSession, company_id, date_from: str, date_to: str,
    stations: list[str] | None = None, top: int = 15,
    regions: list[str] | None = None,
) -> dict[str, Any]:
    """Разбор составных визитов для таба «Повторные попытки».

    Отвечает на три вопроса сразу: сколько людей всё-таки зарядилось (успех
    визита), скольким для этого пришлось тыкать разъём повторно (проблемный
    массив) и где именно это происходит — станция, коннектор, регион, клиент.
    """
    # asyncpg типизирует параметр по CAST в запросе и строку не примет.
    p = {"company_id": str(company_id), **acl_params(),
         "date_from": _as_date(date_from), "date_to": _as_date(date_to),
         "charged_min": CHARGED_MIN_KWH, "top": top}
    if stations is not None:
        p["stations"] = stations
    if regions is not None:
        p["regions"] = regions

    async def q(sql: str) -> list[Any]:
        return list((await db.execute(text(_scoped(sql, stations, regions)), p)).mappings().all())

    totals = (await q("""
        SELECT count(*)                                          AS visits,
               count(*) FILTER (WHERE charged)                   AS charged,
               count(*) FILTER (WHERE charged AND attempts > 1)  AS retried,
               count(*) FILTER (WHERE NOT charged)               AS failed,
               count(*) FILTER (WHERE charged AND NOT paid)      AS unpaid,
               coalesce(sum(attempts), 0)                        AS sessions,
               coalesce(sum(wasted), 0)                          AS wasted_sessions,
               coalesce(sum(amount), 0)                          AS amount,
               coalesce(sum(kwh), 0)                             AS kwh,
               coalesce(max(attempts), 0)                        AS max_attempts
          FROM v
    """))[0]

    # Распределение по числу попыток: 1 — сразу, 2-3 — терпимо, 4+ — клиент
    # борется с оборудованием. Хвост схлопываем, иначе таблица уезжает в 40 строк.
    dist = await q("""
        SELECT CASE WHEN attempts >= 6 THEN 6 ELSE attempts END AS attempts,
               count(*) AS visits,
               count(*) FILTER (WHERE charged) AS charged,
               coalesce(sum(kwh), 0) AS kwh
          FROM v GROUP BY 1 ORDER BY 1
    """)

    def by(dim: str, label_expr: str, min_visits: int = 10, extra: str = "") -> str:
        return f"""
        SELECT {label_expr} AS label,{extra}
               count(*) AS visits,
               count(*) FILTER (WHERE charged) AS charged,
               count(*) FILTER (WHERE charged AND attempts > 1) AS retried,
               count(*) FILTER (WHERE NOT charged) AS failed,
               coalesce(sum(attempts), 0) AS sessions,
               coalesce(sum(wasted), 0) AS wasted,
               coalesce(sum(amount), 0) AS amount,
               round(CAST(avg(attempts) AS numeric), 2) AS avg_attempts
          FROM v WHERE {dim} IS NOT NULL
         GROUP BY 1 HAVING count(*) >= {min_visits}
         ORDER BY CAST(count(*) FILTER (WHERE charged AND attempts > 1) AS float)
                  / NULLIF(count(*), 0) DESC, count(*) DESC, label
         LIMIT :top
        """

    stations_rows = await q(by("station_code",
                               "coalesce(station_name, station_code) || ' (' || station_code || ')'"))
    connectors = await q(by("connector_type", "connector_type", min_visits=1))
    # ⚠ НЕ переприсваивать `regions` — это параметр-фильтр, который читает q()
    # ниже (clients/worst). Иначе _scoped увидит truthy-список и добавит :regions
    # в SQL, а params собраны со старым фильтром → «bind parameter regions».
    regions_rows = await q(by("region", "region", min_visits=1))
    # Клиенты: у ЮЛ — название организации, у ФЛ — маскированный телефон.
    # Сырой номер за пределы бэкенда не отдаём (как в «Частных лицах»).
    clients = [
        {**{k: val for k, val in dict(r).items() if k != "client_name"},
         "label": r["client_name"] or mask_phone(r["label"])}
        for r in await q(by("user_id", "user_id", extra=" max(client_name) AS client_name,"))
    ]

    # Самые тяжёлые визиты — конкретные случаи, которые можно поднять в поддержке.
    worst = [
        {**{k: val for k, val in dict(r).items() if k not in ("user_id", "client_name")},
         "client": r["client_name"] or mask_phone(r["user_id"])}
        for r in await q("""
        SELECT visit_key, first_at, attempts, charged, wasted,
               coalesce(station_name, station_code) AS station, station_code,
               region, connector_type, client_name, user_id,
               kwh, amount, duration_min
          FROM v WHERE attempts > 1
         ORDER BY attempts DESC, duration_min DESC, visit_key LIMIT :top
    """)]

    visits = int(totals["visits"] or 0)
    charged = int(totals["charged"] or 0)
    retried = int(totals["retried"] or 0)
    sessions = int(totals["sessions"] or 0)

    return {
        "gap_min": VISIT_GAP_MIN,
        "totals": {
            "visits": visits,
            "sessions": sessions,
            "charged": charged,
            "failed": int(totals["failed"] or 0),
            "retried": retried,
            "unpaid": int(totals["unpaid"] or 0),
            "wasted_sessions": int(totals["wasted_sessions"] or 0),
            "max_attempts": int(totals["max_attempts"] or 0),
            "amount": float(totals["amount"] or 0),
            "kwh": float(totals["kwh"] or 0),
            # Успех визита — «человек уехал заряженным». Главная цифра раздела.
            "success_pct": round(charged / visits * 100, 1) if visits else 0.0,
            # Успех по сырым сессиям — оставляем рядом, чтобы разрыв между
            # двумя показателями был виден, а не «исправился» молча.
            "session_success_pct": round((sessions - int(totals["wasted_sessions"] or 0))
                                         / sessions * 100, 1) if sessions else 0.0,
            "retried_pct": round(retried / charged * 100, 1) if charged else 0.0,
        },
        "distribution": [dict(r) for r in dist],
        "stations": [dict(r) for r in stations_rows],
        "connectors": [dict(r) for r in connectors],
        "regions": [dict(r) for r in regions_rows],
        "clients": [dict(r) for r in clients],
        "worst": [dict(r) for r in worst],
    }


# Бакет визита = бакет его ПЕРВОЙ сессии (визит атрибутируется моменту, когда
# клиент подъехал). Форматы строк совпадают с analytics_service._cs_bucket_axis,
# иначе спарклайн не ляжет на ось обзора.
_BUCKET_EXPR = {
    "day": "to_char(first_at, 'YYYY-MM-DD')",
    "week": "to_char(date_trunc('week', first_at), 'YYYY-MM-DD')",
    "decade": ("to_char(first_at, 'YYYY-MM') || '-Д' || "
               "CASE WHEN EXTRACT(day FROM first_at) <= 10 THEN 1 "
               "WHEN EXTRACT(day FROM first_at) <= 20 THEN 2 ELSE 3 END"),
    "month": "to_char(first_at, 'YYYY-MM')",
    "quarter": "to_char(first_at, 'YYYY') || '-Q' || to_char(first_at, 'Q')",
}


async def visit_success(
    db: AsyncSession, company_id, date_from, date_to,
    stations: list[str] | None = None, regions: list[str] | None = None,
) -> dict[str, Any]:
    """Успех на уровне визитов за период — KPI обзора «Зарядились»."""
    rows = await _q(db, company_id, date_from, date_to, stations, """
        SELECT count(*) AS visits,
               count(*) FILTER (WHERE charged) AS charged,
               count(*) FILTER (WHERE charged AND attempts > 1) AS retried
          FROM v
    """, regions=regions)
    r = rows[0]
    visits, charged = int(r["visits"] or 0), int(r["charged"] or 0)
    return {
        "visits": visits, "charged": charged, "retried": int(r["retried"] or 0),
        "success_pct": round(charged / visits * 100, 1) if visits else 0.0,
    }


async def visit_success_series(
    db: AsyncSession, company_id, date_from, date_to, bucket: str,
    stations: list[str] | None = None, regions: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """Визиты и их успех по бакетам → спарклайны обзора. Ключи совпадают с осью
    `_cs_bucket_axis`, пустые бакеты заполняет вызывающий."""
    expr = _BUCKET_EXPR.get(bucket)
    if expr is None:
        return {}
    rows = await _q(db, company_id, date_from, date_to, stations, f"""
        SELECT {expr} AS b,
               count(*) AS visits,
               count(*) FILTER (WHERE charged) AS charged
          FROM v GROUP BY 1
    """, regions=regions)
    return {r["b"]: {"visits": int(r["visits"]),
                     "success_pct": round(int(r["charged"]) / int(r["visits"]) * 100, 1)}
            for r in rows if int(r["visits"] or 0) > 0}


async def visit_success_by_station(
    db: AsyncSession, company_id, date_from, date_to,
    stations: list[str] | None = None, min_visits: int = 30,
    regions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Успех визитов по станциям — станции риска в алертах обзора. Порог
    min_visits отсекает станции, где 2 визита из 3 дают «33% успеха»."""
    rows = await _q(db, company_id, date_from, date_to, stations, f"""
        SELECT station_code,
               max(coalesce(station_name, station_code)) AS station_name,
               count(*) AS visits,
               count(*) FILTER (WHERE charged) AS charged
          FROM v WHERE station_code IS NOT NULL
         GROUP BY station_code HAVING count(*) >= {int(min_visits)}
    """, regions=regions)
    return [{
        "code": r["station_code"],
        "label": f"{r['station_name']} ({r['station_code']})",
        "visits": int(r["visits"]),
        "success_pct": round(int(r["charged"]) / int(r["visits"]) * 100, 1),
    } for r in rows]


async def _q(db: AsyncSession, company_id, date_from, date_to,
             stations: list[str] | None, sql: str,
             regions: list[str] | None = None) -> list[Any]:
    p = {"company_id": str(company_id), **acl_params(),
         "date_from": _as_date(date_from), "date_to": _as_date(date_to),
         "charged_min": CHARGED_MIN_KWH}
    if stations is not None:
        p["stations"] = stations
    if regions is not None:
        p["regions"] = regions
    return list((await db.execute(text(_scoped(sql, stations, regions)), p)).mappings().all())


async def recompute_visits(
    db: AsyncSession, company_id, gap_min: int = VISIT_GAP_MIN,
) -> dict[str, Any]:
    """Пересчитать визиты компании целиком. Вызывается после загрузки сессий.

    Возвращает сводку для лога канала: сколько визитов, какая доля успешных и
    сколько из них потребовали повторных попыток.
    """
    res = await db.execute(_RECOMPUTE_SQL, {
        "company_id": str(company_id), **acl_params(), "gap_min": gap_min,
        "charged_min": CHARGED_MIN_KWH,
    })
    touched = int(res.rowcount or 0)
    await db.flush()

    row = (await db.execute(_STATS_SQL, {"company_id": str(company_id)})).one()
    visits = int(row.visits or 0)
    charged = int(row.charged or 0)
    retried = int(row.retried or 0)

    return {
        "visits": visits,
        "sessions": int(row.sessions or 0),
        "charged": charged,
        "failed": int(row.failed or 0),
        "retried": retried,
        "touched": touched,
        "gap_min": gap_min,
        "success_pct": round(charged / visits * 100, 1) if visits else 0.0,
        "retried_pct": round(retried / charged * 100, 1) if charged else 0.0,
    }
