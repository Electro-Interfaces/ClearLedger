# Контекст обслуживания: согласованный контракт v1 (C02)

Дата: 20.10.2026. Run Orca `run_bff66284ed19`. Статус: договор реализации,
не утверждение о готовности кода или рабочего подключения.

Основания: план `../handoff/20261020/support-context-plan.md`, C00 в TSupport
`8b076ef45a3b2d762e2733806a8f4283278e2ad3`, C01 в ClearLedger
`da6aa6c34c4bb2cd740f9cf75b04d1fa4716c9a8`. Оба отчёта проверены, их задачи завершены.
Этот документ разрешает оставшиеся расхождения их предложений и имеет приоритет
над несовпадающими примерами/путями C00/C01. Общая матрица A01–A18 остаётся обязательной.

## 1. Владельцы и совместимость

- Support: context, точный binding оператора, предметные данные/права/процесс,
  команды/квитанции, связь live/final, интерфейс обслуживания.
- Core: вход пространства, связь компаний, проверка своего actor и продуктов,
  ограниченное делегирование/introspection, собственные реестры/зарядки.
- Node: приём/медиа, запуск prepare, факты звонка, текущий оператор и допуски,
  одноразовый admission, безопасное встраивание окна.
- CC server: прежнее распределение и управление; новый contextRef, личный grant,
  предметные UUID, клиентское досье и command receipt к нему не отправляются.
- ecosystem-deploy: только шаблон точного bootstrap/ресурсов/заголовков кромки,
  локальная проверка, инструкции включения; без изменения действующих стеков.

Новая возможность opt-in, выключена без явной настройки. Обычные Support SSO/роуты,
Node card/итог/вебхуки и КЦ продолжают работать. Необязательное расширение финального
события меняется вместе со схемой и версией его API; CC stream без фактического
изменения его wire contract не повышать произвольно. I12 обязан явно назвать
изменяемую версию и доказать совместимость, а не молча расширить протокол.

## 2. Общая схема идентичности

Во всех JSON нового API `version:"support-context/1"`, `schemaVersion:1`.
Неизвестные поля запросов запрещены. В JWT `version:"support-context/1"`;
числовая схема относится к HTTP DTO, не подменяет issuer/aud/scopes.

```ts
type CallRef = { nodeId: string; connectorId: string; nodeContactId: string };
// connectorId — Support connector телефонии; connectionId — другое, подключение КЦ.
// nodeContactId — разговор, contactRef — человек в Support.
type CallKey = { coreCid: string; cid: string; callRef: CallRef };
type SourceState = 'loading'|'available'|'empty'|'partial'|'unavailable'|'permission_denied';
type Block<T> = { state:SourceState; source:string; asOf:string|null;
  data:T|null; reason:string|null };
type Count = { value:number|null; source:string;
  period:{from:string|null;to:string;timezone:'UTC';timeField:string};
  identity:'phone'|'support_contact'|'core_person'|'selected_object';
  definition:string;complete:boolean };
```

Уникальность prepare, live-link, effect и final fact включает company + nodeId +
connectorId + nodeContactId. Отображение Core company → Support company проверяется,
UUID двух приложений не отождествляются. `contextRef` случайный `scx_` + 256 бит
base64url; это ссылка, не право доступа. `threadRef`, `ticketRef`, `personRef`,
`objectRef`, `equipmentRef`, `chargingConnectorRef` самостоятельны.

Телефон только в доверенном prepare, внутри пространства. В последующих личных
операциях нет поиска произвольного номера. Один context относится к одному call;
один call закрепляется за одной заявкой, несколько calls/threads могут дополнять
одну заявку. Второе дело не создаётся скрытым перелинкованием первого.

## 3. Транспорт и маршруты (окончательный выбор)

Личные операции POST, context/cursor/селекторы в JSON body, не в URL.
Все ответы с данными/допуском `Cache-Control: private, no-store` и
`Referrer-Policy: no-referrer`. Запрос до 64 KiB; summary до 128 KiB,
details до 384 KiB. Ошибки не раскрывают внутренние SQL, токены и чужие сущности.

