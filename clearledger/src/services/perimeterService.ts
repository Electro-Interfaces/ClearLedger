/**
 * Клиент `/api/perimeter/*` — «Периметр»: три слоя обязательств вне баланса.
 *
 * Первые два слоя считает «Бухгалтерия» (`/api/books/off-balance*`), и здесь они
 * берутся её же ручками — второй реализации у цифры быть не должно. Своё у продукта
 * только третье: договорённости, обещания и решения, которых в учёте нет.
 */
import { del, get, post, put } from './apiClient'

/** Запись третьего слоя. Суммы может не быть: не всё меряется деньгами. */
export interface PerimeterRecord {
  id: string
  kind: string; kindLabel: string
  direction: string; directionLabel: string
  title: string; details: string | null
  counterpartyId: string | null; counterparty: string | null
  amount: number | null
  startedOn: string | null; dueOn: string | null
  /** Дней до срока; отрицательное — просрочено. Считает бэкенд. */
  daysLeft: number | null
  overdue: boolean
  status: string; statusLabel: string
  confidence: string; confidenceLabel: string
  source: string | null; evidence: string | null
  consequence: string | null
  /** Забалансовый счёт, на который запись встала бы при оформлении. */
  account: string | null
  createdAt: string | null; closedAt: string | null; closedNote: string | null
}

export interface PerimeterRecordIn {
  title: string
  kind: string
  direction: string
  details?: string | null
  counterpartyId?: string | null
  counterpartyName?: string | null
  amount?: number | null
  startedOn?: string | null
  dueOn?: string | null
  status: string
  confidence: string
  source?: string | null
  evidence?: string | null
  consequence?: string | null
  account?: string | null
  closedNote?: string | null
}

export interface PerimeterDicts {
  kinds: { key: string; label: string }[]
  directions: { key: string; label: string }[]
  statuses: { key: string; label: string }[]
  confidence: { key: string; label: string }[]
}

export interface PerimeterOverview {
  layers: {
    key: string; no: number; title: string; hint: string
    /** Официальный слой приезжает из учёта, неофициальный записан человеком. */
    official: boolean
    count: number; amount: number; empty: boolean; note: string
  }[]
  byKind: { key: string; label: string; count: number; amount: number }[]
  byConfidence: { key: string; label: string; count: number; amount: number }[]
  overdue: PerimeterRecord[]
  soon: PerimeterRecord[]
  /** Записи с проставленным счётом, по которому в учёте пусто: пора оформлять. */
  toFormalize: PerimeterRecord[]
  withoutAmount: number
  activeCount: number
  totalCount: number
}

export interface PerimeterParty {
  counterparty: string; counterpartyId: string | null
  active: number; closed: number; amount: number; overdue: number
  nearest: string | null; kinds: string[]
}

export const getPerimeterDicts = (companyId: string) =>
  get<PerimeterDicts>(`/api/perimeter/dictionaries?company_id=${companyId}`)

export const getPerimeterOverview = (companyId: string) =>
  get<PerimeterOverview>(`/api/perimeter/overview?company_id=${companyId}`)

export const getPerimeterRecords = (
  companyId: string, f: { status?: string; kind?: string; direction?: string; q?: string } = {},
) => get<{ rows: PerimeterRecord[]; count: number }>(
  `/api/perimeter/records?company_id=${companyId}`
  + (f.status ? `&status=${f.status}` : '')
  + (f.kind ? `&kind=${f.kind}` : '')
  + (f.direction ? `&direction=${f.direction}` : '')
  + (f.q ? `&q=${encodeURIComponent(f.q)}` : ''))

export const createPerimeterRecord = (companyId: string, body: PerimeterRecordIn) =>
  post<PerimeterRecord>(`/api/perimeter/records?company_id=${companyId}`, body)

export const updatePerimeterRecord = (
  companyId: string, id: string, body: PerimeterRecordIn,
) => put<PerimeterRecord>(`/api/perimeter/records/${id}?company_id=${companyId}`, body)

