/**
 * Общие мелочи экранов «Оборудования»: выгрузка в Excel, листание, сообщение о
 * сбое загрузки. Сбой обязан выглядеть сбоем: пустой список при ошибке сервера
 * читается как «данных нет», и человек уходит с неверным ответом.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ChevronLeft, ChevronRight, Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ApiError } from '@/services/apiClient'
import { getAccountingMeta } from '@/services/equipmentService'
import { exportEquipmentXlsx, type ExportSheet } from './equipmentDocPrint'

/** Счёт и статья затрат расхода со склада: куда ушло — дебет проводки в 1С
 *  («Требование-накладная», «Списание товаров»). Пустой счёт — по умолчанию сервера. */
export function CostAccountFields({ op, value, onChange }: {
  op: 'issue' | 'write_off'
  value: { costAccount: string; costItem: string }
  onChange: (v: { costAccount: string; costItem: string }) => void
}) {
  const meta = useQuery({ queryKey: ['equipment', 'accounting-meta'], queryFn: getAccountingMeta, staleTime: Infinity }).data
  const def = meta?.defaultCostAccount[op] ?? ''
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-xs">{op === 'issue' ? 'Счёт затрат' : 'Счёт списания'}
        <select aria-label="Счёт затрат" className="h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm"
          value={value.costAccount || def} onChange={(e) => onChange({ ...value, costAccount: e.target.value })}>
          {/* Ключи «23», «94» браузер ставит перед «20.01»: порядок плана счетов — сортировкой. */}
          {Object.entries(meta?.costAccounts ?? (def ? { [def]: def } : {}))
            .sort(([a], [b]) => a.localeCompare(b, 'ru', { numeric: true }))
            .map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select></label>
      <label className="text-xs">Статья затрат
        <input aria-label="Статья затрат" className="h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm"
          value={value.costItem} maxLength={150} onChange={(e) => onChange({ ...value, costItem: e.target.value })}
          placeholder={op === 'issue' ? 'ремонт и обслуживание ЭЗС' : 'порча, недостача, моральный износ'} /></label>
    </div>
  )
}

/** Выгружает весь отбор экрана, а не загруженную страницу: строки собирает `load`. */
export function ExportXlsxButton({ title, load }: { title: string; load: () => Promise<ExportSheet[]> }) {
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      const sheets = (await load()).filter((s) => s.rows.length > 0)
      if (!sheets.length) toast.info('Выгружать нечего: по текущему отбору строк нет')
      else await exportEquipmentXlsx(title, sheets)
    } catch (e) {
      toast.error('Выгрузка не удалась', { description: e instanceof Error ? e.message : String(e) })
    } finally { setBusy(false) }
  }
  return (
    <Button variant="outline" size="sm" className="h-8" disabled={busy} onClick={() => void go()} data-export-ignore>
      {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Download className="h-3.5 w-3.5 mr-1" />}
      Excel
    </Button>
  )
}

export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-center gap-2" data-export-ignore>
      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" aria-label="Предыдущая страница"
        disabled={page <= 1} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="h-3.5 w-3.5" />
      </Button>
      <span className="text-xs text-muted-foreground tabular-nums">страница {page} из {pages}</span>
      <Button variant="outline" size="sm" className="h-7 px-2 text-xs" aria-label="Следующая страница"
        disabled={page >= pages} onClick={() => onPage(page + 1)}>
        <ChevronRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

export function LoadError({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  const text = error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error)
  return (
    <Card>
      <CardContent role="alert" className="flex flex-wrap items-center justify-center gap-3 py-8 text-sm text-muted-foreground">
        <span>Не удалось загрузить {what}: {text}</span>
        <Button variant="outline" size="sm" onClick={onRetry}>Повторить</Button>
      </CardContent>
    </Card>
  )
}