| Владелец | Путь | Вызывающая сторона |
|---|---|---|
| Core | `POST /api/eco/support-context/v1/prepare` | Node, именной интеграционный ключ своей компании с явно разрешённой подготовкой |
| Core | `POST /api/eco/support-context/v1/admit` | Новое окно, одноразовый code и DPoP ключ этого окна |
| Core | `POST /api/eco/support-context/v1/renew` | То же окно, действующий/допустимый к обновлению grant + новая проверка основания |
| Core | `POST /api/eco/support-context/v1/postcall` | То же подтверждённое окно: переход на отдельное право назначенной заявки, не продление live-досье |
| Core | `POST /api/eco/support-context/v1/introspect` | Только доверенный Support service, текущий grant identity/digest |
| Core | `POST /api/eco/support-context/v1/service-token` | Именной машинный ключ Support своей компании с `support-context.introspect`; только фиксированный service scope |
| Support | `POST /api/v1/eco/support-context/v1/prepare` | Только Core service `svc=support-context.prepare` |
| Support | `POST /api/v1/eco/support-context/v1/actor-resolve` | Только Core service `svc=support-context.actor-resolve`; leaf, только собственная БД |
| Support | `POST /api/v1/support-context/v1/read` | Личный scoped DPoP grant |
| Support | `POST /api/v1/support-context/v1/details` | Личный scoped DPoP grant |
| Support | `POST /api/v1/support-context/v1/select-object` | Личный scoped DPoP grant, версия и idempotency |
| Support | `POST /api/v1/support-context/v1/actions` | Личный scoped DPoP grant, версия и idempotency |
| Support | `POST /api/v1/support-context/v1/receipt` | Личный актуальный scoped DPoP grant |
| Node | `POST /cc/v0/me/contacts/{nodeContactId}/support-admission` | Существующее окно узла, его DPoP/session и публичный JWK нового iframe |
| Node | выделенные `consume/status` backchannel | Только закреплённый Core service `aud=node-support-admission`, не admin и не CC server |

Node реализует два выделенных внутренних метода consume/status в своём API
под namespace `/support-context/v1/admission/`, фиксирует точный listener/path
в контракте I12 и сообщает I11 до integration. Адрес берётся из доверенной
конфигурации пространства, никогда из браузерного URL. Это единственная деталь
transport placement, которую владельцы обязаны согласовать до теста стыка;
смысл и схемы методов ниже фиксированы.

Браузер видит Support URL с префиксом пространства:
`/support/api/v1/support-context/v1/...`; gateway срезает только `/support`.
Человеческие и служебные route/auth отделены от legacy middleware; ни широкий
Support JWT, ни service prepare не дают доступ к личным operations.

Источники Core: сохранить существующий конечный leaf
`POST /api/eco/support/customer-context` и identify как источник данных сборщика.
Нужное для v1 строгое выбранное person/candidates поведение реализовать минимальным
совместимым расширением/новым leaf с переиспользованием того же SQL, без обратного
вызова Support и без нового независимо редактируемого реестра. Существующий именной
ключ Support проверяет компанию и карту приложений; human grant не становится этим
ключом. Новый source JWT/refresh-secret протокол не требуется только ради переноса
существующего leaf: это не самостоятельный объём v1. Если владельцы найдут реальную
необходимость отдельного source path/scope, сначала согласуют её с координатором.

## 4. Prepare и сборка

Node после сохранения calls запускает prepare до предложения/ответа, не ожидая
Core/Support для телефонии. Сохраняет и восстанавливает связь после рестарта;
повторная подготовка того же call не создаёт новый context. Именной ключ Node
не даёт человеческих команд; адрес/узел/коннектор/компания проверяются конфигурацией
на стороне Core. Отсутствие новой настройки оставляет feature выключенной.

```json
{"version":"support-context/1","schemaVersion":1,"callRef":{"nodeId":"node-demo-a","connectorId":"40000000-0000-4000-8000-000000000001","nodeContactId":"call-demo-17"},"phone":"+79990000001","startedAt":"2026-10-20T12:00:00Z","direction":"inbound"}
```

Core фиксирует доверенное соответствие и направляет service prepare в Support.
Support атомарно сохраняет context и отвечает 202 с `contextRef`, `callRef`,
`contextVersion`, `state:"preparing"`, preparedAt/expiresAt и retryAfterMs.
Чтение/подготовка не вызывают ingestCall/resolveContact, не создают новый thread,
ticket, call_record или внешнюю доставку. Worker сборки восстанавливается по
pending contexts; сетевой вызов не держит DB-lock. Предельный context TTL 24 часа
от prepare, read его не продлевает; durable связи/квитанции сохраняются по политике.

Сборка по источникам: identity/candidates, раздельная история/обещания, заявки,
зарядки, объект, оборудование, знания. Каждому блоку присваиваются source/asOf/state.
Нельзя превращать unavailable в 0/«не найден». При неоднозначности нет автоматически
подтверждённого человека; смешанная phone-история явно отличается от выбранного person.
Последняя сессия — только кандидат станции. Детали дозагружаются по section/cursor,
предел страницы 100, точный total/hasMore и устойчивый cursor объявлены явно.

