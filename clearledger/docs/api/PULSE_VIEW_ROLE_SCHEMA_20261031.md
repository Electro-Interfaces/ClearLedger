# Владелец схемы назначения витрин ролям, M08/M16-C2

**ROOT принял ограниченный пакет** (`msg_80dc21a1034f`). База реализации `875929b3885d98ace8e370a72d62a825bf76960b`; первая source-стадия была от `e9d793d600974fe3142abade67ad8f5ff6980de2`. Worker выполнял только Git/read/AST/compile/hash; SQL, imports и тесты исполнял ROOT.

## Результат

`PulseViewRoleGrant` теперь отражает подтверждённый контракт: две UUID NOT NULL без defaults, PK(view_id,role_id), два FK CASCADE к PulseView и CompanyRole, только PK btree без дополнительного role index. Сохранены owner-only ACL, выключенный RLS и штатные FK triggers. Два простых FK не обеспечивают равенство компаний: native membership/product/company filters остаются ACL.

В Core DDL принадлежит только existing versioned framework revision `0003_pulse_view_role_grants`, parent0002; ORM mapping исключён из legacy metadata DDL. Каталог проверяется до Core startup DDL/seed/jobs. Исторический exact live shape можно использовать до отдельного adopted0003: runtime guard проверяет каталог, не stamp и не журнал. Для standalone public сохранён явный legacy ORM fresh путь того же контракта с проверкой до bootstrap commit. Missing core при configured core/public не разрешается молча в canonical public; неоднозначный public path отвергается. Truelegacy $user/public и explicitpublic сохранены.

`/api/ready` вызывает bounded3s catalogue-only guard на borrowed connection: missing/drift даёт503. Guard не создаёт соединение, не меняет transaction/search_path, не выполняет DDL/commit/rollback/lock и не читает business rows. Framework остался единственным explicit migration runner; frozen0001/0002 payloads и существующая default0001 check/apply семантика сохранены.

**Это общий Core-код с безусловным требованием каталога при startup/readiness.** Из live-пространств наблюдался только каталог РусГидро; другие пространства не измерены, не валидированы и не активированы. Нельзя считать этот пакет разрешением его выпуска во все стеки.

## Фактическое основание схемы

Первый ROOT read-only snapshot `2026-10-31T01:23:39.830013+00:00` подтвердил core relation, отсутствие public counterpart, две колонки/PK/FKs/единственный PK index и explicit owner-only ACL, RLS false/no policies. Полный trigger section достиг cap256 и сам по себе был неполным. Отдельный narrow snapshot `2026-10-31T01:29:23.281699+00:00` дал8 internal enabled-O immediate/nondeferrable child/parent FK triggers <cap64, без custom triggers в запрошенном scope; это другой timestamp, не единый snapshot. Business rows не читались.

Первый snapshot SHA256 `4a70f7b90b4a7555525ff9f2334e4dbc1454b1dfa8c81f4297b975f6aee9ffbf`; narrow trigger snapshot `9353d5324028a969dde537438c1eb0aa67b0a52728aa9816f1e8c7b6655c5f8c`. Полные обобщённые contract/hash/provenance — в одноимённом JSON. Raw live CSV, роли, OIDs и container IDs остаются private ROOT artifacts, в Git не копировались. Предыдущий ограниченный DDL search не повторялся и не объявлялся всемирным отсутствием DDL. P8/P9 receipts сохранены.

## Приёмка ROOT: две серии

| Серия | Фактический результат | Время и процесс |
|---|---|---|
| V1, msg_75122d6c59fe | 41 primary PASS,14 fixture FAIL,13 pure subtests PASS | pytest25.44с, outer43.624425892с,exit1/reaped |
| V2, msg_80dc21a1034f | только прежние14 failed IDs:14 PASS,0 FAIL,0 subtests,subtests_ok true | pytest34.65с,outer52.648500619с,exit0/reaped |

