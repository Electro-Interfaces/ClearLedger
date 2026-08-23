"""Дефолтный состав продуктов пространства (без явной записи в eco_company_apps).

Разрез Учёта на рабочие места свой у каждого профиля: у сети ЭЗС (`energy`) это
«Проекты», «Эксплуатация», «Продажи», «Финансы», «Данные»; у розницы нефтепродуктов
(`fuel`) — «Продажи», «Магазин», «Управленческий», «Бухгалтерский», «Данные». У профиля
без разреза «Учёт» остаётся единым продуктом, а плитки продуктов вели бы в пустые разделы.
"""

from app.access_catalog import system_roles_for
from app.routers.sso_router import INTERNAL_ROUTES
from app.services.app_registry import (
    _ALWAYS_ON, _BY_PROFILE, _CARVED_BY_PROFILE, _default_app_on, carved_products,
)

CARVED_PROFILES = sorted(_CARVED_BY_PROFILE)


def test_every_carved_product_has_route():
    """Плитка без маршрута ведёт в никуда: каталог /api/sso/apps строит ссылку отсюда."""
    for profile in CARVED_PROFILES:
        for code in carved_products(profile):
            assert code in INTERNAL_ROUTES, f"{profile}: {code}"


def test_product_on_only_in_its_profile():
    """Продукт включён по умолчанию ровно тем профилям, в чей разрез он входит."""
    for profile in CARVED_PROFILES:
        own = carved_products(profile)
        others = set().union(*(carved_products(p) for p in CARVED_PROFILES if p != profile))
        for code in own:
            assert _default_app_on(code, profile) is True, f"{profile}: {code}"
        for code in others - own:
            assert _default_app_on(code, profile) is False, f"{profile}: чужой {code}"


def test_carved_products_off_without_profile():
    for profile in CARVED_PROFILES:
        for code in carved_products(profile):
            assert _default_app_on(code, None) is False, code


def test_ledger_replaced_by_products_when_carved():
    """Разрезанный профиль «Учёт» плиткой не показывает — его разделы уехали в продукты."""
    for profile in CARVED_PROFILES:
        assert _default_app_on("ledger", profile) is False, profile
    assert _default_app_on("ledger", "general") is True
    assert _default_app_on("ledger", None) is True


def test_space_management_and_services_always_on():
    # `plan` из списка ушёл вместе с продуктом: «Задачи» сняты с лаунчера
    # 16.08.2026, работа компании ведётся «Треком» (`docs`).
    for code in ("admin", "chat", "conf", "info", "pulse"):
        for profile in (*CARVED_PROFILES, "general", None):
            assert _default_app_on(code, profile) is True, f"{profile}: {code}"
    # «Трек» включён во всех разрезанных профилях — именно он теперь несёт работу.
    for profile in CARVED_PROFILES:
        assert _default_app_on("docs", profile) is True, profile


def test_coordinator_needs_explicit_enable():
    assert _default_app_on("support", "energy") is False
    assert _default_app_on("support", "fuel") is False


def test_profile_names_belong_to_carved_products():
    """Имя продукта подменяется только там, где профиль его действительно получает."""
    for (code, profile), (name, desc) in _BY_PROFILE.items():
        assert code in carved_products(profile), f"{profile}: {code}"
        assert name and desc


def test_system_roles_follow_carve():
    """Роль на ключах `ledger:*` после разреза не даёт ничего — приложения нет. Набор
    системных ролей обязан идти за разрезом профиля."""
    for profile in CARVED_PROFILES:
        keys = {k for r in system_roles_for(profile) for k in (r["modules"] or [])}
        assert keys, profile
        assert not any(k.startswith("ledger") for k in keys), profile
        # Роль вправе ссылаться на продукты разреза, на всегда включённые рабочие места
        # Ядра (Задачи, Пульс, Чаты, Конференции) и на Поддержку — она подключается
        # явной записью. Раньше список был жёстким `{"support", "chat"}`, и профиль без
        # своих продуктов (офис) не мог получить ни одной осмысленной роли.
        allowed = carved_products(profile) | _ALWAYS_ON | {"support"}
        for key in keys:
            assert key.split(":")[0] in allowed, f"{profile}: {key}"
    plain = {k for r in system_roles_for("general") for k in (r["modules"] or [])}
    assert all(k.startswith("ledger") for k in plain)


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
    # Карта фронта описывает продукты, у которых есть рабочая область; продукты «на
    # вырост» (за маршрутом заставка) в неё не входят. Обратное недопустимо: продукт с
    # разделами, не попавший ни в один разрез, никому не покажется.
    every = set().union(*(carved_products(p) for p in CARVED_PROFILES))
    assert {c for c, _ in pairs} <= every, {c for c, _ in pairs} - every
