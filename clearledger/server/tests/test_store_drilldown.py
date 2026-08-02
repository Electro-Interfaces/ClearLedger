"""Расшифровка строки в «Магазине»: состав накладной приезжает на фронт.

Приёмка и Поставщики раскрываются составом документа, а не отдельной ручкой, поэтому
`receipts()` обязана возвращать `lines` — раньше отдавалось только их количество.
"""
import uuid
from datetime import date
from types import SimpleNamespace

from app.services.goods_dashboard import GoodsDashboardService

PTU = [{"Документ": {
    "Дата": "2026-06-11", "Номер": "ПТУ-1", "Контрагент": "cp-1", "СуммаВключаетНДС": True,
    "Товары": [{"Номенклатура": "g-1", "Сумма": 120.0, "СуммаНДС": 20.0, "Количество": 2},
               {"Номенклатура": "g-2", "Сумма": 60.0, "СуммаНДС": 10.0, "Количество": 3}],
}}]


def _svc():
    s = GoodsDashboardService(session=None, company_id=uuid.uuid4())

    async def _p(df, dt, stations):
        return PTU

    async def _refs(kind):
        return {"cp-1": "ООО «Поставщик»"}

    async def _names():
        return {"g-1": SimpleNamespace(name="Вода 0,5"), "g-2": SimpleNamespace(name="Кофе 250 г")}

    s._load_purchases, s._refs, s._names = _p, _refs, _names
    return s


async def test_receipts_carry_document_lines():
    r = await _svc().receipts(date(2026, 6, 1), date(2026, 6, 30))
    doc = r["docs"][0]

    assert doc["supplier"] == "ООО «Поставщик»"
    assert doc["positions"] == 2
    assert [l["name"] for l in doc["lines"]] == ["Вода 0,5", "Кофе 250 г"]
    # net считается тем же правилом, что и в сводке: сумма минус НДС
    assert [l["amount_net"] for l in doc["lines"]] == [100.0, 50.0]
    assert doc["amount_net"] == 150.0
    # ref нужен, чтобы строка вела в карточку товара
    assert doc["lines"][0]["ref"] == "g-1"
