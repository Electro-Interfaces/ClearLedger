# DEP-1: приёмка зависимостей в целевом образе

Дата: 30.10.2026. ROOT принял чистую offline-установку: 59 runtime distributions
плюс `pip==26.2.2`, точный metadata inventory и `pip check`. Успешный повтор v3
завершился за 21,096977875 с; собственный scratch и внешние объекты запуска очищены.
Опубликованы четыре разрешённых provisional файла. Runtime не активирован.

Первый полный run v2 завершился FAIL за 29,114987042 с во время runtime install.
Его свидетельство сохранено. В v3 повторена только не принятая offline стадия;
прошедшие tooling, wheel build и compiler использованы по проверенным receipts.
Это не независимая повторная сборка образа и не приёмка приложения.

## Неизменяемые входы

Ветка отчёта создана от `2a296442cadf21f06df83e1ab70d274edcc71861`.
Source исторического build context — `88fdef78bab8c8ced97b29d6d24c2a47c472799a`.
Worker работал с исходниками и свидетельствами чтением; installer, compiler,
backend и контейнеры исполнял только ROOT.

| Объект | SHA-256 / digest |
|---|---|
| Исторический actual-build receipt | `68f0231bed370837a1489b1be85b9e452d45ffce2d7e4d9be7d5f4503bdb1a10` |
| Manifest целевого образа | `sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51` |
| Манифест 65 артефактов | `3390cbfaa680b9bb970ce43e8d3e32014230908c46fd9e7b1d4464c7cf7365ee` |
| `requirements.in`, 530 байт | `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0` |
| Baseline 59 версий без pip | `0ffe95bf719106fc03b76fc8ec2627173e574ee32b974660b7aadc7561e4f6f8` |
| Исправленный stdlib verifier | `b306a05fc1a6222cd53ae2f4c3ed6ddf89752ee8be5adc847cf08a214d3cc091` |
| Driver полного run v2 | `a98940f0624f48305331dc0da97c96ab4f682756e6f3c49d682e3f0c51e2a5f7` |
| Предложение run v2 | `3165e3a06e2143bb1ccace99f165c854c2f7084f07a98d9a6cafcbac59548edb` |
| Driver offline-only v3 | `ebfc64a126f83fd64af57dd7879cdcf702f0023880ab95dbb4e49291f5b55329` |
| Предложение offline-only v3 | `8f07bed3ffb75af8645e612e60ac1f07d202f201052c4ee2d3bc10574367d821` |
| Журнал 130 исходных загрузок | `0a51518675ae0277df465e42ac69b251739a88ea0d5b3975e62acaa48a702b20` |

22 прямых требования, три extras и все 130 upstream файлов сохранены. Для run v2
ROOT подготовил read-only snapshot: 195 файлов, 74 707 443 байта, включая отдельные
копии 58 runtime wheels. Source bug числового сравнения исправлен ранее;
исторический `False` не переименован в отказ выбранного артефакта.

Tooling закреплён отдельно: pip `26.2.2`, pip-tools `7.6.2`, build `1.3.0`,
click `8.5.0`, packaging `26.3`, pyproject-hooks `1.2.0`, setuptools `80.9.0`,
wheel `0.45.1`. В рабочий runtime compiler не добавлялся.

## Фактические результаты ROOT

Внешнее время run включает запуск контейнерного процесса, но не загрузку архива.
Образ ROOT сверил по digest и всем layers; зафиксированная загрузка заняла
25,044761607 с, exit 0, клиент reaped.

| Фаза | Run v2 | Offline-only v3 |
|---|---|---|
| Target-факты и frozen inputs | PASS, 0,927 с | PASS, 0,842 с; также 14 prior files |
| Tooling, восемь pins, metadata и pip check | PASS, 9,175 с | Не повторялись; принят прежний receipt |
| Производный http-ece wheel | PASS, 4,067 с | Не пересобирался; прежние bytes/hash проверены |
| Compiler и hash-complete замыкание 59 pins | PASS, 2,027 с; provisional | Не повторялся; прежний lock проверен |
| Чистая offline стадия | FAIL, 11,905 с; FileNotFoundError | PASS, 19,057 с |
| Полный inventory 59+pip и финальный pip check | NOT RUN после отказа | PASS: ровно 60 distributions, без tooling leakage |
| Собственный scratch cleanup | PASS, 0,085 с | PASS, 0,001 с |
| Внешние контейнер и временный образ | Очистка подтверждена ROOT перед повтором | Очистка подтверждена ROOT; процесс не работает, PID 0 |
| Полный процесс | Exit 1, 29,114987042 с | Exit 0 / container exit 0, 21,096977875 с |

