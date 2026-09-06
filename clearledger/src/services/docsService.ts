/**
 * Приложение «Трек» — документооборот и работа компании.
 *
 * Документ здесь самостоятельный объект: вид, реквизиты, регистрационный номер,
 * редакции файла и след. Поручение по документу — обычная задача, поэтому здесь
 * только заведение связи, а сама работа живёт в «Задачах».
 */
import { del, get, post, put, upload } from './apiClient'

export interface DocKind {
  id: string
  code: string
  name: string
  description: string | null
  family: string          // ord | incoming | outgoing | internal | contract | other
  direction: string       // in | out | none
  number_template: string
  number_scope: string    // kind | kind_year | kind_org | kind_org_year
  number_prefix: string
  fields: DocKindField[]
  route: Array<Record<string, unknown>>
  default_case_id: string | null
  errand_type_id: string | null
  requires_registration: boolean
  is_active: boolean
  sort_order: number
  /** Какой пункт чек-листа проекта закрывает согласованный документ этого вида. */
  gate_key?: string | null
}

export interface DocKindField {
  code: string
  label: string
  type: 'text' | 'textarea' | 'number' | 'date' | 'boolean' | 'select'
  options?: string[]
  required: boolean
}

export interface DocKindSubjects {
  people: Array<{ id: string; name: string }>
  roles: Array<{ id: string; name: string }>
  departments: Array<{ id: string; name: string }>
  positions: string[]
  task_types: Array<{ id: string; name: string }>
}

export interface ProcessTemplate {
  id: string
  kind: 'document' | 'task'
  name: string
  title: string
  description: string | null
  docKindId?: string
  docKindName?: string
  taskTypeId?: string | null
  taskTypeName?: string
  steps: number
  requiresPreparation: boolean
  preparationReason: string | null
  defaultResponsibleId: string | null
  dueDays: number | null
  capabilities?: Array<'assign' | 'transfer' | 'comments' | 'files'>
}

interface ProcessLaunchBase {
  title: string
  templateId: string
  templateName: string
  started: boolean
  steps: number
  reason: string | null
}

export type ProcessLaunchResult = ProcessLaunchBase & ({
  kind: 'document'
  docId: string
  state: 'preparation' | 'approval'
  round?: number
  approvals?: number
} | {
  kind: 'task'
  taskId: string
  taskNumber: number
  state: 'task'
  stage: string
})

export interface DocSavedView {
  id: string
  name: string
  query: Record<string, string>
  shared: boolean
  position?: number
  can_delete?: boolean
}

export interface DocLabel {
  id: string
  name: string
  color: string
}

export interface DocCard {
  edit_version?: string | null
  id: string
  kind_id: string
  kind_code: string
  kind_name: string
  family: string
  direction: string
  title: string
  summary: string | null
  status: string          // draft | registered | in_force | executed | archived | cancelled
  /** Колонка общей оси состояния (этап 13а) — та же, что у поручений. */
  state?: 'new' | 'in_work' | 'approval' | 'external' | 'done'
  state_name?: string
  reg_number: string | null
  reg_date: string | null
  number_manual: boolean
  organization_id: string | null
  organization_name: string
  counterparty_id: string | null
  counterparty_name: string
  external_number: string | null
  external_date: string | null
  subject_ref: string | null
  object_id: string | null
  author_id: string | null
  responsible_id: string | null
  signatory_id: string | null
  due_at: string | null
  confidentiality: 'company' | 'private' | 'strict'
  attrs: Record<string, unknown>
  source: string
  source_ref: string | null
  current_revision: number
  has_files: boolean
  case_id: string | null
  storage_until: string | null
  retention_state: string
  retention_class: string
  retention_extended_until: string | null
  inherit_kind_acl: boolean
  acl_revision: number
  approval_status: string
  approval_round: number
  created_at: string | null
  labels?: DocLabel[]
}

export interface DocVersion {
  id: string
  revision: number
  role: string            // body | appendix | signed_scan | attachment
  file_id: string
  file_name: string
  mime: string | null
  size: number
  sha256: string
  title: string | null
  is_current: boolean
  uploaded_at: string | null
}

export interface DocEvent {
  id: string
  kind: string
  actor: string | null
  /** Кто действовал: человек, чужая система, наш агент или планировщик.
   *  Подпись «Аудитор Поддержки» без этого читается как имя сотрудника. */
  actor_kind?: 'user' | 'partner' | 'agent' | 'system'
  from: string | null
  to: string | null
  note: string | null
  created_at: string | null
}

export interface DocRelation {
  id: string
  kind: string
  target_ref: string
  target_doc_id: string | null
}

/** Виза: строка листа согласования. */
export interface DocApprovalRow {
  id: string
  round: number
  step_no: number
  step_name: string
  step_kind: 'approve' | 'sign'
  status: string          // waiting | pending | approved | rejected | skipped
  assignee_id: string | null
  assignee_name: string | null
  decided_by_id: string | null
  decided_by_name: string | null
  can_decide: boolean
  snapshot_sha256: string | null
  comment: string | null
  decided_at: string | null
  due_at: string | null
}

