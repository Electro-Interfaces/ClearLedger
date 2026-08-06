"""Правила экрана дня «Пульса» (ecosystem-deploy/docs/PULSE.md §3, §7).

Проверяем то, ради чего продукт существует: экран молчит, пока вмешательство не
требуется, и не превращается в ленту, когда данные плохие. Пороги намеренно с
запасом — тест фиксирует именно это поведение, а не «сработало хоть что-то».
"""
from datetime import datetime

from app.routers.pulse_router import (
    EXT_BACKLOG, MAX_CARDS, OWN_SLA_DAYS, SILENT_SHARE, STALE_DAYS, build_cards, money,
)

AS_OF = datetime(2026, 7, 22, 9, 29)


def cards(**kw):
    base = dict(as_of=AS_OF, stale_days=0, own_sla_stale=0, own_reopen=0,
                ext_old=0, silent=0, park=436, acked=set(), visible=None)
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


# ── Контакт-центр ────────────────────────────────────────────────────────────
# Цифры взяты с пилота rushydro (04.08.2026): 552 входящих за неделю, 105 без
# ответа (19%) против 15% неделей раньше при цели 5%.

def cc(**kw):
    base = dict(calls=552, missed=105, missed_share=19.0, missed_share_prev=15.0,
                wrapup_stuck=0, repeat_people=0, escalations=0, target_missed=5.0)
    return {**base, **kw}


def test_contact_center_is_silent_without_telephony():
    """Стек без контакт-центра: правила молчат, а не падают на пустом словаре."""
    assert cards(cc=None) == [] and cards(cc={}) == []


def test_missed_calls_escalate_only_above_the_target_with_margin():
    """Цель 5% не повод будить директора на 6%: порог с запасом (×1,5)."""
    assert "cc_missed" not in keys(cc=cc(missed_share=7.0, missed_share_prev=6.0))
    assert "cc_missed" in keys(cc=cc())


def test_missed_calls_stay_quiet_when_the_week_is_improving():
    """Доля высокая, но неделя лучше предыдущей — работа уже идёт, не мешаем."""
    assert "cc_missed" not in keys(cc=cc(missed_share=19.0, missed_share_prev=25.0))


def test_missed_calls_become_alert_when_it_is_a_disaster():
    c = [x for x in cards(cc=cc(missed_share=40.0)) if x["key"] == "cc_missed"][0]
    assert c["level"] == "alert" and "цели 5%" in c["insight"]


def test_dropped_conversations_and_repeat_callers_have_floors():
    """Единичный хвост — не эскалация: у обоих правил есть порог."""
    assert "cc_wrapup" not in keys(cc=cc(wrapup_stuck=9))
    assert "cc_wrapup" in keys(cc=cc(wrapup_stuck=10))
    assert "cc_repeat" not in keys(cc=cc(repeat_people=2))
    assert "cc_repeat" in keys(cc=cc(repeat_people=3))


def test_operator_escalation_is_never_thresholded():
    """Оператор позвал старшего — это уже решение человека, порогов тут нет."""
    c = [x for x in cards(cc=cc(escalations=1)) if x["key"] == "cc_escalation"][0]
    assert c["level"] == "alert"


# ── Продажи ──────────────────────────────────────────────────────────────────
# Цифры пилота (неделя данных на 31.07.2026): 1 038 152 ₽ против 1 152 454 ₽,
# 288 станций в работе против 304, 38 выпавших, успех приездов 89,9%.

def sales(**kw):
    base = dict(revenue=1_038_152.0, revenue_prev=1_152_454.0,
                sessions=5956, sessions_prev=6673, live=288, live_prev=304,
                stations_out=38, stations_out_revenue=23_319.0, visit_ok_share=89.9)
    return {**base, **kw}


def test_sales_are_silent_without_data():
    assert cards(sales=None) == [] and cards(sales={}) == []


def test_revenue_dip_of_ten_percent_is_noise():
    """Минус 10% на пилоте — обычное недельное колебание, а не эскалация."""
    assert "sales_drop" not in keys(sales=sales())


