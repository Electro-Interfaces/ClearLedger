/**
 * CatalogPage — справочник-БИБЛИОТЕКА входного контура TradeLedger: какие
 * типы источников, шаблоны каналов и правила разрезов сверки вообще бывают.
 * Это обзор + точка входа в настройку; СОСТОЯНИЕ ПОДКЛЮЧЕНИЯ к компании здесь
 * НЕ показывается — оно живёт в «Источниках данных» и «Каналах».
 *
 * Группировка: Источники/Каналы — по категории, Разрезы — по модулю.
 * Кнопка строки = вход в настройку (источник → добавить, канал → мастер).
 */
import { useState, type ReactNode } from 'react'
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Database, Radio, GitCompare, ChevronDown, Plug, Plus } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import {
  getChannelTemplates,
  getReconcileRules,
  getSourceTypes,
  type ChannelTemplateItem,
  type ReconcileRuleItem,
  type SourceTypeItem,
} from '@/services/catalogService'

// ── Продуктовая доступность типа (не про компанию) ──────────────────
const STATUS: Record<string, { label: string; dot: string; text: string }> = {
  available: { label: 'доступен', dot: 'bg-emerald-400', text: 'text-emerald-300/80' },
  imperative: { label: 'обязательный', dot: 'bg-emerald-400', text: 'text-emerald-300/80' },
  partial: { label: 'частично', dot: 'bg-amber-400', text: 'text-amber-300/80' },
  planned: { label: 'план', dot: 'bg-zinc-500', text: 'text-zinc-400' },
}
function statusMeta(s: string) {
  return STATUS[s] ?? { label: s, dot: 'bg-zinc-500', text: 'text-zinc-400' }
}

// Модули разрезов сверки → читаемые ярлыки
const MODULE_LABEL: Record<string, string> = {
  fuel: 'Нефтепродукты',
  sidegoods: 'Сопутка',
  food: 'Общепит',
}
function moduleLabel(m: string) {
  return m
    .split(',')
    .map((x) => MODULE_LABEL[x.trim()] ?? x.trim())
    .join(' · ')
}

// ── Нормализованная строка справочника ──────────────────────────────
type RowAction = { label: string; kind: 'connect' | 'create'; onClick: () => void }

interface CatalogRow {
  code: string
  label: string
  status: string
  description: string
  group: string
  meta?: string
  chips: string[]
  action?: RowAction
}

function groupRows(rows: CatalogRow[]): [string, CatalogRow[]][] {
  const map = new Map<string, CatalogRow[]>()
  for (const r of rows) {
    const arr = map.get(r.group)
    if (arr) arr.push(r)
    else map.set(r.group, [r])
  }
  return [...map.entries()]
}

// ── Строка списка ───────────────────────────────────────────────────
function Row({ row }: { row: CatalogRow }) {
  const st = statusMeta(row.status)
  return (
    <div className="flex items-start gap-3 rounded-md px-3 py-2 transition-colors hover:bg-accent/40">
      <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', st.dot)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-sm font-medium">{row.label}</span>
          <code className="shrink-0 text-xs text-muted-foreground/70">{row.code}</code>
          <span className={cn('ml-auto shrink-0 text-xs', st.text)}>{st.label}</span>
        </div>
        {row.description && (
          <p className="mt-0.5 text-sm text-muted-foreground">{row.description}</p>
        )}
        {(row.meta || row.chips.length > 0) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {row.meta && <span className="text-xs text-muted-foreground/60">{row.meta}</span>}
            {row.chips.map((c, i) => (
              <Badge
                key={i}
                variant="outline"
                className="border-zinc-600/60 font-normal text-zinc-400"
              >
                {c}
              </Badge>
            ))}
          </div>
        )}
      </div>
      {row.action && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 shrink-0 gap-1 self-center text-xs"
          onClick={row.action.onClick}
        >
          {row.action.kind === 'connect' ? <Plug className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
          {row.action.label}
        </Button>
      )}
    </div>
  )
}

