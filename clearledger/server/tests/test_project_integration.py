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
    assert integration.confirmation_problem(s, "6.7", data)  # нет версии перечня и даты подключения
    data["documents"] = [{"id": "list", "kind": "stations", "signedDocId": "f", "signingEvidence": "подписано"}]
    data["listVersions"] = [{"id": "v1", "scenarioId": "scenario-1", "version": 1, "stationIds": ["station-a"], "documentId": "list"}]
    assert integration.confirmation_problem(s, "6.7", data)
    data["scenarios"][0]["connectedMeta"] = {"station-a": {"at": "2026-10-04", "basis": "session", "ref": "S-1"}}
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
    data["lead"] = {"initiator": "partner"}
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


def test_реестр_и_отчёт_интеграций_считают_станции_и_внимание():
    a = site("negotiation")
    a.title, a.next_action_due = "Партнёр А", "2026-01-01"
    a.workspace_data = {"integration": {**integration.read(a), "partner": {"name": "А"},
        "scenarios": [scenario(agreedIds=["station-a"], connectedIds=["station-a"]),
                      scenario(id="s2", direction="incoming", format="roaming", selectedIds=["x"])]}}
    a.gates = {"lead": {"1.1": {"done": True, "needs_confirmation": True}}}
    b = site("live")
    b.title, b.owner_user_id = "Без сценария", None
    rows = [integration.portfolio_row(a, "Руководитель", today="2026-10-04"), integration.portfolio_row(b, None)]
    assert rows[0]["stations"] == {"selected": 3, "agreed": 1, "connected": 1, "pilot": 0}
    assert rows[0]["overdue"] and rows[0]["checklist"]["stale"] == 1
    assert rows[0]["stageLabel"] == "Переговоры"
    s = integration.summarize(rows)
    assert (s["total"], s["active"], s["live"]) == (2, 1, 1)
    assert s["stations"]["outgoing:information"]["connected"] == 1
    assert s["stations"]["incoming:roaming"]["selected"] == 1
    assert s["attention"]["stale"] == [rows[0]["id"]]
    assert s["attention"]["overdue"] == [rows[0]["id"]]
    assert s["attention"]["noOwner"] == []  # закрытый проект во внимание не попадает
    assert s["partners"][0]["partner"] == "А"


def _with(s, **patch):
    data = integration.read(s)
    data.update(patch)
    return data


def test_условия_по_сценариям_и_порядок_расчётов():
    s = site("negotiation")
    data = _with(s, scenarios=[scenario(format="roaming"), scenario(id="s2", direction="incoming", format="information")])
    data["results"]["2.2"] = data["results"]["6.2"] = {"comment": "ок"}
    assert integration.confirmation_problem(s, "2.2", data)
    data["scenarios"][0].update(payer="partner", model="commission", rate="7 %")
    data["scenarios"][1].update(payer="none")  # информационный обмен без денег — допустимо
    assert "периодичность" in integration.confirmation_problem(s, "2.2", data)
    data["settlement"] = {"period": "ежемесячно"}
    assert integration.confirmation_problem(s, "2.2", data) is None
    assert integration.confirmation_problem(s, "6.2", data)  # срок оплаты, документы, НДС
    data["settlement"].update(paymentTerm="10 рабочих дней", documents="отчёт агента, акт", vat="с НДС 20 %")
    assert integration.confirmation_problem(s, "6.2", data) is None


def test_согласование_комиссии_не_сбрасывается_отметкой_станций():
    s = site("negotiation")
    data = _with(s, scenarios=[scenario(payer="partner", model="commission", rate="7 %")])
    before = integration.snapshot(s, "2.2", data)
    data["scenarios"][0]["agreedIds"] = ["station-a"]
    assert integration.snapshot(s, "2.2", data) == before
    data["scenarios"][0]["rate"] = "8 %"
    assert integration.snapshot(s, "2.2", data) != before


