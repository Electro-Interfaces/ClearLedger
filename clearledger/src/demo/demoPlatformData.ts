import { DEMO_COMPANY_ID, DEMO_DOCS, DEMO_TASKS } from './demoData'

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()
const dateFrom = (days: number, hour = 12) => {
  const date = new Date()
  date.setDate(date.getDate() + days)
  date.setHours(hour, 0, 0, 0)
  return date.toISOString()
}

export const DEMO_INVITATIONS = [
  {
    id: 'invite-shift', email: 'shift.operator@polus.demo', role: 'user', position: 'Сменный оператор',
    status: 'pending', created_at: dateFrom(-2), expires_at: dateFrom(5), email_sent: true,
    party_type: 'internal', organization_id: null, organization_name: null,
    scope: 'company', company_id: DEMO_COMPANY_ID, company_name: 'ООО «Полюс Ритейл»',
  },
  {
    id: 'invite-engineer', email: 'engineer.ivanov@polus.demo', role: 'user', position: 'Инженер сети',
    status: 'accepted', created_at: dateFrom(-12), expires_at: dateFrom(-5), email_sent: true,
    party_type: 'internal', organization_id: null, organization_name: null,
    scope: 'company', company_id: DEMO_COMPANY_ID, company_name: 'ООО «Полюс Ритейл»',
  },
]

export const DEMO_SPACE_CONNECTORS = {
  companyId: DEMO_COMPANY_ID,
  total: 6,
  problems: [{ app: 'network', app_name: 'Шлюзы АЗС', error: 'АЗС Лесная: основной Ethernet недоступен, резервный LTE активен' }],
  connectors: [
    {
      key: 'core-chat', app: 'core', app_name: 'Ядро', provider: 'Matrix', kind: 'Платформенный сервис',
      label: 'Чаты пространства', brings: 'Сообщения, каналы, группы и уведомления', direction: 'both',
      initiator: 'both', status: 'up', enabled: true, last_sync_at: ago(1), last_test_at: ago(1),
      last_error: null, records: 148, files: 7, settings_route: '/messages',
    },
    {
      key: 'core-conference', app: 'core', app_name: 'Ядро', provider: 'Jitsi', kind: 'Платформенный сервис',
      label: 'Конференции', brings: 'Встречи по одноразовым гостевым ссылкам', direction: 'both',
      initiator: 'both', status: 'up', enabled: true, last_sync_at: ago(18), last_test_at: ago(3),
      last_error: null, records: 9, files: 0,
    },
    {
      key: 'station-gateways', app: 'data', app_name: 'Данные', provider: 'ElsyPlus Agent', kind: 'Телеметрия объектов',
      label: 'Шлюзы сети АЗС', brings: 'Состояние Ethernet, LTE, overlay и критичных сервисов пяти АЗС', direction: 'in',
      initiator: 'them', status: 'warn', enabled: true, last_sync_at: ago(2), last_test_at: ago(2),
      last_error: 'АЗС Лесная: Ethernet down; работа через резервный LTE, INC-2471', records: 5, files: 0, settings_route: '/connect?mode=connect&sub=sources',
    },
    {
      key: 'mail-inbox', app: 'docs', app_name: 'Трек', provider: 'IMAP', kind: 'Почтовый ящик',
      label: 'Почта сетевой службы', brings: 'Ответы провайдера и вложения по INC-2471 для регистрации в Треке', direction: 'in',
      initiator: 'us', status: 'up', enabled: true, last_sync_at: ago(12), last_test_at: ago(8),
      last_error: null, records: 8, files: 3, settings_route: '/docs/setup',
    },
    {
      key: 'incident-api', app: 'core', app_name: 'Ядро', provider: 'REST API', kind: 'Входящий ключ',
      label: 'События сетевых инцидентов', brings: 'События отказа канала и связь с поручениями Трека', direction: 'in',
      initiator: 'them', status: 'up', enabled: true, last_sync_at: ago(3), last_test_at: ago(3),
      last_error: null, records: 14, files: 0,
    },
    {
      key: 'incident-archive', app: 'docs', app_name: 'Трек', provider: 'SFTP', kind: 'Файловый обмен',
      label: 'Архив сетевой службы', brings: 'Акты диагностики и итоговые документы по инцидентам', direction: 'out',
      initiator: 'us', status: 'up', enabled: true, last_sync_at: ago(18), last_test_at: ago(14),
      last_error: null, records: 4, files: 9,
      settings_route: '/docs/setup',
    },
  ],
}

