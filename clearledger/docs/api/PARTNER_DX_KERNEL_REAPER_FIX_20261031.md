# Внешний владелец cgroup: исправление PR92

**SOURCE FROZEN / локальное независимое чтение завершено; review основного ожидается. C compilation/runtime/controls NOTRUN.**

Отдельный source-пакет по задаче ROOT `msg_b722dcc067d9`. База `Electro-Interfaces/ClearLedger@4e1a00692930d20934bd883365241602467879b4` (draft PR92) сохранена. Код автора `1fa494079529286ae1f3ea2144773826c43a2ab9` перенесён без изменения bytes как `696bd654a0632973765cf23da32b499d982c771b`. Ветка `MagLook/partner-dx-cgroup-reaper-fix-20261031`; дата имени пакета сохранена от начала31.10.2026, фиксация выполнена01.11.2026 МСК.

## Вывод и предмет приёмки

Подтверждено исходниками: новый внешний controller владеет exact cgroup до старта broker; после каждого нормального исхода broker, включая fatal/_exit/watchdog/SIGKILL, его finally требует положительной остановки и пустоты перед удалением своего ресурса. Проверка результата pidfd_send_signal отделена от доказательства завершения. Accepted F допускается после подтверждённой очистки. Это описание исходного пути, а не выполненная OS-проверка.

PR92-A-001 (P2) был пробелом очистки: `launcher.c:551` создавал cgroup, `fatal:91–96`/`safety_tick:462–467` завершались через `_exit`, единственный `rmdir:841` стоял после successful FINAL; `controller.py:1239–1255` только останавливал/закрывал broker. PR92-A-O01 отдельно указывал на игнорирование pidfd result и отсутствие CAP_KILL в required caps. Escape, оставшийся живым candidate и false F прежним review не доказаны. Эти старые места относятся только к frozen PR92 base, новые места ниже относятся к code commit `696bd654a0632973765cf23da32b499d982c771b`.

## Scope, источники и ограничения

Ровно три изменённых исходника и два новых отчёта. Приложение, серверные обработчики, права, flags, SDK, CI, общие API-спецификации, БД, ai-base и чужие WIP не меняются. PR91/PR92 worktrees/refs/reports остаются frozen. Это внутренняя оснастка ROOT; партнёру не выдаются административные права или инструкция запуска privileged broker.

Метод: Git/filesystem, чтение исходников, Python stdlib AST/hash/JSON и compile в памяти без exec. Ни приложение, helper, controller, launcher, pure validator, тесты/PoC/controls/BPF, C compiler/preprocessor/formatter, Node/SQL/SSH/Docker/browser/network не запускались. Ни один timeout, syscall, kernel primitive, ACL, реальный API или final consumer этим чтением не проверен.

| Файл относительно репозитория | Байты / строки | SHA-256 |
|---|---:|---|
| `clearledger/tools/partner-dx-kernel-v1/controller.py` | 85244 / 1589 | `086121d9b3c2aa06a112d72f5533047faee2bbb883b003360d234780341f99fb` |
| `clearledger/tools/partner-dx-kernel-v1/launcher.c` | 71255 / 902 | `a47809b7413974a7380e4a8e410560dfbdd23bc426c033ea5846b8480b791599` |
| `clearledger/tools/partner-dx-kernel-v1/launcher_protocol.h` | 5037 / 90 | `c923ed750b39011172deeb6a32330a0215478834a53e2b4f819b3328052861cd` |

## Реализация и доказательства

Во всех следующих строках repository `Electro-Interfaces/ClearLedger`, commit `696bd654a0632973765cf23da32b499d982c771b`; классификация **подтверждено исходниками**. Точные raw-span SHA находятся в JSON. «Подтверждено контрактом» относится только к неизменной закрытой schema A/F PR91; это не подтверждение kernel enforcement.

