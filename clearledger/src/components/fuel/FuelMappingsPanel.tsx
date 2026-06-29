/**
 * Панель маппингов топливных каналов STS → 1С (компания-scoped).
 * Каналы оплаты · Маппинг видов оплат (образец→канал) · Виды топлива.
 * Эталон — расширение TradeLedger.cfe. Источник истины — приложение.
 */
import { useState, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getFuelMappings, createPaymentMapping, deletePaymentMapping, updateFuelMapping,
  type FuelMappingsAll, type FuelMapping,
} from '@/services/fuel/fuelMappingService'
import { isApiEnabled } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { NomenclaturePicker } from '@/components/fuel/NomenclaturePicker'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Trash2, Plus, Loader2, Fuel, CreditCard, ArrowRightLeft, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

/** Сворачиваемая секция справочника (по умолчанию свёрнута). */
function Section({ icon, title, desc, count, children }: {
  icon: ReactNode; title: string; desc?: string; count?: number; children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <Card className="py-0 gap-0 overflow-hidden">
      <CardHeader className="cursor-pointer select-none py-2.5 px-4" onClick={() => setOpen((o) => !o)}>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform shrink-0', open ? '' : '-rotate-90')} />
          {icon}<span>{title}</span>
          {count != null && <span className="ml-auto text-xs font-normal text-muted-foreground tabular-nums">{count}</span>}
        </CardTitle>
        {open && desc && <CardDescription className="ml-6 text-xs mt-1">{desc}</CardDescription>}
      </CardHeader>
      {open && <CardContent className="px-4 pb-4 pt-0 space-y-3">{children}</CardContent>}
    </Card>
  )
}

const CHANNEL_BADGE: Record<string, string> = {
  retail_cash: 'border-emerald-400/50 text-emerald-300/80',
  retail_card: 'border-blue-400/50 text-blue-300/80',
  cards: 'border-amber-400/50 text-amber-300/80',
  online: 'border-violet-400/50 text-violet-300/80',
  voucher: 'border-zinc-500 text-zinc-300',
  ledger: 'border-zinc-500 text-zinc-300',
  writeoff_fuel: 'border-red-400/50 text-red-300/70',
  '': 'border-zinc-700 text-zinc-500',
}

