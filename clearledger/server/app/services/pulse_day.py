"""Данные экрана дня и общие определения его трёх профилей.

Видимость/доступ проверяет caller. visible=None — существующий системный срез
для digest/desk; ProgrammingError fallbacks могут делать rollback его session.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.support_scope import support_company_id
from app.services.tax_mode import tax_mode as space_tax_mode
from app.services.ezs_changes import STAGE_LABELS


STALE_DAYS = 7          # данные сессий не обновлялись дольше — эскалация №0


OWN_SLA_DAYS = 3        # своя заявка с нарушенным SLA висит дольше — карточка


EXT_BACKLOG = 1000      # хвост зеркал внешней FSM старше месяца — сводная карточка


SILENT_SHARE = 0.6      # доля молчащих станций парка — карточка


SILENT_HOURS = 48       # «молчит» = нет сессий столько часов ДАННЫХ (от as_of)


CC_MISSED_FACTOR = 1.5  # доля пропущенных выше цели во столько раз — карточка


CC_WRAPUP_STUCK = 10    # столько разговоров зависло в разборе с просроченным ответом


CC_REPEAT_TIMES = 3     # клиент обращался столько раз за неделю — он не решил вопрос


CC_REPEAT_PEOPLE = 3    # столько таких клиентов — карточка


CC_DEFAULT_TARGETS = {"missed_share": 5.0, "first_response_sec": 120.0,
                      "in_sla_share": 95.0, "handle_sec": 900.0}


SALES_DROP = 20.0       # выручка недели упала на столько % — карточка


SALES_OUT_SHARE = 0.05  # столько парка выпало из работы за неделю — карточка


SALES_OUT_MIN = 10      # и не меньше стольких станций: у мелкой сети % обманчив


SALES_VISIT_OK = 85.0   # успех визитов ниже — клиенты уезжают, не зарядившись


PR_STUCK_DAYS = 90      # стоит в одной стадии дольше — застрял


PR_STUCK_SHARE = 0.10   # столько портфеля застряло — карточка


PR_STUCK_MIN = 20       # и не меньше стольких проектов


PR_OWNER_SHARE = 0.30   # столько портфеля без ответственного — карточка


PR_OWNER_MIN = 20


PR_MOVES_WEEKS = 3      # столько недель без единой смены стадии — портфель встал


OPS_DOCS_OVERDUE = 20   # столько начислений без документа после срока — карточка


OPS_OPEN_MONTHS = 2     # период не закрыт дольше стольких месяцев — карточка


OPS_COST_JUMP = 15.0    # ожидание месяца выросло на столько % — карточка


OBJ_SILENT_DAYS = 30    # нет сессий столько дней ДАННЫХ — точка не продаёт


OBJ_DROP_PCT = 50.0     # выручка недели упала на столько % — провал точки


OBJ_PAIN_MIN = 2        # столько признаков сразу — «болит»


OBJ_IDLE_COST_MIN = 10  # столько платных точек без выручки — карточка


ST_ALIVE_DAYS = 60


ST_SILENT_DAYS = 7      # ни одного кВт·ч столько дней данных — станция не отпускает


ST_DROP_PCT = 50.0      # выручка недели упала на столько % к прошлой — «в 2 раза»


ST_DROP_FLOOR = 5000    # прошлой недели меньше — процент ничего не значит


ST_VISIT_OK = 70.0      # доля приездов с зарядом ниже — клиенты уезжают ни с чем


ST_VISIT_MIN = 10       # приездов за неделю меньше — доля не показательна


ST_AVAIL_PCT = 50.0     # доля дней «Активная» за 30 дн. по витрине ниже — «Первое окно»


ACCESS_ACTIONS = ("user.create", "user.remove", "member.access", "member.scope",
                  "member.party", "role.create", "role.update", "invite.create")


class _TicketsZero:
    """Пустой ответ по заявкам: контур Поддержки недоступен этому пространству.

    Нули, а не отсутствие ключей: экраны читают поля напрямую, и «нет данных»
    здесь означает «заявок не видно», а не «ошибка».
    """

    created = closed = created_prev = closed_prev = 0
    own_open = own_sla = own_sla_stale = own_reopen = ext_open = ext_old = 0
    n = 0
    at = None


async def _tickets_available(db: AsyncSession) -> bool:
    """Есть ли у пространства доступ к таблице заявок Поддержки.

    У части пространств Поддержка стоит отдельным контуром, и прав на её таблицы
    у Ядра нет. Это НЕ ошибка: заявок просто не видно, и экран должен показать
    остальное, а не упасть целиком.
    """
    try:
        return bool((await db.execute(text(
            "SELECT has_table_privilege(current_user, 'tickets', 'SELECT')"))).scalar())
    except Exception:
        return False


async def _access_snapshot(db: AsyncSession, cid: str) -> dict[str, Any]:
    """Люди и доступ: то, что касается руководителя лично.

    Не «кто во сколько пришёл», а риск: у кого остались права, которыми не
    пользуются, кого позвали и он не дошёл, и что за месяц меняли в допуске.
    """
    m = (await db.execute(text("""
        select
          count(*) as members,
          count(*) filter (where uc.role = 'admin') as admins,
          count(*) filter (where uc.party_type = 'partner') as partners,
          count(*) filter (where u.last_seen_at is null
                or u.last_seen_at < now() - interval '30 days') as dormant,
          count(*) filter (where uc.role = 'admin'
                and (u.last_seen_at is null
                     or u.last_seen_at < now() - interval '30 days')) as dormant_admins
        from user_companies uc join users u on u.id = uc.user_id
        where uc.company_id = :cid
    """), {"cid": cid})).one()

    inv = (await db.execute(text("""
        select count(*) filter (where accepted_at is null and status <> 'revoked') as pending,
               count(*) filter (where accepted_at is null and status <> 'revoked'
                     and created_at < now() - interval '7 days') as stale
        from invitations where company_id = :cid
    """), {"cid": cid})).one()

    failed = (await db.execute(text("""
        select count(*) from audit_events
        where company_id = :cid and action = 'auth.login_failed'
          and timestamp >= now() - interval '7 days'
    """), {"cid": cid})).scalar_one()

    dormant_list = [{"name": r.name, "email": r.email, "role": r.role,
                     "party": r.party_type,
                     "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None}
                    for r in (await db.execute(text("""
        select u.name, u.email, uc.role, uc.party_type, u.last_seen_at
        from user_companies uc join users u on u.id = uc.user_id
        where uc.company_id = :cid
          and (u.last_seen_at is null or u.last_seen_at < now() - interval '30 days')
        order by u.last_seen_at asc nulls first limit 12
    """), {"cid": cid})).all()]

    # Список действий подставляем как literal-набор: expanding-параметр здесь
    # лишняя церемония, а значения — наша же константа, не пользовательский ввод.
    acts = ", ".join(f"'{a}'" for a in ACCESS_ACTIONS)
    events = [{"at": r.timestamp.isoformat() if r.timestamp else None,
               "action": r.action, "who": r.user_name, "details": r.details}
              for r in (await db.execute(text(f"""
        select timestamp, action, user_name, details from audit_events
        where company_id = :cid and action in ({acts})
          and timestamp >= now() - interval '30 days'
        order by timestamp desc limit 12
    """), {"cid": cid})).all()]

    return {"members": m.members, "admins": m.admins, "partners": m.partners,
            "dormant": m.dormant, "dormant_admins": m.dormant_admins,
            "invites_pending": inv.pending, "invites_stale": inv.stale,
            "login_failed_7d": failed,
            "dormant_list": dormant_list, "events": events}


CARD_SCOPE = {
    # `data_stale` темы намеренно НЕ имеет: это метка доверия к цифрам, а не
    # отдельный разрез. Кто видит цифры — должен знать, что им нельзя верить,
    # включая куратора, которому закрыты «Источники».
    "src_stale": "sources",
    "own_sla": "business.support", "ext_backlog": "business.support",
    "own_reopen": "business.support",
    "silent_surge": "business.sales", "sales_drop": "business.sales",
    "sales_out": "business.sales", "sales_visit": "business.sales",
    "st_attention": "business.sales",
    "cc_missed": "business.contacts", "cc_wrapup": "business.contacts",
    "cc_repeat": "business.contacts", "cc_escalation": "business.contacts",
    "pr_stuck": "business.projects", "pr_no_owner": "business.projects",
    "pr_frozen": "business.projects", "pr_overdue": "business.projects",
    "ops_docs": "business.ops", "ops_open": "business.ops",
    "ops_jump": "business.ops", "ops_contracts": "business.ops",
    "obj_idle_cost": "business.objects",
    "access_admins": "team.access", "access_invites": "team.access",
    # Офисное пространство: карточки о деньгах учёта, документах и сроках.
    "doc_overdue": "business.requests", "intake_waiting": "business.requests",
    "tax_overdue": "business.deadlines", "tax_next": "business.deadlines",
    "periods_open": "business.accounting",
}


KPI_SCOPE = {
    "revenue": "business.sales", "sessions": "business.sales",
    "silent": "business.sales", "cc_missed": "business.contacts",
    "own_open": "business.support", "ext_open": "business.support",
    "funnel": "business.projects", "people": "team.people",
    # Офисные плитки: у выручки свой ключ (`money_revenue`), потому что «revenue»
    # уже занят продажами сети, и общая область прав скрывала бы её не по делу.
    "money_revenue": "business.money", "profit": "business.money",
    "vat": "business.taxes",
    "receivable": "business.money", "doc_requests": "business.requests",
    "periods": "business.accounting",
}


PROFILE_SALES = {
    # профиль: (таблица, поле времени, поле выручки, поле объёма, подпись объёма,
    #           поле точки, слово для «сессии»)
    # `dt` у заправок — с часовым поясом, `started_at` у сессий — без. Окна
    # считаются вычитанием из `as_of`, и смешивать эти два типа нельзя: asyncpg
    # отвечает «can't subtract offset-naive and offset-aware datetimes».
    # Приводим время топлива к timestamp — дальше вся арифметика одинаковая.
    "fuel": ("fuel_transactions", "dt::timestamp", "amount", "liters", "Отпущено, л",
             "station_code::text", "Заправок"),
    "energy": ("charge_sessions", "started_at", "amount", "energy_kwh", "Отпущено, кВт·ч",
               "location_id", "Зарядных сессий"),
}


DEFAULT_PROFILE = "energy"


SOURCE_MIN_ROWS = 10


async def _profile(db: AsyncSession, cid: str) -> str:
    """Отраслевой профиль компании: от него зависит, что считать продажами."""
    pid = (await db.execute(text(
        "select profile_id from companies where id = :cid"), {"cid": cid})).scalar_one_or_none()
    return pid if pid in PROFILE_SALES else DEFAULT_PROFILE


def _data_sources(profile: str) -> list[dict[str, Any]]:
    """Приёмники этого профиля: у топлива продажи едут заправками, у ЭЗС — сессиями."""
    # Бухгалтерское пространство кормится другим: выгрузкой из 1С, почтой и
    # первичкой. Сетевой список там показывал пять молчащих контуров, которых в
    # компании нет вовсе, — и экран «чему верить» сам переставал вызывать доверие.
    if profile == "office":
        return [
            {"key": "gl", "label": "Проводки из 1С", "feeds": "«Деньги», «Налоги»",
             "window": 14,
             "sql": "select max(created_at) as at, count(*) as n from gl_entries"
                    " where company_id = :cid"},
            {"key": "docs", "label": "Документы из 1С", "feeds": "«Учёт», «Контрагенты»",
             "window": 14,
             "sql": "select max(created_at) as at, count(*) as n from accounting_docs"
                    " where company_id = :cid"},
            {"key": "balances", "label": "Остатки по счетам", "feeds": "«Деньги», «Сроки»",
             "window": 35,
             "sql": "select max(created_at) as at, count(*) as n from gl_balances"
                    " where company_id = :cid"},
            {"key": "intake", "label": "Первичка на приёмке", "feeds": "«Загрузка»",
             "window": 30,
             "sql": "select max(created_at) as at, count(*) as n from intake_batches"
                    " where company_id = :cid"},
            {"key": "mail", "label": "Почта компании", "feeds": "«Чего ждём», «Контрагенты»",
             "window": 14,
             "sql": "select max(created_at) as at, count(*) as n from mail_messages"
                    " where company_id = :cid"},
            {"key": "tasks", "label": "Задачи", "feeds": "«Задачи»",
             "window": 14,
             "sql": "select max(created_at) as at, count(*) as n from tasks"
                    " where company_id = :cid"},
        ]
    table, ts, _amt, _vol, _lbl, _loc, _word = PROFILE_SALES[profile]
    sales_label = "Операции АЗС" if profile == "fuel" else "Сессии сети"
    return [
        {"key": "sessions", "label": sales_label, "feeds": "«Продажи», «Где болит»",
         "window": 7,
         "sql": f"select max({ts}) as at, count(*) as n from {table} where company_id = :cid"},
        {"key": "telephony", "label": "Телефония", "feeds": "«Обращения»",
         "window": 2,
         "sql": "select max(started_at) as at, count(*) as n from call_records"},
        {"key": "tickets", "label": "Заявки", "feeds": "«Поддержка», экран дня",
         "window": 3,
         "sql": "select max(created_at) as at, count(*) as n from tickets"},
        {"key": "charges", "label": "Начисления по договорам", "feeds": "«Эксплуатация»",
         "window": 35,
         "sql": "select max(updated_at) as at, count(*) as n from ops_period_charges where company_id = :cid"},
        {"key": "projects", "label": "Проекты", "feeds": "«Проекты»",
         "window": 14,
         "sql": "select max(created_at) as at, count(*) as n from ezs_site_events where company_id = :cid"},
    ]


async def _sources_snapshot(db: AsyncSession, cid: str) -> list[dict[str, Any]]:
    """По каждому источнику: когда пришли данные и не пора ли беспокоиться.

    Различие, без которого экран врал на каждом непилотном стеке: источник, в
    котором НИКОГДА не было записей, — это не «молчит», а «контур в этом
    пространстве не ведётся». У ГИГ нет телефонии, начислений по договорам и
    проектов ЭЗС, и тревога по ним сообщала бы о поломке там, где просто другой
    набор продуктов.
    """
    profile = (await db.execute(text(
        "select profile_id from companies where id = :cid"),
        {"cid": cid})).scalar_one_or_none() or ""
    if profile != "office":
        profile = await _profile(db, cid)
    out: list[dict[str, Any]] = []
    for src in _data_sources(profile):
        try:
            params = {"cid": cid} if ":cid" in src["sql"] else {}
            r = (await db.execute(text(src["sql"]), params)).one()
        except ProgrammingError:
            await db.rollback()
            continue          # таблицы в этом стеке нет — источника тоже
        at = r.at
        days = (datetime.now(timezone.utc) - at.replace(tzinfo=timezone.utc)).days \
            if at is not None else None
        used = bool(r.n)
        out.append({
            "key": src["key"], "label": src["label"], "feeds": src["feeds"],
            "window": src["window"], "count": r.n,
            "last_at": at.isoformat() if at is not None else None,
            "days": days,
            # Контур используется в пространстве? Если нет — он не «молчит».
            "used": used,
            # Поток должен быть регулярным, чтобы молчание что-то значило: у ГИГ
            # две заявки за всё время, и «не приходят 5 дней» — не сигнал, а
            # свойство контура, который только начали вести.
            "stale": r.n >= SOURCE_MIN_ROWS and (days is None or days > src["window"]),
        })
    return out


THRESHOLDS: dict[str, dict[str, Any]] = {
    "sales_drop_pct": {"default": SALES_DROP, "unit": "%", "section": "Продажи",
        "label": "Падение выручки за неделю",
        "hint": "На сколько процентов недельная выручка должна просесть, чтобы это стало карточкой."},
    "sales_visit_ok_pct": {"default": SALES_VISIT_OK, "unit": "%", "section": "Продажи",
        "label": "Норма успешных приездов",
        "hint": "Ниже этой доли приездов с зарядом клиенты уезжают ни с чем — эскалация."},
    "pr_stuck_days": {"default": float(PR_STUCK_DAYS), "unit": "дн", "section": "Проекты",
        "label": "Проект стоит в стадии",
        "hint": "Сколько дней без смены стадии считать застреванием."},
    "pr_owner_share": {"default": PR_OWNER_SHARE * 100, "unit": "%", "section": "Проекты",
        "label": "Доля проектов без ведущего",
        "hint": "Какая часть портфеля без ответственного — уже повод сказать."},
    "ops_docs_overdue": {"default": float(OPS_DOCS_OVERDUE), "unit": "шт", "section": "Эксплуатация",
        "label": "Начислений без документа",
        "hint": "Сколько просроченных подтверждений собрать, прежде чем поднимать тревогу."},
    "ops_cost_jump_pct": {"default": OPS_COST_JUMP, "unit": "%", "section": "Эксплуатация",
        "label": "Рост стоимости месяца",
        "hint": "На сколько процентов ожидания месяца должны вырасти, чтобы спросить «почему»."},
    "obj_silent_days": {"default": float(OBJ_SILENT_DAYS), "unit": "дн", "section": "Где болит",
        "label": "Точка молчит",
        "hint": "Сколько дней без сессий считать «точка не продаёт»."},
    "obj_idle_min": {"default": float(OBJ_IDLE_COST_MIN), "unit": "шт", "section": "Где болит",
        "label": "Платных точек без выручки",
        "hint": "Сколько таких точек накопить, прежде чем выносить на экран дня."},
    "cc_wrapup_stuck": {"default": float(CC_WRAPUP_STUCK), "unit": "шт", "section": "Обращения",
        "label": "Разговоров брошено в разборе",
        "hint": "Сколько незакрытых обращений с просроченным ответом — уже система."},
    "st_silent_days": {"default": float(ST_SILENT_DAYS), "unit": "дн", "section": "Станции",
        "label": "Станция без отпуска",
        "hint": "Сколько дней данных без единого кВт·ч считать, что станция не работает."},
    "st_drop_pct": {"default": ST_DROP_PCT, "unit": "%", "section": "Станции",
        "label": "Падение выручки станции",
        "hint": "На сколько процентов недельная выручка станции должна упасть к прошлой неделе. 50% — «в 2 раза»."},
    "st_visit_ok_pct": {"default": ST_VISIT_OK, "unit": "%", "section": "Станции",
        "label": "Успешных приездов на станции",
        "hint": "Ниже этой доли приездов с зарядом станция попадает в карточку."},
    "st_avail_pct": {"default": ST_AVAIL_PCT, "unit": "%", "section": "Станции",
        "label": "Доступность станции за 30 дней",
        "hint": "Доля дней, когда витрина АСУиМ показывала станцию «Активной». Ниже — станция в карточке."},
    "digest_hour": {"default": 9.0, "unit": "ч", "section": "Доставка",
        "label": "Час утреннего письма",
        "hint": "Во сколько по Москве отправлять карточки экрана дня тем, у кого есть доступ. −1 — не отправлять."},
    "cc_missed_factor": {"default": CC_MISSED_FACTOR, "unit": "×", "section": "Обращения",
        "label": "Запас к цели по пропущенным",
        "hint": "Во сколько раз доля пропущенных должна превысить цель контакт-центра."},
}


DEFAULT_THRESHOLDS: dict[str, float] = {k: float(v["default"]) for k, v in THRESHOLDS.items()}


async def _thresholds(db: AsyncSession, cid: str) -> dict[str, float]:
    """Пороги компании поверх дефолтов. Нет таблицы или значения — берём своё."""
    th = dict(DEFAULT_THRESHOLDS)
    try:
        rows = (await db.execute(text(
            "select key, value from pulse_targets where company_id = :cid"
        ), {"cid": cid})).all()
    except ProgrammingError:
        await db.rollback()
        return th
    for r in rows:
        if r.key in th and r.value is not None:
            th[r.key] = float(r.value)
    return th


MAX_CARDS = 7


def money(v: float | int | None) -> str:
    """«3 210 978» — разделитель разрядов пробелом.

    Раньше формат делался как `f"{v:,.0f}".replace(",", " ")` прямо в тексте
    карточки, и `replace` съедал ВСЕ запятые предложения: «ждут акта или счёта,
    срок подачи прошёл» превращалось в «счёта  срок подачи прошёл».
    """
    return f"{0 if v is None else v:,.0f}".replace(",", " ")


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
    cc: dict[str, Any] | None = None, sales: dict[str, Any] | None = None,
    projects: dict[str, Any] | None = None, ops: dict[str, Any] | None = None,
    objects: dict[str, Any] | None = None, th: dict[str, float] | None = None,
    sources: list[dict[str, Any]] | None = None, access: dict[str, Any] | None = None,
    visible: set[str] | None = None, stations: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Правила экрана дня — чистая функция над уже посчитанными цифрами.

    Отделена от запросов сознательно: правила — сердце «Пульса», и проверять их
    надо без базы (`tests/test_pulse_rules.py`). Каждая карточка — сводка или
    аномалия, ни одна не заводится на отдельную запись.

    `cc` — срез контакт-центра (см. `_cc_snapshot`); None или пустой словарь =
    телефонии в пространстве нет, и правила по ней молчат.
    """
    out: list[dict[str, Any]] = []
    # Пороги: значения компании поверх дефолтов реестра. Правила ниже читают
    # только `t[...]`, чтобы «норму» нельзя было зашить мимо настройки.
    t = {**DEFAULT_THRESHOLDS, **(th or {})}

    def card(key: str, title: str, insight: str, *, count: int | None = None,
             level: str = "warn", link: str | None = None) -> None:
        if key in acked:
            return
        # Отбор картины (см. `_visible_items`) применяется ЗДЕСЬ, до колпака:
        # иначе семь мест забирали бы темы, закрытые этому человеку, и куратор
        # видел бы пустой экран при живых сообщениях по своим разрезам.
        scope = CARD_SCOPE.get(key)
        if visible is not None and scope is not None and scope not in visible:
            return
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
             count=own_sla_stale, link="/tickets?sla=breached")

    if ext_old > EXT_BACKLOG:
        card("ext_backlog", "Хвост внешней сервисной системы",
             f"{ext_old} {plural(ext_old, 'заявка', 'заявки', 'заявок')} HubEx "
             f"старше месяца. Это зеркала чужой системы: "
             f"разбирать не нам, но хвост такого размера — повод для разговора "
             f"с подрядчиком.",
             count=ext_old, link="/tickets?src=external")

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
             count=own_reopen, link="/tickets?src=own")

    # ── Контакт-центр: разговор с потребителем ──────────────────────────────
    # Правила отвечают на «дозвонились ли», «не бросили ли хвост» и «не ходит ли
    # клиент по кругу». Как считается доступность и скорость — не наше мнение, а
    # цели самого контакт-центра (`cc_kpi_targets`), иначе «Пульс» ругался бы на
    # цифры, которые операторы своей нормой не считают.
    cc = cc or {}
    calls = int(cc.get("calls") or 0)
    missed = int(cc.get("missed") or 0)
    share = cc.get("missed_share")
    share_prev = cc.get("missed_share_prev")
    target = float(cc.get("target_missed") or CC_DEFAULT_TARGETS["missed_share"])
    # Порог с запасом: цель 5% не повод будить директора на 6%. Плюс требование
    # «не лучше прошлой недели» — разовый плохой день сам себя не эскалирует.
    if calls and share is not None and share > target * t["cc_missed_factor"] \
            and (share_prev is None or share >= share_prev):
        trend = (f"неделей раньше было {share_prev:.0f}%"
                 if share_prev is not None else "сравнить не с чем")
        card("cc_missed", "До нас не дозваниваются",
             f"{missed} из {calls} звонков за неделю остались без ответа "
             f"({share:.0f}% при цели {target:.0f}%), {trend}.",
             count=missed, level="alert" if share > target * 3 else "warn",
             link="/pulse/business?view=contacts")

    stuck = int(cc.get("wrapup_stuck") or 0)
    if stuck >= t["cc_wrapup_stuck"]:
        card("cc_wrapup", "Разговоры не закрыты",
             f"{stuck} {plural(stuck, 'обращение висит', 'обращения висят', 'обращений висят')} "
             f"в разборе с просроченным ответом: разговор состоялся, а итог не оформлен.",
             count=stuck, link="/pulse/business?view=contacts")

    repeat = int(cc.get("repeat_people") or 0)
    if repeat >= CC_REPEAT_PEOPLE:
        card("cc_repeat", "Клиенты звонят повторно",
             f"{repeat} {plural(repeat, 'человек обращался', 'человека обращались', 'человек обращались')} "
             f"{CC_REPEAT_TIMES}+ раза за неделю — с первого раза вопрос не закрыли.",
             count=repeat, link="/pulse/business?view=contacts")

    # Эскалация оператора — единственное правило «Пульса», заведённое человеком,
    # а не порогом: оператор сам позвал старшего. Такое молчанием не отсеивается.
    esc = int(cc.get("escalations") or 0)
    if esc:
        card("cc_escalation", "Оператор поднял эскалацию",
             f"{esc} {plural(esc, 'обращение передано', 'обращения переданы', 'обращений переданы')} "
             f"выше по линии и ещё не разобрано.",
             count=esc, level="alert", link="/pulse/business?view=contacts")

    # ── Продажи: деньги сети ────────────────────────────────────────────────
    # Три вопроса: столько же ли продаём, вся ли сеть в работе и доезжает ли
    # клиент до заряда. Проценты считаются от НЕДЕЛИ ДАННЫХ: файл приезжает с
    # отставанием, и «за последние 7 дней» от now() резало бы живую неделю.
    sales = sales or {}
    rev, rev_prev = sales.get("revenue"), sales.get("revenue_prev")
    if rev is not None and rev_prev:
        drop = (rev_prev - rev) / rev_prev * 100
        if drop >= t["sales_drop_pct"]:
            # Причина падения важнее самого факта: меньше чеков или дешевле чек —
            # это два разных разговора, и первый ответ виден прямо в карточке.
            why = ("станций в работе стало меньше"
                   if (sales.get("live_prev") or 0) - (sales.get("live") or 0) >= 5
                   else "сессий стало меньше"
                   if (sales.get("sessions_prev") or 0) > (sales.get("sessions") or 0)
                   else "упал средний чек")
            card("sales_drop", "Выручка сети просела",
                 f"За неделю данных {money(rev)} ₽ против {money(rev_prev)} ₽ неделей "
                 f"раньше — минус {drop:.0f}%: {why}.",
                 count=int(rev_prev - rev),
                 level="alert" if drop >= t["sales_drop_pct"] * 2 else "warn", link="/pulse/business")

    out_n = int(sales.get("stations_out") or 0)
    if park and out_n >= SALES_OUT_MIN and out_n / park >= SALES_OUT_SHARE:
        lost = sales.get("stations_out_revenue") or 0
        card("sales_out", "Станции выпали из работы",
             f"{out_n} {plural(out_n, 'станция давала', 'станции давали', 'станций давали')} "
             f"сессии неделю назад и молчат всю эту — это {money(lost)} ₽ "
             f"недельной выручки.",
             count=out_n, link="/pulse/business")

    visit_ok = sales.get("visit_ok_share")
    if visit_ok is not None and visit_ok < t["sales_visit_ok_pct"]:
        card("sales_visit", "Клиенты уезжают без заряда",
             f"Зарядкой заканчивается {visit_ok:.0f}% приездов: каждый "
             f"{max(2, round(100 / max(1, 100 - visit_ok)))}-й клиент уехал ни с чем.",
             count=int(round(100 - visit_ok)), link="/pulse/business")

    # ── Станции поштучно: «Первое окно» руководителя ────────────────────────
    # Сеть в целом может выглядеть нормально, пока десяток станций стоит.
    # Одна сводная карточка, а не три: при колпаке в семь мест три отдельные
    # вытеснялись карточками контакт-центра (проверено на rushydro 29.09).
    # Список целиком живёт в «Эксплуатации», здесь — счёт и две самые дорогие.
    stations = stations or {}
    alive = int(stations.get("alive") or 0)

    def worst(key: str) -> str:
        names = [n for n in (stations.get(key) or [])[:2] if n]
        return f" ({'; '.join(names)})" if names else ""

    st_silent = int(stations.get("silent") or 0)
    st_drop = int(stations.get("drop") or 0)
    st_visit = int(stations.get("low_ok") or 0)
    parts = []
    if st_silent:
        parts.append(f"{st_silent} из {alive} не отпустили ни одного кВт·ч за "
                     f"{t['st_silent_days']:.0f} дн.{worst('silent_top')}")
    if st_drop:
        parts.append(f"у {st_drop} выручка недели упала на {t['st_drop_pct']:.0f}% и больше — "
                     f"минус {money(stations.get('drop_lost'))} ₽{worst('drop_top')}")
    if st_visit:
        parts.append(f"на {st_visit} зарядкой заканчивается меньше "
                     f"{t['st_visit_ok_pct']:.0f}% приездов{worst('low_ok_top')}")
    # Статусы витрины АСУиМ — раз в сутки, поэтому «больше суток» = две книги подряд.
    st_nolink = int(stations.get("no_link") or 0)
    st_off = int(stations.get("disabled") or 0)
    st_conn = int(stations.get("conn_fault") or 0)
    st_avail = int(stations.get("avail_low") or 0)
    if st_nolink:
        parts.append(f"{st_nolink} без связи{worst('no_link_top')}")
    if st_off:
        parts.append(f"{st_off} отключены больше суток{worst('disabled_top')}")
    if st_conn:
        parts.append(f"на {st_conn} работающих больше суток неисправен разъём{worst('conn_fault_top')}")
    if st_avail:
        parts.append(f"у {st_avail} доступность за 30 дн. ниже "
                     f"{t['st_avail_pct']:.0f}%{worst('avail_low_top')}")
    if parts:
        text_ = "; ".join(parts)
        card("st_attention", "Станции требуют разбора",
             text_[0].upper() + text_[1:] + ".",
             count=st_silent + st_drop + st_visit + st_nolink + st_off + st_conn + st_avail,
             level="alert" if alive and st_silent / alive >= 0.1 else "warn",
             link="/operations")

    # ── Проекты: что компания строит ────────────────────────────────────────
    # Портфель меряется не неделями, а тем, движется ли он вообще и есть ли у
    # каждого дела хозяин. Правки полей карточки движением не считаются: на
    # пилоте их 1156 за неделю против 5 смен стадии — «активность» без движения.
    projects = projects or {}
    active = int(projects.get("active") or 0)
    stuck = int(projects.get("stuck") or 0)
    if active and stuck >= PR_STUCK_MIN and stuck / active >= PR_STUCK_SHARE:
        worst = projects.get("stuck_stage")
        where = f", хуже всего на стадии «{worst}»" if worst else ""
        card("pr_stuck", "Проекты стоят на месте",
             f"{stuck} из {active} проектов портфеля не меняли стадию дольше "
             f"{t['pr_stuck_days']:.0f} дней{where}. Это не работа в процессе, это очередь.",
             count=stuck, link="/pulse/business?view=projects")

    no_owner = int(projects.get("no_owner") or 0)
    if active and no_owner >= PR_OWNER_MIN and no_owner / active >= t["pr_owner_share"] / 100:
        card("pr_no_owner", "Проекты без ответственного",
             f"У {no_owner} из {active} проектов не назначен ведущий — спросить "
             f"о них некого, и в отчёте они появятся только по факту провала.",
             count=no_owner, link="/pulse/business?view=projects")

    # Ноль движений за три недели — это не «спокойный период», это остановка.
    moves = projects.get("moves_3w")
    if active and moves == 0:
        card("pr_frozen", "Портфель не двигается",
             f"За {PR_MOVES_WEEKS} недели ни один проект не сменил стадию, "
             f"хотя в работе {active}.",
             count=active, level="alert", link="/pulse/business?view=projects")

    overdue = int(projects.get("overdue") or 0)
    if overdue:
        card("pr_overdue", "Просрочены обещанные действия",
             f"{overdue} {plural(overdue, 'проект перешагнул', 'проекта перешагнули', 'проектов перешагнули')} "
             f"срок следующего шага, записанный в карточке.",
             count=overdue, link="/pulse/business?view=projects")

    # ── Доступ: то, что касается руководителя лично ─────────────────────────
    # Права переживают людей: человек ушёл из проекта, а админский доступ у него
    # остался. Правило говорит только о том, что требует решения, — спящие
    # админы и приглашения, до которых никто не дошёл.
    access = access or {}
    dormant_admins = int(access.get("dormant_admins") or 0)
    invites_stale = int(access.get("invites_stale") or 0)
    if dormant_admins:
        card("access_admins", "У спящих учёток остались права админа",
             f"{dormant_admins} {plural(dormant_admins, 'человек с полным доступом не заходил', 'человека с полным доступом не заходили', 'человек с полным доступом не заходили')} "
             f"больше месяца. Права переживают людей — это вход, о котором никто не помнит.",
             count=dormant_admins, link="/pulse/team?view=access")
    if invites_stale:
        card("access_invites", "Приглашения повисли",
             f"{invites_stale} {plural(invites_stale, 'человек приглашён', 'человека приглашены', 'человек приглашены')} "
             f"больше недели назад и до сих пор не вошёл. Либо письмо не дошло, либо человек не понял, что делать.",
             count=invites_stale, link="/pulse/team?view=access")

    # ── Источники: чему сегодня можно верить ────────────────────────────────
    # Правило №0 следит за сессиями сети, но их пять, и молчащий канал заявок
    # так же обесценивает экран. Одна карточка на все источники: перечислением,
    # а не пятью строчками — это состояние обвязки, а не пять разных проблем.
    stale_src = [x for x in (sources or []) if x.get("stale") and x["key"] != "sessions"]
    if stale_src:
        names = ", ".join(f"{x['label']} ({x['days']} дн)" if x["days"] is not None
                          else f"{x['label']} (данных нет)" for x in stale_src[:4])
        card("src_stale", "Источники молчат",
             f"Данные не приходят: {names}. Цифры разделов, которые они кормят, "
             f"остались на прошлом обмене.",
             count=len(stale_src), level="alert" if len(stale_src) > 1 else "warn",
             link="/pulse?view=sources")

    # ── Объект как ось: точка сразу во всех контурах ────────────────────────
    # Самый дорогой сигнал пространства и единственный, которого нет ни в одном
    # приложении по отдельности: за точку платим аренду и энергию, а выручки с
    # неё нет. «Продажи» видят молчание, «Эксплуатация» видит расход — вместе
    # это видит только «Пульс».
    objects = objects or {}
    idle = int(objects.get("idle_cost_count") or 0)
    if idle >= t["obj_idle_min"]:
        cost = objects.get("idle_cost_amount") or 0
        card("obj_idle_cost", "Платим за точки, которые не продают",
             f"{idle} {plural(idle, 'точка', 'точки', 'точек')} без единой сессии "
             f"за {t['obj_silent_days']:.0f} дней, а расходы по договорам идут: "
             f"ожидаем {money(cost)} ₽ за два прошлых месяца.",
             count=idle, level="alert", link="/pulse/business?view=objects")

    # ── Эксплуатация: хозяйство вокруг сети ─────────────────────────────────
    # Здесь мера — не неделя, а период: месяц закрывается документами от
    # контрагентов. Руководителю важны три вещи — подтверждены ли расходы,
    # не висят ли старые месяцы и не подорожало ли хозяйство разом.
    ops = ops or {}
    docs_late = int(ops.get("docs_overdue") or 0)
    if docs_late >= t["ops_docs_overdue"]:
        amount = ops.get("docs_overdue_amount") or 0
        oldest = ops.get("docs_overdue_oldest")
        since = f" Самый старый срок — {oldest}." if oldest else ""
        card("ops_docs", "Расходы не подтверждены документами",
             f"{docs_late} начислений на {money(amount)} ₽ ждут акта или счёта, "
             f"срок подачи уже прошёл.{since} Пока документа нет, это не расход, "
             f"а обещание.",
             count=docs_late, level="alert", link="/pulse/business?view=ops")

    open_old = int(ops.get("open_periods") or 0)
    if open_old:
        card("ops_open", "Периоды не закрыты",
             f"{open_old} {plural(open_old, 'период', 'периода', 'периодов')} старше "
             f"{OPS_OPEN_MONTHS} месяцев "
             f"{plural(open_old, 'остаётся открытым', 'остаются открытыми', 'остаются открытыми')}: "
             f"цифры прошлых месяцев ещё могут измениться.",
             count=open_old, link="/pulse/business?view=ops")

    expired = int(ops.get("contracts_expired") or 0)
    if expired:
        card("ops_contracts", "Договоры с истёкшим сроком",
             f"{expired} {plural(expired, 'договор действует', 'договора действуют', 'договоров действуют')} "
             f"за пределами своего срока и не закрыт: платим по бумаге, которой формально уже нет.",
             count=expired, link="/pulse/business?view=ops")

    jump = ops.get("cost_jump_pct")
    if jump is not None and jump >= t["ops_cost_jump_pct"]:
        card("ops_jump", "Хозяйство подорожало",
             f"Ожидания месяца выросли на {jump:.0f}% против прошлого "
             f"({money(ops.get('expected'))} ₽ против {money(ops.get('expected_prev'))} ₽) — "
             f"стоит посмотреть, у кого именно.",
             count=int(round(jump)), link="/pulse/business?view=ops")

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
    """Динамика в процентах. Молчит, когда любое из окон пусто.

    Ноль в ТЕКУЩЕМ окне почти всегда означает «данные ещё не доехали», а не падение
    до нуля, — и «−100 %» на плитке читается как катастрофа. Та же защита стоит в
    `_delta` с тем же обоснованием: это самая опасная ложь витрины.
    """
    if not prev or not cur:
        return None
    return round((cur - prev) / prev * 100, 1)


