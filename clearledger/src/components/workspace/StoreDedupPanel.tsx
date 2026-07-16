/**
 * «Магазин» → Контроль → Дубли.
 *
 * Анализ дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ:
 * обзор (KPI), группы дублей (нечёткий матч, «в ассортименте»=не дубль), мост
 * касса↔карточка (коды на помеченные, ≥2 кода, рассинхрон цен), статусы/трекинг
 * правок, экспорт плана дедупа. Данные — кеш dedup_* (pull 208 + склейка ЦБ по GUID).
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import * as XLSX from 'xlsx'
import {
  CopyCheck, Search, Download, ChevronDown, ChevronRight, AlertTriangle,
  Tag, Store, Loader2, Check, FileSpreadsheet, RefreshCw, ShoppingCart,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  getDedupSummary, getDedupGroups, getDedupBridge, setDedupStatus, getDedupExport, reloadDedup,
  type DedupGroup, type DedupMember,
} from '@/services/storeService'

const fmtPrice = (p: number | null | undefined) =>
  p == null ? '—' : new Intl.NumberFormat('ru-RU').format(p) + ' ₽'

const STATUSES: { key: string; label: string; cls: string }[] = [
  { key: 'pending', label: 'Не разобрано', cls: 'border-zinc-600 text-zinc-400' },
  { key: 'not_duplicate', label: 'Не дубль', cls: 'border-sky-400/50 text-sky-300/80' },
  { key: 'in_progress', label: 'В работе', cls: 'border-amber-400/50 text-amber-300/80' },
  { key: 'repointed', label: 'Перецеплено', cls: 'border-violet-400/50 text-violet-300/80' },
  { key: 'merged', label: 'Слито', cls: 'border-emerald-400/50 text-emerald-300/80' },
  { key: 'done', label: 'Готово', cls: 'bg-emerald-600/80 text-white border-transparent' },
]
const statusMeta = (k: string) => STATUSES.find((s) => s.key === k) ?? STATUSES[0]

const PREFIX_CLS: Record<string, string> = {
  '008': 'border-blue-400/50 text-blue-300/80',
  '208': 'border-amber-400/50 text-amber-300/80',
  'ЦБ': 'border-violet-400/50 text-violet-300/80',
}
const fmt = (n: number | undefined) => new Intl.NumberFormat('ru-RU').format(n ?? 0)

// ── KPI ──────────────────────────────────────────────────────────────────────
function Kpi({ label, value, hint, warn }: { label: string; value: string; hint?: string; warn?: boolean }) {
  return (
    <div className={cn('rounded-lg border bg-card/40 px-3 py-2', warn ? 'border-red-400/40' : 'border-border/50')}>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn('text-lg font-semibold tabular-nums', warn && 'text-red-400')}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

// ── карточка группы дублей ────────────────────────────────────────────────────
function GroupCard({ g }: { g: DedupGroup }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  // канон по умолчанию — карточка, что РЕАЛЬНО продаётся сейчас (recommendedCanon)
  const [canon, setCanon] = useState<string | null>(g.canonGuid ?? g.recommendedCanon)
  const [note, setNote] = useState(g.note ?? '')
  const sm = statusMeta(g.status)

  const mut = useMutation({
    mutationFn: (patch: { status?: string; canonGuid?: string | null; note?: string }) =>
      setDedupStatus({ entityType: 'group', entityKey: g.key, ...patch }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['dedup-groups'] }); qc.invalidateQueries({ queryKey: ['dedup-summary'] }); toast.success('Статус сохранён') },
    onError: () => toast.error('Не удалось сохранить'),
  })

  return (
    <div className="rounded-lg border border-border/50 bg-card/30">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/40">
        {open ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{g.title}</span>
        {g.priceSpread.length > 1 && (
          <Badge variant="outline" className="border-red-400/50 text-red-300/80 gap-1"><AlertTriangle className="size-3" />цены {g.priceSpread.join('/')}</Badge>
        )}
        {g.sellingCount === 0 ? (
          <Badge variant="outline" className="border-zinc-600 text-zinc-400 gap-1"><ShoppingCart className="size-3" />нет продаж</Badge>
        ) : g.sellingCount === 1 ? (
          <Badge variant="outline" className="border-emerald-400/50 text-emerald-300/80 gap-1"><ShoppingCart className="size-3" />продаётся 1</Badge>
        ) : (
          <Badge variant="outline" className="border-amber-400/50 text-amber-300/80 gap-1"><ShoppingCart className="size-3" />продаётся {g.sellingCount} ⚠</Badge>
        )}
        {g.prefixes.map((p) => (
          <Badge key={p} variant="outline" className={cn('text-[10px]', PREFIX_CLS[p] ?? 'border-zinc-600 text-zinc-400')}>{p}</Badge>
        ))}
        <Badge variant="outline" className="text-[10px]">{g.count} карт. · {g.live} живых</Badge>
        <Badge variant="outline" className={cn('text-[10px]', sm.cls)}>{sm.label}</Badge>
      </button>

      {open && (
        <div className="border-t border-border/40 px-3 py-2.5">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead>
                <tr className="border-b border-border/40 text-left text-muted-foreground">
                  <th className="py-1 pr-2 font-medium">Канон</th>
                  <th className="py-1 pr-2 font-medium">Код</th>
                  <th className="py-1 pr-2 font-medium">Наименование</th>
                  <th className="py-1 pr-2 font-medium text-right">Цена</th>
                  <th className="py-1 pr-2 font-medium">Коды кассы</th>
                  <th className="py-1 pr-2 font-medium">ЦБ</th>
                  <th className="py-1 pr-2 font-medium">Статус карт.</th>
                </tr>
              </thead>
              <tbody>
                {g.members.map((m) => <MemberRow key={m.guid} m={m} canon={canon} onCanon={setCanon} spread={g.priceSpread} recommended={g.recommendedCanon} />)}
              </tbody>
            </table>
          </div>

          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Select value={g.status} onValueChange={(v) => mut.mutate({ status: v })}>
              <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {STATUSES.map((s) => <SelectItem key={s.key} value={s.key} className="text-xs">{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Заметка (что сделано / кем)…" className="h-8 max-w-xs flex-1 text-xs" />
            <Button size="sm" variant="outline" className="h-8 text-xs"
              onClick={() => mut.mutate({ canonGuid: canon, note })} disabled={mut.isPending}>
              {mut.isPending ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Check className="mr-1 size-3.5" />}
              Сохранить {canon ? '(канон выбран)' : ''}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function MemberRow({ m, canon, onCanon, spread, recommended }: {
  m: DedupMember; canon: string | null; onCanon: (g: string) => void; spread: number[]; recommended: string | null
}) {
  const isCanon = canon === m.guid
  const isRec = recommended === m.guid
  // при рассинхроне подсвечиваем цену, отличную от минимальной живой (переоценённый дубль)
  const desync = spread.length > 1 && m.price != null && !m.marked && m.price !== Math.min(...spread)
  return (
    <tr className={cn('border-b border-border/20', m.marked && 'opacity-55',
      isRec && 'bg-emerald-500/5')}>
      <td className="py-1 pr-2">
        <button onClick={() => onCanon(m.guid)} title="Сделать каноном (хозяином группы)"
          className={cn('inline-flex size-4 items-center justify-center rounded-full border',
            isCanon ? 'border-emerald-500 bg-emerald-500 text-white' : 'border-border hover:border-emerald-400')}>
          {isCanon && <Check className="size-3" />}
        </button>
      </td>
      <td className="py-1 pr-2 font-mono text-[11px] whitespace-nowrap">
        <Badge variant="outline" className={cn('mr-1 text-[9px]', PREFIX_CLS[m.prefix ?? ''] ?? 'border-zinc-600 text-zinc-400')}>{m.prefix}</Badge>
        {m.code}
      </td>
      <td className="py-1 pr-2">
        {m.name}
        {m.marked && <span className="ml-1 rounded bg-red-500/15 px-1 text-[9px] text-red-300">помечена</span>}
        {m.sellsNow && (
          <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-emerald-500/15 px-1 text-[9px] text-emerald-300"
            title={`Касса реально продаёт через эту карточку: ${m.soldQty} шт за 30 дн`}>
            <ShoppingCart className="size-2.5" />продаётся {Math.round(m.soldQty ?? 0)}
          </span>
        )}
        {isRec && <span className="ml-1 rounded bg-emerald-600/80 px-1 text-[9px] text-white">канон по продажам</span>}
      </td>
      <td className={cn('py-1 pr-2 text-right tabular-nums whitespace-nowrap', desync && 'font-semibold text-red-400')} title={desync ? 'Цена отличается от минимальной в группе' : undefined}>
        {fmtPrice(m.price)}
      </td>
      <td className="py-1 pr-2 text-[11px]">
        {m.nsCodes.length === 0 ? <span className="text-muted-foreground/50">—</span> : m.nsCodes.map((c) => (
          <span key={c.nsCode} className={cn('mr-1 inline-block rounded px-1', c.active ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground line-through')}>
            {c.nsCode}
          </span>
        ))}
        {m.marked && m.nsActive && <span className="ml-1 rounded bg-red-500/20 px-1 text-[9px] text-red-300">касса бьёт удалённую!</span>}
      </td>
      <td className="py-1 pr-2">{m.inCb ? <Check className="size-3.5 text-emerald-400" /> : <span className="text-muted-foreground/40">—</span>}</td>
      <td className="py-1 pr-2 text-[11px] text-muted-foreground">{m.marked ? 'на удаление' : 'активна'}</td>
    </tr>
  )
}

// ── мост касса ↔ карточка ─────────────────────────────────────────────────────
function BridgeTab() {
  const [kind, setKind] = useState<'on_marked' | 'multi' | 'price_split'>('on_marked')
  const { data = [], isLoading } = useQuery({ queryKey: ['dedup-bridge', kind], queryFn: () => getDedupBridge(kind) })
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {([
          ['on_marked', 'Коды на помеченные карточки'],
          ['multi', 'Карточки с ≥2 кодами'],
        ] as const).map(([k, l]) => (
          <button key={k} onClick={() => setKind(k)}
            className={cn('rounded-md px-2.5 py-1.5 text-xs transition-colors', kind === k ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-accent')}>{l}</button>
        ))}
      </div>
      {kind === 'on_marked' && (
        <p className="text-[11px] text-muted-foreground">Активные коды кассы, бьющие на <b>помеченную на удаление</b> карточку — касса пробивает удалённый дубль (риск старой цены).</p>
      )}
      {isLoading ? <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div> : (
        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full min-w-[560px] text-xs">
            <thead>
              <tr className="border-b border-border/40 bg-muted/30 text-left text-muted-foreground">
                {kind === 'on_marked'
                  ? <><th className="p-2 font-medium">Код кассы</th><th className="p-2 font-medium">Склад</th><th className="p-2 font-medium">Карточка (помечена)</th><th className="p-2 font-medium">Цена</th></>
                  : <><th className="p-2 font-medium">Карточка</th><th className="p-2 font-medium">Кодов</th><th className="p-2 font-medium">Коды кассы</th><th className="p-2 font-medium">Цены</th></>}
              </tr>
            </thead>
            <tbody>
              {data.map((r, i) => (
                <tr key={i} className="border-b border-border/20">
                  {kind === 'on_marked'
                    ? <><td className="p-2 font-mono">{r.nsCode}</td><td className="p-2">{r.warehouse}</td><td className="p-2">{r.cardName}</td><td className="p-2 tabular-nums">{r.price ?? '—'}</td></>
                    : <><td className="p-2">{r.cardName}{r.marked && <span className="ml-1 rounded bg-red-500/15 px-1 text-[9px] text-red-300">помечена</span>}</td><td className="p-2 tabular-nums">{r.codes}</td><td className="p-2 font-mono text-[10px]">{(r.nsCodes ?? []).join(', ')}</td><td className="p-2 tabular-nums">{(r.prices ?? []).join(' / ') || '—'}</td></>}
                </tr>
              ))}
              {data.length === 0 && <tr><td colSpan={4} className="p-6 text-center text-muted-foreground">Нет записей</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── корневой ──────────────────────────────────────────────────────────────────
export function StoreDedupPanel() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'groups' | 'bridge'>('groups')
  const [q, setQ] = useState('')
  const [onlyLive, setOnlyLive] = useState(true)
  const [inclAssort, setInclAssort] = useState(false)
  const [priceDesync, setPriceDesync] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: sum } = useQuery({ queryKey: ['dedup-summary'], queryFn: getDedupSummary })
  const { data: groups = [], isLoading } = useQuery({
    queryKey: ['dedup-groups', q, onlyLive, inclAssort, priceDesync, statusFilter],
    queryFn: () => getDedupGroups({ q, onlyLive, includeAssortment: inclAssort, priceDesync, status: statusFilter === 'all' ? undefined : statusFilter }),
    enabled: tab === 'groups',
  })

  const reloadMut = useMutation({
    mutationFn: (file: File) => reloadDedup(file),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['dedup-summary'] })
      qc.invalidateQueries({ queryKey: ['dedup-groups'] })
      qc.invalidateQueries({ queryKey: ['dedup-bridge'] })
      toast.success(`Срез обновлён: ${r.cards} карточек, ${r.bindings} привязок, ${r.prices} цен`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось загрузить дамп'),
  })

  const doneCount = useMemo(() => groups.filter((g) => ['merged', 'done'].includes(g.status)).length, [groups])

  const exportExcel = async () => {
    try {
      const rows = await getDedupExport()
      const ws = XLSX.utils.json_to_sheet(rows.map((r) => ({
        'Группа': r.group, 'Статус': r.status, 'Рассинхрон цен': r.priceSpread,
        'Дубль код': r.dupCode, 'Дубль наим.': r.dupName, 'Дубль цена': r.dupPrice,
        'Дубль помечен': r.dupMarked ? 'да' : '', 'Дубль коды кассы': r.dupNsCodes.join(', '),
        'Канон код': r.canonCode, 'Канон наим.': r.canonName, 'Канон цена': r.canonPrice,
        'Дубль GUID': r.dupGuid, 'Канон GUID': r.canonGuid,
      })))
      const wb = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(wb, ws, 'Дедуп 208')
      XLSX.writeFile(wb, `dedup_plan_208_${new Date().toISOString().slice(0, 10)}.xlsx`)
      toast.success(`Excel: ${rows.length} пар дубль→канон`)
    } catch { toast.error('Не удалось выгрузить Excel') }
  }

  const exportPlan = async () => {
    try {
      const rows = await getDedupExport()
      const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `dedup_plan_208_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      toast.success(`Экспортирован план: ${rows.length} пар дубль→канон`)
    } catch { toast.error('Не удалось выгрузить план') }
  }

  return (
    <div className="p-4 space-y-4">
      {/* Заголовок */}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary shrink-0"><CopyCheck className="size-5" /></div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Контроль дублей номенклатуры</h3>
          <p className="text-sm text-muted-foreground mt-0.5 leading-relaxed">
            Цепочка Нефтосервер → локальная 1С 208 → ЦБ. Один товар под кодами 008/208/ЦБ, касса бьёт удалённый дубль, рассинхрон цен — видно наглядно, отмечается статусами.
          </p>
          {sum?.updatedAt && (
            <p className="mt-0.5 text-[11px] text-muted-foreground/70">Срез 208 обновлён: {new Date(sum.updatedAt).toLocaleString('ru-RU')}</p>
          )}
        </div>
      </div>

      {/* KPI */}
      {sum && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <Kpi label="Карточек 208" value={fmt(sum.cardsTotal)} hint={`008:${fmt(sum.byPrefix['008'])} · 208:${fmt(sum.byPrefix['208'])} · ЦБ:${fmt(sum.byPrefix['ЦБ'])}`} />
          <Kpi label="Групп дублей" value={fmt(sum.dupGroups)} hint={`лишних ${fmt(sum.excessCards)} · живых ${fmt(sum.liveDupGroups)}`} />
          <Kpi label="Рассинхрон цен" value={fmt(sum.priceDesyncGroups)} hint="разные цены на дубли" warn={(sum.priceDesyncGroups ?? 0) > 0} />
          <Kpi label="В ассортименте" value={fmt(sum.assortmentCards)} hint="не дубли (исключены)" />
          <Kpi label="Привязок кассы" value={fmt(sum.nsActive)} hint={`с ЦБ-склейкой ${fmt(sum.cbLinked)}`} />
          <Kpi label="Касса → удалён." value={fmt(sum.nsOnMarked)} hint="бьёт помеченную" warn={(sum.nsOnMarked ?? 0) > 0} />
          <Kpi label="Карт. ≥2 кодов" value={fmt(sum.multiCodeCards)} hint="несколько кодов кассы" />
        </div>
      )}

      {/* Вкладки */}
      <div className="flex items-center gap-1.5 border-b border-border/40">
        <button onClick={() => setTab('groups')} className={cn('flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm', tab === 'groups' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground')}><Tag className="size-4" />Группы дублей</button>
        <button onClick={() => setTab('bridge')} className={cn('flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm', tab === 'bridge' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground')}><Store className="size-4" />Мост касса↔карточка</button>
        <div className="flex-1" />
        <input ref={fileRef} type="file" accept=".txt" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) reloadMut.mutate(f); if (fileRef.current) fileRef.current.value = '' }} />
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => fileRef.current?.click()} disabled={reloadMut.isPending} title="Загрузить свежий дамп 208 (probe-раннер)">
          {reloadMut.isPending ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <RefreshCw className="mr-1 size-3.5" />}Обновить срез
        </Button>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={exportExcel}><FileSpreadsheet className="mr-1 size-3.5" />Excel</Button>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={exportPlan}><Download className="mr-1 size-3.5" />JSON</Button>
      </div>

      {tab === 'groups' ? (
        <div className="space-y-2.5">
          {/* Фильтры */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[180px] flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по названию…" className="h-8 pl-8 text-xs" />
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={onlyLive} onChange={(e) => setOnlyLive(e.target.checked)} />только с &gt;1 живой</label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={priceDesync} onChange={(e) => setPriceDesync(e.target.checked)} />только рассинхрон цен</label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" checked={inclAssort} onChange={(e) => setInclAssort(e.target.checked)} />показать «в ассортименте»</label>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 w-[140px] text-xs"><SelectValue placeholder="Статус" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all" className="text-xs">Все статусы</SelectItem>
                {STATUSES.map((s) => <SelectItem key={s.key} value={s.key} className="text-xs">{s.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <span className="ml-auto text-xs text-muted-foreground">{groups.length} групп · разобрано {doneCount}</span>
          </div>

          {isLoading ? <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
            : groups.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">Групп по фильтру нет</p>
            : <div className="space-y-1.5">{groups.map((g) => <GroupCard key={g.key} g={g} />)}</div>}
        </div>
      ) : <BridgeTab />}
    </div>
  )
}

export default StoreDedupPanel
