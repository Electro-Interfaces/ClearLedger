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

import csv
import io
import secrets
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import (
    assert_company_member, assert_company_product, get_current_user,
    resolve_member_modules,
)
from app.database import get_db
from app.models import (
    ChatMessage, PulseAck, PulseView, PulseViewBlock, PulseViewGrant, PulseViewLink,
    Task, TaskEvent, User, UserCompany,
)
# Словарь стадий — общий с «Проектами»: «Проработка» не должна стать «dd»
# только потому, что экран другой.
from app.services.ezs_changes import STAGE_LABELS

router = APIRouter(prefix="/pulse", tags=["Пульс"])

# Пороги В1 — с большим запасом (решение МАГа 31.07.2026, PULSE.md §3):
# период адаптации система проходит тихо. Настройка в «Управлении» — волна В3.
STALE_DAYS = 7          # данные сессий не обновлялись дольше — эскалация №0
OWN_SLA_DAYS = 3        # своя заявка с нарушенным SLA висит дольше — карточка
EXT_BACKLOG = 1000      # хвост зеркал внешней FSM старше месяца — сводная карточка
SILENT_SHARE = 0.6      # доля молчащих станций парка — карточка
SILENT_HOURS = 48       # «молчит» = нет сессий столько часов ДАННЫХ (от as_of)

# Контакт-центр. Окна тут считаются от now(), а не от as_of: телефония приезжает
# синхронизацией каждые 5 минут, и «вчера» здесь означает настоящее вчера.
CC_MISSED_FACTOR = 1.5  # доля пропущенных выше цели во столько раз — карточка
CC_WRAPUP_STUCK = 10    # столько разговоров зависло в разборе с просроченным ответом
CC_REPEAT_TIMES = 3     # клиент обращался столько раз за неделю — он не решил вопрос
CC_REPEAT_PEOPLE = 3    # столько таких клиентов — карточка
# Цель по умолчанию, если в контакт-центре не задали свою (`cc_kpi_targets`).
CC_DEFAULT_TARGETS = {"missed_share": 5.0, "first_response_sec": 120.0,
                      "in_sla_share": 95.0, "handle_sec": 900.0}

# Продажи. Окна — от as_of (последняя загруженная сессия), а не от now(): данные
# сети приезжают файлами с отставанием, и «неделя» здесь означает неделю ДАННЫХ.
SALES_DROP = 20.0       # выручка недели упала на столько % — карточка
SALES_OUT_SHARE = 0.05  # столько парка выпало из работы за неделю — карточка
SALES_OUT_MIN = 10      # и не меньше стольких станций: у мелкой сети % обманчив
SALES_VISIT_OK = 85.0   # успех визитов ниже — клиенты уезжают, не зарядившись

# Проекты (стройка сети). Портфель живёт месяцами, поэтому пороги — про
# застревание и бесхозность, а не про недельные колебания.
PR_STUCK_DAYS = 90      # стоит в одной стадии дольше — застрял
PR_STUCK_SHARE = 0.10   # столько портфеля застряло — карточка
PR_STUCK_MIN = 20       # и не меньше стольких проектов
PR_OWNER_SHARE = 0.30   # столько портфеля без ответственного — карточка
PR_OWNER_MIN = 20
PR_MOVES_WEEKS = 3      # столько недель без единой смены стадии — портфель встал

# Эксплуатация: хозяйство вокруг сети — энергия, аренда, услуги подрядчиков.
# Мера здесь не «неделя», а ПЕРИОД: месяц закрывается документами от контрагентов.
OPS_DOCS_OVERDUE = 20   # столько начислений без документа после срока — карточка
OPS_OPEN_MONTHS = 2     # период не закрыт дольше стольких месяцев — карточка
OPS_COST_JUMP = 15.0    # ожидание месяца выросло на столько % — карточка

# Объект как ось. Единственное место в пространстве, где точка видна сразу во
# всех контурах: выручка, расходы, подтверждение документов. Признаки считаются
# по одному объекту, и в список попадает тот, у кого их сошлось несколько.
OBJ_SILENT_DAYS = 30    # нет сессий столько дней ДАННЫХ — точка не продаёт
OBJ_DROP_PCT = 50.0     # выручка недели упала на столько % — провал точки
OBJ_PAIN_MIN = 2        # столько признаков сразу — «болит»
OBJ_IDLE_COST_MIN = 10  # столько платных точек без выручки — карточка
# Признаки словами: в выгрузке те же подписи, что на экране, иначе файл
# приходится расшифровывать по коду.
OBJ_FLAG_LABELS = {
    "idle_cost": "платим, не продаёт", "revenue_drop": "выручка провалилась",
    "docs_late": "документы просрочены", "silent": "молчит",
}


# Критичные действия журнала: те, что меняют состав людей и их права. Правки
# данных сюда не входят — это работа, а не риск.
ACCESS_ACTIONS = ("user.create", "user.remove", "member.access", "member.scope",
                  "member.party", "role.create", "role.update", "invite.create")


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


# ── Что из «Пульса» кому видно ────────────────────────────────────────────
#
# Пороги отвечают на вопрос «когда реагировать», видимость — «кому это вообще
# показывать». Куратор — руководитель верхнего уровня: ему нужна картина, а не
# весь разбор, и решает, что именно входит в эту картину, директор, а не код.
#
# Ключи те же, что в реестре приложений (`app_registry._PULSE_MODULES`), поэтому
# отбор виден и в конструкторе роли «Управления» — вторая система прав здесь не
# заводится.
PULSE_ITEMS: list[tuple[str, str, str]] = [
    ("today", "Экран дня", "Экран дня"),
    ("accepted", "Принятое сегодня", "Экран дня"),
    ("sources", "Источники данных", "Экран дня"),
    ("targets", "Пороги эскалаций", "Экран дня"),
    ("business.sales", "Продажи", "Бизнес"),
    ("business.projects", "Проекты", "Бизнес"),
    ("business.ops", "Эксплуатация", "Бизнес"),
    ("business.contacts", "Обращения", "Бизнес"),
    ("business.objects", "Где болит", "Бизнес"),
    ("business.support", "Поддержка", "Бизнес"),
    ("business.summary", "Коротко", "Бизнес"),
    ("team.people", "Люди", "Команда"),
    ("team.departments", "Подразделения", "Команда"),
    ("team.access", "Доступ", "Команда"),
    ("team.comms", "Переписка", "Команда"),
    ("week.totals", "Итоги недели", "Неделя"),
    ("week.moves", "Движения", "Неделя"),
    # Витрина — отдельный пункт прав: внешнему получателю нужна ТОЛЬКО она, а
    # без своего ключа роль открывала либо весь «Пульс» (включая «Команду» и
    # журнал доступа), либо ничего.
    ("showcase", "Моя витрина", "Витрины"),
    ("views", "Настройка витрин", "Витрины"),
]
PULSE_ITEM_KEYS = {k for k, _, _ in PULSE_ITEMS}

# Тема карточки и плитки: к какому пункту относится сообщение. Без этого отбор
# работал бы только на уровне меню, а экран дня показывал бы куратору всё
# подряд — включая то, что для него закрыто.
CARD_SCOPE = {
    # `data_stale` темы намеренно НЕ имеет: это метка доверия к цифрам, а не
    # отдельный разрез. Кто видит цифры — должен знать, что им нельзя верить,
    # включая куратора, которому закрыты «Источники».
    "src_stale": "sources",
    "own_sla": "business.support", "ext_backlog": "business.support",
    "own_reopen": "business.support",
    "silent_surge": "business.sales", "sales_drop": "business.sales",
    "sales_out": "business.sales", "sales_visit": "business.sales",
    "cc_missed": "business.contacts", "cc_wrapup": "business.contacts",
    "cc_repeat": "business.contacts", "cc_escalation": "business.contacts",
    "pr_stuck": "business.projects", "pr_no_owner": "business.projects",
    "pr_frozen": "business.projects", "pr_overdue": "business.projects",
    "ops_docs": "business.ops", "ops_open": "business.ops",
    "ops_jump": "business.ops", "ops_contracts": "business.ops",
    "obj_idle_cost": "business.objects",
    "access_admins": "team.access", "access_invites": "team.access",
}
KPI_SCOPE = {
    "revenue": "business.sales", "sessions": "business.sales",
    "silent": "business.sales", "cc_missed": "business.contacts",
    "own_open": "business.support", "ext_open": "business.support",
    "funnel": "business.projects", "people": "team.people",
}


async def _may_configure(db: AsyncSession, cid: str, user: User) -> bool:
    """Кто вправе настраивать отбор и смотреть чужими глазами: полный доступ."""
    if user.is_superadmin:
        return True
    m = await db.get(UserCompany, (user.id, uuid.UUID(cid)))
    if m is None:
        return False
    return m.role == "admin" or await resolve_member_modules(m, db) is None


async def _role_items(db: AsyncSession, cid: str, role_id: str) -> set[str] | None:
    """Набор пунктов роли — для режима «смотреть глазами».

    None — у роли полный доступ: смотреть её глазами не имеет смысла, картина
    та же самая.
    """
    row = (await db.execute(text(
        "select modules from company_roles where id = :rid and company_id = :cid"
    ), {"rid": role_id, "cid": cid})).first()
    if row is None or row.modules is None or "pulse" in row.modules:
        return None
    return {k.split(":", 1)[1] for k in row.modules if k.startswith("pulse:")} & PULSE_ITEM_KEYS


async def _visible_items(db: AsyncSession, cid: str, user: User,
                         as_role: str | None = None) -> set[str] | None:
    """Что этому человеку показывать. None — ограничений нет (полный доступ).

    Набор прав уже несёт ответ: ключ `pulse` целиком или отдельные `pulse:...`.
    Отдельного хранилища видимости не заводим — иначе право и видимость
    разъехались бы, и «убрал из картины» перестало бы значить «закрыл доступ».
    """
    # Режим «глазами роли»: доступен только тому, кто и так видит всё и настраивает
    # отбор. Иначе им можно было бы РАСШИРИТЬ себе картину, а не сузить.
    if as_role and await _may_configure(db, cid, user):
        return await _role_items(db, cid, as_role)
    if user.is_superadmin:
        return None
    m = await db.get(UserCompany, (user.id, uuid.UUID(cid)))
    if m is None or m.role == "admin":
        return None
    mods = await resolve_member_modules(m, db)
    if mods is None or "pulse" in mods:
        return None
    picked = {k.split(":", 1)[1] for k in mods if k.startswith("pulse:")}
    return picked & PULSE_ITEM_KEYS



# ── Профиль пространства решает, ЧЕМ мерить ───────────────────────────────
#
# «Пульс» родился на пилоте ЭЗС и всё считал по `charge_sessions`. На топливном
# профиле это давало ложь в самом громком месте: у ГИГ 376 744 заправки и свежие
# данные, а экран дня писал «Данных о сессиях нет» тревогой — просто смотрел не в
# ту таблицу. Мера продаж выбирается профилем компании, а не зашита в код.
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

# Молчание источника — сигнал только там, где поток регулярный: на паре записей
# «не приходят данные» означает, что контур ещё заводят, а не что он сломался.
SOURCE_MIN_ROWS = 10


async def _profile(db: AsyncSession, cid: str) -> str:
    """Отраслевой профиль компании: от него зависит, что считать продажами."""
    pid = (await db.execute(text(
        "select profile_id from companies where id = :cid"), {"cid": cid})).scalar_one_or_none()
    return pid if pid in PROFILE_SALES else DEFAULT_PROFILE


# ── Источники данных: чему сегодня можно верить ───────────────────────────
#
# Реестр приёмников, а не реестр коннекторов: коннектор может числиться
# «активным», а данные не приезжать неделю. Правда — в самих таблицах, поэтому
# каждый источник описан запросом «когда последняя запись» и окном, после
# которого молчание становится подозрительным.
#
# `window` — сколько дней тишины ещё нормально. У телефонии это часы, у
# начислений — месяц: они и приходят раз в месяц.
def _data_sources(profile: str) -> list[dict[str, Any]]:
    """Приёмники этого профиля: у топлива продажи едут заправками, у ЭЗС — сессиями."""
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


# ── Пороги эскалаций: реестр, а не константы в тексте правил ───────────────
#
# Порог — это мнение о норме, и оно принадлежит компании, а не коду. Здесь
# только дефолты: фактическое значение приходит из `pulse_targets`, где его
# правит руководитель в «Управлении» (PULSE.md §3, волна В3). Ключ добавляется
# одной строкой — экран настройки рисуется по этому же реестру.
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


# Колпак экрана дня: больше семи карточек читаются как лента, а лента — это то,
# от чего «Пульс» уходит. Лишнее отсекается по уровню (PULSE.md §7).
# Excel делит строки только по CRLF; собираем его из кодов, чтобы литерал
# не разъезжался при переносе файла между окончаниями строк.
CRLF = chr(13) + chr(10)

MAX_CARDS = 7

# Имена правил для журнала «Принятое»: ключ в базе технический, человеку нужен текст.
CARD_TITLES = {
    "data_stale": "Данные сессий не обновлялись",
    "own_sla": "Свои заявки встали",
    "ext_backlog": "Хвост внешней сервисной системы",
    "silent_surge": "Молчит большая часть сети",
    "own_reopen": "Заявки открываются повторно",
    "cc_missed": "До нас не дозваниваются",
    "cc_wrapup": "Разговоры не закрыты",
    "cc_repeat": "Клиенты звонят повторно",
    "cc_escalation": "Оператор поднял эскалацию",
    "sales_drop": "Выручка сети просела",
    "sales_out": "Станции выпали из работы",
    "sales_visit": "Клиенты уезжают без заряда",
    "pr_stuck": "Проекты стоят на месте",
    "pr_no_owner": "Проекты без ответственного",
    "pr_frozen": "Портфель не двигается",
    "pr_overdue": "Просрочены обещанные действия",
    "src_stale": "Источники молчат",
    "access_admins": "У спящих учёток остались права админа",
    "access_invites": "Приглашения повисли",
    "obj_idle_cost": "Платим за точки, которые не продают",
    "ops_docs": "Расходы не подтверждены документами",
    "ops_contracts": "Договоры с истёкшим сроком",
    "ops_open": "Периоды не закрыты",
    "ops_jump": "Хозяйство подорожало",
}


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
    visible: set[str] | None = None,
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
             f"за {t['obj_silent_days']:.0f} дней, а начисления по ним идут: "
             f"{money(cost)} ₽ за два месяца.",
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
    if not prev:
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