async def _cc_targets(db: AsyncSession) -> dict[str, float]:
    """Цели контакт-центра из его же настроек; чего не задали — берём по умолчанию.

    `distinct on (metric)`: наборов целей в базе может быть несколько (компания и
    заводская заготовка), и без выбора «самой свежей» одна метрика приезжала
    дважды с разными числами.
    """
    targets = dict(CC_DEFAULT_TARGETS)
    if not (await db.execute(text("select to_regclass('public.cc_kpi_targets')"))).scalar():
        return targets
    try:
        rows = (await db.execute(text("""
            select distinct on (metric) metric, target
            from cc_kpi_targets order by metric, updated_at desc nulls last
        """))).all()
    except ProgrammingError:
        # Таблица видна в каталоге, но SELECT не выдан: у контура Поддержки свой
        # владелец, и гранты на новые таблицы появляются не сразу. Это не повод
        # ронять экран — работаем на целях по умолчанию.
        await db.rollback()
        return targets
    for r in rows:
        if r.target is not None:
            targets[r.metric] = float(r.target)
    return targets


async def _sales_snapshot(db: AsyncSession, cid: str, as_of: datetime | None,
                          profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    """Срез продаж: неделя ДАННЫХ против предыдущей.

    Окна от `as_of`, а не от now(): выгрузка приезжает файлом с отставанием в
    несколько дней, и «последние 7 дней» по календарю отрезали бы половину живой
    недели — цифра падала бы каждый раз, когда файл задержался.
    """
    if as_of is None:
        return {}
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]
    # Визит (клиент приехал и уехал заряженным) — понятие ЭЗС: у заправки его нет,
    # там каждая операция самостоятельна. На топливе показатель просто не считается.
    VISIT_KEY = "visit_key" if profile == "energy" else "null::text"
    VISIT_OK = "visit_charged" if profile == "energy" else "false"
    p = {"cid": cid, "as_of": as_of}
    m = (await db.execute(text(f"""
        select
          count(*) filter (where w = 0) as sessions,
          count(*) filter (where w = 1) as sessions_prev,
          coalesce(sum({AMT}) filter (where w = 0), 0) as revenue,
          coalesce(sum({AMT}) filter (where w = 1), 0) as revenue_prev,
          coalesce(sum({VOL}) filter (where w = 0), 0) as kwh,
          coalesce(sum({VOL}) filter (where w = 1), 0) as kwh_prev,
          count(distinct loc) filter (where w = 0) as live,
          count(distinct loc) filter (where w = 1) as live_prev,
          count(distinct visit_key) filter (where w = 0) as visits,
          count(distinct visit_key) filter (where w = 1) as visits_prev,
          count(distinct visit_key) filter (where w = 0 and visit_charged) as visits_ok,
          count(distinct visit_key) filter (where w = 1 and visit_charged) as visits_ok_prev
        from (
          select {AMT}, {VOL}, {LOC} as loc, {VISIT_KEY} as visit_key,
                 {VISIT_OK} as visit_charged,
                 case when {TS} > CAST(:as_of AS timestamp) - interval '7 days'
                      then 0 else 1 end as w
          from {TBL}
          where company_id = :cid
            and {TS} > CAST(:as_of AS timestamp) - interval '14 days'
        ) x
    """), p)).one()

    # Выпавшие из работы: станция давала сессии неделю назад и молчит всю эту.
    # Это не то же самое, что «молчит 48 часов»: там разовая пауза, здесь неделя.
    out = (await db.execute(text(f"""
        with cur as (
          select distinct {LOC} as loc from {TBL}
          where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '7 days'
        ), prev as (
          select {LOC} as loc, coalesce(sum({AMT}), 0) as rev from {TBL}
          where company_id = :cid
            and {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
            and {TS} > CAST(:as_of AS timestamp) - interval '14 days'
          group by 1
        )
        select count(*) as n, coalesce(sum(rev), 0) as rev
        from prev where loc not in (select loc from cur)
    """), p)).one()

    def share(ok: int, total: int) -> float | None:
        return round(100.0 * ok / total, 1) if total else None

    return {
        "sessions": m.sessions, "sessions_prev": m.sessions_prev,
        "revenue": float(m.revenue), "revenue_prev": float(m.revenue_prev),
        "kwh": float(m.kwh), "kwh_prev": float(m.kwh_prev),
        "live": m.live, "live_prev": m.live_prev,
        "avg_check": round(float(m.revenue) / m.sessions, 1) if m.sessions else None,
        "avg_check_prev": round(float(m.revenue_prev) / m.sessions_prev, 1) if m.sessions_prev else None,
        "visits": m.visits, "visits_prev": m.visits_prev,
        "visit_ok_share": share(m.visits_ok, m.visits),
        "visit_ok_share_prev": share(m.visits_ok_prev, m.visits_prev),
        "stations_out": out.n, "stations_out_revenue": float(out.rev),
    }


