# DEP: advisory metadata intake и план совместимого обновления

Дата: 30.10.2026. Intake завершён: все 170 исходных package-advisory pairs связаны
с полученными OSV details; unresolved — 0. Сохранены входной порядок, алиасы,
ranges, source refs и расхождения. Ни exploitability, ни достижимость конкретного
advisory в приложении здесь не оценивались; alerts не закрывались.

Предложение для review ROOT: PyJWT **2.15.0**, pypdf **6.21.2**, python-dotenv
**1.2.2**, python-multipart **0.0.31**, Starlette **1.3.1** вместе с FastAPI
**0.133.0**. Это metadata-кандидаты. Для pypdf нужен переход 5→6, для Starlette
0.x→1.x; новый runtime состав ещё не принят.

## Источник и полнота intake

Ветка создана от `66848e8b3c88c931d6bfb3f5fa7c22e6bc9f891f`.
Baseline — 59 runtime distributions плюс pip `26.2.2` из принятой ROOT чистой
offline-установки. [Исторические locks и target evidence](BACKEND_DEPENDENCY_TARGET_20261030.md)
сохранены без изменения: прежний PASS доказывает установку того состава,
но не является security certification.

| Frozen вход ROOT | SHA-256 |
|---|---|
| Metadata inventory | `9ae342037c53c21765f18d6db0e049279ab7c2c1a258787ef552bbcfeabc6983` |
| `request.json`, 60 queries | `af448c0e986cf05fbef314c102f7702dca1b1d410036609e90e8d2291431711f` |
| `response.json`, 60 results | `c9ceb2d64f7dd55a99a2184326d82667113a786e060d3d17e7629c416c35a928` |
| `summary.json` | `d57accae1d5725d45d6ba88934f2b8ec23bd4407de0ee1fef1c9cdafc6d4450e` |
| Исходный `query.py`, здесь не исполнялся | `69df3bfa816e754f68f9807ee2ccb3d8fa004697e38d686f464f7f991e3f822d` |

Baseline querybatch ROOT выполнен в 14:50:15 UTC. Worker его не повторял.
55 исходных results пусты; это отражает данный ответ OSV, а не полноту всех
возможных advisory sources. Pagination в frozen ответе отсутствует.

| Package / baseline | Исходные pairs | Группы явных alias-связей |
|---|---:|---:|
| pyjwt 2.10.1 | 32 | 17 |
| pypdf 5.1.0 | 108 | 60 |
| python-dotenv 1.0.1 | 2 | 1 |
| python-multipart 0.0.18 | 14 | 7 |
| starlette 0.41.3 | 14 | 7 |
| Всего | **170** | **92** |

92 группы означают связность по опубликованным aliases, а не число подтверждённых
уязвимостей. Все 170 записей остаются отдельными. Withdrawn details в полученной
выборке — 0.

[Публичный bounded index](BACKEND_DEPENDENCY_ADVISORY_INDEX_20261030.json), 710 821 байт,
SHA-256 `e986031fa0ac8303072565f505aa466f9a35c604915e4ec61bdcb7bdfea60d85`,
содержит исходные 60 query/result records, 170 pair positions, literal aliases,
range events, references, withdrawal metadata и receipts URL/hash/time/status.
Полные immutable bodies и длинные version lists сохранены приватно; в index для
version lists приведены count/hash и связь с точным detail body.

Сетевая фаза worker: 336 GET, все HTTP 200, с 14:57:24 до 15:05:01 UTC,
456,835033 с. Получены 170 OSV details, 157 PyPI JSON и 9 официальных upstream
advisory pages. Redirects отклонялись, TLS проверялся стандартным context;
concurrency ≤3, timeout ≤25 с. Максимальный response — 583 176 байт при лимите
4 МиБ; response bodies суммарно 7 891 912 байт, приватный intake менее 9 МиБ
при лимите 64 МиБ. Ограниченный fetch log — 103 541 байт, SHA-256
`9f3f18ca1aa6175403f9dab3d167376a7e46cc848391bb0e6aa2f90dec1db09f`.
После закрытия этой фазы новых сетевых запросов worker не выполнял.

## Что сохраняется как расхождение или unknown

