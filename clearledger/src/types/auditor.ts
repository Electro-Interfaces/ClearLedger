/** Типы для модуля AI-аудитора ClearLedger */

// ---- AI Chat ----

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
}

export type AIModel = 'claude-sonnet' | 'claude-haiku' | 'gpt-4o' | 'gpt-4o-mini'

export const MODEL_LABELS: Record<AIModel, string> = {
  'claude-sonnet': 'Claude Sonnet',
  'claude-haiku': 'Claude Haiku',
  'gpt-4o': 'GPT-4o',
  'gpt-4o-mini': 'GPT-4o Mini',
}

// ---- Commands / Skills ----

export interface CommandItem {
  id: string
  label: string
  description: string
  icon: string // lucide icon name
}

export interface CommandGroup {
  id: string
  label: string
  icon: string
  items: CommandItem[]
}

export const COMMAND_GROUPS: CommandGroup[] = [
  {
    id: 'audit',
    label: 'Аудит',
    icon: 'Shield',
    items: [
      { id: 'audit-full', label: 'Полный аудит', description: 'Комплексная проверка всех документов', icon: 'ShieldCheck' },
      { id: 'audit-duplicates', label: 'Поиск дубликатов', description: 'Найти дублирующиеся записи', icon: 'Copy' },
      { id: 'audit-gaps', label: 'Пропуски нумерации', description: 'Найти пропуски в нумерации документов', icon: 'Hash' },
      { id: 'audit-amounts', label: 'Проверка сумм', description: 'Сверка итогов и промежуточных сумм', icon: 'Calculator' },
    ],
  },
  {
    id: 'reports',
    label: 'Отчёты',
    icon: 'FileText',
    items: [
      { id: 'report-summary', label: 'Сводный отчёт', description: 'Общая статистика по документам', icon: 'BarChart3' },
      { id: 'report-counterparties', label: 'По контрагентам', description: 'Разбивка по контрагентам', icon: 'Users' },
      { id: 'report-periods', label: 'По периодам', description: 'Динамика поступления документов', icon: 'Calendar' },
    ],
  },
  {
    id: 'stats',
    label: 'Статистика',
    icon: 'TrendingUp',
    items: [
      { id: 'stats-quality', label: 'Качество данных', description: 'Оценка полноты и корректности', icon: 'CheckCircle' },
      { id: 'stats-sources', label: 'По источникам', description: 'Статистика по каналам поступления', icon: 'ArrowDownToLine' },
      { id: 'stats-processing', label: 'Скорость обработки', description: 'Среднее время обработки документа', icon: 'Timer' },
    ],
  },
  {
    id: 'processing',
    label: 'Обработки',
    icon: 'Cog',
    items: [
      { id: 'proc-normalize', label: 'Нормализация', description: 'Привести данные к единому формату', icon: 'Wand2' },
      { id: 'proc-classify', label: 'Переклассификация', description: 'Пересмотреть категории документов', icon: 'Tags' },
      { id: 'proc-enrich', label: 'Обогащение', description: 'Дополнить данные из внешних источников', icon: 'Sparkles' },
    ],
  },
]

export const COMMAND_PROMPTS: Record<string, string> = {
  'audit-full': 'Проведи полный аудит документов компании. Проверь: дубликаты, пропуски нумерации, несоответствия сумм, просроченные документы. Выдай список findings с severity.',
  'audit-duplicates': 'Найди все дублирующиеся документы. Сравни по: номеру, дате, сумме, контрагенту. Покажи группы дубликатов.',
  'audit-gaps': 'Найди пропуски в нумерации документов по каждому типу. Покажи ожидаемые и пропущенные номера.',
  'audit-amounts': 'Проверь соответствие сумм в документах. Сравни итоги накладных со счетами-фактурами и актами.',
  'report-summary': 'Сформируй сводный отчёт по всем документам: количество по типам, статусам, суммы, средний чек.',
  'report-counterparties': 'Покажи статистику по контрагентам: количество документов, суммы, последний документ, проблемы.',
  'report-periods': 'Покажи динамику поступления документов по месяцам за последний год.',
  'stats-quality': 'Оцени качество данных: процент заполненных полей, корректность ИНН/КПП, соответствие форматов дат.',
  'stats-sources': 'Покажи статистику по каналам поступления документов: email, 1С, загрузка, API.',
  'stats-processing': 'Рассчитай среднее время обработки документа от поступления до верификации.',
  'proc-normalize': 'Приведи данные к единому формату: ИНН без пробелов, даты в ISO, суммы без валютных символов.',
  'proc-classify': 'Пересмотри категории документов на основе содержимого. Предложи изменения классификации.',
  'proc-enrich': 'Дополни данные контрагентов из открытых источников: полное наименование, адрес, ОГРН.',
}

// ---- Findings & Dashboard ----

export type FindingSeverity = 'critical' | 'warning' | 'info'

export interface AuditFinding {
  id: string
  title: string
  severity: FindingSeverity
  description: string
  category: string
  timestamp: string
}

export interface AuditDashboard {
  findings: {
    critical: number
    warning: number
    info: number
    resolved: number
  }
  instances: {
    active: number
    total: number
  }
  recentFindings: AuditFinding[]
}

// ---- Instances ----

export interface AuditorInstance {
  id: string
  name: string
  companyId: string
  status: 'active' | 'inactive'
  documentsCount: number
  lastAuditAt?: string
}
