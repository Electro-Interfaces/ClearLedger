# Partner DX: исходное ревью оснастки ROOT, 31.10.2026

**SOURCE FIX AUTHORED, статическая проверка; runtime=0, runtime-приёмка NOTRUN, независимое ревью координатора ожидается.** F9–F11 исправлены по исходнику; этот отчёт не утверждает успешное выполнение оснастки или готовность PR82 к выпуску.

Точный неизменяемый родитель этой правки — PR85 HEAD `2b81ce6b9bc9ed2558aff41fe519ae259406b1d4`. Его helper: SHA-256 `cb08651807954ea9b31a1bbb3e21b2ef89eb8e46ceb2e110340e008fcf7d6455`, 73343 байта, 1116 строк; прежние bytes и B1–B8 provenance сохранены в Git/JSON. Новый helper зафиксирован первым отдельным коммитом `f75e1ead72ba0f8cfd40108e79ce9a62a5f23a6c`, SHA-256 `f2945b558434c7f500f72fe6d2b48fce63d6e33db8bc2657d9b0a0429b5581ee`, 85985 байт, 1333 строки. Второй коммит меняет только эти Markdown/JSON отчёты. Дельта к exact PR85 parent — ровно три существовавших пути; старое PR85 worktree не изменялось, новые пути не создавались. Ветка автора: `MagLook/partner-dx-harness-dirfd-fix-20261031`; push/PR не выполнялись.