def test_испытания_и_техническая_приёмка():
    s = site("construction")
    data = _with(s, work={"pilotOutcome": "принят"})
    data["results"]["5.10"] = {"comment": "ок"}
    data["results"]["5.11"] = {"comment": "ок"}
    assert "Сформируйте" in integration.confirmation_problem(s, "5.10", data)
    data["tests"] = [{"id": "t1", "title": "Старт и стоп", "required": True, "status": "failed", "comment": "не стартует"},
                     {"id": "t2", "title": "Отображение", "required": False, "status": "pending"}]
    assert "Старт и стоп" in integration.confirmation_problem(s, "5.10", data)
    data["tests"][0]["status"] = "passed"
    assert integration.confirmation_problem(s, "5.10", data) is None
    assert "подписанную" in integration.confirmation_problem(s, "5.11", data)  # нужен протокол испытаний
    data["documents"] = [{"id": "p", "kind": "test_protocol", "signedDocId": "f", "signingEvidence": "ИТ обеих сторон"}]
    assert integration.confirmation_problem(s, "5.11", data) is None
    data["results"]["5.11"] = {"comment": "", "notApplicable": True}
    assert integration.confirmation_problem(s, "5.11", data)  # приёмку нельзя объявить неприменимой


@pytest.mark.parametrize("ours,partner,state", [
    ({"sessions": 10, "kwh": 100, "amount": 1500}, {"sessions": 10, "kwh": 100.05, "amount": 1500.5}, "match"),
    ({"sessions": 10, "kwh": 100, "amount": 1500}, {"sessions": 9, "kwh": 100, "amount": 1500}, "diff"),
    ({"sessions": 10, "kwh": 100, "amount": 1500}, {"sessions": 10, "kwh": 100, "amount": 1502}, "diff"),
])
def test_расхождение_сверки(ours, partner, state):
    assert integration.recon_state({"ours": ours, "partner": partner}) == state


def test_сверки_пилота_и_месяца():
    s = site("construction")
    data = _with(s)
    data["results"]["5.13"] = {"comment": "ок"}
    data["results"]["6.14"] = {"comment": "ок"}
    diff = {"id": "r1", "kind": "pilot", "period": "пилот", "ours": {"sessions": 5, "kwh": 50, "amount": 700},
            "partner": {"sessions": 4, "kwh": 40, "amount": 560}}
    data["reconciliations"] = [diff]
    assert integration.confirmation_problem(s, "5.13", data)
    diff.update(resolution="одна сессия у партнёра не дошла, доначислено", docId="act")
    assert integration.confirmation_problem(s, "5.13", data) is None
    month = {"id": "r2", "kind": "monthly", "period": "2026-11", "ours": {"sessions": 5, "kwh": 50, "amount": 700},
             "partner": {"sessions": 5, "kwh": 50, "amount": 700}}
    data["reconciliations"].append(month)
    assert integration.confirmation_problem(s, "6.14", data)  # без подписанного акта
    month["docId"] = "act2"
    assert integration.confirmation_problem(s, "6.14", data) is None


def test_версия_перечня_снимок_и_неизменность():
    s = site("commissioning")
    old = integration.normalize({"revision": 0, "scenarios": [scenario(agreedIds=["station-a"])],
                                 "documents": [{"id": "list", "kind": "stations"}]}, integration.read(s))
    data = integration.normalize({"revision": 0, "listVersions": [{"scenarioId": "scenario-1", "documentId": "list"}]}, old)
    v = data["listVersions"][0]
    assert (v["version"], v["stationIds"]) == (1, ["station-a"])
    v.pop("new")
    with pytest.raises(ValueError):  # удалить зафиксированную версию нельзя
        integration.normalize({"revision": 0, "listVersions": []}, data)
    data["scenarios"][0]["agreedIds"] = ["station-a", "station-b"]
    ok, problem = integration.versions_state(data)
    assert not ok and "изменён после версии 1" in problem
    again = integration.normalize({"revision": 0, "listVersions": [v, {"scenarioId": "scenario-1", "documentId": "list"}]}, data)
    assert [x["version"] for x in again["listVersions"]] == [1, 2]
    assert again["listVersions"][0]["stationIds"] == ["station-a"]  # первая версия не переписана


def test_автор_испытания_не_переписывается_чужим_сохранением():
    s = site("construction")
    old = integration.read(s)
    old["tests"] = [{"id": "t1", "scenarioId": "", "title": "Старт", "required": True, "status": "passed",
                     "sessionRef": "S-1", "comment": "", "docId": "", "by": "u1", "byName": "Иванов", "at": "2026-10-01"}]
    data = integration.normalize({"revision": 0, "tests": [dict(old["tests"][0]), {"title": "Стоп", "required": True}]}, old)
    integration.stamp(old, data, SimpleNamespace(id="u2", name="Петров"))
    assert data["tests"][0]["byName"] == "Иванов" and data["tests"][1]["byName"] == "Петров"


