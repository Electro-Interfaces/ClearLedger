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
import hashlib
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
    assert_company_item, assert_company_member, assert_company_product,
    get_current_user,
    resolve_member_modules,
)
import httpx

from app.services.support_scope import support_company_id
from app.services import space_projection, sso
from app.database import get_db
from app.services.tax_mode import tax_mode as space_tax_mode
from app.models import (
    ChatMessage, PulseAck, PulseView, PulseViewBlock, PulseViewGrant, PulseViewLink,
    Task, TaskEvent, User, UserCompany,
)
# Словарь стадий — общий с «Проектами»: «Проработка» не должна стать «dd»
# только потому, что экран другой.
from app.services import tax_regime
from app.services.ezs_changes import STAGE_LABELS

router = APIRouter(prefix="/pulse", tags=["Пульс"])
from app.routers.pulse_home import router as home_router
router.include_router(home_router)

# Пороги В1 — с большим запасом (решение МАГа 31.07.2026, PULSE.md §3):
# период адаптации система проходит тихо. Настройка в «Управлении» — волна В3.
# Правила экрана дня теперь принадлежат service owner; описание «всё здесь»
# выше — историческое. Reexports сохраняют общие identity для native consumers.
from app.services.pulse_day import (
    STALE_DAYS,
    OWN_SLA_DAYS,
    EXT_BACKLOG,
    SILENT_SHARE,
    SILENT_HOURS,
    CC_MISSED_FACTOR,
    CC_WRAPUP_STUCK,
    CC_REPEAT_TIMES,
    CC_REPEAT_PEOPLE,
    CC_DEFAULT_TARGETS,
    SALES_DROP,
    SALES_OUT_SHARE,
    SALES_OUT_MIN,
    SALES_VISIT_OK,
    PR_STUCK_DAYS,
    PR_STUCK_SHARE,
    PR_STUCK_MIN,
    PR_OWNER_SHARE,
    PR_OWNER_MIN,
    PR_MOVES_WEEKS,
    OPS_DOCS_OVERDUE,
    OPS_OPEN_MONTHS,
    OPS_COST_JUMP,
    OBJ_SILENT_DAYS,
    OBJ_DROP_PCT,
    OBJ_PAIN_MIN,
    OBJ_IDLE_COST_MIN,
    ST_ALIVE_DAYS,
    ST_SILENT_DAYS,
    ST_DROP_PCT,
    ST_DROP_FLOOR,
    ST_VISIT_OK,
    ST_VISIT_MIN,
    ST_AVAIL_PCT,
    ACCESS_ACTIONS,
    _TicketsZero,
    _tickets_available,
    _access_snapshot,
    CARD_SCOPE,
    KPI_SCOPE,
    PROFILE_SALES,
    DEFAULT_PROFILE,
    SOURCE_MIN_ROWS,
    _profile,
    _data_sources,
    _sources_snapshot,
    THRESHOLDS,
    DEFAULT_THRESHOLDS,
    _thresholds,
    MAX_CARDS,
    money,
    plural,
    build_cards,
    _kpi,
    _dpct,
    _cc_targets,
    _sales_snapshot,
    _OBJECTS_SQL_TPL,
    _objects_snapshot,
    _stations_snapshot,
    _stations_status,
    _ops_snapshot,
    _projects_snapshot,
    _cc_snapshot,
    _cc_measure,
    pulse_day_data,
    _MONTHS_RU,
    _books_anchor,
    _work_day_data,
    _office_day_data,
    _period_bounds,
    _result_window,
    _tax_mode,
    _ru_date,
)


# Контакт-центр. Окна тут считаются от now(), а не от as_of: телефония приезжает
# синхронизацией каждые 5 минут, и «вчера» здесь означает настоящее вчера.
# Цель по умолчанию, если в контакт-центре не задали свою (`cc_kpi_targets`).

# Продажи. Окна — от as_of (последняя загруженная сессия), а не от now(): данные
# сети приезжают файлами с отставанием, и «неделя» здесь означает неделю ДАННЫХ.

# Проекты (стройка сети). Портфель живёт месяцами, поэтому пороги — про
# застревание и бесхозность, а не про недельные колебания.

# Эксплуатация: хозяйство вокруг сети — энергия, аренда, услуги подрядчиков.
# Мера здесь не «неделя», а ПЕРИОД: месяц закрывается документами от контрагентов.

# Объект как ось. Единственное место в пространстве, где точка видна сразу во
# всех контурах: выручка, расходы, подтверждение документов. Признаки считаются
# по одному объекту, и в список попадает тот, у кого их сошлось несколько.

# Станции поштучно — «Первое окно» руководителя РусГидро (29.09.2026): сигналы
# по каждой ЭЗС, а не по сети в целом. Сетевые карточки выше отвечают «как мы
# продаём», эти — «сколько станций требуют разбора». Живой считается станция с
# сессиями за ST_ALIVE_DAYS: давно закрытые не должны раздувать счётчик молчания.
# Признаки словами: в выгрузке те же подписи, что на экране, иначе файл
# приходится расшифровывать по коду.
OBJ_FLAG_LABELS = {
    "idle_cost": "платим, не продаёт", "revenue_drop": "выручка провалилась",
    "docs_late": "документы просрочены", "silent": "молчит",
}


# Критичные действия журнала: те, что меняют состав людей и их права. Правки
# данных сюда не входят — это работа, а не риск.










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
    # Контакт-центр вблизи. Право отдельное от «Обращений»: там неделя
    # компании, здесь текущая минута одного человека и одной смены.
    ("business.myline", "Моя линия", "Бизнес"),
    ("business.shift", "Смена", "Бизнес"),
    ("business.objects", "Где болит", "Бизнес"),
    ("business.support", "Поддержка", "Бизнес"),
    ("business.summary", "Коротко", "Бизнес"),
    # Пункты «Бизнеса» бухгалтерского пространства: предмет другой, права такие же.
    ("business.money", "Деньги", "Бизнес"),
    ("business.accounting", "Учёт", "Бизнес"),
    ("business.taxes", "Налоги", "Бизнес"),
    ("business.requests", "Чего ждём", "Бизнес"),
    ("business.deadlines", "Сроки", "Бизнес"),
    ("business.tasks", "Задачи", "Бизнес"),
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


async def _sees_money(db: AsyncSession, cid: str, user: User) -> bool:
    """Показывать ли этому человеку выручку.

    Деньги сети — не «ещё один разрез», а отдельное право: контакт-центр работает в
    пространстве заказчика по договору и выручку видеть не должен (решение МАГа
    16.09.2026). Ключ один — пункт «Продажи»: он же гейтит карточки дня и KPI
    (`KPI_SCOPE`), и заводить для тех же цифр второй признак значило бы развести
    право и видимость.
    """
    visible = await _visible_items(db, cid, user)
    return visible is None or "business.sales" in visible


