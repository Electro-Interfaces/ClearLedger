# Подготовка сценариев связей партнёрского API · 31.10.2026

Статус: SOURCE_PREPARED_RUNTIME_NOTRUN. Подготовлен один source файл fixture.py и два документа этого пакета. Все проверки исполнения, включая pure mocks, NOTRUN; runtime responses не наблюдались.

Репозиторий: https://github.com/Electro-Interfaces/ClearLedger.git. База: `2a8128dfc59aaf9195d5113e7ab10d67061caf19`.
Пакет не выдаёт кредит готовности: M00–M19 (20 этапов) и 11 gates остаются без изменений.

## Подготовленный seed и manifest

`fixture.py` сохраняет существующие allowed/foreign/ungranted vectors, credentials, членство и content checks. Новое поле fixture return `relations` попадает в существующий `manifest.resources.relations` через `sandbox/server.py:219–222`; raw inventory не используется для вывода эффективного ALL. A должен читать эти явно переданные inputs. Wire DTO остаются сгенерированными; SDK-generator и ручные wire types не предлагаются.

`rental.contracts` содержит полный `expected` ContractWire, nullable `metadata` ContractTypeWire и `objects={contractId,scopeType,allowed,hidden}`. `documents.contracts` содержит `{contractId,allowed,hidden}`. Оба раздела содержат `hiddenParents` и `foreignParents`. UUID берутся исключительно из собственных синтетических rows; ObjectId сохраняется побайтно: ` Точка Ё pilot `.

Первый существующий разрешённый договор получает две разрешённые явные связи и две скрытые: третий объект и чужой tenant. Второй сохраняет одну связь. У первого договора неизвестный точный typeCode ` Pilot Unknown Ё ` и raw validUntil `31.12.2030`; у второго typeCode пустой и validUntil null. Неизвестному коду соответствует полный metadata объект с четырьмя null; пустой код не отправляется в metadata query. Classifier lookup допустим только после independently visible contract evidence.

К первому договору привязаны разрешённые d0 и d2, private d1, чужой d3 и новый company d4 вне существующего grant. d0 имеет subject_ref и две graph edges разных kind, но должен появиться один раз. Нативная схема разрешает одну subject card на company/ref, остальные связи идут через DocRelation. Синтетические cross-tenant links преднамеренно проверяют child ACL; приложение не должно доверять им как разрешению.

## Ограничение прав

Существующий documents client имеет `openid documents:read documents.files:download`, а contracts grant EMPTY (`sandbox/server.py:253–255`). Его relation documents запрос ожидаемо получает 403 до чтения parent. Положительный сценарий: **BLOCKED_BY_PROFILE**, будущий прогон **NOTRUN**. Scopes/grants сохранены без расширения. Для будущего отдельного допуска нужны delegated user consent, contracts:read И documents:read, оба resource grants и текущая native document visibility. Это не даёт права скачивать файл; download проверяется отдельно. Machine identity на documents relation получает 403.

Hidden/foreign parent даёт 404 только после успешного route admission. Скрытые дети исключаются до total и limit независимо от видимости parent. Company/unassigned parent не разворачивается в ALL; при location SET сам parent может быть скрыт, поэтому нельзя обещать 200 без указания профиля.

## Будущие проверки · NOTRUN

Проверить полное сравнение contract list/detail и explicit expectations; точный typeCode и raw validUntil; metadata null; opaque objectId без trim; independently hidden children и parent tenant boundaries. Пройти страницы с неизменным pageSize до буквального nextCursor=null, сверить полный explicit set, отсутствие дублей, стабильный total в неизменном синтетическом наборе. Изменение pageSize, parent/resource или binding делает cursor недействительным (400); подписанные cursor bytes заранее не выдумывать. Relation endpoints запрещают q/dateFrom/dateTo/typeCode/companyId (422), допускают только pageSize/cursor. Машинный documents вызов даёт403. Все Problem assertions и исходные checks сохраняются. При текущем профиле новый positive relation case должен записать passed:false и NOTRUN/BLOCKED без positive GET; прежние docs metadata/binary/session проверки завершаются, затем весь пилот обязан завершиться ненулевым до SUCCESS. При отдельно согласованных правах positive helper вызывается до membership revoke.

Guard остаётся прежним: `server.configure()` вызывает validate до app imports, требует отдельную loopback test DB, абсолютный test UPLOAD_DIR, SQL-window opt-in для DDL; клиент требует root-assigned exact loopback HTTPS origin и TLS verification. Маски redaction/transport, opt-in flags и существующие checks не изменены. Сейчас не запускались app/helper imports, framework, tests/collection, server, controls, SQL/HTTP/SSH/Docker, browser, build, install, codegen или formatter.

Точное source provenance (base/path/line/blob/base SHA256/current SHA256), границы выводов и future test statuses находятся в соседнем JSON. Перед будущим исполнением нужен отдельный допуск; сведение A+B и совпадение базы проверяются статически. Этот документ не подтверждает runtime responses, выпуск или приёмку.

Будущая отдельная проверка pure mocks (NOTRUN): из `clearledger/tools/partner-pilots/clients` явно запустить `node --experimental-strip-types --test guards.test.ts relations.test.ts`. Текущий `package.json:test:unit` перечисляет только guards.test.ts и новый файл не охватывает. package.json/package-lock остаются без изменений; команда сейчас не запускалась.

## Разрешение и независимое ревью

Переход от proposal к source preparation выполнен по сообщению координатора `msg_587606287f3e`, передающему прямое разрешение МАГа «Разрешаю код, тесты и документацию в отдельных ветках» (main `msg_f141e959f608`, сессия `codex_22b96a77_7ffb_487a_84d2_880f88417089`, 31.10.2026). Записаны только fixture.py и эти MD/JSON; локальные proposal artifacts не входят в целевой коммит. Runtime-допуск этим действием не использовался.

В исходном A patch найден A-P1-01: gate до consent пропускал все прежние docs проверки. Finding отправлен A и координатору. В patch SHA256 `22398104a935c9e445940de43cd7fa8e71b52ce41395ee3ee593b44a8423b736` статически подтверждено исправление: gate после binary checks, NOTRUN/blocked result passed:false, positive helper до membership revoke, fail-closed после исходных checks и до SUCCESS. Точные context/hunk counts и сохранение старых assertion/check имён проверены в памяти; TS execution NOTRUN. После материализации независимо перечитаны actual `run.ts`, `scenarios.ts`, `relations.test.ts` из worktree A. Исправление A-P1-01 подтверждено в actual run.ts:194–226; дополнительных source findings не найдено. SHA256 каждого actual файла и точные line references сохранены в JSON. Девять новых pure mock тестов остаются NOTRUN.

Pure mock с четырьмя одинаковыми ответами403 не проверяет серверный ACL. Отдельные inputs отсутствующих scopes/grants проверяют только клиентский admission helper; ни один из девяти mock tests не запускался и не заменяет будущий OAuth/HTTP/SQL прогон.
