# M05-B: адаптеры импорта существующих точек

Дата: 30.10.2026. Статус: implementation-ready source design, код не реализован.
Рекомендуется совместимый протокол **полный sorted-ID set → company → rows**,
с запретом расширять набор внутри транзакции. Просто вызвать `update()` для
каждой строки нельзя. Подключение W10 требует подготовки на входе загрузки
сессий; подключение W07 к unit требует согласовать unit/link writers.

## 1. Закреплённая база и границы доказательств

Integration HEAD: `73086a5d54fadc623ae61031057eec55ff28bf6b`.
Исходная command revision: `5c0deb220ab328eacad6c098121a46c8fcfb94ad`;
`location_commands.py` в HEAD побайтно совпадает с ней (H02 в companion).
Два новых файла этого пакета: этот документ и
`M05_IMPORT_ADAPTER_DESIGN_20261030.json`. Runtime, tests, models, DDL, auth и
`OBJECT_LIFECYCLE_WRITERS_20261030.md` не изменяются.

Прочитаны инструкции машины из задания, корневой и `clearledger/CLAUDE.md`,
установленные `rushydro-space` и `orchestration`, карта writers, особенно A–E
и предупреждение о смене lock order. Нумерация строк ниже относится к HEAD,
а не к более ранним anchors внутри карты. Hxx означает точный путь, git blob,
SHA-256 и размер в companion JSON; Fxx связывает факт со строками и caller.
Это ограниченная проверка исходников. SQL, HTTP acceptance, реальные данные,
SSH, realenv и полный security scan не выполнялись; runtime race не доказана.
Git push двух документов разрешён заданием отдельно от запрета доступа к сервисам.
Private deploy canon, выгрузки и raw inventory не копировались. Примеры ниже
искусственные: company C, точки P/Q, станция U, номера N1/N2.

Зависимость history: immutable source
`0b215a1e285328fda46e76efe59b9008ac06a2df`, по сообщению координатора перенесён
как `1f0cf49a`; это **не merge/deploy** и не часть указанного HEAD. Прочитаны
его `location_commands.py` и сопроводительный отчёт соседнего worker только
для чтения. Заявленные там результаты тестов не являются проверкой этого плана.
H19/H20 закрепляют прочитанные bytes; при интеграции dependency перепроверить.

## 2. Реальные входы, callers и транзакции

