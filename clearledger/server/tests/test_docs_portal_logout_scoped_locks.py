"""AUTHORED / NOTRUN (including collection): stdlib source contracts only.

No app/helper/parser/auth imports or calls. Tests inspect actual function bodies,
not dependency defaults/decorators. Parent conftest remains unsafe to collect
without a separate ROOT-owned composition/admission.
"""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app/services/docs_portal.py"
ROUTER = ROOT / "app/routers/docs_portal_router.py"
IDENTITY = ROOT / "app/services/partner_identity.py"
BASE = "bf741aa6ee852bdee511204bfb1027436dd845a9"

PROTECTED_BYTES = {'app/routers/partner_admin_router.py': 'ced1958f0f2cfe85c39af4984bb55663c3139c844925622af5f869575ad3f2ff', 'app/routers/partner_oauth_router.py': 'f2c81e888eb6300c6e4ad1a11903f1ade875db332a7d9ea4799fbe5ff4bfd3b3', 'app/services/partner_identity.py': '1c1748b3bb12fd9fa9ce017be20e35d109d835987fcb7fc57dfcbafe60c47724', 'tests/test_partner_writer_scoped_locks.py': 'b2ca00492ddf2f669306fba5eb1e931df0b081b4f1f4be457dcfdc3784f1ccf2', 'tests/test_partner_writer_scoped_locks_pg.py': '756372a2bab417a81bb6fc30bdaf4e85e2ce6b68f8dc5d621624bb6575163819', 'app/services/contract_write_locks.py': 'a1d544fcace1080629a29b42701861a04f0286f7d8ba5a133d0df446eb331c54', 'app/models_partner.py': '51695adcc2784279fa00a0b2cccd99f181ee0a51cbf6232b8499adc0a7ada916', 'app/models_docs_portal.py': '57bce6f84b8992503e2069bc3b6f7a91be830adc1312269e7742309a19087c64', 'app/models.py': 'ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682', 'app/database.py': 'c2c028fc528b7260c69de441e41a564595d07c23c74e4433f02fc9f04db005af', 'app/auth.py': '0020fc52525e16c9a701598a871d72d67af25683690debe153b1995ed0c1b889', 'tests/conftest.py': '32ea55b426d111d8615e0f85ac7561a55ec802ee98a2b59a336405205ab1f57b', 'tests/partner_test_safety.py': '43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1', 'tests/test_docs_portal.py': 'a56f0eda9bf6ab89f24fefd4c73a61c3ff3a33e2257df64971432a5c2f22c6ff', 'tests/test_docs_portal_browser.py': '6b52236afd7fb367b75e88fed6439d12f75b190bd2fbe99d8506ae430e50df58', 'tests/test_partner_main_composition.py': 'ee887de322fa62aee1af01304ee4b8d6c33b1c2940c7b8f22bd9eca0a93d7f32', 'tests/partner_main_composition_approved.py': '23fa037557b16ab2ffcf672a7759fa89ff1adf2e11d4afbb5644fc534fea5bd8', 'tests/partner_contract_schema_v4_fixture.py': '5fbd458cfb1b07c86f4e835e8699aba3608c01cf7d86fe713ad9bdf3d6dca777', 'tests/partner_contract_schema_v4_approval.py': 'e056ac5abf886180e25855dd9f8f5f50a0efa6d106b7b849763e1336a7f97920'}
# Только принятый ROOT UUID result adapter; baseline DPL и остальные byteguards прежние.
UUID_ADAPTER_SOURCE = '29baa0c6a938c366edb2ee69cbcd1a60532558e4'
# Дополнительный scalar producer CompanyKey: единственное поле компании контакта.
UUID_CONTACT_SOURCE = '56a911478b9007b038e0cf20798151f255c198b0'
UUID_MODEL_OVERLAY = {'app/models.py': {'baseline': 'ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682', 'reviewed': 'bee511c0f1682519a6f074fd58dd88bc14068981599ba91e773838ed58ab6a49'}, 'app/models_partner.py': {'baseline': '51695adcc2784279fa00a0b2cccd99f181ee0a51cbf6232b8499adc0a7ada916', 'reviewed': '2de59cd89fee2f6c468db14e24e99b07577ea0078b7263abdc7a3da43e74ec94'}, 'app/models_docs_portal.py': {'baseline': '57bce6f84b8992503e2069bc3b6f7a91be830adc1312269e7742309a19087c64', 'reviewed': '28b84b5229f2d95d17d9f2ff7b2959ebb9ac6cad038cc6327b26f6f7c0bbbdc2'}}
UUID_SUPPORT_BYTES = {'app/db_types.py': '59a7aa9e1c4d93599fd399cfb94aa19eb8f97ffc621ebe6d5ca735ab8f409aba', 'app/models_partner_contracts.py': 'd38d57424373220d358f5411bb566c62a6dbd30212be9bc482d8f7358e4cf2de', 'app/product_api/queries.py': '3d9a1b141def031c48d47229fb0fc59191d901247597f581dbb9f8f06f1d8ad1', 'app/services/counterparty_usage.py': '6d50c33790c0ced4933d73b662e1a3e8c20c1056a30496aa8cf36ea1dc4ef5c9'}