## 5. Делегирование, binding, DPoP и отзыв

Canonical exact binding в Support/cc_agent_identities:
`(cid,nodeId,connectorId,ccIssuer,connectionId,ccOperatorSub,validFrom,validUntil)`
→ активный Support user → существующий `eco_user_id`. Новый scoped путь не использует
fallback по имени/email/голому UUID и не назначает права по старой неполной записи.
Binding имеет версию, а новый API администрирования/настройки проверяет существующее
право управлять допусками; это не прямой SQL-only способ включить продукт.
Core не заводит второй справочник, людей или членства при admit.

Node выдаёт одноразовый opaque admission 30 секунд по текущему назначению и
подтверждённому браузерному ключу. Consume принимает code и назначение public JWK,
атомарно помечает использование; status возвращает актуальное состояние call,
assignmentVersion, CC issuer/connection/operator, допустимые actions и wrapup deadline.
Оба метода доступны только Core service с фиксированными issuer/audience/сроком
и своей компанией/node. При status не возвращаются телефон, имя или досье.

Core по consume + Support actor-resolve проверяет своего actor, активность/версию
его сеанса/членства, продукт и module/object scope. Возвращает grant <=120 секунд:

```json
{"version":"support-context/1","iss":"elsyplus","aud":"support-context","sub":"10000000-0000-4000-8000-000000000001","act":{"iss":"https://cc.example.invalid","sub":"operator-demo-a"},"scp":"support_context","coreCid":"20000000-0000-4000-8000-000000000001","cid":"30000000-0000-4000-8000-000000000001","callRef":{"nodeId":"node-demo-a","connectorId":"40000000-0000-4000-8000-000000000001","nodeContactId":"call-demo-17"},"connectionId":"connection-demo-a","contextRef":"scx_demo","grantId":"grant-demo-a","jti":"token-demo-a","assignmentVersion":4,"permissionsVersion":2,"bindingVersion":3,"phase":"connected","actions":["context.read","context.details","context.select","context.clarify","ticket.create","ticket.append"],"cnf":{"jkt":"demo-public-key-thumbprint"},"amr":["pwd","otp"],"iat":1792497600,"nbf":1792497600,"exp":1792497720}
```

Это пример claims, не исполняемый токен. Core service-family имеет отдельный `svc`
и `sub=service:<scope>`, тоже фиксированные version/aud/cid/coreCid/call и jti/iat/nbf/exp.
Для prepare/actor-resolve `aud=support-context`, для introspection Core
`aud=core-support-context`, `svc=support-context.introspect`. Точный bootstrap
доверенного Support service использует конфигурацию пространства, не токен браузера.

Support проверяет строгие RS256/JWKS issuer/aud/kid/обязательные claims и текущий
grant binding. Unknown kid — отказ, без fallback на первый ключ. Actor требует
`Authorization: DPoP <grant>` и ES256 proof: public JWK/thumbprint, подпись, htm/htu,
ath, короткий iat/jti и отсутствие replay. Нельзя лишь проверить наличие cnf.
Replay/одноразовый code/отзыв должны переживать рестарт и проверяться между процессами
через согласованное хранилище. Canonical public URL для proof берётся из доверенной
настройки прокси/приложения, не произвольного Host/X-Forwarded-* пользователя.

Линейная точка разрешения операции — положительная online introspection до локальной
business transaction; без положительного кэша прав в v1. Затем под локальным lock
повторно проверить active/role/membership/bindingVersion/assignment записи Support.
HTTP под DB-lock запрещён. Уже допущенный in-flight запрос может закончиться после
конкурентного revoke; новая операция после revoke/transfer не допускается. Не обещать
распределённую атомарную отмену, которой нет. Race-test доказывает именно эту границу.

Оператор offering читает только конкретно предложенный call. Connected owner получает
пересечение возможностей; consult только чтение. Transfer повышает assignmentVersion,
прежний оператор не получает новые действия. Wrapup ограничен действующим deadline
узла (passport.disposition.wrapupSec), а не новым независимым таймером на 15 минут.
Postcall — отдельный ticket-specific допуск при действительном текущем назначении,
без общего dossier/history/charging; общий максимальный период из политики, default
60 минут от endedAt, configurable. Он не возобновляет истёкший full-context grant.
Подрядчик/производитель получает только разрешённую свою заявку и техническую проекцию
оборудования по существующим договорным ACL, не человеческий профиль/баланс/зарядки.

## 6. Встроенное окно и кромка

