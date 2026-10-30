# Проверка безопасности API contracts, 30.10.2026

Это краткая сводка завершённого Standard Codex Security scan, а не замена автоматически сформированного canonical report.

## Объём и результат

Проверена неизменная ревизия `310b31afb263d0ece311094f32e13a8b0cf0383e` в отдельном Orca worktree `api-contracts-security-review-20261030`.
Scope: только `clearledger/server/app/api_contracts`.

| Показатель | Результат |
|---|---|
| Полностью проверенные файлы | `__init__.py`, `context.py`, `routing.py`: 3 из 3, 472 строки |
| Canonical status / coverage | `complete` / `complete` в указанном scope |
| Подтверждённые findings | 0: critical 0, high 0, medium 0, low 0 |
| Отложенная работа внутри scope | Нет |
| Метод | Чтение текущих исходников, трассировка вызовов, проверка counterevidence и SHA256 |
| Preflight | `ready`, без изменения конфигурации; последовательный fallback |

## Выводы по исходникам

- `context.py:30–74,121–167`: пустые и неинициализированные разрешения закрывают доступ; пересечение ограничивает scopes, ресурсы и поля. Для пересечения контекстов должны совпадать principal, company и версия политики. Отсутствующее разрешение не становится `ALL`.
- `routing.py:88–111,138–167`: до обработчика вызываются серверный resolver и guard. Проверяются валидность контекста, версия политики, вид principal, наличие компании, scopes, разрешение ресурса и обязательные поля.
- `routing.py:145–163`: переданный tenant selector должен совпасть с компанией контекста; resource selector проверяется на непустой `SET`, принадлежность всех идентификаторов и последующее сужение контекста.
- Наличие необязательных selectors само по себе не доказывает IDOR. В текущем потребителе `product_api/app.py:128–201` они не передаются, а `product_api/queries.py:67–98,160–168` добавляет условия компании, ресурсных grants, объектов и организации до list/detail. Это supporting trace, а не полная проверка этих файлов.
- `routing.py:114–135,170–291`: политики связаны с метаданными; неподписанные контрактом маршруты, callbacks и неподдерживаемые native HTTP/WebSocket routes отвергаются. Registry проверяет mount, циклы и дубли. Основа отключает HTTP Swagger/ReDoc/OpenAPI URLs.
- Contracts не выпускает credentials и не реализует Code/PKCE/consent/refresh/revoke. Эти механизмы принадлежат supporting identity-коду. В scope не найдено встроенных credentials/private keys или подтверждённого пути от входа атакующего к опасному sink.

## Границы вывода

Независимого baseline-подагента и независимого architecture-подагента не было: вложенная делегация запрещена заданием, проверка выполнена последовательно. Отсутствие findings не является сертификатом всего API и не разрешает исправления, merge или release.

Contracts принимает факты от доверенного resolver. Проверка credentials, company/client/installation binding и live grants, SQL/object/org ACL, проекция полей и документные разрешения остаются обязанностями вызывающего кода. Supporting `product_api`, identity, auth, config и main читались только для трассировки; legacy endpoints, учётные записи, файловая выдача документов и публикация Swagger полностью не проверены.

В исходниках подтверждены 12 curated GET и независимые default-off флаги OAuth/API/docs (`product_api/app.py:128–201`, `config.py:52–78`). Фактическая активация в production не проверялась. Приложение и тесты не запускались; реальные API, БД, токены, секретные конфигурации, SSH и браузер не использовались. Git history и другие ревизии не анализировались. SHA256 всех трёх файлов и HEAD сверены перед завершением.

## Canonical reference

- Scan ID: `95377b0c-3f7a-4e36-b1f7-1d7cba6150d7`.
- Canonical completion: `2026-10-30T04:22:45.011295Z`; `complete_codex_security_scan` успешно выполнен один раз.
- Generated report: `/home/mag/.codex/state/plugins/codex-security/scans/api-contracts-security-review-20261030/310b31afb263d0ece311094f32e13a8b0cf0383e_20261030T041849Z_5dq7gsmm/report.md`.
- В том же canonical наборе сохранены `scan-manifest.json`, `findings.json`, `coverage.json` и `threatmodel.md`; доступ к ним только штатными Codex Security tools. Эта сводка не копирует защищённые артефакты и не содержит секретных значений.
- Инструмент сообщил usage `1 371 483` tokens, включая `1 292 288` cached input tokens; источник `codex_rollout`, coverage `complete`, один thread.

Daybreak advisory вернул `not_granted`: отображение защищённых результатов может требовать отдельного доступа. Другие credential-каналы не использовались.
