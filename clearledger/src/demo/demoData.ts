const COMPANY_ID = '00000000-0000-4000-8000-000000000001'
const COMPANY_NAME = 'ООО «Полюс Ритейл»'
const COMPANY_SHORT_NAME = 'ПОЛЮС РИТЕЙЛ'
const COMPANY_SLUG = 'polus-retail'

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()
const daysFromNow = (days: number, hour = 12) => {
  const date = new Date()
  date.setDate(date.getDate() + days)
  date.setHours(hour, 0, 0, 0)
  return date.toISOString()
}

export const DEMO_COMPANY_ID = COMPANY_ID

export const DEMO_AUTH_USER = {
  id: 'demo-operator',
  email: 'demo-operator@polus.demo',
  name: 'demo-operator',
  role: 'admin',
  is_superadmin: true,
  default_company_id: COMPANY_ID,
  position: 'Оператор центрального офиса',
  party_type: 'internal' as const,
  company_name: COMPANY_NAME,
  company_role: 'admin',
  companies: [{
    id: COMPANY_ID,
    slug: COMPANY_SLUG,
    name: COMPANY_NAME,
    short_name: COMPANY_SHORT_NAME,
    color: '#2563eb',
    profile_id: 'office',
    role: 'admin' as const,
    modules: null,
  }],
}

const app = (
  code: string, name: string, icon: string, layer: 'admin' | 'service' | 'app',
  route: string | undefined, description: string,
) => ({
  code, name, icon, layer, route,
  mode: route ? 'internal' as const : 'link' as const,
  base_url: route ?? '', callback: '', description,
})

const catalogApp = (code: string, name: string, icon: string, description: string) => ({
  ...app(code, name, icon, 'app', undefined, description),
  mode: 'internal' as const,
})

const CATALOG_APP_CODES = new Set([
  'pulse', 'support', 'projects', 'ops', 'corp', 'shop', 'marketing',
  'monitor', 'netlink', 'books', 'revenue', 'retail_store', 'econ', 'diag',
  'perimeter',
])

export const DEMO_SSO_APPS = [
  app('admin', 'Управление', 'shield-check', 'admin', '/admin',
    'Люди, роли, доступы, объекты и журнал пространства'),
  catalogApp('pulse', 'Пульс', 'activity',
    'Рабочее место руководителя: показатели, отклонения и решения'),
  catalogApp('support', 'Поддержка', 'life-buoy',
    'Заявки, обращения и обслуживание клиентов'),
  catalogApp('projects', 'Проекты', 'hard-hat',
    'Стройка сети: площадки, портфель проектов, присоединение и ввод'),
  catalogApp('ops', 'Эксплуатация', 'gauge',
    'Состояние сети; в топливном пространстве — «Управленческий»'),
  catalogApp('monitor', 'Монитор', 'gauge',
    'Состояние и наблюдение за оборудованием торговых точек'),
  catalogApp('books', 'Бухгалтерия', 'book-open',
    'Учёт, проводки, документы и закрытие периода'),
  catalogApp('revenue', 'Реализация', 'bar-chart-3',
    'Продажи, отгрузки и документы реализации'),
  catalogApp('retail_store', 'Розничный магазин', 'shopping-cart',
    'Торговый зал, ассортимент, остатки, цены, чеки и маркировка'),
  catalogApp('econ', 'Экономика', 'wallet',
    'Финансовый результат, экономика и налоги'),
  catalogApp('perimeter', 'Периметр', 'shield-check',
    'Контур объектов, границы ответственности и контроль состояния'),
  catalogApp('netlink', 'Сеть передачи данных', 'network',
    'Каналы связи объектов, VPN, удалённый доступ и обновления'),
  catalogApp('diag', 'Диагностика', 'stethoscope',
    'Состояние служб, интеграций, очередей и качества загрузки'),
  catalogApp('shop', 'Интернет-магазин', 'shopping-cart',
    'Товары и заказы; в топливном пространстве — «Магазин»'),
  catalogApp('corp', 'Корпоративный процессинг', 'building-2',
    'Юридические лица: договоры, лимиты и счета'),
  catalogApp('marketing', 'Маркетинг', 'megaphone',
    'Кампании, акции, сегменты и коммуникации с клиентами'),
  app('chat', 'Чаты', 'message-circle', 'service', '/messages',
    'Переписка, каналы и рабочие группы пространства'),
  app('docs', 'Трек', 'file-text', 'service', '/docs',
    'Документооборот, согласования, поручения и регламент'),
  app('conf', 'Конференции', 'video', 'service', undefined,
    'Без регистрации, прямо в браузере — ссылка участникам в буфере'),
  app('connect', 'Подключения', 'network', 'admin', '/connect',
    'Источники, каналы, расписания и состояние интеграций'),
  app('data', 'Данные', 'database', 'admin', '/data',
    'Откуда берутся цифры: загрузка, нормализация и качество'),
  app('info', 'Инфо', 'book-open', 'admin', '/info',
    'Инструкции, нормы и документы компании там, где они нужны'),
]

const ADMIN_MODULES = [
  ['profile', 'Реквизиты'], ['members', 'Сотрудники'], ['roles', 'Роли и доступ'],
  ['invites', 'Приглашения'], ['partners', 'Компании'], ['counterparties', 'Контрагенты'],
  ['objects', 'Объекты'], ['refs', 'Договоры и оборудование'], ['map', 'Карта'],
  ['audit', 'Журнал'],
]

const CONNECT_MODULES = [
  ['connections', 'Состояние'], ['connectors', 'Коннекторы'], ['sources', 'Источники'],
  ['catalog', 'Каталог типов'], ['notifications', 'Оповещения'], ['apps', 'Приложения и модули'],
]

const DATA_MODULES = [
  ['normalize', 'Нормализация'], ['reconcile', 'Сверка'], ['data_sources', 'Источники'],
  ['data_model', 'База пространства'], ['data_quality', 'Качество данных'],
]

const modulesFor = (code: string) => {
  const rows = code === 'admin' ? ADMIN_MODULES : code === 'connect' ? CONNECT_MODULES
    : code === 'data' ? DATA_MODULES : []
  return rows.map(([moduleCode, name]) => ({
    code: moduleCode, name, isCore: code === 'admin', enabled: true,
  }))
}

export const DEMO_COMPANY_APPS = DEMO_SSO_APPS.filter((item) => !CATALOG_APP_CODES.has(item.code)).map((item, index) => ({
  id: `demo-app-${index + 1}`,
  code: item.code,
  name: item.name,
  description: item.description,
  baseUrl: item.route ?? null,
  icon: item.icon,
  enabled: true,
  modules: modulesFor(item.code),
}))

