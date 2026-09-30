"""Тип причины выхода из работы по тексту — на живых формулировках пилота rushydro."""
from app.services.ezs_site_work import EXIT_REASONS, guess_exit_kind


def test_live_phrases():
    cases = {
        "Развитие территории рассмотрим в 2027 году": "our_priority",
        "Поэтапная отработка локаций": "our_priority",
        "Наличие свободной мощности не подтверждено Псковэнерго": "no_power",
        "КА отказал в размещении ЭЗС после консультации с электриком из-за слабой сети в ТЦ": "no_power",
        "КА отказал в размещении без объяснения причин.": "owner_refused",
        "КА не дает мощности. До ближайшей ТП более 200 метров": "no_power",
        "Заявленный размер АП 1 млн. руб. Двигаться не готовы": "commercial",
        "Необходимо внесение изменений в назначение ЗУ. Без директивы из МСК заниматься не будут": "land",
        "Дубль проекта ЭЗС-2026-0012": "duplicate",
        "Экономически не целесообразно, длинна трассы более 300 м": "grid_cost",
    }
    for text, kind in cases.items():
        assert guess_exit_kind(text) == kind, text


def test_not_a_refusal_is_not_guessed():
    # В архиве пилота лежат и успехи: угадывать им причину отказа нельзя.
    for text in ("согласовано ЛИ", "заключен договор аренды", "перспективно, но есть сложности", "", None):
        assert guess_exit_kind(text) is None, text


def test_every_hint_kind_is_in_the_list():
    from app.services.ezs_site_work import _EXIT_HINTS
    assert all(k in EXIT_REASONS for k, _ in _EXIT_HINTS)
