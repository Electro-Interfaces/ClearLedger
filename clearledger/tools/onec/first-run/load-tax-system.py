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
from datetime import date as date_type

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company
from resolve_org import org_id, org_map

SRC = '/tmp/onec-taxsys.json'
KIND = 'tax_system'

# Система 1С → код режима в справочнике слоя (`tax_regimes`). Патент и НПД в этом
# регистре не живут: патент виден начислениями 68.45, НПД в бухгалтерии не ведут.
def regime_code(row) -> str | None:
    system = (row.get('СистемаНалогообложения') or '').strip().lower()
    if row.get('ПрименяетсяУСН'):
        obj = (row.get('ОбъектУСН') or '').strip().lower()
        return 'usn_income_expense' if 'уменьшен' in obj else 'usn_income'
    if 'общая' in system:
        return 'osno'
    if 'сельск' in system or 'есхн' in system:
        return 'eshn'
    return None

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

        added = regimes = 0
        touched: set[str] = set()
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

            # ГЛАВНОЕ: режим ложится в ТАБЛИЦУ СЛОЯ. Справочник выше — сырой факт
            # выгрузки, а расчёт налога берёт режим отсюда (`services/tax_regime`),
            # вместе со ставками и периодами действия. Пока настройки не грузились,
            # режим определялся по проводкам с пометкой `detected` — догадкой, которая
            # не различает объект упрощёнки.
            code = regime_code(r)
            if not code or not org_ref or not since:
                continue
            await s.execute(text("""
                DELETE FROM organization_tax_regimes
                 WHERE company_id = CAST(:c AS uuid)
                   AND organization_id = CAST(:o AS uuid)
                   AND valid_from = CAST(:since AS date)"""),
                {"c": cid, "o": org_ref, "since": date_type.fromisoformat(since)})
            await s.execute(text("""
                INSERT INTO organization_tax_regimes
                       (id, company_id, organization_id, regime_code, valid_from,
                        is_primary, vat_payer, source, note, created_at, updated_at)
                VALUES (gen_random_uuid(), CAST(:c AS uuid), CAST(:o AS uuid), :code,
                        CAST(:since AS date), true, :vat, '1c',
                        'из настроек 1С: ' || :sysname, now(), now())"""),
                {"c": cid, "o": org_ref, "code": code,
                 "since": date_type.fromisoformat(since),
                 "vat": bool(r.get('ПлательщикНДС')),
                 "sysname": label(r)})
            regimes += 1
            touched.add(org_ref)

        # Догадка уступает факту: записи `detected` (режим определён по проводкам) для
        # тех организаций, по которым пришли настройки 1С, удаляются. Иначе рядом
        # действуют две записи, и какая победит — вопрос сортировки, а не данных.
        if touched:
            await s.execute(text(
                "DELETE FROM organization_tax_regimes"
                " WHERE company_id = CAST(:c AS uuid) AND source = 'detected'"
                "   AND organization_id = ANY(CAST(:orgs AS uuid[]))"),
                {"c": cid, "orgs": sorted(touched)})

        # Закрываем предыдущие записи датой начала следующей: режим меняется во
        # времени, и без `valid_to` две записи одновременно считаются действующими.
        await s.execute(text("""
            UPDATE organization_tax_regimes t SET valid_to = nxt.next_from - 1
              FROM (SELECT id, lead(valid_from) OVER (PARTITION BY organization_id
                                                      ORDER BY valid_from) AS next_from
                      FROM organization_tax_regimes
                     WHERE company_id = CAST(:c AS uuid) AND source = '1c') nxt
             WHERE t.id = nxt.id AND nxt.next_from IS NOT NULL"""), {"c": cid})
        await s.commit()

        print('настроек налогообложения загружено:', added, '· режимов в слое:', regimes)
        for r in (await s.execute(text("""
            SELECT t.valid_from::text, t.valid_to::text, t.regime_code, o.name, t.source
              FROM organization_tax_regimes t
              JOIN organizations o ON o.id = t.organization_id
             WHERE t.company_id = CAST(:c AS uuid)
             ORDER BY o.name, t.valid_from"""), {"c": cid})).all():
            print('   %-26s %-20s с %s по %-12s (%s)'
                  % ((r[3] or '')[:26], r[2], r[0], r[1] or '—', r[4]))


asyncio.run(main())