| Механизм | Точное место | Что установлено чтением |
|---|---|
| Владение до опасного окна | `controller.py:665–809` | До mkdir проверяются SIGCHLD DFL/единственный thread-waiter/CAP_KILL, writable cgroup2/domain и parent memory+pids. Parent FD/name/nonce существуют заранее; successful exclusive mkdir даёт witness, scoped signal mask закрывает bookkeeping окно. Exact retain retry ограничен, fchmod0700/readback явные. EEXIST не принимается за своё. |
| Передача owner broker | `controller.py:893–960`; `launcher_protocol.h:9–57`; `launcher.c:580–619,813–815` | Wire version2, CONFIG затем OWNER6 LPs, FD100/101, nonce/name/dev+ino bind; broker только проверяет и использует scope. Candidate прежним close_range99+ теряет эти FD. Никакого native mkdir/unlink cgroup. |
| Сигнал и actual stop | `launcher.c:93–125,636–657,791–815`; `controller.py:1023–1072` | CAP_KILL, pre-CONTINUE signal0 после UID drop, pidfd return/errno и ESRCH отдельно. Numeric PID/PGID kill fallback удалён; failed pidfd_open до CONFIG закрывает pipe, затем actual wait. Успех сигнала не считается termination. PDEATHSIG/parent pidfd fallback прежние. |
| Удаление exact ресурса | `controller.py:814–871` | Positive broker WAITED либо доказанный NOT_SPAWNED; exact held/named parent+scope identity; cgroup.kill при необходимости; populated0 AND pids.current0 AND пустой procs; checked rmdir, retained inode nlink0 и exact-name absence. Неизвестное остаётся CLEANUP_UNCONFIRMED. |
| Барьер F и отказ | `controller.py:1421–1427,1455–1558,1579–1588` | Native FINAL/exit0 предварительны. Manifest содержит cleanup и связан SHA в неизменном F; publish после positive reap. finally выполняет reap и rollback неполного final даже при cleanup exception. Bounded diagnostic содержит фактическую REMOVED/NOT_CREATED/CLEANUP_UNCONFIRMED observation; потребителю требуется successful external controller exit, одного файла F недостаточно. |

## Traces отказов

| Trigger | Source path | Результат / предел |
|---|---|---|
| First postmkdir open/stat/chmod fail before broker | run finally -> CgroupOwner.reap -> exact retain_created witness -> empty -> own checked removal | Transient failure may recover; persistent identity/read failure unconfirmed; no F. |
| Before spawn / known posix_spawn failure | Broker NOT_ATTEMPTED/FAILED_NO_CHILD -> no_spawn -> own reap | No fabricated wait; only known no-child allows cleanup. |
| Ambiguous spawn interruption | Broker IN_PROGRESS without PID -> no_spawn false -> reap rejects | No unknown-as-termination; explicit ROOT recovery, no accepted F. |
| fatal/_exit, candidate nonzero/laterexec/overflow, native watchdog, forced broker death | Broker transport refusal -> finally Broker.kill actual wait -> CgroupOwner.reap cgroup.kill if needed -> triple empty -> rmdir/held unlink/absence | Reject+no accepted F, actual removal and baseline census remain future ROOT evidence. |
| Native successful FINAL/exit0 | Broker.finish positive wait -> owner.reap -> artifact manifest cleanup binding -> unchanged F -> controller exit0 | F barrier includes cleanup, actual mandatory facts and independent successful controller exit. |
| Cleanup/signal/wait/identity/empty/removal failure | finally observation CLEANUP_UNCONFIRMED -> failure diagnostic; rollback final if publication incomplete or owner not removed | No accepted F on unknown; no foreign scope removal; no automatic recovery claim. |

## Находки при чтении и устранение противоречий

