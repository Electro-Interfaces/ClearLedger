"""Мост «проект ↔ кейс»: ход проекта ведёт Координатор, данные остаются в Ядре.

ЗАЧЕМ. Регламенты заказчика описывают не только ЧТО заполнить (это у нас есть — 55 граф
банка ЗУ и чек-лист из 55 задач), но и КАК движется работа: кнопка у роли, три исхода
согласования, уведомление по событию, приёмка двумя службами, просрочка этапа. Писать
второй движок процессов внутри Учёта незачем — он уже работает в Координаторе, вместе
с редактором маршрута, журналом фактов, надёжной доставкой и эскалациями.

РАЗДЕЛЕНИЕ МАСТЕРСТВА. Учёт — мастер ДАННЫХ проекта (поля, документы, оборудование,
экономика, капвложения по ФСБУ 26/2020). Координатор — мастер ХОДА: где стоим, чья
кнопка, что просрочено, кому ушло уведомление. Данные проекта в кейс не копируем —
только сводку, от которой зависят условия рёбер маршрута.

Транспорт тот же, что у проекции пространства (`space_projection`): служебный токен
RS256 Ядра и внутренний адрес приложения. Отдельного секрета мост не заводит.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite, EzsSiteParticipant, User
from app.services.ezs_changes import make_change
from app.services.space_projection import (
    DEFAULT_TIMEOUT,
    ProjectionError,
    _error_text,
    _internal_base_url,
    _target,
)

APP_CODE = "support"

# Фасад процессов — общий вход в движок маршрутов. Проектные ручки `/eco/projects/*`
# ещё живы для совместимости, но Ядро ходит сюда: пока ходило туда, фаза 2 оставалась
# витриной, а мост нельзя было отключить в принципе.
FACADE = "/api/v1/process"
SUBJECT_TYPE = "ezs_site"
PROCESS_DEFINITION = "ezs_work"


def _from_facade(card: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Ответ фасада в словах карточки проекта.

    Фасад говорит о процессе — `processId`, `currentStep`, `steps`; карточка проекта
    говорит о ходе работы — `stage`, `stages`, `path`. Приводим в одном месте: менять
    словарь во фронте значило бы переучивать людей ради внутреннего переезда, а
    отдавать наружу два разных словаря — плодить третью правду.
    """
    return {
        "ok": True,
        "exists": True,
        "caseId": card.get("processId"),
        "stage": card.get("currentStep"),
        "stages": card.get("steps"),
        "links": card.get("transitions"),
        "path": card.get("history"),
        "actions": card.get("availableActions"),
        "fields": card.get("fields"),
        "values": card.get("values"),
        "milestones": card.get("milestones"),
        "participants": card.get("participants"),
        "branches": card.get("branches"),
        "readonly": card.get("readonly"),
        "readonlyReason": card.get("readonlyReason"),
        "stageEnteredAt": card.get("stepEnteredAt"),
        "daysInStage": card.get("daysInStep"),
        **{key: card[key] for key in ("created", "participantsUnknown", "undone")
           if key in card},
        **extra,
    }


async def _instance_id(db: AsyncSession, company_id, site: EzsSite) -> tuple[str | None, dict]:
    """Процесс предмета и — если его ещё нет — сам маршрут.

    Возвращает пару: идентификатор процесса и предпросмотр графа. Пустой процесс не
    ошибка: работа по проекту может быть ещё не начата, а путь показать уже нужно.
    """
    data = await _call(db, company_id, "GET", f"{FACADE}/instances", params={
        "subjectType": SUBJECT_TYPE,
        "subjectId": str(site.id),
        "definition": PROCESS_DEFINITION,
    })
    items = data.get("instances") or []
    return (items[0].get("processId") if items else None), (data.get("definitionPreview") or {})

# Стадии кейса, при входе в которые проект считается введённым в эксплуатацию.
# Это узел 21 блок-схемы («автоматическое обновление статуса на "Введена в
# эксплуатацию"»): решение принимает маршрут, но запись о вводе — наша, потому что
# дата ввода это основание перевода капвложений со счёта 08 на 01.
COMMISSIONED_STAGES = {"ezs_commissioning", "ezs_oco_final", "ezs_done"}


