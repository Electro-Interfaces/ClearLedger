/**
 * Документ ЗИП: приход, отпуск на станцию, перемещение, списание, инвентаризация.
 *
 * Операция проводится документом на несколько строк — с номером, датой, складом,
 * контрагентом и договором из справочников пространства, «сдал / принял» и
 * основанием. Остатки и переходы проверяет сервер; проведённый документ не
 * правится — ошибку исправляет отмена в реестре документов и новый документ.
 *
 * Приход — по цене без НДС (сумма строки идёт в остаток), расход и перемещение —
 * по средней стоимости остатка склада: её считает сервер. Документ можно сохранить
 * черновиком и провести позже из реестра.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, Plus, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import {
  SPARE_DOC_META, getSpareCountSheet, getWarehousesSummary, listEquipmentDocuments, listUnits, postSpareDocument,
  type EquipmentUnit, type SpareDocOp, type SparePart,
} from '@/services/equipmentService'
import { CounterpartyContractPicker } from './CounterpartyContractPicker'
import { eqName } from './equipmentDocPrint'
import { printSpareDocument, ruDate, signed, spareSigners } from './spareDocPrint'

const selectClass = 'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const num = (s: string) => (s.trim() === '' ? NaN : Number(s.replace(',', '.')))
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
/** Станция в эксплуатации показывается названием станции, прочая единица — моделью. */
const unitLabel = (u: Pick<EquipmentUnit, 'serialNumber' | 'vendor' | 'model' | 'state' | 'location'>) =>
  `${(u.state === 'in_operation' && u.location?.name) || eqName(u.vendor, u.model) || 'Станция'} · с/н ${u.serialNumber ?? '—'}`

