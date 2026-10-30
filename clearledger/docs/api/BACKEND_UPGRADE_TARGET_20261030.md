# Backend upgrade: принятый target evidence, 30.10.2026

Основа: точный integration `cf209237bf495e7b5fa981976fac20959c88d5db`.
ROOT выполнил единственный tooling-v3 target run; worker независимо проверил
сохранённые bytes/hashes/receipts, не повторяя исполнение. Результат:
**resolver и чистая offline установка кандидата PASS; runtime не активирован**.

Target image manifest `sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51`:
CPython 3.13.18, Linux x86_64, ordinary cp313/GIL, glibc 2.41, uid1000.
Outer 32.1183745553717 с; driver 30.987 с. Это Docker target, а не host3.13.7.

| Фаза | Секунды | Фактический результат ROOT |
|---|---:|---|
| verify-inputs | 0.950 | frozen artifacts/inputs и target приняты |
| clean-tooling | 9.059 | exact inventory8, offline hashes, pip check exit0 |
| http-ece-reuse | 0.131 | retained wheel/исторический receipt; rebuild отсутствует |
| target-resolution | 2.288 | 22 roots, три extras, точные 60 pin/hash |
| clean-offline-install | 18.537 | exact runtime60 + pip26.2.2 =61; pip check exit0 |
| cleanup | 0.001 | owned scratch удалён |

Десять command receipts имеют exit0; SHA и размеры каждого журнала сверены.
Все 27 retained output hashes и 198 input SHA/size независимо совпали с ROOT
receipts. Это проверка сохранённого evidence, а не новая проверка живого Docker.
ROOT cleanup-proof подтверждает удаление своего контейнера/образа и сохранение
существовавшего PostgreSQL. Worker Docker/SQL не вызывал.

COMPILER_TOOLING: pip26.2.2, pip-tools7.6.2, build1.3.0, click8.5.0,
packaging26.3, pyproject-hooks1.2.0, setuptools84.1.0, wheel0.46.2.
BUILD_TOOLING retained http-ece по-прежнему содержит setuptools80.9.0/wheel0.45.1;
новые compiler pins не приписаны старой сборке. Wheel SHA:
`a89e8aa1521d121dde75250524981f3f3fa3594cc1117da99904f2ba5ac24f9d`.

Три **новых provisional** файла опубликованы отдельно от трёх baseline locks.
Удалены все source/sandbox comments; effective requirement/hash lines полностью
равны соответствующему output ROOT, включая пробелы, продолжения и порядок.
Новых URL/finder/index/options нет; безопасный header явно говорит о кандидате.

| Новый lock | Pin | SHA-256 файла | SHA-256 effective lines |
|---|---:|---|---|
| `bootstrap-upgrade-20261030-py313-linux-amd64.provisional.txt` | 1 | `b41fd964893071eb489e01e85256f471764997721fe151eaf08684bfb12a87b8` | `f409e9c999da22f4920b4724c68adadb416a515f38d760dfd34ae6382d43df04` |
| `tooling-upgrade-20261030-py313-linux-amd64.provisional.txt` | 8 | `554fc211ee0ed4e88a2136029781308ac4d820b33ec60fcc242b88a556c33162` | `49add53ba85d34e3b6eaaf85069449b396291103fe5ffdf8ab6c50828d96d0e6` |
| `runtime-upgrade-20261030-py313-linux-amd64.provisional.txt` | 60 | `a9b060f941cda22fab721522eb68f717711c55f17dbbdc83fae169a8e0fbf2bc` | `d5df996891b7d0b13169c84602e6de3807074af1feff2865c1efd0f3b3179261` |

Контрольные SHA ROOT:

| Evidence | SHA-256 |
|---|---|
| root_summary_sha256 | `4da1b8a2058c0b3e4aa66636ebe399fa9d0aa677daacd7040bffbb5f938998ca` |
| input_proof_sha256 | `cbc72d15e62394bd42ea1e13684d35c4a55cab5a5c6b34059a9a8a2b7bae3d46` |
| cleanup_proof_sha256 | `54e5cbb6a0738aff37b126ee2ed1f02453e3f83237fe2687c40a92143dac50a8` |
| output/result.json | `93b0ce68480c2f7887935f9dee49ee104c7563e8cca0d13bf2560dfe45495d60` |
| source runtime output | `a291ec5f7c27182b6bb3bf2dc4c8f903d61bd3193ee8fb896ea8effba712d5c6` |
| driver tooling-v3 | `0a3b207319bdc94c9c1f77007e762abdc6cb3661a5e2febba70f33168842663b` |
| prospective artifact manifest | `8711de6afb6bc461718851a537c2456ea9b1f68b2f4236f3de599df561493b7f` |

Полные receipts и read-only verification report остаются private у ROOT/worker.
Старые failure/provenance, прежние locks и evidence не изменены и не заменены.
Исторический отчёт [подготовки](BACKEND_UPGRADE_ARTIFACTS_20261030.md) сохранён:
его NOT RUN относится к worker preparation, этот документ добавляет actual ROOT
resolver/install result. Source requirements, Dockerfile/Compose/features/CI,
приложение, старые tests и рабочие данные не изменены.

Не доказаны functional compatibility, JWT/multipart/PDF поведение, startup/SQL,
независимый rebuild, безопасность/OSV нового test tooling, production и release.
Отсутствие совпадений прежнего OSV query66 не означает security certification.
Следующий этап: отдельный ROOT review runner/proposal, новый изолированный host
candidate Python3.13.7/runtime60+pip и dedicated test DB; до решения ROOT
app/import/pytest/runner/SQL/env/install запрещены. Никакого merge/deploy.