// ── Сворачиваемая группа (по умолчанию свёрнута) ────────────────────
function Group({ title, rows }: { title: string; rows: CatalogRow[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60 transition-colors hover:text-muted-foreground"
      >
        <ChevronDown
          className={cn('h-3 w-3 shrink-0 transition-transform', open ? '' : '-rotate-90')}
        />
        <span>{title}</span>
        <span className="text-muted-foreground/40">{rows.length}</span>
      </button>
      {open && (
        <div className="divide-y divide-border/30">
          {rows.map((row) => (
            <Row key={row.code} row={row} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Раздел (один справочник) ────────────────────────────────────────
function Section<T>({
  title,
  icon,
  query,
  toRows,
}: {
  title: string
  icon: ReactNode
  query: UseQueryResult<T[]>
  toRows: (items: T[]) => CatalogRow[]
}) {
  const rows = query.data ? toRows(query.data) : []
  const groups = groupRows(rows)

  return (
    <section className="space-y-1">
      <div className="flex items-center gap-2 border-b border-border/60 pb-2">
        <span className="text-muted-foreground">{icon}</span>
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {!query.isLoading && (
          <Badge variant="secondary" className="font-normal">
            {rows.length}
          </Badge>
        )}
      </div>

      {query.isLoading ? (
        <div className="space-y-2 pt-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-md" />
          ))}
        </div>
      ) : query.isError ? (
        <p className="px-3 py-4 text-sm text-destructive">Не удалось загрузить справочник.</p>
      ) : (
        <div className="pt-1">
          {groups.map(([group, groupRowsList]) => (
            <Group key={group} title={group} rows={groupRowsList} />
          ))}
        </div>
      )}
    </section>
  )
}

export function CatalogPage() {
  const navigate = useNavigate()

  const sources = useQuery({ queryKey: ['catalog', 'source-types'], queryFn: getSourceTypes })
  const channels = useQuery({ queryKey: ['catalog', 'channel-templates'], queryFn: getChannelTemplates })
  const rules = useQuery({ queryKey: ['catalog', 'reconcile-rules'], queryFn: getReconcileRules })

  const sourceRows = (items: SourceTypeItem[]): CatalogRow[] =>
    items.map((s) => ({
      code: s.source_type,
      label: s.label,
      status: s.status,
      description: s.description,
      group: s.category,
      chips: s.available_doc_types.map((d) => d.name),
      action: {
        label: 'Подключить',
        kind: 'connect',
        onClick: () =>
          navigate(
            `/sources?add=1&type=${s.source_type}&name=${encodeURIComponent(s.label)}`,
          ),
      },
    }))

  const channelRows = (items: ChannelTemplateItem[]): CatalogRow[] =>
    items.map((c) => ({
      code: c.id,
      label: c.label,
      status: c.status,
      description: c.description,
      group: c.category,
      meta: `${c.streams.length} потоков · ${c.stages.length} стадий`,
      chips: c.reconcile_rules,
      action: { label: 'Создать канал', kind: 'create', onClick: () => navigate('/channels?wizard=1') },
    }))

  const ruleRows = (items: ReconcileRuleItem[]): CatalogRow[] =>
    items.map((r) => ({
      code: r.id,
      label: r.label,
      status: r.status,
      description: r.description,
      group: moduleLabel(r.module),
      meta: r.key.length ? `ключ: ${r.key.join(' · ')}` : undefined,
      chips: r.streams.map((st) => `${st.role}: ${st.source_type}`),
    }))

  return (
    <div className="space-y-8 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Каталоги входного контура</h1>
        <p className="text-sm text-muted-foreground">
          Библиотека источников, каналов и разрезов сверки — что вообще можно подключить.
          Реальные подключения компании — в разделах «Источники данных» и «Каналы».
        </p>
      </div>

      <Section
        title="Источники"
        icon={<Database className="h-5 w-5" />}
        query={sources}
        toRows={sourceRows}
      />
      <Section
        title="Каналы"
        icon={<Radio className="h-5 w-5" />}
        query={channels}
        toRows={channelRows}
      />
      <Section
        title="Разрезы сверки"
        icon={<GitCompare className="h-5 w-5" />}
        query={rules}
        toRows={ruleRows}
      />
    </div>
  )
}
