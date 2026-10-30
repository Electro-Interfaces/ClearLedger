// Видеоконференции TradeLedger (Jitsi meet.dataworker.ru). Бэк подписывает токен
// организатора своим ключом (RS256/ASAP), фронт открывает ссылку.
import { toast } from 'sonner'
import { captureApiContextGuard, get, isDemoMode, post } from './apiClient'
import { следитьЗаВкладкой } from './confService'

export interface MeetingUrls {
  room: string
  /** Ссылка организатора (с токеном) — открыть первым, входит модератором. */
  moderator_url: string
  /** Гостевая ссылка (без токена) — разослать участникам. */
  guest_url: string
  /** Вход во встречу: созыв, с каким пропуском вошли и до какого времени
   *  ждём ведущего (после — первый вошедший откроет комнату сам). */
  session_id?: string
  moderator?: boolean
  host_wait_until?: string | null
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

/**
 * Вошёл участником — сказать, кого и до какого часа ждём. Иначе человек видит
 * «ждём организатора» и не знает, что через пять минут откроет комнату сам.
 */
export function сказатьОВходе(m: MeetingUrls) {
  if (m.moderator !== false) return
  const до = m.host_wait_until
    ? new Date(m.host_wait_until).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : null
  toast.info(до
    ? `Вы вошли участником: ведущего ждём до ${до}. Если он не придёт, войдите снова после ${до} — откроете комнату сами.`
    : 'Вы вошли участником: ведущий уже в комнате.', { duration: 10_000 })
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
  const проверитьКонтекст = captureApiContextGuard()
  if (вкладка) вкладка.opener = null
  try {
    const m = await post<MeetingUrls>(
      `/api/work/calendar/${eventId}/meeting?company_id=${encodeURIComponent(companyId)}`,
      undefined, { contextGuard: проверитьКонтекст })
    проверитьКонтекст()
    if (вкладка) вкладка.location.href = m.moderator_url
    else window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
    проверитьКонтекст()
    // Присутствие — как у входа из «Конференций»: по нему решается, есть ли
    // ведущий в комнате, когда истекут пять минут ожидания.
    if (m.session_id) следитьЗаВкладкой(companyId, m.session_id, вкладка)
    проверитьКонтекст()
    сказатьОВходе(m)
    проверитьКонтекст()
    return m
  } catch (e) {
    try { if (вкладка?.location.href === 'about:blank') вкладка.close() } catch { /* чужой origin */ }
    throw e
  }
}


/** Видеосвязь заявки: актуальный ticket ACL; только личный короткий вход, без гостевой ссылки. */
export async function startTicketMeeting(ticketId: string): Promise<void> {
  const tab = window.open('about:blank', '_blank')
  if (tab) tab.opener = null
  try {
    const result = await post<{ joinUrl: string }>(`/api/chat/tickets/${encodeURIComponent(ticketId)}/video`, {})
    if (tab) tab.location.replace(result.joinUrl)
    else window.open(result.joinUrl, '_blank', 'noopener,noreferrer')
  } catch (error) { tab?.close(); throw error }
}
