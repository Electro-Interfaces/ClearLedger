# M16: actual backend image packaging proof, 30.10.2026

**ROOT: BUILD / ARCHIVE / LOAD / ACTUAL IMAGE PROBE / CLEANUP — PASS.**
Один candidate build исходного Dockerfile завершился exit0 за144.035000198s;
actual image probe — exit0 за13.642142142s. Автор выполнил только filesystem/Git,
AST/compile и разрешённые readonly Docker CLI; все Docker mutations и исполнение
приложения выполнял исключительно ROOT после source review и staged approval.
Повторов после PASS не было. Это локальный packaging/import proof; M16 целиком,
M00–M19 и production release остаются открытыми.

## Immutable source и неизменённый рецепт

Прежние clean HEAD=origin совпадали с
`4a963a5cfe1e7f123446226d918783a875377dd8`.
Own ветка `agent/api-backend-image-packaging-20261030` создана в прежнем isolated
worktree от exact integration
`88fdef78bab8c8ced97b29d6d24c2a47c472799a`.
Pull/new worktrees/shared-branch changes не выполнялись. В Git изменён только
этот новый отчёт; runtime/tests/Dockerfile/requirements/Compose/skills не менялись.

Прочитаны проектные CLAUDE и elsy-deploy SKILL.md, references/stacks.md/pitfalls.md.
User явно выделил локальную доказательную сборку: ship/build-image/release/
provision/SSH/VM/Compose/version workflow этого навыка не использовался.

| Source input | Count / bytes | SHA256 |
|---|---|---|
| app | 489 / 17114637 | 8e002e545929bc08c6034818c1921a828092dc48195074e8e5ea101796cb8236 |
| schema_migrations | 16 / 66799 | c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e |
| Dockerfile | unchanged | aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d |
| requirements.txt | 23 lines | f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0 |
| .dockerignore | unchanged | 219f4861afde083e955dccd850e20ac3f86a4d3b51164c484e7fca1620490d6a |

Context подготовлен Git archive **из корня репозитория**, не из server/clearledger
subdirectory. Shape команды, с условными private destination/root:

```text
git -C <repo-root> archive --format=tar --output=<private-context.tar> 88fdef78bab8c8ced97b29d6d24c2a47c472799a:clearledger/server Dockerfile requirements.txt .dockerignore app schema_migrations
```

Только реальные входы COPY:508 tracked files,17183940 bytes; regular files/directories,
без traversal/symlinks/hardlinks/.env/uploads/pycache/pyc/чужого WIP. Original
.dockerignore применялся без изменения. Root независимо проверил Git blob parity
каждого файла. Context tree SHA256
`980d4bba70dbc3f83e7e12922aa079ada9e83a4496ba476403a4375883110e04`;
context tar17592320 bytes SHA256
`8d6dec21a7ead462fb1dc9b31fb8d45131efb05da09d9e757a3c68b5bd1e7f4d`;
manifest SHA256 `371c7c3b73813cd66cf2f76f4c7611a7333b5eebeee386c674aa037be1418fea`.

Сборка использовала настоящий неизменённый FROM python:3.13-slim, реальные apt
build-essential/curl/ffmpeg и pip upgrade/install, затем COPY app + schema_migrations.
Не использовались подставной Dockerfile, copied-layout/host venv или пропуск deps.
Dockerfile/ignore pins относятся к контексту и рецепту; эти файлы не добавлялись
в image через дополнительные COPY. Requirements внутри image также hash-совпали.

Buildx incidental `vcs:revision=cadd246ab9828e770abaf1f506376f40b2e11d71`
относится к host checkout вокруг private context, **не** к источнику app bytes.
Источник88fdef78 доказан Git blob parity/context manifest и actual image file
hashes; image label api-modernization.source также равен88fdef78.

## Preflight, подготовительные наблюдения и actual builder

Readonly checkpoint: Buildxv0.36.1, cached host python:3.13-slim/amd64 ID
`sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`.
image ls178MB и inspect Size43078356 bytes — отдельные измерения.
Свободно22482374656 bytes, filesystem94% used. Перед mutations ROOT повторил
fresh names/tag/ownership/storage checks. Local Unix daemon, fresh private
DOCKER_CONFIG, без working env, credentials и secret/SSH mounts.

До candidate build были два отдельно сохранённых setup наблюдения:

