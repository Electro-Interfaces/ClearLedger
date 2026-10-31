# Общий примитив создания карточки договора

**SOURCE prerequisite M06/M12: локальное независимое чтение завершено; review основного ожидается. Runtime и tests NOTRUN.**

Точный base `Electro-Interfaces/ClearLedger@675654298f9a7cde30f3ab8097935478bb534088`. Код автора `7d7b56379ba558d09faa94ab9e47e32a17c9e221` перенесён без изменения bytes как `761fbf3f8884f8c7fb742c02ef501bae9b70d871` в отдельной ветке `MagLook/contract-create-workflow-20261101`. Поручение ROOT `msg_08dfd013e919` допускает законченный CREATE либо один точно локализованный upstream contract с независимым кодом. Здесь реализована независимая часть; полный partner CREATE и SDK CREATE не представлены работающими.

## Конкретное изменение

Два блока из native create_native_contract теперь имеют одного предметного владельца `services/contract_card_creation.py`: точный tenant/parties duplicate SELECT с существующей contract_identity и реальный Contract constructor/add/flush. Frozen keyword-only ContractCardValues содержит32 обязательных scalar-поля без новых defaults, runtime validation или normalizer. Новый общий модуль не принимает User, native DTO, Request/Facts, не выбирает authority и не завершает транзакцию. Текущий native handler реально вызывает оба примитива; пустой facade или второй matcher не добавлены.

Native caller сохраняет current User/company/visit/superadmin admission, проверку сторон, native request hash/defaults/UUID spelling, прежний advisory, key/actor/hash replay, sorted-ID HTTP409, duplicate-before-active-type и прежний _req_val. Replay остаётся до повторной проверки active type. Сохраняются null/empty/zero/False, incomplete identity, caller commit/rollback и отсутствие ContractLocation даже при native scopeType=locations. Service actor не превращён в native User. Import create/index/upsert остаётся у прежнего владельца и не меняется.

| Файл | Байты / строки | SHA-256 |
|---|---:|---|
| `clearledger/server/app/services/contract_card_creation.py` | 4136 / 109 | `9a18628d5e6f701dab13c30fced65ef711ce8aa3d7fef4a0ae51ecf8cf5b4158` |
| `clearledger/server/app/services/native_contract_commands.py` | 3555 / 76 | `9a8f88d0b5bb539a19c596a374e786d5f00be672f489625be4066557a71f49e4` |
| `clearledger/server/tests/test_contract_card_creation.py` | 12086 / 199 | `4dd129e23d0317a31d1446900aeed259c664c1c3c5be596d79a057e82716cbf2` |

## Доказательства и точная граница

Repository для всех мест ниже — Electro-Interfaces/ClearLedger, code commit `761fbf3f8884f8c7fb742c02ef501bae9b70d871`, классификация **подтверждено исходниками**. Raw spans находятся в JSON. Source-only чтение не означает выполненную проверку приложения или БД.

| Место | Что проверено |
|---|---|
| `clearledger/server/app/services/contract_card_creation.py:16–51` / ContractCardValues | 32 scalar fields, frozen keyword-only, defaults/normalizer отсутствуют. |
| `clearledger/server/app/services/contract_card_creation.py:54–68` / find_contract_card_duplicates | Точные прежние company+counterparty+organization predicates и существующая identity; возвращает все duplicates, без HTTP/policy/locks. |
| `clearledger/server/app/services/contract_card_creation.py:71–109` / create_contract_card | Единственный extracted actual constructor/add/flush; перенос всех32 полей one-to-one, без commit/связей/доставки. |
| `clearledger/server/app/services/native_contract_commands.py:26–76` / create_native_contract | Обе delegation calls подключены; исходные правила и порядок восстановлены reverse AST. |

Обратное AST-восстановление проверяет исходные аргументы и их порядок, literal11-field requisite map и32 one-to-one field projections. После inlining duplicate helper и actual add/flush/return вся исходная native функция совпала; автор дополнительно восстановил весь module с удалением ровно одного нового import. Нет сортировки statements или общего scrubber, который скрыл бы поведение. Новая dataclass allocation/call boundary не выдаётся за доказанную runtime equivalence.

Координатор Python3.11.2 получил function AST SHA `0375240115ea2cd1c27705dfbcb8681fcba7f0eb6a893254bc6e30265dc673cf`. Автор Python3.13.7 получил `f5d691cfba94f29010cbdfacfefbf14ac1454420dd49c778071fb3a57651e76d`, module `dbada576d6af67528f21587d57463954ebe35946069294f8e8eec760b130ecf9`. Это **разные сериализации ast.dump**:3.13 по умолчанию опускает empty fields. Координатор отдельно воспроизвёл3.13 raw module dump из точного base и сверил old==reconstructed. Сравнения base/current внутри каждой версии совпали; cross-version identity задаётся raw file SHA, не смешением AST SHA.