| Факт | Source anchor (Hxx + строки) | Caller и наблюдаемое поведение |
|---|---|---|
| F01 | H03 `channels_router.py:456–489,327–405` | `POST /channels/{id}/run`: `get_owned(Channel)`; создаёт/коммитит running log, запускает background с отдельной session. Company берётся из channel; actor/ACL не передаются явным аргументом в normalizer |
| F02 | H04 `channel_orchestrator.py:557–585,713–734` | `_dispatch → _run_stations`: SourceFile → `ingest_asuim_book`; при None `parse_stations_xlsx → ingest_stations(...mode,log_id)` |
| F03 | H05 `asuim_normalize.py:1006–1069,1137–1152` | Книга идёт в `VIEW_ORDER`; stations → `map_stations → ingest_stations(mode="replace")` независимо от запрошенного append, с `partial=True`. Затем `_invalidate` |
| F04 | H01 `stations_normalize.py:154–252,562–568` | Parser full: ext_id/name/number/serial, address/geo, station passport, stage/status, source link hints. Parser compact: number/name/ocpp_id/address/region/protocol/brand/connectors/status_dev/owner, compact marker → W07 |
| F05 | H01 `333–370,382–417` | W07 `_ingest_compact`: ORM cache ev_charging; OCPP → mixed source/code/serial index → unique number fallback; touched и deterministic `_loc_id(company,"ocpp:...")` fallback через `db.get`. Индексы `setdefault`, не доказательство уникальности |
| F06 | H01 `425–495,497–559` | W07 existing append всегда skip; replace пишет point, metadata и через `write_value` unit. New ID детерминирован, code=ocpp or number. Каждый обработанный row в SAVEPOINT, ошибки считаются, return может остаться success |
| F07 | H01 `574–657,671–674` | W08 full/partial `ingest_stations`: ext/source/code → serial → number, test/non-network только source; serial допускает иной source ID; foreign number и multiple number возвращают None. Append пропускает existing только если serial_number **не None**, даже пустая строка считается обогащённой |
| F08 | H01 `697–817` | W08 existing: typed setattr непосредственно loc, metadata merge, CPO name/history; не меняет id/code/source_bindings. New ветка выбирает number/serial/ext code и создаёт deterministic ID; None resolver может попасть сюда после ambiguity |
| F09 | H01 `255–265,370,535–548,661,815–832` | `_bump` коммитит ту же db только если log_id не None. Начальный bump происходит после загрузки caches; промежуточный idx+1 кратен200, но continue/exception до него пропускает checkpoint; финальный flush/bump. Это не гарантированные chunks по200 успешных строк |
| F10 | H06 `charge_sessions_normalize.py:203–260,275–292,378–427,458–469` | `_run_charge_sessions` / asuim sessions → ingest: индексы point, replace DELETE и pending session FOR UPDATE, batched inserts/flush, backfill(auto_create=False), W10, enrichment/visits/mart/bump_version; прогресс отдельной session, основная T едина до финального bump |
| F11 | H01 `1087–1117` | W10 `refresh_location_names` из H06:416: raw SQL latest session by location, btrim name, append old nameHistory; исключает только nameSource=cpo_registry. Нет ACL fragment, command/advisory lock или manual marker проверки |
| F12 | H02 `69–116,287–308` | Native/registry/mapping → `_barrier(ID→company)` → tenant-qualified FOR UPDATE + populate_existing → O/G; command не коммитит. Cached admission row не является актуальным mutation snapshot |
| F13 | H07 `locations_router.py:216–273`; H08 `space_registry.py:126–157`; H17 `database.py:5543–5551` | Native POST upsert/PATCH flush+refresh+project_object, commit dependency; registry create/update audit+собственный commit. Проекция native внутри прежнего lifetime T; adapter не добавляет её в import |
| F14 | H09 `station_mapping.py:204–256`; H10 `ops_router.py:237–276` | Уже исправленный mapping add/close вызывает locked_visible; close фильтрует company+parent(path)+relation. Сервис коммитит сам; это участник ID→company, не прежний незащищённый W16 из старой карты |
| F15 | H11 `station_passport.py:58–99,100–150` | W07 `stations_by_location(None)` загружает current placement/unit без row locks; write_value пишет unit при наличии, иначе loc. FEED_OWNED пуст; W08 typed loop всё ещё пишет loc вопреки комментарию helper |
| F16 | H12 `ezs_equipment.py:344–357,494–574`; H13 `ezs_equipment_docs.py:328–343,352–405` | Movement route → post_document → apply_movement unit FOR UPDATE, далее sync_placement и optional _sync_passport loc UPDATE. Документ обходит unit_ids в порядке payload; post_draft уже держит document row до вызова. Общего point barrier здесь нет |
| F17 | H14 `equipment_router.py:467–535,568–613`; H12 `614–630,806–1024` | Manual unit patch inventory и import_units/dismantle также меняют unit; номер inventory freeze producer. Нельзя чинить только apply_movement и объявлять inventory сериализованным |
| F18 | H15 `object_freeze.py:40–100`; H07 `204–212` | Freeze читает contract/session, исторические placed_at→inventory, external links и company-wide external export log. Экспорт вставляет ObjectExportLog, общего advisory не берёт |
| F19 | H02 `129–184,187–248`; H01 `476–494,697–791` | Command охраняет code, station_number и metadata.number, историю и occupancy; W07/W08 напрямую обходят эти guards, W10 меняет только name/history. Текущая _prepare manual allowlist недостаточна для passport adapter |
| F20 | H16 `scope.py:138–167`; H02 `91–103,119–153` | ORM listener не охватывает raw SQL; explicit _assert_visible различает O=None/EMPTY и G. Occupancy Core company-wide без загрузки hidden ORM rows; перенос импорта не должен превращать внутреннее чтение в ACL bypass |
| F21 | H01 `865–940,999–1084`; H18 `session_scope.py:24–53` | Station readers используют actual number/numberHistory, backfill может rebind closed shadow. Домен code туда не добавлять; E остаётся отдельной обязательной защитой перед retirement |
| F22 | H21 `analytics_cache.py:168–181`; H05 `850–859`; H04 `658–709` | bump_version действительно commit. Книга может коммитить через _invalidate помимо station _bump; run_channel rollback только незавершённой T, публикация sync fact коммитит отдельно. Ошибка после прошлого chunk не возвращает его назад |
| F23 | H22 `models.py:5880–5881,6304–6313`; H13 `ezs_equipment_docs.py:480–547` | Session/unit location FK дают дополнительные lock edges; cancel берёт document, movements+units, восстанавливает поля, вызывает sync_placement; receipt cancel удаляет unit и placed_at. Это отдельный обход сохранения inventory/history, не действие W07/W08 |
| F24 | H24 `space_registry_router.py:68–86,135–147,177–215`; H25 `deps.py:83–129`; H26 `auth.py:294–345` | Registry route требует admin, валидирует enums и confirm409, model_dump(exclude_none=True); native/channel get_owned проверяет членство, current scope задаётся отдельно assert_company_member. Нельзя унифицировать эти admissions ради import adapter |
| F25 | H27 `channelService.ts:334–348,367–387`; H28 `ChannelDetailPage.tsx:404–455,682–687,2212–2254`; H29 `useRawPanelTree.ts:131–133` | API status:string уже допускает partial, run history его документирует; upload polling и handleSync показывают toast.success для всего кроме error. Badge/raw-panel умеют Частично, но это не исправляет toast. Source observation, браузер не запускался |
| F26 | H03 `channels_router.py:353–386,494–520,554–600` | Background сохраняет выбранные result fields в events, run_status/channel_runs сериализуют выбранные поля; arbitrary reconciliation из result автоматически до клиента не доезжает. Нужны явные bounded sanitized count/list и приёмка consumers |


Admission на входе тоже часть совместимости (F24): registry сохраняет admin-only,
_validate и confirm409, native сохраняет membership/get_owned, channel сохраняет
get_owned(Channel). У background нет явного actor/scope аргумента: нельзя считать
company_id достаточным доказательством user admission и нельзя обнулить O/G для
удобства импорта. Prepared context должен нести существующее авторизованное
намерение запуска и server-derived scope, проверять его при старте worker и
после lock wait; context для service caller допустим только если этот caller
уже имел такое admission. Проверка реального channel entrypoint обязательна;
подменять её прямым вызовом service с scope=None нельзя. Существующие пробелы
get_owned/ContextVar inheritance не объявляются исправленными этим дизайном.

### Поля и authority: old contract и candidate