- readonly manifest request к публичному mirror отказал при TLS validation;
  official public registry request прошёл с обычной проверкой TLS;
- helper lookup по config digest27933730... вернул No such image; ROOT перешёл
  к правильному manifest-addressed image reference. Это произошло **до** создания
  candidate build, не является провалом backend recipe или его повтором.

TLS не отключался; host Docker/network/DNS/proxy/firewall/registry credentials
не изменялись. Private mirror override ради успеха не добавлялся.
Setup receipts сохранены отдельно, в public report нет их raw logs.

ROOT создал отдельный docker-container builder
`api-backend-image-20261030-f347`, node `api-backend-image-20261030-f3470`,
BuildKitv0.33.1. Helper pinned:
`moby/buildkit@sha256:98cc6a3fc46220d00f8224ae483f3274fc874e9be8d7dd1e2e2c5481209228b5`.
Стандартный owned BuildKit container был privileged; он не являлся runtime probe.
Actual cgroups подтверждены до build: memory.max4294967296,
memory.swap.max0, cpu.max200000/100000. State volume — hard tmpfs2147483648 bytes,
не общий cache. Сам build также передал --resource memory=4g/cpu-period=100000/
cpu-quota=200000; host networking/extra entitlements не запрашивались build argv.

## Staged execution и storage accounting

ROOT сначала разрешил только build/export. Фактически использовался buildx build
с owned builder, linux/amd64, исходным context/Dockerfile, --progress=plain,
--provenance=false, --sbom=false, synthetic proof/source labels, --iidfile,
--metadata-file и --output type=docker,dest=<private archive>.
Tag: `api-modernization-backend-proof:20261030`; vNN/elsyplus tags не использовались.

| Этап | Actual result | Elapsed, seconds |
|---|---|---|
| Original Dockerfile build/export | exit0, client reaped | 144.0350001975894 |
| Archive/layer integrity and allocation accounting | ok=True, до load | 10.890926593914628 |
| Separately approved load | exit0, client reaped | 25.518849790096283 |
| Actual image sandbox probe | exit0, client reaped | 13.642142142169178 |
| Ownership cleanup + independent check | PASS | не SLO |

Archive370388992 bytes; expanded layers1051445760 bytes; outer members17.
SHA256 `f84238ef4582fa84ba451a949303c9147b232376407793c95f79282818f64a46`.
Conservative peak model4061597184 bytes <4GiB4294967296; только после проверки
целостности и этого accounting ROOT отдельно разрешил load.

Build/load fresh free precondition>=20GiB, universal reserve>=16GiB и own
additional-disk guard<=4GiB; build deadline900s, log<=16MiB, exported-file hard
RLIMIT_FSIZE1GiB. State hard quota2GiB — tmpfs. Watchdog/capacity model не
объявляется hard quota всего Docker filesystem или воспроизводимым storage SLO.
Перед image load ROOT остановил/удалил только own builder/cache/state/helper.

После уже проверенного load ROOT отдельно принял probe free precondition17GiB:
probe read-only, tmpfs64MiB и output<=1MiB; reserve16GiB сохранился. Это не прежний
20GiB build/load precondition. Actual free bytes: build start22049349632,
after export21676834816, after builder cleanup22039572480,
after load20578095104, after probe20577828864, final cleanup22039080960.

Cancellation был предусмотрен по точному owned container ID: stop/wait до
RunningFalse/Pid0, затем client terminate/kill/reap и удаление только own state.
Kill Docker CLI не выдавался за остановку daemon job. Shell=True, global prune,
daemon restart и удаление чужого cache/base не применялись. Timeout cancellation
в успешном candidate build не потребовался.

## Actual image identities и versions

| Identity | Actual value |
|---|---|
| Platform | linux/amd64 |
| Resolved FROM material digest | sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb |
| Loaded image / OCI manifest ID | sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51 |
| Image config digest | sha256:c6f6c19482fb4af69cd7e3b2a38fe2d358447cc38be5348de2c14142007655e0 |
| Local RepoDigest | api-modernization-backend-proof@sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51 |

Cached host image ID и фактически resolved FROM material — разные identities;
не заявляется сборка из предварительного cached ID. Root не менял FROM ради
успеха. Local RepoDigest не означает push/publication: registry push не выполнялся.
Loaded image config/history подтвердили исходные COPY/apt/pip/CMD; CMD gunicorn
не запускался.

