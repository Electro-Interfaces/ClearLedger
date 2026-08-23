"""Мост «проект ↔ кейс»: что уезжает в Координатор и когда проект считается введённым.

Ловим три тихие поломки, каждая из которых даёт неверную запись в учёте или
неверный доступ, но ни одна не падает с ошибкой:

  • дата ввода в эксплуатацию проставлена, хотя воронка проект НЕ приняла —
    это основание перевода капвложений со счёта 08 на 01, и ложная дата тут
    дороже любой ошибки в интерфейсе;
  • в сводке кейса пропал `project_kind` — развилка маршрута на входе считается
    по нему, и без него новое строительство поедет по короткому пути переноса;
  • состав участников уехал без роли регламента — тогда слой прав по участию
    пропускает кнопку ОКС кому угодно.

Координатор здесь не поднимаем: проверяем нашу половину моста, подменив вызов.
"""
import pytest
from sqlalchemy import select

from app.models import Company, EzsSite, EzsSiteParticipant, User
from app.services import projects_process as pp


# --- сводка проекта -------------------------------------------------------

def test_контекст_несёт_ось_развилки_и_не_несёт_лишнего():
    site = EzsSite(kind="relocation", stage="build", project_no="ЭЗС-0007",
                   region_norm="Приморский край", full_address="Владивосток, Светланская 1")
    ctx = pp._context(site)

    assert ctx["project_kind"] == "relocation"
    assert ctx["eco_stage"] == "build"
    assert ctx["eco_project_no"] == "ЭЗС-0007"
    # Сводка — не копия карточки: в кейс не уезжают ни экономика, ни документы.
    assert set(ctx) == {"project_kind", "eco_stage", "eco_project_no",
                        "eco_region", "eco_address"}


def test_вид_проекта_по_умолчанию_новое_строительство():
    # Пустой kind не должен превращаться в None: условие ребра сравнивает строку,
    # и None увёл бы проект в ветку «не новое строительство» молча.
    assert pp._context(EzsSite(kind=None))["project_kind"] == "new_build"


# --- состав участников ----------------------------------------------------

async def test_участники_уезжают_с_ролью_регламента(db):
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    user = User(email="oks@test.ru", name="ОКС", password_hash="x", company_id=company.id)
    db.add(user)
    await db.flush()

    site = EzsSite(company_id=company.id, title="Мост: состав", kind="new_build",
                   stage="lead")
    db.add(site)
    await db.flush()
    db.add(EzsSiteParticipant(company_id=company.id, site_id=site.id,
                              user_id=user.id, role_code="ОКС"))
    await db.flush()

    rows = await pp._participants(db, site)
    assert rows == [{"email": "oks@test.ru", "roleCode": "ОКС",
                     "ecoUserId": str(user.id)}]
    await db.rollback()


# --- ввод в эксплуатацию --------------------------------------------------

class _FakeWork:
    """Подменяет воронку: принял проект или удержал на гейтах."""

    def __init__(self, moved: bool):
        self.result = {"moved": moved, "blocking": [] if moved else ["Акт ввода"],
                       "message": None if moved else "Не закрыты обязательные пункты"}

    # Сигнатура повторяет настоящую `ezs_site_work.set_stage`, включая
    # именованные-только параметры: подделка, отставшая от контракта, падает
    # на TypeError и выглядит поломкой продукта.
    async def set_stage(self, db, site, stage, *, reason=None, user=None,
                        may_override=False, override=False, source="user"):
        if self.result["moved"]:
            site.stage = stage
        return self.result



def _facade(step_code: str, step_name: str):
    """Фасад в ответ на два вызова: найти процесс предмета и двинуть его.

    Раньше мост звал одну ручку и получал «стадию»; теперь сначала спрашивает,
    заведён ли процесс, и только потом действует — поэтому и подделка двойная.
    """
    async def fake_call(db_, company_id, method, path, *, json=None, params=None):
        if path.endswith("/instances"):
            return {"instances": [{"processId": "p-1"}]}
        return {"processId": "p-1", "currentStep": {"code": step_code, "name": step_name}}
    return fake_call

@pytest.mark.parametrize("moved,ожидаем_дату", [(True, True), (False, False)])
async def test_дата_ввода_только_когда_воронка_приняла(db, monkeypatch, moved,
                                                       ожидаем_дату):
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    # `build` — это ЭТАП воронки («Реализация»), а не стадия: стадии внутри него
    # называются `construction` и `commissioning`. Проект на несуществующей
    # стадии считается снятым с воронки, и маршрут честно отвечал «верните его
    # в работу» — проверка ловила не гейты, а собственную опечатку.
    site = EzsSite(company_id=company.id, title=f"Мост: ввод {moved}",
                   kind="new_build", stage="construction")
    db.add(site)
    await db.flush()

    monkeypatch.setattr(pp, "_call", _facade("ezs_commissioning", "Ввод в эксплуатацию"))
    import app.services.ezs_site_work as work
    monkeypatch.setattr(work, "set_stage", _FakeWork(moved).set_stage)

    state = await pp.apply_step(db, company.id, site, "link-1", {}, None)

    assert state["funnel"]["moved"] is moved
    assert (site.commissioned_on is not None) is ожидаем_дату
    if not moved:
        # Гейт держит — маршрут об этом сообщает, а не обходит молча.
        assert state["funnel"]["blocking"] == ["Акт ввода"]
        assert site.stage == "construction"
    await db.rollback()


async def test_промежуточная_стадия_воронку_не_трогает(db, monkeypatch):
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    site = EzsSite(company_id=company.id, title="Мост: середина маршрута",
                   kind="new_build", stage="build")
    db.add(site)
    await db.flush()

    monkeypatch.setattr(pp, "_call", _facade("ezs_pnr", "Пусконаладка"))

    state = await pp.apply_step(db, company.id, site, "link-1", {}, None)
    assert "funnel" not in state
    assert site.commissioned_on is None
    await db.rollback()
