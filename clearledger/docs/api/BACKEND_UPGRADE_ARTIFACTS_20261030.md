# Подготовка артефактов обновления backend, 30.10.2026

Подготовлены отдельные входы для 60 runtime distributions и 66 уникальных wheel
в объединении runtime/tooling. Проверены файлы, metadata и активные declarations;
resolver, installer и приложение для этого состава **не запускались**. Новые input,
constraints и manifest остаются предложением. Действующие requirements.txt,
Dockerfile, Compose, CI и исторические baseline locks не изменены.

## Основание и точный состав

Основа ветки: `5a67955b6a79098cb2436338bb4135a0acca6898`, принятый metadata intake.
Исторический manifest подготовки имеет SHA-256
`3390cbfaa680b9bb970ce43e8d3e32014230908c46fd9e7b1d4464c7cf7365ee`.
Verifier сохранён без правок, SHA-256
`b306a05fc1a6222cd53ae2f4c3ed6ddf89752ee8be5adc847cf08a214d3cc091`.
Предыдущий ROOT результат чистой offline-установки 59 runtime плюс pip за
21,097 с относится к прежнему составу и не подтверждает новый состав.

В [requirements-upgrade-20261030.in](../../server/requirements-upgrade-20261030.in)
сохранены 22 roots, порядок, комментарий и три extras:
`uvicorn[standard]`, `sqlalchemy[asyncio]`, `passlib[bcrypt]`.
Заменены ровно пять прямых pin: FastAPI, PyJWT, pypdf, python-dotenv,
python-multipart. Прежние четыре `>=` остаются прямыми декларациями;
их конкретные версии ограничены новым constraints.

В [runtime-upgrade-20261030.constraints.txt](../../server/locks/runtime-upgrade-20261030.constraints.txt)
сохранены 53 прежние версии, заменены шесть, добавлен annotated-doc.
Это 60 точных pin, а не hash-complete lock и не результат resolver.

| Distribution | Прежняя версия | Кандидат | Requires-Python из wheel |
|---|---|---|---|
| fastapi | 0.115.6 | 0.133.0 | >=3.10 |
| pyjwt | 2.10.1 | 2.15.0 | >=3.9 |
| pypdf | 5.1.0 | 6.21.2 | >=3.9 |
| python-dotenv | 1.0.1 | 1.2.2 | >=3.10 |
| python-multipart | 0.0.18 | 0.0.31 | >=3.10 |
| starlette | 0.41.3 | 1.3.1 | >=3.10 |
| annotated-doc | отсутствовал | 0.0.2 | >=3.8 |

