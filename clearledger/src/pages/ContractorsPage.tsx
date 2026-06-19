/**
 * «Контрагенты» (раздел «Данные») — разрез контрагентов и их договоров (ось
 * контрагент↔договор↔точки/разрезы). Мастер-деталь: слева список контрагентов,
 * справа — выбранный контрагент с полными реквизитами из 1С, где он работает,
 * и его договоры (с детальной карточкой каждого).
 */
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from '@/components/ui/dialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Search, Building2, MapPin, Loader2, Database, FileText, Plus, Pencil, Trash2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import {
  useCounterparties, useContracts, useCounterpartyLocations,
  useCreateCounterparty, useUpdateCounterparty, useDeleteCounterparty,
  useCreateContract, useDeleteContract,
} from '@/hooks/useReferences'
import * as refs from '@/services/referenceService'
import { ContractScopeDialog, ContractScopeBadgeLabel } from '@/components/reference/ContractScopeDialog'
import type { Counterparty, Contract, CounterpartyType } from '@/types'

const TYPE_COLOR: Record<string, string> = {
  'ЮЛ': 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
  'ИП': 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  'ФЛ': 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400',
}
const TYPE_LABEL: Record<string, string> = { 'ЮЛ': 'Юр. лицо', 'ИП': 'Инд. предприниматель', 'ФЛ': 'Физ. лицо' }

