# Partner DX: исходное ревью оснастки ROOT, 31.10.2026

**SOURCE_REVIEW_COMPLETE для замороженного helper; runtime=0, runtime-приёмка NOTRUN.** Это исходное ревью оснастки, без утверждения о её успешном выполнении или готовности PR82 к выпуску.

База PR82 freeze18: `725bee174f40b7155c87c38493b0581138da3ef0`. Неизменяемая база checker: `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Helper после точечной правки B8: коммит `2f14a1840f451fc8784e30b904e70a307e672d16`, SHA-256 `cb08651807954ea9b31a1bbb3e21b2ef89eb8e46ceb2e110340e008fcf7d6455`, 73343 байта, 1116 строк. Первоначальный A commit `8c31d7f79962d6958914a97492c0d47901a1580d` добавил к базе только helper; итоговая B8-ветка содержит ровно три новых пути (helper и два отчёта), а B8 commit `2f14a1840f451fc8784e30b904e70a307e672d16` меняет только одну SHA-константу относительно своего родителя. Существующие 18 файлов PR82 не менялись. Первоначально своя зона включала только Markdown и JSON; в отдельном B8 follow-up координатор передал также helper для одной замены FROZEN_SITE.sha256 после освобождения A. Теперь итоговая дельта содержит ровно три новых пути; остальные байты helper и существующие 18 файлов PR82 неизменны.

Прочитаны CLAUDE.md проекта и clearledger, machine instructions/карточки/SSH canon и применимые инструкции rushydro-space. Рабочая машина LIN-DEV; проекты не переносились. Общие рекомендации о тестах, памяти, push и выпуске ограничены явным SOURCE-ONLY заданием: никаких app/helper/framework imports, pytest/collection/controls, HTTP/SQL/SSH/Docker/browser/Node/codegen/build/install/live/.env/secrets. Только чтение, Git, stdlib AST/hash и compile в памяти без исполнения полученного кода. Последний frozen helper и два original test files синтаксически разобраны/скомпилированы таким способом; это не runtime PASS.

Полные файловые манифесты и typed bindings находятся в JSON. Строка каждого манифеста: relative path, длина, SHA-256; SHA манифеста вычисляется по JSON отсортированных строк с separators comma/colon и обычным ensure_ascii=True. Для app/tests/schema relative root — server; для site — site-packages. SELF helper исключён из tests и закреплён отдельным полным SHA; отчёты находятся вне этих деревьев. Подтверждены точные счётчики, байты и SHA по независимому чтению.

| Дерево | Файлов | Байт | SHA-256 манифеста |
|---|---:|---:|---|
| app | 504 | 17249730 | `a2766d51aaaa9c684357005e411914b928f508b02d5b1f1da93a9ef77dcaf84f` |
| tests | 397 | 5741903 | `a78fc8de5d574724cf8da8d8d492315c131245ceca56209fd85aa32e8662d979` |
| schema_migrations | 24 | 107419 | `2fd1936ae592fcd65ca8878e9797c8fb3579aaa77e7f62ee6b0d9db96f6305a4` |
| site | 7245 | 169999373 | `49071b9c07b1fe65baf287e952e9b3c98907ee92f9434c0f30d151d513f8bec2` |

Native runtime задан как существующий CPython3.13.7 `/srv/projects/api-modernization-upgrade-test-env-20261030/.venv`, ровно 77 pinned distributions. В JSON сохранены все 77 Name/Version/METADATA hashes, pyvenv.cfg hash и полный site manifest, включая 3044 существующих .pyc как хешируемые данные. Исполнение .pyc запрещено. Проверки helper до/после заново сканируют полные app/tests/schema/site, поддержку и self; ANY symlink и nonregular entries отвергаются. Source binding loader проверяет реальные `.py` bytes, включая direct spec_from_file_location исходного checker; флаги -B сами по себе не доказывают запрет чтения кеша.

Typed import closure: 18 действительных app modules, actual tests package/два tests/checker; три modules app.services/ops_monitor_context/session_scope импортируются из actual source, их функции запрещены. Единственный адаптер app.database предоставляет реальный SQLAlchemy DeclarativeBase без engine/session; реальные models/DTO/Pydantic/route policies не заменены. Только объявление CONTRACT_TYPES разрешает один source-pinned genexpr queries.py:23; вызовы Query/SQL/file/budget/service/lifespan/job/config/sender/HTTP handler остаются запрещены. Unknown/dynamic runtime import closure здесь не измерена; разрешены только проверенный SITE/stdlib и точные app/test bindings, неизвестные исходники/действия ведут к отказу. Подробные actual/inert/denied/unknown записи и source references находятся в JSON.

Из frozen AST независимо получены **12 определений, 26 ожидаемых node IDs: 19 metadata +7 examples**, без запуска collection. Развёртка metadata: 1+6+10+1+1; examples: семь одиночных функций. Все26 точных IDs и строки/число Assert/pytest.raises сохранены в JSON. Два original test hashes неизменны: metadata `70d9d6bdaaeb0d7ef2d8fdfe88dc8016e603715307cbe6ef190ec682dea60463`, examples `ed7caa5eeeb38d4ce4cde41557bda5216224fe12217f3e9b366d2f40bd039019`. Будущий запуск требует ровно 26 collected IDs, 78 setup/call/teardown reports и 26 совпадающих JUnit cases; errors/skips/xfail/deselection/missing/extra cases/guard attempts отвергаются. Assertions сохранены побайтно, optimize=0 и --assert=plain; тестовые функции и normalizer oracle не подменяются.

Исходные опоры: `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/server/tests/test_partner_dx_metadata_20261031.py:20` (неизменённый checker fixture), `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/server/tests/test_partner_dx_metadata_20261031.py:121` (защищённые источники), `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/server/tests/test_partner_dx_metadata_20261031.py:129` (actual registry), `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/server/tests/test_partner_dx_examples_20261031.py:31` (actual DTO/schema fixture), `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/scripts/verify_partner_dx_metadata_20261031.py:49` (Git bridge), `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/scripts/verify_partner_dx_metadata_20261031.py:87` и `Electro-Interfaces/ClearLedger@725bee174f40b7155c87c38493b0581138da3ef0:clearledger/scripts/verify_partner_dx_metadata_20261031.py:193` (normalizers).

Cache содержит ровно 12 tuple: один ls-files(product_api, api_contracts) и 11 show из cec2c984 (DTO/app +9 protected files). Каждый hash независимо сверен с actual read-only Git stdout, включая исходный terminal newline; перечень tuple, длины и источники SHA в JSON. ROOT prepare выполняется отдельно в чистом Git checkout с pinned HEAD/branch/base и ограниченными Git timeout/bytes; создаёт внешний 0600 prepare-cache.json под0700. Закрытый executor принимает его SHA и ownership/regular/non-symlink/size/exact12/per-byte pins, работает без .git, никогда не читает hidden host repo. Bridge обслуживает только исходный checker.git caller и точный argv без kwargs; возвращает исходные immutable bytes, unknown/cached-miss deny+record. Четвёртый tracked snapshot не потребовался и не создавался.

Closed boundary устанавливается до первого framework/app import, в том числе eager app.product_api.__init__. Она запрещает сеть, SQL/engine/session, процессы, senders, реальные settings, serving/main/lifespan/jobs, outside writes, замену hooks и лишние env mutations. Pytest выполняется одной actual main/code identity в одном процессе: --noconftest, explicit pytest_asyncio.plugin, noautoload/nocache/no faulthandler, без nested pytest. Будущие phase/trace/output/JUnit/imports/schema/receipt outputs записываются только в owned evidence; failures не превращаются в успех. На Python/guard/pytest FAIL выполняются feasible postchecks источников, inventory, seal, env/cwd, artifacts и boundary. Guard exception остаётся отказом, даже если тест её поймал.

Будущий отдельный schema phase вызывает actual create_product_api/curated_openapi/public_client_openapi/policy_registry и actual DTOs. Оба canonical/public schema проверяются действительным Draft202012Validator по pinned official OAS3.1 structural meta-schema; component schemas отдельно проходят check_schema, examples — JSON Schema и Pydantic strict roundtrip. Проверяются 15 GET, 11 service-capable/4 user-only, security alternatives,14 JSON examples/field aliases, problem/cache/request/challenge/retry headers, binary application/octet-stream. Public projection не должна менять canonical и меняет operation security при сохранении schema/examples/headers/binary. Browser означает public execution schema; браузер и HTTP не запускались. Export canonical/browser/registry идёт в evidence, не в SDK. Official SDK generation/freshness NOTRUN.

Конечные границы исходника: 180s total wall, рабочее окно 150s и отдельное 30s postcheck; CPU soft=hard150s, RAM2GiB, core0, FD96; максимум20k entries на дерево,16MiB на файл/JUnit/JSON,256MiB на дерево; pytest stdout+stderr 8MiB и phase aggregate 4MiB;64MiB/128 файлов суммарно evidence+scratch, free floor 8GiB до/после. JSON writer перед каждым open резервирует один файл и точное число encoded bytes, в том числе на FAIL; output/JUnit резервируются отдельно. Trace/sections/imports/cache hits/denials ограничены (32KiB phase trace,2048 chars/section,8 sections/report,4096 imports,256 cachehits,64 denials/8 frames). ROOT должен оценить фактическую стоимость, границы здесь не проверялись исполнением.

Preapproval refusal не обещает receipt в ещё не принятые каталоги. SIGKILL/OOM/жёсткий CPU-limit не могут исполнить finally; переполненный admission может не допустить даже FAIL receipt. В этих случаях ROOT/controller обязан независимо сверить source/site/process/evidence census. Приёмка требует exit0, целого согласованного receipt и необходимых внешних проверок; частичный JUnit/schema/output или один status не подтверждают успех. Жёсткие лимиты и гарантия наличия receipt разделены явно.

B1–B7 первоначально проверены по A commit `8c31d7f79962d6958914a97492c0d47901a1580d`, SHA `28b0b7f6b3120b04fe93b21b143feb8c44e232d61fe8eef57360c4fbcdf55342`, и отчётам `159f5915f4f679caf0bf70f049a9a41b1132cab9`; их provenance сохранён в JSON. B8 найден координатором и независимо подтверждён в этом follow-up: прежний SHA `937b3668aef208860ab8ea14b49caf13c1b8d9367932c809a051ee3a712386c2` относится только к ошибочному Path-порядку, который ставил `aiofiles/__init__.py` перед `aiofiles-24.1.0.dist-info/INSTALLER`. Глобальная сортировка строк и независимое чтение filesystem дают канонический SHA `49071b9c07b1fe65baf287e952e9b3c98907ee92f9434c0f30d151d513f8bec2`, 7245 файлов и 169999373 байта. Helper исправлен отдельным коммитом `2f14a1840f451fc8784e30b904e70a307e672d16` (интегрирован координатором как `7f954a80af5b5f8ba5098c13d7d5deef861d0d8a`, bytes совпадают) одной заменой SHA; другие bytes, 77 versions и 26/78 ожидаемых counts не менялись.

Материальные находки закрыты только по frozen source `2f14a1840f451fc8784e30b904e70a307e672d16`; runtime controls не запускались. Все source ссылки таблицы относятся к этому helper commit/SHA.

| ID | Находка | Проверенная редакция | Точка исходника |
|---|---|---|---|
| B1 | Загрузчик отвергал настоящий пакет tests | Добавлен точный hash binding tests/__init__.py; conftest по-прежнему запрещён | `clearledger/server/tests/partner_dx_metadata_approved.py:478` |
| B2 | Счётчик pytest.main использовал неверное имя модуля | Проверяются origin/hash настоящего _pytest.config.main; profile считает точный code object и требует один вызов | `clearledger/server/tests/partner_dx_metadata_approved.py:588`, `clearledger/server/tests/partner_dx_metadata_approved.py:431` |
| B3 | mkdir допускал аргумент dir_fd | Проверяется точная audit signature и отвергается fd-relative mkdir; запись вне разрешённых путей запрещена | `clearledger/server/tests/partner_dx_metadata_approved.py:359` |
| B4 | Postcheck полного SITE конфликтовал с 3044 существующими .pyc | Чтение pinned SITE .pyc разрешено только точной цепочке code frames postcheck/inventory/tree/bounded_bytes для хеширования; imports загружают проверенные .py, phase устанавливается перед postcheck | `clearledger/server/tests/partner_dx_metadata_approved.py:359`, `clearledger/server/tests/partner_dx_metadata_approved.py:463`, `clearledger/server/tests/partner_dx_metadata_approved.py:963` |
| B5 | AST ID и limits проверялись до guarded try | Сначала создаётся минимальный proof; limits и AST IDs находятся внутри try/finally; preapproval failure явно не обещает receipt | `clearledger/server/tests/partner_dx_metadata_approved.py:1020` |
| B6 | Поздние файлы и FAIL receipt обходили общий лимит | Перед каждым JSON open writer резервирует один файл и точный encoded размер; output/JUnit резервируются отдельно, поздние файлы попадают в final scan; отказ admission не создаёт лишний файл | `clearledger/server/tests/partner_dx_metadata_approved.py:683`, `clearledger/server/tests/partner_dx_metadata_approved.py:588`, `clearledger/server/tests/partner_dx_metadata_approved.py:939`, `clearledger/server/tests/partner_dx_metadata_approved.py:1020` |
| B7 | Генератор объявления ошибочно считался runtime function | Разрешён только frozen genexpr queries.py:23 с точными filename/line и same-globals caller <module> для метаданных CONTRACT_TYPES; Query и остальные функции запрещены | `clearledger/server/tests/partner_dx_metadata_approved.py:431` |

| B8 | Координатор выявил несовпадение Path-порядка и rows.sort для SITE | Независимо подтверждён canonical SHA; заменён только FROZEN_SITE.sha256, site.rows глобально отсортированы и совпадают с filesystem | `clearledger/server/tests/partner_dx_metadata_approved.py:88` |

Ниже только **будущий ROOT skeleton с placeholders**, не выполненные команды. ROOT отдельно утверждает exact source/helper/cache SHA и создаёт четыре пустых owned 0700 непересекающихся каталога вне source на каждый запуск. Execute использует свежие каталоги; prepare evidence/cache остаётся отдельно под0700/0600. HOME — фактический passwd HOME текущего ROOT процесса; DSN, tokens, secrets и .env отсутствуют.

```sh
cd "<PREPARE_EMPTY_CWD>"
env -i HOME="<ACTUAL_PASSWD_HOME>" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
 ROOT_APPROVED_PARTNER_DX=1 RUN_PARTNER_DX_METADATA=1 \
 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
 DX_RUNNER_SHA256="<REVIEWED_HELPER_SHA256>" \
 DX_SOURCE_HEAD="<FROZEN_GIT_SOURCE_HEAD>" DX_SOURCE_BRANCH="<FROZEN_GIT_SOURCE_BRANCH>" \
 DX_EMPTY_CWD="<PREPARE_EMPTY_CWD>" DX_EVIDENCE_DIR="<PREPARE_EVIDENCE_0700>" \
 DX_SCRATCH_DIR="<PREPARE_SCRATCH_0700>" DX_UPLOAD_DIR="<PREPARE_UPLOAD_0700>" \
 /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
 "<CLEAN_GIT_SOURCE>/clearledger/server/tests/partner_dx_metadata_approved.py" \
 --prepare-approved-partner-dx-cache
