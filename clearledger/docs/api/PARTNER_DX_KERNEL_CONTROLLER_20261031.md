# Внешний controller и native launcher Partner DX

31.10.2026. **SOURCE CODE FROZEN / SOURCE REVIEW COMPLETE; runtime и C compilation NOTRUN.** Четыре исходных файла статически сверены автором, координатором и независимым reviewer C. Проверки исполнения отсутствуют; исходный код не является OS proof. Controller, launcher, candidate, компилятор, helper, тесты и kernel controls не запускались. PR91, его helper/schema/reports и исходные pins остаются неизменными.

## Предмет и полномочия

Основной оркестратор передал отдельную source-реализацию внешнего controller/F сообщением `msg_d8df5bfac6d9`. Единственный checkpoint перед кодом — `msg_6481915e9890`; решение `msg_41baa70a3b6b`, подтверждённое `msg_67f189f092cc`, разрешает шесть новых файлов с обязательной коррекцией механизма exec. Parent — `Electro-Interfaces/ClearLedger@59c23b6561a1417ec11f14a7cbab1701dedef9df` (draft PR91). Ветка интеграции — `MagLook/partner-dx-kernel-controller-20261031`.

Принятый private contract: `/srv/projects/preview/partner-dx-kernel-admission-contract-20261031/contract.md`, SHA-256 `55cb90ea165f547a0afc4234acf42261eb7b8974d127cb44d18f5b63bd15d9b0`. Фактические закрытые A/F shapes и clock erratum читаются в неизменном PR91: `clearledger/docs/api/PARTNER_DX_KERNEL_ADMISSION_V1.schema.json` и `clearledger/server/tests/partner_dx_metadata_approved.py`. Поля clock обязательны: только целые миллисекунды `CLOCK_MONOTONIC_MS`, общая actual time namespace controller/candidate. Дорешенческий текст private contract не переписывался.

| Владелец | Только новые файлы |
|---|---|
| A, `task_798582a8779d` / `ctx_9ea46515798a` | `clearledger/tools/partner-dx-kernel-v1/controller.py` |
| B, `task_704a363b1c8c` / `ctx_fa7c1baefd5d` | `clearledger/tools/partner-dx-kernel-v1/launcher.c`, `launcher_protocol.h`, `seccomp-policy.json` |
| Третий координатор, Run `run_1e4d8306c273` | этот Markdown и одноимённый JSON с source manifest |

Не меняются приложение, DTO, права, flags, SDK, CI, общие API-спецификации, БД, старые PR/worktrees и ai-base. C-бинарник в пакет не входит: его будущая компиляция и независимый binary SHA принадлежат ROOT. Source-компиляция Python допустима только в памяти без исполнения результата; ни pure validator/controller functions, ни C compiler не вызываются.

## Механизм и граница доверия

Внешний Python supervisor и доверенный C broker остаются вне candidate. Native bootstrap создаёт единственный candidate PID1 непосредственно через `clone3` с отдельными mnt/net/pid/ipc namespaces и отдельным cgroup v2; user/time namespaces сохраняются общими. Privileged capability, поддержка clone3/cgroup/USER_NOTIF/O_TMPFILE и реальные ABI/CPython пути пока UNKNOWN. Неподдерживаемая primitive должна приводить к отказу без ослабленного fallback.

Все mounts и pivot_root заканчиваются до приложения. Rootfs минимален, отдельно измерен и независимо pinned. Source/native/venv/policy/admission/cache видны RO; старый root отсоединён, его handles в candidate не остаются. Один tmpfs имеет общий максимум64MiB/133inodes: root UID0 mode0755 и ровно четыре sibling dirs candidate UID mode0700. Cwd/upload получают RO self-bind mounts тех же subdirs; evidence/scratch остаются RW. Дополнительного inner init/child для remount нет.

До первого candidate exec устанавливаются реальные hard limits CPU150s, AS2GiB, file16MiB, core0, NOFILE96, cgroup memory2GiB/swap0/pids1; empty supplementary groups, точные ненулевые real/effective/saved/fs UID/GID, все capability sets/bounding/ambient0, NoNewPrivs1 и actual seccomp. После drop нет получения новых привилегий, mount/namespace/process/network/hardlink escape. Возможные allowlist compatibility failures не превращаются в разрешение всех syscalls.

