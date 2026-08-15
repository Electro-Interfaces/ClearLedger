# -*- coding: utf-8 -*-
"""Карточки юрлиц компании из справочника «Организации» 1С.

Запускается ПЕРВЫМ: остальные загрузчики сводят имя организации из выгрузки к
`organizations.id`, и без карточек ось юрлица во всём слое осталась бы пустой —
документы двух налогоплательщиков сложились бы в одну цифру, молча.

Данные читает из /tmp/onec-refs.json (набор `queries-first/05-refs-full`).
"""
import asyncio
import json
import os

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, Organization

SRC = '/tmp/onec-refs.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        have = {(o.inn or '').strip(): o for o in (await s.execute(
            select(Organization).where(Organization.company_id == cid))).scalars()}

        added = updated = 0
        for r in data['01-org']:
            inn = (r.get('ИНН') or '').strip()
            if not inn:
                # ИНН — единственный надёжный ключ юрлица; без него карточку не заводим,
                # иначе при повторном заходе появится второй экземпляр той же организации.
                print('пропущена организация без ИНН:', r.get('Наименование'))
                continue
            fields = dict(
                name=(r.get('Наименование') or inn)[:500],
                full_name=(r.get('Полное') or None),
                kpp=(r.get('КПП') or '').strip() or None,
                ogrn=(r.get('ОГРН') or '').strip() or None,
                okpo=(r.get('ОКПО') or '').strip() or None,
                prefix=(r.get('Префикс') or '').strip() or None,
                vid=(str(r.get('Вид')) or '')[:40] or None,
            )
            org = have.get(inn)
            if org is None:
                s.add(Organization(company_id=cid, inn=inn, **fields))
                added += 1
            else:
                for k, v in fields.items():
                    setattr(org, k, v)
                updated += 1

        await s.commit()
        print('юрлиц заведено %d, обновлено %d' % (added, updated))


asyncio.run(main())
