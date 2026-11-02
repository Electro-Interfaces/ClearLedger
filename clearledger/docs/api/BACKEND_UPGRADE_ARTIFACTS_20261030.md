# Подготовка артефактов обновления backend, 30.10.2026

## Текущий prospective состав: отдельное обновление tooling

Подготовка двух новых compiler-tooling pin завершена без исполнения tooling.
Основа: принятый ROOT commit `19fda5c6a15ac111a89f5593d3b09e2309dddc35`.
Текущий manifest заменяет только setuptools 80.9.0→84.1.0 и wheel 0.45.1→0.46.2.
Остальные шесть tooling pin, все 60 runtime entries, 22 roots и три extras
сохранены. Новый состав ещё не установлен и не активирован; actual execution
требует отдельного решения ROOT. Предыдущий driver не запускался.

Восемь **COMPILER_TOOLING**: pip 26.2.2, pip-tools 7.6.2, build 1.3.0,
click 8.5.0, packaging 26.3, pyproject-hooks 1.2.0, setuptools 84.1.0,
wheel 0.46.2. Объединение runtime/tooling по-прежнему содержит 66 имён:
60 runtime + 8 tooling − 2 пересечения click/packaging.

Неизменные входы:

| Вход | SHA-256 |
|---|---|
| requirements-upgrade-20261030.in, 531 байт | `90e92d607c5f3c966f5dca129461d92fdfc2a094e5b3a77e5e211ad5dc4d8caf` |
| runtime-upgrade-20261030.constraints.txt, 1235 байт | `0df586ccfd455936da34929fd32ded0c241b0bf3befad06e83b0be61c94ebfce` |
| Canonical stdlib verifier | `b306a05fc1a6222cd53ae2f4c3ed6ddf89752ee8be5adc847cf08a214d3cc091` |

В Git изменяются только prospective manifest и этот отчёт; requirements.txt,
Dockerfile, Compose, CI, baseline locks, verifier, приложение и тесты не менялись.
Прежний manifest `833b2d37…` сохранён полностью в принятом commit
`d12065242ed92fdf8d841fd447d8b80ebe8a2d18` и отдельной private byte-копии до правок.
Прежние driver `be57dfd1…`, proposal `c5d1fd61…`, пять OSV записей, aliases,
network receipts и прочие evidence остаются неизменными. Ниже сохранён архив
первой подготовки; его tooling pin и hashes относятся к историческому составу.

## Два новых wheel и закрытый сетевой этап

| Новый wheel | Байт | Requires-Python | SHA-256 |
|---|---:|---|---|
| setuptools-84.1.0-py3-none-any.whl | 819380 | >=3.10 | `5231689c6ac8156cd155cfb98c3fd6fb252c3e7e9bd3d78b64d3c55f132624c9` |
| wheel-0.46.2-py3-none-any.whl | 29971 | >=3.9 | `33ae60725d69eaa249bc1982e739943c23b34b58d51f1cb6253453773aca6e65` |

