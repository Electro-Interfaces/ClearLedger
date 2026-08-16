# -*- coding: utf-8 -*-
"""Договоры контрагентов из выгрузки бухгалтерии + членство админа в организации.

Договоры лежат в общем слое пространства (`contracts`), а не в домене бухгалтерии:
это опора, которой пользуются и продажи, и услуги, и будущая сверка.
"""
import asyncio
import json
from datetime import date

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import Company, Contract, Counterparty, User, UserCompany
from resolve_org import org_id, org_map

SRC = '/tmp/onec-core.json'


def d(s):
    return date.fromisoformat(s) if s else None


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

        # ИНН → id контрагента: договор без владельца бесполезен.
        by_inn = {c.inn: c.id for c in (await s.execute(
            select(Counterparty).where(Counterparty.company_id == cid))).scalars() if c.inn}

        # Юрлицо договора — из выгрузки. Раньше сюда клали id КОМПАНИИ: колонка
        # объявлена строкой без внешнего ключа, поэтому подмена проходила молча, а
        # разрез по юрлицу не находил ни одного договора.
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        await s.execute(delete(Contract).where(Contract.company_id == cid))
        added = skipped = 0
        for c in data['08-contracts']:
            if c.get('Удален'):
                continue
            inn = (c.get('КонтрагентИНН') or '').strip()
            cp = by_inn.get(inn)
            if cp is None:
                skipped += 1
                continue
            vid = str(c.get('ВидДоговора') or '')
            s.add(Contract(
                company_id=cid, counterparty_id=str(cp),
                organization_id=org_id(orgs, c.get('Организация1С')),
                number=(c.get('Номер') or '').strip()[:100] or 'б/н',
                date=(c.get('Дата') or ''),
                # Представление 1С — ключ связи с субконто оборотов и реквизитами
                # документов; наименование как запасной вариант.
                title=((c.get('Договор') or c.get('Имя') or '').strip() or None),
                valid_until=((c.get('СрокДействия') or '') or None),
                # Вид договора из бухгалтерии — тип; охват не задан: у офисной
                # компании договор не привязан к объектам, их нет.
                type=(c.get('Наименование') or vid or 'договор')[:100],
                kind='purchase' if 'поставщик' in vid.lower() else 'sale',
                scope_type='unassigned',
                external_ref=None,
            ))
            added += 1
        print('договоров загружено:', added, '| без контрагента:', skipped)

        # Членство: без него «Люди пространства» пусты, а права на организацию
        # держатся только суперадминством.
        admin = (await s.execute(select(User).where(User.email == 'admin@elsyplus.ru'))).scalar_one()
        has = (await s.execute(select(UserCompany).where(
            UserCompany.user_id == admin.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if has is None:
            s.add(UserCompany(user_id=admin.id, company_id=cid, role='admin'))
            print('членство админа в организации заведено')
        else:
            print('членство уже есть')

        await s.commit()


asyncio.run(main())
