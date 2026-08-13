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
  login: string | null
  secretEnv: string | null
  smtpHost: string | null
  smtpPort: number
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
  attachments: { id: string; name: string; size: number; contentType: string | null }[]
}

export const getMailAccounts = (companyId: string) =>
  get<{ rows: MailAccount[] }>(`/api/mail/accounts?company_id=${companyId}`)

export type MailAccountInput = Omit<MailAccount,
  'id' | 'lastUid' | 'lastSyncAt' | 'lastError' | 'secretPresent'>

/** Ключи ручки — в змеином регистре: это тело pydantic-модели, а не наш camelCase. */
const toBody = (a: MailAccountInput) => ({
  address: a.address, title: a.title, purpose: a.purpose, mode: a.mode,
  imap_host: a.imapHost, imap_port: a.imapPort, imap_folder: a.imapFolder,
  login: a.login, secret_env: a.secretEnv,
  smtp_host: a.smtpHost, smtp_port: a.smtpPort, is_active: a.isActive,
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
