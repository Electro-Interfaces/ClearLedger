ACCOUNTING_DOCUMENT_KINDS = (
    "purchase",
    "return_purchase",
    "transfer",
    "inventory",
    "gain",
    "writeoff",
    "retail_sale_sidegoods",
    "return_sale",
    "recipe",
    "production_release",
    "ingredients_writeoff",
)

PROJECTION_DOCUMENT_KINDS = ACCOUNTING_DOCUMENT_KINDS + (
    "fiscal_receipt",
    "store_shift",
    "revaluation",
)


def require_projection_document_kind(kind: object) -> str:
    value = str(kind or "").strip()
    if value not in PROJECTION_DOCUMENT_KINDS:
        raise ValueError(
            f"Тип документа {value or 'пусто'} не разрешён для сопутки/общепита"
        )
    return value