def _drop_money(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Убрать денежные строки разреза — для того, кто не видит выручку."""
    return [r for r in rows if r.get("unit") != "₽"]


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

# Молчание источника — сигнал только там, где поток регулярный: на паре записей
# «не приходят данные» означает, что контур ещё заводят, а не что он сломался.




# ── Источники данных: чему сегодня можно верить ───────────────────────────
#
# Реестр приёмников, а не реестр коннекторов: коннектор может числиться
# «активным», а данные не приезжать неделю. Правда — в самих таблицах, поэтому
# каждый источник описан запросом «когда последняя запись» и окном, после
# которого молчание становится подозрительным.
#
# `window` — сколько дней тишины ещё нормально. У телефонии это часы, у
# начислений — месяц: они и приходят раз в месяц.




# ── Пороги эскалаций: реестр, а не константы в тексте правил ───────────────
#
# Порог — это мнение о норме, и оно принадлежит компании, а не коду. Здесь
# только дефолты: фактическое значение приходит из `pulse_targets`, где его
# правит руководитель в «Управлении» (PULSE.md §3, волна В3). Ключ добавляется
# одной строкой — экран настройки рисуется по этому же реестру.





# Колпак экрана дня: больше семи карточек читаются как лента, а лента — это то,
# от чего «Пульс» уходит. Лишнее отсекается по уровню (PULSE.md §7).
# Excel делит строки только по CRLF; собираем его из кодов, чтобы литерал
# не разъезжался при переносе файла между окончаниями строк.
CRLF = chr(13) + chr(10)


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
    "st_attention": "Станции требуют разбора",
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

















# Объект сразу во всех контурах: выручка (сессии), расход (начисления по
# договорам) и подтверждение (документы). Ключ один — `service_locations.id`,
# на него ссылаются и сессии, и начисления. Заявки Поддержки живут в своём
# реестре (`public.service_objects`), и общего ключа с Ядром у них сейчас нет —
# поэтому в эту ось они не входят: сшивка по имени дала бы ложные пары.
















@router.get("/day")
async def pulse_day(
    company_id: str = Query(...),
    as_role: str | None = Query(None, description="смотреть глазами этой роли"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Экран дня: строка KPI по направлениям + карточки-эскалации (сводки)."""
    # Проверка доступа возвращает UUID компании — им и работаем: внутренние запросы
    # кастуют `:cid` в uuid, и переданный slug («rti») ронял весь экран пятисоткой
    # «invalid UUID». Остальные продукты пространства slug принимают, этот — нет.
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    visible = await _visible_items(db, str(cid), current_user, as_role)
    return await pulse_day_data(db, str(cid), visible)









async def _office_week_data(db: AsyncSession, cid: str) -> dict[str, Any]:
    """«Неделя» бухгалтерского пространства: что доехало, что разобрали, чего ждём.

    Тот же жанр, что у сети: семь дней против предыдущих семи. Предмет другой —
    документы из 1С, пакеты первички, требования к клиенту, задачи и письма.
    """
    def pair(table: str, ts: str = "created_at", extra: str = "") -> str:
        return f"""
            select count(*) filter (where {ts} >= now() - interval '7 days') as n,
                   count(*) filter (where {ts} >= now() - interval '14 days'
                                      and {ts} < now() - interval '7 days') as p
              from {table} where company_id = CAST(:cid AS uuid) {extra}"""

    rows: list[dict[str, Any]] = []
    for label, sql, better in (
        ("Документов доехало", pair("accounting_docs"), True),
        ("Проводок доехало", pair("gl_entries"), True),
        ("Пакетов первички", pair("intake_batches"), True),
        ("Требований выставлено", pair("doc_requests"), True),
        ("Требований закрыто", pair("doc_requests", "updated_at",
                                    "and status = 'closed'"), True),
        ("Периодов закрыто", pair("periods", "closed_at", "and status = 'closed'"), True),
        ("Задач поставлено", pair("tasks"), True),
        ("Задач закрыто", pair("tasks", "closed_at", "and closed_at is not null"), True),
        ("Писем получено", pair("mail_messages", "created_at", "and direction = 'in'"), True),
    ):
        try:
            r = (await db.execute(text(sql), {"cid": cid})).one()
        except Exception:  # noqa: BLE001 — таблицы может не быть в этом пространстве
            continue
        # Строку показываем и с нулём: исчезнувшая метрика читается как поломка,
        # а «0 против 0» — как честное «на этой неделе тихо».
        rows.append({"label": label, "value": r.n, "prev": r.p,
                     "unit": None, "higher_is_better": better})

    # Что именно сдвинулось: закрытые периоды и требования — с именами, а не числом.
    highlights = [{"at": r.at.isoformat() if r.at else None, "text": r.txt}
                  for r in (await db.execute(text("""
        select closed_at as at,
               'закрыт период ' || year || '-' || lpad(month::text, 2, '0') as txt
          from periods
         where company_id = CAST(:cid AS uuid) AND status = 'closed'
           and closed_at >= now() - interval '7 days'
        union all
        select updated_at,
               'документ получен: ' || coalesce(counterparty_name, '—')
               || ' · ' || coalesce(doc_kind, 'документ')
          from doc_requests
         where company_id = CAST(:cid AS uuid) AND status = 'closed'
           and updated_at >= now() - interval '7 days'
        order by 1 desc limit 10"""), {"cid": cid})).all()]

    as_of = (await db.execute(text("""
        SELECT max(as_of)::text FROM gl_balances
         WHERE company_id = CAST(:cid AS uuid) AND source <> 'monthly'"""),
        {"cid": cid})).scalar()
    return {"rows": rows, "highlights": highlights, "as_of": as_of}






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
    # Выжимка для куратора — это выручка сети и её тренд: свой пункт.
    cid = await assert_company_item(company_id, current_user, db, "pulse", "business.summary")
    cid = str(cid)

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
    # Выгрузка обязана повторять экран, включая закрытое: файл — обход показа,
    # если брать его отдельным путём. Деньги здесь режутся тем же правилом.
    деньги = await _sees_money(db, cid, current_user)
    rows: list[list[Any]] = []
    if view == "week":
        d = await pulse_week_data(db, cid)
        строки = d["rows"] if деньги else _drop_money(d["rows"])
        rows = [["Показатель", "За неделю", "Предыдущая", "Единица"]]
        rows += [[r["label"], r["value"], r["prev"] if r["prev"] is not None else "",
                  r["unit"] or ""] for r in строки]
        name = "pulse-week"
    elif view == "objects":
        # Разрез точек целиком про деньги: выручка, «под вопросом», начисления.
        await assert_company_item(company_id, current_user, db, "pulse", "business.objects")
        o = await _objects_snapshot(db, cid)
        rows = [["Точка", "Код", "Признаки", "Под вопросом, ₽", "Выручка недели, ₽",
                 "Было неделей раньше, ₽", "Ожидаем по договорам за 2 мес, ₽", "Без документа",
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
    from app.services.export_audit import log_export
    log_export(db, uuid.UUID(cid), current_user, f"«Пульс», разрез {view}: {max(len(rows) - 1, 0)} строк",
               rows=max(len(rows) - 1, 0))
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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    a = await _access_snapshot(db, str(cid))
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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    items = await _sources_snapshot(db, str(cid))
    # Каналы обмена — как их видит Учёт: имя, расписание, последний обмен.
    channels = [{"name": r.name, "status": r.status, "docs": r.docs_loaded or 0,
                 "last_sync": r.last_sync_at.isoformat() if r.last_sync_at else None}
                for r in (await db.execute(text("""
        select name, status, docs_loaded, last_sync_at from channels
        where company_id = :cid order by last_sync_at desc nulls last limit 12
    """), {"cid": str(cid)})).all()]
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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    th = await _thresholds(db, str(cid))
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
    # В разрезе выручка точек и «под вопросом, ₽» — гейт по своему пункту.
    cid = await assert_company_item(company_id, current_user, db, "pulse", "business.objects")
    s = await _objects_snapshot(db, str(cid))
    if not s:
        return {"available": False, "kpi": [], "pain": []}

    kpi = [
        _kpi("pain", "Точек с проблемами", s["pain_count"],
             note=f"из {s['total']} с движением", state="warn" if s["pain_count"] else None,
             higher_is_better=False),
        _kpi("idle", "Платим, но не продают", s["idle_cost_count"],
             note=f"ожидаем {money(s['idle_cost_amount'])} ₽ по договорам за два прошлых месяца",
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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(cid)
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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    cid = str(cid)
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
    # Весь экран — про деньги: гейт по своему пункту, а не по продукту.
    cid = await assert_company_item(company_id, current_user, db, "pulse", "business.sales")
    cid = str(cid)

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


# ── Контакт-центр вблизи: своя линия и своя смена ────────────────────────────
#
# «Обращения» отвечают руководителю компании и меряют неделю. Людям НА ЛИНИИ
# нужен другой горизонт — прямо сейчас: оператору «что на мне и успеваю ли я»,
# руководителю смены «кто сегодня работает и где затор». Считается всё по тем же
# таблицам Поддержки, что и «Обращения»: второго набора метрик контакт-центра не
# заводим (PULSE.md §6) — меняются горизонт и разрез, а не определения.


async def _cc_tables(db: AsyncSession) -> bool:
    """Есть ли контур контакт-центра в этой базе.

    У стека без Поддержки таблиц нет вовсе, а на новых может не оказаться гранта.
    И то, и другое гасит раздел, а не роняет «Пульс».
    """
    return bool((await db.execute(text(
        "select to_regclass('public.inbox_threads') is not null"
        "   and to_regclass('public.cc_staff') is not null"
    ))).scalar())


async def _cc_me(db: AsyncSession, email: str) -> Any:
    """Кто этот человек в Поддержке.

    Учётки Ядра и Поддержки — разные записи, и даже у одного человека id не
    совпадают; связывает их адрес почты — единый ключ входа в пространство.
    Нет записи — человек в контакт-центре не заведён, и показывать нечего.
    """
    return (await db.execute(text(
        "select id, name from public.users where lower(email) = lower(:email) limit 1"
    ), {"email": email})).one_or_none()


@router.get("/my-line")
async def pulse_my_line(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Моя линия» — рабочий день человека на линии его же глазами.

    Единственный экран «Пульса», который считает не по компании, а по тому, кто
    смотрит. Оператору цифры всей смены не помогают: он не отвечает за то,
    сколько звонков потеряла линия, он отвечает за свои разговоры. Отсюда набор:
    что на мне сейчас, что уже просрочено, как отработана неделя против нормы —
    и сколько людей ждёт в общей очереди, потому что это единственная общая
    цифра, на которую оператор влияет своими руками.

    Нормы берутся из целей самого контакт-центра (`cc_kpi_targets`), а не
    назначаются «Пульсом»: иначе экран ругался бы на то, что нормой не считают.
    """
    await assert_company_product(company_id, current_user, db, "pulse")
    if not await _cc_tables(db):
        return {"available": False, "reason": "no_support"}
    me = await _cc_me(db, current_user.email)
    if me is None:
        return {"available": False, "reason": "not_in_support"}

    targets = await _cc_targets(db)
    frt_target = targets["first_response_sec"]

    now = (await db.execute(text("""
        select count(*) as in_work,
               count(*) filter (where response_due_at < now()
                                  and first_response_at is null) as overdue
        from inbox_threads
        where assigned_to = :me and status <> 'closed'
    """), {"me": me.id})).one()

    # Очередь общая: обращения, которые ещё никто не взял. Она стоит рядом с
    # личными цифрами, потому что оператор влияет на неё прямо сейчас.
    queue = (await db.execute(text("""
        select count(*) as waiting, min(created_at) as oldest
        from inbox_threads
        where status <> 'closed' and assigned_to is null
    """))).one()

    week = (await db.execute(text("""
        select count(*) filter (where accepted_at >= now() - interval '7 days') as accepted,
               count(*) filter (where closed_at >= now() - interval '7 days') as closed,
               avg(extract(epoch from (first_response_at - created_at)))
                 filter (where first_response_at >= now() - interval '7 days') as frt,
               count(*) filter (where first_response_at >= now() - interval '7 days') as answered,
               count(*) filter (where first_response_at >= now() - interval '7 days'
                 and extract(epoch from (first_response_at - created_at)) <= :t) as in_sla
        from inbox_threads
        where assigned_to = :me or handled_by = :me
    """), {"me": me.id, "t": frt_target})).one()

    shift = (await db.execute(text("""
        select s.state, sh.started_at as shift_started_at,
               coalesce(st.max_concurrent, p.max_concurrent, 3) as max_concurrent
        from public.users u
        left join cc_agent_states s on s.user_id = u.id and s.ended_at is null
        left join cc_operator_shifts sh on sh.user_id = u.id and sh.status = 'active'
        left join cc_agent_profiles p on p.user_id = u.id
        left join cc_staff st on st.user_id = u.id
        where u.id = :me
    """), {"me": me.id})).one_or_none()

    mine = [{"id": str(r.id), "subject": r.subject, "channel": r.channel,
             "contact": r.contact_name or r.contact,
             "due_at": r.response_due_at.isoformat() if r.response_due_at else None,
             "answered": r.first_response_at is not None,
             "last_at": r.last_message_at.isoformat() if r.last_message_at else None}
            for r in (await db.execute(text("""
        select id, subject, channel, contact, contact_name, response_due_at,
               first_response_at, last_message_at
        from inbox_threads
        where assigned_to = :me and status <> 'closed'
        order by response_due_at nulls last, last_message_at desc
        limit 10
    """), {"me": me.id})).all()]

    # Мои смены: ближайшие по графику и последние отработанные. «Когда я
    # выхожу» и «как прошло вчера» — вопросы, за которыми оператор иначе идёт к
    # руководителю.
    plan = [{"starts_at": r.starts_at.isoformat(), "ends_at": r.ends_at.isoformat(),
             "duty": r.duty, "now": bool(r.now)}
            for r in (await db.execute(text("""
        select starts_at, ends_at, duty,
               (starts_at <= now() and ends_at > now()) as now
        from cc_shift_plan
        where user_id = :me and status = 'planned' and ends_at > now()
        order by starts_at limit 10
    """), {"me": me.id})).all()]

    shifts = [{"started_at": r.started_at.isoformat(),
               "ended_at": r.ended_at.isoformat() if r.ended_at else None,
               "minutes": int(r.minutes or 0), "closed": int(r.closed)}
              for r in (await db.execute(text("""
        select sh.started_at, sh.ended_at,
               extract(epoch from (coalesce(sh.ended_at, now()) - sh.started_at)) / 60 as minutes,
               (select count(*) from inbox_threads t
                 where t.handled_by = :me and t.closed_at >= sh.started_at
                   and t.closed_at <= coalesce(sh.ended_at, now())) as closed
        from cc_operator_shifts sh
        where sh.user_id = :me
        order by sh.started_at desc limit 5
    """), {"me": me.id})).all()]

    # Мои звонки: телефония уже связала разговор с человеком (`operator_user_id`),
    # поэтому лента личная, а не «все звонки компании с моим именем в тексте».
    calls = []
    if (await db.execute(text("select to_regclass('public.call_records')"))).scalar():
        calls = [{"at": r.started_at.isoformat() if r.started_at else None,
                  "phone": r.client_phone, "missed": bool(r.missed),
                  "wait": int(r.wait_sec or 0), "duration": int(r.duration_sec or 0)}
                 for r in (await db.execute(text("""
            select started_at, client_phone, missed, wait_sec, duration_sec
            from call_records
            where operator_user_id = :me
            order by started_at desc nulls last limit 15
        """), {"me": me.id})).all()]

    # Итог месяца рядом с недельным: одна неделя ничего не говорит о том, стало
    # лучше или хуже — а именно это человек и хочет увидеть в своей отчётности.
    month = (await db.execute(text("""
        select count(*) filter (where accepted_at >= now() - interval '30 days') as accepted,
               count(*) filter (where closed_at >= now() - interval '30 days') as closed,
               avg(extract(epoch from (first_response_at - created_at)))
                 filter (where first_response_at >= now() - interval '30 days') as frt,
               count(*) filter (where first_response_at >= now() - interval '30 days') as answered,
               count(*) filter (where first_response_at >= now() - interval '30 days'
                 and extract(epoch from (first_response_at - created_at)) <= :t) as in_sla
        from inbox_threads
        where assigned_to = :me or handled_by = :me
    """), {"me": me.id, "t": frt_target})).one()

    in_sla_share = (round(100.0 * week.in_sla / week.answered, 1)
                    if week.answered else None)
    max_concurrent = int(shift.max_concurrent) if shift else 3
    kpi = [
        _kpi("in_work", "На мне сейчас", int(now.in_work),
             note=f"предел {max_concurrent} одновременно", higher_is_better=False,
             state="warn" if now.in_work >= max_concurrent else None),
        _kpi("overdue", "Просрочен ответ", int(now.overdue), note="из тех, что на мне",
             higher_is_better=False, state="alert" if now.overdue else None),
        _kpi("closed", "Закрыто за неделю", int(week.closed), note="моих разговоров"),
        _kpi("frt", "Мой первый ответ, с",
             round(float(week.frt), 1) if week.frt is not None else None,
             note=f"норма ≤ {frt_target:.0f} с", higher_is_better=False,
             state=("warn" if week.frt is not None and week.frt > frt_target else None)),
        _kpi("in_sla", "В норме, %", in_sla_share,
             note=(f"из {int(week.answered)} отвеченных" if week.answered
                   else "отвечать было нечего")),
        _kpi("queue", "Ждут в очереди", int(queue.waiting), note="ничьи обращения",
             higher_is_better=False, state="warn" if queue.waiting else None),
    ]

    return {
        "available": True,
        "me": {"name": me.name},
        "shift": {
            "state": (shift.state if shift else None) or "offline",
            "on_shift": bool(shift and shift.shift_started_at),
            "since": (shift.shift_started_at.isoformat()
                      if shift and shift.shift_started_at else None),
        },
        "kpi": kpi,
        "threads": mine,
        "plan": plan,
        "shifts": shifts,
        "calls": calls,
        "accepted_week": int(week.accepted),
        "month": {
            "accepted": int(month.accepted), "closed": int(month.closed),
            "frt": round(float(month.frt), 1) if month.frt is not None else None,
            "in_sla_share": (round(100.0 * month.in_sla / month.answered, 1)
                             if month.answered else None),
            "answered": int(month.answered),
        },
        "queue_oldest": queue.oldest.isoformat() if queue.oldest else None,
        "targets": {"first_response_sec": frt_target},
    }


class LineAction(BaseModel):
    """Что человек делает со своей линией с телефона."""

    action: str
    state: str | None = None
    handover: bool = False
    note: str | None = None


@router.post("/my-line/action")
async def pulse_my_line_action(
    payload: LineAction,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Короткое действие линии: открыть смену, отойти, вернуться, взять следующее.

    «Пульс» — упрощённое представление рабочего места, а не второе рабочее место:
    с телефона нужны ровно эти движения, а разговор человек ведёт там, где для
    него всё есть. Поэтому Ядро ничего не решает само — оно пересказывает
    действие Поддержке, и правила (лимит одновременных, навыки, передача
    активных обращений при закрытии смены) остаются в одном месте.

    Действуем от имени того, кто нажал: адрес почты — единственный общий ключ
    человека в двух половинах пространства.
    """
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    visible = await _visible_items(db, str(cid), current_user)
    if visible is not None and "business.myline" not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Линия закрыта для этой роли")

    try:
        app_row, _link, _tok = await space_projection._target(db, cid, "support")
    except space_projection.ProjectionError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    # Свой скоуп: право проецировать справочники не должно означать право
    # открывать человеку смену и назначать на него обращения.
    token = sso.sign_service_token(aud="support", scope="desk")
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Единый вход не настроен — действовать за сотрудника нельзя")

    url = f"{space_projection._internal_base_url(app_row, 'support')}/api/v1/eco/cc/action"
    body = {"email": current_user.email, "action": payload.action,
            "state": payload.state, "handover": payload.handover, "note": payload.note}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Поддержка не отвечает: {e}")
    if resp.status_code >= 400:
        # Отказ приложения показываем как есть: «передайте активные обращения» и
        # «достигнут лимит» — это ответ человеку, а не наша внутренняя ошибка.
        detail = (resp.json().get("error") if resp.headers.get("content-type", "").startswith("application/json")
                  else resp.text)
        raise HTTPException(resp.status_code, detail or "Действие не выполнено")
    return resp.json()


@router.get("/shift")
async def pulse_shift(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """«Смена» — линия прямо сейчас глазами того, кто её ведёт.

    «Обращения» показывают неделю и отвечают на вопрос «как мы работаем».
    Руководителю смены нужен другой — «что происходит в эту минуту»: кто вышел,
    у кого очередь упёрлась в предел, сколько людей ждёт и давно ли. Состав
    берётся тот же, что ведётся в самой Поддержке (`cc_staff`): второго реестра
    людей контакт-центра здесь не заводим.

    Пункт проверяется отдельно от продукта: здесь поимённая нагрузка коллег, и
    оператору, которому «Смена» не открыта, её не должно отдавать и по адресу.
    """
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    visible = await _visible_items(db, str(cid), current_user)
    if visible is not None and "business.shift" not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Смена контакт-центра закрыта для этой роли")
    if not await _cc_tables(db):
        return {"available": False, "reason": "no_support"}

    # Человек в смене — это человек пространства: чтобы руководитель мог с ним
    # связаться прямо отсюда, нужны его учётка Ядра (для личного чата) и
    # телефон. Связывает половины адрес почты — общий ключ входа.
    agents = [{"id": str(r.id), "name": r.name, "duty": r.duty,
               "email": r.email,
               "core_user_id": str(r.core_user_id) if r.core_user_id else None,
               "phone": r.phone,
               "state": r.state or "offline",
               "on_shift": r.shift_started_at is not None,
               "since": r.shift_started_at.isoformat() if r.shift_started_at else None,
               "in_work": int(r.in_work), "max": int(r.max_concurrent),
               "overdue": int(r.overdue), "closed_today": int(r.closed_today),
               "planned": ({"starts_at": r.plan_starts.isoformat(),
                            "ends_at": r.plan_ends.isoformat(),
                            "now": bool(r.plan_now)} if r.plan_starts else None)}
              for r in (await db.execute(text("""
        select u.id, u.name, u.email, st.duty, s.state, sh.started_at as shift_started_at,
               cu.id as core_user_id,
               coalesce(cu.phone_mobile, cu.phone_office) as phone,
               coalesce(st.max_concurrent, p.max_concurrent, 3) as max_concurrent,
               (select count(*) from inbox_threads t
                 where t.assigned_to = u.id and t.status <> 'closed') as in_work,
               (select count(*) from inbox_threads t
                 where t.assigned_to = u.id and t.status <> 'closed'
                   and t.response_due_at < now() and t.first_response_at is null) as overdue,
               (select count(*) from inbox_threads t
                 where t.handled_by = u.id
                   and t.closed_at > now() - interval '24 hours') as closed_today,
               pl.starts_at as plan_starts, pl.ends_at as plan_ends,
               (pl.starts_at <= now() and pl.ends_at > now()) as plan_now
        from cc_staff st
        join public.users u on u.id = st.user_id
        left join core.users cu on lower(cu.email) = lower(u.email)
        left join cc_agent_states s on s.user_id = u.id and s.ended_at is null
        left join cc_operator_shifts sh on sh.user_id = u.id and sh.status = 'active'
        left join cc_agent_profiles p on p.user_id = u.id
        -- Смена по графику: идущая сейчас, иначе ближайшая впереди. Так строка
        -- отвечает и «кто на линии», и «кто следующий», одним запросом.
        left join lateral (
            select starts_at, ends_at from cc_shift_plan
             where user_id = u.id and status = 'planned' and ends_at > now()
             order by starts_at limit 1
        ) pl on true
        where st.active and coalesce(u.is_active, true)
        order by (sh.started_at is null), u.name
    """))).all()]

    # График на неделю вперёд: «кто когда выходит» — вопрос, на который иначе
    # отвечают перепиской. Отменённые смены не показываем: «не поставили» и
    # «сняли» руководитель различает в самом приложении.
    plan = [{"user": r.name, "duty": r.duty,
             "starts_at": r.starts_at.isoformat(), "ends_at": r.ends_at.isoformat(),
             "now": bool(r.now)}
            for r in (await db.execute(text("""
        select u.name, pl.duty, pl.starts_at, pl.ends_at,
               (pl.starts_at <= now() and pl.ends_at > now()) as now
        from cc_shift_plan pl
        join public.users u on u.id = pl.user_id
        where pl.status = 'planned'
          and pl.ends_at > now() and pl.starts_at < now() + interval '7 days'
        order by pl.starts_at
        limit 60
    """))).all()]

    # Лента звонков: убедиться, что линия дышит. Пятнадцать последних — это
    # «что сейчас происходит», а не отчёт: за отчётом идут в «Обращения».
    calls = []
    if (await db.execute(text("select to_regclass('public.call_records')"))).scalar():
        calls = [{"at": r.started_at.isoformat() if r.started_at else None,
                  "phone": r.client_phone, "missed": bool(r.missed),
                  "operator": r.operator, "wait": int(r.wait_sec or 0),
                  "duration": int(r.duration_sec or 0)}
                 for r in (await db.execute(text("""
            select started_at, client_phone, missed, operator, wait_sec, duration_sec
            from call_records
            where direction = 'inbound' or direction = 'in'
            order by started_at desc nulls last
            limit 15
        """))).all()]

    queue = (await db.execute(text("""
        select count(*) as waiting, min(created_at) as oldest,
               count(*) filter (where response_due_at < now()
                                  and first_response_at is null) as overdue
        from inbox_threads
        where status <> 'closed' and assigned_to is null
    """))).one()

    esc = 0
    if (await db.execute(text("select to_regclass('public.cc_escalations')"))).scalar():
        esc = (await db.execute(text(
            "select count(*) from cc_escalations where resolved_at is null"
        ))).scalar_one()

    on_line = sum(1 for a in agents if a["on_shift"])
    loaded = [a for a in agents if a["max"] and a["in_work"] >= a["max"]]
    kpi = [
        _kpi("on_line", "На линии", on_line, note=f"из {len(agents)} в составе",
             state="alert" if agents and not on_line else None),
        _kpi("queue", "Ждут в очереди", int(queue.waiting), note="никем не взяты",
             higher_is_better=False, state="warn" if queue.waiting else None),
        _kpi("queue_overdue", "Просрочен первый ответ", int(queue.overdue),
             note="в очереди", higher_is_better=False,
             state="alert" if queue.overdue else None),
        _kpi("loaded", "Перегружены", len(loaded), note="очередь упёрлась в предел",
             higher_is_better=False, state="warn" if loaded else None),
        _kpi("escalations", "Эскалации", int(esc),
             note="передано выше и не разобрано", higher_is_better=False,
             state="alert" if esc else None),
    ]

    return {"available": True, "kpi": kpi, "agents": agents,
            "plan": plan, "calls": calls,
            "queue_oldest": queue.oldest.isoformat() if queue.oldest else None}


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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    # Заявки лежат в схеме Поддержки, где company_id свой: без карты
    # соответствия компания видела бы чужие счётчики. Нет карты — считаем
    # по несуществующей компании, то есть ноль, а не всё подряд.
    support_cid = await support_company_id(db, cid) or "-"
    cid = str(cid)
    tickets_ok = await _tickets_available(db)
    # Без прав на заявки колонка считается нулями: остальная картина по
    # человеку (проекты, чаты, действия) от этого не страдает.
    tickets_block = """select count(*) filter (where tk.status not in ('closed','cancelled')
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
            where tk.company_id::text = :support_cid
              and coalesce(tk.is_deleted,false) = false
              and coalesce(tk.is_archived,false) = false
              and (au.id is not null or cu.id is not null)""" if tickets_ok else (
        "select 0 as open, 0 as breached, 0 as authored, 0 as closed_30d")

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
    } for r in (await db.execute(text(f"""
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
            {tickets_block}
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
    """), {"cid": cid, "support_cid": support_cid})).all()]

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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    # Заявки лежат в схеме Поддержки, где company_id свой: без карты
    # соответствия компания видела бы чужие счётчики. Нет карты — считаем
    # по несуществующей компании, то есть ноль, а не всё подряд.
    support_cid = await support_company_id(db, cid) or "-"
    cid, uid = str(cid), str(user_id)

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

    tickets = [] if not await _tickets_available(db) else [{
        "number": r.display_number or r.number, "title": r.title, "status": r.status,
        "breached": bool(r.sla_breached), "object": r.obj,
        "created": r.created_at.isoformat() if r.created_at else None,
    } for r in (await db.execute(text("""
        select tk.display_number, tk.number, tk.title, tk.status, tk.sla_breached,
               tk.created_at, so.name as obj
        from public.tickets tk
        join public.users au on au.id = coalesce(tk.current_assignee_id, tk.assigned_to)
        left join public.service_objects so on so.id = tk.service_object_id
        where tk.company_id::text = :support_cid
          and lower(au.email) = lower(:email)
          and tk.status not in ('closed','cancelled')
          and coalesce(tk.is_deleted,false)=false and coalesce(tk.is_archived,false)=false
        order by tk.sla_breached desc nulls last, tk.created_at
        limit 20
    """), {"support_cid": support_cid, "email": who.email})).all()]

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
    cid = await assert_company_product(company_id, current_user, db, "pulse")
    d = await pulse_week_data(db, str(cid))
    # Экран недели нужен и тем, кто выручку не видит: заявки, звонки, сроки — их
    # работа. Поэтому закрываем не экран, а денежные строки.
    if not await _sees_money(db, str(cid), current_user):
        d["rows"] = _drop_money(d["rows"])
    return d


async def pulse_week_data(db: AsyncSession, company_id: str) -> dict[str, Any]:
    """Данные «Недели» без проверки доступа — её делает вызывающий (и выгрузка)."""
    cid = str(company_id)
    # Заявки лежат в схеме Поддержки, где company_id свой: без карты
    # соответствия компания видела бы чужие счётчики. Нет карты — считаем
    # по несуществующей компании, то есть ноль, а не всё подряд.
    support_cid = await support_company_id(db, cid) or "-"

    # Бухгалтерское пространство меряет неделю не сессиями и стадиями проектов, а
    # тем, что доехало из 1С, что разобрали и чего дождались от клиента.
    if (await db.execute(text(
            "select profile_id from companies where id = :cid"),
            {"cid": cid})).scalar_one_or_none() == "office":
        return await _office_week_data(db, cid)

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

    # Заявки живут в контуре Поддержки: без прав на него экран показывает
    # остальное, а не падает целиком.
    t = _TicketsZero() if not await _tickets_available(db) else (await db.execute(text("""
        select count(*) filter (where created_at >= now() - interval '7 days') as created,
               count(*) filter (where closed_at >= now() - interval '7 days') as closed,
               count(*) filter (where created_at >= now() - interval '14 days'
                                and created_at < now() - interval '7 days') as created_prev,
               count(*) filter (where closed_at >= now() - interval '14 days'
                                and closed_at < now() - interval '7 days') as closed_prev
        from public.tickets
        where company_id::text = :support_cid
          and coalesce(is_deleted,false)=false and coalesce(is_archived,false)=false
    """), {"support_cid": support_cid})).one()
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
    # Каталог показывает ТОЛЬКО то, что в этом пространстве считается. Предлагать
    # блок, который вернёт «не считается», значит обманывать того, кто собирает
    # витрину: он узнает об этом от получателя.
    base = OFFICE_BLOCKS if profile == "office" else NET_BLOCKS
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
               (SELECT count(*) FROM pulse_view_grants g WHERE g.view_id = v.id) AS people,
               (SELECT count(*) FROM pulse_view_role_grants rg WHERE rg.view_id = v.id) AS roles
          FROM pulse_views v
         WHERE v.company_id = CAST(:cid AS uuid)
         ORDER BY v.status, v.name"""), {"cid": cid})).all()

    return {
        "views": [{
            "id": r[0], "name": r[1], "audience": r[2], "period": r[3],
            "owner": r[4], "note": r[5], "status": r[6],
            "updatedAt": r[7].isoformat() if r[7] else None,
            "blocks": r[8], "people": r[9], "roles": r[10],
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
            # Обращение без адресата ложится задачей в общий поток и никому не
            # «горит» — на пилоте так потерялись два вопроса клиента.
            if v.feedback_mode in ("task", "both") and not v.feedback_assignee_id:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите, кому уходят обращения, — иначе они лягут без адресата")
            if v.feedback_mode in ("chat", "both") and not v.feedback_room_id:
                raise HTTPException(status_code=400,
                                    detail="Для канала «чат» нужна комната")
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


@router.delete("/views/{view_id}")
async def pulse_view_delete(
    view_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Удалить витрину вместе с составом, назначениями и ссылками.

    Опубликованную удалять нельзя: у кого-то она сейчас открыта, и исчезновение
    без предупреждения читается как поломка. Сначала снять с показа — это отдельное
    решение, которое видно в журнале.
    """
    cid = await assert_company_admin_product(company_id, current_user, db)
    v = await _view_or_404(db, str(cid), view_id)
    if v.status == "published":
        raise HTTPException(status_code=400,
                            detail="Сначала снимите витрину с показа")
    await db.delete(v)      # состав, гранты и ссылки уходят каскадом
    await db.commit()
    return {"deleted": True}


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
            data = await _net_block_data(db, cid, key, _profile_of_row(profile))
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


@router.get("/blocks")
async def pulse_blocks(
    company_id: str = Query(...),
    keys: str = Query(..., description="ключи блоков через запятую"),
    period: str = Query("month"),
    organization_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Готовые блоки — те же, что уходят в витрину, но для экранов «Пульса».

    Каталог «Бизнеса» собран под сети (продажи ЭЗС, эксплуатация, объекты), и в
    бухгалтерском пространстве все его пункты пусты: данных такого рода там нет
    вовсе. Считать для офиса ВТОРОЙ набор метрик нельзя — разошедшиеся цифры
    внутри одного пространства хуже отсутствующих, поэтому экраны берут ровно то,
    что уже посчитано для витрины по ручкам «Бухгалтерии».
    """
    cid = str(await assert_company_product(company_id, current_user, db, "pulse"))
    profile = (await db.execute(text(
        "SELECT profile_id FROM companies WHERE id = CAST(:cid AS uuid)"),
        {"cid": cid})).scalar_one_or_none()
    catalog = {k: t for k, t, _ in await _catalog(db, cid)}

    blocks = []
    for key in [k.strip() for k in keys.split(",") if k.strip()][:12]:
        if key == "view.feedback":
            data = await _feedback_block(db, cid, current_user)
        elif key.startswith("my."):
            data = await _my_block(db, cid, current_user, key)
        elif profile == "office":
            data = await _office_block_data(db, cid, key, period, organization_id)
        else:
            data = await _net_block_data(db, cid, key, _profile_of_row(profile))
        blocks.append({
            "key": key, "title": catalog.get(key, key), "hint": None,
            "metrics": data.get("metrics") or [], "items": data.get("items") or [],
            "note": data.get("note"), "link": data.get("link"),
        })
    return {"blocks": blocks, "asOf": date.today().isoformat()}


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

# Блоки витрины для сетей. Имена — словами получателя: владельцу сети «Продажи»
# понятнее как «Отпуск и выручка», а «Где болит» — как «Проблемные точки».
NET_BLOCKS: list[tuple[str, str, str]] = [
    ("net.sales", "Отпуск и выручка", "Сеть"),
    ("net.objects", "Проблемные точки", "Сеть"),
    ("net.ops", "Эксплуатация", "Сеть"),
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
    # Окно — от последнего месяца с данными, а не от календарного: см. `_books_anchor`.
    since, till, prev_since, prev_till = _period_bounds(period, await _books_anchor(db, cid))

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
        mode = await _tax_mode(db, p)

        # Ставку 25 % применяем только к настоящему налогу на прибыль. У предпринимателя
        # её нет ни на общем режиме (там НДФЛ), ни тем более на УСН и патенте.
        if mode["osno"] or not (mode["usn"] or mode["patent"] or mode.get("osnoIp")):
            # ОСНО: налог СЧИТАЕМ, а не ждём проводки закрытия — в незакрытом месяце
            # её нет, и блок показывал бы ноль вместо реальной оценки.
            _, profit = await _result_window(db, p, since, till)
            _, profit_was = await _result_window(db, p, prev_since, prev_till)
            # Ставка из справочника на дату периода: в 2025-м она выросла с 20 до
            # 25 %, и зашитый процент пересчитал бы задним числом прошлые годы.
            rate = float((await db.execute(text("""
                SELECT value FROM tax_regime_rates
                 WHERE regime_code = 'osno' AND kind = 'rate'
                   AND valid_from <= CAST(:on AS date)
                   AND (valid_to IS NULL OR valid_to >= CAST(:on AS date))
                 ORDER BY valid_from DESC LIMIT 1"""),
                {"on": till})).scalar() or 25) / 100
            tax, tax_was = max(profit, 0) * rate, max(profit_was, 0) * rate
            tax_label = "Налог на прибыль"
            note = ("Оценка по данным учёта за период, до закрытия месяца. "
                    "Декларацию формирует бухгалтерия.")
        else:
            # УСН и патент: считать 25 % от прибыли здесь нельзя — база другая (доход
            # либо доход минус расходы, у патента вменённая). Берём НАЧИСЛЕННОЕ по
            # 68.12 и 68.45: это факт учёта, а не наша модель чужого режима.
            async def income_tax_for(a, b):
                # 68.10 здесь ради предпринимателя на общем режиме: его налог с дохода
                # живёт там, и без этого счёта блок показал бы ему ноль.
                return (await db.execute(text("""
                    SELECT coalesce(sum(amount) FILTER (
                             WHERE account_kt LIKE '68.12%' OR account_kt LIKE '68.45%'
                                OR account_kt LIKE '68.10%'), 0)
                         - coalesce(sum(amount) FILTER (
                             WHERE (account_dt LIKE '68.12%' OR account_dt LIKE '68.45%'
                                 OR account_dt LIKE '68.10%')
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

            tax = float(await income_tax_for(since, till) or 0)
            tax_was = float(await income_tax_for(prev_since, prev_till) or 0)

            # Расчёт по базе режима рядом с начисленным: расхождение на закрытом
            # периоде — повод посмотреть декларацию, а не молча поверить одной из
            # двух цифр (сверка 16.08.2026, docs/TAXES.md §11).
            gap_note = ""
            if p.get("org"):
                est = await tax_regime.estimate_tax(
                    db, p["cid"], p["org"], since, till,
                    income=0.0, expense=0.0, vat_accrued=0.0)
                calc = next((l["amount"] for l in est.get("lines", [])
                             if l["key"] in ("usn", "psn")), None)
                if calc is not None and abs(calc - tax) > max(1000, tax * 0.05):
                    gap_note = (" По базе периода выходит %s — разница с начисленным "
                                "%s." % (_money(calc), _money(abs(calc - tax))))
            tax_label = ("НДФЛ предпринимателя" if mode.get("osnoIp") and not mode["usn"]
                         else "Налог по патенту" if mode["patent"] and not mode["usn"]
                         else "Налог УСН с оборота" if mode.get("usnRevenueBased")
                         else "Налог УСН с разницы" if mode.get("usnObject")
                         else "Налог по УСН")
            note = ("Режим: %s. Начислено по учёту за период — авансовый платёж "
                    "приходится не на каждый месяц. Декларацию формирует бухгалтерия."
                    % mode["label"]) + gap_note

        # Плитку НДС не убираем: исчезнувшая строка читается как поломка экрана.
        # Вместо этого прямо сказано, почему на этом режиме там ноль.
        vat_metric = {"label": "НДС к уплате", "value": _money(vat),
                      "delta": _delta(vat, vat_was, higher_is_better=False)}
        if not mode["vat"]:
            vat_metric["hint"] = "на этом режиме НДС не начисляется"
        return {
            "metrics": [
                vat_metric,
                {"label": tax_label, "value": _money(tax),
                 "delta": _delta(tax, tax_was, higher_is_better=False)},
            ],
            "note": note,
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
            "note": ("Выручка без НДС и прибыль до налога за %s (последний период с "
                     "данными учёта) и по месяцам." % (
                         _MONTHS_RU[till.month - 1] + " " + str(till.year))),
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
            -- Справочники 1С (`gl_references`) оси юрлица не имеют: они общие для
            -- компании. Фильтр по организации здесь ронял блок целиком — «column
            -- organization_id does not exist», и в витрине заказчика тоже.
            SELECT name, meta->>'Период' FROM gl_references
             WHERE company_id = CAST(:cid AS uuid) AND kind = 'reports_filed'
             ORDER BY code DESC LIMIT 8"""), {"cid": p["cid"]})).all()]
        return {"items": items, "note": "Последняя сданная отчётность по данным 1С."}

    return {"note": "Блок не рассчитывается в этом пространстве."}




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
        # Тип обязателен по делу, а не по схеме: доска «Задач» строится ПО ТИПУ, и
        # задача без него не попадает ни в одну колонку — в сводке она числится
        # «без типа» и выпадает из работы. Берём «Поручение», если оно заведено:
        # обращение с витрины — именно разовая работа с исполнителем и сроком.
        type_id = (await db.execute(text(
            "SELECT id FROM task_types WHERE company_id = CAST(:cid AS uuid)"
            " AND code = 'errand' LIMIT 1"), {"cid": cid})).scalar_one_or_none()
        t = Task(
            company_id=uuid.UUID(cid), title=title[:300], description=text_,
            priority="medium", status="open", type_id=type_id,
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





def _profile_of_row(profile: str | None) -> str:
    """Профиль пространства → профиль расчёта продаж (fuel/energy)."""
    return profile if profile in PROFILE_SALES else DEFAULT_PROFILE


async def _net_block_data(db: AsyncSession, cid: str, key: str,
                          profile: str) -> dict[str, Any]:
    """Блоки витрины для сети: те же снимки, что у рабочих экранов «Пульса»."""
    if key == "net.sales":
        snap = await _sales_snapshot(db, cid, None, profile)
        if not snap:
            return {"note": "Данных о продажах за период нет."}
        unit = PROFILE_SALES.get(profile, PROFILE_SALES[DEFAULT_PROFILE])
        return {
            "metrics": [
                {"label": "Выручка", "value": _money(snap.get("revenue")),
                 "delta": _delta(float(snap.get("revenue") or 0),
                                 float(snap.get("revenue_prev") or 0))},
                {"label": unit[4], "value": f"{float(snap.get('kwh') or 0):,.0f}".replace(",", " "),
                 "delta": _delta(float(snap.get("kwh") or 0),
                                 float(snap.get("kwh_prev") or 0))},
                {"label": unit[6], "value": str(snap.get("sessions") or 0),
                 "delta": _delta(float(snap.get("sessions") or 0),
                                 float(snap.get("sessions_prev") or 0))},
                {"label": "Точки в работе", "value": str(snap.get("live") or 0),
                 "delta": _delta(float(snap.get("live") or 0),
                                 float(snap.get("live_prev") or 0))},
            ],
            "note": "Отпуск и выручка сети за период — те же цифры, что на экране дня.",
        }

    if key == "net.objects":
        snap = await _objects_snapshot(db, cid)
        pain = snap.get("pain") or []
        return {
            "metrics": [
                {"label": "Точек в сети", "value": str(snap.get("total") or 0)},
                {"label": "Требуют внимания", "value": str(snap.get("pain_count") or 0),
                 "tone": "warning" if snap.get("pain_count") else None},
                {"label": "Платим, но не продают", "value": str(snap.get("idle_cost_count") or 0),
                 "tone": "warning" if snap.get("idle_cost_count") else None},
                {"label": "На сумму", "value": _money(snap.get("idle_cost_amount"))},
            ],
            "items": [{"title": p.get("name") or p.get("code") or "Точка",
                       "detail": p.get("why") or "", "amount": ""} for p in pain[:8]],
            "note": "Точки, где сошлось несколько проблем сразу.",
            "link": {"title": "Открыть «Пульс»", "href": "/pulse/business?view=objects"},
        }

    if key == "net.ops":
        snap = await _ops_snapshot(db, cid)
        return {
            "metrics": [
                {"label": "Период", "value": str(snap.get("period") or "—")},
                {"label": "Договоров", "value": str(snap.get("contracts_total") or 0)},
                {"label": "Со сроком", "value": str(snap.get("contracts_with_term") or 0)},
                {"label": "Срок истёк", "value": str(snap.get("contracts_expired") or 0),
                 "tone": "warning" if snap.get("contracts_expired") else None},
            ],
            "note": "Состояние эксплуатации и договоров сети.",
            "link": {"title": "Открыть «Пульс»", "href": "/pulse/business?view=ops"},
        }

    return {"note": "Блок не рассчитывается."}


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
        total_tasks = (await db.execute(text("""
            SELECT count(*) FROM tasks
             WHERE company_id = CAST(:cid AS uuid) AND assignee_id = CAST(:u AS uuid)
               AND status NOT IN ('done', 'closed', 'cancelled')"""),
            {"cid": cid, "u": str(user.id)})).scalar_one()
        return {
            "metrics": [{"label": "Задач на мне", "value": str(total_tasks)},
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
               -- Ответом считается комментарий НЕ автора: иначе человек видит
               -- собственный текст как ответ на свой же вопрос.
               (SELECT e.note FROM task_events e
                 WHERE e.task_id = t.id AND e.kind = 'comment' AND e.note IS NOT NULL
                   AND e.user_id IS DISTINCT FROM t.author_id
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
        "id": str(r.id), "token": r.token[:6] + "…", "label": r.label,
        "expiresAt": r.expires_at.isoformat() if r.expires_at else None,
        "revoked": r.revoked,
        "expired": bool(r.expires_at and r.expires_at < now),
        "opened": r.opened_count,
        "lastOpenedAt": r.last_opened_at.isoformat() if r.last_opened_at else None,
        # Хеш ссылку не восстанавливает: адрес виден только при выдаче.
        "url": None if len(r.token) == 64 else f"/showcase/{r.token}",
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
    raw = secrets.token_urlsafe(24)
    row = PulseViewLink(
        view_id=v.id, token=hashlib.sha256(raw.encode()).hexdigest(), label=label.strip(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        created_by=current_user.email)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "token": raw, "url": f"/showcase/{raw}",
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
        PulseViewLink.token == hashlib.sha256(token.encode()).hexdigest()))).scalar_one_or_none()
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
                else await _net_block_data(db, cid, key, _profile_of_row(profile)))
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