| ID | Итог source | Runtime |
|---|---|
| PR92-A-001 | CORRECTED_IN_NEW_SOURCE_PENDING_MAIN_REVIEW: CgroupOwner до broker spawn; retained exact parent/name/nonce/dev+ino; all normal broker rejection/death paths go to external finally reap. Positive own empty/removal mandatory before F. | NOTRUN |
| PR92-A-O01 | CORRECTED_IN_NEW_SOURCE_PENDING_MAIN_REVIEW: Effective CAP_KILL checks, pre-CONTINUE pidfd signal0 probe after UID drop; return/errno retained, ESRCH and SIGNAL_SENT never termination; independent actual wait/empty plus unchanged PDEATHSIG. | NOTRUN |
| REAPER-REVIEW-NO-SPAWN | CORRECTED_BEFORE_FREEZE: Explicit NOT_ATTEMPTED/FAILED_NO_CHILD permit positive no-spawn cleanup; IN_PROGRESS remains unknown, pid=None is not termination. | NOTRUN |
| REAPER-REVIEW-PID-REUSE | CORRECTED_BEFORE_FREEZE: SIGCHLD DFL/sole-thread waiter before mkdir/spawn; native DFL/no-SA_NOCLDWAIT; numeric PID/PGID signal fallback removed entirely. Failed pidfd_open before CONFIG closes pipes and waits actual broker exit. | NOTRUN |
| REAPER-CREATION-WINDOW | CORRECTED_BEFORE_FREEZE: Held trusted parent/name/nonce precede mkdir; scoped mask until created witness; bounded exact retain retry; explicit fchmod0700/readback; recurring failure remains unconfirmed. | NOTRUN |

Независимый reviewer нашёл pre-spawn cleanup и inherited SIGCHLD/PID reuse candidates в WIP; автор исправил их до freeze. Координатор отдельно проверил ранний mkdir→handle и mode/readback. SIGINT bookkeeping передан reviewer и закрыт scoped mask. Эти находки не выдаются за эксплуатированные runtime дефекты. Независимый reviewer task_e501e99ae316 / ctx_3004c5944dff завершил чтение сообщением msg_62a1393edc28: открытых material findings в scoped frozen patch нет. Его26 raw evidence spans проверены координатором. Это локальная source-квитанция; ROOT ещё не принял новый пакет, runtime UNKNOWN.

Авторские NC01–NC22 сохранены полностью в JSON как **предложение / SOURCE_AUTHORED_NOTRUN**, с исходными IDs. Они пересекаются с R00–R19 и не являются42 выполненными проверками. Для NC02 одноразовый отказ и persistent failure разделены: при повторной невозможности наблюдения restoration не утверждается. NC15 pre-exec signal0 и поздний SIGKILL errno разделены в R08. NC19 default0755 с успешным fchmod может продолжить setup; actual chmod/readback failure требует отказа. Эти уточнения устраняют blanket wording из авторского inventory, не меняя frozen исходники или авторский отчёт.

## Статическая сверка

Git blobs == author raw == integration raw для3paths; exact parent/delta; AST/compile в памяти без exec, imports только stdlib; policy canonical raw и C POLICY_SHA совпадают; numeric PID/PGID kill calls0 и native cgroup mkdir/unlink0. Полные C функции filter_install, limits_and_identity, mount_setup, child_run и notification_once побайтно сохранены относительно PR92. Helper/schema/policy/oldreports и два оригинальных metadata/example test-файла совпали с base. C не компилировался, BPF не эмулировался.

## Граница trusted owner и неизвестные

Live external controller переживает смерть broker. Автоматическая уборка после смерти самого trusted controller (любой сигнал/default termination, не только SIGKILL), host loss, смерти всех owners, повторного прерывания cleanup или hostile external root mutation не реализована. Независимого guardian/durable identity recovery journal нет. Nonce journal обеспечивает одноразовость, но не превращается этим в журнал восстановления cgroup. При persistent primitive/identity/read/removal failure или ambiguous IN_PROGRESS/wait требуется ROOT recovery; нельзя удалять всё по prefix или объявлять cleanup success по отсутствию имени. Source deadlines не доказывают scheduling/syscall latency.

