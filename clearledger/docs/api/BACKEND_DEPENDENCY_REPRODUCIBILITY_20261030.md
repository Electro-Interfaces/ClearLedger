# M16: воспроизводимость зависимостей backend

Дата: 30.10.2026. Статус: проект реализации; runtime и сборочные файлы не изменены.

Рекомендуется сохранить pip и текущий состав приложения, добавить отдельный lock всех
Python-зависимостей с SHA-256 для CPython 3.13 / linux/amd64, устанавливать их из
сохранённого набора wheels, закрепить базовый образ по digest и APT по snapshot.
Первый переход должен сохранять наблюдавшиеся версии; обновление библиотек оформляется
отдельным изменением. Этот документ завершает анализ зависимостей, но не закрывает M16
и не подтверждает готовность выпуска.

## 1. Основание и границы доказательств

Прочитан существующий receipt фактической сборки и проверки импорта, а также сохранённые
build metadata и исходный контекст. Сборка, загрузка образа и проверка импорта здесь
не повторялись. Публичный отчёт содержит только исходники, версии, количества и хеши;
операционные материалы и пути окружения в него не включены.

| Объект | Проверенное значение |
|---|---|
| SHA-256 исходного `root-actual-summary.json` | `68f0231bed370837a1489b1be85b9e452d45ffce2d7e4d9be7d5f4503bdb1a10` |
| Неизменяемый Git-источник контекста | `88fdef78bab8c8ced97b29d6d24c2a47c472799a` |
| База ветки этого документа | `cadd246ab9828e770abaf1f506376f40b2e11d71` |
| SHA-256 `build-metadata.json` | `19b2c171dddac8167988d4f7841efc2f080e793d9fc3a33d27f40850af1e21e2` |
| SHA-256 `clearledger/server/Dockerfile` | `aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d` |
| SHA-256 `clearledger/server/requirements.txt` | `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0` |
| Результат сборки по receipt | exit 0, 144,035 с, `linux/amd64` |
| Результат проверки импорта по receipt | exit 0, 13,642 с, Python `3.13.18`, 60 distributions |
| Разрешённый digest базового `python:3.13-slim` | `sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb` |

Контрольные суммы summary и metadata проверены чтением файлов. Dockerfile и requirements
побайтово совпадают между сохранённым контекстом, Git-объектами `88fdef78…` и базой
`cadd246a…`. Полное соответствие контекста исходникам отражено в receipt контекста;
здесь независимо сравнены именно два сборочных входа.

