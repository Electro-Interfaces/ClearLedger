"""Возврат исхода круга виз в процесс: сопоставление действия по глаголу.

Ошибка здесь молчалива и дорога: круг виз закрыт, действие в процессе не найдено —
и стройка стоит, пока кто-нибудь не заметит. Поэтому глагол сравнивается без учёта
регистра и лишних пробелов, а заодно с кодом ребра: маршруты пишут разные люди, и
«approve» рядом с «Согласовано» встречается чаще, чем хотелось бы.
"""

from app.services.approval_requests import _labels, _match_action

ACTIONS = [
    {"id": "a1", "verb": "Согласовано", "code": "approve"},
    {"id": "a2", "verb": "Отказано", "code": "reject"},
]


def test_glagol_nahoditsya_bez_uchyota_regisstra():
    assert _match_action(ACTIONS, "согласовано")["id"] == "a1"
    assert _match_action(ACTIONS, "  ОТКАЗАНО  ")["id"] == "a2"


def test_kod_rebra_tozhe_podhodit():
    """Маршрут может ссылаться на код, а не на видимый глагол."""
    assert _match_action(ACTIONS, "approve")["id"] == "a1"


def test_neizvestnoe_deystvie_ne_ugadyvaetsya():
    """Похожее — не то же самое: угаданный переход двинул бы процесс не туда."""
    assert _match_action(ACTIONS, "согласовать") is None
    assert _match_action(ACTIONS, "передано") is None


def test_pustoy_glagol_ne_sovpadaet_s_pustym_polem():
    """Действие без глагола не должно ловиться пустой строкой из настройки."""
    assert _match_action([{"id": "x", "verb": "", "code": ""}], "") is None


def test_perechen_deystviy_dlya_soobscheniya_ob_oshibke():
    """Текст ошибки показывает, что вообще было доступно, — иначе искать наугад."""
    assert _labels(ACTIONS) == ["Согласовано", "Отказано"]
