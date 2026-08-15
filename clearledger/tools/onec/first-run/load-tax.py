# -*- coding: utf-8 -*-
"""Налоговый контур и помесячные сальдо.

Календарь бухгалтера, сданная отчётность, начисления и уведомления ЕНС ложатся
справочниками (`gl_references`), помесячные срезы сальдо — в `gl_balances` с
пометкой `source='monthly'`.

⚠ Помесячные срезы обязаны нести именно эту пометку: все запросы за ДЕТАЛЬНЫМ
сальдо исключают её (`source <> 'monthly'`), потому что в сводных остатках нет
аналитики по контрагентам — без разделения «Взаиморасчёты» опустеют.

Данные читает из /tmp/onec-tax.json (наборы `queries-tax` и `queries-balances`).
"""
import asyncio
import json
import os
from datetime import date

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import Company, GlBalance, GlReference
from resolve_org import org_id, org_map

SRC = '/tmp/onec-tax.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')

# Набор запроса → вид справочника пространства.
REF_KINDS = {
    'tax_calendar': 'tax_calendar',
    'reports_filed': 'reports_filed',
    'enp_accrual': 'enp_accrual',
    'enp_notice': 'enp_notice',
}


def name_of(row):
    """Имя записи. Уникальный индекс справочника — (компания, вид, код, имя),
    поэтому имя обязано различать строки: у календаря одно правило повторяется на
    каждый срок, и без срока в имени 289 задач схлопывались в 30."""
    # Начисление ЕНС: собственного имени в наборе нет — «Налог (взносы): начислено /
    # уплачено» стоит у всех 54 строк.
    if row.get('ПериодРасчета') and row.get('Счет'):
        # Различают строки внутримесячные периоды НДФЛ (05.11 и 20.11 одного месяца)
        # и сумма: без них 54 начисления схлопывались в 29 по уникальному индексу.
        return '%s за %s–%s (срок %s) — %s' % (
            row['Счет'],
            str(row.get('НачалоПериода') or row['ПериодРасчета'])[:10],
            str(row.get('КонецПериода') or row['ПериодРасчета'])[:10],
            str(row.get('СрокУплаты') or '')[:10] or 'н/д',
            row.get('Начислено') or row.get('СуммаНалога') or 0)
    base = None
    for key in ('Отчет', 'Документ', 'Наименование', 'Правило', 'Налог'):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            base = v.strip()
            break
    if base is None:
        for v in row.values():
            if isinstance(v, str) and v.strip():
                base = v.strip()
                break
    if row.get('Отчет'):
        # Один и тот же отчёт сдают повторно: РСВ за 2025 подписан 26.01 и 05.02,
        # ЕФС-1 — 24.04 и 27.04. Без даты подписи корректировка затирает первичную
        # сдачу, и в реестре остаётся одна строка вместо двух.
        signed = str(row.get('ДатаПодписи') or '')[:10]
        return '%s — подписан %s' % (base, signed) if signed else base
    if base and not row.get('Документ'):
        due = str(row.get('Срок') or row.get('ПериодСобытия') or '')[:10]
        if due:
            base = '%s — %s' % (base, due)
    return base


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        # ── справочники налогового контура ──
        for block, kind in REF_KINDS.items():
            rows = data.get(block) or []
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))
            seen = set()
            for r in rows:
                name = name_of(r)
                if not name:
                    continue
                code = str(r.get('КБК') or r.get('Код') or '')[:100]
                # Ключ ровно тот же, что у уникального индекса таблицы: иначе вставка
                # падает на дубле посреди пачки и не грузится вообще ничего.
                # Совпадение имени НЕ означает дубль: в 1С бывают две записи, различимые
                # только ссылкой (две сдачи 6-НДФЛ одним днём). Такие нумеруем, а не
                # выбрасываем — потерянная строка тихо занижает реестр.
                name = name[:500]
                if (code, name) in seen:
                    n = 2
                    while (code, '%s (%d)' % (name[:490], n)) in seen:
                        n += 1
                    name = '%s (%d)' % (name[:490], n)
                key = (code, name)
                seen.add(key)
                s.add(GlReference(
                    company_id=cid, kind=kind, code=code, name=name[:500],
                    is_deleted=bool(r.get('Удален')),
                    # `code` и `name` объявлены NOT NULL — пустое кладём строкой.
                    meta={k: v for k, v in r.items() if v not in (None, '')}))
            print('%-14s %5d' % (kind, len(seen)))

        # ── помесячные срезы сальдо ──
        rows = data.get('monthly_balances') or []
        await s.execute(delete(GlBalance).where(
            GlBalance.company_id == cid, GlBalance.source == 'monthly'))
        n = 0
        for i, b in enumerate(rows):
            period = b.get('Период')
            if not period:
                continue
            s.add(GlBalance(
                company_id=cid, as_of=date.fromisoformat(str(period)[:10]),
                account=str(b.get('Счет') or '')[:20],
                account_name=(b.get('ИмяСчета') or '')[:255] or None,
                debit=b.get('ОстатокДт') or 0,
                credit=b.get('ОстатокКт') or 0,
                organization_id=org_id(orgs, b.get('Организация1С')),
                source='monthly', external_key='m|%d' % i,
            ))
            n += 1
        print('%-14s %5d' % ('сальдо помес.', n))

        await s.commit()
        print('налоговый контур загружен')


asyncio.run(main())