## Будущие controls ROOT

Все строки ниже **предложение / NOTRUN**. Для применимых postmkdir отказов нужны реальные REJECTED/no accepted F, exact identity, broker wait либо доказанный no-spawn, положительная пустота, actual removal и независимо восстановленный baseline census. Если факты недоступны, UNKNOWN сохраняется; графа ожидаемого результата не является квитанцией выполнения. Старые30 controls PR92 сохранены в неизменном отчёте.

| ID | Сценарий / trigger | Критерий приёмки | Статус |
|---|---|---|---|
| R00 | Positive lifecycle: Успешный workload с достаточными actual observations | Positive broker wait; exact own populated0/pids.current0/procs-empty; checked rmdir+held inode unlinked+absence; cleanup receipt bound by manifest before F; baseline census restored | NOTRUN |
| R01 | Immediately after mkdir: Одиночный отказ stat/open до сохранения scope handle, broker ещё не запущен | Повторное удержание только exact exclusive creation witness; пустота/удаление; чужой scope untouched; no accepted F; baseline census restored | NOTRUN |
| R02 | Missing late primitive: После exclusive scope creation отказ clone3/USER_NOTIF/O_TMPFILE/прочего обязательного primitive | Broker positively stopped/waited; exact scope killed if populated, positively empty and removed; no F; census restored | NOTRUN |
| R03 | Candidate nonzero: Наблюдаемый workload exit !=0 или signal | Rejected diagnostic, no accepted F; actual wait and exact scope removal; baseline census restored | NOTRUN |
| R04 | Subsequent exec: Повторный exec, включая absolute-path execveat при закрытом96 | No second CONTINUE; rejection checked separately from actual stop; cleanup+baseline census | NOTRUN |
| R05 | Output overflow: Combined stdout/stderr >8MiB | Bounded refusal, no F; independent stop+positive own scope cleanup+census | NOTRUN |
| R06 | Watchdog: Wall/CPU/floor<8GiB/gap>1500ms | Native fatal/_exit cannot bypass external reap; actual outcome/empty/removal+census, no F | NOTRUN |
| R07 | Forced broker death: SIGKILL native broker после создания scope, до handshake и после candidate clone/exec | Live external controller positively waits broker, cgroup.kill if necessary then positive empty/removal; no F; census restored | NOTRUN |
| R08 | Signal authority: CAP_KILL отсутствует либо signal0/native pidfd_send_signal даёт EPERM | CAP_KILL missing или pre-exec signal0 EPERM: отказ до untrusted execution. Поздний non-ESRCH SIGKILL error: сохранить errno и rejected; separate actual wait/positive empty/removal mandatory; permission != termination, no accepted F. | NOTRUN |
| R09 | ESRCH: pidfd_send_signal returns ESRCH during rejection/exit race | ESRCH is not termination proof; separate actual wait/positive empty/removal mandatory; no fabricated success | NOTRUN |
| R10 | Unknown broker wait: ECHILD/timeout or otherwise unconfirmed wait ownership | Reject, no accepted F; never remove potentially clone-capable live broker scope or claim baseline restoration; ROOT recovery required | NOTRUN |
| R11 | Foreign/replaced scope: Name collision EEXIST or altered held/named parent/scope dev+ino | Never adopt/delete foreign cgroup; reject without prefix scans; own unresolved identity recorded as unknown | NOTRUN |
| R12 | Cleanup failure: cgroup.kill/write/read/empty deadline/rmdir/unlinked/absence verification failure | Reject and no accepted-looking F even on later publication/finally failure; unknown cleanup remains unknown; actual residual evidence retained | NOTRUN |
| R13 | Wire/FD mismatch: Wrong OWNER nonce/devino/name/FD/protocol version or unexpected inherited descriptor | Fail closed; candidate cannot retain FD100/101; external cleanup restores baseline; no F | NOTRUN |
| R14 | Scope membership: cgroup.procs differs from actual candidate PID or pids.current!=1 | No permission based on claimed scope; native reject, external actual cleanup and census | NOTRUN |
| R15 | Controller/host loss boundary: SIGKILL всего external controller либо host loss | Outside live-owner guarantee; do not assert automatic cleanup/accepted F; independent ROOT recovery contract and durable identity evidence required before any stronger claim | NOTRUN |
| R16 | No-spawn cleanup: После owner.create Broker.start: pipe/open/pin/FD bounds/known posix_spawn failure до фактического broker | Явное положительное NO_SPAWN разрешает уборку exact own empty scope; ambiguous spawn отдельно unknown; no F; baseline census restored | NOTRUN |
| R17 | Kernel mode / fchmod failure: cgroupfs default mode игнорирует mkdir0700 либо own fchmod/readback fails до spawn | При kernel default0755 explicit own fchmod0700/readback допускает дальнейший reviewed path; default mode сам по себе не отказ. При actual fchmod/readback failure до spawn — no F и positive empty/removal только собственного exclusive root-owned nonwritable scope; baseline census restored при наблюдённых cleanup facts. | NOTRUN |
| R18 | SIGINT creation bookkeeping: SIGINT между mkdir success и записью exclusive creation witness | Прерывание отложено на минимальное creation/bookkeeping окно, затем доставлено; живая finally cleanup знает own scope; no F, census restored; смерть всех trusted owners вне гарантии | NOTRUN |
| R19 | Inherited SIGCHLD and pidfd open failure: Controller inherited SIGCHLD=SIG_IGN/auto-reap, broker exits around spawn/pidfd_open; отдельный pidfd_open failure | До mkdir/spawn явно нормализован SIGCHLD и проверен единственный trusted waiter; native проверяет DFL/no-SA_NOCLDWAIT; numeric PID kill fallback отсутствует. Failed pidfd_open до CONFIG закрывает pipe и требует actual bounded wait/EOF refusal; unknown не cleanup success; foreign signal запрещён. | NOTRUN |

