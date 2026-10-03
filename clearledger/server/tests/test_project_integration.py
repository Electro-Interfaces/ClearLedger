import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.models import EzsSite, ServiceLocation, MarketSite
from app.services import project_integration as integration
from app.services.ezs_site_work import gate_state
from app.services.projects_process import _context, _pending_diff


def site(stage="lead"):
    return EzsSite(id=uuid.uuid4(), company_id=uuid.uuid4(), kind="integration", stage=stage,
                   gates={}, workspace_data={}, owner_user_id=uuid.uuid4())


def scenario(**patch):
    return {"id": "scenario-1", "direction": "outgoing", "format": "information",
            "selectedIds": ["station-a", "station-b"], "agreedIds": [],
            "connectedIds": [], "pilotIds": [], **patch}


def test_перечни_фиксированы_и_не_зависят_от_условий_фильтра():
    s = site()
    data = integration.normalize({"revision": 0, "scenarios": [scenario()]}, integration.read(s))
    assert data["scenarios"][0]["selectedIds"] == ["station-a", "station-b"]
    assert data["scenarios"][0]["agreedIds"] == []
    assert data["scenarios"][0]["connectedIds"] == []
    assert s.location_id is None


@pytest.mark.parametrize("field,ids", [("pilotIds", ["outside"]), ("agreedIds", ["outside"]), ("connectedIds", ["station-a"])])
def test_подмножества_станций_проверяются_на_сервере(field, ids):
    with pytest.raises(ValueError):
        integration.normalize({"revision": 0, "scenarios": [scenario(**{field: ids})]}, integration.read(site()))


def test_пилот_и_подключение_раздельны():
    s = site()
    data = integration.normalize({"revision": 0, "scenarios": [scenario(agreedIds=["station-a"], pilotIds=["station-b"])]}, integration.read(s))
    assert data["scenarios"][0]["connectedIds"] == []
    assert data["scenarios"][0]["pilotIds"] == ["station-b"]


def test_старое_сохранение_не_переписывает_новые_данные():
    old = integration.read(site())
    old["revision"] = 4
    with pytest.raises(ValueError, match="Карточка изменилась"):
        integration.normalize({"revision": 3, "partner": {"name": "Старое"}}, old)


def test_одно_направление_и_формат_на_сценарий():
    with pytest.raises(ValueError, match="одно направление"):
        integration.normalize({"revision": 0, "scenarios": [scenario(direction="both")]}, integration.read(site()))


def test_паспорт_сам_не_подтверждает_чек_лист():
    s = site()
    data = integration.read(s)
    data["partner"] = {"name": "Партнёр", "purpose": "Роуминг"}
    s.workspace_data = {"integration": data}
    assert not gate_state(s)["canAdvance"]
    assert not next(i for i in gate_state(s)["items"] if i["key"] == "1.1")["done"]
    assert integration.confirmation_problem(s, "1.1", data)


def test_нужен_содержательный_результат_и_причина_неприменимости():
    s = site()
    data = integration.read(s)
    data["results"]["5.6"] = {"notApplicable": True}
    assert integration.confirmation_problem(s, "5.6", data) == "Укажите причину неприменимости"
    data["results"]["5.6"]["comment"] = "Информационный сценарий без команд"
    assert integration.confirmation_problem(s, "5.6", data) is None


def test_файл_не_равен_согласованному_или_подписанному_договору():
    s = site()
    data = integration.read(s)
    data["results"]["6.6"] = {"comment": "Подписано"}
    data["documents"] = [{"id": "doc", "kind": "contract", "fileDocId": "file", "agreedDocId": "file"}]
    assert integration.confirmation_problem(s, "6.6", data)
    data["documents"][0].update(signedDocId="signed", signingEvidence="02.10.2026, обе стороны, скан")
    assert integration.confirmation_problem(s, "6.6", data) is None
    data["results"]["4.3"] = {"comment": "Есть договор"}
    assert integration.confirmation_problem(s, "4.3", data)


def test_существенная_правка_открывает_подтверждённый_пункт():
    s = site("negotiation")
    data = integration.read(s)
    data["commercial"] = {"commission": "5 %", "settlements": "Ежемесячно"}
    s.workspace_data = {"integration": data}
    s.gates = {"negotiation": {"2.2": {"done": True, "snapshot": integration.snapshot(s, "2.2")}}}
    assert next(i for i in gate_state(s)["items"] if i["key"] == "2.2")["done"]
    revised = deepcopy(data)
    revised["commercial"]["commission"] = "7 %"
    s.workspace_data = {"integration": revised}
    item = next(i for i in gate_state(s)["items"] if i["key"] == "2.2")
    assert not item["done"] and item["needsConfirmation"]
    assert item["label"] in gate_state(s)["blocking"]


def test_изменение_другого_раздела_не_снимает_согласование():
    s = site("negotiation")
    data = integration.read(s)
    before = integration.snapshot(s, "2.2", data)
    data["partner"]["commercialContact"] = "Новый контакт"
    assert integration.snapshot(s, "2.2", data) == before