Три alias-группы PyJWT имеют разные range events:

| Связанные input IDs | Различие metadata |
|---|---|
| GHSA-993g-76c3-p5m4 / PYSEC-2026-175 | Introduced `2.0.0` / `0`; fixed у обоих `2.13.0` |
| GHSA-fhv5-28vv-h8m8 / PYSEC-2026-177 | Introduced `2.0.0` / `0`; fixed у обоих `2.13.0` |
| GHSA-jq35-7prp-9v3f / PYSEC-2026-176 | Fixed `2.13.0` / `2.12.1` |

Для третьей группы upstream указывает patched `2.13.0`; обе OSV записи сохранены,
предпочтение не используется для удаления входа.
[Upstream advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-jq35-7prp-9v3f),
[PYSEC detail](https://api.osv.dev/v1/vulns/PYSEC-2026-176)

У python-dotenv upstream одновременно публикует affected `<1.2.1` и patched
`1.2.2`, тогда как OSV range/versions включает `1.2.1` до fixed `1.2.2`.
План сохраняет эту границу как source discrepancy и выбирает опубликованный
patched-кандидат `1.2.2`.
[Upstream](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94),
[OSV](https://api.osv.dev/v1/vulns/GHSA-mf9w-mj56-hr94)

Числовые сравнения выполнены только принятым stdlib verifier SHA-256
`b306a05fc1a6222cd53ae2f4c3ed6ddf89752ee8be5adc847cf08a214d3cc091`.
Для GHSA-42vr-xj54-vc7v и PYSEC-2026-4141 introduced `2.0.0a1` находится вне
поддержанного numeric subset: локальная range evaluation остаётся **unknown**.
Upstream сообщает patched `2.15.0`; это отдельный metadata факт, а не устранение
unknown в ограниченном evaluator.
[Upstream](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v)

ROOT затем передал отдельное PEP 440 observation: `packaging.version.Version`
26.3 из ранее проверенного wheel SHA-256
`d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`.
Для обеих записей `2.10.1`, `2.14.0`, `2.15.0rc1` попадают в интервал,
`2.15.0` и `2.15.0.post1` — вне него. ROOT выполнил это read-only без установки
и приложения; worker не запускал этот инструмент. Proof SHA-256
`72bd6ab539253570416609901c1185e266f3564d891bd957361406f09def3d5f`.
В index добавлено отдельное ROOT observation; исторические два unknown limited
evaluator не переписаны. Это уточнение interval metadata, не remediation или
exploitability verdict; три расхождения источников остаются сохранёнными.

Для остальных 168 pair records кандидат находится вне объявленных numeric ranges
по этому ограниченному сравнению. Это не app verdict. Из 170 полей modified
169 различаются добавленной точностью меньше микросекунды и совпадают на точности
batch; одно совпадает буквально. Оба timestamp сохранены; различие точности
не объявлено доказательством изменения или неизменности advisory content.

## Кандидаты минимальных stable версий

Минимум здесь ограничен этим набором baseline advisory IDs и опубликованными
numeric final releases, доступными без yanked status. Учитываются все известные
fixed границы, а не только одна alias-запись. Prerelease/post/dev/epoch identifiers
за пределами verifier не получают приближённый результат. Общий PEP 440 resolver
не запускался.

| Package | Baseline → metadata-кандидат | Requires-Python кандидата | Комментарий |
|---|---|---|---|
| PyJWT | 2.10.1 → **2.15.0** | `>=3.9` | Наибольшая reported fixed граница `2.15.0`; два range unknown сохранены |
| pypdf | 5.1.0 → **6.21.2** | `>=3.9` | **Major 5→6**; наибольшая fixed граница `6.21.2` |
| python-dotenv | 1.0.1 → **1.2.2** | `>=3.10` | Сохраняется указанное выше расхождение sources |
| python-multipart | 0.0.18 → **0.0.31** | `>=3.10` | Наибольшая fixed граница `0.0.31` |
| Starlette | 0.41.3 → **1.3.1** | `>=3.10` | **Переход 0.x→1.x**; требует новой пары с FastAPI |

Все пять version JSON объявляют non-yanked release и Requires-Python, допускающий
actual CPython `3.13.18`. Это проверка declarations, без получения wheels,
проверки ABI или исполнения библиотеки.
[PyJWT metadata](https://pypi.org/pypi/pyjwt/2.15.0/json),
[pypdf metadata](https://pypi.org/pypi/pypdf/6.21.2/json),
[dotenv metadata](https://pypi.org/pypi/python-dotenv/1.2.2/json),
[multipart metadata](https://pypi.org/pypi/python-multipart/0.0.31/json),
[Starlette metadata](https://pypi.org/pypi/starlette/1.3.1/json)

Наибольшие границы pypdf, multipart и Starlette также прочитаны в upstream pages:
[pypdf](https://github.com/py-pdf/pypdf/security/advisories/GHSA-6c7f-9265-g8fw),
[multipart](https://github.com/Kludex/python-multipart/security/advisories/GHSA-v9pg-7xvm-68hf),
[Starlette](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq).

ROOT отдельно проверил шесть предложенных версий, включая FastAPI `0.133.0`,
в новом querybatch 15:17:27 UTC: HTTP 200, шесть results, ноль matches, без
pagination. Baseline batch 60 строк не повторялся. Request SHA-256
`db6470926b5c5e35f1c3a0f745fd7d50463cd90e05b3d7c4f31254cba6706318`,
response SHA-256 `e7e00f5759742ba9322ec6db4bd44d79d245d9831a06655a80cdb93e39c27928`.
Этот отдельный результат OSV сохранён в index; он не отменяет три расхождения
источников и два локальных unknown и не даёт runtime/exploitability verdict.

## Минимальная declaration-compatible пара FastAPI / Starlette

| FastAPI | Обязательный Requires-Dist Starlette | Starlette 1.3.1 |
|---|---|---|
| 0.115.6, baseline | `>=0.40.0,<0.42.0` | Не входит в constraint |
| 0.132.1, непосредственный предшественник | `>=0.40.0,<1.0.0` | Не входит в constraint |
| **0.133.0**, кандидат | `>=0.40.0` | Входит по metadata |

Проверены version JSON всех 145 опубликованных numeric stable FastAPI releases
не ниже baseline `0.115.6`. `0.133.0` — первый non-yanked из этого множества,
чей Starlette constraint допускает `1.3.1`; его Requires-Python `>=3.10` допускает
Python `3.13.18`. Это минимальный non-downgrade metadata pair, без обещания API
совместимости. Полный audit версий, URLs и hashes находится в index.
[Baseline](https://pypi.org/pypi/fastapi/0.115.6/json),
[0.132.1](https://pypi.org/pypi/fastapi/0.132.1/json),
[0.133.0](https://pypi.org/pypi/fastapi/0.133.0/json)

Потенциальное влияние на closure:

- FastAPI `0.133.0` требует pydantic `>=2.7.0`, typing-extensions `>=4.8.0`,
  typing-inspection `>=0.4.2`; наблюдавшиеся `2.14.2`, `4.16.0`, `0.4.4` подходят
  по numeric declarations. Их версии следует удержать в новом candidate constraints.
- Новая обязательная зависимость — `annotated-doc>=0.0.2`. Минимальный `0.0.2`
  объявляет Python `>=3.8` и не объявляет Requires-Dist. Он отсутствовал в baseline
  60 и в отдельном ROOT batch шести кандидатов; advisory coverage ещё требуется.
  [Metadata](https://pypi.org/pypi/annotated-doc/0.0.2/json)
- Starlette `1.3.1` требует anyio `>=3.6.2,<5`; baseline `4.15.1` подходит.
  Его typing-extensions marker `python_version < "3.13"` не активен для `3.13.18`.
  Optional `full`/`standard` extras не добавляются автоматически. Для Starlette[full]
  metadata отдельно объявляет `httpx2>=2.0.0` и `httpx>=0.27.0,<0.29.0`; поэтому
  включение этого extra изменит граф, а совместимость test-client tooling требует
  отдельной фактической проверки. В исходном batch httpx2 отсутствовал.
- Возможен состав 60 runtime+pip вместо 59+pip за счёт annotated-doc, если остальные
  зависимости останутся прежними. Это оценка metadata; фактический resolver может
  показать дополнительные изменения. Нового полного lock пока нет.

## Пакет обновления для отдельного решения ROOT

1. ROOT рассматривает шесть pins и два major-перехода, расхождения и исходные
   unknown вместе с отдельным PEP 440 observation ROOT.
   Конкретная static exploitability triage, если нужна для claims, выполняется
   ROOT отдельно inline. Эта intake-задача не создаёт finding/triage verdict.
2. В отдельной области создать новый candidate input/constraints. В direct input
   меняются FastAPI, PyJWT, pypdf, python-dotenv и python-multipart; три исходных
   extras сохраняются. Starlette `1.3.1` и потенциальный annotated-doc `0.0.2`
   задаются в новом candidate constraints. Исторические baseline/locks не редактировать.
3. После отдельного approval ROOT получить и проверить новые артефакты, выполнить
   clean target resolution на CPython 3.13.18/linux amd64 и получить hash-complete
   closure. Сверить весь diff name/version/hash/markers, сохранить прежние pins
   остальных пакетов либо отдельно объяснить изменение. Проверить OSV для всего
   нового closure и дополнительного tooling; шесть пустых results не покрывают их.
4. Выполнить actual clean offline install/pip check, затем перечисленные ниже
   library и продуктовые regressions. Полный backend suite — только в отдельном
   тестовом контуре с явным TEST_DATABASE_URL и отдельным UPLOAD_DIR; реальные
   env-файлы/keys не используются. В этой задаче эти действия не запускались.
5. ROOT принимает результаты и решает активацию отдельным изменением сборочного
   контракта. До этого существующие requirements, Dockerfile, Compose и CI остаются
   действующими; текущие provisional locks сохраняют историческую идентичность.

## Предлагаемые regressions и rollback

ROOT передал source inventory только для выбора будущих проверок, без verdict
по advisory. Он включает [auth.py](../../server/app/auth.py), SSO, partner/app identity,
management delegation, Jitsi, support/voice context и native routers. Для PDF
указан [contract_liability.py](../../server/app/services/contract_liability.py),
PdfReader/extract_text; dotenv используется через Settings env_file.

| Область | Конкретная будущая приёмка |
|---|---|
| PyJWT и общие потребители | Настоящие encode/decode кандидатной библиотеки на синтетических ключах и golden claims; алгоритмы, подпись, issuer/audience, срок, leeway, типы claims и JWKS. Затем Core/SSO/partner/app identity, delegation, Jitsi, support/voice context и native-router regressions с реальным token path |
| pypdf 5→6 | Golden PDF fixtures для PdfReader/extract_text: ожидаемый текст, кодировки, пустые страницы, поддерживаемые encrypted документы и ошибки; сравнить результат consumer contract_liability и resource bounds |
| Settings / dotenv | Синтетические config fixtures: precedence, quoting, encoding, expansion и override semantics; без чтения настоящих env-файлов |
| FastAPI / Starlette / multipart | Реальные library parsing и ASGI paths: upload/form limits и cleanup; FileResponse/HEAD/Range/status/headers; OpenAPI golden diff, validation/error schemas, auth и company scope |
| Новый closure | Полный inventory/hash set, pip check, отсутствие лишних extras/tooling, actual target import/compatibility checks в отдельно разрешённом ROOT контуре |

HTTP fixtures с подменённым current_user не заменяют настоящие JWT encode/decode
и token-path regressions общих потребителей. Здесь нет PoC, runtime тестов или
оценки того, достигается ли условие конкретного advisory.

Rollback возвращает единый ранее принятый комплект source/input/lock/artifact
hashes и exact image. Новые и прежние артефакты сохраняются до принятия выпуска;
сборка старого Git через плавающие индексы не является rollback. Любое изменение
форматов/контрактов, найденное при major regressions, требует отдельного решения
до активации. Возврат исторических pins не закрывает текущие advisory observations.

NOT RUN: package/wheel/sdist download, установка, resolver, приложение/драйверы,
app/network tests, PoC, SQL/БД, static exploitability triage, fixes, alert closure,
CI, merge, deploy и runtime activation. Единственные новые repo-результаты —
этот план и bounded public index; прежние evidence, baseline, locks и код не менялись.
