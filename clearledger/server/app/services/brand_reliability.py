"""Надёжность станций в разрезе ПРОИЗВОДИТЕЛЯ оборудования — на модели визитов.

Отвечает на «оборудование какого вендора надёжнее работает у клиента»: по этому
планируют ТОиР и предъявляют поставщику. Считается на ТОЙ ЖЕ склейке визитов
(`charge_visits.py`), что и вкладка «Повторные попытки», — поэтому цифры между
вкладками сходятся, а не расходятся (условие доверия менеджера).

Единицы счёта (важно не путать — от них зависит смысл процентов):
  • сессия — одна строка CPO = одно касание разъёма;
  • визит  — все попытки одного клиента на одной станции подряд (разрыв ≤15 мин)
             склеены в одно событие «человек приехал зарядиться».

Метрики (все — доля ОТ ЯВНО НАЗВАННОЙ базы):
  • успех визита %   = зарядившиеся визиты ÷ все визиты. «Человек уехал
                       заряженным» (отпущена энергия, а не флаг Complete от CPO);
  • повторных сессий = сессий − визитов (лишние переподключения разъёма);
  • неудачных сессий = сессии без отпуска энергии (пробы/сорвы);
  • ср. попыток      = сессий ÷ визитов (1.0 = всегда с первой);
  • станция риска    = ≥30 визитов И успех визита <80% (кандидат на ТОиР).

Паспортную мощность станции (`power_kwt`) отдаём как справку для карточки станции,
но НЕ считаем «факт против паспорта»: сырое отношение шумит на коротких сессиях,
превышает 100% при простое соседних портов и держится на допущении «power_kwt =
вся станция» — для надёжностной вкладки это не однозначный показатель (решение
МАГа 21.07). Надёжность меряем визитами.

Наружу отдаём ПЛОСКИЙ список станций с брендом и сырыми счётчиками: фронт сам
группирует по вендору / показывает списком, сортирует и ищет, а бренд-итоги
собирает суммированием (визит принадлежит одной станции — итоги сходятся).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scope import acl_params, acl_sql

from app.services.charge_grouping import _BRAND_CANON
from app.services.charge_visits import CHARGED_MIN_KWH, VISIT_GAP_MIN, _as_date

NO_BRAND = "— (нет бренда)"
#: Станция риска: заметный поток визитов и низкий успех — не единичный сбой.
RISK_MIN_VISITS = 30
RISK_SUCCESS_PCT = 80.0


def _canon_brand(raw: str | None) -> str:
    """Каноническое имя вендора (снимает гомоглифы «StarCharge»/«StarСharge»,
    «PSS»/«ПСС»). Пусто/None → группа «нет бренда». Тот же словарь, что в БД-разрезе
    `charge_grouping._BRAND_EXPR`, — иначе один вендор размазан по написаниям."""
    if not raw or not raw.strip():
        return NO_BRAND
    key = raw.strip().upper()
    return _BRAND_CANON.get(key, raw.strip())


def _scope_fragment(stations: list[str] | None, regions: list[str] | None,
                    user_type: str | None) -> str:
    """Фрагменты WHERE для сужения выборки сессий (сеть/регион/тип клиента).

    Регион — из справочника (location_id → region_id → regions.name), не из
    денорм-колонки. Пустой список ≠ None: пустой = «контур выбран, станций нет» →
    отчёт обязан быть пустым. Фрагменты фиксированные, значения — через bind.
    Скоуп участника (app/scope.py) — та же граница, что в списках объектов."""
    flt = acl_sql("location_id")
    if stations is not None:
        flt += " AND station_code = ANY(:stations)"
    if regions is not None:
        flt += (" AND location_id IN (SELECT sl.id FROM service_locations sl"
                " JOIN regions r ON r.id = sl.region_id"
                " WHERE sl.company_id = :company_id AND r.name = ANY(:regions))")
    if user_type:
        flt += " AND user_type = :user_type"
    return flt


_STATION_SQL = """
WITH v AS (
    SELECT visit_key,
           min(station_code)                     AS station_code,
           min(location_id)                      AS location_id,
           max(station_name)                     AS station_name,
           bool_or(visit_charged)                AS charged,
           -- attempts = полный размер визита (как в charge_visits): суммируется в
           -- «сессий», чтобы цифры сходились с вкладкой «Повторные попытки».
           max(visit_size)                       AS attempts,
           count(*) FILTER (WHERE energy_kwh <= :charged_min) AS wasted,
           coalesce(sum(energy_kwh), 0)          AS kwh,
           coalesce(sum(coalesce(client_amount, amount)), 0) AS amount
      FROM charge_sessions
     WHERE company_id = :company_id
       -- Верхняя граница включительно: date_to — «по такое-то число».
       AND started_at >= CAST(:date_from AS date)
       AND started_at <  CAST(:date_to AS date) + 1
       AND visit_key IS NOT NULL
       {scope}
     GROUP BY visit_key
)
SELECT v.station_code                              AS code,
       max(v.station_name)                         AS station_name,
       -- Бренд/паспорт — из справочника, join ТОЛЬКО по location_id (не по коду:
       -- у CPO код обрастает суффиксами блоков и ведущими пробелами).
       max(btrim(l.brand))                         AS brand_raw,
       count(*)                                    AS visits,
       count(*) FILTER (WHERE v.charged)           AS charged_visits,
       count(*) FILTER (WHERE NOT v.charged)       AS failed_visits,
       count(*) FILTER (WHERE v.charged AND v.attempts > 1) AS retried_visits,
       coalesce(sum(v.attempts), 0)                AS sessions,
       coalesce(sum(v.wasted), 0)                  AS wasted_sessions,
       coalesce(sum(v.kwh), 0)                     AS energy,
       coalesce(sum(v.amount), 0)                  AS amount,
       max(l.power_kwt)                            AS power_kwt,
       max(l.connectors_count)                     AS connectors
  FROM v
  LEFT JOIN service_locations l ON l.id = v.location_id
 GROUP BY v.station_code
