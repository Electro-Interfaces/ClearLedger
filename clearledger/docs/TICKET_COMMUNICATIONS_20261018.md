# ТП9: канонический ticket ACL Поддержки

Core public.tickets не авторитет Support-заявки. services/ticket_communications.py связывает Core company через единственную eco_app_company_links(app=support) с точным SupportUUID и отправляет RS256 aud=support, svc=ticket.communication, sub=service:ticket.communication, cid, actor, jti, TTL120 на pinned internal Support API. Проверка требует действующего UserCompany, включённого support и активного stable-bound пользователя Support; email/имена/slug не используются.

POST /api/support/tickets/{UUID}/chat|staff-candidates|video принимает строго {supportCompanyId:UUID}. OpenAPI содержит типизированные request/response модели и503 video unavailable. Старый /api/chat/tickets/{UUID}/room сохранён как URL и переведён на тот же gate; новый /api/chat/tickets/{UUID}/video нужен native ChatPanel.

Private staff room: product support, purpose support_staff, audience internal, scope_ticket_id=SupportUUID. Создатель является единственным initial owner; дальнейшее участие только явным приглашением с новым ACL check. Связь не открывает whole-tenant историю, legacy mixed комнаты остаются закрытыми без удаления. Все room reads/writes/files, WS подписка/typing/delivery, push проверяют актуальный ACL. Внутренний ticket chat не пересылается email и не появляется в общем поиске/админском массовом управлении. Приглашение без истории ограничивает также reply preview/forward/file/message actions.

Стабильная ticket_video_rooms(company_id,ticket_id,room) сохраняет непрозрачный media room при рестарте/ротации signing key. Она отдельно от tenant-wide ConfRoom/ConfSession: их общие join/recording права не подходят private ticket. Native ChatPanel не публикует guest URL нового ticket video в переписке.

## Schema upgrade перед HTTP

Штатный main lifespan ждёт app.database.create_all() до обслуживания запросов. Новая таблица создаётся metadata migration; новый partial unique index uq_support_staff_ticket_room присутствует также в incremental DDL после уже существующих scope_purpose/audience ALTERs. **Новых колонок в generic chat projection эта дельта не добавляет.** На существующей БД необходимо выполнить тот же schema step до запуска нового HTTP кода. Нет destructive backfill или удаления старой истории.

Локальный actual PG upgrade proof: заполненные chat_rooms сохраняются, удаляются только пустая новая таблица/index этой дельты, штатный create_all выполняется дважды, после старта прежняя private room сохраняет UUID. Fresh metadata fixture в одиночку за upgrade proof не считается.

## Private media capability и внешняя граница

JITSI_TICKET_PRIVATE_ENABLED по умолчанию false. Без него или без корректного RSA signing key ответ503 (detail.code=private_video_unavailable), без trace/room/URL. Staff chat работает независимо. Включение допустимо только после проверки, что данный Jitsi-контур действительно требует JWT и запрещает anonymous/guest admission. Флаг не меняет Prosody и не доказывает приватность медиа.

При opt-in Core выдаёт только signed room-bound JWT TTL120; customer moderator=false, staff с ticket ACL moderator=true. Сервисный Core→Support JWT не выдаётся браузеру. JWT/URL не пишутся в Support trace/историю чата. Ссылка Jitsi является bearer до истечения TTL; работающая внешняя медиасессия подчиняется настройкам Jitsi, мгновенный revoke внутри media этим кодом не заявлен.

Порядок: Support190+receiver/stable identity → Core schema-before-HTTP+gate → Support UI; private media opt-in только после внешней приёмки. Деплой, live env/ключи/маршруты не менялись.

## Воспроизводимые проверки

Составной runner находится в сопутствующей TSupport-ветке:
CORE_DIR=<this clearledger> CORE_PYTHON=<venv/python> npm run test:ticket-communications.
Он запускает собственные Core FastAPI/Support Express/tmpfs PG и настоящую RS256/JWKS цепочку. TICKET_COMMUNICATIONS_BASELINE=1 загружает исходный immutable375ccab chat router: свой Core admin получает200 для чужой Support заявки (paired expected-denied FAIL). Fixed включает current ACL/tenant, inactive/unbound, contract object scope, private history/files/WS/offline push/mail, migration/restart, default-off video и opt-in participant issuance.

CPU: TEST_DATABASE_URL=postgresql+asyncpg://isolated:isolated@127.0.0.1:9/ticket_cpu_only pytest tests/test_ticket_communications.py tests/test_chat_ws.py -k 'not postgres_delivers_between_worker_managers and not postgres_presence_is_shared_between_workers' -q (только тесты без DB fixtures).

Playwright TSupport component harness ходит в настоящие HTTP/PG Core/Support; внешний Jitsi media page перехватывается. Звук/видео, реальный Prosody no-anonymous admission и active media revoke остаются внешней приёмкой.

## Локальный итог 18.10.2026

Paired baseline HTTP/PG исходного router:1 ожидаемый FAIL exit1, current composition16/16 PASS exit0. Core CPU35/35, Support units351/351, оба typecheck/build PASS. Browser actual APIs/PG PASS exit0: /tmp/support-ticket-communications-QoAVR8/result.json; только внешний media page перехвачен. ActualHTTP canary: ordinary superadmin file200/private attachment404/private room404; прежняя non-ticket политика сохранена. Core file gate не расширяет private права superadmin. Новые room refs типизированы и JWT не попадают в Support/history/storage.

Выездной инженер считается staff при существующем ticket ACL, developer — при существующем contract/object ACL; customer/vendor staff chat не получают. Support UI query/cache изолированы по user.id и непрозрачному session epoch; поздний ответ от прежнего actor отбрасывается. None/ошибка подписания video проверены до communication-events и дают typed503 без history/URL.

Existing Core7 regression:49/49 PASS, каждый pytest file в отдельном process/random loopback DB собственного tmpfs контейнера. Покрыты chat_ws, chat_room_subject, chat_scope_directory, raw_intake, conf_protocol, conf_app, conf_privacy; артефакты /tmp/core-ticket-existing-regression-BhPnPU/result.json. QA runner в TSupport: npm run test:ticket-communications-core-regression с CORE_DIR/CORE_PYTHON. Совместный запуск conf_app→conf_privacy в одной session-БД оставлял чужие live встречи; исправлена изоляция QA, продукт под порядок не менялся.

Финальный CPU набор35 включает12 новых gate-тестов и существующие чистые WS/raw-intake/protocol проверки. Inactive private room не получает WS/push по старому членству; исчезнувшая room прекращает push. Все own fixtures CLOSED, push/deploy/live configuration не выполнялись.
