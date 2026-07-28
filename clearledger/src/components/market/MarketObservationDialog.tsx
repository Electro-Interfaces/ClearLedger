/**
 * Записать наблюдение по точке рынка (принцип 2 docs/MARKET.md).
 *
 * Наблюдение — факт с датой, автором и каналом. Цена без этих трёх вещей выглядит
 * достоверной, а решение по ней ошибочно, поэтому дата обязательна, а автор и канал
 * проставляются сами: кто записал — тот и наблюдал.
 *
 * Приведение к ₽/кВтч считается здесь же: сравнивать «за сессию» с «за кВтч» нельзя,
 * а заставлять менеджера считать в уме — верный способ получить кривые данные.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { createMarketObservation, type MarketSite } from '@/services/marketService'

const TODAY = () => new Date().toISOString().slice(0, 10)

export function MarketObservationDialog({ sites, siteId, trigger }: {
  sites: MarketSite[]
  /** Точка задана заранее (открыли из её карточки). */
  siteId?: string
  trigger: React.ReactNode
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    siteId: siteId ?? '', kind: 'price', observedOn: TODAY(),
    price: '', unit: 'kwh', basis: '', connector: '', power: '',
    channel: 'service_visit', sourceRef: '', note: '',
  })

  const save = useMutation({
    mutationFn: () => {
      const price = form.price ? Number(form.price.replace(',', '.')) : null
      const power = form.power ? Number(form.power.replace(',', '.')) : null
      return createMarketObservation(companyId, {
        site_id: form.siteId,
        kind: form.kind,
        observed_on: form.observedOn,
        price_value: price,
        price_unit: form.unit,
        // Приведение: «за кВтч» уже сравнимо, остальное — только с оговоркой в базе.
        price_per_kwh: form.unit === 'kwh' ? price : null,
        basis: form.basis.trim() || null,
        connector_type: form.connector.trim() || null,
        power_kw: power,
        channel: form.channel,
        source_ref: form.sourceRef.trim() || null,
        note: form.note.trim() || null,
      })
    },
    onSuccess: () => {
      toast.success('Наблюдение записано')
      qc.invalidateQueries({ queryKey: ['market-observations'] })
      qc.invalidateQueries({ queryKey: ['market-sites'] })
      setOpen(false)
      setForm((f) => ({ ...f, price: '', basis: '', note: '', sourceRef: '' }))
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось записать'),
  })

  const isPrice = form.kind === 'price'

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Наблюдение по точке рынка</DialogTitle></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label className="text-xs">Точка</Label>
            <Select value={form.siteId} onValueChange={(v) => setForm({ ...form, siteId: v })}>
              <SelectTrigger><SelectValue placeholder="Выберите точку" /></SelectTrigger>
              <SelectContent>
                {sites.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}{s.city ? ` · ${s.city}` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Что наблюдали</Label>
            <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="price">Цена</SelectItem>
                <SelectItem value="availability">Доступность</SelectItem>
                <SelectItem value="equipment">Оборудование</SelectItem>
                <SelectItem value="opened">Открылась</SelectItem>
                <SelectItem value="closed">Закрыта</SelectItem>
                <SelectItem value="note">Заметка</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Дата наблюдения</Label>
            <Input type="date" value={form.observedOn}
              onChange={(e) => setForm({ ...form, observedOn: e.target.value })} />
          </div>

          {isPrice && (
            <>
              <div>
                <Label className="text-xs">Цена</Label>
                <Input value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })}
                  placeholder="24,50" />
              </div>
              <div>
                <Label className="text-xs">За что</Label>
                <Select value={form.unit} onValueChange={(v) => setForm({ ...form, unit: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="kwh">за кВтч</SelectItem>
                    <SelectItem value="session">за сессию</SelectItem>
                    <SelectItem value="minute">за минуту</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Коннектор</Label>
                <Input value={form.connector}
                  onChange={(e) => setForm({ ...form, connector: e.target.value })}
                  placeholder="CCS2 / GB/T / Type2" />
              </div>
              <div>
                <Label className="text-xs">Мощность, кВт</Label>
                <Input value={form.power} onChange={(e) => setForm({ ...form, power: e.target.value })} />
              </div>
              <div className="sm:col-span-2">
                <Label className="text-xs">База сравнения</Label>
                <Input value={form.basis} onChange={(e) => setForm({ ...form, basis: e.target.value })}
                  placeholder="DC 60+ кВт, будни днём, без абонемента" />
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Без базы «дороже на 12 %» ничего не значит: цена зависит от мощности,
                  времени и программы.
                </p>
              </div>
            </>
          )}

          <div>
            <Label className="text-xs">Канал</Label>
            <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="service_visit">Выезд сервиса</SelectItem>
                <SelectItem value="marketing">Маркетинг</SelectItem>
                <SelectItem value="partner">Партнёр</SelectItem>
                <SelectItem value="manual">Вручную</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Ссылка или снимок</Label>
            <Input value={form.sourceRef}
              onChange={(e) => setForm({ ...form, sourceRef: e.target.value })}
              placeholder="URL страницы или фото" />
          </div>
          <div className="sm:col-span-2">
            <Label className="text-xs">Комментарий</Label>
            <Textarea rows={2} value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button disabled={!form.siteId || save.isPending} onClick={() => save.mutate()}>
            Записать
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
