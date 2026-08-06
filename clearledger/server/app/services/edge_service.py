from datetime import date, datetime, timedelta, timezone
"""
Теневая сверка Ledger Edge: пакет агента станции против пакета ЦБ (1С).

Этап v0 проекта Edge: агент собирает смену напрямую из кассы, 1С делает то же
самое своим путём. Пока оба источника не сойдутся 14 дней подряд, переключать
контур нельзя — эта сверка и есть критерий.

Сопоставление по номеру смены: оба источника формируют его одинаково
(2082083007202601 = АЗС+АЗС+ддММгггг+01).
"""
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgePacket

AGENT_SOURCE_PREFIX = "Edge Agent"
MONEY_TOLERANCE = 0.01   # копеечные округления
QTY_TOLERANCE = 0.001


def _is_agent(source: str | None) -> bool:
    return bool(source) and source.startswith(AGENT_SOURCE_PREFIX)


def _retail_doc(payload: dict) -> dict | None:
    for doc in payload.get("Документы") or []:
        if isinstance(doc, dict) and doc.get("Тип") == "retail_sale_sidegoods":
            return doc
    return None


def _canon(uid, aliases: dict[str, str] | None) -> str:
    """Привести карточку к канонической: касса и 1С знают её под разными UUID.

    На 208 живут пары вроде «Американо 200 мл» и «Американо 200 мл.» — один
    товар, две карточки, потому что справочники расходились годами. Сверка,
    не знающая об этом, каждый день показывает расхождение там, где продан
    один и тот же кофе.
    """
    u = str(uid or "")
    return (aliases or {}).get(u, u)


def _by_item(doc: dict, aliases: dict[str, str] | None = None) -> dict[str, list[float]]:
    """Свернуть строки документа по номенклатуре: количество, сумма, НДС.

    Детализация строк у источников разная по построению (агент знает код НС,
    1С — нет), поэтому сверять нужно агрегаты, а не построчное совпадение.
    """
    agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for row in doc.get("Товары") or []:
        v = agg[_canon(row.get("Номенклатура"), aliases)]
        v[0] += float(row.get("Количество") or 0)
        v[1] += float(row.get("Сумма") or 0)
        v[2] += float(row.get("СуммаНДС") or 0)
    for row in doc.get("ВозвращенныеТовары") or []:
        v = agg[_canon(row.get("Номенклатура"), aliases)]
        v[0] -= float(row.get("Количество") or 0)
        v[1] -= float(row.get("Сумма") or 0)
        v[2] -= float(row.get("СуммаНДС") or 0)
    return agg


def _payments(doc: dict) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for p in doc.get("Оплаты") or []:
        out[str(p.get("ВидОплаты"))] += float(p.get("Сумма") or 0)
    return dict(out)


def _empty_side() -> dict:
    return {"total": 0.0, "vat": 0.0, "rows": 0, "items": 0}


# Ставки, которых в 2026 году не существует. Их присылает ЦБ из карточек,
# заведённых при прошлых режимах налогообложения: «18% / 118%» — расчётная
# ставка эпохи НДС-18. Касса по таким товарам давно бьёт действующие 22%, и
# расхождение означает протухшую карточку в 1С, а не ошибку агента.
STALE_CB_VAT = {"НДС18_118", "НДС20", "НДС5"}


def _stale_cb_items(doc: dict) -> set[str]:
    return {r.get("Номенклатура") for r in (doc.get("Товары") or [])
            if r.get("СтавкаНДС") in STALE_CB_VAT}


