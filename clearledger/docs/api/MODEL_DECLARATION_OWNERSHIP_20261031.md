# M16-C1: единственный владелец ORM-объявления

Дата: 31.10.2026. База: `81a8e516c3037bd507e35de05e806138b8961c77`.
Статус: ROOT V5 PASS, четыре fresh payload совпали побайтно; три повтора ORM-объявлений устранены.
Это ограниченный source refactor трёх полей. Остальные задачи M16 и общая цель M00–M19 остаются открытыми.

## Изменение и основание

AST исходной модели подтвердил по два объявления `Contract.valid_until`,
`ReconcileMapping.created_at`, `ReconcileMapping.updated_at`. В Python последнее
присваивание определяет значение, первое сохраняет позицию ключа в словаре класса
и аннотациях. Действующие последние выражения перенесены в позицию первого ключа;
у каждого поля осталось одно объявление. У timestamp-полей сохранено отсутствие
явного `nullable=False`: действующая nullable-семантика выводится из `Mapped[datetime]`.

В установленном SQLAlchemy 2.0.36 `orm/decl_base.py::_cls_attr_resolver` объединяет
порядок `vars(cls)` и аннотаций; `_extract_declared_columns` сохраняет его в OrderedSet,
`_setup_table` стабильно сортирует по `MappedColumn.columns_to_assign` / `sort_order`.
Значение по умолчанию для `sort_order` равно нулю. Удаление первого `valid_until`
перенесло бы колонку из позиции после `title` в позицию после `signer_cp_basis`.
Применённое решение оставляет исходную позицию. Явные `sort_order`, placeholder,
миграции и изменения других классов не добавлены.

ROOT согласовал решение в ответе `msg_389a4cf83a87` на `msg_1c839ce71b08`.
AST-сравнение подтвердило идентичность прежних LAST annotation/RHS и всех остальных
узлов модуля после удаления только этих трёх повторов. Поиск `_creation_order`
в production app/scripts и прежних tests не нашёл потребителей. Приватный абсолютный
счётчик аллокаций SQLAlchemy изменяется при удалении неиспользованных объектов;
это не доказательство сохранности metadata. Любое изменение наблюдаемого порядка,
имён или DDL означает FAIL и требует нового review, без корректировки expected/schema.

## Frozen source V5