export const DEMO_INBOUND_KEYS = {
  keys: [
    { id: 'key-stations', consumer: 'Шлюзы сети АЗС', prefix: 'dmo_azs_247', created_at: dateFrom(-28), last_used_at: ago(2), revoked_at: null },
    { id: 'key-mail-gateway', consumer: 'Шлюз почты сетевой службы', prefix: 'dmo_mail_471', created_at: dateFrom(-61), last_used_at: ago(12), revoked_at: null },
    { id: 'key-old', consumer: 'Старый агент АЗС Лесная', prefix: 'dmo_old_les', created_at: dateFrom(-90), last_used_at: dateFrom(-45), revoked_at: dateFrom(-30) },
  ],
}

export const DEMO_SOURCES = [
  {
    id: 'source-stations', company_id: DEMO_COMPANY_ID, source_type: 'station_gateway',
    name: 'Шлюзы сети АЗС', description: 'Телеметрия Ethernet, LTE, overlay и сервисов пяти объектов',
    status: 'connected', connection_config: { endpoint: 'https://agents.demo.local/events', objects: 5, schedule: 'каждые 5 минут' },
    configured_secrets: ['api_key'], last_test_at: ago(2), error_message: 'АЗС Лесная: основной Ethernet недоступен, резервный LTE активен',
  },
  {
    id: 'source-mail', company_id: DEMO_COMPANY_ID, source_type: 'mail_imap',
    name: 'Почта сетевой службы', description: 'Ответы провайдера и вложения по INC-2471 для Трека',
    status: 'connected', connection_config: { host: 'imap.demo.local', mailbox: 'network@polus.demo' },
    configured_secrets: ['password'], last_test_at: ago(8), error_message: null,
  },
  {
    id: 'source-incidents', company_id: DEMO_COMPANY_ID, source_type: 'incident_webhook',
    name: 'События сетевых инцидентов', description: 'Связь событий шлюза с карточками и поручениями Трека',
    status: 'connected', connection_config: { endpoint: 'https://space.demo.local/incidents' },
    configured_secrets: ['api_key'], last_test_at: ago(3), error_message: null,
  },
]

export const DEMO_CHANNELS = [
  {
    id: 'channel-telemetry', company_id: DEMO_COMPANY_ID, name: 'Телеметрия сети АЗС',
    description: 'Состояние основного и резервного каналов пяти АЗС', status: 'active',
    template_id: 'tpl-station-telemetry', schedule: { mode: 'interval', intervalMinutes: 5 },
    duplicate_policy: 'update', config: { incident: 'INC-2471', objects: 5 }, period_days: 7,
    last_sync_at: ago(2),
    streams: [
      { id: 'stream-primary', source_id: 'source-stations', doc_type_id: 'primary_link', name: 'Основной Ethernet', enabled: true, role: 'anchor' },
      { id: 'stream-reserve', source_id: 'source-stations', doc_type_id: 'reserve_link', name: 'Резервный LTE', enabled: true, role: 'control' },
      { id: 'stream-services', source_id: 'source-stations', doc_type_id: 'service_state', name: 'Критичные сервисы', enabled: true, role: 'reference' },
    ],
    stages: [
      { id: 'stage-fetch', stage_type: 'fetch', name: 'Получение данных', order_index: 0, enabled: true },
      { id: 'stage-normalize', stage_type: 'normalize', name: 'Нормализация', order_index: 1, enabled: true },
      { id: 'stage-quality', stage_type: 'validate', name: 'Проверки качества', order_index: 2, enabled: true },
    ],
  },
  {
    id: 'channel-mail', company_id: DEMO_COMPANY_ID, name: 'Документы сетевой службы',
    description: 'Письма провайдера и вложения связываются с INC-2471', status: 'active',
    template_id: 'tpl-mail-docs', schedule: { mode: 'interval', intervalMinutes: 10 },
    duplicate_policy: 'skip', config: { folder: 'INCIDENTS', route: 'incoming', incident: 'INC-2471' }, period_days: 14,
    last_sync_at: ago(12),
    streams: [{ id: 'stream-mail', source_id: 'source-mail', doc_type_id: 'mail', name: 'Письма', enabled: true, role: 'anchor' }],
    stages: [
      { id: 'stage-mail', stage_type: 'fetch', name: 'Получение писем', order_index: 0, enabled: true },
      { id: 'stage-doc', stage_type: 'normalize', name: 'Разбор реквизитов', order_index: 1, enabled: true },
    ],
  },
  {
    id: 'channel-incidents', company_id: DEMO_COMPANY_ID, name: 'События и поручения по инцидентам',
    description: 'События отказа связываются с объектом, документами и работой', status: 'active',
    template_id: 'tpl-incident', schedule: { mode: 'interval', intervalMinutes: 5 },
    duplicate_policy: 'update', config: { incident: 'INC-2471' }, period_days: 30,
    last_sync_at: ago(3),
    streams: [{ id: 'stream-incidents', source_id: 'source-incidents', doc_type_id: 'incident_event', name: 'События инцидента', enabled: true, role: 'external' }],
    stages: [
      { id: 'stage-partner-fetch', stage_type: 'fetch', name: 'Получение статусов', order_index: 0, enabled: true },
      { id: 'stage-partner-link', stage_type: 'normalize', name: 'Связь с работой', order_index: 1, enabled: true },
    ],
  },
]

