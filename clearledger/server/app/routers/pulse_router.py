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


# Колпак экрана дня: больше семи карточек читаются как лента, а лента — это то,
# от чего «Пульс» уходит. Лишнее отсекается по уровню (PULSE.md §7).
MAX_CARDS = 7


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 заявка», «3 заявки», «11 заявок» — карточку читает человек, а не парсер."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def build_cards(
    *, as_of: datetime | None, stale_days: int | None,
    own_sla_stale: int, own_reopen: int, ext_old: int,
    silent: int, park: int, acked: set[str],
) -> list[dict[str, Any]]:
    """Правила экрана дня — чистая функция над уже посчитанными цифрами.

    Отделена от запросов сознательно: правила — сердце «Пульса», и проверять их
    надо без базы (`tests/test_pulse_rules.py`). Каждая карточка — сводка или
    аномалия, ни одна не заводится на отдельную запись.
    """
    out: list[dict[str, Any]] = []

    def card(key: str, title: str, insight: str, *, count: int | None = None,
             level: str = "warn", link: str | None = None) -> None:
        if key not in acked:
            out.append({"key": key, "title": title, "insight": insight,
                        "count": count, "level": level, "link": link})

    # №0 — свежесть данных: без неё остальные цифры обсуждать нельзя.
    if stale_days is None:
        card("data_stale", "Данных о сессиях нет",
             "Ни одной загрузки сессий: цифрам сети верить пока нечему.",
             level="alert", link="/data")
    elif stale_days > STALE_DAYS:
        card("data_stale", "Данные сессий не обновлялись",
             f"Последняя загрузка {as_of:%d.%m}: прошло {stale_days} дн. "
             f"Цифрам сети можно верить только по эту дату."
             if as_of else f"Загрузок нет {stale_days} дн.",
             count=stale_days, level="alert", link="/data")

    if own_sla_stale:
        w = plural(own_sla_stale, "заявка", "заявки", "заявок")
        v = plural(own_sla_stale, "висит", "висят", "висят")
        card("own_sla", "Свои заявки встали",
             f"{own_sla_stale} {w} с нарушенным SLA {v} дольше "
             f"{OWN_SLA_DAYS} дней — работа стоит на нашей стороне.",
             count=own_sla_stale, link="/tickets")

    if ext_old > EXT_BACKLOG:
        card("ext_backlog", "Хвост внешней сервисной системы",
             f"{ext_old} {plural(ext_old, 'заявка', 'заявки', 'заявок')} HubEx "
             f"старше месяца. Это зеркала чужой системы: "
             f"разбирать не нам, но хвост такого размера — повод для разговора "
             f"с подрядчиком.",
             count=ext_old, link="/tickets")

    if park and silent / park > SILENT_SHARE:
        card("silent_surge", "Молчит большая часть сети",
             f"{silent} из {park} станций без сессий за {SILENT_HOURS} часа "
             f"данных — это уже не отдельные точки.",
             count=silent, link="/sales")

    if own_reopen:
        card("own_reopen", "Заявки открываются повторно",
             f"{own_reopen} {plural(own_reopen, 'своя заявка', 'своих заявки', 'своих заявок')} "
             f"{plural(own_reopen, 'переоткрыта', 'переоткрыты', 'переоткрыты')} второй раз — "
             f"решение не держится, стоит посмотреть, что там происходит.",
             count=own_reopen, link="/tickets")

    # Колпак: сначала тревожные, потом предупреждения; хвост отсекаем.
    out.sort(key=lambda c: 0 if c["level"] == "alert" else 1)
    return out[:MAX_CARDS]


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
    return await pulse_day_data(db, str(company_id))


async def pulse_day_data(db: AsyncSession, company_id: str) -> dict[str, Any]:
    """Данные экрана дня без проверки доступа — её делает вызывающий.

    Отдельной функцией, потому что плитку «Пульса» на рабочем столе считает тот же
    код (`services/space_desk._pulse`): второй набор правил разошёлся бы с первым,
    и плитка начала бы врать про то, что внутри.
    """
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
        select count(*) filter (where started_at > CAST(:as_of AS timestamp) - interval '7 days') as s7,
               coalesce(sum(amount) filter (where started_at > CAST(:as_of AS timestamp) - interval '7 days'), 0) as r7,
               count(*) filter (where started_at <= CAST(:as_of AS timestamp) - interval '7 days'
                                and started_at > CAST(:as_of AS timestamp) - interval '14 days') as s7p,
               coalesce(sum(amount) filter (where started_at <= CAST(:as_of AS timestamp) - interval '7 days'
                                and started_at > CAST(:as_of AS timestamp) - interval '14 days'), 0) as r7p
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
               count(*) filter (where last_at <= CAST(:as_of AS timestamp) - interval '{SILENT_HOURS} hours') as silent
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
    # commissioned_on хранится строкой (как и stage_since) — каст обязателен,
    # иначе «operator does not exist: character varying >= date».
    commissioned_30d = (await db.execute(text("""
        select count(*) from ezs_projects
        where company_id = :cid
          and nullif(commissioned_on, '')::date >= current_date - 30
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
                    note=f"введено за 30 дн: {commissioned_30d}"))
    kpi.append(_kpi("people", "Сейчас в системе", p.online,
                    note=f"за сегодня: {p.today} из {p.total}"))

    # ── Карточки-эскалации: аномалия или сводка, не запись (PULSE.md §7) ──
    acked = {r.card_key for r in (await db.execute(text(
        "select card_key from pulse_acks where company_id = :cid and acked_on = current_date"
    ), {"cid": cid})).all()}
    cards = build_cards(
        as_of=as_of, stale_days=stale_days,
        own_sla_stale=t.own_sla_stale, own_reopen=t.own_reopen, ext_old=t.ext_old,
        silent=(silent.silent if silent else 0), park=(silent.park if silent else 0),
        acked=acked,
    )

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
