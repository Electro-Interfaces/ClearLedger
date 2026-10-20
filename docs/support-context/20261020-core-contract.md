# C01. Контракт Ядра и доступа к контексту Поддержки

Дата: 20.10.2026. Версия предложения: `support-context/1`, до сведения C02.
Область C01: исследование и контракт; runtime не изменён, интеграционные проверки ещё не выполнены.

База ClearLedger: `18d1a5076c4598e6064de4e4e49ef59fc2eb4471`, ветка
`MagLook/support-context-core-20261020`. Соседи прочитаны без изменений:
TSupport `55a135465ee688b311180d9e080ae5c129d40654`, ContactHub
`10819e28bca98029e0fcd4c751bf69d7738f59e9`.
`git pull --ff-only` сделал fetch, но ветка без upstream; HEAD совпал с указанной базой
`origin/feat/voice-megafon-20261019`. Слияние другой ветки в контрактную базу не выполнялось.

Канон: корневой и `clearledger/CLAUDE.md`; `ecosystem-deploy/docs/CORE.md` §4, §6,
§7 и §7б; `BRIDGE.md` §1–2 и §6; предупреждение об отзыве Support access JWT в
`CURRENT-STATE.md` от 20.10.2026. Эти документы прочитаны в read-only снимке,
операционные сведения и идентификаторы клиентов сюда не перенесены. Общий план
`support-context-plan.md` и матрица A01–A18 остаются документом координатора.

## 1. Что существует и что это действительно разрешает

Пути Core в таблице относительно `clearledger/server/app/`, Support относительно
корня TSupport, Node/CC относительно корня ContactHub. Имена новых ручек ниже являются
предложением, существующими считаются только явно перечисленные в этом разделе.

| Владелец и исходник | Реальный механизм | Существенная граница |
|---|---|---|
| Core `auth.py`: `create_access_token`, `get_current_user`, `session_valid` | Собственная сессия JWT: `sub`, `email`, `exp`, `iat`, `tv`, `at`; чтение User на запросе, сравнение token_version и предела 7 суток | Это не JWT внешнего КЦ. Здесь нет общего контроля audience/jti, а неизвестный `scp` отвергается. Новый grant нельзя пропустить как обычную сессию |
| Core `auth.py`: `assert_company_member`, `scope.py`; `resolve_member_modules` | Членство `UserCompany`; company, object_scope, own_organization_id, именованные роли; отдельные проверки модулей | Включённое приложение само по себе не даёт права на данные. Superadmin имеет явное исключение; оно не основание наделять КЦ администрированием |
| Core `routers/auth_router.py`: login, `totp` | Если включён TOTP, login проверяет OTP | В SSO/служебном токене Core нет `amr`, доказательства MFA КЦ или свежести второго фактора |
| Core `services/sso.py`: `sign_sso_token` | RS256; `iss`, `aud`, Core `sub`, `email/name`, `cid`, `companies`, `roles`, `adm`, `jti`, `iat`, `nbf=iat-10`, `exp` | `adm` только для отображения. Роли получателя и авторизация не заменяются этим флагом. `jti` при выпуске не означает его одноразовое потребление |
| Core `routers/sso_router.py`: `authorize`, `_issue_app_token` | `GET /api/sso/authorize?app=support` возвращает callback `#token=...`; подпись по конфигу приложения; срок из `sso_token_ttl_seconds` | В самой `authorize` нет `assert_company_member` и гейта продукта, в отличие от `app_token`; фильтрация лаунчера не является серверным ACL. Не использовать как новый контекстный вход |
| Core `routers/sso_router.py`: `app_token`, `voice_token_for_support` | `GET /api/sso/token?app=voice&company_id=...`: членство и включённый voice; срок не более 300 с. `voice-token-for-support` делает обратное точное отображение Support company → Core company и вызывает ту же выдачу | Только `TOKEN_APPS={voice}`. Нет роли оператора КЦ: `services/app_roles.py` допускает для voice только `admin`, прямо назначенного либо выведенного из admin компании/платформы |
| Core `services/sso.py`: `sign_service_token` | RS256, `sub=service:<scope>`, `svc`, `jti`, срок по умолчанию 120 с, необязательные `cid/actor` | Служебный актор не равен человеку. `voice.stats/voice.audit` не дают доступа к досье. Текущий `voice.context` не связывает звонок с оператором |
| Core `auth.py`: `_named_key`, `CompanyByKeyScope`; `routers/voice_router.py`: `voice_company` | `X-Cloud-API-Key`: SHA256, `revoked_at IS NULL`, точная область `voice.identify`, компания из ключа, включённый voice | Нет `sub/aud/jti/MFA/срока` JWT: это долгоживущий машинный ключ, отзыв действует на следующем обращении. Не ограничен конкретным звонком или человеком. Общий legacy cloud key сюда не проходит |
| Core `routers/voice_router.py`: `identify`, `find_candidates`, `customer_summary`, `support_customer_context` | `POST /api/eco/identify`, `/ezs/customer-summary`, `/support/customer-context`; телефон в body, поиск внутри компании | Опознание номера не удостоверяет личность. `customer-summary` вызывает Support; `customer-context` сверяет `supportCompanyId` с картой, support enabled, читает только Core |
| Core `services/voice_support_context.py`: `support_tickets`, `_support_target` | Core → Support `/api/v1/eco/voice/context`, `svc=voice.context`, `aud=support`, `cid=Support company`, таймаут 0,65 с, redirects запрещены | Нет пользовательского actor/назначения и проверки callRef. Ошибки сворачиваются в `unavailable`; это не доказательство отсутствия заявок |
| Support `scripts/lib/sso-verify.js`: `verifyHandoffToken` | Настроенный JWKS одного Core; RS256, `iss`, `aud=support`, проверка срока/nbf при наличии | Есть fallback на первый ключ при неизвестном kid. Нет обязательного набора exp/iat/jti/sub, проверки max TTL, replay store, онлайн-отзыва Core. Для нового grant нужен отдельный строгий verifier |
| Support `scripts/routes/v1/auth.js`: `/sso`, `ssoCompanySlug`; `scripts/lib/eco-user-identity.js`: `resolveEcoUser` | Core `sub` связывается с `users.eco_user_id`; email только начальная совместимость, конфликт связи → 409, чужое членство → 403, inactive → 403. При разрешённом autoprov создаётся базовая роль из настроек | Старый SSO company выбирается по slug из `companies[cid]` → Support `companies.code`, а не `AppCompanyLink`. Новый API не должен смешивать эти способы. Ответ выдаёт обычные access/refresh JWT, широкие для контекстного окна |
| Support `scripts/lib/auth-middleware.js`: `requireAuth`, `generateTokens` | Собственный bearer access JWT до 2 часов; refresh до 30 дней | `requireAuth` не читает текущие active/role/членство/отзыв из БД. Короткий срок нового grant этого долга не исправляет; новый API обязан иметь живую проверку |
| Support `scripts/routes/v1/voice-context.js` | Требует `svc=voice.context`, UUID cid, непустой jti, exp не дальше 130 с; `openCallerTickets` с company из JWT | `jti` не записывается как использованный, `exp-iat` отдельно не проверяется. Тело не выбирает компанию. Это машинная выдача своей компании, не человеческий допуск |
| Support `scripts/lib/cc-identity.js`: `resolveOperatorIdentity`; `scripts/lib/voice-events.js`: `resolveUser` | Для asterisk UUID login может быть Core `eco_user_id`: active+membership+CC role, без кеша; иначе явная identity по provider/connector/login и ограниченный legacy email fallback | Существуют legacy bindings оператора телефонии к Support user. Нет общего trusted CC issuer+connection+sub → Core actor. Совпадение произвольного UUID оператора с Core sub не доказывает делегацию |
| Node `node/src/people.ts`: `SOURCE_OF`, `createPeople`, `link`, `resolve` | `cc_operator` имеет `source=support`, канон связи в `Support.cc_agent_identities`; узел хранит ссылку и временные интервалы, свои идентификаторы ВАТС ведёт отдельно | W05 запрещает второй независимый справочник оператора КЦ. Метка source сама по себе не проверяет разрешение нового API; необходим exact resolve в Support |
| Node `cc/src/server.ts`: `windowToken`; `node/src/cc-auth.ts`: `verifyCcJwt` | КЦ после своей сессии/смены выдаёт 60-секундный JWT `iss/aud=nodeUrl/sub/shift/amr`; узел проверяет закреплённые JWKS/kid, ES256/RS256, iss, audience, TTL ≤120, iat/nbf, одноразовый jti | Это отдельный CC sub. `iss=elsyplus` Core одинаков у пространств, поэтому ключи и компания обязательны наряду с issuer |
| Node `node/src/window.ts`: `exchange`, `me`, `verifyChannel`, `mine` | Admission operator registry, active connection, часы/CIDR, MFA `amr` с `otp` по умолчанию, DPoP. Выдаёт собственный HS256 token 900 с: act, conn, lines, cnf.jkt. На запросах сверяет connection, admitted, отзыв и DPoP htm/htu/ath/jti/jkt | Узловой HS256 token не проверяется третьей стороной. `mine` хранит множество когда-либо предложенных операторов и срок postContactAccessHours (по умолчанию 2 ч); этого недостаточно для прав новой заявки после transfer |
| Node `node/src/space.ts`: auth | Проверяет Core RS256/JWKS, `aud=voice`, cid узла и admin роль; служебные scopes только своим ручкам | Не использовать этот admin API как обход admission оператора |