Actual Python3.13.18; установлено60 distributions. Ключевые metadata versions:
FastAPI0.115.6, SQLAlchemy2.0.36, asyncpg0.30.0, Authlib1.9.1, joserfc1.7.7,
PyJWT2.10.1, pydantic2.14.2, pydantic-settings2.7.1, uvicorn0.34.0, gunicorn23.0.0,
cryptography50.0.2, pip26.2.2. Полный inventory сохранён private.
Floating base tag, pip upgrade и >=/transitive dependencies не закреплены lock;
это измерение конкретной сборки, не обещание bit-reproducible release или future
dependency compatibility. Requirements/locks ради этого proof не менялись.

## Sandbox import, frozen runner и default-OFF

Actual probe container использовал exact loaded image ID, entrypoint python
с args -I -B -, stdin pinned probe SHA256
`79037458a3abfbad4522e949c22d9b21e2739c0719df611b653a21870bd2934d`.
Никаких host volumes, Docker socket, рабочих uploads/env/keys не монтировалось.

Root inspect подтвердил NetworkMode=none, ReadonlyRootfs=True, CapDrop=ALL,
no-new-privileges, Privileged=False, user65534:65534, memory1GiB/no extra swap,
CPU1, PidsLimit128, tmpfs /tmp64MiB noexec/nosuid, Mounts=[], Ports={}.
Probe deadline60s, stdout/stderr budget1MiB; actual output2939 bytes.

Предложение показывало --env NAME; фактический запуск передал **явные synthetic
--env NAME=VALUE**, не наследовал значения host по одним именам. APP_ENV=test,
UPLOAD_DIR=/tmp/backend-image-proof-test-uploads, PYTHONDONTWRITEBYTECODE=1;
DATABASE_URL — фиксированный fake loopback DSN на127.0.0.1:1/api_backend_image_test,
SECRET_KEY — отдельный fixed synthetic test literal. Секретоподобные значения
и raw env здесь не публикуются. Feature flag ENV overrides отсутствовали.

В actual image подтверждены exact489 app/16 package files и requirements bytes;
все четыре runtime modules main/database/config/schema_version_gate загружены
из image. Source defaults и actual settings **False** для:

- managed_core_budget_enabled;
- partner_oauth_enabled;
- partner_api_enabled;
- partner_api_budget_enabled;
- partner_docs_enabled.

Frozen manifest/load и настоящий runner module CLI entrypoint исполнились offline
через runpy.run_module(..., run_name=__main__) с argv plan в том же actual Python.
До app import plan не импортировал app/asyncpg и не подключался к БД. Receipt:
foundation_only=True, namespace=core, revision0001_product_api_budgets,
artifact SHA256 `301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1`.
Поддержанный CLI — python -m schema_migrations.runner plan; у frozen16 нет
schema_migrations/__main__.py. Package-level shorthand не выдаётся за
существующий entrypoint, shim в runtime не добавлялся.

Connect/DNS/bind/sendto/driver connect+pool/subprocess/exec/fork/thread/task
attempts блокировались probe; actual attempts0, Python threads1. Lifespan и SQL
не исполнялись. Network-none/read-only дополняли эти guards; это не security
sandbox certification или runtime health acceptance.

## Docs assets: actual local reads

После actual app import существующий filesystem-only docs_portal.asset прочитал
четыре shipped assets без HTTP/login/DB. Manifest также сверён с Git source.

| Asset | Bytes | SHA256 |
|---|---|---|
| swagger-ui-bundle.js | 1684244 | 3f6abf70480db7e07914df4c98a77385f22ea585eaf457a3e6415ba0eae2d167 |
| swagger-ui.css | 187576 | c3cfe8248c4b0b89673600fb829924eafbac6de4bc4b2b06f5f5243483074d0a |
| portal-init.js | 9413 | d54e100b61c90be459a00bb280a72a1faf5ecf19d15b71b4b70a71904ba1680a |
| oauth-callback.js | 1464 | 507619812458967c2719488e4e773d93bc3392fe48e0b8f7869497ee77fa9624 |

Asset manifest SHA256
`dda3abb12efbec2fc092565bd5a957920e7c9dc74bcf39ae3c1a997ea9d9e212`.
Swagger-ui-dist5.34.0 remains source-pinned; no npm/browser/CDN fetch performed.
Docs/OAuth/API flags остались False; это не portal-login/OAuth flow acceptance.

