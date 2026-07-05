// Видеоконференции TradeLedger (Jitsi meet.dataworker.ru). Бэк подписывает токен
// организатора своим ключом (RS256/ASAP), фронт открывает ссылку.
import { get, post } from './apiClient'

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

/** Доступны ли конференции (задан ли ключ подписи на бэке). */
export async function getMeetingsConfig(): Promise<{ enabled: boolean; domain: string }> {
  return get<{ enabled: boolean; domain: string }>('/api/meetings/config')
}
