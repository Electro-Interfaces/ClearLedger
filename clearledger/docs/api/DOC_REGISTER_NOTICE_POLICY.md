# Уведомление о регистрации документа

Статус: подготовлены исходники, **SOURCE ONLY / NOTRUN**. Ни импорт приложения,
ни сбор тестов, ни PG/SQL, ни транспорт при подготовке не выполнялись.

Только `register_doc` явно передаёт доверенный `doc_notice_id` в `log_audit`
с `notification_timing="after_root_commit"`. Отдельный frozen `DocNotice` содержит
ровно UUID компании и документа. В очередь не попадают ORM, Session, claims,
capability, имя автора или снимок реквизитов. UUID документа допускает штатный
подтип драйвера и сохраняется как неизменяемое значение UUID; прежний строгий
UUID-guard компании сохранён. AuditEvent продолжает хранить прежний журнал.

После фактического commit принадлежащего вызывающему корня очередь очищается
до callback. Сохраняются правила SAVEPOINT, rollback поддерева, sticky poison,
повторного использования Session, reentrant callback и подавления ошибок
планирования после commit. Это память процесса: гарантий доставки и повтора нет.
Регистрация, счётчик, публикация outbox, финальная проверка, seal и commit прежние.

Доставка читает существующее правило, не создавая defaults через `rules_for`.
Начальная аудитория даёт только UUID кандидатов. Непосредственно перед **каждым**
SMTP-вызовом новая собственная Session заново читает категорию, enabled,
via_email и аудиторию через существующий `_recipients`, включая admins-only.
Затем нужны текущий User/email, явное членство UserCompany даже для superadmin,
тот же `assert_company_product(..., "docs")`, текущая карточка той же компании
и тот же `_can_doc(..., "read", record_break_glass_use=False)`. Право DOWNLOAD
не требуется; break-glass use_count/last_used_at и аудит использования не меняются.
Никакой новой политики Doc organization/object этот адаптер не вводит.
Отсутствующие/удалённые/чужие ссылки подавляют письмо без возврата к снимку.

Фон не выдаёт JWT за получателя. Публичный `native_claims_context(None, None)`
убирает унаследованные claims/visit, а публичные getters/setters сохраняют и
восстанавливают object scope и organization в finally. Это действует при успехе,
отказе, SQL/SMTP-ошибке и отмене. Предыдущий медленный SMTP не сохраняет
identity map User/Member/Role/Doc и grants для следующего получателя.

Письмо содержит только фиксированную метку `doc.register`, **текущий разрешённый**
регистрационный номер и первые 200 символов текущего названия. Subject состоит
только из фиксированной метки. Получатель один, размер To равен 1. В текст не
включаются manual_reason, actorName, компания, организация, контрагент, объект,
файл, токен, ссылка с DocID или старый snapshot. Общий чат и производный push
для этого opt-in выключены; новый inbox и схема не создаются. Остальные 105
вызовов аудита и прежние dispatcher/чат/почта сохраняют прежнее поведение.

## Граница свежести

Отзыв, закоммиченный до начала свежей проверки, должен подавить передачу.
READ COMMITTED и несколько отдельных SELECT не дают единого атомарного снимка
всех правил. Изменение во время этих чтений или после них может соревноваться
с handoff; начавшуюся передачу SMTP отозвать нельзя. Нет lease, блокировки прав
через SMTP, exactly-once или обещания вернуть уже совершённую регистрацию.
Кандидат, добавленный после первоначального выбора UUID аудитории, не получает
это событие. Индивидуальные настройки, не участвующие в существующей доставке
NotificationRule, этим изменением не переопределяются.

URL/HMAC/internal-app publisher и его payload сохранены побайтово. Их политика
делегирования и PartnerGrant остаются отдельным **OPEN**: человеческий READ
не заменяет полномочия машинного канала. Нативная политика Doc object/org также
не считается закрытой этой доработкой.

## Будущая проверка владельцем прогона