Модель компаний: `models.py:AppCompanyLink` (`eco_app_company_links`) имеет уникальность
`(app_id,company_id)` и `(app_id,external_company_id)`. `services/support_scope.py` читает
точную пару в обе стороны, без fallback по имени/slug/текущей компании. Новый контракт
использует эту пару. В Support один deployment доверяет одному Core JWKS; issuer сам по себе
не глобальный namespace. Межпространственный `PartnerSpace.support_company_id` относится к
мосту переписки, а не заменяет локальное отображение Core → Support.

Пропуск инженера уже решает другую задачу: `space_bridge_router.py:accept_visit`,
`_verify_visit`, `_use_once`, `auth.py:_check_visit` принимают RS256 по строго выбранному kid,
`aud=space:<slug>`, exp/iat/iss/aud, max TTL 120 с, active vendor partner и одноразовый jti
в PostgreSQL. Сессия `scp=visit/cid/pvs` живёт час, заново проверяет связь и членство,
ограничивает ORM-чтение `UserCompany`; местную привилегированную учётку по email не подменяет.
Но этот вход создаёт guest по email и не ограничивает call/context. КЦ не получает его
автоматически, в `PartnerSpace` не заводится только ради обхода нового допуска.

## 2. Предлагаемая граница identity и прав

Оператор входит своим CC login/TOTP. Сессия Ядра клиента, широкий Support JWT и роли admin
ему для открытия окна не нужны. Применяется отдельная делегация; она не выдаёт обычный
Core access/refresh token, не вызывает autoprov `/auth/sso`, не даёт доступ к каталогу
людей/всем телефонам и не меняет его обычные роли.

По решению координатора `msg_f5da8c7368bb` владельцем явной активной связи остаётся
Support (`cc_agent_identities`), а не новый справочник Core:
`(supportCompanyId,trustedNodeId,connectorId,ccIssuer,connectionId,ccOperatorSub)`
`→ Support user → users.eco_user_id=coreActorSub`. Существующий binding расширяется
проверяемыми namespace/сроками, не создаётся параллельная независимая истина.
Core получает эту связь служебным actor-resolve, проверяет существующего Core actor,
company membership/права и включённые продукты. Support проверяет активность, нужную
компанию, реальную роль и прикладные ACL. Mapping создаёт/отзывает уполномоченный
администратор существующим процессом Поддержки; КЦ не управляет этой картой.
Один CC sub у двух издателей или в двух пространствах означает разные связи.
Ни email, ни телефон, ни присланное браузером `actor` не могут создать связь.

`coreActorSub` является адресатом атрибуции и явного разрешения компании. Если для
применения нынешних Core object/module ACL используется `UserCompany`, это заранее
настроенное ограниченное членство без повышения роли и без выдачи широкой сессии.
Отсутствие такого основания означает `actor_unmapped`/`actor_forbidden`, а не создание
сотрудника/членства при входе. Согласованная база v1 требует действующего ограниченного
членства; нельзя заменить `assert_company_member` машинным ключом. Обязательного
интерактивного входа оператора в Ядро и широкой SSO-сессии при этом нет.