export const deletePerimeterRecord = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/perimeter/records/${id}?company_id=${companyId}`)

export const getPerimeterParties = (companyId: string) =>
  get<{ rows: PerimeterParty[] }>(`/api/perimeter/by-counterparty?company_id=${companyId}`)

/* ── Наличные расчёты вне учёта ──────────────────────────────────────────── */

export interface CashMove {
  id: string
  direction: string; directionLabel: string
  kind: string; kindLabel: string
  happenedOn: string
  amount: number
  person: string
  counterpartyId: string | null
  purpose: string | null
  proof: string; proofLabel: string
  /** Чьи деньги: личные средства собственника или наличные компании. */
  purse: string; purseLabel: string
  parentId: string | null
  recordId: string | null
  dueOn: string | null
  overdue: boolean
  note: string | null
  /** Сотрудник, частное лицо, собственник: от этого зависит, примет ли учёт. */
  personKind: string; personKindLabel: string
  formalized: boolean
  formalizedOn: string | null
  formalizedBy: string | null
  /** Из тех, что бухгалтерия проводит документами, но ещё не провела. */
  awaitsPapers: boolean
  /** Возвращено и остаток есть у займа и подотчёта; у премии они null. */
  repaid: number | null
  rest: number | null
  createdAt: string | null
  payments?: {
    id: string; happenedOn: string; amount: number; note: string | null
    kind: string; kindLabel: string
  }[]
}

export interface CashIn {
  personName: string
  amount: number
  happenedOn: string
  direction: string
  kind: string
  personKind: string
  formalized: boolean
  formalizedOn?: string | null
  formalizedBy?: string | null
  purpose?: string | null
  proof: string
  purse: string
  parentId?: string | null
  recordId?: string | null
  dueOn?: string | null
  note?: string | null
  counterpartyId?: string | null
}

export interface CashJournal {
  rows: CashMove[]
  count: number
  out: number
  in: number
  net: number
  byKind: { key: string; label: string; out: number; in: number; count: number }[]
  ownerOut: number
  ownerIn: number
  noProof: number
  noProofCount: number
  /** Выдачи своим сотрудникам и то, что ещё не проведено документами. */
  employeeOut: number
  awaitsPapers: number
  awaitsPapersCount: number
}

export interface CashPerson {
  person: string
  personKind: string; personKindLabel: string
  awaits: number; awaitsAmount: number
  out: number; in: number; work: number
  /** Непогашенные займы: плюс — должны нам, минус — должны мы. */
  loanRest: number
  operations: number
  last: string | null
  overdue: number
  noProof: number
}

export interface CashDicts {
  kinds: { key: string; label: string }[]
  personKinds: { key: string; label: string }[]
  proof: { key: string; label: string }[]
  purse: { key: string; label: string }[]
  directions: { key: string; label: string }[]
}

export const getCashDicts = (companyId: string) =>
  get<CashDicts>(`/api/perimeter/cash/dictionaries?company_id=${companyId}`)

export const getCashJournal = (
  companyId: string, f: { from?: string; to?: string; kind?: string; person?: string } = {},
) => get<CashJournal>(
  `/api/perimeter/cash?company_id=${companyId}`
  + (f.from ? `&date_from=${f.from}` : '')
  + (f.to ? `&date_to=${f.to}` : '')
  + (f.kind ? `&kind=${f.kind}` : '')
  + (f.person ? `&person=${encodeURIComponent(f.person)}` : ''))

export const createCash = (companyId: string, body: CashIn) =>
  post<CashMove>(`/api/perimeter/cash?company_id=${companyId}`, body)

export const updateCash = (companyId: string, id: string, body: CashIn) =>
  put<CashMove>(`/api/perimeter/cash/${id}?company_id=${companyId}`, body)

export const deleteCash = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/perimeter/cash/${id}?company_id=${companyId}`)

export const getCashPeople = (companyId: string) =>
  get<{ rows: CashPerson[]; peopleCount: number; loanRestTotal: number }>(
    `/api/perimeter/cash/people?company_id=${companyId}`)

export const getCashLoans = (companyId: string) =>
  get<{ rows: CashMove[]; givenRest: number; takenRest: number; overdue: number }>(
    `/api/perimeter/cash/loans?company_id=${companyId}`)

export interface CashPapers {
  waiting: CashMove[]
  done: CashMove[]
  waitingAmount: number
  doneAmount: number
  byKind: { key: string; label: string; count: number; amount: number }[]
  /** Выданное под отчёт, по чему ещё не отчитались. */
  openAdvances: CashMove[]
}

export const getCashPapers = (companyId: string) =>
  get<CashPapers>(`/api/perimeter/cash/papers?company_id=${companyId}`)

/* ── Люди периметра ──────────────────────────────────────────────────────── */

/** Человек, с которым компания имеет дело помимо штата и договоров. */
export interface PerimeterPerson {
  id: string
  name: string
  kind: string; kindLabel: string
  role: string | null
  phone: string | null
  counterpartyId: string | null
  note: string | null
  isActive: boolean
  /** Что за человеком числится: считается по расчётам и договорённостям. */
  operations: number
  out: number; in: number
  /** Незакрытые займы и подотчёт: плюс — за человеком, минус — за нами. */
  rest: number
  awaits: number
  records: number
  last: string | null
}

export interface PersonIn {
  name: string
  kind: string
  role?: string | null
  phone?: string | null
  counterpartyId?: string | null
  note?: string | null
  isActive: boolean
}

export const getPerimeterPeople = (companyId: string, q?: string) =>
  get<{
    rows: PerimeterPerson[]
    kinds: { key: string; label: string }[]
    count: number
    byKind: { key: string; label: string; count: number }[]
    orphans: string[]
  }>(`/api/perimeter/people?company_id=${companyId}`
     + (q ? `&q=${encodeURIComponent(q)}` : ''))

export const createPerson = (companyId: string, body: PersonIn) =>
  post<{ id: string; name: string }>(`/api/perimeter/people?company_id=${companyId}`, body)

export const updatePerson = (companyId: string, id: string, body: PersonIn) =>
  put<{ id: string; name: string }>(
    `/api/perimeter/people/${id}?company_id=${companyId}`, body)

export const deletePerson = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/perimeter/people/${id}?company_id=${companyId}`)