export const DEMO_SOURCE_TYPES = [
  {
    source_type: 'station_gateway', label: 'Шлюз объекта', category: 'Сеть АЗС',
    description: 'Ethernet, LTE, overlay и доступность критичных сервисов', icon: 'network', status: 'available', version: 'v1',
    setup_guide: 'Укажите адрес приёма телеметрии и отдельный ключ демонстрационного агента.',
    setup_schema: [
      { key: 'endpoint', label: 'Адрес приёма', type: 'url', required: true, placeholder: 'https://space.example.ru/events' },
      { key: 'api_key', label: 'Ключ агента', type: 'password', required: true, secret: true },
    ],
    available_doc_types: [
      { id: 'primary_link', name: 'Основной канал' }, { id: 'reserve_link', name: 'Резервный канал' },
      { id: 'service_state', name: 'Состояние сервисов' },
    ],
  },
  {
    source_type: 'mail_imap', label: 'Почтовый ящик', category: 'Документы',
    description: 'Письма и вложения для регистрации в Треке', icon: 'mail', status: 'available', version: 'IMAP',
    setup_guide: 'Подключите отдельный служебный ящик и выберите папку входящих.',
    setup_schema: [
      { key: 'host', label: 'IMAP-сервер', type: 'text', required: true },
      { key: 'mailbox', label: 'Адрес ящика', type: 'text', required: true },
      { key: 'password', label: 'Пароль приложения', type: 'password', required: true, secret: true },
    ],
    available_doc_types: [{ id: 'mail', name: 'Письма и вложения' }],
  },
  {
    source_type: 'incident_webhook', label: 'События инцидентов', category: 'Интеграции',
    description: 'События отказов, восстановления и изменения транспортного канала', icon: 'plug', status: 'available', version: 'v1',
    setup_guide: 'Создайте именной входящий ключ для источника событий.',
    setup_schema: [{ key: 'endpoint', label: 'Адрес API', type: 'url', required: true }],
    available_doc_types: [{ id: 'incident_event', name: 'События инцидента' }],
  },
]

export const DEMO_CHANNEL_TEMPLATES = [
  {
    id: 'tpl-station-telemetry', label: 'Телеметрия сети АЗС', category: 'Сеть',
    description: 'Состояние основного и резервного каналов объектов', icon: 'network', direction: 'in', status: 'available',
    streams: [
      { source_type: 'station_gateway', doc_type: 'primary_link', role: 'anchor', label: 'Ethernet' },
      { source_type: 'station_gateway', doc_type: 'reserve_link', role: 'control', label: 'LTE' },
    ],
    stages: [{ stage_type: 'fetch', name: 'Загрузка' }, { stage_type: 'normalize', name: 'Нормализация' }, { stage_type: 'validate', name: 'Контроль качества' }],
    reconcile_rules: ['primary-vs-reserve'], schedule: { mode: 'interval', intervalMinutes: 5 },
  },
  {
    id: 'tpl-mail-docs', label: 'Входящие документы', category: 'Документооборот',
    description: 'Приём писем и вложений в Трек', icon: 'mail', direction: 'in', status: 'available',
    streams: [{ source_type: 'mail_imap', doc_type: 'mail', role: 'anchor', label: 'Письма' }],
    stages: [{ stage_type: 'fetch', name: 'Получение' }, { stage_type: 'normalize', name: 'Разбор реквизитов' }],
    reconcile_rules: [], schedule: { mode: 'interval', intervalMinutes: 10 },
  },
]

export const DEMO_RECONCILE_RULES = [
  {
    id: 'primary-vs-reserve', label: 'Основной канал ↔ резервный канал', module: 'data',
    description: 'Проверяет, что при отказе Ethernet объект остаётся доступен через LTE', status: 'imperative', impl: 'channel_failover',
    streams: [
      { role: 'anchor', source_type: 'station_gateway', doc_type: 'primary_link', label: 'Ethernet' },
      { role: 'control', source_type: 'station_gateway', doc_type: 'reserve_link', label: 'LTE' },
    ],
    key: ['object_id'], match: { time_tolerance: '5m' },
    compare: [{ field: 'available', tolerance_abs: 0, unit: 'boolean' }], severity: { thresholds: { warn: 1, error: 2 } },
  },
]