interface Line { key: number; partId: string; qty: string; price: string; book?: number }
let lineKey = 0
const newLine = (partId = '', book?: number): Line => ({ key: ++lineKey, partId, qty: '', price: '', book })
const rub = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function SpareDocumentDialog({ companyId, op, parts, presetPartId, onClose }: {
  companyId: string
  op: SpareDocOp
  /** Вся номенклатура, включая архив: архивная позиция может числиться на складе. */
  parts: SparePart[]
  presetPartId?: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { company } = useCompany()
  const meta = SPARE_DOC_META[op]
  const inventory = op === 'inventory'
  const needsFrom = op === 'issue' || op === 'write_off' || op === 'transfer'
  const needsTo = op === 'receipt' || op === 'transfer' || inventory
  // Ключ документа выдаёт форма: повторная отправка вернёт уже проведённый документ.
  const [docId] = useState(() => crypto.randomUUID())
  const [docDate, setDocDate] = useState(new Date().toISOString().slice(0, 10))
  const [number, setNumber] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [party, setParty] = useState({ counterpartyId: '', contractId: '' })
  const [responsibleFrom, setResponsibleFrom] = useState('')
  const [responsibleTo, setResponsibleTo] = useState('')
  const [basis, setBasis] = useState('')
  const [comment, setComment] = useState('')
  const [lines, setLines] = useState<Line[]>(() => (inventory ? [] : [newLine(presetPartId)]))
  const [target, setTarget] = useState<'unit' | 'note'>('unit')
  const [unitQ, setUnitQ] = useState('')
  const [pickedUnit, setPickedUnit] = useState<{ id: string; label: string } | null>(null)
  const [targetNote, setTargetNote] = useState('')
  const [repairId, setRepairId] = useState('')
  const [primaryNumber, setPrimaryNumber] = useState('')
  const [primaryDate, setPrimaryDate] = useState('')
  const receipt = op === 'receipt'

  const whQ = useQuery({ queryKey: ['equipment', 'warehouses-summary', companyId], queryFn: () => getWarehousesSummary(companyId), staleTime: 60_000 })
  const warehouses = useMemo(() => (whQ.data?.warehouses ?? []).filter((w) => w.status !== 'closed').map((w) => w.location), [whQ.data])
  const byId = useMemo(() => new Map(parts.map((p) => [p.id, p])), [parts])
  const stockAt = (partId: string, whId: string) => byId.get(partId)?.byLocation.find((b) => b.locationId === whId)?.qty ?? 0
  const unitsQ = useQuery({
    queryKey: ['equipment', 'units-pick', companyId, unitQ],
    queryFn: () => listUnits({ companyId, q: unitQ.trim(), pageSize: 20 }),
    enabled: op === 'issue' && target === 'unit' && !pickedUnit && unitQ.trim().length >= 2,
  })
  const repairsQ = useQuery({
    queryKey: ['equipment', 'repair-docs', companyId],
    queryFn: async () => (await Promise.all((['to_repair', 'from_repair'] as const).map((o) => listEquipmentDocuments({ companyId, op: o, limit: 200 })))).flatMap((r) => r.items),
    enabled: op === 'issue', staleTime: 60_000,
  })
  // Лист пересчёта: что числится на складе сейчас — заготовка строк описи.
  const sheet = useMutation({
    mutationFn: (whId: string) => getSpareCountSheet(companyId, whId),
    onSuccess: (s) => setLines(s.lines.map((l) => newLine(l.partId, l.book))),
    onError: (e) => { setLines([]); toast.error('Лист пересчёта не получен', { description: errText(e) }) },
  })

  const filled = lines.filter((l) => l.partId && l.qty.trim() !== '')
  const mut = useMutation({
    mutationFn: (draft: boolean) => postSpareDocument(companyId, {
      id: docId, op, docDate, number: number.trim() || undefined, draft,
      primaryNumber: primaryNumber.trim() || undefined, primaryDate: primaryDate || undefined,
      lines: filled.map((l) => (inventory ? { partId: l.partId, fact: num(l.qty) }
        : { partId: l.partId, qty: num(l.qty), price: receipt && l.price.trim() ? num(l.price) : undefined })),
      fromLocationId: needsFrom ? fromId : undefined, toLocationId: needsTo ? toId : undefined,
      targetUnitId: op === 'issue' && target === 'unit' ? pickedUnit?.id : undefined,
      targetNote: op === 'issue' && target === 'note' ? targetNote.trim() : undefined,
      repairDocumentId: op === 'issue' && repairId ? repairId : undefined,
      counterpartyId: party.counterpartyId || undefined, contractId: party.contractId || undefined,
      responsibleFrom: responsibleFrom.trim() || undefined, responsibleTo: responsibleTo.trim() || undefined,
      basis: basis.trim() || undefined, comment: comment.trim() || undefined,
    }),
    onSuccess: (doc, draft) => {
      for (const k of ['equipment', 'eq-spares', 'eq-spare-movements', 'eq-warehouses', 'equipment-warehouses']) void qc.invalidateQueries({ queryKey: [k] })
      if (draft) {
        toast.success(`Черновик № ${doc.number} сохранён`, { description: 'Провести его можно из реестра «Документы».' })
      } else {
        toast.success(`${doc.title} № ${doc.number} проведён: ${doc.positions} поз.`)
        for (const w of doc.warnings ?? []) toast.warning(w)
        try { printSpareDocument(doc, company?.name || 'Пространство') } catch (e) { toast.info(errText(e)) }
      }
      onClose()
    },
    onError: (e, draft) => toast.error(draft ? 'Черновик не сохранён' : 'Документ не проведён', { description: errText(e) }),
  })
  const total = receipt ? filled.reduce((s, l) => s + (num(l.qty) || 0) * (num(l.price) || 0), 0) : 0

  const problem = !docDate ? 'Укажите дату документа'
    : needsFrom && !fromId ? 'Выберите склад, с которого выдаётся'
    : needsTo && !toId ? (inventory ? 'Выберите склад — появится лист пересчёта' : 'Выберите склад-получатель')
    : op === 'transfer' && fromId === toId ? 'Склады «откуда» и «куда» должны быть разными'
    : op === 'issue' && target === 'unit' && !pickedUnit ? 'Выберите станцию, на которую уходит расход'
    : op === 'issue' && target === 'note' && !targetNote.trim() ? 'Напишите, на какой объект уходит расход'
    : inventory && !filled.length ? 'Введите фактическое количество хотя бы по одной позиции'
    : !inventory && (filled.length !== lines.length || !lines.length) ? 'Заполните номенклатуру и количество в каждой строке'
    : filled.some((l) => !(inventory ? num(l.qty) >= 0 : num(l.qty) > 0)) ? (inventory ? 'Фактическое количество — число не меньше нуля' : 'Количество — число больше нуля')
    : receipt && filled.some((l) => l.price.trim() && !(num(l.price) >= 0)) ? 'Цена — число не меньше нуля'
    : null

  const setLine = (key: number, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const taken = new Set(lines.map((l) => l.partId))
  const whSelect = (label: string, value: string, onChange: (v: string) => void, skip = '') => (
    <label className="text-xs">{label}
      <select aria-label={label} className={selectClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{whQ.isLoading ? 'Загрузка…' : warehouses.length ? 'Не выбран' : 'Складов нет — заведите склад в «Складах»'}</option>
        {warehouses.filter((w) => w.id !== skip).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select></label>)
  const [signFrom, signTo] = spareSigners(op)

  return <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent className="sm:max-w-3xl w-[96vw] max-h-[92dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>{meta.title}</DialogTitle></DialogHeader>
      <div className="space-y-3">
        {whQ.isError && <p role="alert" className="text-xs text-destructive">Список складов не загрузился: {errText(whQ.error)}</p>}
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">Дата документа<Input aria-label="Дата документа" type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="h-9" /></label>
          <label className="text-xs">Номер<Input aria-label="Номер документа" value={number} onChange={(e) => setNumber(e.target.value)} placeholder={`${meta.prefix}-${docDate.slice(0, 4)}-… автоматически`} className="h-9" /></label>
          {needsFrom && whSelect('Склад-отправитель', fromId, setFromId)}
          {needsTo && whSelect(inventory ? 'Склад' : 'Склад-получатель', toId, (v) => { setToId(v); if (inventory) { if (v) sheet.mutate(v); else setLines([]) } }, op === 'transfer' ? fromId : '')}
          {!inventory && <>
            <label className="text-xs">Первичный документ контрагента, №<Input aria-label="Номер первичного документа" value={primaryNumber}
              onChange={(e) => setPrimaryNumber(e.target.value)} placeholder={receipt ? 'УПД, накладная поставщика' : 'акт, накладная'} className="h-9" /></label>
            <label className="text-xs">Дата первичного документа<Input aria-label="Дата первичного документа" type="date" value={primaryDate}
              onChange={(e) => setPrimaryDate(e.target.value)} className="h-9" /></label>
          </>}
        </div>

        {op === 'issue' && <div className="space-y-2 rounded-md border p-2">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="text-muted-foreground">Получатель:</span>
            <label className="flex items-center gap-1.5"><input type="radio" checked={target === 'unit'} onChange={() => setTarget('unit')} />Станция</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={target === 'note'} onChange={() => setTarget('note')} />На объект без привязки к станции</label>
          </div>
          {target === 'note' && <Input aria-label="Объект без привязки к станции" value={targetNote} onChange={(e) => setTargetNote(e.target.value)} placeholder="Что за объект: адрес, назначение" className="h-9" />}
          {target === 'unit' && (pickedUnit
            ? <div className="flex items-center gap-1.5 text-sm">{pickedUnit.label}
              <Button variant="ghost" size="icon" className="size-6" title="Выбрать другую" onClick={() => setPickedUnit(null)}><X className="size-3.5" /></Button></div>
            : <div className="space-y-1.5">
              <div className="relative"><Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input aria-label="Поиск станции" value={unitQ} onChange={(e) => setUnitQ(e.target.value)} placeholder="Серийный номер, модель или название станции — от 2 символов" className="pl-8 h-9" /></div>
              {unitsQ.isFetching && <div className="text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin inline-block mr-1" />Поиск…</div>}
              {unitsQ.isError && <p role="alert" className="text-xs text-destructive">Поиск не удался: {errText(unitsQ.error)}</p>}
              {unitsQ.data && unitsQ.data.items.length === 0 && <div className="text-xs text-muted-foreground">Станции не найдены</div>}
              {!!unitsQ.data?.items.length && <div className="max-h-40 overflow-y-auto rounded-md border divide-y divide-border/50">
                {unitsQ.data.items.map((u) => <button key={u.id} type="button" onClick={() => setPickedUnit({ id: u.id, label: unitLabel(u) })}
                  className="block w-full px-2.5 py-1.5 text-left text-xs hover:bg-muted/60">{unitLabel(u)}<span className="text-muted-foreground"> · {u.stateLabel}</span></button>)}
              </div>}
            </div>)}
          <label className="text-xs block">Акт ремонта (если запчасти ушли в ремонт по акту)
            <select aria-label="Акт ремонта" className={selectClass} value={repairId} onChange={(e) => setRepairId(e.target.value)}>
              <option value="">{repairsQ.isError ? 'Акты ремонта не загрузились' : 'Не указан'}</option>
              {(repairsQ.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.number} от {ruDate(d.docDate)} · {d.opLabel}{d.counterpartyName ? ` · ${d.counterpartyName}` : ''}</option>)}
            </select></label>
        </div>}

        <div className="rounded-md border">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground text-left">
              <th className="p-2 font-medium">Номенклатура</th>
              {inventory ? <><th className="p-2 font-medium text-right w-24">По учёту</th><th className="p-2 font-medium w-28">Фактически</th><th className="p-2 font-medium text-right w-24">Отклонение</th></>
                : <>{needsFrom && <th className="p-2 font-medium text-right w-24">На складе</th>}<th className="p-2 font-medium w-28">Количество</th>
                  {receipt && <><th className="p-2 font-medium w-32">Цена без НДС, ₽</th><th className="p-2 font-medium text-right w-28">Сумма, ₽</th></>}</>}
              <th className="w-8" /></tr></thead>
            <tbody>
              {sheet.isPending && <tr><td colSpan={5} className="p-3 text-muted-foreground"><Loader2 className="size-3.5 animate-spin inline-block mr-1" />Лист пересчёта…</td></tr>}
              {inventory && !sheet.isPending && toId && !lines.length && <tr><td colSpan={5} className="p-3 text-muted-foreground">На складе ничего не числится. Найденное при пересчёте добавьте строкой.</td></tr>}
              {lines.map((l) => {
                const p = byId.get(l.partId)
                const book = inventory ? l.book ?? stockAt(l.partId, toId) : stockAt(l.partId, fromId)
                const q = num(l.qty)
                return <tr key={l.key} className="border-b border-border/30">
                  <td className="p-1.5">
                    {inventory && l.book !== undefined ? <span className="px-1">{p?.name ?? '—'}{p?.article ? <span className="text-muted-foreground"> · {p.article}</span> : null}</span>
                      : <select aria-label="Номенклатура" className={selectClass} value={l.partId} onChange={(e) => setLine(l.key, { partId: e.target.value })}>
                        <option value="">Выберите</option>
                        {parts.filter((x) => (!x.isArchived && !taken.has(x.id)) || x.id === l.partId).map((x) => <option key={x.id} value={x.id}>{x.name}{x.article ? ` · ${x.article}` : ''}</option>)}
                      </select>}
                  </td>
                  {(inventory || needsFrom) && <td className="p-1.5 text-right tabular-nums whitespace-nowrap">{l.partId ? `${nf.format(book)} ${p?.unitLabel ?? ''}` : '—'}</td>}
                  <td className="p-1.5"><Input aria-label={inventory ? 'Фактическое количество' : 'Количество'} inputMode="decimal" value={l.qty} onChange={(e) => setLine(l.key, { qty: e.target.value })} className="h-8" /></td>
                  {receipt && <>
                    <td className="p-1.5"><Input aria-label="Цена без НДС" inputMode="decimal" value={l.price} onChange={(e) => setLine(l.key, { price: e.target.value })} className="h-8" /></td>
                    <td className="p-1.5 text-right tabular-nums whitespace-nowrap">{Number.isFinite(num(l.qty) * num(l.price)) ? rub.format(num(l.qty) * num(l.price)) : '—'}</td>
                  </>}
                  {inventory && <td className={`p-1.5 text-right tabular-nums ${Number.isFinite(q) && q !== book ? 'font-medium text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}>
                    {Number.isFinite(q) ? (q === book ? '—' : signed(q - book)) : ''}</td>}
                  <td className="p-1"><Button variant="ghost" size="icon" className="size-6" title="Убрать строку" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}><X className="size-3.5" /></Button></td>
                </tr>
              })}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-3 p-1.5">
            <Button type="button" variant="ghost" size="sm" disabled={inventory && !toId} onClick={() => setLines((ls) => [...ls, newLine()])}><Plus className="h-3.5 w-3.5 mr-1" />Добавить строку</Button>
            {inventory && <span className="text-[11px] text-muted-foreground">Строки без фактического количества в опись не войдут, их остаток не изменится. Учётное количество берётся на момент проведения.</span>}
            {receipt && <span className="ml-auto text-xs">Итого без НДС: <span className="font-mono tabular-nums font-medium">{rub.format(total)} ₽</span></span>}
            {!receipt && !inventory && <span className="text-xs text-muted-foreground">Стоимость расхода — по средней стоимости остатка склада, считается при проведении.</span>}
          </div>
        </div>

        {!inventory && <CounterpartyContractPicker companyId={companyId} value={party} onChange={setParty}
          label={op === 'receipt' ? 'Поставщик' : op === 'transfer' ? 'Контрагент (если склад чужой — подставится из карточки склада)' : 'Контрагент'} />}
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">{signFrom} (должность, ФИО)<Input aria-label={signFrom} value={responsibleFrom} onChange={(e) => setResponsibleFrom(e.target.value)}
            placeholder={needsFrom ? 'по умолчанию — МОЛ склада' : undefined} className="h-9" /></label>
          <label className="text-xs">{signTo} (должность, ФИО)<Input aria-label={signTo} value={responsibleTo} onChange={(e) => setResponsibleTo(e.target.value)}
            placeholder={needsTo ? 'по умолчанию — МОЛ склада' : undefined} className="h-9" /></label>
        </div>
        <label className="text-xs block">Основание<Input aria-label="Основание" value={basis} onChange={(e) => setBasis(e.target.value)} placeholder={inventory ? 'приказ об инвентаризации…' : 'заявка, накладная поставщика, распоряжение…'} className="h-9" /></label>
        <label className="text-xs block">Комментарий<Textarea aria-label="Комментарий" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
        {problem && <p className="text-xs text-muted-foreground">{problem}</p>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button variant="outline" disabled={!docDate || mut.isPending} onClick={() => mut.mutate(true)}
            title="Номер займётся, остатки не изменятся — провести можно позже из реестра">Сохранить черновик</Button>
          <Button disabled={!!problem || mut.isPending} onClick={() => mut.mutate(false)}>
            {mut.isPending && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Провести и распечатать</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
}