/** Состояние шага: сколько решили и кого ждут. */
export interface DocApprovalStep {
  step_no: number
  name: string
  step_kind: 'approve' | 'sign'
  mode: string
  quorum: string
  decided: number
  total: number
  passed: boolean
  active: boolean
  waiting: string[]
  queued: string[]
  rejected: boolean
}

export interface DocApprovalSnapshot {
  card: {
    id: string
    title: string
    reg_number: string | null
    current_revision: number
    attrs: Record<string, unknown>
  }
  files: Array<{
    id: string
    file_id: string
    role: string
    revision: number
    file_name: string
    size_bytes: number
    sha256: string
  }>
}

export interface DocApprovalState {
  status: string          // none | pending | approved | rejected
  round: number
  snapshot: DocApprovalSnapshot | null
  snapshot_sha256: string | null
  steps: DocApprovalStep[]
  rows: DocApprovalRow[]
}

/** Что ждёт моей визы — экран «На мне». */
export interface MyApproval {
  id: string
  doc_id: string
  step_name: string
  step_kind: 'approve' | 'sign'
  mode: string
  due_at: string | null
  doc_title: string
  doc_number: string | null
  acting_for?: string | null
}

export interface DocCase {
  id: string
  year: number
  index: string
  title: string
  storage_term: string
  storage_years: number | null
  epk: boolean
  status: string
  organization_id: string | null
  department_id: string | null
  closed_at: string | null
  note: string | null
}

/** Строка листа ознакомления: кому направлен документ и расписался ли он. */
export interface DocAcquaint {
  id: string
  user_id: string
  status: string          // pending | done | superseded
  reason: string
  reason_name: string | null
  read_at: string | null
  due_at: string | null
  reminded_at: string | null
  reminder_attempted_at: string | null
  reminder_error: string | null
  snapshot_sha256: string | null
  revision: number | null
  note: string | null
}

export interface DocSignatureEvidence {
  id: string
  approval_id: string | null
  method: 'internal_approval' | 'internal_direct' | 'qualified_external'
  provider: string | null
  external_id: string | null
  signer_id: string | null
  signer_name: string
  represented_signer_id: string | null
  represented_signer_name: string | null
  snapshot_sha256: string
  revision: number | null
  files_count: number
  verification_status: 'pending' | 'verified' | 'failed' | 'revoked'
  verified_at: string | null
  verification_error: string | null
  signed_at: string
}

/** Замещение: кто работает за человека, пока его нет. */
export interface Substitution {
  id: string
  user: string
  user_id: string
  deputy: string
  deputy_id: string
  starts_on: string
  ends_on: string
  basis: string | null
  is_active: boolean
  now: boolean
}

export interface DocDetails extends DocCard {
  kind: DocKind | null
  available_actions: string[]
  can_manage_access: boolean
  can_manage_kind_access: boolean
  capabilities: Record<DocPermission, boolean>
  versions: DocVersion[]
  signatures: DocSignatureEvidence[]
  events: DocEvent[]
  relations: DocRelation[]
  approval: DocApprovalState
  acquaints: DocAcquaint[]
  labels: DocLabel[]
}

export type DocPermission = 'read' | 'edit' | 'approve' | 'sign' | 'download'
  | 'print' | 'export' | 'send' | 'manage_acl' | 'archive'

export interface DocAccessGrant {
  id: string
  scope_type: 'doc' | 'kind'
  scope_id: string
  subject_type: 'user' | 'role' | 'department'
  subject_id: string
  subject_name: string
  permissions: DocPermission[]
  denied_permissions: DocPermission[]
  inherited: boolean
}

export interface DocAccessRules {
  grants: DocAccessGrant[]
  inherit_kind_acl: boolean | null
  acl_revision: number | null
}

export interface DocFilters {
  family?: string
  direction?: string
  status?: string
  kind_id?: string
  label_id?: string
  counterparty_id?: string
  responsible_id?: string
  object_ids?: string
  date_from?: string
  date_to?: string
  q?: string
  mine?: boolean
  /** За чем пришли из обзора: unnumbered | returned | pending | overdue. */
  attention?: string
  limit?: number
  offset?: number
}

/** Что показывает отбор из обзора. Слово в родительном падеже: подставляется
 *  в «Отбор: просроченные» и в подпись пустого результата. */
export const DOC_ATTENTION: Record<string, string> = {
  unnumbered: 'без номера',
  returned: 'возвращённые с визы',
  pending: 'на визах',
  overdue: 'просроченные',
}

export interface CounterScope {
  scope_key: string
  organization: string | null
  year: number | null
  issued: number
  next: number
  updated_at: string | null
}

export interface CounterRow {
  kind_id: string
  code: string
  name: string
  prefix: string
  template: string
  scope: string
  scopes: CounterScope[]
  issued: number
}

export async function listCounters(companyId: string) {
  return get<{ counters: CounterRow[] }>('/api/docs/counters', { company_id: companyId })
}

