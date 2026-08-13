/**
 * Аудитор пространства — клиент сквозного агента (сервис `auditor` стека).
 *
 * Не путать с `auditorService.ts`: тот обслуживает страницу партнёрского контура
 * (`pages/partner/AuditorPage.tsx`) и ходит в `/api/auditor/*`. Здесь другой адрес
 * (`/auditor/api/*`, свой контейнер) и другой смысл: агент отвечает по данным ЭТОГО
 * пространства и с оглядкой на экран, с которого его позвали.
 *
 * Запрос идёт токеном пользователя: аудитор своих прав не имеет и не покажет того,
 * чего человек не видит сам.
 */
import { get, getToken, put } from './apiClient'

/** Где человек находился, когда позвал. Отсюда агент понимает, куда смотреть. */
export interface AuditorContext {
  path?: string
  product?: string | null
  params?: Record<string, string> | null
}

export interface AuditorFinding {
  severity: 'high' | 'medium' | 'low'
  title: string
  detail?: string
  action?: string
}

export interface AuditorEvents {
  onStatus?: (text: string) => void
  onSkills?: (ids: string[]) => void
  onText: (chunk: string) => void
  onFindings?: (findings: AuditorFinding[]) => void
  onError?: (message: string) => void
  onDone?: () => void
}

export interface AuditorSkill { id: string; name: string; group: string; when: string }

/** Настройки агента в пространстве. Живут в Ядре, а не в образе сервиса. */
export interface AuditorSettings {
  disabled_skills: string[]
  instructions: string | null
  mode: 'careful' | 'normal' | 'thorough'
  model_plan: string | null
  model_answer: string | null
  updated_at?: string | null
}

export interface AuditorRun {
  id: string
  question: string
  path: string | null
  skills: string[]
  answer: string | null
  findings: AuditorFinding[]
  duration_ms: number | null
  created_at: string | null
  user: string | null
}

const BASE = '/auditor/api'

/** Каталог навыков — чем аудитор вообще умеет отвечать. */
export async function getSkills(): Promise<AuditorSkill[]> {
  const res = await fetch(`${BASE}/skills`)
  // Тот же случай, что и в `ask`: без профиля в стеке сюда приходит index.html SPA
  // с кодом 200, и `res.json()` падал бы «Unexpected token <» вместо внятного ответа.
  if (!res.ok || !res.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Аудитор в этом пространстве не подключён')
  }
  return res.json()
}

// ── Настройки и журнал: это Ядро, а не сервис агента ──────────────────────────
// Адрес другой намеренно: настройки принадлежат ПРОСТРАНСТВУ (правятся человеком,
// переживают пересборку образа, попадают в бэкап), а сервис агента — сменная часть.

export const getSettings = (companyId: string) =>
  get<AuditorSettings>('/api/auditor/settings', { company_id: companyId })

export const saveSettings = (companyId: string, s: Omit<AuditorSettings, 'updated_at'>) =>
  put<AuditorSettings>(`/api/auditor/settings?company_id=${encodeURIComponent(companyId)}`, s)

export const getRuns = (companyId: string, limit = 50) =>
  get<{ runs: AuditorRun[] }>('/api/auditor/runs', { company_id: companyId, limit })

/**
 * Задать вопрос. Ответ приходит потоком: сначала статусы («смотрю данные»), затем
 * текст кусками, в конце находки. Возвращает AbortController — уход со страницы или
 * новый вопрос обрывает предыдущий, чтобы не платить за ответ, который никто не ждёт.
 */
export function ask(
  question: string,
  ctx: AuditorContext,
  companyId: string,
  history: { role: 'user' | 'assistant'; content: string }[],
  ev: AuditorEvents,
): AbortController {
  const controller = new AbortController()

  fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken() ?? ''}`,
      'X-Company-Id': companyId,
    },
    body: JSON.stringify({ question, context: ctx, history }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        // Ответ ошибки — обычный JSON, а не поток: 503 «нет CLI», 401 «токен не принят».
        const detail = await res.json().catch(() => null)
        ev.onError?.(detail?.error || `${res.status} ${res.statusText}`)
        ev.onDone?.()
        return
      }
      // Профиль `auditor` в стеке не поднят — кромка не знает такого пути и отдаёт SPA
      // Ядра с кодом 200. Без этой проверки панель молча дочитывала бы HTML до конца и
      // не показывала ничего: ни ответа, ни ошибки.
      if (!res.headers.get('content-type')?.includes('text/event-stream')) {
        ev.onError?.('Аудитор в этом пространстве не подключён')
        ev.onDone?.()
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6)
          if (raw === '[DONE]') { ev.onDone?.(); return }
          try {
            const msg = JSON.parse(raw)
            if (msg.type === 'text') ev.onText(msg.content)
            else if (msg.type === 'status') ev.onStatus?.(msg.content)
            else if (msg.type === 'skills') ev.onSkills?.(msg.content)
            else if (msg.type === 'findings') ev.onFindings?.(msg.content)
            else if (msg.type === 'error') ev.onError?.(msg.content)
          } catch { /* не наша строка потока */ }
        }
      }
      ev.onDone?.()
    })
    .catch((e: Error) => {
      if (e.name === 'AbortError') return
      ev.onError?.(e.message)
      ev.onDone?.()
    })

  return controller
}
