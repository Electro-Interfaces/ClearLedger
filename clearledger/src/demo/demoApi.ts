import {
  DEMO_ACCESS_CATALOG,
  DEMO_ACTIVITY,
  DEMO_ADMIN_ROOMS,
  DEMO_AUDIT,
  DEMO_AUTH_USER,
  DEMO_CHAT_MESSAGES,
  DEMO_CHAT_PARTICIPANTS,
  DEMO_CHAT_ROOMS,
  DEMO_COMPANY_APPS,
  DEMO_COMPANY_ID,
  DEMO_CONTRACTS,
  DEMO_CORE_STATUS,
  DEMO_DATA_MODEL,
  DEMO_DATA_QUALITY,
  DEMO_DEPARTMENTS,
  DEMO_DISABLED_APPS,
  DEMO_DOC_KINDS,
  DEMO_DOC_LABELS,
  DEMO_DOCS,
  DEMO_EQUIPMENT,
  DEMO_INFO_ARTICLES,
  DEMO_INFO_TREE,
  DEMO_MEETING,
  DEMO_OBJECTS,
  DEMO_ORGANIZATIONS,
  DEMO_ROLES,
  DEMO_SPACE_MAP,
  DEMO_SSO_APPS,
  DEMO_TASK_TYPES,
  DEMO_TASKS,
  DEMO_USERS,
  demoInfoRow,
} from './demoData'
import {
  DEMO_APPROVAL_DISCIPLINE,
  DEMO_BOOKS_DATASETS,
  DEMO_BOOKS_MODEL,
  DEMO_BOOKS_PROFILE,
  DEMO_BOOKS_QUALITY,
  DEMO_BOOKS_SOURCES,
  DEMO_CHANNEL_TEMPLATES,
  DEMO_CHANNELS,
  DEMO_DOC_BOARD,
  DEMO_DOC_CASES,
  DEMO_DOC_VIEWS,
  DEMO_EXCHANGE_TARGETS,
  DEMO_INBOUND_KEYS,
  DEMO_INVITATIONS,
  DEMO_MY_ACQUAINTS,
  DEMO_MY_APPROVALS,
  DEMO_MY_WORK,
  DEMO_NOTIFY_CATALOG,
  DEMO_NOTIFY_RULES,
  DEMO_PROCESS_TEMPLATES,
  DEMO_RECONCILE_RULES,
  DEMO_SOURCES,
  DEMO_SOURCE_TYPES,
  DEMO_SPACE_CONNECTORS,
  DEMO_SUBSTITUTIONS,
  DEMO_TASK_RECURRENCES,
  DEMO_TASK_TEMPLATES,
  DEMO_TASK_VIEWS,
  DEMO_WORK,
} from './demoPlatformData'

type Params = Record<string, string | number | undefined>

const clone = <T>(value: T): T => structuredClone(value)
const requestUrl = (path: string) => new URL(path, window.location.origin)
const pathname = (path: string) => requestUrl(path).pathname

export class DemoReadOnlyError extends Error {
  constructor() {
    super('Демонстрационный контур: изменения отключены')
    this.name = 'DemoReadOnlyError'
  }
}

const roomDetail = (id: string) => ({
  ...(DEMO_CHAT_ROOMS.find((room) => room.id === id) ?? DEMO_CHAT_ROOMS[0]),
  participants: DEMO_CHAT_PARTICIPANTS,
})

const taskDetails = (id: string) => {
  const task = DEMO_TASKS.find((item) => item.id === id) ?? DEMO_TASKS[0]
  return {
    ...task,
    description: `Работа по INC-2471 на АЗС Лесная: ${task.title}. Основной Ethernet недоступен, объект работает через резервный LTE.`,
    events: [
      { id: `${id}-event-1`, kind: 'created', user: 'demo-operator', from: null, to: null, note: 'Работа создана из инцидента INC-2471', pinned: false, created_at: task.created_at },
      { id: `${id}-event-2`, kind: 'stage', user: task.assignee, from: 'Новая', to: task.stage, note: 'АЗС Лесная остаётся доступна через резервный LTE', pinned: false, created_at: task.updated_at },
    ],
    checklist_items: [
      { id: `${id}-check-1`, text: 'Проверить Ethernet, LTE и overlay', done: true, position: 1, done_at: task.updated_at },
      { id: `${id}-check-2`, text: 'Зафиксировать результат в INC-2471', done: false, position: 2, done_at: null },
    ],
    watchers: [{ user_id: 'lead.engineer', name: 'lead.engineer', reason: 'Руководитель службы' }],
    attachments: [], links: [], participants: [], external: [], work_items: [], reply_address: null,
  }
}

