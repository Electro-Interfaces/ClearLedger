/**
 * Приложение «Дело» — документооборот пространства.
 *
 * Документ здесь самостоятельный объект: вид, реквизиты, регистрационный номер,
 * редакции файла и след. Поручение по документу — обычная задача, поэтому здесь
 * только заведение связи, а сама работа живёт в «Задачах».
 */
import { get, post, put, upload } from './apiClient'

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
  fields: Array<Record<string, unknown>>
  errand_type_id: string | null
  requires_registration: boolean
  is_active: boolean
  sort_order: number
}

export interface DocCard {
  id: string
  kind_id: string
  kind_code: string
  kind_name: string
  family: string
  direction: string
  title: string
  summary: string | null
  status: string          // draft | registered | in_force | executed | archived | cancelled
  reg_number: string | null
  reg_date: string | null
  number_manual: boolean
  organization_id: string | null
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
  confidentiality: string  // company | private
  attrs: Record<string, unknown>
  source: string
  source_ref: string | null
  current_revision: number
  has_files: boolean
  created_at: string | null
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
  status: string          // pending | approved | rejected | skipped
  assignee_id: string | null
  comment: string | null
  decided_at: string | null
  due_at: string | null
}

/** Состояние шага: сколько решили и кого ждут. */
export interface DocApprovalStep {
  step_no: number
  name: string
  mode: string
  quorum: string
  decided: number
  total: number
  passed: boolean
  waiting: string[]
  rejected: boolean
}

export interface DocApprovalState {
  status: string          // none | pending | approved | rejected
  round: number
  steps: DocApprovalStep[]
  rows: DocApprovalRow[]
}

/** Что ждёт моей визы — экран «На мне». */
export interface MyApproval {
  id: string
  doc_id: string
  step_name: string
  mode: string
  due_at: string | null
  doc_title: string
  doc_number: string | null
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
}

export interface DocDetails extends DocCard {
  kind: DocKind | null
  versions: DocVersion[]
  events: DocEvent[]
  relations: DocRelation[]
  approval: DocApprovalState
  case_id: string | null
  storage_until: string | null
  approval_status: string
  approval_round: number
}

export interface DocFilters {
  family?: string
  direction?: string
  status?: string
  kind_id?: string
  counterparty_id?: string
  responsible_id?: string
  date_from?: string
  date_to?: string
  q?: string
  limit?: number
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

/** Присвоить номер. Без `regNumber` номер выдаёт счётчик компании. */
export async function registerDoc(
  companyId: string, id: string, regNumber?: string, regDate?: string,
): Promise<DocCard> {
  return post<DocCard>(`/api/docs/${id}/register`, {
    company_id: companyId,
    reg_number: regNumber || null,
    reg_date: regDate || null,
  })
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
  companyId: string, id: string, body: Record<string, unknown>,
): Promise<{ task_id: string; number: number }> {
  return post(`/api/docs/${id}/errand`, { ...body, company_id: companyId })
}


/** Запустить круг согласования. Без маршрута берётся маршрут вида документа. */
export async function startApproval(
  companyId: string, id: string, route?: Array<Record<string, unknown>>,
): Promise<{ round: number; approvals: number; steps: number }> {
  return post(`/api/docs/${id}/approval/start`, { company_id: companyId, route: route ?? null })
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

/** Перенести номенклатуру на следующий год. Идемпотентно. */
export async function rolloverCases(
  companyId: string, year: number,
): Promise<{ added: number; year: number }> {
  return post(`/api/docs/cases/rollover?company_id=${companyId}&year=${year}`, {})
}