Эффективные возможности = пересечение разрешения компании/mapping, текущего admission узла,
назначения звонка, Core module/object/organization scope и Support ACL/роли/назначения.
Скоуп токена только сужает эти права. Даже явно сопоставленный admin не получает в
контекстном токене admin/tech, управление КЦ, справочниками, SLA или произвольный route.

По умолчанию: `context.read`, `context.select`, `ticket.create`, `ticket.append`.
`context.select` означает уточнение кандидата/оборудования, а не изменение справочника.
Закрытие, статус, приоритет, переназначение, эскалация и dispatch не добавляются в v1 по
умолчанию. Их последующее включение требует отдельной capability и текущей проверки
существующего workflow. Например Support `tickets.js:POST /:id/route` требует
`userCanAccessTicket` и одну из явно перечисленных операторских ролей; это не право КЦ
как организации. Для производителя/подрядчика применяются `ticket-access.js`,
`contract-access.js:participantCanAccessTicket`, vendor_id/участие и маска полей; допустимы
только назначенные ему задачи/оборудование, `context.read` не означает досье человека.

## 3. Идентификаторы, подготовка и маршрутизация

| Поле v1 | Значение, хозяин |
|---|---|
| `callRef` | Структура `{nodeId, connectorId, nodeContactId}` внутри coreCompanyId; узел подтверждает, что звонок принадлежит ему. Не UUID контакта-человека, не телефон |
| `contextRef` | Случайная устойчивая ссылка Support на подготовленный контекст конкретного callRef; scoped company, не bearer-доступ сама по себе |
| `threadRef` | Обращение Поддержки. Создаётся/связывается прикладным процессом, чтение/prepare не создаёт обращение |
| `ticketRef` | Заявка Поддержки; несколько callRef могут быть связаны с одной заявкой |
| `personRef`, `objectRef`, `equipmentRef` | Разные scoped ссылки: человек, станция/объект, конкретная колонка/разъём. Код станции не заменяет equipmentRef |
| `actor` | Core sub и проверенный исходный CC issuer/sub; передаются только между узлом, Core, Support и окном пространства |

Устойчивая уникальность контекста: `(coreCompanyId,nodeId,connectorId,nodeContactId)`;
в Support также проверяется отображённый supportCompanyId. `connectionId` подключения КЦ
не равен connectorId интеграции Support. Обе связи проверяются по настройке заказчика,
не по полю `customer` пульта. Сервер КЦ не получает contextRef, actor UUID, thread/ticket UUID,
person/object/equipment refs. Существующий transport contactId допускается лишь в прежнем
назначении как служебный ID, без добавления к нему предметных данных.

Распределение ответственности:

1. Узел после фиксации входящего callRef запускает prepare асинхронно до ответа.
   Основание: уже существующие `node/src/calls.ts:win.open` и `window.ts:open` не должны
   блокировать телефонию. Источник телефона и call facts только узел, не сервер КЦ.
2. Node → `POST /api/eco/support-context/v1/prepare` Core. Именной key узла и его server-side
   binding к компании/узлу/коннектору; существующий `voice.identify` можно использовать
   только на этом доверенном машинном входе с дополнительными проверками call identity.
   Body `{callRef, phone, startedAt, direction}`; `extra=forbid`, лимиты, никаких raw ASR/audio.
   Core сам определяет компанию и mapping Support; body не выбирает чужую компанию.
3. Core отправляет `POST /api/v1/eco/support-context/v1/prepare` в Support через
   `App.config.internalUrl`/`space_projection._internal_base_url`, без внешнего кругового
   proxy и redirects. Токен `aud=support-context`, `svc=support-context.prepare`,
   `sub=service:support-context.prepare`, coreCid/cid, callRef, jti, iat/nbf/exp ≤120 с.
   Этот scope не может читать/изменять заявки от имени человека. Support возвращает
   `202 {protocol,contextRef,version,state:"preparing"}`; retry возвращает тот же контекст.
   Core фиксирует соответствие callRef/contextRef до разрешения чтения source; сборщик
   стартует после подтверждения binding или повторяет только этот ограниченный шаг,
   не создавая второй context при гонке первого prepare.
4. Support владеет сборкой досье, истории до установки узла, заявок, оборудования и
   знаний. Для данных Core использует только leaf `/api/eco/support/customer-context`
   с уже настроенным именным ключом, как `createCoreCallerClient`, без новой общей
   пары credentials. Телефон берётся из зарегистрированного prepare, а не свободного
   body оператора. C02 выбирает этот leaf либо его минимальное расширение для передачи
   проверенного actor/object scope; отдельный новый сборщик/источник не обязателен.
5. Browser читает/пишет непосредственно `/support/api/v1/support-context/v1/...` под
   origin заказчика. Core является единым входом/центром допуска, а не копией досье.
   Путь `/api` остаётся Core, `/support/api` nginx срезает до Support `/api`,
   `/voice/api` до API узла через существующий mTLS gateway. Контракт не разрешает
   произвольный URL/path в proxy, callback или returnTo.

Граф конечный: `Node → Core prepare → Support assembler → Core source (только SQL)`.
Это повторное обращение к разным операциям Core без рекурсивного сборщика: source не
вызывает Support, не запускает prepare и не вызывает `/ezs/customer-summary`.
Read/command идут Browser → Support; обновление Core-части Support → Core source.
Нельзя использовать `customer-summary/support_tickets` как источник сборщика Support:
они уже идут обратно в Support. Тест обязан запретить повторный вход в сборщик и
подтвердить конечное число HTTP-запросов при частичных отказах. Core не читает заявки
прямым SQL ради нового API, хотя старые витрины `support_scope` такой путь имеют.

Core source обязан применять object/organization ограничения контекста; сборка для
prewarm машинная, но любая выдача человеку дополнительно фильтруется его scope.
Кеш полного prewarm контекста не может автоматически стать ответом оператора или vendor.
`charging_context` сейчас читает данные компании и сводит найденных клиентов, а не
подтверждённое оборудование; это совместимый источник фактов, не готовый ACL нового окна.

## 4. Допуск окна из уже работающего окна узла

