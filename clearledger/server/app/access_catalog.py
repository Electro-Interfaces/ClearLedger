"""
Каталог прав доступа (RBAC) экосистемы — app-namespaced.

Роль/член компании (`company_roles.modules`, `UserCompany.modules`) хранит список
разрешённых ключей:
  None  → полный доступ (admin, суперадмин, старые члены до миграции);
  list  → только перечисленные ключи.

Ключ бывает двух видов:
  `<app>`          — доступ к приложению целиком (все его модули). Напр. `support`.
  `<app>:<module>` — доступ к конкретному модулю приложения. Напр. `ledger:store`.

Историческое: раньше ключи были плоскими модулями ТОЛЬКО Ledger (`store`, `accounting`,
…). Такие ключи трактуются как `ledger:<key>` (см. `normalize_modules`) — старые роли
не ломаются. Список приложений/модулей для конструктора роли строится ДИНАМИЧЕСКИ из
реестра (`eco_apps`/`eco_app_modules`), а не из фикс-каталога — добавили приложение
манифестом, оно доступно в роли.
"""

import re

LEDGER_APP = "ledger"

# Legacy-ключи модулей Ledger (для нормализации плоских ключей старых ролей).
LEDGER_MODULE_KEYS: set[str] = {
    "management", "store", "financial", "accounting", "tax",
    "documents", "reconciliation", "sources", "locations", "onec", "catalog",
}

# Формат допустимого ключа: `app` или `app:module` (нижний регистр, цифры, _-).
_KEY_RE = re.compile(r"^[a-z0-9_-]+(:[a-z0-9_-]+)?$")

# Системные роли (сидятся в каждую компанию). app-namespaced; `ledger` = доступ к
# приложению Ledger целиком, `ledger:<module>` — к конкретному режиму/разделу.
#
# Набор зависит от ПРОФИЛЯ компании: у сети ЭЗС Учёт разрезан на продукты, и роль с
# ключами `ledger:*` не даёт ничего — приложения, на которое она ссылается, у компании
# нет. До 27.07.2026 сидился один ledger-набор, поэтому в пилоте пять системных ролей
# висели пустыми, и раздавать доступ было нечем.
SYSTEM_ROLES: list[dict] = [
    {"name": "Полный доступ", "modules": None},
    {"name": "Финансист", "modules": ["ledger", "ledger:management", "ledger:financial", "ledger:documents", "ledger:catalog"]},
    {"name": "Бухгалтер", "modules": ["ledger", "ledger:accounting", "ledger:tax", "ledger:documents", "ledger:onec", "ledger:catalog"]},
    {"name": "Оператор данных", "modules": ["ledger", "ledger:documents", "ledger:reconciliation", "ledger:sources", "ledger:locations"]},
    {"name": "Наблюдатель", "modules": ["ledger", "ledger:management"]},
]

# Профиль `energy` (сеть ЭЗС): роли по рабочим местам разреза. Коды разделов — пункты
# меню продуктов (`config/productAccess.ts` на фронте).
SYSTEM_ROLES_ENERGY: list[dict] = [
    {"name": "Полный доступ", "modules": None},
    {"name": "Проектный офис", "modules": ["projects"]},
    {"name": "Инженер эксплуатации", "modules": ["ops"]},
    {"name": "Коммерция", "modules": ["sales", "corp"]},
    # Маркетолог смотрит сегментацию сети и веб-аналитику — они живут разделами
    # «Продаж» (28.07.2026); ключ `marketing` оставлен на будущий продукт.
    {"name": "Маркетолог", "modules": [
        "marketing", "sales:cs_abcxyz", "sales:cs_trend", "sales:metrika"]},
    {"name": "Бухгалтер", "modules": ["finance"]},
    {"name": "Оператор данных", "modules": ["data"]},
    {"name": "Диспетчер поддержки", "modules": ["support", "chat"]},
    # Внешний участник: заявки и состояние железа — без коммерции, денег и данных.
    # Типовая выдача подрядчику; сузить до конкретных разделов можно матрицей.
    {"name": "Подрядчик (внешний)", "modules": [
        "support", "chat", "ops:ops_overview", "ops:eq_fleet", "ops:objects"]},
    {"name": "Наблюдатель", "modules": ["sales:cs_dashboard", "ops:ops_overview"]},
]