# Объект сразу во всех контурах: выручка (сессии), расход (начисления по
# договорам) и подтверждение (документы). Ключ один — `service_locations.id`,
# на него ссылаются и сессии, и начисления. Заявки Поддержки живут в своём
# реестре (`public.service_objects`), и общего ключа с Ядром у них сейчас нет —
# поэтому в эту ось они не входят: сшивка по имени дала бы ложные пары.
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
    and ch.period >= to_char(current_date - interval '2 month', 'YYYY-MM-01')
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


@router.get("/day")
async def pulse_day(
    company_id: str = Query(...),
    as_role: str | None = Query(None, description="смотреть глазами этой роли"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Экран дня: строка KPI по направлениям + карточки-эскалации (сводки)."""
    await assert_company_product(company_id, current_user, db, "pulse")
    visible = await _visible_items(db, str(company_id), current_user, as_role)
    return await pulse_day_data(db, str(company_id), visible)


async def pulse_day_data(db: AsyncSession, company_id: str,
                         visible: set[str] | None = None) -> dict[str, Any]:
    """Данные экрана дня без проверки доступа — её делает вызывающий.

    Отдельной функцией, потому что плитку «Пульса» на рабочем столе считает тот же
    код (`services/space_desk._pulse`): второй набор правил разошёлся бы с первым,
    и плитка начала бы врать про то, что внутри.
    """
    cid = str(company_id)
    # Чем мерить продажи, решает профиль: у топливного пространства это заправки,
    # у ЭЗС — зарядные сессии. Раньше таблица была зашита, и на профиле fuel экран
    # дня тревожно писал «Данных о сессиях нет» при 376 744 живых заправках.
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
        th=th, sources=sources, access=access, visible=visible,
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
    await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(company_id)

    profile = await _profile(db, cid)
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]
    as_of = (await db.execute(text(
        f"select max({TS}) from {TBL} where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()

    net: list[dict[str, Any]] = []
    trend: list[dict[str, Any]] = []
    if as_of is not None:
        m = (await db.execute(text(f"""
            select count(*) filter (where {TS} > CAST(:as_of AS timestamp) - interval '30 days') as s30,
                   coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '30 days'), 0) as r30,
                   coalesce(sum({VOL}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '30 days'), 0) as e30,
                   count(*) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and {TS} > CAST(:as_of AS timestamp) - interval '60 days') as s30p,
                   coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and {TS} > CAST(:as_of AS timestamp) - interval '60 days'), 0) as r30p,
                   coalesce(sum({VOL}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '30 days'
                                    and {TS} > CAST(:as_of AS timestamp) - interval '60 days'), 0) as e30p,
                   count(distinct {LOC}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '30 days') as live
            from {TBL} where company_id = :cid
        """), {"cid": cid, "as_of": as_of})).one()
        # Единица измерения — в заголовке, а не рядом с числом: «271,8 тыс. кВт·ч»
        # не помещалось в плитку на телефоне и вылезало за рамку.
        net = [
            _kpi("revenue", "Выручка, ₽", float(m.r30),
                 delta_pct=_dpct(float(m.r30), float(m.r30p))),
            _kpi("energy", VOL_LABEL, float(m.e30),
                 delta_pct=_dpct(float(m.e30), float(m.e30p))),
            _kpi("sessions", SESS_WORD, m.s30, delta_pct=_dpct(m.s30, m.s30p)),
            _kpi("live", "Работающих точек", m.live, note="давали операции за 30 дней"),
        ]
        # Помесячно за полгода — форма кривой важнее точных чисел.
        trend = [{"month": r.m.strftime("%m.%Y"), "revenue": float(r.rev), "sessions": r.n}
                 for r in (await db.execute(text(f"""
            select date_trunc('month', {TS}) as m, count(*) as n,
                   coalesce(sum({AMT}), 0) as rev
            from {TBL}
            where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '6 months'
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


class TargetsIn(BaseModel):
    company_id: str
    # Только известные ключи реестра; пустое значение — вернуть дефолт.
    values: dict[str, float | None]


@router.get("/export")
async def pulse_export(
    view: str = Query(..., pattern="^(week|objects|operations)$"),
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Выгрузка разреза в CSV.

    Общий `ExportButton` пространства собирает выгрузку из DOM (плитки и
    таблицы), а разделы «Пульса» свёрстаны карточками — он отдал бы почти пустой
    файл. Поэтому выгрузка серверная: те же цифры, что на экране, но из тех же
    запросов, а не из разметки.

    CSV с точкой с запятой и BOM — иначе Excel открывает кириллицу кракозябрами
    и не делит строку на колонки.
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    rows: list[list[Any]] = []
    if view == "week":
        d = await pulse_week_data(db, cid)
        rows = [["Показатель", "За неделю", "Предыдущая", "Единица"]]
        rows += [[r["label"], r["value"], r["prev"] if r["prev"] is not None else "",
                  r["unit"] or ""] for r in d["rows"]]
        name = "pulse-week"
    elif view == "objects":
        o = await _objects_snapshot(db, cid)
        rows = [["Точка", "Код", "Признаки", "Под вопросом, ₽", "Выручка недели, ₽",
                 "Было неделей раньше, ₽", "Начислено за 2 мес, ₽", "Без документа",
                 "Последняя сессия"]]
        rows += [[p["name"], p["code"],
                  " · ".join(OBJ_FLAG_LABELS.get(f, f) for f in p["flags"]),
                  round(p["at_risk"]),
                  round(p["revenue"]), round(p["revenue_prev"]), round(p["cost"]),
                  p["late_docs"], (p["last_session"] or "")[:10]]
                 for p in o.get("pain", [])]
        name = "pulse-objects"
    else:
        ops = await _ops_snapshot(db, cid)
        rows = [["Период", "Начислений", "Ожидание, ₽", "Без документа",
                 "Просрочено подтверждений"]]
        rows.append([ops["period"][:7], ops["charges"], round(ops["expected"]),
                     ops["no_doc"], ops["docs_overdue"]])
        name = "pulse-operations"

    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator=CRLF).writerows(rows)
    body = "\ufeff" + buf.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{name}-{date.today():%Y%m%d}.csv"'},
    )