Основной вариант по решению координатора `msg_230c6dcdc50b`: iframe Поддержки внутри
существующего окна заказчика, которое уже встроено в пульт КЦ. Допуск инициирует
только окно узла со своим origin и текущим DPoP-сеансом. В `cc/web/src/Windows.tsx`
iframe уже имеет `sandbox="allow-scripts allow-same-origin allow-forms"`, без
allow-popups. Контракт не добавляет popup и не заменяет рабочий процесс новой вкладкой.
Предметные данные остаются в дочернем iframe origin пространства; shell КЦ не получает их.

Предлагаемые операции:

| Операция | Caller и вход | Результат и проверки |
|---|---|---|
| `POST /cc/v0/me/contacts/{nodeContactId}/support-admission` Node | Окно узла; `Authorization: DPoP`, proof; public JWK вложенного окна Support | Node проверяет `me`, текущее назначение/consult/wrapup, call version, admissible actions; возвращает одноразовый admissionCode и фиксированный публичный origin пространства, TTL 30 с |
| `POST /api/eco/support-context/v1/admit` Core | Вложенное окно пространства; `{admissionCode,nodeId}` и свой DPoP proof | Core по заранее настроенному backchannel узла разрешает opaque code, проверяет компании, CC issuer/conn/sub, mapping, версии и cnf.jkt; выдаёт ограниченный grant. CC bearer/Core session не принимаются как замена |
| `POST /api/eco/support-context/v1/renew` Core | Тот же grant+DPoP, новая актуальная admission assertion узла | Новый JWT ≤120 с, тот же actor/call/context, только суженные/заново проверенные actions; отозванный grant не оживает |
| `POST /api/eco/support-context/v1/introspect` Core | Только доверенный Support service caller; grant identity/digest | Проверка signature binding, active grant/mapping, Core прав и current Node assignment/revocation; возвращает текущие actions/versions/expiry, без клиентского досье. Не публичный endpoint просмотра actor |

Для introspect служебная схема отдельная: Core-signed `aud=core-support-context`,
`svc=support-context.introspect`, `sub=service:support-context.introspect`,
`coreCid/cid/contextRef/grantId`, обязательные version/jti/iat/nbf/exp и TTL≤120 с;
Core проверяет закреплённый ключ и сохранённое соответствие, не превращает svc в user.
Такой service token выдаётся доверенному Support по настройке внутри пространства,
не браузеру/КЦ; метод не принимает произвольный URL, actor или company вместо binding.

Внутренний `POST /api/v1/eco/support-context/v1/actor-resolve` Support вызывается **только
Core** при admit/renew/introspect: RS256 `aud=support-context`,
`svc=support-context.actor-resolve`, `sub=service:support-context.actor-resolve`,
`coreCid/cid`, trusted node/connector/connection и CC issuer/sub, request jti, TTL≤120 с.
Поля binding в подписанных claims и теле обязаны совпасть; `expectedBindingVersion`
передаётся при повторной проверке. Ответ только `{protocol,bindingRef,bindingVersion,
coreActorSub,supportUserRef,active,membership,permissionsVersion,capabilities}`,
без имени, email, телефона, досье или списка других операторов. Он идёт по доверенному
внутреннему HTTP в пределах стека; Support не вызывает Core из этой операции. Core
отвергает неоднозначный ответ/несовпадение expected actor, inactive/no membership и
перечитывает своего actor и права; подпись служебного запроса не даёт создавать binding.
Новый resolve не использует legacy fallback `resolveOperatorIdentity` по имени/email
или голому UUID. Кеш ссылки `source=support` узла не является решением о правах.

Node admission state доступен Core по узкому служебному backchannel, не admin API;
токен Node HS256 за пределы узла не передаётся. Core → Node запрос аутентифицирован
закреплённым `aud=node-support-admission` и `svc=support-context.admission`, имеет
coreCid/nodeId, короткий срок и строго выделенные consume/status методы. Сетевой адрес
берётся из конфигурации пространства, не из входного nodeId/URL браузера. Реализация
этих внутренних методов и выбор служебного transport должны быть закреплены C02.

Окно узла встраивает фиксированный `/support/context-entry` публичного origin пространства.
Дочерний iframe генерирует non-extractable DPoP key в своей памяти и сообщает public
JWK/nonce **непосредственно родительскому окну узла**, не top-level shell КЦ. Узел
запрашивает admissionCode, привязанный к этому JWK, и передаёт его только ожидаемому
`iframe.contentWindow`: точный `targetOrigin`, проверки `event.source`, `event.origin`,
nonce и строгой схемы в обе стороны. Grant остаётся в памяти iframe Support; `ready`
в shell КЦ не включает admissionCode/context/данные. При смене iframe/session/call
bootstrap nonce аннулируется. `*`, `window.top.postMessage` с данными и ретрансляция
bootstrap через сервер/оболочку КЦ запрещены. Обычные разрешённые Node shell события
сохраняются по прежним схемам.

Существующий `cl_gate` не выдаётся: он открывает обычную сборку пространства и рассчитан
на Core session, которой здесь нет. Выделяются минимальный public entry
`/support/context-entry` и отдельные статические assets `/support/context-assets/*`;
они не содержат PII, обычного Support shell/SSO или session storage и не открывают
`/support/`, `/admin` и обычные assets. Данные доступны только новому scoped DPoP API.
Public entry/assets имеют явный CSP: frame-ancestors включает всю разрешённую цепочку
origin КЦ → origin узла → origin пространства, `frame-src` родителя разрешает точный
origin Support, `connect-src` только нужные endpoints. Источник origin allowlist:
доверенная настройка подключения, не query/postMessage body. Конфликтующий X-Frame-Options
или общий более строгий CSP не должен случайно блокировать nested iframe; проверка
идёт с настоящими HTTP заголовками. Wildcard для произвольных КЦ не добавляется.
Широкое выключение nginx gate запрещено. Изменения исходников ecosystem-deploy под эти
точные location/headers/API C02 выделяет отдельной задачей/веткой кромки; C01 их не
выполняет, выкатка/rproxy/prod не затрагиваются.

Пример адресации, только синтетические адреса:

