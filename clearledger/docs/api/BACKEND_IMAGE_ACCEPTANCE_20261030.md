# Локальная контейнерная приёмка backend, 30.10.2026

**ROOT: main8 —8PASS; full376 —370PASS/6harnessFAIL. Corrective affected6 pending; единого376GREEN нет.**
Основа `07f12c6575cbb397e9945c7f9efda724445615c2`; собственная ветка
`agent/api-container-acceptance-20261030`. Прежние ignored artifacts и Git-история
сохранены. ROOT integration worktree не переключался; app/tests/DTO, прежние gates,
Dockerfile, requirements, locks, версии и default-OFF flags не менялись.

Новый комплект находится в `server/tools/backend_image_acceptance_20261030/`.
Автор выполняет только чтение исходников, stdlib AST/compile в памяти, hashes/Git.
Docker/build/load/container, приложение, pytest/collect, SQL, драйверы и установка
зависимостей исполняются исключительно ROOT после review frozen proposal.
Контекст локальный: SSH/стенд РусГидро/ship/release/provision не используются.

## Замороженный источник и наследование проверок

| Дерево | Файлов | SHA256 |
|---|---:|---|
| app |492|9595a3002cf0c80409a4caf9b1209aa20fb2d1619c25ca0da52867a2c7a8eb54|
| tests, включая прежние gates |349|1588d43dfb02ca7d5dd6beb700ae53c998bd2dab84b986d716fbaef32354f57f|
| schema_migrations |16|c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e|

`source-manifest.json` содержит per-file SHA всего app/tests/schema/support,
прежних gates и новых скриптов/рецептов, точные inventories61/16 и retained wheel
hashes. ROOT context содержит byte-identical alias support.dockerignore для COPY frozen .dockerignore; прежний ignore не меняется и Dockerfile-specific filter не требуется.
Сам JSON не хеширует себя; ROOT передаёт его SHA и SHA обоих entrypoints
аргументами до любых сторонних/app imports. Взаимных embedded SHA нет.
Проверка source повторяется после выполнения. Все tests и assertions прежние.
ObjectId и lifecycle fixes, P2 и M18 входят в этот новый ROOT snapshot;
прежние375/1 и раздельные3+5 не переименовываются в новый результат.

`full376.py` сохраняет exact16-file selection и6 исходных probes из
`tests/backend_upgrade_approved.py`, но собирает их из SELF нового runner, без импорта host-only gate. Шесть probes тестируют настоящий raw JWT,
PDF/pypdf/app extraction, malformed PDF, multipart bytes/filename/limits и dotenv
synthetic stream. Переиспользованы observer с exact owned anchor/ENOENT-only,
atomic outcomes/redaction, CPU/AS/FD/file/log/deadline и kill/reap semantics.
`main8.py` сохраняет8 unchanged distinct cases, настоящий ASGI/lifespan/create_all,
startup prepare/seed seam и8 parked jobs; final cancellation всех8 обязательна.
Ожидаются prepare1, chat start1/stop1, каждый scheduler1, notify.dispatch_async8,
остальные transport captures0. Независимые existing business/auth/file oracles
и их assertions не менялись. Production bootstrap/seed не доказывается seam.

Оба новых runner используют точную узкую owned-PG buffers-only sendmsg policy из
принятого main gate SHA4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd.
Её16 metadata controls сохранены. Только5 initial imports временно видят
has_ipv6=False; исходное значение восстанавливается до app/fixtures, bind allowance
отсутствует. External network/process/env attempts должны остаться0.

## Candidate, acceptance и собственные контейнеры

`Dockerfile.candidate` получает через обязательный ARG BASE_IMAGE verified local name:tag@digest для retained image
sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51.
ROOT повторно проверяет archive SHA/размер/layers/free-space до load; скачиваний нет.
Retained61 wheels (в том числе единственный derived http-ece и pip) создают
новый image-local `/opt/candidate` через exact unchanged runtime/bootstrap locks.
Старые system distributions и app/schema directories удаляются, новый source
копируется целиком, без overlay остатков. Host environments не копируются.
После COPY build-time `image_probe.py --profile runtime61` под -I -S -B проверяет
реальные CPython3.13.18/glibc2.41, exact inventory61, no .pth/customize/symlinks,
полный baked app/schema source, actual imports и default flags OFF, deny network/SQL.
SHA probe/manifest ROOT передаёт build args. Pip check обязателен.

`Dockerfile.acceptance` требует ROOT-approved immutable candidate image ID;
добавляет только отдельные16 test tools и frozen tests/support. App/schema
наследуются из candidate. ROOT сверяет candidate61 → acceptance77 и одинаковые
app/schema/runtime pins; actual acceptance77 probe предваряет тесты.
Candidate runtime не содержит testtools16; версия host3.13.7 не используется.

