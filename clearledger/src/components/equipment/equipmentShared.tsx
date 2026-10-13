/**
 * Общие мелочи экранов «Оборудования»: выгрузка в Excel, листание, сообщение о
 * сбое загрузки. Сбой обязан выглядеть сбоем: пустой список при ошибке сервера
 * читается как «данных нет», и человек уходит с неверным ответом.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { ChevronLeft, ChevronRight, Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ApiError } from '@/services/apiClient'
import { exportEquipmentXlsx, type ExportSheet } from './equipmentDocPrint'

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
