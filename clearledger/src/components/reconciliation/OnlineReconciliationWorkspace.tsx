import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileCheck2,
  ListChecks,
  Save,
  Search,
  SlidersHorizontal,
  Wrench,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import {
  applyOnlineDecisions,
  deleteOnlineDecision,
  saveOnlineDecision,
  type OnlineReconCase,
  type OnlineReconDecision,
  type OnlineReconParams,
  type OnlineReconShift,
  type OnlineReconStatus,
  type OnlineReconWorkspace,
} from '@/services/onlineReconciliationService'

const PAGE_SIZE = 100

const STATUS_LABELS: Record<string, string> = {
  matched: 'Совпало',
  resolved: 'Решено',
  wait_done: 'WAIT в MSTO',
  only_msto: 'Только MSTO',
  only_transaction: 'Только операция',
  mismatch: 'Расхождение',
  shift_mismatch: 'Итог смены',
}

function fmtMoney(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value) + ' ₽'
}

function fmtVolume(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(value) + ' л'
}

function fmtDate(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function StatusBadge({ status }: { status: OnlineReconStatus }) {
  const variant = status === 'matched' || status === 'resolved'
    ? 'secondary'
    : status === 'mismatch' || status === 'shift_mismatch'
      ? 'destructive'
      : 'outline'
  return <Badge variant={variant}>{STATUS_LABELS[status] ?? status}</Badge>
}

function SourceMetric({
  icon: Icon,
  label,
  count,
  amount,
  volume,
  muted,
}: {
  icon: typeof Database
  label: string
  count: number
  amount: number
  volume: number
  muted?: boolean
}) {
  return (
    <div className={cn('min-w-0 flex-1 px-4 py-3', muted && 'bg-muted/20')}>
      <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
        <span className="ml-auto tabular-nums">{count}</span>
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-base font-semibold tabular-nums">{fmtMoney(amount)}</span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{fmtVolume(volume)}</span>
      </div>
    </div>
  )
}

function ShiftRow({
  shift,
  active,
  onClick,
}: {
  shift: OnlineReconShift
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full rounded-lg px-3 py-2.5 text-left transition-colors',
        active ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/60',
      )}
    >
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium">{shift.station_name} · смена {shift.shift_number}</span>
        {shift.locked ? <FileCheck2 className="ml-auto size-3.5 text-muted-foreground" aria-label="Период закрыт" /> : null}
        {shift.unresolved_count > 0 ? (
          <Badge variant="destructive">{shift.unresolved_count}</Badge>
        ) : (
          <CheckCircle2 className="ml-auto size-3.5 text-muted-foreground" aria-label="Сверено" />
        )}
      </div>
      <div className="mt-1 grid grid-cols-3 gap-2 text-[11px] tabular-nums text-muted-foreground">
        <span>M {fmtVolume(shift.msto.volume)}</span>
        <span>О {fmtVolume(shift.transactions.volume)}</span>
        <span>С {fmtVolume(shift.shift.volume)}</span>
      </div>
    </button>
  )
}