_OBJECTS_SQL_TPL = """
with a as (
  select max({TS}) as t from {TBL} where company_id = :cid
), sess as (
  select cs.{LOC} as location_id,
         max(cs.{TS}) as last_at,
         coalesce(sum(cs.{AMT}) filter (
           where cs.{TS} > a.t - interval '7 days'), 0) as rev,
         coalesce(sum(cs.{AMT}) filter (
           where cs.{TS} <= a.t - interval '7 days'
             and cs.{TS} > a.t - interval '14 days'), 0) as rev_prev
  from {TBL} cs, a
  where cs.company_id = :cid
  group by cs.{LOC}
), cost as (
  select ch.location_id,
         coalesce(sum(ch.expected_gross), 0) as cost,
         count(*) filter (where ch.doc_id is null
              and ch.doc_due_on ~ '^\\d{4}-\\d{2}-\\d{2}$'
              and ch.doc_due_on::date < current_date) as late_docs
  from ops_period_charges ch
  where ch.company_id = :cid
    -- Два последних ПОЛНЫХ месяца, как сказано в подписи. Было «с 1-го числа
    -- позапрошлого месяца» — три периода с текущим целиком (14.10.2026).
    and ch.period >= to_char(date_trunc('month', current_date) - interval '2 month', 'YYYY-MM-01')
    and ch.period < to_char(date_trunc('month', current_date), 'YYYY-MM-01')
  group by ch.location_id
)
select sl.id, sl.name, coalesce(sl.code, '') as code,
       coalesce(c.cost, 0) as cost, coalesce(c.late_docs, 0) as late_docs,
       coalesce(s.rev, 0) as rev, coalesce(s.rev_prev, 0) as rev_prev,
       s.last_at,
       -- Признак 1: платим, а точка не продаёт (самый дорогой случай).
       (coalesce(c.cost, 0) > 0 and (s.last_at is null
          or s.last_at < (select t from a) - make_interval(days => :silent))) as idle_cost,
       -- Признак 2: выручка недели провалилась к предыдущей.
       (coalesce(s.rev_prev, 0) > 5000
          and coalesce(s.rev, 0) < coalesce(s.rev_prev, 0) * :drop_ratio) as revenue_drop,
       -- Признак 3: расходы точки не подтверждены после срока.
       (coalesce(c.late_docs, 0) > 0) as docs_late,
       -- Признак 4: точка молчит, хотя раньше работала.
       (s.last_at is not null
          and s.last_at < (select t from a) - interval '7 days') as silent
from service_locations sl
left join sess s on s.location_id = {OBJ_KEY}
left join cost c on c.location_id = sl.id
where sl.company_id = :cid and (s.location_id is not null or c.location_id is not null)
"""


