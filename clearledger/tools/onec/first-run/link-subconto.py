# -*- coding: utf-8 -*-
"""Свести аналитику оборотов со справочниками пространства.

Оборот несёт субконто ПРЕДСТАВЛЕНИЕМ («АЗИМУТ ООО», «Основной договор»), а что
именно записано в первой позиции — знает план счетов: у 62.01 это контрагент, у
20.01 номенклатурная группа, у 51 банковский счёт. Карта видов лежит в
`gl_accounts.subconto` (её кладёт `load-subconto.py`), значение ищется в своём
справочнике по НОРМАЛИЗОВАННОМУ имени.

Что осознанно НЕ сводится:
  * виды без своего справочника в слое (номенклатурные группы, партии в
    эксплуатации, прочие доходы и расходы) — связывать не с чем;
  * значения, которых в справочнике нет: в `sub_links` пишется вид без ссылки,
    чтобы «не нашли» отличалось от «не искали».

Идемпотентен: перед проходом ссылки сбрасываются, иначе перезагрузка справочника
оставила бы ссылки на исчезнувшие карточки.
"""
import asyncio
import json
import os
import re

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')

# Вид субконто 1С → где искать значение. Слева — наименование вида в плане счетов,
# справа — таблица слоя (`ref:<kind>` = справочник `gl_references` этого вида).
KIND_SOURCE = {
    'Контрагенты': 'counterparties',
    'Договоры': 'contracts',
    'Номенклатура': 'nomenclature',
    'Продукция': 'nomenclature',
    'Банковские счета': 'ref:bank_accounts',
    'Статьи затрат': 'ref:cost_items',
    'Статьи движения денежных средств': 'ref:cashflow_items',
    'Работники организаций': 'ref:persons',
    'Физические лица': 'ref:persons',
    'Склады': 'ref:warehouses',
    'Подразделения': 'ref:subdivisions',
    'Виды налогов': 'ref:tax_types',
}

# Виды без своего справочника — связывать НЕ С ЧЕМ, и это разное «нечем»:
#   * перечисление платформы («Виды платежей в бюджет (фонды)» — это «Налог: начислено
#     / уплачено», «Пени: доначислено», а не справочник налогов);
#   * документ вместо элемента («Партии» показываются поступлением, «Счета-фактуры»
#     — самим счётом-фактурой);
#   * справочник, которого в слое нет вовсе (номенклатурные группы, прибыли и убытки).
# Перечислены явно, чтобы отчёт связывания отличал «не нашли» от «искать негде».


def norm(s) -> str:
    """Имя к сравнимому виду: регистр, кавычки, лишние пробелы.

    В 1С одно и то же юрлицо в разных местах пишется «ООО "Ромашка"», «ООО Ромашка»
    и «Ромашка ООО» — последнее уже другое имя, и его мы не угадываем. Здесь только
    то, что заведомо шум: кавычки, регистр, двойные пробелы.
    """
    s = (s or '').strip().lower().replace('ё', 'е')
    s = s.replace('«', '"').replace('»', '"').replace(' ', ' ')
    s = re.sub(r'["\']', '', s)
    return re.sub(r'\s+', ' ', s).strip()