def test_revenue_drop_names_the_reason():
    """Карточка обязана отвечать «почему», иначе директор идёт искать сам."""
    c = [x for x in cards(sales=sales(revenue=800_000.0)) if x["key"] == "sales_drop"][0]
    assert "станций в работе стало меньше" in c["insight"]
    c2 = [x for x in cards(sales=sales(revenue=800_000.0, live=304, live_prev=304))
          if x["key"] == "sales_drop"][0]
    assert "сессий стало меньше" in c2["insight"]


def test_half_the_revenue_gone_is_an_alert():
    c = [x for x in cards(sales=sales(revenue=500_000.0)) if x["key"] == "sales_drop"][0]
    assert c["level"] == "alert"


def test_stations_out_need_both_share_and_count():
    """Порог двойной: у мелкой сети процент врёт, у крупной — абсолютное число."""
    assert "sales_out" in keys(sales=sales(), park=436)
    assert "sales_out" not in keys(sales=sales(stations_out=9), park=436)
    assert "sales_out" not in keys(sales=sales(stations_out=38), park=2000)


def test_visit_success_escalates_only_below_the_floor():
    assert "sales_visit" not in keys(sales=sales())
    c = [x for x in cards(sales=sales(visit_ok_share=80.0)) if x["key"] == "sales_visit"][0]
    assert "80%" in c["insight"]


# ── Проекты ──────────────────────────────────────────────────────────────────
# Портфель пилота (04.08.2026): 347 в работе, 46 стоят дольше 90 дней (все на
# «Проработке»), 307 без ответственного, 5 смен стадии за неделю.

def projects(**kw):
    base = dict(active=347, stuck=46, stuck_stage="Проработка", no_owner=307,
                overdue=0, moves=5, moves_prev=0, moves_3w=5, gates=9)
    return {**base, **kw}


def test_projects_are_silent_without_portfolio():
    assert cards(projects=None) == [] and cards(projects={}) == []


def test_stuck_projects_need_share_and_count():
    """Пять застрявших в портфеле из тысячи — не эскалация, а обычная жизнь."""
    assert "pr_stuck" in keys(projects=projects())
    assert "pr_stuck" not in keys(projects=projects(stuck=19))
    assert "pr_stuck" not in keys(projects=projects(stuck=46, active=2000))


def test_stuck_card_names_the_stage():
    c = [x for x in cards(projects=projects()) if x["key"] == "pr_stuck"][0]
    assert "Проработка" in c["insight"] and "90" in c["insight"]


def test_ownerless_portfolio_escalates():
    assert "pr_no_owner" in keys(projects=projects())
    assert "pr_no_owner" not in keys(projects=projects(no_owner=100, active=1000))


def test_frozen_portfolio_is_an_alert_but_movement_silences_it():
    """Ноль переходов за три недели — остановка; один переход снимает карточку."""
    c = [x for x in cards(projects=projects(moves_3w=0)) if x["key"] == "pr_frozen"][0]
    assert c["level"] == "alert"
    assert "pr_frozen" not in keys(projects=projects(moves_3w=1))


def test_overdue_next_step_has_no_threshold():
    """Обещанный срок — обязательство: одна просрочка уже повод сказать."""
    assert "pr_overdue" not in keys(projects=projects())
    assert "pr_overdue" in keys(projects=projects(overdue=1))


# ── Эксплуатация ─────────────────────────────────────────────────────────────
# Пилот (04.08.2026): ожидания 3,2 млн ₽ в месяц посчитаны, документов нет ни за
# один месяц — 4 682 начисления с прошедшим сроком подтверждения.

def ops(**kw):
    base = dict(docs_overdue=4682, docs_overdue_amount=22_000_000.0,
                docs_overdue_oldest="2025-12-10", open_periods=2,
                expected=3_211_291.0, expected_prev=3_216_661.0, cost_jump_pct=-0.2)
    return {**base, **kw}


def test_operations_are_silent_without_charges():
    assert cards(ops=None) == [] and cards(ops={}) == []


def test_unconfirmed_costs_are_an_alert_with_the_oldest_date():
    """Расход без документа — обещание: карточка называет и сумму, и давность."""
    c = [x for x in cards(ops=ops()) if x["key"] == "ops_docs"][0]
    assert c["level"] == "alert" and "2025-12-10" in c["insight"]
    # Разряды разделяет НЕРАЗРЫВНЫЙ пробел — как в Intl.NumberFormat('ru-RU')
    # на фронте: иначе сумма переносится на другую строку посередине.
    assert money(22_000_000) + " ₽" in c["insight"]