export const DEMO_DISABLED_APPS = [
  ...DEMO_SSO_APPS.filter((item) => CATALOG_APP_CODES.has(item.code)).map((item, index) => ({
    id: `demo-app-catalog-${index + 1}`,
    code: item.code,
    name: item.name,
    description: item.description,
    baseUrl: null,
    icon: item.icon,
    enabled: false,
    modules: [],
  })),
]

export const DEMO_ACCESS_CATALOG = DEMO_COMPANY_APPS.map((item) => ({
  app: item.code,
  name: item.name,
  icon: item.icon ?? undefined,
  modules: item.modules.map((module) => ({
    key: `${item.code}:${module.code}`, code: module.code, name: module.name,
  })),
}))

export const DEMO_USERS = [
  {
    id: 'demo-operator', email: 'demo-operator@polus.demo', name: 'demo-operator',
    role: 'admin', position: 'Оператор центрального офиса', modules: null,
    role_id: 'role-operator', role_name: 'Оператор', party_type: 'internal',
    organization_id: null, organization_name: null, object_scope: null,
    department_id: 'dep-operations', department_name: 'Центральный офис', is_superadmin: true,
    last_seen_at: minutesAgo(1), companies: [{ slug: COMPANY_SLUG, name: COMPANY_SHORT_NAME, role: 'admin' }],
  },
  {
    id: 'engineer.ivanov', email: 'engineer.ivanov@polus.demo', name: 'engineer.ivanov',
    role: 'user', position: 'Инженер сети', modules: ['docs', 'info', 'chat', 'connect', 'data'],
    role_id: 'role-engineer', role_name: 'Инженер', party_type: 'internal',
    organization_id: null, organization_name: null, object_scope: null,
    department_id: 'dep-network', department_name: 'Служба эксплуатации сети', is_superadmin: false,
    last_seen_at: minutesAgo(4), companies: [{ slug: COMPANY_SLUG, name: COMPANY_SHORT_NAME, role: 'user' }],
  },
  {
    id: 'lead.engineer', email: 'lead.engineer@polus.demo', name: 'lead.engineer',
    role: 'user', position: 'Руководитель службы эксплуатации', modules: ['docs', 'info', 'chat', 'conf', 'connect', 'data'],
    role_id: 'role-lead', role_name: 'Руководитель службы', party_type: 'internal',
    organization_id: null, organization_name: null, object_scope: null,
    department_id: 'dep-network', department_name: 'Служба эксплуатации сети', is_superadmin: false,
    last_seen_at: minutesAgo(7), companies: [{ slug: COMPANY_SLUG, name: COMPANY_SHORT_NAME, role: 'user' }],
  },
]

export const DEMO_ROLES = [
  { id: 'role-operator', name: 'Оператор', modules: null, is_system: true, members_count: 1 },
  { id: 'role-engineer', name: 'Инженер', modules: ['docs', 'info', 'chat', 'connect', 'data'], is_system: false, members_count: 1 },
  { id: 'role-lead', name: 'Руководитель службы', modules: ['docs', 'info', 'chat', 'conf', 'connect', 'data'], is_system: false, members_count: 1 },
]

export const DEMO_DEPARTMENTS = [
  { id: 'dep-operations', name: 'Центральный офис', code: 'OPERATIONS', parent_id: null, manager_id: 'demo-operator', manager_name: 'demo-operator', sort_order: 10 },
  { id: 'dep-network', name: 'Служба эксплуатации сети', code: 'NETWORK', parent_id: null, manager_id: 'lead.engineer', manager_name: 'lead.engineer', sort_order: 20 },
]

export const DEMO_ORGANIZATIONS = [
  {
    id: 'org-polus', name: COMPANY_NAME, shortName: 'Полюс Ритейл',
    inn: '7805123456', kpp: '780501001', type: 'own',
    legalAddress: '190020, Санкт-Петербург, Лифляндская улица, 6',
    actualAddress: '191040, Санкт-Петербург, Лиговский проспект, 50',
    phone: '+7 812 000-24-71', email: 'office@polus.demo',
  },
  {
    id: 'org-telecom', name: 'ООО «Телеком Сервис»', shortName: 'Телеком Сервис',
    inn: '7806123456', kpp: '780601001', type: 'counterparty',
    legalAddress: '195027, Санкт-Петербург, Магнитогорская улица, 23',
    actualAddress: '195027, Санкт-Петербург, Магнитогорская улица, 23',
    phone: '+7 812 000-47-21', email: 'support@telecom.demo',
  },
  {
    id: 'org-reserve', name: 'ООО «Связь Резерв»', shortName: 'Связь Резерв',
    inn: '7812123456', kpp: '781201001', type: 'counterparty',
    legalAddress: '197110, Санкт-Петербург, Пионерская улица, 30', actualAddress: null,
    phone: '+7 812 000-24-72', email: 'noc@reserve.demo',
  },
]

export const DEMO_CONTRACTS = [
  {
    id: 'contract-telecom', number: 'NET-18/26', date: '2026-03-14', type: 'Услуги связи',
    kind: 'service', direction: 'in', basis: 'Основные Ethernet-каналы сети АЗС',
    counterpartyId: 'org-telecom', counterpartyName: 'ООО «Телеком Сервис»',
    counterpartyInn: '7806123456', scopeType: 'objects', objectsCount: 5,
    validUntil: '2027-03-13', isClosed: false,
  },
  {
    id: 'contract-reserve', number: 'LTE-2471', date: '2026-01-10', type: 'Резервная связь',
    kind: 'service', direction: 'in', basis: 'Резервные LTE-каналы сети АЗС',
    counterpartyId: 'org-reserve', counterpartyName: 'ООО «Связь Резерв»',
    counterpartyInn: '7812123456', scopeType: 'objects', objectsCount: 5,
    validUntil: '2027-01-09', isClosed: false,
  },
]

