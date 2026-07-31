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

# Имена правил для журнала «Принятое»: ключ в базе технический, человеку нужен текст.
CARD_TITLES = {
    "data_stale": "Данные сессий не обновлялись",
    "own_sla": "Свои заявки встали",
    "ext_backlog": "Хвост внешней сервисной системы",
    "silent_surge": "Молчит большая часть сети",
    "own_reopen": "Заявки открываются повторно",
}


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
         state: str | None = None, link: str | None = None,
         higher_is_better: bool = True) -> dict[str, Any]:
    """Плитка показателя.

    `link` — куда проваливаться (лестница погружения, PULSE.md §2): цифра без
    входа в разрез оставляет руководителя с вопросом «и что теперь».
    `higher_is_better=False` — рост это плохо (поток заявок, молчащие станции):
    иначе «заявок поступило +30%» красится зелёным как достижение.
    """
    return {"key": key, "title": title, "value": value, "unit": unit,
            "delta_pct": delta_pct, "note": note, "state": state, "link": link,
            "higher_is_better": higher_is_better}


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
        kpi.append(_kpi("revenue", "Выручка за 7 дн, ₽", float(s.r7),
                        delta_pct=_dpct(float(s.r7), float(s.r7p)), state=data_state,
                        link="/pulse/business"))
        kpi.append(_kpi("sessions", "Сессии за 7 дн", s.s7,
                        delta_pct=_dpct(s.s7, s.s7p), state=data_state,
                        link="/pulse/business"))
    if silent is not None and silent.park:
        share = silent.silent / silent.park
        # Плитка желтеет раньше, чем срабатывает карточка-эскалация: треть сети без
        # сессий — ещё не повод будить директора, но и не «норма», о которой молчат.
        kpi.append(_kpi("silent", "Молчат станции", silent.silent,
                        note=f"из {silent.park} за {SILENT_HOURS} ч данных",
                        state="warn" if share > 0.3 else data_state,
                        link="/sales", higher_is_better=False))
    kpi.append(_kpi("own_open", "Свои заявки", t.own_open,
                    note=f"SLA нарушен: {t.own_sla}",
                    state="warn" if t.own_sla_stale else None,
                    link="/tickets", higher_is_better=False))
    kpi.append(_kpi("ext_open", "Внешняя FSM", t.ext_open,
                    note=f"старше месяца: {t.ext_old}",
                    link="/tickets", higher_is_better=False))
    active_projects = sum(r.n for r in funnel)
    kpi.append(_kpi("funnel", "Проекты в работе", active_projects,
                    note=f"введено за 30 дн: {commissioned_30d}",
                    link="/pulse/business"))
    kpi.append(_kpi("people", "Сейчас в системе", p.online,
                    note=f"за сегодня: {p.today} из {p.total}",
                    link="/pulse/team"))

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