async def _objects_snapshot(db: AsyncSession, cid: str) -> dict[str, Any]:
    """Точки, где сошлось несколько признаков сразу.

    Балл не «рейтинг проблемности», а счётчик независимых сигналов: одна
    просроченная бумага — работа бухгалтерии, а вот молчание плюс расход плюс
    неподтверждённые документы на одной точке — это уже вопрос к руководителю.
    """
    profile = await _profile(db, cid)
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]
    # Подстановка через replace, а не format: в шаблоне есть регулярное
    # выражение с фигурными скобками (`\d{4}-\d{2}-\d{2}`), и format принял бы
    # их за поля подстановки.
    sql = _OBJECTS_SQL_TPL
    obj_key = "sl.id" if profile == "energy" else "sl.code"
    for name, value in (("{TBL}", TBL), ("{TS}", TS), ("{AMT}", AMT), ("{LOC}", LOC),
                        ("{OBJ_KEY}", obj_key)):
        sql = sql.replace(name, value)
    rows = (await db.execute(text(sql), {
        "cid": cid, "silent": OBJ_SILENT_DAYS, "drop_ratio": 1 - OBJ_DROP_PCT / 100,
    })).all()
    if not rows:
        return {}

    pain = []
    idle_n = idle_amount = 0.0
    for r in rows:
        flags = [f for f, on in (
            ("idle_cost", r.idle_cost), ("revenue_drop", r.revenue_drop),
            ("docs_late", r.docs_late), ("silent", r.silent)) if on]
        if r.idle_cost:
            idle_n += 1
            idle_amount += float(r.cost or 0)
        if len(flags) >= OBJ_PAIN_MIN:
            # Цена вопроса = что платим за точку плюс сколько выручки потеряли.
            at_risk = float(r.cost or 0) + max(0.0, float(r.rev_prev or 0) - float(r.rev or 0))
            pain.append({
                "id": r.id, "name": r.name or r.code or r.id, "code": r.code,
                "flags": flags, "cost": float(r.cost or 0),
                "revenue": float(r.rev or 0), "revenue_prev": float(r.rev_prev or 0),
                "late_docs": r.late_docs,
                "last_session": r.last_at.isoformat() if r.last_at else None,
                "at_risk": at_risk,
            })
    pain.sort(key=lambda p: (-len(p["flags"]), -p["at_risk"]))
    return {
        "total": len(rows), "pain": pain, "pain_count": len(pain),
        "idle_cost_count": int(idle_n), "idle_cost_amount": idle_amount,
        "at_risk_total": sum(p["at_risk"] for p in pain),
    }