## Существенная source-находка до кода: execveat

Исходный вариант разрешал `execveat` на FD96 с `AT_EMPTY_PATH`, рассчитывая на CLOEXEC и hard NOFILE96. A (`msg_04cbacf09bcc`), B (`msg_e95d98ad4698`) и ROOT независимо отвергли этот reasoning до реализации: абсолютный pathname игнорирует dirfd, а AT_EMPTY_PATH разрешает пустую строку, но не требует её. После закрытия96 вызов с абсолютным путём всё ещё обошёл бы такой cBPF predicate. Этот контрпример **не запускался**.

Принята обязательная коррекция: actual `SECCOMP_RET_USER_NOTIF` и stateful разрешение единственного bootstrap exec доверенным внешним broker. Listener отсутствует у приложения. До первого CONTINUE broker связывает notification ID/native PID/clone identity с ожидаемым single-thread bootstrap и точным initial syscall/ELF; единственный permit расходуется **до** CONTINUE. Любой последующий exec, иной первый syscall, invalid notification, утрата broker/listener, timeout или failed initial exec означает kill/reject без retry. Это не универсальная pathname security decision через CONTINUE и не secret pointer/IP allowance. TOCTOU premise ограничена единственным доверенным native bootstrap до первого запуска untrusted candidate; в этот момент нет иных candidate threads/handlers.

FD96/CLOEXEC остаётся частью передачи initial ELF; high CLOEXEC channels закрываются на exec и не могут быть воссозданы при hard NOFILE96. Их роль не подменяет stateful exec authorization. Notification receive не должен блокировать независимый внешний watchdog/physical monitor. Особая семантика PID1 и SIGALRM не считается внешней гарантией wall180s.

## Измерения A и seal

Доверенный native bootstrap после final mounts/identity/security setup читает реальные mountinfo/status/ns/stat/statvfs/limits. Candidate не вызывается для attestations. Parent формирует A по этим фактам, свежим физическим before samples и независимым input pins. Admission file — regular/nlink1, owned candidate0400, отдельный parent0700 на RO layout; cache остаётся0600. Заранее открытый внешний writer заполняет admission после замеров mounts, fsync/close завершаются перед передачей независимого SHA(A)/nonce/env. Запись bytes в уже смонтированный файл не меняет mount topology; после измерения mount transitions запрещены.

A ограничен65536 bytes, канонический ASCII JSON с одним LF; hash включает LF. Выдача/expiry и samples используют CLOCK_MONOTONIC_MS. A содержит before-наблюдение и обязательства внешнего мониторинга, будущие during/after значения не выдумываются. Nonce выдаётся однократно и связывает весь запуск.

## Бюджет controller и артефактов

Именованные controller logs до запуска нарушили бы `private_empty`/evidence whitelist неизменного helper. Принято локальное implementation-решение координатора (`msg_c69057a3cae1`, `msg_4749cc458469`): root-owned unnamed O_TMPFILE reservations на **том же** tmpfs, без entries в четырёх private dirs и без доступа candidate к FD. Reserve: combined raw stdout/stderr8MiB, bounded metadata4MiB, final64KiB и artifact manifest64KiB. Их реальные blocks/inodes расходуют общий pool64MiB/133inodes; это консервативно уменьшает доступный candidate бюджет. Нет скрытой второй candidate-writable области. При неподдерживаемой reservation primitive — отказ.

После завершения candidate итоговые logs/files/F входят в общий logical budget64MiB/128 regular entries/file16MiB; unused reservations сокращаются до реально записанных bytes. Финальный bundle сохраняется только в явно заданный root-owned external output с физическим мониторингом до/после сохранения. F находится вне writable candidate. Отсутствующий бюджет или факты не заполняются фиктивными значениями: accepted F не создаётся, missing/incomplete evidence трактуется как отказ.

## Внешний final F

