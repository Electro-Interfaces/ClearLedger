# Подготовка сценариев связей партнёрского API · 31.10.2026

Статус: SOURCE_PREPARED_RUNTIME_NOTRUN. Сводный пакет содержит четыре файла исходников (run.ts, scenarios.ts, relations.test.ts и fixture.py) и два отчёта. Все проверки исполнения, включая pure mocks и TypeScript typecheck, NOTRUN; runtime responses не наблюдались.

Репозиторий: https://github.com/Electro-Interfaces/ClearLedger.git. База: `2a8128dfc59aaf9195d5113e7ab10d67061caf19`.
Пакет не выдаёт кредит готовности: M00–M19 (20 этапов) и 11 gates остаются без изменений.

## Подготовленный seed и manifest

`fixture.py` сохраняет существующие allowed/foreign/ungranted vectors, credentials, членство и content checks. Новое поле fixture return `relations` попадает в существующий `manifest.resources.relations` через `sandbox/server.py:219–222`; raw inventory не используется для вывода эффективного ALL. `run.ts` передаёт эти явные inputs сценариям rental и documents. Ответы типизированы через существующие generated operations; генератор и generated.d.ts не менялись.

`rental.contracts` содержит полный `expected` ContractWire, nullable `metadata` ContractTypeWire и `objects={contractId,scopeType,allowed,hidden}`. `documents.contracts` содержит `{contractId,allowed,hidden}`. Оба раздела содержат `hiddenParents` и `foreignParents`. UUID берутся исключительно из собственных синтетических rows; ObjectId сохраняется побайтно: ` Точка Ё pilot `.

Первый существующий разрешённый договор получает две разрешённые явные связи и две скрытые: третий объект и чужой tenant. Второй сохраняет одну связь. У первого договора неизвестный точный typeCode ` Pilot Unknown Ё ` и raw validUntil `31.12.2030`; у второго typeCode пустой и validUntil null. Неизвестному коду соответствует полный metadata объект с четырьмя null; пустой код не отправляется в metadata query. Classifier lookup допустим только после independently visible contract evidence.

К первому договору привязаны разрешённые d0 и d2, private d1, чужой d3 и новый company d4 вне существующего grant. d0 имеет subject_ref и две graph edges разных kind, но должен появиться один раз. Нативная схема разрешает одну subject card на company/ref, остальные связи идут через DocRelation. Синтетические cross-tenant links преднамеренно проверяют child ACL; приложение не должно доверять им как разрешению.

## Ограничение прав

На базе `2a8128df` documents client имеет `openid documents:read documents.files:download`, а contracts grant EMPTY (`sandbox/server.py:253–255`). Его relation documents запрос ожидаемо получает 403 до чтения parent. На этом составе положительный сценарий **BLOCKED_BY_PROFILE**, будущий прогон **NOTRUN**. В этих шести файлах scopes/grants сохранены без расширения. Для положительного чтения нужны delegated user consent, contracts:read И documents:read, оба resource grants и текущая native document visibility. Это не даёт права скачивать файл; download проверяется отдельно. Machine identity на documents relation получает 403.

ROOT подтвердил отдельную правку принадлежащего ему `sandbox/server.py` (сообщение `msg_e41e48c5bc73`): только synthetic documents client получит `contracts:read`, contracts SET по выбранным fixture contract IDs и явный contracts vector. Objects/counterparties scopes, portal/session и machine grants остальных клиентов сохраняются. Эта правка не входит в текущий пакет; её состав и совместный ROOT прогон должны быть зафиксированы отдельно. Подтверждение плана не считается выполненным запуском или наблюдением ответа API.

Hidden/foreign parent даёт 404 только после успешного route admission. Скрытые дети исключаются до total и limit независимо от видимости parent. Company/unassigned parent не разворачивается в ALL; при location SET сам parent может быть скрыт, поэтому нельзя обещать 200 без указания профиля.

## Будущие проверки · NOTRUN

Проверить полное сравнение contract list/detail и explicit expectations; точный typeCode и raw validUntil; metadata null; opaque objectId без trim; independently hidden children и parent tenant boundaries. Пройти страницы с неизменным pageSize до буквального nextCursor=null, сверить полный explicit set, отсутствие дублей, стабильный total в неизменном синтетическом наборе. Изменение pageSize, parent/resource или binding делает cursor недействительным (400); подписанные cursor bytes заранее не выдумывать. Relation endpoints запрещают q/dateFrom/dateTo/typeCode/companyId (422), допускают только pageSize/cursor. Машинный documents вызов даёт403. Все Problem assertions и исходные checks сохраняются. При текущем профиле новый positive relation case должен записать passed:false и NOTRUN/BLOCKED без positive GET; прежние docs metadata/binary/session проверки завершаются, затем весь пилот обязан завершиться ненулевым до SUCCESS. При отдельно согласованных правах positive helper вызывается до membership revoke.

