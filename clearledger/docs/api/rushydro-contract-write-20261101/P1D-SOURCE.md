# P1d: typed business columns and shared Site document boundary

Source-only test hardening; runtime NOTRUN by this author. Immutable application
and policy Source is `3fce95e716cd6301d51f2526cda075d8ff7a0ca1`, tree
`df8617ea4326958f5b725233d493a883429d3227`. This change owns exactly this document
and `server/tests/test_doc_site_business_native.py`; no application, schema,
controller, helper, SDK, OpenAPI, migration or flag changes are included.
Effective schema6 predecessor remains `46566816f59e0d65f61b5426842d6a496e8fc13c`.
Root reported separate native6 acceptance (47 PASS); this Source author has not
run or independently verified it. Controller7 implementation/execution and its
admission remain separate Root gates, not authorized by this source handoff.
PERSISTENCE-DECISION, ROOT-DECISION and TARGET remain unchanged. Site writers OFF;
this change makes no claim that the full API is ready.

`Contract.validity_kind` preserves NULL/legacy dates; explicit `until` checks
lexical and real calendar dates behind CASE barriers before either date cast.
`OpsContractTerm.site_id` is UUID, with a tenant FK and a separate unique axis;
the original location axis applies where Site is NULL. Unsupported/site-NULL
history remains available to the existing blocking readers.
`DocCard.site_id` requires no ObjectId and an organization in the real Site
context. Context revocation denies access without deleting documents. Core-only
tenant/context FKs and supporting unique belong to explicit7 SQL/catalogue;
global ORM declares nullable fields, safe checks and indexes. Fresh public OFF
keeps its original bootstrap and NULL-Site document branch, creates no Core Site
tables and grants no Site authority.

The common SQL subject predicate is P1c `site_authority._clause`, rereading the
actual user/member/org/context/action and raw ObjectId ceiling. Doc access adds
it before admin/author returns, list/count/limit, files and egress; independent
DocGrant, confidentiality, retention, approval and version rules still apply.
Native entrance authentication and background notice recipient ownership stay
with their existing owners. A detached product User is not native auth proof.
Product Site checks must reverify through the canonical partner issuer on the
actual query Session and intersect its current Site SET and object/document
grants; principal identity must match the original request.

Revision7 is explicit and additive. Frozen1..6 bytes/entries/artifacts stay
unchanged. New binaries require7 before ORM/legacy DDL; create_all cannot repair
an old schema. An old6 binary is not claimed compatible with schema7.

## External native Source fixture ABI (v1)

Only Root runs `tests/test_doc_site_business_native.py`, with `--noconftest`.
Before collection inject `rushydro_doc_site_root_admission` into `sys.modules`;
its `require_running_approval()` must validate the external running admission.
The module guards before any driver/app import. No local approval, environment
selection, providers, fake tokens/facts or mocked policies exist in this Source.

Fixture `doc_site_pg` provides actual PG16 `connection`, admitted migration
`config` and actual `session` (AsyncSession), all on the same disposable target.
`baseline(prefix=3|6, source=BASE)` starts the REAL frozen native process
`0db9a97e2f6b86f2307cfa5abefb1a32982d37ec` for full native3/5. A separate REAL
corrected6 process `46566816f59e0d65f61b5426842d6a496e8fc13c` explicitly applies6 for the
upgrade target; candidate7 is a third process. Fresh means actual native3 then
explicit4+5+6+7, upgrade means actual corrected native6 then explicit7. Never use
candidate/future metadata to construct a predecessor, drop future columns or
rewrite history. Retain original5141 create_all refusal at prefix3 as an actual
observation; it is not a bootstrap builder. Candidate ORM selection follows7.
All real source trees, original create_all observations and actual object counts
are recorded independently by the controller.
`native_bearer(uid,cid)` uses the real native signing/session owner on the
actual fixture Session. `partner_bearer(uid,cid)` uses the real canonical issuer,
returns `(bearer, installation_id)`, with documents ALL, sites EMPTY and objects
ALL. Issuer configuration is externally admitted before app imports; identity
setup uses the fixture transaction. `publish()` commits synthetic preparation
without expiring loaded fixture rows,
so an independent actual request can read it, and leaves `session` usable.
`product_get(bearer,path,after_resolve=None,before_query=None,after_query=None)`
runs the actual registered product ASGI request with the real resolver, including
its separate, closed identity Session, and returns the original response. All
three optional hooks default to `None`; existing callers remain compatible.
The awaited zero-argument `after_resolve()` callback runs exactly once after the
REAL resolver closes its identity Session and before the actual Query owner. It
only coordinates real synthetic-row revocations and replaces no verifier, facts,
token, policy or result.