def compare(agent: dict, cb: dict, aliases: dict[str, str] | None = None) -> dict:
    """Сравнить два пакета одной смены. Возвращает расхождения по существу.

    Набор ключей результата постоянен: вызывающий читает `agent`/`cb` всегда,
    в том числе когда сравнивать нечего (смена без продаж сопутки — такие в
    истории есть).
    """
    a_doc, c_doc = _retail_doc(agent), _retail_doc(cb)
    if a_doc is None or c_doc is None:
        missing = "агента" if a_doc is None else "ЦБ"
        return {"ok": False,
                "no_data": True,
                "issues": [f"в пакете {missing} нет документа продаж"],
                "agent": _empty_side(), "cb": _empty_side()}

    issues: list[str] = []
    a_total = float(a_doc.get("СуммаДокумента") or 0)
    c_total = float(c_doc.get("СуммаДокумента") or 0)
    if abs(a_total - c_total) > MONEY_TOLERANCE:
        issues.append(f"сумма документа: агент {a_total:.2f}, ЦБ {c_total:.2f}")

    a_vat = float(a_doc.get("СуммаНДС") or 0)
    c_vat = float(c_doc.get("СуммаНДС") or 0)
    vat_note = ""

    a_items, c_items = _by_item(a_doc, aliases), _by_item(c_doc, aliases)
    only_agent = sorted(set(a_items) - set(c_items))
    only_cb = sorted(set(c_items) - set(a_items))
    if only_agent:
        issues.append(f"номенклатур только у агента: {len(only_agent)} (напр. {only_agent[0]})")
    if only_cb:
        issues.append(f"номенклатур только у ЦБ: {len(only_cb)} (напр. {only_cb[0]})")

    # Позиции, по которым агент честно сказал «ставку взять неоткуда»: код
    # нефтесервера погашен и отдан другому товару, карточки в кассе уже нет.
    # Расхождение НДС по ним объяснимо и дефектом сборки не является — иначе
    # пара выведенных карточек навсегда закрывает критерий перехода.
    unknown_vat = {_canon(u, aliases) for u in (a_doc.get("СтавкаНеизвестна") or [])}
    stale_cb = {_canon(u, aliases) for u in _stale_cb_items(c_doc)}

    qty_diff = sum_diff = vat_diff = explained_vat = stale_vat = 0
    worst = None
    for uid in set(a_items) & set(c_items):
        a, c = a_items[uid], c_items[uid]
        if abs(a[0] - c[0]) > QTY_TOLERANCE:
            qty_diff += 1
        if abs(a[1] - c[1]) > MONEY_TOLERANCE:
            sum_diff += 1
            delta = abs(a[1] - c[1])
            if worst is None or delta > worst[1]:
                worst = (uid, delta)
        if abs(a[2] - c[2]) > MONEY_TOLERANCE:
            if uid in unknown_vat:
                explained_vat += 1
            elif uid in stale_cb:
                # У ЦБ ставка, которой больше нет. Считать это дефектом агента
                # нельзя: он присылает то, чем товар реально пробивается.
                stale_vat += 1
            else:
                vat_diff += 1
    if qty_diff:
        issues.append(f"расходится количество по {qty_diff} номенклатурам")
    if sum_diff:
        issues.append(f"расходится сумма по {sum_diff} номенклатурам"
                      + (f" (максимум {worst[1]:.2f} у {worst[0]})" if worst else ""))
    if vat_diff:
        issues.append(f"НДС: агент {a_vat:.2f}, ЦБ {c_vat:.2f}"
                      f" — расходится по {vat_diff} номенклатурам")
    if explained_vat:
        vat_note = (f"по {explained_vat} позициям ставка неизвестна агенту "
                    f"(код погашен, карточки в кассе нет)")
    if stale_vat:
        vat_note = ((vat_note + "; ") if vat_note else "") + (
            f"по {stale_vat} позициям в 1С недействующая ставка НДС — "
            f"карточку нужно поправить в справочнике")

    a_pay, c_pay = _payments(a_doc), _payments(c_doc)
    for kind in sorted(set(a_pay) | set(c_pay)):
        if abs(a_pay.get(kind, 0) - c_pay.get(kind, 0)) > MONEY_TOLERANCE:
            issues.append(f"оплата «{kind}»: агент {a_pay.get(kind, 0):.2f}, ЦБ {c_pay.get(kind, 0):.2f}")

    return {
        "ok": not issues,
        "issues": issues,
        "note": vat_note,
        "agent": {"total": round(a_total, 2), "vat": round(a_vat, 2),
                  "rows": len(a_doc.get("Товары") or []), "items": len(a_items)},
        "cb": {"total": round(c_total, 2), "vat": round(c_vat, 2),
               "rows": len(c_doc.get("Товары") or []), "items": len(c_items)},
    }


