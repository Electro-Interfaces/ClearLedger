// Приложение «Конференции»: журнал конференций поверх календаря пространства.
// Встречу заводит и хранит календарь, здесь — свой экран, вход ведущим и то,
// что осталось после конференции: кто пришёл, сколько шло, о чём договорились.
import { downloadBlob, get, post } from './apiClient'
import type { MeetingUrls } from './conferenceService'

export interface ConfAttendee {
  user_id: string
  name: string
  response: 'pending' | 'accepted' | 'declined' | 'tentative' | string
}

export interface ConfGuest {
  email: string
  name?: string | null
  response?: string | null
}

export interface ConfSession {
  id: string
  started_at: string
  ended_at?: string | null
  /** Сколько длился конференция; null — идёт сейчас. */
  seconds?: number | null
  note?: string | null
  recording: boolean
  recording_seconds?: number | null
  came: { user_id: string; name: string; joined_at: string }[]
}

export interface ConfMeeting {
  id: string
  title: string
  description?: string | null
  starts_at: string
  ends_at: string
  tz: string
  status: string
  subject_ref?: string | null
  organizer_id: string
  organizer?: string | null
  /** Ссылка для участников: без токена, ведущим по ней не войти. */
  guest_url?: string | null
  room?: string | null
  mine: boolean
  /** Мой ответ: pending — меня позвали и я ещё не сказал, буду ли. */
  my_response?: 'pending' | 'accepted' | 'declined' | 'tentative' | null
  organizer_is_me: boolean
  attendees: ConfAttendee[]
  guests: ConfGuest[]
  live: boolean
  session?: ConfSession | null
}

export interface LiveConf extends ConfSession {
  title: string
  event_id?: string | null
  guest_url: string
  /** Сколько звали и сколько подтвердили — как у назначенной конференции. */
  invited?: number
  accepted?: number
  /** Завершать конференцию вправе тот, кто её собрал. */
  organizer_is_me?: boolean
}

export async function listMeetings(companyId: string, scope: 'upcoming' | 'past' | 'mine',
                                   q = '') {
  return get<{ meetings: ConfMeeting[]; enabled: boolean }>('/api/conf/meetings',
    { company_id: companyId, scope, q })
}

export async function listLive(companyId: string) {
  return get<{ live: LiveConf[] }>('/api/conf/live', { company_id: companyId })
}

export interface NewMeeting {
  title: string
  /** Пусто — конференция прямо сейчас. */
  startsAt?: string
  minutes?: number
  attendeeIds?: string[]
  guestEmails?: string[]
  subjectRef?: string
  description?: string
  notify?: boolean
  /** Продублировать приглашение письмом. Чат уходит всегда. */
  emailCopy?: boolean
  /** Открыть конференцию всему пространству: её увидят и смогут войти все. */
  openToSpace?: boolean
}

export async function createMeeting(companyId: string, data: NewMeeting) {
  return post<ConfMeeting & { delivery: { mailed: number; chatted: number; guests: number } }>(
    '/api/conf/meetings', {
      company_id: companyId,
      title: data.title,
      starts_at: data.startsAt || null,
      minutes: data.minutes ?? 60,
      attendee_ids: data.attendeeIds ?? [],
      guest_emails: data.guestEmails ?? [],
      subject_ref: data.subjectRef || null,
      description: data.description || null,
      notify: data.notify ?? true,
      email_copy: data.emailCopy ?? false,
      open_to_space: data.openToSpace ?? false,
    })
}

/**
 * Войти ведущим. Вкладку открываем СИНХРОННО по клику: после `await` браузер
 * считает её попапом и молча блокирует — кнопка выглядит нерабочей.
 */
export async function joinMeeting(companyId: string, eventId: string): Promise<MeetingUrls> {
  const вкладка = window.open('about:blank', '_blank')
  if (вкладка) вкладка.opener = null
  try {
    const m = await post<MeetingUrls & { session_id: string; moderator: boolean }>(
      `/api/conf/meetings/${eventId}/join?company_id=${encodeURIComponent(companyId)}`)
    if (вкладка) вкладка.location.href = m.moderator_url
    else window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
    return m
  } catch (e) {
    вкладка?.close()
    throw e
  }
}

