/**
 * «ЗИП и запчасти» — количественный складской учёт запчастей ЭЗС (energy):
 * номенклатура + материализованные остатки по складам + журнал движений.
 * Три вкладки: Остатки · Номенклатура · Движения.
 *
 * Расход (issue) опционально привязывается к станции-единице (targetUnitId,
 * поиск по серийнику через listUnits) или площадке ev_charging
 * (targetLocationId). Корректировка = установка фактического остатка на
 * складе (qty — устанавливаемое значение, комментарий обязателен).
 * Отрицательный остаток запрещён бэком (409 «Недостаточно остатка…»).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, ChevronLeft, ChevronRight,
  Loader2, Package, Pencil, Plus, Search, Trash2, X,
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
import { getLocations } from '@/services/locationService'
import {
  SPARE_CATEGORY_META,
  applySpareMovement, createSparePart, deleteSparePart,
  listSpareMovements, listSpareParts, listUnits, updateSparePart,
  type SpareMovementPayload, type SpareMovementRow, type SparePart, type SparePartPayload,
} from '@/services/equipmentService'

// ─── локальные справочники / утилиты ────────────────────────────────────────

type SpareOp = SpareMovementPayload['op']

const OP_LABELS: Record<SpareOp, string> = {
  receipt: 'Приход', issue: 'Расход', transfer: 'Перемещение',
  write_off: 'Списание', correction: 'Корректировка',
}

const nfQty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const catLabel = (c: string) => SPARE_CATEGORY_META[c] ?? c
const todayIso = () => new Date().toISOString().slice(0, 10)

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

// ─── главная панель ──────────────────────────────────────────────────────────

type TabId = 'stock' | 'parts' | 'movements'
const TABS: { id: TabId; label: string }[] = [
  { id: 'stock', label: 'Остатки' },
  { id: 'parts', label: 'Номенклатура' },
  { id: 'movements', label: 'Движения' },
]

export function EquipmentSparesPanel({ companyId }: { companyId: string }) {
  const [tab, setTab] = useState<TabId>('stock')
  const [movDlg, setMovDlg] = useState<{ part: SparePart; op: SpareOp } | null>(null)

  // Один запрос со всей номенклатурой (включая архив) — фильтры клиентские:
  // объём справочника ЗИП мал, зато поиск мгновенный и KPI без второго запроса.
  const { data: parts = [], isLoading } = useQuery({
    queryKey: ['eq-spares', companyId],
    queryFn: () => listSpareParts({ companyId, includeArchived: true }),
  })
  const activeParts = useMemo(() => parts.filter((p) => !p.isArchived), [parts])

  const kpi = useMemo(() => {
    const totalQty = activeParts.reduce((s, p) => s + p.totalQty, 0)
    const wh = new Set<string>()
    for (const p of activeParts) for (const b of p.byLocation) if (b.qty > 0) wh.add(b.locationId)
    return {
      positions: activeParts.length,
      totalQty,
      warehouses: wh.size,
      zero: activeParts.filter((p) => p.totalQty <= 0).length,
    }
  }, [activeParts])

  return (
    <div className="space-y-4 p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Позиций" value={nfQty.format(kpi.positions)} sub="активная номенклатура" />
        <Kpi label="Суммарный остаток" value={nfQty.format(kpi.totalQty)} sub="сумма в разных ед. изм." />
        <Kpi label="Складов с ЗИП" value={nfQty.format(kpi.warehouses)} sub="с ненулевым остатком" />
        <Kpi label="Нулевой остаток" value={nfQty.format(kpi.zero)} sub="позиций без остатка" />
      </div>

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

      {tab === 'stock' && (
        <StockTab parts={activeParts} loading={isLoading}
          onMove={(part, op) => setMovDlg({ part, op })} />
      )}
      {tab === 'parts' && <PartsTab companyId={companyId} parts={parts} loading={isLoading} />}
      {tab === 'movements' && <MovementsTab companyId={companyId} parts={parts} />}

      {movDlg && (
        <SpareMovementDialog companyId={companyId} part={movDlg.part}
          initialOp={movDlg.op} onClose={() => setMovDlg(null)} />
      )}
    </div>
  )
}

// ─── вкладка «Остатки» ───────────────────────────────────────────────────────

function StockTab({ parts, loading, onMove }: {
  parts: SparePart[]
  loading: boolean
  onMove: (part: SparePart, op: SpareOp) => void
}) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('all')

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    return parts.filter((p) => {
      if (cat !== 'all' && p.category !== cat) return false
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
        <Select value={cat} onValueChange={setCat}>
          <SelectTrigger className="h-9 w-[190px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все категории</SelectItem>
            {Object.entries(SPARE_CATEGORY_META).map(([k, v]) => (
              <SelectItem key={k} value={k}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-[11px] text-muted-foreground whitespace-nowrap">
          Позиций: {filtered.length}{filtered.length !== parts.length && ` из ${parts.length}`}
        </span>
      </div>

      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px]">Номенклатура</TableHead>
              <TableHead className="w-[130px]">Категория</TableHead>
              <TableHead className="w-[120px]">Вендор</TableHead>
              <TableHead className="w-[170px]">Совместимость</TableHead>
              <TableHead className="min-w-[200px]">Остатки по складам</TableHead>
              <TableHead className="w-[100px] text-right">Итого</TableHead>
              <TableHead className="w-[240px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!loading && parts.length === 0 && (
              <TableRow><TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                <Package className="size-5 mx-auto mb-1.5 opacity-50" />
                Номенклатуры ЗИП пока нет — добавьте позиции на вкладке «Номенклатура»
              </TableCell></TableRow>
            )}
            {!loading && parts.length > 0 && filtered.length === 0 && (
              <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">
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
                  <TableCell>
                    <div className="flex justify-end gap-0.5 whitespace-nowrap">
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onMove(p, 'receipt')}>
                        <ArrowDownToLine className="size-3.5 mr-1" /> Приход
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onMove(p, 'issue')}>
                        <ArrowUpFromLine className="size-3.5 mr-1" /> Расход
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                        onClick={() => onMove(p, 'transfer')}>
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

function PartsTab({ companyId, parts, loading }: {
  companyId: string
  parts: SparePart[]
  loading: boolean
}) {
  const [showArchived, setShowArchived] = useState(false)
  const shown = useMemo(
    () => (showArchived ? parts : parts.filter((p) => !p.isArchived)),
    [parts, showArchived],
  )

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SparePartFormDialog companyId={companyId}>
          <Button size="sm"><Plus className="size-4 mr-1.5" /> Добавить позицию</Button>
        </SparePartFormDialog>
        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
          <Switch size="sm" checked={showArchived} onCheckedChange={setShowArchived} />
          Показывать архив
        </label>
      </div>

      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px]">Наименование</TableHead>
              <TableHead className="w-[130px]">Категория</TableHead>
              <TableHead className="w-[120px]">Вендор</TableHead>
              <TableHead className="w-[110px]">Артикул</TableHead>
              <TableHead className="w-[80px]">Ед. изм.</TableHead>
              <TableHead className="min-w-[160px]">Примечание</TableHead>
              <TableHead className="w-[80px]">Статус</TableHead>
              <TableHead className="w-[90px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!loading && shown.length === 0 && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                Номенклатуры ЗИП пока нет
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
                <TableCell><CategoryBadge category={p.category} /></TableCell>
                <TableCell className="text-sm">{p.vendor || '—'}</TableCell>
                <TableCell className="text-sm">{p.article || '—'}</TableCell>
                <TableCell className="text-sm">{p.unitLabel}</TableCell>
                <TableCell className="text-xs text-muted-foreground max-w-[220px] truncate"
                  title={p.notes ?? undefined}>
                  {p.notes || '—'}
                </TableCell>
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
  const initial = () => ({
    name: edit?.name ?? '',
    category: edit?.category ?? 'other',
    vendor: edit?.vendor ?? '',
    article: edit?.article ?? '',
    compatibleModels: edit?.compatibleModels ?? '',
    unitLabel: edit?.unitLabel ?? 'шт',
    notes: edit?.notes ?? '',
  })
  const [f, setF] = useState(initial)
  const set = (k: keyof ReturnType<typeof initial>) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setF((s) => ({ ...s, [k]: e.target.value }))

  const mut = useMutation({
    mutationFn: (body: SparePartPayload) =>
      edit ? updateSparePart(companyId, edit.id, body) : createSparePart(companyId, body),
    onSuccess: () => {
      toast.success(edit ? 'Номенклатура обновлена' : 'Позиция добавлена')
      qc.invalidateQueries({ queryKey: ['eq-spares'] })
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
      unitLabel: f.unitLabel.trim() || 'шт',
      notes: f.notes.trim() || null,
    })
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v) setF(initial()) }}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60!">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="size-5" /> {edit ? 'Изменить позицию ЗИП' : 'Новая позиция ЗИП'}
          </DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
          <FField label="Наименование" required span>
            <Input value={f.name} onChange={set('name')} placeholder="Силовой модуль 30 кВт…" />
          </FField>
          <FField label="Категория">
            <Select value={f.category} onValueChange={(v) => setF((s) => ({ ...s, category: v }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(SPARE_CATEGORY_META).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FField>
          <FField label="Ед. измерения">
            <Input value={f.unitLabel} onChange={set('unitLabel')} placeholder="шт" />
          </FField>
          <FField label="Вендор">
            <Input value={f.vendor} onChange={set('vendor')} placeholder="Sicon, ABB…" />
          </FField>
          <FField label="Артикул">
            <Input value={f.article} onChange={set('article')} />
          </FField>
          <FField label="Совместимые модели" span>
            <Textarea value={f.compatibleModels} onChange={set('compatibleModels')} rows={2}
              placeholder="Перечень моделей станций через запятую" />
          </FField>
          <FField label="Примечание" span>
            <Textarea value={f.notes} onChange={set('notes')} rows={2} />
          </FField>
        </div>
        <DialogFooter>
          <Button disabled={f.name.trim() === '' || mut.isPending} onClick={save}>
            {mut.isPending && <Loader2 className="size-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
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
      qc.invalidateQueries({ queryKey: ['eq-spares'] })
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
  switch (m.op) {
    case 'receipt':
      return <span className="text-emerald-600/90 dark:text-emerald-400/80">+{n}{unit}</span>
    case 'issue':
    case 'write_off':
      return <span className="text-red-600/90 dark:text-red-400/80">−{n}{unit}</span>
    case 'transfer':
      return <span className="text-muted-foreground">{n}{unit} →</span>
    default: // correction: установлен фактический остаток
      return <span className="text-muted-foreground">= {n}{unit}</span>
  }
}

function MovementsTab({ companyId, parts }: { companyId: string; parts: SparePart[] }) {
  const [partId, setPartId] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: ['eq-spare-movements', companyId, partId, dateFrom, dateTo, page],
    queryFn: () => listSpareMovements({
      companyId,
      partId: partId === 'all' ? undefined : partId,
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
            onChange={(e) => { setDateFrom(e.target.value); setPage(1) }} />
          —
          <Input type="date" value={dateTo} className="h-9 w-[150px]"
            onChange={(e) => { setDateTo(e.target.value); setPage(1) }} />
        </label>
        <Select value={partId} onValueChange={(v) => { setPartId(v); setPage(1) }}>
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
              <TableHead className="w-[130px]">Операция</TableHead>
              <TableHead className="min-w-[180px]">Номенклатура</TableHead>
              <TableHead className="w-[110px] text-right">Кол-во</TableHead>
              <TableHead className="min-w-[180px]">Откуда → Куда</TableHead>
              <TableHead className="min-w-[140px]">Станция / площадка</TableHead>
              <TableHead className="min-w-[130px]">Основание</TableHead>
              <TableHead className="w-[140px]">Кто</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                <Loader2 className="size-4 animate-spin inline-block" />
              </TableCell></TableRow>
            )}
            {!isLoading && items.length === 0 && (
              <TableRow><TableCell colSpan={8} className="h-20 text-center text-muted-foreground">
                Движений пока нет
              </TableCell></TableRow>
            )}
            {items.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="text-sm whitespace-nowrap">{m.occurredOn}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={`text-[11px] ${ZINC_BADGE}`}>
                    {OP_LABELS[m.op as SpareOp] ?? m.op}
                  </Badge>
                </TableCell>
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
                  {m.targetUnitId
                    ? <span className="font-mono text-xs" title={m.targetUnitId}>ст. {m.targetUnitId.slice(0, 8)}…</span>
                    : m.targetLocation
                      ? m.targetLocation.name
                      : <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground max-w-[180px] truncate"
                  title={[m.basis, m.comment].filter(Boolean).join(' · ') || undefined}>
                  {m.basis || m.comment || '—'}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground truncate max-w-[140px]">
                  {m.createdBy || '—'}
                </TableCell>
              </TableRow>
            ))}
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

// ─── диалог движения ЗИП (динамическая форма по op) ─────────────────────────

type IssueTarget = 'none' | 'unit' | 'site'
const ISSUE_TARGET_LABELS: Record<IssueTarget, string> = {
  none: 'Без привязки', unit: 'На станцию', site: 'На площадку',
}

function SpareMovementDialog({ companyId, part, initialOp, onClose }: {
  companyId: string
  part: SparePart
  initialOp: SpareOp
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [op, setOp] = useState<SpareOp>(initialOp)
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [qty, setQty] = useState('')
  const [occurredOn, setOccurredOn] = useState(todayIso())
  const [basis, setBasis] = useState('')
  const [comment, setComment] = useState('')
  // привязка расхода: станция-единица (поиск по серийнику) или площадка
  const [target, setTarget] = useState<IssueTarget>('none')
  const [unitQ, setUnitQ] = useState('')
  const [pickedUnit, setPickedUnit] = useState<{ id: string; label: string } | null>(null)
  const [siteId, setSiteId] = useState('')

  const warehouses = useMemo(() => getLocations().filter((l) => l.type === 'warehouse'), [])
  const sites = useMemo(() => getLocations().filter((l) => l.type === 'ev_charging'), [])
  const stockAt = useMemo(
    () => new Map(part.byLocation.map((b) => [b.locationId, b.qty])),
    [part.byLocation],
  )

  const unitsQuery = useQuery({
    queryKey: ['eq-units-pick', companyId, unitQ],
    queryFn: () => listUnits({ companyId, q: unitQ.trim(), pageSize: 20 }),
    enabled: op === 'issue' && target === 'unit' && unitQ.trim().length >= 2,
  })

  const qtyNum = Number(qty.replace(',', '.'))
  const qtyOk = Number.isFinite(qtyNum) && qtyNum > 0
  const needsFrom = op === 'issue' || op === 'write_off' || op === 'transfer'
  const needsTo = op === 'receipt' || op === 'transfer' || op === 'correction'
  const commentRequired = op === 'correction'
  const canSave = qtyOk
    && (!needsFrom || fromId !== '')
    && (!needsTo || toId !== '')
    && (op !== 'transfer' || fromId !== toId)
    && (!commentRequired || comment.trim() !== '')
    && (op !== 'issue' || target !== 'unit' || pickedUnit != null)
    && (op !== 'issue' || target !== 'site' || siteId !== '')

  const mut = useMutation({
    mutationFn: () => {
      const body: SpareMovementPayload = {
        op, qty: qtyNum,
        occurredOn: occurredOn || undefined,
        basis: basis.trim() || undefined,
        comment: comment.trim() || undefined,
      }
      if (needsFrom) body.fromLocationId = fromId
      if (needsTo) body.toLocationId = toId
      if (op === 'issue' && target === 'unit' && pickedUnit) body.targetUnitId = pickedUnit.id
      if (op === 'issue' && target === 'site' && siteId) body.targetLocationId = siteId
      return applySpareMovement(companyId, part.id, body)
    },
    onSuccess: () => {
      toast.success(`${OP_LABELS[op]}: «${part.name}», ${nfQty.format(qtyNum)} ${part.unitLabel}`)
      qc.invalidateQueries({ queryKey: ['eq-spares'] })
      qc.invalidateQueries({ queryKey: ['eq-spare-movements'] })
      onClose()
    },
    onError: (e) => toast.error(errMsg(e)),
  })

  /** Select склада с показом текущего остатка позиции на нём. */
  const whSelect = (value: string, onChange: (v: string) => void, placeholder: string) => (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {warehouses.length === 0 && (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">
            Нет складов — заведите точку типа «Склад»
          </div>
        )}
        {warehouses.map((w) => (
          <SelectItem key={w.id} value={w.id}>
            {w.name}
            {(stockAt.get(w.id) ?? 0) > 0 && ` · ${nfQty.format(stockAt.get(w.id) ?? 0)} ${part.unitLabel}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60!">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="size-5" /> Движение ЗИП — {part.name}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">
            Остаток: <span className="tabular-nums text-foreground">{nfQty.format(part.totalQty)} {part.unitLabel}</span>
            {part.byLocation.filter((b) => b.qty !== 0).map((b) => (
              <span key={b.locationId} className="ml-2">{b.locationName}: {nfQty.format(b.qty)}</span>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
            <FField label="Операция">
              <Select value={op} onValueChange={(v) => setOp(v as SpareOp)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(Object.keys(OP_LABELS) as SpareOp[]).map((o) => (
                    <SelectItem key={o} value={o}>{OP_LABELS[o]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FField>
            <FField label="Дата">
              <Input type="date" value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
            </FField>

            {needsFrom && (
              <FField label="Склад-источник" required>
                {whSelect(fromId, setFromId, 'Откуда')}
              </FField>
            )}
            {needsTo && (
              <FField label={op === 'correction' ? 'Склад' : 'Склад-получатель'} required>
                {whSelect(toId, setToId, op === 'correction' ? 'Где корректируем' : 'Куда')}
              </FField>
            )}

            <FField label={op === 'correction'
              ? `Новый фактический остаток, ${part.unitLabel}`
              : `Количество, ${part.unitLabel}`} required>
              <Input inputMode="decimal" value={qty} placeholder="0"
                onChange={(e) => setQty(e.target.value)} />
            </FField>
            {op === 'correction' && (
              <p className="col-span-2 text-[11px] text-muted-foreground -mt-1">
                Корректировка устанавливает фактический остаток на складе
                (указывается итоговое значение, а не дельта).
              </p>
            )}
            {op === 'transfer' && fromId !== '' && fromId === toId && (
              <p className="col-span-2 text-[11px] text-destructive -mt-1">
                Склады «откуда» и «куда» должны быть разными.
              </p>
            )}
          </div>

          {op === 'issue' && (
            <div className="space-y-2 rounded-md border border-border/60 p-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Привязка расхода:</span>
                <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5">
                  {(Object.keys(ISSUE_TARGET_LABELS) as IssueTarget[]).map((t) => (
                    <button key={t} type="button" onClick={() => setTarget(t)}
                      className={`px-2 py-0.5 text-xs rounded-[5px] transition-colors ${
                        target === t ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
                      }`}>
                      {ISSUE_TARGET_LABELS[t]}
                    </button>
                  ))}
                </div>
              </div>
              {target === 'unit' && (
                pickedUnit
                  ? (
                    <div className="flex items-center gap-1.5">
                      <Badge variant="outline" className="font-normal">{pickedUnit.label}</Badge>
                      <Button variant="ghost" size="icon" className="size-6" title="Сбросить"
                        onClick={() => setPickedUnit(null)}>
                        <X className="size-3.5" />
                      </Button>
                    </div>
                  )
                  : (
                    <div className="space-y-1.5">
                      <div className="relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                        <Input value={unitQ} onChange={(e) => setUnitQ(e.target.value)}
                          placeholder="Поиск станции-единицы по серийному номеру…" className="pl-8 h-9" />
                      </div>
                      {unitsQuery.isFetching && (
                        <div className="text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin inline-block mr-1" /> Поиск…</div>
                      )}
                      {unitsQuery.data && unitsQuery.data.items.length === 0 && (
                        <div className="text-xs text-muted-foreground">Единицы не найдены</div>
                      )}
                      {unitsQuery.data && unitsQuery.data.items.length > 0 && (
                        <div className="max-h-40 overflow-y-auto rounded-md border divide-y divide-border/50">
                          {unitsQuery.data.items.map((u) => {
                            const label = `${u.serialNumber ?? 'без с/н'} · ${[u.vendor, u.model].filter(Boolean).join(' ') || '—'}`
                            return (
                              <button key={u.id} type="button"
                                onClick={() => setPickedUnit({ id: u.id, label })}
                                className="block w-full px-2.5 py-1.5 text-left text-xs hover:bg-muted/60">
                                <span className="font-mono">{u.serialNumber ?? 'без с/н'}</span>
                                <span className="text-muted-foreground"> · {[u.vendor, u.model].filter(Boolean).join(' ') || '—'} · {u.stateLabel}</span>
                              </button>
                            )
                          })}
                        </div>
                      )}
                      {unitQ.trim().length < 2 && (
                        <p className="text-[11px] text-muted-foreground">Введите минимум 2 символа серийного номера.</p>
                      )}
                    </div>
                  )
              )}
              {target === 'site' && (
                <Select value={siteId} onValueChange={setSiteId}>
                  <SelectTrigger><SelectValue placeholder="Выберите площадку" /></SelectTrigger>
                  <SelectContent>
                    {sites.length === 0 && (
                      <div className="px-2 py-1.5 text-xs text-muted-foreground">Нет площадок ev_charging</div>
                    )}
                    {sites.map((s) => (
                      <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
            <FField label="Основание">
              <Input value={basis} onChange={(e) => setBasis(e.target.value)}
                placeholder="Накладная, акт, заявка…" />
            </FField>
            <FField label="Комментарий" required={commentRequired}>
              <Input value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder={commentRequired ? 'Причина корректировки (обязательно)' : ''} />
            </FField>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button disabled={!canSave || mut.isPending} onClick={() => mut.mutate()}>
            {mut.isPending && <Loader2 className="size-4 animate-spin mr-2" />}
            {OP_LABELS[op]}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
