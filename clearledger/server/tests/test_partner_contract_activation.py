"""AUTHOR ONLY / NOTRUN, including collection. ROOT owns runtime admission.

No runner, target, settings or schema provision. Parent conftest is destructive;
these definitions require ROOT's separate admitted composition before imports.
"""
import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas_partner import ActivateContractCreateProfile
from app.services.partner_contract_activation import _request


def request(**changes):
    return dict(expectedGeneration=1, userEnabled=False, serviceEnabled=False, **changes)


@pytest.mark.parametrize("field", ["expectedGeneration", "userEnabled", "serviceEnabled"])
def test_all_activation_fields_are_required_and_not_nullable(field):
    body = request()
    del body[field]
    with pytest.raises(ValidationError):
        ActivateContractCreateProfile.model_validate(body)
    body[field] = None
    with pytest.raises(ValidationError):
        ActivateContractCreateProfile.model_validate(body)


@pytest.mark.parametrize("value", [True, False, 0, -1, "1", 1.0, 9223372036854775808])
def test_generation_is_strict_positive_bigint(value):
    with pytest.raises(ValidationError):
        ActivateContractCreateProfile.model_validate({**request(), "expectedGeneration": value})


@pytest.mark.parametrize("field", ["userEnabled", "serviceEnabled"])
@pytest.mark.parametrize("value", [0, 1, "true", "false", [], {}, None])
def test_flags_are_exact_booleans(field, value):
    with pytest.raises(ValidationError):
        ActivateContractCreateProfile.model_validate({**request(), field: value})


@pytest.mark.parametrize("field", ["userIds", "revoked", "profileId", "receipt", "companyId", "user_enabled"])
def test_activation_has_no_child_or_authority_input(field):
    with pytest.raises(ValidationError):
        ActivateContractCreateProfile.model_validate({**request(), field: True})


@pytest.mark.parametrize("changes", [{"userEnabled": 1}, {"expectedGeneration": True},
                                      {"serviceEnabled": None}, {"expectedGeneration": 0}])
def test_forged_construct_and_copy_are_revalidated(changes):
    for body in (ActivateContractCreateProfile.model_construct(**{**request(), **changes}),
                 ActivateContractCreateProfile.model_validate(request()).model_copy(update=changes)):
        with pytest.raises(HTTPException) as error:
            _request(body)
        assert error.value.status_code == 422


def test_exact_dto_type_and_instance_fields_cannot_be_forged():
    class Child(ActivateContractCreateProfile):
        pass
    forged = ActivateContractCreateProfile.model_validate(request()).model_copy(update={"receipt": True})
    for body in (request(), Child(**request()), forged):
        with pytest.raises(HTTPException) as error:
            _request(body)
        assert error.value.status_code == 422
    assert _request(ActivateContractCreateProfile.model_validate(request())).expectedGeneration == 1


ROOT = Path(__file__).resolve().parents[1]


def test_source_exact_private_composition_one_b_and_no_children_dml():
    service = ast.parse((ROOT / "app/services/partner_contract_activation.py").read_bytes())
    operation = next(n for n in service.body if isinstance(n, ast.ClassDef) and n.name == "ActivationOperation")
    assert not operation.bases
    code = ast.unparse(operation)
    assert "ProfileOperation(installation_id, None)" in code
    for name in ("discover", "recheck", "readback"):
        assert f".graph.{name}(" in ast.unparse(service)
    forbidden = {"delete", "add_all", "commit", "acquire_scoped_locks", "live_grant", "verify_access"}
    assert not {n.func.attr for n in ast.walk(operation) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)} & forbidden
    mutation = next(n for n in service.body if isinstance(n, ast.FunctionDef)
                    and n.name == "activate_partner_contract_create_profile")
    calls = [n for n in ast.walk(mutation) if isinstance(n, ast.Call)]
    assert sum(isinstance(n.func, ast.Name) and n.func.id == "_prepare_partner_write" for n in calls) == 1
    assert sum(isinstance(n.func, ast.Attribute) and n.func.attr == "flush" for n in calls) == 1
    assert "partner.contract_profile.activation" in ast.unparse(mutation)
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in {"Principal", "Ref", "Type", "Intent", "Contract"} for n in calls)


def test_source_activation_only_gate_stage_and_whole_root_completion():
    identity = ast.parse((ROOT / "app/services/partner_identity.py").read_bytes())
    composer = next(n for n in identity.body if isinstance(n, ast.FunctionDef) and n.name == "_prepare_partner_write")
    source = ast.unparse(composer)
    assert "type(contract_profile) is not ActivationOperation" in source
    assert "activation_purpose = mutation == 'contract-profile-activation'" in source
    assert "activation_writer is not None and stage_index == 0" in source
    assert "spec.model not in contract_profile.parent_models" in source
    assert source.index("contract_profile.freeze(db, ordered, installation_sets, credential_sets)") < source.index("cap = acquire_scoped_locks(db, plan)")
    service = ast.parse((ROOT / "app/services/partner_contract_activation.py").read_bytes())
    owner = next(n for n in service.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "activation_admin_request")
    transaction = owner.body[-1]
    assert isinstance(transaction, ast.Try)
    assert ast.unparse(transaction.handlers[0].type) == "BaseException"
    assert [ast.unparse(n) for n in transaction.handlers[0].body] == ["await db.rollback()", "raise"]
    assert [ast.unparse(n) for n in transaction.body][-2:] == ["await db.commit()", "return result"]