| Источник | SHA-256 / состав |
|---|---|
| Исходный `models.py` из базы | `6aef22c515d013e282e02f39bde3431d94d45fb25077d056144250b606b509a1` |
| Кандидат `models.py` | `f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e` |
| `tests/model_declaration_ownership_approved.py` | `786daada5c33583281613d74e400fc694d9f0a1f192dffa979e634210e4cd7bb` |
| Полный `server/app` | 498 файлов; `03ebbf3edacef2eee1f5f8cd815ecb5add677ba313c09dce66f26a87bd78b8a9` |
| Полный `server/tests`, кроме самого helper | 368 файлов; `e7083210c983b0769d0ce1e34009a3d4171cc788b050f1c172879c789cc9f524` |
| Полный `server/schema_migrations` | 16 файлов; `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| Полный установленный `sqlalchemy`, без bytecode cache | 268 файлов; `a6476b4195ce507ae5c42a7dbcfec0ee256935ea27ae60e6047799e56f010beb` |
| Официальный `scripts/export-partner-openapi.py` | `b5d52daca7220a523b4c5edc85852de39b0b921e5c033a86029b2f92040abd51` |

Tree digest: SHA-256 компактного JSON массива `[relative_path, file_sha256]`, пути
отсортированы, относительны `server` (для SQLAlchemy: site-packages). Исключены только
`__pycache__` и сам helper из tests. Девять support/tool hashes, включая requirements,
pytest.ini, Dockerfile и официальный SDK generator/lock/tests/consumer, зафиксированы
в `SUPPORT`; весь принятый candidate77 inventory 61+16 зафиксирован в `RUNTIME`/`TOOLS`.
Ни exporter, ни SDK, ни зависимости в этом пакете не меняются.

## Контракт полного proof

Один запуск helper означает один новый процесс. ROOT выполняет baseline дважды,
затем candidate дважды; все четыре stdout должны совпасть побайтно. В stdout входят:

- Все 330 ORM-классов из `models`, `models_dedup`, `models_partner`,
  `models_docs_portal`, `models_product_budget`. Регистрация каждого класса проверяется.
- Вся metadata: схемы, naming convention, порядок таблиц и колонок, имена и quoting,
  типы и их параметры/cache keys/variants, nullable и declared nullable, defaults,
  onupdate/server defaults, computed/identity, FK с порядком составных элементов,
  PK/check/unique/index и dialect options, sequence/enum, comments/info.
- Реально скомпилированные PostgreSQL CreateTable/CreateIndex/CreateSequence,
  enum DDL и ALTER для use_alter constraints. DDL сохраняется дословно.
- Порядок mapper properties и аннотаций всех классов, колонки ColumnProperty.
  `iterate_properties` не вызывает дополнительную конфигурацию mapper relationships.
- Полная фактическая curated OpenAPI от неизменённого официального exporter,
  включая прежние 15 operations и auth profiles.

Нормализация `explicit-v2` ограничена известными типами. Python callables представлены
module/qualname/типом, байткодом, constants/names/varnames/freevars/cellvars, аргументами,
flags, exception table, defaults/kwdefaults, closure cells и `__wrapped__`; closure callable
раскрывается рекурсивно, остальные значения проходят тот же строгий normalizer.
Для builtin bound callables сохраняется владелец. Не вызываются defaults, uuid4 или
генераторы времени. Не сохраняются адреса объектов и пути/номера строк code objects;
исполняемый код и привязанные значения сохраняются. Неизвестное значение или callable
останавливает proof для review. Нет общего удаления `repr`, адресов или SQL-фрагментов.
Списки/кортежи/словарь сохраняют порядок; сортируются только настоящие unordered sets,
включая table.indexes и column.foreign_keys. Одна отдельная source-proven exception:
`TypeEngine._static_cache_key` строит keyword-state хвост из set, возвращённого
`get_cls_kwargs` (`sql/type_api.py:978–995`, `util/langhelpers.py:424–475`). Только этот
хвост сортируется по имени ключа. Проверяются точный class head, provenance base
descriptor, уникальные публичные ключи, полный ожидаемый constructor keyset и identity
каждого значения с реальным attribute либо cached tuple вложенного TypeEngine.
Вложенные типы обрабатываются так же; обычные tuple-значения сохраняют свой порядок.
ExternalType/custom override/unknown sentinel/shape/duplicate/mismatch означают FAIL.
Cache keys и значения не удаляются. ROOT одобрил исключение в `msg_5e70158b77af`.
Constraint order берётся из настоящего
`table._sorted_constraints`, который использует относительный `_creation_order`.

## ROOT-only запуск

Worker helper не импортирует и не исполняет. До runtime ROOT проверяет эти исходники
и frozen hashes. Базовый blob ROOT извлекает без импорта приложения:

```sh
umask 077
mkdir /tmp/api-model-declaration-ownership-test-20261031-ctx8550
git show 81a8e516c3037bd507e35de05e806138b8961c77:clearledger/server/app/models.py > /tmp/api-model-declaration-ownership-test-20261031-ctx8550/baseline-models.py
```

Для каждого из `baseline-1`, `baseline-2`, `candidate-1`, `candidate-2` создаётся
отдельный пустой owned 0700 cwd вне source. Пример точного argv/env для первого:

```sh
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test PYTHONDONTWRITEBYTECODE=1 ROOT_APPROVED_MODEL_DECLARATION=1 \
  M16_RUNNER_SHA256=786daada5c33583281613d74e400fc694d9f0a1f192dffa979e634210e4cd7bb \
  M16_MODE=baseline \
  M16_BASELINE_BLOB=/tmp/api-model-declaration-ownership-test-20261031-ctx8550/baseline-models.py \
  M16_EMPTY_CWD=/tmp/api-model-declaration-ownership-test-20261031-ctx8550/cwd-baseline-1 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/model_declaration_ownership_approved.py \
  --export-approved-model-metadata
