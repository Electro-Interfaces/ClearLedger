import { useState, useMemo, memo } from 'react'
import { Link } from 'react-router-dom'
import { useAllBundleTrees } from '@/hooks/useBundle'
import { useAuditorVerify } from '@/hooks/useEntries'
import { resolveRole, BUNDLE_ROLE_LABELS } from '@/services/bundleService'
import { StatusBadge } from './StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  ChevronRight, ChevronDown, ShieldCheck,
  Building2, ScrollText, FileText,
} from 'lucide-react'
import { formatDate } from '@/lib/formatDate'
import type { DataEntry, BundleNode, BundleTree, BundleRole } from '@/types'

// ---- Статус аудитора ----

const AUDITOR_STATUS_MAP: Record<string, { label: string; className: string }> = {
  approved: { label: 'OK', className: 'border-muted-foreground/40 text-muted-foreground' },
  needs_review: { label: 'Проверить', className: 'border-muted-foreground/40 text-muted-foreground' },
  rejected: { label: 'Отклонён', className: 'border-destructive/50 text-destructive/80' },
}

// ---- Форматирование суммы ----

const numberFormatter = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function parseAmount(value: string | undefined): number {
  if (!value) return 0
  const num = parseFloat(value)
  return isNaN(num) ? 0 : num
}

function formatAmount(value: string | undefined): string {
  if (!value) return ''
  const num = parseFloat(value)
  if (isNaN(num)) return ''
  return numberFormatter.format(num) + ' ₽'
}

// ---- Группировка: Контрагент → Договор → Документы ----

const NO_COUNTERPARTY = '__no_counterparty__'

interface CounterpartyGroup {
  name: string
  trees: BundleTree[]
  orphans: DataEntry[]
  totalCount: number
  totalAmount: number
}

function sumTreeAmount(node: BundleNode): number {
  const own = parseAmount(node.entry.metadata.amount)
  return own + node.children.reduce((s, c) => s + sumTreeAmount(c), 0)
}

function buildCounterpartyGroups(
  trees: BundleTree[],
  orphans: DataEntry[],
): CounterpartyGroup[] {
  const map = new Map<string, { trees: BundleTree[]; orphans: DataEntry[] }>()

  function getOrCreate(key: string) {
    let g = map.get(key)
    if (!g) { g = { trees: [], orphans: [] }; map.set(key, g) }
    return g
  }

  // Комплекты → по контрагенту корня
  for (const tree of trees) {
    const cp = tree.root.entry.metadata.counterparty || NO_COUNTERPARTY
    getOrCreate(cp).trees.push(tree)
  }

  // Орфаны → по контрагенту
  for (const entry of orphans) {
    const cp = entry.metadata.counterparty || NO_COUNTERPARTY
    getOrCreate(cp).orphans.push(entry)
  }

  const groups: CounterpartyGroup[] = []
  for (const [cp, data] of map) {
    const treeAmount = data.trees.reduce((s, t) => s + sumTreeAmount(t.root), 0)
    const orphanAmount = data.orphans.reduce((s, e) => s + parseAmount(e.metadata.amount), 0)
    const treeCount = data.trees.reduce((s, t) => s + t.totalCount, 0)

    groups.push({
      name: cp === NO_COUNTERPARTY ? 'Без контрагента' : cp,
      trees: data.trees,
      orphans: data.orphans,
      totalCount: treeCount + data.orphans.length,
      totalAmount: treeAmount + orphanAmount,
    })
  }

  // Именованные контрагенты — по алфавиту, «Без контрагента» — в конец
  groups.sort((a, b) => {
    if (a.name === 'Без контрагента') return 1
    if (b.name === 'Без контрагента') return -1
    return a.name.localeCompare(b.name, 'ru')
  })

  return groups
}

// ---- DocumentTreeView ----

interface DocumentTreeViewProps {
  entries: DataEntry[]
  onRowClick: (id: string) => void
}

export function DocumentTreeView({ entries, onRowClick }: DocumentTreeViewProps) {
  const { data, isLoading } = useAllBundleTrees(entries)
  const auditorVerify = useAuditorVerify()

  const groups = useMemo(() => {
    if (!data) return []
    return buildCounterpartyGroups(data.trees, data.orphans)
  }, [data])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Загрузка иерархии...
      </div>
    )
  }

  if (!data || groups.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Нет данных для отображения
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <CounterpartyBlock
          key={group.name}
          group={group}
          onRowClick={onRowClick}
          onAuditorVerify={(id) => auditorVerify.mutate(id)}
        />
      ))}
    </div>
  )
}