@router.get("/access")
async def pulse_access(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Люди и доступ: кто есть, кто спит и что меняли в правах.

    Не слежка за присутствием (PULSE.md §3), а риск: доступ переживает людей, и
    единственный, кому это видно целиком, — руководитель пространства.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    a = await _access_snapshot(db, str(company_id))
    kpi = [
        _kpi("members", "Людей в пространстве", a["members"]),
        _kpi("admins", "С полным доступом", a["admins"],
             note="могут менять состав и права"),
        _kpi("partners", "Внешних участников", a["partners"],
             note="не сотрудники компании", higher_is_better=False),
        _kpi("dormant", "Не заходили месяц", a["dormant"],
             note=(f"из них с правами админа: {a['dormant_admins']}"
                   if a["dormant_admins"] else None),
             state="warn" if a["dormant_admins"] else None, higher_is_better=False),
        _kpi("invites", "Приглашения без ответа", a["invites_pending"],
             note=(f"висят больше недели: {a['invites_stale']}" if a["invites_stale"] else None),
             state="warn" if a["invites_stale"] else None, higher_is_better=False),
        _kpi("failed", "Неудачных входов", a["login_failed_7d"],
             note="за неделю", higher_is_better=False),
    ]
    return {"kpi": kpi, "dormant": a["dormant_list"], "events": a["events"]}


@router.get("/sources")
async def pulse_sources(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Источники: когда каждый в последний раз приносил данные и что он кормит.

    Отвечает на вопрос, который стоит перед всеми остальными разделами: каким
    цифрам сегодня можно верить. Реестр коннекторов для этого не годится —
    коннектор бывает «активным» при том, что данные не приезжали неделю.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    items = await _sources_snapshot(db, str(company_id))
    # Каналы обмена — как их видит Учёт: имя, расписание, последний обмен.
    channels = [{"name": r.name, "status": r.status, "docs": r.docs_loaded or 0,
                 "last_sync": r.last_sync_at.isoformat() if r.last_sync_at else None}
                for r in (await db.execute(text("""
        select name, status, docs_loaded, last_sync_at from channels
        where company_id = :cid order by last_sync_at desc nulls last limit 12
    """), {"cid": str(company_id)})).all()]
    return {"items": items, "channels": channels,
            "stale": sum(1 for i in items if i["stale"])}


class VisibilityIn(BaseModel):
    company_id: str
    role_id: str
    # Ключи пунктов «Пульса», которые остаются видимыми этой роли.
    items: list[str]


@router.get("/comms")
async def pulse_comms(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Переписка» — живёт ли общение: сотрудники в чатах, клиенты в обращениях.

    Директору нужен не пересказ чужих лент, а три ответа: пишут ли вообще, кто
    именно из своих, и не осталось ли клиента без ответа. Содержимого сообщений
    здесь нет и не будет — это разрез активности, а не чтение чужой переписки.
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    p = {"cid": cid}

    # Чаты пространства: свои между собой. Комнаты приложений (`app:*`) заводятся
    # автоматически, поэтому «комнат много, сообщений ноль» — нормальное начало.
    chat = (await db.execute(text("""
        select count(*) filter (where m.created_at >= now() - interval '7 days') as w1,
               count(*) filter (where m.created_at >= now() - interval '14 days'
                                 and m.created_at < now() - interval '7 days') as w2,
               count(distinct coalesce(m.user_id::text, m.user_name))
                 filter (where m.created_at >= now() - interval '7 days') as people,
               max(m.created_at) as last_at
        from chat_messages m join chat_rooms r on r.id = m.room_id
        where r.company_id = :cid and m.deleted_at is null
    """), p)).one()
    rooms = (await db.execute(text("""
        select count(*) as total,
               count(*) filter (where exists (
                   select 1 from chat_messages m
                   where m.room_id = r.id and m.deleted_at is null
                     and m.created_at >= now() - interval '30 days')) as alive
        from chat_rooms r where r.company_id = :cid
    """), p)).one()

    # Кто пишет: активность своих по именам. Молчание тоже ответ — в списке
    # видно, что переписку держат двое из шестнадцати.
    authors = [{"name": r.nm, "messages": r.n, "rooms": r.rooms,
                "last": r.last_at.isoformat() if r.last_at else None}
               for r in (await db.execute(text("""
        select coalesce(u.name, m.user_name, '—') as nm, count(*) as n,
               count(distinct m.room_id) as rooms, max(m.created_at) as last_at
        from chat_messages m
        join chat_rooms r on r.id = m.room_id
        left join users u on u.id = m.user_id
        where r.company_id = :cid and m.deleted_at is null
          and m.created_at >= now() - interval '30 days'
        group by 1 order by n desc limit 10
    """), p)).all()]

    # Клиенты: обращения контура Поддержки. Канал показываем как есть — на пилоте
    # это телефония, на других стеках добавятся почта и мессенджеры.
    channels: list[dict[str, Any]] = []
    unanswered = 0
    try:
        channels = [{"channel": r.ch, "threads": r.n, "week": r.w1, "prev": r.w2}
                    for r in (await db.execute(text("""
            select channel as ch, count(*) as n,
                   count(*) filter (where created_at >= now() - interval '7 days') as w1,
                   count(*) filter (where created_at >= now() - interval '14 days'
                                     and created_at < now() - interval '7 days') as w2
            from inbox_threads group by channel order by n desc limit 8
        """))).all()]
        unanswered = (await db.execute(text("""
            select count(*) from inbox_threads
            where first_response_at is null and closed_at is null
              and created_at >= now() - interval '30 days'
        """))).scalar_one()
    except ProgrammingError:
        await db.rollback()

    # Почта пространства: свой ящик стека. Четыре письма — это «контур заведён»,
    # а не «почтой пользуются»; экран говорит об этом прямо.
    mail = {"inbound": 0, "outbound": 0, "last": None}
    try:
        # company_id тут не фильтруется — по той же причине, что и в витрине
        # заявок: пространство однокомпанийное, а идентификаторы контуров разные.
        r = (await db.execute(text("""
            select count(*) filter (where direction = 'inbound') as inb,
                   count(*) filter (where direction = 'outbound') as outb,
                   max(coalesce(sent_at, received_at)) as last_at
            from email_messages
        """))).one()
        mail = {"inbound": r.inb, "outbound": r.outb,
                "last": r.last_at.isoformat() if r.last_at else None}
    except ProgrammingError:
        await db.rollback()

    # Переписка по заявкам — тоже общение с людьми, только вокруг работы.
    tickets_msgs = 0
    try:
        tickets_msgs = (await db.execute(text("""
            select count(*) from ticket_messages where created_at >= now() - interval '7 days'
        """))).scalar_one()
    except ProgrammingError:
        await db.rollback()

    kpi = [
        _kpi("chat", "Сообщений в чатах", chat.w1,
             delta_pct=_dpct(chat.w1, chat.w2), note="за неделю"),
        _kpi("people", "Пишут сотрудников", chat.people,
             note=f"комнат живых: {rooms.alive} из {rooms.total}"),
        _kpi("mail", "Писем в ящике", mail["inbound"] + mail["outbound"],
             note=(f"входящих {mail['inbound']} · исходящих {mail['outbound']}")),
        _kpi("threads", "Обращений за неделю", sum(c["week"] for c in channels),
             delta_pct=_dpct(sum(c["week"] for c in channels),
                             sum(c["prev"] for c in channels)) if channels else None,
             note="каналы контакт-центра"),
        _kpi("unanswered", "Без ответа", unanswered,
             note="обращения за месяц, где мы не ответили",
             state="warn" if unanswered else None, higher_is_better=False),
        _kpi("ticket_msgs", "Сообщений по заявкам", tickets_msgs, note="за неделю"),
    ]
    return {"kpi": kpi, "authors": authors, "channels": channels,
            "rooms_total": rooms.total, "rooms_alive": rooms.alive,
            "chat_last": chat.last_at.isoformat() if chat.last_at else None,
            "mail": mail}


@router.get("/visibility")
async def pulse_visibility(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Состав «Пульса» и то, что из него видит каждая роль пространства.

    Экран отбора: директор идёт по своей же картине и отмечает, что показывать
    куратору. Права пишутся в ту же роль, что и везде, — «Пульс» не заводит
    собственную систему доступа.
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    roles = [{
        "id": str(r.id), "name": r.name,
        # modules = NULL у роли «Полный доступ»: отбирать там нечего.
        "full": r.modules is None,
        "items": sorted({k.split(":", 1)[1] for k in (r.modules or [])
                         if k.startswith("pulse:")} & PULSE_ITEM_KEYS),
        "has_all": "pulse" in (r.modules or []),
        "people": 0,
    } for r in (await db.execute(text(
        "select id, name, modules from company_roles where company_id = :cid order by name"
    ), {"cid": cid})).mappings().all()]
    counts = {str(r.role_id): r.n for r in (await db.execute(text(
        "select role_id, count(*) as n from user_companies"
        " where company_id = :cid and role_id is not null group by role_id"
    ), {"cid": cid})).all()}
    for r in roles:
        r["people"] = counts.get(r["id"], 0)
    return {"items": [{"key": k, "label": lbl, "section": sec}
                      for k, lbl, sec in PULSE_ITEMS], "roles": roles}


@router.put("/visibility")
async def pulse_visibility_save(
    body: VisibilityIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сохранить отбор для роли: что из «Пульса» ей видно.

    Ключи продукта в наборе роли заменяются целиком — иначе снятая галочка не
    убирала бы доступ, а только добавляла новые.
    """
    cid = str(await assert_company_product(body.company_id, current_user, db, "pulse"))
    picked = [i for i in body.items if i in PULSE_ITEM_KEYS]
    row = (await db.execute(text(
        "select modules from company_roles where id = :rid and company_id = :cid"
    ), {"rid": body.role_id, "cid": cid})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    if row.modules is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "У роли полный доступ — отбирать нечего")
    rest = [k for k in row.modules if k != "pulse" and not k.startswith("pulse:")]
    mods = rest + [f"pulse:{i}" for i in picked]
    await db.execute(text(
        "update company_roles set modules = cast(:mods as jsonb) where id = :rid"
    ), {"mods": json.dumps(mods, ensure_ascii=False), "rid": body.role_id})
    await log_audit(db, actor=current_user, company_id=uuid.UUID(cid),
                    action="pulse.visibility", target=body.role_id,
                    details={"items": len(picked)})
    await db.commit()
    return {"ok": True, "items": picked}


@router.get("/targets")
async def pulse_targets(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Пороги эскалаций: что настроено и что предлагается по умолчанию."""
    await assert_company_product(company_id, current_user, db, "pulse")
    th = await _thresholds(db, str(company_id))
    return {"items": [{
        "key": k, "value": th[k], "default": float(v["default"]),
        "is_custom": abs(th[k] - float(v["default"])) > 1e-9,
        "label": v["label"], "hint": v["hint"], "unit": v["unit"], "section": v["section"],
    } for k, v in THRESHOLDS.items()]}


@router.put("/targets")
async def pulse_targets_save(
    body: TargetsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сохранить пороги компании. Ключи вне реестра игнорируются молча — это
    защита от подсунутого поля, а не от опечатки: реестр рисует сам экран."""
    cid = await assert_company_product(body.company_id, current_user, db, "pulse")
    changed: list[str] = []
    for key, value in body.values.items():
        if key not in THRESHOLDS:
            continue
        if value is None:                      # «вернуть как было» — удаляем строку
            await db.execute(text(
                "delete from pulse_targets where company_id = :cid and key = :k"
            ), {"cid": str(cid), "k": key})
        else:
            await db.execute(text("""
                insert into pulse_targets (company_id, key, value, updated_by, updated_at)
                values (:cid, :k, :v, :uid, now())
                on conflict (company_id, key)
                do update set value = excluded.value, updated_by = excluded.updated_by,
                              updated_at = now()
            """), {"cid": str(cid), "k": key, "v": float(value), "uid": current_user.id})
        changed.append(key)
    if changed:
        await log_audit(db, actor=current_user, company_id=cid,
                        action="pulse.targets", target=", ".join(changed))
        await db.commit()
    return {"ok": True, "changed": changed}


@router.get("/objects")
async def pulse_objects(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Где болит» — точка сети сразу во всех контурах.

    Ни одно приложение этого не показывает: «Продажи» видят молчание станции,
    «Эксплуатация» — расходы по ней, и каждый считает, что у соседа всё в
    порядке. Здесь они сведены по одному ключу, и в список попадает точка, у
    которой сошлось несколько независимых признаков сразу.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    s = await _objects_snapshot(db, str(company_id))
    if not s:
        return {"available": False, "kpi": [], "pain": []}

    kpi = [
        _kpi("pain", "Точек с проблемами", s["pain_count"],
             note=f"из {s['total']} с движением", state="warn" if s["pain_count"] else None,
             higher_is_better=False),
        _kpi("idle", "Платим, но не продают", s["idle_cost_count"],
             note=f"{money(s['idle_cost_amount'])} ₽ за два месяца",
             state="warn" if s["idle_cost_count"] >= OBJ_IDLE_COST_MIN else None,
             higher_is_better=False),
        _kpi("at_risk", "Под вопросом, ₽", round(s["at_risk_total"]),
             note="расходы точек плюс потерянная выручка", higher_is_better=False),
    ]
    return {"available": True, "kpi": kpi, "pain": s["pain"][:25],
            "pain_count": s["pain_count"], "total": s["total"]}


@router.get("/operations")
async def pulse_operations(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Эксплуатация» — хозяйство вокруг сети глазами руководителя.

    Приложение «Эксплуатация» показывает хозяйство до последней строки: договоры,
    условия, счётчики, начисления по каждой точке. Руководителю нужен другой
    разрез: во сколько обходится незакрытый период, чем он подтверждён, кому мы
    должны и что тянется с прошлых месяцев.

    Ключевое различие, вокруг которого всё построено: ОЖИДАНИЕ (сколько должны по
    договору) и ФАКТ (документ от контрагента) — разные вещи. Пока акта нет, это
    не расход, а обещание, и закрывать месяц по ожиданиям нельзя.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(company_id)
    s = await _ops_snapshot(db, cid)
    if not s.get("charges") and not s.get("docs_overdue"):
        return {"available": False, "kpi": [], "items": [], "counterparties": [],
                "periods": [], "period": s.get("period")}

    labels = {r.code: r.label for r in (await db.execute(text(
        "select code, label from ops_cost_items"
    ))).all()}

    items = [{"code": code, "label": labels.get(code, code), "count": v["count"],
              "expected": v["expected"], "previous": v["prev"]}
             for code, v in s["by_item"].items()]

    counterparties = [{"name": r.nm, "count": r.n, "expected": float(r.exp or 0)}
                      for r in (await db.execute(text("""
        select coalesce(c.name, ch.counterparty_id, '(без контрагента)') as nm,
               count(*) as n, sum(ch.expected_gross) as exp
        from ops_period_charges ch
        left join counterparties c on c.id::text = ch.counterparty_id
        where ch.company_id = :cid and ch.period = :cur
        group by 1 order by exp desc nulls last limit 8
    """), {"cid": cid, "cur": s["period"]})).all()]

    # Реестр периодов — то самое «ждали ↔ собрали ↔ чем подтверждено», только
    # свёрнутое до строки на месяц: руководителю нужно увидеть хвосты, а не вести их.
    d = "^\\d{4}-\\d{2}-\\d{2}$"
    periods = [{"period": r.period, "charges": r.n, "expected": float(r.exp or 0),
                "with_doc": r.with_doc, "overdue": r.overdue,
                "status": r.status or "open"}
               for r in (await db.execute(text(f"""
        select ch.period, count(*) as n, sum(ch.expected_gross) as exp,
               count(*) filter (where ch.doc_id is not null) as with_doc,
               count(*) filter (where ch.doc_id is null and ch.doc_due_on ~ '{d}'
                                 and ch.doc_due_on::date < current_date) as overdue,
               max(pc.status) as status
        from ops_period_charges ch
        left join ops_period_close pc
               on pc.company_id = ch.company_id and pc.period::text = ch.period
        where ch.company_id = :cid and ch.period <= :cur
        group by ch.period order by ch.period desc limit 8
    """), {"cid": cid, "cur": s["period"]})).all()]

    top = sorted(items, key=lambda i: i["expected"], reverse=True)[:2]
    kpi = [
        _kpi("expected", "Ждём за месяц, ₽", round(s["expected"]),
             delta_pct=_dpct(s["expected"], s["expected_prev"]),
             note=f"период {s['period'][:7]}", higher_is_better=False),
        *[_kpi(f"item_{i['code']}", f"{i['label']}, ₽", round(i["expected"]),
               delta_pct=_dpct(i["expected"], i["previous"]),
               note=f"{i['count']} начислений", higher_is_better=False)
          for i in top],
        _kpi("charges", "Начислений в периоде", s["charges"],
             note="по договорам и условиям"),
        # Подтверждение — главное, чего не хватает пилоту: ожидания посчитаны,
        # а актов нет ни одного.
        _kpi("no_doc", "Без документа", s["no_doc"],
             note=f"на {money(s['no_doc_amount'])} ₽",
             state="warn" if s["no_doc"] else None, higher_is_better=False),
        _kpi("contracts", "Договоров с истёкшим сроком", s["contracts_expired"],
             note=(f"истекают за 60 дней: {s['contracts_ending']}"
                   if s["contracts_ending"] else f"всего договоров: {s['contracts_total']}"),
             state="warn" if s["contracts_expired"] else None, higher_is_better=False),
        _kpi("overdue", "Просрочено подтверждений", s["docs_overdue"],
             note=(f"с {s['docs_overdue_oldest']}" if s["docs_overdue_oldest"] else None),
             state="warn" if s["docs_overdue"] >= OPS_DOCS_OVERDUE else None,
             higher_is_better=False),
    ]

    # Договоры, у которых срок вышел или выйдет: имя контрагента важнее номера —
    # с ним идут разговаривать.
    contracts = [{"number": r.number, "counterparty": r.nm, "type": r.type_code,
                  "valid_until": r.valid_until, "expired": r.expired}
                 for r in (await db.execute(text(f"""
        select c.number, coalesce(cp.name, c.counterparty_id, '—') as nm,
               coalesce(c.type_code, c.type, '—') as type_code, c.valid_until,
               (c.valid_until::date < current_date) as expired
        from contracts c
        left join counterparties cp on cp.id::text = c.counterparty_id
        where c.company_id = :cid and not coalesce(c.is_closed, false)
          and c.valid_until ~ '{d}'
          and c.valid_until::date < current_date + 60
        order by c.valid_until desc limit 12
    """), {"cid": cid})).all()]

    return {"available": True, "period": s["period"], "kpi": kpi, "items": items,
            "counterparties": counterparties, "periods": periods,
            "open_periods": s["open_periods"], "contracts": contracts,
            "contracts_expired": s["contracts_expired"],
            "contracts_ending": s["contracts_ending"],
            "docs_overdue_amount": s["docs_overdue_amount"]}


@router.get("/projects")
async def pulse_projects(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Проекты» — что компания строит, глазами руководителя.

    Витрина приложения «Проекты» отвечает тому, кто ведёт дела («какие карточки
    у меня в работе»). Здесь три других вопроса: движется ли портфель вообще,
    где он застрял и у кого это на руках. Плюс поимённо — проекты-долгожители,
    потому что «46 застряло» задачей не становится, а «Магадан, Пролетарская 66,
    175 дней в проработке, ведущего нет» — становится.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(company_id)
    s = await _projects_snapshot(db, cid)
    if not s.get("active"):
        return {"available": False, "kpi": [], "stages": [], "longest": [],
                "moves": [], "owners": []}

    d = "^\\d{4}-\\d{2}-\\d{2}$"
    stages = [{"stage": r.stage, "label": STAGE_LABELS.get(r.stage, r.stage),
               "count": r.n, "avg_days": int(r.avg_days) if r.avg_days is not None else None,
               "stuck": r.stuck}
              for r in (await db.execute(text(f"""
        select stage, count(*) as n,
               avg(current_date - stage_since::date) filter (where stage_since ~ '{d}') as avg_days,
               count(*) filter (where stage_since ~ '{d}'
                    and current_date - stage_since::date > :days) as stuck
        from ezs_projects where company_id = :cid and stage <> 'archive'
        group by stage order by n desc
    """), {"cid": cid, "days": PR_STUCK_DAYS})).all()]

    # Имя проекта: своё название, иначе адрес площадки — карточки пилота
    # приехали импортом без заголовков, и список «(без имени) × 8» бесполезен.
    longest = [{"title": r.nm, "stage": STAGE_LABELS.get(r.stage, r.stage),
                "days": r.days, "region": r.region, "owner": r.owner,
                "next_action": r.next_action}
               for r in (await db.execute(text(f"""
        select coalesce(nullif(p.title,''), nullif(s.full_address,''),
                        nullif(concat_ws(', ', s.city, s.address), ''),
                        p.location_id, '(без имени)') as nm,
               p.stage, current_date - p.stage_since::date as days,
               coalesce(s.region, '—') as region,
               coalesce(u.name, '') as owner,
               coalesce(nullif(p.next_action, ''), '') as next_action
        from ezs_projects p
        left join ezs_sites s on s.id = p.site_id
        left join users u on u.id = p.owner_user_id
        where p.company_id = :cid and p.stage <> 'archive' and p.stage_since ~ '{d}'
        order by days desc limit 8
    """), {"cid": cid})).all()]

    owners = [{"name": r.owner or "(без ответственного)", "count": r.n}
              for r in (await db.execute(text("""
        select coalesce(u.name, '') as owner, count(*) as n
        from ezs_projects p left join users u on u.id = p.owner_user_id
        where p.company_id = :cid and p.stage <> 'archive'
        group by 1 order by n desc limit 8
    """), {"cid": cid})).all()]

    # Что сдвинулось: только переходы, гейты и документы. Правки полей карточки
    # («Площадь», «Адрес») — работа исполнителя, а не движение портфеля.
    moves = [{"at": r.at.isoformat() if r.at else None, "kind": r.kind, "text": r.txt}
             for r in (await db.execute(text("""
        select created_at as at, kind,
               coalesce(nullif("text",''), 'стадия: ' || coalesce(to_stage,'—')) as txt
        from ezs_site_events
        where company_id = :cid and kind in ('stage','gate','doc')
          and created_at >= now() - interval '7 days'
        order by created_at desc limit 12
    """), {"cid": cid})).all()]

    kpi = [
        _kpi("active", "Проектов в работе", s["active"], note="без архива"),
        _kpi("moves", "Сменили стадию", s["moves"],
             delta_pct=_dpct(s["moves"], s["moves_prev"]), note="за неделю"),
        _kpi("gates", "Гейтов пройдено", s["gates"], note="за неделю"),
        _kpi("stuck", f"Стоят > {PR_STUCK_DAYS} дней", s["stuck"],
             note=(f"хуже всего: {s['stuck_stage']}" if s["stuck_stage"] else None),
             state="warn" if s["stuck"] >= PR_STUCK_MIN else None,
             higher_is_better=False),
        _kpi("no_owner", "Без ответственного", s["no_owner"],
             note=f"из {s['active']} в работе",
             state="warn" if s["active"] and s["no_owner"] / s["active"] >= PR_OWNER_SHARE else None,
             higher_is_better=False),
        _kpi("overdue", "Просрочен следующий шаг", s["overdue"],
             note="по сроку из карточки",
             state="warn" if s["overdue"] else None, higher_is_better=False),
    ]

    return {"available": True, "kpi": kpi, "stages": stages, "longest": longest,
            "moves": moves, "owners": owners}


@router.get("/sales")
async def pulse_sales(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Продажи» — деньги сети глазами руководителя.

    Не копия витрины приложения «Продажи»: разрезов по коннекторам, часам и
    тарифам здесь нет — за ними идут туда. Здесь три вопроса: продаём ли столько
    же, вся ли сеть в работе и доезжает ли клиент до заряда. И один ответ,
    которого нет больше нигде: ЧТО именно двигает недельную цифру — конкретные
    станции и регионы, а не «выручка упала на 10%».
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(company_id)

    profile = await _profile(db, cid)
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]
    # У заправки нет ни «имени станции», ни региона в самой операции: имя — это
    # её код, а разрез по регионам показывать нечем.
    NAME = "station_name" if profile == "energy" else "station_code"
    HAS_REGION = profile == "energy"
    as_of = (await db.execute(text(
        f"select max({TS}) from {TBL} where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()
    s = await _sales_snapshot(db, cid, as_of, profile)
    if not s:
        return {"available": False, "kpi": [], "movers": [], "regions": [],
                "out_stations": [], "as_of": None}

    p = {"cid": cid, "as_of": as_of}
    weeks = (await db.execute(text(f"""
        select date_trunc('week', {TS}) as w,
               coalesce(sum({AMT}), 0) as revenue, count(*) as sessions,
               coalesce(sum({VOL}), 0) as kwh,
               count(distinct {LOC}) as live
        from {TBL}
        where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '8 weeks'
        group by 1 order by 1
    """), p)).all()

    # Что двигает цифру: станции с наибольшим сдвигом выручки в обе стороны.
    # Отсечка по прошлой неделе — чтобы список не заполнили точки, у которых
    # «выручка выросла втрое» с двухсот рублей.
    movers = [{"station": r.nm, "location_id": r.loc, "current": float(r.cur),
               "previous": float(r.prev), "delta": float(r.cur) - float(r.prev)}
              for r in (await db.execute(text(f"""
        select {LOC} as loc, max({NAME}) as nm,
               coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0) as cur,
               coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'), 0) as prev
        from {TBL}
        where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '14 days'
        group by {LOC}
        having coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'), 0) > 5000
            or coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0) > 5000
        order by abs(
          coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0)
          - coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'), 0)
        ) desc limit 8
    """), p)).all()]

    # Регион приносит сам источник: в зарядной сессии он есть, в операции АЗС —
    # нет. Раздел не выдумывает разрез, которого в данных не существует.
    regions = [] if not HAS_REGION else [
        {"region": r.region, "current": float(r.cur), "previous": float(r.prev),
         "stations": r.n}
        for r in (await db.execute(text(f"""
        select coalesce(nullif(region, ''), 'без региона') as region,
               count(distinct {LOC}) as n,
               coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0) as cur,
               coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'), 0) as prev
        from {TBL}
        where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '14 days'
        group by 1 order by cur desc limit 10
    """), p)).all()]

    # Выпавшие — поимённо: «38 станций молчат» без имён не превращается в задачу.
    out_stations = [{"station": r.nm, "location_id": r.loc, "lost": float(r.rev),
                     "last_seen": r.last.isoformat() if r.last else None}
                    for r in (await db.execute(text(f"""
        with cur as (
          select distinct {LOC} as loc from {TBL}
          where company_id = :cid and {TS} > CAST(:as_of AS timestamp) - interval '7 days'
        )
        select {LOC} as loc, max({NAME}) as nm,
               coalesce(sum({AMT}), 0) as rev, max({TS}) as last
        from {TBL}
        where company_id = :cid
          and {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
          and {TS} > CAST(:as_of AS timestamp) - interval '14 days'
          and {LOC} not in (select loc from cur)
        group by {LOC} order by rev desc limit 12
    """), p)).all()]

    kpi = [
        {**_kpi("revenue", "Выручка, ₽", round(s["revenue"]),
                delta_pct=_dpct(s["revenue"], s["revenue_prev"]),
                note="за неделю данных"),
         "spark": [float(w.revenue) for w in weeks]},
        {**_kpi("sessions", SESS_WORD, s["sessions"],
                delta_pct=_dpct(s["sessions"], s["sessions_prev"])),
         "spark": [float(w.sessions) for w in weeks]},
        {**_kpi("kwh", VOL_LABEL, round(s["kwh"]),
                delta_pct=_dpct(s["kwh"], s["kwh_prev"])),
         "spark": [float(w.kwh) for w in weeks]},
        _kpi("check", "Средний чек, ₽", s["avg_check"],
             delta_pct=_dpct(s["avg_check"] or 0, s["avg_check_prev"] or 0),
             note="на сессию"),
        # Успех приездов, а не сессий: клиент, зарядившийся с третьей попытки,
        # уехал довольным — это один успешный визит, а не две ошибки и успех.
        {**_kpi("visit_ok", "Уехали с зарядом, %", s["visit_ok_share"],
                delta_pct=_dpct(s["visit_ok_share"] or 0, s["visit_ok_share_prev"] or 0),
                note=f"из {s['visits']} приездов · норма ≥ {SALES_VISIT_OK:.0f}%",
                state=("warn" if s["visit_ok_share"] is not None
                       and s["visit_ok_share"] < SALES_VISIT_OK else None)),
         "spark": []},
        {**_kpi("live", "Станций в работе", s["live"],
                delta_pct=_dpct(s["live"], s["live_prev"]),
                note=(f"выпало за неделю: {s['stations_out']}"
                      if s["stations_out"] else "выпавших нет"),
                state="warn" if s["stations_out"] >= SALES_OUT_MIN else None),
         "spark": [float(w.live) for w in weeks]},
    ]

    return {
        "available": True,
        "as_of": as_of.isoformat() if as_of else None,
        "kpi": kpi, "movers": movers, "regions": regions,
        "out_stations": out_stations,
        "stations_out": s["stations_out"], "stations_out_revenue": s["stations_out_revenue"],
    }


@router.get("/contact-center")
async def pulse_contact_center(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Обращения» — разговор с потребителем глазами руководителя.

    Не копия рабочего места контакт-центра: ленты, карточек контактов и записей
    разговоров здесь нет — за ними идут в само приложение. Здесь четыре ответа:
    дозвонились ли до нас, быстро ли ответили, не брошены ли хвосты и не ходит
    ли клиент по кругу. Плюс два разреза, которых нет больше нигде: КОГДА не
    отвечают (профиль по часам) и КТО тянет нагрузку.

    Оценка «хорошо/плохо» берётся из целей самого контакт-центра
    (`cc_kpi_targets`), а не назначается «Пульсом».
    """
    await assert_company_product(company_id, current_user, db, "pulse")

    cc = await _cc_snapshot(db)
    if not cc:
        return {"available": False, "kpi": [], "hours": [], "operators": [],
                "as_of": None, "targets": {}}

    # Восемь недель ряда под цифрой: одна неделя против другой отвечает «стало
    # хуже?», а форма кривой — «это тенденция или разовый провал?».
    weeks = (await db.execute(text("""
        select date_trunc('week', started_at) as w,
               count(*) as calls,
               count(*) filter (where missed) as missed,
               avg(wait_sec) as wait
        from call_records
        where direction = 'inbound' and started_at >= now() - interval '8 weeks'
        group by 1 order by 1
    """))).all()
    tweeks = (await db.execute(text("""
        select date_trunc('week', created_at) as w,
               avg(extract(epoch from (first_response_at - created_at))) as frt,
               count(*) filter (where first_response_at is not null) as answered,
               count(*) filter (where first_response_at is not null
                 and extract(epoch from (first_response_at - created_at)) <= :t) as in_sla
        from inbox_threads
        where created_at >= now() - interval '8 weeks'
        group by 1 order by 1
    """), {"t": cc["target_frt"]})).all()

    spark_calls = [float(r.calls) for r in weeks]
    spark_missed = [round(100.0 * r.missed / r.calls, 1) if r.calls else None for r in weeks]
    spark_wait = [round(float(r.wait), 1) if r.wait is not None else None for r in weeks]
    spark_frt = [round(float(r.frt), 1) if r.frt is not None else None for r in tweeks]
    spark_sla = [round(100.0 * r.in_sla / r.answered, 1) if r.answered else None
                 for r in tweeks]

    def _pct_state(value: float | None, target: float, higher: bool) -> str | None:
        """Цвет плитки — по цели контакт-центра, а не по абстрактному «много»."""
        if value is None:
            return None
        return "warn" if (value < target if higher else value > target) else None

    kpi = [
        # Объём обращений — контекст, а не оценка: и рост, и падение потока сами
        # по себе не победа и не провал, поэтому дельта здесь нейтральная.
        {**_kpi("calls", "Звонков за неделю", cc["calls"],
                delta_pct=_dpct(cc["calls"], cc["calls_prev"]),
                note="входящие", link=None), "higher_is_better": None,
         "spark": spark_calls},
        {**_kpi("missed_share", "Пропущено, %", cc["missed_share"],
                delta_pct=_dpct(cc["missed_share"] or 0, cc["missed_share_prev"] or 0),
                note=f"{cc['missed']} звонков · цель ≤ {cc['target_missed']:.0f}%",
                state=_pct_state(cc["missed_share"], cc["target_missed"], higher=False),
                higher_is_better=False), "spark": spark_missed},
        {**_kpi("wait", "Ждут ответа, с", cc["wait"],
                delta_pct=_dpct(cc["wait"] or 0, cc["wait_prev"] or 0),
                note="среднее до снятия трубки", higher_is_better=False),
         "spark": spark_wait},
        {**_kpi("frt", "Первый ответ, с", cc["frt"],
                delta_pct=_dpct(cc["frt"] or 0, cc["frt_prev"] or 0),
                note=f"цель ≤ {cc['target_frt']:.0f} с",
                state=_pct_state(cc["frt"], cc["target_frt"], higher=False),
                higher_is_better=False), "spark": spark_frt},
        {**_kpi("in_sla", "В цели по SLA, %", cc["in_sla_share"],
                delta_pct=_dpct(cc["in_sla_share"] or 0, cc["in_sla_share_prev"] or 0),
                note=f"из {cc['answered']} отвеченных · цель ≥ {cc['target_in_sla']:.0f}%",
                state=_pct_state(cc["in_sla_share"], cc["target_in_sla"], higher=True)),
         "spark": spark_sla},
        _kpi("repeat", "Звонят повторно", cc["repeat_people"],
             note=f"{CC_REPEAT_TIMES}+ обращения за неделю", higher_is_better=False),
    ]

    # Когда именно не отвечают: ночь, обед и утренний пик — разные разговоры с
    # подрядчиком, и по суточной доле их не различить.
    hours = [{"hour": int(r.h), "calls": r.n, "missed": r.missed}
             for r in (await db.execute(text("""
        select extract(hour from started_at at time zone 'Europe/Moscow') as h,
               count(*) as n, count(*) filter (where missed) as missed
        from call_records
        where direction = 'inbound' and started_at >= now() - interval '7 days'
        group by 1 order by 1
    """))).all()]

    # Кто тянет: перекос нагрузки виден только по именам. Пропущенные висят без
    # оператора — их в этот список не берём, для них есть своя плитка.
    operators = [{"name": r.op, "calls": r.n,
                  "wait": round(float(r.wait), 1) if r.wait is not None else None,
                  "talk": round(float(r.talk), 1) if r.talk is not None else None}
                 for r in (await db.execute(text("""
        select coalesce(nullif(operator, ''), '—') as op, count(*) as n,
               avg(wait_sec) as wait, avg(duration_sec) as talk
        from call_records
        where started_at >= now() - interval '7 days' and not missed
          and coalesce(nullif(operator, ''), '') <> ''
        group by 1 order by 2 desc limit 10
    """))).all()]

    as_of = (await db.execute(text("select max(started_at) from call_records"))).scalar()

    return {
        "available": True,
        "as_of": as_of.isoformat() if as_of else None,
        "kpi": kpi, "hours": hours, "operators": operators,
        "stuck": cc["wrapup_stuck"], "escalations": cc["escalations"],
        "targets": {"missed_share": cc["target_missed"], "first_response_sec": cc["target_frt"],
                    "in_sla_share": cc["target_in_sla"]},
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
    await assert_company_product(company_id, current_user, db, "pulse")
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
    await assert_company_product(company_id, current_user, db, "pulse")
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

    # Комнаты схлопываем по имени: у приложений их по нескольку с одинаковым
    # названием («Бухгалтерия» ×3), и в карточке это читалось как ошибка.
    rooms = [{"name": r.name, "kind": r.kind, "count": r.n} for r in (await db.execute(text("""
        select cr.name, min(cr.kind) as kind, count(*) as n
        from chat_participants cp
        join chat_rooms cr on cr.id = cp.room_id
        where cp.user_id = :uid
        group by cr.name order by cr.name limit 30
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

    Доставка утренним письмом живёт отдельно (`services/pulse_digest.py`) и
    считает тот же экран дня, поэтому здесь только запрос-ответ.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    return await pulse_week_data(db, str(company_id))


async def pulse_week_data(db: AsyncSession, company_id: str) -> dict[str, Any]:
    """Данные «Недели» без проверки доступа — её делает вызывающий (и выгрузка)."""
    cid = str(company_id)

    profile = await _profile(db, cid)
    TBL, TS, AMT, VOL, VOL_LABEL, LOC, SESS_WORD = PROFILE_SALES[profile]
    as_of = (await db.execute(text(
        f"select max({TS}) from {TBL} where company_id = :cid"
    ), {"cid": cid})).scalar_one_or_none()

    rows: list[dict[str, Any]] = []
    if as_of is not None:
        w = (await db.execute(text(f"""
            select count(*) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days') as s,
                   coalesce(sum({AMT}) filter (where {TS} > CAST(:as_of AS timestamp) - interval '7 days'), 0) as r,
                   count(*) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
                                    and {TS} > CAST(:as_of AS timestamp) - interval '14 days') as sp,
                   coalesce(sum({AMT}) filter (where {TS} <= CAST(:as_of AS timestamp) - interval '7 days'
                                    and {TS} > CAST(:as_of AS timestamp) - interval '14 days'), 0) as rp
            from {TBL} where company_id = :cid
        """), {"cid": cid, "as_of": as_of})).one()
        rows.append({"label": "Выручка", "value": float(w.r), "prev": float(w.rp),
                     "unit": "₽", "higher_is_better": True})
        rows.append({"label": SESS_WORD, "value": w.s, "prev": w.sp,
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

    # Разговор с потребителем — тремя строками: сколько звонили, скольких не
    # услышали, как быстро отвечали. Подробности — в «Обращениях».
    cc = await _cc_snapshot(db)
    if cc.get("calls"):
        rows.append({"label": "Звонков принято", "value": cc["calls"] - cc["missed"],
                     "prev": (cc["calls_prev"] - cc["missed_prev"]) or None,
                     "unit": None, "higher_is_better": True})
        rows.append({"label": "Звонков пропущено", "value": cc["missed"],
                     "prev": cc["missed_prev"] or None,
                     "unit": None, "higher_is_better": False})
        if cc["frt"] is not None:
            rows.append({"label": "Первый ответ", "value": round(cc["frt"]),
                         "prev": round(cc["frt_prev"]) if cc["frt_prev"] is not None else None,
                         "unit": "с", "higher_is_better": False})

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
    await assert_company_product(company_id, current_user, db, "pulse")
    rows = (await db.execute(text("""
        select a.card_key, a.acked_on, a.acked_at, a.snooze_until, a.note, u.name as who
        from pulse_acks a
        left join users u on u.id = a.user_id
        where a.company_id = :cid
          and (a.acked_on >= current_date - 7
               or (a.snooze_until is not null and a.snooze_until >= current_date))
        order by a.acked_at desc
    """), {"cid": str(company_id)})).all()
    return {"items": [{
        "card_key": r.card_key,
        "title": CARD_TITLES.get(r.card_key, r.card_key),
        "on": r.acked_on.isoformat(),
        "at": r.acked_at.isoformat() if r.acked_at else None,
        "who": r.who,
        "note": r.note,
        "snooze_until": r.snooze_until.isoformat() if r.snooze_until else None,
        "today": r.acked_on == date.today(),
    } for r in rows]}


class AckIn(BaseModel):
    company_id: str
    card_key: str
    # Сколько дней не показывать. 0/None — «принято на сегодня», как раньше.
    snooze_days: int | None = None
    note: str | None = None


@router.post("/ack")
async def ack_card(
    body: AckIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Снять карточку: на сегодня («принято») или на срок («вернуться через N дней»).

    Отложенное — обязательство руководителя, а не забывание: оно остаётся
    видимым в «Принятом» с датой возврата, и по её наступлении живое условие
    вернёт карточку само, если проблема не решилась.
    """
    await assert_company_product(body.company_id, current_user, db, "pulse")
    cid = uuid.UUID(body.company_id)
    days = max(0, min(int(body.snooze_days or 0), 30))   # месяц — потолок
    until = date.today() + timedelta(days=days) if days else None
    row = (await db.execute(text("""
        select 1 from pulse_acks
        where company_id = :cid and card_key = :key and acked_on = current_date
    """), {"cid": str(cid), "key": body.card_key})).first()
    if row:
        # Повторное нажатие в тот же день — обновляем срок, а не плодим записи.
        await db.execute(text("""
            update pulse_acks set snooze_until = :until, note = :note, user_id = :uid
            where company_id = :cid and card_key = :key and acked_on = current_date
        """), {"cid": str(cid), "key": body.card_key, "until": until,
               "note": body.note, "uid": current_user.id})
    else:
        db.add(PulseAck(company_id=cid, card_key=body.card_key,
                        acked_on=date.today(), user_id=current_user.id,
                        snooze_until=until, note=body.note))
    await log_audit(db, actor=current_user, company_id=cid,
                    action="pulse.snooze" if days else "pulse.ack",
                    target=body.card_key,
                    details={"days": days} if days else None)
    await db.commit()
    return {"ok": True, "snooze_until": until.isoformat() if until else None}


# ── Витрины: «Пульс», повёрнутый наружу ─────────────────────────────────────
# Заказчику, владельцу сети, куратору со стороны холдинга нужна проверенная картина
# по своей теме — без погружения в приложения — и канал, по которому им можно
# адресовать просьбу. Витрина собирается из тех же блоков, что считает «Пульс»:
# второго набора метрик не заводим, иначе цифра наружу разойдётся с цифрой внутри.



async def _catalog(db: AsyncSession, cid: str) -> list[tuple[str, str, str]]:
    """Блоки, доступные компании: по профилю пространства."""
    profile = (await db.execute(text(
        "SELECT profile_id FROM companies WHERE id = CAST(:cid AS uuid)"),
        {"cid": str(cid)})).scalar_one_or_none()
    base = OFFICE_BLOCKS if profile == "office" else PULSE_ITEMS
    return [*base, *COMMON_BLOCKS]


@router.get("/views")
async def pulse_views(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Витрины компании и каталог блоков, из которых их собирают."""
    # Список витрин — только администратору: в нём видно, кому и что мы
    # показываем, включая черновики. Своему получателю нужен `/my-views`.
    cid = str(await assert_company_admin_product(company_id, current_user, db))

    rows = (await db.execute(text("""
        SELECT v.id::text, v.name, v.audience, v.period, v.owner_name, v.note, v.status,
               v.updated_at,
               (SELECT count(*) FROM pulse_view_blocks b WHERE b.view_id = v.id) AS blocks,
               (SELECT count(*) FROM pulse_view_grants g WHERE g.view_id = v.id) AS people
          FROM pulse_views v
         WHERE v.company_id = CAST(:cid AS uuid)
         ORDER BY v.status, v.name"""), {"cid": cid})).all()

    return {
        "views": [{
            "id": r[0], "name": r[1], "audience": r[2], "period": r[3],
            "owner": r[4], "note": r[5], "status": r[6],
            "updatedAt": r[7].isoformat() if r[7] else None,
            "blocks": r[8], "people": r[9],
        } for r in rows],
        # Каталог — тот же список пунктов «Пульса»: витрина показывает готовые разрезы,
        # а не свои. Группа нужна конструктору, чтобы блоки не шли одной кучей.
        # Каталог зависит от профиля компании: блоки про заправки и объекты сети в
        # пространстве бухгалтерского аутсорсера пусты, и предлагать их — обманывать
        # того, кто собирает витрину.
        "catalog": [{"key": k, "title": t, "group": g} for k, t, g in await _catalog(db, cid)],
        # Недели в списке нет намеренно: регистр бухгалтерии помесячный, и «неделя»
        # молча превращалась в тот же месяц — ярлык обещал одно, цифра давала другое.
        "periods": [{"key": "month", "title": "Месяц"},
                    {"key": "quarter", "title": "Квартал"},
                    {"key": "year", "title": "Год"}],
    }


@router.post("/views")
async def pulse_view_create(
    company_id: str = Query(...),
    name: str = Query(...),
    audience: str = "",
    period: str = "month",
    owner_name: str | None = None,
    organization_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Завести витрину. Создаётся черновиком: показывать недособранное нельзя."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    org = None
    if organization_id:
        try:
            org = (await db.execute(text(
                "SELECT id FROM organizations WHERE company_id = CAST(:c AS uuid)"
                "   AND id = CAST(:o AS uuid)"),
                {"c": str(cid), "o": organization_id})).scalar_one_or_none()
        except Exception:
            org = None
    row = PulseView(company_id=cid, name=name.strip(), audience=audience.strip(),
                    period=period, owner_name=(owner_name or "").strip() or None,
                    organization_id=org, created_by=current_user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "name": row.name, "status": row.status}


@router.patch("/views/{view_id}")
async def pulse_view_update(
    view_id: str,
    company_id: str = Query(...),
    name: str | None = None,
    audience: str | None = None,
    period: str | None = None,
    owner_name: str | None = None,
    note: str | None = None,
    organization_id: str | None = None,
    feedback_mode: str | None = None,
    feedback_room_id: str | None = None,
    feedback_assignee_id: str | None = None,
    status_: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Изменить витрину или опубликовать её."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, cid, view_id)

    if status_ is not None:
        if status_ not in ("draft", "published"):
            raise HTTPException(status_code=400, detail="Неизвестное состояние витрины")
        if status_ == "published":
            n = (await db.execute(text(
                "SELECT count(*) FROM pulse_view_blocks WHERE view_id = CAST(:v AS uuid)"),
                {"v": str(v.id)})).scalar_one()
            if not n:
                # Пустая витрина у получателя выглядит как поломка, а не как «ещё не
                # собрали»: публиковать нечего.
                raise HTTPException(status_code=400, detail="В витрине нет ни одного блока")
        v.status = status_
    for field, value in (("name", name), ("audience", audience), ("period", period),
                         ("owner_name", owner_name), ("note", note)):
        if value is not None:
            setattr(v, field, value.strip() if isinstance(value, str) else value)

    if organization_id is not None:
        raw = organization_id.strip()
        v.organization_id = None
        if raw:
            try:
                v.organization_id = (await db.execute(text(
                    "SELECT id FROM organizations WHERE company_id = CAST(:c AS uuid)"
                    "   AND id = CAST(:o AS uuid)"),
                    {"c": str(cid), "o": raw})).scalar_one_or_none()
            except Exception:
                v.organization_id = None

    if feedback_mode is not None:
        if feedback_mode not in ("task", "chat", "both", "none"):
            raise HTTPException(status_code=400, detail="Неизвестный канал обращений")
        v.feedback_mode = feedback_mode
    for field, raw in (("feedback_room_id", feedback_room_id),
                       ("feedback_assignee_id", feedback_assignee_id)):
        if raw is None:
            continue
        try:
            setattr(v, field, uuid.UUID(raw.strip()) if raw.strip() else None)
        except ValueError:
            setattr(v, field, None)
    await db.commit()
    return {"id": str(v.id), "status": v.status}


@router.put("/views/{view_id}/blocks")
async def pulse_view_blocks(
    view_id: str,
    payload: dict,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Состав витрины: какие блоки, в каком порядке и под какими заголовками.

    Приходит целиком, а не по одному: перетаскивание блоков в конструкторе — это одно
    действие человека, и половина сохранённого порядка хуже, чем несохранённый.
    """
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, cid, view_id)

    items = payload.get("blocks") or []
    known = {k for k, _, _ in await _catalog(db, cid)}
    clean = [b for b in items if isinstance(b, dict) and b.get("key") in known]

    await db.execute(text("DELETE FROM pulse_view_blocks WHERE view_id = CAST(:v AS uuid)"),
                     {"v": str(v.id)})
    for i, b in enumerate(clean):
        db.add(PulseViewBlock(
            view_id=v.id, block_key=b["key"], sort=i,
            title=(b.get("title") or "").strip() or None,
            hint=(b.get("hint") or "").strip() or None))
    await db.commit()
    return {"blocks": len(clean), "skipped": len(items) - len(clean)}


@router.put("/views/{view_id}/grants")
async def pulse_view_grants(
    view_id: str,
    payload: dict,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Кому назначена витрина."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, cid, view_id)

    raw = payload.get("users") or []
    ids: list[str] = []
    for x in raw:
        try:
            ids.append(str(uuid.UUID(str(x))))
        except ValueError:
            continue
    # Только участники этой компании: витрина не средство раздать доступ наружу
    # в обход членства.
    ours = [str(r[0]) for r in (await db.execute(text("""
        SELECT user_id FROM user_companies
         WHERE company_id = CAST(:cid AS uuid)
           AND user_id = ANY(CAST(:ids AS uuid[]))"""),
        {"cid": str(cid), "ids": ids or ["00000000-0000-0000-0000-000000000000"]})).all()]

    await db.execute(text("DELETE FROM pulse_view_grants WHERE view_id = CAST(:v AS uuid)"),
                     {"v": str(v.id)})
    for uid in ours:
        db.add(PulseViewGrant(view_id=v.id, user_id=uuid.UUID(uid)))
    await db.commit()
    return {"granted": len(ours), "skipped": len(raw) - len(ours)}


@router.get("/views/{view_id}")
async def pulse_view_card(
    view_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Витрина целиком: состав, получатели и подпись.

    Отдаётся и администратору (для конструктора), и получателю (для показа) — но
    получателю только опубликованная и только своя.
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    v = await _view_or_404(db, cid, view_id)

    mine = (await db.execute(text("""
        SELECT 1 FROM pulse_view_grants
         WHERE view_id = CAST(:v AS uuid) AND user_id = CAST(:u AS uuid)
        UNION ALL
        SELECT 1 FROM pulse_view_role_grants rg
          JOIN pulse_views pv ON pv.id = rg.view_id
          JOIN user_companies uc ON uc.role_id = rg.role_id
               AND uc.company_id = pv.company_id
         WHERE rg.view_id = CAST(:v AS uuid) AND uc.user_id = CAST(:u AS uuid)"""),
        {"v": str(v.id), "u": str(current_user.id)})).first() is not None
    is_admin = current_user.is_superadmin or await _is_company_admin(db, cid, current_user)
    if not is_admin and not (mine and v.status == "published"):
        raise HTTPException(status_code=404, detail="Витрина не найдена")

    titles = {k: t for k, t, _ in await _catalog(db, cid)}
    blocks = [{
        "key": r[0], "title": r[1] or titles.get(r[0], r[0]),
        "originalTitle": titles.get(r[0], r[0]), "hint": r[2],
    } for r in (await db.execute(text("""
        SELECT block_key, title, hint FROM pulse_view_blocks
         WHERE view_id = CAST(:v AS uuid) ORDER BY sort"""), {"v": str(v.id)})).all()]

    people = [{"id": str(r[0]), "name": r[1], "email": r[2]}
              for r in (await db.execute(text("""
        SELECT u.id, u.name, u.email FROM pulse_view_grants g
          JOIN users u ON u.id = g.user_id
         WHERE g.view_id = CAST(:v AS uuid) ORDER BY u.name"""), {"v": str(v.id)})).all()]

    return {
        "id": str(v.id), "name": v.name, "audience": v.audience, "period": v.period,
        "owner": v.owner_name, "note": v.note, "status": v.status,
        "blocks": blocks,
        # Состав получателей — дело администратора: получателю ни к чему имена и
        # почты тех, кому показывают ту же картину.
        "people": people if is_admin else [],
        "canEdit": is_admin,
        "roles": [{"id": str(r[0]), "name": r[1]} for r in (await db.execute(text("""
            SELECT cr.id, cr.name FROM pulse_view_role_grants rg
              JOIN company_roles cr ON cr.id = rg.role_id
             WHERE rg.view_id = CAST(:v AS uuid) ORDER BY cr.name"""),
            {"v": str(v.id)})).all()],
        "organizationId": str(v.organization_id) if v.organization_id else None,
        "feedbackMode": v.feedback_mode,
        "feedbackRoomId": str(v.feedback_room_id) if v.feedback_room_id else None,
        "feedbackAssigneeId": (str(v.feedback_assignee_id)
                               if v.feedback_assignee_id else None),
        # Дата, на которую верны цифры: витрина уходит наружу, и «когда-то посчитано»
        # там не ответ.
        "asOf": date.today().isoformat(),
    }


@router.put("/views/{view_id}/roles")
async def pulse_view_roles(
    view_id: str,
    payload: dict,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Каким ролям показываем витрину.

    Роль, а не только поимённый список: «настраиваем для каждой роли» означает, что
    новый сотрудник с этой ролью получает свою картину сам, без ручной выдачи.
    Поимённое назначение остаётся для исключений.
    """
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, str(cid), view_id)

    raw = payload.get("roles") or []
    ids = []
    for x in raw:
        try:
            ids.append(str(uuid.UUID(str(x))))
        except ValueError:
            continue
    ours = [str(r[0]) for r in (await db.execute(text("""
        SELECT id FROM company_roles
         WHERE company_id = CAST(:cid AS uuid) AND id = ANY(CAST(:ids AS uuid[]))"""),
        {"cid": str(cid), "ids": ids or ["00000000-0000-0000-0000-000000000000"]})).all()]

    await db.execute(text("DELETE FROM pulse_view_role_grants WHERE view_id = CAST(:v AS uuid)"),
                     {"v": str(v.id)})
    for rid in ours:
        await db.execute(text("""
            INSERT INTO pulse_view_role_grants (view_id, role_id)
            VALUES (CAST(:v AS uuid), CAST(:r AS uuid))"""), {"v": str(v.id), "r": rid})
    await db.commit()
    return {"roles": len(ours), "skipped": len(raw) - len(ours)}


@router.get("/views/{view_id}/data")
async def pulse_view_data(
    view_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Витрина с данными — то, что видит получатель.

    Блоки считаются по тем же таблицам, что и рабочие экраны: витрина показывает
    состояние дела, а не свою версию цифр. Если блок в этом пространстве не
    считается, он честно говорит об этом, а не показывает ноль — ноль читается как
    «всё хорошо», и это худший способ соврать.
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    v = await _view_or_404(db, cid, view_id)

    mine = (await db.execute(text("""
        SELECT 1 FROM pulse_view_grants
         WHERE view_id = CAST(:v AS uuid) AND user_id = CAST(:u AS uuid)
        UNION ALL
        SELECT 1 FROM pulse_view_role_grants rg
          JOIN pulse_views pv ON pv.id = rg.view_id
          JOIN user_companies uc ON uc.role_id = rg.role_id
               AND uc.company_id = pv.company_id
         WHERE rg.view_id = CAST(:v AS uuid) AND uc.user_id = CAST(:u AS uuid)"""),
        {"v": str(v.id), "u": str(current_user.id)})).first() is not None
    is_admin = current_user.is_superadmin or await _is_company_admin(db, cid, current_user)
    if not is_admin and not (mine and v.status == "published"):
        raise HTTPException(status_code=404, detail="Витрина не найдена")

    catalog = {k: t for k, t, _ in await _catalog(db, cid)}
    profile = (await db.execute(text(
        "SELECT profile_id FROM companies WHERE id = CAST(:cid AS uuid)"),
        {"cid": cid})).scalar_one_or_none()

    blocks = []
    for r in (await db.execute(text("""
        SELECT block_key, title, hint FROM pulse_view_blocks
         WHERE view_id = CAST(:v AS uuid) ORDER BY sort"""), {"v": str(v.id)})).all():
        key, title, hint = r
        if key == "view.feedback":
            data = await _feedback_block(db, cid, current_user)
        elif key.startswith("my."):
            data = await _my_block(db, cid, current_user, key)
        elif profile == "office":
            data = await _office_block_data(db, cid, key, v.period,
                                            str(v.organization_id)
                                            if v.organization_id else None)
        else:
            data = {"note": "Блок этого профиля пока не считается для витрины."}
        blocks.append({
            "key": key, "title": title or catalog.get(key, key), "hint": hint,
            "metrics": data.get("metrics") or [], "items": data.get("items") or [],
            "note": data.get("note"),
            # Витрина не заменяет приложение: где нужно разбираться глубже, она
            # честно уводит туда, а не отращивает вторую копию чата или трекера.
            "link": data.get("link"),
        })

    return {
        "id": str(v.id), "name": v.name, "audience": v.audience,
        "owner": v.owner_name, "note": v.note, "status": v.status,
        "asOf": date.today().isoformat(),
        "period": v.period,
        "periodLabel": {"month": "за месяц", "quarter": "за квартал",
                        "year": "за год"}.get(v.period, v.period),
        # Получателю нужно знать, можно ли отсюда написать: кнопка, которая ничего
        # не делает, хуже её отсутствия.
        "canWrite": v.feedback_mode != "none" and not (
            v.feedback_mode == "chat" and not v.feedback_room_id),
        "company": (await db.execute(text(
            "SELECT name FROM companies WHERE id = CAST(:cid AS uuid)"),
            {"cid": cid})).scalar_one_or_none(),
        "blocks": blocks,
    }


@router.get("/my-views")
async def pulse_my_views(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Витрины, назначенные мне. Для получателя это весь его «Пульс»."""
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    # Витрина достаётся человеку поимённо ИЛИ по его роли в компании: второй путь
    # и есть «настроили для роли» — новый сотрудник получает картину сам.
    rows = (await db.execute(text("""
        SELECT DISTINCT v.id::text, v.name, v.audience, v.owner_name, v.updated_at
          FROM pulse_views v
          LEFT JOIN pulse_view_grants g ON g.view_id = v.id AND g.user_id = CAST(:u AS uuid)
          LEFT JOIN pulse_view_role_grants rg ON rg.view_id = v.id
          LEFT JOIN user_companies uc ON uc.company_id = v.company_id
               AND uc.user_id = CAST(:u AS uuid) AND uc.role_id = rg.role_id
         WHERE v.company_id = CAST(:cid AS uuid) AND v.status = 'published'
           AND (g.user_id IS NOT NULL OR uc.user_id IS NOT NULL)
         ORDER BY v.name"""), {"cid": cid, "u": str(current_user.id)})).all()
    return {"views": [{"id": r[0], "name": r[1], "audience": r[2], "owner": r[3],
                       "updatedAt": r[4].isoformat() if r[4] else None} for r in rows]}


async def _view_or_404(db: AsyncSession, cid, view_id: str) -> PulseView:
    try:
        uid = uuid.UUID(view_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Витрина не найдена")
    v = (await db.execute(select(PulseView).where(
        PulseView.company_id == (cid if isinstance(cid, uuid.UUID) else uuid.UUID(str(cid))),
        PulseView.id == uid))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Витрина не найдена")
    return v


async def _is_company_admin(db: AsyncSession, cid, user: User) -> bool:
    if user.is_superadmin:
        return True
    r = (await db.execute(text("""
        SELECT role FROM user_companies
         WHERE company_id = CAST(:cid AS uuid) AND user_id = CAST(:u AS uuid)"""),
        {"cid": str(cid), "u": str(user.id)})).scalar_one_or_none()
    return r == "admin"


async def assert_company_admin_product(company_id: str, user: User, db: AsyncSession):
    """Собирать витрины может администратор компании: витрина уходит наружу."""
    cid = await assert_company_product(company_id, user, db, "pulse")
    if not await _is_company_admin(db, cid, user):
        raise HTTPException(status_code=403, detail="Витрины настраивает администратор")
    return cid

# ── Период витрины и сравнение с прошлым ────────────────────────────────────
# Витрина показывала состояние на сегодня. Но получателю — куратору, владельцу,
# заказчику — важнее не сама цифра, а стало лучше или хуже: «НДС 158 тысяч» без
# «в прошлом квартале было 96» не говорит ничего.
#
# Период задаётся у витрины (неделя, месяц, квартал) и означает окно, за которое
# считаются оборотные блоки. Остаточные (сальдо, долг) периодом не режутся: остаток
# на дату — это остаток на дату, и «сальдо за неделю» бессмыслица.


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


def _delta(now_v: float, was_v: float, higher_is_better: bool = True) -> dict[str, Any] | None:
    """Сравнение с прошлым окном: сколько и в какую сторону.

    Сравнения НЕТ в двух случаях, и оба — про честность:
    · в прошлом окне пусто — «рост на 100 %» от нуля это не рост, а появление;
    · в ТЕКУЩЕМ окне пусто — месяц просто ещё не закрыт, а «−100 %» зелёным
      читается как «налог упал до нуля». Это самая опасная ложь витрины.
    """
    if not was_v or not now_v:
        return None
    diff = now_v - was_v
    pct = diff / abs(was_v) * 100
    if abs(pct) < 0.5:
        return {"text": "как в прошлом периоде", "tone": None}
    up = diff > 0
    good = up if higher_is_better else not up
    return {
        "text": ("%+.0f%% к прошлому периоду" % pct),
        "tone": "good" if good else "warning",
    }

# ── Блоки витрины для профиля «office» ──────────────────────────────────────
# Каталог «Пульса» собран под сети: продажи ЭЗС, заправки, объекты, эксплуатация.
# В пространстве бухгалтерского аутсорсера этих данных нет вовсе, зато есть учёт
# клиента — и витрина наружу нужна именно по нему: заказчик хочет знать, в каком
# состоянии его учёт, чего от него ждут и сколько будет налогов.
#
# Блоки считают ПО ТЕМ ЖЕ ручкам «Бухгалтерии», а не по своим запросам: разошедшаяся
# цифра наружу — худшее, что может сделать витрина.

# Обратный ход витрины — общий блок для всех профилей.
COMMON_BLOCKS: list[tuple[str, str, str]] = [
    ("view.feedback", "Мои обращения", "Связь"),
    # «Пульс» — место работы, а не только просмотра: у человека тут его разговоры,
    # его заявки и его задачи. Но это ВИТРИНА, а не второй чат и не второй трекер:
    # блок показывает, что требует внимания, и уводит в специализированное
    # приложение, где с этим работают по-настоящему.
    ("my.chats", "Мои разговоры", "Связь"),
    ("my.tickets", "Мои заявки", "Связь"),
    ("my.tasks", "Мои задачи", "Связь"),
]

OFFICE_BLOCKS: list[tuple[str, str, str]] = [
    ("books.state", "Состояние учёта", "Учёт"),
    ("books.closing", "Закрытие периода", "Учёт"),
    ("books.requests", "Чего ждём от вас", "Учёт"),
    ("books.taxes", "Налоги заранее", "Деньги"),
    ("books.result", "Выручка и прибыль", "Деньги"),
    ("books.settlements", "Взаиморасчёты", "Деньги"),
    ("books.calendar", "Сроки и бюджет", "Сроки"),
    ("books.trends", "На что посмотреть", "Сроки"),
]



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


async def _office_block_data(db: AsyncSession, cid: str, key: str,
                             period: str = "month",
                             org: str | None = None) -> dict[str, Any]:
    """Данные одного блока витрины для профиля «office».

    Возвращает готовую к показу карточку: цифры, строка-объяснение и, если есть,
    короткий список. Формат один на все блоки — витрина не должна знать, чем
    отличается «Закрытие периода» от «Налогов»: разное здесь только содержание.
    """
    # Юрлицо витрины. Пусто — вся компания; заданное — только его данные, тем же
    # условием, что и в «Бухгалтерии»: строки без организации видны в любом разрезе
    # (они старше появления оси), чужие — нет.
    p = {"cid": cid, "org": org}
    since, till, prev_since, prev_till = _period_bounds(period, date.today())

    if key == "books.state":
        docs, entries = (await db.execute(text("""
            SELECT (SELECT count(*) FROM accounting_docs WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))),
                   (SELECT count(*) FROM gl_entries WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid)))"""),
            p)).one()
        return {
            "metrics": [{"label": "Документов в учёте", "value": f"{docs:,}".replace(",", " ")},
                        {"label": "Проводок", "value": f"{entries:,}".replace(",", " ")}],
            "note": "Учёт ведётся в вашей 1С; здесь он показан таким, каким доехал к нам.",
        }

    if key == "books.closing":
        rows = (await db.execute(text("""
            SELECT count(*), coalesce(sum(amount), 0)
              FROM doc_requests
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid)) AND status IN ('open','requested','promised')"""),
            p)).one()
        closed, total = (await db.execute(text("""
            SELECT count(*) FILTER (WHERE status = 'closed'), count(*)
              FROM periods WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))"""), p)).one()
        return {
            "metrics": [{"label": "Периодов закрыто", "value": f"{closed} из {total}"},
                        {"label": "Ждём документов", "value": f"{rows[0]}"},
                        {"label": "На сумму", "value": _money(rows[1])}],
            "note": "Закрытый период не переписывается: опоздавший документ попадёт в текущий.",
        }

    if key == "books.requests":
        items = [{"title": r[0] or "—", "detail": f"{r[1]} · до {r[2] or 'срок не задан'}",
                  "amount": _money(r[3]), "requestId": str(r[4])}
                 for r in (await db.execute(text("""
            SELECT counterparty_name, doc_kind, due_date, amount, id
              FROM doc_requests
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
               AND status IN ('open','requested','promised')
             ORDER BY due_date NULLS LAST LIMIT 12"""), p)).all()]
        overdue = (await db.execute(text("""
            SELECT count(*) FROM doc_requests
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
               AND status IN ('open','requested','promised')
               AND due_date IS NOT NULL AND due_date < to_char(CURRENT_DATE, 'YYYY-MM-DD')"""),
            p)).scalar_one()
        # Счётчик — по всем требованиям, а не по показанным: список ограничен
        # дюжиной строк, и «12» рядом с «15» в соседнем блоке той же витрины
        # выглядит как ошибка в цифрах, а не как лимит показа.
        total = (await db.execute(text("""
            SELECT count(*) FROM doc_requests
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
               AND status IN ('open','requested','promised')"""), p)).scalar_one()
        note = "Это то, что нужно от вас, чтобы закрыть период и заявить вычет."
        if total > len(items):
            note += " Показаны первые %d из %d." % (len(items), total)
        return {
            "metrics": [{"label": "Ждём документов", "value": str(total)},
                        {"label": "Срок прошёл", "value": str(overdue),
                         "tone": "warning" if overdue else None}],
            "items": items,
            "note": note,
        }

    if key == "books.taxes":
        # НДС берём по счёту 68.02 — это факт начисления и вычета. А налог на
        # прибыль СЧИТАЕМ, а не ждём проводки закрытия: в незакрытом месяце её нет,
        # и блок «Налоги заранее» показывал ноль вместо реальной оценки.
        async def vat_for(a, b):
            return (await db.execute(text("""
                SELECT coalesce(sum(amount) FILTER (WHERE account_kt LIKE '68.02%'), 0)
                     - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '68.02%'
                                                      AND account_kt NOT LIKE '51%'
                                                      AND account_kt NOT LIKE '68.90%'), 0)
                  FROM gl_entries
                 WHERE company_id = CAST(:cid AS uuid)
                   AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                        OR organization_id = CAST(:org AS uuid))
                   AND make_date(period_year, period_month, 1)
                       BETWEEN date_trunc('month', CAST(:a AS date))::date
                           AND CAST(:b AS date)"""),
                {**p, "a": a, "b": b})).scalar_one()

        vat = float(await vat_for(since, till) or 0)
        vat_was = float(await vat_for(prev_since, prev_till) or 0)
        _, profit = await _result_window(db, p, since, till)
        _, profit_was = await _result_window(db, p, prev_since, prev_till)
        rate = 0.25 if till.year >= 2025 else 0.20
        tax = max(profit, 0) * rate
        tax_was = max(profit_was, 0) * rate
        return {
            "metrics": [
                {"label": "НДС к уплате", "value": _money(vat),
                 "delta": _delta(vat, vat_was, higher_is_better=False)},
                {"label": "Налог на прибыль", "value": _money(tax),
                 "delta": _delta(tax, tax_was, higher_is_better=False)},
            ],
            "note": ("Оценка по данным учёта за период, до закрытия месяца. "
                     "Декларацию формирует бухгалтерия."),
        }

    if key == "books.result":
        rev, prof = await _result_window(db, p, since, till)
        rev_was, prof_was = await _result_window(db, p, prev_since, prev_till)
        rows = [{"title": r[0], "detail": "выручка " + _money(r[1]), "amount": _money(r[2])}
                for r in (await db.execute(text("""
            SELECT period_year || '-' || lpad(period_month::text, 2, '0'),
                   coalesce(sum(amount) FILTER (WHERE account_kt LIKE '90.01%'), 0)
                 - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '90.03%'), 0),
                   coalesce(sum(amount) FILTER (WHERE account_kt LIKE '90.01%'), 0)
                 - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '90.03%'), 0)
                 - coalesce(sum(amount) FILTER (WHERE account_dt LIKE '90.02%'
                                                  OR account_dt LIKE '90.07%'
                                                  OR account_dt LIKE '90.08%'), 0)
              FROM gl_entries
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
             GROUP BY 1 ORDER BY 1 DESC LIMIT 6"""), p)).all()]
        return {
            "metrics": [
                {"label": "Выручка за период", "value": _money(rev),
                 "delta": _delta(rev, rev_was)},
                {"label": "Прибыль за период", "value": _money(prof),
                 "delta": _delta(prof, prof_was)},
            ],
            "items": rows,
            "note": "Выручка без НДС и прибыль до налога: за период и по месяцам.",
        }

    if key == "books.settlements":
        # «Должны вам» — дебет 62 (долг покупателей), «Должны вы» — кредит 60 (долг
        # поставщикам). Складывать дебет обоих счетов нельзя: в дебет 60 попадают
        # АВАНСЫ, выданные поставщикам, а это не то, что вам должны. На пилоте так
        # набегало +150 550 ₽ дебиторки и +432 319 ₽ кредиторки против рабочего
        # экрана. Срез — последний: без max(as_of) вторая выгрузка удвоит суммы.
        dt, kt, adv_out, adv_in = (await db.execute(text("""
            SELECT coalesce(sum(debit) FILTER (WHERE account LIKE '62%'), 0),
                   coalesce(sum(credit) FILTER (WHERE account LIKE '60%'), 0),
                   coalesce(sum(debit) FILTER (WHERE account LIKE '60%'), 0),
                   coalesce(sum(credit) FILTER (WHERE account LIKE '62%'), 0)
              FROM gl_balances
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
               AND source <> 'monthly'
               AND as_of = (SELECT max(as_of) FROM gl_balances
                             WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly')
               AND (account LIKE '62%' OR account LIKE '60%')"""), p)).one()
        as_of = (await db.execute(text("""
            SELECT max(as_of)::text FROM gl_balances
             WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly'"""), p)).scalar()
        return {
            "metrics": [{"label": "Должны вам", "value": _money(dt)},
                        {"label": "Должны вы", "value": _money(kt)},
                        {"label": "Авансы выданы", "value": _money(adv_out)},
                        {"label": "Авансы получены", "value": _money(adv_in)}],
            "note": ("Долг покупателей и наш долг поставщикам на %s. Авансы показаны "
                     "отдельно: это не долг, а деньги вперёд." % _ru_date(as_of)),
        }

    if key == "books.calendar":
        # Раньше окно начиналось за 30 дней и обрезалось лимитом — в список
        # попадала только просрочка, и блок «Сроки» физически не мог показать
        # ближайший срок. Теперь: счётчик просроченного отдельно, список — впереди.
        soon = [{"title": r[1], "detail": _ru_date(r[0]) or "срок не задан", "amount": ""}
                for r in (await db.execute(text("""
            SELECT code, name FROM gl_references
             WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_calendar'
               AND coalesce(meta->>'В архиве', 'false') <> 'true'
               AND code >= to_char(CURRENT_DATE, 'YYYY-MM-DD')
             ORDER BY code LIMIT 8"""), p)).all()]
        overdue = (await db.execute(text("""
            SELECT count(*) FROM gl_references
             WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_calendar'
               AND coalesce(meta->>'В архиве', 'false') <> 'true'
               AND coalesce(meta->>'Статус', '') <> 'Сдано'
               AND code < to_char(CURRENT_DATE, 'YYYY-MM-DD')
               AND code >= to_char(CURRENT_DATE - 60, 'YYYY-MM-DD')"""), p)).scalar_one()
        debt = (await db.execute(text("""
            SELECT coalesce(sum(credit) - sum(debit), 0) FROM gl_balances
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid))
               AND source <> 'monthly'
               AND as_of = (SELECT max(as_of) FROM gl_balances
                             WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly')
               AND (account LIKE '68%' OR account LIKE '69%')"""), p)).scalar_one()
        return {
            "metrics": [{"label": "Долг перед бюджетом", "value": _money(debt)},
                        {"label": "Срок прошёл", "value": str(overdue),
                         "tone": "warning" if overdue else None}],
            "items": soon,
            "note": "Ближайшие сроки из вашей 1С — календарь бухгалтера.",
        }

    if key == "books.trends":
        items = [{"title": r[0], "detail": r[1] or "", "amount": ""}
                 for r in (await db.execute(text("""
            SELECT name, meta->>'Период' FROM gl_references
             WHERE company_id = CAST(:cid AS uuid)
               AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
                    OR organization_id = CAST(:org AS uuid)) AND kind = 'reports_filed'
             ORDER BY code DESC LIMIT 8"""), p)).all()]
        return {"items": items, "note": "Последняя сданная отчётность по данным 1С."}

    return {"note": "Блок не рассчитывается в этом пространстве."}


def _ru_date(v) -> str:
    """ISO-дата в привычный вид: наружу «15.08.2026», а не «2026-08-15»."""
    t = str(v or "")
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return "%s.%s.%s" % (t[8:10], t[5:7], t[:4])
    return t


def _money(v) -> str:
    """Сумма для витрины: без копеек и с пробелами — её читают глазами, а не сверяют."""
    try:
        return f"{float(v or 0):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


# ── Обратная связь с витрины: контур замыкается в то, что уже работает ──────
# Витрина не заводит свой канал обращений. У пространства уже есть задачи (там
# исполнитель, срок и статус), чаты (там скорость) и требования «Бухгалтерии» (там
# конкретный документ, которого ждут). Ещё один параллельный ящик означал бы, что
# ответ получателя лежит там, куда никто не смотрит.
#
# Поэтому с витрины уходит не «сообщение витрины», а:
#   · ответ по строке требования → в само требование (статус + лента обращений);
#   · вопрос или просьба → ЗАДАЧА (не потеряется) и, если задана комната, эхо в чат.


@router.post("/views/{view_id}/feedback")
async def pulse_view_feedback(
    view_id: str,
    payload: dict,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Обращение получателя с витрины: вопрос, просьба, замечание.

    Создаёт задачу от имени получателя — даже если «Задачи» ему не открыты: он не
    работает в трекере, он оставил обращение, и потерять его нельзя. Право
    проверяется по назначению витрины, а не по продукту.
    """
    cid = str(await assert_company_member(company_id, current_user, db))
    v = await _view_or_404(db, cid, view_id)

    mine = (await db.execute(text("""
        SELECT 1 FROM pulse_view_grants
         WHERE view_id = CAST(:v AS uuid) AND user_id = CAST(:u AS uuid)
        UNION ALL
        SELECT 1 FROM pulse_view_role_grants rg
          JOIN pulse_views pv ON pv.id = rg.view_id
          JOIN user_companies uc ON uc.role_id = rg.role_id
               AND uc.company_id = pv.company_id
         WHERE rg.view_id = CAST(:v AS uuid) AND uc.user_id = CAST(:u AS uuid)"""),
        {"v": str(v.id), "u": str(current_user.id)})).first() is not None
    is_admin = current_user.is_superadmin or await _is_company_admin(db, cid, current_user)
    if not is_admin and not (mine and v.status == "published"):
        raise HTTPException(status_code=404, detail="Витрина не найдена")

    text_ = (payload.get("text") or "").strip()
    if not text_:
        raise HTTPException(status_code=400, detail="Пустое обращение")
    block = (payload.get("blockTitle") or "").strip()

    made: dict[str, Any] = {"task": None, "chat": None}
    title = f"С витрины «{v.name}»" + (f": {block}" if block else "")

    if v.feedback_mode in ("task", "both"):
        # Автор — получатель, исполнитель — тот, кого назначили на витрине. Без
        # исполнителя задача попадёт в общий поток «Задач», а не потеряется.
        t = Task(
            company_id=uuid.UUID(cid), title=title[:300], description=text_,
            priority="medium", status="open",
            assignee_id=v.feedback_assignee_id, author_id=current_user.id)
        db.add(t)
        await db.flush()
        db.add(TaskEvent(task_id=t.id, kind="created", user_id=current_user.id,
                         note=f"обращение с витрины «{v.name}»"))
        made["task"] = {"id": str(t.id), "number": t.number}

    if v.feedback_mode in ("chat", "both") and v.feedback_room_id:
        # Эхо в чат — это скорость: задача не пискнет, а комната пискнет сразу.
        db.add(ChatMessage(
            room_id=v.feedback_room_id, user_id=current_user.id, type="text",
            content=f"{title}\n{text_}"))
        made["chat"] = {"roomId": str(v.feedback_room_id)}

    await db.commit()
    if not made["task"] and not made["chat"]:
        # Режим «none» или чат без комнаты: обращение некуда девать, и молчать об
        # этом нельзя — человек будет ждать ответа, которого никто не увидит.
        raise HTTPException(status_code=400,
                            detail="Для этой витрины не настроен канал обращений")
    return {"sent": True, **made}


@router.post("/views/{view_id}/reply")
async def pulse_view_reply(
    view_id: str,
    payload: dict,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ответ получателя по строке блока «Чего ждём от вас».

    Идёт в САМО требование: статус и лента обращений. Отдельная переписка о
    документе рядом с реестром документов означала бы два места, где нужно смотреть,
    и одно из них всегда забывают.

    Ответ получателя не закрывает требование: закрывает его появление документа в
    учёте. «Отправил» — это обещание, а не факт, и подменять им факт нельзя.
    """
    cid = str(await assert_company_member(company_id, current_user, db))
    v = await _view_or_404(db, cid, view_id)

    mine = (await db.execute(text("""
        SELECT 1 FROM pulse_view_grants
         WHERE view_id = CAST(:v AS uuid) AND user_id = CAST(:u AS uuid)
        UNION ALL
        SELECT 1 FROM pulse_view_role_grants rg
          JOIN pulse_views pv ON pv.id = rg.view_id
          JOIN user_companies uc ON uc.role_id = rg.role_id
               AND uc.company_id = pv.company_id
         WHERE rg.view_id = CAST(:v AS uuid) AND uc.user_id = CAST(:u AS uuid)"""),
        {"v": str(v.id), "u": str(current_user.id)})).first() is not None
    is_admin = current_user.is_superadmin or await _is_company_admin(db, cid, current_user)
    if not is_admin and not (mine and v.status == "published"):
        raise HTTPException(status_code=404, detail="Витрина не найдена")

    decision = (payload.get("decision") or "").strip()
    note = (payload.get("note") or "").strip()
    if decision not in ("sent", "will_send", "declined", "question"):
        raise HTTPException(status_code=400, detail="Неизвестный ответ")

    try:
        rid = uuid.UUID(str(payload.get("requestId") or ""))
    except ValueError:
        raise HTTPException(status_code=404, detail="Требование не найдено")

    row = (await db.execute(text("""
        SELECT id::text, status, coalesce(escalations, '[]'::jsonb), counterparty_name, doc_kind
          FROM doc_requests
         WHERE company_id = CAST(:cid AS uuid) AND id = CAST(:id AS uuid)"""),
        {"cid": cid, "id": str(rid)})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Требование не найдено")

    LABEL = {"sent": "документ отправлен", "will_send": "обещали прислать",
             "declined": "документа не будет", "question": "вопрос по требованию"}
    # «Отправил» и «пришлём» — это обещание: статус `promised`. Факт получения
    # ставит появление документа в учёте, а не слово на витрине.
    NEW_STATUS = {"sent": "promised", "will_send": "promised",
                  "declined": "disputed", "question": None}

    entry = {
        "at": datetime.now(timezone.utc).isoformat(), "by": current_user.email,
        "kind": "ответ с витрины", "decision": LABEL[decision], "note": note or None,
        "view": v.name,
    }
    new_status = NEW_STATUS[decision]
    await db.execute(text("""
        UPDATE doc_requests
           SET escalations = coalesce(escalations, '[]'::jsonb) || CAST(:e AS jsonb),
               status = coalesce(:st, status),
               updated_at = now()
         WHERE company_id = CAST(:cid AS uuid)
           AND id = CAST(:id AS uuid)"""),
        {"cid": cid, "id": str(rid), "st": new_status,
         "e": json.dumps([entry], ensure_ascii=False)})

    # Вопрос по требованию — это уже разговор, а не отметка: заводим задачу тем же
    # путём, что и обычное обращение с витрины.
    task = None
    if decision == "question" and v.feedback_mode in ("task", "both"):
        t = Task(company_id=uuid.UUID(cid),
                 title=f"Вопрос по документу: {row[3] or ''} · {row[4] or ''}"[:300],
                 description=note or "Вопрос с витрины", priority="medium", status="open",
                 assignee_id=v.feedback_assignee_id, author_id=current_user.id)
        db.add(t)
        await db.flush()
        db.add(TaskEvent(task_id=t.id, kind="created", user_id=current_user.id,
                         note=f"вопрос с витрины «{v.name}» по требованию"))
        task = {"id": str(t.id), "number": t.number}

    await db.commit()
    return {"ok": True, "status": new_status or row[1], "answer": LABEL[decision],
            "task": task}


# ── «Мои обращения»: обратный ход витрины ───────────────────────────────────
# Получатель написал — и до сих пор узнавал о судьбе обращения только устно. Блок
# показывает ему его же обращения: что он спросил, в какой стадии это сейчас и что
# ответили. Без него витрина односторонняя: мы просим документы, он пишет вопросы,
# и оба ждут ответа в тишине.
#
# Блок общий для любого профиля: обращения приходят с любой витрины.



async def _my_block(db: AsyncSession, cid: str, user: User, key: str) -> dict[str, Any]:
    """Личные блоки: разговоры, заявки, задачи.

    Каждый отвечает на один вопрос — «есть ли что-то, требующее меня», — и ведёт в
    своё приложение. Дублировать чат и трекер внутри витрины бессмысленно: там
    вложения, поиск, история и права, и второй такой же экран будет хуже первого.
    """
    if key == "my.chats":
        rows = (await db.execute(text("""
            SELECT r.name,
                   count(*) FILTER (WHERE m.created_at > coalesce(p.last_read_at,
                                                                  to_timestamp(0))) AS unread,
                   max(m.created_at) AS last_at
              FROM chat_participants p
              JOIN chat_rooms r ON r.id = p.room_id
              LEFT JOIN chat_messages m ON m.room_id = r.id
             WHERE p.user_id = CAST(:u AS uuid) AND r.company_id = CAST(:cid AS uuid)
             GROUP BY r.id, r.name
            HAVING count(*) FILTER (WHERE m.created_at > coalesce(p.last_read_at,
                                                                  to_timestamp(0))) > 0
             ORDER BY 3 DESC NULLS LAST LIMIT 8"""),
            {"cid": cid, "u": str(user.id)})).all()
        total = sum(int(r[1] or 0) for r in rows)
        return {
            "metrics": [{"label": "Непрочитанных", "value": str(total),
                         "tone": "warning" if total else None},
                        {"label": "Разговоров ждут", "value": str(len(rows))}],
            "items": [{"title": r[0] or "Разговор", "detail": "%d новых" % (r[1] or 0),
                       "amount": ""} for r in rows],
            "link": {"title": "Открыть чаты", "href": "/chat"},
            "note": "Ответить и посмотреть историю — в «Чатах».",
        }

    if key == "my.tickets":
        # Заявки живут в контуре Поддержки, и прав на его таблицы у нас может не
        # быть. Спрашиваем ПРАВО заранее, а не ловим падение: после ошибки внутри
        # транзакции сессия уже сломана, и откат в том же месте даёт MissingGreenlet.
        allowed = (await db.execute(text(
            "SELECT has_table_privilege(current_user, 'tickets', 'SELECT')"))).scalar()
        if not allowed:
            return {
                "link": {"title": "Открыть Поддержку", "href": "/tickets"},
                "note": "Заявки показывает «Поддержка» — откройте её, чтобы увидеть свои.",
            }
        rows = (await db.execute(text("""
            SELECT t.number, t.title, t.status, t.updated_at
              FROM tickets t
             WHERE t.company_id = CAST(:cid AS uuid)
               AND (t.customer_user_id = CAST(:u AS uuid)
                 OR t.current_assignee_id = CAST(:u AS uuid))
               AND coalesce(t.status, '') NOT IN ('closed', 'resolved', 'cancelled')
               AND NOT coalesce(t.is_deleted, false)
             ORDER BY t.updated_at DESC NULLS LAST LIMIT 8"""),
            {"cid": cid, "u": str(user.id)})).all()
        return {
            "metrics": [{"label": "Открытых заявок", "value": str(len(rows)),
                         "tone": "warning" if rows else None}],
            "items": [{"title": r[1] or "Заявка", "detail": "№%s · %s" % (r[0], r[2] or ""),
                       "amount": ""} for r in rows],
            "link": {"title": "Открыть Поддержку", "href": "/tickets"},
            "note": "Переписка по заявке и вложения — в «Поддержке».",
        }

    if key == "my.tasks":
        rows = (await db.execute(text("""
            SELECT t.number, t.title, t.status, t.due_at
              FROM tasks t
             WHERE t.company_id = CAST(:cid AS uuid)
               AND t.assignee_id = CAST(:u AS uuid)
               AND t.status NOT IN ('done', 'closed', 'cancelled')
             ORDER BY t.due_at NULLS LAST LIMIT 8"""),
            {"cid": cid, "u": str(user.id)})).all()
        overdue = sum(1 for r in rows if r[3] and r[3].date() < date.today())
        return {
            "metrics": [{"label": "Задач на мне", "value": str(len(rows))},
                        {"label": "Срок прошёл", "value": str(overdue),
                         "tone": "warning" if overdue else None}],
            "items": [{"title": r[1], "amount": "",
                       "detail": "№%s%s" % (r[0], " · до " + r[3].date().isoformat()
                                            if r[3] else "")} for r in rows],
            "link": {"title": "Открыть задачи", "href": "/tasks"},
            "note": "Работать с задачей — в «Задачах».",
        }

    return {"note": "Блок не рассчитывается."}


async def _feedback_block(db: AsyncSession, cid: str, user: User) -> dict[str, Any]:
    """Обращения этого получателя и что с ними стало."""
    rows = (await db.execute(text("""
        SELECT t.number, t.title, t.status, t.created_at,
               (SELECT e.note FROM task_events e
                 WHERE e.task_id = t.id AND e.kind = 'comment' AND e.note IS NOT NULL
                 ORDER BY e.created_at DESC LIMIT 1) AS answer,
               (SELECT max(e.created_at) FROM task_events e
                 WHERE e.task_id = t.id AND e.kind = 'comment') AS answered_at
          FROM tasks t
         WHERE t.company_id = CAST(:cid AS uuid) AND t.author_id = CAST(:u AS uuid)
           -- Скобки обязательны: без них AND связывает сильнее OR, и в ленту
           -- попали бы чужие задачи компании.
           AND (t.title LIKE 'С витрины%' OR t.title LIKE 'Вопрос по документу%')
         ORDER BY t.created_at DESC LIMIT 10"""),
        {"cid": cid, "u": str(user.id)})).all()

    STATUS = {"open": "в работе", "in_progress": "в работе",
              "done": "решено", "closed": "закрыто", "cancelled": "снято"}
    items = [{
        "title": r[1],
        "detail": ("№%s · %s" % (r[0], STATUS.get(r[2], r[2]))
                   + (" · ответ: " + (r[4] or "")[:90] if r[4] else "")),
        "amount": "",
    } for r in rows]

    waiting = sum(1 for r in rows if r[2] in ("open", "in_progress"))
    answered = sum(1 for r in rows if r[4])
    return {
        "metrics": [{"label": "Обращений", "value": str(len(rows))},
                    {"label": "В работе", "value": str(waiting),
                     "tone": "warning" if waiting else None},
                    {"label": "С ответом", "value": str(answered)}],
        "items": items,
        "note": ("Здесь видно, что стало с вашими вопросами. Ответ появляется, когда "
                 "его напишет ответственный."
                 if rows else "Вы пока ничего не спрашивали с этой витрины."),
    }


@router.get("/views/{view_id}/links")
async def pulse_view_links(
    view_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Ссылки на витрину: кому выдана, до какого числа, сколько раз открывали."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, str(cid), view_id)
    rows = (await db.execute(select(PulseViewLink).where(
        PulseViewLink.view_id == v.id).order_by(PulseViewLink.created_at.desc()))).scalars().all()
    now = datetime.now(timezone.utc)
    return {"links": [{
        "id": str(r.id), "token": r.token, "label": r.label,
        "expiresAt": r.expires_at.isoformat() if r.expires_at else None,
        "revoked": r.revoked,
        "expired": bool(r.expires_at and r.expires_at < now),
        "opened": r.opened_count,
        "lastOpenedAt": r.last_opened_at.isoformat() if r.last_opened_at else None,
        "url": f"/showcase/{r.token}",
    } for r in rows]}


@router.post("/views/{view_id}/links")
async def pulse_view_link_create(
    view_id: str,
    company_id: str = Query(...),
    label: str = "",
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Выдать ссылку. Срок обязателен: вечная ссылка на финансы — отложенная утечка."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, str(cid), view_id)
    if v.status != "published":
        raise HTTPException(status_code=400,
                            detail="Витрина не опубликована — показывать нечего")
    row = PulseViewLink(
        view_id=v.id, token=secrets.token_urlsafe(24), label=label.strip(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        created_by=current_user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "token": row.token, "url": f"/showcase/{row.token}",
            "expiresAt": row.expires_at.isoformat()}


@router.delete("/views/{view_id}/links/{link_id}")
async def pulse_view_link_revoke(
    view_id: str,
    link_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отозвать ссылку. Не удаляем: след того, что она была и сколько раз открыта."""
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, str(cid), view_id)
    try:
        uid = uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    row = (await db.execute(select(PulseViewLink).where(
        PulseViewLink.id == uid, PulseViewLink.view_id == v.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    row.revoked = True
    await db.commit()
    return {"revoked": True}


# Публичная ручка: без токена авторизации, доступ — по токену ссылки. Стоит
# отдельно и намеренно скупа: отдаёт витрину и ничего больше, ни списка витрин, ни
# компании, ни людей.
public_router = APIRouter(prefix="/showcase", tags=["Витрина по ссылке"])


@public_router.get("/{token}")
async def showcase_by_link(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Витрина по ссылке — только чтение и только опубликованная.

    Обращений и ответов по требованиям отсюда нет: писать может тот, кто вошёл под
    собой. Аноним с ссылкой смотрит, но не действует.
    """
    row = (await db.execute(select(PulseViewLink).where(
        PulseViewLink.token == token))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.revoked or (row.expires_at and row.expires_at < now):
        # Одинаковый ответ на «нет», «отозвана» и «истекла»: подсказывать, что
        # ссылка существовала, незачем.
        raise HTTPException(status_code=404, detail="Ссылка недействительна")

    v = (await db.execute(select(PulseView).where(
        PulseView.id == row.view_id))).scalar_one_or_none()
    if v is None or v.status != "published":
        raise HTTPException(status_code=404, detail="Ссылка недействительна")

    row.opened_count += 1
    row.last_opened_at = now
    await db.commit()

    cid = str(v.company_id)
    catalog = {k: t for k, t, _ in await _catalog(db, cid)}
    profile = (await db.execute(text(
        "SELECT profile_id FROM companies WHERE id = CAST(:cid AS uuid)"),
        {"cid": cid})).scalar_one_or_none()

    blocks = []
    for r in (await db.execute(text("""
        SELECT block_key, title, hint FROM pulse_view_blocks
         WHERE view_id = CAST(:v AS uuid) ORDER BY sort"""), {"v": str(v.id)})).all():
        key, title, hint = r
        if key == "view.feedback":
            # Личный блок: по ссылке неизвестно, кто смотрит, и показывать чужие
            # обращения нельзя.
            continue
        data = (await _office_block_data(db, cid, key, v.period,
                                         str(v.organization_id) if v.organization_id else None)
                if profile == "office"
                else {"note": "Блок этого профиля пока не считается для витрины."})
        blocks.append({
            "key": key, "title": title or catalog.get(key, key), "hint": hint,
            "metrics": data.get("metrics") or [], "items": data.get("items") or [],
            "note": data.get("note"),
        })

    return {
        "id": str(v.id), "name": v.name, "audience": v.audience,
        "owner": v.owner_name, "note": v.note, "status": v.status,
        "asOf": date.today().isoformat(), "period": v.period,
        "periodLabel": {"month": "за месяц", "quarter": "за квартал",
                        "year": "за год"}.get(v.period, v.period),
        "company": (await db.execute(text(
            "SELECT name FROM companies WHERE id = CAST(:cid AS uuid)"),
            {"cid": cid})).scalar_one_or_none(),
        "canWrite": False,
        "blocks": blocks,
    }
