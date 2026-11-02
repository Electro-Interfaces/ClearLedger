# Владелец session lock дайджеста «Пульса», P9

База: `e951ba1c13b2657f7427170bb3eb7c1941901e3e`. Production меняется только в `app/services/pulse_digest.py`.

AsyncSession привязана к одной явно открытой AsyncConnection от acquisition до unlock/close. Commit и rollback запросов больше не возвращают lease в pool с удерживаемым session advisory lock. Factory, ключ и исходные DBAPI/asyncpg driver фиксируются один раз. При смене физического соединения локальный listener запрещает следующий SQL; повторного lock/retry нет. Прежняя подмена `async_session_factory` через async_sessionmaker сохранена; неподдержанный bind отвергается до SQL.

Cleanup имеет абсолютный deadline 10 секунд, ждёт завершения shield task при повторной отмене, при ошибке invalidates только owned connection. Если invalidate hook откажет, разрешены terminate исходного captured asyncpg driver и один bookkeeping invalidate. Исходная ошибка или отмена сохраняет приоритет. Постоянно сломанный сторонний pool hook не получает универсального восстановления bookkeeping.

Цикл компаний, включая SQL literal, сохранён по AST. `_companies_due`, `_recipients`, `_render`, `run_forever` и остальные 500 app blobs исходные; старые tests/schema bytes не менялись. Не меняются ACL, выбор компании и адресатов, due-hour, содержимое письма, порядок send → audit → Session.commit → unlock → Session.commit. Отправка SMTP и отметка в БД не становятся атомарными; exactly-once не обещается.

## Фактическая приёмка ROOT

Source decisions: `msg_d30801ca57f6`, `msg_c99f230bf5ba`, `msg_28d07b19d671`; независимый source review: `msg_67c49df2fe47`; actual acceptance: `msg_6e4d2f29ed25`.

ROOT исполнил одну серию **32 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, pytest 22.41 с, outer 39.068064610 с, exit 0, процесс reaped. Реальный bounded pool 2/overflow 0: старый дефект воспроизведён отдельно после rollback и commit; новый owner сохраняет PID/lock, второй run_once честно возвращает 0 без domain query/send, третий проходит после освобождения. Подтверждены реальные audit/transaction результаты, query/send/acquisition/unlock/commit errors, false unlock, invalidation/reconnect refusal, cancellation/repeated cancellation/deadline и одноразовый invalidate-hook failure без оставленной cleanup task. Пять target controls выполняются без подключения; advisory results не подменяются.

23 новых случая и 9 прежних: recipient filters ×5, P8 positive trace с двумя commit, quiet, отказ от дайджеста и отпуск. Старые assertions сохранены. Два P8 NullPool случая с hardcoded прежней БД не выбирались; их результаты не используются как доказательство pooled exclusion. Новый fixture использует fixed company/user IDs и прежний ограниченный synthetic Support read projection; он не доказывает полноту Support DDL/FK/ролей.

ROOT проверил source-after, exact inventory 77, native PG sendmsg 16 controls, forbidden 0 и все 32 IDs/assertions. Выполнен штатный DROP только свежей `api_pulse_digest_lock_owner_test_20261031` на `127.0.0.1:33546`: relations 0, clients 0, exists 0, maxlocks 64. Evidence ROOT: `.artifacts/root-pulse-lock-review-20261031/source-review.json`, `actual32/process.json`, `actual32/r1-evidence-test/*`, `actual32/drop.log`.

Frozen runner SHA256: `21da89419e9b5f304ea3648237798f574b8004895c254a83b9f313e5173d707b`; app 501: `4e60da1d80e54ec626c1c5e9046e3cfd1e6cba01fca48c02858ec358b349c050`; tests 376 без runner: `a0466bb0b1c1256956308d5adf3b31a360a5bf05884bbdb0d615dc387d20043e`; schema 16: `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d`. Семь guard functions AST идентичны принятому P8 runner. Полные manifests/argv/env/limits/IDs сохранены в `.artifacts/pulse-digest-lock-owner-20261031/frozen-{manifest,proposal}.json` своего worktree. Worker выполнил только Git/read/AST/compile/hash, runtime исполнял ROOT.

Это приёмка ограниченного пакета P9, не full CI и не завершение M04/M08/M00–M19. P8 business/schema gaps, включая отсутствующего владельца DDL `pulse_view_role_grants`, остаются отдельной работой ROOT. Production/deploy/flags не затрагивались.
