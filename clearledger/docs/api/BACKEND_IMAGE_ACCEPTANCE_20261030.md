# Локальная контейнерная приёмка backend, 30.10.2026

**ROOT scoped verification complete:370 retained PASS +6 corrective PASS;
main8 — единый8/8PASS. Нового единого376GREEN нет.**
Первоначальный контейнерный full376 завершился370PASS/6harnessFAIL; этот FAIL
сохранён. ROOT разрешил исправить только потерянный seam оснастки и повторить
ровно affected6. Assertions, app/tests/DTO и зависимости не менялись.

## Зафиксированный состав

App source base:`07f12c6575cbb397e9945c7f9efda724445615c2`.
Ветка:`agent/api-container-acceptance-20261030`.
Final harness freeze:`c50acb32b37bc4448d81b9fe13107bdf4c004bdb`;
последующая финализация меняет только этот отчёт.

| Дерево | Файлов | SHA256 |
|---|---:|---|
| app |492|9595a3002cf0c80409a4caf9b1209aa20fb2d1619c25ca0da52867a2c7a8eb54|
| tests |349|1588d43dfb02ca7d5dd6beb700ae53c998bd2dab84b986d716fbaef32354f57f|
| schema_migrations |16|c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e|

Комплект:`server/tools/backend_image_acceptance_20261030/`.
Manifest содержит879 per-file SHA, inventories61/16 и retained wheel hashes.
ROOT передаёт self/other/manifest SHA извне, до сторонних/app imports;
source guard повторяется после тестов. Embedded reciprocal hash cycles нет.

Runtime: **CPython3.13.18/glibc2.41**, clean image-local runtime60+pip1;
acceptance добавляет отдельные16 tools, total77. Host79/new77 environments не
использовались как Docker runtime. Старый system site удалён; app/schema заменены
целиком, без overlay остатков. Actual probes подтвердили source, inventory,
пять default flags OFF, HOME и app from image.

| Immutable image | ID |
|---|---|
| Retained base |812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51|
| Candidate61 |0d58065c8b3ed50db553c12e9bd47aee7f16566e8353e99f636084d24714c38e|
| Acceptance77 |ffe96074307ea9e98f97252b3e7831510560b0096127aaabad72e08ddb64cf25|
| Corrective tools overlay |f26c12771f79a0c1f6852c591988e22534bf932ac4342b8f80c2cab1c6d6519e|

Acceptance наследует candidate prefix; corrective overlay наследует acceptance
и копирует **только owned tools/manifest**, без app/schema/tests/site/pins changes.
Base references — inspected local name:tag@digest, pull=false; TLS/mirror не менялись.

## Фактические результаты ROOT

| Проверка | Результат | Время, s |
|---|---|---:|
| Retained archive load, SHA/layers verified |PASS|22.792|
| Candidate61 build + actual runtime probe |PASS|45.038|
| Acceptance77 build |PASS|8.514|
| Full376 V5 |370PASS/6FAIL,149passed subtests|200.22 pytest /226.2434 outer|
| Main8 V5 |8PASS, no failures/errors/skips|68.27 pytest /93.0779 outer|
| Corrective overlay build |PASS|1.5013|
| Corrective actual77 probe |PASS|20.0223|
| Exact affected6 V6 |6PASS, no failures/errors/skips|18.71 pytest /44.0323 outer|

Full376 сохранил16-file selection: шесть AST-identical library probes из SELF
и370 cases из15 unchanged files. Raw JWT, pypdf/application PDF extraction,
malformed PDF, multipart bytes/limits и dotenv проверялись настоящими библиотеками.

Все6 failures относились к tests/test_docs_register.py: blanket subprocess deny
сработал до native FileNotFoundError отсутствующего pdftotext. При переносе MAIN
network boundary автор потерял прежний FULL seam doc_text._command. V6 восстановил
**точный старый accepted captured bempty seam**; остальная boundary AST-идентична V5.
Новых exec/absence permissions нет, subprocess deny сохранён. Это проверка
регистрации/хранения документов, **внешний OCR не проверен**. Affected6 дал22 captures
этого seam, network/process/env forbidden0, source before/after PASS;
affected6_accepted=True и full376_accepted=False.

