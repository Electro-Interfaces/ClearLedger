# -*- coding: utf-8 -*-
"""Налоговый режим компании — ОДНО определение на всё пространство.

Режим читается по НАЧИСЛЕННОМУ налогу с дохода, а не по галочке в настройках:
галочку забывают переключить, а проводка есть или её нет. 68.04 — налог на прибыль
(ОСНО), 68.12 — налог при УСН, 68.45 — патент; режимы совмещаются (на УСН докупают
патенты под отдельные виды деятельности).

Функция живёт отдельно, потому что от неё зависят три разных экрана — «Налоги»,
«Пульс» и паспорт компании. Пока определение было скопировано в каждый, любая
правка расходилась по продукту: один экран уже знал про патент, другой ещё нет.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SQL = """
    SELECT count(*) FILTER (WHERE account_dt LIKE '68.04%' OR account_kt LIKE '68.04%'),
           count(*) FILTER (WHERE account_dt LIKE '68.12%' OR account_kt LIKE '68.12%'),
           count(*) FILTER (WHERE account_dt LIKE '68.45%' OR account_kt LIKE '68.45%'),
           count(*) FILTER (WHERE account_dt LIKE '68.02%' OR account_kt LIKE '68.02%'),
           count(*) FILTER (WHERE account_kt LIKE '004%'),
           -- НДФЛ ПРЕДПРИНИМАТЕЛЯ: у ИП на общем режиме налог с дохода это не 68.04,
           -- а 68.10 «Прочие налоги и сборы» с видом платежа «НДФЛ индивидуального
           -- предпринимателя». Без этой строки ИП на ОСНО выглядел бы компанией без
           -- режима вовсе, а «Пульс» посчитал бы ему налог на прибыль по ставке 25 %.
           count(*) FILTER (WHERE account_kt LIKE '68.10%'),
           -- Взносы «за себя» — не расходы на персонал: единый тариф ИП (69.06.5)
           -- и фиксированные взносы платит сам предприниматель.
           count(*) FILTER (WHERE account_dt LIKE '69.06%' OR account_kt LIKE '69.06%')
      FROM gl_entries
     WHERE company_id = CAST(:cid AS uuid)
       AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
            OR organization_id = CAST(:org AS uuid))
"""

# Юрлицо или предприниматель — из справочника организаций: в 1С это реквизит
# «ЮридическоеФизическоеЛицо», он приезжает в `organizations.vid`.
FORM_SQL = """
    SELECT count(*) FILTER (WHERE coalesce(vid, '') ILIKE '%предпринимател%'
                              OR coalesce(vid, '') ILIKE '%ИП%'
                              OR coalesce(legal_form, '') ILIKE '%предпринимател%'),
           count(*)
      FROM organizations WHERE company_id = CAST(:cid AS uuid)
"""


async def tax_mode(db: AsyncSession, cid, org=None) -> dict[str, Any]:
    """Режим и форма ведения дела компании.

    Возвращает `{osno, usn, patent, osnoIp, ip, vat, commission, cashBasis, label}`.

    `commission` здесь же не случайно: комиссионная торговля (списание с
    забалансового 004) меняет чтение выручки так же сильно, как режим — чтение
    налогов, и спрашивают об этом в тех же местах. `cashBasis` — о том же: у УСН,
    патента и предпринимателя доход признаётся ПО ОПЛАТЕ, а витрины выручки строятся
    по отгрузке, и расхождение здесь законно.
    """
    p = {"cid": str(cid), "org": str(org) if org else None}
    row = (await db.execute(text(SQL), p)).one()

    # Объект упрощёнки — из НАСТРОЕК 1С, а не из проводок: по счёту 68.12 не видно,
    # налог это с оборота или с разницы, а бизнес за этими двумя вариантами разный.
    # Берём последнюю по дате запись, где упрощёнка включена: у компании на общем
    # режиме объект тоже заполнен (остаётся от шаблона) и врал бы.
    obj = (await db.execute(text("""
        SELECT meta->>'usnObject' FROM gl_references
         WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_system'
           AND coalesce((meta->>'usn')::boolean, false)
           AND coalesce(meta->>'usnObject', '') <> ''
         ORDER BY code DESC LIMIT 1"""), {"cid": str(cid)})).scalar()
    osno, usn, patent, vat, commission, ndfl_ip, own_contrib = (bool(x) for x in row)
    forms = (await db.execute(text(FORM_SQL), {"cid": str(cid)})).one()
    # «ИП» здесь означает «в учёте есть предприниматель», а не «все юрлица — ИП»:
    # у аутсорсера в одной базе рядом живут ООО и ИП одного владельца.
    is_ip = bool(forms[0])

    # Общий режим у предпринимателя — это НДФЛ с доходов, а не налог на прибыль.
    # Отдельная метка нужна, чтобы экраны не звали его «налогом на прибыль» и не
    # считали по ставке 25 %: база у НДФЛ другая (доход минус профессиональный вычет).
    osno_ip = is_ip and ndfl_ip and not osno

    # «Доходы» — налог с ОБОРОТА: расходы на него не влияют вовсе, и показывать
    # рядом рентабельность как основание налога бессмысленно. «Доходы минус расходы» —
    # налог с разницы, там каждый принятый расход уменьшает платёж.
    usn_object = None
    if usn and obj:
        usn_object = 'доходы минус расходы' if 'уменьшен' in obj.lower() else 'доходы'
    usn_name = 'УСН (%s)' % usn_object if usn_object else 'УСН'
    names = [n for n, on in (("ОСНО", osno), ("ОСНО (НДФЛ)", osno_ip),
                             (usn_name, usn), ("патент", patent)) if on]
    return {
        "osno": osno, "usn": usn, "patent": patent,
        "vat": vat, "commission": commission,
        "ip": is_ip, "osnoIp": osno_ip, "ownContributions": own_contrib,
        # `usnObject`: «доходы» | «доходы минус расходы» | None (настройки не загружены).
        # `usnRevenueBased` — короткий ответ на вопрос «налог считается от оборота?».
        "usnObject": usn_object,
        "usnRevenueBased": usn_object == 'доходы',
        "organizations": forms[1], "ipOrganizations": forms[0],
        "label": " + ".join(names) if names else None,
        # Доход у УСН и у предпринимателя считается ПО ОПЛАТЕ (кассовый метод), а
        # витрины выручки строятся по отгрузке (90.01.1). Это не ошибка ни там, ни
        # там, но цифры законно расходятся, и экран обязан об этом сказать.
        "cashBasis": bool(usn or patent or osno_ip),
    }