export const DEMO_OBJECTS = [
  { id: 'object-forest', companyId: COMPANY_ID, code: 'AZS-LES', name: 'АЗС Лесная', type: 'station', status: 'active', operationalStatus: 'degraded', address: 'Лесное шоссе, 42', city: 'Санкт-Петербург', street: 'Лесное шоссе', house: '42', latitude: 60.0574, longitude: 30.3349, regionId: '78', description: 'INC-2471: Ethernet недоступен, критичный трафик работает через резервный LTE', createdAt: '2026-01-10T09:00:00Z', updatedAt: minutesAgo(2) },
  { id: 'object-south', companyId: COMPANY_ID, code: 'AZS-YUG', name: 'АЗС Южная', type: 'station', status: 'active', operationalStatus: 'operational', address: 'Южное шоссе, 91', city: 'Санкт-Петербург', street: 'Южное шоссе', house: '91', latitude: 59.8437, longitude: 30.4374, regionId: '78', description: 'Основной Ethernet-канал работает штатно', createdAt: '2026-01-12T09:00:00Z', updatedAt: minutesAgo(8) },
  { id: 'object-port', companyId: COMPANY_ID, code: 'AZS-PORT', name: 'АЗС Портовая', type: 'station', status: 'active', operationalStatus: 'operational', address: 'Портовая улица, 7', city: 'Санкт-Петербург', street: 'Портовая улица', house: '7', latitude: 59.8899, longitude: 30.2516, regionId: '78', description: 'Основной Ethernet-канал работает штатно', createdAt: '2026-01-14T09:00:00Z', updatedAt: minutesAgo(11) },
  { id: 'object-central', companyId: COMPANY_ID, code: 'AZS-CENTR', name: 'АЗС Центральная', type: 'station', status: 'active', operationalStatus: 'operational', address: 'Центральная улица, 10', city: 'Санкт-Петербург', street: 'Центральная улица', house: '10', latitude: 59.9343, longitude: 30.3351, regionId: '78', description: 'Основной Ethernet-канал работает штатно', createdAt: '2026-01-16T09:00:00Z', updatedAt: minutesAgo(15) },
  { id: 'object-lake', companyId: COMPANY_ID, code: 'AZS-LAKE', name: 'АЗС Озёрная', type: 'station', status: 'active', operationalStatus: 'operational', address: 'Озёрный проезд, 5', city: 'Санкт-Петербург', street: 'Озёрный проезд', house: '5', latitude: 60.0131, longitude: 30.2856, regionId: '78', description: 'Штатная работа, резервный LTE готов', createdAt: '2026-01-18T09:00:00Z', updatedAt: minutesAgo(19) },
]

export const DEMO_EQUIPMENT = [
  { id: 'eq-forest-gw', ecoObjectId: 'object-forest', type: 'network', model: 'Gateway G2', manufacturer: 'ElsyPlus', serialNumber: 'POLUS-GW-LES', inventoryNumber: 'СЕТЬ-001', status: 'active', state: 'Резервный LTE' },
  { id: 'eq-south-gw', ecoObjectId: 'object-south', type: 'network', model: 'Gateway G2', manufacturer: 'ElsyPlus', serialNumber: 'POLUS-GW-YUG', inventoryNumber: 'СЕТЬ-002', status: 'active', state: 'В работе' },
  { id: 'eq-port-gw', ecoObjectId: 'object-port', type: 'network', model: 'Gateway G2', manufacturer: 'ElsyPlus', serialNumber: 'POLUS-GW-PORT', inventoryNumber: 'СЕТЬ-003', status: 'active', state: 'В работе' },
  { id: 'eq-central-gw', ecoObjectId: 'object-central', type: 'network', model: 'Gateway G2', manufacturer: 'ElsyPlus', serialNumber: 'POLUS-GW-CENTR', inventoryNumber: 'СЕТЬ-004', status: 'active', state: 'В работе' },
  { id: 'eq-lake-gw', ecoObjectId: 'object-lake', type: 'network', model: 'Gateway G2', manufacturer: 'ElsyPlus', serialNumber: 'POLUS-GW-LAKE', inventoryNumber: 'СЕТЬ-005', status: 'active', state: 'В работе' },
]

const personApps = (codes: string[]) => codes

export const DEMO_SPACE_MAP = {
  windowDays: 30,
  companies: [{
    id: COMPANY_ID, name: COMPANY_NAME, slug: COMPANY_SLUG,
    apps: DEMO_SSO_APPS.map((item) => ({ code: item.code, name: item.name, enabled: true })),
    people: [
      { id: 'demo-operator', name: 'demo-operator', email: 'demo-operator@polus.demo', partyType: 'internal', orgName: null, role: 'Оператор', position: 'Оператор центрального офиса', isSuperadmin: true, apps: personApps(DEMO_COMPANY_APPS.map((x) => x.code)), fullAccess: true, lastSeenAt: minutesAgo(1), online: true, events: 42 },
      { id: 'engineer.ivanov', name: 'engineer.ivanov', email: 'engineer.ivanov@polus.demo', partyType: 'internal', orgName: null, role: 'Инженер', position: 'Инженер сети', isSuperadmin: false, apps: personApps(['docs', 'info', 'chat', 'connect', 'data']), fullAccess: false, lastSeenAt: minutesAgo(4), online: true, events: 31 },
      { id: 'lead.engineer', name: 'lead.engineer', email: 'lead.engineer@polus.demo', partyType: 'internal', orgName: null, role: 'Руководитель службы', position: 'Руководитель службы эксплуатации', isSuperadmin: false, apps: personApps(['docs', 'info', 'chat', 'conf', 'connect', 'data']), fullAccess: false, lastSeenAt: minutesAgo(7), online: true, events: 24 },
    ],
    counts: { people: 3, online: 3, internal: 3, partners: 0, neverSeen: 0, noAccess: 0, objects: 5, organizations: 3, equipment: 5, events: 97 },
    topActions: [
      { action: 'auth.login', count: 34 }, { action: 'sso.handoff', count: 26 },
      { action: 'member.access', count: 8 }, { action: 'space.object.update', count: 4 },
    ],
  }],
  recentEvents: [
    { at: minutesAgo(3), company: COMPANY_SHORT_NAME, userName: 'engineer.ivanov', action: 'incident.update', summary: 'INC-2471: подтверждена работа АЗС Лесная через LTE' },
    { at: minutesAgo(7), company: COMPANY_SHORT_NAME, userName: 'lead.engineer', action: 'doc.approval', summary: 'Согласован временный режим резервного канала' },
    { at: minutesAgo(12), company: COMPANY_SHORT_NAME, userName: 'demo-operator', action: 'auth.login', summary: 'Вход в пространство' },
  ],
}

export const DEMO_CORE_STATUS = {
  version: '1.2.146', env: 'demo',
  sso: { enabled: true, issuer: 'space.demo.local', kid: 'demo-key', jwksKeys: 1, apps: DEMO_SSO_APPS.length },
  registry: { apps: DEMO_SSO_APPS.length, modules: ADMIN_MODULES.length + CONNECT_MODULES.length + DATA_MODULES.length },
  counts: { companies: 1, users: DEMO_USERS.length },
  services: [
    { code: 'chat', name: 'Чаты', configured: true, status: 'up' },
    { code: 'conf', name: 'Конференции', configured: true, status: 'up' },
    { code: 'mail', name: 'Почта', configured: true, status: 'up' },
  ],
}

