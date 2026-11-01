# Первое подключение внешнего приложения

Это инструкция кандидата Product API на Source
`9eb236a4d69f0452208857ac603fd1da515f52d8`: **17 операций, 16 GET и один POST
на 16 путях; 13 user/service и четыре delegated user-only**. Единая
[таблица операций, scopes и профилей](../PARTNER_QUICKSTART.md#current-source-contract-20261101)
находится в quickstart. OAuth, Product API и docs portal
по умолчанию выключены независимо друг от друга. Подготовка этой инструкции
ограничена исходниками (SOURCE ONLY): HTTP, схема работающего сервиса, сторонний
OAuth-клиент, пилоты и эксплуатация **NOTRUN**, будущий runtime неизвестен.
Документ не подтверждает завершение исходных 20 M-этапов или 11 gates.

Все адреса `.invalid`, UUID, имена и данные здесь вымышлены. `<PLACEHOLDER>`
обозначает значение, которое нужно получить в отдельной одобренной песочнице;
это не работающий credential. Выполнение примеров требует отдельного допуска.

## Маршрут по инструкции

1. Получите комплект подключения ниже.
2. Выберите профиль и пройдите [аутентификацию](auth.md).
3. Прочитайте [объекты, оборудование и контрагентов](recipes/read-catalogs.md).
4. Пройдите цепочку [договор → объекты → документы](recipes/contracts.md),
   затем [версии → файл](recipes/documents.md).
5. Для энергетического профиля прочитайте [мониторинг](recipes/monitoring.md).
6. При обработке ответа используйте [словарь данных](data-dictionary.md)
   и [ошибки и повторы](errors.md).

Все успешные JSON-примеры содержат полный DTO, включая обязательные nullable
поля. Это иллюстрации wire-контракта, не результаты HTTP или schema validation.

## Что согласовать с владельцем пространства

Передайте владельцу назначение приложения, владельца поддержки, выбранный профиль
(пользовательский или серверный), точные HTTPS callback URI, компанию, необходимые
scopes и отдельные перечни ресурсов. Для чтения файлов укажите эту потребность
отдельно. Обратный комплект подключения должен содержать:

| Получаемое значение | Для чего нужно |
|---|---|
| HTTPS issuer, например `https://sandbox.example.invalid` | Discovery, проверка OIDC issuer и origin документации |
| Product base URL `https://sandbox.example.invalid/api/v1` и audience от владельца | Вызовы API; audience не выводят из issuer или client ID |
| Client ID, public `none` либо confidential `client_secret_basic` | Выбор способа аутентификации клиента |
| Точные зарегистрированные redirect URI | Code flow; строка callback должна совпадать |
| App и одобренная installation в выбранной компании | Разрешение этому приложению работать в этой компании |
| Разрешённые scopes и typed resource scopes | Предел доступных действий и независимые списки объектов каждого типа |
| Пользователь и подтверждаемое consent либо machine `grant_id` | Основание конкретного доступа |
| Для machine: secret, выданный по защищённому каналу | Хранить только на сервере приложения |
| Отдельный вход в `/developer/api` и docs grant | Просмотр защищённой документации; это отдельное согласие |
| Правила поддержки, фактические лимиты и окно будущего пилота | В этой инструкции нет обещанных RPS, SLA или размера файлов |

Регистрация client, создание app, approval installation и resource scopes, выдача
или отзыв grant принадлежат владельцу пространства. Внешний разработчик не должен
получать Core admin bearer или вызывать внутренние административные endpoints.
Динамическая публичная регистрация клиентов не опубликована.

Установка связывает **owner → client/app → installation компании → resource
scopes → grant**. Consent сотрудника не заменяет approval установки, а secret
сам по себе не заменяет machine grant. Активность client/app/installation/grant,
а для machine также credential, проверяется при следующем API-вызове.

## Пять разных входов

| Профиль | Результат | Где применять |
|---|---|---|
| Core login | Core-сессия сотрудника | Страница входа и согласия в Core; пароль вводится только там |
| OIDC identity, `openid` | ID token, pairwise `sub`; `profile/email` по отдельным scopes | Вход в ваше приложение, не продуктовый Bearer |
| Delegated Code + PKCE S256 | Partner access token от имени сотрудника | Чтение и отдельный CREATE/options при достаточных текущих правах и CREATE-профиле |
| Confidential client credentials + `grant_id` | Machine partner access token без User | 11 read GET и отдельные CREATE/options из 13 user/service операций; без identity, docs и файлов |
| Public docs Code + PKCE | Отдельный `openid docs:read` grant и короткий docs cookie | Docs UI, browser/server OpenAPI и локальные assets |

Core bearer, SSO handoff, ID token и docs cookie не являются взаимозаменяемыми
учётными данными. Внешний браузерный origin не считается разрешённым по умолчанию:
текущий CORS ориентирован на origin пространства. Для внешнего UI используйте
свой сервер; прямой cross-origin сценарий требует отдельной конфигурации и приёмки.

## Scopes и ресурсы проверяются вместе

Для операции требуется пересечение scopes клиента, установки, grant и текущих прав
актора. `objects:read` разрешает действие, а typed `objects=SET{...}` ограничивает
записи. `equipment`, `counterparties`, `contracts`, `documents` имеют самостоятельные
typed grants: выдача объекта не выдаёт оборудование на нём или документы о нём.
Режимы `ALL`, `SET`, `EMPTY` относятся к конкретному типу; отсутствие разрешения
не превращается в `ALL`. Для delegated доступа дополнительно действуют текущие
членство, модули, ограничения по объектам/организации и native document ACL.

Составной метод требует **все** scopes (AND), например:

- Мониторинг: `objects:read` AND `monitoring:read`, typed objects grant.
- Объекты договора: `contracts:read` AND `objects:read`, оба typed grants.
- Документы договора: `contracts:read` AND `documents:read`, оба typed grants и User.
- Файл: `documents:read` AND `documents.files:download`, documents grant, User и file ACL.

Чтобы увидеть `equipment.objectId`, нужно независимо видеть объект. Чтобы увидеть
`contract.counterpartyId` или ссылки документа, нужно независимо видеть их цели.
`null` может скрывать ссылку; не интерпретируйте его как доказательство отсутствия.

Для CREATE/options нужны `contracts:create` и текущий CREATE-профиль установки:
разрешённый пользователь либо явно утверждённый machine grant confidential client,
с соответствующим user/service разрешением профиля. Organization, counterparty,
location и активный typeCode пересекаются с текущими ресурсными и пользовательскими
ограничениями. `contracts:read` не требуется и не заменяет CREATE authority;
успешное создание или replay не выдаёт READ. Порядок и DTO — в
[рецепте создания](recipes/contracts.md#создание-договора).

User/service в общей таблице означает допустимые виды principal, а не
автоматическую выдачу прав на все методы или внутренние операции Core.

## Первый обход

После [получения partner access token](auth.md) выполните пример `listObjects`
из [recipe каталогов](recipes/read-catalogs.md). Используйте IDs из ответов,
сохраняйте все исходные фильтры и `pageSize` при передаче непрозрачного cursor.
Обход заканчивается только на `nextCursor: null`. `total` считает доступный
отбор, не инвентарь компании; между страницами данные могут измениться.
При отказе перейдите к шагу исправления в recipe, не подменяйте его legacy API.

Для минимального walkthrough достаточно последовательно прочитать объект,
оборудование и договор, связи договора, карточку документа и разрешённый файл.
Сверьте `objectId` оборудования со словарём уже полученных объектов на клиенте.
Нет `/objects/{id}/equipment`, `/documents/{id}/versions` или фильтра
`equipment?objectId=...`: такие пути и параметры здесь не опубликованы.

## Граница текущих возможностей

Текущие чтения помогают построить разрешённую витрину. Они не заменяют полные
процессы аренды, энергоснабжения и эксплуатации: нет финансовых DTO, тарифов,
начислений, согласованных расчётов или SLA. Единственная candidate-команда —
`POST /api/v1/contracts`; варианты для неё даёт advisory GET create-options.
Изменение, согласование, загрузка документов, заявки, другие admin/write/events и
partner WS/SSE/change feed не объявлены в этом контракте. Уровни `site`, `EVSE`,
`connector` относятся к будущему
расширению; сейчас доступны `servicePoint` и станционное оборудование `station`.

Отдельные будущие пилоты, включение функций, проверка обычного сотрудника,
квот и runtime требуют своего допуска и доказательств. Эта документация ничего
из перечисленного не запускает и не объявляет принятым.

## Свидетельства исходников

Блок нужен сопровождающему; для прохождения инструкции читать код не требуется.
Текущие свидетельства на `9eb236a4d69f0452208857ac603fd1da515f52d8`:

- `clearledger/server/app/product_api/app.py:create_product_api, _policy, curated_openapi`: методы, principal kinds и AND scopes.
- `clearledger/server/app/product_api/access.py:resolve, create_preflight, options_preflight`: independent grants и разные READ/CREATE boundaries.
- `clearledger/server/app/services/partner_contract_authority.py:_require_coarse_create, select_create_domains`: текущий CREATE-профиль и пересечения ресурсов.
- `clearledger/server/app/config.py:60–81`: независимые default-off gates, не состояние работающего сервиса.

История: исходный walkthrough от 31.10.2026 на
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9` содержал 15 GET (11 user/service и
четыре user-only). Его свидетельства и отдельные принятые серии не означают
приёмку нынешних 17 операций. Канонические отчёты и их границы — в quickstart.

Далее: [аутентификация](auth.md) · [словарь](data-dictionary.md) · [ошибки](errors.md).