ROOT создаёт только новый isolated synthetic PG16 и новый test container.
PG использует уже установленный exact image
sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea,
`--network none`, listen127.0.0.1:33546; test container использует исключительно
`--network container:<new exact PG id>`. Нет published ports, host networking,
host gateway, Docker socket, host HOME/secret mounts или рабочих env.
Реальный HOME65534 `/nonexistent` сохраняется, passwd не подменяется.
Единственный writable bind — новая собственная private `/acceptance` для evidence;
app/tests/schema/tools берутся из image. Rootfs read-only; cap-drop ALL,
no-new-privileges, test2CPUs/3GiB/no swap/PIDs128/FD256; PG1CPU/768MiB/no swap/PIDs64.
PGDATA и test `/tmp` — ограниченные tmpfs; ROOT проверяет actual inspect/cgroups.

Точные disposable DB: full376 `api_backend_upgrade_test_20261030`, main8
`api_partner_main_test_20261030`; role/owner clearledger, только synthetic password.
ROOT готовит отдельную login-роль clearledger без superuser/createdb/createrole/replication и БД через exec только нового PG exactID; bootstrap admin — штатный postgres. В новом PG обе БД должны
быть fresh/empty/exclusive. Sequential full376 затем отдельно main8; схемы,
SQL и cleanup выполняет ROOT. Старый PG4bc7b672… и прочие чужие ресурсы сохраняются.
Нет FORCE/GUC/terminate/global prune; normal DROP после connections0 и size/oracle
receipts, удаление только созданных exactIDs с retained ownership/labels proof.

## Ограничения и критерии результата