export const DEMO_ACTIVITY = {
  days: 30,
  totals: { logins: 41, logins_7d: 18, failed: 1, connected: 3, removed: 0, unique_people: 3 },
  invitations: { pending: 1, expired: 0, accepted: 1 },
  people: DEMO_USERS.map((user, index) => ({
    user_id: user.id, name: user.name, active_days: 19 - index * 2,
    logins: 9 - index, last_at: user.last_seen_at, share: 63 - index * 7,
  })),
}

export const DEMO_AUDIT = [
  { id: 'audit-1', company_id: COMPANY_ID, user_id: 'engineer.ivanov', user_name: 'engineer.ivanov', action: 'incident.update', details: 'INC-2471 · АЗС Лесная · Ethernet down, LTE active', timestamp: minutesAgo(3) },
  { id: 'audit-2', company_id: COMPANY_ID, user_id: 'lead.engineer', user_name: 'lead.engineer', action: 'doc.approval', details: 'INC-2471 · временный режим резервного канала согласован', timestamp: minutesAgo(7) },
  { id: 'audit-3', company_id: COMPANY_ID, user_id: 'demo-operator', user_name: 'demo-operator', action: 'task.create', details: 'INC-2471 · восстановить основной Ethernet-канал АЗС Лесная', timestamp: minutesAgo(18) },
  { id: 'audit-4', company_id: COMPANY_ID, user_id: 'demo-operator', user_name: 'demo-operator', action: 'auth.login', details: 'Вход в пространство', timestamp: minutesAgo(24) },
]

export const DEMO_DATA_MODEL = {
  domains: [
    { key: 'space', label: 'Пространство', entities: [
      { key: 'people', label: 'Люди', table: 'users', records: 3, sources: 'Управление', consumers: 'Чаты · Трек', link: '/admin/company/members', gap: 0, gapLabel: null },
      { key: 'organizations', label: 'Организации', table: 'organizations', records: 3, sources: 'Бухгалтерия · Управление', consumers: 'Трек · Финансы', link: '/admin/company/counterparties', gap: 0, gapLabel: null },
      { key: 'objects', label: 'Объекты', table: 'service_locations', records: 5, sources: 'Управление', consumers: 'Подключения · Трек', link: '/admin/company/objects', gap: 0, gapLabel: null },
    ] },
    { key: 'work', label: 'Работа', entities: [
      { key: 'documents', label: 'Документы', table: 'docs', records: 4, sources: 'Трек · Подключения', consumers: 'Трек · Инфо', link: '/docs', gap: 0, gapLabel: null },
      { key: 'tasks', label: 'Поручения', table: 'tasks', records: 4, sources: 'Трек · Чаты', consumers: 'Трек · Управление', link: '/docs/work', gap: 0, gapLabel: null },
      { key: 'incidents', label: 'Инциденты', table: 'incidents', records: 1, sources: 'Подключения', consumers: 'Трек · Чаты · Данные', link: '/docs/work', gap: 0, gapLabel: null },
    ] },
  ],
  totals: { entities: 6, records: 20, gaps: 0, filled: 20 },
}

export const DEMO_DATA_QUALITY = {
  groups: [
    { label: 'Связи пространства', checks: [
      { key: 'docs-with-case', label: 'Документы без дела', group: 'Связи пространства', count: 0, target: 0, severity: 'warn', hint: 'Все документы INC-2471 помещены в дело', ok: true, error: null },
      { key: 'people-with-role', label: 'Люди без роли доступа', group: 'Связи пространства', count: 0, target: 0, severity: 'warn', hint: 'Назначьте роль в Управлении', ok: true, error: null },
    ] },
    { label: 'Полнота карточек', checks: [
      { key: 'forest-primary-link', label: 'Объекты без основного канала', group: 'Полнота карточек', count: 1, target: 0, severity: 'warn', hint: 'АЗС Лесная работает через резервный LTE, INC-2471 открыт', ok: false, error: null },
    ] },
  ],
  totals: { checks: 3, clean: 2, issues: 1 },
}

