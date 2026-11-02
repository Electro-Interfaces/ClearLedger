# Реальная композиция Support: M01/M13-C2

31.10.2026. Текущий профиль: **ROOT scoped acceptance, V10+V12, 6+2**. Worker не запускал
Node, приложение, tests/collection, SQL, namespaces или installer. Общие M00–M19,
M01/M13, full CI, HTTP/ACL conformance, startup и release этим пакетом не закрыты.

ROOT изменил приёмку сообщением `msg_7f1756d4f12c`: восемь разных конфигураций
проверяются **в двух сериях, 6+2**. Это не один успешный прогон восьми variants.
V10 group остаётся BLOCKED по output budget; шесть завершённых full leaves
сохраняются. V12 запускает только исходные variants6/7 после нового negative26.
ROOT принял V12 negative26 и два оставшихся variants;8конфигураций подтверждены
в двух сериях. Runtime выполнял только ROOT.

## Исходники и владение

Ledger base `875929b3885d98ace8e370a72d62a825bf76960b`, отдельная ветка
`agent/api-support-composition-boundary-20261031`. Изменены только новые два tools,
negative-control module и этот MD/JSON. Production, models, schema, dependencies,
версии, шесть прежних API tools/tests и historical CURRENT/COMPOSED не менялись.

Support target: `/home/mag/orca/workspaces/tsupport/api-support-app-composition-20261031`.
Base `a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df`, reviewed13-file overlay V3
freeze SHA `ee30c46798a20d0f0672662ba1eb266c3efb2df7463246dfe3e3511ef7d65f53`.
Дальнейшая ROOT метка Support e3a не заменяет byte identities в manifest.

| Источник | SHA-256 / охват |
| --- | --- |
| app.js | 34f60532f4c0d6fcc1d5494313cab6fd02ae35b410dc67426d6982569c78254b |
| full graph | e9c28f37380bc3b731db52ff5f73b6df2c8848f34ff35e0550d5899955c98a46;289 files |
| static app graph | 25f622825471290948f5971318cb77c9dcf00ce50634bf2a1dee065105de15c2;264 files |
| ordered registration AST | 264f5d541cab7d1e7b46e66daaf823a303546b24b019f409ae3281ed44a7f57d;100 same после5 reviewed arguments |
| Support toolroot manifest | 23d43f1d34ecba8297fb8d5821fd541a79cbcf7b1a8b5b41d6c1a6a76fb207c9;38088 files,44 internal symlinks,458845567 bytes,863 versions |
| /usr/bin/node | 3517c2df0b2f8cd7f422b4b8450ef81c6889f08eb03e281d6de9079b15e6a327;ROOT v22.23.2 |
| /usr/bin/python3.11 | 9bee109da0dce17a7c9eeaca9f420cc6770a9fe143b9382d73bd22fe59b21a5f |

Toolroot только readonly:
`/home/mag/orca/workspaces/tsupport/api-lifecycle-20261030/node_modules`.
54 отсутствующих optional packages описаны ROOT как несовместимые с Linux x64
Glibc. Это source artifact identity, не live install/container correspondence.
Полный plan содержит все289/264 hashes,1433 stdlib files,9 ELF mount records,
exact Node argv и synthetic env. Ledger dependencies не используются как Support.

## Граница запуска

Stdlib parent проверяет исходники/deps/Node/libs/helpers до target imports и после
серии. Only own user/mount/net/IPC/PID namespaces, private chroot и PID1 reaper.
Readonly `/work/source`, sibling `/work/node_modules`, `/tools`, exact Node/ELF
libraries; private `/tmp`, пустой HOME, own evidence. Host home/etc/proc/.env/keys/
vault не монтируются. FDs кроме0/1/2 закрыты. Caps сняты, no_new_privs включён.
Mounts существуют только в namespace; cleanup касается своего TemporaryDirectory.