@router.get("/business")
async def pulse_business(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Бизнес» — картина для куратора: сеть и продажи + развитие сети.

    Ни фамилий, ни заявок (PULSE.md §3): куратора интересует, в каком состоянии
    дело и как оно движется, а операциями занят директор.
    """
    await assert_company_member(company_id, current_user, db)
    cid = str(company_id)

    as_of = (await db.execute(text(
        "select max(started_at) from charge_sessions where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()

    net: list[dict[str, Any]] = []
    trend: list[dict[str, Any]] = []
    if as_of is not None:
        m = (await db.execute(text("""
            select count(*) filter (where started_at > CAST(:as_of AS timestamp) - interval '30 days') as s30,
                   coalesce(sum(amount) filter (where started_at > CAST(:as_of AS timestamp) - interval '30 days'), 0) as r30,
                   coalesce(sum(energy_kwh) filter (where started_at > CAST(:as_of AS timestamp) - interval '30 days'), 0) as e30,
                   count(*) filter (where started_at <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and started_at > CAST(:as_of AS timestamp) - interval '60 days') as s30p,
                   coalesce(sum(amount) filter (where started_at <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and started_at > CAST(:as_of AS timestamp) - interval '60 days'), 0) as r30p,
                   coalesce(sum(energy_kwh) filter (where started_at <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and started_at > CAST(:as_of AS timestamp) - interval '60 days'), 0) as e30p,
                   count(distinct location_id) filter (where started_at > CAST(:as_of AS timestamp) - interval '30 days') as live
            from charge_sessions where company_id = :cid
        """), {"cid": cid, "as_of": as_of})).one()
        # Единица измерения — в заголовке, а не рядом с числом: «271,8 тыс. кВт·ч»
        # не помещалось в плитку на телефоне и вылезало за рамку.
        net = [
            _kpi("revenue", "Выручка, ₽", float(m.r30),
                 delta_pct=_dpct(float(m.r30), float(m.r30p))),
            _kpi("energy", "Отпущено, кВт·ч", float(m.e30),
                 delta_pct=_dpct(float(m.e30), float(m.e30p))),
            _kpi("sessions", "Зарядных сессий", m.s30, delta_pct=_dpct(m.s30, m.s30p)),
            _kpi("live", "Работающих станций", m.live, note="давали сессии за 30 дней"),
        ]
        # Помесячно за полгода — форма кривой важнее точных чисел.
        trend = [{"month": r.m.strftime("%m.%Y"), "revenue": float(r.rev), "sessions": r.n}
                 for r in (await db.execute(text("""
            select date_trunc('month', started_at) as m, count(*) as n,
                   coalesce(sum(amount), 0) as rev
            from charge_sessions
            where company_id = :cid and started_at > CAST(:as_of AS timestamp) - interval '6 months'
            group by 1 order by 1
        """), {"cid": cid, "as_of": as_of})).all()]

    # Развитие сети: воронка от переговоров до ввода — то, чем растёт бизнес.
    # Порядок — процессный (лид → … → эксплуатация), а не «по убыванию количества»:
    # воронка, отсортированная по величине, перестаёт быть воронкой.
    stage_order = {s: i for i, s in enumerate((
        "lead", "screening", "negotiation", "dd", "decision", "contracting",
        "construction", "commissioning", "live", "on_hold"))}
    funnel_rows = (await db.execute(text("""
        select stage, count(*) as n from ezs_projects
        where company_id = :cid and stage <> 'archive'
        group by stage
    """), {"cid": cid})).all()
    funnel = [{"stage": r.stage, "count": r.n} for r in
              sorted(funnel_rows, key=lambda r: stage_order.get(r.stage, 99))]
    dev = (await db.execute(text("""
        select count(*) filter (where nullif(commissioned_on,'')::date >= current_date - 90) as comm_90,
               count(*) filter (where nullif(commissioned_on,'') is not null) as comm_all,
               count(*) as total
        from ezs_projects where company_id = :cid
    """), {"cid": cid})).one()
    # Вехи: только события, которые двигают дело, — смена стадии, гейт, документ,
    # заметка. Правки полей (`edit`, тысяча записей на пилоте: «Area m2», «Адрес»)
    # куратору не веха, а шум чужой работы.
    events = [{"at": r.at.isoformat() if r.at else None, "text": r.txt}
              for r in (await db.execute(text("""
        select created_at as at,
               coalesce(nullif("text",''), 'стадия: ' || coalesce(to_stage,'—')) as txt
        from ezs_site_events
        where company_id = :cid and kind in ('stage','gate','doc','note','import')
        order by created_at desc limit 8
    """), {"cid": cid})).all()]

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "net": net, "trend": trend, "funnel": funnel,
        "development": {"commissioned_90d": dev.comm_90, "commissioned_total": dev.comm_all,
                        "portfolio": dev.total},
        "events": events,
    }


@router.get("/team")
async def pulse_team(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Команда» — у кого затор: люди, их подразделения, нагрузка по заявкам.

    Не слежка «кто во сколько пришёл» (PULSE.md §3), а ответ на вопрос, кому
    помочь и у кого работа стоит. Заявки Поддержки соединяются с людьми Ядра по
    email — той же связкой, что и разрез по подразделениям в «Заявках».
    """
    await assert_company_member(company_id, current_user, db)
    cid = str(company_id)

    # Человек виден СРАЗУ во всех приложениях пространства (постановка МАГа
    # 31.07.2026): штатное место, заявки, проекты, чаты, журнал. Иначе руководитель
    # смотрит пять экранов, чтобы понять, чем занят один сотрудник.
    people = [{
        "id": str(r.id),
        "name": r.name, "email": r.email, "department": r.dept,
        "is_head": r.is_head, "party": r.party_type, "position": r.position,
        "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None,
        # Заявки: связь Ядра и Поддержки по email — та же, что в разрезе «Заявок».
        "open": r.open_tickets, "breached": r.breached,
        "authored": r.authored_tickets, "closed_30d": r.closed_30d,
        # Проекты: ведёт (ответственный) и сколько правок внёс за 30 дней.
        "projects_owned": r.projects_owned, "project_edits_30d": r.project_edits,
        # Чаты и общая активность в пространстве.
        "chat_rooms": r.chat_rooms, "actions_30d": r.actions_30d,
    } for r in (await db.execute(text("""
        select u.id, u.name, u.email, u.last_seen_at, uc.party_type, uc.position,
               od.name as dept,
               (od.head_user_id = u.id) as is_head,
               coalesce(t.open, 0) as open_tickets,
               coalesce(t.breached, 0) as breached,
               coalesce(t.authored, 0) as authored_tickets,
               coalesce(t.closed_30d, 0) as closed_30d,
               coalesce(p.owned, 0) as projects_owned,
               coalesce(p.edits, 0) as project_edits,
               coalesce(c.rooms, 0) as chat_rooms,
               coalesce(a.n, 0) as actions_30d
        from users u
        join user_companies uc on uc.user_id = u.id and uc.company_id = :cid
        left join org_departments od on od.id = uc.department_id
        left join lateral (
            select count(*) filter (where tk.status not in ('closed','cancelled')
                                    and (au.id is not null)) as open,
                   count(*) filter (where tk.status not in ('closed','cancelled')
                                    and au.id is not null
                                    and coalesce(tk.sla_breached,false)) as breached,
                   -- Автором считаем только СВОИ заявки: зеркала внешней FSM
                   -- повешены на одного человека (11 322 на пилоте) и утопили бы
                   -- реальную картину, кто что заводит.
                   count(*) filter (where cu.id is not null
                                    and tk.external_system is null) as authored,
                   count(*) filter (where au.id is not null
                                    and tk.closed_at >= now() - interval '30 days') as closed_30d
            from public.tickets tk
            left join public.users au on au.id = coalesce(tk.current_assignee_id, tk.assigned_to)
                 and lower(au.email) = lower(u.email)
            left join public.users cu on cu.id = tk.customer_user_id
                 and lower(cu.email) = lower(u.email)
            where coalesce(tk.is_deleted,false) = false
              and coalesce(tk.is_archived,false) = false
              and (au.id is not null or cu.id is not null)
        ) t on true
        left join lateral (
            select (select count(*) from ezs_projects pr
                     where pr.company_id = :cid and pr.owner_user_id = u.id) as owned,
                   (select count(*) from ezs_site_events ev
                     where ev.company_id = :cid and ev.author_user_id = u.id
                       and ev.created_at >= now() - interval '30 days') as edits
        ) p on true
        left join lateral (
            select count(*) as rooms from chat_participants cp where cp.user_id = u.id
        ) c on true
        left join lateral (
            -- audit_events.user_id хранится строкой, а не uuid: сравниваем текстом,
            -- иначе «operator does not exist: character varying = uuid».
            select count(*) as n from audit_events ae
             where ae.company_id = :cid and ae.user_id = u.id::text
               and ae.timestamp >= now() - interval '30 days'
        ) a on true
        order by coalesce(t.breached,0) desc, coalesce(t.open,0) desc,
                 u.last_seen_at desc nulls last
    """), {"cid": cid})).all()]

    departments = [{
        "name": r.name, "head": r.head, "people": r.people,
    } for r in (await db.execute(text("""
        select d.name, hu.name as head,
               (select count(*) from user_companies uc2
                 where uc2.department_id = d.id and uc2.company_id = :cid) as people
        from org_departments d
        left join users hu on hu.id = d.head_user_id
        where d.company_id = :cid
        order by d.name
    """), {"cid": cid})).all()]

    return {"people": people, "departments": departments}


@router.get("/team/{user_id}")
async def pulse_person(
    user_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Карточка человека: чем занят прямо сейчас и что делал в пространстве.

    Открывается из «Команды» разворотом строки — руководителю нужен не только
    счётчик, но и ответ «что именно у него в работе и куда он ходит».
    """
    await assert_company_member(company_id, current_user, db)
    cid, uid = str(company_id), str(user_id)

    who = (await db.execute(text("""
        select u.name, u.email, u.last_seen_at, uc.position, uc.party_type,
               od.name as dept, hu.name as head
        from users u
        join user_companies uc on uc.user_id = u.id and uc.company_id = :cid
        left join org_departments od on od.id = uc.department_id
        left join users hu on hu.id = od.head_user_id
        where u.id = :uid
    """), {"cid": cid, "uid": uid})).first()
    if who is None:
        return {"found": False}

    tickets = [{
        "number": r.display_number or r.number, "title": r.title, "status": r.status,
        "breached": bool(r.sla_breached), "object": r.obj,
        "created": r.created_at.isoformat() if r.created_at else None,
    } for r in (await db.execute(text("""
        select tk.display_number, tk.number, tk.title, tk.status, tk.sla_breached,
               tk.created_at, so.name as obj
        from public.tickets tk
        join public.users au on au.id = coalesce(tk.current_assignee_id, tk.assigned_to)
        left join public.service_objects so on so.id = tk.service_object_id
        where lower(au.email) = lower(:email)
          and tk.status not in ('closed','cancelled')
          and coalesce(tk.is_deleted,false)=false and coalesce(tk.is_archived,false)=false
        order by tk.sla_breached desc nulls last, tk.created_at
        limit 20
    """), {"email": who.email})).all()]

    projects = [{"title": r.title, "stage": r.stage} for r in (await db.execute(text("""
        select coalesce(nullif(title,''), project_no, 'без имени') as title, stage
        from ezs_projects where company_id = :cid and owner_user_id = :uid
        order by updated_at desc nulls last limit 20
    """), {"cid": cid, "uid": uid})).all()]

    rooms = [{"name": r.name, "kind": r.kind} for r in (await db.execute(text("""
        select cr.name, cr.kind from chat_participants cp
        join chat_rooms cr on cr.id = cp.room_id
        where cp.user_id = :uid order by cr.name limit 30
    """), {"uid": uid})).all()]

    actions = [{
        "action": r.action, "at": r.timestamp.isoformat() if r.timestamp else None,
        "details": r.details,
    } for r in (await db.execute(text("""
        select action, timestamp, details from audit_events
        where company_id = :cid and user_id = :uid
        order by timestamp desc limit 15
    """), {"cid": cid, "uid": uid})).all()]

    # Правки в проектах — самый честный след работы: их 1030 на пилоте, и видно,
    # кто действительно ведёт портфель, а кто только числится.
    edits = (await db.execute(text("""
        select count(*) filter (where created_at >= now() - interval '7 days') as w,
               count(*) filter (where created_at >= now() - interval '30 days') as m,
               max(created_at) as last_at
        from ezs_site_events where company_id = :cid and author_user_id = :uid
    """), {"cid": cid, "uid": uid})).one()

    return {
        "found": True,
        "name": who.name, "email": who.email, "position": who.position,
        "department": who.dept, "head": who.head, "party": who.party_type,
        "last_seen": who.last_seen_at.isoformat() if who.last_seen_at else None,
        "tickets": tickets, "projects": projects, "rooms": rooms, "actions": actions,
        "edits": {"week": edits.w, "month": edits.m,
                  "last": edits.last_at.isoformat() if edits.last_at else None},
    }


@router.get("/week")
async def pulse_week(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Неделя» — как прошла неделя: цифры против прошлой и что сдвинулось.

    Пока считается на запрос; снимок с доставкой push/почта/чат — волна В2
    (PULSE.md §3), поэтому формат ответа сразу такой, каким его будет удобно
    складывать в снимок.
    """
    await assert_company_member(company_id, current_user, db)
    cid = str(company_id)

    as_of = (await db.execute(text(
        "select max(started_at) from charge_sessions where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()

    rows: list[dict[str, Any]] = []
    if as_of is not None:
        w = (await db.execute(text("""
            select count(*) filter (where started_at > CAST(:as_of AS timestamp) - interval '7 days') as s,
                   coalesce(sum(amount) filter (where started_at > CAST(:as_of AS timestamp) - interval '7 days'), 0) as r,
                   count(*) filter (where started_at <= CAST(:as_of AS timestamp) - interval '7 days'
                                    and started_at > CAST(:as_of AS timestamp) - interval '14 days') as sp,
                   coalesce(sum(amount) filter (where started_at <= CAST(:as_of AS timestamp) - interval '7 days'
                                    and started_at > CAST(:as_of AS timestamp) - interval '14 days'), 0) as rp
            from charge_sessions where company_id = :cid
        """), {"cid": cid, "as_of": as_of})).one()
        rows.append({"label": "Выручка", "value": float(w.r), "prev": float(w.rp),
                     "unit": "₽", "higher_is_better": True})
        rows.append({"label": "Зарядных сессий", "value": w.s, "prev": w.sp,
                     "unit": None, "higher_is_better": True})

    t = (await db.execute(text("""
        select count(*) filter (where created_at >= now() - interval '7 days') as created,
               count(*) filter (where closed_at >= now() - interval '7 days') as closed,
               count(*) filter (where created_at >= now() - interval '14 days'
                                and created_at < now() - interval '7 days') as created_prev,
               count(*) filter (where closed_at >= now() - interval '14 days'
                                and closed_at < now() - interval '7 days') as closed_prev
        from public.tickets
        where coalesce(is_deleted,false)=false and coalesce(is_archived,false)=false
    """))).one()
    # Поток заявок вырос — это не победа: полярность у строк дайджеста разная.
    rows.append({"label": "Заявок поступило", "value": t.created, "prev": t.created_prev,
                 "unit": None, "higher_is_better": False})
    rows.append({"label": "Заявок закрыто", "value": t.closed, "prev": t.closed_prev,
                 "unit": None, "higher_is_better": True})

    # Движение проектов — смены стадий и гейты, а не правки полей карточки.
    moved = (await db.execute(text("""
        select count(*) from ezs_site_events
        where company_id = :cid and kind in ('stage','gate')
          and created_at >= now() - interval '7 days'
    """), {"cid": cid})).scalar_one()
    rows.append({"label": "Движений по проектам", "value": moved, "prev": None,
                 "unit": None, "higher_is_better": True})

    # Что именно сдвинулось — списком, а не одной цифрой: руководителю нужны имена.
    highlights = [{"at": r.at.isoformat() if r.at else None, "text": r.txt}
                  for r in (await db.execute(text("""
        select created_at as at,
               coalesce(nullif("text",''), 'стадия: ' || coalesce(to_stage,'—')) as txt
        from ezs_site_events
        where company_id = :cid and kind in ('stage','gate','doc','note')
          and created_at >= now() - interval '7 days'
        order by created_at desc limit 10
    """), {"cid": cid})).all()]

    return {"rows": rows, "highlights": highlights,
            "as_of": as_of.isoformat() if as_of else None}


@router.get("/accepted")
async def pulse_accepted(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Что уже снято с экрана дня и кем — за сегодня и предыдущие дни.

    Директор должен видеть не только «что горит», но и «что мы сегодня уже
    посмотрели»: иначе снятая карточка выглядит как пропавшая.
    """
    await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(text("""
        select a.card_key, a.acked_on, a.acked_at, u.name as who
        from pulse_acks a
        left join users u on u.id = a.user_id
        where a.company_id = :cid and a.acked_on >= current_date - 7
        order by a.acked_at desc
    """), {"cid": str(company_id)})).all()
    return {"items": [{
        "card_key": r.card_key,
        "title": CARD_TITLES.get(r.card_key, r.card_key),
        "on": r.acked_on.isoformat(),
        "at": r.acked_at.isoformat() if r.acked_at else None,
        "who": r.who,
        "today": r.acked_on == date.today(),
    } for r in rows]}


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
