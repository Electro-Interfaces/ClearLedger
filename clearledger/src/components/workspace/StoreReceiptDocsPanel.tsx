/**
 * «Магазин» → Склад → Приёмка.
 *
 * Первый документ, который Ledger порождает сам, а не читает из 1С. Точек ввода
 * две и обе законны: здесь, в центре, товаровед заводит накладную поставщика
 * (дальше — из ЭДО), а на станции ту же приёмку делают физически, со сканером.
 * Документ при этом один — иначе накладная и фактическое поступление разъедутся.
 *
 * Логика повторяет ордерную схему 1С:Розница, к которой товаровед привык:
 * «к поступлению» — товар заявлен, но на складе его ещё нет; «принят» — посчитан
 * и оприходован. Пока документ не принят, остатки не двигаются.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackagePlus, Plus, Trash2, Check, AlertTriangle } from 'lucide-react'
import {
  getStoreReceipts, createStoreReceipt, updateStoreReceipt, setStoreReceiptStatus,
  type StoreReceipt, type StoreReceiptLine,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

const STATUS_LABEL: Record<string, string> = {
  draft: 'черновик',
  expected: 'к поступлению',
  accepted: 'принят',
}
const STATUS_STYLE: Record<string, string> = {
  draft: 'border-zinc-600 text-zinc-400',
  expected: 'border-amber-400/50 text-amber-300/80',
  accepted: 'border-emerald-400/50 text-emerald-300/80',
}

function Badge({ status }: { status: string }) {
  return (
    <span className={`rounded border px-2 py-0.5 text-xs ${STATUS_STYLE[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function money(v: number) {
  return v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Пустая строка документа: заявленное и фактическое ведутся раздельно. */
const emptyLine = (): StoreReceiptLine => ({
  nomenclature_ref: null, name: '', barcode: null,
  qty_expected: 0, qty_fact: 0, price: 0, vat_rate: null, amount: 0,
})