export async function endSession(companyId: string, sessionId: string) {
  return post(`/api/conf/sessions/${sessionId}/end?company_id=${encodeURIComponent(companyId)}`)
}

export async function saveNote(companyId: string, sessionId: string, note: string) {
  return post<{ id: string; note: string | null }>(
    `/api/conf/sessions/${sessionId}/note`, { company_id: companyId, note })
}

export interface ConfRecording {
  session_id: string
  event_id?: string | null
  title: string
  started_at: string
  seconds?: number | null
  recording_seconds?: number | null
  /** Адрес файла в хранилище пространства; право проверяется при скачивании. */
  file_url: string
  started_by?: string | null
  subject_ref?: string | null
}

export interface ConfStats {
  days: number
  total: number
  seconds: number
  with_recording: number
  /** Конференций без измеренного времени: закрылись по сроку, а не людьми. */
  unmeasured: number
  people: { user_id: string; name: string; meetings: number; seconds: number }[]
  subjects: { subject_ref: string; meetings: number; seconds: number }[]
}

/**
 * Открыть запись.
 *
 * Прямая ссылка на файл не годится: пропуск лежит в браузере, а не в куках, и
 * новая вкладка приходит к серверу без него — человек видел «Требуется
 * авторизация» вместо своей же записи. Поэтому качаем с пропуском и отдаём
 * браузеру готовый файл.
 */
export async function openRecording(fileUrl: string, name: string) {
  const blob = await downloadBlob(fileUrl)
  const url = URL.createObjectURL(blob)
  const окно = window.open(url, '_blank', 'noopener,noreferrer')
  if (!окно) {
    // Попапы запрещены — сохраняем файлом, лишь бы человек до записи добрался.
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  // Ссылку держим минуту: вкладка успевает забрать файл, память не течёт.
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export async function listRecordings(companyId: string) {
  return get<{ recordings: ConfRecording[] }>('/api/conf/recordings',
    { company_id: companyId })
}

export async function stats(companyId: string, days = 30) {
  return get<ConfStats>('/api/conf/stats', { company_id: companyId, days })
}

/** Ответить на приглашение: буду или не смогу. Ответ видит организатор. */
export async function respond(companyId: string, eventId: string,
                              response: 'accepted' | 'declined') {
  return post(`/api/work/calendar/${eventId}`, { company_id: companyId, response })
}

/**
 * Постоянная комната пространства: место, а не событие.
 *
 * «Оперативка», «Переговорная», «Дежурная» — стоит всегда, входить можно без
 * приглашения и без назначения встречи.
 */
export interface ConfRoom {
  id: string
  name: string
  purpose?: string | null
  /** Ссылка для тех, у кого нет пропуска в пространство. */
  guest_url: string
  /** В комнате сейчас разговаривают. */
  live: boolean
  inside: { user_id: string; name: string }[]
  since?: string | null
}

export async function listRooms(companyId: string) {
  return get<{ rooms: ConfRoom[]; can_manage: boolean }>('/api/conf/rooms',
    { company_id: companyId })
}

export async function createRoom(companyId: string, name: string, purpose?: string) {
  return post<ConfRoom>('/api/conf/rooms',
    { company_id: companyId, name, purpose: purpose || null })
}

export async function archiveRoom(companyId: string, roomId: string) {
  return post(`/api/conf/rooms/${roomId}/archive?company_id=${encodeURIComponent(companyId)}`)
}

/** Войти в постоянную комнату. Ведущим входит каждый: организатора у места нет. */
export async function joinRoom(companyId: string, roomId: string): Promise<MeetingUrls> {
  const вкладка = window.open('about:blank', '_blank')
  if (вкладка) вкладка.opener = null
  try {
    const m = await post<MeetingUrls & { session_id: string }>(
      `/api/conf/rooms/${roomId}/join?company_id=${encodeURIComponent(companyId)}`)
    if (вкладка) вкладка.location.href = m.moderator_url
    else window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
    return m
  } catch (e) {
    вкладка?.close()
    throw e
  }
}
