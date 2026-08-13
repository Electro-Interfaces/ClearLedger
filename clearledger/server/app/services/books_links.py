"""Сведение документов бухгалтерии с нормализованным слоем (docs/REVENUE.md).

Документ приезжает из 1С с контрагентом СТРОКОЙ: имя, иногда ИНН, договор — тоже
строкой в реквизитах. Пока это текст, продукт отвечает лишь на вопрос «сколько», а
на «кому продали и сколько он должен» — нет: одно юрлицо приходит в трёх написаниях,
у платежа ИНН не бывает вовсе, а договор из счёта нельзя показать рядом с его
условиями.

Здесь одна идемпотентная операция: проставить `counterparty_id` и `contract_id` там,
где связь однозначна, и не трогать текст — он остаётся исходником. Приём данных это
не меняет: сведение запускается ПОСЛЕ загрузки (ручка `POST /api/books/relink`) и
безопасно повторяется — заполняются только пустые ссылки.

Порядок сведения контрагента — от надёжного ключа к слабому:

  1. ИНН документа = ИНН карточки        — точное совпадение, 2608 документов пилота;
  2. точное имя (регистр и пробелы)      — платежи и счета, где ИНН не приехал;
  3. нормализованное имя (`_normname`)   — «ООО «Ромашка»» = «Ромашка ООО».

Договор ищется по названию ВНУТРИ контрагента: «Основной договор» заведён у полутора
сотен юрлиц, и без контрагента такая связь ставила бы документ на чужой договор.

ponytail: три UPDATE ... FROM на компанию вместо построчного разбора. Разбирать по
одному есть смысл, когда появится ручное разрешение спорных случаев.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Нормализация имени — та же, что при разборе реестров: расхождение двух функций
# означало бы, что документ и площадка сводятся с РАЗНЫМИ карточками одного юрлица.
_NORM_SQL = """
    lower(regexp_replace(regexp_replace({col}, '[«»"''`]', '', 'g'), '\\s+', ' ', 'g'))
"""

_STEPS: list[tuple[str, str]] = [
    ("по ИНН", """
        UPDATE accounting_docs d SET counterparty_id = k.id
          FROM counterparties k
         WHERE d.company_id = :cid AND d.counterparty_id IS NULL
           AND k.company_id = d.company_id
           AND coalesce(d.counterparty_inn, '') <> ''
           AND k.inn = d.counterparty_inn
    """),
    ("по точному имени", """
        UPDATE accounting_docs d SET counterparty_id = k.id
          FROM counterparties k
         WHERE d.company_id = :cid AND d.counterparty_id IS NULL
           AND k.company_id = d.company_id
           AND coalesce(d.counterparty_name, '') <> ''
           AND k.name = d.counterparty_name
    """),
    ("по нормализованному имени", f"""
        UPDATE accounting_docs d SET counterparty_id = k.id
          FROM counterparties k
         WHERE d.company_id = :cid AND d.counterparty_id IS NULL
           AND k.company_id = d.company_id
           AND coalesce(d.counterparty_name, '') <> ''
           AND {_NORM_SQL.format(col='k.name')} = {_NORM_SQL.format(col='d.counterparty_name')}
    """),
]

# Договор документа лежит в реквизитах строкой («Основной договор», «01-11/2021 от
# 15.11.21»), а в справочнике то же значение — в `type`. Ключ связи составной:
# контрагент + название, иначе «Основной договор» сведётся с первым попавшимся.
_CONTRACT_SQL = """
    UPDATE accounting_docs d SET contract_id = c.id
      FROM contracts c
     WHERE d.company_id = :cid AND d.contract_id IS NULL
       AND d.counterparty_id IS NOT NULL
       AND c.company_id = d.company_id
       AND c.counterparty_id::text = d.counterparty_id::text
       AND coalesce(d.doc_meta->>'Договор', '') <> ''
       AND c.type = d.doc_meta->>'Договор'
"""


async def relink(db: AsyncSession, company_id, *, reset: bool = False) -> dict[str, Any]:
    """Проставить ссылки на контрагента и договор. Возвращает, что чем свелось.

    `reset=True` — пересобрать связи с нуля (после перезагрузки справочников, когда
    карточки получили новые id и старые ссылки обнулились каскадом).
    """
    params = {"cid": str(company_id)}
    if reset:
        await db.execute(text(
            "UPDATE accounting_docs SET counterparty_id = NULL, contract_id = NULL "
            "WHERE company_id = :cid"), params)

    matched: dict[str, int] = {}
    for label, sql in _STEPS:
        res = await db.execute(text(sql), params)
        matched[label] = res.rowcount or 0
    res = await db.execute(text(_CONTRACT_SQL), params)
    matched["договор по названию"] = res.rowcount or 0
    await db.commit()

    total, linked, with_contract, no_name = (await db.execute(text("""
        SELECT count(*), count(counterparty_id), count(contract_id),
               count(*) FILTER (WHERE coalesce(counterparty_name, '') = '')
          FROM accounting_docs WHERE company_id = :cid
    """), params)).one()

    # Кто не свёлся — это не «ошибка загрузки», а рабочий список: либо карточки нет,
    # либо имя в документе написано так, что человек должен решить сам.
    unmatched = [{"name": n, "inn": i, "docs": c} for n, i, c in (await db.execute(text("""
        SELECT counterparty_name, counterparty_inn, count(*)
          FROM accounting_docs
         WHERE company_id = :cid AND counterparty_id IS NULL
           AND coalesce(counterparty_name, '') <> ''
         GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 50
    """), params)).all()]

    return {
        "matched": matched,
        "docs": total,
        "linked": linked,
        "withContract": with_contract,
        # Документы без имени контрагента — регламентные операции и закрытие месяца:
        # у них контрагента нет по природе, и в «не свелось» им не место.
        "withoutCounterparty": no_name,
        "unmatched": unmatched,
    }
