/**
 * «Контрагенты» (раздел «Данные») — разрез контрагентов и их договоров (ось
 * контрагент↔договор↔точки/разрезы). Мастер-деталь: слева список контрагентов,
 * справа — выбранный контрагент с полными реквизитами из 1С, где он работает,
 * и его договоры (с детальной карточкой каждого).
 */
import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Search, Building2, MapPin, Loader2, Database, FileText } from 'lucide-react'
import { useCounterparties, useContracts, useCounterpartyLocations } from '@/hooks/useReferences'
import { ContractScopeDialog, ContractScopeBadgeLabel } from '@/components/reference/ContractScopeDialog'
import type { Counterparty, Contract } from '@/types'

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
      <div>
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
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
            Договоры ({contracts.length})
          </p>
          {kindCounts.map(([k, n]) => (
            <Badge key={k} variant="outline" className={`text-[11px] ${KIND_META[k]?.cls || ''}`}>
              {kindLabel(k)}: {n}
            </Badge>
          ))}
        </div>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[160px]">Номер</TableHead>
                <TableHead className="w-[100px]">Дата</TableHead>
                <TableHead>Вид</TableHead>
                <TableHead className="w-[160px]">Охват</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contracts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground h-20">
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
