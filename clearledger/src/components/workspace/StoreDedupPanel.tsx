/**
 * «Магазин» → Контроль → Дубли.
 *
 * Анализ дублей номенклатуры по цепочке Нефтосервер → локальная 1С 208 → ЦБ:
 * обзор (KPI), группы дублей (нечёткий матч, «в ассортименте»=не дубль), мост
 * касса↔карточка (коды на помеченные, ≥2 кода, рассинхрон цен), статусы/трекинг
 * правок, экспорт плана дедупа. Данные — кеш dedup_* (pull 208 + склейка ЦБ по GUID).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import * as XLSX from 'xlsx'
import {
  CopyCheck, Search, Download, ChevronDown, ChevronRight, AlertTriangle,
  Tag, Store, Loader2, Check, FileSpreadsheet, RefreshCw, ShoppingCart,
  PlayCircle, GitMerge, Upload, Info, Archive,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useCompany } from '@/contexts/CompanyContext'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  getDedupSummary, getDedupGroups, getDedupBridge, setDedupStatus, getDedupExport, reloadDedup,
  correctDedup, refreshDedup, getDedupJobs, cancelDedupJob, getDedupMergeMap,
  type DedupGroup, type DedupMember, type DedupJob,
} from '@/services/storeService'

const fmtPrice = (p: number | null | undefined) =>
  p == null ? '—' : new Intl.NumberFormat('ru-RU').format(p) + ' ₽'

const STATUSES: { key: string; label: string; cls: string }[] = [
  { key: 'pending', label: 'Не разобрано', cls: 'border-zinc-600 text-zinc-400' },
  { key: 'not_duplicate', label: 'Не дубль', cls: 'border-sky-400/50 text-sky-300/80' },
  // Ключ БД остаётся not_used; UI-семантика — «архив»: карточка снята с продажи,
  // но НЕ удаляется (история + GUID сохраняются). Цвет нейтральный, не тревожный.
  { key: 'not_used', label: 'Архив (снята с продажи)', cls: 'border-slate-400/40 text-slate-300/70' },
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
// Бейдж показывает, ГДЕ заведён код карточки, а не чья она: вся витрина — одна
// база (локальная 1С АЗС 208), карточек других станций тут нет. Читается это
// неверно с одного взгляда («008» = станция 8), поэтому бейдж подписан «код NNN»
// + легенда над списком: тултип не наводят, а ошибка стоит дорого — по префиксу
// отсекли бы 28 групп живых проблем 208.
const PREFIX_HINT: Record<string, string> = {
  '008': 'Код заведён в старой нумерации базы 208 — не станция 8. Такие карточки бьёт касса 208',
  '208': 'Код заведён на АЗС 208 в своей нумерации',
  'ЦБ': 'Код пришёл из центральной базы',
}
const PREFIX_WHERE: Record<string, string> = {
  '008': 'старая нумерация',
  '208': 'заведено на 208',
  'ЦБ': 'из центральной базы',
}

// ── легенда: что означает бейдж кода (и что он НЕ означает) ──────────────────
function PrefixLegend({ byPrefix }: { byPrefix: Record<string, number> }) {
  return (
    <div className="flex gap-2 rounded-lg border border-blue-400/25 bg-blue-500/[0.04] px-3 py-2 text-[11px] leading-relaxed">
      <Info className="mt-0.5 size-3.5 shrink-0 text-blue-300/70" />
      <div className="min-w-0 space-y-1">
        <div className="text-foreground/90">
          Все карточки — из одной базы, локальной 1С <b>АЗС 208</b>. Бейдж показывает, где заведён код, а не чья карточка:
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {(['008', '208', 'ЦБ'] as const).map((p) => (
            <span key={p} className="inline-flex items-center gap-1.5">
              <Badge variant="outline" className={cn('text-[9px]', PREFIX_CLS[p])}>код {p}</Badge>
              <span className="text-muted-foreground">{PREFIX_WHERE[p]} · {fmt(byPrefix[p])} карт.</span>
            </span>
          ))}
        </div>
        <div className="text-muted-foreground">
          Касса 208 бьёт через <b>все три</b> — чаще всего как раз через «код 008»: у «Троса» (008000001476) активен код кассы 5147 склада 208 по 550 ₽ при живых дублях 440 и 265 ₽.
          Поэтому принадлежность к станции определяет <span className="text-foreground/80">склад привязки кассы</span>, а не код — это и есть фильтр «только контур 208».
        </div>
      </div>
    </div>
  )
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
  // Выбор канона живёт в локальном state, пока не нажали «Сохранить». Радио сразу
  // стоит на рекомендации — со стороны выбор выглядит сделанным, хотя в БД пусто.
  // Поэтому «решение принято» = g.canonGuid из БД, а расхождение с ним — «не сохранено».
  const savedCanon = g.canonGuid
  const dirty = canon !== savedCanon || note !== (g.note ?? '')

  const mut = useMutation({
    mutationFn: (patch: { status?: string; canonGuid?: string | null; note?: string }) =>
      setDedupStatus({ entityType: 'group', entityKey: g.key, ...patch }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['dedup-groups'] }); qc.invalidateQueries({ queryKey: ['dedup-summary'] }); toast.success('Статус сохранён') },
    onError: () => toast.error('Не удалось сохранить'),
  })

  // Перецеп кодов кассы на канон — только по команде менеджера, погруппово.
  // Канон в задании берётся из статуса, поэтому сначала фиксируем выбор.
  const job = useMutation({
    mutationFn: async () => {
      await setDedupStatus({ entityType: 'group', entityKey: g.key, canonGuid: canon, status: 'in_progress' })
      return correctDedup({ groupKeys: [g.key], dryRun: true })
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['dedup-groups'] })
      qc.invalidateQueries({ queryKey: ['dedup-jobs'] })
      if (r.error) toast.error(r.error)
      else toast.success(`Задание создано: ${r.codes} код(ов) кассы → канон. Нода 208 выполнит пробный прогон.`)
    },
    onError: () => toast.error('Не удалось создать задание'),
  })
  // Перецеп трогает только кассу своей АЗС: коды чужих складов не в счёт.
  const dupCodes = g.members.filter((m) => m.guid !== canon)
    .reduce((n, m) => n + m.nsCodes.filter((c) => c.active && c.wh === '208').length, 0)

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
        {savedCanon ? (
          <Badge variant="outline" className="gap-1 border-emerald-400/50 text-[10px] text-emerald-300/80"
            title={g.canonExternal
              ? `Канон-хозяин в соседней группе (нормализация имени развела дубли): ${g.canonName ?? '—'}`
              : `Канон выбран и сохранён: ${g.canonName ?? g.members.find((m) => m.guid === savedCanon)?.name ?? '—'}`}>
            <Check className="size-3" />{g.canonExternal ? 'канон ↗' : 'канон выбран'}
          </Badge>
        ) : (
          <Badge variant="outline" className="border-zinc-600 text-[10px] text-zinc-500"
            title="Канон ещё не сохранён: раскройте группу, выберите карточку-хозяина и нажмите «Сохранить»">канон не выбран</Badge>
        )}
        {!g.inScope208 && (
          <Badge variant="outline" className="border-zinc-600 text-[10px] text-zinc-500"
            title="Касса 208 через эту группу не работает: нет активных кодов склада 208 и нет продаж">вне контура 208</Badge>
        )}
        {g.prefixes.map((p) => (
          <Badge key={p} variant="outline" className={cn('text-[10px]', PREFIX_CLS[p] ?? 'border-zinc-600 text-zinc-400')}
            title={PREFIX_HINT[p] ?? 'Префикс кода номенклатуры'}>код {p}</Badge>
        ))}
        <Badge variant="outline" className="text-[10px]">{g.count} карт. · {g.live} живых</Badge>
        <Badge variant="outline" className={cn('text-[10px]', sm.cls)}>{sm.label}</Badge>
      </button>

      {open && (
        <div className="border-t border-border/40 px-3 py-2.5">
          {g.canonExternal && (
            <div className="mb-2 flex items-start gap-1.5 rounded border border-emerald-400/30 bg-emerald-500/[0.06] px-2 py-1.5 text-[11px] text-emerald-200/90">
              <GitMerge className="mt-0.5 size-3.5 shrink-0" />
              <span>Канон-хозяин — <b>{g.canonName ?? '—'}</b> — из другой карточки/группы (оператор указал кодом в примечании: нормализация имени развела реальные дубли). Дубли этой группы сливаются на него.</span>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead>
                <tr className="border-b border-border/40 text-left text-muted-foreground">
                  <th className="py-1 pr-2 font-medium">Канон</th>
                  <th className="py-1 pr-2 font-medium">Код</th>
                  <th className="py-1 pr-2 font-medium">Наименование</th>
                  <th className="py-1 pr-2 font-medium text-right">Цена</th>
                  <th className="py-1 pr-2 font-medium">Коды кассы</th>
                  <th className="py-1 pr-2 font-medium" title="Связь с центральной базой. База 208 — узел РИБ ЦБ, поэтому карточка есть в ЦБ почти всегда (7238 из 7241) и код совпадает — отмечаем только аномалии">Связь с ЦБ</th>
                  <th className="py-1 pr-2 font-medium">Статус карт.</th>
                </tr>
              </thead>
              <tbody>
                {g.members.map((m) => <MemberRow key={m.guid} m={m} canon={canon} onCanon={setCanon} spread={g.priceSpread} recommended={g.recommendedCanon} savedCanon={savedCanon} />)}
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
            <Button size="sm" variant="outline" disabled={mut.isPending || !dirty}
              className={cn('h-8 text-xs', dirty && 'border-emerald-400/50 text-emerald-300/90 hover:bg-emerald-500/10')}
              onClick={() => mut.mutate({ canonGuid: canon, note })}
              title={dirty ? 'Выбор ещё не записан в базу' : 'Всё сохранено'}>
              {mut.isPending ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Check className="mr-1 size-3.5" />}
              {dirty ? 'Сохранить выбор' : 'Сохранено'}
            </Button>
            <Button size="sm" variant="outline" className="h-8 border-violet-400/40 text-xs text-violet-300/90 hover:bg-violet-500/10"
              onClick={() => job.mutate()} disabled={job.isPending || !canon || dupCodes === 0}
              title={!canon ? 'Сначала выберите канон' : dupCodes === 0 ? 'На дублях нет активных кодов кассы' :
                `Пробный прогон: нода 208 покажет план перецепа ${dupCodes} код(ов) кассы на канон, без записи в 1С`}>
              {job.isPending ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <PlayCircle className="mr-1 size-3.5" />}
              Перецеп пробно{dupCodes > 0 ? ` (${dupCodes})` : ''}
            </Button>
            <Button size="sm" variant="ghost"
              className={cn('ml-auto h-8 text-xs', g.status === 'not_used'
                ? 'text-slate-300/90' : 'text-muted-foreground hover:bg-slate-500/10 hover:text-slate-200')}
              onClick={() => mut.mutate({ status: g.status === 'not_used' ? 'pending' : 'not_used' })}
              disabled={mut.isPending}
              title="Снять с продажи → в архив: карточка выводится из активного ассортимента 208 (деактивация кода кассы), но НЕ удаляется — история продаж и GUID сохраняются. Не слияние. Повторный клик — вернуть.">
              <Archive className="mr-1 size-3.5" />
              {g.status === 'not_used' ? 'В архиве ✓' : 'В архив'}
            </Button>
          </div>
          <div className="mt-1.5 text-[10px] text-muted-foreground/70">
            Перецеп меняет только привязку кодов кассы к канону. Слияние карточек (ЗаменитьСсылки) на активной кассе
            не автоматизируем — берите «Карту слияния» и запускайте .epf в тихое окно.
          </div>
        </div>
      )}
    </div>
  )
}

function MemberRow({ m, canon, onCanon, spread, recommended, savedCanon }: {
  m: DedupMember; canon: string | null; onCanon: (g: string) => void; spread: number[]
  recommended: string | null; savedCanon: string | null
}) {
  const isCanon = canon === m.guid
  const isRec = recommended === m.guid
  const isSaved = savedCanon === m.guid
  // при рассинхроне подсвечиваем цену, отличную от минимальной живой (переоценённый дубль)
  const desync = spread.length > 1 && m.price != null && !m.marked && m.price !== Math.min(...spread)
  return (
    <tr className={cn('border-b border-border/20', m.marked && 'opacity-55',
      isSaved ? 'bg-emerald-500/10' : isRec && 'bg-emerald-500/5')}>
      <td className="py-1 pr-2">
        <button onClick={() => onCanon(m.guid)}
          title={isSaved ? 'Канон группы — выбор сохранён' : isCanon ? 'Выбрано каноном, но ещё не сохранено — нажмите «Сохранить»' : 'Сделать каноном (хозяином группы)'}
          className={cn('inline-flex size-4 items-center justify-center rounded-full border',
            isCanon && isSaved ? 'border-emerald-500 bg-emerald-500 text-white'
              : isCanon ? 'border-emerald-400/70 border-dashed text-emerald-300'
              : 'border-border hover:border-emerald-400')}>
          {isCanon && <Check className="size-3" />}
        </button>
      </td>
      <td className="py-1 pr-2 font-mono text-[11px] whitespace-nowrap">
        <Badge variant="outline" className={cn('mr-1 text-[9px]', PREFIX_CLS[m.prefix ?? ''] ?? 'border-zinc-600 text-zinc-400')}
          title={PREFIX_HINT[m.prefix ?? ''] ?? 'Префикс кода номенклатуры'}>{m.prefix}</Badge>
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
        {isSaved && <span className="ml-1 rounded bg-emerald-600/80 px-1 text-[9px] text-white" title="Выбор канона сохранён">канон · сохранён</span>}
        {isRec && !isSaved && <span className="ml-1 rounded bg-emerald-500/15 px-1 text-[9px] text-emerald-300" title="Рекомендация по факту продаж — станет каноном после «Сохранить»">канон по продажам</span>}
      </td>
      <td className={cn('py-1 pr-2 text-right tabular-nums whitespace-nowrap', desync && 'font-semibold text-red-400')} title={desync ? 'Цена отличается от минимальной в группе' : undefined}>
        {fmtPrice(m.price)}
      </td>
      <td className="py-1 pr-2 text-[11px]">
        {m.nsCodes.length === 0 ? <span className="text-muted-foreground/50">—</span> : m.nsCodes.map((c) => (
          <span key={`${c.wh}-${c.nsCode}`}
            className={cn('mr-1 inline-block rounded px-1', c.active ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground line-through',
              c.wh !== '208' && 'opacity-60')}
            title={c.wh === '208' ? `Касса АЗС 208, код ${c.nsCode}` : `Склад ${c.wh} — чужой, перецеп его не трогает`}>
            {c.nsCode}{c.wh !== '208' && <span className="ml-0.5 text-[9px] opacity-70">·скл {c.wh}</span>}
          </span>
        ))}
        {m.marked && m.nsActive && <span className="ml-1 rounded bg-red-500/20 px-1 text-[9px] text-red-300">касса бьёт удалённую!</span>}
      </td>
      <td className="py-1 pr-2 text-[11px]">
        {m.cbStatus === 'missing' ? (
          <Badge variant="outline" className="border-amber-400/50 text-[9px] text-amber-300/80"
            title="Карточки нет в центральной базе: заведена локально на 208 и в ЦБ не уехала">нет в ЦБ</Badge>
        ) : m.cbStatus === 'code_diff' ? (
          <Badge variant="outline" className="border-amber-400/50 text-[9px] text-amber-300/80"
            title="Код карточки в ЦБ отличается от локального — рассинхрон нумерации">код ≠ ЦБ</Badge>
        ) : (
          <Check className="size-3.5 text-muted-foreground/40" aria-label="есть в ЦБ, код тот же" />
        )}
      </td>
      <td className="py-1 pr-2 text-[11px] text-muted-foreground">{m.marked ? 'на удаление' : 'активна'}</td>
    </tr>
  )
}

// ── мост касса ↔ карточка ─────────────────────────────────────────────────────
function BridgeTab() {
  const { companyId } = useCompany()
  const [kind, setKind] = useState<'on_marked' | 'multi' | 'price_split'>('on_marked')
  const { data = [], isLoading } = useQuery({ queryKey: ['dedup-bridge', companyId, kind], queryFn: () => getDedupBridge(kind) })
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

// ── задания корректировки ─────────────────────────────────────────────────────
const JOB_CLS: Record<string, string> = {
  pending: 'border-blue-400/50 text-blue-300/80',
  running: 'border-amber-400/50 text-amber-300/80',
  done: 'bg-emerald-600/80 text-white border-transparent',
  error: 'border-red-400/50 text-red-300/80',
  cancelled: 'border-zinc-600 text-zinc-500',
}
const JOB_LABEL: Record<string, string> = {
  pending: 'ждёт ноду', running: 'выполняется', done: 'выполнено', error: 'ошибка', cancelled: 'отменено',
}

function JobsTab({ jobs, isLoading }: { jobs: DedupJob[]; isLoading: boolean }) {
  const qc = useQueryClient()
  const cancel = useMutation({
    mutationFn: (id: string) => cancelDedupJob(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['dedup-jobs'] }); toast.success('Задание отменено') },
    onError: () => toast.error('Задание уже выполняется или выполнено'),
  })

  if (isLoading) return <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
  if (jobs.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        Заданий нет. Станция выполняет их по команде: «Обновить срез» или «Перецеп пробно» в группе.
      </p>
    )
  }
  return (
    <div className="space-y-1.5">
      {jobs.map((j) => (
        <div key={j.id} className="rounded-lg border border-border/50 bg-card/30 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">
              {j.kind === 'repoint' ? 'Перецеп кодов кассы' : j.kind === 'refresh' ? 'Сбор свежего среза' : j.kind}
            </span>
            <Badge variant="outline" className={cn('text-[10px]', JOB_CLS[j.status] ?? 'border-zinc-600 text-zinc-400')}>
              {JOB_LABEL[j.status] ?? j.status}
            </Badge>
            {j.dryRun && <Badge variant="outline" className="border-sky-400/50 text-[10px] text-sky-300/80">пробный (без записи)</Badge>}
            <Badge variant="outline" className="text-[10px]">
              склад {j.warehouse}{j.kind === 'repoint' ? ` · ${j.groups} групп · ${j.codes} код.` : ''}
            </Badge>
            <span className="ml-auto text-[11px] text-muted-foreground/70">
              {j.createdBy} · {j.createdAt ? new Date(j.createdAt).toLocaleString('ru-RU') : ''}
            </span>
            {['pending', 'running'].includes(j.status) && (
              <Button size="sm" variant="ghost" className="h-6 text-[11px] text-muted-foreground"
                onClick={() => cancel.mutate(j.id)} disabled={cancel.isPending}>Отменить</Button>
            )}
          </div>
          {j.titles.length > 0 && (
            <div className="mt-1 truncate text-[11px] text-muted-foreground">{j.titles.join(' · ')}</div>
          )}
          {j.result && (
            <div className="mt-1.5 rounded border border-border/40 bg-background/40 px-2 py-1 text-[11px]">
              {j.result.error ? <span className="text-red-300/90">{j.result.error}</span> : (
                <span className="text-muted-foreground">
                  Обработано {j.result.done ?? 0}{j.result.failed ? `, ошибок ${j.result.failed}` : ''}
                  {j.executedAt ? ` · ${new Date(j.executedAt).toLocaleString('ru-RU')}` : ''}
                </span>
              )}
              {j.result.log && j.result.log.length > 0 && (
                <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto font-mono text-[10px] text-muted-foreground/80">
                  {j.result.log.map((l, i) => <li key={i}>{l}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── корневой ──────────────────────────────────────────────────────────────────
export function StoreDedupPanel() {
  const qc = useQueryClient()
  const { companyId } = useCompany()
  const [tab, setTab] = useState<'groups' | 'bridge' | 'jobs'>('groups')
  const [q, setQ] = useState('')
  const [onlyLive, setOnlyLive] = useState(true)
  const [inclAssort, setInclAssort] = useState(false)
  const [priceDesync, setPriceDesync] = useState(false)
  // Разбираем контур 208 (Нефтосервер → 1С 208 → ЦБ). Мёртвые карточки и коды
  // чужих складов — не наша зона, по умолчанию скрыты.
  const [onlyScope, setOnlyScope] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const fileRef = useRef<HTMLInputElement>(null)

  // Задания опрашиваем в корне (а не во вкладке): пока станция собирает срез,
  // менеджер обычно смотрит на группы — и витрина должна обновиться сама.
  const { data: jobs = [], isLoading: jobsLoading } = useQuery({
    queryKey: ['dedup-jobs', companyId], queryFn: getDedupJobs,
    refetchInterval: (q) =>
      (q.state.data ?? []).some((j) => ['pending', 'running'].includes(j.status)) ? 5000 : 30000,
  })
  const seenRefresh = useRef<string | null | undefined>(undefined)

  const { data: sum } = useQuery({ queryKey: ['dedup-summary', companyId], queryFn: getDedupSummary })
  const { data: groups = [], isLoading } = useQuery({
    queryKey: ['dedup-groups', companyId, q, onlyLive, inclAssort, priceDesync, onlyScope, statusFilter],
    queryFn: () => getDedupGroups({ q, onlyLive, includeAssortment: inclAssort, priceDesync, onlyScope208: onlyScope, status: statusFilter === 'all' ? undefined : statusFilter }),
    enabled: tab === 'groups',
  })

  const invalidateSlice = () => {
    qc.invalidateQueries({ queryKey: ['dedup-summary'] })
    qc.invalidateQueries({ queryKey: ['dedup-groups'] })
    qc.invalidateQueries({ queryKey: ['dedup-bridge'] })
  }

  // Обновление среза — команда станции: бэкенд в сеть АЗС не ходит, поэтому
  // задание кладётся в очередь, нода 208 снимает дамп с локальной 1С и заливает.
  const refreshMut = useMutation({
    mutationFn: refreshDedup,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['dedup-jobs'] })
      toast.success(r.already ? (r.note ?? 'Срез уже собирается')
        : 'Станция 208 собирает срез — обычно около минуты. Ход виден на вкладке «Задания».')
    },
    onError: () => toast.error('Не удалось отправить команду на станцию'),
  })

  // Запасной ход: залить дамп файлом (если станция недоступна).
  const reloadMut = useMutation({
    mutationFn: (file: File) => reloadDedup(file),
    onSuccess: (r) => {
      invalidateSlice()
      toast.success(`Срез обновлён: ${r.cards} карточек, ${r.bindings} привязок, ${r.prices} цен`)
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось загрузить дамп'),
  })

  // Станция отчиталась по сбору среза — подтягиваем витрину, не дёргая менеджера.
  useEffect(() => {
    const newest = jobs.find((j) => j.kind === 'refresh' && j.status === 'done')?.id ?? null
    if (seenRefresh.current === undefined) { seenRefresh.current = newest; return }
    if (newest && newest !== seenRefresh.current) {
      seenRefresh.current = newest
      invalidateSlice()
      toast.success('Станция прислала свежий срез')
    }
  }, [jobs]) // eslint-disable-line react-hooks/exhaustive-deps

  const refreshing = jobs.some((j) => j.kind === 'refresh' && ['pending', 'running'].includes(j.status))

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

  // Карта слияния — вход для .epf ЗаменитьСсылки (запуск руками в тихое окно).
  const exportMergeMap = async () => {
    try {
      const rows = await getDedupMergeMap()
      const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `merge_map_208_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      toast.success(`Карта слияния: ${rows.length} пар дубль→канон для .epf`)
    } catch { toast.error('Не удалось выгрузить карту слияния') }
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
            Префикс кода — нумерация карточки, не станция: «008…» тоже бьётся кассой 208. Разрез даёт склад привязки, поэтому по умолчанию показан только контур 208.
          </p>
          {sum?.updatedAt && (
            <p className="mt-0.5 text-[11px] text-muted-foreground/70">Срез 208 обновлён: {new Date(sum.updatedAt).toLocaleString('ru-RU')}</p>
          )}
        </div>
      </div>

      {/* KPI */}
      {sum && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-4 xl:grid-cols-8">
          <Kpi label="Карточек 208" value={fmt(sum.cardsTotal)} hint={`008:${fmt(sum.byPrefix['008'])} · 208:${fmt(sum.byPrefix['208'])} · ЦБ:${fmt(sum.byPrefix['ЦБ'])}`} />
          <Kpi label="Групп в контуре 208" value={fmt(sum.scopedGroups)} hint={`из ${fmt(sum.dupGroups)} · вне контура ${fmt(sum.outOfScopeGroups)}`} />
          <Kpi label="Рассинхрон цен" value={fmt(sum.priceDesyncGroups)} hint="разные цены, касса 208 бьёт" warn={(sum.priceDesyncGroups ?? 0) > 0} />
          <Kpi label="В ассортименте" value={fmt(sum.assortmentCards)} hint="не дубли (исключены)" />
          <Kpi label="Привязок кассы" value={fmt(sum.nsActive)} hint="активных кодов НС" />
          <Kpi label="Нет в ЦБ" value={fmt(sum.cbMissing)} warn={(sum.cbMissing ?? 0) > 0}
            hint={sum.cbCodeDiff ? `код разошёлся: ${fmt(sum.cbCodeDiff)}` : 'заведены локально'} />
          <Kpi label="Касса → удалён." value={fmt(sum.nsOnMarked)} hint="бьёт помеченную" warn={(sum.nsOnMarked ?? 0) > 0} />
          <Kpi label="Карт. ≥2 кодов" value={fmt(sum.multiCodeCards)} hint="несколько кодов кассы" />
        </div>
      )}

      {/* Вкладки */}
      <div className="flex items-center gap-1.5 border-b border-border/40">
        <button onClick={() => setTab('groups')} className={cn('flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm', tab === 'groups' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground')}><Tag className="size-4" />Группы дублей</button>
        <button onClick={() => setTab('bridge')} className={cn('flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm', tab === 'bridge' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground')}><Store className="size-4" />Мост касса↔карточка</button>
        <button onClick={() => setTab('jobs')} className={cn('flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm', tab === 'jobs' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground')}><PlayCircle className="size-4" />Задания</button>
        <div className="flex-1" />
        <input ref={fileRef} type="file" accept=".txt" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) reloadMut.mutate(f); if (fileRef.current) fileRef.current.value = '' }} />
        <Button size="sm" variant="outline" className="h-8 text-xs"
          onClick={() => refreshMut.mutate()} disabled={refreshMut.isPending || refreshing}
          title="Станция 208 снимет свежий срез с локальной 1С и зальёт сюда (≈1 мин). Ночью то же самое идёт по расписанию.">
          {refreshMut.isPending || refreshing ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <RefreshCw className="mr-1 size-3.5" />}
          {refreshing ? 'Станция собирает…' : 'Обновить срез'}
        </Button>
        <Button size="sm" variant="ghost" className="h-8 px-2 text-xs text-muted-foreground"
          onClick={() => fileRef.current?.click()} disabled={reloadMut.isPending}
          title="Запасной ход: залить дамп файлом, если станция недоступна">
          {reloadMut.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
        </Button>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={exportMergeMap}
          title="Карта дубль→канон для .epf (ЗаменитьСсылки) — запускать в тихое окно, касса активна"><GitMerge className="mr-1 size-3.5" />Карта слияния</Button>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={exportExcel}><FileSpreadsheet className="mr-1 size-3.5" />Excel</Button>
        <Button size="sm" variant="outline" className="h-8 text-xs" onClick={exportPlan}><Download className="mr-1 size-3.5" />JSON</Button>
      </div>

      {tab === 'jobs' ? <JobsTab jobs={jobs} isLoading={jobsLoading} /> : tab === 'groups' ? (
        <div className="space-y-2.5">
          {sum && <PrefixLegend byPrefix={sum.byPrefix} />}
          {/* Фильтры */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[180px] flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск по названию…" className="h-8 pl-8 text-xs" />
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"
              title="Оставить группы, через которые касса 208 реально работает: активный код склада 208 или продажи. Префикс кода (008/208/ЦБ) на это не влияет.">
              <input type="checkbox" checked={onlyScope} onChange={(e) => setOnlyScope(e.target.checked)} />только контур 208</label>
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
            <span className="ml-auto text-xs text-muted-foreground">
              {groups.length} групп · разобрано {doneCount}
              {(sum?.notUsedGroups ?? 0) > 0 && <> · <span className="text-slate-300/80">в архиве {fmt(sum?.notUsedGroups)}</span></>}
            </span>
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
