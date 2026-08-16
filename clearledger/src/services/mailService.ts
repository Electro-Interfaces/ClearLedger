/**
 * Клиент почтового коннектора (`/api/mail`, docs/MAIL.md).
 *
 * Один коннектор — много ящиков. Пароль ящика клиент не видит и не отправляет:
 * в записи хранится имя переменной окружения стека, значение живёт в `.env`.
 */
import { del, get, post, put } from './apiClient'

export interface MailAccount {
  id: string
  address: string
  title: string
  /** Зачем этот ящик: без описания через месяц никто не помнит, что куда идёт. */
  purpose: string | null
  mode: 'in' | 'out' | 'both'
  imapHost: string | null
  imapPort: number
  imapFolder: string
  imapSecurity: 'ssl' | 'starttls' | 'none'
  login: string | null
  /** Имя переменной окружения — путь для внедренца; сотрудник вводит пароль. */
  secretEnv: string | null
  /** Пароль задан (сам он не отдаётся никогда). */
  passwordSet: boolean
  smtpHost: string | null
  smtpPort: number
  smtpSecurity: 'ssl' | 'starttls' | 'none'
  /** Имя в поле «От кого» и подпись — настройка ящика, а не автора письма. */
  displayName: string | null
  signature: string | null
  /** Каждые сколько минут забирать почту; 0 — только вручную. */
  pollIntervalMin: number
  isActive: boolean
  lastUid: number | null
  lastSyncAt: string | null
  lastError: string | null
  /** Переменная с паролем найдена в окружении стека. */
  secretPresent: boolean
}

export interface MailThreadRow {
  id: string
  subject: string | null
  messages: number
  lastAt: string | null
  counterpartyId: string | null
  counterpartyName: string | null
  participants: string[]
}

export interface MailMessageRow {
  id: string
  direction: 'in' | 'out'
  subject: string | null
  fromName: string | null
  fromEmail: string | null
  to: string[]
  sentAt: string | null
  text: string | null
  html: string | null
  status: string
  counterpartyId: string | null
  /** Куда письмо уехало: chat | task | ticket | intake. */
  routedTo?: string | null
  attachments: {
    id: string; name: string; size: number; contentType: string | null
    /** Пакет приёмки, в который вложение уже разобрано. */
    intakeBatchId?: string | null
  }[]
}

export const getMailAccounts = (companyId: string) =>
  get<{ rows: MailAccount[] }>(`/api/mail/accounts?company_id=${companyId}`)

export type MailAccountInput = Omit<MailAccount,
  'id' | 'lastUid' | 'lastSyncAt' | 'lastError' | 'secretPresent' | 'passwordSet'>
  & { password?: string }

/** Ключи ручки — в змеином регистре: это тело pydantic-модели, а не наш camelCase. */
const toBody = (a: MailAccountInput) => ({
  address: a.address, title: a.title, purpose: a.purpose, mode: a.mode,
  imap_host: a.imapHost, imap_port: a.imapPort, imap_folder: a.imapFolder,
  imap_security: a.imapSecurity,
  login: a.login, secret_env: a.secretEnv,
  // Пустой пароль означает «не менять»: правка подписи не должна стирать доступ.
  password: a.password || null,
  smtp_host: a.smtpHost, smtp_port: a.smtpPort, smtp_security: a.smtpSecurity,
  display_name: a.displayName, signature: a.signature,
  poll_interval_min: a.pollIntervalMin, is_active: a.isActive,
})

export const createMailAccount = (companyId: string, a: MailAccountInput) =>
  post<MailAccount>(`/api/mail/accounts?company_id=${companyId}`, toBody(a))

export const updateMailAccount = (companyId: string, id: string, a: MailAccountInput) =>
  put<MailAccount>(`/api/mail/accounts/${id}?company_id=${companyId}`, toBody(a))

