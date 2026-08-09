"""Переписывание адресов рабочего места станции под префикс прокси.

Списки станции открывают документ либо через JS `location='/…'`, либо через
`data-открыть`, который общий обработчик строки передаёт в location.href.
Проверяем оба варианта и обычные ссылки; схемы и якоря не трогаем.
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


def test_переписывает_data_открыть_смены():
    src = '<tr data-открыть="/shift?number=7069" tabindex="0">'
    assert _переписать(src, PFX) == (
        f'<tr data-открыть="{PFX}/shift?number=7069" tabindex="0">'
    )


def test_не_трогает_схемы_и_якоря():
    for src in ('<a href="https://x/y">', '<a href="//cdn/z">', '<a href="#top">',
                "<a onclick=\"location='https://ext/'\">"):
        assert _переписать(src, PFX) == src
