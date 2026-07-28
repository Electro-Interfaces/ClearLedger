/**
 * Импорт точек рынка списком — вставкой из таблицы (Волна 0 docs/MARKET.md).
 *
 * Ручной ввод по одной останавливает работу на десятой строке: у менеджера выгрузка
 * или выписка из чужой карты, а не одна станция. Формат намеренно простой — то, что
 * получается копированием из Excel, без «загрузите файл в нашем формате».
 *
 * Цена в строке становится наблюдением с сегодняшней датой и каналом «импорт»:
 * факта без происхождения в рынке не бывает (принцип 2).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { bulkMarketSites, SITE_KIND_LABEL, type MarketSiteKind } from '@/services/marketService'

/** Колонки строки: имя ; оператор ; город ; широта ; долгота ; порты ; цена ₽/кВтч */
function parseRows(text: string, kind: string) {
  const out: Record<string, unknown>[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    // Разделитель — табуляция (вставка из Excel) или точка с запятой.
    const cells = line.includes('\t') ? line.split('\t') : line.split(';')
    const [name, operator, city, lat, lon, ports, price] = cells.map((c) => (c ?? '').trim())
    if (!name) continue
    const num = (v: string) => {
      const n = Number((v || '').replace(',', '.').replace(/\s/g, ''))
      return Number.isFinite(n) && v ? n : null
    }
    out.push({
      name, kind,
      operator: operator || null,
      city: city || null,
      latitude: num(lat), longitude: num(lon),
      ports: ports ? Math.round(Number(ports)) || null : null,
      price_per_kwh: num(price),
    })
  }
  return out
}

export function MarketImportDialog({ trigger }: { trigger: React.ReactNode }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<MarketSiteKind>('ezs')
  const [text, setText] = useState('')

  const rows = useMemo(() => parseRows(text, kind), [text, kind])
  const withGeo = rows.filter((r) => r.latitude != null && r.longitude != null).length
  const withPrice = rows.filter((r) => r.price_per_kwh != null).length

  const save = useMutation({
    mutationFn: () => bulkMarketSites(companyId, rows),
    onSuccess: (r) => {
      toast.success(`Заведено ${r.created}, обновлено ${r.updated}, наблюдений ${r.observations}`)
      qc.invalidateQueries({ queryKey: ['market-sites'] })
      qc.invalidateQueries({ queryKey: ['market-position'] })
      qc.invalidateQueries({ queryKey: ['market-operators'] })
      setOpen(false)
      setText('')
    },
    onError: (e: Error) => toast.error(e.message || 'Импорт не прошёл'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>Импорт точек рынка списком</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Label className="text-xs">Вид точек</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as MarketSiteKind)}>
              <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(SITE_KIND_LABEL).map(([k, label]) => (
                  <SelectItem key={k} value={k}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">
              Строки: название ; оператор ; город ; широта ; долгота ; портов ; цена ₽/кВтч
            </Label>
            <Textarea rows={10} value={text} onChange={(e) => setText(e.target.value)}
              className="font-mono text-[11px]"
              placeholder={'ЭЗС на Ленина 12;Сеть N;Белгород;50.5977;36.5858;2;24,5\nЭЗС у ТЦ «Восток»;Сеть M;Белгород;50.6110;36.6000;4;22'} />
            <p className="mt-1 text-[11px] text-muted-foreground">
              Можно вставить прямо из таблицы (колонки разделены табуляцией). Заполнены
              только первые колонки — остальное дозаполните наблюдениями.
            </p>
          </div>
          {rows.length > 0 && (
            <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
              Разобрано строк: <b className="text-foreground">{rows.length}</b> ·
              с координатами: {withGeo} · с ценой: {withPrice}
              {withGeo < rows.length && (
                <span className="ml-1 text-amber-500">
                  — точки без координат не попадут на карту и в окружение объектов
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button disabled={!rows.length || save.isPending} onClick={() => save.mutate()}>
            Загрузить {rows.length ? `(${rows.length})` : ''}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