Целевой вариант — CC → существующий sandbox iframe Node → iframe пространства Support.
Не менять его на popup/новую вкладку и не добавлять allow-popups ради обхода gate.
Телефония/медиа остаются в Node; Support iframe содержит предметный контекст и действия.

Public entry ровно `/support/context-entry`; выделенные compiled assets только
`/support/context-assets/`. Это минимальный bootstrap без персональных данных и
обычного Support shell. Core session/cl_gate не требуется только для этих путей;
обычные `/support/`, `/support/assets/`, admin, uploads остаются под прежними правилами.
API уже проходит через `/support/api`; новый namespace защищён собственным grant.

Iframe генерирует non-extractable ключ в памяти, посылает public JWK и случайный nonce
непосредственно parent Node. Node запрашивает admission по своему прежнему DPoP-сеансу
и передаёт opaque code только этому iframe. Обе стороны проверяют origin/source/nonce
и строгий тип сообщения, используют точный targetOrigin. Shell КЦ не посредник этого
обмена. В адресной строке нет phone/JWT/admission/ticket UUID; нет access/refresh в
localStorage/sessionStorage и нет изменения обычной сессии Support.

Внутренние Core/Support/Node URL и публичный origin пространства различаются.
Entry URL строится только по доверенной конфигурации, fixed path, HTTPS; loopback HTTP
допустим в явной изолированной тестовой среде. Docker hostname не выдаётся браузеру.
CSP Node разрешает только нужный origin вложенного frame; CSP entry/kромки учитывает
всю реальную цепочку ancestors с закреплёнными origin, без общего wildcard для КЦ.
Обычные ресурсы не открываются из-за нового location/regex/rewrite.

I13 использует отдельный transport/container и существующие представления
ContextPanel/Dialogs/Ticket. Допустима общая прикладная/представительная extraction
с прежними defaults; не копировать рабочее место и не делать его редизайн.
Query keys нового окна включают company/context/actor и изменяемые параметры.
Отзыв/unmount/смена контекста очищает чувствительный UI/cache; отказ не открывает
общую админскую форму и не вызывает скрытый legacy bearer fallback.

## 7. DTO контекста и операций

```ts
type Selection = {
  personRef:string|null;contactRef:string|null;
  identityState:'unknown'|'ambiguous'|'candidate'|'operator_selected';
  objectRef:string|null;supportObjectRef:string|null;equipmentRef:string|null;
  chargingConnectorRef:string|null;objectState:'unselected'|'candidate'|'operator_confirmed';
  confirmedBy:string|null;confirmedAt:string|null;
};
type Context = {
  version:'support-context/1';schemaVersion:1;contextRef:string;callRef:CallRef;
  contextVersion:number;state:'preparing'|'ready'|'partial'|'unavailable'|'expired';
  preparedAt:string;updatedAt:string;expiresAt:string;threadRef:string|null;
  selection:Selection;capabilities:string[];
  blocks:{identity:Block<unknown>;history:Block<unknown>;tickets:Block<unknown>;
    charging:Block<unknown>;object:Block<unknown>;equipment:Block<unknown>;knowledge:Block<unknown>};
};
```

Конкретные whitelist DTO блоков — типы C00 раздел 3: identity candidates, history
counts/promises, tickets со status/version/SLA, charging с period/definition,
object, Equipment и Article. Это явные DTO, не SQL `e.*`/`so.*` и не произвольный JSON.
В реализации `unknown` из сводного примера выше заменяется этими типами/схемами.
В частности SSH/IP/credentials/internal drafts/лишние сведения чужих участников не выдаются.

Краткие типы блока не ограничивают цель компактной карточкой узла. При разрешённом
доступе обеспечить информационную полноту существующего профиля Поддержки: сведения
клиента/организации, дата регистрации/активность и баланс при разрешённой выдаче,
раздельные обращения/звонки/заявки/обещания, полная сводка зарядок и их детализация,
объект/оборудование/исполнитель/применимые знания. I10 фиксирует явный whitelist
этих полей, I13 использует его в существующих представлениях, V20 проверяет parity
по источникам. Отсутствующее право/сведение отмечается состоянием, а не молча
исчезает из нового API или заменяется ограниченной последней сессией.

`read`: body `{version,schemaVersion,contextRef}` → Context; без бизнес-эффектов.
`details`: дополнительно `section` из history/charging/object/equipment/tickets/knowledge,
`cursor` null/string, `limit` 1..100; ответ с contextVersion, block, nextCursor/hasMore.
Cursor привязан к company/context/section/selection version; смена selection даёт cursor_stale.

