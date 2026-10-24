import { z } from 'zod'
import { ApiError, get, isApiEnabled, isDemoMode } from './apiClient'

export type ManagementKind = 'chats' | 'tasks' | 'calendar'
export interface ManagementParams {
  kind: ManagementKind
  space: string
  query: string
  date_from?: string
  date_to?: string
  time_zone?: string
  limit: number
}

const sourceSchema = z.object({
  code: z.string(), name: z.string(),
  state: z.enum(['ok', 'error', 'forbidden', 'not_configured']),
  fetched_at: z.string().nullable(),
  // В UI идут только известные состояния; произвольный текст отказа не выводится.
  error: z.unknown().optional().transform(() => null),
  truncated: z.boolean().optional(),
})
const optionalText = z.string().nullish()
const itemSchema = z.object({
  id: z.string(), source_id: z.string(), kind: z.enum(['chats', 'tasks', 'calendar']),
  source: z.object({
    code: z.string(), name: z.string(), company_id: z.string(), company_name: z.string(),
  }),
  title: z.string(), href: z.string(), subtitle: optionalText, status: optionalText,
  updated_at: optionalText, author_name: optionalText, assignee_name: optionalText,
  due_at: optionalText, starts_at: optionalText, ends_at: optionalText,
  unread_count: z.number().nullish(), project_name: optionalText,
})
const overviewSchema = z.object({
  enabled: z.boolean(), fetched_at: z.string(), items: z.array(itemSchema),
  sources: z.array(sourceSchema), truncated: z.boolean(),
})
export type ManagementItem = z.infer<typeof itemSchema>
export type ManagementSource = z.infer<typeof sourceSchema>
export type ManagementOverview = z.infer<typeof overviewSchema>

export class ManagementError extends Error {
  readonly status: number
  constructor(status: number) {
    super(status === 403 ? 'У вас нет доступа к управляющему пространству.'
      : status === 401 ? 'Войдите в пространство снова.'
        : status === 404 ? 'Источник или раздел недоступен. Сбросьте отбор, чтобы увидеть доступные источники, или повторите позже.'
          : status === 422 ? 'Проверьте условия поиска и период. Поиск: до 200 символов. Период: до 367 дней, включая обе даты. Измените условия и найдите снова.'
          : 'Не удалось получить обзор. Повторите запрос.')
    this.name = 'ManagementError'
    this.status = status
  }
}

export const managementAvailable = () => isApiEnabled() && !isDemoMode()

export async function getManagementStatus(): Promise<{ enabled: boolean }> {
  if (!managementAvailable()) return { enabled: false }
  try {
    return z.object({ enabled: z.boolean() }).parse(await get<unknown>('/api/management/status'))
  } catch (error) {
    throw new ManagementError(error instanceof ApiError ? error.status : 0)
  }
}

/** Все ограничения запроса и actor входят в ключ; предыдущая компания не подставляется. */
export function managementQueryKey(companyId: string, userId: string, params: ManagementParams) {
  return ['management-overview', companyId, userId, params] as const
}

export async function getManagementOverview(params: ManagementParams): Promise<ManagementOverview> {
  if (!managementAvailable()) throw new ManagementError(503)
  try {
    return overviewSchema.parse(await get<unknown>('/api/management/overview', { ...params }))
  } catch (error) {
    // Включая глобальный queryCache.onError: ни тело HTTP-ошибки, ни конфиг не попадут в toast.
    throw new ManagementError(error instanceof ApiError ? error.status : 0)
  }
}