## Приоритетный план и передача основному

| Приоритет / владелец / слой | Работа и критерий |
|---|---|
| P0 / ROOT source review / contract/source | Review exact5path diff against frozen PR92, wire v2/controller+launcher pairing, closed A/F unchanged and TCB qualifications; independently accept or return concrete findings. |
| P0 / ROOT toolchain/kernel acceptance / future verification | Separately authorize and establish immutable native binary/config/rootfs identity; actual isolation/kill/wait/cgroup positive and negative controls, baseline census, output/physical limits. Nothing executed here. |
| P1 / ROOT persistence/recovery design / future implementation | Decide requirement for controller-death recovery/independent guardian with exact durable identity; current live-owner boundary cannot be promoted to all-owner-death guarantee. |
| P1 / ROOT final composition / contract/verification | Review chosen whole-final repin separately, then only authorized metadata26/78 and actual final consumer validation. |
| P2 / API docs/Identity/SDK owners / documentation/contract | Return validated observations to original PR58/PR82 developer gaps and partner pilot; no claim of full API readiness from this harness fix. |

Независимо можно принять только конкретный source diff и документацию с оговорённым live-owner контрактом после review ROOT. Изменения общих серверных/SDK/API-файлов не предлагаются этим узким fix. ROOT остаётся владельцем toolchain/binary/kernel controls, exact final composition, решения о guardian/recovery и отдельного разрешения исполнения. Runtime GO, merge и выпуск здесь отсутствуют. Готовность полного API или самостоятельное подключение реального партнёра не объявляются.

## Полные исходные M00–M19 и 11 общих условий