База замороженных PR82 app/test manifests остаётся `725bee174f40b7155c87c38493b0581138da3ef0`, checker — `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Это не repin whole-final composition: его статус **UNKNOWN**, отдельная работа ROOT. Полномочия на code/tests/docs в отдельных ветках переданы координатором из `ROOTmsg_f141e959f608`; исходная F9 — `ROOTmsg_68061b7bbcde`, дополнения F10/F11 — `msg_e20cf84970ab`. Никто из relation workers не привлекался.

Прочитаны CLAUDE.md проекта и clearledger, machine instructions/карточки/SSH canon и применимые инструкции rushydro-space. Рабочая машина LIN-DEV; проекты не переносились. Общие рекомендации о тестах, памяти, push и выпуске ограничены явным SOURCE-ONLY заданием: никаких app/helper/framework imports, pytest/collection/controls, HTTP/SQL/SSH/Docker/browser/Node/codegen/build/install/live/.env/secrets. Только чтение, Git, stdlib AST/hash и compile в памяти без исполнения полученного кода. Последний frozen helper и два original test files синтаксически разобраны/скомпилированы таким способом; это не runtime PASS.

Полные файловые манифесты и typed bindings находятся в JSON. Строка каждого манифеста: relative path, длина, SHA-256; SHA манифеста вычисляется по JSON отсортированных строк с separators comma/colon и обычным ensure_ascii=True. Для app/tests/schema relative root — server; для site — site-packages. SELF helper исключён из tests и закреплён отдельным полным SHA; отчёты находятся вне этих деревьев. Независимые счётчики, байты и SHA из прежнего B8 review сохранены; эта правка сверяет неизменность rows/pins относительно exact PR85 parent.

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

Конечные границы исходника: absolute deadline `started+180s`, soft work deadline `started+150s`; postcheck получает fixed target `min(started+180, first_post_entry+30)`, не более30s и только остаток абсолютных180s; повторное армирование не сдвигает этот target; CPU soft=hard150s, RAM2GiB, core0, FD96; максимум20k entries на дерево,16MiB на файл/JUnit/JSON,256MiB на дерево; pytest stdout+stderr 8MiB и phase aggregate 4MiB;64MiB/128 файлов суммарно evidence+scratch, free floor 8GiB до/после. JSON writer перед каждым open резервирует один файл и точное число encoded bytes, в том числе на FAIL; output/JUnit резервируются отдельно. Trace/sections/imports/cache hits/denials ограничены (32KiB phase trace,2048 chars/section,8 sections/report,4096 imports,256 cachehits,64 denials/8 frames). ROOT должен оценить фактическую стоимость, границы здесь не проверялись исполнением.

Preapproval refusal не обещает receipt в ещё не принятые каталоги. SIGKILL/OOM/жёсткий CPU-limit не могут исполнить finally; переполненный admission может не допустить даже FAIL receipt. В этих случаях ROOT/controller обязан независимо сверить source/site/process/evidence census. Приёмка требует exit0, целого согласованного receipt и необходимых внешних проверок; частичный JUnit/schema/output или один status не подтверждают успех. Жёсткие лимиты и гарантия наличия receipt разделены явно.

B1–B7 первоначально проверены по A commit `8c31d7f79962d6958914a97492c0d47901a1580d`, SHA `28b0b7f6b3120b04fe93b21b143feb8c44e232d61fe8eef57360c4fbcdf55342`, и отчётам `159f5915f4f679caf0bf70f049a9a41b1132cab9`; их provenance сохранён в JSON. B8 найден координатором и независимо подтверждён в прежнем B8 follow-up: прежний SHA `937b3668aef208860ab8ea14b49caf13c1b8d9367932c809a051ee3a712386c2` относится только к ошибочному Path-порядку, который ставил `aiofiles/__init__.py` перед `aiofiles-24.1.0.dist-info/INSTALLER`. Глобальная сортировка строк и независимое чтение filesystem дают канонический SHA `49071b9c07b1fe65baf287e952e9b3c98907ee92f9434c0f30d151d513f8bec2`, 7245 файлов и 169999373 байта. Helper исправлен отдельным коммитом `2f14a1840f451fc8784e30b904e70a307e672d16` (интегрирован координатором как `7f954a80af5b5f8ba5098c13d7d5deef861d0d8a`, bytes совпадают) одной заменой SHA; другие bytes, 77 versions и 26/78 ожидаемых counts не менялись.

Исторические B1–B8 рассмотрены по frozen source `2f14a1840f451fc8784e30b904e70a307e672d16`; runtime controls не запускались. Ссылки следующей таблицы относятся к этому историческому helper commit/SHA; актуальные строки нового helper приведены в JSON sourceReferences. Их evidence сохранён, а изменённый профиль теперь завершает процесс при любом исключении callback (подробности F9/F10 ниже).

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

F9: audit event `open(path, mode, flags)` не содержит `dir_fd`. В родителе lexical относительного пути разрешался от cwd, хотя native open мог разрешить его от directory FD. Исходный контрпример: каталог stdlib/json, затем `../email/parser.py` с write/truncate при ложном lexical-попадании в scratch/email. Это описание исходника; directory FD не получался, syscall/контрпример/контроль не выполнялись.

Новый `guarded_open` отвергает любой non-None `dir_fd` (включая -1), integer path, O_DIRECTORY/O_PATH и существующий каталог до native-вызова; после lexical-проверки передаёт абсолютную строку. `posix.open` остаётся исходным native object. `Boundary.profile_event` сравнивает каждый его `c_call` по identity, включая prebound aliases, и допускает только exact active frame, code/globals/closure wrapper. Audit сохраняет read/write/secret/pyc политику и дополнительно отвергает каталоги и отсутствие profile gate. Одной monkeypatch os.open для этого доказательства недостаточно.

Перед closure выполняются конечные `/proc/self/fd` и `/proc/self/task` census: не более128 FD entries, единственный исчезнувший после закрытия scandir iterator non-stdio FD допустим как transient listing entry; любой живой FD>2 и directory stdio0..2 отвергаются. Task census ограничен двумя entries и требует один kernel thread. По native identity запрещены `_thread.start_new_thread`/`start_joinable_thread`, включая aliases/threading.Thread.start; imports threading и locks не запрещены. Trusted manifest `os.scandir`/`os.walk` не патчатся; internal directory enumeration C code не превращается в общее разрешение raw posix.open. Заимствованный directory FD не даёт пропуска native gate.

F10: прежний одноразовый SIGALRM поднимал TimeoutError, который `postcheck.check` мог поглотить вместе с BaseException. Новый `AbsoluteDeadline.control` сохраняет исходный monotonic `started+180`; soft work handler до своего исключения ставит native SIG_DFL и kernel ITIMER_REAL на оставшееся абсолютное время. Первый вход finally фиксирует post target `min(started+180, first_post_entry+30)`; hard/post повторные вызовы используют остаток этого же target, stage work допустим лишь один раз до post. Даже при раннем окончании work postcheck ограничен30s. Минимальный положительный интервал при истечении не отключает timer. Fatal SIGALRM не проходит через Python catch/check. `_signal.signal`, `alarm`, `setitimer`, `pthread_sigmask` защищены identity/frame/code/globals/closure gate; SIGALRM не должен быть унаследован заблокированным. Чужая смена handler/timer/mask приводит к fatal refusal. Так как исключение из profile callback в CPython снимает profile, любое исключение callback, включая прежние service/query denials, теперь вызывает pinned native `posix._exit(1)` и не возвращается к caller. Обычные audit/test/framework/work FAIL по-прежнему доходят до feasible postchecks; fatal profile refusal, SIGALRM, SIGKILL/OOM/hardCPU не обещают receipt. ROOT/controller обязан независимо проверить process/source/site/evidence census и exit status, отсутствие/неполный receipt не принимается.

F11: прежние filename/co_name/globals.__name__ можно повторить у другого compiled кода. Для actual checker `FrozenSource.exec_module` получает проверенный hash-pinned module code; единственный immediate `git` code object из его co_consts должен совпасть с actual function.__code__ после обычного exec модуля. Сохраняются actual module, git function, code и globals dict identities. Bridge до cache lookup требует exact caller code+globals, неизменные module.git/function code/globals; postcheck повторяет integrity. DTO, factory, normalizers, assertions и checker.git исходник не заменены.

Следующие случаи — **только source reasoning и ожидаемая будущая приёмка, все NOTRUN**; ни proof-функции, ни скомпилированный код для них не исполнялись.

| Случай | Ожидаемый исход по ветвям исходника |
|---|---|
| Wrapper с dir_fd/int path, directory flags или existing-directory path | Отказ до native open |
| Direct posix.open/prebound native alias, в том числе borrowed directory FD | c_call identity gate: fatal refusal до syscall |
| Inherited live FD>2 / stdio directory / второй kernel thread | Отказ preclosure census |
| Python thread start через raw alias или Thread.start | Fatal native identity denial; locks/import threading остаются возможны |
| Approved regular frozen source/site/stdlib read | Wrapper и audit допускают, остальные политики сохраняются |
| Owned regular evidence/scratch write | Wrapper и audit допускают при прежних admission/path bounds |
| Directory-relative mkdir | Прежний точный audit dir_fd denial сохранён |
| Pinned3044 pyc manifest hashing | Только прежняя postcheck/inventory/tree/bounded_bytes цепочка; loader/framework pyc read отвергается |
| Ordinary bounded stdout/stderr и уже открытые stdio streams | Не добавлено общего FD-open разрешения; прежний bounded output policy сохранён |
| Catchable soft work timeout / обычная postcheck ошибка | Soft handler сначала армирует fatal remainder; postcheck получает fixed min(absolute180,entry+30), ordinary errors не отменяют kernel deadline |
| Чужой signal/alarm/setitimer/pthread_sigmask alias или пойманный прежний profile denial | Fatal refusal, продолжения без profile нет |
| Forged git с теми же filename/name и новым code/globals | Bridge identity denial до выдачи cache |
| Actual pinned checker.git с exact12 command tuples | Actual code/globals identity проходит; per-byte cache pins/call bounds сохраняются |

Это proof для проверенного Python-кода и фиксированных native dependencies CPython3.13.7/Linux. Предполагаются неизменность trusted helper/closures, отсутствие внешней подмены файлов/FD во время preclosure census и отсутствие незаявленных native thread/syscall путей в pinned extensions. Native/Rust threads, C extensions с внутренними неаудируемыми syscalls, внешние процессы/FS races и произвольная порча Python object graph не получили OS sandbox guarantee. Фактические профили/сигналы/сроки/совместимость framework не измерены. Ни syscall proof, ни ordinary framework positive control не запускались.

Статически сверены неизменные AST units manifests/constants, sources/inventory/tree/expected_ids, исходные12/26 tests, run_pytest/schema_exports/write_json/artifact_scan/prepare/sealed cache и первые пять resource limits относительно exact PR85 parent. Full tests manifest по-прежнему исключает SELF; FROZEN_SITE canonical49071b9…, 77 deps,22 bindings,26 IDs/78 phases,12 real Git tuples и sealed cache не переписывались. AST/compile выполнены лишь как синтаксическая проверка без исполнения; B1–B8 evidence сохранён в JSON.

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
