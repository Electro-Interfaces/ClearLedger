"""Товарный отчёт материально ответственного лица в форме офиса.

Лист, к которому привыкла бухгалтерия ГИГ: остаток на начало, перечень
приходных документов с пятью оценками, расход выручкой кассы, остаток на конец.
Тот же лист печатает рабочее место станции (`edge/agent/internal/web/
tovarny_form.go`) — здесь он собирается по данным центра, то есть по любой
станции сети и за любой период, в том числе за время, когда агента на станции
ещё не было.

⚠ Весь лист ведётся в РОЗНИЧНЫХ ценах: остаток на начало плюс розничная сумма
прихода даёт «Итого с остатком», и эту колонку бухгалтер складывает руками.
Себестоимость сюда не попадает вовсе — это другая величина.

⚠ Расход — выручка МАГАЗИНА по видам оплаты, БЕЗ ТОПЛИВА. Проверено цифрами
04.09.2026: на бумаге АЗС 8 за июль расход 1 137 850 ₽, а топлива станция за тот
же месяц отпустила на 18 583 107 ₽ — взяв кассу целиком, лист разошёлся бы с
бумагой в шестнадцать раз. Порядок подтверждён независимо по 208: магазин там
даёт 1,39 млн ₽ в месяц. Топливо учитывается своим контуром и в товарный отчёт
не входит. В баланс товара расход тоже не входит — остаток на конец считается по
остаткам товара, а не выводится вычитанием.

⚠⚠ Остатки центр умеет показать ТОЛЬКО на дату снимка: `store_stock_balances`
хранит последнее состояние станции, приёмник затирает предыдущее (на 04.09.2026
там одна дата и одна станция — 208). Поэтому остаток на границу периода даётся,
только если снимок в неё попадает; иначе на листе стоит прочерк и строка-
пояснение, а не ноль. Ноль здесь читался бы как «товара не было», и лист ушёл
бы в бухгалтерию с ложью. Чтобы центр печатал остатки за прошлые месяцы, нужна
история снимков — это отдельная работа над приёмником.

⚠ Розничная цена берётся из снимка остатков (`retail_price`), то есть та, что
стояла на момент снимка. Истории цен ни станция, ни центр не ведут.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .store_reports import _остатки_карточек, _период


async def _остаток_в_рознице(db: AsyncSession, cid, на: datetime,
                             stations: list[int] | None) -> float | None:
    """Стоимость запаса станций в розничных ценах на момент.

    None — снимка на этот момент нет. Ноль вернуть нельзя: на листе он читается
    как «товара не было», а это ложь, уходящая в бухгалтерию.
    """
    p = {"cid": cid, "na": на}
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations
    row = (await db.execute(text(f"""
        SELECT count(*) AS строк, coalesce(sum(quantity * retail_price), 0) AS s
        FROM ({_остатки_карточек(ф, " AND snapshot_at <= :na")}) t
    """), p)).mappings().first()
    if not row or not row["строк"]:
        return None
    return round(float(row["s"] or 0), 2)


# Коды видов оплаты кассы NeftoMS. Тот же справочник, что у станции
# (edge/agent/internal/store/basket_analysis.go, НазваниеОплаты): лист обязан
# называть оплату одинаково в центре и на АЗС. Карты зовутся «Банковская
# карта», а не «МПС» — решение МАГа 01.09.2026.
_ОПЛАТЫ = {1: "Наличные", 5: "Банковская карта", 26: "Банковская карта",
           20: "Бонусная карта", 16: "Купон", 27: "Дисконт"}


def _пустая(имя: str, kind: str) -> dict:
    return {"name": имя, "date": "", "number": "", "purchase": None,
            "net": None, "vat": None, "margin": None, "retail": None,
            "kind": kind}


async def goods_report(db: AsyncSession, cid, date_from, date_to,
                       stations: list[int] | None = None) -> dict:
    """Строки листа офиса: остаток, приход по документам, расход, остаток."""
    d1, d2 = _период(date_from, date_to)
    p = {"cid": cid, "d1": d1, "d2": d2}
    ф = " AND station_id = ANY(:st)" if stations else ""
    if stations:
        p["st"] = stations

    начало = await _остаток_в_рознице(db, cid, d1, stations)
    конец = await _остаток_в_рознице(db, cid, d2, stations)

    # Приход. Пять оценок бумаги считаются по строкам самой накладной: сумма с
    # НДС — закупочная, розничная — принятое количество по розничной цене.
    приход: list[dict] = []
    for r in (await db.execute(text(f"""
        SELECT station_id, doc_date,
               coalesce(nullif(incoming_number, ''), number) AS doc_number,
               supplier, lines
        FROM store_receipts
        WHERE company_id = :cid{ф} AND status = 'accepted'
          AND doc_date BETWEEN :d1 AND :d2
        ORDER BY doc_date, number
    """), p)).mappings().all():
        закуп = ндс = розница = 0.0
        for l in r["lines"] or []:
            кол = float(l.get("qty_fact") or 0)
            закуп += float(l.get("amount") or 0)
            ндс += float(l.get("vat_amount") or 0)
            розница += кол * float(l.get("retail_price") or 0)
        приход.append({
            "station_id": r["station_id"],
            "name": r["supplier"] or "—",
            "date": r["doc_date"].strftime("%d.%m.%Y") if r["doc_date"] else "",
            "number": r["doc_number"] or "",
            "purchase": round(закуп, 2), "net": round(закуп - ндс, 2),
            "vat": round(ндс, 2), "margin": round(розница - закуп, 2),
            "retail": round(розница, 2),
        })

    # Расход — выручка кассы по видам оплаты. Возвраты вычитаются: в кассе
    # выручка уже уменьшена на них, и лист обязан показывать те же деньги.
    выручка: dict[str, float] = {}
    for r in (await db.execute(text(f"""
        SELECT pay_type,
               coalesce(nullif(pay_name, ''), '') AS pay_name,
               coalesce(sum(CASE WHEN is_return THEN -abs(total) ELSE total END), 0) AS amount
        FROM store_cheques
        WHERE company_id = :cid{ф} AND at BETWEEN :d1 AND :d2
        GROUP BY pay_type, pay_name
    """), p)).mappings().all():
        # Имя из кассы приходит не всегда: по 208 pay_name пуст у всех чеков, и
        # без справочника вся выручка склеивалась в одно «Прочее». Виды сводим
        # по имени — коды 5 и 26 обе «Банковская карта», это одна строка листа.
        имя = (r["pay_name"] or _ОПЛАТЫ.get(r["pay_type"])
               or f"Код оплаты {r['pay_type']}")
        выручка[имя] = выручка.get(имя, 0.0) + float(r["amount"] or 0)

    оплаты = sorted(
        [{"name": имя, "amount": round(сумма, 2)}
         for имя, сумма in выручка.items() if round(сумма, 2) != 0],
        key=lambda x: -x["amount"])

    итого = {
        "purchase": round(sum(д["purchase"] for д in приход), 2),
        "net": round(sum(д["net"] for д in приход), 2),
        "vat": round(sum(д["vat"] for д in приход), 2),
        "margin": round(sum(д["margin"] for д in приход), 2),
        "retail": round(sum(д["retail"] for д in приход), 2),
    }
    расход = round(sum(о["amount"] for о in оплаты), 2)

    def свод(имя: str, kind: str = "итог", **знач) -> dict:
        строка = _пустая(имя, kind)
        строка.update(знач)
        return строка

    строки: list[dict] = [
        свод(f"Остаток на {d1.strftime('%d.%m.%Y')} 0:00:00",
             "остаток", retail=начало),
        _пустая("Приход", "раздел"),
    ]
    строки += [{**д, "kind": "документ"} for д in приход]
    # Счёт 60 — расчёты с поставщиками, счёт 71 — подотчётные лица. Приход в
    # сети идёт по накладным, поэтому 71 остаётся пустой строкой: на листе
    # офиса её тоже печатают — по ней ищут глазами.
    строки.append(свод("Итого по счету 60", **итого))
    строки.append(свод("Итого по счету 71"))
    строки.append(свод("Итого по приходу", **итого))
    строки.append(свод("Итого с остатком",
                       retail=None if начало is None
                       else round(начало + итого["retail"], 2)))
    строки.append(_пустая("Расход", "раздел"))
    строки += [свод(о["name"], "документ", retail=о["amount"]) for о in оплаты]
    строки.append(свод("Итого по расходу", retail=расход))
    строки.append(свод("Итого по расходу (без учета скидок)", retail=расход))
    строки.append(свод(f"Остаток на {d2.strftime('%d.%m.%Y')} 23:59:59",
                       "остаток", retail=конец))
    # Молчащий прочерк объяснить некому: строку-пояснение печатаем прямо на
    # листе, рядом с графой, где бухгалтер ждёт число.
    if начало is None or конец is None:
        строки.append(_пустая(
            "Остаток на эту дату центр не знает: снимок остатков станции хранится "
            "только последний. Остатки за прошлый период печатает рабочее место "
            "станции — там движения лежат целиком.", "сноска"))

    return {
        "rows": строки, "total": len(строки),
        "opening": начало, "closing": конец,
        "incoming": итого,
        # Плоским полем — панель отчёта показывает итоги по именам полей верхнего
        # уровня, вложенное incoming.retail она не достанет.
        "incoming_retail": итого["retail"], "expense": расход,
        "payments": оплаты, "documents": len(приход),
        "period": {"from": d1.strftime("%d.%m.%Y"), "to": d2.strftime("%d.%m.%Y")},
    }
