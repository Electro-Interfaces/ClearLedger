"""Псевдонимизация аккаунтов ФЛ для аналитики (152-ФЗ).

Ключ аккаунта частного лица в `charge_sessions` — сырой номер телефона
(`user_id`). Показывать его «в лоб» в аналитической панели нельзя. Здесь —
два представления:

  * `account_hash(phone)` — стабильный необратимый псевдоним (соль = SECRET_KEY
    деплоя), пригодный как ключ строки/группировки в UI вместо телефона;
  * `mask_phone(phone)`  — маскированный вид `+7 900 ***-**-67` (хвост оставлен
    для узнаваемости оператором поддержки).

Полный номер отдаётся только под отдельным правом (гейт на уровне роутера/RBAC),
а не в общей витрине. Пространство телефонов мало и брутфорсится — поэтому хеш
это НЕ анонимизация, а стабильный псевдоним; реальная защита — не отдавать сырой
номер в общий ответ.
"""
from __future__ import annotations

import hashlib

from app.config import get_settings


def _digits(phone: str | None) -> str:
    return "".join(ch for ch in phone if ch.isdigit()) if phone else ""


def account_hash(phone: str | None) -> str:
    """Стабильный псевдоним аккаунта: `ac_xxxxxxxxxxxx` (соль = SECRET_KEY)."""
    d = _digits(phone)
    if not d:
        return "ac_anon"
    salt = get_settings().secret_key or "cl-retail"
    h = hashlib.sha256(f"{salt}:{d}".encode()).hexdigest()
    return f"ac_{h[:12]}"


def mask_phone(phone: str | None) -> str:
    """Маскированный вид телефона. РФ-11 → `+7 900 ***-**-67`."""
    d = _digits(phone)
    if not d:
        return "—"
    if len(d) == 11:
        return f"+{d[0]} {d[1:4]} ***-**-{d[-2:]}"
    if len(d) >= 4:
        return f"***-{d[-2:]}"
    return "***"