## Авторские проверки: только будущие исполнения

Новый test module использует существующий guarded native world, реальную будущую synthetic PG transaction и literal expected columns; fixture/transport/schema harness не скопированы. Статически5 функций/10 параметризованных случаев; это не pytest collection и не фактические test IDs от плагинов. Проверяются actual flush visibility до commit, caller rollback, настоящий FK flush failure,32 persisted columns, links0, null/zero/False/empty scalars и exact tenant/parties identity isolation.

**Модульные guards защищают только собственные импорты.** Обычный pytest может загрузить общий conftest раньше. Старый immutable helper не разрешает изменённый source tree и не обновлялся. До любого будущего import/collection/test ROOT обязан отдельно принять runner/source/env/plugins/fixture/точный disposable target; безопасная прямая pytest-команда здесь не публикуется. Никакой runner/diagnostic harness к этому diff не добавлен.

| Статический ID нового случая | Статус |
|---|---|
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_flush_waits_for_caller_commit_and_maps_all_columns` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_flushed_card_disappears_on_caller_rollback` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_flush_failure_propagates_without_partial_card` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_values_preserve_null_zero_false_and_empty_strings[null]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_values_preserve_null_zero_false_and_empty_strings[zero-false]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_values_preserve_null_zero_false_and_empty_strings[empty-strings]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_duplicates_use_exact_company_parties_and_existing_identity[same]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_duplicates_use_exact_company_parties_and_existing_identity[different-number]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_duplicates_use_exact_company_parties_and_existing_identity[different-date]` | AUTHORED_NOTRUN |
| `clearledger/server/tests/test_contract_card_creation.py::test_shared_duplicates_use_exact_company_parties_and_existing_identity[different-type]` | AUTHORED_NOTRUN |

Старый test_native_contract_create.py сохранён byte-exact:16 функций/55 static cases, SHA `bf4cf2d7c22d478c2235aaead82e208bab84a4c31be3c95524c200c089152408`. Они не запускались заново. Старые helpers/tests/DTO/router/auth/Query/SDK/schema/config/CI/flags не изменены; code diff ровно3paths от указанного base. Полные144 новых CREATE +55 native +7 R3 proposed cases исходного дизайна остаются будущими; новые10 prerequisite случаев их не заменяют и не закрывают.

## H01: один недостающий upstream contract

Технический вопрос ROOT `msg_aab27824ca59` направлен до зависимых изменений. После source freeze ROOT ответил `msg_e719c3a4bb5d` и **подтвердил B: завершить независимый shared owner/native adapter**. Scoped keys B выбраны направлением подготовки; global F не выбран. Writer closure/namespaces ещё требуют точной приёмки. ROOT берёт common named permission seam отдельным пакетом: default-empty/прежние политики без действующих route opt-in и fake SET/ALL. Schema registration/head/ordinal и history/policy-generation handoff пока не завершены;0004/profile tables не резервируются, write registration/issuance остаются закрытыми. ROOT дополнительно сообщил `msg_5d2c02e3c2d5` о запуске своего отдельного context.py/routing.py пакета с targeted test/docs; его frozen review/handoff ещё не получен, пересечения с нашими3 paths нет. Это scope-решение ROOT, не принятый код permission seam и не runtime GO. Нужен оставшийся единый frozen **CREATE admission handoff** от ROOT/Core/Identity; повторного разрешения пользователя не требуется.

| Поле handoff | Точное source-доказательство на base675654 | Требуемый результат ROOT |
|---|---|---|
| Lock protocol и участвующие writers | LOCK_ORDER MD:5,11–22,113–118: Исторический MD: A/global fence и B/scoped guards UNSELECTED; позднее ROOT выбрал B как направление подготовки, implementation gate OPEN. | Exact writer closure/scope/owners/namespaces и порядок для выбранного направления B; нельзя самостоятельно массово менять users/roles/OAuth/import roots. |
| Named receipt authority | LOCK_ORDER MD:120–169; access.resolve resource gate и routing.authorize EMPTY/UNINITIALIZED deny — два реальных gate, current exact types не поддерживают receipt-only authority. | ROOT-owned отдельный default-empty seam без active route opt-in; затем явный reviewed opt-in на обоих gate и typed indexed predicate в query transaction, base SET/ALL/EMPTY не переписаны, metadata R3 base-only. Lifetime1000/materialize-all UUID отозваны. |
| Schema и history ownership | LOCK_ORDER MD:173–187; current schema manifest содержит0001–0003 и не резервирует0004. | Accepted schema head/manifest SHA, выданный ordinal и implementer, retention success-history и policy-generation owner; никаких DDL в POST или второго runner. |
| Фактический contract/SDK freeze | product_api/app.py статически15GET; official generate.mjs:16–45 принимает только exact15 candidate GET. | Реализованные POST/create-options и соответствующий canonical17 manifest, затем отдельно разрешённая официальная offline generation; не выдуманная операция и не ручной .d.ts. |

