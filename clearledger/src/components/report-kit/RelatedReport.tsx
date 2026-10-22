import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { showCell, type Cell } from './format'

/**
 * Отчёт-расшифровка значения строки — ещё одно окно поверх карточки строки.
 * Закрыл — остался на той же строке: переходов на другие экраны из карточки
 * нет (МАГ, 15.10.2026: «открываются ещё в одном окне сверху, чтобы я мог его
 * закрыть и остаться там, где был»).
 */
export function RelatedReport({ open, title, subtitle, head, rows, loading, error, note, footer, onClose, children }: {
  open: boolean
  title: string
  subtitle?: string
  head: string[]
  rows: Cell[][]
  loading?: boolean
  error?: boolean
  note?: string
  footer?: ReactNode
  onClose: () => void
  children?: ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-4rem)] max-w-[1200px] flex-col gap-0 p-0 sm:max-w-[1200px]">
        <DialogHeader className="border-b border-border/60 px-6 py-4">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {subtitle}{subtitle && !loading && ' · '}{!loading && !error && `строк: ${rows.length}`}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
          {loading ? (
            <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
          ) : error ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Не удалось получить данные</p>
          ) : rows.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">За это окно записей нет</p>
          ) : (
            children ?? <table className="w-full text-sm">
              <thead className="sticky top-0 bg-background text-xs text-muted-foreground">
                <tr>
                  {head.map((h) => <th key={h} className="whitespace-nowrap border-b border-border/60 px-3 py-2 text-left font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-accent/20">
                    {r.map((v, c) => (
                      <td key={c} className={`px-3 py-1.5 ${typeof v === 'number' ? 'text-right tabular-nums' : ''}`}>
                        {v === '' ? '—' : showCell(v, head[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {note && !loading && <p className="mt-3 text-xs text-muted-foreground">{note}</p>}
          {footer && !loading && <div className="mt-3">{footer}</div>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