async def main():
    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве')
            return
        cid = str(company.id)

        accounts = {r[0]: (r[1] or []) for r in (await s.execute(text(
            "SELECT code, subconto FROM gl_accounts WHERE company_id = :c"),
            {"c": cid})).all()}
        if not any(accounts.values()):
            print('[!] карта субконто пуста — сначала load-subconto.py')
            return

        def kinds_of(code):
            """Виды субконто счёта; у субсчёта без своей карты берём родительский."""
            code = (code or '').strip()
            while code:
                if accounts.get(code):
                    return accounts[code]
                code = code.rpartition('.')[0]
            return []

        # ── индексы справочников: нормализованное имя → id ────────────────────
        idx: dict[str, dict[str, str]] = {}

        cps: dict[str, str] = {}
        for r in (await s.execute(text(
            "SELECT id::text, name, full_name, aliases FROM counterparties WHERE company_id = :c"),
            {"c": cid})).all():
            for nm in [r[1], r[2]] + list(r[3] or []):
                if nm:
                    cps.setdefault(norm(nm), r[0])
        idx['counterparties'] = cps

        # Договор ищется тремя ключами, от точного к общему:
        #   1) ПРЕДСТАВЛЕНИЕ 1С («№ 06/21 от 22.06.2021») — ровно то, что стоит в
        #      субконто; разбирать строку не нужно и вредно: у клиентов встречаются
        #      «233\\2011-пост от 20.06.11» и «№ 21/2 от 02.12.2020г.»;
        #   2) пара «контрагент + номер» — номер уникален только внутри контрагента,
        #      а контрагент у оборота стоит в соседнем субконто;
        #   3) просто номер — если он в компании единственный.
        cons: dict[str, str] = {}
        cons_by_cp: dict[tuple[str, str], str] = {}
        num_seen: dict[str, int] = {}
        for r in (await s.execute(text(
            "SELECT id::text, number, date, title, counterparty_id FROM contracts"
            " WHERE company_id = :c"), {"c": cid})).all():
            cid_cp = (r[4] or '').strip()
            num, dt, title = (r[1] or '').strip(), (r[2] or '')[:10], (r[3] or '').strip()
            if title:
                cons.setdefault(norm(title), r[0])
            if num:
                num_seen[norm(num)] = num_seen.get(norm(num), 0) + 1
                if cid_cp:
                    cons_by_cp.setdefault((cid_cp, norm(num)), r[0])
                if dt:
                    d = '.'.join(reversed(dt.split('-')))
                    cons.setdefault(norm('%s от %s' % (num, d)), r[0])
        for r in (await s.execute(text(
            "SELECT id::text, number FROM contracts WHERE company_id = :c"), {"c": cid})).all():
            n = norm((r[1] or '').strip())
            if n and num_seen.get(n) == 1:
                cons.setdefault(n, r[0])
        idx['contracts'] = cons

        noms: dict[str, str] = {}
        for r in (await s.execute(text(
            "SELECT id::text, name FROM nomenclature WHERE company_id = :c"), {"c": cid})).all():
            if r[1]:
                noms.setdefault(norm(r[1]), r[0])
        idx['nomenclature'] = noms

        for kind in sorted({v.split(':', 1)[1] for v in KIND_SOURCE.values() if v.startswith('ref:')}):
            m: dict[str, str] = {}
            for r in (await s.execute(text(
                "SELECT id::text, code, name FROM gl_references"
                " WHERE company_id = :c AND kind = :k"), {"c": cid, "k": kind})).all():
                for nm in (r[2], r[1]):
                    if nm:
                        m.setdefault(norm(nm), r[0])
            idx['ref:' + kind] = m

        # ── проход ───────────────────────────────────────────────────────────
        await s.execute(text(
            "UPDATE gl_turnovers SET dt_counterparty_id = NULL, kt_counterparty_id = NULL,"
            " dt_contract_id = NULL, kt_contract_id = NULL, sub_links = NULL"
            " WHERE company_id = :c"), {"c": cid})

        rows = (await s.execute(text(
            "SELECT id::text, account_dt, account_kt, dt1, dt2, kt1, kt2"
            "  FROM gl_turnovers WHERE company_id = :c"), {"c": cid})).all()

        stat = {'total': len(rows), 'values': 0, 'linked': 0, 'no_source': 0, 'not_found': 0}
        by_kind: dict[str, list[int]] = {}
        updates = []
        for rid, acc_dt, acc_kt, dt1, dt2, kt1, kt2 in rows:
            links: dict[str, dict] = {}
            cp = {'dt': None, 'kt': None}
            con = {'dt': None, 'kt': None}
            for side, acc, values in (('dt', acc_dt, (dt1, dt2)), ('kt', acc_kt, (kt1, kt2))):
                kinds = kinds_of(acc)
                for pos, value in enumerate(values):
                    if not (value or '').strip():
                        continue
                    stat['values'] += 1
                    kind = kinds[pos] if pos < len(kinds) else None
                    slot = '%s%d' % (side, pos + 1)
                    if not kind:
                        links[slot] = {'kind': None}
                        stat['no_source'] += 1
                        continue
                    src = KIND_SOURCE.get(kind)
                    cnt = by_kind.setdefault(kind, [0, 0])
                    cnt[0] += 1
                    if not src:
                        links[slot] = {'kind': kind}
                        stat['no_source'] += 1
                        continue
                    found = idx.get(src, {}).get(norm(value))
                    if src == 'contracts' and not found and cp[side]:
                        # Номер из представления: «№ 06/21 от 22.06.2021» → «06/21».
                        bare = re.sub(r'^\s*№\s*', '', (value or '').strip())
                        bare = re.split(r'\s+от\s+', bare)[0]
                        found = cons_by_cp.get((cp[side], norm(bare)))
                    links[slot] = {'kind': kind, 'table': src, 'id': found}
                    if found:
                        stat['linked'] += 1
                        cnt[1] += 1
                        if src == 'counterparties':
                            cp[side] = cp[side] or found
                        elif src == 'contracts':
                            con[side] = con[side] or found
                    else:
                        stat['not_found'] += 1
            updates.append({
                'id': rid, 'dtc': cp['dt'], 'ktc': cp['kt'],
                'dtd': con['dt'], 'ktd': con['kt'],
                'links': json.dumps(links, ensure_ascii=False) if links else None,
            })

        SQL = text(
            "UPDATE gl_turnovers SET dt_counterparty_id = CAST(:dtc AS uuid),"
            " kt_counterparty_id = CAST(:ktc AS uuid), dt_contract_id = CAST(:dtd AS uuid),"
            " kt_contract_id = CAST(:ktd AS uuid), sub_links = CAST(:links AS jsonb)"
            " WHERE id = CAST(:id AS uuid)")
        for i in range(0, len(updates), 500):
            await s.execute(SQL, updates[i:i + 500])
        await s.commit()

        print('оборотов: %d · значений субконто: %d · связано: %d · не найдено: %d'
              ' · нечем связывать: %d'
              % (stat['total'], stat['values'], stat['linked'], stat['not_found'],
                 stat['no_source']))
        # ── сальдо: тот же приём ─────────────────────────────────────────────
        # `gl_balances.counterparty_id` проставляется при загрузке сравнением имён и
        # промахивается там, где карточку переименовали или слили. Здесь у нас уже
        # есть индекс с псевдонимами и карта видов субконто — доводим сведение до
        # конца и НЕ трогаем счета, где первое субконто вовсе не контрагент
        # (04.01 — НМА, 51 — банковский счёт, 69.11 — вид платежа в бюджет).
        bal = (await s.execute(text(
            "SELECT id::text, account, sub1 FROM gl_balances"
            " WHERE company_id = :c AND sub1 IS NOT NULL AND counterparty_id IS NULL"),
            {"c": cid})).all()
        fixed = skipped = 0
        upd = []
        for bid, acc, sub1 in bal:
            kinds = kinds_of(acc)
            if not kinds or kinds[0] != 'Контрагенты':
                skipped += 1
                continue
            found = cps.get(norm(sub1))
            if found:
                upd.append({'id': bid, 'cp': found})
                fixed += 1
        for i in range(0, len(upd), 500):
            await s.execute(text(
                "UPDATE gl_balances SET counterparty_id = CAST(:cp AS uuid)"
                " WHERE id = CAST(:id AS uuid)"), upd[i:i + 500])
        await s.commit()
        print('сальдо: досведено %d строк · не про контрагента %d · осталось без ссылки %d'
              % (fixed, skipped, len(bal) - fixed - skipped))

        print('по видам (значений / связано):')
        for kind, (n, ok) in sorted(by_kind.items(), key=lambda kv: -kv[1][0])[:14]:
            mark = '' if KIND_SOURCE.get(kind) else '  — своего справочника нет'
            print('   %-44s %6d / %-6d%s' % (kind[:44], n, ok, mark))


asyncio.run(main())