export const DEMO_NOTIFY_CATALOG = [
  { code: 'access', label: 'Доступ и приглашения', description: 'Новые участники, изменения ролей и блокировки входа', prefixes: ['member.', 'invite.', 'auth.'], default_on: true },
  { code: 'connect', label: 'Подключения', description: 'Ошибки и долгое молчание каналов данных', prefixes: ['connector.', 'channel.'], default_on: true },
  { code: 'docs', label: 'Трек', description: 'Документы на согласование, поручения и сроки', prefixes: ['doc.', 'task.'], default_on: true },
  { code: 'quality', label: 'Качество данных', description: 'Новые разрывы связей и результаты проверок', prefixes: ['quality.'], default_on: false },
]

export const DEMO_NOTIFY_RULES = [
  { id: 'notify-access', category: 'access', enabled: true, via_chat: true, via_email: false, recipients: null },
  { id: 'notify-connect', category: 'connect', enabled: true, via_chat: true, via_email: true, recipients: ['demo-operator', 'engineer.ivanov', 'lead.engineer'] },
  { id: 'notify-docs', category: 'docs', enabled: true, via_chat: true, via_email: true, recipients: ['demo-operator', 'lead.engineer'] },
  { id: 'notify-quality', category: 'quality', enabled: true, via_chat: true, via_email: false, recipients: ['engineer.ivanov'] },
]

export const DEMO_BOOKS_PROFILE = {
  company: { name: 'ООО «Полюс Ритейл»', slug: 'polus-retail', inn: '7805123456' },
  organizations: [{ name: 'ООО «Полюс Ритейл»', inn: '7805123456', docs: 1842 }],
  taxMode: 'ОСНО', vat: true, commission: false,
  data: { from: '2026-01-01', to: '2026-08-23', entries: 18426, balanceAsOf: '2026-08-23', periodsClosed: 7, periodsTotal: 8, lastClosed: '2026-07-31' },
  volumes: { документов: 1842, контрагентов: 126, номенклатуры: 418, счетов: 74 },
  activeCounterparties: 83,
  totals: { revenue: 42860000, revenueNet: 35716667, vat: 7143333, cost: 24980000, grossProfit: 10736667 },
  quality: { checks: 9, problems: 2, worst: [{ key: 'doc-link', label: 'Документы без связи', value: 3 }, { key: 'inn', label: 'Неполные реквизиты', value: 2 }] },
}

export const DEMO_BOOKS_SOURCES = {
  sources: [{
    kind: 'onec_accounting', name: '1С:Бухгалтерия · основная база', loadedAt: ago(47),
    periodFrom: '2026-01-01', periodTo: '2026-08-23',
    datasets: [
      { key: 'gl_entries', label: 'Проводки', records: 18426 },
      { key: 'documents', label: 'Документы', records: 1842 },
      { key: 'counterparties', label: 'Контрагенты', records: 126 },
      { key: 'nomenclature', label: 'Номенклатура', records: 418 },
      { key: 'references', label: 'Справочники', records: 264 },
    ],
    documents: [
      { key: 'sales', label: 'Реализации', records: 486 }, { key: 'receipts', label: 'Поступления', records: 392 },
      { key: 'payments', label: 'Банковские документы', records: 721 }, { key: 'operations', label: 'Регламентные операции', records: 243 },
    ],
    references: [
      { key: 'counterparties', label: 'Контрагенты', records: 126 }, { key: 'nomenclature', label: 'Номенклатура', records: 418 },
      { key: 'contracts', label: 'Договоры', records: 96 }, { key: 'accounts', label: 'План счетов', records: 74 },
    ],
  }],
}