/** Состояния документа: имя для человека и тон плашки. */
export const DOC_STATUS: Record<string, { label: string; tone: string }> = {
  draft: { label: 'Черновик', tone: 'muted' },
  registered: { label: 'Зарегистрирован', tone: 'sky' },
  in_force: { label: 'Действует', tone: 'green' },
  executed: { label: 'Исполнен', tone: 'green' },
  archived: { label: 'В архиве', tone: 'muted' },
  cancelled: { label: 'Отменён', tone: 'red' },
}

export const DOC_FAMILY: Record<string, string> = {
  incoming: 'Входящие',
  outgoing: 'Исходящие',
  ord: 'Приказы и распоряжения',
  internal: 'Внутренние',
  contract: 'Договорные',
  other: 'Прочие',
}

export async function listKinds(companyId: string): Promise<DocKind[]> {
  const r = await get<{ kinds: DocKind[] }>('/api/docs/kinds', { company_id: companyId })
  return r.kinds ?? []
}

export async function saveKind(
  companyId: string, body: Partial<DocKind>, id?: string,
): Promise<DocKind> {
  const payload = { ...body, company_id: companyId }
  return id ? put<DocKind>(`/api/docs/kinds/${id}`, payload) : post<DocKind>('/api/docs/kinds', payload)
}

/** Завести обычный набор видов. Идемпотентно: повторное нажатие ничего не портит. */
export async function starterKinds(companyId: string): Promise<{ added: number }> {
  return post<{ added: number }>(`/api/docs/kinds/starter?company_id=${companyId}`, {})
}

export async function listDocs(
  companyId: string, filters: DocFilters = {},
): Promise<{ docs: DocCard[]; count: number }> {
  const params: Record<string, string> = { company_id: companyId }
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') params[k] = String(v)
  })
  return get<{ docs: DocCard[]; count: number }>('/api/docs', params)
}

export async function getDoc(companyId: string, id: string): Promise<DocDetails> {
  return get<DocDetails>(`/api/docs/${id}`, { company_id: companyId })
}

export async function createDoc(
  companyId: string, body: Record<string, unknown>,
): Promise<DocCard> {
  return post<DocCard>('/api/docs', { ...body, company_id: companyId })
}

export async function listProcessTemplates(companyId: string) {
  return get<{ templates: ProcessTemplate[] }>('/api/docs/process-templates', {
    company_id: companyId,
  })
}

export async function startProcessTemplate(
  id: string, companyId: string,
  options?: {
    responsibleId?: string; title?: string; objectId?: string
    subjectRef?: string
    /** Связь «много к одному»: по проекту документов десяток, а предмет
     *  карточки уникален и годится лишь для отношения один к одному. */
    relateTo?: string
  },
) {
  return post<ProcessLaunchResult>(`/api/docs/process-templates/${id}/start`, {
    company_id: companyId,
    responsible_id: options?.responsibleId || undefined,
    title: options?.title?.trim() || undefined,
    // Предмет: из карточки проекта это сам проект (`site:<id>`). Без него
    // заведённое не найти по проекту, пока у площадки нет объекта сети.
    subject_ref: options?.subjectRef || undefined,
    relate_to: options?.relateTo || undefined,
    // Объект передаётся, когда работу заводят из карточки проекта: без него
    // заведённое не найти по объекту, и лента «что идёт по этой площадке»
    // осталась бы пустой при живых документах и поручениях.
    object_id: options?.objectId || undefined,
  })
}

/** Как называется предмет работы и куда по нему пройти. */
export interface ResolvedRef {
  kind: string
  /** `null` — цель исчезла: связь есть, но она сломана. */
  name: string | null
  url: string | null
}

/**
 * Расшифровать ссылки на предметы пачкой.
 *
 * Ссылка хранится машинным видом (`site:<uuid>`): показать её человеку так же
 * значит не показать ничего — он не отличит проект от договора. Пачкой, потому
 * что в списке работ ссылок столько же, сколько строк.
 */
export async function resolveRefs(companyId: string, refs: string[]): Promise<Record<string, ResolvedRef>> {
  const list = refs.filter(Boolean)
  if (!list.length) return {}
  const res = await get<{ refs: Record<string, ResolvedRef> }>('/api/docs/refs/resolve', {
    company_id: companyId, refs: list.join(','),
  })
  return res.refs || {}
}

export async function listKindSubjects(companyId: string): Promise<DocKindSubjects> {
  return get<DocKindSubjects>('/api/docs/kinds/subjects', { company_id: companyId })
}

export async function listAccessGrants(
  companyId: string, docId: string,
): Promise<DocAccessRules> {
  const result = await get<DocAccessRules>('/api/docs/access', {
    company_id: companyId, doc_id: docId,
  })
  return {
    grants: result.grants ?? [],
    inherit_kind_acl: result.inherit_kind_acl,
    acl_revision: result.acl_revision,
  }
}