| Семейство | Old (точный source) | Candidate, отдельно от остальных изменений |
|---|---|---|
| Server ID, code, source bindings | W07/W08 existing их не меняют | Existing-only adapter не принимает их вообще. Разница external source ID/OCPP не является основанием переименовать point/code или создать новую карточку |
| station_number / metadata.number | W07 fill empty station column; metadata.setdefault(number) независимо. W08 full может записать null; partial только non-null. W08 обычно не меняет metadata.number | Формировать **два независимых** presence-aware изменения. Preserve divergent legacy values при отсутствии запроса. Любое изменение каждого actual number проходит freeze/typed history/no-reuse; новое значение обоих полей проверяется, включая metadata-only change |
| identifierHistory / numberHistory | H02 кладёт также code в numberHistory; импорты history не генерируют | Зависимость H19: typed domain=code/station_number old/new/source/actor/recordedAt; `numberHistory` только station aliases с `было`. Никогда не называть это valid-time ledger. Code-only import mutation запрещена; будущий adapter не смешивает домены |
| Name и nameHistory | W07/W08 принимают meaningful CPO name, numeric label не заменяет real name; consecutive history dedup. W10 пропускает CPO, берёт latest session, btrim и int renamed | CPO > session сохраняется. Manual provenance > оба источника; исходное имя/история берутся после reload. Не писать typed number history при name-only. W10 tie started_at без второго ordering сейчас неопределён: baseline не фиксирует случайного победителя |
| Source metadata/raw | Compact truthy md_extra; full сохраняет в passport_extra также None; partial non-None + row.extra. Прежний source snapshot и человекоуправляемые bindings лежат рядом | Отдельные patch_source_metadata и protected state; allowlist по family, deep copy актуального md. Source raw сохраняется в исходном SourceFile и разрешённых snapshot fields; файл+row ordinal остаются доступны для сверки. Не обещать, что extra_metadata содержит весь исходный row/geo |
| Manual values | W07 не меняет непустой owner/address/number/region, сохраняет собственный отличный OCPP; partial W08 сохраняет непустой loc.owner и omitted nulls. Full W08 может очистить/заменить паспорт | Эти правила сохраняются. Field provenance вводится для явно ручных правок; full-source replace допускается для немаркированного source-owned паспорта по baseline, но не для явно manual. Не называть старую модель универсально защищённой от перезаписи человеком |
| Passport owner | W07 write_value→unit либо loc; W08 напрямую loc | Сохранять текущего владельца записи каждого feeder в B. Перевод W08 всех typed полей на unit отдельным PR: это меняет readers/authority. W07 unit reload под согласованным protocol, сохранение inventory и placement |
| Operational status / point status | W07 operational observation+transition audit, decommissioned→point closed; W08 full stage active/planned/closed, partial только decommissioned закрывает, остальным loc.status | Называть legacy status projection, не disposal. Сохранить эту совместимость в bounded B; не закрывать links, number, inventory и не создавать effective dates. Запрет источнику reopen manual closed требует отдельного lifecycle решения A–E; риск явно остаётся |

Требование **нового independent SourcePatch**: `_apply` сегодня получает number
через public `_prepare`, который при incoming metadata.number одновременно
выставляет station_number (H02:172–183). Поэтому metadata-only defect текущего
public endpoint здесь **не установлен**. Новый adapter сохраняет раздельные
legacy column/metadata semantics, и без доработки `_apply` проверка values может
не включить независимое новое metadata.number или повторно проверить неизменный
shared station_number. Для него нужны `changed_assignments` по каждому code /
station_number / metadata.number: проверять новые непустые values изменившихся
полей, history из актуальных old, freeze также при clear. Не использовать общий
`number_changed` как разрешение переоценить все неизменённые номера. Обязателен
конкретный SourcePatch fixture с расходящимися column/metadata; его результат
нельзя приписывать старому public caller. Изменение относится к будущему diff.

## 3. Где теряются protected/manual данные: source facts и baseline fixtures

1. W07 cache loc/unit и W08 cache loc загружаются до начального commit; session
   factory expire_on_commit=False. После ожидания lock или между chunks содержимое
   не обновляется само. Merge `{**old_md, **snapshot}` способен записать старую
   версию whole JSON поверх более свежей history/manual edit. Это возможность
   по структуре записи, **не воспроизведённый race**.
2. W08 partial `row.extra` перекрывает passport_extra, затем whole md. Текущий
   public mapper H05:290–305 выпускает фиксированные ключи, истории туда не
   входят; утверждения «xlsx может непосредственно подделать identifierHistory»
   из этих строк не следует. Но helper принимает произвольный dict: internal
   arbitrary extra, будущий mapper и stale ORM требуют allowlist и protected keys.
3. W07 own OCPP mismatch сохраняет прежний ocppId, но всё ещё может записать
   status/name/passport от другого устройства и всего лишь увеличить ambiguous.
   W08 multiple-number/foreign возвращает None и может создать duplicate;
   touched compact также превращает второй match в создание. Это source paths,
   а не доказательство существования таких записей в окружении.
4. Native/registry name update не устанавливает manual provenance автоматически
   (H07/H08/H02). W10 защищает только cpo_registry; manual label без него может
   быть заменён. Старые ручные значения невозможно надёжно отличить от source
   labels по одному тексту. Нельзя задним числом объявить их source-owned.
5. Full W08 `typed` содержит nullable значения и status default active: может
   очистить manual address/serial/number и открыть closed. Partial не равен
   «заполнять только пустое»: непустые поля кроме специальных исключений тоже
   обновляются. Serial conflict проверяется по stale by_serial; database unique
   error не заменяет reconciliation причины.
6. Legacy current AC/DC duplicate N1 не конфликт при unchanged update P или Q.
   Fill пустого column значением уже существующего md.number допускается лишь
   как подтверждённая та же current assignment, без новой выдачи, с fixture
   divergent/null states. Если это нельзя доказать, reconciliation; не флаг
   `ignore_conflicts` и не разрешение выдавать N1 ещё одной точке.

Минимальные baseline fixtures: C с P/Q sharing N1, разными source/OCPP и code;
P с column!=metadata.number; column empty+md N1; одинаковые sid/serial/OCPP
на нескольких кандидатах; manual name без provenance; CPO и session label;
full/partial null/empty/omitted; loc.owner/unit.owner divergence и непустой
inventory; histories отсутствуют/unknown dict/numeric/space/malformed;
SourceFile replay с duplicate rows, touched и deterministic-ID fallback;
реальный установленный ORM scope (None, EMPTY, O subset, G incompatible).
Ни raw inventory, ни реальные номера/имена не нужны.