async def reconcile(db: AsyncSession, company_id, station_id: int | None = None,
                    limit: int = 60) -> dict:
    """Отчёт теневой сверки по всем сменам, где есть оба пакета.

    Дубли карточек приводятся к канонической: пара «Американо 200 мл» и
    «Американо 200 мл.» — один товар в двух справочниках, и считать это
    расхождением каждый день бессмысленно.
    """
    aliases = {str(a): str(c) for a, c in (await db.execute(text("""
        SELECT alias_uuid, canonical_uuid FROM store_item_aliases WHERE company_id = :cid
    """), {"cid": company_id})).all()}
    # Только смены. Раньше фильтра не было, и в пары попадали часовые снимки
    # остатков и документы станции: у них свой заголовок «Смена» с внутренним
    # номером 0 и временем закрытия «сейчас», поэтому они всплывали наверх
    # списка и занимали 44 строки экрана сверки как «нет пакета ЦБ».
    q = select(EdgePacket).where(EdgePacket.company_id == company_id,
                                 EdgePacket.kind == "shift")
    if station_id is not None:
        q = q.where(EdgePacket.station_id == station_id)
    packets = (await db.execute(
        q.order_by(EdgePacket.shift_internal_no.desc().nullslast()).limit(limit * 4)
    )).scalars().all()

    # Пары ищем по ВНУТРЕННЕМУ номеру смены (номер смены кассы): он одинаков у
    # обоих источников и не зависит от того, по какой дате смену назвали.
    # Строковый номер вида 2082082704202601 для этого не годится — до июня 2026
    # смены шли сутками с утра на утро, ЦБ называл их по дате открытия, агент по
    # дате закрытия, и весь ряд сходился со сдвигом на одну смену.
    # Запасной ключ — строковый номер: у старых пакетов внутреннего может не быть.
    pairs: dict[tuple[int, str], dict] = {}
    for p in packets:
        key = (p.station_id, str(p.shift_internal_no or p.shift_number or ""))
        slot = pairs.setdefault(key, {})
        side = "agent" if _is_agent(p.source) else "cb"
        # Одна смена может быть выгружена ЦБ несколько раз (перевыгрузки).
        # Берём самый свежий пакет — он и уехал в БП.
        prev = slot.get(side)
        if prev is None or (p.received_at or 0) >= (prev.received_at or 0):
            slot[side] = p

    def order(item) -> str:
        """Порядок — по дате закрытия смены, а не по её номеру.

        Номера у источников разной длины: внутренний счётчик кассы (7063) и
        строковый номер смены (2082081806202601). Сравнение их как чисел ставило
        июньские смены впереди августовских, и «последняя смена» оказывалась
        трёхмесячной давности — серия чистых дней считалась не с того конца.
        """
        любой = item[1].get("agent") or item[1].get("cb")
        сведения = (любой.payload or {}).get("Смена") or {}
        return str(сведения.get("Закрытие") or сведения.get("Открытие") or "")

    shifts, matched, mismatched = [], 0, 0
    for (station, internal), slot in sorted(pairs.items(), key=order, reverse=True):
        agent_p, cb_p = slot.get("agent"), slot.get("cb")
        any_p = agent_p or cb_p
        сведения = (any_p.payload or {}).get("Смена") or {}
        row = {"station_id": station, "shift": any_p.shift_number or internal,
               "internal": internal,
               "closed_at": сведения.get("Закрытие"),
               "opened_at": сведения.get("Открытие")}
        if not agent_p or not cb_p:
            row.update(status="нет пары",
                       detail="нет пакета ЦБ" if agent_p else "нет пакета агента")
            shifts.append(row)
            continue
        res = compare(agent_p.payload, cb_p.payload, aliases)
        if not res.get("no_data"):
            matched += res["ok"]
            mismatched += not res["ok"]
        row.update(status="совпало" if res["ok"]
                          else ("нет данных" if res.get("no_data") else "расхождение"),
                   issues=res["issues"], agent=res["agent"], cb=res["cb"])
        if res.get("note"):
            row["note"] = res["note"]
        shifts.append(row)
        if len(shifts) >= limit:
            break

    streak = _streak(shifts)
    return {
        "station_id": station_id,
        "shifts_compared": matched + mismatched,
        "matched": matched,
        "mismatched": mismatched,
        # clean по ВСЕЙ истории — справочная величина: она включает апрель, когда
        # агента ещё не существовало, и потому почти всегда False.
        "clean": mismatched == 0 and matched > 0,
        "criterion": streak,
        "shifts": shifts,
    }