export const DEMO_BOOKS_QUALITY = {
  errors: 0, warnings: 2, ok: 7,
  checks: [
    { key: 'periods', label: 'Закрытые периоды загружены полностью', status: 'ok', value: '7 из 7', hint: 'Январь — июль совпадают с источником' },
    { key: 'balance', label: 'Обороты сходятся с остатками', status: 'ok', value: '0 ₽', hint: 'Расхождений по контрольной сумме нет' },
    { key: 'doc-link', label: 'Проводки без первичного документа', status: 'warn', value: 3, hint: 'Нужно связать операции с карточками документов' },
    { key: 'counterparty', label: 'Контрагенты без ИНН', status: 'warn', value: 2, hint: 'Заполните реквизиты перед обменом документами' },
    { key: 'duplicates', label: 'Дубли документов', status: 'ok', value: 0, hint: 'Повторные номера не найдены' },
    { key: 'negative', label: 'Отрицательные суммы без сторно', status: 'ok', value: 0, hint: 'Некорректных операций нет' },
    { key: 'currency', label: 'Валюта управленческого слоя', status: 'ok', value: 'RUB', hint: 'Все суммы приведены к рублям' },
    { key: 'users', label: 'Ответственные связаны с людьми', status: 'ok', value: '5 из 5', hint: 'Текстовые роли сведены с участниками пространства' },
    { key: 'freshness', label: 'Свежесть данных', status: 'ok', value: '47 мин', hint: 'Обмен укладывается в расписание' },
  ],
}

export const DEMO_BOOKS_MODEL = {
  rows: 18426,
  layers: [
    { key: 'l0', code: 'L0', title: 'Источник', desc: 'Снимок 1С без изменения', records: 22680, unit: 'записей', tone: 'raw', status: 'ready' },
    { key: 'l1', code: 'L1', title: 'Нормализованный слой', desc: 'Единые даты, суммы и ссылки', records: 21496, unit: 'записей', tone: 'clean', status: 'ready' },
    { key: 'l2', code: 'L2', title: 'База пространства', desc: 'Связанные сущности для приложений', records: 18426, unit: 'проводок', tone: 'export', status: 'ready' },
    { key: 'refs', code: 'НСИ', title: 'Справочники', desc: 'Контрагенты, договоры и статьи', records: 914, unit: 'карточек', tone: 'ref', status: 'ready' },
  ],
  fact: {
    table: 'gl_entries', name: 'Проводки регистра', grain: 'Одна проводка документа', rows: 18426,
    period: { from: '2026-01-01', to: '2026-08-23' },
    measures: [
      { key: 'amount', label: 'Оборот', value: 128450000, unit: '₽', agg: 'sum' },
      { key: 'documents', label: 'Документы', value: 1842, unit: 'шт', agg: 'distinct' },
    ],
  },
  dimensions: [
    { key: 'account', label: 'Счёт', field: 'account', cardinality: 74, fill_pct: 100, canonical: true, grain: 'план счетов', members: [{ label: '60.01', count: 2810 }, { label: '62.01', count: 2464 }, { label: '51', count: 1987 }] },
    { key: 'counterparty', label: 'Контрагент', field: 'counterparty_id', cardinality: 126, fill_pct: 96.8, canonical: true, grain: 'карточка юрлица', members: [{ label: 'ООО «Телеком Сервис»', count: 184 }, { label: 'ООО «Связь Резерв»', count: 142 }] },
    { key: 'document', label: 'Документ', field: 'registrar_id', cardinality: 1842, fill_pct: 99.9, canonical: true, grain: 'регистратор', members: [] },
  ],
  quality: {
    fields: [
      { field: 'account_dt', label: 'Счёт Дт', role: 'измерение', fill_pct: 100 },
      { field: 'account_kt', label: 'Счёт Кт', role: 'измерение', fill_pct: 100 },
      { field: 'counterparty_id', label: 'Контрагент', role: 'ссылка', fill_pct: 96.8 },
      { field: 'registrar_id', label: 'Документ', role: 'ссылка', fill_pct: 99.9 },
    ],
    canonicalization: [
      { name: 'Контрагенты', from: 'counterparty_name', to: 'counterparty_id', members: 126, coverage_pct: 96.8 },
      { name: 'Договоры', from: 'contract_text', to: 'contract_id', members: 96, coverage_pct: 94.2 },
    ],
  },
}

const dataset = (key: string, label: string, table: string, records: number, link: string,
  fields: Array<[string, string, number, number]>, top: Array<[string, number]>) => ({
  key, label, table, records, link, period: { from: '2026-01-01', to: '2026-08-23' },
  fields: fields.map(([field, fieldLabel, fill_pct, distinct]) => ({ field, label: fieldLabel, fill_pct, distinct })),
  top: top.map(([topLabel, count]) => ({ label: topLabel, count })),
})