`select-object`: Idempotency-Key UUID и `If-Match: "ctx:<contextVersion>"`;
body contextRef, objectRef, optional equipmentRef/chargingConnectorRef, confirmed=true.
Проверяются реестр/компания/принадлежность оборудования объекту; последнее место зарядки
само ничего не подтверждает. Меняется контекст, не master registry. Ответ содержит новую
selection/contextVersion и invalidatedSections. После связанной заявки изменение её
предмета только штатным явно разрешённым процессом, не скрытой правкой select.

`actions`: Idempotency-Key = commandRef UUID, тот же If-Match; body
`{version,schemaVersion,contextRef,commandRef,action,input}`. Union:

- create: title/description/priority/type и разрешённые поля формы существующего tracker;
- append: ticketRef, expectedTicketVersion, note, internal=true;
- clarify: выбранный personRef и/или уточнение с источником «со слов клиента».

Разрешения: context.read/details/select/clarify, ticket.create/append. Изменение статуса,
переназначение и управление справочниками не выдаются автоматически. Штатный workflow
сам определяет исполнителя, SLA и эскалации. Производитель имеет иную маску данных.

```ts
type Receipt = { version:'support-context/1';schemaVersion:1;
  receiptRef:string;commandRef:string;contextRef:string;contextVersion:number;
  action:string;state:'pending'|'applied'|'rejected';appliedAt:string|null;
  actorRef:string;threadRef:string|null;ticket:{ref:string;number:string;version:number}|null;
  error:{code:string;retryable:boolean}|null };
```

`receipt`: selector commandRef или receiptRef, актуальные права, 200 Receipt либо
404 недоступная/неизвестная команда. Replay после отзыва не открывает квитанцию.
Номер/UUID результата остаётся в пространстве. Существующая явно разрешённая паспортом
передача технического ticket.number через legacy Node/CC retention — отдельный прежний
контракт, не разрешение передавать новый receipt/UUID/содержание в CC. Её сохраняют и
проверяют отдельно, не распространяют на остальные поля.

## 8. Команды, процесс и live/final

Бизнес-эффекты выполняются общими функциями старого и нового входа Support,
не self-HTTP и не второй реализацией создания/назначения/сообщений.
Первое действие может завести contact/thread, сохранив исходное startedAt для SLA
регистрации; не выбирать thread молча по телефону/суткам. Create и append выполняют
штатную проверку tracker/договора/предмета/пользователя и фиксируют actor, событие,
receipt и outbox вместе. Append не пересоздаёт ticket и не сбрасывает исходный SLA;
разрешённый workflow resume из waiting_customer учитывается как действующий процесс.

Эффект уникален по canonical call + commandRef, а не по новому actor после передачи.
Hash включает canonical body/action/версии, не очередной JWT/DPoP proof. Сначала текущие
права, затем committed receipt/hash, затем expected versions. Совпавший replay возвращает
прежний результат, другая команда со старой версией откатывается целиком.
TicketVersion должен замечать изменения штатных писателей, не только нового окна.
Сетевого запроса под business DB-lock нет.

Внешний tracker не объявляется созданным по одному локальному HTTP 200. Для native
и выбранного внешнего/mirror процесса нужна сохранённая корреляция/outbox/состояние
доставки и безопасный повтор. При неопределённом внешнем результате нельзя слепо
создать ещё раз или молча переключить tracker: Receipt pending и reconciliation.
Тест использует собственный HTTP tracker, не рабочий HubEx/письма.

Live binding допускает отсутствие call_record до реального final. Не вставлять
фиктивный законченный звонок ради NOT NULL legacy voice_ticket_links. Длительность,
запись и факты приходят отдельной подписанной доставкой `call.completed`.
V1-связь ищется по доверенному canonical call; optional supportContext в новом факте
проверяется против него. Новые поля события версионируются и описываются I12.
Отсутствие live binding сохраняет действующее legacy поведение, включая старые узлы.

Если live binding есть: сначала приём/обновление фактов именно этого звонка, связь с
закреплённым thread/ticket, одна техническая запись итога и отдельная final receipt.
Существующий ранний return по voice_ticket_links не должен поглотить эти операции.
Final не создаёт второй ticket, не сбрасывает его SLA/assignment/status, не заменяет
подтверждённый предмет устаревшей подсказкой старой карточки. Противоречащий явный
ticket selector даёт конфликт, не тихое перелинкование.
Command receipt и eventId/hash receipt независимы; семантический повтор факта под
другим eventId тоже не дублирует сообщение/звонок. Рестарт не теряет связь.