Полный CREATE остаётся непринятым до H01 и следующего implementation/review. Сохранён текущий внешний read contract; новый POST, contracts:create scope, profile/intent/receipt tables, broad policy bypass, lifetime cap и SDK wire types этим пакетом не добавлены. Текущие15 деклараций не выдаются за live scan полного API; flags не включались.

## Приоритетный следующий план

| Приоритет / владелец / слой | Результат |
|---|---|
| P0 / ROOT/Core/Identity / upstream contract | Завершить H01: направление scoped keys B выбрано, но нужны точные writer closure/namespaces и их приёмка. ROOT отдельно владеет default-empty permission seam без active route opt-in; schema head/ordinal, history retention и policy-generation owner ещё не переданы. |
| P1 / Contract command author + independent reviewer / implementation | После H01 реализовать user И machine CREATE/options через тот же предметный примитив: current authority/revoke, атомарные card+links+intent/receipt+audit, replay/null/scope/deny и indexed EXISTS/count+page. Второй matcher/writer не добавлять. |
| P1 / API/SDK owner + ROOT offline generation / contract/client | Зафиксировать canonical OpenAPI фактически реализованных17 операций, затем выполнить отдельно разрешённую официальную generation и typed workflow на существующем transport. До реализации сохранять15GET; generated types вручную не писать. |
| P1 / ROOT isolated verification / future verification | Отдельно зафиксировать source/helper/plugins/env и exact synthetic DB до imports/conftest: прежние55 и новые10 prerequisite случаев, затем исходные144 CREATE и7R3, concurrency/revoke/unknown-COMMIT negatives. Здесь всё NOTRUN. |
| P2 / Product/partner acceptance / documentation/pilot | В принятом installed составе выполнить документированные onboarding/create/read связей/разрешённое скачивание/company-switch/deny/revoke на штатном generated client. Source extraction не закрывает20M/11 или внешний пилот. |

## Полные исходные M00–M19 и 11 общих условий

Исходный object сохранён в JSON без сокращений, семантически равен pinned ORIGINAL-PROGRAM.json11555bytes SHA `84f8dd31e6e047bf6fc647f4e601c1c89783dc8ebbeb4fe324814d51a7fb2ba1`. Локальный prerequisite их не закрывает.

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

## Выполненные действия и ограничения

Разрешённые действия: файловое чтение/свои правки, Git/Orca, stdlib AST/hash/JSON. Никакой project/helper/validator import/exec, compile (включая compile в памяти), приложение/tests/collection/SQL/DB/Node/codegen/compiler/PoC/SSH/Docker/browser/network/install/build/CI не выполнялись. Push/открытие собственного draft PR относится только к подготовке source review; merge/выкатки нет. PR94 frozen и не изменён.

Независимый reviewer task_8b1160ffff6b / ctx_e7b428469854 завершил SOURCE review сообщением msg_06c3f16ab15f после фактического diff и полного post-freeze reread: существенных замечаний нет. Координатор сверил10 raw symbol spans с исходниками. Source-функция и весь module восстановлены точно; это не runtime/DB/transaction proof. Оба исполнителя succeeded/released; main review и H01 остаются отдельными. Commit/SHA самого отчёта фиксируются внешней квитанцией без self-referential SHA и выдуманного будущего HEAD.

## Финальные независимые квитанции

`independent-review.md`: 14102 bytes, SHA256 `a6bfcbe67ce727bbbd5eb15be3f091347d9bf012c03c18bf9096886fd69a691c`.

`independent-review.json`: 143843 bytes, SHA256 `505f9cb6b9f66028d9e13da37b350168ba7e59be05bd461348b77c548f690fab`.

Авторский private MD/JSON содержит полный raw AST и3179-path identity manifest; координатор и reviewer независимо сверили narrow diff/защищённые inputs, не выдавая hash inventory за повторный общий аудит. AST dumps3.11/3.13 разделены явно. Финальные2 отчёта и их синтез не объявляются отдельным независимым review всего нового JSON.