def test_сроки_держит_пункт_2_8_а_не_бренд():
    s = site("negotiation")
    data = _with(s)
    data["results"]["2.6"] = {"comment": "ок"}
    data["results"]["2.8"] = {"comment": "ок"}
    assert integration.confirmation_problem(s, "2.6", data) is None
    # с 06.10.2026 сетки дат нет: 2.8 подтверждается результатом
    assert integration.confirmation_problem(s, "2.8", data) is None

def test_правило_сессий_партнёра_держит_5_12():
    s = site("construction")
    data = _with(s)
    data["results"]["5.12"] = {"comment": "проверено на тестовой сессии"}
    assert integration.confirmation_problem(s, "5.12", data)
    data["settlement"] = {"matchKind": "account", "matchValues": "5;\n 17, 5"}
    assert integration.match_values(data["settlement"]) == ["17", "5"]
    assert integration.confirmation_problem(s, "5.12", data) is None
    with pytest.raises(ValueError):
        integration.normalize({"revision": 0, "settlement": {"matchKind": "телефон"}}, integration.read(s))


def test_период_сверки_датами():
    s = site("construction")
    row = {"kind": "monthly", "period": "ноябрь", "from": "2026-11-01", "to": "2026-11-30"}
    data = integration.normalize({"revision": 0, "reconciliations": [row]}, integration.read(s))
    assert (data["reconciliations"][0]["from"], data["reconciliations"][0]["to"]) == ("2026-11-01", "2026-11-30")
    with pytest.raises(ValueError):
        integration.normalize({"revision": 0, "reconciliations": [{**row, "from": "2026-12-01"}]}, integration.read(s))




def test_заявка_предполагаемый_договор_и_технический_куратор():
    """Заявка: 1.3 — вид договора и кто кому платит, 1.4.1 — тех. куратор; значения проверяются."""
    s = site()
    data = integration.read(s)
    assert integration.requirement_problem(s, "1.3", data) == "Укажите вид предполагаемого договора и кто кому платит"
    assert integration.requirement_problem(s, "1.4.1", data) == "Назначьте технического куратора интеграции"
    curator = str(uuid.uuid4())
    data = integration.normalize({"revision": 0, "lead": {"initiator": "us", "contractKind": "roaming", "payer": "partner",
                                                          "coverage": "Приморье, ~40 ЭЗС", "curatorUserId": curator.upper()}}, data)
    assert data["lead"]["curatorUserId"] == curator
    assert integration.requirement_problem(s, "1.3", data) is None and integration.requirement_problem(s, "1.4.1", data) is None
    assert integration.section_for("1.3") == integration.section_for("1.4.1") == "lead"
    for bad in ({"contractKind": "лизинг"}, {"initiator": "кто-то"}, {"payer": "все"}):
        try:
            integration.normalize({"revision": 0, "lead": bad}, integration.read(s))
            raise AssertionError(bad)
        except ValueError:
            pass


def test_подтверждение_данными_и_неприменимость_только_необязательных():
    """Пункт с выполненным требованием к данным подтверждается без комментария; «не применимо» —
    только у необязательного. Состав DATA_RULE_KEYS совпадает с пунктами, у которых есть правило."""
    from app.services.ezs_checklist_integration import TASKS
    s = site()
    empty = integration.read(s)
    with_rule = {t["key"] for t in TASKS if integration.requirement_problem(s, t["key"], empty)}
    # 5.12: правило есть, но нужен и результат — номер тестовой сессии
    assert with_rule - {"5.12"} <= integration.DATA_RULE_KEYS
    s.owner_user_id = uuid.uuid4()
    data = integration.read(s)
    assert integration.confirmation_problem(s, "1.4", data) is None            # руководитель есть — без комментария
    assert integration.confirmation_problem(s, "3.3", data) == "Запишите результат проверки, выберите документ или свяжите поручение"
    data["results"]["1.4"] = {"notApplicable": True, "comment": "не нужно"}
    assert "снимите обязательность" in integration.confirmation_problem(s, "1.4", data)
    data["results"]["3.3"] = {"notApplicable": True, "comment": "доработок нет"}
    assert integration.confirmation_problem(s, "3.3", data) is None