async def _stations_snapshot(db: AsyncSession, cid: str, as_of: datetime | None,
                             th: dict[str, float]) -> dict[str, Any]:
    """Сигналы по каждой ЭЗС: молчит, провалила выручку, не заряжает.

    Окна от `as_of`, как и у среза продаж. Только профиль energy: приезд
    (`visit_*`) и кВт·ч — понятия зарядной сети.
    """
    if await _profile(db, cid) != "energy":
        return {}
    out = await _stations_status(db, cid, th)
    if as_of is None:
        return out
    rows = (await db.execute(text("""
        with s as (
          select location_id,
                 max(station_name) as name,
                 coalesce(sum(energy_kwh) filter (
                   where started_at > CAST(:as_of AS timestamp) - make_interval(days => :silent)), 0) as kwh_recent,
                 coalesce(sum(amount) filter (
                   where started_at > CAST(:as_of AS timestamp) - interval '30 days'), 0) as rev30,
                 coalesce(sum(amount) filter (
                   where started_at > CAST(:as_of AS timestamp) - interval '7 days'), 0) as rev,
                 coalesce(sum(amount) filter (
                   where started_at <= CAST(:as_of AS timestamp) - interval '7 days'
                     and started_at > CAST(:as_of AS timestamp) - interval '14 days'), 0) as rev_prev,
                 count(*) filter (where visit_seq = 1
                   and started_at > CAST(:as_of AS timestamp) - interval '7 days') as visits,
                 count(*) filter (where visit_seq = 1 and visit_charged
                   and started_at > CAST(:as_of AS timestamp) - interval '7 days') as visits_ok
          from charge_sessions
          where company_id = :cid and location_id is not null
            and started_at > CAST(:as_of AS timestamp) - make_interval(days => :alive)
          group by location_id
        )
        -- Имя — из реестра объектов: в сессиях оно пустое у части станций.
        select concat_ws(', ', coalesce(sl.name, s.name),
                         nullif(sl.city, coalesce(sl.name, s.name))) as name,
               rev30, rev, rev_prev, visits, visits_ok,
               kwh_recent = 0 as silent,
               rev_prev > :floor and rev <= rev_prev * CAST(:keep AS numeric) as fell,
               -- Тип параметра явно: у count() он bigint, и драйвер привёл бы 0.7 к 0.
               visits >= :vmin and visits_ok < visits * CAST(:ok AS float) as low_ok
        from s left join service_locations sl on sl.id = s.location_id
    """), {
        "cid": cid, "as_of": as_of, "alive": ST_ALIVE_DAYS,
        "silent": int(th["st_silent_days"]), "floor": ST_DROP_FLOOR,
        "keep": 1 - th["st_drop_pct"] / 100, "vmin": ST_VISIT_MIN,
        "ok": th["st_visit_ok_pct"] / 100,
    })).all()
    if not rows:
        return out

    def top(flag: str, key) -> list[str]:
        return [r.name for r in sorted((r for r in rows if getattr(r, flag)), key=key)]

    drops = [r for r in rows if r.fell]
    return {
        **out,
        "alive": len(rows),
        # Первыми — те, что приносили больше всего: их молчание дороже.
        "silent": sum(1 for r in rows if r.silent),
        "silent_top": top("silent", lambda r: -float(r.rev30)),
        "drop": len(drops),
        "drop_lost": sum(float(r.rev_prev) - float(r.rev) for r in drops),
        "drop_top": top("fell", lambda r: float(r.rev) - float(r.rev_prev)),
        "low_ok": sum(1 for r in rows if r.low_ok),
        "low_ok_top": top("low_ok", lambda r: -(r.visits - r.visits_ok)),
    }


async def _stations_status(db: AsyncSession, cid: str, th: dict[str, float]) -> dict[str, Any]:
    """Сигналы по статусам витрины АСУиМ: без связи, отключена, разъём, доступность."""
    from app.services.station_status_days import status_signals

    sig = await status_signals(db, cid, th["st_avail_pct"])
    if not sig:
        return {}
    ids = {lid for key in ("no_link", "disabled", "conn_fault", "avail_low") for lid, _ in sig[key]}
    names = {r.id: r.name for r in (await db.execute(text(
        "select id, concat_ws(', ', name, nullif(city, name)) as name "
        "from service_locations where id = any(:ids)"), {"ids": list(ids)})).all()} if ids else {}

    def dm(since) -> str:
        d, open_start = since
        return f"с {d.day:02d}.{d.month:02d}" + (" и раньше" if open_start else "")

    return {
        "status_day": sig["status_day"],
        "no_link": len(sig["no_link"]),
        "no_link_top": [f"{names.get(i) or i} {dm(d)}" for i, d in sig["no_link"]],
        "disabled": len(sig["disabled"]),
        "disabled_top": [f"{names.get(i) or i} {dm(d)}" for i, d in sig["disabled"]],
        "conn_fault": len(sig["conn_fault"]),
        "conn_fault_top": [names.get(i) or i for i, _ in sig["conn_fault"]],
        "avail_low": len(sig["avail_low"]),
        "avail_low_top": [f"{names.get(i) or i} {p}%" for i, p in sig["avail_low"]],
    }


async def _ops_snapshot(db: AsyncSession, cid: str) -> dict[str, Any]:
    """Срез хозяйства: сколько ждём в этом периоде и что не подтверждено.

    Период здесь — календарный месяц (`ops_period_charges.period` хранится
    строкой «YYYY-MM-01»). Ожидание — то, что мы ДОЛЖНЫ по договорам; факт
    появляется, когда контрагент прислал акт или счёт (`doc_id`). Пока документа
    нет, это не расход, а обещание — на этом и построены правила.
    """
    cur = (await db.execute(text(
        "select to_char(current_date, 'YYYY-MM-01')"
    ))).scalar_one()
    prev = (await db.execute(text(
        "select to_char(current_date - interval '1 month', 'YYYY-MM-01')"
    ))).scalar_one()

    m = (await db.execute(text("""
        select
          count(*) filter (where period = :cur) as charges,
          coalesce(sum(expected_gross) filter (where period = :cur), 0) as expected,
          coalesce(sum(expected_gross) filter (where period = :prev), 0) as expected_prev,
          count(*) filter (where period = :cur and doc_id is null) as no_doc,
          coalesce(sum(expected_gross) filter (where period = :cur and doc_id is null), 0) as no_doc_amount
        from ops_period_charges where company_id = :cid
    """), {"cid": cid, "cur": cur, "prev": prev})).one()

    # Просрочка подтверждения: срок подачи документа прошёл, а документа нет.
    # Даты в этой таблице строковые — каст только по формату ISO.
    d = "^\\d{4}-\\d{2}-\\d{2}$"
    late = (await db.execute(text(f"""
        select count(*) as n, coalesce(sum(expected_gross), 0) as amount,
               min(doc_due_on) as oldest
        from ops_period_charges
        where company_id = :cid and doc_id is null and doc_due_on ~ '{d}'
          and doc_due_on::date < current_date
    """), {"cid": cid})).one()

    by_item = {r.cost_item: {"expected": float(r.expected or 0), "count": r.n,
                             "prev": float(r.prev or 0)}
               for r in (await db.execute(text("""
        select cost_item, count(*) filter (where period = :cur) as n,
               sum(expected_gross) filter (where period = :cur) as expected,
               sum(expected_gross) filter (where period = :prev) as prev
        from ops_period_charges
        where company_id = :cid and period in (:cur, :prev)
        group by cost_item order by expected desc nulls last
    """), {"cid": cid, "cur": cur, "prev": prev})).all()}

    # Открытые периоды старше порога: закрытый месяц не переписывается, а
    # открытый — ещё может, и цифры прошлого квартала гуляют.
    open_old = (await db.execute(text("""
        select count(*) from ops_period_close
        where company_id = :cid and status <> 'closed'
          and period::date < date_trunc('month', current_date)
                             - make_interval(months => :months)
    """), {"cid": cid, "months": OPS_OPEN_MONTHS})).scalar_one()

    # Договор — основание расхода: без действующего договора начисление нечем
    # подтвердить, а истёкший срок означает, что платим по бумаге, которой уже
    # нет. Даты здесь строковые, поэтому каст только по формату ISO.
    d_iso = r"^\d{4}-\d{2}-\d{2}$"
    ctr = (await db.execute(text(f"""
        select count(*) as total,
               count(nullif(valid_until, '')) as with_term,
               count(*) filter (where valid_until ~ '{d_iso}'
                    and valid_until::date < current_date
                    and not coalesce(is_closed, false)) as expired,
               count(*) filter (where valid_until ~ '{d_iso}'
                    and valid_until::date between current_date and current_date + 60
                    and not coalesce(is_closed, false)) as ending
        from contracts where company_id = :cid
    """), {"cid": cid})).one()

    exp, exp_prev = float(m.expected), float(m.expected_prev)
    return {
        "period": cur, "period_prev": prev,
        "contracts_total": ctr.total, "contracts_with_term": ctr.with_term,
        "contracts_expired": ctr.expired, "contracts_ending": ctr.ending,
        "charges": m.charges, "expected": exp, "expected_prev": exp_prev,
        "no_doc": m.no_doc, "no_doc_amount": float(m.no_doc_amount),
        "docs_overdue": late.n, "docs_overdue_amount": float(late.amount),
        "docs_overdue_oldest": late.oldest,
        "open_periods": open_old,
        "cost_jump_pct": round((exp - exp_prev) / exp_prev * 100, 1) if exp_prev else None,
        "by_item": by_item,
    }