def test_повторное_согласование_прошлого_этапа_держит_следующий_переход():
    s = site("dd")
    s.gates = {"negotiation": {"2.2": {"done": True, "needs_confirmation": True}}}
    assert any("повторного подтверждения" in label for label in gate_state(s)["blocking"])


def test_устаревшее_послабление_можно_подтвердить_повторно(monkeypatch):
    from app.services import ezs_site_work
    events = AsyncMock()
    monkeypatch.setattr(ezs_site_work, "log_event", events)
    monkeypatch.setattr(ezs_site_work, "gate_now", AsyncMock(return_value={}))
    s = site("negotiation")
    s.gates = {"negotiation": {"2.1": {"waived": True, "needs_confirmation": True}}}
    user = SimpleNamespace(id=uuid.uuid4(), name="Ответственный", email="test@example.test")
    res = asyncio.run(ezs_site_work.set_gate_waiver(None, s, "2.1", True, "Повторно принято", user))
    assert res["ok"] and not res.get("unchanged")
    mark = s.gates["negotiation"]["2.1"]
    assert mark["waived"] and not mark["done"] and not integration.stale(s, "2.1", mark)
    assert events.await_count == 1


def test_строительные_поля_не_переносятся_в_интеграцию():
    from app.services.projects_process import _reflect_step_fields
    s = site()
    assert _reflect_step_fields(s, {"control_form": "Аренда", "contractor": "Строитель"}) == []
    assert s.control_form is None


def test_нельзя_подтвердить_фактическое_подключение_одним_сохранением_перечня():
    s = site()
    data = integration.normalize({"revision": 0, "scenarios": [scenario(agreedIds=["station-a"])]}, integration.read(s))
    data["results"]["6.7"] = {"comment": "Запуск"}
    assert integration.confirmation_problem(s, "6.7", data)
    data["scenarios"][0]["connectedIds"] = ["station-a"]
    assert integration.confirmation_problem(s, "6.7", data) is None


def test_календарь_не_принимает_обратный_интервал():
    with pytest.raises(ValueError, match="раньше начала"):
        integration.normalize({"revision": 0, "dates": {"1": {"start": "2026-10-10", "end": "2026-10-01"}}}, integration.read(site()))


def test_проект_интеграции_не_получает_дату_ввода_локации():
    s = site("live")
    s.commissioned_on = None
    assert _pending_diff(s, {"stage": {"code": "int_live"}}) == []
    assert "integration_gate" in _context(s)
    assert s.commissioned_on is None and s.location_id is None


def test_подтверждение_сохраняет_автора_дату_и_предыдущий_результат(monkeypatch):
    from app.services import ezs_site_work
    events = AsyncMock()
    monkeypatch.setattr(ezs_site_work, "log_event", events)
    monkeypatch.setattr(integration, "validate_refs", AsyncMock())
    s = site()
    data = integration.read(s)
    data["partner"] = {"name": "Сеть партнёра", "purpose": "Показ на карте"}
    data["results"]["1.1"] = {"comment": "Согласовано на встрече"}
    s.workspace_data = {"integration": data, "other": {"kept": True}}
    user = SimpleNamespace(id=uuid.uuid4(), name="Ответственный", email="test@example.test")
    asyncio.run(integration.confirm(None, s, "1.1", 0, user))
    mark = s.gates["lead"]["1.1"]
    assert mark["by"] == str(user.id) and mark["by_name"] == "Ответственный" and mark["at"]
    assert mark["snapshot"] and mark["done"]
    asyncio.run(integration.save(None, s, {"revision": 1, "partner": {"name": "Сеть партнёра", "purpose": "Роуминг"}}, user))
    assert s.gates["lead"]["1.1"]["needs_confirmation"]
    assert s.workspace_data["other"]["kept"]
    assert events.await_count == 3
    assert events.call_args_list[0].kwargs["changes"][0]["new"]["result"]["comment"] == "Согласовано на встрече"


def test_чужая_станция_не_попадает_в_перечень():
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])))
    s = site()
    data = integration.normalize({"revision": 0, "scenarios": [scenario()]}, integration.read(s))
    with pytest.raises(ValueError, match="вне выбранной сети"):
        asyncio.run(integration.validate_refs(db, s, data))
    statement = db.execute.call_args.args[0]
    assert "company_id" in str(statement)


def test_каталог_использует_идентификаторы_объектов_а_не_внешние_коды():
    s = ServiceLocation(id="location-id", code="319", name="ЭЗС", extra_metadata={"federalSubject": "Регион"})
    m = MarketSite(id=uuid.uuid4(), name="Станция партнёра", kind="ezs")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [s])), SimpleNamespace(all=lambda: [(m, "Партнёр")])]))
    rows = asyncio.run(integration.station_catalog(db, uuid.uuid4()))
    assert rows[0]["id"] == "location-id" and rows[0]["code"] == "319"
    assert rows[1]["id"] == str(m.id) and rows[1]["network"] == "incoming"
