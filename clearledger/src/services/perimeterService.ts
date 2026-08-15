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
  /** Насколько вероятно, что сработает: у гарантии и претензии сумма без этого немая. */
  likelihood: string | null
  likelihoodLabel: string | null
  amountMin: number | null
  amountMax: number | null
  /** Ожидаемая величина с поправкой на вероятность. */
  expected: number | null
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
  likelihood?: string | null
  amountMin?: number | null
  amountMax?: number | null
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
    /** Из чего сложилась сумма слоя: разнородное показываем составом, а не итогом. */
    parts?: { label: string; amount: number }[]
    /** Записи, по которым величина НЕИЗВЕСТНА, а не равна нулю. */
    unknown?: number
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
  /** Деньги мимо кассы: не слой, а другой срез того же периметра. */
  cash: {
    out: number; in: number; ownerOut: number; count: number
    noProof: number
    awaitsPapers: number; awaitsPapersCount: number
    openAdvances: number
    loanGiven: number; loanTaken: number; loanOverdue: number
  }
  commitments: {
    active: number; people: number; monthlyMoney: number; missedTotal: number
    missed: {
      id: string; person: string; title: string
      missedCount: number; missedPeriods: string[]; missedAmount: number | null
    }[]
  }
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
  /** Регулярное обязательство, по которому платят: период закроется отметкой сам. */
  commitmentId: string | null
  dueOn: string | null
  /** Действие должника, признающее долг: прерывает срок исковой давности. */
  acknowledgedOn: string | null
  acknowledgedBy: string | null
  overdue: boolean
  note: string | null
  /** Сотрудник, частное лицо, собственник: от этого зависит, примет ли учёт. */
  personKind: string; personKindLabel: string
  writeoffReason: string | null
  writeoffReasonLabel: string | null
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
  commitmentId?: string | null
  /** За какой период платим: первый день периода. Пусто — период даты операции. */
  commitmentPeriod?: string | null
  acknowledgedOn?: string | null
  acknowledgedBy?: string | null
  /** Почему списали долг: простили, взыскать не с кого, истёк срок. */
  writeoffReason?: string | null
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
  payoutPhone: string | null
  payoutBank: string | null
  payoutNote: string | null
  counterpartyId: string | null
  note: string | null
  isActive: boolean
  /** Что за человеком числится: считается по расчётам и договорённостям. */
  operations: number
  out: number; in: number
  /** Оплата выполненной работы: долгом не становится, сколько её ни выдай. */
  work: number
  /** Незакрытые займы и подотчёт: плюс — за человеком, минус — за нами. */
  rest: number
  /** Встречные стороны по отдельности: свернуть их в одну цифру нельзя. */
  owed: number; owes: number
  canOffset: boolean
  overdue: number
  noProof: number
  awaits: number
  awaitsAmount: number
  records: number
  last: string | null
}

