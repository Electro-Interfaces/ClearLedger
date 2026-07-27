"""Права на разделы продуктов: ключ `<app>:<module>` не должен раздуваться до `<app>`.

Проверяем ровно то, что ломалось: раньше `normalize_modules` дописывал app-ключ любому
набору с `app:module`, и роль «Продажи: только Реестр сессий» получала весь продукт.
"""
from app.access_catalog import (
    app_allowed, member_allows, module_allowed, normalize_modules, sanitize_modules,
)


def test_частичный_ключ_продукта_не_даёт_продукт_целиком():
    mods = ["sales:cs_list"]
    assert normalize_modules(mods) == ["sales:cs_list"]
    assert app_allowed(mods, "sales")                    # вход в рабочее место открыт
    assert module_allowed(mods, "sales", "cs_list")
    assert not module_allowed(mods, "sales", "cs_clients")   # другой раздел — закрыт
    assert not app_allowed(mods, "finance")


def test_ключ_продукта_целиком_покрывает_разделы():
    mods = ["sales"]
    assert module_allowed(mods, "sales", "cs_list")
    assert module_allowed(mods, "sales", "чего-угодно")


def test_legacy_плоский_ключ_сохраняет_доступ_к_учёту():
    """Старые роли (плоские модули Ledger) продолжают входить в само приложение."""
    norm = normalize_modules(["store", "accounting"])
    assert norm == ["ledger:store", "ledger:accounting", "ledger"]
    assert app_allowed(["store"], "ledger")
    assert member_allows(["store"], "store")


def test_полный_доступ_остаётся_none():
    assert normalize_modules(None) is None
    assert sanitize_modules(None) is None
    assert module_allowed(None, "sales", "cs_list")


def test_санитайзер_принимает_коды_разделов_продуктов():
    """Коды пунктов меню (`cs_dashboard`, `online-orders`, `eq_fleet`) — валидные ключи."""
    keys = ["sales:cs_dashboard", "ops:eq_fleet", "shop:online-orders", "data:normalize"]
    assert sanitize_modules(keys) == keys
    assert sanitize_modules(["ПЛОХОЙ КЛЮЧ", "sales:cs_map"]) == ["sales:cs_map"]
