# -*- coding: utf-8 -*-
"""Три поля, которые хранят не то, что обещают.

1. `operation_type` — «вид операции» по названию и комментарию модели, а лежало в нём
   назначение платежа, обрезанное на 100 символах у 271 документа. Вид операции всё
   это время лежал рядом, в `details`.
2. `organization_name` — два написания одной организации («ООО "ПРОМИЗОЛ СПБ"» и
   «ПРОМИЗОЛ СПБ ООО»), отбор по организации разваливал реестр надвое.
3. `warehouse_code` — хранит наименование склада, а не код; переименовывать поле
   дорого, но значение обязано быть тем, что подписано на экране.
"""
import asyncio

from sqlalchemy import func, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()

        docs = (await s.execute(select(AccountingDoc)
                                .where(AccountingDoc.company_id == cid))).scalars().all()

        moved = org = 0
        for d in docs:
            det = dict(d.details or {})
            kind = det.get('Вид операции')
            # Назначение платежа переезжает в реквизиты целиком, вид операции —
            # в колонку, для которой она и заведена.
            if d.doc_type in ('bank_in', 'bank_out') and d.operation_type:
                if 'Назначение платежа' not in det:
                    det['Назначение платежа'] = d.operation_type
                if kind:
                    d.operation_type = kind[:100]
                    moved += 1
                d.details = det
            if d.organization_name and d.organization_name != 'ООО "ПРОМИЗОЛ СПБ"':
                d.organization_name = 'ООО "ПРОМИЗОЛ СПБ"'
                org += 1

        await s.commit()
        print('вид операции возвращён в колонку:', moved)
        print('организация приведена к одному написанию:', org)

        rows = (await s.execute(text("""
            SELECT organization_name, count(*) FROM accounting_docs
             WHERE company_id = :cid GROUP BY 1"""), {'cid': str(cid)})).all()
        print('написаний организации:', {n: c for n, c in rows})
        long_op = (await s.execute(text("""
            SELECT count(*) FROM accounting_docs
             WHERE company_id = :cid AND length(operation_type) = 100"""),
            {'cid': str(cid)})).scalar_one()
        print('обрезанных назначений в колонке осталось:', long_op)


asyncio.run(main())
