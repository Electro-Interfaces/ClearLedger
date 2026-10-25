import { useState } from 'react'
import { toast } from 'sonner'
import { Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { exportChargeExcel, exportChargePdf } from '@/services/chargeExport'
import { exportRows } from '@/components/workspace/analytics/exportRows'

export function MarketExportButton<T>({ title, total, loaded, columns, values, getAll, subtitle = '' }: {
  title: string; total: number; loaded: T[]; columns: string[]
  values: (row: T) => (string | number | null | undefined)[]
  getAll: () => Promise<T[]>; subtitle?: string
}) {
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  async function run(all: boolean, kind: 'xlsx' | 'pdf') {
    setBusy(true)
    try {
      const rows = all ? await getAll() : loaded
      const root = document.createElement('div'), table = document.createElement('table')
      Object.entries(exportRows(title, columns, rows.map(values))).forEach(([k, v]) => table.setAttribute(k, v))
      root.append(table)
      const caption = `${all ? 'Весь отбор' : 'Загруженные строки'} · ${rows.length} записей${subtitle ? ` · ${subtitle}` : ''}`
      if (kind === 'xlsx') await exportChargeExcel(root, title, caption)
      else await exportChargePdf(root, title, caption)
      setOpen(false)
    } catch (error) {
      toast.error('Выгрузка не завершена', { description: error instanceof Error ? error.message : 'Повторите попытку' })
    } finally { setBusy(false) }
  }
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild><Button variant="outline" size="sm" disabled={busy || !total}>
      {busy ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />} {busy ? 'Готовим файл…' : 'Экспорт'}
    </Button></PopoverTrigger>
    <PopoverContent className="w-72 p-2" align="end">
      <p className="px-2 py-1 text-sm font-medium">В отборе {total.toLocaleString('ru-RU')} записей</p>
      {[true, false].map(all => <div key={String(all)} className="border-t py-2">
        <p className="px-2 text-xs text-muted-foreground">{all ? 'Весь отбор' : `Загруженные строки: ${loaded.length}`}</p>
        <div className="flex gap-2 p-1">{(['xlsx', 'pdf'] as const).map(kind => <Button key={kind} variant="outline" size="sm" disabled={busy}
          aria-label={`${all ? 'Весь отбор' : 'Загруженные строки'}: ${kind === 'xlsx' ? 'Excel' : 'PDF'}`}
          onClick={() => void run(all, kind)}>{kind === 'xlsx' ? 'Excel' : 'PDF'}</Button>)}</div>
      </div>)}
    </PopoverContent>
  </Popover>
}