export const DEMO_INFO_ARTICLES = [
  {
    id: 'info-start', title: 'Как устроено рабочее пространство',
    summary: 'Ядро, приложения и общие сервисы: что где искать.', kind: 'guide', kindLabel: 'Инструкция',
    scope: 'platform', categoryId: 'info-platform', docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['пространство', 'приложения', 'доступ'], processRef: null,
    updatedAt: '2026-08-20T10:00:00Z',
    bodyMd: '# Как устроено рабочее пространство\n\n**Пространство «Полюс Ритейл»** объединяет людей, доступы, пять АЗС и рабочие сервисы компании.\n\n- **Управление** — люди, роли, объекты и журнал.\n- **Трек** — документы и поручения по INC-2471.\n- **Чаты** и **Конференции** — координация восстановления связи.\n- **Подключения** и **Данные** — состояние обмена и единая картина по сети.\n\nВ текущем сценарии основной Ethernet-канал АЗС Лесная недоступен, а критичный трафик продолжает работать через резервный LTE.',
    bindings: [{ appCode: 'admin', sectionKey: null, weight: 100 }],
  },
  {
    id: 'info-access', title: 'Роли и доступ к приложениям',
    summary: 'Как выдать человеку рабочее место и не открыть лишнее.', kind: 'guide', kindLabel: 'Инструкция',
    scope: 'platform', categoryId: 'info-admin', docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['роли', 'доступ', 'люди'], processRef: null,
    updatedAt: '2026-08-18T11:20:00Z',
    bodyMd: '# Роли и доступ\n\nДоступ состоит из двух частей: **какие приложения видит человек** и **какие объекты внутри них ему доступны**.\n\n`demo-operator` координирует инцидент из центрального офиса, `engineer.ivanov` ведёт диагностику и документы, `lead.engineer` согласует аварийный режим. Роли назначаются в «Управление → Роли и доступ», а действия остаются в журнале.',
    bindings: [{ appCode: 'admin', sectionKey: 'roles', weight: 100 }],
  },
  {
    id: 'info-docs', title: 'Регламент работы при отказе основного канала',
    summary: 'Диагностика, резервный LTE, фиксация решений и восстановление Ethernet.', kind: 'lnd', kindLabel: 'Документ компании',
    scope: 'company', categoryId: 'info-company', docNumber: 'РГ-СЕТЬ-04/26', effectiveDate: '2026-05-01',
    sourceUrl: null, tags: ['инцидент', 'Ethernet', 'LTE', 'INC-2471'], processRef: 'docs:incident-response',
    updatedAt: '2026-08-16T09:00:00Z',
    bodyMd: '# Регламент работы при отказе основного канала\n\n1. Оператор регистрирует инцидент и подтверждает переход на резервный LTE.\n2. Инженер проверяет overlay, доступность критичных сервисов, задержку и потери.\n3. Руководитель службы согласует временный режим до восстановления Ethernet.\n4. Диагностика, уведомление провайдеру и итоговый акт сохраняются в Треке.\n\nДля АЗС Лесная эти действия объединены инцидентом **INC-2471**.',
    bindings: [{ appCode: 'docs', sectionKey: 'registry', weight: 100 }],
  },
  {
    id: 'info-faq', title: 'Как начать конференцию',
    summary: 'Комната создаётся одной кнопкой, гостевая ссылка копируется автоматически.', kind: 'faq', kindLabel: 'Вопросы',
    scope: 'platform', categoryId: null, docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['конференции', 'встречи'], processRef: null,
    updatedAt: '2026-08-12T15:30:00Z',
    bodyMd: '# Как начать конференцию\n\nНажмите **«Конференция»** в шапке. Пространство создаст комнату `INC-2471 · АЗС Лесная` и скопирует гостевую ссылку. Участникам не нужна отдельная регистрация; в демо ссылка никуда не отправляется и внешний сервис не открывается.',
    bindings: [{ appCode: 'conf', sectionKey: null, weight: 100 }],
  },
  {
    id: 'info-connect', title: 'Подключение источника и первый обмен',
    summary: 'От источника до рабочего канала: проверка связи, расписание и контроль результата.', kind: 'guide', kindLabel: 'Инструкция',
    scope: 'platform', categoryId: 'info-connect', docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['источники', 'каналы', 'обмен'], processRef: 'connect:first-channel',
    updatedAt: '2026-08-23T13:10:00Z',
    bodyMd: '# Подключения сети АЗС\n\n1. Источник **Шлюзы АЗС** принимает состояние каналов пяти объектов.\n2. Канал **Телеметрия сети АЗС** обновляет снимок каждые пять минут.\n3. При отказе Ethernet АЗС Лесная источник фиксирует резервный LTE и связывает событие с **INC-2471**.\n4. В журнале видны последний успешный обмен, 164 мс задержки и отсутствие потери критичных сервисов.\n\nАдреса и ключи в демонстрационном контуре вымышлены.',
    bindings: [{ appCode: 'connect', sectionKey: 'connections', weight: 100 }],
  },
  {
    id: 'info-data', title: 'Как читать модель и качество данных',
    summary: 'Слои данных, справочники, полнота полей и контрольные проверки.', kind: 'guide', kindLabel: 'Инструкция',
    scope: 'platform', categoryId: 'info-data', docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['данные', 'качество', 'нормализация'], processRef: 'data:quality',
    updatedAt: '2026-08-23T12:40:00Z',
    bodyMd: '# Модель и качество данных\n\n**L0** хранит снимок телеметрии шлюзов, **L1** приводит статусы Ethernet и LTE к единому формату, а **L2** связывает их с карточками АЗС, людьми и инцидентами.\n\nПроверка качества показывает один ожидаемый разрыв: у АЗС Лесная недоступен основной канал. Запись не потеряна — она связана с **INC-2471**, ответственным `engineer.ivanov` и действующим резервным LTE.',
    bindings: [{ appCode: 'data', sectionKey: 'normalize', weight: 100 }],
  },
  {
    id: 'info-track', title: 'Как вести сетевой инцидент в Треке',
    summary: 'Документы, поручения, согласование и история INC-2471.', kind: 'guide', kindLabel: 'Инструкция',
    scope: 'platform', categoryId: 'info-track', docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['трек', 'инцидент', 'INC-2471'], processRef: 'docs:incident',
    updatedAt: '2026-09-05T12:00:00Z',
    bodyMd: `# Сетевой инцидент в Треке

Трек самостоятельно ведёт поручения, документы и согласование. Приложения используют те же функции, передавая контекст своей работы и настройки сценария.

## Что посмотреть в этом демо

1. Откройте поручения по **INC-2471 · АЗС Лесная**: видны исполнитель, срок и состояние.
2. В документах найдите акт диагностики, ответ провайдера и распоряжение о временной работе через LTE.
3. Откройте согласование распоряжения: оператор координирует инцидент, инженер ведёт диагностику, руководитель службы принимает решение.

## Как это работает с приложениями

В рабочем пространстве при создании из сообщения можно выбрать контекст проекта или объекта, применить настройки приложения, проверить исполнителя, срок и шаблон. Карточка сохраняет ссылку на исходное сообщение.

После выполнения блок **«Результаты для приложений»** показывает передачу результата. При ошибке можно повторить доставку; выполненное поручение остаётся выполненным. Следующий этап определяется правилами приложения.

Этот локальный показ содержит вымышленные данные для просмотра. Создание работы и передача результата здесь не выполняются. Полный сценарий приложения «Проекты» демонстрируется отдельно.`,
    bindings: [{ appCode: 'docs', sectionKey: null, weight: 110 }],
  },
  {
    id: 'info-chat', title: 'Какие чаты использовать для работы',
    summary: 'Общий чат, объявления, рабочие группы и внешние участники.', kind: 'faq', kindLabel: 'Вопросы',
    scope: 'platform', categoryId: null, docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['чаты', 'каналы', 'внешние участники'], processRef: null,
    updatedAt: '2026-09-05T12:00:00Z',
    bodyMd: `# Какие чаты использовать

Чат работает самостоятельно: общий разговор, объявления и рабочие группы доступны без проекта или поручения. Приложение может связать комнату со своей работой и предложить дополнительные действия.

## Что посмотреть в этом демо

**Сеть АЗС** показывает оперативную картину, **Оперативные уведомления** — изменения режима, а группа **INC-2471 · АЗС Лесная** собирает переписку по инциденту. Сроки и документы смотрите в Треке.

## Из сообщения в работу

В рабочем пространстве нажмите на сообщении **«Поручить»** или запустите процесс. Проверьте контекст, исполнителя, срок и шаблон. **«Применить настройки приложения»** подставляет предложенные приложением значения. Контекст можно убрать, чтобы вести самостоятельную работу.

У сообщения появляется ссылка на работу и её текущее состояние; из карточки можно вернуться к исходной реплике. Доступ к чату и документу проверяется отдельно.

У проекта основная группа предназначена для команды. Для внешнего участника используют отдельный разговор. В локальном демо приглашения и создание работы не выполняются.`,
    bindings: [{ appCode: 'chat', sectionKey: null, weight: 100 }],
  },
  {
    id: 'info-apps', title: 'Как подключаются бизнес-приложения',
    summary: 'Компания выбирает нужные рабочие места поверх общего ядра.', kind: 'faq', kindLabel: 'Вопросы',
    scope: 'platform', categoryId: null, docNumber: null, effectiveDate: null,
    sourceUrl: null, tags: ['приложения', 'подключение', 'каталог'], processRef: null,
    updatedAt: '2026-09-05T12:00:00Z',
    bodyMd: '# Подключение бизнес-приложений\n\nКомпания подключает приложения под свои задачи. Чат и Трек доступны самостоятельно и предоставляют приложениям общие функции обсуждения, поручений, документов и согласования.\n\nПриложение передаёт контекст, участников, шаблоны и настройки, а затем получает результат. Например, «Проекты» определяют этапы закупки и приёмки, используя согласование документов в Треке и переписку в Чате.\n\nВ этом демо «Проекты» и другие прикладные приложения представлены в каталоге. Их полные сценарии показываются отдельно; подключение из локального демо не выполняется.',
    bindings: [{ appCode: 'admin', sectionKey: 'apps', weight: 90 }],
  },
]