export function StoreReceiptDocsPanel({ stations }: { stations?: string[] }) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const stationId = stations?.length === 1 ? Number(stations[0]) : undefined
  const [openId, setOpenId] = useState<string | null>(null)
  const [onlyDiff, setOnlyDiff] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-receipts', company.id, stationId],
    queryFn: () => getStoreReceipts({ stationId }),
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['store-receipts'] })
  const create = useMutation({
    mutationFn: () => createStoreReceipt({
      station_id: stationId ?? 208,
      lines: [],
    }),
    onSuccess: (r) => { invalidate(); setOpenId(r.id) },
  })

  const open = useMemo(
    () => data?.receipts.find((r) => r.id === openId) ?? null,
    [data, openId],
  )

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка приёмок…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить журнал приёмок</div>

  if (open) {
    return <ReceiptCard receipt={open} onClose={() => { setOpenId(null); invalidate() }}
                        onlyDiff={onlyDiff} setOnlyDiff={setOnlyDiff} />
  }

  const receipts = data?.receipts ?? []
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">Приёмка</h3>
          <p className="text-xs text-muted-foreground">
            Поступление товара от поставщика. Пока документ не принят, остатки не двигаются —
            это ордерная схема: «к поступлению» → «принят».
            {stationId ? ` Показана АЗС ${stationId}.` : ' Показаны все станции контура.'}
          </p>
        </div>
        <button onClick={() => create.mutate()} disabled={create.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-60">
          <Plus className="h-4 w-4" />Новая приёмка
        </button>
      </div>

      {receipts.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Приёмок ещё нет. Заведите накладную здесь или примите товар на станции — документ
          будет один и тот же.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-3 py-2 text-left">Документ</th>
                <th className="px-3 py-2 text-left">Дата</th>
                <th className="px-3 py-2 text-left">АЗС</th>
                <th className="px-3 py-2 text-left">Поставщик</th>
                <th className="px-3 py-2 text-left">Статус</th>
                <th className="px-3 py-2 text-right">Позиций</th>
                <th className="px-3 py-2 text-right">Расхождений</th>
                <th className="px-3 py-2 text-right">Сумма, ₽</th>
                <th className="px-3 py-2 text-left">Ввод</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((r) => (
                <tr key={r.id} onClick={() => setOpenId(r.id)}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-2 font-medium">{r.number}</td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {new Date(r.doc_date).toLocaleDateString('ru-RU')}
                  </td>
                  <td className="px-3 py-2">{r.station_id}</td>
                  <td className="px-3 py-2">{r.supplier ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-3 py-2"><Badge status={r.status} /></td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.lines_count}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${r.diff_count ? 'text-amber-400/90' : ''}`}>
                    {r.diff_count || '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(r.total_amount)}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {r.origin === 'station' ? 'станция' : r.origin === 'edo' ? 'ЭДО' : 'центр'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Карточка документа: шапка, строки, перевод статуса. */
function ReceiptCard({ receipt, onClose, onlyDiff, setOnlyDiff }: {
  receipt: StoreReceipt; onClose: () => void
  onlyDiff: boolean; setOnlyDiff: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const [supplier, setSupplier] = useState(receipt.supplier ?? '')
  const [incoming, setIncoming] = useState(receipt.incoming_number ?? '')
  const [lines, setLines] = useState<StoreReceiptLine[]>(receipt.lines ?? [])
  const readOnly = receipt.status === 'accepted'

  const save = useMutation({
    mutationFn: () => updateStoreReceipt(receipt.id, {
      station_id: receipt.station_id, number: receipt.number,
      supplier: supplier || null, incoming_number: incoming || null, lines,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['store-receipts'] }),
  })
  const accept = useMutation({
    mutationFn: () => setStoreReceiptStatus(receipt.id, 'accepted'),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['store-receipts'] }); onClose() },
  })

  const setLine = (i: number, patch: Partial<StoreReceiptLine>) =>
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))

  const total = lines.reduce((s, l) => s + (l.qty_fact || 0) * (l.price || 0), 0)
  const diffCount = lines.filter((l) => Math.abs((l.qty_fact || 0) - (l.qty_expected || 0)) > 1e-6).length
  const shown = onlyDiff
    ? lines.filter((l) => Math.abs((l.qty_fact || 0) - (l.qty_expected || 0)) > 1e-6)
    : lines

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <PackagePlus className="h-5 w-5 text-muted-foreground" />
          <div>
            <h3 className="text-base font-semibold">{receipt.number}</h3>
            <p className="text-xs text-muted-foreground">
              АЗС {receipt.station_id} · {new Date(receipt.doc_date).toLocaleDateString('ru-RU')} ·{' '}
              <Badge status={receipt.status} />
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-sm">
            К журналу
          </button>
          {!readOnly && (
            <>
              <button onClick={() => save.mutate()} disabled={save.isPending}
                      className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-60">
                Сохранить
              </button>
              <button onClick={() => accept.mutate()} disabled={accept.isPending}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-600/90 px-3 py-2 text-sm text-white disabled:opacity-60">
                <Check className="h-4 w-4" />Принять
              </button>
            </>
          )}
        </div>
      </div>

      {accept.isError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <AlertTriangle className="h-4 w-4" />
          {(accept.error as Error)?.message || 'Не удалось принять документ'}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-xs text-muted-foreground">Поставщик
          <input value={supplier} onChange={(e) => setSupplier(e.target.value)} disabled={readOnly}
                 className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground disabled:opacity-60" />
        </label>
        <label className="text-xs text-muted-foreground">Входящий номер
          <input value={incoming} onChange={(e) => setIncoming(e.target.value)} disabled={readOnly}
                 className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground disabled:opacity-60" />
        </label>
        <div className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="text-xs text-muted-foreground">Сумма по факту</div>
          <div className="text-lg font-semibold tabular-nums">{money(total)} ₽</div>
        </div>
        <div className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="text-xs text-muted-foreground">Расхождений</div>
          <div className={`text-lg font-semibold tabular-nums ${diffCount ? 'text-amber-400/90' : ''}`}>
            {diffCount}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={() => setOnlyDiff(!onlyDiff)}
                className={`rounded-lg border px-3 py-1.5 text-xs ${onlyDiff ? 'border-amber-400/50 text-amber-300/90' : 'border-border text-muted-foreground'}`}>
          Только строки с расхождениями
        </button>
        {!readOnly && (
          <button onClick={() => setLines([...lines, emptyLine()])}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs">
            <Plus className="h-3.5 w-3.5" />Позиция
          </button>
        )}
        <span className="text-xs text-muted-foreground">
          Заявлено — из накладной, факт — сколько реально посчитали. Платим за факт.
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="px-3 py-2 text-left">Наименование</th>
              <th className="px-3 py-2 text-left">Штрихкод</th>
              <th className="px-3 py-2 text-right">Заявлено</th>
              <th className="px-3 py-2 text-right">Факт</th>
              <th className="px-3 py-2 text-right">Расхождение</th>
              <th className="px-3 py-2 text-right">Цена</th>
              <th className="px-3 py-2 text-right">Сумма</th>
              {!readOnly && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => {
              const i = lines.indexOf(l)
              const diff = (l.qty_fact || 0) - (l.qty_expected || 0)
              return (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="px-3 py-1.5">
                    <input value={l.name} onChange={(e) => setLine(i, { name: e.target.value })}
                           disabled={readOnly} placeholder="наименование"
                           className="w-full bg-transparent text-sm outline-none disabled:opacity-70" />
                  </td>
                  <td className="px-3 py-1.5">
                    <input value={l.barcode ?? ''} onChange={(e) => setLine(i, { barcode: e.target.value })}
                           disabled={readOnly} placeholder="сканируйте"
                           className="w-36 bg-transparent text-sm text-muted-foreground outline-none disabled:opacity-70" />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.qty_expected}
                           onChange={(e) => setLine(i, { qty_expected: Number(e.target.value) })}
                           disabled={readOnly}
                           className="w-20 bg-transparent text-right tabular-nums outline-none disabled:opacity-70" />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.qty_fact}
                           onChange={(e) => setLine(i, { qty_fact: Number(e.target.value) })}
                           disabled={readOnly}
                           className="w-20 bg-transparent text-right tabular-nums outline-none disabled:opacity-70" />
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${diff ? 'text-amber-400/90' : 'text-muted-foreground'}`}>
                    {diff ? (diff > 0 ? `+${diff}` : diff) : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.price}
                           onChange={(e) => setLine(i, { price: Number(e.target.value) })}
                           disabled={readOnly}
                           className="w-24 bg-transparent text-right tabular-nums outline-none disabled:opacity-70" />
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {money((l.qty_fact || 0) * (l.price || 0))}
                  </td>
                  {!readOnly && (
                    <td className="px-3 py-1.5 text-right">
                      <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))}
                              className="text-muted-foreground hover:text-red-400">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
            {shown.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                {lines.length ? 'Расхождений нет' : 'Добавьте позиции или примите товар на станции'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