const docDetails = (id: string) => {
  const doc = DEMO_DOCS.find((item) => item.id === id) ?? DEMO_DOCS[0]
  const kind = DEMO_DOC_KINDS.find((item) => item.id === doc.kind_id) ?? null
  const approvalPending = doc.approval_status === 'pending'
  return {
    ...doc,
    kind,
    available_actions: approvalPending ? ['approve', 'reject', 'comment'] : ['comment'],
    can_manage_access: true,
    can_manage_kind_access: true,
    capabilities: {
      read: true, edit: doc.status === 'draft', approve: approvalPending, sign: approvalPending,
      download: true, print: true, export: true, send: true, manage_acl: true, archive: false,
    },
    versions: [
      {
        id: `${id}-version-${doc.current_revision}`, revision: doc.current_revision, role: 'body',
        file_id: `${id}-file`, file_name: `${doc.reg_number ?? 'Черновик'} · редакция ${doc.current_revision}.pdf`,
        size: 386_240, sha256: 'demo-document-sha256', mime: 'application/pdf',
        title: doc.current_revision > 1 ? 'Добавлены результаты диагностики и параметры LTE' : 'Исходная редакция',
        is_current: true, uploaded_at: doc.created_at,
      },
    ],
    signatures: [],
    events: [
      { id: `${id}-event-created`, kind: 'created', actor: 'demo-operator', actor_kind: 'user', from: null, to: null, note: 'Карточка создана для INC-2471', created_at: doc.created_at },
      { id: `${id}-event-route`, kind: 'approval', actor: 'engineer.ivanov', actor_kind: 'user', from: 'Диагностика', to: doc.state_name, note: approvalPending ? 'Документ направлен руководителю службы' : 'Результат связан с инцидентом', created_at: new Date(Date.now() - 4 * 60 * 60_000).toISOString() },
    ],
    relations: [{ id: `relation-${id}-incident`, kind: 'Инцидент', target_ref: 'task:task-2471', target_doc_id: null }],
    approval: {
      status: doc.approval_status, round: doc.approval_round, snapshot: null,
      snapshot_sha256: approvalPending ? 'demo-approval-snapshot' : null,
      steps: approvalPending ? [
        { step_no: 1, name: 'Диагностика инженера', step_kind: 'approve', mode: 'serial', quorum: 'all', decided: 1, total: 1, passed: true, active: false, waiting: [], queued: [], rejected: false },
        { step_no: 2, name: 'Контроль оператора', step_kind: 'approve', mode: 'serial', quorum: 'all', decided: 1, total: 1, passed: true, active: false, waiting: [], queued: [], rejected: false },
        { step_no: 3, name: 'Решение руководителя службы', step_kind: 'sign', mode: 'serial', quorum: 'all', decided: 0, total: 1, passed: false, active: true, waiting: ['lead.engineer'], queued: [], rejected: false },
      ] : [],
      rows: approvalPending ? [
        { id: `${id}-approval-engineer`, round: 1, step_no: 1, step_name: 'Диагностика инженера', step_kind: 'approve', status: 'approved', assignee_id: 'engineer.ivanov', assignee_name: 'engineer.ivanov', decided_by_id: 'engineer.ivanov', decided_by_name: 'engineer.ivanov', can_decide: false, snapshot_sha256: 'demo-approval-snapshot', comment: 'Ethernet down, LTE up, критичные сервисы доступны', decided_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(), due_at: null },
        { id: `${id}-approval-operator`, round: 1, step_no: 2, step_name: 'Контроль оператора', step_kind: 'approve', status: 'approved', assignee_id: 'demo-operator', assignee_name: 'demo-operator', decided_by_id: 'demo-operator', decided_by_name: 'demo-operator', can_decide: false, snapshot_sha256: 'demo-approval-snapshot', comment: 'INC-2471 и выезд провайдера зафиксированы', decided_at: new Date(Date.now() - 60 * 60_000).toISOString(), due_at: null },
        { id: `${id}-approval-sign`, round: 1, step_no: 3, step_name: 'Решение руководителя службы', step_kind: 'sign', status: 'pending', assignee_id: 'lead.engineer', assignee_name: 'lead.engineer', decided_by_id: null, decided_by_name: null, can_decide: true, snapshot_sha256: 'demo-approval-snapshot', comment: null, decided_at: null, due_at: doc.due_at },
      ] : [],
    },
    acquaints: doc.id === 'doc-inc-act' ? [{ id: 'acquaint-doc-act', user_id: 'demo-operator', status: 'pending', reason: 'incident', reason_name: 'Материалы INC-2471', read_at: null, due_at: doc.due_at, reminded_at: null, reminder_attempted_at: null, reminder_error: null, snapshot_sha256: 'demo-incident-snapshot', revision: 2, note: null }] : [],
    labels: doc.id === 'doc-lte-order' ? [DEMO_DOC_LABELS[0], DEMO_DOC_LABELS[1]] : doc.labels,
  }
}

