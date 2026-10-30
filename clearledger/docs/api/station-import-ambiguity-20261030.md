# M05-B: неоднозначная identity при импорте ЭЗС

Состояние: **bounded candidate принят author-проверками: 37 PASS, combined 485 PASS**.
Actual synthetic baseline: 24 FAIL / 13 PASS на тех же test bytes. Own DB
очищена и удалена, SQL_SLOT_RELEASED. Root merged repeat остаётся отдельным gate.
Это bounded часть B, не приёмка всей модернизации импортов.

База отдельного worktree `api-station-import-ambiguity-20261030`, ветка
`MagLook/alewife`: actual HEAD/source commit
`39d81ad775d2f195036ae673928158f2f311f5df`, исходно clean.
Root worktree на момент чтения имел тот же HEAD. Fetch/pull не выполнялся:
dispatch запрещает network и фиксирует actual root SHA.

`stations_normalize.py` Git blob `8600c456e4bc5cf46e1f46ff2d965e0bbc742493`,
SHA256 `0cfde91babd868d56b7f472875d396180d7d3e4fb74f9b9b80ce75a6e9ba7645`.
Читались корневой/clearledger `CLAUDE.md`, текущий канон среды и M05 design
F05–F09/F19, ambiguous/new cases. Изначальный ownership: этот документ и новый
`server/tests/test_station_import_ambiguity.py`; после baseline root отдельно
разрешил `stations_normalize.py`, итоговый patch ограничен этими тремя файлами.

## Source facts и область baseline

| Вход | Actual путь и риск |
|---|---|
| XLSX compact | `parse_stations_xlsx` распознаёт заголовок Номер/Название/OCPP; `_parse_compact`; public `ingest_stations` вызывает `_ingest_compact`. |
| XLSX full | Тот же parser, лист «Станции», 36 колонок → public `ingest_stations`. |
| Partial | `asuim_normalize.map_stations` передаёт словари с `partial=True` в тот же public importer; тесты этого пакета готовят synthetic mapped rows, не заявляют проверку ASUIM parser/book. |
| W07 indexes | `by_ocpp` и mixed `by_ident` используют `setdefault`: несколько existing candidates скрыты за первым. `by_num` хранит все строки. OCPP и mixed идентификаторы могут указывать на разные точки, `or` выбирает OCPP. |
| W07 ambiguous number | Несколько number candidates добавляют текст в ambiguous; `loc` остаётся `None`, затем deterministic fallback и new branch всё ещё доступны. |
| W07 own OCPP mismatch | При unique number fallback различающийся stored OCPP сохраняется, но operational status, имя, unit passport и audit уже меняются; return status остаётся success. |
| W07 touched | Повторное попадание в touched превращается в `None` с `pair_split += 1`; это действующий путь intentional AC/DC split. Его нельзя blanket-запретить без согласования. |
| W08 indexes | Source/code и serial используют `setdefault`. `_resolve` выбирает source перед serial, конфликтующие strong matches не сравнивает; несколько number candidates возвращают `None`, как и неизвестная identity. |
| W08 new | После такого `None` возможен deterministic create. Unique serial с новым source ID явно разрешён старой логикой как enrichment; этот control сохранён. |
| Counters/status | Обе ветки возвращают success даже при ambiguous/errors. W07/W08 existing writes обходят commands, W07 может менять linked unit через actual `write_value`. |

Номер площадки не уникален: две existing AC/DC карточки с shared current number
и различными source/OCPP обязаны остаться двумя IDs. Shared number сам по себе
не опровергает unique strong match. Unique index serial использует `lower`,
но importer индексирует `strip`: допустимая index-ом пара `same-serial` /
` same-serial ` позволяет проверить неоднозначность без удаления constraints.
Точные дубли serial native index отклоняет; тест не отключает этот индекс и
не выдаёт невозможный seed за actual дефект.

## Подготовленные проверки

Новый файл содержит **37 collected/executed кейсов**, 0 ERROR / 0 SKIP.
Test SHA256: `e4c4953d94791f1f36abd687c1e518a983eecb338324747cc087d1cbc2dbe296`.
Реальная native PG fixture `test_location_commands.world` даёт synthetic
companies/points и штатный `setup_database` с migrations/unique indexes;
добавлены actual linked units, `placed_at`, history и непустой inventory.
Actual ORM scope listener установлен; resolver, new branch и passport writer
не подменяются. Унаследованный projection stub native fixture импортер не
вызывает, это не доказательство native HTTP/projection поведения.