export async function listAccessSubjects(
  companyId: string, docId: string,
): Promise<{
  people: Array<{ id: string; name: string }>
  roles: Array<{ id: string; name: string }>
  departments: Array<{ id: string; name: string }>
}> {
  return get('/api/docs/access/subjects', { company_id: companyId, doc_id: docId })
}

export async function saveAccessGrant(companyId: string, body: {
  scope_type: 'doc' | 'kind'
  scope_id: string
  subject_type: 'user' | 'role' | 'department'
  subject_id: string
  permissions: DocPermission[]
  denied_permissions: DocPermission[]
  expected_acl_revision?: number
}): Promise<{
  id: string
  permissions: DocPermission[]
  denied_permissions: DocPermission[]
  acl_revision?: number
}> {
  return post('/api/docs/access', { ...body, company_id: companyId })
}

export async function updateAccessPolicy(companyId: string, docId: string, body: {
  inherit_kind_acl: boolean
  confidentiality?: 'company' | 'private' | 'strict'
  expected_acl_revision: number
}): Promise<{
  inherit_kind_acl: boolean
  confidentiality: 'company' | 'private' | 'strict'
  acl_revision: number
}> {
  return put(`/api/docs/${docId}/access-policy`, { ...body, company_id: companyId })
}

export async function deleteAccessGrant(
  companyId: string, id: string, expectedAclRevision?: number,
): Promise<{ deleted: boolean }> {
  const revision = expectedAclRevision === undefined
    ? '' : `&expected_acl_revision=${expectedAclRevision}`
  return del(`/api/docs/access/${id}?company_id=${companyId}${revision}`)
}

export interface DocBreakGlassAccess {
  id: string
  expires_at: string
  permissions: DocPermission[]
  reason: string
  notification_status: string
  notification_error: string | null
}

export interface DocSecurityState {
  id: string
  kind_code: string
  status: string
  reg_number: string | null
  confidentiality: 'company' | 'private' | 'strict'
  can_manage_access: boolean
  can_break_glass: boolean
  active_break_glass: DocBreakGlassAccess | null
}

export async function getDocSecurity(companyId: string, docId: string): Promise<DocSecurityState> {
  return get(`/api/docs/${docId}/security`, { company_id: companyId })
}

export async function activateBreakGlass(companyId: string, docId: string, body: {
  password: string
  reason: string
  ttl_minutes: number
}): Promise<Omit<DocBreakGlassAccess, 'reason'>> {
  return post(`/api/docs/${docId}/break-glass`, { ...body, company_id: companyId })
}

export async function revokeBreakGlass(companyId: string, accessId: string): Promise<{
  revoked: boolean
}> {
  return post(`/api/docs/break-glass/${accessId}/revoke?company_id=${companyId}`, {})
}

export type DocRetentionState = 'working' | 'archive_pending' | 'archived' | 'legacy_review'
  | 'under_expertise' | 'permanent' | 'destruction_ready' | 'destruction_authorized'
  | 'primary_purged' | 'destroyed'

export interface DocArchiveHold {
  id: string
  authority: string
  reference: string | null
  reason: string
  placed_by: string | null
  placed_at: string
  released_by: string | null
  released_at: string | null
  release_reason: string | null
}

export interface DocArchiveDecision {
  id: string
  decision: 'destroy' | 'extend' | 'permanent'
  reason: string
  epk_reference: string | null
  new_storage_until: string | null
  snapshot_sha256: string
  created_by: string | null
  created_at: string
}

export interface DocArchiveEvent {
  id: string
  kind: string
  doc_id: string | null
  act_id: string | null
  actor_id: string | null
  actor_name: string
  payload: Record<string, unknown>
  prev_hash: string | null
  event_hash: string
  created_at: string
}

export interface DocArchiveUnresolvedExport {
  id: string
  status: 'pending' | 'unknown'
  package_name: string
  channel: string | null
  error: string | null
  created_at: string
}

export interface DocDestructionAct {
  id: string
  organization_id: string | null
  act_number: string
  act_date: string
  basis: string
  committee: string[]
  status: string
  created_by: string | null
  created_at: string
  approved_by: string | null
  approved_at: string | null
  executed_by: string | null
  executed_at: string | null
  backup_attested_by: string | null
  backup_attested_at: string | null
  backup_evidence: {
    evidence: string
    external_copies_evidence?: string | null
    known_external_copies?: boolean
  } | null
  sealed_sha256: string | null
  error: string | null
  cancellation_reason: string | null
  items: number | null
  item_status?: string | null
  item_error?: string | null
  has_known_external_copies?: boolean
}

export interface DocArchiveState {
  retention_state: DocRetentionState
  retention_class: 'temporary' | 'epk' | 'permanent' | 'unclassified'
  retention_snapshot: Record<string, unknown> | null
  storage_until: string | null
  retention_extended_until: string | null
  archive_accepted_at: string | null
  primary_purged_at: string | null
  destroyed_at: string | null
  can_manage: boolean
  blocker: string | null
  holds: DocArchiveHold[]
  decisions: DocArchiveDecision[]
  unresolved_exports: DocArchiveUnresolvedExport[]
  acts: DocDestructionAct[]
  events: DocArchiveEvent[]
}