# Принятые отдельные срезы ROOT; исходные19 и29 policy pins сохранены.
INTEGRATED_SOURCE_PINS = ('9841890a3fd19f51a2ae388ce845c3bd19ea328e', '5b27ed4decd3f86a776d05cb58104bd0d2549f4b', 'c6376f2b887dad9947409d6947520cd3ec6704fa')
INTEGRATED_BYTE_OVERLAY = {'app/routers/partner_admin_router.py': {'baseline': 'ced1958f0f2cfe85c39af4984bb55663c3139c844925622af5f869575ad3f2ff', 'reviewed': '1d097bfca261e25dd6a482cd2b041fde4f6ef593ef29252c55335a5e15ca97db'}, 'app/services/partner_identity.py': {'baseline': '1c1748b3bb12fd9fa9ce017be20e35d109d835987fcb7fc57dfcbafe60c47724', 'reviewed': 'cac8be62a1fdf840c0f285574d0c3266a1404f984b597aa9111fab62f6d1fe22'}, 'tests/test_partner_writer_scoped_locks_pg.py': {'baseline': '756372a2bab417a81bb6fc30bdaf4e85e2ce6b68f8dc5d621624bb6575163819', 'reviewed': '5fb0e0c14074a9aeecb4ae65a515289b57debc22969b18bc6c7ea7f5b663f0a7'}}

CANONICAL_12 = {'verify_access': '8dd700eaa560771a2890ca0837ee2e8c419bccdaad8bbdde2d3643726a7d4250', 'live_grant': '9a24d316c20290bc90a329fe3d2652ee8072028798182ac680b34e94a6881448', 'eligible_scopes': '1524bb5ebec7869c2ac8c742c830da0fd234e9433fcc70f7ed7809c76ef78107', 'admin': '86fdeba221d4968b5ed9c049630703aff94ba1f828a05440ce2ef25d008badba', 'active_user': '3d80e091fce1dfbd10fec98006522ff13181ff6a719a4a900485b99bfa0ff213', 'require_core_user': '29b605e7083c0a2eaa1188a96a8c3fed73af9888a1326ba49943dc4c79dbcb7d', 'signing_key': 'b83ebc8f9da51577d3ebceb5ee7e8bd3bd07c042f6642bd362447893c4852ad7', 'public_jwks': 'a13616725b2fed83b969875b2f9f4913095e6888dbedaab063667a0091d66e0d', 'validate_scopes': '8fe53fb297112853ce73ca204cac1e47f47bccd816e1566d4a90c9c2ec0bbaca', 'validate_redirect': '95eb275ad222abff1ceec38efc6e30ef29809095122270968ad7c4a52e9ede36', 'pairwise_subject': '26e6db2c84bf2f0d6de6f5d70e86a3fecff0e22a4dc0a536c4c5d318aa53a6a1', 'user_info': 'fdd0f58ed887398692f83d3eba178b939a6a04bfeffd65c93d4c1bbc25eb9ade'}
# Explicit ROOT policy extension, not a historical repin. Original 19/17/12
# literals above/below remain authoritative for their baseline projection.
ACCEPTED_CREATE_EXTENSION = {
    "base": "011f0c571912aa7c5d972e851b0d0e3acdf645a9",
    "ratification": ("msg_d78d5ba7a19d", "msg_4bc270231cbd", "msg_c014d327b3a5"),
    "scope": "contracts:create", "module": "references",
    "baseline_file": "cac8be62a1fdf840c0f285574d0c3266a1404f984b597aa9111fab62f6d1fe22",
    "extended_file": "11624851e39b2dbf2671b46d349ed5f627a23f2b6359c716583c8c724fd651d9",
    "baseline_eligible": "1524bb5ebec7869c2ac8c742c830da0fd234e9433fcc70f7ed7809c76ef78107",
    "extended_eligible": "cb9fc729c9b13a563f43c79161e3aba7983c1b45dd6600a20a20e1e4201724d9",
}
# G-ORG01 is a separate, explicitly ratified order extension. Keep the
# accepted CREATE scope record and every historical 19/17/12 pin unchanged.
ACCEPTED_G_ORG_ORDER_EXTENSION = {
    "ratification": "msg_b07b4203c2cc",
    "source_parent": "297f7b4a726b917530e6ba54ff71a7b6c2c33e38",
    "baseline_file": "11624851e39b2dbf2671b46d349ed5f627a23f2b6359c716583c8c724fd651d9",
    "extended_file": "ad2408f8e081a4088668d3f1c45c12be06bb293a43ca48e333248fa90c6f688a",
    "authority_baseline_file": "1b62359305c87a2f6de0c44adf83eef2286b280b191dcd24850067ffe0d8c741",
    "authority_extended_file": "cb762a3d7341d84af400ad0378069a6387c09087d64827e0267ee9eb4c586586",
    "prefix": ("Company", "App", "PartnerClient", "User", "CompanyRole"),
    "parents": ("Counterparty", "Organization", "ServiceLocation", "Contract"),
    "boundary": "after prefix; before ANY UserCompany; including empty Member set",
}
# Explicit HTTP/coarse extension; historical GORG and 19/17/12 pins stay intact.
ACCEPTED_HTTP_CREATE_EXTENSION = {
    "ratification": ("msg_dc2f907bf07e", "msg_85a4864d991c"),
    "source_base": "cdb65361f3207f82283c88da8b431625a5b1804c",
    "authority_baseline_file": "cb762a3d7341d84af400ad0378069a6387c09087d64827e0267ee9eb4c586586",
    "authority_extended_file": "92beb9c24d6d8e30d58414c00190618ab6f1265aece0ab0b20880250bfd98c18",
    "authority_baseline_ast": "b5c4c524e3acd1b347e00c8e78eb591ee7b97baea48e8cdcf5de60792c32765c",
    "operation": ("POST", "/api/v1/contracts", "createContract"),
}