def _shift_date(row: dict) -> str | None:
    """Дата смены — по закрытию: смена принадлежит дню, в который её сдали."""
    for key in ("closed_at", "opened_at"):
        v = row.get(key)
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
    return None


def _streak(shifts: list[dict], today: date | None = None) -> dict:
    """Серия чистых дней подряд — критерий перехода к следующему этапу.

    Считается от свежего дня назад. Единица счёта — ДЕНЬ, а не смена: на 208 их
    бывает три, и засчитывать день по одной сошедшейся значит закрывать глаза на
    остальные.

    Дни обязаны идти ПОДРЯД по календарю. Первая версия считала «чистые дни в
    списке» и перешагивала дыры: в окне 19.06–30.07 набралось 30 засчитанных
    дней при 42 календарных — двенадцать дней (25.06–06.07) не сверялись вовсе,
    потому что ЦБ за них не выгружался. Серия с дырами ничего не доказывает:
    «14 дней подряд» именно про непрерывность.

    И серия обязана быть СВЕЖЕЙ. Иначе критерий показывает «выполнен» на
    исторических данных, тогда как сверки нет уже три дня — ровно это и
    случилось 02.08, когда met=true стоял при последнем проверенном дне 30.07.

    Что серию не рвёт, потому что не говорит о качестве агента: отсутствие
    пакета ЦБ (его выгружают руками) и пакет без документа продаж — сравнивать
    нечего. Но и в зачёт такие дни не идут: непроверенный день не может
    доказывать исправность.
    """
    дни: dict[str, list[str]] = {}
    for row in shifts:
        д = _shift_date(row)
        if д is None:
            continue
        st = row["status"]
        if st == "нет данных":
            continue
        if st == "нет пары" and row.get("detail") == "нет пакета ЦБ":
            continue
        дни.setdefault(д, []).append(st)

    подряд: list[str] = []
    сорвала = None
    ожидаемый: date | None = None
    for д in sorted(дни, reverse=True):
        текущий = date.fromisoformat(д)
        if ожидаемый is not None and текущий != ожидаемый:
            # Между днями провал: за пропущенные даты сверки не было.
            сорвала = {"дата": ожидаемый.isoformat(), "статус": "не сверялось",
                       "смен_в_дне": 0}
            break
        плохие = [st for st in дни[д] if st != "совпало"]
        if плохие:
            сорвала = {"дата": д, "статус": плохие[0], "смен_в_дне": len(дни[д])}
            break
        подряд.append(д)
        ожидаемый = текущий - timedelta(days=1)

    свежесть = None
    if подряд:
        сегодня = today or datetime.now(timezone.utc).date()
        отставание = (сегодня - date.fromisoformat(подряд[0])).days
        if отставание > 1:
            свежесть = f"последний сверенный день — {подряд[0]}, отставание {отставание} дн."

    return {
        "target_days": 14,
        "days": len(подряд),
        # Серия на исторических данных критерий не закрывает: он о том, что
        # канал сходится СЕЙЧАС.
        "met": len(подряд) >= 14 and свежесть is None,
        "from": подряд[-1] if подряд else None,
        "to": подряд[0] if подряд else None,
        "stale": свежесть,
        "broken_by": сорвала,
    }


# ---------------------------------------------------------------------------
# Сверочный контур «касса ↔ учёт» (Этап 2)
# ---------------------------------------------------------------------------
# Отвечает на вопросы, которые станция задаёт письмами: почему товар с полки
# не пробивается, где расходятся остатки, какие позиции пропали из кассы.

# Ставки, допустимые на станции: 22% основная, 10% продукты, 0 у служебных
# позиций кассы. Всё остальное — дефект НСИ: 18/20 остались с прошлых лет,
# 5/7 (ставки УСН) попадают в карточки по ошибке и уезжают в БП неверным НДС.
# Отрицательная ставка сюда не относится — так касса метит ингредиенты
# общепита, которые списываются по ТТК в момент продажи блюда (общепит целиком
# идёт по 22%).
VALID_VAT = {0.0, 10.0, 22.0}


def _stock_doc(payload: dict) -> dict | None:
    for doc in payload.get("Документы") or []:
        if isinstance(doc, dict) and doc.get("Тип") == "stock_snapshot":
            return doc
    return None


