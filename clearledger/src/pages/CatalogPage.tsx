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
import { Database, GitCompare, ChevronDown, Plug, Plus, Boxes, Blocks, Settings2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { WORKSPACE_MODULES, PROFILE_LABEL, getWorkspaceModule, type WorkspaceModuleDef } from '@/config/workspaceModules'
import {
  MODULE_COMPONENTS, getModuleComponentDefs, type ModuleComponent,
} from '@/config/moduleComponents'
import {
  ENERGY_SOURCES, ENERGY_CHANNELS, ENERGY_CUTS,
  channelsForCut, sourcesForCut, cutsForChannel, cutsForSource, energySource,
  type EnergySource, type EnergyChannel, type EnergyCut,
} from '@/config/energyPipeline'
import {
  useModuleConnections, isModuleConnected, setModuleConnected, setModuleParams,
  isComponentEnabled, setComponentEnabled,
  type ModuleConnMap,
} from '@/services/moduleConnectionService'
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
  active: { label: 'рабочий', dot: 'bg-emerald-400', text: 'text-emerald-300/80' },
  demo: { label: 'демо', dot: 'bg-sky-400', text: 'text-sky-300/80' },
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
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const moduleConn = useModuleConnections()
  const [configMod, setConfigMod] = useState<WorkspaceModuleDef | null>(null)

  const sources = useQuery({ queryKey: ['catalog', 'source-types'], queryFn: getSourceTypes })
  const channels = useQuery({ queryKey: ['catalog', 'channel-templates'], queryFn: getChannelTemplates })
  const rules = useQuery({ queryKey: ['catalog', 'reconcile-rules'], queryFn: getReconcileRules })
  // Модули фильтруются по профилю компании: energy не видит fuel-модули (Баланс АЗС и т.п.) и наоборот;
  // 'any' — общие для всех профилей.
  const modules = useQuery({
    queryKey: ['catalog', 'workspace-modules', company.profileId],
    queryFn: async () =>
      WORKSPACE_MODULES.filter((mod) => mod.profiles.some((p) => p === 'any' || p === company.profileId)),
  })
  // Компоненты для сборки модулей (стандартные + специализированные), библиотека по профилю.
  const components = useQuery({
    queryKey: ['catalog', 'module-components', company.profileId],
    queryFn: async () =>
      MODULE_COMPONENTS.filter((c) => c.profiles.some((p) => p === 'any' || p === company.profileId)),
  })
  // Энергоцепочка (для energy-профиля) — из единой модели energyPipeline.
  const eSources = useQuery({ queryKey: ['catalog', 'energy-sources'], queryFn: async () => ENERGY_SOURCES })
  const eChannels = useQuery({ queryKey: ['catalog', 'energy-channels'], queryFn: async () => ENERGY_CHANNELS })
  const eCuts = useQuery({ queryKey: ['catalog', 'energy-cuts'], queryFn: async () => ENERGY_CUTS })

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
      action: { label: 'Создать коннектор', kind: 'create', onClick: () => navigate('/connectors?wizard=1') },
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

  const moduleRows = (items: WorkspaceModuleDef[]): CatalogRow[] =>
    items.map((m) => {
      const connected = isModuleConnected(moduleConn.conn, m, moduleConn.profileId)
      const enabledSpec = getModuleComponentDefs(m.id, moduleConn.profileId)
        .filter((c) => c.kind === 'specialized' && isComponentEnabled(moduleConn.conn, c, moduleConn.profileId))
        .map((c) => c.label)
      return {
        code: m.id,
        label: m.label,
        status: m.status,
        description: m.description,
        group: m.section,
        meta: `${m.profiles.map((p) => PROFILE_LABEL[p]).join(' · ')} · ${connected ? '✓ подключён' : 'не подключён'}`
          + (enabledSpec.length ? ` · компоненты: ${enabledSpec.join(', ')}` : ''),
        chips: m.params.map((p) => p.label),
        action: { label: connected ? 'Настроить' : 'Подключить', kind: 'connect', onClick: () => setConfigMod(m) },
      }
    })

  const componentRows = (items: ModuleComponent[]): CatalogRow[] =>
    items.map((c) => {
      const owner = getWorkspaceModule(c.moduleId)
      const enabled = isComponentEnabled(moduleConn.conn, c, moduleConn.profileId)
      return {
        code: c.id,
        label: c.label,
        status: c.status,
        description: c.description,
        group: owner?.label ?? c.moduleId,
        meta: `${c.kind === 'standard' ? 'стандартный' : 'специализированный'} · ${enabled ? '✓ в сборке' : 'не включён'}`,
        chips: c.menuItems?.map((mi) => mi.label) ?? [],
        action: owner ? { label: 'Настроить', kind: 'connect', onClick: () => setConfigMod(owner) } : undefined,
      }
    })

  const energySourceRows = (items: EnergySource[]): CatalogRow[] =>
    items.map((s) => ({
      code: s.id, label: s.label, status: s.status, description: s.streams.join(' · '),
      group: s.level === 'station' ? 'Привязка: станция' : 'Привязка: компания',
      meta: `питает: ${cutsForSource(s.id).map((c) => c.label).join(', ')}`,
      chips: cutsForSource(s.id).map((c) => c.label),
      action: { label: 'Открыть', kind: 'connect', onClick: () => navigate('/sources') },
    }))

  const energyChannelRows = (items: EnergyChannel[]): CatalogRow[] =>
    items.map((ch) => ({
      code: ch.id, label: ch.label, status: ch.status, description: ch.produces,
      group: 'Нормализация L1 → L2',
      meta: `источник: ${energySource(ch.sourceId)?.label ?? ch.sourceId}`,
      chips: cutsForChannel(ch.id).map((c) => c.label),
      action: { label: 'Открыть', kind: 'create', onClick: () => navigate('/connectors') },
    }))

  const energyCutRows = (items: EnergyCut[]): CatalogRow[] =>
    items.map((c) => ({
      code: c.id, label: c.label, status: c.status, description: c.desc,
      group: 'Разрезы учёта',
      meta: `источники: ${sourcesForCut(c.id).map((s) => s.label).join(', ')}`,
      chips: channelsForCut(c.id).map((ch) => ch.label),
      action: { label: 'Открыть', kind: 'connect', onClick: () => navigate('/reconciliation') },
    }))

  return (
    <div className="space-y-8 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Каталоги</h1>
        <p className="text-sm text-muted-foreground">
          Библиотека того, что можно подключить: модули рабочего стола, источники, каналы и разрезы сверки —
          и настроить под организацию. Реальные подключения — в «Источниках данных»/«Каналах»; параметры модуля — кнопкой «Настроить».
        </p>
      </div>

      <Section
        title="Модули"
        icon={<Boxes className="h-5 w-5" />}
        query={modules}
        toRows={moduleRows}
      />
      <Section
        title="Компоненты модулей"
        icon={<Blocks className="h-5 w-5" />}
        query={components}
        toRows={componentRows}
      />
      {isEnergy ? (
        <>
          <Section title="Подключения" icon={<Database className="h-5 w-5" />} query={eSources} toRows={energySourceRows} />
          <Section title="Коннекторы" icon={<Plug className="h-5 w-5" />} query={eChannels} toRows={energyChannelRows} />
          <Section title="Разрезы учёта" icon={<GitCompare className="h-5 w-5" />} query={eCuts} toRows={energyCutRows} />
        </>
      ) : (
        <>
          <Section title="Подключения" icon={<Database className="h-5 w-5" />} query={sources} toRows={sourceRows} />
          <Section title="Коннекторы" icon={<Plug className="h-5 w-5" />} query={channels} toRows={channelRows} />
          <Section title="Разрезы учёта" icon={<GitCompare className="h-5 w-5" />} query={rules} toRows={ruleRows} />
        </>
      )}

      <ModuleConfigDialog
        module={configMod}
        companyId={moduleConn.companyId}
        profileId={moduleConn.profileId}
        conn={moduleConn.conn}
        org={company.shortName || company.name}
        onSaved={moduleConn.refresh}
        onClose={() => setConfigMod(null)}
      />
    </div>
  )
}

