# Site authority, P1c Source, 2026-11-02

Source base `0db9a97e2f6b86f2307cfa5abefb1a32982d37ec`.
Action map fixed before authoring revision0006. All paths below are relative to
`clearledger/server/app/`; line numbers refer to that base.

| Consumer file:symbol:line | Exact action key |
|---|---|
| services/ezs_sites.py:site_detail:1509 | `site.read` |
| services/ezs_project.py:link_contract:1760; link_location:1790 | `site.link_edit` |
| routers/references_router.py:create_contract:952 | `contract.create` |
| routers/docs_router.py:create_doc:2221 | `document.create` |
| services/doc_access.py:_can_doc:133, read branch:162 | `document.read` |
| services/doc_access.py:_can_doc:133, edit branch:195 | `document.edit` |
| services/doc_access.py:authorize_docs_file_download:528 | `document.download` |
| routers/docs_router.py:print_doc:3482 | `document.print` |
| routers/docs_router.py:export_doc:4563 | `document.export` |
| routers/docs_router.py:send_doc:3394 | `document.send` |
| services/doc_access.py:_can_doc:133, approve branch:199 | `document.approve` |
| services/doc_access.py:_can_doc:133, sign branch:217 | `document.sign` |
| services/doc_access.py:_can_doc:133, archive branch:247 | `document.archive` |
| services/doc_access.py:_can_manage_doc_access:268 | `document.manage_acl` |

These are native permission names prefixed by resource, not public OAuth scopes.
Unknown actions deny; no implication from read to edit/content/egress. The common
predicate is an additional boundary; DocGrant, confidentiality, retention,
approval and file/version rules remain the responsibility of their native owner.
Consumers above are evidence, not newly integrated endpoints: those integrations
and all Site writers remain OFF in this packet.

Current membership is `UserCompany(user_id,company_id)` (`models.py:207`);
`own_organization_id` is Organization, whereas `organization_id` is Counterparty.
Neither admin/superadmin nor author/land contract/receipt supplies Site authority.
Context must explicitly match the member's non-null own organization. Current
SQL scalar reads avoid cached membership/assignment/context values.

`EzsSite.location_id` (`models.py:7061`, `ezs_project.py:link_location:1790`)
is the exact String40 station pointer, distinct from Site UUID. Project pointers
also exist (`EzsProject`, `models.py:7126`); contradictory or multiple distinct
station links deny. No guessed ID or synthetic station is used. A bound Site
requires that station in the current object ceiling; EMPTY remains empty.

Migration0006 precedes this binary: startup and canonical identity reject prefix5
before resource ORM queries. New tables never enter legacy create_all, under any
namespace/flag. DDL is explicit, with no authority backfill or auto approval.
Frozen0001–0005 payloads/manifest entries are unchanged; their own verifiers still
run. Revision0006 separately verifies the additive native tenant keys, new Site
tables and extended partner checks; old v1 profiles/hash/CREATE stay unchanged.
Rollback disables writers and retains compatible readers/schema; no down-DDL.

Native test protocol: an external admission controller supplies `site_authority_pg`
with an already admitted isolated PG16 connection, an AsyncSession on that same
database, real canonical signed partner bearer issuance, native authenticated
User, and synthetic native prerequisites. It owns fresh/upgrade baselines,
transaction rollback and cleanup. The tests define finite cases and direct SQL
assertions; no engine/provider/bootstrap fixture, mocks or authority replacement.
Runtime, imports, metadata, PostgreSQL, pytest/collection and HTTP are NOTRUN here.

Call graph is one-way: startup database → runner.require_site_prefix → frozen
catalogues + catalogue0006; canonical identity → site_authority.require_schema →
that same schema-only runner; partner_site_allowed → canonical verify_access →
schema-only helper, then the live action predicate. The schema helper never calls
identity or the Site predicate. It borrows the caller connection/transaction.

Finite Source tests cover full-native3/five→six/repeat, four catalogue drifts, partial
unrecorded6, prefix5-before-identity, foreign namespace, default deny, tenant Site/
org/membership FK failures, generation/action checks, fourteen exact actions and
current revoke, five membership/org/role cases, spoof/session revoke, five strict
Site-vs-Location cases including conflicting project links, fresh partner Site SET
and native action intersection, ALL/one-ID refusal and original five resource
kinds across ALL/EMPTY/SET. Their external fixture protocol is the module docstring
in `server/tests/test_site_authority_native.py`; no execution/collection occurred.

Fixture ABI uses two actual frozen Sources: predecessor
`0db9a97e2f6b86f2307cfa5abefb1a32982d37ec` builds native prefix3/5, then its
pools close before the candidate Source imports/queries and explicit0006. Fresh6
is native3 → explicit4+5+6; upgrade is native5 → explicit6. Candidate metadata
cannot manufacture an old prefix by hiding/dropping future columns. Root supplied
historical prefix5 counts 343 registered/349 physical, and expects candidate6
345/351; these are protocol expectations, not author runtime measurements.
Minimal prefix0/3 exists only for the separate oldtarget3 compatibility cases.
The externally injected module is `rushydro_site_authority_root_admission`;
`require_running_approval()` precedes app/SQLAlchemy imports. Ordinary server
conftest must be excluded by that external controller. Token issuance uses the
same actual AsyncSession/transaction as the uncommitted synthetic seed.