До исполнения ROOT принимает private frozen proposal с exact SHA/argv/env/budgets.
Первый source freeze273ebe49/V3 отозван до исполнения: неиспользуемый host REPO
вычислял SERVER.parents[1] при SERVER=/app. V4 удаляет только это присваивание
из двух новых runners; старый commit и proposals сохранены. Source-only symbolic
AST review проверил29+35+3 top-level assignments для image paths; никакой runner
не импортировался и не исполнялся. HOME65534=/nonexistent сохраняется по passwd;
записи идут только в ROOT-owned /acceptance, bytecode/cache отключены.
Actual readonly-rootfs/user/mount proofs остаются за ROOT.
V5 сохраняет дополнительно source-only исправление collection: ровно6 прежних
AST-identical probes собираются из SELF, остальные15 файлов/370 cases неизменны.
Импорт старого host gate исключён; его файл и assertions не изменялись.
ROOT V4 candidate build завершился exit1 за2.001785599s до RUN/app: naked
FROM sha256:812e был разобран как repository sha256, registry metadata TLS отказал.
Это setup failure; прежний receipt сохраняется и не выдаётся за Python/app verdict.
V5 использует ARG BASE_IMAGE и verified local name:tag@digest; acceptance получает
аналогичный newly built candidate reference. ROOT повторяет build, не functional tests.
Грамматика описана в [Dockerfile reference](https://docs.docker.com/reference/dockerfile/#from).
[Buildx0.36.1](https://github.com/docker/buildx/blob/v0.36.1/build/opt.go#L529-L534)
выбирает PreferLocal для Docker driver при pull=false;
[BuildKit0.32.2](https://github.com/moby/buildkit/blob/v0.32.2/util/resolver/pool.go#L259-L279)
проверяет local name:tag и digest. Local cache/build success подтверждает только
actual ROOT execution; TLS и mirror configuration не меняются.

Отдельным allocation decision msg_49b88fa5deb3 ROOT заменил собственный
первоначальный плановый reserve16GiB на15GiB; upper bounds load/build не уменьшены.
Это новое решение ROOT для данной локальной приёмки, не изменение прежних proofs.
Диск принимается по последовательным fresh admission stages при reserve≥15GiB
всегда: load upper2473280512B из прежнего accepted2expanded+compressed accounting,
плюс1MiB bounded output; после доказанного освобождения load temporaries — fresh
build admission с upper768MiB для новых context/images/cache/logs; затем fresh
admission160MiB для двух retained test scratch/evidence directories. Это upperbound
и watchdog, не hard quota Docker FS. При исходном ROOT preflight free19578298368B load stage
не укладывается: headroom2398429184B меньше required2474329088B на75899904B.
После ROOT allocation decision free19127570432B даёт headroom3021443072B
над reserve15GiB; fresh measurement перед каждой стадией остаётся обязательным.
Observed прошлый load расход не подменяет upperbound. Старые proof/wheels/env,
чужие ресурсы сохраняются; оба host env ROOT восстановил после отменённой временной архивации. Retained archive не копируется повторно.
Context≤128MiB, PGDATA≤512MiB tmpfs,
test scratch≤64MiB/4096 entries, stdout каждого child≤2MiB, file≤2MiB,
JSON≤2MiB, traces≤16KiB each/1MiB total, DB≤256MiB. ROOT обязан доказать upper bound
реальными retained layer sizes/available allocator accounting до mutations;
при невозможности уложиться выполняется stop/ask, без обхода бюджета.
Build≤600s per stage, probe≤60s, PG preparation≤60s; full900s/main540s,
child CPU600s/AS2GiB/FD256. Контейнер и Docker daemon jobs имеют отдельный ROOT
watchdog с stop/wait/Pid0 и client reap; kill одного CLI не означает остановку job.

376PASS требует ровно376 collected/passed, JUnit376/no errors/failures/skips,
pytest exit0, complete parent/child receipts, source unchanged, actual target
version/inventory и forbidden0. Main8PASS отдельно требует8 collected/passed,
JUnit8, exact lifecycle/delivery counts, parked8 cancelled, unchanged
business/files/auth oracle fingerprints, forbidden0 и independent parent receipts.
Никаких skip/xfail/ослабления assertions. Первый провал сохраняется; retry без
нового review/fresh attempt не предусмотрен. После ROOT receipts здесь разрешена
только report-only finalization. Это не production readiness, выпуск или закрытие M00–M19.


## Фактические ROOT результаты V5 и corrective V6

Candidate61 build PASS45.037790793s, acceptance77 build PASS8.513850699s.
Actual candidate probe: Python3.13.18/glibc2.41, app492/schema16, exact61,
пять default flags OFF, no attempts, source guard before/after, app from image.
Candidate ID0d58065c8b3ed50db553c12e9bd47aee7f16566e8353e99f636084d24714c38e;
acceptance IDffe96074307ea9e98f97252b3e7831510560b0096127aaabad72e08ddb64cf25.
Его RootFS наследует полный candidate prefix; app/schema/runtime pins сохранены.

Full376 завершился370PASS/6FAIL/149passed subtests, pytest200.22s,
ROOT outer226.2434s. Это сохранённый FAIL; network/env0, blocked_subprocess6.
Все failures — шесть unchanged tests/test_docs_register.py: общий subprocess deny
перехватил попытку pdftotext до native FileNotFoundError. Исправленные ROOT facts
показывают отсутствие pdftotext/pdftoppm/tesseract в image. Первое сообщение ROOT
об установленных extractors было premature и явно отозвано.

Причина отличия от прежнего host375/1 — новая оснастка перенесла MAIN boundary,
потеряв FULL seam doc_text._command. Старый принятый full gate возвращал в этом
единственном optional externalOCR seam captured bempty; native Popen не достигался.
ROOT разрешил V6 восстановить **точный** прежний seam, сохранив запрет subprocess.
Нет новой exec/absence allowlist, installer или permissions. Шесть library probes
с actual pypdf/JWT/PDF/multipart/dotenv, их helpers и assertions прежние.
Source-only AST proof подтверждает exact oldfull patch и captured helper;
остальная V5 boundary AST-эквивалентна. Это register lifecycle scope,
не проверка внешнего OCR и не source/app fix.

V6 profile docs-register-affected6 выбирает только шесть actual failing nodeids,
проверяет exact6 collected/passed/JUnit, no errors/skips/xfail, source before/after,
forbidden0 и положительный captured count. Он сохраняет full376_accepted=False
и отдельный affected6_accepted. Fresh RUN/output и новая dedicated DB того же
разрешённого имени готовятся только ROOT после normal DROP.
Dockerfile.harness-overlay наследует exact acceptance77 tag@digest и копирует
только owned tools/manifest; app/tests/schema/runtime/pins/support не меняются.
Старые fullFAIL artifacts не переписываются. ROOT поручил affected-only retest,
main8 повторять не требуется. После6PASS допустим scoped aggregate370retained+6corrective,
который не переименовывается в новый single376GREEN.

Main8 отдельно завершился8/8PASS, ROOT outer93.0779s, child reaped.
Prepare1/chat start1+stop1, scheduler8 parked/cancelled, notify8,
transport0/forbidden0; HOME/source guard/inventory target сохранены.
ROOT независимо проверил65 retained artifacts и44 numbered business/files/auth
transition phases для7 baseline-final fixtures: exact SHA/bytes и разрешённые/
обязательные auth deltas совпали. Прежние affected5 58items/42phases сюда не перенесены.
Normal DROP main DB:344 relations, connections0; обе test DB после первых прогонов отсутствуют.

PG init attempt1 завершился EACCES tmpfs0700root до SQL/app; failure сохранён,
удалён только exact exited own container. ROOT проверил UID70, исправил tmpfs
uid/gid70 и создал fresh own PGf5b2ec249cd684e6ea2aa588fc73061d088995e1bb104f00060ad75f857e4a3c;
test c5b26a77bd2c67adbc7063ec929e58d2222617283a64b2c4e1bb1a8020ccacef.
Isolation inspect PASS. Коррекция UID относится только к новому synthetic PG.
Все runtime/SQL/Docker действия выполнял ROOT; автор читал только завершённые receipts.
Final affected6/cleanup receipts ещё ожидаются; M00–M19, CI и выпуск не закрыты.