export const DEMO_BOOKS_DATASETS = {
  entries: dataset('entries', 'Проводки регистра', 'gl_entries', 18426, 'registrar_id', [
    ['date', 'Дата', 100, 235], ['account_dt', 'Счёт Дт', 100, 74], ['account_kt', 'Счёт Кт', 100, 74], ['counterparty_id', 'Контрагент', 96.8, 126],
  ], [['60.01 → 51', 2810], ['51 → 62.01', 2464], ['26 → 60.01', 1852]]),
  docs: dataset('docs', 'Первичные документы', 'accounting_docs', 1842, 'external_id', [
    ['number', 'Номер', 99.8, 1796], ['date', 'Дата', 100, 235], ['amount', 'Сумма', 100, 1684], ['counterparty_id', 'Контрагент', 98.4, 126],
  ], [['Реализация', 486], ['Поступление', 392], ['Списание с расчётного счёта', 381]]),
  counterparties: dataset('counterparties', 'Контрагенты', 'counterparties', 126, 'inn', [
    ['name', 'Наименование', 100, 126], ['inn', 'ИНН', 98.4, 124], ['kpp', 'КПП', 91.3, 115], ['legal_address', 'Юридический адрес', 88.9, 112],
  ], [['Покупатели', 54], ['Поставщики', 47], ['Прочие', 25]]),
  nomenclature: dataset('nomenclature', 'Номенклатура', 'nomenclature', 418, 'code', [
    ['code', 'Код', 100, 418], ['name', 'Наименование', 100, 416], ['unit', 'Единица', 97.6, 8], ['group', 'Группа', 94.5, 24],
  ], [['Услуги', 164], ['Материалы', 132], ['Товары', 91], ['Прочее', 31]]),
  refs: dataset('refs', 'Справочники учёта', 'reference_items', 264, 'source_key', [
    ['kind', 'Вид справочника', 100, 8], ['code', 'Код', 100, 264], ['name', 'Наименование', 100, 261], ['active', 'Действует', 100, 2],
  ], [['Договоры', 96], ['Счета', 74], ['Статьи ДДС', 42], ['Подразделения', 28]]),
}

export const DEMO_DOC_CASES = [
  { id: 'case-incidents', year: 2026, index: 'СЕТЬ-01', title: 'Акты и материалы сетевых инцидентов', storage_term: '5 лет', storage_years: 5, epk: false, status: 'open', organization_id: 'org-polus', department_id: 'dep-network', closed_at: null, note: 'INC-2471 · АЗС Лесная' },
  { id: 'case-correspondence', year: 2026, index: 'СЕТЬ-02', title: 'Переписка с операторами связи', storage_term: '5 лет', storage_years: 5, epk: false, status: 'open', organization_id: 'org-polus', department_id: 'dep-network', closed_at: null, note: null },
  { id: 'case-orders', year: 2026, index: 'СЕТЬ-03', title: 'Распоряжения по режиму работы сети', storage_term: 'Постоянно', storage_years: null, epk: true, status: 'open', organization_id: 'org-polus', department_id: 'dep-operations', closed_at: null, note: null },
]

export const DEMO_MY_APPROVALS = [
  { id: 'approval-doc-lte', doc_id: 'doc-lte-order', step_name: 'Решение руководителя службы', step_kind: 'sign', mode: 'serial', due_at: dateFrom(0, 15), doc_title: 'Распоряжение о временной работе АЗС Лесная через LTE', doc_number: 'РСП-2471/26', acting_for: null },
]

export const DEMO_MY_ACQUAINTS = [
  { id: 'acquaint-doc-act', doc_id: 'doc-inc-act', doc_title: 'Акт первичной диагностики INC-2471', doc_number: 'АКТ-2471/26', due_at: dateFrom(0, 18), snapshot_sha256: 'demo-incident-snapshot', revision: 2 },
]

export const DEMO_SUBSTITUTIONS = []

export const DEMO_EXCHANGE_TARGETS = [
  { id: 'exchange-main', code: 'NET', name: 'Архив сетевой службы', system: 'sedo', outbox_path: '/demo/incidents/outbox', inbox_path: '/demo/incidents/inbox', outbox_configured: true, inbox_configured: true, as_archive: true, is_active: true, scan_enabled: true, scan_interval_min: 15, note: 'Документы по INC-2471', last_export_at: ago(18), last_scan_at: ago(14), last_error: null },
]

export const DEMO_DOC_VIEWS = [
  { id: 'view-incident', name: 'INC-2471 · АЗС Лесная', query: { subject_ref: 'INC-2471', object_id: 'object-forest' }, shared: true, position: 10, can_delete: true },
  { id: 'view-approval', name: 'Решения по резервному каналу', query: { family: 'ord', status: 'registered' }, shared: true, position: 20, can_delete: true },
]