Объект ORIGINAL-PROGRAM.json сохранён без сокращения и семантически совпал с pinned источником11555bytes SHA256 `84f8dd31e6e047bf6fc647f4e601c1c89783dc8ebbeb4fe324814d51a7fb2ba1`. Все критерии ниже остаются unproven; локальная оснастка их не закрывает.

| ID | Раздел / владелец / зависимости | Исходный критерий |
|---|---|---|
| M00 | P0: актуальный совместимый source/runtime baseline; Выпуск + Core/Support; Нет | Точные версии/хеши/состав, реестр активных потребителей; старый Support не выдан за baseline |
| M01 | P0: завершить реестр поверхностей и владельцев; API + владельцы доменов; M00 | Dynamic/factory/native/WS/SSE/files/proxy разобраны, каждому маршруту назначены class/owner/decision и потребители |
| M02 | P0: characterization и измеряемые сценарии; Домены + проверка; M00, уточнения M01 | Golden outputs/ошибки и отрицательная ACL-матрица на синтетике; исходные SQL/RAM/latency budgets измерены |
| M03 | P0: общий проверенный контекст/route policy; Identity + домены; M00, M02 | Типы токенов/отзыв; ALL/SET/EMPTY/UNINITIALIZED; selector не расширяет доступ; неизвестная новая операция закрыта |
| M04 | P0: границы слоёв и владение транзакцией; Core/Support architecture; M02, M03 skeleton | Извлечённые services не импортируют routers; старые входы вызывают те же правила без изменения поведения |
| M05 | P0: объекты, scopes, population и temporal identity; Core objects/equipment; M03, M04 | Матрица пяти уровней implemented/gap; одинаковый охват list/detail/count/export; create/upsert/rename/retire проверены отдельно |
| M06 | P0: контрагенты, договоры и идентичность; Core references/contracts; M03, M04 | Один matcher и scope service; ambiguous явно; replay/concurrency/null/связи проверены; старые подтверждённые связи сохранены |
| M07 | P0: документы и файлы; Core documents/files; M03, M04 | Карточка/версия/содержимое/тип связи разделены; один writer, domain ACL, rollback cleanup, register/approve отдельно от edit |
| M08 | P0: энергия, начисления и мониторинг; Core energy/ops; M05, M06 | Общие definitions/provenance; чистый GET closing; материализация командой; исторический срез описан честно |
| M09 | P0: протокольный профиль и product OpenAPI; API contracts + домены; M01, M03, соответствующие M05–M08 | Схемы/ошибки/scopes/examples/operationId совпадают с runtime; описательные x-поля не заменяют guard |
| M10 | P0: OAuth/OIDC и developer access; Identity + integrations; M03, M09 profile | Code+PKCE, machine grants отдельно; docs portal/spec/API permissions разделены, отзыв действует и протестирован |
| M11 | P0: защищённый Swagger и quickstart; API docs + Identity; M09, M10, sandbox | UI/raw spec/bundles закрыты; Authorize/Try it out работает на синтетике; нет client secret или общего admin token в браузере |
| M12 | P1: клиентские transports и typed operations; Core/Support frontend; M02, M09 | Один transport на trust boundary; generation/signal, refresh/errors/binary; wire types generated, без `as never` |
| M13 | P1: Support factories и service adapters; Support + Core integration; M03, M04, M06 | Общий ticket lifecycle с параметрами команд; SLA/subject replay/actor и parent SSO ограничения сохранены |
| M14 | P1: доставка событий и change feed; Domain owners + integrations; M03, M04, применимые M13 | Локальные outbox, единый envelope/signature; определены момент подписки, retry/replay/cursor и права перед выдачей |
| M15 | P1: ограничение нагрузки и оптимизация; Backend/DB + домены; M02 и зрелые queries | Измерены SQL/строки/RAM/pool/cache; достигнут принятый бюджет без изменения результата/ACL; большие выгрузки/jobs ограничены |
| M16 | P1/P2: migration/schema ownership; Persistence + выпуск; M00, M02 | Fresh/restore/upgrade/repeat совпадают; Alembic audit отделён от runner; новый DDL versioned и совместим со старым кодом |
| M17 | P1: перевести собственные приложения; Владельцы продуктов; M05–M13 по домену | Переведены UI/service consumers, contracts и workflows проходят регрессию; нет silent online→demo fallback |
| M18 | P0 к внешнему запуску: пилоты и независимая приёмка; Партнёрский пилот + проверка; M09–M17 применимо | Три внешних сценария и общий блок из четырёх доменов реализуются по документации без чтения исходников |
| M19 | P2: deprecation и удаление дублей; Домены + выпуск; M17, M18, usage evidence | Потребители переведены, срок совместимости окончен; старые key/path/adapter удаляются отдельным PR с откатом |