def test_a_couple_of_late_documents_is_not_an_escalation():
    assert "ops_docs" not in keys(ops=ops(docs_overdue=19))


def test_open_periods_are_reported_but_not_alarming():
    c = [x for x in cards(ops=ops()) if x["key"] == "ops_open"][0]
    assert c["level"] == "warn" and "2 периода старше" in c["insight"]
    assert "ops_open" not in keys(ops=ops(open_periods=0))


def test_cost_jump_needs_a_real_jump():
    """Месяц к месяцу хозяйство почти не меняется — шум не эскалируем."""
    assert "ops_jump" not in keys(ops=ops())
    c = [x for x in cards(ops=ops(cost_jump_pct=22.0)) if x["key"] == "ops_jump"][0]
    assert "22%" in c["insight"]


# ── Источники данных ─────────────────────────────────────────────────────────

def src(key, label, days, window, stale=None):
    return {"key": key, "label": label, "days": days, "window": window,
            "stale": (days is None or days > window) if stale is None else stale}


def test_sources_are_silent_when_everything_arrives():
    assert "src_stale" not in keys(sources=[src("tickets", "Заявки", 0, 3)])


def test_sessions_have_their_own_rule_and_are_not_duplicated_here():
    """Правило №0 уже говорит о сессиях — второй раз о том же не напоминаем."""
    assert "src_stale" not in keys(sources=[src("sessions", "Сессии сети", 40, 7)])


def test_one_silent_source_warns_two_alert():
    c = [x for x in cards(sources=[src("telephony", "Телефония", 9, 2)])
         if x["key"] == "src_stale"][0]
    assert c["level"] == "warn" and "Телефония (9 дн)" in c["insight"]
    c2 = [x for x in cards(sources=[src("telephony", "Телефония", 9, 2),
                                    src("tickets", "Заявки", 5, 3)])
          if x["key"] == "src_stale"][0]
    assert c2["level"] == "alert" and c2["count"] == 2


def test_source_that_never_delivered_is_named_plainly():
    c = [x for x in cards(sources=[src("charges", "Начисления", None, 35)])
         if x["key"] == "src_stale"][0]
    assert "Начисления (данных нет)" in c["insight"]


# ── Доступ ───────────────────────────────────────────────────────────────────

def test_access_is_silent_when_nothing_hangs():
    assert cards(access={"dormant_admins": 0, "invites_stale": 0}) == []


def test_dormant_admin_rights_are_reported():
    c = [x for x in cards(access={"dormant_admins": 2}) if x["key"] == "access_admins"][0]
    assert "2 человека с полным доступом не заходили" in c["insight"]


def test_stale_invitation_is_reported_singly():
    """Одно повисшее приглашение — уже разговор: человека позвали и бросили."""
    c = [x for x in cards(access={"invites_stale": 1}) if x["key"] == "access_invites"][0]
    assert "1 человек приглашён" in c["insight"]


# ── Отбор картины (кто что видит) ────────────────────────────────────────────

def test_visibility_none_shows_everything():
    """Без отбора экран прежний: ограничение — исключение, а не норма."""
    assert "own_sla" in keys(own_sla_stale=3, visible=None)


def test_closed_topic_never_reaches_the_screen():
    """Куратор с открытыми продажами не видит сообщений про заявки."""
    k = keys(own_sla_stale=3, silent=400, park=436, visible={"business.sales"})
    assert "silent_surge" in k and "own_sla" not in k


def test_selection_happens_before_the_cap():
    """Колпак не должен съедать темы, открытые этому человеку.

    Семь мест забирали закрытые темы, и на экране куратора не оставалось ничего,
    хотя по его разрезам сообщения были.
    """
    c = cards(stale_days=STALE_DAYS + 10, own_sla_stale=9, own_reopen=4,
              ext_old=EXT_BACKLOG + 500, silent=400, park=436,
              visible={"business.sales"})
    # `data_stale` без темы — метка доверия к цифрам, она остаётся у всех.
    assert [x["key"] for x in c] == ["data_stale", "silent_surge"]


def test_topicless_cards_stay_visible():
    """Сообщения без темы (свежесть данных) видны всем — им верят все цифры."""
    assert "data_stale" in keys(stale_days=STALE_DAYS + 1, visible={"team.people"})
