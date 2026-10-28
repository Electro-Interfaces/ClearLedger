/** Речь в текст: распознаватель своего стека через бэкенд (server/app/routers/speech_router.py). */
import { get, upload } from './apiClient'

export async function health() {
  return get<{ ready: boolean }>('/api/speech/health')
}

/** Через общий `upload`: тот же адрес пространства, заголовки и разбор ошибок, что у файлов. */
export async function dictate(audio: Blob): Promise<string> {
  const form = new FormData()
  form.append('file', audio, 'voice.webm')
  return (await upload<{ text: string }>('/api/speech/dictate', form)).text || ''
}
