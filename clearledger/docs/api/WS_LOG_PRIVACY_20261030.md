# Приватность WebSocket handshake-журнала Uvicorn, 30.10.2026

Результат: исправлен локально воспроизведённый путь записи query authority в
стандартные handshake-сообщения `uvicorn.error`. Синтетический baseline показал
маркер в журнале; кандидат убрал его, сохранив клиентский адрес, путь и статус.
Фактическая утечка на production этим исследованием не установлена. Выпуска не было.

## Источник и граница исправления

- `server/requirements.txt:2` закрепляет `uvicorn[standard]==0.34.0`.
- `server/app/routers/chat_router.py:3296` принимает `token` из query; `_ws_user`
  проверяет этот токен как JWT пользовательской сессии. В тестах этот код не вызывается.
- `server/app/main.py:135` импортирует существующий установщик фильтра и вызывает
  его при сборке приложения. Изменение точки установки не требуется.
- Исходники установленного Uvicorn 0.34.0 подтверждают, что `websockets_impl.py`
  и `wsproto_impl.py` передают `get_path_with_query_string(self.scope)` в
  `self.logger.info`, где logger имеет имя `uvicorn.error`.
- До исправления `install_oauth_access_filters()` устанавливал фильтр только на
  `uvicorn.access` и `gunicorn.access`; его tuple-ветка рассчитана на пять HTTP-аргументов.

Подтверждённые форматы обоих backend:

| ASGI-событие | Точный шаблон | Аргументы | Строки websockets / wsproto |
|---|---|---|---|
| `websocket.accept` | `%s - "WebSocket %s" [accepted]` | client, URL | 273 / 260 |
| `websocket.close` до handshake | `%s - "WebSocket %s" 403` | client, URL | 291 / 283 |
| `websocket.http.response.start` | `%s - "WebSocket %s" %d` | client, URL, status | 302 / 301 |

Исправление в `server/app/api_access_logging.py` добавляет установку фильтра на
`uvicorn.error` и отдельную ветку только для этих точных шаблонов и числа аргументов.
Она применяет прежний `safe_target()` ко второму аргументу. Если URL содержит уже
распознаваемый authority-параметр, query удаляется целиком; путь остаётся.
Обычные query без authority сохраняются. Произвольные сообщения, exception-текст,
mapping-записи и HTTP-подобные пятиаргументные ошибки `uvicorn.error` проходят без изменений.

HTTP/Gunicorn-ветки, набор распознаваемых ключей и публичные имена функций сохранены.
Проверены Gunicorn `SafeAtoms`, регистр custom-header ключей, escaping, missing atoms,
сохранность исходного mapping и идемпотентная установка на все три логгера.
nginx, маршруты, аутентификация, зависимости и lock-файлы не изменялись.

## Воспроизведение и проверки

Окружение: `/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`,
Python 3.13.7, Uvicorn 0.34.0, websockets 17.3, Gunicorn 23.0.0, pytest 9.2.0.
`wsproto` отсутствует и не устанавливался.

SHA-256 проверенных файлов установленного Uvicorn:

```text
websockets_impl.py d32e2493ecd1fae3dd9a98eaf4e62ecc993b83d6a6962b2952633dd65caa45d6
wsproto_impl.py    81af09cc3514d90ad0b2381076022295f6e604722b1f8cdbc8633899aa2f4d1a
```

Из корня репозитория:

```bash
PYTHONPATH="$PWD/clearledger/server" \
  /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -m pytest \
  --noconftest clearledger/server/tests/test_api_access_logging.py \
  clearledger/server/tests/test_api_ws_logging_wire.py -q
git diff --check
```

Итог: **15 PASS, 2 SKIP**, `git diff --check` PASS. Из них 13 pure-проверок,
включая пять существовавших; две actualwire-проверки — baseline и candidate для
websockets. Два SKIP — baseline/candidate actualwire для отсутствующего wsproto.
Проверка синтаксиса трёх Python-файлов через `compile()` также PASS.

До изменения production-модуля этот же wire-тест дал **6 PASS, 1 FAIL, 2 SKIP**:
baseline PASS, candidate FAIL из-за видимого маркера в handshake-журнале.
После изменения candidate PASS. Baseline внутри теста по-прежнему воспроизводит
прежнюю установку только HTTP-фильтров и подтверждает присутствие маркера.

`server/tests/test_api_ws_logging_wire.py` запускает отдельный Uvicorn с минимальным
ASGI callable. Только localhost, заранее связанный ephemeral socket, синтетический
маркер `SYNTHETIC_WS_AUTHORITY_20261030`. Проверяется фактический ответ и запись лога:

| Запрос | Ответ | Baseline | Candidate |
|---|---|---|---|
| WS `/accepted?token=<marker>` | 101 | marker в handshake | путь без query |
| WS `/refused?token=<marker>` | 403 | marker в handshake | путь без query |
| WS `/denied?access_token=<marker>` | 401 | marker в handshake | путь без query |
| WS `/ordinary-ws?q=charger&page=2` | 101 | query сохранён | query сохранён |
| HTTP `/ordinary-http?token=<marker>` | 200 | query очищен | query очищен |
| HTTP `/ordinary-http?q=charger&page=2` | 200 | query сохранён | query сохранён |

В candidate отсутствие sentinel проверяется во всём захваченном журнале локального
процесса при уровне INFO. Сокеты закрываются контекстными менеджерами, дочерний
процесс останавливается в `finally`, ожидается его завершение; при превышении
таймаута применяется kill с обязательным wait. Проверяется завершённый graceful
shutdown. Uvicorn 0.34 повторно поднимает пойманный SIGTERM после shutdown, поэтому
код `-SIGTERM` допустим вместе с записью `Finished server process`.
Окружение дочернего процесса содержит только абсолютный PYTHONPATH и запрет pycache.

`server/tests/test_api_access_logging.py` извлекает AST обоих установленных backend,
проверяет logger, три шаблона, расположение URL/client аргументов и создаёт реальные
`logging.LogRecord` из найденных шаблонов. Проверяются token, ACCESS_TOKEN и обычный
query; client/status сохраняются. Это статическая проверка формата wsproto с
исполнением фильтра, не сетевой прогон wsproto.

## Review и ограничения

Самостоятельный review проверил прямой вызов установщика, оба исходных backend и
все ветки фильтра: общий обработчик URL переиспользован, список форматов закрытый,
изменение args ограничено URL, остальные ошибки возвращаются до HTTP/Gunicorn-веток.
Проверка отрицательных примеров включает custom-шаблон, готовую строку, mapping,
обычный error с двумя/пятью аргументами, exception info, другое имя логгера и
несовпадающую арность. Дополнительные workers не запускались по условию задачи.

Проверка не импортирует `app.main`, не создаёт CoreJWT, не использует пользователя,
БД, SQL, VM, рабочий API, verifier, секреты или файлы `.env`. Общий server conftest
отключён через `--noconftest`. Полный backend CI с БД не запускался.

Гарантия ограничена известными стандартными handshake-форматами Uvicorn 0.34.0
при вызове установщика. Произвольные error/debug/custom-журналы, другие версии
Uvicorn, дополнительные кодировки query-ключей и журналы других компонентов не
проверены и этой правкой не объявляются безопасными. wsproto actualwire остаётся
непроверенным до отдельного прогона в окружении с этим backend.

База работы: `e912a5ad`; ветка `MagLook/marakihau` в выделенном worktree.
`git pull --ff-only` сообщил об отсутствии upstream; выполнен `git fetch origin`,
база не переключалась и не смешивалась с другой линией. Дальнейшая интеграция,
PR, merge и выпуск остаются у координатора и человека.