`vcs:revision=cadd246a…` внутри buildx metadata описывает Git-окружение запуска с локальным
контекстом. Это не подмена подтверждённого источника `88fdef78…`. Docker прямо указывает,
что дополнительные `vcs` значения для локального контекста не проверяются BuildKit;
их следует считать подсказкой, а идентичность исходников подтверждать манифестом
контекста. [Docker: VCS metadata](https://docs.docker.com/build/metadata/attestations/slsa-definitions/#vcs)

Одна удачная сборка и импорт подтверждают упаковку данного состава на тот момент.
Они не доказывают повторную сборку с теми же зависимостями или побайтовое равенство
образов. В receipt lifespan не запускался, SQL не выполнялся. SBOM и опубликованная
provenance attestation были отключены параметрами сборки; локальные build metadata
не заменяют подписанное свидетельство. Этот анализ не является аудитом безопасности
или проверкой работоспособности всех функций приложения.

## 2. Точный состав входных требований

Область: только `clearledger/server/requirements.txt`, который копирует фактический
Dockerfile. Одно непустое требование считается одной прямой зависимостью; extras
не считаются отдельными distributions. Имена сопоставлены без учёта регистра,
с нормализацией `-`, `_`, `.`. Выполнен разбор текста; код приложения не импортировался.

| Категория требований | Количество |
|---|---:|
| Прямые уникальные distributions | 22 |
| С точным `==` | 18 |
| С нижней границей `>=` | 4 |
| Строки с extras | 3 |
| Строки с хешами артефактов | 0 |
| Прямые URL/VCS, includes, constraints, markers в этом файле | 0 |

| Строка | Требование исходника | Версия в фактическом receipt |
|---:|---|---|
| 1 | `fastapi==0.115.6` | `0.115.6` |
| 2 | `uvicorn[standard]==0.34.0` | `0.34.0` |
| 3 | `sqlalchemy[asyncio]==2.0.36` | `2.0.36` |
| 4 | `asyncpg==0.30.0` | `0.30.0` |
| 5 | `pyjwt==2.10.1` | `2.10.1` |
| 6 | `Authlib==1.9.1` | `1.9.1` |
| 7 | `joserfc==1.7.7` | `1.7.7` |
| 8 | `bcrypt==4.2.1` | `4.2.1` |
| 9 | `passlib[bcrypt]==1.7.4` | `1.7.4` |
| 10 | `python-dotenv==1.0.1` | `1.0.1` |
| 11 | `openpyxl==3.1.5` | `3.1.5` |
| 12 | `python-multipart==0.0.18` | `0.0.18` |
| 13 | `pydantic-settings==2.7.1` | `2.7.1` |
| 14 | `email-validator>=2.0.0` | `2.3.0` |
| 15 | `aiofiles==24.1.0` | `24.1.0` |
| 16 | `httpx==0.28.1` | `0.28.1` |
| 17 | `cryptography>=44.0.0` | `50.0.2` |
| 18 | `gunicorn==23.0.0` | `23.0.0` |
| 19 | `aiosmtplib>=3.0.0` | `5.1.3` |
| 20 | `pywebpush>=2.0.0` | `2.5.0` |
| 22 | `pypdf==5.1.0` | `5.1.0` |
| 23 | `python-docx==1.1.2` | `1.1.2` |

Функциональная группировка ниже нужна для назначения проверок. Категории не пересекаются
и охватывают ровно 22 требования; это классификация исходника, а не граф импортов.

| Группа | Пакеты | `==` / `>=` |
|---|---|---:|
| API, настройки, валидация | fastapi, pydantic-settings, email-validator, python-multipart | 3 / 1 |
| ASGI и процесс сервера | uvicorn, gunicorn | 2 / 0 |
| PostgreSQL и ORM | sqlalchemy, asyncpg | 2 / 0 |
| Идентичность и криптография | pyjwt, Authlib, joserfc, bcrypt, passlib, cryptography | 5 / 1 |
| HTTP, файлы, dotenv | httpx, aiofiles, python-dotenv | 3 / 0 |
| Почта и push | aiosmtplib, pywebpush | 0 / 2 |
| Документы | openpyxl, pypdf, python-docx | 3 / 0 |

Из 60 наблюдавшихся distributions 22 совпадают с прямыми требованиями, одна относится
к установщику (`pip==26.2.2`), оставшиеся 37 явно в requirements не перечислены.
Их необходимо охватить будущим lock как кандидатов транзитивного состава. Сам список
версий не доказывает конкретные рёбра зависимостей, extras или происхождение файлов.

Полный остаток из 37 distributions, с нормализованными именами:

```text
aiohappyeyeballs==2.7.1     aiohttp==3.14.5          aiosignal==1.4.0
annotated-types==0.8.0     anyio==4.15.1            attrs==26.1.0
certifi==2026.10.23        cffi==2.1.1              charset-normalizer==3.5.2
click==8.5.0              dnspython==2.9.1         et-xmlfile==2.0.0
frozenlist==1.8.0          greenlet==3.5.6          h11==0.16.0
http-ece==1.2.1           httpcore==1.0.9          httptools==0.9.0
idna==3.20                lxml==6.1.3              multidict==7.2.1
packaging==26.3           propcache==0.5.4         py-vapid==1.9.6
pycparser==3.12           pydantic==2.14.2         pydantic-core==2.50.2
pyyaml==6.0.3             requests==2.34.2         starlette==0.41.3
typing-extensions==4.16.0  typing-inspection==0.4.4 urllib3==2.8.0
uvloop==0.23.0            watchfiles==1.3.0        websockets==17.3
yarl==1.25.1
```

Это инвентаризация наблюдения, **не готовый lockfile**: нет выбранных wheel-файлов,
их хешей, полного графа и правил платформы. Даже JSON `pip install --report` по
определению pip не является lockfile. [pip: Installation Report](https://pip.pypa.io/en/stable/reference/installation-report/)

`requirements-test.txt` отдельно включает runtime requirements и пять тестовых
требований с `>=`. Он не участвует в фактическом Dockerfile. Тестовый lock следует
создать отдельно с ограничением runtime-версий, не добавляя pytest, Alembic и прочие
инструменты в рабочий образ. Другие requirements монорепозитория не объединять.

## 3. Где возникает дрейф

| Вход | Сейчас | Последствие | Предлагаемая фиксация |
|---|---|---|---|
| Python / ОС базы | `FROM python:3.13-slim` | Меняются patch Python, Debian и библиотеки базы | Проверенный digest + platform + явная линия Python/Debian в паспорте |
| Системные пакеты | APT update; `build-essential curl ffmpeg` без версий | Меняются прямые и транзитивные `.deb`, возможны обновления пакетов базы | Snapshot всех используемых архивов, точные версии, полный OS manifest |
| Установщик | `pip install --upgrade pip` | Новый resolver и поведение сборки без изменения Git | Отдельный bootstrap lock с версией и хешем pip |
| Четыре прямых `>=` | Открытый диапазон сверху | Новый релиз выбирается при следующей сборке | Наблюдавшиеся версии в первом полном lock |
| Транзитивный состав | Не перечислен | Дрейф возможен и при неизменных 18 прямых `==` | Полное замыкание графа с `==` и хешами |
| Исходные дистрибутивы | Разрешены pip по умолчанию | Временные build deps и компиляторы добавляют входы | Контролируемая подготовка wheels; рабочая установка только wheels |
| Источник контекста | Локальный snapshot и дополнительный VCS hint | Хостовый commit может отличаться от источника файлов | Git commit + SHA-256 манифеста файлов контекста |

В материалах фактической сборки обнаружен `http_ece-1.2.1.tar.gz` и изготовление
`http_ece-1.2.1-py2.py3-none-any.whl`. Это конкретный риск при включении
`--only-binary=:all:`: существование нужного upstream wheel сейчас не проверялось.
Хеш изготовленного ранее wheel не доказывает хеш исходного архива и повторяемость
его изготовления. Временные build dependencies не входят автоматически в список
60 установленных distributions. Pip описывает их отдельную изолированную среду.
[pip: Build System Interface](https://pip.pypa.io/en/stable/reference/build-system/#build-isolation)

В прочитанном материале APT использовал `trixie`, `trixie-updates`, `trixie-security`.
Полный OS inventory и точные snapshots исходной сборки в рассмотренном receipt
не установлены. Три имени из Dockerfile нельзя выдать за весь набор пакетов ОС.
Отдельный `clearledger/deploy/backend.Dockerfile` отличается составом: в нём нет
ffmpeg и копирования schema migrations. Для будущей реализации канон здесь —
`clearledger/server/Dockerfile`; другой файл нельзя незаметно выбрать вместо него.

## 4. Минимальные варианты и выбранный подход

| Вариант | Польза | Ограничение | Решение |
|---|---|---|---|
| Только заменить четыре `>=` на `==` | Малый diff | Не закрывает транзитивные пакеты, файлы, pip, APT и базу | Недостаточно |
| Полный requirements lock с SHA-256, pip, сохранённые wheels | Совместим с текущей установкой; небольшой переход | Нужно отдельно подготовить source-only пакет и зафиксировать ОС | **По умолчанию** |
| `pylock.toml` через `pip lock` | Стандартный формат окружения | `pip lock` и поддержка pylock в pip отмечены experimental; отдельная миграция и проверка потребителей | Отложить до отдельного решения |

Стандарт PyPA определяет `pylock.toml` для воспроизводимой установки, но наличие
стандарта не доказывает поддержку выбранным инструментарием. Документация pip
ограничивает гарантию `pip lock` текущими Python и платформой.
[PyPA: pylock](https://packaging.python.org/en/latest/specifications/pylock-toml/),
[pip: lock](https://pip.pypa.io/en/stable/cli/pip_lock/)

Предлагается `pip-compile` с зафиксированной версией инструментария, генерацией хешей
и отдельным выходом для целевой среды. Ни один инструмент сейчас не устанавливался.
Комбинацию версий compiler/pip необходимо проверить перед принятием; текущие версии
страниц документации не доказывают их совместимость. Генерация выполняется в целевой
среде: зависимости могут различаться между Python, ОС и реализациями.
[pip-tools: cross-environment usage](https://pip-tools.pypa.io/en/stable/#cross-environment-usage-of-requirements-in-requirements-txt-and-pip-compile)

## 5. План реализации по этапам

Все перечисленные ниже файлы и команды — предложение для следующей задачи.
Они не созданы и не выполнялись в этой работе.

### Этап A. Зафиксировать договор о составе

Владелец: сопровождающий backend dependencies. В `clearledger/server/` предложены:

- `requirements.in`: текущие 22 прямых требования с сохранением трёх extras и комментария.
- `locks/runtime-baseline.constraints.txt`: 59 наблюдавшихся версий без pip, только seed
  первого разрешения. Constraints ограничивают версии, но сами не требуют установки
  всех перечисленных пакетов; не использовать их вместо полного lock.
- `locks/runtime-py313-linux-amd64.txt`: окончательное замыкание зависимостей с точными
  версиями и SHA-256 выбранных wheels.
- `locks/bootstrap-py313-linux-amd64.txt`: отдельно pip, первоначальный кандидат
  `26.2.2`, с проверенным SHA-256 wheel; compiler и его зависимости — в отдельном
  tooling lock, не в runtime.
- `locks/environment.json`: схема паспорта среды, входные хеши, версии tooling,
  источники артефактов, base digests, OS snapshot и политики проверки.

Seed формируется из receipt, затем проверяется resolver и metadata wheels. Сохранить
все 22 direct и extras; убедиться, что все 18 точных версий совпали. Для четырёх `>=`
первый lock выбирает `2.3.0`, `50.0.2`, `5.1.3`, `2.5.0` соответственно. Если resolver
не подтверждает состав из 59 пакетов, остановить переход и объяснить отличие;
не подбирать новые версии молча. Seed — историческое наблюдение, не доказательство
безопасности или корректности разрешения.

Цель первой приёмки: 59 runtime distributions плюс отдельно учтённый pip, без утечки
compiler/build tooling. Подтверждённое отличие возможно только с отдельным разбором
причины и совместимости. Не делать число 59 бессрочной нормой при будущих обновлениях.

### Этап B. Подготовить точные Python-артефакты

Владелец: инженер сборки совместно с сопровождающим dependencies.

1. Использовать CPython `3.13.18`, обычный `cp313`, `linux/amd64`, glibc/Debian той же
   подтверждённой линии. Генерация на произвольном host Python не подходит.
   Изоляция venv не заменяет фиксацию версии интерпретатора; venv следует пересоздавать,
   а не переносить между машинами. [Python: venv](https://docs.python.org/3.13/library/venv.html)
2. Отобрать конкретные wheels всех 59 версий и отдельно bootstrap/tooling. Для каждого
   записать имя distribution, version, filename, SHA-256, исходный публичный источник,
   теги Python/ABI/platform и разрешённые markers. `cp313`, совместимые `abi3` и
   `py3-none-any` проверять по правилам тегов; не заменять Debian на Alpine или
   `linux/arm64`. [PyPA: platform tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)
3. Для `http-ece==1.2.1` сначала проверить наличие подходящего wheel. Если его нет,
   получить и проверить точный SHA-256 sdist в отдельной подготовительной задаче,
   зафиксировать полный build toolchain и build dependencies с хешами. Изготовить
   wheel без свободного сетевого разрешения build deps, сохранить его неизменяемым
   артефактом и внести его SHA-256 в runtime lock. Хеш sdist хранить отдельно.
   Не объявлять `--no-build-isolation` достаточной фиксацией: все build deps должны
   быть заранее установлены из отдельного hashed lock в чистую build-среду.
4. Сохранить выбранные wheels и их манифест в хранилище артефактов с адресацией по
   хешу и сроком хранения не короче поддерживаемых откатов. В Git хранить текстовые
   locks и безопасный паспорт; бинарные пакеты не добавлять в репозиторий приложения.
5. Из полного подготовленного wheelhouse создать runtime lock. Важна фиксация
   конкретных файлов для целевой платформы, а не всех хешей всех платформ PyPI.
   Пакеты, отсутствующие в wheelhouse, должны приводить к ошибке.

Шаблон генерации в подготовленной целевой среде, из `clearledger/server/`:

```sh
python -m piptools compile --no-config --resolver=backtracking \
  --generate-hashes --strip-extras --no-emit-index-url --no-emit-find-links \
  --no-index --find-links wheelhouse \
  --constraint locks/runtime-baseline.constraints.txt \
  --output-file locks/runtime-py313-linux-amd64.txt requirements.in
```

В `requirements.in` extras сохраняются. `--strip-extras` снимает их с выходных
строк после разрешения; необходимые зависимости extras должны остаться в полном
lock. Wheelhouse в шаблоне — заранее подготовленный вход, не команда его получения.
Параметры compiler следует проверить для принятой версии инструмента.
[pip-tools: pip-compile options](https://pip-tools.pypa.io/en/stable/reference/pip-compile/)

Будущая установка из сохранённых wheels после отдельной фиксации bootstrap pip:

```sh
python -m pip install --no-index --find-links wheelhouse \
  --require-hashes --only-binary=:all: \
  -r locks/runtime-py313-linux-amd64.txt
python -m pip check
```

Здесь dependency checking оставлено включённым: неполное замыкание должно завершиться
ошибкой. `--require-hashes` требует точных pins и хешей у всех зависимостей; частичный
lock недопустим. Не разрешать обход через `--no-require-hashes` и не откатываться
автоматически к текущим requirements. [pip: secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/#hash-checking-mode)

Wheelhouse обеспечивает доступность выбранных файлов; одни хеши не обеспечивают их
сохранность в upstream. Offline установка wheels описана pip, но portability зависит
от ОС и архитектуры. [pip: repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/#using-a-wheelhouse-aka-installation-bundles)

### Этап C. Закрепить базовый образ и ОС

Владелец: сопровождающий backend image.

Наблюдавшийся `sha256:2d44738e…` считать зафиксированным материалом сборки, но не
называть без проверки digest именно дочерним amd64 manifest. В имеющемся metadata
нет достаточной цепочки descriptor, чтобы отличить index от platform manifest.
В следующей задаче получить и сохранить эту цепочку: исходный tag → index digest,
если он есть → дочерний `linux/amd64` manifest digest → config digest. Для single-platform
manifest отметить отсутствие index. Не смешивать digest базы с digest результата.
Docker описывает разницу между manifest list и platform manifest.
[Docker: multi-platform structure](https://docs.docker.com/build/building/multi-platform/#difference-between-single-platform-and-multi-platform-images)

В Dockerfile закрепить проверенный platform manifest базы и сохранять
`--platform=linux/amd64` в сборочном контракте. В паспорте указать readable Python patch
и Debian codename вместе с digest; существование нового удобного tag не предполагать.
Фиксация по digest требует отдельного процесса обновления безопасности, поскольку
движение тега больше не обновляет базу автоматически.
[Docker: pin base image versions](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions)

Для APT выбрать следующий минимальный договор:

- Точные timestamps snapshot для архивов `debian` и `debian-security`, suites
  `trixie`, `trixie-updates`, `trixie-security`, component и architecture `amd64`.
  Конкретные timestamps сейчас неизвестны; не подставлять дату отчёта как доказанный
  snapshot первоначальной сборки.
- Удалить смешивание фиксированных snapshots и плавающих live sources в сборке.
  Явно закрепить версии `build-essential`, `curl`, `ffmpeg`, включая epoch/revision;
  сохранить `--no-install-recommends`. Из того же snapshot разрешить их транзитивные
  зависимости и сверить полный результат `name/version/architecture`, включая
  обновлённые пакеты базы, с принятым OS manifest.
- Сохранить сведения о `InRelease`/`Release`, их хеши, используемый Debian keyring,
  SHA-256 индексов и `.deb` для добавленных/обновлённых пакетов. Версии без доступного
  snapshot не гарантируют возможность повторного получения пакетов.
- Для исторического snapshot при необходимости отключить только `Check-Valid-Until`
  конкретного source. Сохранить проверку подписей через `Signed-By`; не применять
  `trusted=yes` или `AllowUnauthenticated`. Это отдельные проверки.

Snapshot Debian допускает обращение к состоянию архива по времени; если точного
импорта нет, выбирается предшествующий. Сохранить фактически выбранный timestamp.
[Debian: snapshot usage](https://snapshot.debian.org/#usage),
[Debian: source options](https://manpages.debian.org/trixie/apt/sources.list.5.en.html#THE_DEB_AND_DEB-SRC_TYPES:_OPTIONS)

Принятие нового snapshot с отличающимся составом ОС — самостоятельное обновление,
даже если Python-пакеты остались прежними. Не выдавать его за точное восстановление
исторической сборки. В первом изменении не удалять ffmpeg, curl, компиляторы и не
переносить слои в multi-stage: это отдельная оптимизация с проверкой поведения.

### Этап D. Проверять происхождение и дрейф

Владелец: сопровождающий сборочного процесса. Предлагаемый паспорт должен содержать:

| Группа | Обязательные поля и сравнение |
|---|---|
| Исходники | Git source commit; путь Dockerfile внутри репозитория; SHA-256 отсортированного контекстного манифеста; хеши Dockerfile, input, locks и vendored assets |
| Среда | CPython patch/ABI, target OS/architecture, Debian codename, locale/timezone политики, версии и digests BuildKit/frontend, exporter/compression параметры |
| База и ОС | Раздельные index/platform/config digests; snapshots; хеши APT metadata; полный OS manifest |
| Python | Версии installer/compiler, хеш tooling lock; полный runtime lock и wheel manifest; фактически установленные name/version и выбранные filenames/hashes |
| Результат | Manifest digest, config digest, layer digests и отдельно checksum транспортного архива; статус import/lifespan/SQL явно раздельно |

Перед сборкой проверять соответствие контекста заявленному source. Хостовый commit
сохранять отдельным полем при необходимости: его отличие от snapshot не ошибка само
по себе, но нельзя подставлять его в authoritative source revision. После сборки
сравнивать базу, wheels, Python/OS inventory и контракт запуска с принятым паспортом.
Новый package, неизвестный хеш, другой platform, live APT source, незаявленный build
backend или расхождение исходного манифеста должны останавливать принятие результата.
Поля build metadata могут зависеть от версии BuildKit; parser должен проверять
схему и завершаться ошибкой при неизвестном обязательном формате.

В публичный паспорт включать только белый список полей. Сырые логи, пути окружения,
идентификаторы инфраструктуры, credentials и URL с авторизацией туда не копировать.
Статусы `NOT RUN`, `PASS`, `FAIL` хранить отдельно от желаемой политики.

### Этап E. Разделить уровни воспроизводимости

| Уровень | Что доказывает приёмка | Текущее состояние |
|---|---|---|
| Сборка одного исходного snapshot | Данный контекст собрался и прошёл ограниченный импорт | PASS по существующему receipt |
| Повторяемая установка зависимостей | Две чистые установки из принятых locks дают одинаковые выбранные файлы, Python и OS inventory | NOT RUN |
| Побайтовая воспроизводимость образа | Две независимые сборки дают одинаковые platform manifest/config/layers при одинаковом exporter contract | NOT RUN |
| Сквозная работоспособность / выпуск | Отдельная приёмка функций и окружения | Не предмет этого анализа |

Во втором уровне нужны два изолированных прогона без использования предыдущего
runtime environment и без зависимости от скрытого pip/APT cache. Сравнивать полные
множества, а не только количество пакетов. Проверка lock также должна отрицательно
проверять изменённый wheel, отсутствующую транзитивную зависимость, неверный platform
и несоответствие хеша контекста. Проверки выполняются только в будущей выделенной
среде; здесь ни один такой прогон не запускался.

Для третьего уровня дополнительно нормализовать timestamps, порядок файлов,
компиляцию/генерацию metadata, параметры сжатия и exporter, toolchain, UID/GID, locale
и источники недетерминированных данных. Одинаковый source commit или список версий
не гарантирует одинаковые байты. `SOURCE_DATE_EPOCH` помогает фиксировать timestamps,
но не заменяет сравнение двух результатов.
[Docker: reproducible build timestamps](https://docs.docker.com/build/ci/github-actions/reproducible-builds/)

Не сравнивать checksum tar-архива с OCI manifest digest как один тип идентичности.
Attestations и transport metadata учитывать отдельно. Настройка provenance
`reproducible=true` сама по себе не является результатом независимого сравнения.

### Этап F. Обновления, проверка совместимости и откат

Владелец dependencies готовит отдельный PR обновления. Предлагаемый ритм: еженедельная
проверка доступных обновлений Python/базы, APT, tooling и runtime; сведения о критических
проблемах разбирать в ближайший рабочий день, фиксируя решение и владельца исправления.
Это предложение процесса, а не утверждение о существующем SLA.

PR должен показывать старые/новые версии и хеши, причину изменения, источники security
advisories, результат разрешения, изменение графа и совместимости. Хеш подтверждает
идентичность файла, но не отсутствие уязвимостей. Проверку безопасности зависимостей,
если она требуется для выпуска, выполнять отдельно с датой и источниками базы знаний;
в этой работе её результата нет. Не объединять фиксацию текущего состава и массовый
upgrade. Перегенерация lock в обычной сборке запрещается договором: обновления делает
владелец в отдельном изменении, затем review и проверки.

| Область риска | Требуемая будущая проверка |
|---|---|
| Python 3.13 / нативные wheels | Теги ABI, glibc, наличие совместимых wheels для asyncpg, bcrypt, cryptography, uvloop и других extensions; при смене patch повторить разрешение |
| FastAPI / Pydantic / Starlette | Сериализация, валидация, OpenAPI и обработка ошибок; нынешний импорт не покрывает эти сценарии |
| Uvicorn standard / SQLAlchemy asyncio / passlib bcrypt extras | Сохранение активируемых зависимостей и проверка их согласованности |
| Authlib / joserfc / PyJWT / cryptography | Синтетические OAuth/JWT/JWK сценарии, алгоритмы и ошибки; проверка подписи и паролей на вымышленных данных |
| Почта / push | Совместимость API aiosmtplib и pywebpush на заглушках, без внешней отправки |
| Документы / ffmpeg / ОС | Синтетические PDF/DOCX/XLSX и видео-вложения, библиотеки системы, сертификаты и TLS; никакого реального контента |
| Запуск | Сохранение gunicorn command, workers, timeout, расположения app и schema migrations |

Откат dependencies должен возвращать единый набор: исходный commit, base digest,
APT snapshots/manifest, runtime/bootstrap/tooling locks и сохранённые wheels.
Откат уже принятого образа использует его точный digest, а не повторную сборку
старого Git через плавающие индексы. Предыдущие артефакты не удалять до окончания
срока поддержки отката. Несоответствие проверок оставляет текущий принятый состав
действующим; молчаливый fallback к незакреплённым зависимостям запрещён.
Операции выпуска и отката среды в эту задачу не входят.

## 6. Следующие задачи и критерии приёмки

Названия ниже — задания для планирования, не созданные записи трекера.

| Задача | Владелец и область | Наблюдаемая приёмка |
|---|---|---|
| DEP-1: Python lock и wheels | Сопровождающий dependencies; только input/locks/tooling и подготовка артефактов | Проверены 22 direct/3 extras; resolver объясняет замыкание; все выбранные wheels и bootstrap имеют точные SHA-256; обработан http-ece; нет неявных sdist/build deps; чистая установка и `pip check` успешны |
| DEP-2: Base и APT contract | Сопровождающий backend image; Dockerfile и паспорт ОС, после согласования состава с DEP-1 | Проверена цепочка digests для amd64; snapshots и версии заданы; полный OS manifest и provenance пакетов сохранены; pip upgrade больше не плавает; app/CMD/schema assets сохранены |
| DEP-3: Drift gate и повторная сборка | Владелец сборочных проверок; новый verifier и его изолированные проверки | Проверки расхождений дают отказ; две чистые установки совпадают по полному составу; ограниченный import проверен отдельно; результат не назван exact rebuild без проверки manifest/config/layers |
| DEP-4: Update/rollback rehearsal | Владелец dependencies и сопровождающий образа | Один синтетический upgrade проходит review и проверки, прежние locks/wheels/base доступны; откат воспроизводит принятый dependency contract; реальные среды не затрагиваются |

Порядок: DEP-1 и выбор base/OS договора DEP-2 согласовать до переключения Dockerfile;
затем DEP-3; DEP-4 использует принятый комплект. Задачи следует передать исполнителям
с соответствующими областями записи и правом на сборочные действия. Текущая задача
ограничена анализом; документ не запускает реализацию или выпуск.

## 7. Что проверено и что не запускалось

Выполнено чтением: инструкции репозитория, чистота исходного checkout, создание новой
ветки от точного `cadd246a…`, SHA-256 разрешённого summary и metadata, побайтовое
соответствие Dockerfile/requirements исходнику и контексту, полный подсчёт требований,
сопоставление всех 22 прямых пакетов с 60 distributions receipt, чтение официальной
документации Docker/Python/PyPA/pip/pip-tools/Debian. Все утверждения о прежней сборке
относятся к существующему receipt, а не к новому выполнению.

| Проверка / действие | Результат в этой работе |
|---|---|
| Установка пакетов, resolver, генерация настоящего lock | NOT RUN |
| Получение wheel/sdist/base manifest или проверка новых artifact hashes | NOT RUN |
| Сборка, pull/load/run образов, app/driver import, probe | NOT RUN |
| Повторная чистая сборка и сравнение OCI digests | NOT RUN |
| pip check, тесты приложения, старые PASS-наборы | NOT RUN |
| SBOM, dependency/security audit | NOT RUN |
| SQL, БД, ключи, реальные API/среды, VM, CI, deploy | NOT RUN |

Единственный результат записи — этот новый документ. Runtime, requirements,
Dockerfile, Compose, CI и общие статусные документы не изменены.