Оба файла объявлены точными официальными version JSON:
[setuptools 84.1.0](https://pypi.org/pypi/setuptools/84.1.0/json),
[wheel 0.46.2](https://pypi.org/pypi/wheel/0.46.2/json).
JSON SHA-256 соответственно
`75427bb7a4289a8f06fe176e3eab998710051b36706c80c1df7e796000372f02` и
`de75a6d8388c2bc34f1c79f2002d344c6f466eeaa54aba79e791bb14cbf1c205`.
SHA/size скачанных wheel совпали с объявлениями; ZIP/METADATA/WHEEL прочитаны
без извлечения или исполнения. Requires-Python и universal tags допускают
заявленный CPython 3.13.18; фактический interpreter/ABI/glibc проверит ROOT.

Новая отдельная network phase: два GET version JSON с pypi.org, два GET wheel
с files.pythonhosted.org и один POST нового union66 в api.osv.dev. Все пять
HTTP 200, 1,145642 с; закрыта `2026-10-30T15:59:36.232513+00:00`.
TLS штатный проверяемый, redirects запрещены, timeout ≤25 с, concurrency 2
при разрешённых ≤3, overall ≤180 с, wheel ≤16 MiB, metadata ≤4 MiB,
новое private staging ≤16 MiB, log ≤2 MiB. Итоговый private объём
1419674 байт, network log 1606 байт. Дальнейшие fetch закрыты.

64 прежних wheel/metadata повторно проверены по SHA/size непосредственно
в immutable предыдущем cache: полной новой копии 40 MiB нет, refetch нет.
Private proposal перечисляет все 66 точных source paths, hashes, sizes и
назначения для последующей сборки ROOT read-only logical union. Worker не
создавал контейнеров или окружений и не устанавливал пакеты.

У setuptools wheel есть `distutils-precedence.pth`, 151 байт, SHA-256
`2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224`.
Прочитанный текст выбирает local distutils по SETUPTOOLS_USE_DISTUTILS и
условно вызывает `_distutils_hack.add_shim()`. Он не выполнялся worker.
У нового wheel package таких hooks нет. Это только изолированный tooling:
setuptools/wheel не добавлены в runtime finder или runtime inventory.
Driver проверяет точные hook name/size/hash до будущей tooling-установки;
runtime запрет `.pth`/sitecustomize/usercustomize сохранён для всех 60 wheel.
Поведение hook и совместимость pip-tools этим чтением не доказаны.

## Metadata closure и OSV scope

Runtime closure неизменен: 289 declarations, 67 активных, 222 неактивных;
достижимы все 60 имён от прежних 22 roots/трёх extras. Tooling: 79 declarations,
девять активных и 70 неактивных. Дополнительный активный edge относительно
прежней подготовки: wheel требует `packaging >= 24.0`; прежний packaging 26.3
его удовлетворяет. Дополнительных имён/версий не понадобилось, unsupported
активных semantics/unresolved нет. Это source-only supported-subset check,
не resolver или installer PASS.

Verifier source не менялся. Только в private процессе проверена исходная
TOOLING map, затем явно назначена точная новая восьмёрка через
`v.TOOLING = dict(COMPILER_TOOLING)` перед проверкой tooling_declarations.
Политика target, inspector, marker/numeric semantics и guards сохранены.

ROOT выбрал maintenance pin по сохранённым официальным advisory details:
setuptools fixed 83.0.0 в [GHSA-h35f-9h28-mq5c](https://api.osv.dev/v1/vulns/GHSA-h35f-9h28-mq5c)
и [PYSEC-2026-3447](https://api.osv.dev/v1/vulns/PYSEC-2026-3447),
fixed 84.1.0 в [GHSA-xmj3-9gf7-h52w](https://api.osv.dev/v1/vulns/GHSA-xmj3-9gf7-h52w);
wheel fixed 0.46.2 в [GHSA-8rrh-rw8j-w5fx](https://api.osv.dev/v1/vulns/GHSA-8rrh-rw8j-w5fx)
и [PYSEC-2026-2047](https://api.osv.dev/v1/vulns/PYSEC-2026-2047).
Все пять advisory ID, range events, aliases, withdrawn=null и source hashes
включены в history manifest; полные исходные details сохранены в принятом
ROOT intake. Новых detail GET не было.
Это основание подготовки кандидатов, без exploitability verdict и без заявления
об исправлении подтверждённой runtime уязвимости.

Новый query66 содержит весь runtime60 и новую compiler-tooling8 с объединением
двух пересечений; все input/result rows и лексикографический порядок сохранены.
66 results, zero matches, zero pagination/error/unresolved. Прежний ответ с пятью
tooling package-advisory записями сохранён отдельно в history и исходном cache;
он не перезаписан новым zero-match ответом. Aliases не схлопывались в вывод
о числе независимых уязвимостей. Query не доказывает безопасность или reachability;
static triage, severity verdict, triage-finding/v0 и закрытие alerts не выполнялись.

## Исторический BUILD_TOOLING и будущий COMPILER_TOOLING

http-ece wheel не пересобирался: SHA-256
`a89e8aa1521d121dde75250524981f3f3fa3594cc1117da99904f2ba5ac24f9d`,
ROOT receipt `4d267b0d…`, source sdist `8c6ab231…`. В его provenance остаётся
первоначальная восьмёрка **BUILD_TOOLING** с setuptools 80.9.0 и wheel 0.45.1.
Она отличается от будущей COMPILER_TOOLING с 84.1.0/0.46.2; равенство этих map
не требуется. Для каждой роли проверяются своя точная map, receipt и hash.
Новый tooling не объявлен toolchain, построившим retained wheel. Backend/build
не включены в будущий pipeline.

Подготовлен новый private `target-upgrade-tooling-v3.py`, отдельные execution
contract/proposal. Они прошли только AST/compile/source review; driver не
импортировался/не исполнялся. Прежние files сохранены. Source comparison
подтвердил неизменность budget, bounded diagnostics, ENOENT-only owned live
scratch rule, process-group kill+reap, install/inventory и cleanup guards.

Предложенный будущий ROOT pipeline:

| Фаза | Лимит, с | Acceptance | Статус worker |
|---|---:|---|---|
| verify-inputs | 60 | Target/frozen66, неизменные inputs/runtime, две точные toolmap, hooks | NOT RUN |
| clean-tooling | 180 | Fresh isolated venv, восемь новых hashed toolpin offline, exact inventory8, pip check | NOT RUN |
| http-ece-reuse | 120 | Exact retained wheel/receipt и историческая BUILD_TOOLING; без backend | NOT RUN |
| target-resolution | 180 | Compile прежних 22 roots/60 constraints; exact60 pin/hash closure | NOT RUN |
| clean-offline-install | 180 | Fresh venv, pip26.2.2, 60runtime с hashes/dependency checking, inventory61/pip check | NOT RUN |
| cleanup | 60 | Только собственный scratch удалён, bounded evidence сохранены | NOT RUN |

Target: тот же exact actual backend image snapshot, CPython 3.13.18 ordinary
cp313/GIL/Linux amd64; фактическая glibc читается внутри target, не с host.
ROOT guards: network-none/read-only root/nonroot, CPU2/memory1 GiB/pids128,
собственный tmpfs256 MiB, readonly safe inputs, fresh owned output, global900 с,
scratch/retained ≤256 MiB, aggregate logs ≤2 MiB. Никаких app/env/key/prod mounts.
Root-only proposal содержит точные команды, schema outputs и все source paths.
Runtime finder: 59 прежних runtime wheel плюс отдельный retained http-ece;
tooling-only files туда не попадают. Compiler/installer используют no-index,
only-binary, exact pins/hashes; первый failure/drift останавливает pipeline
с phase/exit/log SHA, без сети, retries или изменения версий.

Финальная новая readonly-проверка завершилась exit0 за 0,970268 с: оба новых
wheel/JSON, все 64 retained entry, 290 frozen previous files, runtime/input/hash
invariants, source-only closure, OSV order/results, network budgets, proposal
и driver AST/compile. Старые PASS suites не повторялись. Actual tooling/compiler/
installer совместимость, functional regressions, rebuild/security certification,
runtime activation, release и deploy не проверялись.

ROOT остаётся отдельно рассмотреть maintenance evidence и решить actual scope;
после этого выполнить proposed target phases и принять либо сохранить failure.
Acceptance будущего этапа: exact8 tooling, exact60 lock closure, exact61 runtime
inventory с pip, pip check и cleanup receipts. Следующие app regressions и
rollback исходного runtime плана остаются в архиве ниже. До активации действующий
runtime не менялся; откат подготовки заключается в отказе от новых кандидатов,
с сохранением всех исторических input/lock/image evidence.

## Текущие контрольные SHA-256

| Объект | SHA-256 |
|---|---|
| Prospective manifest после двух toolpin replacements | `8711de6afb6bc461718851a537c2456ea9b1f68b2f4236f3de599df561493b7f` |
| Source-only plan перед новой сетью | `ab02368c2c15745d3d8b7012c18450e125250f6a25f1e2415a8f117d8fa0f343` |
| Новый stdlib helper | `ca4e5269808f130f9f389a03d70bdad3e36e3f94c92648a0164918e4a1bb7b33` |
| Source review до сети | `5b979681368764d468586e6ed0e32ac5b38b2b06e1b2ccf0898acd5f40e7166f` |
| Новые network events | `c01c82623c33ead7607e53105965a138d63eb06d153747e2ab60496cd4dec02e` |
| Закрытие новой network phase | `114415a9d83d3cf8c9622115258215a614d660ea28fd4633bb18b6529ba9f92d` |
| Новый query66 request | `1270aacb0b7c378d08b5ca00db3591941c653997027176c27156d6f89a94cdb0` |
| Новый query66 response | `b6d1a26e330ddb48c74cda4970bd8416b1877a7d8ca06bc5a1125ec4faa2e152` |
| Новый private tooling-v3 driver | `0a3b207319bdc94c9c1f77007e762abdc6cb3661a5e2febba70f33168842663b` |
| Новый private tooling-v3 proposal | `c73831982ec1692cdb42697dfea4152a2c57aee19ec9e647fd3855993c95464d` |
| Новый private tooling-v3 contract | `f71f5bc3148add0b7ebb95e2d324507dc7308163dd473c760e5e9f16aa5fe767` |
| Новая readonly-проверка | `5b4a6022fd1f8b8c947cccf11f7229e74726477a29e4b090aece8ad7ce3d24ee` |

Частные paths/raw metadata/receipts/binaries не публикуются. В Git остаются
только безопасные pins, declarations, публичные source URLs и bounded hashes.

---

## Архив первой подготовки d1206524: до обновления двух tooling pin

Следующий текст сохранён как историческое evidence. В нём прежняя compiler
toolchain 80.9.0/0.45.1, прежние manifest/query/driver/proposal и статусы первой
подготовки. Текущий prospective состав и новые hashes указаны выше.


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