## 4. Lock graph и два конкретных варианта

Обозначения: I(P) — нынешний **global advisory ID key** из H02:69–75;
C — нынешний company advisory; R(P) — tenant-qualified point row lock;
U — unit row; D — equipment document row. Hash key/namespace остаются теми же.
Одинаковый ID другой компании требует I(P), но **не** её row lock.

### Недопустимая наивная интеграция

T1 import: I(P) → C → R(P), затем вызывает update(Q) и ждёт I(Q).
T2 native POST/PATCH, registry create/update **или mapping add/close(Q)**:
I(Q) → ждёт C. T1 держит C, T2 держит I(Q): замкнутый wait graph.
Достаточно P≠Q и одной компании. Даже sorted loop по row IDs не помогает,
если C захвачен после первого ID, а не после **всех** ID.

Это вывод о потенциальном cycle из точных call paths F06/F08/F12–F14,
а не зарегистрированный PostgreSQL deadlock. Переименование namespace уберёт
взаимную защиту и не исправит порядок. Новый C→I только у import создаст
ещё более прямой cycle с прежним I→C у single writer.

Unit/link/session paths добавляют другие рёбра:

- Candidate W07 с I(P),C,R(P), затем unit UPDATE ждёт U. Уже сейчас equipment
  `post_document→apply_movement` держит U и через `_sync_passport` может ждать
  R(P). Если новый link adapter поставят внутрь sync_placement, получится также
  U→I(P)→C. Поэтому ни unit lock, ни новый point lock нельзя вставить в середину
  прежнего movement без подготовки всего document/dismantle/patch entrypoint.
- W10 вызывается после pending session locks, inserts/flush и backfill UPDATE.
  FK в models связывает session с point, FOR UPDATE point конфликтует с FK
  key-share (это описано H02:84). Tx с таким FK lock, поздно ждущая I(P), может
  замкнуться с native writer, который держит I(P),C и ждёт R(P). Backfill также
  охватывает старые sessions всей компании, а не только incoming file rows.
- W08 point UPDATE без advisory и W10 raw UPDATE могут ждать/блокировать R(P)
  вне общего порядка; единый allowlist сам этого не меняет. generic ObjectLink
  soft IDs не дают FK сериализации; freeze external mapping уже участвует
  через F14, inventory/export и другие link writers пока нет.
- Post draft берёт D раньше unit; multi-unit post идёт в payload order.
  Если после D/U начать получать I/C, document cancellation/posting тоже надо
  включить в protocol review. «Исправили один movement helper» недостаточно.

### Вариант S (рекомендуемый): полный set до company, без смены I→C

**Применимость:** все потенциальные point IDs транзакции известны до первого
blocking row lock / FK write / dirty ORM flush. Это transaction-level contract,
а не удобство row helper. Прежние single writers с I(P)→C совместимы.

1. `plan_import_transaction` делает только tenant-qualified MVCC scalar reads
   с autoflush disabled; возвращает immutable intents, typed identity evidence,
   source-file reference, candidate ID sets, исходные presence bits. Для W07/W08
   superset включает все возможные source/serial/number matches, deterministic
   ID intents и **все remaining rows до настоящей границы commit**, не первые200.
   Для W10 включает уже linked locations, incoming resolver targets, все цели
   backfill и потенциальные rename по company sessions. При неизвестном размере
   superset допустим весь собственный релевантный point set: нагрузку измерить;
   это не разрешение row-lock всех невидимых points.
2. `acquire_location_set` валидирует opaque IDs, дедуплицирует и сортирует по
   одному фиксированному byte/string order, берёт **все прежние I keys**, затем C.
   Не менять bytes identifier, не строить ID по новому правилу и не использовать
   процессный Python hash. Новые ID намерения входят заранее, включая cross-tenant
   claim protection. Разные companies с пересекающимися ID sets берут тот же order.
3. Capability `LockedLocationSet` привязан к db root transaction+company+frozenset,
   не к row SAVEPOINT. Нельзя передать bool `already_locked=True`, создать
   глобальный bypass, пользоваться capability после commit/rollback или для
   другого db/company. `_locked_in_set` отвергает ID вне set **до** SQL lock;
   не вызывает `_barrier` для нового ID. Single _locked/update сохраняют API.
4. После C заново выполнить resolution из актуального snapshot и проверить
   evidence/cardinality, source keys, membership/O/G; reload конкретных admitted
   rows с company predicate, FOR UPDATE, populate_existing, прежде mutation.
   Выбор другого кандидата **внутри** set разрешён только при однозначном evidence
   и повторной admission; stale conflicting intent идёт в reconciliation.
   Phantom/new match **вне** set → unknown_target, без нового lock/creation.
   Изолировать affected row, сохранить raw reference; повтор планирования только
   после настоящего старого commit или rollback незакоммиченного сегмента с
   явным повтором всего сегмента. Не использовать mid-import commit ради locks.
5. Фиксированный resource order после C: point rows по opaque ID → unit rows
   по UUID bytes → document rows по UUID bytes → movement rows по UUID bytes →
   ObjectLink rows по UUID bytes; пустые категории пропускаются. Тот же order
   обязателен для подготовленных post/cancel/dismantle и link participants. До U reload
   placement: сменившийся unit/parent вне подготовленного набора → reconciliation,
   не догоняющий захват. Point→unit безопасен **только после** устранения прежнего
   U→point у затрагиваемых producers; это dependency gate, не предположение.
