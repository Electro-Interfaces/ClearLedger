"""Внешний контракт двух таблиц НСИ для opt-in setup_store_database.

Источник: Electro-Interfaces/ledger-edge @6a516071f6ab3e3abc5aabaaee2433cf08acdb36,
master/schema/001_nsi.sql (item), 007_catalog.sql (item_group, group_id).
https://github.com/Electro-Interfaces/ledger-edge/tree/6a516071f6ab3e3abc5aabaaee2433cf08acdb36/master/schema

В ClearLedger нет provisioning этих таблиц, только зависимые миграции.
DDL сохранён без комментариев; остальные таблицы/данные станции не нужны.
Проверка drift по checkout владельца схемы (без сети и учётных данных):
    python tests/store_provisioning.py --check /path/to/ledger-edge
"""
import argparse
from pathlib import Path
import re


BASE_DDL = (
    """CREATE TABLE edge.item (
        id bigserial PRIMARY KEY,
        external_uuid uuid NOT NULL UNIQUE,
        code_1c text,
        name text NOT NULL,
        name_full text,
        unit text NOT NULL DEFAULT 'шт',
        vat_rate text NOT NULL,
        kind text NOT NULL DEFAULT 'Товар',
        sku_class text,
        is_dish boolean NOT NULL DEFAULT false,
        deleted boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    );""",
    """CREATE TABLE IF NOT EXISTS edge.item_group (
        id bigserial PRIMARY KEY,
        parent_id bigint REFERENCES edge.item_group(id) ON DELETE RESTRICT,
        name text NOT NULL,
        path text NOT NULL,
        sort integer NOT NULL DEFAULT 100,
        marked_default boolean,
        adult_default boolean,
        price_owner_default text,
        note text,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (parent_id, name)
    );""",
    "ALTER TABLE edge.item ADD COLUMN IF NOT EXISTS group_id bigint REFERENCES edge.item_group(id);",
)


def check_provisioning_contract(checkout: Path) -> None:
    """Сравнить каждый сохранённый оператор с SQL владельца схемы."""
    sources = [checkout / "master/schema" / name for name in (
        "001_nsi.sql", "007_catalog.sql", "007_catalog.sql")]
    for expected, source in zip(BASE_DDL, sources, strict=True):
        sql = re.sub(r"--[^\n]*", "", source.read_text())
        statements = [" ".join(part.split()) for part in sql.split(";")]
        assert " ".join(expected.rstrip(";").split()) in statements, (
            f"Контракт provisioning разошёлся с {source}: {expected.splitlines()[0]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True, type=Path)
    try:
        check_provisioning_contract(parser.parse_args().check)
    except (OSError, AssertionError) as error:
        parser.exit(1, f"Не удалось проверить контракт provisioning: {error}\n")
    print("Контракт item/item_group совпадает с provisioning ledger-edge")
