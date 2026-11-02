# Partner DX: доказательство по исходникам, 31.10.2026

Статус: **SOURCE_ONLY**, runtime-приёмка **NOTRUN**. База: `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`.
Изменены только Field descriptions/examples и documentation metadata 15 существующих GET.
14 JSON 200 имеют полные вымышленные примеры; download описывает 15 ASCII bytes
`Fictional file` + LF, application/octet-stream и пример заголовков без JSON body.

AST-сравнение сохраняет все аннотации, aliases, required/nullable/default, min/max,
regex, validators, operation IDs, paths, response_model, schemas, response headers,
principals, scopes, grants, tenant/file policy, обработчики и общий operation helper.
Нормализуются только конкретные Field description/examples и summary/description,
200.description и 200.content.application/json.examples конкретных операций.
Остальные ключи responses/kwargs не исключаются из сравнения. Required AnnAssign
без default отличается от default=None. Всё вне whitelist совпадает по AST;
защищённые product_api/api_contracts исходники совпадают побайтно.

Новые тесты проверяют сохранение runtime/wire/policy по базе, отрицательные мутации
normalizer, будущую валидацию полных examples действительными DTO и OpenAPI schemas,
required-nullable поля, типы, ограничения ID и provenance. Тесты **WRITTEN_NOTRUN**;
pytest и collection не запускались. Выполнены только stdlib source checker,
AST/literal/hash-анализ и in-memory compile без исполнения компилированного кода.

Точные SHA-256 новых/изменённых Python-файлов, base source SHA, whitelist locations,
15 operation IDs/правила principals и hashes protected sources: соседний JSON.
Сами proof-файлы исключены из рекурсивного hash manifest; их фиксирует Git commit.

Повторить source proof в собственной ветке: `python3
clearledger/scripts/verify_partner_dx_metadata_20261031.py --write-proof`.
По умолчанию отдельно проверяются ровно семь разрешённых путей всей дельты к базе.
В общей ветке `--scope metadata` сохраняет AST/hash-проверку runtime и сообщает
`NOT_CHECKED_INTEGRATED_PACKAGE`; точный общий состав отдельно проверяет координатор.
Тесты нормализации вызывают AST proof отдельно от проверки состава пакета.

Все 20M и 11 gates остаются unproven вне этого пакета. Приложение, helpers и
frameworks не импортировались; OpenAPI exporter/types/Node/codegen, HTTP/SQL,
Docker/SSH/browser, pilots/deps/flags/workflows/billing/deploy не запускались.
Публикация, push, PR и merge не выполнялись. Примеры вымышлены и не доказывают
доступность API, файлов, прав или какой-либо рабочей среды.