Два новых PG-модуля содержат только определения. До их импорта владелец обязан
изолировать ancestor conftest, поднять полную нативную схему с миграциями,
ограничениями и штатными codecs и обеспечить удаление собственной тестовой БД.
Локальный guard модуля не защищает от conftest, импортированного раньше него.
Синтетические родители пишутся партиями Company → User/Role/Org/CP → Case →
Kind/Member/Subscription → Card; старый world не импортируется. Схема и драйвер
не подменяются, native ACL и Session не имитируются.

Определены проверки READ/private/strict/assignment/substitution, READ без DOWNLOAD,
break-glass без записи использования, потери tenant/product/current User, порядка
выдачи/отзыва вокруг enqueue/commit/check/handoff, каждого следующего адресата после
медленного первого SMTP, актуального email/номера/названия и границы 200 символов.
Есть проверки Scope/claims/visit/org на всех путях, To=1, отсутствия нового чата,
push/inbox, фактического root commit и отсутствия доставки до него, rollback,
SAVEPOINT/poison/reentrancy/reuse, старого immediate пути и состава 105 вызовов.
Синтетические попытки и ошибки сохраняются отдельными ledgers, чтобы production
log-only catches не поглощали провал oracle. Реальные транспорты при будущем
прогоне также должны быть перехвачены. Определения не равны успешному прогону.

Остаются OPEN: независимое полное ревью девяти файлов, PG-приёмка владельцем,
HTTP ingress, delivery/runtime, CI и выпуск. Смена поведения исторических
регистрационных тестов, которые ожидают старые who/details или scheduler без
нового opt-in keyword, требует отдельной проверки владельцем общего состава.

## Полная исходная программа: все 20 разделов и 11 условий OPEN

Ни один пункт не объявлен выполненным этой доработкой. Полный исходный текст
сохранён ниже без сокращения; карта статусов отдельно ставит всем 31 пункту OPEN.
SHA-256 исходного JSON: `84f8dd31e6e047bf6fc647f4e601c1c89783dc8ebbeb4fe324814d51a7fb2ba1`.