export const DEMO_PROCESS_TEMPLATES = [
  { id: 'process-incident-doc', kind: 'document', name: 'Документ по сетевому инциденту', title: 'Материал INC-2471', description: 'Диагностика, проверка и решение руководителя службы', docKindId: 'kind-act', docKindName: 'Акт диагностики', taskTypeId: null, taskTypeName: null, steps: 3, requiresPreparation: true, preparationReason: 'Нужны объект, номер инцидента и результаты диагностики', defaultResponsibleId: 'engineer.ivanov', dueDays: 1, capabilities: ['assign', 'comments', 'files'] },
  { id: 'process-incident-task', kind: 'task', name: 'Работа по инциденту', title: 'Новое поручение INC-2471', description: 'Работа со сроком и контролем восстановления связи', taskTypeId: 'task-type-incident', taskTypeName: 'Инцидент', steps: 4, requiresPreparation: false, preparationReason: null, defaultResponsibleId: 'engineer.ivanov', dueDays: 1, capabilities: ['assign', 'transfer', 'comments', 'files'] },
]

export const DEMO_TASK_TEMPLATES = [
  { id: 'template-diagnostics', name: 'Диагностика резервного канала', title: 'Проверить overlay и резервный LTE', description: 'Зафиксировать интерфейсы, задержку, потери и доступность сервисов', type_id: 'task-type-incident', doc_kind_id: null, assignee_id: 'engineer.ivanov', object_id: 'object-forest', priority: 'high', due_days: 1, checklist: ['Проверить Ethernet и LTE', 'Проверить overlay', 'Приложить акт'] },
  { id: 'template-provider', name: 'Работа с провайдером', title: 'Подтвердить выезд на объект', description: 'Получить номер обращения и время восстановления Ethernet', type_id: 'task-type-incident', doc_kind_id: null, assignee_id: 'demo-operator', object_id: 'object-forest', priority: 'high', due_days: 1, checklist: ['Передать диагностику', 'Получить ETA', 'Обновить INC-2471'] },
  { id: 'template-mode', name: 'Согласование резервного режима', title: 'Согласовать работу через LTE', description: 'Зафиксировать срок и условия временного режима', type_id: 'task-type-incident', doc_kind_id: 'kind-order', assignee_id: 'lead.engineer', object_id: 'object-forest', priority: 'medium', due_days: 1, checklist: ['Проверить доступность сервисов', 'Утвердить контроль', 'Подписать распоряжение'] },
]

export const DEMO_TASK_VIEWS = [
  { id: 'task-view-week', name: 'Срок на этой неделе', query: { due: 'week', scope: 'open' }, shared: true, position: 10, can_delete: true },
  { id: 'task-view-overdue', name: 'Просроченные поручения', query: { overdue: '1', scope: 'open' }, shared: true, position: 20, can_delete: true },
]

export const DEMO_TASK_RECURRENCES = [
  { id: 'recurrence-control', template_id: 'template-diagnostics', template: 'Контроль резервного LTE до восстановления Ethernet', rule: { mode: 'daily', at: '09:00', tz: 'Europe/Moscow' }, assignee_id: 'engineer.ivanov', assignee: 'engineer.ivanov', next_at: dateFrom(1, 9), is_active: true },
]

export const DEMO_DOC_BOARD = {
  columns: [
    { key: 'diagnostics', name: 'Диагностика', docs: [{ id: 'doc-recovery-plan', title: 'План восстановления основного Ethernet-канала', reg_number: null, status: 'draft', kind_name: 'Акт диагностики', waiting: 1, due_at: dateFrom(1, 12), approval_due_at: dateFrom(0, 16), approval_overdue: false, waiting_people: [{ user_id: 'engineer.ivanov', name: 'engineer.ivanov', due_at: dateFrom(0, 16) }] }] },
    { key: 'provider', name: 'Ответ провайдера', docs: [{ id: 'doc-provider', title: 'Ответ провайдера по отказу Ethernet АЗС Лесная', reg_number: 'ВХ-2471/26', status: 'registered', kind_name: 'Входящее письмо', waiting: 1, due_at: dateFrom(0, 16), approval_due_at: dateFrom(0, 14), approval_overdue: false, waiting_people: [{ user_id: 'demo-operator', name: 'demo-operator', due_at: dateFrom(0, 14) }] }] },
    { key: 'sign', name: 'Решение руководителя', docs: [{ id: 'doc-lte-order', title: 'Распоряжение о временной работе АЗС Лесная через LTE', reg_number: 'РСП-2471/26', status: 'registered', kind_name: 'Распоряжение', waiting: 1, due_at: dateFrom(0, 15), approval_due_at: dateFrom(0, 15), approval_overdue: false, waiting_people: [{ user_id: 'lead.engineer', name: 'lead.engineer', due_at: dateFrom(0, 15) }] }] },
  ],
  total: 3, page: 1, page_size: 50, pages: 1,
  filter: { assignee_name: null, decision_name: null },
}

