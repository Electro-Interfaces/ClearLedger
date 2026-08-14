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
import { get, getToken, post, put } from './apiClient'

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
  /** id записи в журнале — по нему панель даёт оценить ответ. */
  onRun?: (runId: string) => void
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
  /** Админ пространства: может править настройки и входить в мастерскую. Считает сервер. */
  can_manage?: boolean
}

/** Что умеет сервис аудитора в этом стеке. */
export interface AuditorHealth {
  ok: boolean
  cli: boolean
  auth: boolean
  skills: number
  workshop: boolean
  authProblem?: string
}

export async function getHealth(): Promise<AuditorHealth> {
  const res = await fetch('/auditor/health')
  if (!res.ok || !res.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Аудитор в этом пространстве не подключён')
  }
  return res.json()
}

/** Оценка ответа: вход петли обучения, а не рейтинг для красоты. */
export type AuditorVerdict = 'ok' | 'wrong' | 'not_an_issue'

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
  verdict: AuditorVerdict | null
  feedback: string | null
}

const BASE = '/auditor/api'

export interface AuditorFile { id: string; name: string; size: number }

/**
 * Приложить файл к разговору — выписку, реестр, акт.
 *
 * Файл уходит в СЕРВИС аудитора, а не в Ядро: он живёт в каталоге сессии внутри
 * контейнера и в базу пространства не попадает. Агент читает его сам, инструменты
 * включаются только на этот разговор.
 */
export async function uploadFile(companyId: string, file: File): Promise<AuditorFile> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken() ?? ''}`, 'X-Company-Id': companyId },
    body: form,
  })
  if (!res.ok) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.error || `Не удалось загрузить файл (${res.status})`)
  }
  return res.json()
}

/** Метод — то, чему агента научили: файл в `/work/.claude/skills`. */
export interface AuditorMethod {
  id: string
  name: string
  description: string
  /** Раздел «Чем проверено» заполнен — метод перестал быть гипотезой. */
  verified: boolean
  proof: string
  body: string
  updated: string
}

/** Файл знания о компании — то же, что едет в промпт каждого ответа. */
export interface AuditorKnowledge {
  file: string
  title: string
  body: string
  updated: string
}

/** Коммит рабочей папки: как рос сам агент, а не что у него спрашивали. */
export interface AuditorGrowth {
  hash: string
  date: string
  author: string
  subject: string
}

const readJson = async <T>(path: string, what: string): Promise<T> => {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok || !res.headers.get('content-type')?.includes('application/json')) {
    throw new Error(`${what} недоступны: аудитор не подключён`)
  }
  return res.json()
}

export const getMethods = () => readJson<AuditorMethod[]>('/methods', 'Методы')
export const getKnowledge = () => readJson<AuditorKnowledge[]>('/knowledge', 'Знание')
export const getGrowth = () => readJson<AuditorGrowth[]>('/growth', 'История')

/**
 * Править знание или метод прямо из интерфейса. Только админ пространства; правка
 * сразу коммитится в рабочую папку агента его именем.
 */
export async function saveAgentFile(companyId: string, path: string, body: string) {
  const res = await fetch(`${BASE}/agent-file`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken() ?? ''}`,
      'X-Company-Id': companyId,
    },
    body: JSON.stringify({ path, body }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.error || `Не сохранилось (${res.status})`)
  return res.json() as Promise<{ status: string }>
}

/**
 * Перезапуск агента: сбросить кеш знания, чтобы следующий вопрос читал файлы заново.
 * Контейнер не трогается и не должен — сессии у CLI нет, каждый вопрос это новый
 * процесс, читающий навыки с диска.
 */
export async function reloadAgent() {
  const res = await fetch(`${BASE}/reload`, { method: 'POST' })
  if (!res.ok) throw new Error('Не удалось перезапустить агента')
  return res.json() as Promise<{ methods: number; knowledge: number }>
}

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

/** Оценить ответ. Переоценка разрешена — человек часто меняет решение, разобравшись. */
export const rateRun = (companyId: string, runId: string, verdict: AuditorVerdict, feedback?: string) =>
  post<{ status: string }>(
    `/api/auditor/runs/${runId}/rate?company_id=${encodeURIComponent(companyId)}`,
    { verdict, feedback: feedback ?? null },
  )

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
  files: string[] = [],
  workshop = false,
): AbortController {
  const controller = new AbortController()

  fetch(`${BASE}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken() ?? ''}`,
      'X-Company-Id': companyId,
    },
    body: JSON.stringify({ question, context: ctx, history, files, workshop }),
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
            else if (msg.type === 'run') ev.onRun?.(msg.content)
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