Для accepted F нужны реальные wait/exit/signal, полные source/runtime pre/post hashes, unchanged policy/rootfs/runner/cache, candidate artifacts census, output budget, реальные physical before/during/after samples и их storage identity, gap≤1500ms при периоде1000ms, независимый wall180s/pidfd kill и подтверждённая единственная exec transition. Артефакт helper с `EXTERNAL_FINAL_PENDING` остаётся workload output; он не заменяет измерения controller.

F строго соответствует неизменной закрытой schema PR91. Нельзя дописывать UNKNOWN/default0 вместо неизвестных exit/samples/hashes ради заполнения формы. Rejected F допустим только при известных mandatory facts; иначе внешний диагностический отказ без accepted F. Ни listener EOF, ни candidate exit0 сами по себе не доказывают successful initial exec или safety.

## Проверки и ограничения

Источник каждого будущего вывода фиксируется как исходники, сообщение ROOT, неизвестно или предложение. Точные freeze commit/path/line/SHA и выполненные статические проверки приведены ниже и в JSON. Исходники frozen; данный Markdown не закрывает ни kernel availability, ни безопасность работающего процесса. Слова об установке границ выше описывают будущий путь исходника, а не выполненные действия авторов.

ROOT должен отдельно скомпилировать immutable C source, проверить actual binary/policy и выполнить positive/negative controls: namespaces/mounts/UID/caps/NNP/seccomp/rlimits/cgroup, actual RO cwd/upload, исчерпание quota/log budget, host-floor breach/gap, output overflow, broker death, failed/second exec и absolute-path execveat при закрытом96, timeout/kill, неполный F, source/runtime mutation и nonce replay. Все эти controls здесь **NOTRUN**. Полный список будет связан с конкретными source places, без исполнения сценариев авторами.

Прежние26 metadata cases/78 phases не запускались. PR91 frozen manifests относятся к base725bee и не repin текущего whole-final ROOT состава. Исходные M00–M19 и11 общих критериев остаются без сокращений и без локального закрытия. Принятие source этой новой оснастки не означает приёмку полного API, SDK или реального партнёра.


## Frozen поставка и evidence

Общий source commit `cc02452e83b28f1c1fc76f2209e31d2580fe5cbd` содержит четыре NEW code/data paths поверх exact PR91. A authored `644eaca400c38a7b5e81288373eab7287270918b` интегрирован как `4bfb57608210a1ba06ed94a5c97a8c54ce100561`; B authored `29fa86507505273b8fe2af7f455bc7f59baee906` интегрирован как общий source commit. Авторские и интегрированные raw bytes совпадают. Следующий docs commit добавляет только два отчёта; будущий собственный commit/hash JSON в его bytes не выдумывается. Полный внешний SHA пакета находится в квитанции координатора.

| Путь в `clearledger/tools/partner-dx-kernel-v1/` | Байты / строки | SHA-256 |
|---|---:|---|
| `controller.py` | 68547 / 1282 | `80b67d45791f759e197271cd0e83332201c41ee0bd5c77d8b479e632d09903b1` |
| `launcher.c` | 66691 / 843 | `9da5de6b4f695109d6fc842bfce414e3297e3cc25a73b79e93f8c01adf2d11fe` |
| `launcher_protocol.h` | 3520 / 68 | `cde31bbb39f32dc7c4b541af3e861b830b6b9e6ccf8df25c10749a3aff225f59` |
| `seccomp-policy.json` | 1802 / 1 | `330fb9a4353ea0f922664858c12b4b6d4aae602e5ebc4835e294e658c1f3822f` |

Проверки координатора: raw Git blobs==working files==author hashes; exact parent/delta; AST и compile в памяти только controller.py без исполнения; imports только stdlib; canonical policy bytes==ASCII sorted compact JSON+LF; POLICY_SHA в C==actual policy SHA; numeric allowlist C==JSON, без дубликатов; отдельный runtime ELF cap64MiB в трёх read-only hash calls при неизменном writable file16MiB; Git mounts отсутствуют. C не парсился компилятором, не компилировался и не запускался; BPF не загружался и не эмулировался.

