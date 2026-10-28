# Приёмка техприсоединения

Только синтетические данные, отдельная PostgreSQL `tp_test` на loopback.
Сервер использует настоящие роуты/сервисы и SQL, авторизация подменена тестовым
участником. Это проверка компонента и API, не входа в рабочее пространство.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tp_test:tp_test@127.0.0.1:54339/tp_test \
  PYTHONPATH=server python -m unittest discover -s server/tests -p test_tp_workflow_integration.py -v

TEST_DATABASE_URL=postgresql+asyncpg://tp_test:tp_test@127.0.0.1:54339/tp_test \
  python e2e/tech-connection/server.py
npx vite --config e2e/tech-connection/vite.config.ts
TP_ARTIFACTS=/absolute/path node e2e/tech-connection/check.cjs
```

Не запускать SQL-тесты одновременно с браузерной фикстурой: тест очищает свою
схему. После прогона остановить обе команды и удалить только выделенную тестовую
БД. Сценарий: условия и исполнители, сохранение/перезагрузка, комплект по
сценарию, замечания и срок, этапы ТУ, запрет преждевременного закрытия,
desktop/mobile, ошибки JavaScript.
