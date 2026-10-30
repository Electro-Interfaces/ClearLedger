# DEP-1: подготовленные артефакты зависимостей backend

Дата: 30.10.2026. Статус: подготовка входов и проверка скачанных файлов.
Рабочая сборка не переключена; готового runtime lock нет.

Созданы точный input прямых зависимостей, baseline 59 наблюдавшихся версий,
манифест 65 артефактов и stdlib-инструмент их проверки. Файлы получены только
с официальных PyPI-хостов и сверены с объявленными размером и SHA-256.
Один пакет, `http-ece==1.2.1`, опубликован только как sdist; он сохранён,
но его backend не запускался. Следующий шаг ROOT — отдельная чистая целевая
среда, изготовление этого wheel, разрешение графа и проверка offline установки.

Это продолжение [принятого плана воспроизводимости](BACKEND_DEPENDENCY_REPRODUCIBILITY_20261030.md).
Ни список установленных версий, ни подготовленный манифест не являются полным lock.

## 1. Неизменяемые исходные входы

База ветки подготовки: `8d6740ad9f4d6ca6df112158308404e3f3a644cd`.
Исторический source фактического build context: `88fdef78bab8c8ced97b29d6d24c2a47c472799a`.
Receipt, из которого взяты версии, имеет SHA-256
`68f0231bed370837a1489b1be85b9e452d45ffce2d7e4d9be7d5f4503bdb1a10`.
Он описывает Python `3.13.18`, `linux/amd64`, 60 установленных distributions,
включая `pip==26.2.2`. Запись buildx о Git-окружении запуска не используется
вместо source контекста.

| Новый файл | Состав и роль | SHA-256 |
|---|---|---|
| [requirements.in](../../server/requirements.in) | Побайтовая копия исходных 530 байт: 22 direct, три extras, исходный комментарий | `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0` |
| [runtime-baseline.constraints.txt](../../server/locks/runtime-baseline.constraints.txt) | 59 уникальных точных версий из receipt без pip; seed, а не lock | `0ffe95bf719106fc03b76fc8ec2627173e574ee32b974660b7aadc7561e4f6f8` |
| [dependency-artifacts-py313-linux-amd64.json](../../server/locks/dependency-artifacts-py313-linux-amd64.json) | Версии, официальные URL, размеры, хеши, теги, прочитанные declarations и блокеры; 116 509 байт | `3390cbfaa680b9bb970ce43e8d3e32014230908c46fd9e7b1d4464c7cf7365ee` |

18 прямых требований остаются с `==`, четыре с `>=`. В `.in` они не менялись;
baseline ограничивает их наблюдавшимися версиями. Все 59 baseline pins сверяются
с полным множеством receipt; дубликаты нормализованных имён запрещены.
Constraints сами по себе не требуют установки всех перечисленных пакетов.

## 2. Что получено и что означает выбор платформы

| Группа | Количество |
|---|---:|
| Позиции исторического приложения без pip | 59 |
| Их готовые upstream wheels | 58 |
| Их source-only архивы | 1 |
| Bootstrap pip | 1 wheel |
| Дополнительные позиции tooling вне исторического состава | 5 wheels |
| Всего артефактов | 65: 64 wheels и 1 sdist |
| Wheels с универсальными тегами | 45 |
| Wheels с manylinux x86_64 тегами | 19 |

`click` и `packaging` используются и приложением, и предлагаемым tooling;
они не посчитаны повторно. Сохранены 65 version JSON и 65 соответствующих
дистрибутивов: 130 запросов в журнале подготовки. Полный манифест содержит
каждый выбранный filename и его SHA-256; бинарные файлы в Git не включены.

Политика выбора объявляет обычный CPython `cp313`, Linux amd64 и требования
manylinux к glibc не выше `2.41` для линии Debian trixie. Допускаются точные `cp313-cp313`, подходящие
CPython `abi3` и универсальные Python 3 wheels. Отклоняются `cp313t`, другая
архитектура, musllinux, неоднозначный `linux_x86_64` и manylinux с более новым
требованием к glibc. Сжатые теги filename развернуты и сверены с тегами WHEEL.
Например, выбран `cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl`.

