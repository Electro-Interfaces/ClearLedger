// Видеоконференции TradeLedger (Jitsi meet.dataworker.ru). Бэк подписывает токен
// организатора своим ключом (RS256/ASAP), фронт открывает ссылку.
import { get, isDemoMode, post } from './apiClient'

export interface MeetingUrls {
  room: string
  /** Ссылка организатора (с токеном) — открыть первым, входит модератором. */
  moderator_url: string
  /** Гостевая ссылка (без токена) — разослать участникам. */
  guest_url: string
}

/** Создать конференцию: случайная комната + ссылки организатора и гостя. */
export async function createMeeting(): Promise<MeetingUrls> {
  return post<MeetingUrls>('/api/meetings')
}

/**
 * Создать конференцию и войти в неё организатором.
 *
 * Вкладку заводим СИНХРОННО по клику, до запроса: `window.open` после `await`
 * браузер считает попапом и блокирует молча — кнопка выглядит нерабочей, никакой
 * ошибки при этом нет. Тот же приём, что у консоли станции.
 * Возвращает ссылки: гостевую зовущий рассылает сам (буфер, сообщение в чат).
 */
export async function startMeeting(): Promise<MeetingUrls> {
  if (isDemoMode()) return createMeeting()
  const вкладка = window.open('about:blank', '_blank')
  if (вкладка) вкладка.opener = null      // как noopener: чужая страница не дотянется до нашей
  try {
    const m = await createMeeting()
    if (вкладка) вкладка.location.href = m.moderator_url
    else window.open(m.moderator_url, '_blank', 'noopener,noreferrer') // попапы запрещены — пусть браузер спросит
    return m
  } catch (e) {
    вкладка?.close()
    throw e
  }
}

/** Доступны ли конференции (задан ли ключ подписи на бэке). */
export async function getMeetingsConfig(): Promise<{ enabled: boolean; domain: string }> {
  return get<{ enabled: boolean; domain: string }>('/api/meetings/config')
}

/**
 * Открыть видеовстречу запланированной встречи — ведущим.
 *
 * Комната у встречи одна и та же всегда, поэтому ссылка из карточки и из
 * приглашения ведёт туда же, куда входит ведущий. Вкладку, как и в
 * `startMeeting`, заводим синхронно по клику: после `await` браузер считает
 * её попапом и молча блокирует.
 */
export async function startEventMeeting(companyId: string, eventId: string): Promise<MeetingUrls> {
  const вкладка = window.open('about:blank', '_blank')
  if (вкладка) вкладка.opener = null
  try {
    const m = await post<MeetingUrls>(
      `/api/work/calendar/${eventId}/meeting?company_id=${encodeURIComponent(companyId)}`)
    if (вкладка) вкладка.location.href = m.moderator_url
    else window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
    return m
  } catch (e) {
    вкладка?.close()
    throw e
  }
}
