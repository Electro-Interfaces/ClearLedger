"""Нормализация вида оплаты STS к единому имени («Банковские», «Наличные», «Купон»…).

Перенос из «Монитора» (TradeFrame, `src/utils/paymentUtils.ts` и его серверный
двойник `server/services/analytics/paymentNormalize.js`) — раздел «Операции» ГИГ
повторяет его разрезы, а значит и группировку. Сырых имён у STS десятки на один
смысл («Карта МПС», «Безнал.электрон», «Сбербанк» — всё банковские карты), по ним
KPI-карточки рассыпаются в длинный хвост.

ПОРЯДОК ПРАВИЛ ЗНАЧИМ: «безнал.электрон» проверяется до «безнал», «мобилпр» до
общего «онлайн», «топливные» до «корпоративных». Меняешь здесь — правь и
`src/utils/paymentUtils.ts`: по этому значению группируются агрегаты в БД, а фронт
рисует те же имена на карточках.

Не путать с `payment_mappings` (fuel_mapping_defaults) — там разметка на каналы
1С:БП (склад, перемещение), здесь имя для интерфейса.
"""
from __future__ import annotations


def normalize_payment_method(name: str | None) -> str:
    if not name:
        return "-"
    m = str(name).lower().strip()

    if m in ("cash", "наличные") or "наличн" in m:
        return "Наличные"
    if "безнал" in m and "электрон" in m:
        return "Безнал.электрон"
    if m in ("безнал", "безнал."):
        return "Безнал"
    if "талон" in m:
        return "Талоны"
    if "балтоп" in m:
        return "БАЛТОП"
    if "инфорком" in m:
        return "Инфорком"
    if "viacard" in m or "виакард" in m:
        return "VIAcard"
    if "мобилпр" in m or "мобил.пр" in m or "мобил.п" in m:
        return "Онлайн"
    if m in ("bank_card", "карта", "сбербанк", "card", "credit_card", "debit_card") \
            or "банковск" in m or "мпс" in m:
        return "Банковские"
    if m in ("fuel_card", "топливная_карта", "fleet_card", "нкт") or "топливн" in m:
        return "Топл. карты"
    if m in ("online_order", "мобильная", "мобильная оплата", "mobile", "qr", "онлайн", "online"):
        return "Онлайн"
    if m in ("corporate_card", "кр") or "корпоратив" in m:
        return "Корп. карты"
    if m in ("coupon", "купон", "купон на сдачу"):
        return "Купон"
    if "ведомост" in m:
        return "Ведомость"
    if "тех" in m and "мерник" in m:
        return "Тех. отпуск"
    if m in ("прочие", "прочее"):
        return "Прочие"
    return str(name)


if __name__ == "__main__":  # самопроверка: порядок правил и краевые случаи
    assert normalize_payment_method("Карта МПС") == "Банковские"
    assert normalize_payment_method("Безнал.электрон") == "Безнал.электрон"  # до «Безнал»
    assert normalize_payment_method("Безнал.") == "Безнал"
    assert normalize_payment_method("МобилПр.") == "Онлайн"                  # до общего «онлайн»
    assert normalize_payment_method("Топливные карты") == "Топл. карты"      # до «Корп.»
    assert normalize_payment_method("КР") == "Корп. карты"
    assert normalize_payment_method("Купон на сдачу") == "Купон"
    assert normalize_payment_method("Тех. отпуск в мерник") == "Тех. отпуск"
    assert normalize_payment_method("Хитрый вид") == "Хитрый вид"            # неизвестное — как есть
    assert normalize_payment_method(None) == "-"
    print("ok")