Root explicitly approved observer C for pending product state (decision relayed
as `msg_4301103a139c`, original `msg_bb39cf1a4540`). A single fixture-local wrapper
retains the original bound `Query.conditions` callable: await
`before_query(actualQuery.db)` exactly once before that original callable; await
the original callable exactly once; then await `after_query(actualQuery.db)`
exactly once on success OR exception, before the original dependency/Session
`finally`. Both callbacks receive the same actual AsyncSession owned by Query.
`before_query` stages actual new/dirty/deleted User or DocCard instances only.
`after_query` only records bounded primitive observations of loaded fields,
histories, InstanceState and Session membership; it issues no SQL, lazy loads,
refresh, flush or mutation. Tests assert 409 and compare these observations after
the response without inspecting a cleaned-up Session. The original result and
exception remain owned by the original callable: preserve the result, re-raise
the original exception, and leave the original dependency cleanup unchanged.
Observer assertion failures must fail the run, never become a successful result.
Do not retain the Session beyond HTTP completion, add production hooks, replace
Query/facts/verifier/policy/results, or decide expected outcomes in the fixture.
This is the external Source ABI contract; the later Root controller implements
and reviews it independently, with no local fixture/provider in this Source.

`upload_path` names a disposable existing synthetic file containing
`b'Site document fixture\n'`; no real storage path or credential is an artifact.
No fixture method decides an expected outcome or substitutes an authority object.

The finite literal `CASES` tuple is the native Source inventory: **111 cases**
through **one parametrized test definition**, with no generated inventory or
future phase counted as an executed case. The original 95 literal cases retain
their order, fixtures and native assertions. U3 strictly strengthens the old
partner listing/revocation assertions: status is mandatory, total and positive
presence precede real revocation, denied Site rows remain absent before limit,
and revoked grants require 401/403. No conditional status-200 bypass remains.

The 16 appended literal cases are:

- Four FILE mid-request cases: `partner_file_doc_set_mid_request`,
  `partner_file_site_set_mid_request`, `partner_file_action_mid_request`,
  `partner_file_grant_mid_request`. Each obtains actual file 200 and exact
  synthetic contents first, then commits the real revocation after identity
  Session closure and before original Query/file delivery; denial exposes no
  synthetic file contents or download disposition. Document/Site/action denial
  in the already-resolved request requires 404; the subsequent new listing
  after documents EMPTY requires resolver 403. Grant denial requires 401/403,
  including listing. Positive first-page order uses actual seeded `created_at,id`
  sorting, with both known documents present on an additional pageSize=2 request.
- Two approved native dirty-field cases: `native_dirty_title_preserved`,
  `native_dirty_username_preserved`. Original native claims/User ownership and
  approved Site/assignment remain in effect. Read/edit policy stays positive;
  pending field/history/dirty state and original stored scalar remain intact.
  The old dirty cases with denied assignments stay separate and unchanged.
- Four uninserted native drafts: `native_pending_site_draft`,
  `native_transient_site_draft`, `native_pending_null_draft`,
  `native_transient_null_draft`. Site drafts default-deny, NULL-Site drafts retain
  legacy read; actual pending/transient states survive without INSERT/flush.
- Six actual Query Session cases: `partner_pending_user`, `partner_dirty_user`,
  `partner_deleted_user`, `partner_pending_card`, `partner_dirty_card`,
  `partner_deleted_card`. A real positive request precedes staging; original
  Query must return 409 while original fields/histories and new/dirty/deleted
  memberships remain exactly as observed before canonical refresh/cleanup.

Source verification uses stdlib AST, literal inventory comparison, code-object
compilation without exec, exact-two diff review and tracked blob comparison only.
No project/test/third-party import, collection, pytest, SQL compilation, PG, app,
Docker, SSH, network, dependency/build/Node or private Root artifacts were used.
Adjacent source read as audit only: `server/app/models.py`,
`server/app/services/doc_access.py`, `server/app/services/doc_site_authority.py`,
`server/app/services/site_authority.py`, `server/app/services/partner_identity.py`,
`server/app/product_api/queries.py`, `server/app/product_api/files.py`,
`server/app/product_api/access.py`.

All 111 runtime outcomes remain **NOTRUN** by this author. Root must separately
implement/review the optional hooks and run the admitted original Source with
`--noconftest`, verify U1 on actual fresh public OFF, U4 on the actual PG catalogue,
and review candidate7 admission/integration. These separate Root checks are not
simulated by Source fixtures and are not included in the 111-case count.
