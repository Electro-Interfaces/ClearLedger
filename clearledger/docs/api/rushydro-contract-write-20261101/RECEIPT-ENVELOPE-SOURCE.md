# Receipt envelope — E1a SOURCE ONLY

Owner: `contract_cycle_receipt_body.py`; base `6437eac44231102c8be1692ccda283a4ce2afb8b`.
Root decisions: `msg_e9fd6edb3c35`, `msg_c4b6a52e4c86`; placement GO
`msg_c26ea4c28ecf`. This adds pure grammar, without connecting runtime routes,
services, schema, writers or scope registration. Existing DTO50 is unchanged.

## ABI

Stored object has exactly `formatVersion`, `authoritySnapshot`, `result`.
Operation is an explicit keyword argument from the future receipt owner:
`v2.contract.create` or `v2.document.draft.create`; never another stored field.

- `parse_birth_envelope(value, *, operation) -> BirthReceiptEnvelopeV1` accepts
  a Python JSON object or existing envelope, validating complete nested state.
- `serialize_birth_envelope(value, *, operation) -> str` revalidates then emits
  UTF-8 compatible JSON text. It does not take raw JSON text as input.
- `project_birth_result(value, *, operation) -> dict` revalidates the complete
  envelope before returning only the selected typed result's JSON object.
- Direct `BirthReceiptEnvelopeV1.model_validate` requires
  `context={"operation": <one of the two strings>}`. Its direct Pydantic dump
  methods are ordinary model methods, not validating public helper boundaries.

`ContractBirthResult` contains only UUID `resourceId` and `editVersion`.
`DocumentBirthResult` is TARGET DocState, including explicit nullable
registration fields and 0..200 eligible version descriptions. Neither stores
`replayed`; the future command adapter computes that value. No raw fallback,
authority snapshot, credential, private path or storage ID is projected.

Snapshot contains profile/principal `{id,generation}` and 1..100 bindings.
Each binding contains its own `{id,generation}` birthPolicy, exact context and
closed unique actions. Site context has Site UUID, organization UUID, positive
int32 generation. Location has an opaque ObjectId and organization UUID, with
no location generation. Profile/principal/policy generations are positive
signed int64. Boolean and coercible numbers are rejected.

One Site or 1..100 locations; same organization, no duplicate policy or context,
no mixed variants. Document requires exactly one binding matching its result
context and organization. Internal bindings sort by `(context.kind, exact
context ID Unicode codepoints, canonical policy UUID text)`; actions sort by
Unicode codepoints after duplicate detection. ObjectIds preserve spaces, case,
and UUID-looking text. This never changes original request/hash ordering.
SUCCESS actions are nonempty: contract exactly `["contract.read"]`; document a
nonempty subset of the ten closed actions, without automatically adding read.
Root clarification: `msg_8f2b6217ac30` relayed through coordinator's ask reply.

The module validates shape, not whether every original requested context is
present: comparison to original coverage, receipt columns, current issuer,
grant, membership, SQL, ACL and authority remains E1/A1 work. No permission
boolean, caller-supplied approval, capability or eligibility inference exists.
Registration/status/file business relations absent from TARGET are not invented.

## Revalidation and size limits

Every model uses `revalidate_instances="always"`; its before-validator reads raw
`__dict__` plus retained extras, leaving nested models for their own validators.
It never passes existing state through a JSON serializer before validation.
Thus retained malformed `model_construct`, copied or mutated nested values
cannot be repaired by a serializer. Required missing fields and retained extra
fields are rejected; fields already discarded by Pydantic `model_construct`
cannot be recovered. This is typed-data validation, not a tamper-proof object or
an authority token. Direct Python object mutation remains possible; callers
must use the revalidating helpers at each external boundary.

The authoritative whole stored-envelope bound is unchanged frozen 0005's
`octet_length(result::text) <= 131072` JSONB predicate. Compact Python JSON byte
counts are not PostgreSQL JSONB text byte counts. This module makes no byte
admission claim: actual SQL predicate proof and rollback behavior are PENDING
Root execution. It performs no SQL calls, persistence or immutability proof.
DocState permits 200 versions; binding vector permits 100 locations. Other
field limits follow TARGET and Root's explicit grammar.

## Root-only test admission

AUTHOR: runtime/import/collection/tests NOTRUN. Only stdlib source AST,
`compile` without executing its returned code, hashes and Git diff checks are
allowed during authorship. Root executes the original files with pinned real
Pydantic, independently of new ORM models or application startup.

Before collecting `test_contract_cycle_receipt_body_v2.py`, Root installs an
external module named `receipt_envelope_source_admission_v1` in `sys.modules`.
It supplies `require_running_approval()` (no arguments; raises if admission is
absent) and `receipt_body` (the actual original module object). Test source
checks/calls this guard before importing pytest/Pydantic or accessing the module.
The test file supplies no approval module, fixture provider, environment setup,
database setup or runner. Root must use `--noconftest` and its offline admission.

For standalone loading, Root may create an inert synthetic package and load
original `contract_cycle_dto.py` as `<package>.contract_cycle_dto`, then original
receipt source as `<package>.contract_cycle_receipt_body`, avoiding the real
`product_api/__init__.py`. No package/app startup should be imported. Relative
imports reuse only original `UUIDV2`, `ObjectIdV2`, `VersionV2`, `DateV2` aliases.
Test inventory is the literal `PRIMARY_CASES`; each entry selects one finite
primary test, with bounded subcases. No claim of E1/A1, native SQL acceptance,
80 native cases, schema8 acceptance, deployment or runtime readiness is made.