Legacy `voice_ticket_links` и call_records/provider/time uniqueness не считаются
доказательством v1 identity: два разных node/connector calls одного company могут
совпасть по телефону/времени. I10 должен сохранить legacy поведение и ввести точную
v1 namespace/unique связь без недоказанной склейки провайдеров и без потери истории.
Счётчики всей выборки отдельно от длины страницы. Происхождение/период/границы
дедупликации объявлены; при недоказанной межпровайдерной корреляции нет ложной точности.

## 9. Ошибки, проверки и порядок включения

Общий error: `{version,schemaVersion,error:{code,retryable},requestRef}`.
400/422 неверный запрос/selection/неподдержанный tracker; 401 token/DPoP/expiry/replay;
403 unmapped/forbidden/revoked/action; 404 чужой/неизвестный scoped ресурс;
409 idempotency/call/ticket/cursor/phase conflict; 412 version conflict;
426 version unsupported; 428 version required; 429 rate; 503/504 источник/право недоступны.
Раскрывать currentVersion только для уже доступного ресурса. Личные 401 используют
DPoP challenge, не WWW-Authenticate Bearer. Никакого fallback на admin/legacy bearer.

Сквозная приёмка S01–S08 в acceptance-scenarios.md и A01–A18 общего плана:
настоящие Core/Support/Node HTTP+SQL+подписи, два пространства, реальный nested iframe
через локальную кромку, основной и старый маршруты, desktop+390. Без отключения CSP,
web security, mock claims и подменённого browser API вместо интеграции. Изолированные
фикстуры допустимы, рабочие DSN/ВАТС/массовые Docker teardown — нет.

Отдельно проверить durable DPoP/admission replay, unknown kid, cross-issuer/sub,
отзыв/transfer/in-flight, postcall/vendor mask, ambiguous identity, object refresh,
live-create+late-final+retry, точные counts и сохранение исходного SLA. БД/логи/HTTP/
postMessage/storage КЦ проверяются уникальными маркерами данных/UUID/секретов.

Порядок поставки исходников: Support+Core новые API/схемы с feature off, отдельный
context bundle и кромка, Node feature с корректными машинными scopes/публичными URL/
binding. Включение по компании только после сквозной проверки и явной настройки.
Откат выключает новую возможность, не удаляя durable receipts/live links и не теряя
поздние факты; изменение миграций откатывается по проверенному плану на копии.
Текущая задача готовит PR/инструкции, не выполняет этот порядок на рабочих стеках.

## 10. Точные внутренние DTO стыков I10/I11/I12

Уточнение v1 перед реализацией, не новая возможность. Общие version/schemaVersion
обязательны во всех телах. Не вводить самостоятельно вторые имена этих полей.

### Node admission

Для определённости backchannel обслуживается CC HTTP listener узла (тот же
опубликованный node origin), но отдельным router:
`POST /cc/v0/support-context/v1/admission/consume` и
`POST /cc/v0/support-context/v1/admission/status`. Эти ручки не принимают CC bearer,
window token или admin session вместо выделенного Core service JWT.
В доверенной настройке Core хранится base origin узла, пути фиксированы.

```ts
type NodeAdmissionConsumeIn = {
  version:'support-context/1';schemaVersion:1;
  nodeId:string;admissionCode:string;jkt:string;
};
type NodeAdmissionStatusIn = {
  version:'support-context/1';schemaVersion:1;
  admissionRef:string;contextRef:string;callRef:CallRef;
  connectionId:string;act:{iss:string;sub:string};
};
type NodeAdmissionState = {
  version:'support-context/1';schemaVersion:1;
  admissionRef:string;contextRef:string;callRef:CallRef;
  connectionId:string;act:{iss:string;sub:string};jkt:string;
  active:boolean;revoked:boolean;phase:'offering'|'connected'|'consult'|'wrapup'|'ended';
  assignmentVersion:number;allowedActions:string[];amr:string[];
  phaseDeadline:string|null;endedAt:string|null;
};
```

Consume 200 возвращает NodeAdmissionState, атомарно потребляя code; повтор 409
admission_replayed. Неверный/чужой code не раскрывает другое назначение.
admissionRef живёт как техническая ссылка проверки текущего права, не как bearer.
Status 200 может вернуть active=false и пустые allowedActions, либо 404 для чужой
или отсутствующей ссылки. phaseDeadline — срок предложения/постобработки, не
придуманный второй таймер. После конца wrapup phase=ended и active=false для live-допуска.
revoked=true обозначает явный security/connection/operator отзыв, не естественный
конец разговора или истечение короткого access token. Эта разница нужна для
независимого основания ticket-postcall; статус не восстанавливает права live.

