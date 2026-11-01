"""M15 SOURCE ONLY: authored definitions, NOTRUN including collection.

Only stdlib source inspection. Runtime acceptance belongs to independent ROOT.
No application, ORM, policy, SQL or extracted-AST execution in these guards.
"""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "app/services/partner_contract_activation.py"
I = ROOT / "app/services/partner_identity.py"
MANIFEST = ROOT.parent / "docs/api/PARTNER_CONTRACT_ACTIVATION_BATCHING.json"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _node_hash(node):
    # Independent stdlib serializer with the same empty type_params contract.
    # This guard never executes the inspected source AST.
    def render(value):
        if isinstance(value, ast.AST):
            parts = []
            for field, child in ast.iter_fields(value):
                if field == "type_params" and child == []:
                    continue
                if child is None and getattr(type(value), field, ...) is None:
                    continue
                parts.append(field + "=" + render(child))
            return type(value).__name__ + "(" + ", ".join(parts) + ")"
        if isinstance(value, list):
            return "[" + ", ".join(render(child) for child in value) + "]"
        return repr(value)
    return _hash(render(node).encode())


def _definitions(node, parents=()):
    """Walk all syntax containers, including definitions under if/with/try."""
    for child in ast.iter_child_nodes(node):
        owners = parents
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            owners = (*parents, child.name)
            yield ".".join(owners), child
        yield from _definitions(child, owners)


def _definition(path, qualified):
    matches = [node for name, node in _definitions(ast.parse(path.read_bytes())) if name == qualified]
    assert len(matches) == 1
    return matches[0]


def test_exact_source_two_freeze_and_all_nested_definition_inventory():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["base"] == "b41ba2da0dadaf991df4bdf6e954224752182ca4"
    assert manifest["execution"]["tests"] == "NOTRUN"
    for path in (A, I):
        record = manifest["source"][str(path.relative_to(ROOT))]
        raw = path.read_bytes()
        assert _hash(raw) == record["raw_sha256"]
        actual = [{"name": name, "ast_sha256": _node_hash(node)}
                  for name, node in _definitions(ast.parse(raw))]
        assert actual == record["all_nested_definitions"]


def test_two_passes_remain_separate_around_original_profile_boundary():
    checkpoint = ast.unparse(_definition(I, "_PartnerWrite.checkpoint"))
    assert "type(getattr(self, 'contract_profile', None)) is ActivationOperation" in checkpoint
    assert checkpoint.index("refresh_identity(self.db, self.rows)") < checkpoint.index("profile.recheck(self.db)")
    assert checkpoint.index("profile.recheck(self.db)") < checkpoint.index("self.native(self.db)") < checkpoint.index("admin(self.db, self.actor, self.admin_company)")
    assert "with self.db.no_autoflush:" in checkpoint
    assert "self.request_deadline <= now()" in checkpoint
    scalar = ast.unparse(_definition(A, "ActivationOperation.recheck"))
    assert scalar.index("self.graph.recheck(db)") < scalar.index("_identity_batches(self.ordered)")
    assert "with db.no_autoflush:" in scalar
    assert "_rows(db, _batch_statement(batch, scalar=True))" in scalar
    assert "current != expected" in scalar and "(actual[ident],) != expected" in scalar
    assert scalar.index("_identity_batches(self.ordered)") < scalar.index("self.installation_sets.items()")
    assert "identity._installation_sets(db, iid) != expected" in scalar
    assert "actual != expected" in scalar and "PartnerCredential.client_id == cid" in scalar


def test_no_authority_cache_and_only_closed_homogeneous_groups():
    grouping = ast.unparse(_definition(A, "_identity_batches"))
    assert "spec.model in (Company, User) and spec.pointers == ()" in grouping
    assert "spec.model is ServiceLocation and len(spec.pointers) == 1" in grouping
    assert "key = (spec.model, spec.pointers)" in grouping
    assert "key = (index,)" in grouping
    assert "range(0, len(group), 256)" in grouping
    assert "group[start:start + 256]" in grouping
    batch = ast.unparse(_definition(A, "_batch_statement"))
    assert "model.id.in_(tuple((spec.identity[0] for spec in batch)))" in batch
    assert "model.company_id == batch[0].pointers[0]" in batch
    assert "populate_existing=True" in batch
    for method in ("ActivationOperation.refresh_identity", "ActivationOperation.recheck"):
        node = _definition(A, method)
        # Read-only current passes cannot publish/cache state on self or session.
        for item in ast.walk(node):
            if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                assert not any(isinstance(target, (ast.Attribute, ast.Subscript)) for target in targets)
        spelling = ast.unparse(node)
        assert all(word not in spelling for word in (".info", "registry", "lru_cache", "commit(", "with_for_update"))


def test_every_identity_and_full_scalar_key_rejects_duplicate_unexpected_or_missing_rows():
    keyed = ast.unparse(_definition(A, "_keyed_rows"))
    assert "ident not in expected_ids or ident in actual" in keyed
    assert "set(actual) != expected_ids" in keyed
    refresh = ast.unparse(_definition(A, "ActivationOperation.refresh_identity"))
    assert "db.scalars(spec.statement()).all()" in refresh
    assert "len(rows) != (0 if spec.missing else 1)" in refresh
    assert "len(ids) != len(batch)" in refresh
    assert "expected_ids" in refresh and "type(row) is not batch[0].model" in refresh
    assert "row.company_id != batch[0].pointers[0]" in refresh
    scalar = ast.unparse(_definition(A, "ActivationOperation.recheck"))
    assert "len(self.ordered) != len(self.identity_rows)" in scalar
    assert "len(frozen) != len(self.ordered)" in scalar
    assert "spec.statement().with_only_columns(*spec.model.__table__.c)" in scalar
    assert "model.company_id == self.company_id" in scalar
    assert "deepcopy(tuple((tuple(row) for row in db.execute(statement))))" in ast.unparse(_definition(A, "_rows"))


def test_chunk_tail_proof_does_not_introduce_graph_cap_or_silent_truncation():
    # Integer index proof only; this never invokes the implementation/helper.
    for size in (0, 1, 2, 8, 255, 256, 257, 512, 513, 1025):
        covered = [index for start in range(0, size, 256) for index in range(start, min(start + 256, size))]
        assert covered == list(range(size))
        assert all(min(start + 256, size) - start <= 256 for start in range(0, size, 256))
    scalar = ast.unparse(_definition(A, "ActivationOperation.recheck"))
    assert "range(0, len(parents), 256)" in scalar
    assert "parents[start:start + 256]" in scalar


def test_writes_pending_flags_and_all_physical_lock_methods_remain_exact_base():
    manifest = json.loads(MANIFEST.read_text())
    for qualified in ("ActivationOperation.lock", "ActivationOperation.lock_parents", "ActivationOperation.freeze",
                      "ActivationOperation.discover", "activate_partner_contract_create_profile", "activation_admin_request"):
        node = _definition(A, qualified)
        assert _node_hash(node) == manifest["unchanged_activation_definitions"][qualified]
    checkpoint = _definition(I, "_PartnerWrite.checkpoint")
    branches = [node for node in ast.walk(checkpoint) if isinstance(node, ast.If)
                and ast.unparse(node.test) == "type(getattr(self, 'contract_profile', None)) is ActivationOperation"]
    assert len(branches) == 1
    assert ast.unparse(ast.Module(body=branches[0].orelse, type_ignores=[])) == manifest["original_checkpoint_ORM_loop"]
