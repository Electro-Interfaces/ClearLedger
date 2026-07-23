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
SYSTEM_ROLES: list[dict] = [
    {"name": "Полный доступ", "modules": None},
    {"name": "Финансист", "modules": ["ledger", "ledger:management", "ledger:financial", "ledger:documents", "ledger:catalog"]},
    {"name": "Бухгалтер", "modules": ["ledger", "ledger:accounting", "ledger:tax", "ledger:documents", "ledger:onec", "ledger:catalog"]},
    {"name": "Оператор данных", "modules": ["ledger", "ledger:documents", "ledger:reconciliation", "ledger:sources", "ledger:locations"]},
    {"name": "Наблюдатель", "modules": ["ledger", "ledger:management"]},
]


def normalize_key(key: str) -> str:
    """Плоский legacy-ключ модуля Ledger → `ledger:<key>`; остальные — как есть."""
    if ":" not in key and key in LEDGER_MODULE_KEYS:
        return f"{LEDGER_APP}:{key}"
    return key


def normalize_modules(modules: list[str] | None) -> list[str] | None:
    """Привести набор к app-namespaced. None → None. Если после нормализации есть
    хоть один `ledger:*`, но нет `ledger` (app-доступ) — добавляем его: у старых
    ролей был доступ к Ledger как к приложению неявно."""
    if modules is None:
        return None
    out: list[str] = []
    for k in modules:
        nk = normalize_key(k)
        if nk not in out:
            out.append(nk)
    apps = {k.split(":", 1)[0] for k in out}
    for app in list(apps):
        if app not in out and any(k.startswith(f"{app}:") for k in out):
            out.append(app)
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
