/**
 * Завести точку рынка вручную (Волна 0 docs/MARKET.md).
 *
 * Ручной ввод — не временная мера до парсера, а постоянный канал: сотрудник заехал,
 * увидел новую станцию конкурента и записал её раньше, чем она появится на любой карте.
 * Поэтому форма короткая: имя, вид, где — остальное дозаполнится наблюдениями.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  createMarketSite, createMarketOperator, listMarketOperators,
  SITE_KIND_LABEL, type MarketSiteKind,
} from '@/services/marketService'

export function MarketSiteDialog({ trigger }: { trigger: React.ReactNode }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    name: '', kind: 'ezs' as MarketSiteKind, operatorId: '', newOperator: '',
    address: '', city: '', lat: '', lon: '', ports: '', maxPowerKw: '', notes: '',
  })

  const operators = useQuery({
    queryKey: ['market-operators', companyId],
    queryFn: () => listMarketOperators(companyId),
    enabled: !!companyId && open,
  })

  const save = useMutation({
    mutationFn: async () => {
      let operatorId: string | null = form.operatorId || null
      // Оператора заводим здесь же: заставлять человека идти в другой экран ради
      // строки «Название конкурента» — верный способ не получить данных вовсе.
      if (!operatorId && form.newOperator.trim()) {
        const op = await createMarketOperator(companyId, {
          name: form.newOperator.trim(), relation: 'competitor',
        })
        operatorId = op.id
      }
      return createMarketSite(companyId, {
        name: form.name.trim(),
        kind: form.kind,
        operator_id: operatorId,
        address: form.address.trim() || null,
        city: form.city.trim() || null,
        latitude: form.lat ? Number(form.lat.replace(',', '.')) : null,
        longitude: form.lon ? Number(form.lon.replace(',', '.')) : null,
        ports: form.ports ? Number(form.ports) : null,
        max_power_kw: form.maxPowerKw ? Number(form.maxPowerKw.replace(',', '.')) : null,
        notes: form.notes.trim() || null,
        source: 'manual',
      })
    },
    onSuccess: (r) => {
      toast.success(r.duplicate ? 'Такая точка уже есть — открыта существующая' : 'Точка рынка добавлена')
      qc.invalidateQueries({ queryKey: ['market-sites'] })
      qc.invalidateQueries({ queryKey: ['market-operators'] })
      setOpen(false)
      setForm({ name: '', kind: 'ezs', operatorId: '', newOperator: '', address: '',
        city: '', lat: '', lon: '', ports: '', maxPowerKw: '', notes: '' })
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сохранить'),
  })

  const isEzs = form.kind === 'ezs'

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>Точка рынка</DialogTitle></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label className="text-xs">Название</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="ЭЗС «Сеть N» на Ленина, 12" />
          </div>
          <div>
            <Label className="text-xs">Вид точки</Label>
            <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v as MarketSiteKind })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(SITE_KIND_LABEL).map(([k, label]) => (
                  <SelectItem key={k} value={k}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Оператор</Label>
            <Select value={form.operatorId || 'new'}
              onValueChange={(v) => setForm({ ...form, operatorId: v === 'new' ? '' : v })}>
              <SelectTrigger><SelectValue placeholder="Новый" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="new">Новый оператор…</SelectItem>
                {(operators.data?.operators ?? []).map((o) => (
                  <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!form.operatorId && (
              <Input className="mt-1.5" value={form.newOperator}
                onChange={(e) => setForm({ ...form, newOperator: e.target.value })}
                placeholder="Название оператора" />
            )}
          </div>
          <div className="sm:col-span-2">
            <Label className="text-xs">Адрес</Label>
            <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs">Город</Label>
            <Input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Широта</Label>
              <Input value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })}
                placeholder="55.7558" />
            </div>
            <div>
              <Label className="text-xs">Долгота</Label>
              <Input value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })}
                placeholder="37.6176" />
            </div>
          </div>
          {isEzs && (
            <>
              <div>
                <Label className="text-xs">Портов</Label>
                <Input value={form.ports} onChange={(e) => setForm({ ...form, ports: e.target.value })} />
              </div>
              <div>
                <Label className="text-xs">Макс. мощность, кВт</Label>
                <Input value={form.maxPowerKw}
                  onChange={(e) => setForm({ ...form, maxPowerKw: e.target.value })} />
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <Label className="text-xs">Заметка</Label>
            <Textarea rows={2} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Что важно помнить об этой точке" />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>Отмена</Button>
          <Button disabled={!form.name.trim() || save.isPending} onClick={() => save.mutate()}>
            Сохранить
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
