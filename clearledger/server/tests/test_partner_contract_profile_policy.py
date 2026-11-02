"""AUTHOR ONLY / NOTRUN. Ordinary pytest/collection is UNSAFE: parent conftest
imports app/engine and owns destructive DROP before any module guard. ROOT must
supply its separately admitted preimport composition. No runner/target here.
"""
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas_partner import ReplaceContractCreateProfile


def request(**changes):
    value = dict(userIds=[], machineGrantIds=[], organizationIds=[],
                 counterpartyIds=[], locationIds=[], typeCodes=[])
    value.update(changes)
    return value


def test_omitted_create_generation_and_defaults_do_not_activate():
    body = ReplaceContractCreateProfile.model_validate(request())
    assert body.expectedGeneration is None and body.revoked is False
    assert all(getattr(body, name) == () for name in (
        "userIds", "machineGrantIds", "organizationIds", "counterpartyIds", "locationIds", "typeCodes"))
    assert not hasattr(body, "userEnabled") and not hasattr(body, "serviceEnabled")


@pytest.mark.parametrize("field", ["userEnabled", "serviceEnabled", "user_enabled", "service_enabled", "all", "receipt"])
def test_activation_and_caller_receipt_fields_are_forbidden(field):
    with pytest.raises(ValidationError):
        ReplaceContractCreateProfile.model_validate(request(**{field: True}))


@pytest.mark.parametrize("generation", [True, False, 0, -1, "1", 1.0, 9223372036854775808])
def test_generation_is_an_exact_positive_bigint(generation):
    with pytest.raises(ValidationError):
        ReplaceContractCreateProfile.model_validate(request(expectedGeneration=generation))


@pytest.mark.parametrize("field", ["userIds", "machineGrantIds", "organizationIds", "counterpartyIds", "locationIds", "typeCodes"])
@pytest.mark.parametrize("bad", [None, "x", {}, [True], [["x"]], [{}]])
def test_lists_reject_coercion_and_nested_input(field, bad):
    with pytest.raises(ValidationError):
        ReplaceContractCreateProfile.model_validate(request(**{field: bad}))


@pytest.mark.parametrize("field", ["userIds", "machineGrantIds", "organizationIds", "counterpartyIds"])
def test_uuid_lists_have_no_silent_normalization_or_duplicates(field):
    uid = uuid4()
    for values in [[uid.hex], [str(uid), str(uid).upper()], [str(uid)] * 101]:
        with pytest.raises(ValidationError):
            ReplaceContractCreateProfile.model_validate(request(**{field: values}))
    assert getattr(ReplaceContractCreateProfile.model_validate(request(**{field: [str(uid)]})), field) == (uid,)


@pytest.mark.parametrize("value", ["", " ", "\x00", "x" * 41, "\ud800"])
def test_opaque_locations_reject_invalid_text_without_truncation(value):
    with pytest.raises(ValidationError):
        ReplaceContractCreateProfile.model_validate(request(locationIds=[value]))


def test_opaque_locations_preserve_case_spaces_and_non_uuid_strings():
    ids = ["  ОПАК:Ё/01  ", "A", "a", "7"]
    body = ReplaceContractCreateProfile.model_validate(request(locationIds=ids))
    assert body.locationIds == tuple(ids)


@pytest.mark.parametrize("value", ["", " ", "\x00", "x" * 257])
def test_contract_type_codes_are_bounded_exact_text(value):
    with pytest.raises(ValidationError):
        ReplaceContractCreateProfile.model_validate(request(typeCodes=[value]))


def test_null_and_omitted_generation_equal_only_as_create_input():
    assert ReplaceContractCreateProfile.model_validate(request()).expectedGeneration is None
    assert ReplaceContractCreateProfile.model_validate(request(expectedGeneration=None)).expectedGeneration is None
    assert ReplaceContractCreateProfile.model_validate(request(expectedGeneration=2)).expectedGeneration == 2


