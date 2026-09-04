"""Правила матрицы: кто побеждает и почему.

Порядок конкретности — единственное, что нельзя сломать незаметно: если он
поедет, товаровед выдаст станции право, а оно не сработает, и никто не поймёт
почему. Поэтому лестница проверяется целиком, а не выборочно.
"""
import uuid

import pytest
from sqlalchemy import text

from app.services import matrix

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _подготовить(db, company):
    """Дерево групп и позиция в глубокой ветке."""
    таб = (await db.execute(text("""
        INSERT INTO edge.item_group (name, path) VALUES ('Табак', 'Табак')
        RETURNING id"""))).scalar()
    стики = (await db.execute(text("""
        INSERT INTO edge.item_group (parent_id, name, path)
        VALUES (:p, 'Стики', 'Табак / Стики') RETURNING id"""), {"p": таб})).scalar()
    # Ловушка соседнего имени: «Табак» не должен накрывать «Табакерку».
    табакерка = (await db.execute(text("""
        INSERT INTO edge.item_group (name, path) VALUES ('Табакерка', 'Табакерка')
        RETURNING id"""))).scalar()

    def позиция(имя, группа):
        return db.execute(text("""
            INSERT INTO edge.item (external_uuid, name, vat_rate, group_id)
            VALUES (gen_random_uuid(), :n, 'НДС22', :g) RETURNING id
        """), {"n": имя, "g": группа})

    стик = (await позиция("Стики HEETS Amber", стики)).scalar()
    сувенир = (await позиция("Табакерка сувенирная", табакерка)).scalar()
    await db.commit()
    return {"група_табак": таб, "группа_стики": стики, "стик": стик, "сувенир": сувенир}


async def test_umolchaniya_kogda_pravil_net(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        цена = await matrix.разрешить(db, company, matrix.PRICE, 208, д["стик"])
        ассорт = await matrix.разрешить(db, company, matrix.ASSORTMENT, 208, д["стик"])

    # Цена по умолчанию сетевая, позиция по умолчанию доступна всем.
    assert цена.allow is False and цена.по_умолчанию
    assert ассорт.allow is True and ассорт.по_умолчанию
    assert "цена сетевая" in цена.объяснение()


async def test_stanciya_silnee_seti(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=False,
            reason="по умолчанию цену ведёт центр")
        await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=True, station_id=208,
            reason="АЗС 208 ведёт цены сама — политика v1")
        await db.commit()
        решение = await matrix.разрешить(db, company, matrix.PRICE, 208, д["стик"])
        чужая = await matrix.разрешить(db, company, matrix.PRICE, 209, д["стик"])

    assert решение.allow is True
    assert решение.сработало.station_id == 208
    assert len(решение.перебиты) == 1, "сетевое правило обязано быть видно как перебитое"
    # Другой станции разрешение 208 не досталось.
    assert чужая.allow is False


async def test_zhyostkiy_zapret_bjot_stancionnoe_razreshenie(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=True, station_id=208,
            reason="АЗС 208 ведёт цены сама")
        await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=False, hard=True,
            group_id=д["група_табак"],
            reason="МРЦ: цену табака ведёт только центр, ст. 13 ФЗ-15")
        await db.commit()
        решение = await matrix.разрешить(db, company, matrix.PRICE, 208, д["стик"])

    assert решение.allow is False, "жёсткий запрет обязан перебить станционное право"
    assert решение.сработало.hard
    assert решение.перебиты[0].station_id == 208, "перебитое право должно быть видно"


async def test_glubokaya_gruppa_bjot_vyshestoyashchuyu(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        await matrix.завести_правило(
            db, company, subject=matrix.ASSORTMENT, allow=False, station_id=208,
            group_id=д["група_табак"], reason="табак на этой АЗС не возим")
        await matrix.завести_правило(
            db, company, subject=matrix.ASSORTMENT, allow=True, station_id=208,
            group_id=д["группа_стики"], reason="стики оставляем — спрос есть")
        await db.commit()
        стик = await matrix.разрешить(db, company, matrix.ASSORTMENT, 208, д["стик"])

    assert стик.allow is True
    assert стик.сработало.group_path == "Табак / Стики"


async def test_sosednee_imya_gruppy_ne_nakryvaetsya(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        await matrix.завести_правило(
            db, company, subject=matrix.ASSORTMENT, allow=False, station_id=208,
            group_id=д["група_табак"], reason="табак не возим")
        await db.commit()
        табак = await matrix.разрешить(db, company, matrix.ASSORTMENT, 208, д["стик"])
        сувенир = await matrix.разрешить(db, company, matrix.ASSORTMENT, 208, д["сувенир"])

    assert табак.allow is False
    # «Табак» не должен накрывать «Табакерку» — иначе сувенир исчез бы с полки.
    assert сувенир.allow is True and сувенир.по_умолчанию


async def test_pravilo_ne_pravitsya_a_zakryvaetsya(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        д = await _подготовить(db, company)
        первое = await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=True, station_id=208,
            reason="разрешили в августе")
        второе = await matrix.завести_правило(
            db, company, subject=matrix.PRICE, allow=False, station_id=208,
            reason="отобрали в сентябре")
        await db.commit()

        assert второе["replaced"] == первое["id"], "старое правило обязано закрыться"
        действующие = await matrix.правила_компании(db, company, matrix.PRICE)
        вся_история = await matrix.правила_компании(
            db, company, matrix.PRICE, включая_закрытые=True)
        решение = await matrix.разрешить(db, company, matrix.PRICE, 208, д["стик"])

    assert len(действующие) == 1 and действующие[0]["allow"] is False
    assert len(вся_история) == 2, "история прав не переписывается"
    assert решение.allow is False


async def test_pravilo_bez_prichiny_ne_zavoditsya(setup_database):
    from app.database import async_session_factory
    company = uuid.uuid4()
    async with async_session_factory() as db:
        with pytest.raises(ValueError):
            await matrix.завести_правило(
                db, company, subject=matrix.PRICE, allow=True, station_id=208, reason="  ")
        # Жёсткий запрет — только сетевой: иначе станция перебивала бы сама себя.
        with pytest.raises(ValueError):
            await matrix.завести_правило(
                db, company, subject=matrix.PRICE, allow=False, hard=True,
                station_id=208, reason="так нельзя")
        await db.rollback()