export interface DocArchiveQueueItem {
  id: string
  title: string
  reg_number: string | null
  organization_id: string | null
  storage_until: string | null
  retention_extended_until: string | null
  retention_state: DocRetentionState
  retention_class: 'temporary' | 'epk' | 'permanent' | 'unclassified'
  hold: boolean
  blocker: string | null
}

export interface DocArchiveQueuePage {
  documents: DocArchiveQueueItem[]
  next_cursor: string | null
}

export async function getArchiveQueue(
  companyId: string,
  cursor?: string,
  limit = 100,
): Promise<DocArchiveQueuePage> {
  return get('/api/docs/archive/queue', {
    company_id: companyId, cursor, limit,
  })
}

export async function getDocArchive(companyId: string, docId: string): Promise<DocArchiveState> {
  return get(`/api/docs/${docId}/archive`, { company_id: companyId })
}

export async function placeArchiveHold(companyId: string, docId: string, body: {
  authority: string
  reference?: string | null
  reason: string
}): Promise<DocArchiveHold> {
  return post(`/api/docs/${docId}/archive/holds`, { ...body, company_id: companyId })
}

export async function releaseArchiveHold(companyId: string, holdId: string, reason: string): Promise<{
  id: string
  released_at: string | null
}> {
  return post(`/api/docs/archive/holds/${holdId}/release`, { company_id: companyId, reason })
}

export async function resolveArchiveExport(
  companyId: string,
  exportId: string,
  resolution: 'placed' | 'failed',
  evidence: string,
  noLocalCopy = false,
): Promise<{ id: string; status: string }> {
  return post(`/api/docs/archive/exports/${exportId}/resolve`, {
    company_id: companyId, resolution, evidence, no_local_copy: noLocalCopy,
  })
}

export async function makeArchiveDecision(companyId: string, docId: string, body: {
  decision: 'destroy' | 'extend' | 'permanent'
  reason: string
  epk_reference?: string | null
  new_storage_until?: string | null
}): Promise<DocArchiveDecision> {
  return post(`/api/docs/${docId}/archive/decisions`, { ...body, company_id: companyId })
}

export async function confirmLegacyArchive(companyId: string, docId: string, body: {
  retention_class: 'temporary' | 'epk' | 'permanent' | 'unclassified'
  basis: string
  reason: string
}): Promise<Pick<DocArchiveState, 'retention_state' | 'retention_class' | 'retention_snapshot'>> {
  return post(`/api/docs/${docId}/archive/confirm-legacy`, { ...body, company_id: companyId })
}

export async function listDestructionActs(companyId: string): Promise<DocDestructionAct[]> {
  const result = await get<{ acts: DocDestructionAct[] }>('/api/docs/archive/acts', {
    company_id: companyId,
  })
  return result.acts ?? []
}

export async function createDestructionAct(companyId: string, body: {
  act_number: string
  act_date: string
  basis: string
  committee: string[]
  doc_ids: string[]
}): Promise<DocDestructionAct> {
  return post('/api/docs/archive/acts', { ...body, company_id: companyId })
}

export async function approveDestructionAct(companyId: string, actId: string): Promise<DocDestructionAct> {
  return post(`/api/docs/archive/acts/${actId}/approve`, { company_id: companyId })
}

export async function cancelDestructionAct(
  companyId: string, actId: string, reason: string,
): Promise<DocDestructionAct> {
  return post(`/api/docs/archive/acts/${actId}/cancel`, {
    company_id: companyId, reason,
  })
}

export async function executeDestructionAct(companyId: string, actId: string): Promise<DocDestructionAct> {
  return post(`/api/docs/archive/acts/${actId}/execute`, { company_id: companyId })
}

export async function confirmBackupPurge(
  companyId: string, actId: string, evidence: string, externalCopiesEvidence?: string,
): Promise<DocDestructionAct> {
  return post(`/api/docs/archive/acts/${actId}/confirm-backup-purge`, {
    company_id: companyId,
    evidence,
    external_copies_evidence: externalCopiesEvidence?.trim() || null,
  })
}

/** Присвоить номер. Без `regNumber` номер выдаёт счётчик компании. */
export async function registerDoc(
  companyId: string, id: string, input: {
    regNumber?: string
    regDate?: string
    manualReason?: string
  } = {},
): Promise<DocCard> {
  return post<DocCard>(`/api/docs/${id}/register`, {
    company_id: companyId,
    reg_number: input.regNumber ?? null,
    reg_date: input.regDate ?? null,
    manual_reason: input.manualReason ?? null,
  })
}

export async function getVerificationLink(
  companyId: string, id: string,
): Promise<{ url: string; code: string }> {
  return post(`/api/docs/${id}/verification?company_id=${companyId}`, {})
}

