# -*- coding: utf-8 -*-
"""Система налогообложения из настроек 1С — а не догадка по проводкам.

Проводки говорят, КАКОЙ налог начислен, но не говорят главного: при упрощёнке
объект бывает двух видов, и это два разных бизнеса на одних и тех же счетах.
«Доходы» — налог с оборота, расходы на него не влияют вовсе; «доходы минус
расходы» — налог с разницы, и каждый принятый расход уменьшает платёж. Спутать их
значит показать человеку бессмысленную цифру: эффективную ставку к прибыли там,
где прибыль к налогу отношения не имеет.

Источник — регистр `НастройкиСистемыНалогообложения` (набор `queries-policy`).
Читает /tmp/onec-taxsys.json.

⚠ Объект УСН в 1С заполнен и у тех, кто на общем режиме (значение остаётся от
шаблона): у НПК в записи 2024 года стоит «Доходы, уменьшенные…» при
`ПрименяетсяУСН = false`. Поэтому объект берётся ТОЛЬКО когда упрощёнка включена.
"""
import asyncio
import json
import os

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company
from resolve_org import org_id, org_map

SRC = '/tmp/onec-taxsys.json'
KIND = 'tax_system'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


def label(row) -> str:
    """Человеческое имя режима: «Упрощённая · доходы минус расходы»."""
    sys_name = (row.get('СистемаНалогообложения') or '').strip() or 'не указана'
    if row.get('ПрименяетсяУСН') and (row.get('ОбъектУСН') or '').strip():
        obj = row['ОбъектУСН'].strip().lower()
        short = 'доходы минус расходы' if 'уменьшен' in obj else 'доходы'
        return '%s · %s' % (sys_name, short)
    return sys_name


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    rows = data.get('tax_mode') or []
    if not rows:
        print('в выгрузке нет настроек системы налогообложения')
        return

    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве')
            return
        cid = str(company.id)
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": cid})).all())

        await s.execute(text(
            "DELETE FROM gl_references WHERE company_id = :c AND kind = :k"),
            {"c": cid, "k": KIND})

        added = 0
        for r in rows:
            since = (r.get('Период') or '')[:10]
            usn = bool(r.get('ПрименяетсяУСН'))
            meta = {
                'organization': r.get('Организация'),
                'since': since,
                'system': r.get('СистемаНалогообложения'),
                'usn': usn,
                # Объект — только при включённой упрощёнке, см. предупреждение в шапке.
                'usnObject': (r.get('ОбъектУСН') or '').strip() if usn else None,
                'vat': bool(r.get('ПлательщикНДС')),
                'profitTax': bool(r.get('ПлательщикНалогаНаПрибыль')),
                'ndfl': bool(r.get('ПлательщикНДФЛ')),
                'tradeFee': bool(r.get('ПлательщикТорговогоСбора')),
                'enp': bool(r.get('ПлательщикЕНП')),
            }
            # У справочников слоя нет оси юрлица (колонки `organization_id` в
            # `gl_references` не существует), а режим у разных юрлиц компании бывает
            # разный. Поэтому ссылка на организацию лежит в `meta`, а в коде записи
            # стоит пара «дата · юрлицо» — чтобы записи не затирали друг друга.
            org_ref = org_id(orgs, r.get('Организация1С'))
            meta['organizationId'] = org_ref
            await s.execute(text("""
                INSERT INTO gl_references (id, company_id, kind, code,
                                           name, meta, is_group, is_deleted, created_at)
                VALUES (gen_random_uuid(), CAST(:c AS uuid), :k, :code,
                        :name, CAST(:meta AS jsonb), false, false, now())"""),
                {"c": cid, "k": KIND,
                 "code": '%s · %s' % (since or 'без даты', r.get('Организация') or '—'),
                 "name": label(r),
                 "meta": json.dumps(meta, ensure_ascii=False)})
            added += 1
        await s.commit()

        print('настроек налогообложения загружено:', added)
        for r in (await s.execute(text("""
            SELECT code, name, meta->>'usnObject' FROM gl_references
             WHERE company_id = :c AND kind = :k ORDER BY code"""),
            {"c": cid, "k": KIND})).all():
            print('   с %s — %s%s' % (r[0], r[1], (' (%s)' % r[2]) if r[2] else ''))


asyncio.run(main())