Node `--permission --no-addons`, без child-process/worker/addon grants. Права
чтения ограничены frozen roots, запись — /tmp и единственный result file.
[Node permissions](https://nodejs.org/download/release/v22.23.2/docs/api/permissions.html)
не являются sandbox против malicious code; независимые OS границы обязательны.

До target установлены guards network/DNS/listen/fetch, processes/workers/addons,
SQL driver, timers/unref, env и filesystem. JS tripwire, даже caught, invalidates
actual export. Метод handle/dispatch не вызывается. Source loaders используют
нормальные CJS/ESM/cache semantics; Router/use/route/HTTP wrappers делегируют
исходные args/this/result и сопоставляют каждый intrinsic layer с регистрацией.
Порядок, nested/repeated mounts, raw path/RegExp/arrays, methods, handler hashes,
source refs и unresolved сохраняются. Нет fake Router, auth/SQL-success mocks.

ReadSync разрешён только для guarded openSync(r/0), FD≥3, regular file,
readable path/realpath и неизменных bigint dev/ino/mode/size/mtimeNs/ctimeNs.
Unknown/stale/closed/reused/stdio/pipes и прочие guarded FD reads/writes запрещены.
CloseSync удаляет binding; unknown close запрещён. Writable openSync даже /tmp
отклоняется. Active bindings должны быть0 после case/export. Private result writer
захватывает original open/write/close только для literal /evidence/result.json,
wx0600, full-budget/partial-write checks/finally close; target эту capability не видит.

Env snapshot SHA/keycount/object identity сохраняются. Единственный no-op:
удаление literal DEBUG, отсутствующего initial/current, возвращает true без delete
и учитывается counter. Existing DEBUG и остальные delete/set/define запрещены.
Это source-backed debug4.4.3 enable(load())→save(undefined) startup path, не env grant.

Native policy не обещает запись/KILL каждого syscall. Explicit feature denials:
clone3 и io_uring_setup →ENOSYS; exact socket(16,0x80003,0) →EPERM, **без FD**.
Все другие socket combinations →KILL через exhaustive disjoint complement;
socketpair/bind/listen/send/recv/прочие explicit rules остаются KILL.
Реальный os.networkInterfaces бросает штатный ERR_SYSTEM_ERROR; nodemailer9.0.3
shared/index.js:26 использует свой catch и оставляет undefined. Нет os API stub,
разрешённого netlink, fake interfaces или empty DNS response.

Primary sources: [libuv startup io_uring](https://github.com/nodejs/node/blob/v22.23.2/deps/uv/src/unix/linux.c#L599),
[Node os errno](https://github.com/nodejs/node/blob/v22.23.2/src/node_os.cc#L182),
[UV error formatting](https://github.com/nodejs/node/blob/v22.23.2/src/env.cc#L1545),
[glibc getifaddrs](https://github.com/bminor/glibc/blob/glibc-2.36/sysdeps/unix/sysv/linux/ifaddrs.c#L236).
Pinned Node передаёт positive errno1, поэтому validated native case требует
ERR_SYSTEM_ERROR / info.errno1 / uv_interface_addresses / literal info.code
`Unknown system error 1`; arbitrary message/stack/args/env не публикуются.

## Limits, actual receipts и область доказательства

CPU60s / wall90s / AS2GiB / FD128 per child; output **16MiB cumulative** на
negative+export leaves/aggregates в серии, без truncation. Durable full leaves
сохраняются до cleanup; final compact aggregate содержит refs/SHA/count/status.
При приближении cap следующий child не запускается. Private tmpfs96MiB/6000
inodes +stage16MiB/2000 +evidence16MiB/191 +sentinel1 ≤128MiB/8192.
Disk admission≥8GiB+192MiB, runtime floor≥8GiB; RAM floor не подменяет disk.
Reserve:16stage+16evidence+96tmpfs(RAM, conservatively counted)+16aggregate+48overhead.

ROOT controls:1 kernel process с7 assertions +25 JS =**26 fresh processes**.
Включены native unavailable-feature error, real permission denials, timers,
owned FD positive и unknown/closed/reused/write negatives, zero bindings,
DEBUG no-op и existing JWT_SECRET deletion denial. Старые17 assertions сохранены.

| ROOT receipt | Итог |
| --- | --- |
| V2 admission | 0 controls/app; reserve512MiB refused; история сохранена |
| V3 negative | INVALID до controls из-за outer FSIZE2MiB; ROOT исправил outer16MiB |
| V4/V5 | kernel PASS, Node SIGSYS; V5 trace доказал syscall425, не successful ring FD |
| V6/V7 | INVALID; writer options/source-loader readSync диагностированы, исходные receipts сохранены |
| V8 negative23 | PASS31.357897356s; затем first export blocked env.delete; group8 не принят |
| V9 negative25 | PASS32.152217049s; два failed exports/trace доказали socket41, не FD |
| V10 negative26 | PASS33.314619766s; hashes/FD0/env/source/deps/system verified |
| V10 export8 | BLOCKED32.278677978s before7;6 complete full leaves retained,2 not run |
| V12 negative26 | PASS34.284896281s, exit0/reaped;26leaf hashes/FD0/env/source/deps/system equal |
| V12 fresh2 original6/7 | PASS19.718072574s, exit0/reaped; full leaves/FD0/env/source/deps/system equal |

V10 negative SHA `5989152c5885678cfbc9c88dca6300424790fcd90caf96142b037aabc8417a09`.
Six full leaves total16128602 bytes; каждый denied[], readFD357 opened/read/closed,
active0, env unchanged. ROOT independent `root-partial-export-after-source.json`
подтвердил source/deps/system equal **после** BLOCKED; aggregate сам aftercheck
не достиг. Это основание ROOT для приёмки6, без переименования group в PASS.

Полные paths/SHA/variant/source/Node identities всех6 закреплены в
[plan JSON](SUPPORT_COMPOSITION_BOUNDARY_20261031.json), добавлены в existing
reference verification до/после без изменения launcher logic. Original0..5 — V10;
original6=core/contexttrue/distfalse и7=core/contexttrue/disttrue — только freshV12.
V12 leaf00/01 отображаются в original6/7 явно. Negative26 в V12 использует env
первого выбранного original6; значения соответствуют прежней конфигурации6.
Это не первый local/off variant V10, env keys/flags не изменены.

Источники ROOT: `.artifacts/root-support-composition-isolated-v10-20261031/`;
новый exact target `.artifacts/root-support-composition-isolated-v12-20261031/`.
V1–V10 own source snapshots сохранены. V11 codec alternative целиком сохранён
в ignored `.artifacts/support-composition-boundary-worker-20261031/v11-codec-alternative/`,
**никогда не исполнялся и не включается в commit**. ROOT отказался от расширения
harness и выбрал6+2. Helpers exporter/negative восстановлены byte-for-byte V10;
launcher отличается только literal evidence directory. Cap16MiB не повышался.
Fresh2 projection≤5641612 bytes с controls/reserve, значительно ниже16MiB.

Итоговая ROOT приёмка:
`root-support-composition-isolated-v12-20261031/root-eight-configurations-acceptance.json`,
SHA `44f361c793db38690eb4b8159edf1ac060b7432172bec7319a3187b45885d3cd`.
V12 negative JSON SHA
`6bcf3c8f19b9962f1bec2c76ea4b9bcf21704e6000b9b556d0fda58073335501`;
V12 export aggregate SHA
`8e9cb52d8b2ce97778fa1a64c59fa638e287f12ce0027792eeef84c55fe54309`.

| Fresh V12 variant | Full leaf bytes / SHA-256 |
| --- | --- |
| original6 core/contexttrue/distfalse; leaf00 | 2686466 / 7c4d9f0e896d15ca376d37ed6e3a946a135758b28d0b09a5ca17452fafb67742 |
| original7 core/contexttrue/disttrue; leaf01 | 2689732 / ac7f298bb5a9845210532d0b28db1c1f3496db2b0f2f1aedba90dff81cfefc3c |

Оба fresh leaves:2631/2634 displayed layers,1775/1778 registration calls;
FD357opened/read/closed,active0,denied[], env hash/object identity сохранены.
Это полные JSON, без codec или сокращения дерева. Worker независимо прочитал
и сверил V12 raw leaves и26negative hashes после ROOT receipt; ничего не исполнял.

ROOT independently parsed старые6:774/775 route layers; typed literal/array
expansion даёт777/778 method/path rows, duplicate keys0, unresolved typed paths0.
Row digest distfalse `05ccb07cfcfe25ea266bb2b71ca82d25a96db9138944dafba342f1cfd7ec2fcf`,
disttrue `ff122e1fde6625f3fd2538dec87b4989d075d0782dff40d4dc3246d72e9fd055`.
Source: `root-support-composition-route-review-20261031/six-prefix-summary.json`.
Эти цифры относятся к регистрации и parsed metadata, а не к HTTP/ACL proof.

Регистрация не доказывает request conformance, ACL, tags/owner decisions, SQL,
WS upgrade/SSE/multipart delivery, native SSH/CLI, lifespan/startup, live gateway,
public versions или deployed source correspondence. Эти задачи остаются у ROOT
и следующих владельцев. M01/M13 и общая цель остаются активными.

## Exact V12 freeze и ROOT argv

| Файл | SHA-256 |
| --- | --- |
| executed V12 plan before report-only field | e5d7d74c02059f5719aaacd0846ae56ff130c4424057c4b19a5dfe5491e12bec |
| final JSON with reportActualReceipts | 5741e38acacd47d58ec5f6a00285d4e8df149fad50fd5e6b38bd7d1e0b0860f1 |
| launcher | c2504d56814c57339d78d3cb452f74321fb4f3bd7d4975f3fe13833938bfa217 |
| exporter | 250c666271531a74eabd49e46454e7120c82ec2fba51f0cad0beee7b7c9a0e99 |
| negative module | c76ea4d7391efa24168f059020d815795b01962e5daa749efb5f6415a28a40f1 |

Actual ROOT использовал executed plan SHA выше. После завершения добавлен только
reportActualReceipts; сравнение всех остальных JSON полей подтвердило неизменность
runtime contract. Ни один из трёх helpers после execution не менялся. Для final
JSON команды ниже используют его новый byte SHA. Evidence target уже содержит
receipts, поэтому x-open предотвращает перезапись; новый запуск требует решения ROOT.

ROOT создаёт exact owned0700/non-symlink directory. Сначала26negative, затем
отдельное решение ROOT на2exports; команды не разрешают worker runtime.

```sh
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC /usr/bin/python3.11 -I -S -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/scripts/run-support-composition-isolated.py --plan /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/docs/api/SUPPORT_COMPOSITION_BOUNDARY_20261031.json --plan-sha256 5741e38acacd47d58ec5f6a00285d4e8df149fad50fd5e6b38bd7d1e0b0860f1 --mode negative --output /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-support-composition-isolated-v12-20261031/negative.json
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC /usr/bin/python3.11 -I -S -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/scripts/run-support-composition-isolated.py --plan /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/docs/api/SUPPORT_COMPOSITION_BOUNDARY_20261031.json --plan-sha256 5741e38acacd47d58ec5f6a00285d4e8df149fad50fd5e6b38bd7d1e0b0860f1 --mode export --output /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-support-composition-isolated-v12-20261031/export.json
```