## Exact owned resources и cleanup

| Resource | Created identity | Final state |
|---|---|---|
| Builder | api-backend-image-20261030-f347 | removed |
| Builder container | e872b9bb75ab6ca2803485cad149b7f799627a8db40981b0dfc3352c9ce1d305 | stopped Pid0, removed |
| tmpfs state volume | buildx_buildkit_api-backend-image-20261030-f3470_state | removed |
| Newly fetched helper image/reference | moby/buildkit@sha256:98cc6a3fc46220d00f8224ae483f3274fc874e9be8d7dd1e2e2c5481209228b5 | removed |
| Probe container | 47c3c7361512c53f33f4d277ddf7f2c705ab1709c5b90b002b36800ceb3dece8 | exit0/Pid0, removed |
| Candidate image/tag | sha256:812e423c722ae3cbac7780e4d8bd1ac54387b27c013c33f89c9c1fdefb7cae51 / api-modernization-backend-proof:20261030 | absent |

ROOT independently confirmed0own running containers/build jobs, absent own
builder container/state/helper/candidate/probe. Cached host Python remained the
same70729b46... ID; pre-existing synthetic PostgreSQL container remained running.
No test DB/SQL/restore was needed or executed. No force deletion/global prune/
other images/cache/daemon/network/proxy changes. Private bounded archive/context/
proof/logs retained with hashes; none copied into Git/preview.

## Durable evidence hashes и границы

ROOT final summary:68f0231bed370837a1489b1be85b9e452d45ffce2d7e4d9be7d5f4503bdb1a10.
Автор после root result прочитал только filesystem JSON/hashes; actual commands
не повторял. Private artifacts доступны координатору; здесь только safe hashes:

| Artifact | SHA256 |
|---|---|
| context-proof.json | 1ca4a1c9fcc46e1e30f1b897222dc5232597c5fd76514100e57f96229c0cad85 |
| builder-proof.json | 0cdd086fd27d3583ade4b84dc972faad58fab6f22cb130fc7fb501ce1a12366c |
| build-result.json | 9f4804121892e7cd210972dbaf650918e0e5f42e0c946696b0a7303aefd0c6c4 |
| build.log (137167 bytes) | 399e48014a32c8e768b50fa3ba69fc6d65eef69391f349e2308e045e82e9b58c |
| build-metadata.json | 19b2c171dddac8167988d4f7841efc2f080e793d9fc3a33d27f40850af1e21e2 |
| archive-proof.json | 9f6a32ce90a2735bb82c38ff128c9c87bae05b1b39f7f81bf7fcb6c1666d20af |
| builder-cleanup.json | a9307c6e48b20b77063e8a139b38315d1408fd4aa16da1cb2b385d52245f8a4c |
| load-result.json | c7a0d31f8df27e561d021d6eb72ecd0d88776feed494d529c9842a09b77ab729 |
| loaded-image-proof.json | c10c0b7f4409f4d901c9b767e2add64362b92a2797e62515b8337fef5b16b3d5 |
| probe-container-proof.json | 6c9f9ea3d26e55f12681157a7c9437c7fcc4440ef2e25c1257888d743f4f4098 |
| probe-result.json | 7151c49a57d34344a4b50972878155d067406114ebf195ca33abac6a60120ea2 |
| probe.log (2939 bytes) | 8dcb709de4c523b860dcdde596af45693f541ea9910afd21a6f683928de43532 |
| image-cleanup.json | 1e42184f10c60925fa69954902374c5d71d8aa0e4fee6d1007f3b8ea5a762663 |
| cleanup-independent-proof.json | be232b05a8341c8aaa6f69c4cd31c211a72185a43514fe727ca540cc58d54739 |
| setup config-ID lookup receipt | f137f496ab881f86f8f30fed1d662500538d2bb6f46ee224720966b41042530a |

**NOT RUN:** gunicorn/CMD/full lifespan/background jobs, ASGI server/HTTP/E2E/
health/readiness/SQL/PG restore, старые binaries, full CI/TS/старые accepted suites,
production restore, release/version bump/registry push/merge/deploy и включение
feature flags. Наличие и импорт actual image не заменяют эти acceptance gates.
Программа M00–M19 и рабочая миграция не завершены.