Каждая primary regression сначала сравнивает свежий committed snapshot всех
колонок point/unit/link/region/raw/audit, потом counters/status. JUnit properties
сохраняют actual result, counts и identity/status points до assert. Отсутствие
нового API-символа не служит baseline finding. SourceFile row и XLSX bytes
проверяются на сохранность, но actual upload/channel orchestration не вызывается.

Покрыты multiple number candidates для трёх families и append/replace;
duplicate OCPP/source/trimmed serial; source→P/serial→Q; OCPP→P/source→Q;
own OCPP mismatch; deterministic fallback после ambiguous number;
mixed accepted/rejected rows; 55 conflicts с bounded 50 details.
Положительные controls: unique stronger match двух legacy shared-number IDs,
serial enrichment с новым source ID, append skip, replace update, actual
full/compact parser, unique fresh create/replay и intentional pair_split/replay.
После root review добавлено различие W07 same strong OCPP/source повтор
на non-deterministic existing ID против distinct-new-OCPP pair_split, а также
положительный W08 same-source повтор с прежним updated=2.
Partial omission и unchanged history/inventory проверяются в controls.

## Согласованный root минимум

1. Только после actual baseline: множества candidate IDs и явный internal
   resolution outcome existing/new/ambiguous вместо first/None collapse.
   Несколько strong candidates либо source/OCPP/serial, указывающие на разные
   existing IDs, отклоняются до point/unit/audit/region mutation. Shared number
   не блокирует unique stronger source/OCPP match прежней карточки.
   Повтор одной строки с тем же доказанным strong key на W07 existing ID
   пропускается как duplicate row (не pair_split/new); W08 сохраняет
   прежнее повторное existing update. Это предложение до baseline, не finding.
2. Multiple-number без strong match не доходит до deterministic fallback/new.
   Own OCPP mismatch также отклоняет всю строку. Unique serial enrichment,
   unchanged legacy AC/DC, append/replace/full/partial и доказанный intentional
   pair_split остаются прежними. Не предлагать запрет всех fresh creates:
   broad `new_identity_requires_reconciliation` из полного B не включён в этот
   bounded guard без отдельного согласования.
3. Для каждой rejected строки errors+1, ambiguous+1, created/updated без роста;
   status partial. Additive `reconciliation_count` и `reconciliation` до50
   записей `{rowOrdinal,sourceKind,reasonCode,retryable}` с generic reason без
   raw keys/hidden IDs. Это tentative shape; root должен согласовать delivery
   с отдельным владельцем channel partial package. Ни DDL, ни public route.

Root отдельно согласовал этот минимум после actual baseline; guard внесён
только в `stations_normalize.py`. Это не SourcePatch, не новый lock epoch,
не unit-writer rollout. Нет обещаний
concurrent/global no-reuse, freeze, revalidation между chunks, full multirow
race, SourceFile upload admission или клиентского toast до отдельной приёмки.
Related facts/lock order/full multirow prerequisites полного B остаются открыты.

## Запуск и guard: только после exact grant

До отдельного root GO SQL/connect/admin/pytest/opt-out не выполнялись.
После завершения root independent564 и normalDROP получен baseline-only GO
именно в этот dispatch. Использована отдельная собственная БД
`api_station_import_ambiguity_test`; module guard дополнительно к общему
`partner_test_safety_error` требует именно host/port/name, APP_ENV=test и
DATABASE_URL=TEST_DATABASE_URL. Native fixture также требует
`RUN_OBJECT_COMMAND_TESTS=1`; новый flag
`RUN_STATION_IMPORT_AMBIGUITY_TESTS=1`.

При каждом разрешённом прогоне runner обязан до первого connect проверить exact synthetic
target, выставить APP_ENV=test, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 и явный
`-p pytest_asyncio.plugin`, обе равные URL, абсолютные PYTHONPATH/UPLOAD_DIR,
отдельный test UPLOAD_DIR; empty cwd, без HOME/CODEX_HOME override и без dotenv
из проекта. Setup, baseline pytest, candidate pytest и normal own DROP строго
последовательно. Native conftest разрешён только own DB, он destructive.
Baseline — immutable actual HEAD и **те же final test bytes**, candidate-only
asserts/controls отделяются от реально воспроизведённого persisted-state дефекта.
Baseline/candidate evidence и cleanup должны фиксировать SHA, реальные counts,
exit/reaped, own conns0; без terminate/FORCE/изменений PG settings.

## Actual baseline 30.10.2026

