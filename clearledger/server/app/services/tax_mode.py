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
    SELECT count(*) FILTER (WHERE coalesce(legal_form, '') = 'ip'
                              OR coalesce(vid, '') ILIKE '%предпринимател%'
                              OR coalesce(vid, '') ILIKE '%ИП%'),
           count(*)
      FROM organizations o
     WHERE o.company_id = CAST(:cid AS uuid)
       -- Только юрлица, за которыми ЕСТЬ учёт: в справочнике живут и заготовки
       -- («ИП Проверочный (временно)» у ПРОМИЗОЛ), и по ним компания объявлялась
       -- предпринимательской, хотя ни одного документа за карточкой нет.
       AND (EXISTS (SELECT 1 FROM gl_entries e WHERE e.organization_id = o.id)
         OR EXISTS (SELECT 1 FROM accounting_docs d WHERE d.organization_id = o.id))
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

    # ГЛАВНЫЙ источник — таблица режимов организаций (`organization_tax_regimes` +
    # справочник `tax_regimes` со ставками). Она в слое уже есть, ведётся по юрлицам с
    # периодом действия и знает объект упрощёнки. Проводки ниже остаются ЗАПАСНЫМ
    # вариантом: на них видно, какой налог начислен, но не видно, налог это с оборота
    # или с разницы, — а от этого зависит смысл половины экранов.
    regimes = [(r[0], r[1], r[2]) for r in (await db.execute(text("""
        SELECT t.regime_code, r.object, t.is_primary
          FROM organization_tax_regimes t
          JOIN tax_regimes r ON r.code = t.regime_code
         WHERE t.company_id = CAST(:cid AS uuid)
           AND (CAST(:org AS uuid) IS NULL OR t.organization_id = CAST(:org AS uuid))
           AND t.valid_from <= CURRENT_DATE
           AND (t.valid_to IS NULL OR t.valid_to >= CURRENT_DATE)
         ORDER BY t.is_primary DESC, t.valid_from DESC"""), p)).all()]
    codes = {c for c, _, _ in regimes}

    # Объект упрощёнки: сначала из режима слоя, затем из настроек 1С (справочник
    # `tax_system` — сырой факт выгрузки). У компании на общем режиме объект в 1С тоже
    # заполнен (остаётся от шаблона), поэтому читается только при включённой упрощёнке.
    obj = next((o for c, o, _ in regimes if c.startswith('usn') or c.startswith('ausn')), None)
    if obj == 'income':
        obj = 'Доходы'
    elif obj == 'income_minus_expense':
        obj = 'Доходы, уменьшенные на величину расходов'
    if not obj:
        obj = (await db.execute(text("""
            SELECT meta->>'usnObject' FROM gl_references
             WHERE company_id = CAST(:cid AS uuid) AND kind = 'tax_system'
               AND coalesce((meta->>'usn')::boolean, false)
               AND coalesce(meta->>'usnObject', '') <> ''
             ORDER BY code DESC LIMIT 1"""), {"cid": str(cid)})).scalar()
    osno, usn, patent, vat, commission, ndfl_ip, own_contrib = (bool(x) for x in row)

    # Заведённый режим сильнее наблюдения по проводкам: проводок может не быть вовсе
    # (компания только заведена), а режим бухгалтер уже указал.
    if codes:
        osno = osno or 'osno' in codes
        usn = usn or any(c.startswith('usn') or c.startswith('ausn') for c in codes)
        patent = patent or 'psn' in codes

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
        # Коды режимов из слоя — то, чем пользуется расчёт налога (`services/tax_regime`).
        # Пусто означает «режим не заведён», и это не то же самое, что «ОСНО».
        "codes": sorted(codes),
        "label": " + ".join(names) if names else None,
        # Доход у УСН и у предпринимателя считается ПО ОПЛАТЕ (кассовый метод), а
        # витрины выручки строятся по отгрузке (90.01.1). Это не ошибка ни там, ни
        # там, но цифры законно расходятся, и экран обязан об этом сказать.
        "cashBasis": bool(usn or patent or osno_ip),
    }
