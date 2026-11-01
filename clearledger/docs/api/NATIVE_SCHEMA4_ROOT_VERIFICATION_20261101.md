# Учётные записи и физическая схема партнёрских договоров

## ROOT: учётные записи и физическая схема4 приняты в отдельных профилях · 2026-11-01 00:56 UTC

**138 PASS** для учётных записей и публичного принятия приглашений:
43 unit/source и95 PostgreSQL cases,46 функций,414 успешных фаз,0 ошибок и
пропусков. Независимое Source+RAW review принято. Реальны обработчики,
bcrypt/TOTP и AuditEvent; шесть синтетических таблиц сохраняют только выбранные
FK/defaults, non-PK nullable ослаблен, внешняя доставка подменена.

**Четыре отдельных сценария полной native Core оснастки прошли** и приняты
после независимого Source+RAW review. На каждой новой изолированной PostgreSQL
зарегистрирована341 модель; физических таблиц341 до перехода3→4 и347 после.
Проверены точные named sets,803 физических FK и включённые internal RI triggers,
полный SELECT колонок шести ORM моделей revision4. DTO даты договора прошёл
ещё4 unittest метода. Сценарии: переход3→4/check/repeat; tombstones после удаления
договора/пользователя; удаление разрешающих ссылок без потери истории;
сохранность истории после удаления профиля/grant/installation/app.

Исправлены exact host preflight и затенение типа Contract.date. Инвентаризация
оснастки расширена с337 на341 модель: учтены «На сегодня» и контекст поддержки
вне models*.py. Все прежние FAIL сохранены. Тестовый app состав строго535 файлов
из aaf472b8 с одним DTO overlay be49; это отдельная композиция, не весь поздний
Root HEAD. Все временные контейнеры удалены, остаточные PG clients/locks0/0;
безопасные проекции чужих контейнеров совпали до/после.

Прежние helper135, users/roles27 и body27 сохраняют свои границы. Все исходные
20 M00–M19 и11 требований сохранены. Original13groups/prefix0–2, old-binaries/
restore, StoreB PG, исправления native contracts/OneC и partner identity,
окончательный CREATE/receipt/admin/query/OpenAPI17/SDK, совместный CI и пилоты
ещё открыты. Общего процента нет. Рабочие миграции, flags, merge и выпуск
не выполнялись.

[Подробный отчёт](http://10.10.70.56:8000/api-platform-20261029/native-schema4.html).
Ниже сохранена история прежних срезов со своими границами.

| Отдельный сценарий | Результат | SQL-команд | Секунд |
|---|---|---:|---:|
| smoke-prefix3 | PASS | 6784 | 33.93 |
| current-fk-tombstones | PASS | 5538 | 32.10 |
| approval-ref-deletes | PASS | 5086 | 30.77 |
| parent-history-retention | PASS | 5091 | 31.65 |

После Contract/User delete сравнивалась вся строка intent, кроме двух current FK tombstones. После profile/grant/installation/app delete проверялось наличие того же INTENT по ID/count, не все его поля; company delete не исполнялся. ORM SELECT выполнялись на пустых revision4 таблицах, шесть ORM write paths этим не доказаны.

Это4 component cases, не4 закрытые группы из13. Переход проверен только от3; prefix0–2 остаются обязательными. Четыре DTO unit метода не суммируются с13 группами миграций.

Auth result SHA256: 043cd7f1cb366360cdb4f24fe6288181f553743b5019ad9f1900e689f6b3977c.

Независимое auth review MD: 110ff11ae461af833c4f235a98422b1934d4c5922059b22c89a2ab26c5b7c079; JSON: 5611256916ec7a7064f457ea282da8cc8e43d675caac031a9a7f7f880c9ce3f5.

Независимое schema4 review MD: eb8191ed56a708f073d6f17a15f7d082c2b43b387280e531dcdd95435962d93e; JSON: c1a11abbf0cd5629933ce8adfade409cdf0648c4996eb4442728fd4c4bab5865.

Парный JSON содержит точные Source/result/controller/review pins и границы. Полный TCB общей venv/interpreter/image не переаттестован. Чужие safe projections не доказывают отсутствие любых изменений чужих данных. C libpq может не давать Python socket audit events; это не NoSQL.