# Raw decorator+body hashes are filled from immutable29base by stdlib only.
# They include dependency/default expressions and do not execute a registry.
FROZEN_HANDLERS = {('clearledger/server/app/routers/partner_admin_router.py', 'register'): '6ccfffb28d289d04d8b82d7ff46efa69618313633f1bb86e6bcb39fb50c33049', ('clearledger/server/app/routers/partner_admin_router.py', 'client_status'): 'acf72ed4986a3e08d760e6e44a4d2a96bd3cf1b398940953fa52dbe0336683b9', ('clearledger/server/app/routers/partner_admin_router.py', 'issue_credential'): 'd06c4779bcd131d0f9bc977b67dfe3cc3b3d3affee552a6ca734689514941a23', ('clearledger/server/app/routers/partner_admin_router.py', 'revoke_credential'): '418dc1fbc2b6be471944e334b88321f4aacfeadd5b872adb7e242dc9318d38e1', ('clearledger/server/app/routers/partner_admin_router.py', 'approve_installation'): '1f6987a83b367bf17ff1d2d225a72f2b705fdcde54b3e7f0f31fba7df64b42f4', ('clearledger/server/app/routers/partner_admin_router.py', 'revoke_installation'): 'c9716a61a1b92abb4d2ee022ce4df75ed237aa8492046823cda0278be783eb5f', ('clearledger/server/app/routers/partner_admin_router.py', 'machine_grant'): 'be4a122cc685e72b8f1b09c73622e7563ec9254945a13e3b496a5172e63a03fd', ('clearledger/server/app/routers/partner_admin_router.py', 'revoke_grant'): 'd29cecafe84e921a398120a7497bbab2600f3c0898878fcd508a93a6ccb39ed7', ('clearledger/server/app/routers/partner_oauth_router.py', 'authorize'): 'b06d318120f3d10998c30c8b89a4e90cdb326736bec1385251c36091bd96e7f2', ('clearledger/server/app/routers/partner_oauth_router.py', 'token'): 'ce598250dc93041f83414df0e2c719df889363d16bb9ca0aad7b57008f021dcb', ('clearledger/server/app/routers/partner_oauth_router.py', 'revoke'): 'b18f50f399e84ee5db24a94098bac5d3185a92044fe2881a62fd4be17c09b8fe', ('clearledger/server/app/routers/partner_oauth_router.py', 'discovery'): '27f6304e74038955d5b211c39131a5c187b9a524e30595f0f14c6fa3228da17c', ('clearledger/server/app/routers/partner_oauth_router.py', 'jwks'): 'ebacb896cd47e7d046a6f16a406b80140872e8685a7167f542f26f6f4e8a3c25', ('clearledger/server/app/routers/partner_oauth_router.py', 'userinfo'): '163e8d7b1ec1004e10bb6d6411153800fff6198228253f0ffc11555f52ba0ac3', ('clearledger/server/app/routers/partner_oauth_router.py', 'get_request'): '962a09389e9691435f78c7466588deb45fba135677ae99d55c7c4879bc626008', ('clearledger/server/app/routers/partner_oauth_router.py', 'approve'): '51b0826ffdff1399e56374c98c0c31645f7113785778566d5644aba9cabdc8b8', ('clearledger/server/app/routers/partner_oauth_router.py', 'deny'): 'd83c4879c2768f11b6a2eba336d4503f1a2d307c4e9573783baac467dabf64bb'}
FROZEN_POLICY_FILES = {'clearledger/server/app/api_contracts/context.py': '6ab6a7edd80dc33e6e865f4a394e534c6e5dad7434b79559e7a930b81fdd7ccf', 'clearledger/server/app/api_contracts/routing.py': '86c0ecc2b86b6b4d44ff0e230c16e015dc02de8a3c3e331d8e9c104af06be862', 'clearledger/server/app/product_api/app.py': 'c82da8d35b3ca301a93445a667a44bb861d2f2d2ace9fc3c08aac87a3ccab774', 'clearledger/server/app/product_api/contract_create_body.py': '07c5b7976bc6284a6dc10b43579aaa41047c41e8581d34a19f5f93338b824a8e', 'clearledger/server/app/services/contract_write_locks.py': 'a1d544fcace1080629a29b42701861a04f0286f7d8ba5a133d0df446eb331c54'}


def test_old_seventeen_handlers_and_canonical_policy_sources_are_preserved():
    import ast
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    actual = {}
    for path in {path for path, _ in FROZEN_HANDLERS}:
        source = (root / path).read_bytes()
        lines = source.splitlines(keepends=True)
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (path, node.name) in FROZEN_HANDLERS:
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                actual[(path, node.name)] = hashlib.sha256(b"".join(lines[start-1:node.end_lineno])).hexdigest()
    assert len(FROZEN_HANDLERS) == 17
    assert actual == FROZEN_HANDLERS
    for path, expected in FROZEN_POLICY_FILES.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected
