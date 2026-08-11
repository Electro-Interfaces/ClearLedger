"""Сверка «сессия ↔ платёж ↔ чек» — правило `ezs_payments` из docs/CHANNEL_ASUIM_EZS.md.

Пока платежи жили отдельным пунктом, они отвечали на вопрос «сколько денег
пришло». Сведённые с сессиями, они отвечают на более важный: **где данные о
зарядках расходятся с деньгами**. Именно платёж показывает, что сессия на
10 341 кВт·ч за одиннадцать секунд — не рекорд сети, а битая строка: банк по ней
списал 1 007 ₽, а не 226 468 ₽.

Что считаем деньгами: платёж с банковской транзакцией (`bank_txn_id`). Статус 1
её не имеет и чека тоже — это попытка оплаты, а не оплата. Статусы 0 и 2 — одно
и то же успешное состояние в двух кодировках (02.04.2026 АСУиМ сменил код).

**Разрыв считается только по рознице.** У юрлиц постоплата по договору: эквайринга
по их сессиям нет вовсе, и включать их в сравнение — значит объявить расхождением
2,5 млн ₽ там, где его нет. Корп-начисления показываются отдельной величиной.

Шесть расхождений, каждое со своим смыслом:
  • `impossible`  — сессия противоречит физике: средняя мощность выше предела;
  • `double`      — на одну сессию несколько успешных списаний;
  • `underpaid`   — начислено больше, чем списано;
  • `no_payment`  — ток отпущен, оплаты нет (розница);
  • `no_receipt`  — деньги списаны, фискального чека нет;
  • `orphan`      — платёж есть, а сессии в Учёте нет.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scope import acl_params, acl_sql

# Предел средней мощности сессии. Самые быстрые станции сети — 150–350 кВт;
# 400 взято с запасом, чтобы под правило не попала честная быстрая зарядка.
MAX_POWER_KW = 400.0
# Порог денежного расхождения: копеечные хвосты округления разбирать незачем.
MONEY_EPS = 1.0


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    hint: str


KINDS: list[Kind] = [
    Kind("impossible", "Сессии против физики",
         "Средняя мощность выше 400 кВт — энергия и сумма в такой строке недостоверны. "
         "Сколько списал банк, видно в колонке «Оплачено»."),
    Kind("double", "Несколько списаний на зарядку",
         "На одну зарядку прошло больше одного успешного платежа. Часто это законная "
         "доплата, но если списано больше начисленного — деньги клиента; смотрите разрыв."),
    Kind("underpaid", "Списано меньше начисленного",
         "Сессия говорит одну сумму, банк списал меньшую. Либо ошибка в сессии, "
         "либо часть денег не дошла."),
    Kind("no_payment", "Отпуск без оплаты",
         "Ток отпущен розничному клиенту, платежа нет вовсе — это задолженность."),
    Kind("no_receipt", "Списано без фискального чека",
         "Деньги получены, чек ОФД не выбит: разрыв в фискализации."),
    Kind("overpaid", "Списано больше начисленного",
         "Банк снял больше, чем начислено по сессии, — это деньги клиента. "
         "На пилоте таких нет ни одной, и правило стоит именно чтобы это было видно."),
    Kind("orphan", "Платёж без сессии",
         "Деньги пришли, а зарядки в Учёте нет. На краях периода это глубина выгрузки, "
         "внутри периода — потерянная сессия."),
    # ── Платёжные расхождения: считаются по строкам эквайринга, а не по сессиям ──
    Kind("refund_full", "Полный возврат",
         "Холд снят и возвращён целиком: зарядка не состоялась. Деньги клиенту вернули, "
         "но занятый коннектор и неудачный приезд остались."),
    Kind("hold_rule", "Холд не сходится с возвратом",
         "Нарушено «холд − возврат = списание»: у операции не сходится трёхтактная "
         "схема оплаты картой, разбирать с банком."),
    Kind("receipt_no_txn", "Чек без банковской операции",
         "Фискальный чек выбит, а банковской транзакции нет — чек не на что."),
    Kind("not_card", "Оплата не картой",
         "Операция помечена как оплаченная не картой: другой канал расчёта, "
         "который не покрывается эквайрингом."),
]

# Расхождения, которые живут в самих платежах: тут ключ — строка эквайринга.
_PAY_WHERE = {
    "refund_full": "pp.refund_amount > 0 and pp.amount <= 0",
    "hold_rule": "pp.hold_amount > 0 and abs(pp.hold_amount - pp.refund_amount - pp.amount) >= 0.01",
    "receipt_no_txn": "pp.receipt_url is not null and pp.bank_txn_id is null",
    "not_card": "pp.by_card is false",
}

_SESSION_JOIN = """
    from charge_sessions s
    left join lateral (
        select coalesce(sum(p.amount) filter (where p.bank_txn_id is not null), 0) as paid,
               count(*) filter (where p.bank_txn_id is not null)                  as pay_ok,
               count(*)                                                            as pay_all,
               count(p.receipt_url) filter (where p.bank_txn_id is not null)       as receipts
          from charge_payments p
         where p.company_id = s.company_id and p.session_ext_id = s.session_ext_id
    ) pay on true
   where s.company_id = :cid and s.started_at >= :lo and s.started_at < :hi{acl}
