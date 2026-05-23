class OneCError(Exception):
    """Базовая ошибка интеграции с 1С."""


class OneCConnectionError(OneCError):
    """Сетевая ошибка: timeout, connection refused, DNS."""


class OneCAuthError(OneCError):
    """HTTP 401/403 от 1С — неверный логин/пароль или недостаточно прав."""


class OneCNotFoundError(OneCError):
    """HTTP 404 — несуществующий объект метаданных или ключ."""


class OneCTimeoutError(OneCConnectionError):
    """Запрос не уложился в таймаут."""