На immutable HEAD `39d81ad775d2f195036ae673928158f2f311f5df`, source SHA256
`0cfde91babd868d56b7f472875d396180d7d3e4fb74f9b9b80ce75a6e9ba7645` и
тех же test bytes `e4c4953d94791f1f36abd687c1e518a983eecb338324747cc087d1cbc2dbe296`:
**24 FAIL, 13 PASS, 0 ERROR, 0 SKIP, 21,34 с; child EXIT1/reaped**.
Все regression failures возникли на actual persisted-state asserts, а не на
отсутствующих новых reconciliation fields. Fixture ошибок не было; trapped
bcrypt-version warning от существующего seed не мешал setup/тестам/cleanup.

| Cases | Actual результат старого runtime |
|---|---|
| Shared number без stronger match, 3 families × 2 modes | points 2→3, created=1, errors=0, ambiguous=1, status=success; synthetic region 0→1. |
| Multiple OCPP/source/trimmed serial, 5 cases | Выбрана одна из двух карточек, updated=1, status=success, errors=0; изменены имя/status/passport, audit 0→1, region 0→1. Порядок выбранного кандидата не является контрактом. |
| source→P / serial→Q, 2 cases | Серийник P сохранён, но остальные поля P перезаписаны, updated=1, audit 0→1, status=success. |
| Own OCPP mismatch | Stored OCPP сохранён; point/unit и audit всё равно изменены; updated=1, ambiguous=1, errors=0, status=success. |
| OCPP→P / source→Q | Обновлён P; audit 0→1, ambiguous=0, errors=0, status=success. |
| Ambiguous number → deterministic existing fallback | Point count остался3; unrelated point с другим текущим номером получил incoming name/no_link, audit 0→1, updated=1, ambiguous=1, status=success. |
| Actual compact/full XLSX, 2 cases | SourceFile count1 и байты сохранены; point count2→3, created=1, ambiguous=1, status=success. |
| W07 repeated same strong OCPP/source, 2 cases | points2→3, created=1, updated=1, pair_split=1, errors=0, status=success; non-deterministic existing ID не предотвратил дубль. |
| Mixed accepted/rejected, 3 families | points2→3, created=1+updated=1, errors=0, ambiguous=1, status=success. |
| 55 ambiguous rows | points2→3, created=1, skipped=54, errors=0, ambiguous=55, details50, status=success. |

Все **13 positive controls PASS**: stronger unique source/OCPP сохраняет две
legacy shared-number карточки; append skips, full/partial/compact replace и
nullable omission semantics прежние; inventory/history/links сохранены;
serial enrichment с новым source ID разрешён; intentional distinct-OCPP
AC/DC split/replay и fresh full/compact create/replay работают; W08 repeated
same source сохраняет updated=2. Это реальные synthetic negative/positive
результаты, а не утверждение об incident/client data.

Private artifacts (в git не добавляются):
`.artifacts/station-import-ambiguity-baseline.py`,
`.artifacts/station-import-baseline.log`, `.artifacts/station-import-baseline.xml`.
XML SHA256 `c918482cbe65e7a889b446cb11df5ae5acc1a45a8e191e749210999e44d84247`;
log SHA256 `adf019daa66fbeb459f54c98c326101d803586efbb8a05408cbc6cb8ac4b9a61`.
Baseline выполнялся assigned interpreter
`/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`.
Runner проверял source/test SHA и HEAD до каждого действия, exact URI и общий
guard до import pytest, flags только OBJECT_COMMAND/STATION_IMPORT_AMBIGUITY,
пустой cwd, явный async plugin, test UPLOAD_DIR и APP_ENV=test.

Cleanup выполнен строго после завершения pytest: fresh public/edge tables0,
ownconns0; normal own DROP; fresh DBexists0/ownconns0/otherclients0/maxlocks64;
все admin/probe connections закрыты. **SQL_SLOT_RELEASED** передан root.
На момент baseline runtime не изменялся; последующий candidate подготовлен
только после отдельного root ответа. Новый SQL/candidate запуск требует нового
grant; baseline grant завершён. В baseline-фазе коммит/push не выполнялись.

## Candidate и итоговые проверки

Runtime SHA256 `007c1c17e564a09388f95f2c7c11d13b548b8f985bab4011d5ec8251d45b798d`.
Test SHA256 остался `e4c4953d94791f1f36abd687c1e518a983eecb338324747cc087d1cbc2dbe296`:
baseline и candidate используют те же37test bytes.