"""

# Условие каждого расхождения — одно и то же в сводке и в списке.
_WHERE = {
    "impossible": "s.duration_min > 0 and s.energy_kwh > 0 "
                  "and s.energy_kwh / (s.duration_min / 60.0) > :maxkw",
    "double": "pay.pay_ok > 1",
    "underpaid": "pay.pay_ok > 0 and s.amount - pay.paid > :eps",
    "no_payment": "s.energy_kwh > 0 and pay.pay_all = 0 "
                  "and s.user_type is distinct from 'ЮЛ'",
    "no_receipt": "pay.pay_ok > 0 and pay.receipts = 0",
    "overpaid": "pay.pay_ok > 0 and pay.paid - s.amount > :eps",
}


def _bounds(df: date, dt: date) -> tuple[datetime, datetime]:
    from datetime import timedelta
    return (datetime.combine(df, datetime.min.time()),
            datetime.combine(dt, datetime.min.time()) + timedelta(days=1))


async def reconciliation(db: AsyncSession, company_id, df: date, dt: date) -> dict[str, Any]:
    """Сводка расхождений за период: сколько строк и на какие деньги."""
    lo, hi = _bounds(df, dt)
    p = {"cid": str(company_id), "lo": lo, "hi": hi,
         "maxkw": MAX_POWER_KW, "eps": MONEY_EPS, **acl_params()}
    join = _SESSION_JOIN.format(acl=acl_sql("s.location_id"))

    totals = (await db.execute(text(f"""
        select count(*) as sessions,
               coalesce(sum(coalesce(s.client_amount, s.amount)), 0) as amount,
               -- Розница: только по ней ожидается эквайринг, только её и сверяем.
               coalesce(sum(s.amount) filter (where s.client_name is null), 0) as retail_amount,
               coalesce(sum(coalesce(s.client_amount, 0)) filter (
                   where s.client_name is not null), 0) as corp_amount,
               coalesce(sum(s.energy_kwh), 0) as energy,
               coalesce(sum(pay.paid), 0) as paid,
               -- Энергия недостоверных строк: отпуск завышен ровно на неё.
               coalesce(sum(s.energy_kwh) filter (
                   where s.duration_min > 0 and s.energy_kwh > 0
                     and s.energy_kwh / (s.duration_min / 60.0) > :maxkw), 0) as bad_energy
        {join}
    """), p)).one()

    items: list[dict[str, Any]] = []
    for k in KINDS:
        if k.key in _PAY_WHERE:
            row = (await db.execute(text(f"""
                select count(*) as n,
                       coalesce(sum(pp.amount), 0) as amount,
                       coalesce(sum(pp.refund_amount), 0) as refund
                  from charge_payments pp
                 where pp.company_id = :cid and pp.paid_at >= :lo and pp.paid_at < :hi
                   and ({_PAY_WHERE[k.key]})
            """), p)).one()
            amount = float(row.amount or 0)
            # Для полного возврата «деньги» — это возвращённая сумма, а не списание.
            shown = float(row.refund or 0) if k.key == "refund_full" else amount
            items.append({"key": k.key, "label": k.label, "hint": k.hint,
                          "count": int(row.n or 0), "amount": round(shown, 2),
                          "paid": round(amount, 2), "gap": 0.0})
            continue
        if k.key == "orphan":
            row = (await db.execute(text("""
                select count(*) as n, coalesce(sum(pp.amount), 0) as amount
                  from charge_payments pp
                 where pp.company_id = :cid and pp.paid_at >= :lo and pp.paid_at < :hi
                   and pp.bank_txn_id is not null
                   and not exists (select 1 from charge_sessions ss
                                    where ss.company_id = pp.company_id
                                      and ss.session_ext_id = pp.session_ext_id)
            """), p)).one()
        else:
            row = (await db.execute(text(f"""
                select count(*) as n,
                       coalesce(sum(coalesce(s.client_amount, s.amount)), 0) as amount,
                       coalesce(sum(pay.paid), 0) as paid
                {join} and ({_WHERE[k.key]})
            """), p)).one()
        paid = float(getattr(row, "paid", 0) or 0)
        amount = float(row.amount or 0)
        items.append({
            "key": k.key, "label": k.label, "hint": k.hint,
            "count": int(row.n or 0),
            "amount": round(amount, 2),          # начислено по сессиям
            "paid": round(paid if k.key != "orphan" else amount, 2),   # списано банком
            # Деньги, о которых спор. У сирот спорить не о чем — там всё списано.
            "gap": round(0.0 if k.key == "orphan" else amount - paid, 2),
        })

    return {
        "period": {"from": df.isoformat(), "to": dt.isoformat()},
        "totals": {
            "sessions": int(totals.sessions or 0),
            "amount": round(float(totals.amount or 0), 2),      # начислено по сессиям
            "paid": round(float(totals.paid or 0), 2),          # списано банком
            "energy_kwh": round(float(totals.energy or 0), 1),
            "bad_energy_kwh": round(float(totals.bad_energy or 0), 1),
            # Начислено рознице и оплачено картой — сопоставимые величины.
            "retail_amount": round(float(totals.retail_amount or 0), 2),
            # Корпоратив идёт по договору и в сверку эквайринга не входит.
            "corp_amount": round(float(totals.corp_amount or 0), 2),
            "gap": round(float(totals.retail_amount or 0) - float(totals.paid or 0), 2),
        },
        "kinds": items,
    }


async def reconciliation_list(db: AsyncSession, company_id, df: date, dt: date,
                              kind: str, limit: int = 200) -> list[dict[str, Any]]:
    """Строки одного расхождения — то, с чем идут разбираться."""
    lo, hi = _bounds(df, dt)
    p = {"cid": str(company_id), "lo": lo, "hi": hi, "maxkw": MAX_POWER_KW,
         "eps": MONEY_EPS, "lim": max(1, min(limit, 2000)), **acl_params()}

    if kind in _PAY_WHERE:
        rows = (await db.execute(text(f"""
            select pp.payment_ext_id as id, pp.session_ext_id as session,
                   s.station_name as station, pp.paid_at as at,
                   coalesce(s.energy_kwh, 0) as energy,
                   coalesce(s.amount, 0) as amount,
                   pp.amount as paid, (pp.receipt_url is not null) as receipt, 1 as payments,
                   null::numeric as power_kw,
                   -- Холд и возврат: без них строка «Полного возврата» показывает нули,
                   -- а сводка по нему считает именно возвращённое.
                   pp.hold_amount as hold, pp.refund_amount as refund
              from charge_payments pp
              left join charge_sessions s
                     on s.company_id = pp.company_id and s.session_ext_id = pp.session_ext_id
             where pp.company_id = :cid and pp.paid_at >= :lo and pp.paid_at < :hi
               and ({_PAY_WHERE[kind]})
             order by coalesce(pp.refund_amount, 0) + pp.amount desc limit :lim
        """), p)).mappings().all()
    elif kind == "orphan":
        rows = (await db.execute(text("""
            select pp.payment_ext_id as id, pp.session_ext_id as session, null as station,
                   pp.paid_at as at, 0 as energy, 0 as amount, pp.amount as paid,
                   (pp.receipt_url is not null) as receipt, 1 as payments
              from charge_payments pp
             where pp.company_id = :cid and pp.paid_at >= :lo and pp.paid_at < :hi
               and pp.bank_txn_id is not null
               and not exists (select 1 from charge_sessions ss
                                where ss.company_id = pp.company_id
                                  and ss.session_ext_id = pp.session_ext_id)
             order by pp.amount desc limit :lim
        """), p)).mappings().all()
    else:
        join = _SESSION_JOIN.format(acl=acl_sql("s.location_id"))
        order = ("abs(s.amount - pay.paid) desc" if kind in ("underpaid", "double")
                 else ("s.energy_kwh desc" if kind == "impossible" else "s.amount desc"))
        rows = (await db.execute(text(f"""
            select s.session_ext_id as id, s.session_ext_id as session,
                   s.station_name as station, s.started_at as at,
                   s.energy_kwh as energy, coalesce(s.client_amount, s.amount) as amount,
                   pay.paid as paid, (pay.receipts > 0) as receipt, pay.pay_ok as payments,
                   case when s.duration_min > 0 and s.energy_kwh > 0
                        then round((s.energy_kwh / (s.duration_min / 60.0))::numeric, 1) end as power_kw
            {join} and ({_WHERE[kind]})
            order by {order} limit :lim
        """), p)).mappings().all()

    return [{
        "id": r["id"], "session": r["session"], "station": r["station"],
        "at": r["at"].isoformat() if r["at"] else None,
        "energy": round(float(r["energy"] or 0), 2),
        "amount": round(float(r["amount"] or 0), 2),
        "paid": round(float(r["paid"] or 0), 2),
        "gap": round(float(r["amount"] or 0) - float(r["paid"] or 0), 2),
        "receipt": bool(r["receipt"]), "payments": int(r["payments"] or 0),
        "powerKw": float(r["power_kw"]) if r.get("power_kw") is not None else None,
        "hold": float(r["hold"]) if r.get("hold") is not None else None,
        "refund": float(r["refund"]) if r.get("refund") is not None else None,
    } for r in rows]


# Разрезы расхождений. Вопрос «где не сходится» задают по-разному: сервису важна
# станция, финансам — месяц и клиент, эксплуатации — тип разъёма и канал запуска.
BY_DIMS = {
    "station": "coalesce(s.station_code, '—')",
    "region": "coalesce(r.name, s.region, '—')",
    "month": "to_char(s.started_at, 'YYYY-MM')",
    "connector": "coalesce(s.connector_type, '—')",
    "charge_type": "coalesce(s.charge_type, '—')",
    "client": "coalesce(s.client_name, 'Розница')",
    "card_status": "coalesce(s.card_status, '—')",
}


async def reconciliation_by(db: AsyncSession, company_id, df: date, dt: date,
                            by: str = "station", limit: int = 100) -> list[dict[str, Any]]:
    """Где копятся расхождения: разрез сверки по выбранному измерению.

    Список расхождений отвечает «какие строки битые», этот разрез — «где именно».
    Станция, у которой из месяца в месяц лезут сессии против физики, — это не
    случайность в данных, а неисправный счётчик или контроллер."""
    lo, hi = _bounds(df, dt)
    p = {"cid": str(company_id), "lo": lo, "hi": hi, "maxkw": MAX_POWER_KW,
         "eps": MONEY_EPS, "lim": max(1, min(limit, 500)), **acl_params()}
    # Регион берём из справочника объектов: в самих сессиях он денормализован и
    # написан по-разному (87 написаний на 48 субъектов).
    # По станции группируем ПО КОДУ — он идентичность станции, имя может меняться
    # (волна переименований CPO). Подпись собираем как в разрезах: «Имя (код)»,
    # чтобы строки этого разреза соединялись со списками «Надёжности».
    dim = BY_DIMS.get(by, BY_DIMS["station"])
    join_dim = ("""
        left join service_locations l on l.id = s.location_id
        left join regions r on r.id = l.region_id
    """ if by == "region" else "")

    rows = (await db.execute(text("""
        select {dim} as label,
               max(s.station_name) as station_name,
               count(*) as sessions,
               coalesce(sum(coalesce(s.client_amount, s.amount)), 0) as amount,
               coalesce(sum(s.amount) filter (where s.client_name is null), 0) as retail_amount,
               coalesce(sum(coalesce(s.client_amount, 0)) filter (
                   where s.client_name is not null), 0) as corp_amount,
               coalesce(sum(pay.paid), 0) as paid,
               -- Энергия рядом с деньгами: битые строки завышают не только
               -- выручку, но и отпуск — в отчётности это разные показатели.
               coalesce(sum(s.energy_kwh), 0) as energy,
               coalesce(sum(s.energy_kwh) filter (
                   where s.duration_min > 0 and s.energy_kwh > 0
                     and s.energy_kwh / (s.duration_min / 60.0) > :maxkw), 0) as impossible_energy,
               count(*) filter (where s.duration_min > 0 and s.energy_kwh > 0
                                  and s.energy_kwh / (s.duration_min / 60.0) > :maxkw) as impossible,
               coalesce(sum(coalesce(s.client_amount, s.amount)) filter (
                   where s.duration_min > 0 and s.energy_kwh > 0
                     and s.energy_kwh / (s.duration_min / 60.0) > :maxkw), 0) as impossible_amount,
               count(*) filter (where pay.pay_ok > 0 and s.amount - pay.paid > :eps) as underpaid,
               count(*) filter (where pay.pay_ok > 1) as multi,
               count(*) filter (where pay.pay_ok > 0 and pay.receipts = 0) as no_receipt,
               -- Месяцы, в которых у этой станции были расхождения. Разовый сбой
               -- и хроника лечатся по-разному: первое — правка строки, второе —
               -- выезд к оборудованию.
               count(distinct date_trunc('month', s.started_at)) filter (
                   where (s.duration_min > 0 and s.energy_kwh > 0
                          and s.energy_kwh / (s.duration_min / 60.0) > :maxkw)
                      or (pay.pay_ok > 0 and s.amount - pay.paid > :eps)) as bad_months,
               count(distinct date_trunc('month', s.started_at)) as months
          from charge_sessions s
          left join lateral (
              select coalesce(sum(pp.amount) filter (where pp.bank_txn_id is not null), 0) as paid,
                     count(*) filter (where pp.bank_txn_id is not null)                    as pay_ok,
                     count(pp.receipt_url) filter (where pp.bank_txn_id is not null)       as receipts
                from charge_payments pp
               where pp.company_id = s.company_id and pp.session_ext_id = s.session_ext_id
          ) pay on true
          {join_dim}
         where s.company_id = :cid and s.started_at >= :lo and s.started_at < :hi{acl}
         group by 1
        having count(*) filter (where s.duration_min > 0 and s.energy_kwh > 0
                                  and s.energy_kwh / (s.duration_min / 60.0) > :maxkw) > 0
            or abs(coalesce(sum(s.amount) filter (where s.client_name is null), 0)
                   - coalesce(sum(pay.paid), 0)) > :eps
         order by abs(coalesce(sum(s.amount) filter (where s.client_name is null), 0)
                      - coalesce(sum(pay.paid), 0)) desc
         limit :lim
    """.format(acl=acl_sql("s.location_id"), dim=dim, join_dim=join_dim)),
        p)).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        amount, paid = float(r["amount"] or 0), float(r["paid"] or 0)
        retail = float(r["retail_amount"] or 0)
        corp = float(r["corp_amount"] or 0)
        code = r["label"] if by == "station" else None
        energy = float(r["energy"] or 0)
        bad_energy = float(r["impossible_energy"] or 0)
        label = (f"{(r['station_name'] or 'Станция').strip()} ({code})"
                 if by == "station" else r["label"])
        out.append({
            "label": label, "code": code, "sessions": int(r["sessions"]),
            "amount": round(amount, 2), "paid": round(paid, 2),
            "retailAmount": round(retail, 2), "corpAmount": round(corp, 2),
            "gap": round(retail - paid, 2),
            "gapPct": round((retail - paid) / retail * 100, 1) if retail else 0.0,
            "impossible": int(r["impossible"]),
            "impossibleAmount": round(float(r["impossible_amount"] or 0), 2),
            "energy": round(energy, 1),
            "impossibleEnergy": round(bad_energy, 1),
            "impossibleEnergyPct": round(bad_energy / energy * 100, 1) if energy else 0.0,
            "underpaid": int(r["underpaid"]), "multi": int(r["multi"]),
            "noReceipt": int(r["no_receipt"]),
            "badMonths": int(r["bad_months"] or 0), "months": int(r["months"] or 0),
            # Хроника: расхождения повторяются больше чем в одном месяце периода.
            "chronic": int(r["bad_months"] or 0) > 1,
        })
    return out