| Участник | Адрес |
|---|---|
| Browser iframe entry/assets | `https://space.example.invalid/support/context-entry`, `https://space.example.invalid/support/context-assets/entry.js` |
| Browser → Core admit/renew | `https://space.example.invalid/api/eco/support-context/v1/admit` (или `/renew`), same-origin для Support iframe |
| Browser → Support data/commands | `https://space.example.invalid/support/api/v1/support-context/v1/contexts/context-demo-17` |
| Support → Core leaf/introspection внутри стека | `http://backend:8000/api/eco/support/customer-context`, `http://backend:8000/api/eco/support-context/v1/introspect` |
| Core → Support prepare/actor-resolve внутри стека | `http://support:3003/api/v1/eco/support-context/v1/prepare` и `/actor-resolve`, фактически из App.internalUrl |
| Окно узла → Node admission | Доверенный публичный node origin + `/cc/v0/me/contacts/call-demo-17/support-admission`, как существующий DPoP exchange узла |

Браузер не получает docker-имя `backend` или его внутренний URL. Существующий
`voice-edge.sh` обслуживает `/voice/api/*` → Node `/api/*` и не маршрутизирует `/cc/v0/*`;
новый admission окна использует публичный адрес самого узла, а не выдуманный rewrite.
Core backchannel использует отдельный доверенный внутренний адрес Node из настройки.

В URL нет телефона, JWT, кода допуска или UUID; в storage нет токенов/досье; admissionCode
не показывается родителю и не используется как аналитический идентификатор. Даже
перехваченный одноразовый code требует DPoP ключа привязанного окна. Тело/Authorization,
PII, replayable proof, ответ с grant и private key не журналируются. `Cache-Control:
private, no-store`, `Referrer-Policy: no-referrer` на entry/API; после истечения/отзыва
очистить UI и кеши. Same-origin XSS остаётся границей доверия пространства; широкая
вставка HTML/сторонних скриптов этим контрактом не допускается.

Минимальный новый Core-signed JWT (все значения ниже вымышленные):

```json
{
  "version": "support-context/1",
  "iss": "elsyplus",
  "aud": "support-context",
  "sub": "10000000-0000-4000-8000-000000000001",
  "act": {"iss": "https://cc.example.invalid", "sub": "operator-demo-a"},
  "scp": "support_context",
  "coreCid": "20000000-0000-4000-8000-000000000001",
  "cid": "30000000-0000-4000-8000-000000000001",
  "nodeId": "node-demo-a",
  "connectionId": "connection-demo-a",
  "callRef": {"nodeId": "node-demo-a", "connectorId": "connector-demo-a", "nodeContactId": "call-demo-17"},
  "contextRef": "context-demo-17",
  "grantId": "grant-demo-a",
  "jti": "one-token-demo-a",
  "assignmentVersion": 4,
  "permissionsVersion": 2,
  "phase": "connected",
  "actions": ["context.read", "context.select", "ticket.create", "ticket.append"],
  "ticketRefs": [],
  "cnf": {"jkt": "synthetic-window-key-thumbprint"},
  "amr": ["pwd", "otp"],
  "iat": 1800000000,
  "nbf": 1800000000,
  "exp": 1800000120
}
```

`amr` переносится из проверенного admission КЦ; при обязательной MFA нужен otp и свежий
admission. Это не заявление, что Core password login прошёл MFA. Публичный JWT header
должен содержать точные `alg=RS256`, известный kid, `typ=at+jwt`. Strict verifier требует
все поля схемы, точные типы, единственную ожидаемую audience и `exp-iat≤120`, отклоняет
unknown kid/alg, пропущенный sub/jti, чужой context/call/actor/cid. JWKS закреплён за
конкретным Core deployment, а не загружается по JWT iss/jku. Для service token своя
схема; `sub=service:*` не проходит человеческие операции.
Сейчас Node `exchange` проверяет `amr` CC JWT, но в свой 900-секундный token его не
копирует. I12 должен сохранить проверенное MFA/admission evidence и время его получения
в состоянии узла для нового admission; Core не принимает `amr` из свободного body окна.

AdmissionCode одноразов в durable store узла; потребление связано с request id и
thumbprint. При потере ответа тот же binding возвращает ту же admission-квитанцию,
другому binding отвечает replay. Core grant jti уникален и активен в PostgreSQL,
но не одноразов на каждый GET: API JWT предъявляется несколько раз до срока/отзыва.
DPoP proof jti одноразов на HTTP-запрос; replay store общий для процессов. На renew
старый jti закрывается с определённым ограниченным окном для завершения текущего запроса,
а не превращается в долгоживущий refresh token. Нужны лимиты хранилища и очистка по exp.

## 5. Чтение, команды и жизненный цикл прав

Новый namespace Support: `/api/v1/support-context/v1` (снаружи префикс `/support`).
Для всех методов: strict Core verifier + DPoP, introspection, активный Support user
по eco_user_id и действующая membership/роль, совпадение Core/Support company map,
call/context binding, проверка action и прикладного ACL. Fail closed при невозможности
подтвердить право: unavailable не подменяет forbidden. Payload полей, которых нет в
allowlist, отвергается; body/query/header не могут расширить cid, actor или ticketRefs.

| Метод | Вход | Эффект |
|---|---|---|
| `GET /contexts/{contextRef}` | `context.read` | Состояния частей и разрешённое досье; чтение не создаёт ticket/thread |
| `GET /contexts/{contextRef}/details?section=...&cursor=...` | `context.read`, whitelist section, bounded pagination | Детали той же подтверждённой выборки. Нет `phone` или произвольного person/object selector |
| `GET /contexts/{contextRef}/tickets/{ticketRef}` | `ticket.read` для postcall либо допустимый `context.read`; ticketRef в разрешённом множестве и current ticket ACL | Ограниченная карточка назначенной заявки. Postcall не разрешает GET полного context/profile/details |
| `POST /contexts/{contextRef}/selection` | `context.select`, `{expectedVersion,personRef?,objectRef?,equipmentRef?,confirmation}` | Подтверждает конкретного кандидата/станцию/колонку/разъём в своём scope; увеличивает version, инвалидирует зависимые части |
| `POST /contexts/{contextRef}/commands` | Action + `Idempotency-Key`; `{command:"ticket.create"|"ticket.append",expectedVersion,ticketRef?,fields}` | Оператор создаёт/дополняет заявку во время connected. Create не принимает готовый ticket id; append требует разрешённой существующей заявки и expected ticket version |
| `GET /contexts/{contextRef}/receipts/{commandRef}` | Тот же actor/context, receipt.read как часть разрешённой команды | Восстанавливает результат потери ответа; не создаёт повторный эффект |