6. Held set не меняется до реального commit. Row SAVEPOINT ниже acquisition:
   rollback одной строки не должен лишать остальные строки barriers. Не накапливать
   side effects/counters/indexes из откатившейся строки. После `_bump` с commit,
   `_invalidate` или final cache bump capability инвалидна; следующая T заново
   планирует и acquires полный remaining set. Начальный station `_bump`
   выполнить на прежнем месте, затем acquire для следующей T до row loop и
   до `_region_id` mutation; не acquire с последующим немедленным initial commit.
   При log_id=None `_bump` не
   освобождает locks, planning context живёт до настоящего caller commit.

Почему решает I/C cycle: когда S держит C, он уже владеет каждым I из set и
больше I не запрашивает. Single writer, уже владеющий ещё не полученным I,
дождётся C и завершит, пока S **ещё не держит C**. Между двумя set writers
сортировка предотвращает обратное ожидание IDs. Это proof obligation по
advisory subgraph; row/FK/unit/document рёбра требуют шагов выше и SQL проверки.

Внешний export company-only C допустим для его **конкретной** операции без
point ID acquisition после C; он не вправе потом вызвать point command.
Для inventory producer найти через historical placements все затрагиваемые P,
взять их полный I set+C **до** U/flush, повторно проверить исторические links.
Для link transfer заранее включить оба parent point ID; link namespaced target
unit UUID не становится point ID по строковому сходству. Contract/session writers
либо остаются только FK writers без позднего I acquisition, либо переходят на
предварительный full-set contract целиком. Их нельзя автоматически считать
защищёнными от всех lost-update/race по одному FK.

Недостатки S: discovery/revalidation, длинные sets/ожидания, память/lock budget,
unknown phantoms, подготовка всех callers с ранними FK/row writes. Не увеличивать
лимит PostgreSQL ради дизайна без замеров. Нельзя честно обещать rollout B,
если эти prerequisites не вошли в принятый код.

### Вариант M: согласованная миграция всех writers на новый протокол

Конкретный target: global ID-claim phase для **всего известного create set**,
затем company barrier, затем ordered point/unit/document/link resources;
existing-only paths company-first без поздних global ID claims. Изнутри
company T нельзя решать «всё-таки create» с новым I: вместо этого conflict/replan.
Alternative pure C→global I для всех требует отдельного доказательства против
cross-company multi-ID циклов и здесь не рекомендуется.

Мигрировать одним writer epoch: native upsert(existing/new разветвление),
registry create/update, mapping add/close, W07/W08/W09/new branch, W10/session
entry, unit patch/import/movement/dismantle/post/cancel, placed_at/external_id
bulk writers, contract associations, external export. Native upsert обязан
зафиксировать preplanned create/existing intent и revalidate, не переходить
между ними после C. На время cutover остановить и дождаться **всех** старых
writer транзакций/фоновых jobs; затем переключить весь backend/CLI cohort.
Readers могут работать. Нельзя оставить старый worker с I→C и новый C→I;
новое namespace или rolling restart не являются migration barrier.

Плюсы: existing writers получают один company entrance, проще неизвестные
existing targets под C. Минусы: существенно шире PR, закрытая выборка producers
и operational drain, rollback только целым epoch. Create phantoms/cross-company
claims всё равно требуют full set либо отказа. В данной bounded задаче M не
минимален. Предпочтён S; M оставлен как отдельный coordinated project, а не
смешанная оптимизация части путей.

## 5. Контракт адаптера и reconciliation

Предлагаемые internal APIs в `services/location_commands.py`:

- `plan_location_set`/`acquire_location_set`/`locked_visible_in_set`: primitives S;
  command context = company, existing admission source, actor/source, intent,
  expected current evidence, root-T capability. Ни commit, ни session factory,
  ни scope reset внутри. Source identity indexes возвращают множества, не first.
- `apply_existing_source_patch(db, context, location_id, patch) -> SourceMutation`:
  existing only, no fallback create; allowlisted patch разбит на number changes,
  name changes, source metadata, passport fields, observed status/legacy projection.
  `_apply` общий для number freeze/history/reservation, расширение ручной DTO
  `_prepare` не требуется. Одинаковые invariants у manual и source adapter;
  источниковая authority определяется family, не новым правом пользователя.
- `SourceMutation`: applied field diff, no-op, bounded conflict reason и исходный
  row reference. Source audit перехода operational status строится по reload old
  state и коммитится вместе с изменениями; не добавлять вторую такую запись.

Защищённые metadata keys: identifierHistory, numberHistory, nameHistory,
passportHistory и server provenance; исходные значения сохраняются целиком,
истории append только владельцем операции. Source allowlist: compact
ocppId/statusDev/ownerCpo/numClass и прежние setdefault number/federalSubject;
full passport_extra H01:683–696; partial дополнительно **точные** map_stations
extra H05:290–305. Произвольный row.extra не назначает историю, metadata.number,
sourceBindings или manual override. Known source keys можно обновлять только
по существующей family authority; manual configured hubex/zoi/bu/ocppUrl
сохранять при omission, echo server metadata игнорировать. OCPP own mismatch
теперь конфликт identity до применения остальной строки, не просто warning.

Сначала expand provenance readers: предлагаемый server-owned metadata
`fieldProvenance` с field → {authority: manual|cpo_registry|sessions, source,
actor, recordedAt}; это **новый контракт**, его нет в H02/ServiceLocation.
Не расширяет публичную DTO. Supplied fieldProvenance на create отвергать422,
на update игнорировать echo/подделку с сохранением stored; старый scalar value
тоже не делает ключ editable. Native/registry wrappers помечают реально
изменённые ручные name/address/... allowlisted point fields; source adapter
читает marker, не принимает его из incoming metadata. Явный manual null тоже
защищён, иначе fill-empty его восстановит. Новые ручные записи provenance и
protected merge включать вместе; unit provenance требует своего подготовленного
writer пакета, не хранить его на point вместо unit.

