"""«Пульс» — рабочее место руководителя: экран дня (ecosystem-deploy/docs/PULSE.md).

Витрина-агрегатор: своих расчётов нет — те же таблицы и те же определения, что у
«Продаж», «Заявок» и «Проектов» (единый словарь метрик, PULSE.md §6). Правила
эскалаций В1 зашиты, агрегатные и с большим запасом (§3, §7): экран дня обязан
молчать, пока вмешательство не требуется. Все окна считаются от даты последней
загруженной сессии (as_of), а не от now(): данные приходят файлами, и «молчит
48 часов» от текущего времени объявило бы мёртвой всю сеть.

Модуль намеренно самодостаточен (решение МАГа 31.07.2026: над «Пульсом» работаем
отдельно): вся логика здесь, наружу — только модель PulseAck и точки реестра.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import PulseAck, User

router = APIRouter(prefix="/pulse", tags=["Пульс"])

# Пороги В1 — с большим запасом (решение МАГа 31.07.2026, PULSE.md §3):
# период адаптации система проходит тихо. Настройка в «Управлении» — волна В3.
STALE_DAYS = 7          # данные сессий не обновлялись дольше — эскалация №0
OWN_SLA_DAYS = 3        # своя заявка с нарушенным SLA висит дольше — карточка
EXT_BACKLOG = 1000      # хвост зеркал внешней FSM старше месяца — сводная карточка
SILENT_SHARE = 0.6      # доля молчащих станций парка — карточка
SILENT_HOURS = 48       # «молчит» = нет сессий столько часов ДАННЫХ (от as_of)


def _kpi(key: str, title: str, value: float | int | None, *, unit: str | None = None,
         delta_pct: float | None = None, note: str | None = None,
         state: str | None = None) -> dict[str, Any]:
    return {"key": key, "title": title, "value": value, "unit": unit,
            "delta_pct": delta_pct, "note": note, "state": state}


def _dpct(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


@router.get("/day")
async def pulse_day(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Экран дня: строка KPI по направлениям + карточки-эскалации (сводки)."""
    await assert_company_member(company_id, current_user, db)
    cid = str(company_id)

    # ── Свежесть: правило №0. as_of — дата данных, под ним живут все окна ──
    as_of = (await db.execute(text(
        "select max(started_at) from charge_sessions where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()
    stale_days: int | None = None
    if as_of is not None:
        as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        stale_days = (datetime.now(timezone.utc) - as_of_utc).days

    # ── Сеть и продажи: 7 дней данных против предыдущих 7 ──
    s = (await db.execute(text("""
        select count(*) filter (where started_at > :as_of - interval '7 days') as s7,
               coalesce(sum(amount) filter (where started_at > :as_of - interval '7 days'), 0) as r7,
               count(*) filter (where started_at <= :as_of - interval '7 days'
                                and started_at > :as_of - interval '14 days') as s7p,
               coalesce(sum(amount) filter (where started_at <= :as_of - interval '7 days'
                                and started_at > :as_of - interval '14 days'), 0) as r7p
        from charge_sessions where company_id = :cid
    """), {"cid": cid, "as_of": as_of})).one() if as_of else None

    # Молчащие — по парку станций, когда-либо дававших сессии (как в
    # «Продажах» silent-stations: сравнивать с реестром объектов нельзя,
    # неподключённые станции — другая история, не эскалация оборудования).
    silent = (await db.execute(text(f"""
        with ever as (
            select location_id, max(started_at) as last_at
              from charge_sessions
             where company_id = :cid and location_id is not null
             group by 1
        )
        select count(*) as park,
               count(*) filter (where last_at <= :as_of - interval '{SILENT_HOURS} hours') as silent
        from ever
    """), {"cid": cid, "as_of": as_of})).one() if as_of else None

    # ── Сервис: заявки. Определение «открытой» — как в /tickets/summary
    # (не closed/cancelled), иначе «Пульс» и «Заявки» разойдутся в цифре.
    # company_id тут не фильтруется сознательно — как во всей витрине заявок
    # (предусловие мультикомпанийности, PULSE.md §7): чинить в одном месте.
    t = (await db.execute(text(f"""
        select count(*) filter (where external_system is null) as own_open,
               count(*) filter (where external_system is null
                                and coalesce(sla_breached, false)) as own_sla,
               count(*) filter (where external_system is null
                                and coalesce(sla_breached, false)
                                and created_at < now() - interval '{OWN_SLA_DAYS} days') as own_sla_stale,
               count(*) filter (where external_system is null
                                and coalesce(reopen_count, 0) >= 2) as own_reopen,
               count(*) filter (where external_system is not null) as ext_open,
               count(*) filter (where external_system is not null
                                and created_at < now() - interval '30 days') as ext_old
        from public.tickets
        where status not in ('closed', 'cancelled')
          and coalesce(is_deleted, false) = false
          and coalesce(is_archived, false) = false
    """))).one()

    # ── Развитие: воронка проектов (активные стадии) и вводы за 30 дней ──
    funnel = (await db.execute(text("""
        select stage, count(*) as n from ezs_projects
        where company_id = :cid and stage <> 'archive'
        group by stage order by n desc
    """), {"cid": cid})).all()
    commissioned_30d = (await db.execute(text("""
        select count(*) from ezs_projects
        where company_id = :cid and commissioned_on >= current_date - 30
    """), {"cid": cid})).scalar_one()

    # ── Люди: присутствие тем же окном, что карта пространства (6 минут) ──
    p = (await db.execute(text("""
        select count(*) filter (where u.last_seen_at > now() - interval '6 minutes') as online,
               count(*) filter (where u.last_seen_at >= current_date) as today,
               count(*) as total
        from users u join user_companies uc on uc.user_id = u.id
        where uc.company_id = :cid
    """), {"cid": cid})).one()

    # ── Строка KPI по направлениям (PULSE.md §3): сегодня против вчера ──
    kpi: list[dict[str, Any]] = []
    data_state = "stale" if (stale_days is None or stale_days > STALE_DAYS) else None
    if s is not None:
        kpi.append(_kpi("revenue", "Выручка, 7 дн данных", float(s.r7), unit="₽",
                        delta_pct=_dpct(float(s.r7), float(s.r7p)), state=data_state))
        kpi.append(_kpi("sessions", "Сессии, 7 дн данных", s.s7,
                        delta_pct=_dpct(s.s7, s.s7p), state=data_state))
    if silent is not None and silent.park:
        share = silent.silent / silent.park
        kpi.append(_kpi("silent", "Молчат станции", silent.silent,
                        note=f"из {silent.park} за {SILENT_HOURS} ч данных",
                        state="warn" if share > SILENT_SHARE else data_state))
    kpi.append(_kpi("own_open", "Свои заявки", t.own_open,
                    note=f"SLA нарушен: {t.own_sla}",
                    state="warn" if t.own_sla_stale else None))
    kpi.append(_kpi("ext_open", "Внешняя FSM", t.ext_open,
                    note=f"старше месяца: {t.ext_old}"))
    active_projects = sum(r.n for r in funnel)
    kpi.append(_kpi("funnel", "Проекты в работе", active_projects,
                    note=", ".join(f"{r.stage} {r.n}" for r in funnel[:3]) or None))
    kpi.append(_kpi("people", "Сейчас в системе", p.online,
                    note=f"за сегодня: {p.today} из {p.total}"))

    # ── Карточки-эскалации: аномалия или сводка, не запись (PULSE.md §7) ──
    acked = {r.card_key for r in (await db.execute(text(
        "select card_key from pulse_acks where company_id = :cid and acked_on = current_date"
    ), {"cid": cid})).all()}

    cards: list[dict[str, Any]] = []

    def card(key: str, title: str, insight: str, *, count: int | None = None,
             level: str = "warn", link: str | None = None) -> None:
        if key not in acked:
            cards.append({"key": key, "title": title, "insight": insight,
                          "count": count, "level": level, "link": link})

    if stale_days is None:
        card("data_stale", "Данных о сессиях нет",
             "Ни одной загрузки сессий: цифрам сети верить пока нечему.",
             level="alert", link="/data")
    elif stale_days > STALE_DAYS:
        card("data_stale", "Данные сессий не обновлялись",
             f"Последняя загрузка {as_of:%d.%m}: прошло {stale_days} дн. "
             f"Цифрам сети можно верить только по эту дату.",
             count=stale_days, level="alert", link="/data")

    if t.own_sla_stale:
        card("own_sla", "Свои заявки встали",
             f"{t.own_sla_stale} заявок с нарушенным SLA висят дольше "
             f"{OWN_SLA_DAYS} дней — работа стоит на нашей стороне.",
             count=t.own_sla_stale, link="/tickets")

    if t.ext_old > EXT_BACKLOG:
        card("ext_backlog", "Хвост внешней сервисной системы",
             f"{t.ext_old} заявок HubEx старше месяца. Это зеркала чужой "
             f"системы: разбирать не нам, но хвост такого размера — повод "
             f"для разговора с подрядчиком.",
             count=t.ext_old, link="/tickets")

    if silent is not None and silent.park and silent.silent / silent.park > SILENT_SHARE:
        card("silent_surge", "Молчит большая часть сети",
             f"{silent.silent} из {silent.park} станций без сессий за "
             f"{SILENT_HOURS} часа данных — это уже не отдельные точки.",
             count=silent.silent, link="/sales")

    if t.own_reopen:
        card("own_reopen", "Заявки открываются повторно",
             f"{t.own_reopen} своих заявок переоткрыты второй раз — "
             f"решение не держится, стоит посмотреть, что там происходит.",
             count=t.own_reopen, link="/tickets")

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "stale_days": stale_days,
        "kpi": kpi,
        "cards": cards,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class AckIn(BaseModel):
    company_id: str
    card_key: str


@router.post("/ack")
async def ack_card(
    body: AckIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Принято»: снять карточку с экрана дня до конца суток — со следом в журнале."""
    await assert_company_member(body.company_id, current_user, db)
    cid = uuid.UUID(body.company_id)
    exists = (await db.execute(text("""
        select 1 from pulse_acks
        where company_id = :cid and card_key = :key and acked_on = current_date
    """), {"cid": str(cid), "key": body.card_key})).first()
    if not exists:
        db.add(PulseAck(company_id=cid, card_key=body.card_key,
                        acked_on=date.today(), user_id=current_user.id))
        await log_audit(db, actor=current_user, company_id=cid,
                        action="pulse.ack", target=body.card_key)
        await db.commit()
    return {"ok": True}