Независимый reviewer C `task_8339d6308f38` / `ctx_cdac996ad684` повторно прочитал общий frozen source и подтвердил отсутствие оставшихся существенных source-находок сообщением `msg_abaf22548190`. Его private отчёт и окончательная шестипутевая scope-квитанция сохраняются отдельно в preview/handoff, чтобы не создавать цикл SHA между review и package JSON. Это дополнительное статическое чтение, не runtime-приёмка ROOT.

## Исправленные source-находки

| ID | Проблема | Frozen исправление / ограничение |
|---|---|---|
| C0 | Числовой FD96 не запрещал absolute-path execveat | Stateful outside USER_NOTIF; permit consumed before единственного CONTINUE; subsequent exec deny |
| C1 | inventory_tree arity mismatch | Current controller uses two return values; tree_sha remains explicit three-value wrapper. |
| C2 | Candidate Git directory mounts | mount_setup binds source/native/venv only; Git config is outside provenance only. |
| C3 | Image digest grammar mismatch | C changed rootfs digest to sha256: + 64 lowercase hex, matching A/immutable PR91 Image grammar. msg_1035c90967d7. |
| C4 | Full native trace rejected by one-BEFORE/one-AFTER assumption | A now accepts monotonic BEFORE* DURING+ AFTER*, retains all gaps and binds admission-selected BEFORE. msg_656a47f711f6. |
| C5 | PDEATHSIG parent death race across UID drop | C uses pinned broker pidfd at temporary FD98, polls after rearm, closes before filter; main rechecks original parent after prctl. msg_48d350734f52. |
| C6 | Whole input parent binds expose unpinned siblings | A and B now enforce singleton input parent listings; placeholder requires empty admission parent. msg_193790ed1a8a. |
| C7 | Mandatory immutable helper setitimer omitted from native allowlist | C BPF and policy JSON now allow only setitimer syscall38 ITIMER_REAL full64-bit selector0; independent outside timer unchanged. Source read, no execution. |
| C8 | Final trace snapshot races native monitor aggregates and phase boundary | Native stops and bounded-joins sampler under armed independent timer, takes final sample, persists one frozen trace and emits FINAL from same aggregates. Phase read moved under sample lock. |
| C9 | Real native ELF exceeds writable artifact limit | Reviewer independently stat read31765832bytes. B now separates64MiB readonly ELF hashing cap at three sites; artifact/rlimit16MiB unchanged. |
| C10 | Actual venv interpreter is a relative link chain | Reviewer independently readlink: bin/python -> python3.13 -> exact NATIVE/bin/python3.13. A now bounded8hop alias inspection constrained to venv bin then exact native ELF; all link texts covered by independent full-tree pins. |
| C11 | DURING sample predates initial committed exec | Independently read physical_sample/notification_once/observe_exec: preCONTINUE BEFORE; unknown transition rejects; kernel ELF observation precedes exec_confirmed + physical sample; every DURING bracketed by pinned pidfd live polls; overlapping-exit observation repeated as actual AFTER; samples0 rejects. Sent confirmation msg_b950329efe1e. |

Каждое место в таблице связано с repository/общим source commit/path/line/SHA в JSON. C9/C10 дополнительно подтверждены только filesystem stat/readlink: существующий native ELF имеет31765832 bytes; `.venv/bin/python` указывает на `python3.13`, затем на exact native ELF. Бинарник не запускался. Никакой из отрицательных сценариев C0–C11 не исполнялся.

C11 не заполняется условным «during»: pre-CONTINUE sample относится к BEFORE; DURING требует уже наблюдавшийся actual exec и pidfd-bracketed живой процесс. Быстро завершившийся workload без достаточного реального DURING, либо неоднозначный transition window, отклоняется. Это намеренное ограничение evidence, не обещание отсутствия ложных отказов. Таймеры/ABI/NSS/getpath и производительность должны быть измерены ROOT.

## Подготовка ROOT к будущей проверке

Это внутренний harness для ROOT, не инструкция партнёру и не выдача административных API-прав. Следующие действия только планируются; авторами они не выполнялись.