def _context(site: EzsSite) -> dict[str, Any]:
    """Сводка проекта для условий маршрута. Не копия карточки — только то, что решает.

    `project_kind` — ось развилки на входе: новое строительство уходит на согласование
    земли, перенос и модернизация — сразу в планирование работ.
    """
    return {
        "project_kind": site.kind or "new_build",
        "eco_stage": site.stage,
        "eco_project_no": site.project_no or "",
        "eco_region": site.region_norm or site.region or "",
        "eco_address": site.full_address or site.address or "",
    }


async def _call(db: AsyncSession, company_id, method: str, path: str,
                *, json: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
    app_row, link, token = await _target(db, company_id, APP_CODE)
    url = f"{_internal_base_url(app_row, APP_CODE)}{path}"
    body = dict(json or {})
    body["companyId"] = link.external_company_id
    query = dict(params or {})
    query["companyId"] = link.external_company_id

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=query,
                                        headers={"Authorization": f"Bearer {token}"})
            else:
                resp = await client.post(url, json=body,
                                         headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProjectionError(f"Координатор недоступен: {e}") from e

    if resp.status_code >= 400:
        data: dict[str, Any] = {}
        try:
            data = resp.json()
        except Exception:
            pass
        # Код ошибки движка несём наружу как есть: карточка покажет под кнопкой,
        # чего именно не хватает, вместо пустого места (STAGE_REQUIREMENTS_UNMET,
        # STAGE_ROLE_DENIED, STAGE_CHANGED).
        raise ProjectionError(
            data.get("error") or f"Координатор вернул ошибку (HTTP {resp.status_code}): "
                                 f"{_error_text(resp)}")
    return resp.json()


# Публичное имя того же вызова: к фасаду процессов ходит не только проектный
# мост, но и возврат исхода круга виз. Прятать общий транспорт под подчёркиванием
# и звать его из соседнего сервиса — хуже, чем назвать его вслух.
call_process = _call


async def _participants(db: AsyncSession, site: EzsSite) -> list[dict[str, Any]]:
    """Состав проекта для кейса: человек + служба регламента.

    Ключ сопоставления — email: тем же ключом людей пространства завела проекция
    (`/eco/users/sync`). Внутренний id Ядра шлём справочно, связь по нему не строим.
    """
    rows = (await db.execute(
        select(EzsSiteParticipant, User)
        .join(User, User.id == EzsSiteParticipant.user_id)
        .where(EzsSiteParticipant.site_id == site.id)
    )).all()
    return [{"email": u.email, "roleCode": p.role_code, "ecoUserId": str(u.id)}
            for p, u in rows]


async def sync_case(db: AsyncSession, company_id, site: EzsSite,
                    user: User | None = None) -> dict[str, Any]:
    """Завести кейс проекта либо обновить его сводку и состав. Повтор безопасен.

    Одна операция на два действия сознательно: контекст уезжает при каждом значимом
    изменении проекта, и отдельная «создать» плодила бы гонку «кейс уже есть или нет».
    """
    related = ([{"type": "service_object", "id": str(site.location_id)}]
               if site.location_id else [])
    card = await _call(db, company_id, "POST", f"{FACADE}/instances", json={
        "definition": PROCESS_DEFINITION,
        "subject": {"type": SUBJECT_TYPE, "id": str(site.id)},
        "title": site.title or site.project_no or f"Проект ЭЗС {site.id}",
        "actorEmail": getattr(user, "email", None),
        "context": _context(site),
        "related": related,
        "participants": await _participants(db, site),
    })
    return _from_facade(card)


async def case_state(db: AsyncSession, company_id, site: EzsSite,
                     user: User | None = None) -> dict[str, Any]:
    """Ход проекта для вкладки «Работа»: стадия, кнопки, вехи, сколько стоим.

    Действия считаются ОТ ИМЕНИ человека: кнопку ОКС менеджеру отдела развития
    показывать незачем. Кейса ещё нет — это не ошибка, а «работа не начата».

    **Чтение ничего не пишет.** Раньше здесь же досводился ввод в эксплуатацию,
    и это оказалось худшим из решений: дата ввода — основание перевода капвложений
    08 → 01 — проставлялась фактом открытия карточки, датой чужого просмотра и под
    правами любого члена компании. Теперь расхождение только НАЗЫВАЕТСЯ
    (`needsReconcile`), а устраняет его явная операция `reconcile` — руками или
    фоновым проходом.
    """
    process_id, preview = await _instance_id(db, company_id, site)
    if not process_id:
        # Процесса ещё нет, но маршрут есть: отдаём сам граф, чтобы путь был виден
        # заранее. Без этого схема исчезала с экрана до первого шага и выглядела
        # как пропавшая возможность, а не как «работа не начата».
        return {"ok": True, "exists": False, "kind": site.kind or "new_build",
                **preview, "needsReconcile": []}
    state = _from_facade(await _call(
        db, company_id, "GET", f"{FACADE}/instances/{process_id}",
        params={"actorEmail": getattr(user, "email", None) or ""}))
    # Поля шага тоже досверяем. Их пишет `apply_step` уже после ответа Координатора,
    # и обрыв связи между этими точками оставлял подрядчика и форму права только в
    # кейсе: человек их ввёл, а чек-лист проекта об этом не знал. Значения кейса —
    # канонические, поэтому сверка идемпотентна и повтор ей не вредит.
    state["needsReconcile"] = _pending_diff(site, state)
    return state


def _pending_diff(site: EzsSite, state: dict[str, Any]) -> list[str]:
    """Чем карточка проекта расходится с маршрутом — без единой записи.

    Возвращает причины на языке человека: их видно в карточке, и по ним понятно,
    что даст кнопка «Сверить». Пустой список означает, что сверять нечего.
    """
    reasons: list[str] = []
    values = state.get("values") or {}
    for source, column in STEP_FIELDS_TO_SITE.items():
        if not hasattr(site, column):
            continue
        value = values.get(source)
        if value in (None, ""):
            continue
        if getattr(site, column, None) in (None, "", 0):
            reasons.append(f"поле «{column}» заполнено в маршруте, но не в карточке")

    stage = (state.get("stage") or {}).get("code") or state.get("stageCode")
    if stage in COMMISSIONED_STAGES and not site.commissioned_on:
        reasons.append("маршрут дошёл до ввода в эксплуатацию, дата ввода не зафиксирована")
    if stage == "ezs_rejected" and site.stage != "archive":
        reasons.append("маршрут завершён отказом, проект не переведён в архив")
    if stage == "ezs_hold" and site.stage != "on_hold":
        reasons.append("маршрут на паузе, проект остался в работе")
    return reasons


async def reconcile(db: AsyncSession, company_id, site: EzsSite,
                    user: User | None = None) -> dict[str, Any]:
    """Свести карточку проекта с маршрутом — явной операцией, а не чтением.

    Ровно то, что раньше делалось на GET: поля шага и исход маршрута. Отличие
    в том, что теперь это осознанное действие с автором, и дату ввода ставит тот,
    кто её подтвердил, а не тот, кто открыл экран.
    """
    process_id, _ = await _instance_id(db, company_id, site)
    if not process_id:
        # Сводить нечего: работа по маршруту не начиналась.
        return {"ok": True, "exists": False, "needsReconcile": []}
    state = _from_facade(await _call(
        db, company_id, "GET", f"{FACADE}/instances/{process_id}",
        params={"actorEmail": getattr(user, "email", None) or ""}))
    before = {column: getattr(site, column, None) for column in STEP_FIELDS_TO_SITE.values()}
    written = _reflect_step_fields(site, state.get("values") or {})
    if written:
        state["siteFieldsWritten"] = written
        from app.services.ezs_site_work import log_event
        await log_event(
            db, site, "edit", user=user, source="reconcile",
            text="Поля проекта досверены с маршрутом",
            changes=[make_change(field, before[field], getattr(site, field)) for field in written],
        )
    funnel = await _reflect_outcome(db, site, state, payload=state.get("values") or {}, user=user)
    if funnel:
        state["funnel"] = funnel
    state["needsReconcile"] = _pending_diff(site, state)
    return state


async def _reflect_outcome(db: AsyncSession, site: EzsSite, state: dict[str, Any],
                           payload: dict[str, Any] | None = None,
                           user: User | None = None) -> dict[str, Any] | None:
    """Отразить в воронке проекта исход маршрута: отказ, пауза или возврат в работу.

    Маршрут и воронка — две записи об одном проекте, и расходиться им нельзя.
    Отражался только ввод в эксплуатацию, поэтому отклонённый на маршруте проект
    оставался в воронке «Переговоры»: в шапке карточки висели рабочие бейджи, а
    ход показывал «Отказ, действий больше нет» (замечание отдела развития
    06.08.2026). Причина отказа при этом жила в кейсе Координатора и в карточку
    не доезжала — теперь она пишется в «Причину архивации» и в историю проекта.
    """
    stage_code = (state.get("stage") or {}).get("code")
    from app.services import ezs_site_work

    if stage_code == "ezs_rejected" and site.stage != "archive":
        reason = str((payload or {}).get("cancel_reason") or "").strip()
        moved = await ezs_site_work.set_stage(
            db, site, "archive", user=user, source="system",
            reason=reason or "Отказ по маршруту проекта (Координатор)")
        return {"moved": moved.get("moved", False), "blocking": [], "message": moved.get("message")}

    if stage_code == "ezs_hold" and site.stage != "on_hold":
        reason = str((payload or {}).get("hold_reason") or "").strip()
        moved = await ezs_site_work.set_stage(
            db, site, "on_hold", user=user, source="system",
            reason=reason or "Пауза по маршруту проекта (Координатор)")
        return {"moved": moved.get("moved", False), "blocking": [], "message": moved.get("message")}

    # Возврат в работу: маршрут снова на рабочей стадии, а проект лежит вне воронки.
    # Возвращаем туда, откуда ушёл; не помним — в начало, дальше человек сам.
    if (stage_code and stage_code not in COMMISSIONED_STAGES
            and stage_code not in ("ezs_rejected", "ezs_hold")
            and site.stage in ("archive", "on_hold")):
        from app.services import ezs_sites
        back = site.prev_stage if site.prev_stage in ezs_sites.STAGE_ORDER else "lead"
        moved = await ezs_site_work.set_stage(
            db, site, back, user=user, source="system",
            reason="Возврат в работу по маршруту проекта (Координатор)")
        return {"moved": moved.get("moved", False), "blocking": [], "message": moved.get("message")}

    if stage_code not in COMMISSIONED_STAGES or site.stage == "live":
        return None
    from app.services import ezs_site_work, ezs_sites

    # Пауза и архив лежат ВНЕ воронки, и проверка «идём ли вперёд» для них не
    # считается — а вместе с ней не считаются и обязательные пункты. Замороженный
    # или отклонённый проект получил бы дату ввода вообще без единого гейта, то
    # есть ложное основание перевода капвложений 08 → 01.
    if site.stage not in ezs_sites.STAGE_ORDER:
        return {"moved": False, "blocking": [], "message":
                "Проект снят с воронки (пауза или архив) — верните его в работу,"
                " и ввод в эксплуатацию отразится."}
    # Демонтаж вводом в эксплуатацию не заканчивается: станцию увозят, а не
    # запускают. Маршрут у переноса, модернизации и демонтажа общий, поэтому
    # различаем здесь.
    if (site.kind or "") == "decommission":
        return None

    moved = await ezs_site_work.set_stage(
        db, site, "live",
        reason="Ввод в эксплуатацию по маршруту проекта (Координатор)",
        user=None, source="system")
    # Дату ввода ставим, только если воронка проект ПРИНЯЛА. Это основание
    # перевода капвложений со счёта 08 на 01: на проекте с незакрытыми гейтами
    # она была бы ложной записью в учёте, которую потом никто не оспорит.
    if moved.get("moved") and not site.commissioned_on:
        site.commissioned_on = date.today().isoformat()
        await ezs_site_work.log_event(
            db, site, "edit", user=None, text="Зафиксирована дата ввода",
            changes=[make_change("commissioned_on", None, site.commissioned_on)],
            source="system",
        )
    return {
        "moved": moved.get("moved", False),
        "blocking": moved.get("blocking") or [],
        "message": moved.get("message"),
    }


# Поля формы перехода, которые обязаны попасть в карточку проекта, а не остаться
# в кейсе. Человек заполняет «Подрядчик» при подписании договора подряда и вправе
# считать пункт 6.1 закрытым — но чек-лист читает карточку, а не кейс, и пункт
# оставался красным. Список белый: переносим только то, у чего в карточке есть
# ровно такая же по смыслу графа.
STEP_FIELDS_TO_SITE: dict[str, str] = {
    "contractor": "contractor",          # 6.1 «Поиск подрядной организации»
    "supplier": "supplier",              # 3.11 «Выбор поставщика оборудования»
    "control_form": "control_form",      # 4.1 «Выбор формы оформления земли»
    "tu_status": "tu_status",            # 4.8 «Основание для ТП получено»
    "cost_smr": "smr_cost",              # 3.12 «Расчёт экономики подключения»
    "cost_tech": "tp_cost",              # 3.12, часть про техприсоединение
    "permit_number": "permit_number",    # 4.6 «Разрешение на размещение получено»
}


def _reflect_step_fields(site: EzsSite, payload: dict[str, Any] | None) -> list[str]:
    """Перенести заполненное в форме перехода в карточку проекта.

    Пустым не затираем: маршрут дополняет карточку, а не переписывает её.
    """
    written: list[str] = []
    for code, column in STEP_FIELDS_TO_SITE.items():
        value = (payload or {}).get(code)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if getattr(site, column, None) in (None, "", 0):
            setattr(site, column, value)
            written.append(column)
    return written


async def undo_step(db: AsyncSession, company_id, site: EzsSite,
                    user: User | None = None) -> dict[str, Any]:
    """Отменить последний шаг маршрута — «нажал не ту кнопку».

    Правила отмены держит Координатор (свой последний шаг, сутки): движок хода —
    его, и второй набор правил в Ядре разошёлся бы с ним на первой же правке.
    Наше дело — вернуть воронку следом, тем же `_reflect_outcome`: отменённый
    отказ обязан снять проект с архива, иначе карточка снова разойдётся с ходом.
    """
    process_id, _ = await _instance_id(db, company_id, site)
    if not process_id:
        raise ProjectionError("По этому проекту маршрут ещё не начат — отменять нечего")
    state = _from_facade(await _call(
        db, company_id, "POST", f"{FACADE}/instances/{process_id}/undo",
        json={"actorEmail": getattr(user, "email", None)}))
    funnel = await _reflect_outcome(db, site, state, payload=state.get("values") or {}, user=user)
    if funnel:
        state["funnel"] = funnel
    return state


async def apply_step(db: AsyncSession, company_id, site: EzsSite, link_id: str,
                     payload: dict[str, Any] | None = None,
                     user: User | None = None,
                     branch_case_id: str | None = None) -> dict[str, Any]:
    """Выполнить шаг маршрута и, если проект дошёл до ввода, отразить это в воронке.

    Гейты воронки при этом НЕ обходим: маршрут ведёт ход, а обязательные пункты
    остаются нашими. Если гейт держит — так и говорим, вместо тихого обхода.

    branch_case_id адресует шаг в параллельную ветку проекта (ОР ∥ ОКС, подрядчик):
    ветка держит родителя, и закрывать её человек должен там же, где видит.
    """
    # Намерение отмечается ДО вызова и фиксируется отдельной транзакцией: если
    # связь оборвётся после того, как Координатор закоммитил переход, отметка
    # останется и фоновый проход досверит проект. Раньше это чинилось только тем,
    # что кто-нибудь откроет карточку.
    site.pending_link_id = str(link_id)
    site.pending_at = datetime.now(timezone.utc)
    await db.commit()

    process_id, _ = await _instance_id(db, company_id, site)
    if not process_id:
        raise ProjectionError("По этому проекту маршрут ещё не начат")
    state = _from_facade(await _call(
        db, company_id, "POST", f"{FACADE}/instances/{process_id}/actions", json={
            # Снаружи процесс двигают действием: идентификатор ребра остался тем же,
            # но называется он теперь по делу, а не «переходом стадии».
            "actionId": str(link_id),
            "actorEmail": getattr(user, "email", None),
            "payload": payload or {},
            "branchId": branch_case_id,
        }))

    # Шаг применён — переносим заполненное в карточку, иначе чек-лист не увидит
    # ни подрядчика, ни формы права, и человек будет искать, почему пункт красный.
    # Только для шага самого проекта: ветка ведёт свою часть и карточку не правит.
    if not branch_case_id:
        before = {column: getattr(site, column, None) for column in STEP_FIELDS_TO_SITE.values()}
        written = _reflect_step_fields(site, payload)
        if written:
            state["siteFieldsWritten"] = written
            from app.services.ezs_site_work import log_event
            await log_event(
                db, site, "edit", user=user, text="Поля перенесены из шага маршрута",
                changes=[make_change(field, before[field], getattr(site, field)) for field in written],
            )

    funnel = await _reflect_outcome(db, site, state, payload=payload, user=user)
    if funnel:
        state["funnel"] = funnel

    # Отражение прошло — намерение исполнено.
    site.pending_link_id = None
    site.pending_at = None
    return state
