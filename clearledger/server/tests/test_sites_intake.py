"""Заведение проекта и поиск по реестру — две схемы ввода, где ошибка молчит.

Обе проверки ловят поломки без исключений, но с последствиями:

  • вид работы, не сохранённый при заведении, уводит перенос по маршруту нового
    строительства — с подбором земли и договором, которых у переноса нет;
  • поиск, не знающий названия и номера, отвечает «проектов не найдено» на точное
    имя проекта, и менеджер читает это как потерю данных.
"""
import pytest
from sqlalchemy import select

from app.models import Company, EzsProject
from app.services import ezs_site_work, ezs_sites


async def _company(db):
    return (await db.execute(select(Company).limit(1))).scalars().first()


# --- вид работы на входе --------------------------------------------------

@pytest.mark.parametrize("kind,ожидаем", [
    ("relocation", "relocation"),
    ("decommission", "decommission"),
    (None, "new_build"),          # не указали — стройка, как и раньше
    ("нет такого", "new_build"),  # мусор из внешнего вызова не должен доехать до графа
])
async def test_вид_работы_сохраняется_при_заведении(db, kind, ожидаем):
    company = await _company(db)
    payload = {"address": f"Проверка вида {kind}", "region": "Тест"}
    if kind is not None:
        payload["kind"] = kind

    site = await ezs_site_work.create_site(db, company.id, payload, None)
    assert site.kind == ожидаем

    # Проект-спутник отражает тот же вид: иначе перенос не попадёт в «План работ»,
    # который новое строительство как раз не берёт.
    p = (await db.execute(select(EzsProject).where(EzsProject.site_id == site.id))).scalars().first()
    assert p is not None and p.kind == ожидаем
    await db.rollback()


# --- поиск по реестру -----------------------------------------------------

async def test_поиск_находит_по_названию_и_номеру(db):
    company = await _company(db)
    site = await ezs_site_work.create_site(db, company.id, {
        "title": "ЭЗС на парковке ТЦ «Гринвич»",
        "address": "ул. Кирова, 12", "city": "Екатеринбург",
    }, None)
    await db.flush()

    for запрос in ("гринвич", site.project_no, "кирова", "екатеринбург"):
        found = await ezs_sites.list_sites(db, company.id, search=запрос)
        assert any(r["id"] == str(site.id) for r in found["items"]), f"не нашли по «{запрос}»"

    пусто = await ezs_sites.list_sites(db, company.id, search="такого адреса нет ни у кого")
    assert пусто["total"] == 0
    await db.rollback()


async def test_приостановленные_проекты_доступны_отдельным_фильтром(db):
    company = await _company(db)
    paused = await ezs_site_work.create_site(db, company.id, {
        "title": "Проект в статусе не трогать",
        "address": "Проверка приостановленного проекта",
    }, None)
    paused.stage = "on_hold"
    await db.flush()

    search = "проверка приостановленного проекта"
    on_hold = await ezs_sites.list_sites(db, company.id, stage="on_hold", search=search)
    active = await ezs_sites.list_sites(db, company.id, stage="active", search=search)
    archived = await ezs_sites.list_sites(db, company.id, stage="archive", search=search)

    assert any(row["id"] == str(paused.id) for row in on_hold["items"])
    assert all(row["id"] != str(paused.id) for row in active["items"])
    assert all(row["id"] != str(paused.id) for row in archived["items"])
    await db.rollback()