PROTECTED_17 = [('admin.register', 'app/routers/partner_admin_router.py', 'register', 'babffd869487681577361145bb2fed6f9d34da74a7e84bfcfb0e64063b156f57'), ('admin.client_status', 'app/routers/partner_admin_router.py', 'client_status', 'ecae87c5e9f16b287b94710e8afebb665784a9522fa98305e6a734586d182fd0'), ('admin.issue_credential', 'app/routers/partner_admin_router.py', 'issue_credential', 'd99a543f3e3b2c5935c53842837712a596242fb540c161709e05c394ba985fab'), ('admin.revoke_credential', 'app/routers/partner_admin_router.py', 'revoke_credential', '191517e884f64724b52b58240a72d14bd41903c5ef284e9d0df3712ce43ecfe8'), ('admin.approve_installation', 'app/routers/partner_admin_router.py', 'approve_installation', '0aa0fba2a41483db29ac285ee7c34b95aefdc190c37df0205aa7135a2374d1f5'), ('admin.revoke_installation', 'app/routers/partner_admin_router.py', 'revoke_installation', '79819f21a5df17c66dd4f017246cb6a5f9cb4c0d15edd6d3ebac06ae862c6ac7'), ('admin.machine_grant', 'app/routers/partner_admin_router.py', 'machine_grant', 'eb33e31712ac4bc3a8940925cf198bdbc05f599ef23711b893c4a2da59a68616'), ('admin.revoke_grant', 'app/routers/partner_admin_router.py', 'revoke_grant', '39a21684593bda9fad770cccc244aba5f3fe5f826f7fd4b2a0455f14c02075e7'), ('oauth.authorize', 'app/routers/partner_oauth_router.py', 'authorize', 'a73573447f15f9843a47020eeafeb04cd3c0f638d68dd5e3190dadb4d8facdf3'), ('consent.get_request', 'app/routers/partner_oauth_router.py', 'get_request', '94ae42b6e06ea61e0a88478390c0e9d0670700139b9f4c7531afeb58d2e8560f'), ('consent.approve', 'app/routers/partner_oauth_router.py', 'approve', '759e25b36da56bec7c4fa9abf58f80d87e0b08848b65aefaab62df7e0475b941'), ('consent.deny', 'app/routers/partner_oauth_router.py', 'deny', '6c9fea08b4d9eec59484d9fa80098a43dfa004ad02f980a21d47de6942117250'), ('oauth.token-code', 'app/routers/partner_oauth_router.py', '_protocol_response', '3cae40a3659dd214aaf35232660f7b53983d7e4adeda5634ea2616361692f109'), ('oauth.token-refresh', 'app/routers/partner_oauth_router.py', '_protocol_response', '3cae40a3659dd214aaf35232660f7b53983d7e4adeda5634ea2616361692f109'), ('oauth.token-machine', 'app/routers/partner_oauth_router.py', '_protocol_response', '3cae40a3659dd214aaf35232660f7b53983d7e4adeda5634ea2616361692f109'), ('oauth.revoke', 'app/routers/partner_oauth_router.py', '_protocol_response', '3cae40a3659dd214aaf35232660f7b53983d7e4adeda5634ea2616361692f109'), ('oauth.userinfo', 'app/routers/partner_oauth_router.py', 'userinfo', 'a1fcf03561c44c6bef7ce5c9b6f8138cb3faecaad8b8504f218fc7789bc4bd2e')]