ROOT подтвердил OOM=false, отсутствие watchdog termination и reap клиента.
Контейнер PostgreSQL, существовавший до проверки, сохранён; новая БД не создавалась.

| Свидетельство | SHA-256 |
|---|---|
| Загрузка образа: `load-result.json` | `b49f123b1b12ac418e98ec5a43cd1c4ece72b9e016e9ecf951cf2fb43f4f6a0b` |
| Отказ run v2: `result.json` | `eeb8acd2a0e1780a1264329015af2813f05cf6de8bb243895d2f674806f6cd00` |
| Внешний cleanup после отказа v2 | `59509506c34195d28073d3c6065e420f44dd3bf1490fd860bb6604bc3925d911` |
| Журнал остановленного runtime child v2 | `d6ea58459fd80b3ab075eb07333577cb1f9b4b667d3c37c169256d5c3c05b64c` |
| ROOT acceptance summary v3 | `8fad9f35575e8cc579b4d6ed1d03147b0c81f5dbd31c42fa7c48d4f5184ed4da` |
| Успех v3: `result.json` | `ce247256563019d55c05f3d3bfb4f6f8c5ba821dac32c369671fb140d62a6e90` |
| Runtime inventory v3 | `9ae342037c53c21765f18d6db0e049279ab7c2c1a258787ef552bbcfeabc6983` |
| Журнал успешного runtime pip check | `9261363b733079a641c2e4cc9bc46ffa1d8336945a87f807b6cf68847dbc9b09` |
| Внешний cleanup proof v3 | `7f37b790aaec2e053cb179bd103b8544d5a95887c17d6d0189dc4d5f51cca338` |
| Разрешённые publish candidates: proof | `3b30a30d9393564d3aa96fc2166fcb5f68c3926356a8af0ca8064124b8718814` |

Приватные пути, container IDs, binaries и содержимое операционных журналов здесь
не опубликованы. Свидетельства связывают image/manifest/verifier/driver hashes,
реальные target-факты, phase records, команды, ограниченные log hashes и cleanup.

## Причина отказа и ограниченный повтор

В v2 монитор размера live scratch получил `FileNotFoundError`: ROOT указал сильную
статическую причину — pip удаляет entry между `os.walk` и `lstat`. Точное имя entry
в исходном свидетельстве отсутствует. Finally остановил runtime child, exit −9;
успешный bootstrap pip внутри этой стадии не означал приёмку 59 пакетов.

По отдельному поручению ROOT v3 допускает только ENOENT для названного исчезнувшего
дочернего entry собственного scratch. Ошибки прав, другие errno, inputs, retained
output и root scratch identity остаются строгими. Старые driver/proposal bytes
сохранены. В error receipts добавлены ограниченные type/errno/code-location:
до трёх исключений и восьми frames; без locals, source lines, сообщений и filenames
вне sandbox.

Worker выполнил только семь разрешённых focused pure tests на функциях,
извлечённых из AST, без импорта driver и исполнения фаз. Результат: 7 tests OK;
журнал SHA-256 `39795781bed5bdd80e7d30014fdff3541859ede7ce08afe6f32375f4adac8e16`.
ROOT принял этот результат без повторения тестов и отдельно сверил 14 prior pins.
Прежние 25 pure controls и прочие PASS suites здесь не повторялись.

## Опубликованные provisional файлы

После фактического успеха и cleanup ROOT явно разрешил копирование четырёх
подготовленных им безопасных файлов. Worker скопировал их точные bytes и сверил
контрольные суммы, состав 59/1/8 и неизменность эффективных requirement/hash lines.

| Файл | SHA-256 опубликованных bytes |
|---|---|
| [runtime-py313-linux-amd64.provisional.txt](../../server/locks/runtime-py313-linux-amd64.provisional.txt) | `3b17a7566f0519b7f056697975ed2216e01de5d99972cc882b678be2696cd3d1` |
| [bootstrap-py313-linux-amd64.provisional.txt](../../server/locks/bootstrap-py313-linux-amd64.provisional.txt) | `551e3fb88d8fda035c0d8a2f38c7b08e29b4798d9bad0bfc8d42f5a3c3a8200f` |
| [tooling-py313-linux-amd64.provisional.txt](../../server/locks/tooling-py313-linux-amd64.provisional.txt) | `9e9d2d3d92273c607c2acba679d1d08b3cefa3102583718eade5f665a1c99d80` |
| [derived-http-ece-py313-linux-amd64.provisional.json](../../server/locks/derived-http-ece-py313-linux-amd64.provisional.json) | `84596a3ebfce149db956cc750006eeb55871c80b41d40207cfe29fb0d8961d83` |