Команда атомарно фиксирует effect, author, связи и квитанцию `{commandRef,contextRef,
callRef,threadRef,ticketRef,ticketNumber,contextVersion,ticketVersion,created,replayed}`.
Единица эффекта `(company,callRef,contextRef,commandRef)`, где Idempotency-Key задаёт
устойчивый commandRef и связан с canonical payload hash; повтор иного payload → 409.
Первоначальный actor сохраняется в receipt, а смена оператора не создаёт второй эффект
той же команды. Чтение receipt требует текущего допуска; оно не переписывает автора
и не раскрывает квитанцию прежнего оператора вне разрешённой заявки. При append/create
связывание call с ticket происходит в этой же транзакции. Точный union разрешённых
`fields`, номера версий и форма receipt сводятся с C00; Core не переписывает Support
workflow и SLA. Вариант C00 с POST read/details и refs/cursor в body вместо предложенных
GET выше также передаётся C02 для выбора единого wire API.

Текущий `callerDossier` годится как источник существующих собственных данных, но не
как готовая схема нового доступа: `contacts_total` считает `inbox_threads`, не звонки;
подставляемый последний объект не является подтверждением. Новый ответ обязан иметь
`parts` со `state=loading|available|partial|empty|unavailable|forbidden`, `source`,
`asOf`, error code без PII. `counts.calls/threads/tickets` раздельны, с периодом,
определением и источниками, включая историю Support до установки узла; нет склейки
двух провайдеров по телефону и времени. Ambiguous person остаётся ambiguous;
последняя зарядка только кандидат. Manufacturer/model/service/knowledge разрешаются
по подтверждённому equipmentRef, неизвестное возвращается явно.

| Состояние | Право нового API |
|---|---|
| preparing / offering | Машинная подготовка не даёт права человеку. Явно назначенный оператор получает разрешённый read; create/append после принятия звонка |
| connected | Оператор текущего назначения: read/select/create/append в пересечении ACL. На несколько открытых звонков отдельные grant/context/versions |
| consult | Консультант допускается узлом явно; read-only маска в пределах его роли, без create/append/route. Основной оператор сохраняет свои права |
| transfer requested / failed | Назначение ещё не сменилось. Новый write grant не выдан, исходный жив. Ошибка передачи не оставляет двух писателей |
| transfer committed | Узел увеличивает assignmentVersion; старые write grants более не проходят. Новый оператор получает свой grant и свои ACL; заявки автоматически не переназначаются от смены трубки |
| wrapup | Назначенный на постобработку actor: ограниченное окно срока по политике заказчика; ticket.append только к ticketRefs, связанным этим context. Если заявки нет, create только при явной capability и живом wrapup assignment |
| completed | Доступ к полной истории по номеру прекращается. Возможна отдельная `ticket_postcall` делегация только назначенной заявки и минимальных сведений её контекста; период из политики, без бесконечного продления |
| revoked / expired / operator inactive / mapping disabled | Новые чтения/команды/renew запрещены; сброс видимых данных и кешей, отсутствие fallthrough в legacy bearer |

Для `ticket_postcall`: иной `scp`, `phase=postcall`, обязательный непустой ticketRefs,
`actions=[ticket.read,ticket.append]`, expiry не позже окончания права на постобработку,
живое совпадение current_assignee_id или явно разрешённого назначения workflow.
Watcher и прежнее участие в звонке сами по себе не дают постобработку. Передача инженеру
выдаёт ему ticket-specific право с его маской, не исходное досье и не токен оператора.

Introspection без положительного кеша прав для команд: Core вызывает канонический
Support actor-resolve, сверяет binding/версию допуска, текущий статус узла и Core ACL;
Support непосредственно перед эффектом перечитывает user active/role/company и ticket
assignment в своей транзакции.
Online introspection выполняется до начала бизнес-транзакции/локальных row locks:
она вызывает Core → Support actor-resolve и не должна ждать собственных захваченных
блокировок. Затем в транзакции Support заново проверяет bindingVersion, active,
прикладные права и версии строк; несовпадение → отказ/конфликт без эффекта.
В Core User нет универсального `is_active`, поэтому нельзя обещать проверку
несуществующей колонки: нужны существующий User, актуальное разрешённое членство,
живой binding и сохранённый при admit `User.token_version` (повторно сравнивается при
introspection). Сброс сессий/смена версии закрывают уже выданный grant; новый допуск
всё равно требует актуального CC admission и полного пересмотра прав. Снятие членства
не обходится сохранённым значением token_version.
Для чтений также нет stale positive authorization в v1. Деактивация Support не ждёт
exp. Передача/отзыв узла проверяется перед каждой операцией; линейная точка допуска
фиксируется в introspection, уже допущенный in-flight запрос может завершиться.
Более сильная распределённая сериализация Node/Core/Support не обещается; глобальный
lease в v1 не вводится. Координатор подтвердил эту границу и запрет новых операций
после отзыва/transfer. Ошибка источника данных допускает partial, ошибка источника
прав запрещает данную операцию. Это может ухудшить окно, но никогда не останавливает
телефонию.

Поздний `call.completed` аутентифицируется существующим HMAC/webhook connector и его
компанией, не истёкшим человеческим grant. Он добавляет факты/запись/итог в уже связанную
заявку отдельной идемпотентной транзакцией; не исполняет новые команды от имени отозванного
actor. Receipt live-команды не означает, что факт завершения уже обработан.
В `voice-events.js:receiveCallCompleted` сейчас ранний return по `voice_ticket_links`
стоит до `ingestCall`; простое добавление live-link потеряет поздние данные.
Нужно отдельно хранить квитанции команд и финального события, довести старые call facts
до завершения, не создать второй ticket и не менять исходные SLA deadlines.
Подтверждённые person/object/equipment выбора нового context имеют приоритет: поздний
итог со старым кандидатом из компактной карточки не перезаписывает этот выбор.
Raw ASR/audio/transcript остаются на узле; в заявке только принятые человеком сведения
и разрешённая ссылка записи, не автоматическая копия разговора.

## 6. Ошибки и отсутствие обходного ACL

Новые API возвращают `{protocol:"support-context/1",error:{code,retryable},requestRef}`;
requestRef случайный, не содержит person/company UUID и не передаётся в КЦ как досье.