export async function docAction(
  companyId: string, id: string, body: Record<string, unknown>,
): Promise<DocCard> {
  return post<DocCard>(`/api/docs/${id}/action`, { ...body, company_id: companyId })
}

export async function uploadVersion(
  companyId: string, id: string, file: File, role = 'body', title?: string,
): Promise<{ id: string; revision: number; duplicate?: boolean }> {
  const params = new URLSearchParams({ company_id: companyId, role })
  if (title) params.set('title', title)
  const form = new FormData()
  form.append('file', file)
  return upload(`/api/docs/${id}/versions?${params.toString()}`, form)
}

export async function tombstoneVersion(
  companyId: string, versionId: string, reason: string,
): Promise<{ tombstoned: string }> {
  return post(`/api/docs/versions/${versionId}/tombstone`, { company_id: companyId, reason })
}

export async function createErrand(
  companyId: string, id: string, body: {
    title: string
    assignee_id: string
    due_at?: string | null
    description?: string | null
  },
): Promise<{ task_id: string; number: number }> {
  return post(`/api/docs/${id}/errand`, { ...body, company_id: companyId })
}


/** Запустить круг согласования. Без маршрута берётся маршрут вида документа. */
export async function startApproval(
  companyId: string, id: string, route?: Array<Record<string, unknown>>,
  preview?: ApprovalPreview,
): Promise<{ round: number; approvals: number; steps: number; snapshot_sha256: string }> {
  return post(`/api/docs/${id}/approval/start`, {
    company_id: companyId, route: route ?? null,
    expected_edit_version: preview?.edit_version,
    expected_route_token: preview?.route_token,
  })
}

export interface ApprovalPreview {
  edit_version: string | null
  route_token: string
  problems: string[]
  steps: Array<{
    number: number; name: string; mode: string; quorum: string
    step_kind: string; sla_hours: number | null
    people: Array<{ id: string | null; name: string; kind: string }>
  }>
}

export function previewApproval(companyId: string, id: string) {
  return get<ApprovalPreview>(`/api/docs/${id}/approval/preview`, { company_id: companyId })
}

export function duplicateCandidates(companyId: string, fields: Record<string, string>) {
  return get<{ docs: Array<Pick<DocCard, 'id' | 'title' | 'reg_number' | 'external_number'>> }>(
    '/api/docs/duplicate-candidates', { company_id: companyId, ...fields })
}

export async function listDocViews(companyId: string) {
  return get<{ views: DocSavedView[] }>('/api/docs/views', { company_id: companyId })
}

export async function createDocView(data: {
  companyId: string
  name: string
  query: Record<string, string>
  shared?: boolean
}) {
  return post<DocSavedView>('/api/docs/views', {
    company_id: data.companyId,
    name: data.name,
    query: data.query,
    shared: data.shared ?? false,
  })
}

export async function deleteDocView(id: string, companyId: string) {
  return del(`/api/docs/views/${id}?company_id=${encodeURIComponent(companyId)}`)
}

export async function listDocLabels(companyId: string) {
  return get<{ labels: DocLabel[] }>('/api/docs/labels', { company_id: companyId })
}

export async function createDocLabel(companyId: string, name: string, color = 'slate') {
  return post<DocLabel>('/api/docs/labels', { company_id: companyId, name, color })
}

export async function deleteDocLabel(companyId: string, id: string) {
  return del(`/api/docs/labels/${id}?company_id=${encodeURIComponent(companyId)}`)
}

export async function toggleDocLabel(
  companyId: string, docId: string, labelId: string, on: boolean,
) {
  return post<{ on: boolean }>(`/api/docs/${docId}/labels`, {
    company_id: companyId, label_id: labelId, on,
  })
}

export async function bulkDocs(companyId: string, body: {
  doc_ids: string[]
  action: 'assign_responsible' | 'set_due' | 'assign_case' | 'add_label' | 'remove_label'
  responsible_id?: string
  due_at?: string
  case_id?: string
  label_id?: string
}): Promise<{ selected: number; updated: number; unchanged: number }> {
  return post('/api/docs/bulk', { ...body, company_id: companyId })
}

export async function cancelApproval(
  companyId: string, id: string, reason: string,
): Promise<{ cancelled: number; round: number }> {
  return post(`/api/docs/${id}/approval/cancel`, { company_id: companyId, reason })
}

/** Поставить визу. Отказ обязан нести причину: без неё автор не поймёт, что править. */
export async function decideApproval(
  companyId: string, approvalId: string, approved: boolean, comment?: string,
): Promise<{ status: string; left?: number; returned?: boolean }> {
  return post(`/api/docs/approvals/${approvalId}`, {
    company_id: companyId, approved, comment: comment ?? null,
  })
}

export async function myApprovals(companyId: string): Promise<MyApproval[]> {
  const r = await get<{ approvals: MyApproval[] }>('/api/docs/approvals/mine',
    { company_id: companyId })
  return r.approvals ?? []
}

