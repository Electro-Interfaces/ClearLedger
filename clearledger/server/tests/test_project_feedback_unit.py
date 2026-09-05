import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.services import ezs_lifecycle, ezs_site_work, ezs_sites, project_suggestions


@pytest.mark.asyncio
async def test_фильтры_учитываются_в_количестве_и_строках():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[SimpleNamespace(scalar_one=lambda: 0), SimpleNamespace(all=lambda: [])])
    company_id = uuid.uuid4()
    result = await ezs_sites.list_sites(db, company_id, kind="procurement", place_kind="Гостиница", page=3)
    assert result["total"] == 0 and result["page"] == 3
    for call in db.execute.call_args_list:
        statement = call.args[0].compile(dialect=postgresql.dialect())
        assert company_id in statement.params.values()
        assert "procurement" in statement.params.values()
        assert "гостиница" in statement.params.values()
        assert "coalesce(ezs_sites.kind" in str(statement)


@pytest.mark.asyncio
async def test_подсказки_ограничены_компанией_и_адресом(monkeypatch):
    monkeypatch.setattr(project_suggestions, "get_settings", lambda: SimpleNamespace(dadata_api_key=""))
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["ул. Кирова, 12"])))
    company_id = uuid.uuid4()
    result = await project_suggestions.suggest(db, company_id, "address", "Кирова", region="Свердловская область", city="Екатеринбург")
    statement = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert {company_id, "кирова", "свердловская область", "екатеринбург"} <= set(statement.params.values())
    assert result == {"items": [{"value": "ул. Кирова, 12", "source": "projects"}], "registry": "local"}


@pytest.mark.asyncio
async def test_короткий_запрос_не_выгружает_реестр(monkeypatch):
    monkeypatch.setattr(project_suggestions, "get_settings", lambda: SimpleNamespace(dadata_api_key=""))
    db = MagicMock()
    db.execute = AsyncMock()
    assert (await project_suggestions.suggest(db, uuid.uuid4(), "title", "а"))["items"] == []
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_адресный_сервис_и_резервные_подсказки(monkeypatch, unavailable):
    monkeypatch.setattr(project_suggestions, "get_settings", lambda: SimpleNamespace(dadata_api_key="test-key"))
    response = MagicMock()
    response.json.return_value = {"suggestions": [{"value": "Свердловская обл, г Екатеринбург, ул Кирова, д 12", "data": {
        "region_with_type": "Свердловская обл", "city_with_type": "г Екатеринбург", "street_with_type": "ул Кирова", "house_type": "д", "house": "12",
    }}]}
    client = MagicMock()
    client.post = AsyncMock(return_value=response, side_effect=httpx.ConnectError("offline") if unavailable else None)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(project_suggestions.httpx, "AsyncClient", lambda **kwargs: context)
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["ул. Кирова, 12"])))
    result = await project_suggestions.suggest(db, uuid.uuid4(), "address", "Кирова", region="Свердловская обл", city="Екатеринбург")
    assert result["items"][0]["source"] == "projects"
    if unavailable:
        assert result["registry"] == "unavailable"
    else:
        assert result["items"][1]["fields"] == {"region": "Свердловская обл", "city": "г Екатеринбург", "address": "ул Кирова, д 12"}
        assert client.post.call_args.kwargs["json"]["query"] == "Свердловская обл Екатеринбург Кирова"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["warehouse", "procurement", "corporate_client"])
async def test_новые_виды_работ_и_тип_объекта_сохраняются(monkeypatch, kind):
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])))
    db.flush = AsyncMock()
    monkeypatch.setattr(ezs_site_work, "next_project_no", AsyncMock(return_value="ЭЗС-2026-2000"))
    sync = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(ezs_lifecycle, "sync_from_site", sync)
    monkeypatch.setattr(ezs_site_work, "log_event", AsyncMock())
    site = await ezs_site_work.create_site(db, uuid.uuid4(), {
        "kind": kind, "stage": ezs_lifecycle.KIND_START_STAGE[kind], "title": "Новый проект",
        "address": "ул. Кирова, 12", "place_kind": "гостиница",
    }, None)
    assert site.kind == kind and site.stage == "decision" and site.place_kind == "гостиница"
    assert "place_kind" in site.manual_fields
    assert sync.call_args.args[2] is site


@pytest.mark.parametrize("label", ["АЗС/АГНС", "Гостиница", "Трасса", "Город", "БЦ/ТЦ", "Автосалон", "Общепит", "Девелопмент"])
def test_импорт_сохраняет_типы_объектов(label):
    assert ezs_sites._place_kind(label) == label.lower()
