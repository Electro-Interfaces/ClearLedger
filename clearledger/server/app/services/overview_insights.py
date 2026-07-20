"""Аналитика состояния сети ЭЗС для обзора — то, что видно в данных, но не в KPI.

Обзор отвечал на вопрос «сколько сеть заработала». Эти блоки отвечают на другой:
**где сеть не работает и где на самом деле лежат деньги.** Все они опираются на
уже связанные данные, новых источников не требуют.

  • `silent_stations` — станции без единой сессии за период. На проде это 130 из
    557: почти четверть парка. Счётчик «активных ЭЗС» такую дыру не показывает —
    он говорит, сколько станций работало, а не сколько простаивало.
  • `revenue_concentration` — квинтили станций по выручке. Топ-20% дают 74,5%,
    нижние 20% — 0,1% (247 ₽ за 7 месяцев со станции). Средняя загрузка по сети
    (1,4%) такие полюса смешивает и потому бесполезна.
  • `client_segments` — розница по частоте визитов. 460 человек (4,8% базы) дают
    37,5% выручки; 3 537 разовых — 5,8%. Меняет приоритет с привлечения на
    удержание.
  • `region_extremes` — лучшие и худшие регионы по выручке и доле зарядившихся.
  • `energy_reconciliation` — сессии против реестров РусГидро: расхождение есть
    всегда, и честнее его показать, чем молча выбрать одну из двух цифр.

**Ключ станции.** Связь сессия→объект живёт ТОЛЬКО в `charge_sessions.location_id`.
Прямое сравнение `service_locations.code = charge_sessions.station_code` даёт 90
совпадений из 557: у CPO код обрастает суффиксами блоков («584-1») и ведущими
пробелами. Любой запрос по кодам «в лоб» покажет чушь — джойнить по location_id.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Выручка сессии: у ЮЛ amount=0 (постоплата), фактическая сумма — client_amount.
_REVENUE = "coalesce(NULLIF(client_amount, 0), amount)"

# Боевой парк ЭЗС: без тестовых прогонов и выведенных из эксплуатации. Тот же
# критерий, что в ops_dashboard и stations_model_service — иначе «всего ЭЗС»
# в разных разделах разойдётся.
#
# ⚠ type = 'ev_charging' обязателен: в service_locations лежат и склады
# оборудования (WH-KHV, WH-VVO). Без фильтра они попадали в «молчащие ЭЗС» —
# склад по определению не даёт зарядных сессий, и парк раздувался на 3 объекта.
_NET = """
    SELECT id, code, name, region_id, operational_status, city
      FROM service_locations
     WHERE company_id = :company_id
       AND type = 'ev_charging'
       AND NOT is_test
       AND coalesce(operational_status, '') <> 'decommissioned'
