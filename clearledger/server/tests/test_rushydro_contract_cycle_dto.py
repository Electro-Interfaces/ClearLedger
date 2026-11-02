"""Exactly 50 finite native scenarios, authored SOURCE_ONLY / NOTRUN.

Standalone loading avoids product_api/__init__.py (which imports the app).
Root must execute this source only inside its separate offline audit guard;
ordinary server pytest still has database-owning conftest, so is not authorized.
"""
from datetime import date, datetime
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError


_SOURCE = Path(__file__).resolve().parents[1] / "app/product_api/contract_cycle_dto.py"
_SPEC = importlib.util.spec_from_file_location("rushydro_contract_cycle_dto_isolated", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
dto = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = dto
_SPEC.loader.exec_module(dto)

TODAY = date(2026, 11, 1)
ORG = "00000003-0000-4000-8000-000000000003"
PARTY = "00000005-0000-4000-8000-000000000005"
SITE = "00000007-0000-4000-8000-000000000007"
OTHER_SITE = "00000008-0000-4000-8000-000000000008"
KEY = "10000000-0000-4000-8000-000000000001"
VERSION = "v1:" + "a" * 64
LOCATION = " Учебная точка А "


def card(**changes):
    result = {
        "profile": "Lease", "number": "SYN-LEASE-001", "date": "2026-11-01",
        "organizationId": ORG, "counterpartyId": PARTY, "basis": "servitude",
        "kind": "supplier", "currency": "RUB", "paymentTermDays": 10,
        "vatPct": None, "amountInclVat": None, "signed": False,
        "signedAt": None, "comment": None, "validity": {"kind": "unknown"},
    }
    result.update(changes)
    return result


def term(**changes):
    result = {
        "costItem": "rent", "context": {"kind": "site", "siteId": SITE},
        "validFrom": "2026-11-01", "validTo": None, "periodicity": "monthly",
        "condition": {"kind": "fixed", "amountGross": "1200.00", "vatPct": None},
        "docDueDay": None, "payDueDay": None, "expectedDocs": [], "note": None,
    }
    result.update(changes)
    return result


def accept(schema, value, *, wire=False, clock=True):
    adapter = TypeAdapter(schema)
    context = {"todayMSK": TODAY} if clock else None
    if wire:
        return adapter.validate_json(json.dumps(value, ensure_ascii=False), context=context)
    return adapter.validate_python(value, context=context)


def reject(schema, values, *, clock=True):
    """One finite array validation; every literal vector must have its own error."""
    with pytest.raises(ValidationError) as caught:
        accept(list[schema], values, clock=clock)
    failing = {error["loc"][0] for error in caught.value.errors()}
    assert failing == set(range(len(values)))


def test_01_real_calendar_endpoints_and_leap():
    result = accept(list[dto.DateV2], ["0001-01-01", "9999-12-31", "2024-02-29", date(2026, 11, 1)])
    assert result == [date(1, 1, 1), date(9999, 12, 31), date(2024, 2, 29), TODAY]
    for mode in ("validation", "serialization"):
        assert TypeAdapter(dto.DateV2).json_schema(mode=mode) == {"type": "string", "format": "date", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "minLength": 10, "maxLength": 10}


def test_02_invalid_calendar_and_python_datetime():
    reject(dto.DateV2, ["2026-02-29", "2026-1-01", "0000-01-01", "2026-11-01T00:00:00", datetime(2026, 11, 1)])


def test_03_uuid_python_and_json_canonical_serialization():
    result = accept(list[dto.UUIDV2], [UUID(SITE), "ABCDEF07-0000-4000-8000-000000000007"])
    assert TypeAdapter(list[dto.UUIDV2]).dump_json(result) == b'["00000007-0000-4000-8000-000000000007","abcdef07-0000-4000-8000-000000000007"]'
    assert accept(dto.UUIDV2, SITE, wire=True) == UUID(SITE)
    for mode in ("validation", "serialization"):
        schema = TypeAdapter(dto.UUIDV2).json_schema(mode=mode)
        assert schema["type"] == "string" and schema["format"] == "uuid"
        assert schema["minLength"] == schema["maxLength"] == 36 and "anyOf" not in schema


def test_04_uuid_rejects_noncanonical_inputs():
    reject(dto.UUIDV2, [SITE.replace("-", ""), "{" + SITE + "}", "urn:uuid:" + SITE, SITE.encode(), 7])


def test_05_money_zero_max_and_exact_serialization():
    result = accept(list[dto.MoneyV2], ["0.00", "99999999999999.99", "1200.00"], wire=True)
    assert result == [Decimal("0.00"), Decimal("99999999999999.99"), Decimal("1200.00")]
    assert all(type(item) is Decimal and item.as_tuple().exponent == -2 for item in result)
    assert all(type(item) is Decimal for item in TypeAdapter(list[dto.MoneyV2]).dump_python(result))
    assert TypeAdapter(list[dto.MoneyV2]).dump_json(result) == b'["0.00","99999999999999.99","1200.00"]'
    for mode in ("validation", "serialization"):
        assert TypeAdapter(dto.MoneyV2).json_schema(mode=mode) == {"type": "string", "pattern": r"^(?:0|[1-9][0-9]{0,13})\.[0-9]{2}$", "minLength": 4, "maxLength": 17}


def test_06_money_rejects_lexical_and_type_loss():
    reject(dto.MoneyV2, ["100000000000000.00", "1.0", "1.000", 1.25, 1, True, Decimal("1.00"), "1e2", "NaN", "Infinity", "+1.00", "-0.00", "01.00"])


def test_07_tariff_zero_max_and_six_places():
    result = accept(list[dto.TariffV2], ["0.000000", "99999999.999999", "6.250000"], wire=True)
    assert all(type(item) is Decimal and item.as_tuple().exponent == -6 for item in result)
    assert TypeAdapter(list[dto.TariffV2]).dump_json(result) == b'["0.000000","99999999.999999","6.250000"]'
    for mode in ("validation", "serialization"):
        assert TypeAdapter(dto.TariffV2).json_schema(mode=mode) == {"type": "string", "pattern": r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{6}$", "minLength": 8, "maxLength": 15}


def test_08_tariff_rejects_overflow_scale_numeric_and_sign():
    reject(dto.TariffV2, ["100000000.000000", "6.25000", 6.25, "-1.000000"])


def test_09_rate_zero_and_hundred():
    result = accept(list[dto.RateV2], ["0.00", "100.00"], wire=True)
    assert result == [Decimal("0.00"), Decimal("100.00")]
    assert TypeAdapter(list[dto.RateV2]).dump_json(result) == b'["0.00","100.00"]'
    for mode in ("validation", "serialization"):
        assert TypeAdapter(dto.RateV2).json_schema(mode=mode) == {"type": "string", "pattern": r"^(?:(?:0|[1-9][0-9]?)\.[0-9]{2}|100\.00)$", "minLength": 4, "maxLength": 6}


def test_10_rate_rejects_overflow_scale_and_numeric():
    reject(dto.RateV2, ["100.01", "999.99", "20.0", 20.0])


def test_11_object_id_preserves_unicode_whitespace_case():
    values = [LOCATION, "Я" * 40, "a", "A", SITE]
    assert accept(list[dto.ObjectIdV2], values, wire=True) == values
    for mode in ("validation", "serialization"):
        assert TypeAdapter(dto.ObjectIdV2).json_schema(mode=mode) == {"type": "string", "minLength": 1, "maxLength": 40, "pattern": r"^[^\u0000]+$"}


def test_12_object_id_rejects_empty_long_nul_and_nonstr():
    reject(dto.ObjectIdV2, ["", "Я" * 41, "точка\x00", UUID(SITE)])


def test_13_opaque_lowercase_version_preserved():
    assert accept(dto.VersionV2, VERSION, wire=True) == VERSION


def test_14_version_rejects_malformed_tokens():
    reject(dto.VersionV2, ["v2:" + "a" * 64, "v1:" + "g" * 64, "v1:" + "a" * 63, '"' + VERSION + '"', "v1:" + "A" * 64])


def test_15_card_boolean_and_integer_coercions_rejected():
    reject(dto.CardV2, [card(signed=1), card(amountInclVat="false"), card(paymentTermDays=True), card(paymentTermDays=10.0), card(paymentTermDays="10")])


def test_16_site_context_python_and_json():
    result = accept(dto.ContextV2, {"kind": "site", "siteId": UUID(SITE)})
    assert result.model_dump(mode="json") == {"kind": "site", "siteId": SITE}
    assert accept(dto.ContextV2, {"kind": "site", "siteId": SITE}, wire=True).siteId == UUID(SITE)


def test_17_location_context_keeps_object_id():
    result = accept(dto.ContextV2, {"kind": "location", "locationId": LOCATION}, wire=True)
    assert result.locationId == LOCATION


def test_18_context_rejects_unknown_mixed_extra_and_null():
    reject(dto.ContextV2, [{"kind": "company"}, {"kind": "site", "siteId": SITE, "locationId": LOCATION}, {"kind": "site", "siteId": None}, {"kind": "location", "locationId": LOCATION, "equipmentId": SITE}])


def test_19_site_coverage_has_distinct_uuid_field():
    result = accept(dto.CoverageV2, {"kind": "site", "siteId": SITE}, wire=True)
    assert result.siteId == UUID(SITE)


def test_20_locations_coverage_one_and_hundred():
    # Literal finite domain of 100 different ObjectIds; no fuzzing.
    ids = [str(number) for number in range(100)]
    result = accept(list[dto.CoverageV2], [{"kind": "locations", "locationIds": [LOCATION]}, {"kind": "locations", "locationIds": ids}])
    assert result[0].locationIds == [LOCATION] and len(result[1].locationIds) == 100


def test_21_locations_coverage_rejects_duplicate_empty_101_and_tuple():
    reject(dto.CoverageV2, [{"kind": "locations", "locationIds": [LOCATION, LOCATION]}, {"kind": "locations", "locationIds": []}, {"kind": "locations", "locationIds": [str(number) for number in range(101)]}, {"kind": "locations", "locationIds": (LOCATION,)}])


def test_22_recursive_extras_and_snake_case_rejected():
    reject(dto.ContractCreateCommandV2, [
        {"commandKey": KEY, "card": card(validity={"kind": "unknown", "date": "2027-01-01"}), "coverage": {"kind": "site", "siteId": SITE}},
        {"commandKey": KEY, "card": card(organization_id=ORG), "coverage": {"kind": "site", "siteId": SITE}},
    ])


def test_23_explicit_lease_card():
    result = accept(dto.CardV2, card(), wire=True)
    assert result.profile == "Lease" and result.basis == "servitude"
    assert result.number == "SYN-LEASE-001" and result.date == TODAY


def test_24_explicit_power_supply_card():
    result = accept(dto.CardV2, card(profile="PowerSupply", basis="contract", vatPct="20.00", amountInclVat=True), wire=True)
    assert result.profile == "PowerSupply" and result.vatPct == Decimal("20.00")
    assert result.model_dump(mode="json")["vatPct"] == "20.00"


def test_25_power_supply_rejects_noncontract_basis():
    reject(dto.CardV2, [card(profile="PowerSupply", basis="permission")])


def test_26_card_required_and_bounded_text():
    absent = card()
    del absent["validity"]
    reject(dto.CardV2, [card(number=" \t"), card(number="n" * 101), card(number=None), card(comment="я" * 2001), absent])


def test_27_payment_boundaries_nullable_fields_and_text_boundaries():
    result = accept(list[dto.CardV2], [card(paymentTermDays=0, number="n" * 100, comment="я" * 2000), card(paymentTermDays=366, comment="")])
    assert [item.paymentTermDays for item in result] == [0, 366]
    assert result[1].vatPct is None and result[1].amountInclVat is None


def test_28_payment_outside_bounds_and_strict_integer():
    reject(dto.CardV2, [card(paymentTermDays=-1), card(paymentTermDays=367), card(paymentTermDays=False)])


def test_29_unknown_and_openended_are_explicitly_distinct():
    result = accept(list[dto.CardV2], [card(), card(validity={"kind": "openEnded"})])
    assert [item.validity.kind for item in result] == ["unknown", "openEnded"]


def test_30_until_equal_or_after_card_date():
    result = accept(list[dto.CardV2], [card(validity={"kind": "until", "date": "2026-11-01"}), card(validity={"kind": "until", "date": "2027-01-01"})])
    assert result[0].validity.date == TODAY and result[1].validity.date == date(2027, 1, 1)


def test_31_until_before_card_date_rejected():
    reject(dto.CardV2, [card(validity={"kind": "until", "date": "2026-10-31"})])


def test_32_signed_at_explicit_today():
    result = dto.validate_contract_card(card(signed=True, signedAt="2026-11-01"), todayMSK=TODAY)
    assert result.signed is True and result.signedAt == TODAY


def test_33_signed_requires_nonfuture_date():
    reject(dto.CardV2, [card(signed=True, signedAt="2026-11-02"), card(signed=True)])


def test_34_unsigned_requires_null_signed_at():
    reject(dto.CardV2, [card(signedAt="2026-11-01")])


def test_35_explicit_business_date_required():
    reject(dto.CardV2, [card(), card(signed=True, signedAt="2026-11-01")], clock=False)
    with pytest.raises(ValidationError):
        dto.validate_contract_card(card(), todayMSK=datetime(2026, 11, 1))
    current = dto.validate_contract_card(card(), todayMSK=TODAY)
    with pytest.raises(ValidationError):
        accept(dto.ContractCreateCommandV2, {"commandKey": KEY, "card": current, "coverage": {"kind": "site", "siteId": SITE}}, clock=False)


def test_36_lease_fixed_site_term_pure_compatibility():
    result = dto.validate_contract_term(term(), finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    assert result.condition.amountGross == Decimal("1200.00")


def test_37_power_metered_location_monthly():
    result = dto.validate_contract_term(
        term(costItem="energy", context={"kind": "location", "locationId": LOCATION}, condition={"kind": "metered_kwh", "tariffRub": "6.250000", "vatPct": "20.00"}),
        finalCard=card(profile="PowerSupply", basis="contract"), coverage={"kind": "locations", "locationIds": [LOCATION]}, todayMSK=TODAY,
    )
    assert result.condition.tariffRub == Decimal("6.250000")
    assert result.model_dump(mode="json")["condition"]["tariffRub"] == "6.250000"


def test_38_zero_negative_and_mixed_conditions_rejected():
    reject(dto.TermV2, [
        term(condition={"kind": "fixed", "amountGross": "0.00", "vatPct": None}),
        term(condition={"kind": "fixed", "amountGross": "-1.00", "vatPct": None}),
        term(costItem="energy", condition={"kind": "metered_kwh", "tariffRub": "0.000000", "vatPct": None}),
        term(condition={"kind": "fixed", "amountGross": "1.00", "vatPct": None, "tariffRub": "1.000000"}),
    ])


def test_39_term_end_before_start_rejected():
    reject(dto.TermV2, [term(validTo="2026-10-31")])


def test_40_due_days_document_sets_and_lease_periodicities():
    result = accept(list[dto.TermV2], [
        term(docDueDay=1, payDueDay=31, validTo="2026-11-01", expectedDocs=["act", "upd", "invoice", "sf", "report"]),
        term(periodicity="quarterly"), term(periodicity="annual"), term(periodicity="one_time"),
    ])
    assert result[0].docDueDay == 1 and result[0].payDueDay == 31
    assert result[1].expectedDocs == []


def test_41_invalid_document_sets_and_due_days():
    reject(dto.TermV2, [term(expectedDocs=["act", "act"]), term(expectedDocs=None), term(expectedDocs=["receipt"]), term(docDueDay=0), term(payDueDay=32), term(docDueDay=True)])


def test_42_profile_condition_costitem_and_power_periodicity():
    with pytest.raises(ValueError, match="profile"):
        dto.validate_contract_term(term(), finalCard=card(profile="PowerSupply", basis="contract"), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    reject(dto.TermV2, [
        term(costItem="energy"),
        term(costItem="energy", periodicity="annual", condition={"kind": "metered_kwh", "tariffRub": "6.250000", "vatPct": None}),
    ])


def test_43_context_outside_supplied_coverage_rejected():
    with pytest.raises(ValueError, match="coverage"):
        dto.validate_contract_term(term(), finalCard=card(), coverage={"kind": "site", "siteId": OTHER_SITE}, todayMSK=TODAY)
    with pytest.raises(ValueError, match="coverage"):
        dto.validate_contract_term(term(context={"kind": "location", "locationId": LOCATION}), finalCard=card(), coverage={"kind": "locations", "locationIds": [LOCATION.strip()]}, todayMSK=TODAY)


def test_44_create_and_mutation_envelopes():
    created = accept(dto.ContractCreateCommandV2, {"commandKey": KEY, "card": card(), "coverage": {"kind": "site", "siteId": SITE}}, wire=True)
    assert created.commandKey == UUID(KEY)
    result = accept(dto.MutationResultV2, {"resourceId": KEY, "editVersion": VERSION, "replayed": False}, wire=True)
    assert result.model_dump(mode="json") == {"resourceId": KEY, "editVersion": VERSION, "replayed": False}
    reject(dto.MutationResultV2, [{"resourceId": KEY, "editVersion": VERSION, "replayed": 0}])


def test_45_patch_presence_omitted_null_and_value():
    patch = accept(dto.ContractPatchCommandV2, {"commandKey": KEY, "expectedVersion": VERSION, "changes": {"comment": None, "number": "NEW"}}, wire=True)
    assert patch.changes.model_fields_set == {"comment", "number"}
    assert patch.changes.model_dump(mode="json", exclude_unset=True) == {"number": "NEW", "comment": None}
    merged = dto.merge_contract_card(card(comment="old", vatPct="20.00"), patch.changes, todayMSK=TODAY)
    assert merged.comment is None and merged.number == "NEW" and merged.vatPct == Decimal("20.00")
    for mode in ("validation", "serialization"):
        schema = dto.CardChangesV2.model_json_schema(mode=mode)
        assert schema.get("required", []) == []
        properties = schema["properties"]
        assert set(properties) == {"number", "date", "counterpartyId", "basis", "kind", "currency", "paymentTermDays", "vatPct", "amountInclVat", "signed", "signedAt", "comment", "validity"}
        for name in ("vatPct", "amountInclVat", "signedAt", "comment"):
            assert {"type": "null"} in properties[name]["anyOf"]


def test_46_patch_rejects_empty_immutable_null_and_extra():
    reject(dto.CardChangesV2, [{}, {"profile": "Lease"}, {"organizationId": ORG}, {"number": None}, {"date": None}, {"counterpartyId": None}, {"basis": None}, {"kind": None}, {"currency": None}, {"paymentTermDays": None}, {"signed": None}, {"validity": None}, {"legacy": True}])
    for mode in ("validation", "serialization"):
        properties = dto.CardChangesV2.model_json_schema(mode=mode)["properties"]
        for name in ("number", "date", "counterpartyId", "basis", "kind", "currency", "paymentTermDays", "signed", "validity"):
            field_schema = properties[name]
            assert "default" not in field_schema
            assert "null" not in field_schema.get("type", [])
            assert all(branch.get("type") != "null" for branch in field_schema.get("anyOf", []))
            assert all(branch.get("type") != "null" for branch in field_schema.get("oneOf", []))


def test_47_only_merged_card_proves_dependent_rules():
    # Each partial patch is structurally legal; its final state is invalid.
    with pytest.raises(ValidationError):
        dto.merge_contract_card(card(), {"signed": True}, todayMSK=TODAY)
    with pytest.raises(ValidationError):
        dto.merge_contract_card(card(validity={"kind": "until", "date": "2026-11-01"}), {"date": "2026-11-02"}, todayMSK=TODAY)
    with pytest.raises(ValidationError):
        dto.merge_contract_card(card(profile="PowerSupply", basis="contract"), {"basis": "permission"}, todayMSK=TODAY)


def test_48_term_create_requires_separate_final_card_coverage_check():
    command = accept(dto.TermCreateCommandV2, {"commandKey": KEY, "expectedVersion": VERSION, "term": term()}, wire=True)
    result = dto.validate_contract_term(command.term, finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    assert result.costItem == "rent"


def test_49_term_version_preserves_stream_and_advances_start():
    command = accept(dto.TermNewVersionCommandV2, {"commandKey": KEY, "expectedVersion": VERSION, "replacement": term(validFrom="2026-12-01", condition={"kind": "fixed", "amountGross": "1500.00", "vatPct": None})}, wire=True)
    result = dto.validate_term_replacement(command.replacement, previousTerm=term(), finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    assert result.validFrom == date(2026, 12, 1) and result.condition.amountGross == Decimal("1500.00")


def test_50_term_version_rejects_stream_change_and_nonadvancing_start():
    with pytest.raises(ValueError, match="costItem"):
        dto.validate_term_replacement(term(validFrom="2026-12-01"), previousTerm=term(costItem="energy", condition={"kind": "metered_kwh", "tariffRub": "6.250000", "vatPct": None}), finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    with pytest.raises(ValueError, match="context"):
        dto.validate_term_replacement(term(validFrom="2026-12-01"), previousTerm=term(context={"kind": "site", "siteId": OTHER_SITE}), finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
    with pytest.raises(ValueError, match="validFrom"):
        dto.validate_term_replacement(term(), previousTerm=term(), finalCard=card(), coverage={"kind": "site", "siteId": SITE}, todayMSK=TODAY)