Итого проверены **55 разных primary cases в двух сериях**,41 удержанный PASS +14 исправленных;13 прежних subtests удержаны. Это не single55green и не fullCI. После V1 production/schema остались побайтно теми же: поправлены только новые fixture expectations на прежний namespace refusal и fresh Core metadata checkfirst=False после exact emptyCore assertion/ownerlock; reporter отдельно учитывает pinned SubtestReport с exact contexts/counts и отказом при дублях/ошибках. 41 успешный случай не повторялся.

В обеих сериях ROOT независимо подтвердил source-after, inventory77, PGsendmsg16 controls, forbidden0 и штатный DROP только dedicated `api_pulse_view_role_schema_test_20261031`/33546: relations0,clients0,exists0,maxlocks64. Evidence: `.artifacts/root-pulse-role-schema-review-20261031/`. V1 сохранён также в своём ignored `v1/`.

Реальный fixed-ID SQL/HTTP покрывает две компании/роли, duplicate/foreign/invalid/null replacement counts, current membership/role/product revoke, new member с другой primary company, user OR role grant, published/draft/admin rules, native deletion/default modules, PK/NULL/FK rollback, populated adopt без потери строки, drift/missing/history/future/gap/hash и readiness503. Старые HTTP/output assertions сохранены; из P8 fixture удалён только явно одобренный inferred CREATE/DROP/assertNone scaffold. Metadata/typefield alone не объявлены ACL proof.

Отдельный pre-conftest ROOT proof прошёл без app.main: literal10 parent ORM tables + существующая phone function на empty owned Core, затем тот же framework0001 created →0002 adopted с прежним acknowledgement →0003 created + catalogue guard, после чего owned Core удалён. Это **не доказательство успешного полного legacy Core bootstrap**: per-case Core соседствует с public и namespace guard честно отказывает foreign visibility. Полный Core startup/currentCI/live upgrade/live restore остаются вне приёмки.

## Публичные read-only API для C3

- `manifest.load_known_head(root=ROOT) -> Package`: строго allowlisted source head0003 и проверка frozen artifacts.
- `async runner.require_applied_prefix(conn, config, known_head, *, required_revision=ID) -> None`: boundedN+1=4, полный известный applied prefix/checksums и catalogue каждой применённой ревизии. Required0001 не требует неприменённый latest или его parents. Unknown/future/gap/mismatch отвергаются. Ни создания connection, ни BEGIN/SET/lock/write/commit/rollback нет; lifecycle принадлежит caller.

`MigrationError`: code2 — source/head/required-revision integrity; code3 — target/config/identity; code4 — unapplied/history/catalogue mismatch. Native driver exceptions borrowed connection могут распространяться; consumer должен давать безопасную диагностику. C3 получает immutable accepted pin через ROOT; gate file здесь не менялся. Existing managed-budget flagON/default0001/newerhistory refusal остаётся видимым отдельным edge под ROOT/C3, flags не переключались.

## Pins и границы

Final runner `bfb5a258f9f44cedfd82bd4c72c60ea208e28d87564e64f0532ea4cfda059eb5`; app503 `2630f4725d9befcc8061d781f633e1c3fecf0e26d3d49c0316cf29587db2ebde`; tests382 без runner `9157f82a9fca11db0dd516d54d02b03cefaabdb1947cec749aa26b8196879b97`; schema24 `36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165`. Exact argv/env/IDs/limits/full manifests сохранены в своём `.artifacts/pulse-view-role-schema-20261031/implementation-frozen-*.json`; семь strict boundary functions AST идентичны принятому P9 template.

Reverse AST подтверждает все прежние models/main bodies кроме mapping/двух readiness statements, остальные database symbols/legacy DDL tail и old P8 test bodies. Routers/pulse_day/digest/P9, SDK/Contract/frontend/deps/версии не менялись. M08/M16 и вся программа M00–M19+11 продолжаются; deploy/merge/ship/flags не выполнялись. Дальнейшего владельца и выпуск назначает ROOT.