"""


def _f(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _rows(res: Any) -> list[dict[str, Any]]:
    return [{k: _f(v) for k, v in dict(r).items()} for r in res.mappings().all()]


async def silent_stations(
    db: AsyncSession, company_id, date_from: date, date_to: date, limit: int = 200,
) -> dict[str, Any]:
    """Станции парка, не давшие ни одной сессии за период.

    Отдельно считаем тех, у кого сессий не было НИКОГДА (скорее всего не
    подключены или не запущены) и тех, кто раньше работал, а теперь замолчал —
    это разные истории: первая про запуск, вторая про поломку или демонтаж.
    """
    ctes = f"""
        WITH net AS ({_NET}),
        act AS (
            SELECT DISTINCT location_id FROM charge_sessions
             WHERE company_id = :company_id AND location_id IS NOT NULL
               AND started_at >= CAST(:date_from AS date)
               AND started_at < CAST(:date_to AS date) + 1
        ),
        ever AS (
            SELECT location_id, max(started_at) AS last_at, count(*) AS sessions
              FROM charge_sessions
             WHERE company_id = :company_id AND location_id IS NOT NULL
             GROUP BY location_id
        )
    """
    params = {"company_id": str(company_id), "date_from": date_from, "date_to": date_to}
    # Список для показа — усечён LIMIT; tie-break по коду для стабильного порядка
    # среди станций с одинаковым last_at (иначе состав «хвоста» плавает).
    rows = _rows(await db.execute(text(ctes + """
        SELECT n.id, n.code, n.name, n.city, n.operational_status,
               e.last_at, coalesce(e.sessions, 0) AS sessions_ever
          FROM net n
          LEFT JOIN act a ON a.location_id = n.id
          LEFT JOIN ever e ON e.location_id = n.id
         WHERE a.location_id IS NULL
         ORDER BY e.last_at DESC NULLS LAST, n.code
         LIMIT :limit
    """), {**params, "limit": limit}))
    # Счётчики — по ПОЛНОМУ набору молчащих, не по усечённому списку: иначе при
    # молчащих > limit доля silent_pct занижена и цифра врёт (это уже не «мигание»,
    # а систематически неверное число).
    st = (await db.execute(text(ctes + """
        SELECT count(*) AS silent,
               count(*) FILTER (WHERE coalesce(e.sessions, 0) = 0) AS never
          FROM net n
          LEFT JOIN act a ON a.location_id = n.id
          LEFT JOIN ever e ON e.location_id = n.id
         WHERE a.location_id IS NULL
    """), params)).one()
    silent = int(st.silent or 0)
    never = int(st.never or 0)
    total = (await db.execute(text(f"SELECT count(*) FROM ({_NET}) t"),
                              {"company_id": str(company_id)})).scalar_one()
    return {
        "stations": rows,
        "silent": silent,
        "never_worked": never,
        "went_quiet": silent - never,
        "total": int(total or 0),
        "silent_pct": round(silent / total * 100, 1) if total else 0.0,
    }


async def revenue_concentration(
    db: AsyncSession, company_id, date_from: date, date_to: date,
) -> list[dict[str, Any]]:
    """Квинтили станций по выручке: где сеть зарабатывает, а где тратит ТОиР."""
    sql = text(f"""
        WITH st AS (
            SELECT location_id,
                   sum({_REVENUE}) AS rev,
                   count(DISTINCT visit_key) AS visits
              FROM charge_sessions
             WHERE company_id = :company_id AND location_id IS NOT NULL
               AND started_at >= CAST(:date_from AS date)
               AND started_at < CAST(:date_to AS date) + 1
             GROUP BY location_id
        ),
        q AS (SELECT *, ntile(5) OVER (ORDER BY rev DESC) AS bucket FROM st)
        SELECT bucket, count(*) AS stations,
               coalesce(sum(rev), 0) AS revenue,
               coalesce(sum(visits), 0) AS visits,
               coalesce(round(avg(rev)), 0) AS avg_per_station
          FROM q GROUP BY bucket ORDER BY bucket
    """)
    rows = _rows(await db.execute(sql, {
        "company_id": str(company_id), "date_from": date_from, "date_to": date_to}))
    total = sum(r["revenue"] for r in rows) or 1
    labels = {1: "Топ 20%", 2: "2-я пятая", 3: "Середина", 4: "4-я пятая", 5: "Нижние 20%"}
    for r in rows:
        r["label"] = labels.get(int(r["bucket"]), str(r["bucket"]))
        r["share_pct"] = round(r["revenue"] / total * 100, 1)
    return rows


async def client_segments(
    db: AsyncSession, company_id, date_from: date, date_to: date,
) -> dict[str, Any]:
    """Розничная база по частоте визитов: ядро против разовых.

    Считаем по ВИЗИТАМ, а не сессиям: иначе клиент, у которого разъём схватился
    с третьего раза, выглядел бы втрое лояльнее, чем есть.
    """
    sql = text(f"""
        WITH c AS (
            SELECT user_id,
                   count(DISTINCT visit_key) AS visits,
                   sum({_REVENUE}) AS rev
              FROM charge_sessions
             WHERE company_id = :company_id
               AND user_id IS NOT NULL AND client_name IS NULL
               AND started_at >= CAST(:date_from AS date)
               AND started_at < CAST(:date_to AS date) + 1
             GROUP BY user_id
        )
        SELECT CASE WHEN visits = 1 THEN 1 WHEN visits <= 3 THEN 2
                    WHEN visits <= 10 THEN 3 WHEN visits <= 30 THEN 4 ELSE 5 END AS tier,
               count(*) AS clients,
               coalesce(sum(rev), 0) AS revenue,
               coalesce(sum(visits), 0) AS visits
          FROM c GROUP BY 1 ORDER BY 1
    """)
    rows = _rows(await db.execute(sql, {
        "company_id": str(company_id), "date_from": date_from, "date_to": date_to}))
    labels = {1: "Разовые (1 визит)", 2: "2–3 визита", 3: "4–10", 4: "11–30", 5: "Ядро (31+)"}
    total_rev = sum(r["revenue"] for r in rows) or 1
    total_cl = sum(r["clients"] for r in rows) or 1
    for r in rows:
        r["label"] = labels.get(int(r["tier"]), str(r["tier"]))
        r["rev_share"] = round(r["revenue"] / total_rev * 100, 1)
        r["client_share"] = round(r["clients"] / total_cl * 100, 1)
    core = next((r for r in rows if int(r["tier"]) == 5), None)
    once = next((r for r in rows if int(r["tier"]) == 1), None)
    return {
        "tiers": rows,
        "clients": int(total_cl),
        # Ядро и разовые вынесены отдельно: на них строится вывод «удерживать
        # или привлекать», остальные ряды — контекст.
        "core_clients": int(core["clients"]) if core else 0,
        "core_rev_share": core["rev_share"] if core else 0.0,
        "once_clients": int(once["clients"]) if once else 0,
        "once_rev_share": once["rev_share"] if once else 0.0,
    }


async def region_extremes(
    db: AsyncSession, company_id, date_from: date, date_to: date, top: int = 5,
) -> dict[str, Any]:
    """Регионы: выручка и доля зарядившихся. Успех — по визитам, как в KPI."""
    sql = text(f"""
        WITH v AS (
            -- Регион — из справочника (единый источник истины), а не из денорм
            -- charge_sessions.region: сессия→объект→регион. company_id неоднозначен
            -- при join трёх таблиц → префиксуем cs.
            SELECT cs.visit_key, min(r.name) AS region,
                   max(cs.visit_charged::int) AS charged,
                   sum({_REVENUE}) AS rev
              FROM charge_sessions cs
              LEFT JOIN service_locations sl ON sl.id = cs.location_id
              LEFT JOIN regions r ON r.id = sl.region_id
             WHERE cs.company_id = :company_id AND cs.visit_key IS NOT NULL
               AND cs.started_at >= CAST(:date_from AS date)
               AND cs.started_at < CAST(:date_to AS date) + 1
             GROUP BY cs.visit_key
        )
        SELECT coalesce(region, '—') AS label,
               count(*) AS visits,
               sum(charged) AS charged,
               coalesce(sum(rev), 0) AS revenue
          FROM v GROUP BY 1 HAVING count(*) >= 50
         ORDER BY revenue DESC
    """)
    rows = _rows(await db.execute(sql, {
        "company_id": str(company_id), "date_from": date_from, "date_to": date_to}))
    for r in rows:
        r["success_pct"] = round(r["charged"] / r["visits"] * 100, 1) if r["visits"] else 0.0
    by_success = sorted(rows, key=lambda r: r["success_pct"])
    return {
        "top_revenue": rows[:top],
        "worst_success": by_success[:top],
        "regions": len(rows),
    }


async def energy_reconciliation(
    db: AsyncSession, company_id, date_from: date, date_to: date,
) -> dict[str, Any] | None:
    """Сессии против реестров РусГидро за пересекающиеся месяцы.

    Реестр (`station_energy_periods`) — помесячный отпуск по счётчикам, сессии —
    транзакционный поток CPO. Они не обязаны совпадать до киловатта, но разрыв
    надо видеть: если он растёт, одна из витрин перестала отражать реальность.
    Возвращает None, когда реестров за период нет — блок тогда не рисуем.
    """
    sql = text(f"""
        WITH months AS (
            SELECT to_char(started_at, 'YYYY-MM') AS period,
                   sum(energy_kwh) AS session_kwh
              FROM charge_sessions
             WHERE company_id = :company_id
               AND started_at >= CAST(:date_from AS date)
               AND started_at < CAST(:date_to AS date) + 1
             GROUP BY 1
        ),
        reg AS (
            -- period в реестре — первое число месяца ('2026-06-01'), а не 'YYYY-MM'.
            -- Без обрезки джойн не находит ни одной пары и блок молча пустеет.
            SELECT left(period, 7) AS period, sum(intake_kwh) AS registry_kwh
              FROM station_energy_periods
             WHERE company_id = :company_id
             GROUP BY 1
        )
        SELECT m.period, m.session_kwh, r.registry_kwh
          FROM months m JOIN reg r ON r.period = m.period
         ORDER BY m.period
    """)
    rows = _rows(await db.execute(sql, {
        "company_id": str(company_id), "date_from": date_from, "date_to": date_to}))
    if not rows:
        return None

    # Месяц, где реестр покрывает меньше 60% отпуска по сессиям, — это НЕ
    # расхождение витрин, а недогруженный реестр: на проде за июнь загружено
    # 6 МВт·ч против 198 МВт·ч по сессиям, и «расхождение +3193%» было бы
    # прямой дезинформацией. Такие месяцы помечаем и исключаем из итога,
    # иначе они утаскивают общую цифру в бессмыслицу.
    INCOMPLETE_BELOW = 60.0
    for r in rows:
        s, g = r["session_kwh"] or 0, r["registry_kwh"] or 0
        r["diff_kwh"] = round(s - g, 1)
        r["diff_pct"] = round((s - g) / g * 100, 1) if g else None
        r["coverage_pct"] = round(g / s * 100, 1) if s else None
        r["incomplete"] = bool(s and (g / s * 100) < INCOMPLETE_BELOW)

    solid = [r for r in rows if not r["incomplete"]]
    ts = sum(r["session_kwh"] or 0 for r in solid)
    tr = sum(r["registry_kwh"] or 0 for r in solid)
    incomplete = [r["period"] for r in rows if r["incomplete"]]
    return {
        "months": rows,
        "session_kwh": round(ts, 1),
        "registry_kwh": round(tr, 1),
        "diff_kwh": round(ts - tr, 1),
        "diff_pct": round((ts - tr) / tr * 100, 1) if tr else None,
        # Месяцы, где реестр явно не догружен — их надо не сверять, а дозагрузить.
        "incomplete_months": incomplete,
        "compared_months": len(solid),
    }