async def _projects_snapshot(db: AsyncSession, cid: str) -> dict[str, Any]:
    """Срез портфеля: движется ли стройка и есть ли у дел хозяин.

    Даты в `ezs_projects` хранятся строками (`stage_since`, `next_action_due`) —
    каст обязателен, иначе «operator does not exist: character varying >= date».
    Пустая строка и мусор в дате не должны ронять экран, поэтому сравнение идёт
    через `nullif(...)` и регулярное выражение на формат.
    """
    d = "^\\d{4}-\\d{2}-\\d{2}$"      # только ISO-дата; всё остальное игнорируем
    m = (await db.execute(text(f"""
        select count(*) as active,
               count(*) filter (where owner_user_id is null) as no_owner,
               count(*) filter (where stage_since ~ '{d}'
                    and current_date - stage_since::date > :days) as stuck,
               count(*) filter (where next_action_due ~ '{d}'
                    and next_action_due::date < current_date) as overdue
        from ezs_projects
        where company_id = :cid and stage <> 'archive'
    """), {"cid": cid, "days": PR_STUCK_DAYS})).one()

    # Стадия, где застряло больше всего: карточке нужно не только «сколько», но
    # и «где» — иначе руководитель идёт искать сам.
    stuck_stage = (await db.execute(text(f"""
        select stage from ezs_projects
        where company_id = :cid and stage <> 'archive' and stage_since ~ '{d}'
          and current_date - stage_since::date > :days
        group by stage order by count(*) desc limit 1
    """), {"cid": cid, "days": PR_STUCK_DAYS})).scalar_one_or_none()

    # Движение = смена стадии или пройденный гейт. Правки полей (`edit`) — шум:
    # на пилоте их 1156 за неделю при 5 реальных переходах.
    moves = (await db.execute(text("""
        select count(*) filter (where kind = 'stage'
                 and created_at >= now() - interval '7 days') as w1,
               count(*) filter (where kind = 'stage'
                 and created_at >= now() - interval '14 days'
                 and created_at < now() - interval '7 days') as w2,
               count(*) filter (where kind = 'stage'
                 and created_at >= now() - make_interval(weeks => :weeks)) as w3,
               count(*) filter (where kind = 'gate'
                 and created_at >= now() - interval '7 days') as gates
        from ezs_site_events where company_id = :cid
    """), {"cid": cid, "weeks": PR_MOVES_WEEKS})).one()

    return {
        "active": m.active, "no_owner": m.no_owner, "stuck": m.stuck,
        "overdue": m.overdue, "stuck_stage": STAGE_LABELS.get(stuck_stage, stuck_stage),
        "moves": moves.w1, "moves_prev": moves.w2, "moves_3w": moves.w3,
        "gates": moves.gates,
    }