function DecisionDialog({
  item,
  companyId,
  open,
  onOpenChange,
  onSaved,
}: {
  item: OnlineReconCase | null
  companyId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<void>
}) {
  const [resolution, setResolution] = useState<OnlineReconDecision['resolution']>('accept_transaction')
  const [targetSystem, setTargetSystem] = useState<OnlineReconDecision['target_system']>('ledger')
  const [canonicalAmount, setCanonicalAmount] = useState('')
  const [canonicalVolume, setCanonicalVolume] = useState('')
  const [instruction, setInstruction] = useState('')
  const [note, setNote] = useState('')
  const [assignee, setAssignee] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!item) return
    const d = item.decision
    const fallback = item.kind === 'shift_gap'
      ? 'accept_shift'
      : item.msto_amount != null && item.transaction_amount == null
        ? 'accept_msto'
        : 'accept_transaction'
    setResolution(d?.resolution ?? fallback)
    setTargetSystem(d?.target_system ?? 'ledger')
    setCanonicalAmount(d?.canonical_amount?.toString() ?? item.effective_amount.toString())
    setCanonicalVolume(d?.canonical_volume?.toString() ?? item.effective_volume.toString())
    setInstruction(d?.instruction ?? '')
    setNote(d?.note ?? '')
    setAssignee(d?.assignee ?? '')
  }, [item])

  if (!item) return null

  async function save(status: 'in_progress' | 'resolved') {
    setSaving(true)
    try {
      await saveOnlineDecision({
        case: item!, companyId, status, resolution, targetSystem,
        canonicalAmount: resolution === 'manual' ? Number(canonicalAmount) : undefined,
        canonicalVolume: resolution === 'manual' ? Number(canonicalVolume) : undefined,
        instruction: instruction.trim() || undefined,
        note: note.trim() || undefined,
        assignee: assignee.trim() || undefined,
      })
      await onSaved()
      toast.success(status === 'resolved' ? 'Расхождение закрыто' : 'Поручение сохранено')
      onOpenChange(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить решение')
    } finally {
      setSaving(false)
    }
  }

  async function reset() {
    setSaving(true)
    try {
      await deleteOnlineDecision(companyId, item!.case_key)
      await onSaved()
      toast.success('Решение удалено')
      onOpenChange(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить решение')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{item.station_name} · {item.shift_number ? `смена ${item.shift_number}` : 'без смены'}</DialogTitle>
          <DialogDescription>
            {item.kind === 'shift_gap' ? 'Расхождение итогов трёх источников по смене.' : `${fmtDate(item.event_at)} · ${item.fuel_name}`}
          </DialogDescription>
        </DialogHeader>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Источник</TableHead>
              <TableHead className="text-right">Сумма</TableHead>
              <TableHead className="text-right">Объём</TableHead>
              <TableHead>Идентификатор</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell className="font-medium">MSTO</TableCell>
              <TableCell className="text-right tabular-nums">{fmtMoney(item.msto_amount)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtVolume(item.msto_volume)}</TableCell>
              <TableCell className="max-w-48 truncate text-xs text-muted-foreground">{item.external_order_id ?? '—'}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="font-medium">Операции STS</TableCell>
              <TableCell className="text-right tabular-nums">{fmtMoney(item.transaction_amount)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtVolume(item.transaction_volume)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{item.transaction_ext_id ?? '—'}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="font-medium">Сменный отчёт</TableCell>
              <TableCell className="text-right tabular-nums">{fmtMoney(item.shift_amount)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtVolume(item.shift_volume)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{item.shift_number ?? '—'}</TableCell>
            </TableRow>
          </TableBody>
        </Table>

        {item.locked ? (
          <div className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            <FileCheck2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            Период закрыт. Решение доступно для аудита, но корректировка нормализованных данных заблокирована.
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="recon-resolution">Какое значение принять</Label>
            <Select value={resolution} onValueChange={(value) => setResolution(value as OnlineReconDecision['resolution'])}>
              <SelectTrigger id="recon-resolution"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="accept_transaction">Факт операции STS</SelectItem>
                  <SelectItem value="accept_msto">Факт MSTO</SelectItem>
                  {item.kind === 'shift_gap' ? <SelectItem value="accept_shift">Итог сменного отчёта</SelectItem> : null}
                  <SelectItem value="manual">Ручное значение</SelectItem>
                  <SelectItem value="exclude">Исключить из учёта</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="recon-target">Где требуется исправление</Label>
            <Select value={targetSystem} onValueChange={(value) => setTargetSystem(value as OnlineReconDecision['target_system'])}>
              <SelectTrigger id="recon-target"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="msto">MSTO / агрегатор</SelectItem>
                  <SelectItem value="sts_transaction">Транзакции объекта</SelectItem>
                  <SelectItem value="shift_report">Сменный отчёт</SelectItem>
                  <SelectItem value="ledger">Только Ledger</SelectItem>
                  <SelectItem value="none">Исправление не требуется</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </div>

        {resolution === 'manual' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="recon-amount">Правильная сумма, ₽</Label>
              <Input id="recon-amount" type="number" min="0" step="0.01" value={canonicalAmount} onChange={(event) => setCanonicalAmount(event.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="recon-volume">Правильный объём, л</Label>
              <Input id="recon-volume" type="number" min="0" step="0.001" value={canonicalVolume} onChange={(event) => setCanonicalVolume(event.target.value)} />
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="recon-assignee">Ответственный</Label>
            <Input id="recon-assignee" value={assignee} onChange={(event) => setAssignee(event.target.value)} placeholder="Подразделение или сотрудник" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="recon-note">Комментарий аудитора</Label>
            <Input id="recon-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Почему принято это решение" />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="recon-instruction">Указание для исправления</Label>
          <Textarea id="recon-instruction" rows={3} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Что проверить или исправить в MSTO, STS либо на объекте" />
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {item.decision && !item.decision.applied_at ? (
              <Button variant="ghost" onClick={reset} disabled={saving}>Удалить решение</Button>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => save('in_progress')} disabled={saving || item.locked}>
              <Wrench data-icon="inline-start" />Сохранить поручение
            </Button>
            <Button onClick={() => save('resolved')} disabled={saving || item.locked}>
              <Save data-icon="inline-start" />Принять решение
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function OnlineReconciliationWorkspace({
  data,
  params,
  onReload,
}: {
  data: OnlineReconWorkspace
  params: OnlineReconParams
  onReload: () => Promise<void>
}) {
  const [selectedShift, setSelectedShift] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState('attention')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedCase, setSelectedCase] = useState<OnlineReconCase | null>(null)
  const [applying, setApplying] = useState(false)

  const filtered = useMemo(() => {
    const q = search.trim().toLocaleLowerCase('ru-RU')
    return data.cases.filter((item) => {
      if (selectedShift !== 'all' && item.shift_key !== selectedShift) return false
      if (statusFilter === 'attention' && (item.status === 'matched' || item.status === 'resolved')) return false
      if (statusFilter !== 'all' && statusFilter !== 'attention' && item.status !== statusFilter) return false
      if (!q) return true
      return [item.station_name, item.external_order_id, item.transaction_ext_id, item.fuel_name, item.aggregator]
        .some((value) => String(value ?? '').toLocaleLowerCase('ru-RU').includes(q))
    })
  }, [data.cases, search, selectedShift, statusFilter])

  useEffect(() => { setPage(1) }, [selectedShift, statusFilter, search])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const refreshError = typeof data.refresh?.msto === 'object' && data.refresh?.msto !== null && 'error' in data.refresh.msto

  async function apply() {
    setApplying(true)
    try {
      const result = await applyOnlineDecisions(params)
      await onReload()
      toast.success(`Корректировки применены: ${result.applied}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось применить корректировки')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex divide-x divide-border overflow-hidden rounded-xl border bg-background">
        <SourceMetric icon={Database} label="MSTO" {...data.sources.msto} />
        <SourceMetric icon={ListChecks} label="Операции объектов" {...data.sources.transactions} />
        <SourceMetric icon={ClipboardCheck} label="Сменные отчёты" {...data.sources.shifts} />
        <SourceMetric icon={FileCheck2} label="Нормализовано L2" {...data.sources.normalized} muted />
      </div>

      {refreshError ? (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
          MSTO не обновлён. Сверка построена по локальным данным; проверьте источник в настройке канала.
        </div>
      ) : null}

      <div className="grid min-h-[520px] grid-cols-1 overflow-visible lg:grid-cols-[300px_minmax(0,1fr)] lg:overflow-hidden rounded-xl border bg-background">
        <aside className="border-r bg-muted/15 p-2">
          <button
            type="button"
            onClick={() => setSelectedShift('all')}
            className={cn(
              'mb-1 flex w-full items-center rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-colors',
              selectedShift === 'all' ? 'bg-accent' : 'hover:bg-accent/60',
            )}
          >
            Все расхождения
            <Badge variant={data.unresolved_count ? 'destructive' : 'secondary'} className="ml-auto">{data.unresolved_count}</Badge>
          </button>
          <div className="max-h-[620px] overflow-y-auto">
            {data.shifts.map((shift) => (
              <ShiftRow key={shift.key} shift={shift} active={selectedShift === shift.key} onClick={() => setSelectedShift(shift.key)} />
            ))}
          </div>
        </aside>

        <section className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
            <div className="relative min-w-64 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Заказ, операция, АЗС, топливо…" className="h-8 pl-8" />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 w-48"><SlidersHorizontal data-icon="inline-start" /><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="attention">Требуют внимания</SelectItem>
                  <SelectItem value="all">Все состояния</SelectItem>
                  <SelectItem value="only_msto">Только MSTO</SelectItem>
                  <SelectItem value="only_transaction">Только операции</SelectItem>
                  <SelectItem value="mismatch">Расхождение операции</SelectItem>
                  <SelectItem value="shift_mismatch">Расхождение смены</SelectItem>
                  <SelectItem value="resolved">Решённые</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <ConfirmActionDialog
              trigger={
                <Button size="sm" disabled={applying || data.unresolved_count > 0}>
                  <CheckCircle2 data-icon="inline-start" />
                  Применить в L2
                </Button>
              }
              title="Применить решения в слой L2?"
              description="Все решённые расхождения будут записаны в слой L2 (нормализованные данные, используемые в отчётности и выгрузке). Действие затрагивает данные сверки."
              confirmLabel="Применить в L2"
              onConfirm={apply}
            />
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Состояние</TableHead>
                <TableHead>Операция</TableHead>
                <TableHead>АЗС / смена</TableHead>
                <TableHead className="text-right">MSTO</TableHead>
                <TableHead className="text-right">Факт STS</TableHead>
                <TableHead className="text-right">Смена</TableHead>
                <TableHead className="text-right">Δ объёма</TableHead>
                <TableHead>Решение</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageRows.length ? pageRows.map((item) => (
                <TableRow key={item.case_key} className="cursor-pointer" onClick={() => setSelectedCase(item)}>
                  <TableCell><StatusBadge status={item.status} /></TableCell>
                  <TableCell>
                    <div className="max-w-44 truncate text-sm font-medium">{item.external_order_id ?? item.transaction_ext_id ?? 'Итог смены'}</div>
                    <div className="text-xs text-muted-foreground">{fmtDate(item.event_at)} · {item.fuel_name}</div>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">{item.station_name}</div>
                    <div className="text-xs text-muted-foreground">смена {item.shift_number ?? '—'}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <div>{fmtMoney(item.msto_amount)}</div>
                    <div className="text-xs text-muted-foreground">{fmtVolume(item.msto_volume)}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <div>{fmtMoney(item.transaction_amount)}</div>
                    <div className="text-xs text-muted-foreground">{fmtVolume(item.transaction_volume)}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <div>{fmtMoney(item.shift_amount)}</div>
                    <div className="text-xs text-muted-foreground">{fmtVolume(item.shift_volume)}</div>
                  </TableCell>
                  <TableCell className="text-right text-xs font-medium tabular-nums">
                    <div>{item.msto_volume != null && item.transaction_volume != null
                      ? `M−О ${fmtVolume(item.msto_volume - item.transaction_volume)}`
                      : '—'}</div>
                    {item.transaction_volume != null && item.shift_volume != null ? (
                      <div className="text-muted-foreground">О−С {fmtVolume(item.transaction_volume - item.shift_volume)}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="max-w-52">
                    {item.decision ? (
                      <div>
                        <div className="truncate text-sm">{item.decision.assignee || 'Решение зафиксировано'}</div>
                        <div className="truncate text-xs text-muted-foreground">{item.decision.instruction || item.decision.note || 'Без комментария'}</div>
                      </div>
                    ) : <span className="text-xs text-muted-foreground">Открыть и разобрать</span>}
                  </TableCell>
                </TableRow>
              )) : (
                <TableRow>
                  <TableCell colSpan={8} className="h-40 text-center text-muted-foreground">
                    По выбранному фильтру расхождений нет.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
            <span>Показано {pageRows.length} из {filtered.length}</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon-xs" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page === 1} aria-label="Предыдущая страница">
                <ChevronLeft />
              </Button>
              <span>{page} / {pages}</span>
              <Button variant="outline" size="icon-xs" onClick={() => setPage((value) => Math.min(pages, value + 1))} disabled={page === pages} aria-label="Следующая страница">
                <ChevronRight />
              </Button>
            </div>
          </div>
        </section>
      </div>

      <DecisionDialog
        item={selectedCase}
        companyId={params.companyId}
        open={!!selectedCase}
        onOpenChange={(open) => { if (!open) setSelectedCase(null) }}
        onSaved={onReload}
      />
    </div>
  )
}
