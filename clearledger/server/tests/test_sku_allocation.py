"""Выдача артикулов: номер не повторяется, блоки станций не пересекаются.

Ровно этих гарантий не хватает соседней механике — выдаче кодов кассы: там
линейный перебор без транзакции, и два одновременных вызова возвращают один
номер. Повторять ту ошибку в артикулах нельзя: код кассы переиспользуется и
живёт до погашения, а артикул выдаётся навсегда.
"""
import uuid

import pytest

from app.models import EdgeDownlink
from app.services import sku

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_centralnyy_schyotchik_ne_povtoryaet_nomer(setup_database):
    from app.database import async_session_factory

    async with async_session_factory() as db:
        коды = [await sku.выдать_центральный(db) for _ in range(5)]
        await db.commit()

    assert len(set(коды)) == 5
    номера = [sku.разобрать(к) for к in коды]
    assert all(н is not None for н in номера)
    # Идут подряд и лежат в центральном пуле.
    assert номера == sorted(номера)
    assert номера[-1] - номера[0] == 4
    assert all(sku.ЦЕНТР_ОТ <= н <= sku.ЦЕНТР_ДО for н in номера)


async def test_bloki_stanciy_ne_peresekayutsya(setup_database):
    from app.database import async_session_factory

    company = uuid.uuid4()
    async with async_session_factory() as db:
        первый = await sku.нарезать_блок(db, company, 208)
        второй = await sku.нарезать_блок(db, company, 209)
        третий = await sku.нарезать_блок(db, company, 208)
        await db.commit()

    диапазоны = [(б["from"], б["to"]) for б in (первый, второй, третий)]
    for i, (от_a, до_a) in enumerate(диапазоны):
        assert до_a - от_a + 1 == sku.РАЗМЕР_БЛОКА
        assert sku.СТАНЦИИ_ОТ <= от_a <= sku.СТАНЦИИ_ДО
        for от_b, до_b in диапазоны[i + 1:]:
            assert до_a < от_b or до_b < от_a, "блоки пересеклись"


async def test_blok_narezaetsya_po_ostatku_stancii(setup_database):
    """Блок выдаётся с нуля и по кончающемуся запасу, а впрок — никогда."""
    from app.database import async_session_factory

    company = uuid.uuid4()
    async with async_session_factory() as db:
        # Станция на связи впервые: своих номеров у неё нет.
        первый = await sku.обеспечить_блок(db, company, 811, None)
        await db.commit()
        assert первый is not None
        assert первый["size"] == sku.РАЗМЕР_БЛОКА

        # Запас полон — резать нечего.
        assert await sku.обеспечить_блок(db, company, 811, sku.РАЗМЕР_БЛОКА) is None
        # Агент старой версии остаток не сообщает: впрок не режем.
        assert await sku.обеспечить_блок(db, company, 811, None) is None

        # Номера кончаются — центр нарезает следующий, пока связь есть.
        второй = await sku.обеспечить_блок(db, company, 811, 100)
        await db.commit()
        assert второй is not None
        assert второй["from"] > первый["to"], "блоки станции не должны пересекаться"

        # Задание с новым блоком ещё в пути, станция сообщает прежний остаток —
        # второй раз не режем: иначе за минуту доставки нарезали бы десяток.
        db.add(EdgeDownlink(
            company_id=company, station_id=811, kind="sku_block",
            payload={"block_id": второй["block_id"],
                     "from": второй["from"], "to": второй["to"]}))
        await db.commit()
        assert await sku.обеспечить_блок(db, company, 811, 100) is None
