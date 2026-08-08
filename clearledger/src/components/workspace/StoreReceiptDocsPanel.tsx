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
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackagePlus, Plus, Trash2, Check, AlertTriangle, Send, Warehouse, ScanBarcode, CircleCheck, Loader2 } from 'lucide-react'
import {
  getStoreReceipts, createStoreReceipt, updateStoreReceipt, setStoreReceiptStatus,
  getStoreStations, createStoreReceiptFromUPD, sendStoreReceiptToStation,
  recordStoreReceiptSignature, distributeStoreReceipt, scanStoreReceipt,
  type StoreReceipt, type StoreReceiptLine, type StoreReceiptInput,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Callout } from '@/components/ui/callout'
import { parseReceiptScan, SCAN_TYPE_LABEL } from '@/lib/receiptScanner'

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

function StatusBadge({ status }: { status: string }) {
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
  upd_codes: [], mark_codes: [], pack_codes: [], requires_mark: false, no_card: false,
})

export function StoreReceiptDocsPanel({ stations }: { stations?: string[] }) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const stationId = stations?.length === 1 ? Number(stations[0]) : undefined
  const [openId, setOpenId] = useState<string | null>(null)
  const [onlyDiff, setOnlyDiff] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-receipts', company.id, stationId],
    queryFn: () => getStoreReceipts({ stationId }),
  })
  const { data: stationData } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['store-receipts'] })
  const open = useMemo(
    () => data?.receipts.find((r) => r.id === openId) ?? null,
    [data, openId],
  )

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка приёмок…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить журнал приёмок</div>

  if (open) {
    return <ReceiptCard receipt={open} onClose={() => { setOpenId(null); invalidate() }}
                        onlyDiff={onlyDiff} setOnlyDiff={setOnlyDiff}
                        stationIds={(stationData?.stations ?? []).map((s) => s.station_id)} />
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
        <Button onClick={() => setCreateOpen(true)}><Plus />Новая приёмка</Button>
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
                {/* Кто принял: приёмка, проведённая из центра, коробок не открывала. */}
                <th className="px-3 py-2 text-left">Принял</th>
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
                  <td className="px-3 py-2">{r.station_id ?? r.receiving_warehouse ?? 'центральный склад'}</td>
                  <td className="px-3 py-2">{r.supplier ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.lines_count}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${r.diff_count ? 'text-amber-400/90' : ''}`}>
                    {r.diff_count || '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(r.total_amount)}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {r.origin === 'station' ? 'станция' : r.origin === 'edo' ? 'ЭДО' : 'центр'}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {r.author ?? <span className="text-muted-foreground/60">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewReceiptDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        defaultStation={stationId}
        stationIds={(stationData?.stations ?? []).map((s) => s.station_id)}
        onCreated={(r) => { invalidate(); setOpenId(r.id) }}
      />
    </div>
  )
}

/** Карточка документа: шапка, строки, перевод статуса. */
function ReceiptCard({ receipt, onClose, onlyDiff, setOnlyDiff, stationIds }: {
  receipt: StoreReceipt; onClose: () => void
  onlyDiff: boolean; setOnlyDiff: (v: boolean) => void
  stationIds: number[]
}) {
  const qc = useQueryClient()
  const [supplier, setSupplier] = useState(receipt.supplier ?? '')
  const [incoming, setIncoming] = useState(receipt.incoming_number ?? '')
  const [lines, setLines] = useState<StoreReceiptLine[]>(receipt.lines ?? [])
  const [signatureRef, setSignatureRef] = useState(receipt.signature_ref ?? '')
  const [signerName, setSignerName] = useState(receipt.signer_name ?? '')
  const [mchdGuid, setMchdGuid] = useState(receipt.mchd_guid ?? '')
  const [mchdRegistry, setMchdRegistry] = useState(receipt.mchd_registry ?? '')
  const [mchdUntil, setMchdUntil] = useState(receipt.mchd_valid_until ?? '')
  const readOnly = receipt.status === 'accepted'

  const body = (): StoreReceiptInput => ({
    station_id: receipt.station_id, number: receipt.number,
    supplier: supplier || null, incoming_number: incoming || null, lines,
    delivery_scheme: receipt.delivery_scheme,
    receiving_warehouse: receipt.receiving_warehouse,
    signing_mode: receipt.signing_mode,
    signer_name: signerName || null, mchd_guid: mchdGuid || null,
    mchd_registry: mchdRegistry || null, mchd_valid_until: mchdUntil || null,
    signature_status: receipt.signature_status, signature_ref: receipt.signature_ref,
  })

  const save = useMutation({
    mutationFn: () => updateStoreReceipt(receipt.id, body()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['store-receipts'] }),
  })
  const accept = useMutation({
    mutationFn: async () => {
      await updateStoreReceipt(receipt.id, body())
      return setStoreReceiptStatus(receipt.id, 'accepted')
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['store-receipts'] }); onClose() },
  })
  const send = useMutation({
    mutationFn: () => sendStoreReceiptToStation(receipt.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['store-receipts'] }),
  })
  const sign = useMutation({
    mutationFn: () => recordStoreReceiptSignature(receipt.id, {
      signature_status: 'signed', signature_ref: signatureRef || null,
      signer_name: signerName || null, mchd_guid: mchdGuid || null,
      mchd_registry: mchdRegistry || null, mchd_valid_until: mchdUntil || null,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['store-receipts'] }),
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
              {receipt.delivery_scheme === 'central_warehouse'
                ? receipt.receiving_warehouse
                : `АЗС ${receipt.station_id}`} · {new Date(receipt.doc_date).toLocaleDateString('ru-RU')} ·{' '}
              <StatusBadge status={receipt.status} />
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-sm">
            К журналу
          </button>
          {!readOnly && (
            <>
              {receipt.delivery_scheme === 'supplier_to_station' && (
                <Button variant="outline" onClick={() => send.mutate()} disabled={send.isPending}>
                  <Send />На АЗС
                </Button>
              )}
              <button onClick={() => save.mutate()} disabled={save.isPending}
                      className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-60">
                Сохранить
              </button>
              {receipt.delivery_scheme === 'central_warehouse' && (
                <button onClick={() => accept.mutate()} disabled={accept.isPending}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600/90 px-3 py-2 text-sm text-white disabled:opacity-60">
                  <Check className="h-4 w-4" />Принять на центральный склад
                </button>
              )}
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

      <div className="grid gap-4 rounded-xl border border-border bg-card p-4 lg:grid-cols-2">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Warehouse className="h-4 w-4" />
            {receipt.delivery_scheme === 'central_warehouse'
              ? 'Поставщик → центральный склад'
              : `Поставщик → АЗС ${receipt.station_id}`}
          </div>
          <p className="text-xs text-muted-foreground">
            {receipt.delivery_scheme === 'central_warehouse'
              ? 'После приёмки партия распределяется на АЗС внутренними перемещениями.'
              : 'Базовая схема: УПД сформирован в разрезе конкретной станции и её склада.'}
          </p>
        </div>
        <div className="space-y-3">
          <div className="text-sm font-medium">
            {receipt.signing_mode === 'station_mchd'
              ? 'Администратор АЗС — личная УКЭП по МЧД'
              : 'Офис — подпись генерального директора'}
          </div>
          {receipt.signature_status === 'signed' ? (
            <p className="text-xs text-emerald-400">
              Подписан в ЭДО · {receipt.signature_ref}
            </p>
          ) : (
            <>
              {receipt.signing_mode === 'station_mchd' && (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input value={signerName} onChange={(e) => setSignerName(e.target.value)} placeholder="ФИО представителя" />
                  <Input value={mchdGuid} onChange={(e) => setMchdGuid(e.target.value)} placeholder="GUID МЧД" />
                  <Input value={mchdRegistry} onChange={(e) => setMchdRegistry(e.target.value)} placeholder="Реестр МЧД" />
                  <Input type="date" value={mchdUntil} onChange={(e) => setMchdUntil(e.target.value)} />
                </div>
              )}
              <div className="flex gap-2">
                <Input value={signatureRef} onChange={(e) => setSignatureRef(e.target.value)}
                       placeholder="Идентификатор подписи оператора ЭДО" />
                <Button variant="outline" onClick={() => sign.mutate()} disabled={sign.isPending}>
                  Зафиксировать подпись ЭДО
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Здесь фиксируются реквизиты уже выполненной подписи; криптографическая операция проходит у оператора ЭДО.
              </p>
            </>
          )}
        </div>
      </div>

      {!readOnly && receipt.delivery_scheme === 'central_warehouse' && (
        <ReceiptScanner
          receipt={receipt}
          lines={lines}
          onScanned={(result) => {
            setLines(result.lines)
            qc.invalidateQueries({ queryKey: ['store-receipts'] })
          }}
        />
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
                    {l.requires_mark ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge variant="outline">УПД: {l.upd_codes?.length ?? 0}</Badge>
                        <Badge variant={(l.mark_codes?.length ?? 0) === l.qty_fact ? 'secondary' : 'destructive'}>
                          сканов: {l.mark_codes?.length ?? 0}
                        </Badge>
                      </div>
                    ) : null}
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
      {readOnly && receipt.delivery_scheme === 'central_warehouse' && (
        <DistributionPanel receipt={receipt} stationIds={stationIds} />
      )}
    </div>
  )
}

function ReceiptScanner({ receipt, lines, onScanned }: {
  receipt: StoreReceipt
  lines: StoreReceiptLine[]
  onScanned: (receipt: StoreReceipt) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [code, setCode] = useState('')
  const [units, setUnits] = useState(1)
  const [pack, setPack] = useState(1)
  const [feedback, setFeedback] = useState<{
    kind: 'success' | 'error'; title: string; detail: string; type?: string
  } | null>(null)
  const [scans, setScans] = useState(0)

  const scan = useMutation({
    mutationFn: ({ raw, qty }: { raw: string; qty: number }) =>
      scanStoreReceipt(receipt.id, raw, qty, lines),
    onSuccess: (result) => {
      setScans((count) => count + 1)
      setFeedback({
        kind: 'success', title: result.scan.name || 'Товар найден',
        detail: `Добавлено: ${result.scan.qty_added.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} · штрихкод ${result.scan.barcode}`,
        type: result.scan.type,
      })
      onScanned(result)
    },
    onError: (error) => setFeedback({
      kind: 'error', title: 'Скан не принят',
      detail: (error as Error).message || 'Повторите сканирование',
    }),
    onSettled: () => window.setTimeout(() => inputRef.current?.focus(), 0),
  })

  const submit = () => {
    const parsed = parseReceiptScan(code)
    if (!parsed) {
      setFeedback({ kind: 'error', title: 'Сканер не передал код', detail: 'Поставьте курсор в поле и повторите сканирование.' })
      inputRef.current?.focus()
      return
    }
    if (parsed.checksumValid === false) {
      setFeedback({
        kind: 'error', title: 'Контрольная цифра не сходится',
        detail: `${SCAN_TYPE_LABEL[parsed.type]} прочитан с ошибкой. Повторите сканирование.`,
      })
      setCode('')
      inputRef.current?.focus()
      return
    }
    const qty = parsed.markCode ? 1 : Math.max(1, units) * Math.max(1, pack)
    setCode('')
    scan.mutate({ raw: code, qty })
  }

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4" aria-labelledby="receipt-scanner-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 id="receipt-scanner-title" className="flex items-center gap-2 text-sm font-semibold">
            <ScanBarcode className="size-4" />Поточное сканирование
          </h4>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            USB- и радиосканер работает как клавиатура: наведите на код, сканер введёт его и нажмёт Enter.
            Поддерживаются EAN-8/13, UPC-A, GTIN-14, Code 128, GS1-128, DataMatrix и табачная маркировка.
          </p>
        </div>
        <Badge variant="secondary">Сканов за сеанс: {scans}</Badge>
      </div>
      <form className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_110px_110px_auto]" onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
          Код со сканера
          <Input ref={inputRef} autoFocus autoComplete="off" value={code} maxLength={512}
                 disabled={scan.isPending} onChange={(event) => setCode(event.target.value)}
                 placeholder="поле остаётся в фокусе после каждого скана" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Единиц
          <Input type="number" min={1} step="any" value={units} disabled={scan.isPending}
                 onChange={(event) => setUnits(Number(event.target.value) || 1)} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          В упаковке
          <Input type="number" min={1} step="any" value={pack} disabled={scan.isPending}
                 onChange={(event) => setPack(Number(event.target.value) || 1)} />
        </label>
        <Button type="submit" className="self-end" disabled={scan.isPending || !code}>
          {scan.isPending ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <ScanBarcode data-icon="inline-start" />}
          Принять скан
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">
        Для маркированного товара всегда добавляется ровно один экземпляр. Повторный код и код не из УПД блокируются.
        Весовая этикетка принимается автоматически только при точном штрихкоде в НСИ — масса не угадывается по локальному префиксу.
      </p>
      {feedback && (
        <div aria-live="polite">
          <Callout variant={feedback.kind === 'success' ? 'success' : 'error'}
                   title={feedback.title}
                   icon={feedback.kind === 'success' ? CircleCheck : AlertTriangle}>
            <span>{feedback.detail}</span>
            {feedback.type ? <Badge variant="outline" className="ml-2">{feedback.type}</Badge> : null}
          </Callout>
        </div>
      )}
    </section>
  )
}

function NewReceiptDialog({ open, onOpenChange, defaultStation, stationIds, onCreated }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultStation?: number
  stationIds: number[]
  onCreated: (receipt: StoreReceipt) => void
}) {
  const firstStation = defaultStation ?? stationIds[0] ?? 208
  const [delivery, setDelivery] = useState<'supplier_to_station' | 'central_warehouse'>('supplier_to_station')
  const [station, setStation] = useState(String(firstStation))
  const [warehouse, setWarehouse] = useState('Центральный склад')
  const [signing, setSigning] = useState<'office_director' | 'station_mchd'>('office_director')
  const [signerName, setSignerName] = useState('')
  const [mchdGuid, setMchdGuid] = useState('')
  const [mchdRegistry, setMchdRegistry] = useState('ФНС')
  const [mchdUntil, setMchdUntil] = useState('')
  const [upd, setUpd] = useState<File | null>(null)

  const options: StoreReceiptInput = {
    station_id: delivery === 'supplier_to_station' ? Number(station) : null,
    delivery_scheme: delivery,
    receiving_warehouse: delivery === 'central_warehouse' ? warehouse : null,
    signing_mode: delivery === 'central_warehouse' ? 'office_director' : signing,
    signer_name: signing === 'station_mchd' ? signerName || null : null,
    mchd_guid: signing === 'station_mchd' ? mchdGuid || null : null,
    mchd_registry: signing === 'station_mchd' ? mchdRegistry || null : null,
    mchd_valid_until: signing === 'station_mchd' ? mchdUntil || null : null,
    signature_status: 'pending', signature_ref: null, lines: [],
  }
  const create = useMutation({
    mutationFn: () => upd
      ? createStoreReceiptFromUPD(upd, options)
      : createStoreReceipt(options),
    onSuccess: (receipt) => {
      onCreated(receipt)
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Новая приёмка</DialogTitle>
          <DialogDescription>
            Сначала выберите маршрут товара, затем — кто подпишет УПД. Прямая доставка на АЗС используется по умолчанию.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-5 py-2">
          <label className="grid gap-2 text-sm">
            Доставка
            <Select value={delivery} onValueChange={(value) => {
              const next = value as 'supplier_to_station' | 'central_warehouse'
              setDelivery(next)
              if (next === 'central_warehouse') setSigning('office_director')
            }}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="supplier_to_station">Поставщик → конкретная АЗС (по умолчанию)</SelectItem>
                  <SelectItem value="central_warehouse">Поставщик → центральный склад</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          {delivery === 'supplier_to_station' ? (
            <label className="grid gap-2 text-sm">
              Станция-получатель
              <Select value={station} onValueChange={setStation}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {(stationIds.length ? stationIds : [firstStation]).map((id) => (
                      <SelectItem key={id} value={String(id)}>АЗС {id}</SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </label>
          ) : (
            <label className="grid gap-2 text-sm">Склад приёмки
              <Input value={warehouse} onChange={(e) => setWarehouse(e.target.value)} />
              <span className="text-xs text-muted-foreground">После приёмки товар распределяется внутренними перемещениями.</span>
            </label>
          )}
          <label className="grid gap-2 text-sm">
            Подписание УПД
            <Select value={delivery === 'central_warehouse' ? 'office_director' : signing}
                    disabled={delivery === 'central_warehouse'}
                    onValueChange={(value) => setSigning(value as 'office_director' | 'station_mchd')}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="office_director">Офис — генеральный директор</SelectItem>
                  <SelectItem value="station_mchd">Администратор АЗС — УКЭП по МЧД</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          {delivery === 'supplier_to_station' && signing === 'station_mchd' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Input value={signerName} onChange={(e) => setSignerName(e.target.value)} placeholder="ФИО представителя" />
              <Input value={mchdGuid} onChange={(e) => setMchdGuid(e.target.value)} placeholder="GUID МЧД" />
              <Input value={mchdRegistry} onChange={(e) => setMchdRegistry(e.target.value)} placeholder="Реестр МЧД" />
              <Input type="date" value={mchdUntil} onChange={(e) => setMchdUntil(e.target.value)} />
            </div>
          )}
          <label className="grid gap-2 text-sm">УПД из ЭДО <span className="text-xs text-muted-foreground">необязательно для черновика</span>
            <Input type="file" accept=".xml,text/xml,application/xml" onChange={(e) => setUpd(e.target.files?.[0] ?? null)} />
          </label>
          {create.isError && (
            <p className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending}>Создать приёмку</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DistributionPanel({ receipt, stationIds }: { receipt: StoreReceipt; stationIds: number[] }) {
  const qc = useQueryClient()
  const [station, setStation] = useState(String(stationIds[0] ?? 208))
  const [qty, setQty] = useState<Record<number, number>>({})
  const used = new Map<number, number>()
  receipt.distribution.forEach((allocation) => allocation.lines.forEach((line) => {
    used.set(line.line_index, (used.get(line.line_index) ?? 0) + line.qty)
  }))
  const distribute = useMutation({
    mutationFn: () => distributeStoreReceipt(
      receipt.id, Number(station),
      Object.entries(qty).filter(([, value]) => value > 0)
        .map(([lineIndex, value]) => ({ line_index: Number(lineIndex), qty: value })),
    ),
    onSuccess: () => {
      setQty({})
      qc.invalidateQueries({ queryKey: ['store-receipts'] })
    },
  })

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div>
        <h4 className="text-sm font-semibold">Распределение по станциям</h4>
        <p className="text-xs text-muted-foreground">Создаётся внутреннее перемещение с центрального склада, не второй приход поставщика.</p>
      </div>
      <Select value={station} onValueChange={setStation}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent><SelectGroup>{(stationIds.length ? stationIds : [208]).map((id) => (
          <SelectItem key={id} value={String(id)}>АЗС {id}</SelectItem>
        ))}</SelectGroup></SelectContent>
      </Select>
      <div className="grid gap-2">
        {receipt.lines.map((line, index) => {
          const available = Math.max(0, line.qty_fact - (used.get(index) ?? 0))
          return (
            <label key={index} className="grid grid-cols-[1fr_110px] items-center gap-3 text-sm">
              <span>{line.name} <span className="text-xs text-muted-foreground">доступно {available}</span></span>
              <Input type="number" min={0} max={available} step="any" value={qty[index] ?? ''}
                     disabled={available <= 0}
                     onChange={(e) => setQty((current) => ({ ...current, [index]: Number(e.target.value) }))} />
            </label>
          )
        })}
      </div>
      {distribute.isError && <p className="text-sm text-destructive">{(distribute.error as Error).message}</p>}
      <Button onClick={() => distribute.mutate()} disabled={distribute.isPending}>
        <Send />Передать на АЗС
      </Button>
    </div>
  )
}