amr берётся из действительно проверенного CC login/token-exchange и переносится
в запись admission. Нельзя синтезировать otp из одного requireMfa=true паспорта.
Если старый window token не содержит доказательства, выполнить свежий штатный обмен
или отказать допуску контекста; телефония продолжает работать. held/parked/consulting
основного владельца отображаются в разрешённую фазу по действительному назначению;
приглашённый консультант имеет phase=consult и только чтение.

Окно создаёт admission запросом к Node personal route с телом
`{version,schemaVersion,jwk:<public EC P-256 JWK>}`. Ответ:
`{version,schemaVersion,admissionCode,nodeId,spaceOrigin,entryPath,expiresAt}`,
entryPath ровно `/support/context-entry`. В consume Core передаёт jkt своего
проверенного DPoP proof и сверяет jkt результата, а не доверяет произвольному JWK тела.

### Support actor-resolve

```ts
type ActorResolveIn = {
  version:'support-context/1';schemaVersion:1;
  contextRef:string;callRef:CallRef;connectionId:string;act:{iss:string;sub:string};
  phase:'offering'|'connected'|'consult'|'wrapup'|'postcall';
  assignmentVersion:number;
  expectedBindingVersion?:number;expectedPermissionsVersion?:number;
  ticketRefs?:string[];
};
type ActorResolveOut = {
  version:'support-context/1';schemaVersion:1;
  contextRef:string;callRef:CallRef;connectionId:string;
  bindingRef:string;bindingVersion:number;permissionsVersion:number;
  coreActorSub:string;supportUserRef:string;active:true;membership:true;
  capabilities:string[];fieldMask:'operator'|'consult'|'assigned_ticket'|'vendor';
  ticketRefs:string[];
};
```

cid/coreCid и связанные actor/call/connection/context поля закреплены service JWT;
несовпадение тела даёт отказ. Сначала проверяется существующий context и exact
binding; после этого исходные user/eco_user_id и действительные active/member/role.
Unmapped/ambiguous/inactive/expired binding — 403 actor_unmapped/actor_forbidden,
а не successful active=false с подставленным пользователем. Это leaf без HTTP Core.
Дополнительные expected versions при revalidation обязаны совпасть или допуск
закрывается. permissionsVersion — версия управляемого набора прав binding;
актуальные user role/membership и прикладной ACL всё равно читаются заново.

Core хранит bindingRef/bindingVersion/permissionsVersion и собственный
User.token_version при admit; не превращает их в редактируемую копию mapping.
TicketRefs в postcall проверяются по связи контекста и текущему назначению,
не принимаются по одному утверждению body. Первоначальный live actor-resolve
не требует уже созданной заявки: подготовленный context пока без неё.

### Core admit и introspection

Admit input: `{version,schemaVersion,nodeId,admissionCode}` + DPoP proof нового
iframe (без ath, пока access token ещё нет). Ответ:
`{version,schemaVersion,token,tokenType:'DPoP',expiresIn,grantId,contextRef,phase,actions}`.
JWK выбирается из проверенной подписи proof, не из неподписанного actor/body.
Renew input: `{version,schemaVersion,grantId,admissionCode,nodeId}` с действительным
новым admission и тем же DPoP ключом. Истёкший access сам по себе не является правом
обновления. Для нового admit после истечения требуется обычное подтверждённое основание.

```ts
type IntrospectIn = {
  version:'support-context/1';schemaVersion:1;
  token:string;contextRef:string;callRef:CallRef;
};
type IntrospectOut = {
  version:'support-context/1';schemaVersion:1;
  active:true;grantId:string;contextRef:string;callRef:CallRef;
  coreActorSub:string;supportUserRef:string;bindingRef:string;
  bindingVersion:number;permissionsVersion:number;assignmentVersion:number;
  phase:'offering'|'connected'|'consult'|'wrapup'|'postcall';
  actions:string[];fieldMask:'operator'|'consult'|'assigned_ticket'|'vendor';
  ticketRefs:string[];expiresAt:string;
  objectScope:string[]|null;ownOrganizationId:string|null;
};
```

Токен передаётся только внутренним доверенным HTTP Support→Core, не в URL/логи.
Core сам проверяет подпись/claims исходного токена и digest сохранённого grant;
body не может заменить его actor. Проверяет current NodeAdmissionState, актуальный
Support actor-resolve, Core user/token_version/member/product/scope и версии.
Неуспех — 401/403/404/503 с обычной error-схемой, не cached active=true.
Support непосредственно перед эффектом сверяет актуальный ответ и свои DB-строки.
Полученные права — пересечение подписанных и текущих, не расширение токена.