| HTTP | Коды и поведение |
|---|---|
| 400 / 422 | `invalid_request`, `unsupported_protocol`, `unknown_field`: неверный формат, запрещённое поле, отсутствие обязательной версии |
| 401 | `invalid_token`, `expired_token`, `invalid_dpop`, `replayed_proof`: подпись/kid/aud/iss/тип/срок/DPoP; без подробностей найденного человека |
| 403 | `actor_unmapped`, `actor_forbidden`, `mfa_required`, `grant_revoked`, `assignment_changed`, `action_forbidden`, `product_disabled`: нет основания выдавать данные |
| 404 | `context_not_found`, `ticket_not_found`, `mapping_not_found`: отсутствует scoped ресурс; чужие context/ticket возвращают такой же ответ, без проверки существования наружу |
| 409 | `version_conflict`, `idempotency_conflict`, `selection_required`, `admission_replayed`, `invalid_phase`: без частичного применения |
| 429 | `rate_limited`: ограниченный Retry-After, телефония независима |
| 503 / 504 | `source_unavailable`, `authorization_unavailable`, `sso_unconfigured`: источник/право не подтверждено. Для разрешённого context read данные могут быть partial, для auth отказ целиком |

Подмена body cid/callRef/actor/contextRef, `X-Company-Id`, `companies/roles/adm`, query phone
или ticket UUID никогда не заменяет binding. `svc` не разрешает человеческую команду,
Core сессия не заменяет DPoP grant, старый Support JWT не принимается в новом namespace.
Нет redirect на «войти администратором» при отказе. Публичные клиентские детали не
выдаются через admin exception `userCanAccessTicket`: новый verifier сначала фиксирует
компанию и делегацию, затем применяет прикладной ACL. Чужие watchers/target_company
из существующих правил не могут расширить company/context нового токена.

## 7. Минимальные изменения следующей фазы и совместимость

| Владелец | Следующая реализация |
|---|---|
| Core I11 | Отдельный router/service для prepare/admit/renew/introspect; reuse существующего leaf или минимальное расширение; durable grants/replay, ссылка на канонический Support binding без второго справочника; строгие схемы JWT/DPoP, actor-resolve клиент и аутентифицированный Node backchannel; reuse точной company map, реестра приложений и текущих ACL. Аудит admission/command identity без телефона/досье/секретов, в пространстве заказчика |
| Support I10 | Exact binding с namespace и версией в каноническом cc_agent_identities и узкий actor-resolve; новый scoped middleware с живой active/role/membership/assignment проверкой; сборщик из существующих caller/profile/charging/ticket sources, подтверждённая selection; команды/версии/receipt; исправление раннего final return общим live/final обработчиком. В Core не переносить SQL предметных заявок |
| Node/ContactHub I12 | Неблокирующий prepare; callRef и config binding к Core/Support; consume/status admission с DPoP и актуальным assignment; отдельные consult/transfer/wrapup версии; безопасное открытие окна; receipt live-link остаётся на узле, без UUID/PII на сервере КЦ |
| Support UI I13 | Вложенный iframe `/support/context-entry`, отдельные context-assets и ограниченный context экран из существующих компонентов/логики. Обычные маршруты, вид и функции старого рабочего места сохраняются; grant не записывается в обычный auth store/rail |
| Кромка, отдельная задача C02 | Точные public entry/assets и новые API location/headers в исходниках ecosystem-deploy; CSP всей nested iframe цепочки без popup/широкого cl_gate, проверка локально. Отдельная ветка, без выкатки |

Без schema/runtime изменений в C01. Вводится feature/capability `support-context/1`,
объявленная явно в паспорте/конфигурации, не по пробному ошибочному вызову нового endpoint.
Выключенная функция сохраняет старую карточку и итог. Старые `identify`, `customer-summary`,
`support/customer-context`, `/sso/authorize`, `/sso/token?app=voice`,
`voice-token-for-support`, `call.completed` payload/ответ и media route совместимы.
Не добавлять новые UUID в envelope КЦ или broad postMessage. Новые необязательные
данные финального события версионируются со схемами; legacy отсутствие live-link означает
старую итоговую обработку. Поздний финал старого узла не должен повторно создать уже
связанный новым окном ticket. Нужна обратная совместимость миграций, без backfill
истории в Core или копирования клиентов на сервер КЦ.

## 8. План реальных проверок I11/V20

Это план тестов, а не результаты C01. Нужны реальные подписи временными ключами,
HTTP Core/Support/Node и PostgreSQL с синтетикой; dependency override или mock claims
не доказывают A10/A14. Запуск только на выделенных loopback портах/новых БД и с явной
`TEST_DATABASE_URL`: Core conftest удаляет схемы. Не использовать рабочие DSN, prod HTTP,
ВАТС, секреты или внешние отправки. Никаких npm ci/долгих тестов на контрактной фазе.