Guard остаётся прежним: `server.configure()` вызывает validate до app imports, требует отдельную loopback test DB, абсолютный test UPLOAD_DIR, SQL-window opt-in для DDL; клиент требует root-assigned exact loopback HTTPS origin и TLS verification. Маски redaction/transport, opt-in flags и существующие checks не изменены. Сейчас не запускались app/helper imports, framework, tests/collection, server, controls, SQL/HTTP/SSH/Docker, browser, build, install, codegen или formatter.

Точное source provenance (base/path/line/blob/base SHA256/current SHA256), границы выводов и future test statuses находятся в соседнем JSON. Сведение A+B и совпадение базы проверяются статически; последующее исполнение ведёт ROOT в своём допуске. Этот документ не подтверждает runtime responses, выпуск или приёмку.

Будущая отдельная проверка pure mocks (NOTRUN): из `clearledger/tools/partner-pilots/clients` явно запустить `node --experimental-strip-types --test guards.test.ts relations.test.ts`. Текущий `package.json:test:unit` перечисляет только guards.test.ts и новый файл не охватывает. package.json/package-lock остаются без изменений; команда сейчас не запускалась.

## Разрешение и независимое ревью

Переход от proposal к source preparation выполнен по сообщению координатора `msg_587606287f3e`, передающему прямое разрешение МАГа «Разрешаю код, тесты и документацию в отдельных ветках» (main `msg_f141e959f608`, сессия `codex_22b96a77_7ffb_487a_84d2_880f88417089`, 31.10.2026). A владеет тремя файлами clients, B — fixture и двумя отчётами; координатор сводит ровно эти шесть путей. Локальные proposal artifacts не входят в целевые коммиты. Runtime-допуск этим действием не использовался.

В исходном A patch найден A-P1-01: gate до consent пропускал все прежние docs проверки. Finding отправлен A и координатору. В patch SHA256 `22398104a935c9e445940de43cd7fa8e71b52ce41395ee3ee593b44a8423b736` статически подтверждено исправление: gate после binary checks, NOTRUN/blocked result passed:false, positive helper до membership revoke, fail-closed после исходных checks и до SUCCESS. Точные context/hunk counts и сохранение старых assertion/check имён проверены в памяти; TS execution NOTRUN. После материализации независимо перечитаны actual `run.ts`, `scenarios.ts`, `relations.test.ts` из worktree A. Исправление A-P1-01 подтверждено в actual run.ts:194–226; дополнительных source findings не найдено. SHA256 каждого actual файла и точные line references сохранены в JSON. Девять новых pure mock тестов остаются NOTRUN.

Pure mock с четырьмя одинаковыми ответами403 не проверяет серверный ACL. Отдельные inputs отсутствующих scopes/grants проверяют только клиентский admission helper; ни один из девяти mock tests не запускался и не заменяет будущий OAuth/HTTP/SQL прогон.

Сводный source freeze четырёх файлов: `20daebf1d51700b7d61161ecc8b48d8193350c26`. Клиентская часть A `ae679dbf5fe4881738e11c034a8afa1efc1894a7` интегрирована как `20daebf1d51700b7d61161ecc8b48d8193350c26`; fixture B `1457df337055f83e048ad7a17bef254ce58f454e` — как `ac88cccd7f051413b0e85a5507478efe97b5d11b`. На этом составе отдельно сверены SHA всех четырёх исходников с прочитанными исполнителями байтами, сохранение порядка 14 прежних имён проверок run.ts и побайтное равенство тела operationsScenario. Это сравнение исходного текста. TypeScript compiler, Node tests и фактический pilot не запускались.

Критерий следующей приёмки: ROOT фиксирует совместный состав этого пакета и своего server.py, проверяет TypeScript и оба unit-файла, затем отдельно подтверждает реальные OAuth/HTTP сценарии на вымышленных данных с исходными guards. Требуются наблюдённые положительные связи, отказы и неизменные redaction assertions; mock outcomes не заменяют эти доказательства. Пакет закрывает только подготовку исходников для части M12/M18, не сами этапы и не общую приёмку API.