def tree(path):
    return ast.parse(path.read_bytes(), filename=str(path))


def definition(path, name, owner=None):
    nodes = tree(path).body
    if owner:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner).body
    return next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def body_nodes(node):
    yield node
    children = node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ast.iter_child_nodes(node)
    for child in children:
        yield from body_nodes(child)


def calls(node, name):
    return [n for n in body_nodes(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def text(path, name, owner=None):
    return ast.unparse(definition(path, name, owner))


def stable_ast_dump(value):
    """Keep the original Python 3.11 pins across AST display changes.

    Only empty type_params is compatibility metadata. Nonempty parameters and
    every other field remain in the digest; locations remain excluded.
    """
    if isinstance(value, ast.AST):
        fields = []
        for name, child in ast.iter_fields(value):
            if name == "type_params" and child == []:
                continue
            if child is None and getattr(type(value), name, ...) is None:
                continue
            fields.append(name + "=" + stable_ast_dump(child))
        return type(value).__name__ + "(" + ", ".join(fields) + ")"
    if isinstance(value, list):
        return "[" + ", ".join(stable_ast_dump(child) for child in value) + "]"
    return repr(value)


def digest_node(node):
    return hashlib.sha256(stable_ast_dump(node).encode()).hexdigest()


def baseline_create_policy_projection(node):
    """Remove exactly the reviewed new mapping; preserve every old decision."""
    assert node.name == "eligible_scopes"
    assert digest_node(node) == ACCEPTED_CREATE_EXTENSION["extended_eligible"]
    projected, removed = deepcopy(node), 0
    for item in ast.walk(projected):
        if isinstance(item, ast.Dict):
            for index, key in enumerate(item.keys):
                if isinstance(key, ast.Constant) and key.value == "contracts:create":
                    assert isinstance(item.values[index], ast.Constant)
                    assert item.values[index].value == "references"
                    item.keys.pop(index); item.values.pop(index); removed += 1
                    break
    assert removed == 1
    assert digest_node(projected) == ACCEPTED_CREATE_EXTENSION["baseline_eligible"]
    return projected


def test_accepted_create_scope_extension_preserves_old_eligible_policy_projection():
    assert ACCEPTED_CREATE_EXTENSION["baseline_eligible"] == CANONICAL_12["eligible_scopes"]
    assert ACCEPTED_CREATE_EXTENSION["baseline_file"] == INTEGRATED_BYTE_OVERLAY["app/services/partner_identity.py"]["reviewed"]
    current = definition(IDENTITY, "eligible_scopes")
    old = baseline_create_policy_projection(current)
    assert digest_node(old) == CANONICAL_12["eligible_scopes"]
    assert digest_node(current) != digest_node(old)
    descriptions = next(n for n in tree(IDENTITY).body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SCOPE_DESCRIPTIONS" for t in n.targets))
    additions = [(key.value, value.value) for key, value in zip(descriptions.value.keys, descriptions.value.values)
                 if isinstance(key, ast.Constant) and key.value == "contracts:create"]
    assert additions == [("contracts:create", "Создание карточек договоров по отдельному профилю допуска")]


def test_source_digest_keeps_legacy_pin_and_detects_semantic_changes():
    node = ast.parse("def sample(value):\n    return value + 1\n").body[0]
    before = ast.dump(node, include_attributes=True)
    expected = "ee518d4f1a4c9b0c019cb6669d72a2911d5b0f3baeecaffa8ccf34beee63d22e"
    assert digest_node(node) == expected
    assert ast.dump(node, include_attributes=True) == before
    node.body[0].value.right.value = 2
    assert digest_node(node) != expected
    node.body[0].value.right.value = 1
    node.decorator_list.append(ast.Name(id="changed", ctx=ast.Load()))
    assert digest_node(node) != expected
    node.decorator_list.clear()
    if "type_params" in node._fields:
        node.type_params = [ast.Name(id="T", ctx=ast.Load())]
        assert digest_node(node) != expected


def test_logout_transport_authority_and_wire_are_unchanged():
    node = definition(ROUTER, "close_session")
    assert [ast.unparse(n) for n in node.decorator_list] == ["router.delete('/session')"]
    assert ast.unparse(node.args.defaults[0]) == "Depends(get_db)"
    assert [ast.unparse(n) for n in node.body[:3]] == ["no_overrides(request)",
        "raw = request.cookies.get(portal.COOKIE)", "portal.check_csrf(request, raw)"]
    transaction = node.body[3]
    assert isinstance(transaction, ast.Try) and not transaction.orelse and not transaction.finalbody
    assert [ast.unparse(n) for n in transaction.body] == [
        "await db.run_sync(lambda sync: portal.close_session(sync, raw))", "await db.commit()"]
    assert len(transaction.handlers) == 1
    handler = transaction.handlers[0]
    assert ast.unparse(handler.type) == "BaseException"
    assert [ast.unparse(n) for n in handler.body] == ["await db.rollback()", "raise"]
    assert [ast.unparse(n) for n in node.body[4:]] == ["response = Response(status_code=204)",
        "response.delete_cookie(portal.COOKIE, secure=True, httponly=True, samesite='strict', path=portal.PREFIX)", "return response"]
    for forbidden in ("require_core_user", "live_session", "live_grant", "get_verified_partner_token", "admin"):
        assert not calls(node, forbidden)


def test_logout_clean_admission_precedes_any_attribute_sql_or_flush():
    node = definition(SERVICE, "close_session")
    first = node.body[0]
    assert isinstance(first, ast.If) and ast.unparse(first.test) == "db.new or db.dirty or db.deleted"
    assert calls(first, "ScopedLockError") and isinstance(first.body[0], ast.Raise)
    assert ast.unparse(node.body[1].test) == "not raw"
    context = node.body[2]
    assert isinstance(context, ast.With) and ast.unparse(context.items[0].context_expr) == "db.no_autoflush"
    assert not calls(first, "fresh") and not calls(first, "flush")
    assert not calls(node, "expire") and not calls(node, "expire_all")


def test_logout_full_original_composition_precedes_all_mutation():
    node = definition(SERVICE, "close_session")
    prepare, = calls(node, "_prepare_partner_write")
    assert [ast.unparse(a) for a in prepare.args] == ["db"]
    assert {k.arg: ast.unparse(k.value) for k in prepare.keywords} == {"token_id": "token_id", "mutation": "'revoke'"}
    assignments = [n for n in body_nodes(node) if isinstance(n, ast.Assign)]
    frozen = next(n for n in assignments if ast.unparse(n) == "token_id = candidate.token_id")
    assert frozen.lineno < prepare.lineno
    dirty = next(n for n in assignments if ast.unparse(n) == "row.revoked = True")
    assert prepare.lineno < dirty.lineno
    assert all(n.lineno > prepare.lineno for n in calls(node, "flush") + calls(node, "revoke_token"))
    for forbidden in ("acquire_scoped_locks", "LockPlan", "begin_nested", "commit", "live_session", "live_grant", "verify_access", "admin"):
        assert not calls(node, forbidden)
    # In the exact protocol=None/native=None/actor=None call, the composer's
    # sole InvalidClientError source is empty requests, before acquisition.
    composer = definition(IDENTITY, "_prepare_partner_write")
    failures = [n for n in body_nodes(composer) if isinstance(n, ast.Raise) and calls(n, "InvalidClientError")]
    assert len(failures) == 1
    gate = next(n for n in body_nodes(composer) if isinstance(n, ast.If) and failures[0] in n.body)
    assert ast.unparse(gate.test) == "not requests"
    assert failures[0].lineno < calls(composer, "acquire_scoped_locks")[0].lineno
    scoped_try = next(n for n in body_nodes(node) if isinstance(n, ast.Try))
    assert len(scoped_try.body) == 1 and calls(scoped_try.body[0], "_prepare_partner_write")
    assert ast.unparse(scoped_try.handlers[0].type) == "InvalidClientError"
    assert calls(scoped_try.handlers[0], "_writer_drift")
    assert not calls(scoped_try.handlers[0], "revoke_token") and not calls(scoped_try.handlers[0], "flush")


def test_logout_scoped_docs_row_follows_family_and_token():
    node = definition(SERVICE, "close_session")
    prepare, = calls(node, "_prepare_partner_write")
    lock, = calls(node, "with_for_update")
    assert prepare.lineno < lock.lineno
    row = next(n for n in body_nodes(node) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "row" for t in n.targets))
    statement = ast.unparse(row)
    assert "DocsPortalSession.cookie_hash == cookie_hash" in statement
    assert "DocsPortalSession.token_id == token_id" in statement and "populate_existing=True" in statement
    module = tree(IDENTITY)
    order = next(n for n in module.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ROW_ORDER" for t in n.targets))
    names = [n.id for n in order.value.elts]
    assert names.index("PartnerTokenFamily") < names.index("PartnerToken")
    assert 'mutation in {\'token-refresh\', \'revoke\'}' in text(IDENTITY, "_prepare_partner_write")
    service = ast.unparse(node)
    assert "original_token.pointers" in service and "original_family.pointers" in service
    assert "spec.identity == (token_id,)" in service and "spec.identity == (family_id,)" in service
    assert "token.family_id != family_id" in service
    # Producer's Token->Docs order stays visible; downstream Family accesses
    # are MVCC. This is not a runtime proof of all interleavings/triggers.
    producer = definition(SERVICE, "create_session")
    assert calls(producer, "with_for_update")[0].lineno < calls(producer, "execute")[0].lineno < calls(producer, "flush")[0].lineno < calls(producer, "live_session")[0].lineno
    for path, name in ((SERVICE, "live_session"), (SERVICE, "client_config"), (IDENTITY, "live_grant"), (IDENTITY, "resource_scopes")):
        for forbidden in ("with_for_update", "acquire_scoped_locks", "flush", "pairwise_subject"):
            assert not calls(definition(path, name), forbidden)


def test_logout_callback_requires_actual_writer_and_finishes_checked():
    node = definition(SERVICE, "close_session")
    server, = calls(node, "PartnerAuthorizationServer")
    assert [ast.unparse(a) for a in server.args] == ["db", "writer"]
    callback, = calls(node, "revoke_token")
    flush, = calls(node, "flush")
    dirty = next(n for n in body_nodes(node) if isinstance(n, ast.Assign) and ast.unparse(n) == "row.revoked = True")
    checkpoints = calls(node, "checkpoint")
    assert any(c.lineno < callback.lineno for c in checkpoints)
    assert callback.lineno < dirty.lineno < flush.lineno < checkpoints[-1].lineno
    callback_body = text(IDENTITY, "revoke_token", "RevokeEndpoint")
    assert callback_body.index("self.server.checkpoint()") < callback_body.index("self.server.family.revoked = True") < callback_body.index("self.server.db.flush()")
    missing = next(n for n in body_nodes(node) if isinstance(n, ast.If) and ast.unparse(n.test) == "row is None")
    assert calls(missing, "_writer_drift") and isinstance(missing.body[-1], ast.Return)
    assert not calls(missing, "revoke_token") and not calls(missing, "flush")


def test_logout_preserves_existing17_and_canonical12():
    for path, expected in PROTECTED_BYTES.items():
        if path in INTEGRATED_BYTE_OVERLAY:
            change = INTEGRATED_BYTE_OVERLAY[path]
            assert expected == change["baseline"], path
            expected = change["reviewed"]
        if path in UUID_MODEL_OVERLAY:
            change = UUID_MODEL_OVERLAY[path]
            assert expected == change["baseline"], path
            expected = change["reviewed"]
        if path == "app/services/partner_identity.py":
            assert expected == ACCEPTED_CREATE_EXTENSION["baseline_file"]
            expected = ACCEPTED_CREATE_EXTENSION["extended_file"]
            assert expected == ACCEPTED_G_ORG_ORDER_EXTENSION["baseline_file"]
            expected = ACCEPTED_G_ORG_ORDER_EXTENSION["extended_file"]
        actual = (activation_baseline_digest(ROOT / path) if path in ACTIVATION_RAW_OVERLAY
                  else hashlib.sha256((ROOT / path).read_bytes()).hexdigest())
        assert actual == expected, path
    for path, expected in UUID_SUPPORT_BYTES.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    assert set(UUID_MODEL_OVERLAY) == {"app/models.py", "app/models_partner.py", "app/models_docs_portal.py"}
    assert len(PROTECTED_BYTES) == 19
    assert set(INTEGRATED_BYTE_OVERLAY) == {"app/routers/partner_admin_router.py", "app/services/partner_identity.py", "tests/test_partner_writer_scoped_locks_pg.py"}
    for branch, path, name, expected in PROTECTED_17:
        assert digest_node(definition(ROOT / path, name)) == expected, branch
    assert len(PROTECTED_17) == 17 and len(CANONICAL_12) == 12
    for name, expected in CANONICAL_12.items():
        current = definition(IDENTITY, name)
        if name == "eligible_scopes":
            current = baseline_create_policy_projection(current)
        assert digest_node(current) == expected, name


def test_logout_adds_no_runner_config_fixture_or_authority_surface():
    node = definition(SERVICE, "close_session")
    for forbidden in ("get_current_user", "decode_token", "native_user_from_claims", "verify_locked_partner_access",
                      "live_grant", "admin", "begin_nested", "acquire_scoped_locks", "LockPlan", "VerifiedPartnerToken"):
        assert not calls(node, forbidden)
    # Protected concrete inputs carry the meaningful no-runner/no-fixture-change
    # assertion; the exact Git diff is separately checked by author/reviewer.
    for path in ("tests/conftest.py", "tests/partner_test_safety.py", "tests/partner_main_composition_approved.py"):
        assert path in PROTECTED_BYTES
    service = ast.unparse(node)
    assert "request.headers" not in service and "request.query_params" not in service


def test_accepted_org_order_extension_is_exact_and_preserves_scope_projection():
    order = ACCEPTED_G_ORG_ORDER_EXTENSION
    assert order["ratification"] == "msg_b07b4203c2cc"
    assert order["source_parent"] == "297f7b4a726b917530e6ba54ff71a7b6c2c33e38"
    assert order["baseline_file"] == ACCEPTED_CREATE_EXTENSION["extended_file"]
    assert order["extended_file"] != order["baseline_file"]
    assert activation_baseline_digest(IDENTITY) == order["extended_file"]
    authority = ROOT / "app/services/partner_contract_authority.py"
    assert accepted_http_authority_baseline_digest(authority) == order["authority_extended_file"]
    composer = definition(IDENTITY, "_prepare_partner_write")
    boundary, = (n for n in ast.walk(composer) if isinstance(n, ast.If)
        and ast.unparse(n.test) == "create_writer is not None and stage_index == 0")
    assert [ast.unparse(n) for n in boundary.body] == ["contract_profile.lock_parents()"]
    stage_loop, = (n for n in ast.walk(composer) if isinstance(n, ast.For)
        and ast.unparse(n.target) == "(stage_index, stage)")
    assert boundary in stage_loop.body and isinstance(stage_loop.body[0], ast.For)
    prefix, = (n for n in ast.walk(composer) if isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "before_member")
    assert tuple(n.id for n in prefix.value.elts) == order["prefix"]
    operation = next(n for n in tree(authority).body if isinstance(n, ast.ClassDef) and n.name == "CreateOperation")
    parents, = (n for n in operation.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "parent_models")
    assert tuple(n.id for n in parents.value.elts) == order["parents"]
    assert digest_node(baseline_create_policy_projection(definition(IDENTITY, "eligible_scopes"))) == CANONICAL_12["eligible_scopes"]
    assert len(PROTECTED_BYTES) == 19 and len(PROTECTED_17) == 17 and len(CANONICAL_12) == 12


def accepted_http_authority_baseline_digest(path):
    """Exact explicit overlay plus full inverse AST projection, no skip/repin."""
    extension = ACCEPTED_HTTP_CREATE_EXTENSION
    assert extension["authority_baseline_file"] == ACCEPTED_G_ORG_ORDER_EXTENSION["authority_extended_file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == extension["authority_extended_file"]
    projected = tree(path)
    helper, = (n for n in projected.body if isinstance(n, ast.FunctionDef) and n.name == "_require_coarse_create")
    operation, = (n for n in projected.body if isinstance(n, ast.ClassDef) and n.name == "CreateOperation")
    policy, = (n for n in operation.body if isinstance(n, ast.FunctionDef) and n.name == "policy")
    assert ast.unparse(policy.body[0]) == "refs, types = _require_coarse_create(db, current, self.expected_profile)"
    assert ast.unparse(helper.body[-1]) == "return (refs, types)"

    class RestoreProfile(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == "expected_profile":
                return ast.copy_location(ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
                    attr="expected_profile", ctx=node.ctx), node)
            return node

    expanded = RestoreProfile().visit(ast.Module(body=deepcopy(helper.body[:-1]), type_ignores=[])).body
    policy.body = expanded + policy.body[1:]
    added = {"_require_coarse_create", "_load_coarse_create", "require_coarse_create"}
    assert {n.name for n in projected.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in added} == added
    projected.body = [n for n in projected.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name not in added]
    # The complete original module is restored, including freeze/locks/checkpoint/
    # SQL stamp/last-wait logic. A second allow policy cannot hide in this overlay.
    assert digest_node(projected) == extension["authority_baseline_ast"]
    return extension["authority_baseline_file"]


def test_explicit_http_extension_keeps_original_gorg_and_full_issuer_semantics():
    extension = ACCEPTED_HTTP_CREATE_EXTENSION
    assert extension["ratification"] == ("msg_dc2f907bf07e", "msg_85a4864d991c")
    assert extension["operation"] == ("POST", "/api/v1/contracts", "createContract")
    assert extension["source_base"] == "cdb65361f3207f82283c88da8b431625a5b1804c"
    authority = ROOT / "app/services/partner_contract_authority.py"
    assert accepted_http_authority_baseline_digest(authority) == ACCEPTED_G_ORG_ORDER_EXTENSION["authority_extended_file"]
    loader = definition(authority, "_load_coarse_create")
    forbidden = {"add", "add_all", "flush", "commit", "rollback", "begin", "begin_nested", "with_for_update", "acquire_scoped_locks"}
    assert not any(calls(loader, name) for name in forbidden)
    assert len(PROTECTED_BYTES) == 19 and len(PROTECTED_17) == 17 and len(CANONICAL_12) == 12


# Separate narrow native-admin overlay. Historical literals above remain intact.
ACTIVATION_RAW_OVERLAY = {
    "app/services/partner_identity.py": {
        "baseline": "ad2408f8e081a4088668d3f1c45c12be06bb293a43ca48e333248fa90c6f688a",
        "baseline_ast": "85ef374747e6ee54aa33995e1d3802aab8524c263efa033495abd724c0eefb57",
        "extended": "0968c41deac1955095c9a80ba4542d0ccd074f68699c29c788cbfab11772ac90",
    },
    "app/routers/partner_admin_router.py": {
        "baseline": "1d097bfca261e25dd6a482cd2b041fde4f6ef593ef29252c55335a5e15ca97db",
        "baseline_ast": "5690108145cb66ccb5ea1b31ce2dc51b178ed7b076b5a47942c1b5b52fcc355b",
        "extended": "8d7e9324e1a82a716cb96632f389d2ebedd40dfe4b7f798b4b81d8437afb2494",
    },
}
ACTIVATION_SOURCE = {
    "base": "4a4ba3bc041b69ccb4064a7865873eadd6f0f00f",
    "codegate": "msg_4b02011dc305",
    "purpose": "contract-profile-activation",
    "service_sha": "6b97c9e6c5420af95587b85947c26295b95d82941ada2bc1c6f5912e648ad9a5",
    "profile_sha": "6fdc93816c6ba7af22b97dc6c1e8e1bc91f1563cec1c0672e82e17a11c23abef",
    "schema_baseline_ast": "ad406ab6bb3ac94502a9680402b60659b8e3cfa7928850b9a4b0aede4291323a",
    "schema_sha": "2f9c10a92d960b25ff3bbd74a4990e583cadfaba118570236b325baf8ab02580",
}


def activation_baseline_digest(path):
    """Restore the WHOLE previous module, not just selected old functions."""
    relative = str(path.relative_to(ROOT))
    overlay = ACTIVATION_RAW_OVERLAY[relative]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == overlay["extended"]
    projected = tree(path)
    if relative == "app/services/partner_identity.py":
        composer, = (n for n in projected.body if isinstance(n, ast.FunctionDef)
                     and n.name == "_prepare_partner_write")
        removed = {"if": 0, "assign": 0, "purpose": 0, "writer": 0}
        class RestoreActivation(ast.NodeTransformer):
            def visit_If(self, node):
                spelling = ast.unparse(node.test)
                if spelling in {"activation_purpose", "activation_writer is not None",
                                "activation_writer is not None and stage_index == 0"}:
                    removed["if"] += 1
                    return [self.visit(n) for n in node.orelse]
                return self.generic_visit(node)
            def visit_Assign(self, node):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {
                        "activation_purpose", "activation_writer"}:
                    removed["assign"] += 1
                    return None
                return self.generic_visit(node)
            def visit_Set(self, node):
                matches = [n for n in node.elts if isinstance(n, ast.Constant)
                           and n.value == "contract-profile-activation"]
                removed["purpose"] += len(matches)
                node.elts = [n for n in node.elts if n not in matches]
                return self.generic_visit(node)
            def visit_BoolOp(self, node):
                if ast.unparse(node) == "activation_writer or create_writer or _PartnerWrite(db, cap, ordered, native, actor, admin_company, ca_id, installation_id, request_deadline)":
                    removed["writer"] += 1
                    node.values = node.values[1:]
                return self.generic_visit(node)
        RestoreActivation().visit(composer)
        assert removed == {"if": 8, "assign": 2, "purpose": 1, "writer": 1}
    else:
        additions = []
        for node in projected.body:
            if isinstance(node, ast.ImportFrom) and (
                    node.module == "app.services.partner_contract_activation"
                    or (node.module == "app.schemas_partner" and [n.name for n in node.names] == ["ActivateContractCreateProfile"])):
                additions.append(node)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "activate_contract_create_profile":
                additions.append(node)
        assert len(additions) == 3
        projected.body = [n for n in projected.body if n not in additions]
    assert digest_node(projected) == overlay["baseline_ast"]
    return overlay["baseline"]


def test_activation_explicit_overlay_preserves_whole_identity_routes_profile_and_schema():
    for path in ACTIVATION_RAW_OVERLAY:
        activation_baseline_digest(ROOT / path)
    profile = ROOT / "app/services/partner_contract_profiles.py"
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == ACTIVATION_SOURCE["profile_sha"]
    service = ROOT / "app/services/partner_contract_activation.py"
    assert hashlib.sha256(service.read_bytes()).hexdigest() == ACTIVATION_SOURCE["service_sha"]
    schema = ROOT / "app/schemas_partner.py"
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == ACTIVATION_SOURCE["schema_sha"]
    projected = tree(schema)
    addition, = (n for n in projected.body if isinstance(n, ast.ClassDef) and n.name == "ActivateContractCreateProfile")
    projected.body.remove(addition)
    assert digest_node(projected) == ACTIVATION_SOURCE["schema_baseline_ast"]
    assert len(PROTECTED_BYTES) == 19 and len(PROTECTED_17) == 17 and len(CANONICAL_12) == 12