export const demoInfoRow = (article: typeof DEMO_INFO_ARTICLES[number]) => ({
  id: article.id,
  title: article.title,
  summary: article.summary,
  kind: article.kind,
  kindLabel: article.kindLabel,
  scope: article.scope,
  categoryId: article.categoryId,
  docNumber: article.docNumber,
  effectiveDate: article.effectiveDate,
  sourceUrl: article.sourceUrl,
  tags: article.tags,
  processRef: article.processRef,
  updatedAt: article.updatedAt,
})

export const DEMO_INFO_TREE = {
  profile: 'fuel', total: DEMO_INFO_ARTICLES.length,
  groups: [
    { key: 'guide', label: 'Инструкции', hint: 'Как работать в системе', count: 5,
      categories: [
        { id: 'info-platform', title: 'Начало работы', articles: [demoInfoRow(DEMO_INFO_ARTICLES[0])] },
        { id: 'info-admin', title: 'Управление', articles: [demoInfoRow(DEMO_INFO_ARTICLES[1])] },
        { id: 'info-connect', title: 'Подключения', articles: [demoInfoRow(DEMO_INFO_ARTICLES[4])] },
        { id: 'info-data', title: 'Данные', articles: [demoInfoRow(DEMO_INFO_ARTICLES[5])] },
        { id: 'info-track', title: 'Трек', articles: [demoInfoRow(DEMO_INFO_ARTICLES[6])] },
      ], loose: [] },
    { key: 'norm', label: 'Нормы', hint: 'Отраслевые требования', count: 0, categories: [], loose: [] },
    { key: 'lnd', label: 'Документы компании', hint: 'Регламенты и приказы', count: 1,
      categories: [{ id: 'info-company', title: 'Регламенты', articles: [demoInfoRow(DEMO_INFO_ARTICLES[2])] }], loose: [] },
    { key: 'faq', label: 'Вопросы', hint: 'Короткие ответы', count: 3,
      categories: [], loose: [demoInfoRow(DEMO_INFO_ARTICLES[3]), demoInfoRow(DEMO_INFO_ARTICLES[7]), demoInfoRow(DEMO_INFO_ARTICLES[8])] },
  ],
}

export const DEMO_CHAT_ROOMS = [
  { id: 'room-general', type: 'company', kind: 'general', scopeProduct: null, name: 'Сеть АЗС', isArchived: false, participantCount: 3, unreadCount: 2, directPeerId: null, lastMessage: 'Критичные сервисы АЗС Лесная доступны через LTE', lastMessageAt: minutesAgo(3), createdBy: 'demo-operator', pinnedMessage: { id: 'msg-pin', content: 'INC-2471 · АЗС Лесная · Ethernet недоступен, резервный LTE активен', userName: 'demo-operator' }, myRole: 'owner', avatarUrl: null, mutedUntil: null, isPinned: true, canWrite: true, scopeObjectId: null, scopeObjectName: null, scopeTicketId: 'INC-2471' },
  { id: 'room-news', type: 'channel', kind: 'news', scopeProduct: null, name: 'Оперативные уведомления', isArchived: false, participantCount: 3, unreadCount: 1, directPeerId: null, lastMessage: 'Временный режим LTE согласован до восстановления Ethernet', lastMessageAt: minutesAgo(7), createdBy: 'lead.engineer', pinnedMessage: null, myRole: 'member', avatarUrl: null, mutedUntil: null, isPinned: false, canWrite: true, scopeObjectId: null, scopeObjectName: null, scopeTicketId: 'INC-2471' },
  { id: 'room-incident', type: 'group', kind: 'app:docs', scopeProduct: 'docs', name: 'INC-2471 · АЗС Лесная', isArchived: false, participantCount: 3, unreadCount: 0, directPeerId: null, lastMessage: 'Акт диагностики добавлен в Трек', lastMessageAt: minutesAgo(12), createdBy: 'demo-operator', pinnedMessage: { id: 'msg-pin-incident', content: 'Карточка в Треке: INC-2471', userName: 'demo-operator' }, myRole: 'owner', avatarUrl: null, mutedUntil: null, isPinned: true, canWrite: true, scopeObjectId: 'object-forest', scopeObjectName: 'АЗС Лесная', scopeTicketId: 'INC-2471' },
]

export const DEMO_CHAT_PARTICIPANTS = DEMO_USERS.map((user, index) => ({
  userId: user.id, name: user.name, role: index === 0 ? 'owner' : 'member',
  online: index < 4, isExternal: user.party_type === 'partner',
  companyName: user.organization_name ?? null, partyType: user.party_type,
  avatarUrl: null, mailOnly: false, email: user.email,
}))