| Проверка | Реальная цепочка и утверждение |
|---|---|
| JWT positive | CC login с OTP → подписанный CC JWT → настоящий Node DPoP exchange → admission → Core grant → Support read/create. Зафиксировать actor по Core sub и Support eco_user_id в строках команды/аудита; нет generic technical author |
| wrong-company | Две компании одного Core и две карты Support. Ключ А+supportCompany Б, grant А+header/body/path Б, callRef/ticket/object Б → отказ, SQL Б не меняется; в ответе нет маркеров Б |
| wrong-audience / wrong-key | Валидные подписи, но aud voice/support/чужой space вместо support-context, тот же issuer с другим JWKS, неизвестный kid, alg none/HS, отсутствующие claims → отказ до данных. Service prepare/actor-resolve token не исполняет command |
| wrong-actor | Grant оператора A с DPoP key Б, подмена act/sub на HTTP, совпавший UUID CC sub другого issuer, иной conn/node, unmatched/inactive eco_user_id → отказ. Два разных локальных actor не склеиваются по email |
| stale / revoked | Истёкший/будущий токен, excessive TTL, reuse admissionCode/DPoP jti, закрытый jti, mapping off, смена permissionsVersion, Support user inactive/роль снята, Node connection blocked/admission revoked → следующий запрос/renew отвергнут. Проверить два процесса и PostgreSQL replay, рестарт не воскрешает grant |
| consult | Основной actor A создаёт ticket, консультант Б получает read в своей маске. POST create/append/route Б → 403; A продолжает. Завершение консультации закрывает grant Б |
| transfer / revoke race | Неудачный transfer не меняет право A. Успешный увеличивает assignmentVersion: новая операция A запрещена, Б получает своё пересечение ACL; `mine().operators` не сохраняет право A. В тесте барьерами остановить команду до/после настоящего HTTP introspection: revoke до допуска → отказ без эффекта, revoke после допуска → разрешён один зафиксированный эффект и запрещён следующий запрос. Ответы, порядок событий и строки БД доказывают линейную точку; распределённая атомарность не заявляется |
| wrapup / postcall | До конца звонка получен ticket receipt; после ended только назначенный wrapup actor дополняет связанный ticket; лишний ticket/person selector → отказ. После завершения wrapup только явный ticket_postcall и текущее назначение, после reassignment/expiry отказ |
| два пространства | У А и Б одинаковые CC sub, issuer Core и внешние числовые коды, разные Core ключи/mapping/компании; параллельные окна из одной CC сессии. Grant/call/context/jti/object А не принимаются Б; browser cache/queryKey включают company+actor+context, смена окна не смешивает данные |
| vendor / manufacturer | Пользователь производителя видит назначенную задачу, подтверждённое разрешённое оборудование и документы. Чужой ticket/equipment, profile/history клиента и неподтверждённый station → отказ/маска, не admin fallback |
| live / late / retry | Создание в connected, потеря HTTP ответа, повтор ключа и конфликт версии. Один ticket и receipt. Затем повторяемый HMAC call.completed дополняет call facts/запись/принятый итог, не сбрасывает SLA. Командная и event-квитанции обе сохранены |
| no recursion / partial | Настоящий Support assembler вызывает только Core leaf. Core leaf не вызывает Support, Core→Support timeout не вызывает второй prepare. Источник данных недоступен → partial; introspection недоступен → отказ доступа; prepare таймаут не задерживает ответ узла на телефонию |
| no CC retention | Уникальные синтетические маркеры имени/телефона/станции/описания/UUID. Проверить HTTP/WS/postMessage, все text/json/storage/log поля КЦ, browser local/session storage и URL/referrer; там нет маркеров, grant/admissionCode/DPoP secret. Сетевые артефакты только method/path/status без body/Authorization |
| nested iframe / gateway | Настоящий пульт КЦ → существующий sandbox iframe узла → iframe Support с CSP/headers локальной кромки. Без allow-popups, cl_gate, Core сессии и обычного Support JWT выполнить admit/read/create/append; неправильный ancestor/origin/source/nonce отвергнуть. В network только публичный space origin, нет docker hostname. Прежний Support shell и assets остаются под своим gate |
| legacy | Capability off и старый узел: прежняя карточка/итог; обычный Support экран/SSO/создание/дополнение/запись по старому маршруту. Новое окно без grant не использует сохранённый admin JWT |

Повторно используемые основы: Core `server/tests/test_voice_tokens.py` (real RS256,
mapping и scopes), `test_voice_support_context.py` (company boundary и relay),
TSupport `scripts/test/voice-integration.mjs` и `e2e/voice-operator-support-chain.check.mjs`,
Node `node/test/window.test.ts` и CC tests. Старый браузерный сценарий имеет отдельные
Core admin и CC operator права и явную QA-навигацию к ticket UUID; он не является
доказательством продуктового context admission. В новых тестах нельзя выдавать admin
ради успешной цепочки. A01–A18 закрываются только отдельными фактическими доказательствами.

## 9. Вопросы для C02 и пределы готовности C01

Вопрос координатору отправлен через `orchestration ask`, `msg_8f0462e71273`.
Ответ `msg_f5da8c7368bb`: ограниченный grant и одноразовый admission подтверждены,
mapping принадлежит Support, Core не заводит второй справочник/человека/членство;
unmapped/ambiguous/inactive/no membership означает отказ. Подтверждены
`aud=support-context`, `version=support-context/1`, Core sub, act CC issuer/sub,
Core/Support cid, immutable call/context, cnf.jkt, jti/grantId, версии и actions,
post-call назначенной заявки, read-only consult и прекращение новых действий прежнего
оператора после transfer. Изменение ownership отражено сообщением `msg_93a014e2ed5a`.
Предложенные route names ещё сводятся C02 вместе с C00, не считаются утверждёнными.

Для сведения требуются явные решения:

1. Подтвердить namespace/aud/scopes и call key `{company,node,connector,nodeContactId}`;
   отличить connector интеграции Support от connection КЦ; способ trusted backchannel
   consume/status узла и server-side map адресов.
2. Свести расширение канонического Support binding и точную схему actor-resolve;
   минимальное основание Core actor уже определено: существующее ограниченное членство
   с module/object scope, без клиентской сессии, autoprov и администрирования КЦ.
3. Свести с C00 union полей команд/receipt, GET либо POST read/details и порядок
   live-link → late-final; effect key не зависит от нового actor при передаче;
   применить подтверждённую линейную точку per-operation introspection при гонке
   transfer/revoke, без глобального lease и обещания распределённой транзакции.
4. Установить TTL wrapup/postcall по политике компании и условие ticket assignment,
   закрепить nested iframe bootstrap/JWK/nonce и отдельную задачу кромки. Решение
   `msg_230c6dcdc50b` подтверждает вложенное окно, minimal public entry/assets и
   описанную границу in-flight; отсутствие PII в CC кодах/ссылках проверяется отдельно.

Ответ на второй ask `msg_5a1228078b2a` получен как `msg_1ec899c9bc72`: подтверждены
nested iframe, public bootstrap без новой роли/широкого gate, отдельная локальная
проверка кромки и линейная точка до транзакции без HTTP под DB-lock. Новый источник
или общие credentials не требуются: C02 выбирает existing Core leaf/минимальное расширение.

Отсутствие утверждения C02 не разрешает runtime-реализацию; документ даёт конкретное
предложение для сведения, а не объявляет новый механизм уже существующим.
C01 проверяется чтением источников, синтетическим примером и `git diff --check`.
При проверке примера JSON успешно разобран, `version/aud`, разные Core/CC sub,
согласованность nodeId и TTL 120 с проверены локально без HTTP/БД.
Никаких рабочих данных, правок чужих деревьев, runtime-кода, миграций, выкатки или PR
на этой фазе нет. Коммит документа является входом в приёмку C01, не завершением программы.
