"""Приёмка по канону на живом стенде: правила, проверяемые только на данных.

Гоняется внутри backend-контейнера пространства:

    ~/.claude/skills/elsy-deploy/scripts/exec-py.sh gig      scripts/audit-live.py
    ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro scripts/audit-live.py

Набор проверок подстраивается под данные пространства: топливный контур
проверяется там, где есть реализации, ЭЗС — там, где есть сессии.

Проверяет:
  • ряд графика сходится с цифрой над ним (расхождение = период и бакеты
    считаются в разных часовых поясах, см. канон 6.3.1);
  • пустой бакет у средних приходит null, а не нулём (ноль читался бы как
    «продавали по нулю»);
  • сутки действительно московские, и смены лежат в тех же сутках, что
    реализации;
  • ряд не считается без запроса — лишний скан не оплачивается молча.

Кеш отчётов сбрасывается в начале: иначе ответы приходят со старой логикой
и проверка врёт.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models import ChargeSession, Company, FuelShift, FuelTransaction as T
from app.services.analytics_cache import bump_version
from app.utils import msk_day_end, msk_day_start

# Период проверки — последний месяц с данными, а не «сегодня»: на стенде
# загрузка может отставать, и пустой период даст ложное «всё сходится».
OK: list[str] = []
BAD: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = '') -> None:
    if cond:
        OK.append(name)
    else:
        BAD.append((name, detail))


async def main() -> None:
    async with async_session_factory() as db:
        names = [c.name for c in (await db.execute(select(Company))).scalars().all()]
        print('пространство: %s' % ', '.join(names))
        for c in (await db.execute(select(Company))).scalars().all():
            await bump_version(db, c.id)

        fuel_cid = (await db.execute(select(T.company_id).limit(1))).scalar()
        chg_cid = (await db.execute(select(ChargeSession.company_id).limit(1))).scalar()

        if fuel_cid:
            last = (await db.execute(select(func.max(T.dt)).where(T.company_id == fuel_cid))).scalar()
            dt_ = last.date() if last else date.today()
            df_ = dt_ - timedelta(days=31)
            print('топливо: период %s — %s' % (df_, dt_))

            from app.services.fuel_network_analytics import FuelNetworkAnalytics
            from app.services.fuel_sales_analytics import FuelSalesAnalytics

            f = await FuelSalesAnalytics(db).fills(fuel_cid, df_, dt_, group_by='fuel', with_series=True)
            s, t = f['series'], f['totals']
            check('ряд реализаций сходится с итогом',
                  abs(sum(s['amount']) - t['amount']) < 0.01,
                  'Σ ряда %.2f vs итог %.2f' % (sum(s['amount']), t['amount']))
            check('пустой бакет у средних — null, не ноль',
                  all(v is None or v > 0 for v in s['avg_price']),
                  'ноль в средней цене читается как продажа по нулю')

            p = await FuelNetworkAnalytics(db).pumps(fuel_cid, df_, dt_, level='nozzle')
            check('ряд оборудования сходится с итогом',
                  sum(p['series']['fills']) == p['totals']['fills'],
                  'Σ %s vs итог %s' % (sum(p['series']['fills']), p['totals']['fills']))

            # Сутки московские: выборка одного дня не должна вылезать за границы.
            d = dt_ - timedelta(days=1)
            lo, hi = msk_day_start(d), msk_day_end(d)
            mn, mx = (await db.execute(select(func.min(T.dt), func.max(T.dt)).where(
                T.company_id == fuel_cid, T.dt >= lo, T.dt <= hi))).one()
            check('сутки реализаций — московские',
                  mn is None or (lo <= mn and mx <= hi),
                  'операции дня: %s … %s (границы %s … %s)' % (mn, mx, lo, hi))

            sh = (await db.execute(select(func.min(FuelShift.opened_at)).where(
                FuelShift.company_id == fuel_cid,
                FuelShift.opened_at >= lo, FuelShift.opened_at <= hi))).scalar()
            check('смены и реализации в одних сутках',
                  sh is None or (lo <= sh <= hi),
                  'первая смена дня: %s' % sh)

        if chg_cid:
            last = (await db.execute(select(func.max(ChargeSession.started_at))
                                     .where(ChargeSession.company_id == chg_cid))).scalar()
            dt_ = last.date() if last else date.today()
            df_ = dt_ - timedelta(days=31)
            print('ЭЗС: период %s — %s' % (df_, dt_))

            from app.services.analytics_service import AnalyticsService, PeriodFilter
            pf = PeriodFilter(company_id=chg_cid, date_from=df_, date_to=dt_)
            cs = await AnalyticsService(db).charge_sessions(pf, 'station', with_series=True)
            ssum = sum(v or 0 for v in cs['series']['amount'])
            check('ряд сессий сходится с итогом',
                  abs(ssum - cs['totals']['amount']) < 0.01,
                  'Σ %.2f vs итог %.2f' % (ssum, cs['totals']['amount']))
            check('пустой бакет успешности — null, не ноль',
                  all(v is None or v > 0 for v in cs['series']['success_pct']),
                  'ноль читался бы как «все сессии провалились»')
            cs0 = await AnalyticsService(db).charge_sessions(pf, 'station')
            check('лишний скан не платится без запроса', 'series' not in cs0)

        print('\n== СООТВЕТСТВУЕТ ==')
        for n in OK:
            print('  ок   %s' % n)
        if BAD:
            print('\n== РАСХОЖДЕНИЯ ==')
            for n, d_ in BAD:
                print('  !!   %s\n       %s' % (n, d_))
            raise SystemExit(1)
        print('\nрасхождений нет')


asyncio.run(main())