export const DEMO_APPROVAL_DISCIPLINE = {
  period: { date_from: '2026-08-01', date_to: '2026-08-24', cohort: 'first_approval_start', time_zone: 'Europe/Moscow', as_of: new Date().toISOString() },
  summary: { documents: 18, completed: 14, returned: 2, cancelled: 0, first_pass_rate: 85.7, first_pass_documents: 12, first_pass_sample: 14 },
  backlog: { scope: 'company', as_of: new Date().toISOString(), pending: 3, overdue: 0, people: [{ user_id: 'engineer.ivanov', name: 'engineer.ivanov', pending: 2, overdue: 0 }, { user_id: 'lead.engineer', name: 'lead.engineer', pending: 1, overdue: 0 }] },
  by_kind: [{ kind_id: 'kind-act', kind: 'Акт диагностики', documents: 8, average_hours: 4.4, median_hours: 3.2, p90_hours: 8.6 }, { kind_id: 'kind-incoming', kind: 'Входящее письмо', documents: 6, average_hours: 6.8, median_hours: 4.1, p90_hours: 12.5 }],
  people: [{ user_id: 'engineer.ivanov', name: 'engineer.ivanov', decisions: 11, documents: 9, late_documents: 0, late_decisions: 0, delegated_decisions: 0, estimated_decisions: 0, average_hours: 3.2, median_hours: 2.1, p90_hours: 6.4 }, { user_id: 'lead.engineer', name: 'lead.engineer', decisions: 7, documents: 7, late_documents: 0, late_decisions: 0, delegated_decisions: 0, estimated_decisions: 0, average_hours: 4.8, median_hours: 4.2, p90_hours: 7.5 }],
}

const workDoc = (doc: typeof DEMO_DOCS[number]) => ({
  id: doc.id, kind: 'doc' as const, key: doc.reg_number ?? 'черновик', title: doc.title,
  type: doc.kind_name, stage: null, state: doc.state, state_name: doc.state_name, status: doc.status,
  responsible: doc.responsible_id,
  responsible_id: doc.responsible_id, author: 'demo-operator', due_at: doc.due_at,
  overdue: false, object_id: doc.object_id, object: 'АЗС Лесная', project: 'INC-2471',
  project_id: null, priority: null, labels: doc.labels, updated_at: ago(22),
})

const workTask = (task: typeof DEMO_TASKS[number]) => ({
  id: task.id, kind: 'task' as const, key: task.key, title: task.title, type: task.type,
  stage: task.stage, state: task.state, state_name: task.state_name, status: task.status,
  responsible: task.assignee, responsible_id: task.assignee_id, author: task.author,
  due_at: task.due_at, overdue: task.overdue, object_id: task.object_id, object: task.object,
  project: task.project, project_id: task.project_id, priority: task.priority,
  labels: task.labels, updated_at: task.updated_at,
})

export const DEMO_WORK = [...DEMO_DOCS.map(workDoc), ...DEMO_TASKS.map(workTask)]

export const DEMO_MY_WORK = {
  mine: [
    { kind: 'doc', id: 'doc-lte-order', reason: 'approve', reason_name: 'Подписать', key: 'РСП-2471/26', title: 'Распоряжение о временной работе АЗС Лесная через LTE', note: 'Диагностика подтверждает доступность критичных сервисов', due_at: dateFrom(0, 15), overdue: false, bucket: 'today', state: 'approval', acting_for: null },
    { kind: 'doc', id: 'doc-inc-act', reason: 'acquaint', reason_name: 'Ознакомиться', key: 'АКТ-2471/26', title: 'Акт первичной диагностики INC-2471', note: 'Ethernet down, LTE up, overlay работает', due_at: dateFrom(0, 18), overdue: false, bucket: 'today', state: 'in_work', acquaint_id: 'acquaint-doc-act' },
    { kind: 'task', id: 'task-2473', reason: 'own', reason_name: 'Обновить статус', key: 'INC-2473', title: 'Подтвердить выезд провайдера на АЗС Лесная', note: 'Ожидается время восстановления Ethernet', due_at: dateFrom(0, 16), overdue: false, bucket: 'today', state: 'in_work' },
  ],
  buckets: [{ code: 'overdue', name: 'Просрочено' }, { code: 'today', name: 'Сегодня' }, { code: 'week', name: 'На этой неделе' }, { code: 'later', name: 'Позже' }],
}
