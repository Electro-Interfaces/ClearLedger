"""Без БД: предметные ключи, UUID и отказ при неоднозначности кандидатов."""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace as Row

import pytest

from app.services.reference_identity import (
    ContractIndex, CounterpartyIndex, IdentityConflict, contract_identity,
    counterparty_identity, id_key, json_ids, organization_for_import,
    require_organization,
)


def cp(name='ООО «Тест»', inn="7700000000", kpp="770001001", **kw):
    return Row(id=uuid.uuid4(), name=name, inn=inn, kpp=kpp, raw=None,
               external_ref=None, **kw)


def contract(party, number="74", cdate="2026-01-01", **kw):
    return Row(id=uuid.uuid4(), counterparty_id=party, number=number,
               date=cdate, type="Аренда", **kw)


def test_uuid_and_string_find_same_contract_including_external_ref():
    party = cp()
    existing = contract(party.id)
    index = ContractIndex([existing])
    assert index.resolve(party, "Аренда", "74") is existing
    party.id = str(party.id).upper()
    assert index.resolve(party, "Аренда", "74") is existing
    party.external_ref = party.id
    assert index.resolve(party, "Аренда") is existing  # Один ID не считается дважды.
    party.external_ref, party.id = party.id, uuid.uuid4()
    assert index.resolve(party, "Аренда", "74") is existing


def test_contract_same_run_index_and_dates():
    party = cp()
    index = ContractIndex()
    assert index.resolve(party, "Аренда", "74") is None
    first = contract(party.id)
    index.add(first)
    assert index.resolve(party, "Аренда", "74", "2026-01-01") is first
    second = contract(str(party.id), cdate="2026-02-01")
    index.add(second)
    assert index.resolve(party, "Аренда", "74", "2026-02-01") is second
    assert index.resolve(party, "Аренда", "75") is None
    with pytest.raises(IdentityConflict, match="Неоднозначное"):
        index.resolve(party, "Аренда", "74")
    with pytest.raises(IdentityConflict):
        index.resolve(party, "Аренда")


def test_duplicate_contract_same_number_and_date_is_not_first():
    party = cp()
    index = ContractIndex([contract(party.id), contract(party.id)])
    with pytest.raises(IdentityConflict):
        index.resolve(party, "Аренда", "74", "2026-01-01")


def test_inn_overrides_name_but_does_not_overwrite_another_legal_entity():
    a, b = cp(), cp(inn="7800000000")
    index = CounterpartyIndex([a, b])
    assert index.resolve('ООО "Тест"', "7800000000") is b
    assert index.resolve("Новое написание", "7700000000") is a
    assert index.resolve(a.name, "9900000000") is None
    with pytest.raises(IdentityConflict):
        index.resolve(a.name)
    assert a.inn == "7700000000"


def test_legal_form_preserved_and_branches_require_kpp():
    a, b = cp(), cp(name='АО «Тест»', inn="7800000000")
    index = CounterpartyIndex([a, b])
    assert index.resolve('АО "Тест"') is b
    assert index.resolve('ООО "Тест"') is a
    assert index.resolve("Тест") is None
    branch = cp(name="Филиал", kpp="770002002")
    index.add(branch)
    with pytest.raises(IdentityConflict):
        index.resolve("Новое имя", "7700000000")
    assert index.resolve("Новое имя", "7700000000", "770002002") is branch


def test_supplied_inn_does_not_claim_unknown_name_only_card():
    unknown = cp(inn="")
    with pytest.raises(IdentityConflict, match="сверить ИНН"):
        CounterpartyIndex([unknown]).resolve(unknown.name, "7700000000")
    assert unknown.inn == ""


def test_pinned_fields_can_be_resolved_by_original_source_snapshot():
    party = cp()
    party.raw = {"referenceIdentity": {"name": "Прежнее имя", "inn": "7800000000"}}
    party.manual_overrides = ["name", "inn"]
    index = CounterpartyIndex([party])
    assert index.resolve("Прежнее имя") is party
    assert index.resolve("Другое написание источника", "7800000000") is party
    doc = contract(party.id, number="Исправленный номер")
    doc.raw = {"referenceIdentity": {"number": "74", "date": "2025-01-01", "type": "Прежний вид"}}
    doc.manual_overrides = ["number", "date", "type"]
    contracts = ContractIndex([doc])
    assert contracts.resolve(party, "Прежний вид", "74", "2025-01-01") is doc
    assert contracts.resolve(party, "Аренда", "Исправленный номер", "2026-01-01") is doc
    assert contracts.resolve(party, "Аренда", "74", "2025-01-01") is None


def test_manual_identity_requires_complete_requisites():
    assert counterparty_identity(" 7700000000 ", "770001001") == ("7700000000", "770001001")
    assert counterparty_identity("7700000000", "") == ("7700000000", "")
    assert counterparty_identity("770000000001", None) == ("770000000001", "")
    assert counterparty_identity("", "") is None
    assert contract_identity(" 74 ", "2026-01-01", " Аренда ") == ("74", "2026-01-01", "Аренда")
    assert contract_identity("74", "", "Аренда") is None
    assert contract_identity("74", "не дата", "Аренда") is None


def test_organization_is_from_company_set_and_never_counterparty():
    a, b = Row(id=uuid.uuid4()), Row(id=uuid.uuid4())
    assert organization_for_import([a]) == str(a.id)
    assert organization_for_import([], [Row(organization_id=a.id)]) is None
    assert organization_for_import([a, b]) is None
    assert organization_for_import([a, b], [Row(organization_id=b.id)]) == str(b.id)
    with pytest.raises(IdentityConflict, match="Organization"):
        require_organization(None)


def test_nested_uuid_serialization():
    uid = uuid.uuid4()
    value = json_ids({"_match": {"locationId": uid}, "roles": [uid], "when": datetime(2026, 1, 1)})
    assert json.loads(json.dumps(value))["_match"]["locationId"] == str(uid)
    assert id_key(uid) == id_key(str(uid).upper())