| Общее условие | Полный исходный критерий | Статус |
|---|---|---|
| FULL-SCOPE | Все20M и все поверхности Core/Support/Auditor классифицированы; обязательные документы/контрагенты/договоры/ЭЗС/оборудование/accounts не исчерпывают объём. | unproven |
| SOURCE | Точный актуальный source/runtime/consumer baseline; не потерять параллельные live исправления. | unproven |
| DOMAIN | Единственный владелец правила, tenant/object/org/date scope до count/limit/aggregate/export, текущие actor/grants; неизвестная операция fail-closed. | unproven |
| CONTRACT | OpenAPI/Swagger/SDK/runtime совпадают, содержат реальные auth, errors, headers, limits, null-intent, examples; binary/multipart/SSE/WS/webhook/industry profiles проверяются отдельно. | unproven |
| CHARACTERIZATION | Старые golden outputs и отрицательные матрицы двух компаний/пользователей/apps/resources, реальные SQL/bytes там где требуется; metadata count не заменяет ACL assertion. | unproven |
| MIGRATION | Fresh/restore/upgrade/repeat/old-code, checksums, locking и rollback; перед working migration свежая backup и фактическое восстановление. | unproven |
| CONSUMERS | Полный перевод согласованных UI/service consumers, без stale-context effects и silent fallback; usage evidence перед retirement. | unproven |
| MEASUREMENTS | SQL/RAM/latency/pool/cache/exports/jobs на представительном объёме и принятые бюджеты, без необоснованных pool/index changes. | unproven |
| FINAL-COMPOSITION | Единый окончательный состав исходников и соответствующие проверки; разные frozen серии не объявляются общим полным CI. | unproven |
| LIVE-PILOT | Фактическая приёмка выбранного release/ingress/SSO/callback/CORS/ordinary employee и партнёров; synthetic localhost не подменяет её. | unproven |
| RELEASE | Ревью человеком/согласованный состав/откат; merge и рабочая активация отдельны от зелёных тестов. | unproven |

Commit/SHA самого отчёта публикуются внешней квитанцией после записи; self-referential SHA и будущий HEAD в bytes отчёта не выдумываются. Частные author/reviewer MD/JSON и coordinator-validation остаются в preview как evidence; два новых tracked отчёта содержат их pins.

## Независимая квитанция и lifecycle

`independent-review.md`: 23109 bytes, SHA256 `b12b4c57d30ed70a72151d57d1f819e0e93ca929db7f60372b3824b7b827ab1a`.

`independent-review.json`: 45423 bytes, SHA256 `a82f4a54f1aa64225545a93402ce735cd206300763e49f48855aea67ea8f6e7b`.

Reviewer прочитал snapshot20 futureControls; финальные отчётные metadata добавлены позже. После snapshot R17 редакционно уточнён: kernel default0755 с успешным fchmod не требует обязательного отказа. Это толкование frozen source, не новый результат контроля и не заявка на независимое ревью финального JSON целиком. Авторские22 NC сохранены в JSON с уточнениями координатора. Оба Dispatch succeeded и released; исходники после freeze не менялись.