## SOURCE follow-up из четырёх путей · 31.10.2026

Этот раздел дополняет original PR86 freeze на exact immutable HEAD `21f33b0fa51029aab02799e85a5e8bd63f00948f`. Весь текст выше, включая исходные NOTRUN, базу `2a8128dfc59aaf9195d5113e7ab10d67061caf19`, source freeze и package-source records, сохранён как историческая запись подготовки PR86. Он не описывает текущие package/test bytes после этого follow-up. Старые PR86 branch/worktree не изменены; допуск к исходникам, документации и тестам в отдельных ветках остаётся `msg_f141e959f608`, узкое поручение: `ROOTmsg_983fd9c05a6f`.

Изменены ровно четыре существующих пути: `clearledger/tools/partner-pilots/clients/package.json`, `clearledger/tools/partner-pilots/clients/relations.test.ts` и эти два отчёта `.md/.json`. В package изменено только `scripts.test:unit`: `node --experimental-strip-types --test guards.test.ts relations.test.ts`; все остальные байты, keys, dependencies, engines и scripts сохранены. Lockfile не изменён. В relations.test.ts удалён только строковый префикс `NOTRUN ` из девяти названий тестов и вводного комментария, метка `pure scripted typed mocks` сохранена. Тела, inputs, assertions, imports и весь остальной исходный текст сохранены побайтно.

Статическое доказательство: package равен exact parent bytes после единственной указанной замены; relations.test.ts равен exact parent bytes после ровно десяти ожидаемых строковых замен (9 titles + 1 comment), обратная замена восстанавливает parent целиком. Это текстовое сравнение, без Node, TS parser, formatter, imports, collection или исполнения тестов.

Новые source SHA256 относительно exact PR86 HEAD:

| Путь | SHA256 follow-up |
|---|---|
| `clearledger/tools/partner-pilots/clients/package.json` | `013c45d61f2145a42e46467db0b793f22981a937e8f40b7d0a3179ac0245181a` |
| `clearledger/tools/partner-pilots/clients/relations.test.ts` | `340126967c51545f105ff739dbcf7c784a46e63a1706dd33ff955e2bf8cb7a5c` |

Исторический Markdown PR86 до добавления этого раздела: SHA256 `e100899808500c5ede6d97533e5901af0af8f9dae0f843144684b2b05324cfee`. Поле JSON `markdownSha256` и все прежние `packageSourceManifest`, provenance/currentSha256, review и NOTRUN records относятся к original PR86 freeze; новая запись JSON `fourPathSourceFollowup20261031` отделяет follow-up от них. SHA отчётов после follow-up передаются внешним handoff вместе с итоговым commit, без рекурсивного self hash.

### Внешнее наблюдение ROOT · 31.10.2026 17:24:29 UTC

Acceptance note получена через `ROOTmsg_983fd9c05a6f`, sender `codex_22b96a77_7ffb_487a_84d2_880f88417089`: ROOT сообщает наблюдённые **unit 16 PASS = 7 guards + 9 relations на Node**. Это внешнее наблюдение ROOT, переданное в поручении; исполнитель этого follow-up и координатор его здесь не воспроизводили. Raw artifact, Node version и exact command: **UNKNOWN**, они не переданы. Наблюдение не подтверждает исполнение новой package-команды на этом follow-up и не является доказательством real HTTP/OAuth/SQL или серверного ACL.

Reported source integration commits разрешены локальным Git до exact commits без исполнения кода: `eca5791c43ef8eb915415028426d423b0593b24e`, `ab30202e2b0f0045affcc39caa55e1bfeb0680fb`, `6e893817a9f4741eee555f9190d6977b73ffb4bc`. Это provenance внешнего receipt, не приписывание этих commits новой четырёхфайловой ветке. Отдельная synthetic server dependency ROOT известна как `230b508e`, Git-resolved `230b508e81b514e091bb597ee369728aa3becca5`; `sandbox/server.py` сюда не включён, PR86 ради этого статуса не изменяется.

Локально новая package-команда и TypeScript typecheck: **NOTRUN**. Real HTTP, OAuth, SQL и actual pilot: **NOTRUN**. ROOT позже сам выполняет `npm run test:unit` и tsc на зафиксированном combined composition. Guards, generated/schema, server, transport, OAuth, dependencies и lockfile неизменны относительно exact PR86 HEAD. M00–M19 (20 этапов) и 11 gates сохранены, кредит готовности не добавлен.
