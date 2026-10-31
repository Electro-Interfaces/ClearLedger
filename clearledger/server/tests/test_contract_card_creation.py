"""Future actual-PG checks for the common card primitives; ROOT execution only.

Reuse the native synthetic world and its exact disposable target. No copied
schema/transport harness; the ROOT runner must supply the reviewed db fixture.
Module guards do not protect against conftest loading first: ordinary pytest
is not approved. A separately reviewed ROOT runner must guard before imports.
These tests do not authorize or implement partner CREATE admission.
"""
import os
from urllib.parse import urlsplit

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_CONTRACT_CARD_CREATION_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Requires {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
if (urlsplit(os.environ["TEST_DATABASE_URL"]).path != "/api_native_contract_create_test_20261030"
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or os.environ.get("RUN_NATIVE_CONTRACT_CREATE_TESTS") != "1"
        or os.environ.get("ROOT_APPROVED_NATIVE_CONTRACT_CREATE_TESTS") != "1"):
    raise RuntimeError("Requires ROOT approval and the exact disposable native-create database")

from dataclasses import replace
from decimal import Decimal
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Contract, ContractLocation
from app.services.contract_card_creation import (
    ContractCardValues, create_contract_card, find_contract_card_duplicates,
)
from tests.test_native_contract_create import world

pytestmark = pytest.mark.asyncio(loop_scope="session")


def card_values(w) -> ContractCardValues:
    """Explicit domain input; no native DTO, defaults or normalization helper."""
    return ContractCardValues(
        company_id=w.cid, creation_key=None, creation_actor_id=None,
        creation_request_hash=None, number="Shared-1", date="2026-01-01",
        counterparty_id=w.cp_id, organization_id=w.org_id, type="Синтетическая аренда",
        type_code=w.active, amount_limit=125.5, kind="СПоставщиком", currency="RUB",
        valid_until="без даты", vat_rate="20", amount_incl_vat=True,
        settlement_kind="Синтетический расчёт", comment="Синтетический комментарий",
        basis="договор", is_closed=True, scope_type="locations", signed=True,
        signed_at="2026-01-02", payment_term_days=7, is_state_contract=True,
        igk="synthetic-igk", responsible_id=w.member_id, signer_our="Подписант 1",
        signer_our_position="Должность 1", signer_cp="Подписант 2",
        signer_cp_position="Должность 2", signer_cp_basis="Синтетическое основание",
    )


async def test_shared_flush_waits_for_caller_commit_and_maps_all_columns(world):
    w = world
    key = uuid.uuid4()
    values = replace(card_values(w), creation_key=key, creation_actor_id=w.member_id,
                     creation_request_hash="a" * 64)
    async with w.factory() as transaction:
        row = await create_contract_card(transaction, values)
        assert isinstance(row, Contract) and isinstance(row.id, uuid.UUID)
        row_id = row.id
        # Scalar SQL proves the INSERT happened, independently of the identity map.
        assert await transaction.scalar(select(Contract.id).where(Contract.id == row_id)) == row_id
        async with w.factory() as observer:
            assert await observer.scalar(select(Contract.id).where(Contract.id == row_id)) is None
        await transaction.commit()
    async with w.factory() as fresh:
        row = await fresh.get(Contract, row_id)
        expected = {
            "company_id": w.cid, "creation_key": key, "creation_actor_id": w.member_id,
            "creation_request_hash": "a" * 64, "number": "Shared-1", "date": "2026-01-01",
            "counterparty_id": w.cp_id, "organization_id": w.org_id,
            "type": "Синтетическая аренда", "type_code": w.active,
            "amount_limit": Decimal("125.50"), "kind": "СПоставщиком", "currency": "RUB",
            "valid_until": "без даты", "vat_rate": "20", "amount_incl_vat": True,
            "settlement_kind": "Синтетический расчёт", "comment": "Синтетический комментарий",
            "basis": "договор", "is_closed": True, "scope_type": "locations", "signed": True,
            "signed_at": "2026-01-02", "payment_term_days": 7, "is_state_contract": True,
            "igk": "synthetic-igk", "responsible_id": w.member_id,
            "signer_our": "Подписант 1", "signer_our_position": "Должность 1",
            "signer_cp": "Подписант 2", "signer_cp_position": "Должность 2",
            "signer_cp_basis": "Синтетическое основание", "raw": None,
            "external_ref": None, "manual_overrides": [], "title": None, "liability": None,
        }
        assert row is not None
        assert {name: getattr(row, name) for name in expected} == expected
        assert (await fresh.scalars(select(ContractLocation).where(
            ContractLocation.contract_id == row_id))).all() == []


async def test_shared_flushed_card_disappears_on_caller_rollback(world):
    w = world
    async with w.factory() as transaction:
        row = await create_contract_card(transaction, card_values(w))
        row_id = row.id
        assert isinstance(row_id, uuid.UUID)
        assert await transaction.scalar(select(Contract.id).where(Contract.id == row_id)) == row_id
        await transaction.rollback()
    async with w.factory() as fresh:
        assert await fresh.scalar(select(Contract.id).where(Contract.id == row_id)) is None
        assert (await fresh.scalars(select(Contract).where(Contract.company_id == w.cid))).all() == []


async def test_shared_flush_failure_propagates_without_partial_card(world):
    w = world
    async with w.factory() as transaction:
        # Valid UUID, absent FK target: a real flush failure, no mocked flush.
        with pytest.raises(IntegrityError):
            await create_contract_card(transaction, replace(card_values(w), counterparty_id=uuid.uuid4()))
        await transaction.rollback()
    async with w.factory() as fresh:
        assert (await fresh.scalars(select(Contract).where(Contract.company_id == w.cid))).all() == []


@pytest.mark.parametrize("case", ["null", "zero-false", "empty-strings"])
async def test_shared_values_preserve_null_zero_false_and_empty_strings(world, case):
    w = world
    values = card_values(w)
    if case == "null":
        values = replace(values, type_code=None, amount_limit=None, kind=None, currency=None,
                         valid_until=None, vat_rate=None, amount_incl_vat=None, settlement_kind=None,
                         comment=None, basis=None, signed=None, signed_at=None, payment_term_days=None,
                         is_state_contract=None, igk=None, responsible_id=None, signer_our=None,
                         signer_our_position=None, signer_cp=None, signer_cp_position=None, signer_cp_basis=None)
        expected = {"type_code": None, "amount_limit": None, "kind": None, "currency": None,
                    "valid_until": None, "vat_rate": None, "amount_incl_vat": None, "settlement_kind": None,
                    "comment": None, "basis": None, "signed": None, "signed_at": None,
                    "payment_term_days": None, "is_state_contract": None, "igk": None,
                    "responsible_id": None, "signer_our": None, "signer_our_position": None,
                    "signer_cp": None, "signer_cp_position": None, "signer_cp_basis": None}
    elif case == "zero-false":
        values = replace(values, amount_limit=0, amount_incl_vat=False, is_closed=False,
                         signed=False, payment_term_days=0, is_state_contract=False)
        expected = {"amount_limit": Decimal("0.00"), "amount_incl_vat": False,
                    "is_closed": False, "signed": False, "payment_term_days": 0, "is_state_contract": False}
    else:
        # The primitive receives prepared scalars: only the native adapter owns
        # _req_val's empty-to-null conversion. No second normalizer belongs here.
        values = replace(values, number="", date="", type="", type_code="", kind="", currency="",
                         valid_until="", vat_rate="", settlement_kind="", comment="", basis="",
                         signed_at="", igk="", signer_our="", signer_our_position="",
                         signer_cp="", signer_cp_position="", signer_cp_basis="")
        expected = {"number": "", "date": "", "type": "", "type_code": "", "kind": "", "currency": "",
                    "valid_until": "", "vat_rate": "", "settlement_kind": "", "comment": "", "basis": "",
                    "signed_at": "", "igk": "", "signer_our": "", "signer_our_position": "",
                    "signer_cp": "", "signer_cp_position": "", "signer_cp_basis": ""}
    async with w.factory() as transaction:
        row = await create_contract_card(transaction, values)
        row_id = row.id
        await transaction.commit()
    async with w.factory() as fresh:
        row = await fresh.get(Contract, row_id)
        assert row is not None
        assert {name: getattr(row, name) for name in expected} == expected
        if case == "zero-false":
            assert row.amount_incl_vat is row.is_closed is row.signed is row.is_state_contract is False
        assert row.creation_key is row.creation_actor_id is row.creation_request_hash is None


@pytest.mark.parametrize("case", ["same", "different-number", "different-date", "different-type"])
async def test_shared_duplicates_use_exact_company_parties_and_existing_identity(world, case):
    w = world
    values = card_values(w)
    async with w.factory() as transaction:
        first = await create_contract_card(transaction, values)
        second = await create_contract_card(transaction, replace(values, number=" Shared-1 ",
                                            date=" 2026-01-01 ", type=" Синтетическая аренда "))
        number = await create_contract_card(transaction, replace(values, number="Shared-2"))
        date = await create_contract_card(transaction, replace(values, date="2026-02-01"))
        kind = await create_contract_card(transaction, replace(values, type="Другой вид"))
        # Valid SQL FKs with intentionally crossed tenant attribution isolate the
        # company predicate itself; this is not an admitted native command input.
        await create_contract_card(transaction, replace(values, company_id=w.foreign_cid))
        await create_contract_card(transaction, replace(values, counterparty_id=w.cp2_id))
        await create_contract_card(transaction, replace(values, organization_id=w.org2_id))
        await create_contract_card(transaction, replace(values, date="not-an-iso-date"))
        await create_contract_card(transaction, replace(values, number=""))
        expected_ids = {first.id, second.id} if case == "same" else {
            {"different-number": number.id, "different-date": date.id, "different-type": kind.id}[case]}
        await transaction.commit()
    identity = {
        "same": ("Shared-1", "2026-01-01", "Синтетическая аренда"),
        "different-number": ("Shared-2", "2026-01-01", "Синтетическая аренда"),
        "different-date": ("Shared-1", "2026-02-01", "Синтетическая аренда"),
        "different-type": ("Shared-1", "2026-01-01", "Другой вид"),
    }[case]
    async with w.factory() as reader:
        matches = await find_contract_card_duplicates(reader, w.cid, w.cp_id, w.org_id, identity)
        assert {row.id for row in matches} == expected_ids
        assert len(matches) == len(expected_ids)
        assert all(isinstance(row, Contract) for row in matches)
        await reader.rollback()