export async function listCases(companyId: string, year?: number): Promise<DocCase[]> {
  const params: Record<string, string> = { company_id: companyId }
  if (year) params.year = String(year)
  const r = await get<{ cases: DocCase[] }>('/api/docs/cases', params)
  return r.cases ?? []
}

export async function createCase(
  companyId: string, body: Record<string, unknown>,
): Promise<{ id: string; index: string; title: string }> {
  return post('/api/docs/cases', { ...body, company_id: companyId })
}

export async function assignCase(
  companyId: string, docId: string, caseId: string | null,
): Promise<DocCard> {
  return put(`/api/docs/${docId}/case`, { company_id: companyId, case_id: caseId })
}

export async function closeCase(
  companyId: string, caseId: string, note?: string,
): Promise<{ id: string; status: string; closed_at: string }> {
  return post(`/api/docs/cases/${caseId}/close`, {
    company_id: companyId, note: note ?? null,
  })
}

/** Перенести номенклатуру на следующий год. Идемпотентно. */
export async function rolloverCases(
  companyId: string, year: number,
): Promise<{ added: number; defaults_updated: number; year: number }> {
  return post(`/api/docs/cases/rollover?company_id=${companyId}&year=${year}`, {})
}


/** Доска: колонки — шаги маршрута согласования, а не состояния карточки. */
export interface DocBoardColumn {
  key: string
  name: string
  docs: Array<{
    id: string; title: string; reg_number: string | null; status: string
    kind_name: string; waiting: number; due_at: string | null
    approval_due_at: string | null
    approval_overdue: boolean
    waiting_people: Array<{ user_id: string; name: string; due_at: string | null }>
  }>
}

export interface DocBoard {
  columns: DocBoardColumn[]
  total: number
  page: number
  page_size: number
  pages: number
  filter: { assignee_name: string | null; decision_name: string | null }
}

export type DocBoardReportMetric = 'started' | 'completed' | 'returned' | 'cancelled'
  | 'first_pass' | 'decisions' | 'late_decisions'

export async function board(companyId: string, filters: {
  family?: string
  kindId?: string
  assigneeId?: string
  pendingOnly?: boolean
  overdueOnly?: boolean
  cohortFrom?: string
  cohortTo?: string
  reportMetric?: DocBoardReportMetric
  decisionBy?: string
  page?: number
  pageSize?: number
} = {}): Promise<DocBoard> {
  const params: Record<string, string> = { company_id: companyId }
  if (filters.family) params.family = filters.family
  if (filters.kindId) params.kind_id = filters.kindId
  if (filters.assigneeId) params.assignee_id = filters.assigneeId
  if (filters.pendingOnly) params.pending_only = 'true'
  if (filters.overdueOnly) params.overdue_only = 'true'
  if (filters.cohortFrom) params.cohort_from = filters.cohortFrom
  if (filters.cohortTo) params.cohort_to = filters.cohortTo
  if (filters.reportMetric) params.report_metric = filters.reportMetric
  if (filters.decisionBy) params.decision_by = filters.decisionBy
  if (filters.page) params.page = String(filters.page)
  if (filters.pageSize) params.page_size = String(filters.pageSize)
  return get<DocBoard>('/api/docs/board', params)
}


export interface ApprovalDisciplineReport {
  period: {
    date_from: string
    date_to: string
    cohort: 'first_approval_start'
    time_zone: string
    as_of: string
  }
  summary: {
    documents: number
    completed: number
    returned: number
    cancelled: number
    first_pass_rate: number
    first_pass_documents: number
    first_pass_sample: number
  }
  backlog: {
    scope: 'company'
    as_of: string
    pending: number
    overdue: number
    people: Array<{
      user_id: string
      name: string
      pending: number
      overdue: number
    }>
  }
  by_kind: Array<{
    kind_id: string
    kind: string
    documents: number
    average_hours: number
    median_hours: number
    p90_hours: number
  }>
  people: Array<{
    user_id: string
    name: string
    decisions: number
    documents: number
    late_documents: number
    late_decisions: number
    delegated_decisions: number
    estimated_decisions: number
    average_hours: number
    median_hours: number
    p90_hours: number
  }>
}

export async function approvalDiscipline(
  companyId: string, dateFrom?: string, dateTo?: string,
): Promise<ApprovalDisciplineReport> {
  return get<ApprovalDisciplineReport>('/api/docs/reports/discipline', {
    company_id: companyId, date_from: dateFrom, date_to: dateTo,
  })
}


/** Точка обмена с корпоративной системой головной компании: папка туда и обратно. */
export interface DocExchangeTarget {
  id: string
  code: string
  name: string
  system: string          // sedo | naumen | other
  outbox_path: string
  inbox_path: string
  outbox_configured: boolean
  inbox_configured: boolean
  as_archive: boolean
  is_active: boolean
  scan_enabled: boolean
  scan_interval_min: number
  note: string | null
  last_export_at: string | null
  last_scan_at: string | null
  last_error: string | null
}

export interface DocExportRow {
  id: string
  status: string          // placed | downloaded | failed
  package: string
  path: string | null
  size: number
  target: string
  files: number
  error: string | null
  created_at: string | null
}

