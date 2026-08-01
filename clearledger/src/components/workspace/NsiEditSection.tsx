/**
 * Правка карточки в мастер-НСИ Ledger — прямо в карточке товара.
 *
 * Всё выше в модалке показывает 1С: это зеркало, и править его бессмысленно —
 * следующая выгрузка затрёт. Здесь начинается собственный справочник Ledger
 * (схема edge): наименование, ставка, штрихкоды, цена станции. Он наполняется
 * снимками со станции и живёт своей жизнью — то, что изменено тут, поедет на
 * кассу, а не обратно в 1С.
 *
 * Показывается только если карточка в мастере есть: пока идёт параллельный
 * период, часть справочника ЦБ в мастер не доехала, и обещать правку того,
 * чего нет, нельзя.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Barcode, Wallet, AlertTriangle } from 'lucide-react'
import {
  getNsiCard, saveNsiCard, setNsiPrice, addNsiBarcode, retireNsiBarcode,
  NSI_VAT_CODES, type NsiCard,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const money = (n: number | null | undefined) => (n == null ? '—' : fmtMoney(n))

/** Ставки, которых в 2026 году быть не должно: это дефект НСИ, а не выбор. */
const STALE_VAT = new Set(['НДС18_118', 'НДС20', 'НДС5'])

function Box({ icon: Icon, title, right, children }: {
  icon: typeof Pencil; title: string; right?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-primary/25 bg-primary/[0.03] p-3.5">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <Icon className="h-4 w-4 text-primary" /> {title}
        </div>
        {right}
      </div>
      {children}
    </div>
  )
}