// Виды договоров 1С (Перечисление.ВидыДоговоровКонтрагентов) — ярлык + цвет по
// направлению (продажа / закупка / агентские / финансы-логистика / прочее).
const KIND_META: Record<string, { label: string; cls: string }> = {
  'СПокупателем':            { label: 'С покупателем',              cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' },
  'СПоставщиком':            { label: 'С поставщиком',              cls: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20' },
  'СКомитентом':             { label: 'С комитентом',               cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20' },
  'СКомиссионером':          { label: 'С комиссионером',            cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20' },
  'СКомитентомНаЗакупку':    { label: 'С комитентом (закупка)',     cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20' },
  'СКомиссионеромНаЗакупку': { label: 'С комиссионером (закупка)',  cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20' },
  'СФакторинговойКомпанией': { label: 'С факторинговой компанией',  cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20' },
  'СТранспортнойКомпанией':  { label: 'С транспортной компанией',   cls: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20' },
  'ЗаемПолученный':          { label: 'Заём полученный',            cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20' },
  'Прочее':                  { label: 'Прочее',                     cls: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20' },
}
function kindLabel(k?: string): string { return (k && KIND_META[k]?.label) || k || '—' }

function KindBadge({ kind }: { kind?: string }) {
  if (!kind) return <span className="text-sm text-muted-foreground">—</span>
  const m = KIND_META[kind]
  return <Badge variant="outline" className={m?.cls || ''}>{m?.label || kind}</Badge>
}

// Человекочитаемые ярлыки реквизитов 1С (raw). Неизвестные ключи — как есть.
const RAW_LABELS: Record<string, string> = {
  Description: 'Наименование', НаименованиеПолное: 'Полное наименование', Код: 'Код',
  ИНН: 'ИНН', КПП: 'КПП', КодПоОКПО: 'ОКПО',
  ЮридическоеФизическоеЛицо: 'Вид', ИндивидуальныйПредприниматель: 'ИП', Комментарий: 'Комментарий',
  Номер: 'Номер', Дата: 'Дата', ВидДоговора: 'Вид договора', СрокДействия: 'Срок действия',
  Сумма: 'Сумма', ДоговорЗакрыт: 'Договор закрыт', СуммаВключаетНДС: 'Сумма включает НДС',
  СтавкаНДС: 'Ставка НДС', ВидВзаиморасчетов: 'Вид взаиморасчётов',
}
const RAW_SKIP = new Set(['Ref_Key', 'DeletionMark', 'ЭтоГруппа', 'Predefined', 'PredefinedDataName', 'Code', 'Description'])

function fmtRaw(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Да' : 'Нет'
  return String(v)
}

/** Универсальный рендер «сырых» реквизитов 1С (raw) — показывает всё, что пришло
 *  из синка, кроме внутренних/GUID-ключей. После расширения синка покажет больше. */
function RawRequisites({ raw, hide }: { raw?: Record<string, unknown>; hide?: string[] }) {
  const skip = useMemo(() => new Set([...RAW_SKIP, ...(hide ?? [])]), [hide])
  if (!raw) return null
  const entries = Object.entries(raw).filter(
    ([k, v]) => !skip.has(k) && !k.endsWith('_Key') && v !== null && v !== undefined && v !== '',
  )
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">Доп. реквизиты не загружены.</p>
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
      {entries.map(([k, v]) => (
        <div key={k} className="space-y-0.5">
          <div className="text-[11px] text-muted-foreground/70">{RAW_LABELS[k] ?? k}</div>
          <div className="text-sm break-words">{fmtRaw(v)}</div>
        </div>
      ))}
    </div>
  )
}

/** Поле «ярлык + значение» (скрывается, если значения нет). */
function Req({ label, value, span }: { label: string; value?: React.ReactNode; span?: boolean }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <div className={`space-y-0.5 ${span ? 'col-span-2' : ''}`}>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      <div className="text-sm break-words">{value}</div>
    </div>
  )
}

function WhereWorks({ counterpartyId }: { counterpartyId: string }) {
  const { data, isLoading } = useCounterpartyLocations(counterpartyId)
  if (isLoading) return <Loader2 className="size-4 animate-spin text-muted-foreground" />
  if (!data) return null
  return (
    <div className="flex items-center gap-2 flex-wrap text-sm">
      <MapPin className="size-4 text-muted-foreground shrink-0" />
      {data.scope === 'company' && <Badge variant="secondary">Вся компания</Badge>}
      {data.scope === 'locations' && data.locations.map((l) => (
        <Badge key={l.id} variant="outline">{l.name}</Badge>
      ))}
      {data.scope === 'none' && <span className="text-xs text-muted-foreground">точки не заданы</span>}
      {data.unassignedCount > 0 && (
        <span className="text-xs text-amber-600 dark:text-amber-400">
          · нераспределённых договоров: {data.unassignedCount}
        </span>
      )}
    </div>
  )
}

// ─── Детальная карточка договора ─────────────────────────────────────────────
function ContractDetailDialog({ contract: c, children }: { contract: Contract; children: React.ReactNode }) {
  const raw = c.raw ?? {}
  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-5" /> Договор {c.number}
            {c.isClosed && <Badge variant="outline" className="text-muted-foreground">закрыт</Badge>}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Req label="Номер" value={c.number} />
            <Req label="Дата" value={c.date} />
            <Req label="Вид договора" value={<KindBadge kind={c.kind || c.type} />} />
            <Req label="Валюта" value={c.currency} />
            <Req label="Срок действия" value={c.validUntil} />
            <Req label="Сумма" value={c.amountLimit ? c.amountLimit.toLocaleString('ru-RU') : undefined} />
            <Req label="Сумма включает НДС" value={'СуммаВключаетНДС' in raw ? fmtRaw(raw.СуммаВключаетНДС) : undefined} />
            <Req label="Договор закрыт" value={fmtRaw(c.isClosed)} />
            <Req label="Охват точек" value={ContractScopeBadgeLabel(c.scopeType)} />
            <Req label="Комментарий" value={raw.Комментарий as string} span />
          </div>
          <div className="space-y-2 border-t border-border/50 pt-3">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">Все реквизиты из 1С</p>
            <RawRequisites raw={c.raw} hide={['Номер', 'Дата', 'ВидДоговора', 'СрокДействия', 'Сумма', 'ДоговорЗакрыт', 'СуммаВключаетНДС', 'Комментарий']} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Карточка контрагента ────────────────────────────────────────────────────
function ContractorDetail({ cp, all }: { cp: Counterparty; all: Counterparty[] }) {
  const { data: allContracts = [] } = useContracts()
  // Договоры из 1С хранят counterpartyId = GUID (externalRef); ручные — наш id.
  const contracts = useMemo(
    () => allContracts.filter(
      (c) => c.counterpartyId === cp.externalRef || c.counterpartyId === cp.id,
    ),
    [allContracts, cp.externalRef, cp.id],
  )
  const head = cp.headRef ? all.find((c) => c.externalRef === cp.headRef) : undefined
  const raw = cp.raw ?? {}
  // Сводка по видам договоров (различаем покупатель/поставщик/агентские/…).
  const kindCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of contracts) { const k = c.kind || c.type || 'Прочее'; m.set(k, (m.get(k) ?? 0) + 1) }
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [contracts])

  return (
    <div className="space-y-5">
      {/* Заголовок */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Building2 className="size-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">{cp.name}</h2>
            <Badge variant="outline" className={TYPE_COLOR[cp.type] || ''}>{cp.type}</Badge>
            {cp.externalRef && (
              <Badge variant="secondary" className="gap-1"><Database className="size-3" /> Из 1С</Badge>
            )}
          </div>
          <div className="mt-2"><WhereWorks counterpartyId={cp.id} /></div>
        </div>
        {cp.externalRef ? (
          <span className="text-[11px] text-muted-foreground shrink-0 mt-1 whitespace-nowrap">правка в 1С</span>
        ) : (
          <div className="flex gap-1 shrink-0">
            <CounterpartyFormDialog edit={cp}>
              <Button variant="outline" size="sm"><Pencil className="size-3.5 mr-1.5" /> Изменить</Button>
            </CounterpartyFormDialog>
            <DeleteCounterpartyButton cp={cp} />
          </div>
        )}
      </div>

      {/* Реквизиты контрагента */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Req label="Полное наименование" value={cp.fullName} span />
        <Req label="ИНН" value={cp.inn} />
        <Req label="КПП" value={cp.kpp} />
        <Req label="ОКПО" value={cp.okpo} />
        <Req label="Вид" value={TYPE_LABEL[cp.type] || cp.type} />
        <Req label="Головной контрагент" value={head?.name} />
        <Req label="Комментарий" value={raw.Комментарий as string} span />
      </div>

      {/* Договоры */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              Договоры ({contracts.length})
            </p>
            {kindCounts.map(([k, n]) => (
              <Badge key={k} variant="outline" className={`text-[11px] ${KIND_META[k]?.cls || ''}`}>
                {kindLabel(k)}: {n}
              </Badge>
            ))}
          </div>
          <ContractFormDialog counterpartyId={cp.externalRef || cp.id}>
            <Button size="sm" variant="outline" className="shrink-0"><Plus className="size-4 mr-1.5" /> Добавить</Button>
          </ContractFormDialog>
        </div>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[160px]">Номер</TableHead>
                <TableHead className="w-[100px]">Дата</TableHead>
                <TableHead>Вид</TableHead>
                <TableHead className="w-[160px]">Охват</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {contracts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground h-20">
                    У контрагента нет договоров
                  </TableCell>
                </TableRow>
              )}
              {contracts.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <ContractDetailDialog contract={c}>
                      <button className="font-mono text-sm text-primary hover:underline text-left">{c.number}</button>
                    </ContractDetailDialog>
                  </TableCell>
                  <TableCell className="text-sm">{c.date || '—'}</TableCell>
                  <TableCell><KindBadge kind={c.kind || c.type} /></TableCell>
                  <TableCell>
                    <ContractScopeDialog contract={c}>
                      <Button variant="ghost" size="sm" className="h-7 -ml-2 gap-1.5 font-normal">
                        <MapPin className="size-3.5 text-muted-foreground shrink-0" />
                        <Badge
                          variant={c.scopeType === 'company' ? 'secondary' : 'outline'}
                          className={c.scopeType === 'unassigned' || !c.scopeType ? 'text-muted-foreground' : ''}
                        >
                          {ContractScopeBadgeLabel(c.scopeType)}
                        </Badge>
                      </Button>
                    </ContractScopeDialog>
                  </TableCell>
                  <TableCell>
                    {!c.externalRef && (
                      <div className="flex gap-1 justify-end">
                        <ContractFormDialog counterpartyId={cp.externalRef || cp.id} edit={c}>
                          <Button variant="ghost" size="icon" className="h-8 w-8"><Pencil className="size-4" /></Button>
                        </ContractFormDialog>
                        <DeleteContractButton id={c.id} />
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Все реквизиты из 1С */}
      {cp.externalRef && (
        <details className="group rounded-md border border-border/50 p-3">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70 hover:text-muted-foreground">
            Все реквизиты из 1С
          </summary>
          <div className="pt-3">
            <RawRequisites raw={cp.raw} hide={['НаименованиеПолное', 'ИНН', 'КПП', 'КодПоОКПО', 'ЮридическоеФизическоеЛицо', 'Комментарий']} />
          </div>
        </details>
      )}
    </div>
  )
}

// ─── Форма контрагента (создание/правка) ─────────────────────────────────────
const VID_OPTIONS: { value: CounterpartyType; label: string }[] = [
  { value: 'ЮЛ', label: 'Юр. лицо' }, { value: 'ИП', label: 'Инд. предприниматель' }, { value: 'ФЛ', label: 'Физ. лицо' },
]

function CounterpartyFormDialog({ edit, children }: { edit?: Counterparty; children: React.ReactNode }) {
  const create = useCreateCounterparty()
  const update = useUpdateCounterparty()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({
    name: edit?.name ?? '', shortName: edit?.shortName ?? '',
    inn: edit?.inn ?? '', kpp: edit?.kpp ?? '', type: (edit?.type ?? 'ЮЛ') as CounterpartyType,
  })
  const set = (k: 'name' | 'shortName' | 'inn' | 'kpp') => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }))
  const canSave = f.name.trim() !== '' && f.inn.trim() !== ''
  const pending = create.isPending || update.isPending
  function save() {
    const payload = {
      name: f.name.trim(), shortName: f.shortName.trim() || undefined,
      inn: f.inn.trim(), kpp: f.kpp.trim() || undefined, type: f.type,
    }
    const opts = {
      onSuccess: () => { toast.success(edit ? 'Контрагент обновлён' : 'Контрагент добавлен'); setOpen(false) },
      onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
    }
    if (edit) update.mutate({ id: edit.id, updates: payload }, opts)
    else create.mutate({ ...payload, aliases: [] }, opts)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Building2 className="size-5" /> {edit ? 'Изменить контрагента' : 'Новый контрагент'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Наименование <span className="text-destructive">*</span></Label>
            <Input value={f.name} onChange={set('name')} placeholder="ООО …" />
          </div>
          <div className="space-y-1.5"><Label>Краткое имя</Label><Input value={f.shortName} onChange={set('shortName')} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5"><Label>ИНН <span className="text-destructive">*</span></Label><Input value={f.inn} onChange={set('inn')} placeholder="7800…" /></div>
            <div className="space-y-1.5"><Label>КПП</Label><Input value={f.kpp} onChange={set('kpp')} /></div>
          </div>
          <div className="space-y-1.5">
            <Label>Вид</Label>
            <Select value={f.type} onValueChange={(v) => setF((s) => ({ ...s, type: v as CounterpartyType }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{VID_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!canSave || pending} onClick={save}>
            {pending && <Loader2 className="size-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Форма договора (создание/правка) ────────────────────────────────────────
function ContractFormDialog({ counterpartyId, edit, children }: {
  counterpartyId: string; edit?: Contract; children: React.ReactNode
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const create = useCreateContract()
  const update = useMutation({
    mutationFn: (updates: Partial<Contract>) => refs.updateContract(companyId, edit!.id, updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['references', companyId] }),
  })
  const orgsQuery = useQuery({
    queryKey: ['references', companyId, 'organizations'],
    queryFn: () => refs.getOrganizations(companyId), enabled: !!companyId,
  })
  const orgs = orgsQuery.data ?? []
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({
    number: edit?.number ?? '', date: edit?.date ?? '', kind: edit?.kind ?? 'СПокупателем',
    type: edit?.type ?? '', organizationId: edit?.organizationId ?? '',
    currency: edit?.currency ?? 'RUB', validUntil: edit?.validUntil ?? '',
    amountLimit: edit?.amountLimit != null ? String(edit.amountLimit) : '',
  })
  const orgId = f.organizationId || (orgs[0]?.externalRef || orgs[0]?.id || '')
  const canSave = f.number.trim() !== '' && f.date.trim() !== '' && orgId !== ''
  const pending = create.isPending || update.isPending
  function save() {
    const payload = {
      number: f.number.trim(), date: f.date.trim(), counterpartyId,
      organizationId: orgId, kind: f.kind, type: f.type.trim() || kindLabel(f.kind),
      currency: f.currency.trim() || 'RUB', validUntil: f.validUntil.trim() || undefined,
      amountLimit: f.amountLimit ? Number(f.amountLimit) : undefined, scopeType: 'unassigned' as const,
    }
    const opts = {
      onSuccess: () => { toast.success(edit ? 'Договор обновлён' : 'Договор добавлен'); setOpen(false) },
      onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
    }
    if (edit) update.mutate(payload, opts)
    else create.mutate(payload, opts)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-5" /> {edit ? 'Изменить договор' : 'Новый договор'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5"><Label>Номер <span className="text-destructive">*</span></Label>
              <Input value={f.number} onChange={(e) => setF((s) => ({ ...s, number: e.target.value }))} /></div>
            <div className="space-y-1.5"><Label>Дата <span className="text-destructive">*</span></Label>
              <Input type="date" value={f.date} onChange={(e) => setF((s) => ({ ...s, date: e.target.value }))} /></div>
          </div>
          <div className="space-y-1.5"><Label>Вид договора</Label>
            <Select value={f.kind} onValueChange={(v) => setF((s) => ({ ...s, kind: v }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{Object.entries(KIND_META).map(([k, m]) => <SelectItem key={k} value={k}>{m.label}</SelectItem>)}</SelectContent>
            </Select></div>
          <div className="space-y-1.5"><Label>Тип / предмет</Label>
            <Input value={f.type} onChange={(e) => setF((s) => ({ ...s, type: e.target.value }))} placeholder="Поставка ГСМ, аренда, услуги…" /></div>
          <div className="space-y-1.5"><Label>Организация</Label>
            <Select value={orgId} onValueChange={(v) => setF((s) => ({ ...s, organizationId: v }))}>
              <SelectTrigger><SelectValue placeholder={orgs.length ? 'Выберите' : 'Нет организаций'} /></SelectTrigger>
              <SelectContent>{orgs.map((o) => <SelectItem key={o.id} value={o.externalRef || o.id}>{o.name}</SelectItem>)}</SelectContent>
            </Select></div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5"><Label>Валюта</Label>
              <Input value={f.currency} onChange={(e) => setF((s) => ({ ...s, currency: e.target.value }))} /></div>
            <div className="space-y-1.5"><Label>Срок действия</Label>
              <Input type="date" value={f.validUntil} onChange={(e) => setF((s) => ({ ...s, validUntil: e.target.value }))} /></div>
            <div className="space-y-1.5"><Label>Сумма</Label>
              <Input value={f.amountLimit} onChange={(e) => setF((s) => ({ ...s, amountLimit: e.target.value.replace(/[^\d.]/g, '') }))} /></div>
          </div>
          {orgs.length === 0 && <p className="text-xs text-amber-600 dark:text-amber-400">Сначала заведите организацию (раздел «Данные → Организация»).</p>}
        </div>
        <DialogFooter>
          <Button disabled={!canSave || pending} onClick={save}>
            {pending && <Loader2 className="size-4 animate-spin mr-2" />} Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteCounterpartyButton({ cp }: { cp: Counterparty }) {
  const del = useDeleteCounterparty()
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" className="text-destructive"><Trash2 className="size-3.5" /></Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Удалить контрагента «{cp.name}»?</AlertDialogTitle>
          <AlertDialogDescription>Действие необратимо. Договоры контрагента не удаляются автоматически.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate(cp.id, {
            onSuccess: () => toast.success('Контрагент удалён'),
            onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
          })}>Удалить</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function DeleteContractButton({ id }: { id: string }) {
  const del = useDeleteContract()
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8"><Trash2 className="size-4 text-destructive" /></Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Удалить договор?</AlertDialogTitle>
          <AlertDialogDescription>Действие необратимо.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate(id, {
            onSuccess: () => toast.success('Договор удалён'),
            onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
          })}>Удалить</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ContractorsPage() {
  const { data: counterparties = [], isLoading } = useCounterparties()
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return counterparties
    return counterparties.filter(
      (c) => c.name.toLowerCase().includes(q) || c.inn.includes(q),
    )
  }, [counterparties, search])

  const selected = counterparties.find((c) => c.id === selectedId) ?? null

  return (
    <div className="flex-1 min-w-0 p-4 lg:p-6">
      <div className="mb-4 flex items-center gap-2">
        <Building2 className="h-6 w-6 text-primary shrink-0" />
        <div>
          <h1 className="text-xl font-semibold">Контрагенты и договоры</h1>
          <p className="text-sm text-muted-foreground">
            Разрез по контрагентам: их реквизиты из 1С, договоры, охват точек и ограничения по разрезам.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
        {/* Список контрагентов */}
        <Card className="lg:h-[calc(100vh-12rem)] flex flex-col">
          <CardContent className="p-3 flex flex-col gap-3 min-h-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <Input placeholder="Поиск по имени или ИНН..." value={search}
                onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9" />
            </div>
            <CounterpartyFormDialog>
              <Button size="sm" variant="outline" className="w-full"><Plus className="size-4 mr-2" /> Добавить контрагента</Button>
            </CounterpartyFormDialog>
            <div className="overflow-y-auto space-y-0.5 min-h-0">
              {isLoading && <div className="text-sm text-muted-foreground p-2">Загрузка…</div>}
              {!isLoading && filtered.length === 0 && (
                <div className="text-sm text-muted-foreground p-2">Контрагенты не найдены.</div>
              )}
              {filtered.slice(0, 300).map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={`w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                    c.id === selectedId ? 'bg-accent' : 'hover:bg-muted'
                  }`}
                >
                  <div className="font-medium truncate">{c.name}</div>
                  <div className="text-xs text-muted-foreground">ИНН {c.inn}</div>
                </button>
              ))}
              {filtered.length > 300 && (
                <div className="text-[11px] text-muted-foreground p-2">
                  …показаны первые 300, уточните поиском ({filtered.length} всего)
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Детали выбранного контрагента */}
        <Card className="lg:h-[calc(100vh-12rem)] overflow-y-auto">
          <CardContent className="p-4">
            {selected
              ? <ContractorDetail cp={selected} all={counterparties} />
              : (
                <div className="h-full flex items-center justify-center text-sm text-muted-foreground py-20">
                  Выберите контрагента слева
                </div>
              )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default ContractorsPage
