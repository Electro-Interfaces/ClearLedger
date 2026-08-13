"""Качество данных пространства — именованные проверки с числом и подсказкой.

Разовая чистка ничего не закрепляет: через месяц выгрузка приносит новые
расхождения, и разбирать приходится заново. Здесь набор проверок, каждая из
которых отвечает на вопрос «сколько сейчас плохих записей и что с ними делать».

Проверка описывается декларативно: SQL, который возвращает одно число, плюс
подпись и подсказка. Ни одна из них не «ошибка системы» — это состояние данных,
и часть цифр никогда не станет нулём (например, платежи за период, где сессий у
нас нет вовсе). Поэтому у проверки есть `target`: сколько считается нормой.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    group: str
    sql: str            # возвращает ровно одно число (:cid — компания)
    hint: str           # что означает и что делать
    severity: str = "warn"   # warn | info
    target: int = 0     # сколько считается нормой


CHECKS: list[Check] = [
    # ── Объекты ──────────────────────────────────────────────────────────────
    Check("obj_no_vitrina", "Станции, которых нет в витрине", "Объекты",
          "select count(*) from service_locations where company_id=:cid and type='ev_charging' "
          "and extra_metadata->>'asuimStationId' is null",
          "Карточка есть у нас, но парк АСУиМ её не подтверждает: либо станция чужая, "
          "либо сменился её идентификатор. Разобрать поштучно."),
    Check("obj_dup_number", "Станции с одинаковым номером", "Объекты",
          "select coalesce(sum(c-1),0) from (select count(*) c from service_locations "
          "where company_id=:cid and type='ev_charging' and station_number is not null "
          "group by station_number having count(*)>1) x",
          "Один номер у нескольких карточек — обычно след разных источников. Слить."),
    Check("obj_closed_no_date", "Закрытые без даты вывода", "Объекты",
          "select count(*) from service_locations where company_id=:cid and type='ev_charging' "
          "and status='closed' and decommissioned_on is null",
          "Станция выведена, а когда — неизвестно. Для учёта ОС дата обязательна."),
    Check("obj_no_inventory", "Станции, не поставленные на учёт", "Объекты",
          "select count(*) from service_locations where company_id=:cid and type='ev_charging' "
          "and status<>'closed' and (inventory_number is null or inventory_number='')",
          "Инвентарный номер присваивает 1С при постановке ЭЗС на учёт в бухгалтерии "
          "(ответ ПА РусГидро 13.08.2026): пустое поле — не пробел в данных, а станция, "
          "которой на балансе ещё нет. Смотреть вместе со следующей строкой: часть из "
          "них уже принимает заезды."),
    Check("obj_earning_no_inventory", "Зарабатывают, но не на балансе", "Объекты",
          "select count(*) from service_locations l where l.company_id=:cid "
          "and l.type='ev_charging' and not l.is_test and l.status='active' "
          "and (l.inventory_number is null or l.inventory_number='') "
          "and exists (select 1 from charge_sessions s where s.location_id=l.id)",
          "Станция отпускает энергию и приносит выручку, но в бухгалтерии на учёт не "
          "поставлена — основного средства под этой выручкой нет. Список нужен "
          "бухгалтерии для постановки на баланс."),
    Check("obj_no_contract", "Станции без договора", "Объекты",
          "select count(*) from service_locations l where l.company_id=:cid and l.type='ev_charging' "
          "and l.status<>'closed' and not exists (select 1 from contract_locations cl "
          "where cl.location_id=l.id)",
          "Действующая станция без единого договора: аренда, электроснабжение или ТО не заведены."),
    Check("obj_orphan", "Записи вне парка ЭЗС", "Объекты",
          "select count(*) from service_locations where company_id=:cid and type='ezs'",
          "Остатки зеркал реестра Поддержки: аппараты-замены и записи без серийника. "
          "Слить с карточками станций или увести в оборудование."),

    # ── Продажи ──────────────────────────────────────────────────────────────
    Check("pay_no_session", "Платежи без сессии", "Продажи",
          "select count(*) from charge_payments p where p.company_id=:cid "
          "and p.session_ext_id is not null and not exists (select 1 from charge_sessions s "
          "where s.company_id=p.company_id and s.session_ext_id=p.session_ext_id)",
          "Деньги списаны, а зарядной сессии в Учёте нет. На краях периода это нормально "
          "(сессии выгружены не так глубоко), внутри периода — повод запросить выгрузку."),
    Check("ses_no_object", "Сессии без станции", "Продажи",
          "select count(*) from charge_sessions where company_id=:cid and location_id is null",
          "Сессия не привязана к объекту сети: её не видно ни в карточке станции, ни в разрезах по сети."),
    Check("ses_no_cut", "Сессии без разреза расчёта", "Продажи",
          "select count(*) from charge_sessions where company_id=:cid and cut_key is null",
          "Разрез расчёта (розница · корпоратив · служебная) проставляется при загрузке; "
          "у перенесённых с прода строк его нет, и они выпадают из сверки по каналам."),
    Check("ses_admin", "Служебные заезды персонала", "Продажи",
          "select count(*) from charge_sessions where company_id=:cid and charge_type='ADMIN'",
          "Заезды персонала (проверка станции, обслуживание). Решение МАГа 10.08.2026: "
          "считаем их выручкой наравне с клиентскими — отдельной корзины у них нет. "
          "Цифра стоит здесь, чтобы её видели, а не находили в разборе.", "info"),
    Check("card_no_owner", "Карты без владельца", "Продажи",
          "select count(*) from ezs_rfid_cards where company_id=:cid and customer_ext_id is null",
          "Карта есть, а чья — неизвестно: сессии по ней не связываются с клиентом."),
    Check("cust_no_phone", "Клиенты без телефона", "Продажи",
          "select count(*) from ezs_customers where company_id=:cid and (phone is null or phone='')",
          "Телефон — единственный ключ связи клиента с сессиями и платежами."),

    # ── Справочники ──────────────────────────────────────────────────────────
    Check("tariff_no_station", "Прайс без привязки к станциям", "Справочники",
          "select count(*) from ezs_tariffs where company_id=:cid and (stations is null or stations='')",
          "Витрина не отдаёт, к каким станциям применяется тариф. Пока сопоставляем по региону "
          "из названия тарифа.", "info"),
    Check("obj_no_group", "Станции без группы", "Справочники",
          "select count(*) from service_locations where company_id=:cid and type='ev_charging' "
          "and status<>'closed' and extra_metadata->>'asuimGroupId' is null",
          "Связь «станция → группа» витрина потеряла (колонка пуста), восстанавливается "
          "сопоставлением по владельцу, адресу и региону — подтверждается не для всех групп."),
    Check("obj_no_brand", "Станции без бренда из справочника", "Справочники",
          "select count(*) from service_locations where company_id=:cid and type='ev_charging' "
          "and extra_metadata->>'asuimBrandId' is null",
          "Бренд записан текстом и не сошёлся со справочником витрины — обычно потому, "
          "что такого бренда в справочнике нет вовсе."),

    # ── Обслуживание ─────────────────────────────────────────────────────────
    Check("tickets_no_object", "Заявки без станции", "Обслуживание",
          "select count(*) from public.tickets t join public.service_objects so on so.id=t.service_object_id "
          "where so.eco_object_id is null and coalesce(t.is_deleted,false)=false",
          "Заявка висит на объекте, который не связан с реестром: в карточке станции её не видно."),
]


async def data_quality(db: AsyncSession, company_id) -> dict[str, Any]:
    """Прогон всех проверок: число, норма, подсказка. Порядок — как в CHECKS."""
    items: list[dict[str, Any]] = []
    for c in CHECKS:
        try:
            n = int((await db.execute(text(c.sql), {"cid": str(company_id)})).scalar() or 0)
            err = None
        except Exception as exc:  # noqa: BLE001 — одна проверка не должна ронять экран
            n, err = -1, f"{type(exc).__name__}: {exc}"
        items.append({
            "key": c.key, "label": c.label, "group": c.group, "count": n,
            "target": c.target, "severity": c.severity, "hint": c.hint,
            "ok": err is None and n <= c.target, "error": err,
        })
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        groups.setdefault(it["group"], []).append(it)
    return {
        "groups": [{"label": g, "checks": v} for g, v in groups.items()],
        "totals": {
            "checks": len(items),
            "clean": sum(1 for i in items if i["ok"]),
            "issues": sum(i["count"] for i in items if i["count"] > 0 and i["severity"] == "warn"),
        },
    }
