/**
 * Выгрузка отчёта или реестра «Трека»: Excel и PDF.
 *
 * Правило пространства, а не изобретение этого экрана: каждая аналитика обязана
 * уметь «дать таблицу». Совещание идёт по Excel, и без выгрузки цифры
 * переписывают руками в свой файл — назавтра он расходится с системой, и спорят
 * уже не о деле, а о том, чьи числа правильные.
 *
 * PDF делает печать браузера («Сохранить как PDF» в диалоге печати), а не
 * генератор на сервере: печать даёт правильную кириллицу без шрифтовых пакетов
 * в образе. Печатные стили прячут меню, рельсы и полосу контура — на лист
 * уходит рабочая область (`index.css`, `@media print`).
 *
 * Сама кнопка на лист не попадает: увидев её в распечатке, человек решает, что
 * распечаталось не то.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { Download, Loader2, Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { downloadFile } from '@/services/apiClient'

export function TrackExport({ href, fileName, hint }: {
  /** Адрес выгрузки вместе с отбором — тем же, каким посчитан экран. */
  href: string
  fileName: string
  hint?: string
}) {
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      await downloadFile(href, fileName)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась')
    } finally { setBusy(false) }
  }
  return (
    <div className="no-print inline-flex items-center gap-1">
      <Button variant="outline" size="sm" className="h-8" disabled={busy} onClick={go}
        title={hint ?? 'Выгрузить в Excel'}>
        {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          : <Download className="mr-1 h-3.5 w-3.5" />}
        Excel
      </Button>
      <Button variant="outline" size="sm" className="h-8"
        title="Печать или сохранение в PDF" onClick={() => window.print()}>
        <Printer className="mr-1 h-3.5 w-3.5" />PDF
      </Button>
    </div>
  )
}
