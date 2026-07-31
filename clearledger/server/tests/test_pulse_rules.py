"""Правила экрана дня «Пульса» (ecosystem-deploy/docs/PULSE.md §3, §7).

Проверяем то, ради чего продукт существует: экран молчит, пока вмешательство не
требуется, и не превращается в ленту, когда данные плохие. Пороги намеренно с
запасом — тест фиксирует именно это поведение, а не «сработало хоть что-то».
"""
from datetime import datetime

from app.routers.pulse_router import (
    EXT_BACKLOG, MAX_CARDS, OWN_SLA_DAYS, SILENT_SHARE, STALE_DAYS, build_cards,
)

AS_OF = datetime(2026, 7, 22, 9, 29)


def cards(**kw):
    base = dict(as_of=AS_OF, stale_days=0, own_sla_stale=0, own_reopen=0,
                ext_old=0, silent=0, park=436, acked=set())
    return build_cards(**{**base, **kw})


def keys(**kw):
    return {c["key"] for c in cards(**kw)}


def test_quiet_when_all_is_well():
    """Норма = пустой экран: это нормальное состояние, а не поломка."""
    assert cards() == []


def test_stale_data_is_the_first_alert():
    """Правило №0: несвежим данным верить нельзя, поэтому уровень alert."""
    assert "data_stale" not in keys(stale_days=STALE_DAYS)
    c = cards(stale_days=STALE_DAYS + 1)
    assert c[0]["key"] == "data_stale" and c[0]["level"] == "alert"


def test_no_data_at_all_is_alert():
    assert "data_stale" in keys(stale_days=None, as_of=None)


def test_own_tickets_escalate_only_when_stuck():
    assert "own_sla" not in keys(own_sla_stale=0)
    assert "own_sla" in keys(own_sla_stale=1)


def test_external_backlog_needs_to_be_big():
    """Хвост зеркал внешней FSM — сводка, и только когда он действительно велик:
    на пилоте 1314 заявок старше месяца, единичные висяки директора не касаются."""
    assert "ext_backlog" not in keys(ext_old=EXT_BACKLOG)
    assert "ext_backlog" in keys(ext_old=EXT_BACKLOG + 1)


def test_silent_stations_only_on_mass_outage():
    """205 молчащих из 436 (47% пилота) — не эскалация: так сеть живёт всегда."""
    assert "silent_surge" not in keys(silent=205, park=436)
    assert "silent_surge" in keys(silent=int(436 * SILENT_SHARE) + 1, park=436)
    assert "silent_surge" not in keys(silent=5, park=0)  # парка нет — делить не на что


def test_acked_card_disappears_for_the_day():
    assert "own_sla" not in keys(own_sla_stale=3, acked={"own_sla"})


def test_cap_holds_and_alerts_come_first():
    """Всё плохо сразу: экран остаётся экраном, а не лентой; тревожное — сверху."""
    c = cards(stale_days=STALE_DAYS + 10, own_sla_stale=9, own_reopen=4,
              ext_old=EXT_BACKLOG + 500, silent=400, park=436)
    assert len(c) <= MAX_CARDS
    assert c[0]["level"] == "alert"
    assert all(x["count"] is not None for x in c)


def test_insight_is_a_sentence_not_a_number():
    """Под цифрой — строка-инсайт словами: руководитель не должен догадываться."""
    c = cards(own_sla_stale=2)[0]
    assert str(OWN_SLA_DAYS) in c["insight"] and len(c["insight"]) > 40


def test_plural_reads_like_russian():
    """«1 заявок» в карточке директора — брак: цифры читает человек."""
    from app.routers.pulse_router import plural
    assert [plural(n, "заявка", "заявки", "заявок") for n in (1, 2, 5, 11, 21, 104)] == \
        ["заявка", "заявки", "заявок", "заявок", "заявка", "заявки"]
    assert "1 заявка с нарушенным SLA висит" in cards(own_sla_stale=1)[0]["insight"]
