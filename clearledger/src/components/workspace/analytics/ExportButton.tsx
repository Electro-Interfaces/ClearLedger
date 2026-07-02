/**
 * Кнопка экспорта пункта аналитики в Excel/PDF. Читает DOM элемента getEl():
 * KPI-карточки (data-kpi), таблицы (<table>), графики (recharts/heatmap).
 */

import { useState } from 'react'
import { Download, FileSpreadsheet, FileText, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { exportChargeExcel, exportChargePdf } from '@/services/chargeExport'

export function ExportButton({ title, subtitle, getEl }: {
  title: string
  subtitle?: string
  getEl: () => HTMLElement | null
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<'xlsx' | 'pdf' | null>(null)

  const run = async (kind: 'xlsx' | 'pdf') => {
    const el = getEl()
    if (!el) return
    setBusy(kind)
    try {
      if (kind === 'xlsx') await exportChargeExcel(el, title, subtitle)
      else await exportChargePdf(el, title)
      setOpen(false)
    } catch (e) {
      console.error('[charge-export]', e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs px-2 gap-1 shrink-0" title="Экспорт в Excel / PDF">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          Экспорт
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52 p-1">
        <button
          className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs hover:bg-accent/50 disabled:opacity-50"
          onClick={() => run('xlsx')} disabled={!!busy}
        >
          <FileSpreadsheet className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
          <div className="text-left leading-tight">
            <div className="font-medium">Excel</div>
            <div className="text-[10px] text-muted-foreground">KPI · таблицы · графики</div>
          </div>
        </button>
        <button
          className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs hover:bg-accent/50 disabled:opacity-50"
          onClick={() => run('pdf')} disabled={!!busy}
        >
          <FileText className="h-4 w-4 text-red-600 dark:text-red-400 shrink-0" />
          <div className="text-left leading-tight">
            <div className="font-medium">PDF</div>
            <div className="text-[10px] text-muted-foreground">снимок пункта</div>
          </div>
        </button>
      </PopoverContent>
    </Popover>
  )
}