async def _cc_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Обёртка: любой отказ контура Поддержки гасит только раздел, а не экран."""
    try:
        return await _cc_measure(db)
    except ProgrammingError:
        await db.rollback()
        return {}


async def _cc_measure(db: AsyncSession) -> dict[str, Any]:
    """Срез контакт-центра за 7 дней против предыдущих семи.

    Пусто, если телефонии в пространстве нет ИЛИ если таблицы контура Поддержки
    приложению не отданы: у стека без контакт-центра таблиц
    `call_records`/`inbox_threads` не существует, а на новых таблицах может не
    оказаться гранта — и то, и другое уронило бы весь экран дня, а он обязан
    открываться всегда.

    company_id тут не фильтруется — по той же причине, что и в витрине заявок
    (пространство однокомпанийное, предусловие мультикомпанийности чинится в
    одном месте, PULSE.md §7).
    """
    has = (await db.execute(text(
        "select to_regclass('public.call_records') is not null"
        "   and to_regclass('public.inbox_threads') is not null"
    ))).scalar()
    if not has:
        return {}

    targets = await _cc_targets(db)
    frt_target = targets["first_response_sec"]

    c = (await db.execute(text("""
        select count(*) filter (where w = 0) as calls,
               count(*) filter (where w = 0 and missed) as missed,
               count(*) filter (where w = 1) as calls_prev,
               count(*) filter (where w = 1 and missed) as missed_prev,
               avg(wait_sec) filter (where w = 0) as wait,
               avg(wait_sec) filter (where w = 1) as wait_prev
        from (
          select missed, wait_sec,
                 case when started_at >= now() - interval '7 days' then 0 else 1 end as w
          from call_records
          where direction = 'inbound' and started_at >= now() - interval '14 days'
        ) x
    """))).one()

    t = (await db.execute(text("""
        select avg(frt) filter (where w = 0) as frt,
               avg(frt) filter (where w = 1) as frt_prev,
               count(*) filter (where w = 0 and frt is not null) as answered,
               count(*) filter (where w = 1 and frt is not null) as answered_prev,
               count(*) filter (where w = 0 and frt is not null and frt <= :frt_target) as in_sla,
               count(*) filter (where w = 1 and frt is not null and frt <= :frt_target) as in_sla_prev
        from (
          select extract(epoch from (first_response_at - created_at)) as frt,
                 case when created_at >= now() - interval '7 days' then 0 else 1 end as w
          from inbox_threads
          where created_at >= now() - interval '14 days'
        ) x
    """), {"frt_target": frt_target})).one()

    # Разговор состоялся, а итог не оформлен: тред остался в разборе, и срок
    # ответа уже вышел. Это не «медленно», это брошено.
    stuck = (await db.execute(text("""
        select count(*) from inbox_threads
        where closed_at is null and response_due_at < now()
    """))).scalar_one()

    repeat = (await db.execute(text("""
        select count(*) from (
          select contact_id from inbox_threads
          where contact_id is not null and created_at >= now() - interval '7 days'
          group by contact_id having count(*) >= :times
        ) x
    """), {"times": CC_REPEAT_TIMES})).scalar_one()

    esc = 0
    if (await db.execute(text("select to_regclass('public.cc_escalations')"))).scalar():
        esc = (await db.execute(text(
            "select count(*) from cc_escalations where resolved_at is null"
        ))).scalar_one()

    def share(missed: int | None, total: int | None) -> float | None:
        return round(100.0 * missed / total, 1) if total else None

    return {
        "calls": c.calls, "calls_prev": c.calls_prev,
        "missed": c.missed, "missed_prev": c.missed_prev,
        "missed_share": share(c.missed, c.calls),
        "missed_share_prev": share(c.missed_prev, c.calls_prev),
        "wait": round(float(c.wait), 1) if c.wait is not None else None,
        "wait_prev": round(float(c.wait_prev), 1) if c.wait_prev is not None else None,
        "frt": round(float(t.frt), 1) if t.frt is not None else None,
        "frt_prev": round(float(t.frt_prev), 1) if t.frt_prev is not None else None,
        "in_sla_share": share(t.in_sla, t.answered),
        "in_sla_share_prev": share(t.in_sla_prev, t.answered_prev),
        "answered": t.answered,
        "wrapup_stuck": stuck, "repeat_people": repeat, "escalations": esc,
        "target_missed": targets["missed_share"],
        "target_frt": frt_target,
        "target_in_sla": targets["in_sla_share"],
    }


async def pulse_day_data(db: AsyncSession, company_id: str,
                         visible: set[str] | None = None) -> dict[str, Any]:
    """Данные экрана дня без проверки доступа — её делает вызывающий.

    Отдельной функцией, потому что плитку «Пульса» на рабочем столе считает тот же
    код (`services/space_desk._pulse`): второй набор правил разошёлся бы с первым,
    и плитка начала бы врать про то, что внутри.
    """
    cid = str(company_id)
    # Заявки лежат в схеме Поддержки, где company_id свой: без карты
    # соответствия компания видела бы чужие счётчики. Нет карты — считаем
    # по несуществующей компании, то есть ноль, а не всё подряд.
    support_cid = await support_company_id(db, cid) or "-"
    # Чем мерить продажи, решает профиль: у топливного пространства это заправки,
    # у ЭЗС — зарядные сессии. Раньше таблица была зашита, и на профиле fuel экран
    # дня тревожно писал «Данных о сессиях нет» при 376 744 живых заправках.
    # У бухгалтерского пространства сети нет вовсе, и весь сетевой набор — сессии,
    # молчащие станции, воронка проектов — давал пустой экран с тревожной карточкой
    # «Данных о сессиях нет». Там мерят другим: деньгами учёта, документами и сроками.
    # Профиль спрашиваем НАПРЯМУЮ: `_profile` знает только отраслевые профили
    # продаж и всё остальное сводит к `energy` — «office» до проверки не доживал.
    if (await db.execute(text(
            "select profile_id from companies where id = :cid"),
            {"cid": cid})).scalar_one_or_none() == "office":
        # У office-профиля два разных дня. Где ведут учёт («Аудит») — деньги из 1С.
        # Где учёта нет и ведут работу (ElsyPlus, решение МАГа 07.09.2026) — поручения,
        # визы, встречи, заявки и люди: бухгалтерский набор давал там пять нулей и
        # тревожную карточку «Данных учёта нет» про то, чего в пространстве и не должно
        # быть. Разделяем по факту: есть ли хоть одна проводка.
        has_ledger = (await db.execute(text(
            "select 1 from gl_entries where company_id = CAST(:cid AS uuid) limit 1"),
            {"cid": cid})).scalar()
        return await (_office_day_data if has_ledger else _work_day_data)(db, cid, visible)
    profile = await _profile(db, cid)
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]

    # ── Свежесть: правило №0. as_of — дата данных, под ним живут все окна ──
    as_of = (await db.execute(text(
        f"select max({TS}) from {TBL} where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()
    stale_days: int | None = None
    if as_of is not None:
        as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        stale_days = (datetime.now(timezone.utc) - as_of_utc).days

    # ── Сеть и продажи: 7 дней данных против предыдущих 7 ──
    s = (await db.execute(text(f"""
        select count(*) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days') as s7,
               coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0) as r7,
               count(*) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
                                and {TS} > CAST(:as_of AS timestamp) - interval '14 days') as s7p,
               coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
                                and {TS} > CAST(:as_of AS timestamp) - interval '14 days'), 0) as r7p
        from {TBL} where company_id = :cid
    """), {"cid": cid, "as_of": as_of})).one() if as_of else None

    # Молчащие — по парку станций, когда-либо дававших сессии (как в
    # «Продажах» silent-stations: сравнивать с реестром объектов нельзя,
    # неподключённые станции — другая история, не эскалация оборудования).
    silent = (await db.execute(text(f"""
        with ever as (
            select {LOC} as loc, max({TS}) as last_at
              from {TBL}
             where company_id = :cid and {LOC} is not null
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
    # Заявки — чужой контур: без прав на него экран показывает остальное.
    t = _TicketsZero() if not await _tickets_available(db) else (await db.execute(text(f"""
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
          and company_id::text = :support_cid
    """), {"support_cid": support_cid})).one()

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
        kpi.append(_kpi("sessions", f"{SESS_WORD} за 7 дн", s.s7,
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
    # Пустой контур не показываем: ноль по продукту, которого в пространстве нет,
    # читается как «всё встало», а не как «мы этим не пользуемся».
    if t.own_open or t.ext_open:
        kpi.append(_kpi("own_open", "Свои заявки", t.own_open,
                        note=f"SLA нарушен: {t.own_sla}",
                        state="warn" if t.own_sla_stale else None,
                        link="/tickets?src=own", higher_is_better=False))
    if t.ext_open:
        kpi.append(_kpi("ext_open", "Заявки подрядчика", t.ext_open,
                        note=f"старше месяца: {t.ext_old}",
                        link="/tickets?src=external", higher_is_better=False))
    active_projects = sum(r.n for r in funnel)
    if active_projects:
        kpi.append(_kpi("funnel", "Проекты в работе", active_projects,
                        note=f"введено за 30 дн: {commissioned_30d}",
                        link="/pulse/business?view=projects"))
    kpi.append(_kpi("people", "Сейчас в системе", p.online,
                    note=f"за сегодня: {p.today} из {p.total}",
                    link="/pulse/team"))

    sales = await _sales_snapshot(db, cid, as_of, profile)
    projects = await _projects_snapshot(db, cid)
    ops = await _ops_snapshot(db, cid)
    objects = await _objects_snapshot(db, cid)
    th = await _thresholds(db, cid)
    sources = await _sources_snapshot(db, cid)
    access = await _access_snapshot(db, cid)
    stations = await _stations_snapshot(db, cid, as_of, th)

    # ── Разговор с потребителем: одна плитка, подробности — в «Обращениях» ──
    cc = await _cc_snapshot(db)
    if cc.get("calls"):
        cc_share = cc["missed_share"]
        kpi.append(_kpi(
            "cc_missed", "Пропущено звонков", cc["missed"],
            delta_pct=_dpct(cc["missed"], cc["missed_prev"]),
            note=f"из {cc['calls']} за неделю · цель ≤ {cc['target_missed']:.0f}%",
            state="warn" if cc_share is not None and cc_share > cc["target_missed"] else None,
            link="/pulse/business?view=contacts", higher_is_better=False))

    # ── Карточки-эскалации: аномалия или сводка, не запись (PULSE.md §7) ──
    # Карточка не показывается, если её приняли сегодня ИЛИ отложили на срок,
    # который ещё не наступил. Отложенное живёт в «Принятом» со своей датой.
    acked = {r.card_key for r in (await db.execute(text("""
        select card_key from pulse_acks
        where company_id = :cid
          and (acked_on = current_date
               or (snooze_until is not null and snooze_until >= current_date))
    """), {"cid": cid})).all()}
    cards = build_cards(
        as_of=as_of, stale_days=stale_days,
        own_sla_stale=t.own_sla_stale, own_reopen=t.own_reopen, ext_old=t.ext_old,
        silent=(silent.silent if silent else 0), park=(silent.park if silent else 0),
        acked=acked, cc=cc, sales=sales, projects=projects, ops=ops, objects=objects,
        th=th, sources=sources, access=access, visible=visible, stations=stations,
    )

    # Карточки отобраны внутри правил (до колпака), здесь остаются плитки:
    # цифра закрытого разреза — та же информация, только числом.
    if visible is not None:
        kpi = [k for k in kpi if KPI_SCOPE.get(k["key"]) is None
               or KPI_SCOPE[k["key"]] in visible]

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "stale_days": stale_days,
        "kpi": kpi,
        "cards": cards,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


_MONTHS_RU = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


async def _books_anchor(db: AsyncSession, cid: str) -> date:
    """Последний месяц, за который в учёте есть проводки.

    Выгрузка из 1С приезжает с задержкой: у аутсорсера август идёт, а закрытые
    цифры кончаются июлем. Считать «за текущий месяц» по календарю значит
    показать руководителю и заказчику ноль — тогда как деньги за период есть.
    Опора — последний месяц с данными, и он же называется в подписи.
    """
    # Месяц опознаётся по ХОЗЯЙСТВЕННОЙ деятельности — оборотам счетов результата
    # (90/91), а не по числу проводок. В идущем месяце уже есть зарплата, отпуска и
    # платежи по ЕНС: два десятка проводок без единой продажи. По ним якорь уезжал на
    # такой месяц, и витрина показывала «Выручка за месяц 0 ₽, −100 %» — ровно тот ноль,
    # ради избежания которого якорь и написан.
    row = (await db.execute(text("""
        SELECT period_year, period_month FROM gl_entries
         WHERE company_id = CAST(:cid AS uuid)
           AND (account_dt LIKE '90%' OR account_kt LIKE '90%'
                OR account_dt LIKE '91%' OR account_kt LIKE '91%')
         GROUP BY 1, 2 HAVING count(*) > 2
         ORDER BY 1 DESC, 2 DESC LIMIT 1"""), {"cid": cid})).first()
    if not row:
        return date.today()
    y, m = int(row[0]), int(row[1])
    last = date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)
    return min(last, date.today())


async def _work_day_data(db: AsyncSession, cid: str,
                         visible: set[str] | None = None) -> dict[str, Any]:
    """Экран дня пространства, которое ведёт РАБОТУ, а не учёт.

    Решение МАГа 07.09.2026 по пространству ElsyPlus: «это производственное
    пространство, здесь не надо бухгалтерии». До этого office-профиль знал один
    набор — деньги из 1С, — и в пространстве без учёта «Пульс» показывал пять нулей
    и карточку «Данных учёта нет», хотя рядом жили поручения, документы на визе,
    встречи и заявки.

    Предмет здесь — дневная работа пространства: что просрочено, что ждёт решения,
    что сегодня в календаре и кто из приглашённых так и не дошёл до системы.
    Определения взяты у экранов, откуда цифры: поручение открыто, пока
    `status = 'open'` («Трек»), виза и ознакомление ждут в `pending` («Дело»),
    заявка открыта, пока не closed/cancelled (витрина Поддержки).
    """
    support_cid = await support_company_id(db, cid) or "-"

    w = (await db.execute(text("""
        select count(*) filter (where status = 'open') as open,
               count(*) filter (where status = 'open' and due_at is not null
                                and due_at < now()) as overdue,
               count(*) filter (where status = 'open' and assignee_id is null) as no_owner,
               count(*) filter (where status = 'open' and due_at is not null
                                and due_at::date = current_date) as due_today
          from tasks where company_id = :cid"""), {"cid": cid})).one()

    ap = (await db.execute(text("""
        select count(*) as pending,
               count(*) filter (where activated_at is not null
                                and activated_at < now() - interval '3 days') as stuck
          from doc_approvals
         where company_id = CAST(:cid AS uuid) and status = 'pending'"""), {"cid": cid})).one()

    aq = (await db.execute(text("""
        select count(*) as pending,
               count(*) filter (where due_at is not null and due_at < now()) as overdue
          from doc_acquaints
         where company_id = CAST(:cid AS uuid) and status = 'pending'"""), {"cid": cid})).one()

    ev = (await db.execute(text("""
        select count(*) filter (where starts_at::date = current_date) as today,
               count(*) filter (where starts_at > now()
                                and starts_at < now() + interval '7 days') as week
          from calendar_events
         where company_id = CAST(:cid AS uuid)
           and coalesce(status, '') <> 'cancelled'"""), {"cid": cid})).one()

    # Заявки — тем же определением, что в сетевом наборе и в витрине Поддержки.
    t = _TicketsZero() if not await _tickets_available(db) else (await db.execute(text(f"""
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
           and company_id::text = :support_cid"""), {"support_cid": support_cid})).one()

    ppl = (await db.execute(text("""
        select count(*) as total,
               count(*) filter (where u.last_seen_at > now() - interval '24 hours') as today,
               count(*) filter (where u.last_seen_at > now() - interval '7 days') as week,
               count(*) filter (where u.last_seen_at is null) as never
          from user_companies uc join users u on u.id = uc.user_id
         where uc.company_id = :cid"""), {"cid": cid})).one()

    kpi: list[dict[str, Any]] = [
        _kpi("work_open", "Поручений в работе", w.open,
             note=(f"срок сегодня у {w.due_today}" if w.due_today else None),
             link="/docs/work?view=mine-all", higher_is_better=False),
        _kpi("work_overdue", "Просрочено", w.overdue,
             state="bad" if w.overdue else None,
             link="/docs/work?view=today", higher_is_better=False),
        _kpi("approvals", "Ждут визы", ap.pending,
             note=(f"{ap.stuck} стоят дольше трёх дней" if ap.stuck else None),
             link="/docs/work?view=approvals", higher_is_better=False),
        _kpi("acquaints", "Ознакомиться", aq.pending,
             link="/docs/work?view=acquaints", higher_is_better=False),
        _kpi("meetings", "Встреч сегодня", ev.today,
             note=(f"за неделю {ev.week}" if ev.week else None),
             link="/docs/work?view=calendar"),
        _kpi("own_open", "Заявки открыты", t.own_open,
             note=(f"{t.own_sla} с нарушенным сроком" if t.own_sla else None),
             link="/tickets?src=own", higher_is_better=False),
        _kpi("people", "Заходили за неделю", ppl.week,
             note=f"из {ppl.total} в пространстве", link="/pulse/team"),
    ]

    acked = {r.card_key for r in (await db.execute(text("""
        select card_key from pulse_acks
         where company_id = :cid
           and (acked_on = current_date
                or (snooze_until is not null and snooze_until >= current_date))"""),
        {"cid": cid})).all()}

    cards: list[dict[str, Any]] = []

    def card(key: str, title: str, insight: str, *, count: int | None = None,
             level: str = "warn", link: str | None = None) -> None:
        if key in acked:
            return
        cards.append({"key": key, "title": title, "insight": insight,
                      "count": count, "level": level, "link": link})

    if w.overdue:
        card("work_overdue", "Поручения просрочены",
             f"{w.overdue} {plural(w.overdue, 'поручение', 'поручения', 'поручений')} "
             f"с прошедшим сроком: решите или перенесите срок — сам он не сдвинется.",
             count=w.overdue, level="alert", link="/docs/work?view=today")

    if w.no_owner:
        card("work_no_owner", "Работа без исполнителя",
             f"{w.no_owner} {plural(w.no_owner, 'поручение', 'поручения', 'поручений')} "
             f"никому не поручено: срок идёт, а делать некому.",
             count=w.no_owner, link="/docs/work?view=mine-all")

    if ap.stuck:
        card("appr_stuck", "Визы стоят",
             f"{ap.stuck} {plural(ap.stuck, 'документ ждёт', 'документа ждут', 'документов ждут')} "
             f"решения дольше трёх дней.",
             count=ap.stuck, link="/docs/work?view=approvals")

    if aq.overdue:
        card("acq_overdue", "Ознакомление просрочено",
             f"{aq.overdue} {plural(aq.overdue, 'ознакомление', 'ознакомления', 'ознакомлений')} "
             f"не закрыто в назначенный срок.",
             count=aq.overdue, link="/docs/work?view=acquaints")

    if t.own_sla_stale:
        card("own_sla", "Заявки нарушили срок",
             f"{t.own_sla_stale} {plural(t.own_sla_stale, 'заявка', 'заявки', 'заявок')} "
             f"с нарушенным SLA лежит дольше {OWN_SLA_DAYS} дней.",
             count=t.own_sla_stale, level="alert", link="/tickets?sla=breached")

    if ppl.never:
        card("people_never", "Приглашённые не дошли",
             f"{ppl.never} из {ppl.total} "
             f"{plural(ppl.never, 'человек ни разу не заходил', 'человека ни разу не заходили', 'человек ни разу не заходили')} "
             f"в пространство.",
             count=ppl.never, level="info", link="/pulse/team")

    if visible is not None:
        cards = [c for c in cards
                 if CARD_SCOPE.get(c["key"]) is None or CARD_SCOPE[c["key"]] in visible]
        kpi = [k for k in kpi if KPI_SCOPE.get(k["key"]) is None
               or KPI_SCOPE[k["key"]] in visible]

    return {
        "as_of": None,
        "stale_days": None,
        "kpi": kpi,
        "cards": cards,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _office_day_data(db: AsyncSession, cid: str,
                           visible: set[str] | None = None) -> dict[str, Any]:
    """Экран дня бухгалтерского пространства: деньги учёта, документы, сроки.

    Тот же жанр, что и сетевой: строка плиток и карточки-эскалации. Меняется
    только предмет — вместо «молчащих станций» здесь «требования просрочены»,
    вместо выручки сети выручка по данным учёта клиента.

    Цифры считаются ТЕМИ ЖЕ формулами, что «Бухгалтерия» и витрина (`_result_window`,
    68.02 по счёту, дебиторка дебетом 62): второй набор определений в одном
    пространстве расходится с первым на первой же правке.
    """
    p = {"cid": cid, "org": None}
    anchor = await _books_anchor(db, cid)
    since, till, prev_since, prev_till = _period_bounds("month", anchor)

    # Свежесть: чем свежее срез остатков, тем к какой дате относятся деньги.
    as_of_raw = (await db.execute(text("""
        SELECT max(as_of)::text FROM gl_balances
         WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly'"""),
        {"cid": cid})).scalar()
    as_of = datetime.fromisoformat(as_of_raw) if as_of_raw else None
    stale_days = (date.today() - as_of.date()).days if as_of else None

    rev, prof = await _result_window(db, p, since, till)
    rev_was, prof_was = await _result_window(db, p, prev_since, prev_till)

    vat = float((await db.execute(text("""
        SELECT coalesce(sum(amount) FILTER (WHERE account_kt LIKE '68.02%'), 0)
             - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '68.02%'
                                              AND account_kt NOT LIKE '51%'
                                              AND account_kt NOT LIKE '68.90%'), 0)
          FROM gl_entries
         WHERE company_id = CAST(:cid AS uuid)
           AND make_date(period_year, period_month, 1)
               BETWEEN date_trunc('month', CAST(:a AS date))::date AND CAST(:b AS date)"""),
        {"cid": cid, "a": since, "b": till})).scalar_one() or 0)
    tax_mode = await _tax_mode(db, p)

    # Долг покупателей — дебет 62 по последнему срезу (дебет 60 это авансы, не долг).
    debt = float((await db.execute(text("""
        SELECT coalesce(sum(debit), 0) FROM gl_balances
         WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly'
           AND account LIKE '62%'
           AND as_of = (SELECT max(as_of) FROM gl_balances
                         WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly')"""),
        {"cid": cid})).scalar_one() or 0)

    req = (await db.execute(text("""
        SELECT count(*) AS open,
               count(*) FILTER (WHERE due_date IS NOT NULL
                                  AND due_date < to_char(CURRENT_DATE, 'YYYY-MM-DD')) AS overdue
          FROM doc_requests
         WHERE company_id = CAST(:cid AS uuid)
           AND status IN ('open','requested','promised')"""), {"cid": cid})).one()

    per = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE status = 'closed') AS closed, count(*) AS total
          FROM periods WHERE company_id = CAST(:cid AS uuid)"""), {"cid": cid})).one()

    tax_overdue = (await db.execute(text("""
        SELECT count(*) FROM gl_references
         WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_calendar'
           AND coalesce(meta->>'В архиве', 'false') <> 'true'
           AND coalesce(meta->>'Статус', '') <> 'Сдано'
           AND code < to_char(CURRENT_DATE, 'YYYY-MM-DD')
           AND code >= to_char(CURRENT_DATE - 60, 'YYYY-MM-DD')"""),
        {"cid": cid})).scalar_one()
    tax_next = (await db.execute(text("""
        SELECT code, name FROM gl_references
         WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_calendar'
           AND coalesce(meta->>'В архиве', 'false') <> 'true'
           AND code >= to_char(CURRENT_DATE, 'YYYY-MM-DD')
         ORDER BY code LIMIT 1"""), {"cid": cid})).first()

    # Первичка, доехавшая, но не разобранная до конца: работа, которая стоит.
    intake = (await db.execute(text("""
        SELECT count(*) FROM intake_batches
         WHERE company_id = CAST(:cid AS uuid) AND status = 'parsed'"""),
        {"cid": cid})).scalar_one()

    people = (await db.execute(text("""
        select count(*) filter (where u.last_seen_at > now() - interval '6 minutes') as online,
               count(*) filter (where u.last_seen_at >= current_date) as today,
               count(*) as total
        from users u join user_companies uc on uc.user_id = u.id
        where uc.company_id = :cid"""), {"cid": cid})).one()

    m_label = "%s %d" % (_MONTHS_RU[till.month - 1], till.year)
    kpi: list[dict[str, Any]] = [
        _kpi("money_revenue", "Выручка за месяц, ₽", round(rev),
             delta_pct=_dpct(rev, rev_was), note=m_label, link="/books?tab=trends"),
        _kpi("profit", "Прибыль за месяц, ₽", round(prof),
             delta_pct=_dpct(prof, prof_was), note=m_label, link="/books?tab=trends"),
        # Плитка остаётся на любом режиме: пропавшая плитка читается как поломка, а
        # ноль без объяснения — как потерянные данные. На УСН подпись говорит, почему.
        _kpi("vat", "НДС к уплате, ₽", round(vat),
             note=("%s · оценка до закрытия" % m_label if tax_mode["vat"]
                   else "%s · на %s НДС не начисляется"
                        % (m_label, tax_mode["label"] or "этом режиме")),
             link="/books?tab=taxes", higher_is_better=False),
        _kpi("receivable", "Должны вам, ₽", round(debt),
             note=f"на {_ru_date(as_of_raw)}" if as_of_raw else None,
             link="/counterparties", higher_is_better=False),
    ]
    if req.open:
        kpi.append(_kpi("doc_requests", "Ждём документов", req.open,
                        note=f"срок прошёл: {req.overdue}",
                        state="warn" if req.overdue else None,
                        link="/books?tab=requests", higher_is_better=False))
    if per.total:
        kpi.append(_kpi("periods", "Периодов закрыто", per.closed,
                        note=f"из {per.total}", link="/books?tab=closing"))
    kpi.append(_kpi("people", "Сейчас в системе", people.online,
                    note=f"за сегодня: {people.today} из {people.total}",
                    link="/pulse/team"))

    acked = {r.card_key for r in (await db.execute(text("""
        select card_key from pulse_acks
        where company_id = :cid
          and (acked_on = current_date
               or (snooze_until is not null and snooze_until >= current_date))"""),
        {"cid": cid})).all()}

    cards: list[dict[str, Any]] = []

    def card(key: str, title: str, insight: str, *, count: int | None = None,
             level: str = "warn", link: str | None = None) -> None:
        if key in acked:
            return
        cards.append({"key": key, "title": title, "insight": insight,
                      "count": count, "level": level, "link": link})

    # №0 — свежесть: без неё остальные цифры обсуждать нельзя (правило то же,
    # что и у сети, предмет другой — выгрузка из 1С, а не сессии).
    if stale_days is None:
        card("books_stale", "Данных учёта нет",
             "Из 1С ещё ничего не доехало: считать по чему.",
             level="alert", link="/connect")
    elif stale_days > 30:
        card("books_stale", "Учёт не обновлялся",
             f"Последняя выгрузка из 1С на {_ru_date(as_of_raw)}: прошло "
             f"{stale_days} дн. Цифры верны только по эту дату.",
             count=stale_days, level="alert", link="/connect")

    if req.overdue:
        card("doc_overdue", "Документы не приходят в срок",
             f"{req.overdue} {plural(req.overdue, 'требование', 'требования', 'требований')} "
             f"с прошедшим сроком: без них период не закрыть и вычет не заявить.",
             count=req.overdue, link="/books?tab=requests")

    if tax_overdue:
        card("tax_overdue", "Сроки отчётности прошли",
             f"{tax_overdue} {plural(tax_overdue, 'срок', 'срока', 'сроков')} в календаре "
             f"не отмечены сданными — проверьте, что отчёт ушёл.",
             count=tax_overdue, level="alert", link="/books?tab=calendar")
    elif tax_next:
        card("tax_next", "Ближайший срок отчётности",
             f"{tax_next[1]} — до {_ru_date(tax_next[0])}.",
             level="info", link="/books?tab=calendar")

    if intake:
        card("intake_waiting", "Первичка ждёт разбора",
             f"{intake} {plural(intake, 'пакет', 'пакета', 'пакетов')} загружено, но не "
             f"принято в учёт: пока не примете, документы не станут проводками.",
             count=intake, link="/intake")

    if per.total and per.closed < per.total:
        open_p = per.total - per.closed
        card("periods_open", "Периоды не закрыты",
             f"{open_p} {plural(open_p, 'период', 'периода', 'периодов')} открыто: "
             f"цифры в них ещё могут измениться.",
             count=open_p, level="info", link="/books?tab=closing")

    if visible is not None:
        cards = [c for c in cards
                 if CARD_SCOPE.get(c["key"]) is None or CARD_SCOPE[c["key"]] in visible]
        kpi = [k for k in kpi if KPI_SCOPE.get(k["key"]) is None
               or KPI_SCOPE[k["key"]] in visible]

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "stale_days": stale_days,
        "kpi": kpi,
        "cards": cards,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _period_bounds(period: str, today: date) -> tuple[date, date, date, date]:
    """Границы текущего и предыдущего окна: (с, по, с_прошлого, по_прошлого)."""
    if period == "year":
        start = date(today.year, 1, 1)
        return start, today, date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if period == "quarter":
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        prev_end = start - timedelta(days=1)
        prev_start = date(prev_end.year, ((prev_end.month - 1) // 3) * 3 + 1, 1)
        return start, today, prev_start, prev_end
    start = date(today.year, today.month, 1)
    prev_end = start - timedelta(days=1)
    prev_start = date(prev_end.year, prev_end.month, 1)
    return start, today, prev_start, prev_end


async def _result_window(db: AsyncSession, p: dict, a, b) -> tuple[float, float]:
    """Выручка без НДС и прибыль ДО налога за окно — как считает «Бухгалтерия».

    Расход берётся тем, что списано на финрезультат (90.02, 90.07, 90.08 и 91.02
    минус 91.01): складывать обороты затратных счетов с себестоимостью значит
    считать одни деньги дважды — 26-й закрывается на 90.02, 44-й на 90.07.
    """
    row = (await db.execute(text("""
        SELECT coalesce(sum(amount) FILTER (WHERE account_kt LIKE '90.01%'), 0)
             - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '90.03%'), 0) AS revenue,
               coalesce(sum(amount) FILTER (WHERE account_dt LIKE '90.02%'
                                              OR account_dt LIKE '90.07%'
                                              OR account_dt LIKE '90.08%'), 0)
             + coalesce(sum(amount) FILTER (WHERE account_dt LIKE '91.02%'), 0)
             - coalesce(sum(amount) FILTER (WHERE account_kt LIKE '91.01%'), 0) AS expense
          FROM gl_entries
         WHERE company_id = CAST(:cid AS uuid)
           AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                OR organization_id = CAST(:org AS uuid))
           AND make_date(period_year, period_month, 1)
               BETWEEN date_trunc('month', CAST(:a AS date))::date AND CAST(:b AS date)"""),
        {**p, "a": a, "b": b})).one()
    revenue = float(row[0] or 0)
    return revenue, revenue - float(row[1] or 0)


async def _tax_mode(db: AsyncSession, p: dict) -> dict[str, Any]:
    """Режим компании — общим определением пространства (`services/tax_mode.py`).

    Своей копии здесь нет намеренно: «Налоги», «Пульс» и паспорт обязаны отвечать
    про режим одинаково, а скопированное определение расходится на первой правке.
    """
    return await space_tax_mode(db, p.get("cid"), p.get("org"))


def _ru_date(v) -> str:
    """ISO-дата в привычный вид: наружу «15.08.2026», а не «2026-08-15»."""
    t = str(v or "")
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return "%s.%s.%s" % (t[8:10], t[5:7], t[:4])
    return t
