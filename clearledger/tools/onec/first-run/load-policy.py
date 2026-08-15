# -*- coding: utf-8 -*-
"""Контакты контрагентов, даты запрета изменения и учётная политика.

Контакты кладём В КАРТОЧКУ контрагента (адрес, телефон, почта — колонки уже есть),
а не в общий справочник: по ним ищут и ими подписывают документы. Запрет и политика —
свойства учёта, а не сущности: они ложатся в `gl_references` со своим видом.
"""
import asyncio
import json

from sqlalchemy import delete, select

from app.database import async_session_factory
from app.models import Company, Counterparty, GlReference

SRC = '/tmp/onec-policy.json'

# Вид контакта 1С → колонка карточки. Прочие виды (факс, скайп) в карточке места не
# имеют и остаются в raw — заводить под них колонки незачем.
FIELD_BY_KIND = {
    'Юридический адрес': 'legal_address',
    'Фактический адрес': 'actual_address',
    'Телефон': 'phone',
    'E-mail': 'email',
    'Адрес электронной почты': 'email',
}


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()

        # ── контакты контрагентов ──
        by_inn: dict[str, Counterparty] = {}
        for c in (await s.execute(
                select(Counterparty).where(Counterparty.company_id == cid))).scalars():
            if c.inn:
                by_inn.setdefault(c.inn, c)

        touched, skipped = set(), 0
        for r in data.get('01-contacts', []):
            inn = (r.get('ИНН') or '').strip()
            cp = by_inn.get(inn)
            value = (r.get('Значение') or '').strip()
            if cp is None or not value:
                skipped += 1
                continue
            field = FIELD_BY_KIND.get((r.get('Вид') or '').strip())
            if field and not getattr(cp, field, None):
                setattr(cp, field, value[:1000] if 'address' in field else value[:255])
            raw = dict(cp.raw or {})
            raw.setdefault('contacts', {})[r.get('Вид') or 'прочее'] = value
            cp.raw = raw
            touched.add(cp.id)
        print('контрагентов обогащено:', len(touched), '| строк мимо:', skipped)

        # ── запрет изменения и учётная политика ──
        for kind in ('period_locks', 'accounting_policy', 'org_contacts'):
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))

        for r in data.get('03-locks', []):
            date = (r.get('ДатаЗапрета') or '')[:10]
            who = (r.get('Пользователь') or 'Для всех пользователей').strip()
            s.add(GlReference(company_id=cid, kind='period_locks', code=date,
                              name='Запрет изменения до %s — %s' % (date, who),
                              meta={'date': date, 'scope': who,
                                    'section': r.get('Раздел') or None}))
        print('дат запрета:', len(data.get('03-locks', [])))

        for r in data.get('04-policy', []):
            since = (r.get('Период') or '')[:10]
            s.add(GlReference(company_id=cid, kind='accounting_policy', code=since,
                              name='Учётная политика с %s' % since,
                              meta={'since': since, 'organization': r.get('Организация'),
                                    'inn': r.get('ИНН'),
                                    # Состав полей политики через COM недоступен:
                                    # коллекции метаданных 1С в PowerShell возвращают
                                    # null. Забран факт и период действия.
                                    'note': 'состав параметров требует выгрузки конфигурации'}))
        print('записей политики:', len(data.get('04-policy', [])))

        for r in data.get('02-org-contacts', []):
            value = (r.get('Значение') or '').strip()
            if not value:
                continue
            s.add(GlReference(company_id=cid, kind='org_contacts',
                              code=(r.get('Вид') or '')[:100],
                              name=value[:500],
                              meta={'kind': r.get('Вид'), 'type': r.get('Тип'),
                                    'organization': r.get('Организация')}))
        print('контактов организации:', len(data.get('02-org-contacts', [])))

        await s.commit()
        print('готово')


asyncio.run(main())