# Профиль `fuel` (розница нефтепродуктов): те же пять ролей, что раньше, но на ключах
# продуктов разреза. Роль с ключами `ledger:*` после разреза не даёт ничего — приложения,
# на которое она ссылается, у компании нет (на пилоте энергетики это уже ловили).
SYSTEM_ROLES_FUEL: list[dict] = [
    {"name": "Полный доступ", "modules": None},
    # Коммерция сети плюс договоры и аренда: и то и другое ведёт один человек.
    {"name": "Финансист", "modules": ["sales", "ops"]},
    {"name": "Бухгалтер", "modules": ["finance"]},
    {"name": "Оператор данных", "modules": ["data"]},
    # Сопутка и общепит — своё рабочее место: 28 экранов товарного контура.
    {"name": "Товаровед", "modules": ["shop"]},
    {"name": "Наблюдатель", "modules": ["sales"]},
]


def system_roles_for(profile_id: str | None) -> list[dict]:
    """Набор системных ролей под профиль компании.

    Набор идёт за разрезом: если у профиля Учёт разрезан на продукты, роли собираются на
    ключах продуктов, иначе — на модулях Учёта (`ledger:*`).
    """
    from app.services.app_registry import carved_products
    if not carved_products(profile_id):
        return SYSTEM_ROLES
    return SYSTEM_ROLES_ENERGY if profile_id == "energy" else SYSTEM_ROLES_FUEL


def normalize_key(key: str) -> str:
    """Плоский legacy-ключ модуля Ledger → `ledger:<key>`; остальные — как есть."""
    if ":" not in key and key in LEDGER_MODULE_KEYS:
        return f"{LEDGER_APP}:{key}"
    return key


def normalize_modules(modules: list[str] | None) -> list[str] | None:
    """Привести набор к app-namespaced. None → None.

    Плоский legacy-ключ (`store`) означал и доступ к самому Ledger — такому набору
    app-ключ `ledger` дописывается, иначе старые роли потеряли бы вход в приложение.

    ⚠ Явным ключам `<app>:<module>` app-ключ НЕ дописывается. Раньше дописывался
    любому — и право на один раздел продукта («Продажи: Реестр сессий») молча
    становилось правом на весь продукт: `module_allowed` находил ключ `sales` и
    пропускал что угодно. С разрезом Учёта на продукты это обесценивало настройку
    доступа целиком. Вход в продукт по частичному ключу всё равно открыт —
    `app_allowed` пускает по любому `<app>:*`.
    """
    if modules is None:
        return None
    out: list[str] = []
    had_legacy = False
    for k in modules:
        nk = normalize_key(k)
        if nk != k:
            had_legacy = True
        if nk not in out:
            out.append(nk)
    if had_legacy and LEDGER_APP not in out:
        out.append(LEDGER_APP)
    return out


def sanitize_modules(modules: list[str] | None) -> list[str] | None:
    """Валидация ключей роли: формат `app` / `app:module`, с нормализацией legacy.
    Каталог реальных приложений/модулей — реестр; здесь только форма ключа."""
    if modules is None:
        return None
    seen: list[str] = []
    for raw in modules:
        k = normalize_key(str(raw).strip())
        if _KEY_RE.match(k) and k not in seen:
            seen.append(k)
    return normalize_modules(seen)


def app_allowed(modules: list[str] | None, app_code: str) -> bool:
    """Доступно ли приложение `app_code`. None → да. Иначе — есть `app` (доступ к
    приложению целиком) ИЛИ любой `app:module` (доступ к модулю ⇒ к приложению)."""
    if modules is None:
        return True
    norm = normalize_modules(modules) or []
    return app_code in norm or any(k.startswith(f"{app_code}:") for k in norm)


def module_allowed(modules: list[str] | None, app_code: str, module_code: str) -> bool:
    """Доступен ли модуль `module_code` приложения `app_code`. None → да. Иначе —
    есть `app` (всё приложение) ИЛИ точный `app:module`."""
    if modules is None:
        return True
    norm = normalize_modules(modules) or []
    return app_code in norm or f"{app_code}:{module_code}" in norm


def member_allows(modules: list[str] | None, key: str) -> bool:
    """Совместимость: разрешён ли ключ (плоский legacy или app:module)."""
    if modules is None:
        return True
    norm = normalize_modules(modules) or []
    nk = normalize_key(key)
    app = nk.split(":", 1)[0]
    return nk in norm or app in norm
