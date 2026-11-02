# Извлечение document access policy: первая волна M04/M07

29.10.2026. Основа: `5ce5779b`, ветка `refactor/doc-access-policy-20261029`.
Это кандидат для интеграции, без PR, мержа и выпуска. Координатор отдельно
сообщил результат M00: 454 Python-файла работающего Core совпали с этой основой;
исполнитель policy не обращался к стендам и не читал рабочие секреты.

## Состав

В `server/app/services/doc_access.py` перенесены 20 функций и две константы
из `routers/docs_router.py`, без изменения тел, сигнатур и ошибок:

- `_visible`, `_access_rows`, `_subject_ids`, `_matches_subject`, `_denied`;
- `_active_break_glass`, `_action_policy_allows`, `_can_doc`,
  `_assert_doc_permission`, `_can_manage_doc_access`, `_assert_manage_doc_access`;
- `_can_process_inbox`, `_assert_process_inbox`, `_available_actions`;
- `_readable_docs`, `_readable_doc_clause`, `_archiveable_doc_clause`;
- `_docs_members`, `authorize_docs_file_download`, `authorize_docs_file_egress`;
- `_CONTENT_PERMISSIONS`, `_BREAK_GLASS_PERMISSIONS`.

Замыкание использует модели, `doc_approvals`, `log_audit`,
`resolve_member_modules` и `not_service`. HTTP-роутер импортирует и совместимо
переэкспортирует прежние имена; отдельной копии правил или forwarding wrappers нет.
Карточки, редакции и исходные файлы не объединялись. Writer, DTO, команды,
транзакции, схемы и authentication/scope не менялись.

`space_documents`, `process_documents`, `work_links`, `acquaint_requests` и
`ezs_tp_method` импортируют policy из сервиса. В `acquaint_requests` соседний
импорт `_acquaint_snapshot` заменён прямым импортом существующего владельца
`doc_approvals._document_snapshot`: прежний router helper только делегировал ему.

Проверенный контекст компании по-прежнему обязан передать вызывающий код.
`_readable_doc_clause` дополняет tenant-фильтр выборки, не заменяет его.
При break-glass сохраняются счётчик использования и аудит в текущей транзакции;
policy не делает commit. Прямое скачивание требует `download`, egress — `send`;
сохраняются tombstone/purge/retention gates, обработка входящих и 404 без раскрытия
содержимого. Файлы без связи с документооборотом остаются вне этого guard.

## Доказательство parity

AST исходного `docs_router.py` получен через `git show 5ce5779b:…` и сравнен
с кандидатом Python 3.13: все 20 перенесённых и 124 оставшихся функции совпадают,
множество функций не изменилось. Совпадают также все остальные top-level runtime
выражения и классы router после исключения перемещённых определений и импортов.
Значения двух констант сохранены. Это проверяет перенос, включая действия и поля
HTTP handlers, независимо от выбранных интеграционных сценариев.

В свежем интерпретаторе импортированы все шесть сервисов (новый policy и пять
потребителей): в `sys.modules` отсутствуют `app.routers*` и `app.main`.
Постоянные тесты проверяют направление импортов и тождество совместимых exports
реальным функциям policy.

## Проверки

Перед прогонами прочитан `tests/conftest.py`: он удаляет схемы `public`/`edge`.
Использована только выделенная локальная PostgreSQL координатора:
контейнер `api-modernization-test-20261029`, `127.0.0.1:33546`, база
`api_doc_policy_test`. Каждый DB-прогон получил явный `TEST_DATABASE_URL`.
Файлы создавались только в отдельных `.artifacts/baseline-test-uploads` и
`.artifacts/test-uploads`. Рабочие конфигурации и хранилища не использовались.
Python 3.13.7 — готовое изолированное окружение координатора; зависимости не менялись.

| Проверка | Результат |
|---|---|
| Исходная основа `5ce5779b`, 14 существующих целевых модулей | 138 PASS, 58.85 с |
| Кандидат, те же модули + новый `test_doc_access_policy.py` | 222 PASS, 59.62 с |
| Новый policy-набор отдельно, `--noconftest`, без БД | 84 PASS |
| AST parity и fresh imports | PASS |
| `git diff --check` | PASS |

В обоих DB-прогонах одинаковые две исходные `SAWarning`: archive-flow cleanup
пытается удалить уже удалённые строки `doc_exports` и `doc_versions`.
Новых ошибок или пропусков нет; это целевые проверки, не полный CI.

14 существующих модулей: `test_docs_register`, `test_docs_next`,
`test_docs_reports`, `test_docs_archive_security`, `test_docs_archive_flow`,
`test_docs_archive_queue`, `test_docs_editing_unit`, `test_doc_workflow_unit`,
`test_doc_note_in_force`, `test_approval_requests`, `test_external_approval`,
`test_contract_doc_replay`, `test_profile_security`, `test_doc_text`.
Основа проверена отдельной копией `app`/`tests` в `.artifacts/baseline-server`
с исходными файлами из Git; затем кандидат — из `clearledger/server`.
Локальные логи: `.artifacts/baseline-pytest.log`, `.artifacts/candidate-pytest.log`.

Новые тесты используют вымышленные UUID и mock DB: матрица действий/видимости,
deny-read для user/role/department поверх owner/admin/grant, ограничения retention
и strict/break-glass, аудит использования и read-only probe, права principal/deputy
при подписи, точные ошибки 403/404, отдельные download/send, закрытые редакции без
fallback во входящие, разрешение обработки входящих, egress каждого вложения и
блокировка карточек, модули участников, tenant-bindings и kind inheritance в SQL.

Повторный запуск нового набора из `clearledger/server`, с явно установленными
синтетическими `DATABASE_URL`, `SECRET_KEY` и отдельным `UPLOAD_DIR`:

```sh
PYTHONPATH="$PWD" /srv/projects/api-modernization-test-env-20261029/.venv/bin/python \
  -m pytest --noconftest -q tests/test_doc_access_policy.py
```

Для DB-набора обязательно задать выделенную `TEST_DATABASE_URL` и убрать
`--noconftest`; без неё запускать существующий conftest нельзя.

## Осталось за границей первой волны

Обратные импорты policies задач/чата в `work_links` остаются отдельной работой
M04. Сохранённые router exports позволяют переводить другие HTTP-адаптеры позднее.
Объединение writer, rollback cleanup и прочие пакеты M07 не выполнялись.
Полная программа M04/M07, интеграция, независимая приёмка и выпуск не завершены
этой правкой; их координирует основной исполнитель.
