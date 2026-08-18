from __future__ import annotations

import unicodedata


class AccountingPaymentMappingBlocked(ValueError):
    code = "blocked_mapping"


_CASH = frozenset({
    "cash",
    "наличные",
    "наличными",
})
_CASHLESS = frozenset({
    "cashless",
    "безнал",
    "безналичная",
    "безналичные",
    "безналичный",
    "банковская карта",
    "банковские карты",
    "карта",
    "карта мпс",
    "карты мпс",
    "мпс",
    "прочие",
    "эквайринг",
})
_APPROVED_AGGREGATORS = frozenset({
    "autooplata",
    "payterm",
    "яндекс заправки",
})


def _key(value: object) -> str:
    return " ".join(
        unicodedata.normalize("NFC", str(value or "")).strip().casefold().split()
    )


def map_accounting_payment(value: object) -> str:
    key = _key(value)
    if key in _CASH:
        return "Наличные"
    if key in _CASHLESS or key in _APPROVED_AGGREGATORS:
        return "Безнал"
    raise AccountingPaymentMappingBlocked(
        f"Неизвестный вид оплаты '{str(value or '').strip() or '<пусто>'}'"
    )
