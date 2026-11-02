# Document Case catalog protocol

Status: SOURCE implementation; acceptance definitions AUTHORED / NOTRUN,
including collection. Runtime behavior has not been demonstrated by this change.

`app.services.doc_case_locks.acquire_case_catalog(db, cids, mode)` accepts a
normal caller-owned `AsyncSession`, a complete company set and explicit `S` or
`X`. It uses only the existing two-integer PostgreSQL transaction advisory key
`(435223, company_id.int % 2**31)`. Physical keys are deduplicated and acquired
in ascending order; UUID order is not physical key order. A collision deliberately
serializes different companies on the legacy key. Returning does not release a
lock: PostgreSQL retains it until the owning transaction completes.

Readers acquire S before any DocCard row lock. Registration always participates,
even when its current Case is null: the Kind default can change. Assignment and
bulk `assign_case` participate; other bulk actions retain their original path.
Within this barrier the existing DocCard → Case row order stays intact, including
the sorted bulk DocCard lock and native numbering/token/retention completion.

All catalog/default writers acquire X before Kind/Case reads, predicates and
setters: Kind create/update (including clearing the default), starter and contract
Kind insertion (including null defaults), Case create/close/rollover, and seed.
`_lock_case_catalog` keeps its signature as the exclusive compatibility delegate.
`_default_case_id` also takes X for null/empty input; its native Case lookup and
closed-Case errors are preserved. No administrator requirement is added to the
idempotent ordinary-member contract-kind GET.

Callers that need X choose X initially. S→X upgrade after acquiring rows and
incremental multi-company key extension after acquiring rows are unsupported
compositions. The helper does not silently strengthen S, invent a namespace,
authorize a caller, start/commit/roll back a root or implement domain checks.
Repeated same-mode acquisition, and S while already owning X, are compatible.
The caller remains responsible for complete key discovery and transaction scope.

Seed preserves the first Company SELECT and its ORM autoflush before the first
catalog lock. Pending Role/User writes from the unchanged startup root therefore
finish first. The complete deduplicated physical company key set is acquired X
before any Case read or subsequent flush/default assignment, independent of query
row order. Seed keeps its caller and startup atomicity. New Kinds matching a
closed Case are still created, with null defaults; existing null-default Kinds
are not backfilled to a closed Case. Existing nonnull defaults remain unchanged,
including historical inconsistencies. Open matches retain normal backfill.

The earlier catalog wait is an intentional timing change. Existing ACL and error
precedence after admission, response/commit behavior, registration numbering,
token, Case validations and audit keyword remain owned by their original code.
This prerequisite does not implement the complete registration ownership barrier
or a policy recheck after counter UPSERT/last wait. Retained pending ORM state,
last-wait composition and full registration acceptance remain open. The five
inherited canonical User references and model mappings are unchanged.

The three new test modules define native-handler/seed acceptance using actual
AsyncSessions, real transaction completion, synthetic data, SQL event observation,
`pg_blocking_pids` and `pg_locks`, with bounded waits. Only notification dispatch
may be suppressed to avoid external delivery. They include both S/X orders,
physical collision/order/lifetime, default-set/clear versus close, null-default
writers versus seed's no-Kinds predicate, DocCard-before-Case order, rollover,
seed pending-role autoflush and closed-Case behavior, native errors, manual/auto
numbering, repeat conflict and rollback. The JSON inventory is a static source
enumeration; it is neither pytest collection nor a successful test count.

Before importing these modules, the runtime owner must independently isolate
ancestor conftest, prepare the complete native schema/bootstrap/codecs and
constraints in a disposable database, and provide cleanup. Module guards only
check the supplied composition declarations; they cannot provide that isolation
or prove schema fidelity. Ordinary repository pytest can import a destructive
ancestor conftest before a module guard. No runner or conftest change is included.

Case patch/delete roots were absent in the bounded source inventory; this does
not prove runtime absence. Dynamic/external writers remain unknown. Archive
Case reads and work execution are outside the writer cut. Full Docs, organization
deletion, complete registration, last-wait acceptance, CI and release readiness
remain OPEN. The JSON retains the full original 20 programme sections and 11
cross-cutting requirements verbatim, with all 31 explicitly OPEN.