```

ROOT устанавливает указанный cwd перед запуском. Для остальных запусков меняются
только mode и cwd. stdout/receipts stderr захватывает родитель ROOT в свои ignored
artifacts; child ничего не пишет в файловую систему. Лимиты child: CPU60s,
wall alarm120s, RAM1GiB, FD64, stdout16MiB. ROOT ограничивает stderr64KiB,
ставит внешний timeout125s с TERM/KILL/reap и сохраняет exit codes/хеши/размеры.
По окончании ROOT удаляет только собственные tmp cwd/blob; чужие artifacts сохраняются.

До импорта third-party проверяются interpreter3.13.7/glibc2.36, `-I -S -B`, чистый env,
точный candidate77, immutable source/tools, отсутствие site hooks/symlink и dotenv.
Используется официальный schema-only DeclarativeBase adapter; актуальный model blob
подставляет узкий import loader только для `app.models`, без правки production.
`app.database` не исполняется; config/main/auth/partner_identity запрещены.
Audit запрещает сеть/DNS/socket, subprocess/exec/fork, ctypes, запись/мутации файлов
и чтение вне источников/stdlib/candidate. Exporter может очистить env и поставить
только LANG/PYTHONDONTWRITEBYTECODE. Нет SQL, create_all, подключения, сервера,
pytest collection, миграций, codegen, внешнего трафика или чтения секретов.

## Результаты и пределы

Worker выполнил только чтение, AST-сравнение и compile без исполнения моделей/helper.
ROOT V1 source review подтвердил изменение ровно трёх LAST-effective declarations
и отсутствие остальных изменений app. Первый actual baseline1 завершился exit1,
reaped за 0.610s, stdout0: SourceFileLoader попытался прочитать
`scripts/__pycache__/export-partner-openapi.cpython-313.pyc` за пределами read roots.
Guard корректно отказал; модели ещё не импортировались, metadata parity не заявляется.
ROOT evidence: `.artifacts/root-model-declaration-review-20261031/`
(`processes.json`, `baseline-1.stderr`, `source-review.json`), receipt `msg_5fdccc2b1e06`.

По прямому решению ROOT V2 читает pinned exporter source и выполняет compile/exec
в ModuleType с тем же `__file__` и отдельным `__name__`, без bytecode probe.
Production, normalizer, guards, все source/tool pins и runtime limits неизменны.
V1 helper SHA `1c43df459aa3670d8d1b6d43cb9f85c4d7d8c087a448b2912aa28b8852538e72`
и прежний report сохранены локально в ignored
`.artifacts/model-declaration-ownership-worker-20261031/`.
ROOT V2 baseline1 завершился exit1/reaped за 4.542s, stdout0; sourceAfter неизменён.
Финальная проверка сообщила `runtime modules or forbidden activity`, не различая
накопленный deny, запрещённые модули и pytest. Evidence:
`.artifacts/root-model-declaration-review-20261031/v2/`, receipt `msg_4bd404a1843e`.
V3 по решению ROOT добавляет только безопасную диагностику: до 16 событий,
категория причины, audit event, до восьми stack entries module/function/line,
имена запрещённых модулей и флаг pytest. Пути и произвольные error contents не выводятся.
Каждый deny по-прежнему немедленно отказывает и сохраняет FAIL финальной проверки,
даже если сторонний код перехватил исключение. Guards/normalizer/pins не ослаблены.
V2 helper/report сохранены рядом с V1, исходный helper SHA
`e5dcff0841b387cd9bfb48cbfb00f7b3745cb2e4606b209f3a518fd3ed83b27a`.
ROOT V3 diagnostic baseline завершился exit1/reaped за 4.4144s: blocked modules пусты,
pytest false; построены 330 таблиц / 4587 колонок / 330 mapper / 1 sequence.
Единственный recovered deny: importlib.metadata → zipfile пробовал открыть отсутствующий
interpreter ZIP из sys.path. Evidence `.artifacts/root-model-declaration-review-20261031/v3/`,
receipt `msg_6d6494d152c5`. Full parity по этому запуску не заявляется.
По решению ROOT V4 до установки boundary оставляет только существующие каталоги
проверенной stdlib (включая lib-dynload), затем добавляет ровно SERVER/SITE.
Удаляется только точный отсутствующий `STDLIB.parent/python313.zip`; неизвестная
существующая или другая отсутствующая запись приводит к отказу. ZIP/read-root
разрешения не добавлены, recovered deny по-прежнему означает FAIL.
V3 helper/report сохранены рядом с V1/V2; SHA helper
`3cb5a5e380f7e6df49bbd4decfe20000b0935a857f5a9404ada095c217b1d3c5`.
ROOT V4 baseline1/2 оба exit0/reaped за 4.627s/4.418s, по 12 604 305 байт,
denied пуст, sourceAfter true. До candidate выполнение остановлено:
1572 различия касались только перестановки keyword-пар type cache keys;
DDL, ORM, counts и полная API schema равны. Evidence:
`.artifacts/root-model-declaration-review-20261031/v4/`, receipt `msg_cbf5e2223470`.
Source diagnosis подтверждён точными SHA SQLAlchemy `type_api.py`
`48dd7afe83591ba1bae5cbc6e8004f729b73fd8579bdf0767e49f0259c6b90eb`
и `langhelpers.py` `b882b7b3366eabd68c9cefaf1294a535e90d5afe08f84dfdd5ee7a6e44e7526d`.
V5 вводит только описанную `explicit-v2` exception; production/guards/pins неизменны.
V4 helper/report сохранены рядом с V1–V3; SHA helper
`dc375055aa6814fdf51dbf6b1027e7ac5a078b91bc47a70a6394a65b2eadafb6`.
ROOT V5 принят receipt `msg_31748a41301f`. Четыре fresh process capture:

| Запуск | Exit / reaped | Время | Stdout |
|---|---|---|---|
| baseline-1 | 0 / true | 4.6356s | 12 364 117 bytes |
| baseline-2 | 0 / true | 4.4271s | 12 364 117 bytes |
| candidate-1 | 0 / true | 4.6208s | 12 364 117 bytes |
| candidate-2 | 0 / true | 4.5210s | 12 364 117 bytes |

ROOT выполнил независимое побайтное сравнение всех четырёх payload, а не только
сравнение хешей. Общий SHA-256:
`e5a4b3743651c30f97aad52e45367f4799e85934175d1d0c4de3d5c1356855ca`.
Полные metadata/compiled PostgreSQL DDL/ORM order/annotations/curated API равны:
330 таблиц, 4587 колонок, 330 mapper, 1 sequence, 0 enum; все прежние 15 operations
и auth profiles сохранены. SourceAfter full manifest true; candidate77,
SQLAlchemy268 и девять support/tool pins подтверждены. Denied events пусты,
SQL0/network0/filesystem writes0. ROOT удалил только собственные временные blob/cwd.
Evidence: `.artifacts/root-model-declaration-review-20261031/v5/`
(`source-review.json`, `processes.json`, четыре полных JSON, `acceptance.json`).
V1–V4 отказы и исходная недетерминированность сохранены как история; их результаты
не подменяют V5. Production и helper после приёмки не менялись, обновлён только отчёт.
Даже равенство metadata/DDL не подтверждает fresh/upgrade/restore существующих БД,
совместимость всего bootstrap, readiness всех runtime путей, CI или release.