Для старых labels без provenance: CPO marker сохраняет прежний приоритет;
известные source=session/auto_from_sessions можно обрабатывать по baseline;
неизвестное происхождение meaningful label → name-only reconciliation, имя
не перетирать и не объявлять его ручным автоматически. Это намеренное
ограничение по сравнению с W10, требующее отдельного baseline/candidate case.
Никакого массового угадывания или переписывания старых metadata. Полный source
replace паспорта сохраняет своё старое поведение для неотмеченных полей; ручную
защиту прошлого без доказательств обещать нельзя.

Row conflict policy: при freeze/no-reuse/malformed history/identity ambiguity
отклоняется вся промо-строка (point+unit+audit), сохраняется исходный SourceFile
и bounded reconciliation `{rowOrdinal, sourceKind, reasonCode, retryable}`;
не смешивать часть чужого паспорта с прежней identity. Для W10 это одна name
mutation; session data могут сохраниться в прежней атомарной T. ACL miss не
раскрывает hidden IDs, имён, истории или collision value. Внешний отчёт generic,
подробная сверка только под прежней admission. Reason codes: ambiguous_identity,
source_identity_mismatch, unknown_target, stale_expected_value, number_frozen,
number_reserved, malformed_history, manual_value_protected, admission_denied.

Ambiguous/new cases: multiple source/OCPP/serial/number candidates, conflicting
source vs number, touched не доказавший второе устройство, own OCPP mismatch,
исторически занятый номер или deterministic-ID conflict → **reconciliation**,
не None→new, не merge и не первая строка. Existing P/Q с разными доказанными
источниками и неизменным shared N1 обновляются раздельно и остаются двумя IDs.
Unique fresh intent без conflicts остаётся в прежней create wave вне гарантий
B; он обязан пройти собственные no-reuse/admission/reservation guards перед
подключением. До готовности этого guard adapter не передаёт такие cases в
legacy create молча: возвращает `new_identity_requires_reconciliation`.
Это сужение прежнего auto-create отдельно учитывается в acceptance; общего
bypass для AC/DC create нет. W09 auto_create=False сохраняется.

Stats compatibility: прежние поля created/updated/skipped/errors/tests/pair_split/
ambiguous/mode/message сохраняются по fixtures; updated у W07/W08 по-прежнему
число успешно обработанных existing rows, не число отличающихся колонок.
W10 возвращает int реально переименованных, включая btrim equality semantics.
Conflicts не увеличивают updated/created: errors+1, ambiguous+1 только для
ambiguity reasons; добавить bounded reconciliation count/list (например50),
не засчитывать одну строку дважды. При conflicts итог partial, не ложный success.
Это явное расширение result contract: `_run_channel_background` должен сохранять
partial, `_publish_sync_fact` не публиковать completed как безошибочный, book
aggregator учитывать partial листы и cache invalidation для фактически изменённых
данных. Эти места входят в minimal B, иначе JSON добавка не будет видна клиенту.
End-to-end consumers (F25/F26): `src/services/channelService.ts:334–344,367–382`
сейчас не описывает reconciliation. Добавить optional typed count/list с default
0/[] для old responses; список не более50 записей с generic reason и ordinal,
без raw row/source keys/hidden point data. Backend `_run_channel_background`
должен положить его в `ChannelSyncLog.events`, `run_status` и `channel_runs` явно
вернуть sanitised fields под прежним get_owned admission; DDL не требуется.
`src/pages/ChannelDetailPage.tsx` `ManualTableCard.uploadAndRun`:449–452 и `handleSync`:2252–2253
должны отдельно обработать partial как «Частично, требуется сверка» с warning
и count, error как error, success как success. Существующие status badge:686 и
`src/components/workspace/raw-panel/useRawPanelTree.ts:132` уже поддерживают
«Частично»; повторно переопределять их не нужно. Реальная UI приёмка после
implementation: upload и manual sync с одним accepted и одним frozen/ambiguous
row показывают partial без success toast; bounded раскрытие и старый response
без новых fields; hidden-value negative case. Здесь это только source и план,
UI/runtime файлы не менялись и браузерный test не выполнялся.

Старые успешные, пропущенные и ошибочные chunks остаются с прежним lifetime;
reconciliation не разрешает откатить ранее committed chunks.

## 6. Минимальный состав PR и порядок expand/readers/writers

Не один огромный retirement PR. Минимальная **когерентная** поставка B ниже;
prerequisite commits можно review отдельно, activation лишь после gates.