Источники точных релизов: [FastAPI](https://pypi.org/pypi/fastapi/0.133.0/json),
[PyJWT](https://pypi.org/pypi/pyjwt/2.15.0/json),
[pypdf](https://pypi.org/pypi/pypdf/6.21.2/json),
[python-dotenv](https://pypi.org/pypi/python-dotenv/1.2.2/json),
[python-multipart](https://pypi.org/pypi/python-multipart/0.0.31/json),
[Starlette](https://pypi.org/pypi/starlette/1.3.1/json),
[annotated-doc](https://pypi.org/pypi/annotated-doc/0.0.2/json).
Использованы сохранённые version JSON и их receipts от предыдущего intake;
новых запросов за этими metadata не было.

Tooling оставлен прежним: pip 26.2.2, pip-tools 7.6.2, build 1.3.0,
click 8.5.0, packaging 26.3, pyproject-hooks 1.2.0, setuptools 80.9.0,
wheel 0.45.1. Click и packaging входят также в runtime:
`60 + 8 − 2 = 66` уникальных artifacts, все wheel.

## Файлы и provenance

[Новый manifest](../../server/locks/dependency-artifacts-upgrade-py313-linux-amd64-20261030.json)
содержит для каждого из 66 файлов имя, версию, роли, размер, SHA-256,
официальный URL, pin/hash исходного version JSON, wheel tags, Requires-Python,
Requires-Dist, Provides-Extra и hashes прочитанных METADATA/WHEEL.
Новые wheel выбраны проверенным stdlib verifier; все семь имеют
`py3-none-any`. Остальные сохраняют прежний выбор cp313/abi3/universal и
manylinux x86_64 с заявленным glibc ceiling 2.41. Это выбор по declarations;
его принятие фактическим installer на целевом CPython 3.13.18 проверит ROOT.

| Новый wheel | Байт | SHA-256 |
|---|---:|---|
| annotated_doc-0.0.2-py3-none-any.whl | 4056 | `2188cb99e353fcb5c20f23b8bc6f5fa7c924b213fac733d4b44883f9edffa090` |
| fastapi-0.133.0-py3-none-any.whl | 104787 | `0a78878483d60702a1dde864c24ab349a1a53ef4db6b6f74f8cd4a2b2bc67d2f` |
| pyjwt-2.15.0-py3-none-any.whl | 33680 | `7a3742debf6b879e912dbb9819ceec1594be812452b78c5f2e2dfc56564954f8` |
| pypdf-6.21.2-py3-none-any.whl | 407766 | `1d44d1a3a200f25062adff0085b02040e4646431ac2ccac22e42679e91466084` |
| python_dotenv-1.2.2-py3-none-any.whl | 22101 | `1d8214789a24de455a8b8bd8ae6fe3c6b69a5e3d64aa8a8e5d68e694bbcb285a` |
| python_multipart-0.0.31-py3-none-any.whl | 29996 | `8408153d68a9773291fc1da39a8b85a50044bddbabd2dd72e9229776b7b15e28` |
| starlette-1.3.1-py3-none-any.whl | 73632 | `c7372aae11c3c3f26a42df7bd626cec2f47d03483d261d369516a615a53714c6` |

Повторно использованы 58 upstream wheel из прежнего cache и один производный
http-ece wheel. Копии обычные, без hardlinks; SHA/size проверены повторно.
Исходные 130 metadata/artifact файлов и прежний download-events остались
побайтово прежними. Сохранённые binary files не включены в Git.

http-ece 1.2.1 не пересобирался. Повторно проверен wheel
`http_ece-1.2.1-py2.py3-none-any.whl`, 4849 байт, SHA-256
`a89e8aa1521d121dde75250524981f3f3fa3594cc1117da99904f2ba5ac24f9d`.
Связь manifest сохраняет source sdist SHA-256
`8c6ab23116bbf6affda894acfd5f2ca0fb8facbcbb72121c11c75c33e7ce8cff`,
ROOT receipt SHA-256
`4d267b0d80dc10bbb129b620fd9aa7a849424289497029604a0435d7e08a145e`,
первоначальный build receipt SHA-256
`498ef9638616b52fcebaf75effed4a8a05abf7308f040b586f75e87c3c5e4964`
и точные восемь tooling pin. Source sdist относится к provenance и не добавлен
как 67-й installable artifact. Одиночная прежняя сборка не доказывает
воспроизводимость wheel.

ZIP разбирался без извлечения и исполнения, с прежними ограничениями путей,
дубликатов, размера и metadata. Для всех 60 runtime wheel не обнаружены
`.pth`, `sitecustomize.py`, `usercustomize.py`. Это узкая проверка startup hooks,
не полный анализ поведения или безопасности содержимого.

Сетевой этап: ровно семь GET wheel с files.pythonhosted.org, 676018 байт суммарно,
и один новый OSV POST; все восемь HTTP 200, 1,149349 с.
Завершён `2026-10-30T15:41:08.520282+00:00`; дальнейшие fetch закрыты.
TLS проверялся штатным SSL context, redirects запрещены; timeout 25 с,
concurrency 3, overall 600 с, один wheel ≤16 MiB, metadata ≤4 MiB,
private cache ≤96 MiB, network log ≤2 MiB. Частное staging после проверок
занимает 40573297 байт с дополнением proposal v2; log 2960 байт.
Ограничения не увеличивались.

## Что подтверждают declarations

Для фактических wheel проверены Requires-Python и все 368 Requires-Dist:
289 runtime и 79 tooling. На заданном environment CPython 3.13.18/Linux/x86_64
и только трёх разрешённых root extras активны 67 runtime и восемь tooling
declarations. Все активные требования удовлетворены предложенными pin;
222 runtime и 71 tooling declaration неактивны для этого environment/extras.
Extras распространялись до неподвижной точки, все 60 runtime имён достижимы
от 22 roots. Unsupported активных semantics и unresolved не получено.
Для неактивных optional requirements сохранены исходные строки и причины
неактивности; их состав не разрешался и их совместимость не утверждается.

FastAPI 0.133.0 объявляет Starlette >=0.40.0, Pydantic >=2.7.0,
typing-extensions >=4.8.0, typing-inspection >=0.4.2 и annotated-doc >=0.0.2.
Starlette 1.3.1 объявляет AnyIO >=3.6.2,<5. Прежние Pydantic 2.14.2,
typing-extensions 4.16.0, typing-inspection 0.4.4 и AnyIO 4.15.1 укладываются
в эти declarations; необходимость нового annotated-doc отражена constraints.
Опциональные FastAPI standard/all и Starlette full не активированы.
[FastAPI metadata](https://pypi.org/pypi/fastapi/0.133.0/json),
[Starlette metadata](https://pypi.org/pypi/starlette/1.3.1/json).

Сырой текст release JSON и wheel metadata отличается у 24 distributions:
aiosmtplib, build, cryptography, dnspython, fastapi, gunicorn, httpcore, httpx,
idna, lxml, passlib, pip-tools, py-vapid, pydantic, pydantic-settings, pypdf,
python-docx, setuptools, sqlalchemy, starlette, urllib3, uvicorn, uvloop, wheel.
Есть различия пробелов/кавычек/порядка и написания extra; у passlib JSON
Provides-Extra отсутствует, wheel содержит четыре extra. Эти записи не
перезаписывались и не объявлены побайтово или полностью семантически равными.
Полные обе стороны сохранены в частном readonly receipt; критерий installable
declarations в manifest взят из проверенного wheel. Это не resolver PASS.

## Новый OSV scope и открытый вопрос tooling

Отдельный POST [OSV querybatch](https://api.osv.dev/v1/querybatch) содержит
66 уникальных пар package/version: весь новый runtime плюс все восемь tooling
с объединением двух пересечений. Имена упорядочены лексикографически; полный
request, 66 result rows и их порядок сохранены. Pagination/error отсутствуют.
Повторных baseline60 или candidate6 запросов не было.

Для 60 runtime версий query не вернул matches. Для двух неизменённых tooling
версий получено пять package-advisory записей:

| Package/version | Все возвращённые advisory ID в исходном порядке |
|---|---|
| setuptools 80.9.0 | GHSA-h35f-9h28-mq5c; GHSA-xmj3-9gf7-h52w; PYSEC-2026-3447 |
| wheel 0.45.1 | GHSA-8rrh-rw8j-w5fx; PYSEC-2026-2047 |

Пять записей не означают пять независимых уязвимостей: aliases здесь не
объединялись, advisory details этим этапом не запрашивались. В manifest
сохранены ID/modified как их вернул OSV. ROOT принял эти metadata и подтвердил
сохранение прежних восьми pin; actual execution пока **не разрешён ROOT**.
Отдельный review/выбор scope или обновления tooling остаётся у ROOT.
Утверждённые восемь pin не менялись.
Отсутствие matches не доказывает безопасность или отсутствие достижимого пути;
version query не доказывает достижимую уязвимость. Exploitability/severity
triage, закрытия alerts и triage-finding/v0 не выполнялись.

## Подготовленный ROOT-only execution proposal

Частные driver, proposal и execution contract зафиксированы hash ниже.
По уточнению ROOT добавлен proposal v2: полные частные request/response/
provenance paths и явное отсутствие разрешения actual execution. Proposal v1
сохранён; driver, contract и manifest не менялись. Дополнение проверено отдельно
по JSON/paths/hashes без повторения artifact checks. Таблица описывает будущий
технический контракт; запуск допускается только по последующему решению ROOT.
Driver только разобран AST и скомпилирован как текст, без импорта и исполнения.
Он основан на принятом v3; AST функций target_facts, owned_scratch_bytes и
safe_exception_details совпадает с принятым исходником. Правило ENOENT
действует только для исчезнувшего дочернего entry собственного live scratch;
ошибки входов, output и прочие errno не подавляются.

ROOT запускает в точном ранее доказанном backend image snapshot, CPython
3.13.18 ordinary cp313/GIL/Linux amd64. Sandbox: network none, read-only root,
nonroot, CPU 2, memory 1 GiB, pids 128, собственный tmpfs 256 MiB,
только безопасные read-only inputs и fresh owned writable output.
Никакие реальные env, credentials или исходники приложения не нужны.
Driver сверяет фактическую libc внутри target, mounts/cgroups, pin/hash
manifest/verifier/inputs, 66 wheel и metadata. ROOT отдельно отвечает за image
digest/archive/resource preflight и очистку Docker resources.

| Фаза ROOT | Лимит, с | Критерий принятия | Статус здесь |
|---|---:|---|---|
| verify-inputs | 60 | Target/guards, 66 SHA/size/metadata, 60 constraints, 22 roots/3 extras | NOT RUN |
| clean-tooling | 180 | Fresh venv без system-site-packages; восемь hashed pin offline; exact inventory и pip check | NOT RUN |
| http-ece-reuse | 120 | Проверенный wheel/receipt скопированы в output; без build/backend | NOT RUN |
| target-resolution | 180 | pip-tools compile; ровно 60 pin и по одному утверждённому wheel hash | NOT RUN |
| clean-offline-install | 180 | Fresh venv, hashed pip 26.2.2, install 60 с dependency checking, pip check, exact inventory 61 | NOT RUN |
| cleanup | 60 | Удалён только собственный scratch; bounded evidence сохранены | NOT RUN |

Global deadline 900 с; scratch/retained ≤256 MiB каждый, совокупные logs ≤2 MiB.
Subprocess capture ограничен; на сбое собственная process group останавливается
и leader reap выполняется. Первый compiler/installer/semantic/resource failure
останавливает этап с phase/log SHA/exit code; upgrades, сеть, retries и подмена
pin запрещены. Tooling scratch удаляется после receipts до свежей runtime venv.

Runtime finder содержит только 59 runtime wheel без http-ece; второй finder
содержит один повторно использованный http-ece wheel. Tooling-only wheel туда
не попадают. Compiler получает `--no-config --no-index --generate-hashes
--strip-extras`, новые constraints и исходные 22 roots, pip args
`--no-index --only-binary=:all: --no-cache-dir --retries 0`.
Чистая установка использует `--require-hashes --only-binary=:all: --no-index`
и сохраняет dependency checking. Дополнительное имя, версия или wheel hash
считаются drift и завершают этап ошибкой.

Выходная схема proposal: result.json со status/failure/target/records/hashes,
phase receipts, tooling/runtime inventories, provisional-lock receipt,
один reused wheel, bounded logs с SHA/size/exit code, hashed bootstrap/tooling
inputs и созданный ROOT compiler provisional runtime lock. В этой подготовке
runtime lock не создавался. Inventory читается через stdlib metadata с `-S`,
без импорта приложения или установленных runtime packages.

## Проверки и следующий пакет работ

Единственная финальная readonly-проверка нового состава завершилась exit 0
за 0,668246 с: все 66 artifacts и 66 version JSON, точная delta inputs,
130 прежних cache hashes, network receipts/order, declarations, driver AST/
compile, contract/proposal hashes и budgets. Старые PASS suites не повторялись.
Список текстовых различий metadata сохранён, а не скрыт итоговым статусом.

ROOT владеет следующим этапом: рассмотреть metadata tooling, проверить
immutable inputs/proposal, затем отдельно выполнить target compiler/offline
install по таблице. Acceptance: ровно 60 runtime в hash-complete provisional
lock и 61 installed distribution с pip, без drift, pip check и cleanup evidence.
При неудаче сохранить phase/log hashes и остановиться без смены pin.

После этого ROOT отдельно определяет static triage и функциональные regressions:
JWT verification/claims, multipart limits и uploads, FastAPI request/response
validation, lifespan/middleware/errors, PDF text extraction на синтетических
fixtures, dotenv parsing на фиктивных строках, прежние async contracts.
Major переходы pypdf 5→6 и Starlette 0.x→1.x, а также FastAPI API/behavior changes
требуют таких проверок независимо от совпадения dependency declarations.
Никаких PoC, production data или реальных env для этих предложений не нужно.

Активация требует отдельного решения ROOT после actual checks. До неё откат
заключается в отказе от новых предложенных файлов; действующий runtime не
менялся. Для будущей активации сохраняются прежние input/lock/image evidence;
нельзя получать «откат» повторной установкой прежних плавающих requirements.
Baseline locks остаются историческими артефактами, не security certification.

NOT RUN: Docker/image load/run, venv/install/compiler/backend/build,
app/driver import, lifespan, SQL/DB, функциональные tests, независимый rebuild,
SBOM/security audit, CI, activation, release/deploy. Worker не выполнял ROOT driver.

## Контрольные SHA-256

| Объект | SHA-256 |
|---|---|
| Новый manifest | `833b2d37033c31608a4af235937838d8cc9ab040a94f4284ec2d5beb36279edf` |
| Source-only plan до сети | `5e3f8930916acc0bf7bfd9a04def5c1aca6b256285029d1233acd4cad547ec63` |
| Stdlib preparation helper | `6cbced961efa87d5242ec24c5218e891c8089c5f7e9bbc5a80ae0b819579c3e2` |
| Review receipt до сети | `43f0d4a09c67d8eda34b2406e68378384d8884e6c5247fe756e1289932575bff` |
| Network events | `ec796e8807487c1c3511829060f8e239e9c46eb484951167981bd9574cf6c452` |
| Закрытие network phase | `09007f69490ca9e50d2b83c21089b874e5d85ed0120e352a22b4a47c83727300` |
| OSV request 66 | `8b62a9b22cc443ec8cb89b9e34a03c977b55a3351cceff2aaf0dc1dbb2a073f4` |
| OSV response 66 | `7c9a3be47db0e365eb471b56f6b80662cc5704982a7303770896099bcda78c2b` |
| Новый private ROOT driver | `be57dfd15801be2440bb08507963c57642c2fd74f608e09f8f8e70fb4c50c645` |
| Private execution proposal v1, сохранён | `0a912c14981dd5ddd4ec1b797a7afc4ec72a88f663c6daea85148ae05e75792c` |
| Новый private execution proposal v2 | `c5d1fd6107e7e07c6f8bb3a44871b5dd695ecc2207fd91f728db06d56f022cee` |
| Review дополнения proposal v2 | `c7e08106892dd19b28f9f3b0f84fe7608168b6122d3cf55f0c538c6f46e4deae` |
| Private execution contract | `99685e9199f321808a95bbdaab9600808a3ca3e77f7cd578dc221e57a4575646` |
| Финальная readonly-проверка | `99857aa53d9816755ce4e3e19a49ffb53760eb0b9701f39d64c89aad1388a7aa` |

Hash/size двух новых input находятся в manifest. Частные исходные receipts,
metadata, helper/proposal/driver и wheel сохранены для независимой проверки ROOT;
в публичные файлы включены только безопасные pins, declarations, URL и hashes.
