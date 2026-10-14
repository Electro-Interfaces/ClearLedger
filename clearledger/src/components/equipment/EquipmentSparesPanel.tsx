/**
 * «ЗИП и материалы» — количественный складской учёт: запчасти к станциям и прочие
 * предметы склада (кабель, инструмент, расходные материалы). Номенклатура,
 * остатки по складам, документы и журнал движений.
 *
 * Операции оформляются документом на несколько строк (`SpareDocumentDialog`):
 * приход, отпуск на станцию, перемещение, списание, инвентаризация. Проведённый
 * документ не правится — отмена и повторная печать в реестре «Документы».
 * Отрицательный остаток запрещён сервером.
 *
 * С 14.10.2026 «Номенклатура» — общий справочник под 1С: и количественные позиции,
 * и модели станций (вид «Зарядная станция» — учёт по экземплярам в «Парке»). У
 * позиции вид, единица ОКЕИ, ставка НДС и счёт учёта. Остаток — в количестве и сумме.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, ChevronLeft, ChevronRight,
  ClipboardList, Loader2, Package, Pencil, Plus, Search, Trash2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Kpi } from '@/components/workspace/analytics/Kpi'
import { ApiError } from '@/services/apiClient'
import {
  SPARE_CATEGORY_META, SPARE_DOC_META, SPARE_STATION_CATEGORIES,
  createSparePart, deleteSparePart, getAccountingMeta, getWarehousesSummary,
  listSpareMovements, listSpareParts, updateSparePart,
  type NomenclatureKind, type SpareDocOp, type SpareMovementRow, type SparePart, type SparePartPayload,
} from '@/services/equipmentService'
import { SpareDocumentDialog } from './SpareDocumentDialog'
import { SpareDocumentsSection } from './SpareDocumentsSection'
import { ruDate, signed, spareTarget } from './spareDocPrint'
import { invalidateEquipment } from './useEquipmentScope'

// ─── локальные справочники / утилиты ────────────────────────────────────────

/** Операции журнала движений (инвентаризация и отмена пишутся корректировкой). */
const MOVE_LABELS: Record<string, string> = {
  receipt: 'Приход', issue: 'Отпуск на станцию', transfer: 'Перемещение',
  write_off: 'Списание', correction: 'Корректировка',
}
const DOC_ICONS: Record<SpareDocOp, typeof Package> = {
  receipt: ArrowDownToLine, issue: ArrowUpFromLine, transfer: ArrowLeftRight,
  write_off: Trash2, inventory: ClipboardList,
}
/** Отбор по назначению: запчасти к станциям или прочие предметы склада. */
const GROUPS: Record<string, string> = { 'g:station': 'Запчасти к станциям', 'g:other': 'Прочие предметы' }
const inCategory = (p: SparePart, cat: string) =>
  cat === 'all' || (cat in GROUPS ? SPARE_STATION_CATEGORIES.includes(p.category) === (cat === 'g:station') : p.category === cat)

const nfQty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const nfRub = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const catLabel = (c: string) => SPARE_CATEGORY_META[c] ?? c

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}

/** Нейтральный zinc-бейдж (категории, операции — вторичная информация). */
const ZINC_BADGE = 'border-zinc-400/60 text-zinc-500 dark:border-zinc-600 dark:text-zinc-400'

function CategoryBadge({ category }: { category: string }) {
  return <Badge variant="outline" className={`text-[11px] ${ZINC_BADGE}`}>{catLabel(category)}</Badge>
}

/** Поле формы: подпись + контрол. */
function FField({ label, required, span, children }: {
  label: string; required?: boolean; span?: boolean; children: React.ReactNode
}) {
  return (
    <div className={`space-y-1.5 ${span ? 'col-span-2' : ''}`}>
      <Label className="text-xs text-muted-foreground">
        {label}{required && <span className="text-destructive"> *</span>}
      </Label>
      {children}
    </div>
  )
}

/** Строка таблицы с ошибкой запроса: сбой не должен выглядеть пустым списком. */
function ErrorRow({ cols, error }: { cols: number; error: unknown }) {
  return (
    <TableRow><TableCell colSpan={cols} role="alert" className="h-20 text-center text-destructive">
      Данные не загрузились: {errMsg(error)}
    </TableCell></TableRow>
  )
}