// ---- Виртуальная группировка орфанов под договоры ----

interface VirtualContractGroup {
  contract: DataEntry
  documents: DataEntry[]
  totalAmount: number
}

function getDocTime(entry: DataEntry): number {
  return new Date(entry.metadata.docDate || entry.createdAt).getTime()
}

/** Группирует орфанов: договоры → заголовки, остальные → под ближайший по дате договор */
function virtualGroupByContracts(entries: DataEntry[]): {
  contractGroups: VirtualContractGroup[]
  loose: DataEntry[]
} {
  const contracts = entries.filter((e) => resolveRole(e.docTypeId) === 'contract')
  const others = entries.filter((e) => resolveRole(e.docTypeId) !== 'contract')

  if (contracts.length === 0) {
    return { contractGroups: [], loose: entries }
  }

  // Сортируем договоры по дате
  contracts.sort((a, b) => getDocTime(a) - getDocTime(b))

  // Создаём группы
  const groups = new Map<string, DataEntry[]>()
  for (const c of contracts) groups.set(c.id, [])

  // Назначаем каждый документ ближайшему по дате договору
  for (const doc of others) {
    const docTime = getDocTime(doc)
    let nearest = contracts[0]
    let minDiff = Infinity
    for (const c of contracts) {
      const diff = Math.abs(docTime - getDocTime(c))
      if (diff < minDiff) { minDiff = diff; nearest = c }
    }
    groups.get(nearest.id)!.push(doc)
  }

  const contractGroups: VirtualContractGroup[] = contracts.map((c) => {
    const docs = groups.get(c.id) ?? []
    return {
      contract: c,
      documents: docs,
      totalAmount: parseAmount(c.metadata.amount) + docs.reduce((s, d) => s + parseAmount(d.metadata.amount), 0),
    }
  })

  return { contractGroups, loose: [] }
}

// ---- CounterpartyBlock (уровень 1: Контрагент) ----

