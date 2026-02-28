/**
 * Сервис AI-аудитора ClearLedger.
 * Dual-mode: localStorage (demo) / API.
 */

import type { AuditDashboard, AuditorInstance, AIModel, AuditFinding } from '@/types/auditor'
import { isApiEnabled, get } from './apiClient'

// ---- Demo data ----

const DEMO_INSTANCES: AuditorInstance[] = [
  {
    id: 'inst-1',
    name: 'ClearLedger — Основная',
    companyId: 'npk',
    status: 'active',
    documentsCount: 1247,
    lastAuditAt: new Date(Date.now() - 86400000).toISOString(),
  },
  {
    id: 'inst-2',
    name: 'ClearLedger — Тест',
    companyId: 'rti',
    status: 'inactive',
    documentsCount: 85,
  },
]

const DEMO_FINDINGS: AuditFinding[] = [
  { id: 'f1', title: 'Дубликат: Счёт №142 от 15.01.2026', severity: 'critical', description: 'Найден дубликат документа с идентичным номером и датой', category: 'duplicates', timestamp: new Date(Date.now() - 3600000).toISOString() },
  { id: 'f2', title: 'Пропуск нумерации: УПД №№ 87-89', severity: 'warning', description: 'Отсутствуют документы с номерами 87, 88, 89 в серии УПД', category: 'gaps', timestamp: new Date(Date.now() - 7200000).toISOString() },
  { id: 'f3', title: 'Расхождение суммы: Акт №56 vs Счёт-фактура', severity: 'warning', description: 'Сумма акта 125 400 ₽ не совпадает со счётом-фактурой 125 040 ₽', category: 'amounts', timestamp: new Date(Date.now() - 14400000).toISOString() },
  { id: 'f4', title: 'ИНН контрагента не найден в ЕГРЮЛ', severity: 'info', description: 'ООО «Ромашка» — ИНН 7701234567 не найден в открытых реестрах', category: 'quality', timestamp: new Date(Date.now() - 28800000).toISOString() },
  { id: 'f5', title: 'Просроченный документ: Договор №12/2024', severity: 'critical', description: 'Срок действия договора истёк 31.12.2025', category: 'expired', timestamp: new Date(Date.now() - 43200000).toISOString() },
]

const DEMO_DASHBOARD: AuditDashboard = {
  findings: { critical: 2, warning: 5, info: 8, resolved: 14 },
  instances: { active: 1, total: 2 },
  recentFindings: DEMO_FINDINGS,
}

// ---- Public API ----

/** Получить дашборд аудитора */
export async function getDashboard(companyId?: string): Promise<AuditDashboard> {
  if (isApiEnabled()) {
    return get<AuditDashboard>('/api/auditor/dashboard', companyId ? { company_id: companyId } : undefined)
  }
  return DEMO_DASHBOARD
}

/** Получить список инстансов */
export async function getInstances(): Promise<AuditorInstance[]> {
  if (isApiEnabled()) {
    return get<AuditorInstance[]>('/api/auditor/instances')
  }
  return DEMO_INSTANCES
}

/** Тип callback для стриминга */
export type StreamCallback = (chunk: string, done: boolean) => void

/**
 * Стрим AI-ответа (SSE или имитация).
 * Возвращает AbortController для отмены.
 */
export function streamAudit(
  prompt: string,
  instanceId: string,
  model: AIModel,
  onChunk: StreamCallback,
  context?: string,
): AbortController {
  const controller = new AbortController()

  if (isApiEnabled()) {
    // SSE стрим от бэкенда
    fetch('/api/auditor/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, instance_id: instanceId, model, context }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok || !res.body) {
          onChunk(`Ошибка: ${res.status} ${res.statusText}`, true)
          return
        }
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) { onChunk('', true); break }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6)
              if (data === '[DONE]') { onChunk('', true); return }
              onChunk(data, false)
            }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          onChunk(`Ошибка соединения: ${err.message}`, true)
        }
      })
  } else {
    // Demo-режим: имитация стриминга
    simulateStream(prompt, onChunk, controller.signal)
  }

  return controller
}

// ---- Demo streaming ----

function simulateStream(prompt: string, onChunk: StreamCallback, signal: AbortSignal) {
  const responses: Record<string, string> = {
    'audit-full': '## Результаты полного аудита\n\n### Критические находки (2)\n- **Дубликат:** Счёт №142 от 15.01.2026 — дублирует Счёт №142 от 14.01.2026\n- **Просрочен:** Договор №12/2024 — истёк 31.12.2025\n\n### Предупреждения (5)\n- Пропуск нумерации УПД №87-89\n- Расхождение суммы в Акте №56\n- 3 документа без подписи контрагента\n\n### Информация (8)\n- 4 контрагента без проверки по ЕГРЮЛ\n- 2 документа с низкой уверенностью OCR\n- 2 записи без привязки к договору\n\n✅ Проверено: 1 247 документов за 3.2 сек.',
    'default': `Анализирую запрос...\n\nОбрабатываю данные по вашему запросу. Промежуточные результаты:\n\n- Документов проверено: 1 247\n- Контрагентов: 48\n- Период: 01.2025 — 02.2026\n\nДля детального анализа подключите инстанс ClearLedger к API.`,
  }

  const cmdId = Object.keys(responses).find((k) => prompt.includes(k))
  const text = responses[cmdId ?? 'default'] ?? responses['default']

  let idx = 0
  const interval = setInterval(() => {
    if (signal.aborted) { clearInterval(interval); return }
    if (idx < text.length) {
      const chunk = text.slice(idx, idx + 3 + Math.floor(Math.random() * 5))
      idx += chunk.length
      onChunk(chunk, false)
    } else {
      clearInterval(interval)
      onChunk('', true)
    }
  }, 30)
}
