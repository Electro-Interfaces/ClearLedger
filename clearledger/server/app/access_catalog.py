"""
Каталог модулей доступа (RBAC) — backend-зеркало src/config/accessModules.ts.

Член компании (UserCompany) имеет список разрешённых ключей `modules`:
  None  → полный доступ (admin, суперадмин, старые члены до миграции);
  list  → только перечисленные ключи.
"""

# Все допустимые ключи доступа (валидация входных modules).
ACCESS_KEYS: set[str] = {
    "management", "financial", "accounting", "tax",
    "documents", "reconciliation", "sources", "locations", "onec", "catalog",
}

# Системные роли (сидятся в каждую компанию) — зеркало ACCESS_PRESETS фронта.
SYSTEM_ROLES: list[dict] = [
    {"name": "Полный доступ", "modules": None},
    {"name": "Финансист", "modules": ["management", "financial", "documents", "catalog"]},
    {"name": "Бухгалтер", "modules": ["accounting", "tax", "documents", "onec", "catalog"]},
    {"name": "Оператор данных", "modules": ["documents", "reconciliation", "sources", "locations"]},
    {"name": "Наблюдатель", "modules": ["management"]},
]


def sanitize_modules(modules: list[str] | None) -> list[str] | None:
    """Оставить только валидные ключи; None → None (полный доступ)."""
    if modules is None:
        return None
    return [k for k in modules if k in ACCESS_KEYS]


def member_allows(modules: list[str] | None, key: str) -> bool:
    """Разрешён ли модуль key при наборе modules (None = всё разрешено)."""
    if modules is None:
        return True
    return key in modules