1. Проверить exact source commit и шесть NEW paths; отдельно скомпилировать frozen C с Linux headers/glibc/pthreads и сохранить независимый SHA actual ELF. В пакете нет готового бинарника, его SHA не выдуман. Требуются Linux x86_64, clone3/CLONE_INTO_CGROUP/cgroup v2 с уже доступными pids/memory controllers, pidfd/USER_NOTIF/CONTINUE и нужные привилегии вне candidate. Rootless, отсутствующие primitives и неподдерживаемая physical filesystem дают отказ.
2. Предоставить independently measured minimal rootfs, содержащий все mount targets и `/.oldroot` заранее. Rootfs не строится этим controller и не должен мутировать при подготовке mounts. В нём нужны отдельно pinned ELF loader/runtime dependencies и минимальные NSS/passwd/group записи для actual UID/GID/HOME; никакие реальные secrets/home/host cgroup не передаются. Source snapshot `.git`-free; actual Git reference directories читаются только снаружи. Native/venv путям требуются exact PR91 absolute locations. Venv interpreter resolver допускает bounded pinned chain только внутри VENV/bin до exact native ELF.
3. Подготовить separate singleton cache/policy parents candidate0700: cache0600 и policy0400, regular/nlink1. Для admission предоставить только отдельный **пустой parent candidate0700**; controller эксклюзивно создаёт в нём empty admission0400 через admission_placeholder. Заранее созданный admission-файл отвергается. Input parent binds не должны скрывать незакреплённые siblings. Четыре work dirs native создаёт только на новом tmpfs. Nonce journal — отдельный durable private root-owned0700 каталог, который может содержать прежние claims: его нельзя очищать или удалять старые записи, в том числе после failed launch. Только final/archive должны быть отдельными первоначально пустыми private root-owned0700 каталогами для каждого запуска.
4. Независимо сформировать canonical controller config и его raw SHA. Верхние поля ровно `format`, `native`, `pins`, `launcher`, `nonce_dir`, `final_dir`; тип/порядок25 native LP fields и opcode contract заданы header и JSON этого отчёта. Ожидаемые source/native/venv/rootfs/controller/launcher/cache/policy/runner/python/schema pins задаёт ROOT, их нельзя просто вывести и объявить доверенными автоматически. Текущая реализация поддерживает один независимо проверенный local physical storage, покрывающий все snapshots/runtime/evidence/bookkeeping; большее покрытие не имитируется.
5. Сначала независимые positive/negative kernel controls, включая absolute-path execveat при закрытом96, death/timeout/gap/quota/output и insufficient evidence. Только после их приёмки рассматривать запуск неизменного helper metadata26/78 на exact PR91 composition. Текущий whole-final integration иной; repin — отдельная reviewed работа ROOT, обходом несовпадения pins заниматься нельзя.

Будущий opt-in интерфейс supervisor, **не выполненная команда**:

```text
<REVIEWED_STDLIB_PYTHON> -I -S -B <FROZEN_SOURCE>/clearledger/tools/partner-dx-kernel-v1/controller.py --execute-root-approved-kernel-controller-v1 /absolute/reviewed-config.json <INDEPENDENT_RAW_CONFIG_SHA256>
```

Native broker принимает только `--broker-v1` и пустой inherited environment; его запускает supervisor по независимо pinned binary path. Candidate argv/env фиксированы, arbitrary shell/program не принимаются. Полный закрытый input descriptor и30 обязательных будущих control-сценариев находятся в JSON.

## Приоритет и передача основному

Можно независимо рассматривать source-поставку: конкретные controller/native/bootstrap/policy/protocol, сохранённые PR91 bytes и привязанный статический review. P0 остаётся у ROOT: сборка actual C ELF и проверка headers/ABI, provision проверенного minimal image/config, kernel availability и реальные isolation controls. P1 после их приёмки: original26/78, полный evidence A/F, затем отдельный whole-composition repin. P2: применение подтверждённых результатов к API/SDK/партнёрскому сценарию. Ни одна из этих будущих проверок не закрыта локальным чтением.

Оба автора завершили source-задачи; merge, выпуск, CI/workflow actions, Docker/SQL/SSH/browser/HTTP, изменение flags или ai-base не выполнялись. ROOT не получал от этой поставки runtime GO. M00–M19 и11 общих критериев не заменяются30 локальными control-сценариями.