export interface DocInboxItem {
  id: string
  file_name: string
  size: number
  file_id: string | null
  target: string
  parsed: Record<string, string>
  status: string
  doc_id: string | null
  found_at: string | null
}

export async function exchangeTargets(companyId: string): Promise<DocExchangeTarget[]> {
  const r = await get<{ targets: DocExchangeTarget[] }>('/api/docs/exchange/targets',
    { company_id: companyId })
  return r.targets ?? []
}

export async function createExchangeTarget(
  companyId: string, body: Record<string, unknown>,
): Promise<{ id: string; code: string; name: string }> {
  return post('/api/docs/exchange/targets', { ...body, company_id: companyId })
}

export async function updateExchangeSchedule(
  companyId: string, id: string, enabled: boolean, intervalMin: number,
): Promise<{ enabled: boolean; interval_min: number }> {
  return put(`/api/docs/exchange/targets/${id}/schedule`, {
    company_id: companyId, enabled, interval_min: intervalMin,
  })
}

/** Выгрузить документ в папку головной компании. */
export async function exportDoc(
  companyId: string, id: string, targetId: string,
): Promise<{ id: string; package: string; path: string; files: number }> {
  return post(`/api/docs/${id}/export?company_id=${companyId}&target_id=${targetId}`, {})
}

export async function listExports(companyId: string, id: string): Promise<DocExportRow[]> {
  const r = await get<{ exports: DocExportRow[] }>(`/api/docs/${id}/exports`,
    { company_id: companyId })
  return r.exports ?? []
}

/** Посмотреть, что головная компания положила нам в папку. */
export async function scanInbox(
  companyId: string, targetId?: string,
): Promise<{ targets: number; added: number; errors: Array<{ target: string; error: string }> }> {
  return post(`/api/docs/exchange/scan?company_id=${companyId}${
    targetId ? `&target_id=${encodeURIComponent(targetId)}` : ''}`, {})
}

export async function listInbox(
  companyId: string, status = 'new',
): Promise<DocInboxItem[]> {
  const r = await get<{ items: DocInboxItem[] }>('/api/docs/exchange/inbox',
    { company_id: companyId, status })
  return r.items ?? []
}

export async function decideInbox(
  companyId: string, itemId: string, body: Record<string, unknown>,
): Promise<{ status: string; doc_id?: string }> {
  return post(`/api/docs/exchange/inbox/${itemId}`, { ...body, company_id: companyId })
}


/** Направить документ на ознакомление: поимённо или всему подразделению. */
export async function addAcquaint(
  companyId: string, id: string, body: Record<string, unknown>,
): Promise<{ added: number; total: number; skipped: number; snapshot_sha256: string }> {
  return post(`/api/docs/${id}/acquaint`, { ...body, company_id: companyId })
}

/** Отметиться ознакомленным. Только за себя. */
export async function markAcquainted(
  companyId: string, id: string, acquaintId?: string, note?: string,
): Promise<{ status: string; read_at: string | null }> {
  return post(`/api/docs/${id}/acquaint/read`, {
    company_id: companyId, acquaint_id: acquaintId ?? null, note: note ?? null,
  })
}

export interface AcquaintSubjects {
  people: { id: string; name: string; department_id: string | null }[]
  departments: { id: string; name: string; people: number }[]
}

export function acquaintSubjects(companyId: string): Promise<AcquaintSubjects> {
  return get('/api/docs/acquaint/subjects', { company_id: companyId })
}

export async function myAcquaints(companyId: string): Promise<Array<{
  id: string; doc_id: string; doc_title: string; doc_number: string | null
  due_at: string | null; snapshot_sha256: string | null; revision: number | null
}>> {
  const r = await get<{ acquaints: Array<{
    id: string; doc_id: string; doc_title: string; doc_number: string | null
    due_at: string | null; snapshot_sha256: string | null; revision: number | null
  }> }>('/api/docs/acquaints/mine', { company_id: companyId })
  return r.acquaints ?? []
}

export async function listSubstitutions(companyId: string): Promise<Substitution[]> {
  const r = await get<{ substitutions: Substitution[] }>('/api/docs/substitutions',
    { company_id: companyId })
  return r.substitutions ?? []
}

export async function createSubstitution(
  companyId: string, body: Record<string, unknown>,
): Promise<{ id: string }> {
  return post('/api/docs/substitutions', { ...body, company_id: companyId })
}

export async function stopSubstitution(
  companyId: string, id: string,
): Promise<{ stopped: string }> {
  return del(`/api/docs/substitutions/${id}?company_id=${companyId}`)
}

/** Пункты проекта, которые может закрывать документ: собираются из чек-листа. */
export async function listGateKeys(companyId: string): Promise<{ key: string; label: string }[]> {
  const res = await get<{ keys: { key: string; label: string }[] }>(
    '/api/docs/kinds/gate-keys', { company_id: companyId })
  return res.keys || []
}