export const deleteMailAccount = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/mail/accounts/${id}?company_id=${companyId}`)

/** Забрать почту сейчас: один ящик или все активные. */
export const pollMail = (companyId: string, accountId?: string) =>
  post<{ fetched?: number; saved?: number; error?: string; accounts?: number }>(
    `/api/mail/poll?company_id=${companyId}` + (accountId ? `&account_id=${accountId}` : ''), {})

export const getMailThreads = (companyId: string, q?: string) =>
  get<{ rows: MailThreadRow[] }>(`/api/mail/threads?company_id=${companyId}`
    + (q ? `&q=${encodeURIComponent(q)}` : ''))

export const getMailThread = (companyId: string, threadId: string) =>
  get<{ rows: MailMessageRow[] }>(
    `/api/mail/thread?company_id=${companyId}&thread_id=${threadId}`)

export const mailAttachmentUrl = (companyId: string, attachmentId: string) =>
  `/api/mail/attachment?company_id=${companyId}&attachment_id=${attachmentId}`


/** Правило обработки письма: первое сработавшее решает его судьбу. */
export interface MailRule {
  id: string
  name: string
  sort: number
  accountId: string | null
  fromEmail: string | null
  fromDomain: string | null
  subjectLike: string | null
  hasAttachment: boolean | null
  unknownSender: boolean | null
  action: 'intake' | 'ticket' | 'chat' | 'task' | 'doc' | 'archive' | 'quarantine' | 'reject'
  setCounterpartyId: string | null
  setContractId: string | null
  /** Куда доставить: комната чата для действия «в чат». */
  setRoomId: string | null
  /** Объект для действия «в заявку»: заявка всегда про объект. */
  setObjectId: string | null
  isActive: boolean
  /** Сколько раз сработало: правило без срабатываний — мусор в списке. */
  hits: number
}

export type MailRuleInput = Omit<MailRule, 'id' | 'hits'>

const ruleBody = (r: MailRuleInput) => ({
  name: r.name, account_id: r.accountId, sort: r.sort,
  from_email: r.fromEmail || null, from_domain: r.fromDomain || null,
  subject_like: r.subjectLike || null, has_attachment: r.hasAttachment,
  unknown_sender: r.unknownSender, action: r.action,
  set_counterparty_id: r.setCounterpartyId, set_contract_id: r.setContractId,
  set_room_id: r.setRoomId, set_object_id: r.setObjectId || null,
  is_active: r.isActive,
})

export const getMailRules = (companyId: string) =>
  get<{ rows: MailRule[] }>(`/api/mail/rules?company_id=${companyId}`)

export const createMailRule = (companyId: string, r: MailRuleInput) =>
  post<MailRule>(`/api/mail/rules?company_id=${companyId}`, ruleBody(r))

export const updateMailRule = (companyId: string, id: string, r: MailRuleInput) =>
  put<MailRule>(`/api/mail/rules/${id}?company_id=${companyId}`, ruleBody(r))

export const deleteMailRule = (companyId: string, id: string) =>
  del<{ deleted: boolean }>(`/api/mail/rules/${id}?company_id=${companyId}`)

/** «Это письмо от такого-то»: запомнить адрес и применить к прошлой переписке. */
export const learnMailAddress = (companyId: string, address: string, counterpartyId: string) =>
  post<{ address: string; messages: number; threads: number }>(
    `/api/mail/learn-address?company_id=${companyId}`,
    { address, counterparty_id: counterpartyId })

export const getMailAddresses = (companyId: string) =>
  get<{ rows: { id: string; address: string; source: string; counterpartyId: string; counterpartyName: string }[] }>(
    `/api/mail/addresses?company_id=${companyId}`)


/** Разобрать вложения письма как документы приёмки (в учёт — отдельным шагом). */
export const mailToIntake = (companyId: string, messageId: string) =>
  post<{ batches: number; items: number; skipped?: string[] }>(
    `/api/mail/to-intake?company_id=${companyId}&message_id=${messageId}`, {})


/** Ответить в нить или написать заново — с того же ящика. */
export const sendMail = (companyId: string, body: {
  account_id: string; to: string[]; subject: string; body: string
  thread_id?: string | null; reply_to_message_id?: string | null
}) => post<{ sent?: boolean; error?: string; threadId?: string }>(
  `/api/mail/send?company_id=${companyId}`, body)

/** Переписка с контрагентом — для его карточки. */
export const getMailByCounterparty = (companyId: string, counterpartyId: string) =>
  get<{ rows: { id: string; subject: string | null; messages: number; lastAt: string | null }[] }>(
    `/api/mail/by-counterparty?company_id=${companyId}&counterparty_id=${counterpartyId}`)


/** Письмо, отложенное до решения человека. */
export interface MailQuarantineRow {
  id: string
  status: 'quarantine' | 'rejected'
  subject: string | null
  fromEmail: string | null
  fromName: string | null
  sentAt: string | null
  threadId: string | null
  hasAttachments: boolean
  /** Вердикт почтового сервера о подлинности, если он был. */
  authVerdict: string | null
}

export const getMailQuarantine = (companyId: string) =>
  get<{ rows: MailQuarantineRow[] }>(`/api/mail/quarantine?company_id=${companyId}`)

export const decideMailQuarantine = (
  companyId: string, messageIds: string[], decision: 'accept' | 'reject',
) => post<{ updated: number }>(`/api/mail/quarantine/decide?company_id=${companyId}`,
  { message_ids: messageIds, decision })


/** Проверить настройки ящика: приём и отправка отдельными ответами. */
export const testMailAccount = (companyId: string, id: string) =>
  post<{ imap?: { ok: boolean; text: string }; smtp?: { ok: boolean; text: string } }>(
    `/api/mail/accounts/${id}/test?company_id=${companyId}`, {})
