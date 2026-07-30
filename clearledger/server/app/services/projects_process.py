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

from datetime import date
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite, EzsSiteParticipant, User
from app.services.space_projection import (
    DEFAULT_TIMEOUT,
    ProjectionError,
    _error_text,
    _internal_base_url,
    _target,
)

APP_CODE = "support"

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
    return await _call(db, company_id, "POST", "/api/v1/eco/projects/case", json={
        "projectId": str(site.id),
        "title": site.title or site.project_no or f"Проект ЭЗС {site.id}",
        "kind": site.kind or "new_build",
        "objectEcoId": str(site.location_id) if site.location_id else None,
        "actorEmail": getattr(user, "email", None),
        "fields": _context(site),
        "participants": await _participants(db, site),
    })


async def case_state(db: AsyncSession, company_id, site: EzsSite,
                     user: User | None = None) -> dict[str, Any]:
    """Ход проекта для вкладки «Работа»: стадия, кнопки, вехи, сколько стоим.

    Действия считаются ОТ ИМЕНИ человека: кнопку ОКС менеджеру отдела развития
    показывать незачем. Кейса ещё нет — это не ошибка, а «работа не начата».

    Здесь же досводится ввод в эксплуатацию. Шаг применяется в двух системах по
    очереди: Координатор коммитит переход, Ядро двигает воронку — и если между
    этими точками оборвалась связь, маршрут ушёл вперёд, а проект остался в
    прежней стадии навсегда: повторить шаг нельзя, второй раз ребро не сработает.
    Проверка при чтении карточки чинит расхождение сама.
    """
    state = await _call(db, company_id, "GET", f"/api/v1/eco/projects/{site.id}/case",
                        params={"actorEmail": getattr(user, "email", None) or "",
                                # Вид проекта нужен, когда кейса ещё нет: Координатор
                                # вернёт маршрут, чтобы путь было видно заранее.
                                "kind": site.kind or "new_build"})
    # Поля шага тоже досверяем. Их пишет `apply_step` уже после ответа Координатора,
    # и обрыв связи между этими точками оставлял подрядчика и форму права только в
    # кейсе: человек их ввёл, а чек-лист проекта об этом не знал. Значения кейса —
    # канонические, поэтому сверка идемпотентна и повтор ей не вредит.
    written = _reflect_step_fields(site, state.get("values") or {})
    if written:
        state["siteFieldsWritten"] = written
    funnel = await _reflect_commissioning(db, site, state, user=user)
    if funnel:
        state["funnel"] = funnel
    return state


async def _reflect_commissioning(db: AsyncSession, site: EzsSite, state: dict[str, Any],
                                 user: User | None = None) -> dict[str, Any] | None:
    """Отразить ввод в эксплуатацию в воронке проекта, если маршрут до него дошёл.

    Возвращает None, когда отражать нечего, иначе — что вышло с воронкой.
    """
    stage_code = (state.get("stage") or {}).get("code")
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
        reason="Ввод в эксплуатацию по маршруту проекта (Координатор)", user=user)
    # Дату ввода ставим, только если воронка проект ПРИНЯЛА. Это основание
    # перевода капвложений со счёта 08 на 01: на проекте с незакрытыми гейтами
    # она была бы ложной записью в учёте, которую потом никто не оспорит.
    if moved.get("moved") and not site.commissioned_on:
        site.commissioned_on = date.today().isoformat()
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
    state = await _call(db, company_id, "POST",
                        f"/api/v1/eco/projects/{site.id}/case/transition", json={
                            "linkId": str(link_id),
                            "actorEmail": getattr(user, "email", None),
                            "payload": payload or {},
                            "branchCaseId": branch_case_id,
                        })

    # Шаг применён — переносим заполненное в карточку, иначе чек-лист не увидит
    # ни подрядчика, ни формы права, и человек будет искать, почему пункт красный.
    # Только для шага самого проекта: ветка ведёт свою часть и карточку не правит.
    if not branch_case_id:
        written = _reflect_step_fields(site, payload)
        if written:
            state["siteFieldsWritten"] = written

    funnel = await _reflect_commissioning(db, site, state, user=user)
    if funnel:
        state["funnel"] = funnel
    return state