function CounterpartyBlock({
  group,
  onRowClick,
  onAuditorVerify,
}: {
  group: CounterpartyGroup
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)

  // Виртуальная группировка орфанов под договоры
  const { contractGroups, loose } = useMemo(
    () => virtualGroupByContracts(group.orphans),
    [group.orphans],
  )

  return (
    <div className="border border-border/60 rounded-lg overflow-hidden">
      {/* Заголовок контрагента */}
      <button
        type="button"
        className="flex items-center gap-2.5 px-4 py-2.5 bg-muted/20 border-b border-border/60 w-full text-left hover:bg-muted/40 transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="size-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="size-4 text-muted-foreground shrink-0" />
        )}
        <Building2 className="size-4 text-muted-foreground shrink-0" />
        <span className="text-sm font-semibold flex-1 truncate">{group.name}</span>
        {group.totalAmount > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums shrink-0">
            {numberFormatter.format(group.totalAmount)} ₽
          </span>
        )}
        <Badge variant="secondary" className="text-xs shrink-0">{group.totalCount} док.</Badge>
      </button>

      {/* Содержимое */}
      {!collapsed && (
        <div className="py-1">
          {/* Реальные комплекты (из bundleService) */}
          {group.trees.map((tree) => (
            <ContractBlock
              key={tree.root.entry.id}
              tree={tree}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}

          {/* Виртуальные группы: договор-орфан + его документы */}
          {contractGroups.map((cg) => (
            <VirtualContractBlock
              key={cg.contract.id}
              group={cg}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}

          {/* Документы без какого-либо договора */}
          {loose.length > 0 && (
            <LooseDocsSection
              entries={loose}
              hasContracts={group.trees.length > 0 || contractGroups.length > 0}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          )}
        </div>
      )}
    </div>
  )
}

// ---- ContractBlock (уровень 2: Договор/Комплект) ----

function ContractBlock({
  tree,
  onRowClick,
  onAuditorVerify,
}: {
  tree: BundleTree
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const rootRole = resolveRole(tree.root.entry.docTypeId)
  const rootRoleLabel = BUNDLE_ROLE_LABELS[rootRole] ?? BUNDLE_ROLE_LABELS.other
  const totalAmount = sumTreeAmount(tree.root)

  return (
    <div className="ml-4 mr-1">
      {/* Заголовок договора/комплекта */}
      <button
        type="button"
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-muted/40 transition-colors rounded border-l-2 border-l-border"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
        )}
        <ScrollText className="size-4 shrink-0 text-muted-foreground" />
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 text-muted-foreground">
          {rootRoleLabel}
        </Badge>
        <span className="text-sm font-medium truncate flex-1">{tree.root.entry.title}</span>
        {tree.root.entry.metadata.docDate && (
          <span className="text-xs text-muted-foreground shrink-0">
            {formatDate(tree.root.entry.metadata.docDate)}
          </span>
        )}
        {totalAmount > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums shrink-0">
            {numberFormatter.format(totalAmount)} ₽
          </span>
        )}
        <Badge variant="secondary" className="text-xs shrink-0">{tree.totalCount}</Badge>
      </button>

      {/* Дочерние документы (пропускаем корень — он уже в заголовке) */}
      {!collapsed && tree.root.children.length > 0 && (
        <div className="ml-4">
          {tree.root.children.map((child) => (
            <TreeNode
              key={child.entry.id}
              node={child}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---- VirtualContractBlock (уровень 2: виртуальная группировка орфанов под договор) ----

function VirtualContractBlock({
  group,
  onRowClick,
  onAuditorVerify,
}: {
  group: VirtualContractGroup
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const c = group.contract
  const docCount = group.documents.length + 1 // +1 за сам договор

  return (
    <div className="ml-4 mr-1">
      {/* Заголовок договора */}
      <button
        type="button"
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-muted/40 transition-colors rounded border-l-2 border-l-border"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
        )}
        <ScrollText className="size-4 shrink-0 text-muted-foreground" />
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 text-muted-foreground">
          Договор
        </Badge>
        <span className="text-sm font-medium truncate flex-1">{c.title}</span>
        {c.metadata.docDate && (
          <span className="text-xs text-muted-foreground shrink-0">
            {formatDate(c.metadata.docDate)}
          </span>
        )}
        {group.totalAmount > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums shrink-0">
            {numberFormatter.format(group.totalAmount)} ₽
          </span>
        )}
        <StatusBadge status={c.status} />
        <Badge variant="secondary" className="text-xs shrink-0">{docCount}</Badge>
      </button>

      {/* Подчинённые документы */}
      {!collapsed && group.documents.length > 0 && (
        <div className="ml-6">
          {group.documents.map((entry, idx) => (
            <DocRow
              key={entry.id}
              entry={entry}
              depth={0}
              even={idx % 2 === 0}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---- LooseDocsSection (уровень 2: документы без договора) ----

function LooseDocsSection({
  entries,
  hasContracts,
  onRowClick,
  onAuditorVerify,
}: {
  entries: DataEntry[]
  hasContracts: boolean
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)

  // Если нет ни одного договора — показываем плоский список
  if (!hasContracts) {
    return (
      <div className="ml-4 mr-1">
        {entries.map((entry, idx) => (
          <DocRow
            key={entry.id}
            entry={entry}
            depth={0}
            even={idx % 2 === 0}
            onRowClick={onRowClick}
            onAuditorVerify={onAuditorVerify}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="ml-4 mr-1">
      <button
        type="button"
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-muted/40 transition-colors rounded border-l-2 border-l-border"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
        )}
        <FileText className="size-4 text-muted-foreground shrink-0" />
        <span className="text-sm font-medium text-muted-foreground flex-1">Без договора</span>
        <Badge variant="secondary" className="text-xs shrink-0">{entries.length}</Badge>
      </button>

      {!collapsed && (
        <div className="ml-6">
          {entries.map((entry, idx) => (
            <DocRow
              key={entry.id}
              entry={entry}
              depth={0}
              even={idx % 2 === 0}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---- TreeNode (рекурсивный, для дерева комплекта) ----

const TreeNode = memo(function TreeNode({
  node,
  onRowClick,
  onAuditorVerify,
}: {
  node: BundleNode
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const hasChildren = node.children.length > 0
  const role = (node.entry.metadata._bundleRole || resolveRole(node.entry.docTypeId)) as BundleRole
  const roleLabel = BUNDLE_ROLE_LABELS[role] ?? BUNDLE_ROLE_LABELS.other

  const vs = node.entry.metadata._verificationStatus
  const auditorCfg = vs ? AUDITOR_STATUS_MAP[vs] : null

  return (
    <div>
      <div
        className="flex items-center gap-2 pr-3 py-2 group hover:bg-muted/40 transition-colors border-l-2 border-l-border/60"
        style={{ paddingLeft: `${node.depth * 20 + 8}px` }}
      >
        {/* Expand/collapse */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="size-5 shrink-0 flex items-center justify-center text-muted-foreground hover:text-foreground rounded hover:bg-muted"
          >
            {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}

        <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 text-muted-foreground">{roleLabel}</Badge>

        <Link
          to={`/data/${node.entry.categoryId}/${node.entry.id}`}
          className="text-sm font-medium truncate flex-1 hover:underline"
          onClick={(e) => { e.preventDefault(); onRowClick(node.entry.id) }}
        >
          {node.entry.title}
        </Link>

        {node.entry.metadata.docDate && (
          <span className="text-xs text-muted-foreground shrink-0">
            {formatDate(node.entry.metadata.docDate)}
          </span>
        )}

        {node.entry.metadata.amount && (
          <span className="text-xs font-medium tabular-nums shrink-0">
            {formatAmount(node.entry.metadata.amount)}
          </span>
        )}

        {auditorCfg && (
          <Badge variant="outline" className={`text-[10px] px-1.5 py-0 shrink-0 ${auditorCfg.className}`}>
            {auditorCfg.label}
          </Badge>
        )}

        <StatusBadge status={node.entry.status} />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground hover:bg-muted"
              onClick={(e) => { e.stopPropagation(); onAuditorVerify(node.entry.id) }}
            >
              <ShieldCheck className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">Проверить аудитором</TooltipContent>
        </Tooltip>
      </div>

      {!collapsed && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.entry.id}
              node={child}
              onRowClick={onRowClick}
              onAuditorVerify={onAuditorVerify}
            />
          ))}
        </div>
      )}
    </div>
  )
})

// ---- DocRow (документ-лист без детей) ----

function DocRow({
  entry,
  depth,
  even,
  onRowClick,
  onAuditorVerify,
}: {
  entry: DataEntry
  depth: number
  even: boolean
  onRowClick: (id: string) => void
  onAuditorVerify: (id: string) => void
}) {
  const role = resolveRole(entry.docTypeId)
  const roleLabel = BUNDLE_ROLE_LABELS[role] ?? BUNDLE_ROLE_LABELS.other
  const vs = entry.metadata._verificationStatus
  const auditorCfg = vs ? AUDITOR_STATUS_MAP[vs] : null

  return (
    <div
      className={`flex items-center gap-2 pr-3 py-2 group hover:bg-muted/40 transition-colors border-l-2 border-l-border/40 ${even ? '' : 'bg-muted/5'}`}
      style={{ paddingLeft: `${depth * 20 + 8}px` }}
    >
      <span className="size-5 shrink-0" />

      {entry.metadata.docNumber && (
        <span className="text-xs text-muted-foreground font-mono shrink-0 w-14 text-right">
          №{entry.metadata.docNumber}
        </span>
      )}

      <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 text-muted-foreground">{roleLabel}</Badge>

      <button
        type="button"
        className="text-sm font-medium text-foreground hover:underline truncate flex-1 text-left"
        onClick={() => onRowClick(entry.id)}
      >
        {entry.title}
      </button>

      {entry.metadata.docDate && (
        <span className="text-xs text-muted-foreground shrink-0">
          {formatDate(entry.metadata.docDate)}
        </span>
      )}

      {entry.metadata.amount && (
        <span className="text-xs font-medium tabular-nums shrink-0">
          {formatAmount(entry.metadata.amount)}
        </span>
      )}

      {auditorCfg && (
        <Badge variant="outline" className={`text-[10px] px-1.5 py-0 shrink-0 ${auditorCfg.className}`}>
          {auditorCfg.label}
        </Badge>
      )}

      <StatusBadge status={entry.status} />

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground hover:bg-muted"
            onClick={(e) => { e.stopPropagation(); onAuditorVerify(entry.id) }}
          >
            <ShieldCheck className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">Проверить аудитором</TooltipContent>
      </Tooltip>
    </div>
  )
}
