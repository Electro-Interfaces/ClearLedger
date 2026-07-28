"""Дефолтный состав продуктов пространства (без явной записи в eco_company_apps).

Учёт разрезан на рабочие места только у профиля `energy` (сеть ЭЗС): там работают
«Проекты», «Эксплуатация», «Сеть», «Финансы», «Данные», а сам «Учёт» плиткой не
показывается. У топливного профиля разреза нет — единый «Учёт», и наоборот: плитки
продуктов вели бы в пустые разделы.
"""

from app.routers.sso_router import INTERNAL_ROUTES
from app.services.app_registry import _CARVED_PRODUCTS, _SETUP_PRODUCTS, _default_app_on


def test_setup_products_have_route_and_follow_profile():
    """Продукт «на вырост» («Сеть передачи данных», «Бухгалтерия») заведён в реестре,
    но экранов ещё не имеет: маршрут обязан существовать — иначе плитка со стола ведёт
    в «страница не найдена», а не в заставку «в подключении»."""
    for code in _SETUP_PRODUCTS:
        assert code in INTERNAL_ROUTES, code
        assert _default_app_on(code, "energy") is True, code
        assert _default_app_on(code, "fuel") is False, code


def test_carved_products_only_for_energy():
    for code in _CARVED_PRODUCTS:
        assert _default_app_on(code, "energy") is True, code
        assert _default_app_on(code, "fuel") is False, code
        assert _default_app_on(code, None) is False, code


def test_ledger_replaced_by_products_on_energy():
    assert _default_app_on("ledger", "fuel") is True
    assert _default_app_on("ledger", "energy") is False


def test_space_management_and_services_always_on():
    for code in ("admin", "chat", "plan", "conf"):
        assert _default_app_on(code, "fuel") is True
        assert _default_app_on(code, "energy") is True


def test_coordinator_needs_explicit_enable():
    assert _default_app_on("support", "energy") is False


def test_every_carved_product_has_route():
    """Плитка без маршрута ведёт в никуда: каталог /api/sso/apps строит ссылку отсюда."""
    for code in _CARVED_PRODUCTS:
        assert code in INTERNAL_ROUTES, code


def test_routes_match_frontend_map():
    """Маршруты продуктов заданы дважды — в реестре (здесь) и в карте фронта. Разъезд
    даёт плитку в 404, поэтому сверяем пары код→маршрут напрямую по файлу карты."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "config" / "spaceProducts.ts"
    if not src.exists():           # бэкенд собирается без фронта (образ) — сверять нечем
        return
    pairs = re.findall(r"code:\s*'([a-z]+)',\s*route:\s*'([^']+)'", src.read_text(encoding="utf-8"))
    assert pairs, "карта продуктов не разобралась — изменился формат spaceProducts.ts"
    for code, route in pairs:
        assert INTERNAL_ROUTES.get(code) == route, f"{code}: {INTERNAL_ROUTES.get(code)} != {route}"
    assert {c for c, _ in pairs} == _CARVED_PRODUCTS
