"""Сопоставление ролей с карточками контрагентов (docs/SPACE.md §8).

Роль участника приезжала строкой: у площадки — собственник, поставщик, подрядчик,
у техприсоединения — сетевая организация, у корпклиента — название организации.
Пока это текст, одно и то же юрлицо в проектах и в договорах — два разных мира:
собственника участка нельзя сопоставить с арендодателем, которому платим.

Здесь одна механика на все такие поля: взять различные значения текста, свести с
карточкой контрагента по нормализованному имени (`_normname` — та же функция, что при
разборе реестров, поэтому «ООО «Ромашка»» и «Ромашка ООО» это одна карточка), чего нет
— завести. Текст не трогаем: он остаётся исходником.

Без `apply=True` ничего не пишет — считает, сколько совпадёт и сколько карточек
придётся завести. Решение «заводить 145 новых контрагентов» человек должен принять
глазами, а не узнать по факту.

ponytail: обновление — по одному UPDATE на различное имя (~200 на пилоте). Разовая
админская операция, батч через VALUES — когда понадобится делать это регулярно.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CorporateClient, Counterparty, EzsSite, EzsSiteEquipment, EzsTechConnection,
)
from app.services.reestr_normalize import _clean_cp_name, _cp_type, _normname

# (ключ, что за роль, модель, текстовое поле, поле ссылки, метка в aliases карточки)
_LINKS: list[tuple[str, str, Any, Any, Any, str]] = [
    ("site_owner", "Собственник площадки", EzsSite,
     EzsSite.owner, EzsSite.owner_counterparty_id, "собственник"),
    ("site_supplier", "Поставщик ЭЗС (проект)", EzsSite,
     EzsSite.supplier, EzsSite.supplier_counterparty_id, "поставщик"),
    ("site_contractor", "Подрядчик проекта", EzsSite,
     EzsSite.contractor, EzsSite.contractor_counterparty_id, "подрядчик"),
    ("grid_operator", "Сетевая организация", EzsTechConnection,
     EzsTechConnection.grid_operator, EzsTechConnection.grid_operator_counterparty_id,
     "сетевая организация"),
    ("site_equipment_supplier", "Поставщик оборудования проекта", EzsSiteEquipment,
     EzsSiteEquipment.supplier, EzsSiteEquipment.supplier_counterparty_id, "поставщик"),
    ("corporate_client", "Корпоративный клиент", CorporateClient,
     CorporateClient.name, CorporateClient.counterparty_id, "corporate"),
]

# Мусорные значения в роли: «-», «не определен», «информация уточняется» и подобное.
_JUNK = ("информац", "уточня", "не опред", "неизвест", "нет данных", "н/д", "отсутств")


def _usable(raw: str) -> bool:
    """Годится ли строка в имя контрагента (иначе заведём карточку-призрак)."""
    low = str(raw).strip().lower()
    if len(low) < 3 or low in ("-", "—", "нет", "н/а"):
        return False
    if any(j in low for j in _JUNK):
        return False
    return bool(_normname(raw))


async def link_counterparties(db: AsyncSession, company_id: uuid.UUID,
                              apply: bool = False,
                              only: set[str] | None = None) -> dict[str, Any]:
    """Свести текстовые роли с карточками контрагентов. apply=False — только отчёт.

    `only` — какие роли писать (остальные всё равно посчитаются в отчёте). Роли не
    равноценны: подрядчик и корпоративный клиент — уже стороны договора, а собственник
    площадки из банка кандидатов чаще всего останется кандидатом, и заводить его
    карточкой значит превратить реестр контрагентов в список «с кем поговорили».
    """
    cps = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == company_id))).scalars().all()
    by_norm: dict[str, Counterparty] = {}
    for cp in cps:
        nn = _normname(cp.name)
        if nn:
            by_norm.setdefault(nn, cp)
        for alias in (cp.aliases or []):
            an = _normname(alias)
            if an and an not in by_norm:
                by_norm[an] = cp

    links: list[dict[str, Any]] = []
    total_linked = total_created = 0

    for key, label, model, text_col, fk_col, alias in _LINKS:
        write = apply and (only is None or key in only)
        rows = (await db.execute(
            select(text_col, func.count()).where(
                model.company_id == company_id,
                text_col.isnot(None), text_col != "", fk_col.is_(None),
            ).group_by(text_col)
        )).all()

        matched = created = linked = skipped = 0
        samples: list[str] = []
        for raw, cnt in rows:
            if not _usable(raw):
                skipped += cnt
                continue
            nn = _normname(raw)
            cp = by_norm.get(nn)
            if cp is None:
                created += 1
                if len(samples) < 5:
                    samples.append(_clean_cp_name(raw)[:80])
                if write:
                    cp = Counterparty(
                        company_id=company_id, inn="", name=_clean_cp_name(raw)[:500],
                        type=_cp_type(raw), aliases=[alias], kind="external",
                    )
                    db.add(cp)
                    await db.flush()
                    by_norm[nn] = cp
            else:
                matched += 1
                if write and alias not in (cp.aliases or []):
                    cp.aliases = sorted(set((cp.aliases or []) + [alias]))
            linked += cnt
            if write and cp is not None:
                await db.execute(update(model).where(
                    model.company_id == company_id, text_col == raw, fk_col.is_(None),
                ).values({fk_col.key: cp.id}))

        links.append({
            "key": key, "label": label, "table": model.__tablename__,
            "field": text_col.key, "names": len(rows), "records": sum(c for _, c in rows),
            "matched": matched, "created": created, "linked": linked,
            "skipped": skipped, "samples": samples, "written": write,
        })
        # Итог — про сделанное: при выборочной записи невыбранные роли остаются планом.
        if write or not apply:
            total_linked += linked
            total_created += created

    if apply:
        await db.commit()

    return {"applied": apply, "links": links,
            "totals": {"linked": total_linked, "created": total_created}}


def unlinked(text_col, fk_col):
    """Условие «роль записана текстом, а ссылки нет» — для карты базы."""
    return (text_col.isnot(None)) & (text_col != "") & (fk_col.is_(None))


def any_unlinked(*pairs) -> Any:
    """То же для нескольких ролей одной сущности."""
    return or_(*[unlinked(t, f) for t, f in pairs])