function infoContext(params: Params) {
  const appCode = String(params.app_code ?? 'admin')
  const items = DEMO_INFO_ARTICLES
    .filter((article) => article.bindings.some((binding) => binding.appCode === appCode))
    .map((article) => ({ ...demoInfoRow(article), exact: true }))
  return { appCode, sectionKey: params.section_key ? String(params.section_key) : null, items, empty: items.length === 0 }
}

export async function demoGet<T>(path: string, params: Params = {}): Promise<T> {
  const url = requestUrl(path)
  const urlPath = url.pathname
  const param = (key: string) => params[key] ?? url.searchParams.get(key) ?? undefined

  if (urlPath === '/api/auth/me') return clone(DEMO_AUTH_USER) as T
  if (urlPath === '/api/sso/apps') {
    return clone({ enabled: true, sso_enabled: true, chat_enabled: true, apps: DEMO_SSO_APPS, allowed_apps: null }) as T
  }
  if (urlPath === '/api/sso/authorize') {
    const code = String(params.app ?? '')
    const found = DEMO_SSO_APPS.find((item) => item.code === code)
    return clone({ url: found?.route ?? '#catalog', app: code, expires_in: 60 }) as T
  }
  if (urlPath === '/api/registry/company-apps') return clone({ apps: [...DEMO_COMPANY_APPS, ...DEMO_DISABLED_APPS] }) as T
  if (urlPath === '/api/registry/access-catalog') return clone({ catalog: DEMO_ACCESS_CATALOG }) as T
  if (urlPath === '/api/registry/apps') return clone({ apps: DEMO_COMPANY_APPS }) as T
  if (urlPath === '/api/registry/space-map') return clone(DEMO_SPACE_MAP) as T
  if (urlPath === '/api/registry/objects') return clone({ objects: DEMO_OBJECTS }) as T
  if (urlPath === '/api/registry/organizations') return clone({ organizations: DEMO_ORGANIZATIONS }) as T
  if (urlPath === '/api/registry/contracts') return clone({ contracts: DEMO_CONTRACTS }) as T
  if (urlPath === '/api/registry/equipment') return clone({ equipment: DEMO_EQUIPMENT }) as T
  if (urlPath === '/api/registry/data-model') return clone(DEMO_DATA_MODEL) as T
  if (urlPath === '/api/registry/data-quality') return clone(DEMO_DATA_QUALITY) as T
  if (urlPath === '/api/registry/connectors') return clone(DEMO_SPACE_CONNECTORS) as T

  if (urlPath === '/api/inbound-keys') return clone(DEMO_INBOUND_KEYS) as T
  if (urlPath === '/api/sources') return clone(DEMO_SOURCES) as T
  if (urlPath === '/api/source-types') return clone({ items: DEMO_SOURCE_TYPES }) as T
  if (urlPath === '/api/channel-templates') return clone({ items: DEMO_CHANNEL_TEMPLATES }) as T
  if (urlPath === '/api/reconcile-rules') return clone({ items: DEMO_RECONCILE_RULES }) as T
  if (urlPath === '/api/channels') return clone(DEMO_CHANNELS) as T
  const channelRunsMatch = urlPath.match(/^\/api\/channels\/([^/]+)\/runs$/)
  if (channelRunsMatch) return clone([
    { id: `${channelRunsMatch[1]}-run-1`, status: 'success', started_at: new Date(Date.now() - 47 * 60_000).toISOString(), finished_at: new Date(Date.now() - 44 * 60_000).toISOString(), records_read: 684, records_written: 681, errors: 0, trigger: 'schedule' },
    { id: `${channelRunsMatch[1]}-run-2`, status: 'success', started_at: new Date(Date.now() - 107 * 60_000).toISOString(), finished_at: new Date(Date.now() - 104 * 60_000).toISOString(), records_read: 412, records_written: 412, errors: 0, trigger: 'schedule' },
  ]) as T
  const channelLogsMatch = urlPath.match(/^\/api\/channels\/([^/]+)\/logs$/)
  if (channelLogsMatch) return clone([
    { id: `${channelLogsMatch[1]}-log-1`, level: 'info', message: 'Загрузка завершена: 681 запись принята', created_at: new Date(Date.now() - 44 * 60_000).toISOString() },
    { id: `${channelLogsMatch[1]}-log-2`, level: 'info', message: 'Контроль качества пройден', created_at: new Date(Date.now() - 45 * 60_000).toISOString() },
  ]) as T
  const channelStatusMatch = urlPath.match(/^\/api\/channels\/([^/]+)\/run-status$/)
  if (channelStatusMatch) return clone({ channel_id: channelStatusMatch[1], running: false, status: 'success', progress: 100, message: 'Последний обмен завершён' }) as T
  const channelMatch = urlPath.match(/^\/api\/channels\/([^/]+)$/)
  if (channelMatch) return clone(DEMO_CHANNELS.find((item) => item.id === channelMatch[1]) ?? DEMO_CHANNELS[0]) as T

  if (urlPath === '/api/books/profile') return clone(DEMO_BOOKS_PROFILE) as T
  if (urlPath === '/api/books/sources') return clone(DEMO_BOOKS_SOURCES) as T
  if (urlPath === '/api/books/quality') return clone(DEMO_BOOKS_QUALITY) as T
  if (urlPath === '/api/books/model') return clone(DEMO_BOOKS_MODEL) as T
  if (urlPath === '/api/books/dataset') {
    const key = String(param('key') ?? 'entries') as keyof typeof DEMO_BOOKS_DATASETS
    return clone(DEMO_BOOKS_DATASETS[key] ?? DEMO_BOOKS_DATASETS.entries) as T
  }

  if (urlPath === '/api/core/status') return clone(DEMO_CORE_STATUS) as T
  if (urlPath === '/api/core/audit') return clone(DEMO_AUDIT.map((event) => ({
    id: event.id, companyId: DEMO_COMPANY_ID, companySlug: 'polus-retail', companyName: 'ООО «Полюс Ритейл»',
    userId: event.user_id, userName: event.user_name, action: event.action,
    details: event.details, timestamp: event.timestamp,
  }))) as T
  if (urlPath === '/api/audit') return clone(DEMO_AUDIT) as T
  if (urlPath === '/api/audit/activity') return clone(DEMO_ACTIVITY) as T
  if (urlPath === '/api/tickets/summary') {
    return clone({
      open: 4, sla_breached: 0, created_7d: 4, closed_7d: 3, created_30d: 11, closed_30d: 10,
      by: { responsibility: [{ key: 'Служба эксплуатации', count: 3 }, { key: 'Провайдер', count: 1 }], status: [{ key: 'В работе', count: 4 }], category: [{ key: 'Связь', count: 4 }], assignee: [{ key: 'engineer.ivanov', count: 2 }, { key: 'demo-operator', count: 1 }], department: [{ key: 'Служба эксплуатации сети', count: 4 }] },
    }) as T
  }

  if (urlPath === '/api/users') return clone(DEMO_USERS) as T
  if (urlPath === '/api/invitations') return clone(DEMO_INVITATIONS) as T
  if (urlPath === '/api/companies') {
    return clone([{ id: DEMO_COMPANY_ID, name: 'ООО «Полюс Ритейл»', slug: 'polus-retail', short_name: 'ПОЛЮС РИТЕЙЛ', profile_id: 'office', color: '#2563eb', inn: '7805123456' }]) as T
  }
  if (urlPath === '/api/roles') return clone(DEMO_ROLES) as T
  if (urlPath === '/api/departments') return clone({ departments: DEMO_DEPARTMENTS }) as T
  if (urlPath === '/api/references/organizations') return clone(DEMO_ORGANIZATIONS) as T
  if (urlPath === '/api/references/counterparties') return clone(DEMO_ORGANIZATIONS.slice(1)) as T
  if (urlPath === '/api/notifications/catalog') return clone(DEMO_NOTIFY_CATALOG) as T
  if (urlPath === '/api/notifications') {
    if (param('company_id')) return clone(DEMO_NOTIFY_RULES) as T
    return clone([
      { id: 'notification-approval', type: 'doc.approval', title: 'INC-2471 ждёт решения', message: 'РСП-2471/26 · режим LTE до восстановления Ethernet', read: false, created_at: new Date(Date.now() - 7 * 60_000).toISOString(), href: '/docs?view=all&doc=doc-lte-order' },
      { id: 'notification-quality', type: 'quality.warning', title: 'АЗС Лесная на резервном канале', message: 'Ethernet недоступен, LTE и критичные сервисы работают', read: true, created_at: new Date(Date.now() - 12 * 60_000).toISOString(), href: '/data?mode=data_quality' },
    ]) as T
  }
  if (urlPath === '/api/notifications/unread-count') return clone({ count: 1 }) as T

  if (urlPath === '/api/info/tree') return clone(DEMO_INFO_TREE) as T
  if (urlPath === '/api/info/context') return clone(infoContext(params)) as T
  if (urlPath === '/api/info/search') {
    const query = String(params.q ?? '').trim().toLocaleLowerCase('ru-RU')
    const items = DEMO_INFO_ARTICLES.filter((article) =>
      `${article.title} ${article.summary ?? ''} ${article.bodyMd}`.toLocaleLowerCase('ru-RU').includes(query))
      .map((article) => {
        const row = demoInfoRow(article)
        return { ...row, snippet: row.summary ?? row.title }
      })
    return clone({ query, items }) as T
  }
  if (urlPath === '/api/info/stats') {
    return clone({ byKind: [{ kind: 'guide', label: 'Инструкции', platform: 5, company: 0 }, { kind: 'lnd', label: 'Документы компании', platform: 0, company: 1 }, { kind: 'faq', label: 'Вопросы', platform: 3, company: 0 }], apps: 7, profile: 'fuel' }) as T
  }
  const articleMatch = urlPath.match(/^\/api\/info\/articles\/([^/]+)$/)
  if (articleMatch) return clone(DEMO_INFO_ARTICLES.find((article) => article.id === articleMatch[1]) ?? DEMO_INFO_ARTICLES[0]) as T

  if (urlPath === '/api/chat/rooms') return clone(DEMO_CHAT_ROOMS) as T
  if (urlPath === '/api/chat/presence') return clone(DEMO_CHAT_PARTICIPANTS.map((person) => ({ userId: person.userId, name: person.name, online: person.online }))) as T
  if (urlPath === '/api/chat/folders') return clone([{ id: 'folder-main', name: 'INC-2471', roomIds: ['room-general', 'room-incident'], sortOrder: 10 }]) as T
  if (urlPath === '/api/chat/admin/rooms') return clone(DEMO_ADMIN_ROOMS) as T
  if (urlPath === '/api/chat/admin/people') return clone(DEMO_CHAT_PARTICIPANTS.map((person) => ({ userId: person.userId, name: person.name, email: person.email, isExternal: person.isExternal ?? false, companyName: person.companyName ?? null, partyType: person.partyType }))) as T
  if (urlPath === '/api/chat/users/search') return clone(DEMO_CHAT_PARTICIPANTS.map((person) => ({ userId: person.userId, name: person.name, email: person.email ?? '', online: person.online, partyType: person.partyType, avatarUrl: null }))) as T
  const messagesMatch = urlPath.match(/^\/api\/chat\/rooms\/([^/]+)\/messages$/)
  if (messagesMatch) {
    const messages = DEMO_CHAT_MESSAGES.filter((message) => message.roomId === messagesMatch[1])
    return clone(messages.length > 0 ? messages : DEMO_CHAT_MESSAGES.map((message) => ({ ...message, roomId: messagesMatch[1] }))) as T
  }
  const roomMatch = urlPath.match(/^\/api\/chat\/rooms\/([^/]+)$/)
  if (roomMatch) return clone(roomDetail(roomMatch[1])) as T

  if (urlPath === '/api/tasks') return clone({ tasks: DEMO_TASKS, total: DEMO_TASKS.length, limit: 50, offset: 0 }) as T
  if (urlPath === '/api/tasks/summary') return clone({
    days: Number(params.days ?? 30), totals: { open: 4, overdue: 0, mine: 4, unassigned: 0, created: 4, done: 7, avg_days: 1.2 },
    by_assignee: [{ id: 'engineer.ivanov', name: 'engineer.ivanov', open: 2, overdue: 0, done: 4 }, { id: 'demo-operator', name: 'demo-operator', open: 1, overdue: 0, done: 2 }, { id: 'lead.engineer', name: 'lead.engineer', open: 1, overdue: 0, done: 1 }],
    by_type: [{ id: 'task-type-incident', name: 'Инцидент', open: 4, overdue: 0, done: 7 }],
    by_object: [{ id: 'object-forest', name: 'АЗС Лесная', open: 4, overdue: 0, done: 7 }], activity: [],
  }) as T
  if (urlPath === '/api/tasks/people') return clone({ people: DEMO_USERS.map((user) => ({ id: user.id, name: user.name, partyType: user.party_type, avatarUrl: null })) }) as T
  if (urlPath === '/api/tasks/types') return clone({ types: DEMO_TASK_TYPES, default_route: DEMO_TASK_TYPES[0].route, columns: [{ code: 'new', name: 'Новые' }, { code: 'in_work', name: 'В работе' }, { code: 'approval', name: 'Согласование' }, { code: 'external', name: 'Внешняя сторона' }, { code: 'done', name: 'Готово' }] }) as T
  if (urlPath === '/api/tasks/projects') return clone({ projects: [{ id: 'project-incidents', code: 'INC', name: 'Инциденты сети', description: 'Восстановление связи и сервисов объектов Полюс Ритейл', lead_id: 'lead.engineer', counter: 2474, is_archived: false, sort_order: 10, tasks: 11, open: 4 }] }) as T
  if (urlPath === '/api/tasks/versions') return clone({ versions: [] }) as T
  if (urlPath === '/api/tasks/sprints') return clone({ sprints: [{ id: 'sprint-inc-2471', project_id: 'project-incidents', name: 'INC-2471 · АЗС Лесная', state: 'active', starts_on: daysFrom(-1), ends_on: daysFrom(1), carried_over: 0, taken: 4, done: 0, left: 4 }] }) as T
  if (urlPath === '/api/tasks/views') return clone({ views: DEMO_TASK_VIEWS }) as T
  if (urlPath === '/api/tasks/templates') return clone({ templates: DEMO_TASK_TEMPLATES }) as T
  if (urlPath === '/api/tasks/recurrences') return clone({ recurrences: DEMO_TASK_RECURRENCES }) as T
  if (urlPath === '/api/tasks/labels') return clone({ labels: DEMO_DOC_LABELS }) as T
  const taskMatch = urlPath.match(/^\/api\/tasks\/([^/]+)$/)
  if (taskMatch) return clone(taskDetails(taskMatch[1])) as T

  if (urlPath === '/api/work/summary') return clone({
    columns: [
      { code: 'new', name: 'Новые', docs: 1, tasks: 0, total: 1 },
      { code: 'in_work', name: 'В работе', docs: 2, tasks: 3, total: 5 },
      { code: 'approval', name: 'Согласование', docs: 1, tasks: 1, total: 2 },
      { code: 'external', name: 'Внешняя сторона', docs: 0, tasks: 0, total: 0 },
      { code: 'done', name: 'Готово', docs: 0, tasks: 0, total: 0 },
    ],
  }) as T
  if (urlPath === '/api/work/mine') return clone(DEMO_MY_WORK) as T
  if (urlPath === '/api/work') return clone({
    work: DEMO_WORK, total: DEMO_WORK.length, limit: 50, offset: 0,
    columns: [{ code: 'new', name: 'Новые' }, { code: 'in_work', name: 'В работе' }, { code: 'approval', name: 'Согласование' }, { code: 'external', name: 'Внешняя сторона' }, { code: 'done', name: 'Готово' }],
  }) as T

  if (urlPath === '/api/docs/kinds/subjects') return clone({ people: DEMO_USERS.map((user) => ({ id: user.id, name: user.name })), roles: DEMO_ROLES.map((role) => ({ id: role.id, name: role.name })), departments: DEMO_DEPARTMENTS.map((department) => ({ id: department.id, name: department.name })) }) as T
  if (urlPath === '/api/docs/acquaint/subjects') return clone({ people: DEMO_USERS.map((user) => ({ id: user.id, name: user.name, position: user.position })), departments: DEMO_DEPARTMENTS }) as T
  if (urlPath === '/api/docs/access/subjects') return clone({ users: DEMO_USERS.map((user) => ({ id: user.id, name: user.name })), roles: DEMO_ROLES, departments: DEMO_DEPARTMENTS }) as T
  if (urlPath === '/api/docs/access') return clone({ grants: [], inherit_kind_acl: true, acl_revision: 1 }) as T
  if (urlPath === '/api/docs/process-templates') return clone({ templates: DEMO_PROCESS_TEMPLATES }) as T
  if (urlPath === '/api/docs/kinds') return clone({ kinds: DEMO_DOC_KINDS }) as T
  if (urlPath === '/api/docs') return clone({ docs: DEMO_DOCS, count: DEMO_DOCS.length }) as T
  if (urlPath === '/api/docs/labels') return clone({ labels: DEMO_DOC_LABELS }) as T
  if (urlPath === '/api/docs/views') return clone({ views: DEMO_DOC_VIEWS }) as T
  if (urlPath === '/api/docs/approvals/mine') return clone({ approvals: DEMO_MY_APPROVALS }) as T
  if (urlPath === '/api/docs/acquaints/mine') return clone({ acquaints: DEMO_MY_ACQUAINTS }) as T
  if (urlPath === '/api/docs/cases') return clone({ cases: DEMO_DOC_CASES }) as T
  if (urlPath === '/api/docs/substitutions') return clone({ substitutions: DEMO_SUBSTITUTIONS }) as T
  if (urlPath === '/api/docs/exchange/targets') return clone({ targets: DEMO_EXCHANGE_TARGETS }) as T
  if (urlPath === '/api/docs/board') return clone(DEMO_DOC_BOARD) as T
  if (urlPath === '/api/docs/reports/discipline') return clone(DEMO_APPROVAL_DISCIPLINE) as T
  const docMatch = urlPath.match(/^\/api\/docs\/([^/]+)$/)
  if (docMatch) return clone(docDetails(docMatch[1])) as T

  if (urlPath === '/api/meetings/config') return clone({ enabled: true, domain: 'meet.demo.local' }) as T

  throw new Error(`Демо-данные для ${urlPath} пока не заданы`)
}

const daysFrom = (days: number) => {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

export async function demoPost<T>(path: string): Promise<T> {
  const urlPath = pathname(path)
  if (urlPath === '/api/meetings') return clone(DEMO_MEETING) as T
  if (/^\/api\/chat\/rooms\/[^/]+\/read$/.test(urlPath)) return { ok: true } as T
  throw new DemoReadOnlyError()
}

export async function demoWrite<T>(): Promise<T> {
  throw new DemoReadOnlyError()
}