```json
{
  "programme_status": {
    "M00": "OPEN",
    "M01": "OPEN",
    "M02": "OPEN",
    "M03": "OPEN",
    "M04": "OPEN",
    "M05": "OPEN",
    "M06": "OPEN",
    "M07": "OPEN",
    "M08": "OPEN",
    "M09": "OPEN",
    "M10": "OPEN",
    "M11": "OPEN",
    "M12": "OPEN",
    "M13": "OPEN",
    "M14": "OPEN",
    "M15": "OPEN",
    "M16": "OPEN",
    "M17": "OPEN",
    "M18": "OPEN",
    "M19": "OPEN",
    "FULL-SCOPE": "OPEN",
    "SOURCE": "OPEN",
    "DOMAIN": "OPEN",
    "CONTRACT": "OPEN",
    "CHARACTERIZATION": "OPEN",
    "MIGRATION": "OPEN",
    "CONSUMERS": "OPEN",
    "MEASUREMENTS": "OPEN",
    "FINAL-COMPOSITION": "OPEN",
    "LIVE-PILOT": "OPEN",
    "RELEASE": "OPEN"
  },
  "original_program": {
    "planSHA256": "2f0ce3f319b1bbeff98905f2921514b5b722c1c65d4c7c13ca8b344f9e888352",
    "sections": [
      {
        "id": "M00",
        "title": "P0: актуальный совместимый source/runtime baseline",
        "owner": "Выпуск + Core/Support",
        "dependencies": "Нет",
        "original_acceptance": "Точные версии/хеши/состав, реестр активных потребителей; старый Support не выдан за baseline"
      },
      {
        "id": "M01",
        "title": "P0: завершить реестр поверхностей и владельцев",
        "owner": "API + владельцы доменов",
        "dependencies": "M00",
        "original_acceptance": "Dynamic/factory/native/WS/SSE/files/proxy разобраны, каждому маршруту назначены class/owner/decision и потребители"
      },
      {
        "id": "M02",
        "title": "P0: characterization и измеряемые сценарии",
        "owner": "Домены + проверка",
        "dependencies": "M00, уточнения M01",
        "original_acceptance": "Golden outputs/ошибки и отрицательная ACL-матрица на синтетике; исходные SQL/RAM/latency budgets измерены"
      },
      {
        "id": "M03",
        "title": "P0: общий проверенный контекст/route policy",
        "owner": "Identity + домены",
        "dependencies": "M00, M02",
        "original_acceptance": "Типы токенов/отзыв; ALL/SET/EMPTY/UNINITIALIZED; selector не расширяет доступ; неизвестная новая операция закрыта"
      },
      {
        "id": "M04",
        "title": "P0: границы слоёв и владение транзакцией",
        "owner": "Core/Support architecture",
        "dependencies": "M02, M03 skeleton",
        "original_acceptance": "Извлечённые services не импортируют routers; старые входы вызывают те же правила без изменения поведения"
      },
      {
        "id": "M05",
        "title": "P0: объекты, scopes, population и temporal identity",
        "owner": "Core objects/equipment",
        "dependencies": "M03, M04",
        "original_acceptance": "Матрица пяти уровней implemented/gap; одинаковый охват list/detail/count/export; create/upsert/rename/retire проверены отдельно"
      },
      {
        "id": "M06",
        "title": "P0: контрагенты, договоры и идентичность",
        "owner": "Core references/contracts",
        "dependencies": "M03, M04",
        "original_acceptance": "Один matcher и scope service; ambiguous явно; replay/concurrency/null/связи проверены; старые подтверждённые связи сохранены"
      },
      {
        "id": "M07",
        "title": "P0: документы и файлы",
        "owner": "Core documents/files",
        "dependencies": "M03, M04",
        "original_acceptance": "Карточка/версия/содержимое/тип связи разделены; один writer, domain ACL, rollback cleanup, register/approve отдельно от edit"
      },
      {
        "id": "M08",
        "title": "P0: энергия, начисления и мониторинг",
        "owner": "Core energy/ops",
        "dependencies": "M05, M06",
        "original_acceptance": "Общие definitions/provenance; чистый GET closing; материализация командой; исторический срез описан честно"
      },
      {
        "id": "M09",
        "title": "P0: протокольный профиль и product OpenAPI",
        "owner": "API contracts + домены",
        "dependencies": "M01, M03, соответствующие M05–M08",
        "original_acceptance": "Схемы/ошибки/scopes/examples/operationId совпадают с runtime; описательные x-поля не заменяют guard"
      },
      {
        "id": "M10",
        "title": "P0: OAuth/OIDC и developer access",
        "owner": "Identity + integrations",
        "dependencies": "M03, M09 profile",
        "original_acceptance": "Code+PKCE, machine grants отдельно; docs portal/spec/API permissions разделены, отзыв действует и протестирован"
      },
      {
        "id": "M11",
        "title": "P0: защищённый Swagger и quickstart",
        "owner": "API docs + Identity",
        "dependencies": "M09, M10, sandbox",
        "original_acceptance": "UI/raw spec/bundles закрыты; Authorize/Try it out работает на синтетике; нет client secret или общего admin token в браузере"
      },
      {
        "id": "M12",
        "title": "P1: клиентские transports и typed operations",
        "owner": "Core/Support frontend",
        "dependencies": "M02, M09",
        "original_acceptance": "Один transport на trust boundary; generation/signal, refresh/errors/binary; wire types generated, без `as never`"
      },
      {
        "id": "M13",
        "title": "P1: Support factories и service adapters",
        "owner": "Support + Core integration",
        "dependencies": "M03, M04, M06",
        "original_acceptance": "Общий ticket lifecycle с параметрами команд; SLA/subject replay/actor и parent SSO ограничения сохранены"
      },
      {
        "id": "M14",
        "title": "P1: доставка событий и change feed",
        "owner": "Domain owners + integrations",
        "dependencies": "M03, M04, применимые M13",
        "original_acceptance": "Локальные outbox, единый envelope/signature; определены момент подписки, retry/replay/cursor и права перед выдачей"
      },
      {
        "id": "M15",
        "title": "P1: ограничение нагрузки и оптимизация",
        "owner": "Backend/DB + домены",
        "dependencies": "M02 и зрелые queries",
        "original_acceptance": "Измерены SQL/строки/RAM/pool/cache; достигнут принятый бюджет без изменения результата/ACL; большие выгрузки/jobs ограничены"
      },
      {
        "id": "M16",
        "title": "P1/P2: migration/schema ownership",
        "owner": "Persistence + выпуск",
        "dependencies": "M00, M02",
        "original_acceptance": "Fresh/restore/upgrade/repeat совпадают; Alembic audit отделён от runner; новый DDL versioned и совместим со старым кодом"
      },
      {
        "id": "M17",
        "title": "P1: перевести собственные приложения",
        "owner": "Владельцы продуктов",
        "dependencies": "M05–M13 по домену",
        "original_acceptance": "Переведены UI/service consumers, contracts и workflows проходят регрессию; нет silent online→demo fallback"
      },
      {
        "id": "M18",
        "title": "P0 к внешнему запуску: пилоты и независимая приёмка",
        "owner": "Партнёрский пилот + проверка",
        "dependencies": "M09–M17 применимо",
        "original_acceptance": "Три внешних сценария и общий блок из четырёх доменов реализуются по документации без чтения исходников"
      },
      {
        "id": "M19",
        "title": "P2: deprecation и удаление дублей",
        "owner": "Домены + выпуск",
        "dependencies": "M17, M18, usage evidence",
        "original_acceptance": "Потребители переведены, срок совместимости окончен; старые key/path/adapter удаляются отдельным PR с откатом"
      }
    ],
    "cross_cutting_requirements": [
      {
        "id": "FULL-SCOPE",
        "requirement": "Все20M и все поверхности Core/Support/Auditor классифицированы; обязательные документы/контрагенты/договоры/ЭЗС/оборудование/accounts не исчерпывают объём.",
        "completion": "unproven"
      },
      {
        "id": "SOURCE",
        "requirement": "Точный актуальный source/runtime/consumer baseline; не потерять параллельные live исправления.",
        "completion": "unproven"
      },
      {
        "id": "DOMAIN",
        "requirement": "Единственный владелец правила, tenant/object/org/date scope до count/limit/aggregate/export, текущие actor/grants; неизвестная операция fail-closed.",
        "completion": "unproven"
      },
      {
        "id": "CONTRACT",
        "requirement": "OpenAPI/Swagger/SDK/runtime совпадают, содержат реальные auth, errors, headers, limits, null-intent, examples; binary/multipart/SSE/WS/webhook/industry profiles проверяются отдельно.",
        "completion": "unproven"
      },
      {
        "id": "CHARACTERIZATION",
        "requirement": "Старые golden outputs и отрицательные матрицы двух компаний/пользователей/apps/resources, реальные SQL/bytes там где требуется; metadata count не заменяет ACL assertion.",
        "completion": "unproven"
      },
      {
        "id": "MIGRATION",
        "requirement": "Fresh/restore/upgrade/repeat/old-code, checksums, locking и rollback; перед working migration свежая backup и фактическое восстановление.",
        "completion": "unproven"
      },
      {
        "id": "CONSUMERS",
        "requirement": "Полный перевод согласованных UI/service consumers, без stale-context effects и silent fallback; usage evidence перед retirement.",
        "completion": "unproven"
      },
      {
        "id": "MEASUREMENTS",
        "requirement": "SQL/RAM/latency/pool/cache/exports/jobs на представительном объёме и принятые бюджеты, без необоснованных pool/index changes.",
        "completion": "unproven"
      },
      {
        "id": "FINAL-COMPOSITION",
        "requirement": "Единый окончательный состав исходников и соответствующие проверки; разные frozen серии не объявляются общим полным CI.",
        "completion": "unproven"
      },
      {
        "id": "LIVE-PILOT",
        "requirement": "Фактическая приёмка выбранного release/ingress/SSO/callback/CORS/ordinary employee и партнёров; synthetic localhost не подменяет её.",
        "completion": "unproven"
      },
      {
        "id": "RELEASE",
        "requirement": "Ревью человеком/согласованный состав/откат; merge и рабочая активация отдельны от зелёных тестов.",
        "completion": "unproven"
      }
    ],
    "completion_asserted": false,
    "note": "Исходные20 критериев и11 условий сохранены без сокращения; source-only аудит не доказывает их завершение."
  }
}
```