| Порядок | Точные файлы / функции следующего кода | Граница |
|---|---|---|
| 0. Dependency | `location_commands.py:_history_entries,_with_identifier_history,_assert_numbers_free`; immutable H19 | Интегрировать domain-separated history и повторить tests на выбранной integration SHA. Readers numberHistory остаются station-only; ни нового DDL, ни repair old aliases |
| 1. Expand | `location_commands.py:_barrier,_locked,locked_visible,_apply,merge_metadata` + proposed set/context/provenance helpers | Сохранить single-path I→C; добавить set primitive+changed_assignments+protected provenance, без подключения импорта. Capability tests на root T/commit/SAVEPOINT |
| 2. Readers/admission | `stations_normalize.py` resolution helpers/`_ingest_compact`/`ingest_stations`; `locations_router.py:create_location,update_location`; `space_registry.py:create_object,update_object` | Pure plan/revalidation, presence-aware family patches, provenance read/stamp. Сохранить native upsert и registry create/error semantics, не менять auth. Unknown old label policy явно в tests |
| 3. Protocol prerequisites | `charge_sessions_normalize.py:ingest_charge_sessions` **до** replace DELETE/pending lock; `asuim_normalize.py:ingest_asuim_book,_ingest_view`; `station_mapping.py:add_external_id,close_external_id` | Session entry получает полный set для всей T до writes; mapping сохраняет existing admission/path+commit и single barrier. Book plan должен охватить оставшиеся feeders до действительного commit; планировать по одному листу после предыдущих writes нельзя |
| 4. Unit/freeze prerequisite | `ezs_equipment.py:apply_movement,sync_placement,_sync_passport,dismantle_from_site,import_units_xlsx`; `ezs_equipment_docs.py:post_document,post_draft,cancel_document`; `equipment_router.py:patch_unit`; `locations_router.py:export_locations` | Предварительно полный affected point set, затем C, sorted resources, reload. Inventory учитывает historical placements. Вынесенный common link adapter из M05-D сохраняет caller commit ownership. Даты/cancel semantics не чинить попутно; без этого gate W07 unit writes/full freeze acceptance заблокированы |
| 5. Writers B | `stations_normalize.py:_ingest_compact,ingest_stations,refresh_location_names,_bump`; `charge_sessions_normalize.py` call W10 | Только existing updates через SourceMutation, current `_bump` locations и log_id semantics. W10 получает prepared context; standalone helper без предварительной T preparation fail closed, не поздний acquire. Не внедрять commit в domain commands |
| 6. Results | `channels_router.py:_run_channel_background,run_status,channel_runs,_run_summary`; `channel_orchestrator.py:_publish_sync_fact`; `asuim_normalize.py:ingest_asuim_book,_invalidate`; `src/services/channelService.ts:ChannelRunStatus,ChannelRun`; `src/pages/ChannelDetailPage.tsx:ManualTableCard.uploadAndRun,handleSync` | Доставить bounded sanitized partial/reconciliation до toast/log/raw-panel, с old-response fallback, без скрытого изменения атомарности/cache behavior. Ни outbox, ни per-row native projection |
| 7. Evidence | новые `server/tests/test_station_import_adapters.py`, `test_location_lock_sets.py`, `test_station_import_concurrency.py` + необходимая fixture инфраструктура | Baseline/candidate одинаковые fixtures и реальные PostgreSQL/ORM listener; только отдельным разрешённым тестовым запуском. Документы acceptance на final SHA |

В scope B не входят новые public routes/permissions/retire, schema/models/DDL,
изменение старой карты, financial remap, полная эвристическая чистка идентичностей,
перевод W08 паспорта на unit, переписывание deterministic IDs, global no-reuse
ledger rollout. M05-E `backfill_session_locations` shadow guard и W06/W20 остаются
обязательной отдельной wave до temporal retire; B не заявляет, что текущий
backfill корректен для окончательно closed historical points.

Export `locations_router.py:export_locations` (H07:172–213) сохраняет
service-key admission; implementation не подменяет её пользовательской. Если шаг4
не помещается в reviewable минимальный PR, он поставляется отдельным prerequisite
перед activation B, а не удаляется из proof obligations. Ordinary single-path
mapping уже защищён HEAD, повторный перенос старого unguarded W16 не нужен.

## 7. Baseline + candidate SQL concurrency plan (не выполнялся)

Запуск только после отдельного grant: synthetic PostgreSQL, выделенные DB,
TEST_DATABASE_URL/DATABASE_URL и UPLOAD_DIR, safety guard против realenv;
настоящие routes/callers, ORM scopes, FK, JSON и advisory keys. Сначала immutable
HEAD baseline, затем final candidate с одинаковыми test bytes, fixture seed,
barrier instrumentation и Isolation=READ COMMITTED. Нужны отдельные connections,
согласованные events/locks и bounded timeouts; sleep не доказывает interleaving.
Не monkeypatch resolver/admission/guards; допустим hooks остановки на known
acquisition points, projection stub только для изоляции внешнего I/O.