def analyze_stock(doc: dict) -> dict:
    """Сравнить кассу и учёт одного снимка."""
    cash_rows = doc.get("Касса") or []
    book_rows = doc.get("Учет") or []

    # Учёт ведётся по (номенклатура, ШК, цена) — для кассы важен ШК.
    book_by_barcode: dict[str, float] = defaultdict(float)
    book_by_item: dict[str, float] = defaultdict(float)
    book_name: dict[str, str] = {}
    negatives = []
    for r in book_rows:
        bc = str(r.get("ШтрихКод") or "")
        qty = float(r.get("Остаток") or 0)
        uid = str(r.get("Номенклатура") or "")
        book_by_barcode[bc] += qty
        book_by_item[uid] += qty
        book_name[uid] = str(r.get("Наименование") or "")
        if qty < 0:
            negatives.append({"item": uid, "name": r.get("Наименование"),
                              "barcode": bc, "qty": round(qty, 3)})

    # Касса: сначала собираем итоги по карточке, потом ищем непродаваемое.
    #
    # Считать «товар есть, продать нельзя» по ОТДЕЛЬНОЙ строке кассы нельзя: у
    # карточки бывает несколько кодов НС и несколько штрихкодов, и нулевая
    # строка одного кода при живом остатке по другому давала ложную тревогу.
    # Обратная ошибка тоже была: центр агрегировал по ШК, агент — по карточке,
    # и на одном и том же снимке они выдавали 1 и 9 проблемных позиций.
    # Правда — по карточке: продаётся товар, а не строка таблицы.
    cash_by_barcode: dict[str, float] = defaultdict(float)
    cash_by_item: dict[str, float] = defaultdict(float)
    for r in cash_rows:
        cash_by_barcode[str(r.get("ШтрихКод") or "")] += float(r.get("Остаток") or 0)
        cash_by_item[str(r.get("Номенклатура") or "")] += float(r.get("Остаток") or 0)

    cannot_sell, no_price, stale_vat = [], [], []
    видели: set[str] = set()
    for r in cash_rows:
        bc = str(r.get("ШтрихКод") or "")
        uid = str(r.get("Номенклатура") or "")
        qty = float(r.get("Остаток") or 0)
        # «Товар есть, продать нельзя»: по карточке в кассе ноль, в учёте остаток.
        if uid and uid not in видели and cash_by_item[uid] <= 0 and book_by_item.get(uid, 0) > 0:
            видели.add(uid)
            cannot_sell.append({"ns_code": r.get("КодНС"), "barcode": bc,
                                "name": r.get("Наименование"),
                                "book_qty": round(book_by_item[uid], 3)})
        if qty > 0 and float(r.get("Цена") or 0) <= 0:
            no_price.append({"ns_code": r.get("КодНС"), "name": r.get("Наименование"),
                             "qty": round(qty, 3)})
        vat = float(r.get("СтавкаНДСПроцент") or 0)
        if vat >= 0 and vat not in VALID_VAT:
            stale_vat.append({"ns_code": r.get("КодНС"), "name": r.get("Наименование"),
                              "vat": r.get("СтавкаНДСПроцент")})

    # Учёт есть, а в кассе такого ШК нет вовсе — товар не доехал до кассы.
    missing_in_cash = []
    for uid, qty in book_by_item.items():
        if qty > 0 and uid and uid not in cash_by_item:
            missing_in_cash.append({"item": uid, "name": book_name.get(uid, ""),
                                    "qty": round(qty, 3)})

    # Расхождение количеств по общим ШК.
    qty_diff = []
    for bc, cash_qty in cash_by_barcode.items():
        if not bc or bc not in book_by_barcode:
            continue
        delta = cash_qty - book_by_barcode[bc]
        if abs(delta) > 0.001:
            qty_diff.append({"barcode": bc, "cash": round(cash_qty, 3),
                             "book": round(book_by_barcode[bc], 3), "delta": round(delta, 3)})
    qty_diff.sort(key=lambda x: -abs(x["delta"]))

    return {
        "taken_at": doc.get("Момент"),
        "cash_positions": len(cash_rows),
        "book_rows": len(book_rows),
        "totals": {
            "cannot_sell": len(cannot_sell),
            "missing_in_cash": len(missing_in_cash),
            "qty_mismatch": len(qty_diff),
            "negative_book": len(negatives),
            "no_price": len(no_price),
            "stale_vat": len(stale_vat),
        },
        "cannot_sell": cannot_sell[:50],
        "missing_in_cash": missing_in_cash[:50],
        "qty_mismatch": qty_diff[:50],
        "negative_book": sorted(negatives, key=lambda x: x["qty"])[:50],
        "no_price": no_price[:50],
        "stale_vat": stale_vat[:50],
    }


