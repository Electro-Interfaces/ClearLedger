"""Ценообразование: события смены цены и склейка волн (чистая логика, без БД)."""
from datetime import date, timedelta

from app.services.fuel_pricing import Day, group_waves, price_events, trading_days


def day(n: int, price: float, liters: float = 1000.0) -> Day:
    d = date(2026, 6, 1) + timedelta(days=n)
    return Day(day=d, price=price, liters=liters, amount=price * liters, fills=10,
               varies=False, price_low=price, price_high=price)


def test_ступенька_даёт_одно_событие_с_шагом_и_удержанием():
    days = [day(i, 57.0) for i in range(5)] + [day(i, 59.5) for i in range(5, 10)]
    (e,) = price_events(days)
    assert e["day"] == date(2026, 6, 6)
    assert (e["was"], e["became"], e["step"]) == (57.0, 59.5, 2.5)
    assert e["held_days"] == 5


def test_пауза_в_продажах_не_читается_как_смена_цены():
    """Дни простоя в ряду отсутствуют; без явного сравнения с прошлым ДНЁМ ПРОДАЖ
    разрыв дал бы ложное событие."""
    days = [day(0, 57.0), day(1, 57.0), day(9, 57.0), day(10, 57.0)]
    assert price_events(days) == []


def test_реакция_объёма_считается_по_окну_и_помечается_неполной():
    before = [day(i, 57.0, liters=1000) for i in range(7)]
    after = [day(7 + i, 60.0, liters=800) for i in range(7)]
    (e,) = price_events(before + after)
    assert e["liters_before"] == 1000.0
    assert e["liters_after"] == 800.0
    assert e["response_pct"] == -20.0
    assert e["window_full"] is True

    # То же событие в последний день ряда: окно справа пустое — реакции ещё не видно.
    (short,) = price_events(before + [day(7, 60.0, liters=800)])
    assert short["window_full"] is False


def test_день_огрызок_не_создаёт_события_и_не_обнуляет_реакцию():
    """1,3 литра за сутки — техпролив на остановленной ТРК. Без отсечения такой день
    и давал ложное событие, и ронял реакцию до −99% («объём упал»), хотя станция
    просто не торговала."""
    row = ([day(i, 57.0, liters=1000) for i in range(7)]
           + [day(7, 60.0, liters=900)]
           + [day(8, 60.0, liters=1.3)]        # огрызок
           + [day(9 + i, 60.0, liters=880) for i in range(6)])
    assert [d.day.day for d in trading_days(row)] == [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]
    (e,) = price_events(row)
    assert e["liters_before"] == 1000.0
    assert e["liters_after"] == 880.0          # не 1,3 и не среднее с ним
    assert e["response_pct"] == -12.0


def test_реакция_не_считается_от_ничтожной_базы():
    """До смены цены брали 30 л/сут, после — 1000: это выход позиции в продажу, а не
    реакция на цену. Процент по такой базе (+3200%) — мусор, который тянет за собой
    любую агрегацию, поэтому его нет вовсе, а литры остаются видны."""
    row = ([day(i, 89.9, liters=30) for i in range(7)]
           + [day(7 + i, 91.9, liters=1000) for i in range(7)])
    (e,) = price_events(row)
    assert (e["liters_before"], e["liters_after"]) == (30.0, 1000.0)
    assert e["response_pct"] is None


def test_догоняющий_скачок_помечен_и_в_волну_не_идёт():
    """Станция стояла, вернулась сразу на цене на 30% выше: ступени прошли мимо.
    Такой шаг реален, но это не одно решение о цене."""
    row = [day(0, 70.0), day(1, 70.0), day(2, 91.0), day(3, 91.0)]
    (e,) = price_events(row)
    assert e["jump"] is True
    assert group_waves([{**e, "station_code": 1, "station": "АЗС 1",
                         "fuel_code": 3, "fuel_name": "АИ-95"}]) == []


def test_волна_склеивает_станции_одного_решения_и_рвётся_на_развороте():
    def ev(d: int, station: int, step: float, jump: bool = False):
        return {"day": date(2026, 6, 1) + timedelta(days=d), "station_code": station,
                "station": f"АЗС {station}", "fuel_code": 3, "fuel_name": "АИ-95",
                "step": step, "jump": jump}

    waves = group_waves([
        ev(0, 208, 2.5), ev(1, 209, 2.5), ev(2, 210, 2.5),   # одно решение, три дня
        ev(20, 208, -1.0),                                    # разворот через три недели
    ])
    assert len(waves) == 2
    up = next(w for w in waves if w["step_avg"] > 0)
    assert (up["stations"], up["days"], up["first"]) == (3, 3, ["АЗС 208"])
    assert up["last"] == ["АЗС 210"]


def test_волна_не_склеивает_разные_шаги_в_одно_решение():
    """Две недели ежедневного роста по разным станциям слипались в «одно решение» на
    18 дней с шагом 1,5…25,9 ₽/л — решения, которого не было."""
    def ev(d: int, station: int, step: float):
        return {"day": date(2026, 6, 1) + timedelta(days=d), "station_code": station,
                "station": f"АЗС {station}", "fuel_code": 2, "fuel_name": "АИ-92",
                "step": step, "jump": False}

    waves = group_waves([ev(0, 1, 1.5), ev(1, 2, 1.5), ev(2, 3, 5.0), ev(3, 4, 5.0)])
    assert len(waves) == 2
    assert sorted(w["step_avg"] for w in waves) == [1.5, 5.0]
    assert all(w["stations"] == 2 for w in waves)