```

После отдельного чтения ROOT prepared receipt/cache и pin полного cache SHA:

```sh
cd "<EXEC_EMPTY_CWD>"
env -i HOME="<ACTUAL_PASSWD_HOME>" PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
 ROOT_APPROVED_PARTNER_DX=1 RUN_PARTNER_DX_METADATA=1 \
 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
 DX_RUNNER_SHA256="<REVIEWED_HELPER_SHA256>" \
 DX_SOURCE_HEAD="<SAME_FROZEN_GIT_SOURCE_HEAD>" DX_SOURCE_BRANCH="<SAME_FROZEN_GIT_SOURCE_BRANCH>" \
 DX_EMPTY_CWD="<EXEC_EMPTY_CWD>" DX_EVIDENCE_DIR="<EXEC_EVIDENCE_0700>" \
 DX_SCRATCH_DIR="<EXEC_SCRATCH_0700>" DX_UPLOAD_DIR="<EXEC_UPLOAD_0700>" \
 DX_PREPARED_CACHE="<PREPARE_EVIDENCE_0700>/prepare-cache.json" \
 DX_PREPARED_CACHE_SHA256="<ROOT_REVIEWED_SEALED_CACHE_SHA256>" \
 /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
 "<EXACT_SOURCE_COPY_WITH_OR_WITHOUT_GIT>/clearledger/server/tests/partner_dx_metadata_approved.py" \
 --execute-approved-partner-dx
```

Это оснастка для base725, а не repin текущей whole-final ROOT composition. Интеграция иных исходников требует отдельного reviewed repin; несовпадение manifests нельзя обходить. **Все 20M и 11gates UNPROVEN; runtime/collection/controls/schema exports/SDK generation/freshness NOTRUN.** Push/PR/merge/deploy здесь не выполнялись; координатор интегрирует отдельные helper-fix и report commits. Markdown и JSON исключены из собственного рекурсивного manifest: JSON содержит полный helper SHA и Markdown SHA, свой полный SHA фиксируется внешним Git commit/сообщением координатору.