// ─── главная панель ──────────────────────────────────────────────────────────

type TabId = 'stock' | 'parts' | 'docs' | 'movements'
const TABS: { id: TabId; label: string }[] = [
  { id: 'stock', label: 'Остатки' },
  { id: 'parts', label: 'Номенклатура' },
  { id: 'docs', label: 'Документы' },
  { id: 'movements', label: 'Движения' },
]

export function EquipmentSparesPanel({ companyId }: { companyId: string }) {
  const [tab, setTab] = useState<TabId>('stock')
  const [docDlg, setDocDlg] = useState<{ op: SpareDocOp; partId?: string } | null>(null)

  // Один запрос со всей номенклатурой (включая архив) — фильтры клиентские:
  // объём справочника мал, зато поиск мгновенный и KPI без второго запроса.
  const partsQ = useQuery({
    queryKey: ['equipment', 'spares', companyId, 'all'],
    queryFn: () => listSpareParts({ companyId, includeArchived: true, includeSerial: true }),
  })
  const allParts = useMemo(() => partsQ.data ?? [], [partsQ.data])
  // Остатки и документы ЗИП — только количественная номенклатура; модели станций
  // учитываются экземплярами в «Парке» и живут здесь лишь в справочнике.
  const parts = useMemo(() => allParts.filter((p) => !p.serial), [allParts])
  const activeParts = useMemo(() => parts.filter((p) => !p.isArchived), [parts])

  const kpi = useMemo(() => {
    const totalAmount = activeParts.reduce((s, p) => s + (p.totalAmount ?? 0), 0)
    const wh = new Set<string>()
    for (const p of activeParts) for (const b of p.byLocation) if (b.qty > 0) wh.add(b.locationId)
    return {
      positions: activeParts.length,
      totalAmount,
      warehouses: wh.size,
      zero: activeParts.filter((p) => p.totalQty <= 0).length,
    }
  }, [activeParts])

  return (
    <div className="space-y-4 p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Позиций" value={nfQty.format(kpi.positions)} sub="активная номенклатура" />
        <Kpi label="Сумма остатка, ₽" value={nfRub.format(kpi.totalAmount)} sub="без НДС, по средней" />
        <Kpi label="Складов с остатком" value={nfQty.format(kpi.warehouses)} sub="запчасти и материалы" />
        <Kpi label="Нулевой остаток" value={nfQty.format(kpi.zero)} sub="позиций без остатка" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5">
          {TABS.map((t) => (
            <button key={t.id} type="button" onClick={() => setTab(t.id)}
              className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${
                tab === t.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
              }`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {(Object.keys(SPARE_DOC_META) as SpareDocOp[]).map((op) => {
            const Icon = DOC_ICONS[op]
            return (
              <Button key={op} variant="outline" size="sm" className="h-8" title={SPARE_DOC_META[op].title}
                disabled={activeParts.length === 0} onClick={() => setDocDlg({ op })}>
                <Icon className="size-3.5 mr-1" /> {SPARE_DOC_META[op].label}
              </Button>
            )
          })}
        </div>
      </div>

      {tab === 'stock' && (
        <StockTab parts={activeParts} loading={partsQ.isLoading} error={partsQ.error}
          onDoc={(op, partId) => setDocDlg({ op, partId })} />
      )}
      {tab === 'parts' && <PartsTab companyId={companyId} parts={allParts} loading={partsQ.isLoading} error={partsQ.error} />}
      {tab === 'docs' && <SpareDocumentsSection companyId={companyId} />}
      {tab === 'movements' && <MovementsTab companyId={companyId} parts={parts} />}

      {docDlg && (
        <SpareDocumentDialog companyId={companyId} op={docDlg.op} parts={parts}
          presetPartId={docDlg.partId} onClose={() => setDocDlg(null)} />
      )}
    </div>
  )
}

/** Отбор по категории: сначала две группы, затем сами категории. */
function CategorySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-9 w-[210px]"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="all">Все категории</SelectItem>
        {Object.entries({ ...GROUPS, ...SPARE_CATEGORY_META }).map(([k, v]) => (
          <SelectItem key={k} value={k}>{v}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

// ─── вкладка «Остатки» ───────────────────────────────────────────────────────

function StockTab({ parts, loading, error, onDoc }: {
  parts: SparePart[]
  loading: boolean
  error: unknown
  onDoc: (op: SpareDocOp, partId: string) => void
}) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    return parts.filter((p) => {
      if (!inCategory(p, cat)) return false
      if (!s) return true
      return [p.name, p.article, p.vendor, p.compatibleModels]
        .some((v) => v && v.toLowerCase().includes(s))
    })
  }, [parts, q, cat])

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input placeholder="Поиск: название, артикул, вендор…" value={q}
            onChange={(e) => setQ(e.target.value)} className="pl-8 h-9" />
        </div>
        <CategorySelect value={cat} onChange={setCat} />
        <span className="text-[11px] text-muted-foreground whitespace-nowrap">
          Позиций: {filtered.length}{filtered.length !== parts.length && ` из ${parts.length}`}
        </span>
      </div>

      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px]">Номенклатура</TableHead>
              <TableHead className="w-[150px]">Категория</TableHead>
              <TableHead className="w-[120px]">Вендор</TableHead>
              <TableHead className="w-[170px]">Совместимость</TableHead>
              <TableHead className="min-w-[200px]">Остатки по складам</TableHead>
              <TableHead className="w-[100px] text-right">Итого</TableHead>
              <TableHead className="w-[120px] text-right">Сумма, ₽</TableHead>
              <TableHead className="w-[240px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!!error && <ErrorRow cols={8} error={error} />}
            {!loading && !error && parts.length === 0 && (
              <TableRow><TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                <Package className="size-5 mx-auto mb-1.5 opacity-50" />
                Номенклатуры пока нет — добавьте позиции на вкладке «Номенклатура»
              </TableCell></TableRow>
            )}
            {!loading && parts.length > 0 && filtered.length === 0 && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                Ничего не найдено
              </TableCell></TableRow>
            )}
            {filtered.map((p) => {
              const stocks = p.byLocation.filter((b) => b.qty !== 0)
              return (
                <TableRow key={p.id}>
                  <TableCell>
                    <div className="text-sm font-medium">{p.name}</div>
                    {p.article && <div className="text-[11px] text-muted-foreground">{p.article}</div>}
                  </TableCell>
                  <TableCell><CategoryBadge category={p.category} /></TableCell>
                  <TableCell className="text-sm">{p.vendor || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[170px] truncate"
                    title={p.compatibleModels ?? undefined}>
                    {p.compatibleModels || '—'}
                  </TableCell>
                  <TableCell>
                    {stocks.length === 0
                      ? <span className="text-sm text-muted-foreground">—</span>
                      : (
                        <div className="flex flex-wrap gap-1">
                          {stocks.map((b) => (
                            <Badge key={b.locationId} variant="outline"
                              className={`text-[11px] font-normal ${ZINC_BADGE}`}>
                              {b.locationName}: {nfQty.format(b.qty)}
                            </Badge>
                          ))}
                        </div>
                      )}
                  </TableCell>
                  <TableCell className={`text-right text-sm tabular-nums whitespace-nowrap ${
                    p.totalQty <= 0 ? 'text-muted-foreground' : 'font-medium'
                  }`}>
                    {nfQty.format(p.totalQty)} <span className="text-[11px] text-muted-foreground">{p.unitLabel}</span>
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums whitespace-nowrap">
                    {p.totalAmount ? nfRub.format(p.totalAmount) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-0.5 whitespace-nowrap">
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onDoc('receipt', p.id)}>
                        <ArrowDownToLine className="size-3.5 mr-1" /> Приход
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onDoc('issue', p.id)}>
                        <ArrowUpFromLine className="size-3.5 mr-1" /> Отпуск
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onDoc('transfer', p.id)}>
                        <ArrowLeftRight className="size-3.5 mr-1" /> Переместить
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ─── вкладка «Номенклатура» (CRUD) ──────────────────────────────────────────

function PartsTab({ companyId, parts, loading, error }: {
  companyId: string
  parts: SparePart[]
  loading: boolean
  error: unknown
}) {
  const [showArchived, setShowArchived] = useState(false)
  const [cat, setCat] = useState('all')
  const [kind, setKind] = useState('all')
  const metaQ = useQuery({ queryKey: ['equipment', 'accounting-meta'], queryFn: getAccountingMeta, staleTime: Infinity })
  const shown = useMemo(
    () => parts.filter((p) => (showArchived || !p.isArchived) && (p.serial || inCategory(p, cat))
      && (kind === 'all' || p.kind === kind)),
    [parts, showArchived, cat, kind],
  )

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <SparePartFormDialog companyId={companyId}>
          <Button size="sm"><Plus className="size-4 mr-1.5" /> Добавить позицию</Button>
        </SparePartFormDialog>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-9 w-[230px]" aria-label="Вид номенклатуры"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все виды</SelectItem>
            {Object.entries(metaQ.data?.kinds ?? {}).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <CategorySelect value={cat} onChange={setCat} />
        <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <Switch size="sm" checked={showArchived} onCheckedChange={setShowArchived} />
          Показывать архив
        </label>
      </div>

      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px]">Наименование</TableHead>
              <TableHead className="w-[170px]">Вид · категория</TableHead>
              <TableHead className="w-[120px]">Вендор</TableHead>
              <TableHead className="w-[110px]">Артикул</TableHead>
              <TableHead className="w-[80px]">Ед. изм.</TableHead>
              <TableHead className="w-[80px]">НДС</TableHead>
              <TableHead className="w-[80px]">Счёт</TableHead>
              <TableHead className="w-[80px]">Статус</TableHead>
              <TableHead className="w-[90px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={9} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!!error && <ErrorRow cols={9} error={error} />}
            {!loading && !error && shown.length === 0 && (
              <TableRow><TableCell colSpan={9} className="h-20 text-center text-muted-foreground">
                {parts.length ? 'Ничего не найдено' : 'Номенклатуры пока нет'}
              </TableCell></TableRow>
            )}
            {shown.map((p) => (
              <TableRow key={p.id} className={p.isArchived ? 'opacity-60' : ''}>
                <TableCell>
                  <div className="text-sm font-medium">{p.name}</div>
                  {p.compatibleModels && (
                    <div className="text-[11px] text-muted-foreground max-w-[240px] truncate"
                      title={p.compatibleModels}>
                      {p.compatibleModels}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <div className="text-xs">{p.kindLabel || 'Запчасти (ЗИП)'}</div>
                  {p.serial
                    ? <div className="text-xs text-muted-foreground">{p.units ? `${p.units} ед. в парке` : 'учёт по экземплярам'}</div>
                    : <CategoryBadge category={p.category} />}
                </TableCell>
                <TableCell className="text-sm">{p.vendor || '—'}</TableCell>
                <TableCell className="text-sm">{p.article || '—'}</TableCell>
                <TableCell className="text-sm">{p.unitLabel}</TableCell>
                <TableCell className="text-sm">{p.vatRate || '—'}</TableCell>
                <TableCell className="font-mono text-xs">{p.account || '—'}</TableCell>
                <TableCell>
                  {p.isArchived
                    ? <Badge variant="outline" className="text-[11px] border-zinc-600 text-zinc-500">архив</Badge>
                    : <span className="text-xs text-muted-foreground">—</span>}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-0.5">
                    <SparePartFormDialog companyId={companyId} edit={p}>
                      <Button variant="ghost" size="icon" className="size-7" title="Редактировать">
                        <Pencil className="size-3.5" />
                      </Button>
                    </SparePartFormDialog>
                    <DeletePartButton companyId={companyId} part={p} />
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

/** Форма номенклатуры (создание/правка). Состояние сбрасывается при открытии. */
function SparePartFormDialog({ companyId, edit, children }: {
  companyId: string
  edit?: SparePart
  children: React.ReactNode
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const metaQ = useQuery({ queryKey: ['equipment', 'accounting-meta'], queryFn: getAccountingMeta, staleTime: Infinity })
  const meta = metaQ.data
  const initial = () => ({
    name: edit?.name ?? '',
    category: edit?.category ?? 'other',
    vendor: edit?.vendor ?? '',
    article: edit?.article ?? '',
    compatibleModels: edit?.compatibleModels ?? '',
    unitLabel: edit?.unitLabel ?? 'шт',
    notes: edit?.notes ?? '',
    kind: (edit?.kind ?? 'spare') as NomenclatureKind,
    model: edit?.model ?? '',
    unitCode: edit?.unitCode ?? '796',
    vatRate: edit?.vatRate ?? '20%',
    account: edit?.account ?? '',
    bpRef: edit?.bpRef ?? '',
  })
  const [f, setF] = useState(initial)
  const set = (k: keyof ReturnType<typeof initial>) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setF((s) => ({ ...s, [k]: e.target.value }))
  const serial = !!meta?.kinds[f.kind]?.serial
  // Совместимость с моделями станций имеет смысл только у запчастей к станциям.
  const forStation = !serial && SPARE_STATION_CATEGORIES.includes(f.category)
  // Вид задаёт счёт по умолчанию, как «Счета учёта номенклатуры» в 1С.
  const setKind = (k: string) => setF((s) => ({
    ...s, kind: k as NomenclatureKind, account: meta?.kinds[k as NomenclatureKind]?.account ?? s.account,
    unitCode: meta?.kinds[k as NomenclatureKind]?.serial ? '796' : s.unitCode,
  }))

  const mut = useMutation({
    mutationFn: (body: SparePartPayload) =>
      edit ? updateSparePart(companyId, edit.id, body) : createSparePart(companyId, body),
    onSuccess: () => {
      toast.success(edit ? 'Номенклатура обновлена' : 'Позиция добавлена')
      void invalidateEquipment(qc)
      setOpen(false)
    },
    onError: (e) => toast.error(errMsg(e)),
  })

  function save() {
    mut.mutate({
      name: f.name.trim(),
      category: f.category,
      vendor: f.vendor.trim() || null,
      article: f.article.trim() || null,
      compatibleModels: f.compatibleModels.trim() || null,
      unitLabel: meta?.okei[f.unitCode] ?? (f.unitLabel.trim() || 'шт'),
      notes: f.notes.trim() || null,
      kind: f.kind,
      model: serial ? f.model.trim() || null : null,
      unitCode: f.unitCode,
      vatRate: f.vatRate || null,
      account: f.account || null,
      bpRef: f.bpRef.trim() || null,
    })
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v) setF(initial()) }}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60!">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="size-5" /> {edit ? 'Изменить позицию' : 'Новая позиция'}
          </DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
          <FField label="Вид номенклатуры" required>
            <Select value={f.kind} onValueChange={setKind}>
              <SelectTrigger aria-label="Вид номенклатуры"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(meta?.kinds ?? {}).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </FField>
          {serial ? (
            <FField label="Модель">
              <Input value={f.model} onChange={set('model')} placeholder="DC60, AC22…" />
            </FField>
          ) : (
            <FField label="Категория">
              <Select value={f.category} onValueChange={(v) => setF((s) => ({ ...s, category: v }))}>
                <SelectTrigger aria-label="Категория"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(SPARE_CATEGORY_META).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FField>
          )}
          <FField label="Наименование" required span>
            <Input value={f.name} onChange={set('name')}
              placeholder={serial ? 'Станция Фора 150 кВт DC' : forStation ? 'Силовой модуль 30 кВт…' : 'Кабель ВВГнг 5×10, набор ключей, стяжки…'} />
          </FField>
          <FField label="Единица измерения (ОКЕИ)">
            <Select value={f.unitCode} onValueChange={(v) => setF((s) => ({ ...s, unitCode: v }))} disabled={serial}>
              <SelectTrigger aria-label="Единица измерения"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(meta?.okei ?? {}).map(([k, v]) => <SelectItem key={k} value={k}>{v} · {k}</SelectItem>)}
              </SelectContent>
            </Select>
          </FField>
          <FField label="Ставка НДС">
            <Select value={f.vatRate} onValueChange={(v) => setF((s) => ({ ...s, vatRate: v }))}>
              <SelectTrigger aria-label="Ставка НДС"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(meta?.vatRates ?? []).map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          </FField>
          <FField label="Счёт учёта">
            <Select value={f.account || meta?.kinds[f.kind]?.account || ''} onValueChange={(v) => setF((s) => ({ ...s, account: v }))}>
              <SelectTrigger aria-label="Счёт учёта"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(meta?.accounts ?? {}).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          </FField>
          <FField label="Ссылка (GUID) в 1С">
            <Input value={f.bpRef} onChange={set('bpRef')} placeholder="заполняется выгрузкой" className="font-mono" />
          </FField>
          <FField label="Вендор">
            <Input value={f.vendor} onChange={set('vendor')} placeholder={forStation ? 'Sicon, ABB…' : ''} />
          </FField>
          <FField label="Артикул">
            <Input value={f.article} onChange={set('article')} />
          </FField>
          {serial && (
            <p className="col-span-2 text-xs text-muted-foreground">
              Станции и оборудование учитываются по экземплярам: каждая единица с серийным номером — в «Парке»,
              на складе на счёте {f.account || '07'}, в монтаже — 08.03, после ввода — основное средство 01.01.
            </p>
          )}
          {forStation && (
            <FField label="Совместимые модели" span>
              <Textarea value={f.compatibleModels} onChange={set('compatibleModels')} rows={2}
                placeholder="Перечень моделей станций через запятую" />
            </FField>
          )}
          <FField label="Примечание" span>
            <Textarea value={f.notes} onChange={set('notes')} rows={2} />
          </FField>
        </div>
        <DialogFooter>
          <Button disabled={f.name.trim() === '' || mut.isPending} onClick={save}>
            {mut.isPending && <Loader2 className="size-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
        {metaQ.isError && <p role="alert" className="text-xs text-destructive">Справочники учёта не загрузились — вид, единица и счёт недоступны.</p>}
      </DialogContent>
    </Dialog>
  )
}

/** Удаление: при наличии движений бэк переводит позицию в архив (archived+reason). */
function DeletePartButton({ companyId, part }: { companyId: string; part: SparePart }) {
  const qc = useQueryClient()
  const del = useMutation({
    mutationFn: () => deleteSparePart(companyId, part.id),
    onSuccess: (res) => {
      if (res.archived) toast.warning(`«${part.name}»: ${res.reason ?? 'номенклатура отправлена в архив'}`)
      else toast.success('Позиция удалена')
      void invalidateEquipment(qc)
    },
    onError: (e) => toast.error(errMsg(e)),
  })
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon" className="size-7" title="Удалить">
          <Trash2 className="size-3.5 text-destructive" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Удалить позицию «{part.name}»?</AlertDialogTitle>
          <AlertDialogDescription>
            Если по позиции есть движения — она не удалится, а уйдёт в архив (история сохранится).
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate()}>Удалить</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// ─── вкладка «Движения» ─────────────────────────────────────────────────────

const MOVES_PAGE_SIZE = 50

function qtyCell(m: SpareMovementRow) {
  const n = nfQty.format(m.qty)
  const unit = <span className="text-[11px] text-muted-foreground"> {m.part.unitLabel}</span>
  const plus = 'text-emerald-600/90 dark:text-emerald-400/80'
  const minus = 'text-red-600/90 dark:text-red-400/80'
  switch (m.op) {
    case 'receipt':
      return <span className={plus}>+{n}{unit}</span>
    case 'issue':
    case 'write_off':
      return <span className={minus}>−{n}{unit}</span>
    case 'transfer':
      return <span className="text-muted-foreground">{n}{unit} →</span>
    default: // корректировка: изменение остатка; у записей до перехода на документы — установленный остаток
      return m.delta == null
        ? <span className="text-muted-foreground">= {n}{unit}</span>
        : <span className={m.delta < 0 ? minus : plus}>{signed(m.delta)}{unit}</span>
  }
}

function MovementsTab({ companyId, parts }: { companyId: string; parts: SparePart[] }) {
  const [partId, setPartId] = useState('all')
  const [whId, setWhId] = useState('all')
  const [op, setOp] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const pick = (set: (v: string) => void) => (v: string) => { set(v); setPage(1) }
  const any = (v: string) => (v === 'all' ? undefined : v)

  const whQ = useQuery({ queryKey: ['equipment', 'warehouses-summary', companyId], queryFn: () => getWarehousesSummary(companyId), staleTime: 60_000 })
  const { data, isLoading, error } = useQuery({
    queryKey: ['equipment', 'spare-movements', companyId, partId, whId, op, dateFrom, dateTo, page],
    queryFn: () => listSpareMovements({
      companyId, partId: any(partId), locationId: any(whId), op: any(op),
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      page, pageSize: MOVES_PAGE_SIZE,
    }),
    placeholderData: (prev) => prev,
  })
  const items = data?.items ?? []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / MOVES_PAGE_SIZE))

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Период:
          <Input type="date" value={dateFrom} className="h-9 w-[150px]"
            onChange={(e) => pick(setDateFrom)(e.target.value)} />
          —
          <Input type="date" value={dateTo} className="h-9 w-[150px]"
            onChange={(e) => pick(setDateTo)(e.target.value)} />
        </label>
        <Select value={whId} onValueChange={pick(setWhId)}>
          <SelectTrigger className="h-9 w-[200px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{whQ.isError ? 'Склады не загрузились' : 'Все склады'}</SelectItem>
            {(whQ.data?.warehouses ?? []).map((w) => (
              <SelectItem key={w.location.id} value={w.location.id}>{w.location.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={op} onValueChange={pick(setOp)}>
          <SelectTrigger className="h-9 w-[180px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все операции</SelectItem>
            {Object.entries(MOVE_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={partId} onValueChange={pick(setPartId)}>
          <SelectTrigger className="h-9 w-[240px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Вся номенклатура</SelectItem>
            {parts.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}{p.isArchived ? ' (архив)' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-muted-foreground whitespace-nowrap">Движений: {total}</span>
      </div>

      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[100px]">Дата</TableHead>
              <TableHead className="w-[150px]">Операция</TableHead>
              <TableHead className="w-[130px]">Документ</TableHead>
              <TableHead className="min-w-[180px]">Номенклатура</TableHead>
              <TableHead className="w-[110px] text-right">Кол-во</TableHead>
              <TableHead className="min-w-[160px]">Склад</TableHead>
              <TableHead className="min-w-[160px]">Получатель</TableHead>
              <TableHead className="min-w-[130px]">Основание</TableHead>
              <TableHead className="w-[140px]">Кто</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow><TableCell colSpan={9} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!!error && <ErrorRow cols={9} error={error} />}
            {!isLoading && !error && items.length === 0 && (
              <TableRow><TableCell colSpan={9} className="h-20 text-center text-muted-foreground">
                Движений нет
              </TableCell></TableRow>
            )}
            {!error && items.map((m) => {
              const target = spareTarget({ targetUnit: m.targetUnit ?? null, targetLocation: m.targetLocation?.name ?? null, targetNote: m.targetNote ?? null })
              return (
                <TableRow key={m.id}>
                  <TableCell className="text-sm whitespace-nowrap">{ruDate(m.occurredOn)}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[11px] ${ZINC_BADGE}`}>
                      {MOVE_LABELS[m.op] ?? m.op}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs whitespace-nowrap">{m.documentNumber || '—'}</TableCell>
                  <TableCell className="text-sm">{m.part.name}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums whitespace-nowrap">
                    {qtyCell(m)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {!m.fromLocation && !m.toLocation
                      ? <span className="text-muted-foreground">—</span>
                      : [m.fromLocation?.name, m.toLocation?.name].filter(Boolean).join(' → ')}
                  </TableCell>
                  <TableCell className="text-sm">
                    {target || <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[180px] truncate"
                    title={[m.basis, m.comment].filter(Boolean).join(' · ') || undefined}>
                    {m.basis || m.comment || '—'}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground truncate max-w-[140px]">
                    {m.createdBy || '—'}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-[11px] text-muted-foreground">
            {(page - 1) * MOVES_PAGE_SIZE + 1}–{Math.min(page * MOVES_PAGE_SIZE, total)} из {total}
          </span>
          <Button variant="outline" size="icon" className="size-7" disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft className="size-4" />
          </Button>
          <Button variant="outline" size="icon" className="size-7" disabled={page >= pages}
            onClick={() => setPage((p) => p + 1)}>
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
