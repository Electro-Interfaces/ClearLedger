from app.models import Contract, Counterparty
from app.services.reference_overrides import (
    apply_import_values, mark_reference_changes, snapshot_reference_fields,
)


def test_changed_contract_fields_survive_import_and_unedited_fields_refresh():
    contract = Contract(number="ONE", valid_until="2026-12-31", amount_limit=100,
                        manual_overrides=[])
    before = snapshot_reference_fields(contract)
    contract.valid_until = "2027-12-31"
    contract.amount_limit = None  # Явная ручная очистка также имеет приоритет.
    mark_reference_changes(contract, before)
    apply_import_values(contract, {"number": "TWO", "valid_until": "2026-12-31",
                                   "amount_limit": 200})
    assert contract.valid_until == "2027-12-31"
    assert contract.amount_limit is None
    assert contract.number == "TWO"
    assert contract.manual_overrides == ["amount_limit", "valid_until"]


def test_unchanged_form_does_not_pin_imported_fields():
    party = Counterparty(name="Test", inn="1234567890", manual_overrides=[])
    before = snapshot_reference_fields(party)
    party.name = "Test"
    mark_reference_changes(party, before)
    apply_import_values(party, {"name": "Updated by source"})
    assert not party.manual_overrides
    assert party.name == "Updated by source"


def test_manual_markers_do_not_pollute_or_freeze_raw_snapshot():
    party = Counterparty(name="Test", raw={"Description": "Old"}, manual_overrides=None)
    before = snapshot_reference_fields(party)
    party.name = "Manual"
    mark_reference_changes(party, before)
    apply_import_values(party, {"name": "Imported"})
    party.raw = {"Description": "New"}
    assert party.name == "Manual"
    assert party.raw == {"Description": "New"}
    assert party.manual_overrides == ["name"]
