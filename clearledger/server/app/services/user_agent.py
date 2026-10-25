"""Человеческое название устройства из строки User-Agent.

Полная строка UA в интерфейсе бесполезна: человек не опознаёт в ней свой
ноутбук. Нужно ровно два слова — браузер и система, — чтобы в списке устройств
и в журнале входов он сказал «это я с рабочего компьютера», а про остальное
спросил.

Разбор нарочно грубый и без зависимостей: точность до версии здесь не нужна,
а библиотека разбора UA — это обновляемая база ради одной подписи в профиле.
"""
import re

_БРАУЗЕРЫ: tuple[tuple[str, str], ...] = (
    # Порядок важен: Edge и Opera представляются Chrome, Chrome — Safari.
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("YaBrowser/", "Яндекс.Браузер"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)

_СИСТЕМЫ: tuple[tuple[str, str], ...] = (
    ("Windows NT", "Windows"),
    ("Android", "Android"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def describe(ua: str | None) -> str:
    """«Chrome · Windows». Неизвестное — «Неизвестное устройство»."""
    if not ua:
        return "Неизвестное устройство"
    браузер = next((имя for метка, имя in _БРАУЗЕРЫ if метка in ua), None)
    система = next((имя for метка, имя in _СИСТЕМЫ if метка in ua), None)
    части = [ч for ч in (браузер, система) if ч]
    return " · ".join(части) if части else "Неизвестное устройство"


def short(ua: str | None, limit: int = 300) -> str | None:
    """Строка UA для хранения: пробелы в порядок, длина в предел колонки."""
    if not ua:
        return None
    return re.sub(r"\s+", " ", ua).strip()[:limit] or None