Фактически исполнялись raw-файлы с другими полными hashes:

| Назначение | SHA-256 raw executed lock |
|---|---|
| Runtime | `4ab76335c77cb2647e1fc8add8744e2ad65ff4d0203896e6ef0557e31bfcb4ef` |
| Bootstrap | `f409e9c999da22f4920b4724c68adadb416a515f38d760dfd34ae6382d43df04` |
| Tooling | `5909b28d651743c2b3167223be15140bcafd7dda95625700e3775d7755942985` |

Разрешённое преобразование ROOT удаляет только comment-only и blank lines,
затем добавляет стабильные provisional comments. Requirement/hash lines остаются
побайтово прежними. В публикуемых файлах нет execution paths. Эти преобразованные
комментарии не требуют повторного installer run; его здесь не выполняли.
Связь raw → published зафиксирована в provenance и publish proof.

Производный `http_ece-1.2.1-py2.py3-none-any.whl`, 4 849 байт, имеет SHA-256
`a89e8aa1521d121dde75250524981f3f3fa3594cc1117da99904f2ba5ac24f9d`.
Он изготовлен один раз из проверенного sdist SHA-256
`8c6ab23116bbf6affda894acfd5f2ca0fb8facbcbb72121c11c75c33e7ce8cff`.
Binary хранится приватно. Runtime lock требует именно этот wheel и 58 принятых
upstream wheels; получение произвольного одноимённого пакета не заменяет этот вход.

## Исполненный контракт и ограничения вывода

ROOT запускал pinned driver с `-I -S -B`, network-none, read-only root и nonroot;
CPU 2, memory 1 ГиБ, pids 128, собственный tmpfs 256 МиБ, безопасные read-only
inputs и свежий writable output. Фактический target: CPython 3.13.18, ordinary
cp313, GIL, Linux/x86_64, glibc 2.41. Факты машины подготовки не подменяли target.

Команды в приватных receipts привязаны к hashes drivers. Существенные argv ниже;
места файлов обозначены символически, execution paths не публикуются:

```text
python -I -S -B TARGET_DRIVER --mode offline-install-only --image-digest IMAGE_DIGEST --driver-sha256 DRIVER_SHA256
python -I -S -B -m venv FRESH_VENV
VENV_PYTHON -I -B -m pip --isolated install --no-cache-dir --disable-pip-version-check --no-index --retries 0 --require-hashes --only-binary=:all: --find-links APPROVED_WHEELS -r HASHED_LOCK
VENV_PYTHON -I -B -m pip --isolated check
```

В первом полном прогоне compiler использовал `--no-config --resolver=backtracking
--generate-hashes --strip-extras --no-emit-index-url --no-emit-find-links
--no-emit-options --no-index`, baseline и только 58 исходных wheels плюс производный
wheel. Build выполнялся с `--wheel --no-isolation` без сети. В v3 они не повторялись.
Metadata inventory читался stdlib с явным venv site-path и `-S`, без импорта пакетов.

Лимиты фаз: 60/180/120/180/180/60 с, общий deadline 900 с, резерв cleanup 60 с;
в offline-only повторе исполнялись проверки входов, offline install и cleanup.
Журнал ограничен 2 МиБ на файл и фазу, retained output и scratch — по 256 МиБ.
Предусмотрены process group, ограниченный capture, kill и wait/reap. Output допускает
только ожидаемые файлы; backend/compiler временные файлы остаются в собственном
scratch. Pins и версии при отказе не менялись.

Исторический image/import proof не заменяет эту свежую offline-приёмку. Приёмка
metadata/pip check не является функциональной проверкой приложения. Один wheel
build и повторная установка не доказывают побайтовую воспроизводимость образа.

NOT RUN в этой задаче: app/driver imports, lifespan, SQL/БД, функциональные тесты,
независимый rebuild/сравнение образов, SBOM, security audit и выпуск. M16 целиком
не закрыта. Существующие requirements, Dockerfile, Compose, CI, inputs, verifier,
тесты и прежние отчёты не изменены; provisional locks не подключены к runtime.
