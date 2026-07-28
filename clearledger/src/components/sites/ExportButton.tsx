/**
 * Кнопка выгрузки экрана в Excel и печати.
 *
 * Каждая аналитика обязана уметь «дать таблицу»: совещание идёт по Excel, и без
 * выгрузки цифры переписывают руками в свой файл — назавтра он расходится с
 * системой, и спорят уже не о деле, а о том, чьи числа правильные.
 *
 * PDF делаем печатью браузера, а не генерацией на сервере: печать даёт
 * правильную кириллицу без шрифтовых пакетов в образе, а на выходе тот же PDF
 * («Сохранить как PDF» в диалоге печати). Печатные стили прячут меню и рельсы —
 * на лист уходит только рабочая область (см. `index.css`, `@media print`).
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Download, Loader2, Printer } from 'lucide-react'
import { exportXlsx } from '@/services/sitesService'

export function ExportButton({ companyId, report, fileName, label = 'Excel', print = true }: {
  companyId: string
  /** Ключ отчёта: portfolio | funnel | matrix | budget | accounting | tech-connections | equipment. */
  report: string
  fileName?: string
  label?: string
  print?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      await exportXlsx(companyId, report, fileName)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась')
    } finally { setBusy(false) }
  }
  return (
    <div className="inline-flex items-center gap-1">
      <Button variant="outline" size="sm" className="h-8 text-sm" disabled={busy} onClick={go}>
        {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Download className="h-3.5 w-3.5 mr-1" />}
        {label}
      </Button>
      {print && (
        <Button variant="outline" size="sm" className="h-8 text-sm" title="Печать или сохранение в PDF"
          onClick={() => window.print()}>
          <Printer className="h-3.5 w-3.5 mr-1" />PDF
        </Button>
      )}
    </div>
  )
}