Это проверка деклараций по заданной политике, **не сертификат целевой среды**.
Здесь не запускались Python 3.13.18 из образа, нативные расширения или resolver;
наличие совместимого тега не доказывает фактическую загрузку библиотеки.
Правила Python/ABI/platform тегов описаны в [спецификации PyPA](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/).

## 3. Точные кандидаты bootstrap/tooling

Все версии ниже заданы явно. Pip взят из receipt; compiler выбран из принятого
подхода pip-compile и явно закреплён по version JSON; click/packaging сохранены
из наблюдавшегося состава. Остальные четыре
версии — явные кандидаты по их официальным version JSON, не запрос `latest`.
Их declarations допускают выбранный Python и указанные зависимости в поддержанном
numeric/marker subset. Исполнение compiler с этим pip ещё не проверено.

| Пакет / первичный источник | Версия | SHA-256 скачанного wheel |
|---|---|---|
| [pip](https://pypi.org/pypi/pip/26.2.2/json) | `26.2.2` | `fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70` |
| [pip-tools](https://pypi.org/pypi/pip-tools/7.6.2/json) | `7.6.2` | `f37eb4b736859c2c30230e50977312c61918b7ef931071ff7811fd067715c25f` |
| [build](https://pypi.org/pypi/build/1.3.0/json) | `1.3.0` | `7145f0b5061ba90a1500d60bd1b13ca0a8a4cebdd0cc16ed8adf1c0e739f43b4` |
| [click](https://pypi.org/pypi/click/8.5.0/json) | `8.5.0` | `255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360` |
| [packaging](https://pypi.org/pypi/packaging/26.3/json) | `26.3` | `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` |
| [pyproject-hooks](https://pypi.org/pypi/pyproject-hooks/1.2.0/json) | `1.2.0` | `9e5c6bfa8dcc30091c74b0cf803c81fdd29d94f01992a7707bc97babb1141913` |
| [setuptools](https://pypi.org/pypi/setuptools/80.9.0/json) | `80.9.0` | `062d34222ad13e0cc312a4c02d73f059e86a4acbfbdea8f8f76b28c99f306922` |
| [wheel](https://pypi.org/pypi/wheel/0.45.1/json) | `0.45.1` | `708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248` |

Прочитанные активные зависимости без optional extras: pip-tools требует
`build>=1.0.0`, `click>=8`, `pip>=22.2`, `pyproject_hooks`, `setuptools`, `wheel`;
build требует `packaging>=19.1`, `pyproject_hooks`. В этом контексте не активируются
его Windows colorama и зависимости старых Python. Манифест сохраняет исходные
Requires-Dist и восемь активных рёбер tooling-предложения.

Это ограниченная статическая сверка declarations. Полный PEP 440/508 resolver
не реализован; неизвестная семантика при необходимой проверке отклоняется.
Даже согласованные declarations не исключают несовместимость pip-tools с внутренними
API pip. ROOT должен проверить установленный tooling и реальный запуск compiler
в отдельной чистой среде; приложение для этого не используется.

## 4. Source-only пакет и точный build-план

[Официальный version JSON http-ece 1.2.1](https://pypi.org/pypi/http-ece/1.2.1/json)
объявляет единственный `http_ece-1.2.1.tar.gz`, 8 830 байт, SHA-256
`8c6ab23116bbf6affda894acfd5f2ca0fb8facbcbb72121c11c75c33e7ce8cff`.
В этой выборке upstream wheel отсутствует. Скачанный архив соответствует JSON.

Прочитаны PKG-INFO, setup.py и setup.cfg. `pyproject.toml` отсутствует;
из AST вызова setup извлечён литеральный `install_requires=['cryptography>=2.5']`.
Динамические hooks не вызывались. Для будущего запуска предложен стандартный
legacy backend `setuptools.build_meta:__legacy__` с implicit
`setuptools>=40.8.0`, закреплённым кандидатом `80.9.0` и wheel `0.45.1`.
Это build-план, а не доказательство достаточности toolchain.

ROOT должен изготовить wheel в чистой среде без сети, вычислить его фактический
SHA-256 и сохранить отдельное свидетельство связи sdist → toolchain → wheel.
Хеш старого wheel из исторического журнала не подставлялся. Исходный манифест
подготовки остаётся неизменяемым; новый wheel и будущий lock получают отдельные
артефакты и приёмку. `--require-wheels` у проверяющего инструмента сейчас намеренно
отказывает; наличие рядом самостоятельно построенного файла не снимает блокер
автоматически.

## 5. Проверяющий инструмент и ограничения

[prepare_dependency_artifacts.py](../../server/tools/prepare_dependency_artifacts.py)
работает на Python 3.11+ и использует только stdlib. Он не импортирует приложение,
драйверы, скачанные пакеты или build backend.

- `fetch` создаёт новый приватный каталог подготовки, получает только version JSON
  с `pypi.org` и объявленные файлы с `files.pythonhosted.org`. HTTPS проверяется
  стандартным TLS context; credentials, query, fragment, нестандартный port и
  redirect на другой host отклоняются. Нет fallback hosts или правок proxy/CA.
- `verify` выполняет только чтение и не делает сетевых запросов. Он сверяет
  frozen receipt/input/baseline, уникальные pins/roles, официальное объявление
  файла, локальные размер/SHA-256, содержимое metadata и полный журнал загрузки.
- Wheel проверяется по имени/version, единственному dist-info, Name/Version,
  Requires-Python, декларациям Requires-Dist и равенству filename/WHEEL tags.
  Для sdist читаются только ограниченные metadata и AST; ничего не извлекается
  на диск и не исполняется.
- Небезопасные пути, symlinks/hardlinks к файлам набора, архивные links/special
  members, дубликаты, неверные хеши/размеры, неподдержанные markers, неизвестный
  обязательный формат и неразрешённый source fallback приводят к отказу.
- Ограниченный marker parser поддерживает известные имена PEP 508, сравнения,
  группировки, `and/or`, `in/not in`. Для runtime он проверяет синтаксис и сохраняет
  declarations; полного графа и активации всех extras не вычисляет. Для tooling
  применяется объявленная целевая среда без optional extras. Недоступные свойства
  target, необходимые для вычисления marker, не подменяются свойствами host.

Лимиты: весь сохранённый набор до 256 МиБ; один скачиваемый файл до 64 МиБ;
metadata одного архива, включая ZIP central directory и выбранные wheel headers,
до 4 МиБ; один журнал до 2 МиБ; до 10 000 members; распакованный объявленный размер
до 128 МиБ; fetch deadline до 900 с и максимум 160 запросов. Уже существующий
каталог fetch не перезаписывается, частичная неудачная загрузка и её журнал
сохраняются. Отсутствие места или превышение лимита останавливает операцию.

Сохранённый набор вместе с проверочными журналами и ROOT-предложением занимает
40 487 554 байта, менее 39 МиБ. Журнал загрузок — 36 585 байт. Реальные пути
окружения и содержимое журналов в публичный отчёт не включены.

## 6. Проверки этой задачи

[Чистые тесты](../../server/tests/test_prepare_dependency_artifacts.py) запускались
один раз после окончательных правок кода. Использован unittest discovery только
нового файла, без pytest/conftest; сетевой opener в тестах заблокирован.
Синтетические архивы проверяют обходы путей, links, дубликаты, identity/tag/hash/size
mismatch, неподдержанные markers, лимиты HTTP/ZIP, несовпадение frozen inputs,
неполный tooling-план и запрет превращения sdist в wheel-only состав.
Проверяется также отсутствие записи при offline verify.

| Проверка | Наблюдавшийся результат | SHA-256 сохранённого журнала |
|---|---|---|
| Чистые тесты инструмента | 19 tests, OK, exit 0 | `b43ddccdb3f304acb39b8171eb2f7cd7b93da568d4bce2f7dff7b3c52da35f33` |
| Offline verifier скачанного набора | exit 0; 65 артефактов, 58 runtime wheels, один source-only блокер | `3380eee1870090580e6c5749e6284618300a74af0130ae81593c0e3056b8014a` |
| Тот же verifier с `--require-wheels` | Ожидаемый exit 1: complete wheel lock unavailable | `260b800e95a812d127ddff826fa89f478873f1a27dc638326d156eda3f45f60a` |
| Журнал 130 загрузок | Объявленные размеры и SHA-256 совпали | `0a51518675ae0277df465e42ac69b251739a88ea0d5b3975e62acaa48a702b20` |

Offline-проверка подтверждает сохранённые входы и прочитанные declarations.
Она не подтверждает доверенность содержимого пакетов, отсутствие уязвимостей
или исполнение целевого runtime. Существующие тестовые наборы приложения
не повторялись; не было установки pip-tools или других пакетов.

## 7. Следующее поручение ROOT

В приватной области сохранено точное предложение с SHA-256
`3d38bbd9c37086f897e64cd4e0738aeea737eebfd6a53c2897ec7b4fa54974f6`.
Оно содержит восемь hashed tooling pins из таблицы, отдельную строку bootstrap pip,
параметры команд и критерии каждой стадии. Это предложение не исполнялось.
ROOT может назначить следующий bounded dispatch в пределах уже согласованной
работы; дополнительный вопрос пользователю для выбора обычных параметров не нужен.

| Стадия | Лимит времени | Действие ROOT и приёмка |
|---|---:|---|
| Входы и target | 60 с | Проверить данный манифест и точный Python 3.13.18 / ordinary cp313 / amd64 / glibc; отдельно подтвердить базовый platform manifest; не использовать application venv |
| Чистый tooling | 180 с | Создать отдельный venv, установить ровно восемь предложенных wheels offline с hashes; сверить версии и выполнить pip check |
| Wheel http-ece | 120 с | Просмотреть сохранённый setup.py, извлечь уже проверенные regular members; выполнить build без isolation и без сети с закреплённым toolchain; проверить и хешировать результат |
| Целевое разрешение | 180 с | Передать compiler только 58 runtime wheels и новый http-ece wheel, `.in` и baseline; получить отдельный hash-complete кандидат lock и объяснить полное замыкание |
| Чистая offline установка | 180 с | После удаления tooling scratch создать новый runtime venv; закрепить pip, установить кандидат lock и выполнить pip check; сверить 59 runtime pins плюс pip без утечки compiler |
| Свидетельства и очистка | 60 с | Сохранить хеши, состав, логи и новый wheel; удалить только принадлежащие стадии venv/source/copies; оставить исходные артефакты и производный wheel до принятия результата |

Общий deadline — 900 с, включая 120 с резерва. Предложены до двух CPU,
1 ГиБ памяти, 128 МиБ scratch на стадию, 256 МиБ суммарных сохраняемых артефактов
и до 2 МиБ на журнал. Tooling и runtime venv последовательно сменяют друг друга.
ROOT должен контролировать фактическое место; превышение лимита, отсутствующий
артефакт, изменение pin или ошибка compiler останавливают стадию с сохранением
журнала. Автоматические upgrades и сеть для backend/resolver/install не допускаются.

Параметры будущего compiler: `--no-config --resolver=backtracking --generate-hashes
--strip-extras --no-index --find-links` на подготовленный runtime wheelhouse,
`--constraint` на baseline и отдельный `--output-file`. Extras сохраняются
в `.in`, а зависимости extras должны попасть в полное замыкание.
Будущая установка использует `--no-cache-dir --no-index --require-hashes
--only-binary=:all:`; dependency checking остаётся включённым.

Эти команды потребуют настоящей целевой среды и выполняются следующим исполнителем
под руководством ROOT. При неизвестном marker или неподдержанном specifier следует
расширить проверяемый контракт отдельной правкой, а не игнорировать декларацию.
При отличии графа от 59 наблюдавшихся пакетов нужен разбор причины без молчаливой
подмены baseline. При несовместимости pip-tools/pip новая пара версий выбирается
явным изменением и получает новую проверку.

Отдельно остаются base/APT snapshot, повторная независимая сборка и сравнение
результатов, функциональная совместимость и выпуск. Текущая подготовка не меняет
Dockerfile, runtime requirements, test requirements, Compose или CI.

## 8. Явно не запускалось

| Действие | Статус |
|---|---|
| Resolver / pip-compile / генерация полного runtime lock | NOT RUN |
| Установка tooling, bootstrap или runtime | NOT RUN |
| Setup/backend/hooks, изготовление wheel | NOT RUN |
| Целевая Python/ABI/runtime проверка и pip check | NOT RUN |
| Контейнеры, image pull/load/run/build и app/driver import | NOT RUN |
| SQL, БД, настоящие API/ключи/среды, VM и CI | NOT RUN |
| Повторная сборка, SBOM, security audit, выпуск | NOT RUN |
