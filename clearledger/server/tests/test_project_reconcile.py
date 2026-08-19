"""Чтение карточки проекта называет расхождение, но не устраняет его.

Прежде эта же проверка выполнялась на GET и сразу писала в базу: дата ввода в
эксплуатацию — основание перевода капвложений 08 → 01 — проставлялась датой
чужого просмотра. Теперь чтение обязано остаться чтением, и тест стережёт именно
это: он падает, если в список расхождений попадёт что-то, чего в маршруте нет,
или если расхождение перестанет называться.
"""
from types import SimpleNamespace

from app.services.projects_process import _pending_diff


def _site(**kw):
    base = dict(commissioned_on=None, stage="works", contractor=None,
                smr_cost=None, tp_cost=None, control_form=None, tu_status=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_field_filled_in_route_but_not_in_card():
    reasons = _pending_diff(_site(), {"values": {"contractor": "ООО «Подрядчик»"}})
    assert any("contractor" in r for r in reasons), reasons


def test_filled_card_is_not_a_discrepancy():
    reasons = _pending_diff(_site(contractor="ООО «Подрядчик»"),
                            {"values": {"contractor": "ООО «Подрядчик»"}})
    assert not any("contractor" in r for r in reasons), reasons


def test_commissioning_without_a_date():
    reasons = _pending_diff(_site(), {"stage": {"code": "ezs_commissioning"}})
    assert any("дата ввода" in r for r in reasons), reasons


def test_commissioning_with_a_date_is_clean():
    reasons = _pending_diff(_site(commissioned_on="2026-05-01"),
                            {"stage": {"code": "ezs_commissioning"}})
    assert not reasons, reasons


def test_rejected_route_but_project_still_active():
    reasons = _pending_diff(_site(stage="works"), {"stage": {"code": "ezs_rejected"}})
    assert any("отказом" in r for r in reasons), reasons


def test_rejected_and_archived_is_clean():
    reasons = _pending_diff(_site(stage="archive"), {"stage": {"code": "ezs_rejected"}})
    assert not reasons, reasons


def test_hold_route_but_project_in_work():
    reasons = _pending_diff(_site(stage="works"), {"stage": {"code": "ezs_hold"}})
    assert any("паузе" in r for r in reasons), reasons


def test_empty_state_says_nothing():
    """Кейса ещё нет — это не расхождение, а «работа не начата»."""
    assert _pending_diff(_site(), {}) == []