"""


async def brand_reliability(
    db: AsyncSession, company_id, date_from: str, date_to: str,
    *, stations: list[str] | None = None, regions: list[str] | None = None,
    user_type: str | None = None,
) -> dict[str, Any]:
    """Плоский список станций с метриками надёжности + бренд + сырые счётчики."""
    p: dict[str, Any] = {
        "company_id": str(company_id), **acl_params(),
        "date_from": _as_date(date_from), "date_to": _as_date(date_to),
        "charged_min": CHARGED_MIN_KWH,
    }
    if stations is not None:
        p["stations"] = stations
    if regions is not None:
        p["regions"] = regions
    if user_type:
        p["user_type"] = user_type

    sql = _STATION_SQL.format(scope=_scope_fragment(stations, regions, user_type))
    rows = (await db.execute(text(sql), p)).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        visits = int(r["visits"] or 0)
        charged_v = int(r["charged_visits"] or 0)
        failed_v = int(r["failed_visits"] or 0)
        retried_v = int(r["retried_visits"] or 0)
        sessions = int(r["sessions"] or 0)
        wasted = int(r["wasted_sessions"] or 0)
        pw = float(r["power_kwt"]) if r["power_kwt"] is not None else None
        conn = int(r["connectors"]) if r["connectors"] else 0
        v_succ = (charged_v / visits * 100.0) if visits else 0.0
        code = r["code"]
        name = r["station_name"] or code or "—"
        out.append({
            "code": code,
            "label": f"{name} ({code})" if code else name,
            "brand": _canon_brand(r["brand_raw"]),
            "visits": visits,
            "charged_visits": charged_v,
            "failed_visits": failed_v,
            "retried_visits": retried_v,
            "sessions": sessions,
            # Повторных сессий = лишние переподключения (все касания сверх одного
            # на визит). Неудачных сессий = без отпуска энергии.
            "repeat_sessions": max(sessions - visits, 0),
            "wasted_sessions": wasted,
            "visit_success_pct": round(v_succ, 1),
            # Отпуск энергии по СЕССИЯМ (доля касаний, давших ток) — «сырой» успех
            # оборудования, ниже успеха визита; оставляем для сверки.
            "charged_pct": round((sessions - wasted) / sessions * 100, 1) if sessions else 0.0,
            "failed_pct": round(failed_v / visits * 100, 1) if visits else 0.0,
            "retried_pct": round(retried_v / charged_v * 100, 1) if charged_v else 0.0,
            "avg_attempts": round(sessions / visits, 2) if visits else 0.0,
            "energy_kwh": round(float(r["energy"] or 0), 1),
            "amount": round(float(r["amount"] or 0), 2),
            # Паспорт станции — справка для карточки (не «факт против паспорта»).
            "power_kwt": round(pw, 1) if pw is not None else None,
            "connectors": conn or None,
            "risk": visits >= RISK_MIN_VISITS and v_succ < RISK_SUCCESS_PCT,
        })
    out.sort(key=lambda s: -s["visits"])

    t_visits = sum(s["visits"] for s in out)
    t_charged = sum(s["charged_visits"] for s in out)
    brands = {s["brand"] for s in out}
    return {
        "period": {"from": _as_date(date_from).isoformat(), "to": _as_date(date_to).isoformat()},
        "gap_min": VISIT_GAP_MIN,
        "risk": {"min_visits": RISK_MIN_VISITS, "success_pct": RISK_SUCCESS_PCT},
        "totals": {
            "brands": len(brands),
            "stations": len(out),
            "visits": t_visits,
            "sessions": sum(s["sessions"] for s in out),
            "charged_visits": t_charged,
            "failed_visits": sum(s["failed_visits"] for s in out),
            "repeat_sessions": sum(s["repeat_sessions"] for s in out),
            "wasted_sessions": sum(s["wasted_sessions"] for s in out),
            "visit_success_pct": round(t_charged / t_visits * 100, 1) if t_visits else 0.0,
            "energy_kwh": round(sum(s["energy_kwh"] for s in out), 1),
            "amount": round(sum(s["amount"] for s in out), 2),
            "risk_stations": sum(1 for s in out if s["risk"]),
        },
        "stations": out,
    }