| Test ID | Baseline characterization | Candidate acceptance |
|---|---|---|
| T01 | W07/W08 family fields: full/partial/compact, append/replace, null/omitted, aliases/name/status/passport. Числа счётчиков и audit transitions | Тот же accepted-state/result, кроме перечисленных reconciliation/provenance guards; two unchanged shared N1 both update, no new alias/code history |
| T02 | Native manual number/history write между initial import cache и mutation; ещё раз между chunks | Source reload видит новое; stale import number конфликтует/не переписывает, protected history полностью сохранена, raw file доступен; no double audit |
| T03 | Naive two-ID schedule только в отдельной baseline reproduction adapter harness: T1 I(P)+C, T2 I(Q)→C, T1→I(Q) | Actual S importer берёт I(P),I(Q) до C; native POST/PATCH, registry CREATE/UPDATE и mapping ADD/CLOSE на Q завершаются без deadlock, state линейно объясним. Harness не выдавать за доказательство deadlock старого importer, который commands не вызывает |
| T04 | Two imports: reverse row order, shared/partially overlapping sets, same/different C, concurrent global opaque ID claim | Одинаковый sorted I set order, different-tenant row не FOR UPDATE; чужой занятой row не вызывает ожидания его row lock; same ID не переносится между tenants |
| T05 | После discovery создан/изменён source match вне set, несколько cands/setdefault duplicates, touched, deterministic fallback | revalidation→unknown/ambiguous reconciliation, никакого нового I после C и duplicate create; correct P/Q identity preserved |
| T06 | inventory patch / import_units / movement+passport / post_draft / multi-unit post+cancel interleave W07; ввести остановку после U и перед R | Подготовленные callers locks до U/D, sorted resource order, переместившийся unit повторно разрешён; atomic unit+point+audit, inventory не обнуляется. Не принятый prerequisite = blocked, а не skip как успех |
| T07 | ContractLocation/ChargeSession insert key-share против manual number edit; W10 после session flush, backfill touched old rows | Вся session T preplanned до FK/DELETE/row locks; freeze после вставки видит факт, prior rename остаётся последовательным. Sessions+visits+mart+cache версия прежне атомарны, нет нового mid-import commit |
| T08 | External mapping, closed mapping, historical placed_at inventory, company-wide external export racing import number | Общий protocol обеспечивает serialized decision; internal projection не freeze. External export C-only не делает поздних I. Company-wide скрытый conflict generic без утечки |
| T09 | W07/W08 errors/continue на индексах199/200/201/400, initial/final bump; log_id None/present; row/savepoint failure после diff/audit/region | Реальные прежние commit checkpoints; rollback одной строки без leaked indexes/touched/counters, ранее committed chunks сохраняются, active context инвалиден строго после настоящего commit |
| T10 | W10 cpo_registry/manual/no-provenance/session, trim equality, null nameHistory и shape variants, tie latest timestamp | Только допускаемое переименование, preserved manual/CPO, int count, history once; неизвестный label reconciliation. Все имена/metadata исходные intact после отказа |
| T11 | metadata.number-only, station_number-only, divergent/clear, malformed and hidden history; stale row.extra с forged keys | Все реально новые assignments проверены; unchanged legacy duplicate не новый conflict; typed station aliases/number reader positive controls, code-only не становится station alias, no repair unknown JSON |
| T12 | O=None/O=EMPTY/O subset + G mismatch, background channel invocation/ContextVar inheritance, foreign target; replay exact same file/lost response | Ни source context, ни Core occupancy не расширяют ACL; hidden no entity serialization. Идемпотентные изменения/истории, ожидаемые old counters; partial в UI/run fact/book, raw retained; UI upload/sync acceptance отдельно от SQL, без ложного success и hidden values |
| T13 | Native projection skipped/failed/raised после flush, registry audit и import downstream exception | Старые commit/error contracts сохранены, command без commit, rollback снимает mutation+history. Не перемещать native projection за commit без отдельного outbox проекта |
| T14 | Книга stations→connectors→sessions с промежуточными _bump/_invalidate и caller cache commit | Новая T каждый раз получает свежий полный set; в T, продолжающей другой feeder, нет поздних I и stale unit maps; cache invalidation не пропадает от partial |

SQL evidence сохранять вне public repo, публиковать только synthetic итог/хеши.
Проверять final state, отсутствие unintended writes/aliases и wait graph,
не только вызов helper. Записывать transaction boundaries и blocking locks;
не считать отсутствие deadlock в одном прогоне доказательством всех расписаний.
Baseline failures нового контракта отделить от воспроизведённой старой ошибки.
Нужны rollback/cleanup own DB и отсутствие оставленных соединений/locks.

## 8. Совместимость, откат, критерии и блокеры

Old/new contracts: IDs/URL/company/source bindings неизменны; manual DTO/null и
native upsert/registry create различаются как прежде. Shared current numbers не
получают unique constraint; no-reuse и сохранение inventory уже обязательны и
не предлагаются как продуктовый выбор. CPO precedence, partial omission,
legacy status projection и passport owner сохраняются; новые отказы перечислены
явно: ambiguous new/create, protected manual, unknown target, freeze/history.
Backward readers могут игнорировать новые metadata keys, но **writers** не
взаимозаменяемы: старые imports пишут без guards и могут потерять history.

Rollback до activation: code revert additive helpers без data rewrite.
После начала typed history/provenance записи: остановить old import jobs и
mutating callers до отката, оставить read access, проверить pending transactions;
не считать revert на H02 совместимым с typed reservations H19. Использовать
последний version, понимающий protected keys и обе истории, либо держать writes
выключенными. При S старые single writers с теми же I/C keys lock-совместимы,
но старые unit/import writers не объявляются data-совместимыми. При M rollback
только всем drained cohort, не смешивать epochs. Никаких destructive down/alias
cleanup, новых commits посреди импорта или разрыва unit+placement атомарности.

Приёмка следующего кода:

- Final source diff ограничен принятым PR set; H19 dependency закреплена и
  re-reviewed, old ACL/native/mapping regressions проходят на final SHA.
- На всех принятых import paths нет mutation существующего point вне общей
  boundary, late I acquisition после C, stale ORM merge или source forged history.
- Actual baseline/candidate T01–T14 и meaningful concurrency outcomes зафиксированы;
  прежние stats/chunks/audit/projection и source raw подтверждены отдельно.
- Conflict виден как bounded reconciliation/partial, не duplicate creation и не
  success с молча потерянной строкой; unchanged shared N1 работает.
- Unit/link/freeze participants подготовлены до activation; не закрыты — B blocked
  в соответствующей части. HTTP acceptance и полный security scan отдельные gates,
  этот design их не заменяет.

Реальные blockers implementation: (B1) протокол охватывает transaction callers,
включая multi-sheet книгу и ранние session locks; до этого row helper не подключать.
(B2) unit-first/document-first producers и inventory/export без общего protocol:
нужна согласованная prerequisite поставка, не локальная перестановка locks.
(B3) нет достоверной provenance старых ручных labels/passport; ограничить новые
writes и reconciliation, не придумывать прошлое. (B4) new import intents сейчас
обходят canonical reservation/admission; creation wave ещё не готова, ambiguous
и неподготовленные fresh cases fail closed. (B5) исторический no-reuse не полон
без persistent ledger и удаления старых bypass; это уже канон будущей wave,
не основание ослаблять B guards; receipt cancellation F23 также не объявляется сохранением inventory. (B6) отсутствует SQL/HTTP/runtime evidence данного
пакета; проверка lock budget/load/real constraints остаётся открытой.

Этот пакет выполнен как два документа с проверкой immutable source references,
JSON структуры и diff whitespace. Он не включает реализацию, тестовый прогон,
security verdict, выпуск или приёмку реального пространства.