def test_подтверждение_пункта_не_сбивают_соседние_поля_раздела():
    """06.10.2026: назначение куратора (1.4.1) снимало подтверждение договора (1.3),
    выбор станций (1.6) — направления (1.2)."""
    s = SimpleNamespace(owner_user_id=None, workspace_data={})
    data = integration.normalize({"revision": 0, "lead": {"contractKind": "roaming", "payer": "partner"},
                        "scenarios": [{"id": "a", "direction": "outgoing", "format": "roaming", "selectedIds": []}]}, integration.read(s))
    s13, s12 = integration.snapshot(s, "1.3", data), integration.snapshot(s, "1.2", data)
    data["lead"]["curatorUserId"] = "u1"
    data["scenarios"][0]["selectedIds"] = ["st1"]
    assert integration.snapshot(s, "1.3", data) == s13 and integration.snapshot(s, "1.2", data) == s12
    data["lead"]["payer"] = "us"
    assert integration.snapshot(s, "1.3", data) != s13
    # подтверждение, снятое до перехода на v2, по чужим полям не устаревает
    assert integration.same_snapshot(s, "1.3", "старый-отпечаток", data)
    assert not integration.same_snapshot(s, "1.3", s13, data)


def test_цена_для_чужого_клиента_не_снимает_согласование_комиссии():
    """06.10.2026: цена в 2.3 снимала подтверждение 2.2."""
    s = SimpleNamespace(owner_user_id=None, workspace_data={})
    data = integration.normalize({"revision": 0, "scenarios": [{"id": "a", "direction": "outgoing", "format": "roaming", "payer": "partner", "model": "commission", "rate": "7 %"}]}, integration.read(s))
    s22, s23 = integration.snapshot(s, "2.2", data), integration.snapshot(s, "2.3", data)
    data["scenarios"][0]["clientPrice"] = "розничный тариф"
    assert integration.snapshot(s, "2.2", data) == s22 and integration.snapshot(s, "2.3", data) != s23
    data["scenarios"][0]["rate"] = "8 %"
    assert integration.snapshot(s, "2.2", data) != s22


def test_пустая_сверка_не_закрывает_пункт():
    """06.10.2026: нули у обеих сторон считались «сходится» и закрывали 5.13."""
    empty = {"kind": "pilot", "ours": {"sessions": 0, "kwh": 0, "amount": 0}, "partner": {"sessions": 0, "kwh": 0, "amount": 0}}
    assert integration.recon_state(empty) == "empty"
    full = {**empty, "ours": {"sessions": 5, "kwh": 100, "amount": 1500}, "partner": {"sessions": 5, "kwh": 100, "amount": 1500}}
    assert integration.recon_state(full) == "match"


def test_правки_других_пунктов_не_снимают_подтверждения():
    """06.10.2026, проход на боевом: 6.2/6.3 снимали 5.12, месячная сверка — пробную,
    технические параметры — пункты без своих данных."""
    s = SimpleNamespace(owner_user_id=None, workspace_data={})
    data = integration.normalize({"revision": 0, "settlement": {"matchKind": "account", "matchValues": "A1"},
                                  "reconciliations": [{"kind": "pilot", "period": "пилот", "ours": {"sessions": 5}, "partner": {"sessions": 5}}]},
                                 integration.read(s))
    before = {k: integration.snapshot(s, k, data) for k in ("5.12", "5.13", "5.2", "5.10")}
    data["settlement"]["paymentTerm"] = "10 дней"
    data["reconciliations"].append({"kind": "monthly", "period": "ноябрь", "ours": {"sessions": 9}, "partner": {"sessions": 9}})
    data["technical"]["protocol"] = "OCPI"
    data["work"]["launchDate"] = "2026-11-01"
    assert {k: integration.snapshot(s, k, data) for k in before} == before


def test_внешние_участники_с_ролью_без_дублей():
    cp = "11111111-2222-3333-4444-555555555555"
    data = integration.normalize({"revision": 0, "parties": [
        {"counterpartyId": cp, "side": "vendor", "note": "техническая интеграция"},
        {"counterpartyId": cp, "side": "other"}]}, integration.read(site()))
    assert data["parties"] == [{"counterpartyId": cp, "side": "vendor", "note": "техническая интеграция"}]
    with pytest.raises(ValueError):
        integration.normalize({"revision": 0, "parties": [{"counterpartyId": cp, "side": "boss"}]}, integration.read(site()))


def test_21_закрывается_данными_сценария():
    s = site()
    data = integration.normalize({"revision": 0, "scenarios": [scenario()]}, integration.read(s))
    assert integration.confirmation_problem(s, "2.1", data)
    data["scenarios"][0]["restrictions"] = "только корпоративные клиенты"
    assert integration.confirmation_problem(s, "2.1", data) is None