async def stock_report(db: AsyncSession, company_id, station_id: int) -> dict:
    """Свежий отчёт «касса ↔ учёт» по станции."""
    row = (await db.execute(
        select(EdgePacket)
        .where(EdgePacket.company_id == company_id,
               EdgePacket.station_id == station_id,
               EdgePacket.kind == "stock")
        .order_by(EdgePacket.received_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"station_id": station_id, "available": False,
                "detail": "снимков остатков ещё нет"}
    doc = _stock_doc(row.payload)
    if doc is None:
        return {"station_id": station_id, "available": False,
                "detail": "в последнем пакете нет снимка"}
    out = analyze_stock(doc)
    out["ns_pool"] = _pool(doc)
    out["station_id"] = station_id
    out["available"] = True
    out["received_at"] = row.received_at
    return out


# ---------------------------------------------------------------------------
# Алерты (шаг 2.4): то, что требует действия человека
# ---------------------------------------------------------------------------
# Смысл шага — заменить письма оператора «опять не пробивается» на утренний
# отчёт, который приходит ДО того, как станция это заметит.

NS_POOL_WARN = 200   # свободных кодов кассы меньше — новые товары под угрозой
NS_POOL_CRIT = 50


def _pool(doc: dict) -> dict:
    return doc.get("КодыНС") or {}


def build_alerts(stock: dict, recon: dict | None = None) -> list[dict]:
    """Собрать список того, что требует внимания, из отчётов сверки."""
    alerts: list[dict] = []
    if not stock.get("available"):
        return [{"level": "warning", "topic": "снимок",
                 "text": "нет свежего снимка остатков — агент не присылает данные"}]

    t = stock["totals"]
    if t["cannot_sell"]:
        alerts.append({
            "level": "critical", "topic": "касса",
            "text": f"товар есть в учёте, но касса не пробьёт: {t['cannot_sell']} позиций",
            "items": [f"{r['name']} (код {r['ns_code']}, учёт {r['book_qty']})"
                      for r in stock["cannot_sell"][:10]],
        })
    if t["missing_in_cash"]:
        alerts.append({
            "level": "critical", "topic": "выгрузка",
            "text": (f"{t['missing_in_cash']} позиций есть в учёте, но отсутствуют в "
                     "кассе — вероятно, не нажата «Загрузить ККМ»"),
            # Ключи те же, что кладёт analyze_stock: список считается по
            # карточке, а не по строке кассы. Здесь читались barcode и
            # book_qty — письмо падало ровно тогда, когда было о чём сообщить.
            "items": [f"{r.get('name') or r.get('item')}, учёт {r.get('qty')}"
                      for r in stock["missing_in_cash"][:10]],
        })
    if t["negative_book"]:
        alerts.append({
            "level": "warning", "topic": "учёт",
            "text": f"минусы в физике склада: {t['negative_book']} позиций",
            "items": [f"{r['name']}: {r['qty']}" for r in stock["negative_book"][:5]],
        })
    if t["stale_vat"]:
        alerts.append({
            "level": "warning", "topic": "НСИ",
            "text": f"устаревшие ставки НДС в карточках: {t['stale_vat']}",
            "items": [f"{r['name']} — НДС {r['vat']}%" for r in stock["stale_vat"][:5]],
        })

    pool = stock.get("ns_pool") or {}
    free = pool.get("Свободно")
    if isinstance(free, int) and pool.get("Макс"):
        if free <= NS_POOL_CRIT:
            alerts.append({"level": "critical", "topic": "коды кассы",
                           "text": f"свободных кодов нефтесервера почти не осталось: {free}"})
        elif free < NS_POOL_WARN:
            alerts.append({"level": "warning", "topic": "коды кассы",
                           "text": f"свободных кодов нефтесервера мало: {free}"})

    if recon and recon.get("shifts_compared") and recon.get("mismatched"):
        bad = [s for s in recon["shifts"] if s.get("status") == "расхождение"]
        alerts.append({
            "level": "critical", "topic": "сверка смен",
            "text": f"расхождение агента и 1С по {recon['mismatched']} сменам",
            "items": [f"смена {s['shift']}: " + "; ".join(s.get("issues") or []) for s in bad[:5]],
        })
    return alerts


# Темы, которые умеет находить расчёт по снимку остатков. Сходимости смен
# среди них нет: снимок про неё ничего не знает и закрывать её не вправе.
STOCK_TOPICS = {"снимок", "касса", "выгрузка", "учёт", "НСИ", "коды кассы"}


async def sync_alerts(db: AsyncSession, company_id, station_id: int,
                      items: list[dict], topics: set[str] | None = None) -> list[dict]:
    """Запомнить находки как события: когда появились и когда ушли.

    `topics` ограничивает синхронизацию темами, которые данный расчёт вообще
    умеет находить: снимок остатков ничего не знает про сходимость смен, и
    закрывать её находку он не вправе — иначе расхождение «уходило» бы каждый
    час само собой.

    Возвращает те же находки, дополненные временем первого появления, — по
    нему видно, висит проблема третью неделю или возникла сегодня.
    """
    from app.models import StoreStationAlert   # локально: цикл импорта модулей

    now = datetime.now(timezone.utc)
    открытые = {r.topic: r for r in (await db.execute(select(StoreStationAlert).where(
        StoreStationAlert.company_id == company_id,
        StoreStationAlert.station_id == station_id,
        StoreStationAlert.resolved_at.is_(None)))).scalars().all()}

    видимые = {a["topic"] for a in items}
    for a in items:
        row = открытые.get(a["topic"])
        if row is None:
            row = StoreStationAlert(company_id=company_id, station_id=station_id,
                                    topic=a["topic"], first_seen=now)
            db.add(row)
        row.level = a["level"]
        row.text = a["text"][:500]
        row.items = a.get("items") or []
        row.last_seen = now
        a["first_seen"] = row.first_seen or now

    охват = topics if topics is not None else set(открытые) | видимые
    for topic, row in открытые.items():
        if topic not in видимые and topic in охват:
            row.resolved_at = now
    await db.commit()
    return items


async def alerts(db: AsyncSession, company_id, station_id: int,
                 remember: bool = True) -> dict:
    stock = await stock_report(db, company_id, station_id)
    recon = await reconcile(db, company_id, station_id, limit=20)
    items = build_alerts(stock, recon)
    if remember:
        items = await sync_alerts(db, company_id, station_id, items)
    return {
        "station_id": station_id,
        "critical": sum(1 for a in items if a["level"] == "critical"),
        "warnings": sum(1 for a in items if a["level"] == "warning"),
        "alerts": items,
        "shifts_clean": recon.get("clean"),
    }


def alerts_as_text(report: dict) -> str:
    """Текст для письма: коротко и по делу, без служебных полей."""
    lines = [f"АЗС {report['station_id']} — сводка Ledger Edge",
             f"критично: {report['critical']}, предупреждений: {report['warnings']}",
             f"сверка смен с 1С: {'чисто' if report.get('shifts_clean') else 'есть расхождения'}",
             ""]
    if not report["alerts"]:
        lines.append("Замечаний нет.")
    for a in report["alerts"]:
        mark = "!!" if a["level"] == "critical" else " *"
        lines.append(f"{mark} [{a['topic']}] {a['text']}")
        for it in a.get("items") or []:
            lines.append(f"      - {it}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Паритет с 1С
#
# Пока идёт параллельная работа, главный вопрос не «правильно ли мы считаем», а
# «всё ли мы вообще умеем». 1С на станции продолжает вести учёт, её пакеты
# приходят в мастер тем же каналом — и по ним видно, какие виды документов она
# создаёт и сколько. Наш результат виден рядом.
#
# Это не сверка сумм (её делает reconcile по сменам), а сверка ОХВАТА: чего мы
# ещё не делаем и где отстаём по количеству.

# Виды документов, которые агент умеет собирать. Список ведётся вручную и
# сверяется с контрактом пакета: без него измеритель путает «кода нет» с «такой
# операции ещё не делали», а это разные вещи — первое требует разработки,
# второе просто ждёт своего случая.
LEDGER_SUPPORTED = {
    "retail_sale_sidegoods", "purchase", "transfer", "inventory", "writeoff",
    "gain", "return_sale", "return_purchase", "production_release", "recipe",
    "stock_snapshot",
}

PARITY_TITLES = {
    "retail_sale_sidegoods": "продажи смены",
    "purchase": "приёмка от поставщика",
    "production_release": "выпуск продукции (общепит)",
    "ingredients_writeoff": "списание ингредиентов",
    "recipe": "техкарты блюд",
    "transfer": "перемещение",
    "inventory": "инвентаризация",
    "writeoff": "списание",
    "gain": "оприходование",
    "return_sale": "возврат покупателя",
    "return_purchase": "возврат поставщику",
    "stock_snapshot": "снимок остатков",
}


async def parity(db: AsyncSession, company_id, station_id: int, days: int = 30) -> dict:
    """Что 1С делает за период и что за тот же период делаем мы."""
    rows = (await db.execute(text("""
        WITH src AS (
            SELECT CASE WHEN p.source LIKE 'Edge%' THEN 'ledger' ELSE 'onec' END AS сторона,
                   d->>'Тип' AS вид,
                   -- Считаем ДОКУМЕНТЫ, а не вхождения в пакеты. Техкарты едут
                   -- вместе с каждым выпуском (так делает и 1С), поэтому 32
                   -- карты давали 840 «документов», и паритет по общепиту
                   -- выглядел трёхкратно полнее, чем есть. Ключ документа —
                   -- ИсточникUUID: он детерминирован и переживает пересборку
                   -- смены; для документов без него берём отпечаток содержимого.
                   coalesce(d->>'ИсточникUUID', md5(d::text)) AS ид,
                   coalesce((p.payload->'Смена'->>'Закрытие')::timestamptz,
                            p.received_at) AS момент
            FROM edge_packets p, jsonb_array_elements(p.payload->'Документы') d
            WHERE p.company_id = :cid AND p.station_id = :st
        )
        SELECT вид,
               count(DISTINCT ид) FILTER (WHERE сторона = 'onec')   AS onec_all,
               count(DISTINCT ид) FILTER (WHERE сторона = 'ledger') AS ledger_all,
               count(DISTINCT ид) FILTER (WHERE сторона = 'onec'   AND момент > now() - make_interval(days => :d)) AS onec_period,
               count(DISTINCT ид) FILTER (WHERE сторона = 'ledger' AND момент > now() - make_interval(days => :d)) AS ledger_period,
               max(момент) FILTER (WHERE сторона = 'onec')   AS onec_last,
               max(момент) FILTER (WHERE сторона = 'ledger') AS ledger_last
        FROM src GROUP BY вид ORDER BY onec_all DESC, вид
    """), {"cid": company_id, "st": station_id, "d": days})).mappings().all()

    виды = []
    покрыто = отсутствует = 0
    for r in rows:
        # Снимок остатков — наш собственный вид, у 1С аналога нет. В счёт
        # паритета он не идёт: это инструмент сверки, а не документ учёта.
        служебный = r["вид"] == "stock_snapshot"
        умеем = r["вид"] in LEDGER_SUPPORTED
        # «Было хоть раз» и «умеем» — разные ответы. Документ может быть
        # реализован и оттестирован, но на станции его ещё не заводили: так
        # выглядит оприходование, которое случается 48 раз в квартал.
        было = r["ledger_all"] > 0
        if not служебный and r["onec_all"] > 0:
            if умеем:
                покрыто += 1
            else:
                отсутствует += 1
        виды.append({
            "kind": r["вид"],
            "title": PARITY_TITLES.get(r["вид"], r["вид"]),
            "onec": r["onec_all"], "ledger": r["ledger_all"],
            "onec_period": r["onec_period"], "ledger_period": r["ledger_period"],
            "onec_last": r["onec_last"].isoformat() if r["onec_last"] else None,
            "ledger_last": r["ledger_last"].isoformat() if r["ledger_last"] else None,
            "covered": умеем, "used": было, "own": r["onec_all"] == 0,
        })
    return {
        "station_id": station_id, "days": days,
        "covered": покрыто, "missing": отсутствует,
        "kinds": виды,
    }
