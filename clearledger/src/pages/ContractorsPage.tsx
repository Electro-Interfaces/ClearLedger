/**
 * «Контрагенты» (раздел «Данные») — разрез контрагентов и их договоров (ось
 * контрагент↔договор↔точки/разрезы). Мастер-деталь: слева список контрагентов,
 * справа — выбранный контрагент с полными реквизитами из 1С, где он работает,
 * и его договоры (с детальной карточкой каждого).
 */
import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
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
import { Search, Building2, MapPin, Loader2, Database, FileText, Plus, Pencil, Trash2, ChevronDown, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import {
  useCounterparties, useContracts, useCounterpartyLocations, useCounterpartyActivity,
  useCreateCounterparty, useUpdateCounterparty, useDeleteCounterparty,
  useCreateContract, useDeleteContract, useSettlementsDetail,
} from '@/hooks/useReferences'
import * as refs from '@/services/referenceService'
import { getCorporateClients } from '@/services/corporateService'
import { ROLE_LABEL, PAYMENT_META, paidThroughLabel } from '@/types/settlement'
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

// Роли контрагента в энергосети (из aliases — заполняется при загрузке реестра ЭЗС).
// Ключи = как пишет ingest реестров (reestr_rushydro: energy/rent/service).
// Один контрагент может выступать в нескольких ролях (напр. энергосбыт + аренда).
const ROLE_META: Record<string, { label: string; cls: string }> = {
  energy:  { label: 'Энергосбыт', cls: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20' },
  rent:    { label: 'Аренда',     cls: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20' },
  service: { label: 'Сервис',     cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' },
}
const ROLE_ORDER = ['energy', 'rent', 'service']

// Energy-профиль: реальный смысл договора лежит в type (Энергоснабжение/Аренда/
// Сервис из реестра), а 1С-вид (kind) у реестровых договоров всегда «СПоставщиком»
// и только вводит в заблуждение — показываем type с цветом по смыслу.
const ENERGY_TYPE_CLS: [string, string][] = [
  ['Энергоснабжение', 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20'],
  ['Поставка электроэнергии', 'bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20'],
  ['Аренда', 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20'],
  ['Сервис', 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'],
  ['Техническое обслуживание', 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'],
]
function energyTypeCls(t: string): string {
  return ENERGY_TYPE_CLS.find(([prefix]) => t.startsWith(prefix))?.[1]
    ?? 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20'
}

/** Бейдж «вид договора» с учётом профиля компании: fuel → 1С-вид, energy → type. */
function ContractKindBadge({ contract: c }: { contract: Contract }) {
  const { company } = useCompany()
  if (company.profileId === 'energy') {
    if (!c.type) return <span className="text-sm text-muted-foreground">—</span>
    return <Badge variant="outline" className={energyTypeCls(c.type)}>{c.type}</Badge>
  }
  return <KindBadge kind={c.kind || c.type} />
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

// Кап бейджей «где работает»: у сетевых подрядчиков сотни точек — стена бейджей
// съедает карточку, а полный список и так есть в блоке «Станции и расчёты».
const WHERE_WORKS_MAX = 10

function WhereWorks({ counterpartyId }: { counterpartyId: string }) {
  const { data, isLoading } = useCounterpartyLocations(counterpartyId)
  const [expanded, setExpanded] = useState(false)
  if (isLoading) return <Loader2 className="size-4 animate-spin text-muted-foreground" />
  if (!data) return null
  const shown = expanded ? data.locations : data.locations.slice(0, WHERE_WORKS_MAX)
  const hidden = data.locations.length - shown.length
  return (
    <div className="flex items-center gap-2 flex-wrap text-sm">
      <MapPin className="size-4 text-muted-foreground shrink-0" />
      {data.scope === 'company' && <Badge variant="secondary">Вся компания</Badge>}
      {data.scope === 'locations' && (
        <>
          <span className="text-xs text-muted-foreground">точек: {data.locations.length}</span>
          {shown.map((l) => (
            <Badge key={l.id} variant="outline">{l.name}</Badge>
          ))}
          {hidden > 0 && (
            <button onClick={() => setExpanded(true)}
              className="text-xs text-primary hover:underline">
              и ещё {hidden}
            </button>
          )}
          {expanded && data.locations.length > WHERE_WORKS_MAX && (
            <button onClick={() => setExpanded(false)}
              className="text-xs text-muted-foreground hover:underline">
              свернуть
            </button>
          )}
        </>
      )}
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
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
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
            <Req label="Вид договора" value={<ContractKindBadge contract={c} />} />
            {!isEnergy && <Req label="Тип / предмет" value={c.type} />}
            <Req label="Валюта" value={c.currency} />
            <Req label="Срок действия" value={c.validUntil} />
            <Req label="Сумма" value={c.amountLimit ? c.amountLimit.toLocaleString('ru-RU') : undefined} />
            <Req label="Ставка НДС" value={c.vatRate} />
            <Req label="Сумма включает НДС" value={c.amountInclVat == null ? ('СуммаВключаетНДС' in raw ? fmtRaw(raw.СуммаВключаетНДС) : undefined) : (c.amountInclVat ? 'Да' : 'Нет')} />
            <Req label="Вид взаиморасчётов" value={c.settlementKind} />
            <Req label="Договор закрыт" value={c.isClosed ? 'Да' : 'Нет'} />
            {isEnergy && <Req label="Охват точек" value={ContractScopeBadgeLabel(c.scopeType)} />}
            <Req label="Комментарий" value={c.comment || (raw.Комментарий as string)} span />
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

// ─── Блок «Станции и расчёты» (energy: платёжная дисциплина контрагента) ─────
function SettlementsBlock({ cp }: { cp: Counterparty }) {
  const { data: all = [] } = useSettlementsDetail()
  const rows = useMemo(
    () => all.filter((s) => s.counterpartyId
      && (s.counterpartyId === cp.id || (cp.externalRef && s.counterpartyId === cp.externalRef))),
    [all, cp.id, cp.externalRef],
  )
  if (rows.length === 0) return null
  const monthly = rows.reduce((sum, r) => sum + (r.amountGross ?? 0), 0)
  const unpaid = rows.filter((r) => r.paymentStatus === 'unpaid').length
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
          Станции и расчёты ({rows.length})
        </p>
        {monthly > 0 && (
          <Badge variant="outline" className="text-[11px]">
            {Math.round(monthly).toLocaleString('ru-RU')} ₽/мес
          </Badge>
        )}
        {unpaid > 0 && (
          <Badge variant="outline" className={`text-[11px] ${PAYMENT_META.unpaid.cls}`}>
            не оплачено: {unpaid}
          </Badge>
        )}
      </div>
      <div className="rounded-md border max-h-72 overflow-y-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-card z-10">
            <TableRow>
              <TableHead>Станция</TableHead>
              <TableHead className="w-[130px]">Роль</TableHead>
              <TableHead className="w-[110px] text-right">Плата, ₽/мес</TableHead>
              <TableHead className="w-[170px]">Оплата</TableHead>
              <TableHead className="w-[150px]">Срок договора</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={`${r.locationId}-${r.role}-${i}`}>
                <TableCell className="text-sm">
                  <span className="font-medium">{r.buNumber || r.stationCode || '—'}</span>
                  {r.stationName && (
                    <span className="text-muted-foreground"> · {r.stationName}</span>
                  )}
                </TableCell>
                <TableCell className="text-sm">{ROLE_LABEL[r.role] ?? r.role}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">
                  {r.amountGross ? Math.round(r.amountGross).toLocaleString('ru-RU') : '—'}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={`text-[11px] ${PAYMENT_META[r.paymentStatus]?.cls ?? ''}`}>
                    {paidThroughLabel(r)}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                  {r.contractStart || r.contractEnd
                    ? `${r.contractStart ?? '…'} — ${r.contractEnd ?? '…'}`
                    : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ─── Блок «Документы в учёте» (fuel: документы БП по ИНН контрагента) ────────
const DOC_TYPE_LABELS: Record<string, string> = {
  'ПТУ': 'Поступление (ПТУ)',
  'ОРП': 'Розничные продажи (ОРП)',
  'ОПЗС': 'Производство за смену (ОПЗС)',
  'ПеремещениеТоваров': 'Перемещение товаров',
  'СписаниеТоваров': 'Списание товаров',
  'КорректировкаПоступления': 'Корректировка поступления',
}
const docTypeLabel = (t: string) => DOC_TYPE_LABELS[t] ?? t

function ActivityBlock({ cp }: { cp: Counterparty }) {
  const { data } = useCounterpartyActivity(cp.id)
  if (!data || data.docs === 0) return null
  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
          Документы в учёте ({data.docs})
        </p>
        <Badge variant="outline" className="text-[11px]">
          {Math.round(data.amount).toLocaleString('ru-RU')} ₽
        </Badge>
        {data.lastDate && (
          <span className="text-[11px] text-muted-foreground">последний: {data.lastDate}</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1 mb-2">
        {data.byType.map((g) => (
          <Badge key={g.docType} variant="outline" className="text-[11px] text-muted-foreground">
            {docTypeLabel(g.docType)}: {g.count}
          </Badge>
        ))}
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Документ</TableHead>
              <TableHead className="w-[160px]">Номер</TableHead>
              <TableHead className="w-[100px]">Дата</TableHead>
              <TableHead className="w-[120px] text-right">Сумма, ₽</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.recent.map((d, i) => (
              <TableRow key={`${d.number}-${i}`}>
                <TableCell className="text-sm">{docTypeLabel(d.docType)}</TableCell>
                <TableCell className="font-mono text-sm">{d.number}</TableCell>
                <TableCell className="text-sm whitespace-nowrap">{d.date}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">
                  {d.amount ? d.amount.toLocaleString('ru-RU') : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Последние 10 документов БП, сопоставление по ИНН.
      </p>
    </div>
  )
}

// ─── Карточка контрагента ────────────────────────────────────────────────────
function ContractorDetail({ cp, all }: { cp: Counterparty; all: Counterparty[] }) {
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
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
  // Сводка по видам договоров: fuel — 1С-вид (покупатель/поставщик/агентские/…),
  // energy — реальный смысл из type (Энергоснабжение/Аренда/Сервис).
  const kindCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of contracts) {
      const k = isEnergy ? (c.type || 'Прочее') : (c.kind || c.type || 'Прочее')
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [contracts, isEnergy])

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
          {isEnergy && <div className="mt-2"><WhereWorks counterpartyId={cp.id} /></div>}
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

      {/* Реквизиты контрагента — свёрнуты по умолчанию, раскрываются по клику */}
      <details className="group rounded-md border border-border/50 p-3">
        <summary className="flex cursor-pointer list-none items-center justify-between text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70 hover:text-muted-foreground">
          <span>Реквизиты</span>
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
        </summary>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 pt-3">
          <Req label="Полное наименование" value={cp.fullName} span />
          <Req label="ИНН" value={cp.inn} />
          <Req label="КПП" value={cp.kpp} />
          <Req label="ОГРН" value={cp.ogrn} />
          <Req label="ОКПО" value={cp.okpo} />
          <Req label="ОКВЭД" value={cp.okved} />
          <Req label="Вид" value={TYPE_LABEL[cp.type] || cp.type} />
          <Req label="Головной контрагент" value={head?.name} />
          <Req label="Юридический адрес" value={cp.legalAddress} span />
          <Req label="Фактический адрес" value={cp.actualAddress} span />
          <Req label="Телефон" value={cp.phone} />
          <Req label="Email" value={cp.email} />
          <Req label="Руководитель" value={cp.directorName} />
          <Req label="Должность руководителя" value={cp.directorPosition} />
          <Req label="Расчётный счёт" value={cp.bankAccount} />
          <Req label="БИК" value={cp.bankBik} />
          <Req label="Банк" value={cp.bankName} span />
          <Req label="Комментарий" value={raw.Комментарий as string} span />
        </div>
      </details>

      {/* Договоры */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              Договоры ({contracts.length})
            </p>
            {kindCounts.map(([k, n]) => (
              <Badge key={k} variant="outline"
                className={`text-[11px] ${isEnergy ? energyTypeCls(k) : KIND_META[k]?.cls || ''}`}>
                {isEnergy ? k : kindLabel(k)}: {n}
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
                {isEnergy && <TableHead className="w-[160px]">Охват</TableHead>}
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {contracts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={isEnergy ? 5 : 4} className="text-center text-muted-foreground h-20">
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
                  <TableCell><ContractKindBadge contract={c} /></TableCell>
                  {isEnergy && (
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
                  )}
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

      {/* Связь со слоем данных: energy — платёжная дисциплина по станциям,
          fuel — документы БП, сопоставленные по ИНН */}
      {isEnergy ? <SettlementsBlock cp={cp} /> : <ActivityBlock cp={cp} />}

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

// Хелперы форм (секция + поле с подписью).
function FSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">{title}</p>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">{children}</div>
    </div>
  )
}
function LField({ label, required, span, children }: {
  label: string; required?: boolean; span?: boolean; children: React.ReactNode
}) {
  return (
    <div className={`space-y-1.5 ${span ? 'col-span-2' : ''}`}>
      <Label className="text-xs text-muted-foreground">{label}{required && <span className="text-destructive"> *</span>}</Label>
      {children}
    </div>
  )
}

const CP_FIELDS = [
  'name', 'shortName', 'fullName', 'inn', 'kpp', 'ogrn', 'okpo', 'okved',
  'legalAddress', 'actualAddress', 'phone', 'email', 'directorName',
  'directorPosition', 'bankAccount', 'bankBik', 'bankName',
] as const
type CpField = typeof CP_FIELDS[number]

function CounterpartyFormDialog({ edit, children }: { edit?: Counterparty; children: React.ReactNode }) {
  const create = useCreateCounterparty()
  const update = useUpdateCounterparty()
  const [open, setOpen] = useState(false)
  const [f, setF] = useState<Record<CpField, string>>(
    () => Object.fromEntries(CP_FIELDS.map((k) => [k, (edit?.[k] as string) ?? ''])) as Record<CpField, string>,
  )
  const [type, setType] = useState<CounterpartyType>(edit?.type ?? 'ЮЛ')
  const set = (k: CpField) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }))
  const canSave = f.name.trim() !== '' && f.inn.trim() !== ''
  const pending = create.isPending || update.isPending
  function save() {
    const c = (v: string) => v.trim() || undefined
    const base = {
      name: f.name.trim(), inn: f.inn.trim(), type,
      shortName: c(f.shortName), fullName: c(f.fullName), kpp: c(f.kpp),
      ogrn: c(f.ogrn), okpo: c(f.okpo), okved: c(f.okved),
      legalAddress: c(f.legalAddress), actualAddress: c(f.actualAddress),
      phone: c(f.phone), email: c(f.email),
      directorName: c(f.directorName), directorPosition: c(f.directorPosition),
      bankAccount: c(f.bankAccount), bankBik: c(f.bankBik), bankName: c(f.bankName),
    }
    const opts = {
      onSuccess: () => { toast.success(edit ? 'Контрагент обновлён' : 'Контрагент добавлен'); setOpen(false) },
      onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
    }
    if (edit) update.mutate({ id: edit.id, updates: base }, opts)
    else create.mutate({ ...base, aliases: [] }, opts)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60!">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Building2 className="size-5" /> {edit ? 'Изменить контрагента' : 'Новый контрагент'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <FSection title="Идентификация">
            <LField label="Вид">
              <Select value={type} onValueChange={(v) => setType(v as CounterpartyType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{VID_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
              </Select>
            </LField>
            <LField label="Краткое наименование" required><Input value={f.name} onChange={set('name')} placeholder="ООО …" /></LField>
            <LField label="Полное наименование" span><Input value={f.fullName} onChange={set('fullName')} /></LField>
            <LField label="ИНН" required><Input value={f.inn} onChange={set('inn')} placeholder="7800…" /></LField>
            <LField label="КПП"><Input value={f.kpp} onChange={set('kpp')} /></LField>
            <LField label="ОГРН / ОГРНИП"><Input value={f.ogrn} onChange={set('ogrn')} /></LField>
            <LField label="ОКПО"><Input value={f.okpo} onChange={set('okpo')} /></LField>
            <LField label="ОКВЭД"><Input value={f.okved} onChange={set('okved')} /></LField>
          </FSection>
          <div className="h-px bg-border/60" />
          <FSection title="Адреса">
            <LField label="Юридический адрес" span><Textarea value={f.legalAddress} onChange={set('legalAddress')} rows={2} /></LField>
            <LField label="Фактический адрес" span><Textarea value={f.actualAddress} onChange={set('actualAddress')} rows={2} /></LField>
          </FSection>
          <div className="h-px bg-border/60" />
          <FSection title="Контакты и руководитель">
            <LField label="Телефон"><Input value={f.phone} onChange={set('phone')} placeholder="+7 …" /></LField>
            <LField label="Email"><Input value={f.email} onChange={set('email')} /></LField>
            <LField label="Руководитель (ФИО)"><Input value={f.directorName} onChange={set('directorName')} /></LField>
            <LField label="Должность"><Input value={f.directorPosition} onChange={set('directorPosition')} placeholder="Генеральный директор" /></LField>
          </FSection>
          <div className="h-px bg-border/60" />
          <FSection title="Банковские реквизиты">
            <LField label="Расчётный счёт"><Input value={f.bankAccount} onChange={set('bankAccount')} placeholder="40702810…" /></LField>
            <LField label="БИК"><Input value={f.bankBik} onChange={set('bankBik')} /></LField>
            <LField label="Банк" span><Input value={f.bankName} onChange={set('bankName')} placeholder="ПАО Сбербанк" /></LField>
          </FSection>
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
    vatRate: edit?.vatRate ?? '', settlementKind: edit?.settlementKind ?? '', comment: edit?.comment ?? '',
    amountInclVat: edit?.amountInclVat == null ? '' : (edit.amountInclVat ? 'true' : 'false'),
    isClosed: edit?.isClosed ?? false,
  })
  const orgId = f.organizationId || (orgs[0]?.externalRef || orgs[0]?.id || '')
  const canSave = f.number.trim() !== '' && f.date.trim() !== '' && orgId !== ''
  const pending = create.isPending || update.isPending
  function save() {
    const payload = {
      number: f.number.trim(), date: f.date.trim(), counterpartyId,
      organizationId: orgId, kind: f.kind, type: f.type.trim() || kindLabel(f.kind),
      currency: f.currency.trim() || 'RUB', validUntil: f.validUntil.trim() || undefined,
      amountLimit: f.amountLimit ? Number(f.amountLimit) : undefined,
      vatRate: f.vatRate.trim() || undefined,
      amountInclVat: f.amountInclVat === '' ? undefined : f.amountInclVat === 'true',
      settlementKind: f.settlementKind.trim() || undefined,
      comment: f.comment.trim() || undefined,
      isClosed: f.isClosed,
      scopeType: 'unassigned' as const,
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
      <DialogContent className="max-h-[90vh] overflow-y-auto [&_input]:bg-muted/60! [&_textarea]:bg-muted/60! [&_[data-slot=select-trigger]]:bg-muted/60!">
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
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5"><Label>Ставка НДС</Label>
              <Input value={f.vatRate} onChange={(e) => setF((s) => ({ ...s, vatRate: e.target.value }))} placeholder="20% / Без НДС" /></div>
            <div className="space-y-1.5"><Label>Сумма включает НДС</Label>
              <Select value={f.amountInclVat || '—'} onValueChange={(v) => setF((s) => ({ ...s, amountInclVat: v === '—' ? '' : v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="—">—</SelectItem>
                  <SelectItem value="true">Да</SelectItem>
                  <SelectItem value="false">Нет</SelectItem>
                </SelectContent>
              </Select></div>
            <div className="space-y-1.5"><Label>Вид взаиморасчётов</Label>
              <Input value={f.settlementKind} onChange={(e) => setF((s) => ({ ...s, settlementKind: e.target.value }))} /></div>
          </div>
          <div className="space-y-1.5"><Label>Комментарий</Label>
            <Textarea value={f.comment} onChange={(e) => setF((s) => ({ ...s, comment: e.target.value }))} rows={2} /></div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={f.isClosed} onChange={(e) => setF((s) => ({ ...s, isClosed: e.target.checked }))} className="size-4 accent-primary" />
            Договор закрыт
          </label>
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

// Стиль чипса-фильтра (общий для контрагентов и договоров).
const chipCls = (active: boolean) =>
  `px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
    active ? 'bg-primary text-primary-foreground border-primary'
           : 'bg-muted/40 text-muted-foreground border-border/60 hover:bg-muted'
  }`

// ─── Глобальный список всех договоров (с фильтром по типу) ───────────────────
function AllContractsView({ counterparties }: { counterparties: Counterparty[] }) {
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  // Ярлык типа: fuel хранит в type код 1С-вида (СПокупателем/…) — показываем перевод.
  const typeLabel = (t: string) => (isEnergy ? t : kindLabel(t))
  const { data: allContracts = [], isLoading } = useContracts()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [limit, setLimit] = useState(100)
  const [sortKey, setSortKey] = useState<'date' | 'amount'>('date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const toggleSort = (col: 'date' | 'amount') => {
    if (sortKey === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(col); setSortDir('desc') }
  }

  // counterpartyId договора = externalRef из 1С или наш id → имя контрагента.
  const cpName = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of counterparties) {
      if (c.externalRef) m.set(c.externalRef, c.name)
      m.set(c.id, c.name)
    }
    return m
  }, [counterparties])

  const typeCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of allContracts) { const t = c.type || '—'; m.set(t, (m.get(t) ?? 0) + 1) }
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [allContracts])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = allContracts.filter((c) => {
      if (typeFilter !== 'all' && (c.type || '—') !== typeFilter) return false
      if (!q) return true
      const name = cpName.get(c.counterpartyId) ?? ''
      return c.number.toLowerCase().includes(q) || name.toLowerCase().includes(q)
    })
    const sign = sortDir === 'asc' ? 1 : -1
    return [...list].sort((a, b) => {
      if (sortKey === 'amount') {
        // пустые суммы всегда внизу, независимо от направления
        const an = a.amountLimit == null, bn = b.amountLimit == null
        if (an && bn) return 0
        if (an) return 1
        if (bn) return -1
        return sign * (a.amountLimit! - b.amountLimit!)
      }
      // дата: пустые всегда внизу
      const ad = a.date || '', bd = b.date || ''
      if (!ad && !bd) return 0
      if (!ad) return 1
      if (!bd) return -1
      return sign * ad.localeCompare(bd)
    })
  }, [allContracts, search, typeFilter, cpName, sortKey, sortDir])

  const SortIcon = ({ col }: { col: 'date' | 'amount' }) =>
    sortKey !== col ? <ArrowUpDown className="size-3 opacity-40" />
      : sortDir === 'desc' ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />

  useEffect(() => { setLimit(100) }, [search, typeFilter])
  const shown = filtered.slice(0, limit)

  return (
    <Card className="lg:h-[calc(100vh-13rem)] flex flex-col">
      <CardContent className="p-3 flex flex-col gap-2.5 min-h-0">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input placeholder="Поиск по номеру или контрагенту..." value={search}
              onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9" />
          </div>
          <span className="text-[11px] text-muted-foreground whitespace-nowrap">
            Найдено: {filtered.length}{filtered.length !== allContracts.length && ` из ${allContracts.length}`}
          </span>
        </div>

        {/* Фильтр по типу договора */}
        <div className="flex flex-wrap gap-1">
          <button onClick={() => setTypeFilter('all')} className={chipCls(typeFilter === 'all')}>
            Все · {allContracts.length}
          </button>
          {typeCounts.map(([t, n]) => (
            <button key={t} onClick={() => setTypeFilter(t)} className={chipCls(typeFilter === t)}>
              {t === '—' ? t : typeLabel(t)} · {n}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto min-h-0 rounded-md border">
          <Table>
            <TableHeader className="sticky top-0 bg-card z-10">
              <TableRow>
                <TableHead className="w-[150px]">Номер</TableHead>
                <TableHead className="w-[100px]">
                  <button onClick={() => toggleSort('date')} className="inline-flex items-center gap-1 hover:text-foreground transition-colors">
                    Дата <SortIcon col="date" />
                  </button>
                </TableHead>
                <TableHead className="w-[180px]">Тип</TableHead>
                <TableHead>Контрагент</TableHead>
                {isEnergy && <TableHead className="w-[150px]">Охват</TableHead>}
                <TableHead className="w-[120px] text-right">
                  <button onClick={() => toggleSort('amount')} className="inline-flex items-center gap-1 hover:text-foreground transition-colors ml-auto">
                    Сумма <SortIcon col="amount" />
                  </button>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow><TableCell colSpan={isEnergy ? 6 : 5} className="h-20 text-center text-muted-foreground">Загрузка…</TableCell></TableRow>
              )}
              {!isLoading && filtered.length === 0 && (
                <TableRow><TableCell colSpan={isEnergy ? 6 : 5} className="h-20 text-center text-muted-foreground">Договоры не найдены</TableCell></TableRow>
              )}
              {shown.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <ContractDetailDialog contract={c}>
                      <button className="font-mono text-sm text-primary hover:underline text-left">{c.number}</button>
                    </ContractDetailDialog>
                  </TableCell>
                  <TableCell className="text-sm whitespace-nowrap">{c.date || '—'}</TableCell>
                  <TableCell className="text-sm">{c.type ? typeLabel(c.type) : '—'}</TableCell>
                  <TableCell className="text-sm truncate max-w-[280px]">
                    {cpName.get(c.counterpartyId) ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  {isEnergy && (
                  <TableCell>
                    <Badge variant={c.scopeType === 'company' ? 'secondary' : 'outline'}
                      className={c.scopeType === 'unassigned' || !c.scopeType ? 'text-muted-foreground' : ''}>
                      {ContractScopeBadgeLabel(c.scopeType)}
                    </Badge>
                  </TableCell>
                  )}
                  <TableCell className="text-right text-sm tabular-nums">
                    {c.amountLimit ? c.amountLimit.toLocaleString('ru-RU') : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {filtered.length > limit && (
            <div className="p-2 text-center border-t">
              <Button variant="ghost" size="sm" onClick={() => setLimit((l) => l + 200)}>
                Показать ещё ({filtered.length - limit})
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Покупатели (корп.) — реестр корп-клиентов ЭЗС (energy) ──────────────────
const CORP_MODE_LABEL: Record<string, string> = {
  matrix: 'матрица тарифов', flat: 'фикс. ставка', retail: 'розничный',
}

function CorpClientsView() {
  const { companyId } = useCompany()
  // Метрики по зарядным сессиям за последние 12 месяцев.
  const [range] = useState(() => ({
    from: new Date(Date.now() - 365 * 86400_000).toISOString().slice(0, 10),
    to: new Date().toISOString().slice(0, 10),
  }))
  const { data, isLoading } = useQuery({
    queryKey: ['corp-clients', companyId, range.from, range.to],
    queryFn: () => getCorporateClients({ companyId, dateFrom: range.from, dateTo: range.to }),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  const clients = data?.clients ?? []
  const t = data?.totals
  return (
    <Card className="lg:h-[calc(100vh-13rem)] flex flex-col">
      <CardContent className="p-3 flex flex-col gap-2.5 min-h-0">
        <div className="flex items-center gap-2 flex-wrap text-[11px] text-muted-foreground">
          <span>Корпоративные покупатели (реестр из обогащения сессий) · метрики за 12 месяцев</span>
          {t && (
            <>
              <Badge variant="outline" className="text-[11px]">активных: {t.active_clients} из {t.clients}</Badge>
              <Badge variant="outline" className="text-[11px]">{Math.round(t.corp_revenue).toLocaleString('ru-RU')} ₽</Badge>
              <Badge variant="outline" className="text-[11px]">{Math.round(t.energy_kwh).toLocaleString('ru-RU')} кВт·ч</Badge>
            </>
          )}
        </div>
        <div className="overflow-y-auto min-h-0 rounded-md border">
          <Table>
            <TableHeader className="sticky top-0 bg-card z-10">
              <TableRow>
                <TableHead>Клиент</TableHead>
                <TableHead className="w-[130px]">Режим тарифа</TableHead>
                <TableHead className="w-[110px]">Договор с</TableHead>
                <TableHead className="w-[90px] text-right">Сессии</TableHead>
                <TableHead className="w-[110px] text-right">кВт·ч</TableHead>
                <TableHead className="w-[130px] text-right">Выручка, ₽</TableHead>
                <TableHead className="w-[110px] text-right">Ср. тариф</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">Загрузка…</TableCell></TableRow>
              )}
              {!isLoading && clients.length === 0 && (
                <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">Корп-клиенты не загружены (справочник «Организации» в канале сессий)</TableCell></TableRow>
              )}
              {clients.map((c) => (
                <TableRow key={c.phone}>
                  <TableCell className="text-sm font-medium max-w-[280px] truncate">{c.name}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{CORP_MODE_LABEL[c.mode] ?? c.mode}</TableCell>
                  <TableCell className="text-sm whitespace-nowrap">{c.contract_start || '—'}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums">{c.sessions.toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums">{Math.round(c.energy_kwh).toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums">{Math.round(c.corp_revenue).toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums">
                    {c.avg_tariff ? `${c.avg_tariff.toFixed(2)} ₽` : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export function ContractorsPage() {
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const { data: counterparties = [], isLoading } = useCounterparties()
  const { data: allContracts = [] } = useContracts()
  const [view, setView] = useState<'counterparties' | 'contracts' | 'corp'>('counterparties')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<string>('all')
  const [sortBy, setSortBy] = useState<'name' | 'contracts'>('name')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Число договоров на контрагента (ключ = externalRef из 1С или наш id).
  const contractCount = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of allContracts) {
      if (!c.counterpartyId) continue
      m.set(c.counterpartyId, (m.get(c.counterpartyId) ?? 0) + 1)
    }
    return m
  }, [allContracts])
  const cpContracts = (c: Counterparty) =>
    (c.externalRef ? contractCount.get(c.externalRef) ?? 0 : 0) + (contractCount.get(c.id) ?? 0)

  // Счётчики по ролям (для чипсов-фильтров).
  const roleCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of counterparties)
      for (const a of c.aliases ?? []) m.set(a, (m.get(a) ?? 0) + 1)
    return m
  }, [counterparties])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = counterparties.filter((c) => {
      if (roleFilter !== 'all' && !(c.aliases ?? []).includes(roleFilter)) return false
      if (!q) return true
      return c.name.toLowerCase().includes(q) || (c.inn ?? '').includes(q)
    })
    if (sortBy === 'contracts')
      return [...list].sort((a, b) => cpContracts(b) - cpContracts(a))
    return list
  }, [counterparties, search, roleFilter, sortBy, contractCount])

  const selected = counterparties.find((c) => c.id === selectedId) ?? null
  const chip = chipCls

  return (
    <div className="flex-1 min-w-0 p-4 lg:p-6">
      <div className="mb-4 flex items-center gap-2">
        <Building2 className="h-6 w-6 text-primary shrink-0" />
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">Контрагенты и договоры</h1>
          <p className="text-sm text-muted-foreground">
            Разрез по контрагентам: их реквизиты, договоры, охват точек и ограничения по разрезам.
          </p>
        </div>
      </div>

      {/* Переключатель режимов: список контрагентов / все договоры */}
      <div className="mb-4 inline-flex rounded-lg border border-border/60 bg-muted/30 p-0.5">
        <button onClick={() => setView('counterparties')}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors ${view === 'counterparties' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
          Контрагенты ({counterparties.length})
        </button>
        <button onClick={() => setView('contracts')}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors ${view === 'contracts' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
          Все договоры ({allContracts.length})
        </button>
        {isEnergy && (
          <button onClick={() => setView('corp')}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${view === 'corp' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
            Покупатели (корп.)
          </button>
        )}
      </div>

      {view === 'corp' ? (
        <CorpClientsView />
      ) : view === 'contracts' ? (
        <AllContractsView counterparties={counterparties} />
      ) : (
      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-4">
        {/* Список контрагентов */}
        <Card className="lg:h-[calc(100vh-12rem)] flex flex-col">
          <CardContent className="p-3 flex flex-col gap-2.5 min-h-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <Input placeholder="Поиск по имени или ИНН..." value={search}
                onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9" />
            </div>

            {/* Фильтр по ролям */}
            <div className="flex flex-wrap gap-1">
              <button onClick={() => setRoleFilter('all')} className={chip(roleFilter === 'all')}>
                Все · {counterparties.length}
              </button>
              {ROLE_ORDER.filter((r) => roleCounts.get(r)).map((r) => (
                <button key={r} onClick={() => setRoleFilter(r)} className={chip(roleFilter === r)}>
                  {ROLE_META[r].label} · {roleCounts.get(r)}
                </button>
              ))}
            </div>

            <CounterpartyFormDialog>
              <Button size="sm" variant="outline" className="w-full"><Plus className="size-4 mr-2" /> Добавить контрагента</Button>
            </CounterpartyFormDialog>

            {/* Счётчик + сортировка */}
            <div className="flex items-center justify-between text-[11px] text-muted-foreground px-0.5">
              <span>Найдено: {filtered.length}{filtered.length !== counterparties.length && ` из ${counterparties.length}`}</span>
              <button
                onClick={() => setSortBy((s) => (s === 'name' ? 'contracts' : 'name'))}
                className="hover:text-foreground transition-colors"
                title="Переключить сортировку"
              >
                сортировка: {sortBy === 'name' ? 'по имени' : 'по договорам'}
              </button>
            </div>

            <div className="overflow-y-auto space-y-0.5 min-h-0 -mr-1 pr-1">
              {isLoading && <div className="text-sm text-muted-foreground p-2">Загрузка…</div>}
              {!isLoading && filtered.length === 0 && (
                <div className="text-sm text-muted-foreground p-2">Контрагенты не найдены.</div>
              )}
              {filtered.map((c) => {
                const roles = (c.aliases ?? []).filter((a) => ROLE_META[a])
                const n = cpContracts(c)
                return (
                  <button
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={`w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                      c.id === selectedId ? 'bg-accent' : 'hover:bg-muted'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium truncate">{c.name}</div>
                      {n > 0 && (
                        <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
                          {n} дог.
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 flex-wrap mt-0.5">
                      {roles.length > 0
                        ? roles.map((r) => (
                            <span key={r} className={`text-[9px] leading-none px-1 py-0.5 rounded border ${ROLE_META[r].cls}`}>
                              {ROLE_META[r].label}
                            </span>
                          ))
                        : (
                          <span className="text-xs text-muted-foreground">
                            {c.inn ? `ИНН ${c.inn}` : 'ИНН не задан'}
                          </span>
                        )}
                    </div>
                  </button>
                )
              })}
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
      )}
    </div>
  )
}

export default ContractorsPage