export const DEMO_CHAT_MESSAGES = [
  { id: 'msg-1', roomId: 'room-general', userId: 'demo-operator', userName: 'demo-operator', type: 'text', content: 'INC-2471: на АЗС Лесная потерян основной Ethernet. Шлюз автоматически перешёл на резервный LTE.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 3, reactions: [{ emoji: '👀', count: 2, mine: false, users: ['engineer.ivanov', 'lead.engineer'] }], createdAt: minutesAgo(145), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-2', roomId: 'room-general', userId: 'engineer.ivanov', userName: 'engineer.ivanov', type: 'text', content: 'Проверил overlay: orders и stationdata доступны, RTT 164 мс, потери 1,8%. Критичный трафик удерживается через LTE.', fileUrl: null, fileName: null, fileSize: null, replyTo: 'msg-1', replyPreview: 'Потерян основной Ethernet', replyAuthor: 'demo-operator', isEdited: false, isDeleted: false, readCount: 3, reactions: [{ emoji: '✅', count: 2, mine: true, users: ['Вы', 'lead.engineer'] }], createdAt: minutesAgo(115), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-3', roomId: 'room-general', userId: 'lead.engineer', userName: 'lead.engineer', type: 'text', content: 'Оставляем АЗС Лесная на резервном LTE до восстановления Ethernet. Решение и поручения фиксируем в INC-2471.', fileUrl: null, fileName: null, fileSize: null, replyTo: 'msg-2', replyPreview: 'Критичный трафик удерживается через LTE', replyAuthor: 'engineer.ivanov', isEdited: false, isDeleted: false, readCount: 3, reactions: [], createdAt: minutesAgo(87), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-4', roomId: 'room-general', userId: 'engineer.ivanov', userName: 'engineer.ivanov', type: 'text', content: 'Критичные сервисы АЗС Лесная доступны через LTE. Провайдер подтвердил выезд, ожидаем восстановление Ethernet.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 2, reactions: [], createdAt: minutesAgo(3), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-news-1', roomId: 'room-news', userId: 'lead.engineer', userName: 'lead.engineer', type: 'text', content: 'Временный режим LTE для АЗС Лесная согласован до восстановления основного Ethernet-канала. INC-2471 остаётся в работе.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 2, reactions: [{ emoji: '✅', count: 2, mine: false, users: ['demo-operator', 'engineer.ivanov'] }], createdAt: minutesAgo(7), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-news-2', roomId: 'room-news', userId: 'demo-operator', userName: 'demo-operator', type: 'text', content: 'Остальные четыре АЗС работают штатно. Инцидент локализован на АЗС Лесная.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 3, reactions: [], createdAt: minutesAgo(76), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-incident-1', roomId: 'room-incident', userId: 'demo-operator', userName: 'demo-operator', type: 'text', content: 'Создал карточку INC-2471 и связал её с АЗС Лесная. @engineer.ivanov, приложи результаты диагностики.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 3, reactions: [], createdAt: minutesAgo(132), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-incident-2', roomId: 'room-incident', userId: 'engineer.ivanov', userName: 'engineer.ivanov', type: 'text', content: 'Акт первичной диагностики INC-2471 добавлен в Трек. Ethernet down, LTE up 20 Мбит/с, overlay поднят.', fileUrl: null, fileName: 'INC-2471-diagnostics.pdf', fileSize: 284160, replyTo: 'msg-incident-1', replyPreview: 'Приложи результаты диагностики', replyAuthor: 'demo-operator', isEdited: false, isDeleted: false, readCount: 3, reactions: [{ emoji: '👍', count: 2, mine: true, users: ['Вы', 'lead.engineer'] }], createdAt: minutesAgo(112), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-incident-3', roomId: 'room-incident', userId: 'lead.engineer', userName: 'lead.engineer', type: 'text', content: 'Согласование завершил. Продолжаем контроль каждые 15 минут, закрываем INC-2471 только после возврата Ethernet.', fileUrl: null, fileName: null, fileSize: null, replyTo: 'msg-incident-2', replyPreview: 'Акт первичной диагностики добавлен в Трек', replyAuthor: 'engineer.ivanov', isEdited: false, isDeleted: false, readCount: 3, reactions: [], createdAt: minutesAgo(38), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
  { id: 'msg-incident-4', roomId: 'room-incident', userId: 'engineer.ivanov', userName: 'engineer.ivanov', type: 'text', content: 'Акт диагностики добавлен в Трек, поручение провайдеру обновлено.', fileUrl: null, fileName: null, fileSize: null, replyTo: null, replyPreview: null, replyAuthor: null, isEdited: false, isDeleted: false, readCount: 2, reactions: [], createdAt: minutesAgo(12), authorParty: 'internal', forwardedFrom: null, externalSource: null, poll: null },
]

export const DEMO_ADMIN_ROOMS = DEMO_CHAT_ROOMS.map((room, index) => ({
  id: room.id, type: room.type, kind: room.kind, name: room.name,
  scopeProduct: room.scopeProduct, isArchived: false, ownerName: index === 1 ? 'lead.engineer' : 'demo-operator',
  participantCount: room.participantCount, externalCount: 0,
  messageCount: 48 - index * 13, lastMessageAt: room.lastMessageAt,
  createdAt: daysFromNow(-40 - index * 10),
}))

const task = (
  id: string, number: number, title: string, priority: string, stage: string,
  assignee: string, dueAt: string, overdue = false,
) => ({
  id, number, key: `INC-${number}`, project: 'Инциденты сети', project_id: 'project-incidents',
  project_number: number, fix_version: null, fix_version_id: null, found_version: null,
  found_version_id: null, state: stage === 'Согласование' ? 'approval' : 'in_work',
  state_name: stage, sprint: 'INC-2471', sprint_id: 'sprint-inc-2471', title,
  status: 'open', priority, stage, stage_code: stage === 'Согласование' ? 'approval' : 'work',
  route: [{ code: 'new', name: 'Новая', column: 'new' }, { code: 'work', name: 'В работе', column: 'in_work' }, { code: 'approval', name: 'Согласование', column: 'approval' }, { code: 'done', name: 'Готово', column: 'done' }],
  type: 'Инцидент', type_id: 'task-type-incident', assignee,
  assignee_id: assignee === 'engineer.ivanov' ? 'engineer.ivanov' : assignee === 'lead.engineer' ? 'lead.engineer' : 'demo-operator',
  author: 'demo-operator', object: 'АЗС Лесная', object_id: 'object-forest',
  subject_ref: 'INC-2471', due_at: dueAt, overdue, waiting_for: 'us',
  created_at: daysFromNow(-1), updated_at: minutesAgo((number - 2468) * 7), closed_at: null,
  labels: priority === 'high' ? [{ id: 'label-important', name: 'Важно', color: 'red' }] : [],
  checklist: { total: 4, done: number % 3 }, subtasks: { total: 0, open: 0 },
  time: { estimate: 120, spent: 45, estimate_text: '2 ч', spent_text: '45 мин' }, visibility: 'company',
})

export const DEMO_TASKS = [
  task('task-2471', 2471, 'Восстановить основной Ethernet-канал АЗС Лесная', 'high', 'В работе', 'engineer.ivanov', daysFromNow(0, 18)),
  task('task-2472', 2472, 'Приложить диагностику overlay и резервного LTE к INC-2471', 'high', 'В работе', 'engineer.ivanov', daysFromNow(0, 14)),
  task('task-2473', 2473, 'Подтвердить выезд провайдера на АЗС Лесная', 'medium', 'В работе', 'demo-operator', daysFromNow(0, 16)),
  task('task-2474', 2474, 'Согласовать временную работу критичных сервисов через LTE', 'medium', 'Согласование', 'lead.engineer', daysFromNow(0, 15)),
]

export const DEMO_TASK_TYPES = [
  { id: 'task-type-incident', code: 'incident', name: 'Инцидент', description: 'Восстановление сервисов сети АЗС', route: [{ code: 'new', name: 'Новая', column: 'new' }, { code: 'work', name: 'В работе', column: 'in_work' }, { code: 'approval', name: 'Согласование', column: 'approval' }, { code: 'done', name: 'Готово', column: 'done' }], default_priority: 'high', due_days: 1, project_id: 'project-incidents', is_active: true, sort_order: 10, reaction_hours: 1, escalate_to_id: 'lead.engineer' },
  { id: 'task-type-errand', code: 'errand', name: 'Поручение', description: 'Работа по объектам компании', route: [{ code: 'new', name: 'Новая', column: 'new' }, { code: 'work', name: 'В работе', column: 'in_work' }, { code: 'approval', name: 'Согласование', column: 'approval' }, { code: 'done', name: 'Готово', column: 'done' }], default_priority: 'medium', due_days: 3, project_id: null, is_active: true, sort_order: 20, reaction_hours: 4, escalate_to_id: 'lead.engineer' },
]

export const DEMO_DOC_KINDS = [
  { id: 'kind-act', code: 'act', name: 'Акт диагностики', description: 'Результаты проверки объекта и каналов связи', family: 'act', direction: 'none', number_template: '{prefix}-{seq}/{yy}', number_scope: 'kind_year', number_prefix: 'АКТ', fields: [], route: [], default_case_id: 'case-incidents', errand_type_id: 'task-type-incident', requires_registration: true, is_active: true, sort_order: 10 },
  { id: 'kind-incoming', code: 'incoming', name: 'Входящее письмо', description: 'Ответы провайдеров и внешняя корреспонденция', family: 'incoming', direction: 'in', number_template: '{prefix}-{seq}/{yy}', number_scope: 'kind_year', number_prefix: 'ВХ', fields: [], route: [], default_case_id: 'case-correspondence', errand_type_id: 'task-type-incident', requires_registration: true, is_active: true, sort_order: 20 },
  { id: 'kind-order', code: 'order', name: 'Распоряжение', description: 'Решения по режиму работы сети', family: 'ord', direction: 'none', number_template: '{prefix}-{seq}/{yy}', number_scope: 'kind_year', number_prefix: 'РСП', fields: [], route: [], default_case_id: 'case-orders', errand_type_id: 'task-type-incident', requires_registration: true, is_active: true, sort_order: 30 },
]

const doc = (
  id: string, kind: typeof DEMO_DOC_KINDS[number], title: string, status: string,
  regNumber: string | null, responsible: string, dueAt: string | null, approval: string,
) => ({
  id, kind_id: kind.id, kind_code: kind.code, kind_name: kind.name, family: kind.family,
  direction: kind.direction, title, summary: null, status,
  state: approval === 'pending' ? 'approval' : status === 'draft' ? 'new' : 'in_work',
  state_name: approval === 'pending' ? 'Согласование' : status === 'draft' ? 'Новый' : 'В работе',
  reg_number: regNumber, reg_date: regNumber ? '2026-08-20' : null, number_manual: false,
  organization_id: 'org-polus', organization_name: COMPANY_NAME,
  counterparty_id: kind.code === 'incoming' ? 'org-telecom' : null,
  counterparty_name: kind.code === 'incoming' ? 'ООО «Телеком Сервис»' : '',
  external_number: kind.code === 'incoming' ? 'TT-78142' : null, external_date: kind.code === 'incoming' ? '2026-08-25' : null, subject_ref: 'INC-2471', object_id: 'object-forest',
  author_id: 'demo-operator', responsible_id: responsible,
  signatory_id: 'lead.engineer', due_at: dueAt, confidentiality: 'company', attrs: { incident: 'INC-2471', channel: 'LTE' },
  source: 'manual', source_ref: null, current_revision: regNumber ? 2 : 1, has_files: true,
  case_id: kind.default_case_id, storage_until: null, retention_state: 'active', retention_class: '5y',
  retention_extended_until: null, inherit_kind_acl: true, acl_revision: 1,
  approval_status: approval, approval_round: approval === 'pending' ? 1 : 0,
  created_at: daysFromNow(-6), labels: [],
})

export const DEMO_DOCS = [
  doc('doc-inc-act', DEMO_DOC_KINDS[0], 'Акт первичной диагностики INC-2471', 'registered', 'АКТ-2471/26', 'engineer.ivanov', daysFromNow(0, 14), 'approved'),
  doc('doc-provider', DEMO_DOC_KINDS[1], 'Ответ провайдера по отказу Ethernet АЗС Лесная', 'registered', 'ВХ-2471/26', 'demo-operator', daysFromNow(0, 16), 'approved'),
  doc('doc-lte-order', DEMO_DOC_KINDS[2], 'Распоряжение о временной работе АЗС Лесная через LTE', 'registered', 'РСП-2471/26', 'lead.engineer', daysFromNow(0, 15), 'pending'),
  doc('doc-recovery-plan', DEMO_DOC_KINDS[0], 'План восстановления основного Ethernet-канала', 'draft', null, 'engineer.ivanov', daysFromNow(1, 12), 'none'),
]

export const DEMO_DOC_LABELS = [
  { id: 'label-important', name: 'Важно', color: 'red' },
  { id: 'label-week', name: 'На этой неделе', color: 'blue' },
]

export const DEMO_MEETING = {
  room: 'inc-2471-azs-lesnaya',
  moderator_url: 'https://meet.demo.local/inc-2471-azs-lesnaya#moderator',
  guest_url: 'https://meet.demo.local/inc-2471-azs-lesnaya',
}