export interface PersonIn {
  name: string
  kind: string
  role?: string | null
  phone?: string | null
  /** Как вернуть деньги: телефон перевода, банк, способ словами. */
  payoutPhone?: string | null
  payoutBank?: string | null
  payoutNote?: string | null
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
    /** Итоги по расчётам: раньше их считал отдельный экран. */
    peopleInSettlements: number
    restTotal: number
    overdueTotal: number
    awaitsTotal: number
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

/* ── Регулярные обязательства ────────────────────────────────────────────── */

/** Период обязательства: закрыт отметкой, пропущен сознательно или просто пропущен. */
export interface CommitmentPeriod {
  periodStart: string
  label: string
  outcome: string
  doneOn: string | null
  /** Всего за период: выплаты журнала плюс отмеченное руками. Только для показа. */
  amount: number | null
  /** Отмеченное руками — то, что прошло мимо журнала. Форма правит именно его. */
  manualAmount: number | null
  paid: number | null
  note: string | null
  markId: string | null
  isCurrent: boolean
}

export interface Commitment {
  id: string
  person: string
  personId: string | null
  title: string
  details: string | null
  form: string; formLabel: string
  /** Сумма за период; у неденежной формы её нет. */
  amount: number | null
  periodicity: string; periodicityLabel: string
  dueDay: number | null
  startedOn: string
  endsOn: string | null
  status: string; statusLabel: string
  confidence: string; confidenceLabel: string
  note: string | null
  /** Последние 24 периода: у бессрочного недельного их накапливаются сотни. */
  periods: CommitmentPeriod[]
  periodsTotal: number
  doneCount: number
  skippedCount: number
  missedCount: number
  missedPeriods: string[]
  paidTotal: number | null
  lastPeriod: string | null
  /** Во что обошлись пропуски — только для денежной формы с названной суммой. */
  missedAmount: number | null
  nextPeriod: string | null
}

export interface CommitmentIn {
  personName: string
  title: string
  startedOn: string
  form: string
  amount?: number | null
  periodicity: string
  dueDay?: number | null
  endsOn?: string | null
  status: string
  confidence: string
  details?: string | null
  note?: string | null
  personKind: string
}

export interface CommitmentList {
  rows: Commitment[]
  dictionaries: {
    periodicity: { key: string; label: string }[]
    forms: { key: string; label: string }[]
    statuses: { key: string; label: string }[]
    confidence: { key: string; label: string }[]
  }
  activeCount: number
  missedTotal: number
  /** Регулярные выплаты, приведённые к месяцу: иначе недельное и годовое не сложить. */
  monthlyMoney: number
  peopleCount: number
}

export const getCommitments = (companyId: string) =>
  get<CommitmentList>(`/api/perimeter/commitments?company_id=${companyId}`)

export const createCommitment = (companyId: string, body: CommitmentIn) =>
  post<Commitment>(`/api/perimeter/commitments?company_id=${companyId}`, body)

export const updateCommitment = (companyId: string, id: string, body: CommitmentIn) =>
  put<Commitment>(`/api/perimeter/commitments/${id}?company_id=${companyId}`, body)

export const deleteCommitment = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/perimeter/commitments/${id}?company_id=${companyId}`)

export const markCommitment = (
  companyId: string, id: string,
  body: { periodStart: string; outcome: string; doneOn?: string | null
    amount?: number | null; note?: string | null },
) => post<Commitment>(
  `/api/perimeter/commitments/${id}/marks?company_id=${companyId}`, body)

export const unmarkCommitment = (companyId: string, id: string, markId: string) =>
  del<{ deleted: boolean }>(
    `/api/perimeter/commitments/${id}/marks/${markId}?company_id=${companyId}`)

/* ── Настройки, проверки и правовой контур ───────────────────────────────── */

export interface PerimeterSettings {
  /** Доплаты сверх ведомости: спорная возможность, выключена по умолчанию. */
  allowExtraPay: boolean
  advanceDays: number
  cashLimit: number
  loanWrittenFrom: number
  loanInterestFrom: number
  limitationYears: number
  showDisclaimer: boolean
  disclaimer: string
  updatedAt: string | null
}

export const getPerimeterSettings = (companyId: string) =>
  get<PerimeterSettings>(`/api/perimeter/settings?company_id=${companyId}`)

export const savePerimeterSettings = (companyId: string, body: Omit<PerimeterSettings,
  'disclaimer' | 'updatedAt'>) =>
  put<PerimeterSettings>(`/api/perimeter/settings?company_id=${companyId}`, body)

/** Предупреждения до сохранения: не запреты, а то, что стоит знать. */
export const checkCash = (companyId: string, body: CashIn) =>
  post<{ warnings: { key: string; text: string }[] }>(
    `/api/perimeter/cash/check?company_id=${companyId}`, body)

export interface CashAging {
  rows: (CashMove & {
    age: number; bucket: string; overdueReport: boolean
    limitationFrom?: string; limitationExpiresOn?: string
    limitationDaysLeft?: number; limitationBase?: string
  })[]
  /** Полученные займы: наш долг. Отдельно от выданного — свернуть их в один итог
   *  значило бы сказать, что долг знакомого гасит наш. */
  takenRows: CashAging['rows']
  takenRest: number
  buckets: { key: string; label: string; count: number; amount: number }[]
  byPurse: { key: string; label: string; amount: number }[]
  total: number
  overdueReports: CashMove[]
  advanceDays: number
  /** Право требования, сгорающее в ближайший квартал. */
  expiring: CashAging['rows']
  /** Уже сгоревшее: взыскать через суд нельзя, разговор другой. */
  expired: CashAging['rows']
  disclaimer: string | null
}

export const getCashAging = (companyId: string) =>
  get<CashAging>(`/api/perimeter/cash/aging?company_id=${companyId}`)

export const cashOffset = (
  companyId: string, body: { personName: string; amount: number; happenedOn: string
    note?: string | null },
) => post<{ offset: number; rows: number; left: number }>(
  `/api/perimeter/cash/offset?company_id=${companyId}`, body)

/** Отметить выгрузку: файл живёт дальше сам по себе, и след нужен. */
export const logExport = (companyId: string, what: string, rows: number) =>
  post<{ logged: boolean }>(
    `/api/perimeter/export-log?company_id=${companyId}`
    + `&what=${encodeURIComponent(what)}&rows=${rows}`, {})

/* ── Разбор недели ───────────────────────────────────────────────────────── */

export interface WeekReview {
  weekStart: string
  weekEnd: string
  isCurrent: boolean
  added: {
    cash: number; cashOut: number; records: number
    rows: {
      id: string; date: string; person: string; kind: string
      amount: number; direction: string; proof: string
    }[]
    recordRows: {
      id: string; title: string; counterparty: string | null; confidence: string
    }[]
  }
  /** Что требует решения: список намеренно короткий — длинный не разбирают. */
  todo: {
    key: string; title: string; count: number; hint: string
    mode: string; sub: string
    items: { id: string; text: string; note: string }[]
  }[]
  todoTotal: number
  reviewed: boolean
  reviewedAt: string | null
  reviewNote: string | null
  snapshot: unknown
}

export const getWeekReview = (companyId: string, week?: string) =>
  get<WeekReview>(`/api/perimeter/review?company_id=${companyId}`
    + (week ? `&week=${week}` : ''))

export const markWeekReview = (
  companyId: string, body: { weekStart: string; note: string | null },
) => post<{ weekStart: string; reviewed: boolean }>(
  `/api/perimeter/review?company_id=${companyId}`, body)

export const getReviewHistory = (companyId: string) =>
  get<{
    rows: {
      weekStart: string; reviewedAt: string | null; by: string | null
      note: string | null; todoTotal: number | null
      added: { cash: number; cashOut: number; records: number } | null
    }[]
    weeksInRow: number
  }>(`/api/perimeter/reviews?company_id=${companyId}`)

/* ── Быстрый ввод, сверка, прогноз, мост ─────────────────────────────────── */

/** Разобранная строка быстрого ввода: то, в чём система уверена. */
export interface QuickDraft extends CashIn {
  kindLabel: string
  /** Что удалось понять — показывается человеку до сохранения. */
  understood: string[]
  /** Чего не хватает для сохранения. */
  missing: string[]
}

export const parseQuick = (companyId: string, line: string) =>
  post<QuickDraft>(`/api/perimeter/cash/parse?company_id=${companyId}`
    + `&text_line=${encodeURIComponent(line)}`, {})

export interface ReconcileState {
  purse: string; purseLabel: string
  out: number; in: number
  /** Сколько должно быть в кошельке по журналу. */
  byJournal: number
  lastCheckedOn: string | null
  lastDiff: number | null
}

export const getReconcileState = (companyId: string, purse = 'owner') =>
  get<ReconcileState>(`/api/perimeter/cash/reconcile?company_id=${companyId}&purse=${purse}`)

export const doReconcile = (
  companyId: string,
  body: { countedOn: string; counted: number; purse: string; note?: string | null },
) => post<{ diff: number; created: boolean; message?: string }>(
  `/api/perimeter/cash/reconcile?company_id=${companyId}`, body)

export interface CashForecast {
  points: { date: string; amount: number; what: string; kind: string; id: string }[]
  total: number
  weeks: { weekStart: string; amount: number }[]
  horizon: string
  next30: number
}

export const getCashForecast = (companyId: string, days = 90) =>
  get<CashForecast>(`/api/perimeter/cash/forecast?company_id=${companyId}&days=${days}`)

export interface DebtBridge {
  steps: { key: string; label: string; amount: number; kind: string }[]
  from: string; to: string
  checks: { calculated: number; actual: number; diff: number }
}

export const getDebtBridge = (companyId: string, from: string, to: string) =>
  get<DebtBridge>(`/api/perimeter/cash/debt-bridge?company_id=${companyId}`
    + `&date_from=${from}&date_to=${to}`)

/* ── Напоминания и акт сверки ────────────────────────────────────────────── */

export interface Reminder {
  id: string; person: string; happenedOn: string
  channel: string; channelLabel: string
  outcome: string; outcomeLabel: string
  promisedOn: string | null
  /** Обещал и срок прошёл: второе обещание стоит дешевле первого. */
  promiseBroken: boolean
  note: string | null
  cashId: string | null; recordId: string | null; commitmentId: string | null
  createdAt: string | null
}

export const getReminders = (companyId: string, person?: string) =>
  get<{
    rows: Reminder[]; count: number
    channels: { key: string; label: string }[]
    outcomes: { key: string; label: string }[]
    broken: Reminder[]
  }>(`/api/perimeter/reminders?company_id=${companyId}`
     + (person ? `&person=${encodeURIComponent(person)}` : ''))

export const createReminder = (companyId: string, body: {
  personName: string; happenedOn: string; channel: string; outcome: string
  promisedOn?: string | null; note?: string | null
  cashId?: string | null; recordId?: string | null; commitmentId?: string | null
}) => post<Reminder>(`/api/perimeter/reminders?company_id=${companyId}`, body)

/**
 * Удалить запись разговора. Признание долга держалось на нём: сервер вернёт срок
 * исковой давности к прежнему основанию или к более раннему разговору.
 */
export const deleteReminder = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(
    `/api/perimeter/reminders/${id}?company_id=${companyId}`)

export interface PersonStatement {
  person: string
  card: {
    kind: string | null; role: string | null; phone: string | null
    payoutPhone: string | null; payoutBank: string | null; payoutNote: string | null
  } | null
  cash: (CashMove & { limitationExpiresOn?: string; limitationDaysLeft?: number })[]
  commitments: Commitment[]
  records: PerimeterRecord[]
  reminders: Reminder[]
  totals: {
    out: number; in: number
    /** Не закрыто: плюс за человеком, минус за нами. */
    open: number; openCount: number; writtenOff: number
  }
  disclaimer: string | null
}

export const getPersonStatement = (companyId: string, person: string) =>
  get<PersonStatement>(`/api/perimeter/people/statement?company_id=${companyId}`
    + `&person=${encodeURIComponent(person)}`)

/* ── Сводка в чат и календарь выдач ──────────────────────────────────────── */

export interface Digest {
  text: string
  weekStart: string
  todoTotal: number
  rooms: { id: string; title: string; kind: string }[]
  /** Готовые тексты персональных напоминаний — рассылать их продукт не станет. */
  personal: { person: string; text: string }[]
}

export const getDigest = (companyId: string, week?: string) =>
  get<Digest>(`/api/perimeter/digest?company_id=${companyId}`
    + (week ? `&week=${week}` : ''))

export const sendDigest = (companyId: string, body: { roomId: string; text: string }) =>
  post<{ sent: boolean; roomId: string }>(
    `/api/perimeter/digest/send?company_id=${companyId}`, body)

export interface CashCalendar {
  from: string; to: string
  weeks: {
    weekStart: string
    days: { date: string; amount: number; count: number; inRange: boolean }[]
  }[]
  days: { date: string; amount: number; count: number; people: string[]; weekday: number }[]
  byWeekday: { weekday: number; label: string; amount: number; count: number }[]
  total: number
  maxDay: number
  activeDays: number
  /** Среднее по дням С ВЫДАЧАМИ: делить на календарные — врать. */
  avgActiveDay: number
}

export const getCashCalendar = (companyId: string, from?: string, to?: string) =>
  get<CashCalendar>(`/api/perimeter/cash/calendar?company_id=${companyId}`
    + (from ? `&date_from=${from}` : '') + (to ? `&date_to=${to}` : ''))