Из существующих top-level functions изменены только `_ingest_compact` и
`ingest_stations` (включая её local `_resolve`); остальные20functions побайтово
совпадают по исходным AST segments. Добавлены internal dataclass
`_StationIdentity` и helpers `_station_identity`, `_index_station`,
`_reconcile_station_identity`. Strong indexes хранят все IDs; rejection
проверяется до row writes; W07 strong touched повтор увеличивает только skipped,
number fallback с новым distinct OCPP сохраняет прежний pair_split. Возвращаются
partial и точный reconciliation_count только при новых identity conflicts;
прочая legacy exception/status политика не расширяется. Старые result keys/types
сохранены; ambiguous_keys теперь generic строки с ordinal без candidate keys/IDs.
Барьеры, `_bump`, commit/checkpoint code, source ownership и passport writer
не менялись. SourceFile retention проверяется теми же actual file tests.

AST и `git diff --check` PASS. Source search по
`server/tests` не нашёл прежних прямых parser/ingest tests, кроме нового файла.
Смежные существующие `test_station_canon.py` (4 normalization cases) и
`test_stations_region_ci.py` (3 actual resolver cases) включены дополнительно
к37новым+прежним441 = **485 author cases, все PASS**. Source-number123 отсутствует
в author base; будущий root combined repeat не выдаётся за author evidence.

| Проверка | Результат |
|---|---|
| Baseline, immutable39d, final same-test | 24 FAIL / 13 PASS, 21,34с; EXIT1/reaped, 0 ERROR/SKIP. |
| Candidate, final same37test bytes | **37 PASS**, 20,44с; EXIT0/reaped, 0 FAIL/ERROR/SKIP. |
| Candidate combined: new37 + previous441 + canon4 + region3 | **485 PASS**, 66,05с; EXIT0/reaped, 0 FAIL/ERROR/SKIP/DESELECTED. |
| Opt-out, `--noconftest`, own flag отсутствует | 1 module SKIP, collected0, 0,36с; штатный EXIT5/reaped, fixtures не запрошены. |
| Final cleanup после combined/opt-out | Fresh public/edge tables0, ownconns0; normal own DROP; DBexists0/ownconns0/otherclients0/maxlocks64, probes closed. |
| Root merged independent | Pending: ожидается608 с source-number123; не author PASS. |

Каждый из24regression cases теперь PASS: ambiguous rows не меняют ни point,
ни unit/link/region/audit, не создают дубль и возвращают partial/errors+1.
Mixed files сохраняют ровно accepted update без лишнего create. На55conflicts
actual result: created0/updated0/skipped0/errors55/ambiguous55,
reconciliation_count55/details50, statuspartial, сохранённый snapshot неизменён.
Все13positivecontrols снова PASS, включая distinct-OCPP pair_split и повтор,
unique fresh create/replay, stronger unique match обеих shared-number карточек,
serial enrichment, W08 repeat updated2 и прежние nullable omission semantics.

Candidate runner использовал те же exact URI/guards, выделенный interpreter,
пустой cwd, APP_ENV=test, PYTHONNOUSERSITE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 и
явный pytest_asyncio plugin, равные test URLs, отдельный UPLOAD_DIR и все8opt-ins.
Baseline → освобождение слота → отдельный runtime grant → code review →
отдельный candidate SQL grant соблюдены. Setup, candidate37, combined485,
opt-out и normal DROP выполнялись последовательно; новых повторов после PASS нет.

Дополнительные private evidence: `.artifacts/station-import-ambiguity-candidate.py`,
`.artifacts/station-import-{candidate,combined,optout}.{log,xml}`. Runner и
синтетические credentials не коммитятся. Final runtime/test SHA выше неизменны;
отчёт фиксирует проверенный code state, а итоговый commit SHA сообщается root
отдельно, чтобы не создавать самоссылочный hash документа.
Candidate XML SHA256 `96bdb28c964f76fe56a5762a4b34b23212b091c93b7dfe500faa7a1f909312d0`;
combined XML SHA256 `b8ac56ee8ad074fbe0114ce02362c04e62d4e70250d57d0ec3f96fcfc695986f`.

Приёмка ограничена synthetic sequential PG paths и перечисленными прежними
регрессиями. Scalar legacy metadata, stale indexes после последующих mutations,
concurrent/global identity/no-reuse, полный multirow race и оставшиеся protocol
prerequisites не объявляются решёнными. Клиентский upload/sync toast, HTTP,
security scan, стенд и production не проверялись этим worker-ом. Откат: revert
трёх файлов без переписывания данных; он возвращает воспроизведённую прежнюю
небезопасную обработку неоднозначных строк.
