"""Переписывание адресов рабочего места станции под префикс прокси.

Списки станции открывают документ кликом по строке через JS `location='/…'`.
Раньше прокси правил только href/action/src — и клик по УПД уходил на корень
пространства (404). Проверяем, что теперь и location под префиксом, а схемы и
якоря не тронуты.
"""
from app.routers.station_console_router import _переписать

PFX = "/api/store/station/208/console"


def test_переписывает_клик_по_строке():
    # location='/…' (клик по УПД/строке документа) — под префикс.
    assert _переписать("<tr onclick=\"location='/receipts/42'\">", PFX) \
        == f"<tr onclick=\"location='{PFX}/receipts/42'\">"
    # href/action/src по-прежнему переписываются.
    assert _переписать('<a href="/item/7">x</a>', PFX) == f'<a href="{PFX}/item/7">x</a>'
    assert _переписать('<form action="/doc/undo">', PFX) == f'<form action="{PFX}/doc/undo">'


def test_не_трогает_схемы_и_якоря():
    for src in ('<a href="https://x/y">', '<a href="//cdn/z">', '<a href="#top">',
                "<a onclick=\"location='https://ext/'\">"):
        assert _переписать(src, PFX) == src