objectScope — эффективный canonical Core scope по service_locations.id: null
означает всю сеть своей компании, пустой список — отсутствие доступных объектов.
ownOrganizationId — своё юрлицо Core, не внешний контрагент. Большие списки не
включаются в JWT, а читаются свежими при introspection. Support сопоставляет Core
refs с проекциями и применяет эти ограничения ко всем блокам, деталям и командам.
Неразрешимая часть даёт permission_denied/partial, не выдачу всей компании или 0.
Ограниченного актёра нельзя целиком отклонить ради упрощения: положительный сценарий
по его разрешённому объекту обязателен, чужой объект/юрлицо недоступны.

Инженер/подрядчик может продолжать обычную назначенную работу в существующем
рабочем месте Support. Для этого не создаётся фиктивный CC sub или широкая сессия
контекста: новое окно не расширяет его права и не выдаёт dossier. Если используется
ticket-specific postcall окно, оно требует своего реального основания назначения
и выдаёт только техническую маску. V20 проверяет и допустимую назначенную задачу,
и отказ доступа к личному/чужому контексту, не заменяя это тестом admin.

Все machine DTO содержат только служебные ссылки/подтверждения; содержимое досье
не входит в Node consume/status/actor-resolve/introspection. До кода доверенного
Support→Core introspection транспорта I11 обязан назвать способ получения service
токена/аутентификации I10: отдельная ограниченная настройка, не API человеческого
токена и не общий admin ключ. Реальная настройка входит в I11, не остаётся test-only hook.

Зафиксированный bootstrap для этого транспорта: Support меняет свой именной Core key
с областью `support-context.introspect` через `/service-token` (X-Cloud-API-Key,
body только version/schemaVersion). Ответ с Bearer service token на <=120 секунд,
`aud=core-support-context`, `svc=support-context.introspect`, `sub=service:support-context.introspect`,
Core company ключа, разрешённая Support company из канонической карты, keyId/jti/iat/nbf/exp.
Ключ/токен не выдаются окну. При introspection проверяются актуальные keyId/revocation,
связь компаний/продукт и исходный человеческий grant. Этот фиксированный обмен не
принимает arbitrary audience/scope/actor/company и не выдаёт человеческие права.
Существующему ключу `voice.identify` область записи/делегирования не добавляется молча.
В конфигурации Support выбирается источник/ключ именно компании данного context;
при отсутствии своей настройки — явная недоступность, без использования ключа соседа.

### Ticket-specific postcall (уточнение по вопросу I11)

Обычное рабочее место Support для инженера не заменяет отдельное право оператора
продолжить назначенную заявку в новом окне. Core `/postcall` принимает
`{version,schemaVersion,grantId,ticketRef}` и свежий DPoP proof ключа подтверждённого
iframe (без ath на этапе выдачи). Core по сохранённому grant record проверяет
оригинальные actor/jkt/call/context/admissionRef, текущие Core user/token_version/
membership/products, canonical Support binding и actor-resolve phase=postcall,
ticketRefs=[ticketRef]. Заявка обязана быть связана с context и действительно
назначена этому участнику по действующему workflow/ACL.

Node status должен подтвердить endedAt и revoked=false. phase=ended/active=false
означают закрытый live-допуск, не запрет независимого assigned-ticket основания.
Явно отозванный source grant/binding/actor не возрождается. Истёкший короткий access
не равен отзыву: свежий proof сохранившимся private key + текущее назначение являются
новым основанием, строго в пределах hard deadline. Нельзя вводить произвольный
ticket selector или менять actor из body. Неуспех проверки — отказ, без legacy fallback.

Результат той же формы выдачи token, но новый grant:
`scp=ticket_postcall`, `phase=postcall`, один ticketRefs, actions только
ticket.read/ticket.append, fieldMask assigned_ticket (либо ещё более узкая vendor).
TTL <=120 секунд, hard deadline min(context expiry, endedAt+политика postcall,
default 60 минут). Повторное `/postcall` не сдвигает hard deadline. Introspection
постоянно перепроверяет это назначение и scoped ограничения; Node live allowedActions
не подставляются вместо бизнес-права и не становятся разрешением на полное досье.

Support read/details в этом режиме принимают ticket.read и возвращают только
связанную техническую заявку/её оборудование/разрешённые знания; identity, charging,
общая история и другие заявки закрыты. Create/select/clarify запрещены.
При снятии назначения следующее чтение/append отвергается и UI очищает данные.
Встроенный UI должен давать реальный переход в этот режим и работу с назначенной
заявкой после завершения разговора; одного недостижимого backend endpoint недостаточно.