// ── Настройка/подключение модуля под организацию ─────────────────────
function ModuleConfigDialog({
  module, companyId, profileId, conn, org, onSaved, onClose,
}: {
  module: WorkspaceModuleDef | null
  companyId: string
  profileId: string
  conn: ModuleConnMap
  org: string
  onSaved: () => void
  onClose: () => void
}) {
  return (
    <Dialog open={!!module} onOpenChange={(o) => { if (!o) onClose() }}>
      {module && (
        <ModuleConfigContent
          key={module.id}
          module={module}
          companyId={companyId}
          profileId={profileId}
          conn={conn}
          org={org}
          onSaved={onSaved}
          onClose={onClose}
        />
      )}
    </Dialog>
  )
}

function ModuleConfigContent({
  module, companyId, profileId, conn, org, onSaved, onClose,
}: {
  module: WorkspaceModuleDef
  companyId: string
  profileId: string
  conn: ModuleConnMap
  org: string
  onSaved: () => void
  onClose: () => void
}) {
  const [connected, setConnected] = useState(() => isModuleConnected(conn, module, profileId))
  const [params, setParams] = useState<Record<string, string>>(() => conn[module.id]?.params ?? {})
  const compDefs = getModuleComponentDefs(module.id, profileId)
  const [comps, setComps] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(compDefs.map((c) => [c.id, isComponentEnabled(conn, c, profileId)])),
  )

  const handleSave = () => {
    setModuleConnected(companyId, module.id, connected)
    setModuleParams(companyId, module.id, params)
    for (const c of compDefs) {
      if (c.kind === 'specialized') setComponentEnabled(companyId, module.id, c.id, comps[c.id] ?? false)
    }
    onSaved()
    toast.success(`Модуль «${module.label}» ${connected ? 'подключён' : 'отключён'}`, {
      description: `Сборка и параметры сохранены под «${org}»`,
    })
    onClose()
  }

  return (
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Settings2 className="h-4 w-4" /> Настройка модуля «{module.label}»
        </DialogTitle>
        <DialogDescription>
          Раздел рабочего стола: {module.section} · параметры под организацию «{org}» (применяются только к этой компании).
        </DialogDescription>
      </DialogHeader>

      <div className="flex items-center justify-between rounded-md border border-border/60 p-3">
        <div>
          <Label className="text-sm">Подключён к компании</Label>
          <p className="text-[11px] text-muted-foreground">модуль появляется в разделе «{module.section}»</p>
        </div>
        <Switch checked={connected} onCheckedChange={setConnected} />
      </div>

      <div className={`space-y-3 py-1 ${connected ? '' : 'opacity-50'}`}>
        {module.params.map((p) => (
          <div key={p.key} className="space-y-1">
            <Label className="text-xs">{p.label}</Label>
            <Input
              className="h-8 text-xs"
              value={params[p.key] ?? ''}
              onChange={(e) => setParams((s) => ({ ...s, [p.key]: e.target.value }))}
              placeholder={p.hint || `значение для «${org}»`}
            />
          </div>
        ))}
      </div>

      {compDefs.length > 0 && (
        <div className="space-y-2 border-t border-border/60 pt-3">
          <Label className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
            Компоненты модуля
          </Label>
          {compDefs.map((c) => {
            const isStd = c.kind === 'standard'
            const isPlanned = c.status === 'planned'
            return (
              <div key={c.id} className="flex items-start justify-between gap-3 rounded-md border border-border/60 p-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-sm">
                    <span>{c.label}</span>
                    <Badge variant="outline" className="font-normal text-[10px]">
                      {isStd ? 'стандартный' : 'спец.'}
                    </Badge>
                    {isPlanned && <Badge variant="outline" className="font-normal text-[10px]">план</Badge>}
                  </div>
                  <p className="text-[11px] text-muted-foreground">{c.description}</p>
                </div>
                <Switch
                  checked={isStd ? true : (comps[c.id] ?? false)}
                  disabled={isStd || isPlanned || !connected}
                  onCheckedChange={(v) => setComps((s) => ({ ...s, [c.id]: v }))}
                />
              </div>
            )
          })}
        </div>
      )}

      <DialogFooter>
        <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
        <Button size="sm" onClick={handleSave}>Сохранить</Button>
      </DialogFooter>
    </DialogContent>
  )
}
