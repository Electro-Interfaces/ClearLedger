"""Свёртка сбоев интерфейса: журнал ошибок не должен сам становиться отказом.

Цикл перерисовки шлёт падения пачками, и без общего ключа каждая перерисовка
завела бы свою строку. При этом разные падения на одном экране обязаны остаться
разными — иначе журнал скажет «одна ошибка» там, где их две.
"""
from app.routers.client_errors_router import отпечаток

СТЕК = "\n    at MarketLandscapePanel\n    at WorkspaceScreen\n    at FilterProvider"


def test_один_сбой_один_ключ():
    a = отпечаток("Minified React error #185", "/workspace/mk_landscape2", СТЕК)
    b = отпечаток("Minified React error #185", "/workspace/mk_landscape2", СТЕК)
    assert a == b


def test_другой_экран_другой_ключ():
    рынок = отпечаток("Minified React error #185", "/workspace/mk_landscape2", СТЕК)
    чат = отпечаток("Minified React error #185", "/messages", СТЕК)
    assert рынок != чат


def test_другая_ошибка_другой_ключ():
    сто85 = отпечаток("Minified React error #185", "/messages", СТЕК)
    иное = отпечаток("Cannot read properties of undefined", "/messages", СТЕК)
    assert сто85 != иное


def test_хвост_стека_не_дробит_свёртку():
    # Место падения — верхние кадры. Ниже идёт оболочка, и она у одного и того же
    # сбоя различается: вкладки, модальные окна, порядок провайдеров. Если бы в ключ
    # шёл весь стек, одна ошибка рассыпалась бы на десяток «разных».
    верх = "\n    at SitesTable\n    at MarketRouter"
    низ_один = "\n    at TabsProvider\n    at CompanyProvider\n    at Router"
    низ_два = "\n    at DialogPortal\n    at TabsProvider\n    at Router"
    первый = отпечаток("#185", "/workspace/mk_sites", СТЕК + верх + низ_один)
    второй = отпечаток("#185", "/workspace/mk_sites", СТЕК + верх + низ_два)
    assert первый == второй


def test_пустые_поля_не_роняют():
    assert len(отпечаток("", "", None)) == 32
