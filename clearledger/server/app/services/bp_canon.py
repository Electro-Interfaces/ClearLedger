"""
Канонизация JSON и SHA-256 хеш пакета «смена ЦБ→БП» — точная реплика 1С-модуля
TL_ЭкспортБП_Идемпотентность (ext-cb-export). Нужна для идемпотентности: приёмник
БП (РС.TL_СоответствиеИсточников) распознаёт «тот же пакет» по ХешПакета.

Алгоритм канонизации (§5.3 контракта, см. STORE_BP_EXPORT_CONTRACT.md):
  1. Удалить поле "ХешПакета" на верхнем уровне.
  2. Объекты — рекурсивно отсортировать ключи РЕГИСТРОНЕЗАВИСИМО (1С
     СписокЗначений.СортироватьПоЗначению == casefold; проверено на 5 боевых
     пакетах — совпадает и с Windows-locale ru, но casefold портируем на Linux).
  3. Числа: целые "123", дробные "123.45" (точка), до 6 знаков, без trailing нулей; 0 → "0".
  4. Строки: экранирование ", \\, управляющих (\\b\\t\\n\\f\\r\\uXXXX); Unicode > U+007F как есть.
     == json.dumps(ensure_ascii=False) (проверено идентично 1С-экранированию).
  5. Массивы — порядок сохраняется.
  6. Без пробелов/переносов/BOM. SHA-256 от UTF-8, hex lowercase.

Проверено: reproduces ХешПакета 5/5 боевых пакетов ext-cb-export/epf/out/.
"""
from __future__ import annotations

import hashlib
import json


def _canon_str(s: str) -> str:
    # 1С-экранирование строки идентично json.dumps(ensure_ascii=False)
    return json.dumps(s, ensure_ascii=False)


def _canon_num(n: float | int) -> str:
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    a = abs(n)
    s = f"{a:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return sign + s


def _sort_keys(keys: list[str]) -> list[str]:
    # Регистронезависимая сортировка (1С СортироватьПоЗначению). Вторичный ключ —
    # сама строка, для детерминизма при равных casefold.
    return sorted(keys, key=lambda s: (s.casefold(), s))


def canonicalize(value, drop_hash: bool = False) -> str:
    """Каноническая JSON-строка значения (без хеша). drop_hash — убрать
    поле 'ХешПакета' только на верхнем уровне."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        keys = _sort_keys([k for k in value.keys() if not (drop_hash and k == "ХешПакета")])
        return "{" + ",".join(_canon_str(k) + ":" + canonicalize(value[k]) for k in keys) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonicalize(e) for e in value) + "]"
    if isinstance(value, str):
        return _canon_str(value)
    if isinstance(value, (int, float)):
        return _canon_num(value)
    return _canon_str(str(value))


def packet_hash(packet: dict) -> str:
    """SHA-256 (hex lowercase, 64 симв.) канонической формы пакета без ХешПакета."""
    return hashlib.sha256(canonicalize(packet, drop_hash=True).encode("utf-8")).hexdigest().lower()