export function NsiEditSection({ guid, companyId, stationId = 208 }: {
  guid: string; companyId: string; stationId?: number
}) {
  const qc = useQueryClient()
  const key = ['nsi-card', companyId, guid, stationId]
  const { data, isLoading, error } = useQuery<NsiCard>({
    queryKey: key,
    queryFn: () => getNsiCard(guid, stationId),
    retry: false,   // 404 «нет в мастере» — штатный ответ, а не сбой связи
  })

  const [form, setForm] = useState<{ name: string; unit: string; vat_rate: string }>(
    { name: '', unit: '', vat_rate: '' })
  const [price, setPrice] = useState('')
  const [newCode, setNewCode] = useState('')
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)

  useEffect(() => {
    if (!data) return
    setForm({ name: data.item.name, unit: data.item.unit, vat_rate: data.item.vat_rate })
    setPrice(data.prices.find((p) => p.valid_to == null)?.price?.toString() ?? '')
  }, [data])

  const done = (text: string) => {
    setMsg({ text })
    qc.invalidateQueries({ queryKey: key })
  }
  const failed = (e: unknown) => setMsg({ text: e instanceof Error ? e.message : String(e), bad: true })

  const saveCard = useMutation({
    mutationFn: () => saveNsiCard(guid, form),
    onSuccess: () => done('Карточка сохранена.'), onError: failed,
  })
  const savePrice = useMutation({
    mutationFn: () => setNsiPrice(guid, stationId, Number(price.replace(',', '.'))),
    onSuccess: (r) => done(r.note ?? 'Цена сохранена.'), onError: failed,
  })
  const addCode = useMutation({
    mutationFn: () => addNsiBarcode(guid, newCode.trim()),
    onSuccess: (r) => { setNewCode(''); done(r.already ? 'Такой штрихкод уже был.' : 'Штрихкод добавлен.') },
    onError: failed,
  })
  const retire = useMutation({
    mutationFn: (id: number) => retireNsiBarcode(id),
    onSuccess: () => done('Штрихкод переведён в исторические.'), onError: failed,
  })

  if (isLoading) return <div className="text-xs text-muted-foreground px-1">Мастер-НСИ: загрузка…</div>
  if (error || !data) {
    return (
      <div className="rounded-lg border border-border/50 bg-card/40 p-3 text-xs text-muted-foreground">
        Карточки нет в мастер-НСИ Ledger — править нечего. Она появится там, когда
        станция пришлёт её в снимке остатков или кассы.
      </div>
    )
  }

  const it = data.item
  const dirty = form.name !== it.name || form.unit !== it.unit || form.vat_rate !== it.vat_rate
  const current = data.prices.find((p) => p.valid_to == null)
  const priceDirty = price !== (current?.price?.toString() ?? '')
  const active = data.barcodes.filter((b) => b.status === 'active')
  const rejected = data.barcodes.filter((b) => b.status === 'rejected')

  return (
    <div className="space-y-3.5">
      {msg && (
        <div className={`text-xs rounded-md px-2.5 py-1.5 border ${msg.bad
          ? 'border-red-400/50 text-red-300/90 bg-red-500/5'
          : 'border-emerald-400/40 text-emerald-300/80 bg-emerald-500/5'}`}>
          {msg.text}
        </div>
      )}

      <Box icon={Pencil} title="Карточка в мастер-НСИ Ledger"
        right={<span className="text-[10px] text-muted-foreground">изменено {new Date(it.updated_at).toLocaleString('ru-RU')}</span>}>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="col-span-2 block">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">Наименование</span>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="mt-0.5 w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background" />
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">Единица</span>
            <input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}
              className="mt-0.5 w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background" />
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">Ставка НДС</span>
            <select value={form.vat_rate} onChange={(e) => setForm({ ...form, vat_rate: e.target.value })}
              className="mt-0.5 w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background">
              {NSI_VAT_CODES.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
        </div>

        {STALE_VAT.has(it.vat_rate) && (
          <div className="mt-2.5 flex items-start gap-1.5 text-[11px] text-amber-300/85">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-px" />
            Ставка {it.vat_rate} устарела — товар уедет в кассу и бухгалтерию с неверным налогом.
          </div>
        )}

        <div className="mt-3 flex items-center gap-2">
          <button disabled={!dirty || saveCard.isPending} onClick={() => saveCard.mutate()}
            className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-40">
            {saveCard.isPending ? 'Сохраняю…' : 'Сохранить карточку'}
          </button>
          {dirty && <span className="text-[11px] text-muted-foreground">есть несохранённые правки</span>}
        </div>
      </Box>

      <div className="grid gap-3.5 md:grid-cols-2">
        <Box icon={Wallet} title={`Цена на станции ${data.station_id}`}>
          <div className="flex items-end gap-2">
            <label className="flex-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">Розничная цена</span>
              <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal"
                className="mt-0.5 w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background tabular-nums" />
            </label>
            <button disabled={!priceDirty || savePrice.isPending} onClick={() => savePrice.mutate()}
              className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-40">
              Установить
            </button>
          </div>
          {data.prices.length > 0 && (
            <table className="w-full text-xs mt-2.5">
              <tbody>
                {data.prices.slice(0, 6).map((p) => (
                  <tr key={p.id} className="border-b border-border/20 last:border-0">
                    <td className="py-1 pr-2 whitespace-nowrap text-muted-foreground">
                      {new Date(p.valid_from).toLocaleDateString('ru-RU')}
                      {p.valid_to == null && <span className="ml-1 text-emerald-300/80">действует</span>}
                    </td>
                    <td className="py-1 text-right tabular-nums">{money(p.price)}</td>
                    <td className="py-1 pl-2 text-right text-[10px] text-muted-foreground truncate max-w-[9rem]">{p.author ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Box>

        <Box icon={Barcode} title="Штрихкоды"
          right={<span className="text-[11px] text-muted-foreground">{active.length} активных</span>}>
          <div className="space-y-1">
            {active.map((b) => (
              <div key={b.id} className="flex items-center gap-2 text-xs">
                <span className="font-mono tabular-nums">{b.code}</span>
                {b.ns_code != null && <span className="text-[10px] text-muted-foreground">код кассы {b.ns_code}</span>}
                {b.qty != null && <span className="text-[10px] text-muted-foreground">остаток {b.qty}</span>}
                <button onClick={() => retire.mutate(b.id)}
                  className="ml-auto text-[10px] text-muted-foreground hover:text-red-400/90">снять</button>
              </div>
            ))}
            {active.length === 0 && <div className="text-xs text-muted-foreground">Активных штрихкодов нет</div>}
          </div>

          <div className="flex gap-2 mt-2.5">
            <input value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="новый штрихкод"
              className="flex-1 text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background font-mono" />
            <button disabled={!newCode.trim() || addCode.isPending} onClick={() => addCode.mutate()}
              className="text-xs px-3 py-1.5 rounded-md border border-border/50 disabled:opacity-40">Добавить</button>
          </div>

          {rejected.length > 0 && (
            <div className="mt-2.5 text-[11px] text-amber-300/85">
              <div className="flex items-center gap-1.5 mb-1">
                <AlertTriangle className="h-3.5 w-3.5" /> Коллизии: код занят другой карточкой
              </div>
              {rejected.map((b) => (
                <div key={b.id} className="font-mono text-[10px] text-muted-foreground">{b.code}</div>
              ))}
            </div>
          )}
        </Box>
      </div>
    </div>
  )
}