Main8 использовал unchanged fixture и настоящий ASGI/lifespan/create_all:
prepare1, chat start1/stop1,8 scheduler jobs parked/cancelled, notify8,
все transport/forbidden counters0. Production prepare/seed seam изолирован;
production bootstrap не доказан. ROOT независимо сверил65 retained artifacts,
44 business/files/auth transition phases и7 baseline-final fixtures: SHA/bytes,
разрешённые и обязательные auth deltas совпали. Старые42phases/58items не использованы.

## Изоляция, ограничения и cleanup

Новый PG16 использовал установленный immutable image721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea,
network none, loopback127.0.0.1:33546; test containers делили только его namespace.
Нет host networking/ports/gateway, Docker socket, host HOME/env/secret/app mounts.
Read-only rootfs, UID65534/реальный HOME=/nonexistent, private writable evidence,
manual verified site и -I -S -B. Узкие approved PG sendmsg controls и five-import
IPv6 suppression сохранены; original flag восстановлен, bind allowance отсутствует.

ROOT отдельно заменил свой плановый reserve16GiB на15GiB
(msg_49b88fa5deb3); предыдущие proofs не менялись. Load upper2474329088B,
build upper805306368B и fresh admission/live guard сохранены. Child CPU600s,
AS2GiB/FD256, wall full900s/main540s, log/file2MiB, scratch64MiB/4096entries,
DB256MiB. Runtime cgroups/PIDs/mounts проверял ROOT; build per-step PIDs hard limit
не предоставляется выбранным Buildx ResourcesConfig и не заявляется как проверенный.

Normal DROP: main DB344 relations; corrective DB0 relations/0clients,
existsAfter0/maxLocks64. FORCE/GUC/terminate/global prune не применялись.
ROOT подтвердил cleanup: old testc5, corrective testa7 и own PGf5 удалены только
после PID0; четыре own image tags overlay/acceptance/candidate/base удалены.
Foreign PG4bc7b672… остался running; archive/proofs/wheels сохранены, daemon не менялся.

Сохранены setup failures: V4 FROM naked sha256 registry-metadata TLS refusal
(2.0018s, до RUN/app) и первый PG init EACCES (tmpfs owner, до SQL/app).
ROOT исправил PG tmpfs по actual UID70; старый foreign PG4bc7b672… не затрагивался.
Сохранены V5 fullFAIL, все старые freezes/ignored artifacts и отдельные прежние
375/1, main3+5 proofs. Исторические результаты не переименовывались.

## Проверяемые квитанции

ROOT worktree:`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029`.
Private root:`.artifacts/root-container-acceptance-review-20261030/`.
Основные receipts находятся в attempt2/ и affected6/; исходный вывод и JUnit сохранены.

| Receipt | SHA256 |
|---|---|
| attempt2/candidate-process.json |3d6f8e91dafcfc67b69ffab3d1e0cb1e32066f0c383a033032105844168be9e7|
| attempt2/acceptance-process.json |d3a44dbc64049557402b2a49adce5d3b2534ac6fdc901654761ebc01ada3186b|
| attempt2/root-main-oracle.json |19c23043c40be77331ff2d40d7e5073fa06e67422bb13175635a8d4710526372|
| affected6/docs-register-affected6-process.json |3d4f33ccdf9c9f25be577705fcd961e428d52fdec30fd19e6ff8e1860573fffe|
| affected6/docs-register-affected6-db-drop.json |84c0da0844497df32ce14d3655ac16e2d9d3d40a1bc4ebaff200adb772317c97|
| accepted-result.json |e3dc7f2366685a50b8d3fff5b2bf995da88dcd1cd96e21c2f99fe507af229899|
| owned-images-removed.json |9a30c33f3d0c17c038e75c9eb168738ae6656991b50ead14b6f6224d6d07cc73|

Все Docker/app/pytest/SQL/installer/runtime действия выполнял ROOT.
Автор выполнял только source reads/AST/in-memory compile/hashes/Git и читал receipts.
Production Dockerfile/requirements/locks, default-OFF flags и версия не менялись;
SSH/remote Rushydro/ship/nginx/deploy отсутствуют. Это scoped local evidence,
не single376GREEN, общий CI, production readiness или закрытие M00–M19.
