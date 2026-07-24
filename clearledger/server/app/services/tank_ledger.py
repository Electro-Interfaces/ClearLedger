"""Книга резервуара: движение смена за сменой, книга против факта, контроль стыковки.

Что бухгалтер должен увидеть по каждому резервуару и почему:

**Книга** — документальный остаток. Считается арифметикой: остаток на начало
смены + слив по ТТН − отпуск через ТРК = остаток на конец. Проверено на данных
ГИГ: равенство держится в 94% записей, и начало каждой смены равно книжному
концу предыдущей в 95% переходов. То есть книга ведётся непрерывной цепочкой.

**Факт** — замер уровнемером на конец смены (секция `rest` отчёта STS). Меряется
независимо от книги и с ней расходится: у ГИГ отклонение больше 50 л в 59%
записей.

**Книга минус факт** — это и есть недостача (книга больше — топлива в резервуаре
меньше, чем должно быть) или излишек. Система НЕ подтягивает книгу к факту
автоматически: расхождение копится от смены к смене, пока инвентаризация не
спишет его документом. Поэтому важна не столько разница одной смены (её даёт
погрешность замера, температура, наклон резервуара), сколько накопленный тренд
за период — он отделяет естественную убыль от утечки, недолива поставщика или
пролива.

Три независимых контроля, каждый ловит свой класс проблем:

1. **Арифметика книги** внутри смены: (начало + приход − отпуск) − конец ≠ 0.
   Значит сам сменный отчёт внутренне противоречив — считать по нему нельзя.
2. **Стыковка смен**: начало смены ≠ конец предыдущей. Между сменами что-то
   произошло мимо учёта: правка на станции, пропущенная смена, подмена отчёта.
3. **Книга против факта**: расхождение замера с документом — предмет
   инвентаризации.

Разделять их обязательно: сумма расхождений без разбора причины — цифра, по
которой нельзя принять решение.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelReceipt, FuelShift, FuelStation, FuelTank

# Порог, ниже которого расхождение считаем шумом измерения, а не событием.
# Уровнемер даёт ±0,2–0,5% объёма; для типового резервуара 20–25 м³ это
# десятки литров. Порог применяется только к подсветке, в суммы входит всё.
ARITHMETIC_TOLERANCE_L = 0.5   # книга обязана сходиться точно — это арифметика
CONTINUITY_TOLERANCE_L = 0.5   # стык смен тоже арифметика, а не измерение
FACT_TOLERANCE_L = 50.0        # замер — измерение, у него есть погрешность


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _n(v: Any) -> float | None:
    return float(v) if v is not None else None


def _fuel_key(tank: FuelTank) -> str:
    if tank.fuel_code is not None:
        return f"code:{tank.fuel_code}"
    return f"name:{(tank.fuel_type or '—').strip().casefold()}"


# --- Классификация разрывов стыка -----------------------------------------
# Разрыв «книга на начало ≠ книга на конец предыдущей» — это НЕ один дефект.
# Разбор 774 разрывов ГИГ (авг-25…июл-26) дал пять разных причин, и топлива
# касается только последняя. Смешивать их нельзя: у каждой свой адресат —
# приёмка, служба эксплуатации, оператор станции или бухгалтер.
DELIVERY_TOLERANCE = 0.02      # ТТН признаём совпавшей при отклонении ≤2%
RENUMBER_DROP = 50             # номер смены упал больше чем на столько → сброс счётчика
LONG_PAUSE_HOURS = 36          # пауза между сменами, после которой цепочка рвётся штатно
MANUAL_ROUND_STEP = 50.0       # «круглый» разрыв — подпись человека, а не расходомера


def _is_round(v: float) -> bool:
    """Разрыв кратен 50 л — так правит человек, прибор такого не выдаёт."""
    return abs(v) >= MANUAL_ROUND_STEP and abs(v) % MANUAL_ROUND_STEP < 0.51


def _is_whole(v: float) -> bool:
    return abs(v - round(v)) < 0.05


def _manual_note(gap: float, book_start: float, prev_book_end: float) -> str | None:
    """Признак ручного ввода: разрыв ровно в целых литрах, тогда как сами остатки
    дробные. Книга и уровнемер дают десятые (1128,5 / 3249,2) — ровно целая
    разница при них берётся не из прибора, а с клавиатуры. На ГИГ целых разрывов
    603 из 774 (78%), из них 520 при дробных остатках; случайно ожидалось бы ~10%.
    """
    if not _is_whole(gap):
        return None
    if _is_round(gap):
        return f"ручная правка на {gap:+,.0f} л — круглое значение"
    if not _is_whole(book_start) or not _is_whole(prev_book_end):
        return (f"ручная правка на {gap:+,.0f} л — ровно целые литры "
                "при дробных остатках (ввод с клавиатуры, не прибор)")
    return None


def _classify_break(
    gap: float, *, book_start: float, prev_book_end: float, prev_fact: float | None,
    receipts_between: list[tuple[float, str]], shift_number: int, prev_shift_number: int,
    hours_gap: float | None, receipts_in_shift: float,
    receipts_linked: list[tuple[float, str]] | None = None,
) -> tuple[str, str]:
    """Тип разрыва + человеческая формулировка причины.

    Порядок проверок — от самой доказуемой причины к предположению.
    """
    # 1. Перенумерация смен: счётчик сброшен (станцию переустановили/заменили).
    #    ГИГ 01.07.2026: АЗС 9008 7360→2, АЗС 8 7361→4 — в один день, разрывы до 22 642 л.
    if prev_shift_number - shift_number > RENUMBER_DROP:
        return ("renumber", f"перенумерация смен: {prev_shift_number} → {shift_number}, "
                            "станция переустановлена — цепочка книги начата заново")
    # 2. Сброс книги в ноль (переинициализация учёта). ГИГ 29–30.03.2026:
    #    5 АЗС × 3 резервуара, 84 016 л, в тех же сменах отрицательный остаток.
    if book_start == 0 and prev_book_end > 100:
        return ("book_reset", "книга обнулена: начало смены 0 при остатке "
                              f"{prev_book_end:,.0f} л — переинициализация учёта на станции")
    # Обратная сторона того же сбоя: книга закрылась нулём, а следующая смена
    # открылась нормальным остатком. Без этой ветки «восстановление» выглядело
    # необъяснённым, хотя это второй шаг той же переинициализации.
    if prev_book_end == 0 and book_start > 100:
        return ("book_reset", f"книга восстановлена после обнуления: предыдущая смена "
                              f"закрыта нулём, эта открыта остатком {book_start:,.0f} л")
    if book_start < 0 or prev_book_end < 0:
        return ("book_reset", "отрицательный остаток в книге — отчёт недостоверен")
    # 3. Слив между сменами. Сначала — прямая привязка: накладная сама указывает
    #    смену и резервуар (секция `receipt` отчёта). Если приход в смене не
    #    отражён, а накладная на этот резервуар есть — объём ушёл в начальный
    #    остаток вместо прихода. Это доказательство, а не совпадение чисел.
    if gap > 0 and receipts_linked:
        for vol, ttn in receipts_linked:
            if vol > 0 and abs(vol - gap) <= max(1.0, gap * DELIVERY_TOLERANCE):
                return ("delivery", f"слив между сменами: накладная {ttn} на {vol:,.0f} л "
                                    "закреплена за этой сменой и резервуаром — объём попал "
                                    "в начальный остаток, а не в приход")
        if receipts_in_shift == 0:
            total = sum(v for v, _ in receipts_linked)
            if abs(total - gap) <= max(1.0, gap * DELIVERY_TOLERANCE):
                ttns = ", ".join(sorted({t for _, t in receipts_linked}))
                return ("delivery", f"слив между сменами: накладные {ttns} на {total:,.0f} л "
                                    "за смену, приход в резервуаре не отражён")
    # Запасной путь — по времени и объёму (для записей без привязки к смене).
    #    ГИГ АЗС 207 13.06: ТТН 9303 — АИ-92 10 431 л и АИ-95 8 210 л, литр в литр.
    if gap > 0 and receipts_between:
        for vol, ttn in receipts_between:
            if vol > 0 and abs(vol - gap) <= max(1.0, gap * DELIVERY_TOLERANCE):
                return ("delivery", f"слив между сменами: ТТН {ttn} на {vol:,.0f} л — "
                                    "объём не попал в приход закрытой смены")
    # 4. Книга подтянута к замеру: расхождение списано на станции молча.
    if prev_fact and abs(book_start - prev_fact) <= 1.0:
        return ("pulled_to_fact", f"книга подтянута к замеру ({prev_fact:,.0f} л): "
                                  "расхождение списано на станции, минуя инвентаризацию")
    # 5. Длинная пауза — смены за промежуток отсутствуют, сверять нечего.
    if hours_gap is not None and hours_gap > LONG_PAUSE_HOURS:
        return ("gap", f"пауза {hours_gap:,.0f} ч между сменами — смены за этот срок нет")
    # 6. Ручная правка: разрыв целым числом литров при дробных остатках.
    #    ГИГ АЗС 208/209/9008 — основная масса разрывов именно такая.
    note = _manual_note(gap, book_start, prev_book_end)
    if note:
        return ("manual", note + ("" if receipts_in_shift else " · прихода в смене не было"))
    return ("unexplained", "причина не установлена — требует разбора")


async def build_tank_ledger(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    station_codes: list[int] | None = None,
    tank_number: int | None = None,
    fuel_codes: list[int] | None = None,
    max_rows: int = 5000,
) -> dict[str, Any]:
    """Журнал движения по резервуарам за период + сводка и замечания."""
    dt_from = datetime(date_from.year, date_from.month, date_from.day)
    dt_to = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    q = (
        select(FuelTank, FuelShift, FuelStation)
        .join(FuelShift, FuelShift.id == FuelTank.shift_id)
        .join(FuelStation, FuelStation.id == FuelShift.station_id)
        .where(FuelShift.company_id == company_id,
               FuelShift.opened_at >= dt_from,
               FuelShift.opened_at <= dt_to)
        .order_by(FuelStation.code, FuelTank.tank_number,
                  FuelShift.opened_at, FuelShift.shift_number)
    )
    if station_codes:
        q = q.where(FuelStation.code.in_([int(c) for c in station_codes]))
    if tank_number is not None:
        q = q.where(FuelTank.tank_number == int(tank_number))
    if fuel_codes:
        q = q.where(FuelTank.fuel_code.in_([int(c) for c in fuel_codes]))

    records = (await db.execute(q)).all()

    # Накладные периода — чтобы отличить «слив между сменами» от настоящей потери.
    # Ключ — только станция + момент: поле `tank` в накладных ненадёжно (в одной
    # ТТН оба вида топлива бывают записаны на резервуар 1), поэтому совпадение
    # ищем по ОБЪЁМУ в интервале между сменами, а не по номеру резервуара.
    rq = (
        select(FuelReceipt, FuelStation.code)
        .join(FuelStation, FuelStation.id == FuelReceipt.station_id)
        .where(FuelReceipt.company_id == company_id,
               FuelReceipt.received_at >= dt_from - timedelta(days=2),
               FuelReceipt.received_at <= dt_to + timedelta(days=1))
    )
    if station_codes:
        rq = rq.where(FuelStation.code.in_([int(c) for c in station_codes]))
    receipts_by_station: dict[int, list[tuple[datetime, float, float, str]]] = defaultdict(list)
    # Прямая привязка (станция × смена × резервуар) — после миграции v4.9 накладные
    # знают свою смену и резервуар из секции `receipt` сменного отчёта. Это точное
    # доказательство слива, в отличие от подбора по времени и объёму.
    receipts_by_shift: dict[tuple[int, int, int], list[tuple[float, str]]] = defaultdict(list)
    for rec, st_code in (await db.execute(rq)).all():
        vol = _f(rec.fact_volume_liters) or _f(rec.doc_volume_liters)
        ttn = rec.ttn or "б/н"
        if rec.shift_number is not None and rec.tank is not None:
            receipts_by_shift[(int(st_code), int(rec.shift_number), int(rec.tank))].append((vol, ttn))
        if rec.received_at is None:
            continue
        receipts_by_station[int(st_code)].append((
            rec.received_at.replace(tzinfo=None) if rec.received_at.tzinfo else rec.received_at,
            _f(rec.doc_volume_liters), _f(rec.fact_volume_liters), ttn,
        ))

    def _receipts_between(st_code: int, since: datetime | None, until: datetime | None
                          ) -> list[tuple[float, str]]:
        """Объёмы накладных, закрытых в промежутке между сменами (± сутки на неточность
        отметки времени слива — на станции ТТН часто проводят задним числом)."""
        if since is None or until is None:
            return []
        # Смены приходят из БД с таймзоной, накладные приведены к naive — без
        # выравнивания сравнение падает (TypeError на offset-naive vs aware).
        since = since.replace(tzinfo=None) if since.tzinfo else since
        until = until.replace(tzinfo=None) if until.tzinfo else until
        lo, hi = since - timedelta(days=1), until + timedelta(days=1)
        out: list[tuple[float, str]] = []
        for at, doc_v, fact_v, ttn in receipts_by_station.get(st_code, ()):
            if lo <= at <= hi:
                out.append((fact_v or doc_v, ttn))
        return out

    # Группировка в цепочки по физическому резервуару (станция + номер).
    chains: dict[tuple[int, int], list[tuple[FuelTank, FuelShift, FuelStation]]] = defaultdict(list)
    for tank, shift, station in records:
        chains[(int(station.code), int(tank.tank_number))].append((tank, shift, station))

    rows: list[dict[str, Any]] = []
    tanks_summary: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for (station_code, tank_no), chain in sorted(chains.items()):
        prev: FuelTank | None = None
        prev_shift: FuelShift | None = None
        first = chain[0][0]
        station_name = chain[0][2].name or f"АЗС {station_code}"

        sum_receipts = sum_sales = 0.0
        sum_mass_receipts = sum_mass_sales = 0.0
        arithmetic_breaks = continuity_breaks = fact_breaks = 0
        # Разрывы этой цепочки — для пост-прохода по зеркальным возвратам.
        chain_breaks: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        worst_fact = 0.0
        worst_fact_shift: int | None = None

        for tank, shift, _station in chain:
            book_start = _f(tank.volume_start)
            book_end = _f(tank.volume_end)
            receipts = _f(tank.volume_received)
            sales = _f(tank.sales)
            # `or None`: ноль в замере — это «уровнемер не дал показание», а не
            # пустой резервуар. Иначе книга − факт = весь книжный остаток и в
            # недостачу попадает вся ёмкость (как идиома приёма в fuel_shift_refresh).
            fact_end = _n(tank.fact_volume) or None
            # Факт на начало смены = замер конца предыдущей смены по этому же
            # резервуару (STS даёт один замер на смену — на сдачу/конец; замер
            # начала и есть замер конца предыдущей, как книга нач = книга кон пред.).
            fact_start = (_n(prev.fact_volume) or None) if prev is not None else None

            # 1. Арифметика книги внутри смены.
            arithmetic_gap = round(book_start + receipts - sales - book_end, 2)
            # 2. Стык с предыдущей сменой.
            continuity_gap = (round(book_start - _f(prev.volume_end), 2)
                              if prev is not None else None)
            # 3. Книга против факта (недостача > 0, излишек < 0).
            fact_gap = round(book_end - fact_end, 2) if fact_end is not None else None
            fuel_changed = prev is not None and _fuel_key(prev) != _fuel_key(tank)

            sum_receipts += receipts
            sum_sales += sales
            sum_mass_receipts += _f(tank.mass_received)
            sum_mass_sales += _f(tank.mass_sales)

            if abs(arithmetic_gap) > ARITHMETIC_TOLERANCE_L:
                arithmetic_breaks += 1
                issues.append({
                    "type": "arithmetic",
                    "station_code": station_code, "station_name": station_name,
                    "tank_number": tank_no, "fuel_name": (tank.fuel_type or "—").strip(),
                    "shift_number": int(shift.shift_number),
                    "date": shift.opened_at.date().isoformat() if shift.opened_at else None,
                    "gap_liters": arithmetic_gap,
                    "detail": (f"начало {book_start:,.1f} + приход {receipts:,.1f} "
                               f"− отпуск {sales:,.1f} ≠ конец {book_end:,.1f}"),
                })
            # Тип разрыва: без него все причины выглядят одинаково «разрыв N л»,
            # хотя слив между сменами и молчаливое списание — разные адресаты.
            break_kind: str | None = None
            break_reason: str | None = None
            if continuity_gap is not None and abs(continuity_gap) > CONTINUITY_TOLERANCE_L:
                if fuel_changed:
                    break_kind, break_reason = "fuel_change", (
                        "в резервуаре сменился вид топлива — остатки несопоставимы")
                else:
                    hours_gap = None
                    if prev_shift is not None and prev_shift.opened_at and shift.opened_at:
                        hours_gap = (shift.opened_at - prev_shift.opened_at).total_seconds() / 3600
                    break_kind, break_reason = _classify_break(
                        continuity_gap,
                        book_start=book_start,
                        prev_book_end=_f(prev.volume_end) if prev is not None else 0.0,
                        prev_fact=_n(prev.fact_volume) or None if prev is not None else None,
                        receipts_between=_receipts_between(
                            station_code,
                            prev_shift.opened_at if prev_shift else None,
                            shift.opened_at),
                        shift_number=int(shift.shift_number),
                        prev_shift_number=int(prev_shift.shift_number) if prev_shift else 0,
                        hours_gap=hours_gap,
                        receipts_in_shift=receipts,
                        # Накладные, закреплённые за этой сменой и резервуаром,
                        # плюс за предыдущей: слив на стыке станция относит то к
                        # закрываемой смене, то к открываемой.
                        receipts_linked=(
                            receipts_by_shift.get((station_code, int(shift.shift_number), tank_no), [])
                            + (receipts_by_shift.get(
                                (station_code, int(prev_shift.shift_number), tank_no), [])
                               if prev_shift else [])),
                    )
            if continuity_gap is not None and (abs(continuity_gap) > CONTINUITY_TOLERANCE_L or fuel_changed):
                continuity_breaks += 1
                issue_entry = {
                    "kind": break_kind, "reason": break_reason,
                    "type": "fuel_change" if fuel_changed else "continuity",
                    "station_code": station_code, "station_name": station_name,
                    "tank_number": tank_no, "fuel_name": (tank.fuel_type or "—").strip(),
                    "shift_number": int(shift.shift_number),
                    "prev_shift_number": int(prev_shift.shift_number) if prev_shift else None,
                    "date": shift.opened_at.date().isoformat() if shift.opened_at else None,
                    "gap_liters": continuity_gap,
                    "detail": (f"конец смены {prev_shift.shift_number if prev_shift else '—'} "
                               f"{_f(prev.volume_end):,.1f} ≠ начало смены "
                               f"{shift.shift_number} {book_start:,.1f}"
                               + (" · смена вида топлива" if fuel_changed else "")),
                }
                issues.append(issue_entry)
            else:
                issue_entry = None
            if fact_gap is not None and abs(fact_gap) > FACT_TOLERANCE_L:
                fact_breaks += 1
                if abs(fact_gap) > abs(worst_fact):
                    worst_fact = fact_gap
                    worst_fact_shift = int(shift.shift_number)

            rows.append({
                "station_code": station_code, "station_name": station_name,
                "tank_number": tank_no,
                "fuel_code": int(tank.fuel_code) if tank.fuel_code is not None else None,
                "fuel_name": (tank.fuel_type or "—").strip(),
                "shift_number": int(shift.shift_number),
                "opened_at": shift.opened_at.isoformat() if shift.opened_at else None,
                "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
                "book_start": round(book_start, 1),
                "receipts": round(receipts, 1),
                "sales": round(sales, 1),
                "book_end": round(book_end, 1),
                "fact_start": round(fact_start, 1) if fact_start is not None else None,
                "fact_end": round(fact_end, 1) if fact_end is not None else None,
                "fact_gap": fact_gap,
                "arithmetic_gap": arithmetic_gap,
                "continuity_gap": continuity_gap,
                "continuity_kind": break_kind,
                "continuity_reason": break_reason,
                "mass_start": _n(tank.mass_start), "mass_end": _n(tank.mass_end),
                "mass_received": _n(tank.mass_received), "mass_sales": _n(tank.mass_sales),
                "fact_mass": _n(tank.fact_mass),
                "density_beg": _n(tank.density_beg), "density_end": _n(tank.density),
                "temp_beg": _n(tank.temp_beg), "temp_end": _n(tank.temp_end),
                "level_end": _n(tank.level_end),
                "water_volume": _n(tank.water_volume),
                "fuel_changed": fuel_changed,
            })
            if issue_entry is not None and continuity_gap is not None:
                chain_breaks.append((continuity_gap, issue_entry, rows[-1]))
            prev, prev_shift = tank, shift

        # Зеркальный возврат: разрыв, который в пределах трёх следующих разрывов
        # по этому же резервуару компенсируется точно наоборот. Значение вернулось
        # — топливо никуда не двигалось, это артефакт отчёта (АЗС 209 01–02.04:
        # +4 275,1 → −4 275,1 на четырёх резервуарах сразу). Переписываем только
        # «необъяснённые»: у доказанных причин (слив, сброс, перенумерация)
        # основание сильнее.
        for idx, (gap_i, issue_i, row_i) in enumerate(chain_breaks):
            if issue_i.get("kind") != "unexplained":
                continue
            for gap_j, issue_j, row_j in chain_breaks[idx + 1:idx + 4]:
                if abs(gap_i + gap_j) <= max(1.0, abs(gap_i) * 0.02):
                    text = (f"возврат: разрыв {gap_i:+,.0f} л отменён обратным "
                            f"{gap_j:+,.0f} л в смене {issue_j.get('shift_number')} — "
                            "значение вернулось, движения топлива не было")
                    for iss, rw in ((issue_i, row_i), (issue_j, row_j)):
                        if iss.get("kind") in ("unexplained", None):
                            iss["kind"], iss["reason"] = "reversal", text
                            rw["continuity_kind"], rw["continuity_reason"] = "reversal", text
                    break

        last = chain[-1][0]
        book_start_period = _f(first.volume_start)
        book_end_period = _f(last.volume_end)
        fact_end_period = _n(last.fact_volume) or None
        # Расхождение книги и факта на конец периода — то, что пойдёт в инвентаризацию.
        fact_gap_period = (round(book_end_period - fact_end_period, 1)
                           if fact_end_period is not None else None)
        # Разница расхождений начала и конца периода: сколько «набежало» именно
        # за период. Без этого нельзя отделить старую недостачу от новой.
        first_fact_gap = (_f(first.volume_start) - _f(first.fact_volume)
                          if first.fact_volume else None)

        tanks_summary.append({
            "station_code": station_code, "station_name": station_name,
            "tank_number": tank_no,
            "fuel_code": int(last.fuel_code) if last.fuel_code is not None else None,
            "fuel_name": (last.fuel_type or "—").strip(),
            "shifts": len(chain),
            "first_shift": int(chain[0][1].shift_number),
            "last_shift": int(chain[-1][1].shift_number),
            "book_start": round(book_start_period, 1),
            "receipts": round(sum_receipts, 1),
            "sales": round(sum_sales, 1),
            "book_end": round(book_end_period, 1),
            "fact_end": round(fact_end_period, 1) if fact_end_period is not None else None,
            "fact_gap": fact_gap_period,
            "fact_gap_pct": (round(fact_gap_period / sum_sales * 100, 3)
                             if fact_gap_period is not None and sum_sales else None),
            "fact_gap_opening": round(first_fact_gap, 1) if first_fact_gap is not None else None,
            "mass_receipts": round(sum_mass_receipts, 1),
            "mass_sales": round(sum_mass_sales, 1),
            "mass_end": _n(last.mass_end),
            "fact_mass_end": _n(last.fact_mass),
            "arithmetic_breaks": arithmetic_breaks,
            "continuity_breaks": continuity_breaks,
            "fact_breaks": fact_breaks,
            "worst_fact_gap": round(worst_fact, 1) if worst_fact else 0.0,
            "worst_fact_shift": worst_fact_shift,
        })

    # Сортировка: сначала то, где расхождение больше — с этого начинают разбор.
    tanks_summary.sort(key=lambda r: -abs(r["fact_gap"] or 0))
    issues.sort(key=lambda i: -abs(i["gap_liters"] or 0))

    totals = {
        "book_start": round(sum(t["book_start"] for t in tanks_summary), 1),
        "receipts": round(sum(t["receipts"] for t in tanks_summary), 1),
        "sales": round(sum(t["sales"] for t in tanks_summary), 1),
        "book_end": round(sum(t["book_end"] for t in tanks_summary), 1),
        "fact_end": round(sum(t["fact_end"] or 0 for t in tanks_summary), 1),
        "fact_gap": round(sum(t["fact_gap"] or 0 for t in tanks_summary), 1),
        "mass_receipts": round(sum(t["mass_receipts"] for t in tanks_summary), 1),
        "mass_sales": round(sum(t["mass_sales"] for t in tanks_summary), 1),
        "tanks": len(tanks_summary),
        "shifts": len({(r["station_code"], r["shift_number"]) for r in rows}),
        "arithmetic_breaks": sum(t["arithmetic_breaks"] for t in tanks_summary),
        "continuity_breaks": sum(t["continuity_breaks"] for t in tanks_summary),
        "fact_breaks": sum(t["fact_breaks"] for t in tanks_summary),
    }
    totals["fact_gap_pct"] = (round(totals["fact_gap"] / totals["sales"] * 100, 3)
                              if totals["sales"] else 0.0)

    # Разрывы стыка по причинам: сколько случаев и на сколько литров. Нужна
    # именно разбивка — «774 разрыва» одной цифрой не говорят, что делать, а
    # «слив между сменами 140 / молчаливое списание 7 / необъяснённых 12» говорят.
    kinds: dict[str, dict[str, float]] = {}
    for i in issues:
        k = i.get("kind")
        if not k:
            continue
        e = kinds.setdefault(k, {"count": 0, "liters": 0.0})
        e["count"] += 1
        e["liters"] = round(e["liters"] + abs(i.get("gap_liters") or 0), 1)
    totals["continuity_kinds"] = kinds

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "totals": totals,
        "tanks": tanks_summary,
        "rows": rows[:max_rows],
        "rows_total": len(rows),
        "rows_truncated": len(rows) > max_rows,
        "issues": issues[:500],
        "issues_total": len(issues),
        "tolerances": {
            "arithmetic_liters": ARITHMETIC_TOLERANCE_L,
            "continuity_liters": CONTINUITY_TOLERANCE_L,
            "fact_liters": FACT_TOLERANCE_L,
        },
    }
