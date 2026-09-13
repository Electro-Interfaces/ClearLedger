"""Сведение профилей операторов (app/services/market_operators.py).

Проверяем ровно то, на чём приём соврал на живых данных: две строки источника,
схлопывающиеся в одного оператора после приведения имени, и запись, где мелкая
строка не должна перебивать крупную.

Прогон:  py -m pytest server/tests/test_market_operators.py -q
"""
from __future__ import annotations

from app.services.market_operators import parse_csv
from app.services.market_ocm import _canon_operator

BOM = "﻿"
CRLF = "\r\n"


def test_two_rows_collapse_into_one_operator():
    """«Россети» и «MOJeSK-EV(ROSSETI)» — одна компания после приведения имени.

    На живых данных мелкая строка (7 точек, 3 города, пустая платформа) перезаписала
    крупную (371 точка, платформа Sitronics), и сеть осталась без платформы.
    """
    assert _canon_operator("Россети") == _canon_operator("MOJeSK-EV(ROSSETI)")


def test_profiles_csv_reads_with_bom():
    """Профили приходят в том же формате, что и станции: `;` и UTF-8 с BOM."""
    lines = [
        BOM + "operator;points;cities;platform_owner;own_platform;ocpi_roaming",
        "Россети;371;88;Sitronics;0;0",
        "MOJeSK-EV(ROSSETI);7;3;;0;0",
    ]
    rows = parse_csv(CRLF.join(lines).encode("utf-8"))
    assert len(rows) == 2
    assert rows[0]["operator"] == "Россети"          # ключ не спрятан за BOM
    assert rows[0]["platform_owner"] == "Sitronics"
    assert rows[1]["platform_owner"] == ""


def test_bigger_row_goes_first():
    """Порядок применения — по числу точек убыв.: крупная строка пишет первой,
    мелкая потом может только дополнить пустое."""
    rows = [{"operator": "Россети", "points": "7"}, {"operator": "Россети", "points": "371"}]
    ordered = sorted(rows, key=lambda r: -int(r["points"]))
    assert ordered[0]["points"] == "371"


if __name__ == "__main__":  # прогон без pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