export function FuelMappingsPanel() {
  const qc = useQueryClient()
  const [pattern, setPattern] = useState('')
  const [channel, setChannel] = useState('cards')

  const { data, isLoading } = useQuery<FuelMappingsAll>({
    queryKey: ['fuel-mappings'],
    queryFn: getFuelMappings,
    enabled: isApiEnabled(),
  })

  const createMut = useMutation({
    mutationFn: () => createPaymentMapping({
      pattern,
      channel_code: channel === '__ignore__' ? '' : channel,
    }),
    onSuccess: () => {
      toast.success('Образец оплаты добавлен')
      setPattern('')
      qc.invalidateQueries({ queryKey: ['fuel-mappings'] })
    },
    onError: (e: Error) => toast.error('Ошибка', { description: e.message }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePaymentMapping(id),
    onSuccess: () => {
      toast.success('Образец удалён')
      qc.invalidateQueries({ queryKey: ['fuel-mappings'] })
    },
    onError: (e: Error) => toast.error('Ошибка', { description: e.message }),
  })

  // Сохранение вида топлива (привязка номенклатуры 1С / плотность). PUT требует
  // полный объект (FuelMappingIn) — мержим существующий + правку. На бэке при
  // сохранении reconcile-fuel выводится из fuel_mappings (единый источник).
  const { companyId } = useCompany()
  const saveFuelMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<FuelMapping> }) => updateFuelMapping(id, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['fuel-mappings'] }); toast.success('Сохранено') },
    onError: (e: Error) => toast.error('Ошибка', { description: e.message }),
  })
  function saveFuel(f: FuelMapping, patch: Partial<FuelMapping>) {
    const { id: _id, ...rest } = f
    void _id
    saveFuelMut.mutate({ id: f.id, body: { ...rest, ...patch } })
  }

  if (!isApiEnabled()) {
    return <p className="text-sm text-muted-foreground">Маппинги доступны при подключённом API (backend).</p>
  }
  if (isLoading) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  if (!data) return null

  const channelCodes = data.payment_channels.map((c) => c.code)

  return (
    <div className="space-y-2">
      {/* ── Каналы оплаты ── */}
      <Section icon={<CreditCard className="h-4 w-4" />} title="Каналы оплаты"
        count={data.payment_channels.length}
        desc="Канал определяет документ 1С и склад. «Требует перемещения» → создаётся Перемещение 41.02→41.01 на виртуальный склад канала.">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Код</TableHead>
                <TableHead>Наименование</TableHead>
                <TableHead>Склад БП</TableHead>
                <TableHead>Перемещение</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.payment_channels.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <Badge variant="outline" className={CHANNEL_BADGE[c.code] ?? ''}>{c.code}</Badge>
                  </TableCell>
                  <TableCell>{c.name}</TableCell>
                  <TableCell className="text-muted-foreground">{c.warehouse_name ?? '—'}</TableCell>
                  <TableCell>
                    {c.requires_transfer
                      ? <Badge variant="outline" className="border-amber-400/50 text-amber-300/80">да</Badge>
                      : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
      </Section>

      {/* ── Маппинг видов оплат ── */}
      <Section icon={<ArrowRightLeft className="h-4 w-4" />} title="Маппинг видов оплат STS"
        count={data.payment_mappings.length}
        desc="Образец имени из STS (подстрока, регистронезависимо) → канал оплаты. Первое совпадение по порядку. Пустой канал = игнор (купоны/прокачка).">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[180px]">
              <Input placeholder="образец имени (напр. сбербанк)" value={pattern}
                     onChange={(e) => setPattern(e.target.value.toLowerCase())} />
            </div>
            <Select value={channel} onValueChange={setChannel}>
              <SelectTrigger className="w-[180px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {channelCodes.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                <SelectItem value="__ignore__">— игнор —</SelectItem>
              </SelectContent>
            </Select>
            <Button
              onClick={() => createMut.mutate()}
              disabled={!pattern.trim() || createMut.isPending}
            >
              {createMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Добавить
            </Button>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Образец имени</TableHead>
                <TableHead>Канал</TableHead>
                <TableHead>Склад (переопр.)</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.payment_mappings.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-mono text-sm">{m.pattern}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={CHANNEL_BADGE[m.channel_code] ?? ''}>
                      {m.channel_code || 'игнор'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{m.warehouse_override ?? '—'}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon"
                            onClick={() => deleteMut.mutate(m.id)} disabled={deleteMut.isPending}>
                      <Trash2 className="h-4 w-4 text-muted-foreground hover:text-red-400" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
      </Section>

      {/* ── Виды топлива ── */}
      <Section icon={<Fuel className="h-4 w-4" />} title="Виды топлива"
        count={data.fuel_mappings.length}
        desc="Единый справочник видов топлива: код STS → номенклатура 1С по GUID (тонны для 41.01, литры для 41.02) + плотность. Выбор из каталога 1С — наименование согласовано с бухгалтерией; reconcile выводится отсюда.">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Код</TableHead>
                <TableHead>Топливо</TableHead>
                <TableHead>Номенклатура (т)</TableHead>
                <TableHead>Номенклатура (л)</TableHead>
                <TableHead className="text-right">Плотность</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.fuel_mappings.map((f) => (
                <TableRow key={f.id}>
                  <TableCell><Badge variant="outline" className="border-zinc-600 text-zinc-400">{f.service_code}</Badge></TableCell>
                  <TableCell>{f.fuel_name}</TableCell>
                  <TableCell className="min-w-[200px]">
                    <NomenclaturePicker companyId={companyId} valueRef={f.nomenclature_t_ref} valueName={f.nomenclature_tonnes}
                      placeholder="Номенклатура (т)…"
                      onPick={(ref, name) => saveFuel(f, { nomenclature_t_ref: ref, nomenclature_tonnes: name })} />
                  </TableCell>
                  <TableCell className="min-w-[200px]">
                    <NomenclaturePicker companyId={companyId} valueRef={f.nomenclature_l_ref} valueName={f.nomenclature_liters}
                      placeholder="Номенклатура (л)…"
                      onPick={(ref, name) => saveFuel(f, { nomenclature_l_ref: ref, nomenclature_liters: name })} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Input type="number" step="0.0001" defaultValue={f.density ?? ''}
                      className="h-7 w-20 text-xs text-right ml-auto font-mono"
                      onBlur={(e) => {
                        const v = e.target.value === '' ? null : parseFloat(e.target.value)
                        if (v !== (f.density ?? null)) saveFuel(f, { density: v })
                      }} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
      </Section>
    </div>
  )
}
