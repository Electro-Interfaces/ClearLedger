/**
 * «Документы» в виде проводника Windows 11.
 *
 * Layout один-в-один с File Explorer: командная панель → адресная строка
 * (навигация + хлебные крошки + поиск) → [дерево навигации | таблица (Details)
 * | панель превью] → статус-бар. Данные — каталог компании (дерево из
 * `catalog`-путей загруженных документов, `useRawPanelTree`).
 */

import { useMemo, useState } from 'react'
import {
  Plus, Scissors, Copy, ClipboardPaste, PencilLine, Share2, Trash2,
  ArrowUpDown, LayoutList, MoreHorizontal, PanelRight,
  ArrowLeft, ArrowRight, ArrowUp, RotateCw, Search, ChevronRight, ChevronDown, ChevronUp,
  Folder, FolderOpen, FileText, Fuel, FileSpreadsheet, File as FileIcon, HardDrive,
  Home, Check,
} from 'lucide-react'
import { useRawPanelState } from './useRawPanelState'
import { useRawPanelTree, buildVisibleList, docTypeLabel } from './useRawPanelTree'
import { ShiftDetailModal } from '@/components/shift-reports/ShiftDetailModal'
import { DeliveryDetailModal } from '@/components/shift-reports/DeliveryDetailModal'
import { ShiftDetailsDialog } from '@/components/fuel/ShiftDetailsDialog'
import { ReceiptDetailsModal } from '@/components/fuel/ReceiptDetailsModal'
import type { FsNode } from './raw-panel-types'
import type { DocRow } from '@/services/booksService'
import { useCompany } from '@/contexts/CompanyContext'
import { BookDocDialog } from './BookDocDialog'
import { FlatDocsView } from './FlatDocsView'
import { cn } from '@/lib/utils'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 2 })

/* ── иконки файлов по типу документа ── */
function fileIcon(node: FsNode) {
  if (node.docType === 'shift') return { Icon: FileText, cls: 'text-blue-400' }
  if (node.docType === 'delivery') return { Icon: Fuel, cls: 'text-emerald-500' }
  const t = node.doc?.docType ?? ''
  if (t === 'price' || t.includes('tank') || t.includes('transaction')) return { Icon: FileSpreadsheet, cls: 'text-emerald-400' }
  return { Icon: FileIcon, cls: 'text-muted-foreground' }
}

function typeLabel(node: FsNode): string {
  if (node.type === 'folder') return 'Папка с файлами'
  return node.typeText ?? docTypeLabel(node.doc?.docType ?? '')
}

/* ── командная панель (Win11 command bar) ── */
function CmdButton({ icon: Icon, label, onClick, disabled, chevron }: {
  icon: React.ComponentType<{ className?: string }>
  label?: string
  onClick?: () => void
  disabled?: boolean
  chevron?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-1.5 h-8 rounded-md px-2 text-[13px] transition-colors',
        'text-foreground/90 hover:bg-accent disabled:opacity-40 disabled:hover:bg-transparent',
        label ? 'px-2.5' : 'w-8 justify-center',
      )}
      title={label}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label && <span>{label}</span>}
      {chevron && <ChevronDown className="h-3 w-3 opacity-60" />}
    </button>
  )
}

function Sep() { return <div className="mx-1 h-5 w-px bg-border self-center" /> }

/* ── дерево навигации (левая панель) ── */
function NavTree({
  fsTree, expandedPaths, currentKey, onToggle, onNavigate,
}: {
  fsTree: Map<string, FsNode[]>
  expandedPaths: string[]
  currentKey: string
  onToggle: (path: string) => void
  onNavigate: (path: string) => void
}) {
  const visible = useMemo(() => buildVisibleList(fsTree, expandedPaths).filter((v) => v.node.type === 'folder'), [fsTree, expandedPaths])
  return (
    <div className="py-1">
      <div className="px-3 py-1 text-[11px] font-semibold text-muted-foreground/70">Каталог компании</div>
      {visible.length === 0 && (
        <div className="px-3 py-2 text-xs text-muted-foreground/60">Пусто</div>
      )}
      {visible.map(({ node, depth }) => {
        const isOpen = expandedPaths.includes(node.path)
        const active = node.path === currentKey
        const hasChildren = (fsTree.get(node.path) ?? []).some((n) => n.type === 'folder')
        return (
          <div
            key={node.path}
            onClick={() => onNavigate(node.path)}
            className={cn(
              'group flex items-center gap-1 h-7 pr-2 cursor-pointer rounded-sm mx-1 text-[13px] transition-colors',
              active ? 'bg-primary/25 text-foreground' : 'hover:bg-sidebar-accent text-foreground/90',
            )}
            style={{ paddingLeft: depth * 14 + 6 }}
          >
            <button
              onClick={(e) => { e.stopPropagation(); onToggle(node.path) }}
              className={cn('flex h-4 w-4 items-center justify-center shrink-0', !hasChildren && 'invisible')}
            >
              <ChevronRight className={cn('h-3.5 w-3.5 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
            </button>
            {isOpen ? <FolderOpen className="h-4 w-4 text-amber-400 shrink-0" /> : <Folder className="h-4 w-4 text-amber-400 shrink-0" />}
            <span className="truncate">{node.name}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ── таблица содержимого (Details view) ── */
function DetailsList({
  items, selectedPath, onSelect, onOpen, sortConfig, onSort,
}: {
  items: FsNode[]
  selectedPath: string | null
  onSelect: (n: FsNode) => void
  onOpen: (n: FsNode) => void
  sortConfig: { column: string; direction: 'asc' | 'desc' }
  onSort: (col: 'name' | 'date' | 'status') => void
}) {
  const Head = ({ col, label, className }: { col?: 'name' | 'date' | 'status'; label: string; className?: string }) => (
    <button
      onClick={() => col && onSort(col)}
      className={cn('flex items-center gap-1 h-full px-2 text-left text-[12px] font-normal text-muted-foreground hover:bg-accent/70', className)}
    >
      {label}
      {col && sortConfig.column === col && (
        sortConfig.direction === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
      )}
    </button>
  )

  return (
    <div className="min-w-0 flex-1 flex flex-col">
      {/* заголовки колонок — на мобиле только Имя + Дата */}
      <div className="grid grid-cols-[minmax(0,1fr)_104px] md:grid-cols-[minmax(220px,1fr)_150px_180px_110px] h-9 border-b border-border shrink-0 bg-card sticky top-0 z-10">
        <Head col="name" label="Имя" />
        <Head col="date" label="Дата изменения" />
        <Head label="Тип" className="hidden md:flex" />
        <Head label="Размер" className="justify-end pr-3 hidden md:flex" />
      </div>
      {/* строки */}
      <div className="flex-1 overflow-y-auto scroll-thin">
        {items.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground/60 py-16">
            <Folder className="h-9 w-9 opacity-30" />
            <p className="text-sm">Эта папка пуста</p>
          </div>
        )}
        {items.map((n) => {
          const selected = n.path === selectedPath
          const isFolder = n.type === 'folder'
          const { Icon, cls } = isFolder ? { Icon: Folder, cls: 'text-amber-400' } : fileIcon(n)
          return (
            <div
              key={n.path}
              onClick={() => onSelect(n)}
              onDoubleClick={() => onOpen(n)}
              className={cn(
                'group grid grid-cols-[minmax(0,1fr)_104px] md:grid-cols-[minmax(220px,1fr)_150px_180px_110px] items-center h-8 text-[13px] cursor-default select-none',
                selected ? 'bg-primary/25' : 'hover:bg-accent/70',
              )}
            >
              <div className="flex items-center gap-2 min-w-0 pl-2">
                <span className={cn('flex h-4 w-4 items-center justify-center shrink-0', selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}>
                  <span className={cn('flex h-3.5 w-3.5 items-center justify-center rounded-[3px] border', selected ? 'bg-primary border-primary' : 'border-muted-foreground/50')}>
                    {selected && <Check className="h-2.5 w-2.5 text-primary-foreground" />}
                  </span>
                </span>
                <Icon className={cn('h-4 w-4 shrink-0', cls)} />
                <span className="truncate">{n.name}</span>
              </div>
              <div className="px-2 text-muted-foreground tabular-nums truncate">{n.date ?? '—'}</div>
              <div className="hidden md:block px-2 text-muted-foreground truncate">{typeLabel(n)}</div>
              <div className="hidden md:block px-3 text-right text-muted-foreground tabular-nums truncate">
                {isFolder ? (n.childCount ? `${n.childCount} эл.` : '') : (n.size && n.size !== '—' ? n.size : '')}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── панель превью (правая) ── */
function PreviewPane({ node }: { node: FsNode | null }) {
  if (!node) {
    return (
      <div className="hidden md:flex w-72 shrink-0 bg-card border-l border-border items-center justify-center text-xs text-muted-foreground/50 p-4 text-center">
        Выберите файл для предпросмотра
      </div>
    )
  }
  const { Icon, cls } = node.type === 'folder' ? { Icon: Folder, cls: 'text-amber-400' } : fileIcon(node)
  // Шапка документа учёта: у него в `data` лежит строка реестра бухгалтерии.
  const book = node.typeText ? (node.doc?.data as DocRow | undefined) : undefined
  return (
    <div className="hidden md:flex w-72 shrink-0 bg-card border-l border-border flex-col p-4 gap-3 overflow-y-auto scroll-thin">
      <div className="flex flex-col items-center gap-2 py-4">
        <Icon className={cn('h-16 w-16', cls)} />
        <div className="text-sm font-medium text-center break-words">{node.name}</div>
        <div className="text-xs text-muted-foreground">{typeLabel(node)}</div>
      </div>
      <div className="space-y-1.5 text-xs">
        <Row k="Дата изменения" v={node.date ?? '—'} />
        {node.status && <Row k="Статус" v={node.status} />}
        {book && <>
          <Row k="Номер" v={book.number || 'б/н'} />
          <Row k="Контрагент" v={book.counterparty || '—'} />
          <Row k="Сумма" v={money.format(book.amount)} />
          {book.vat > 0 && <Row k="в т.ч. НДС" v={money.format(book.vat)} />}
          {book.operation && <Row k="Назначение" v={book.operation} />}
          <Row k="Строк в составе" v={book.lines ? String(book.lines) : 'только шапка'} />
        </>}
        {node.doc?.channelId && <Row k="Канал" v={node.doc.channelId} />}
        {node.stationId != null && !book && <Row k="Станция" v={String(node.stationId)} />}
        <Row k="Путь" v={'/' + node.path.replace(/\/#[^/]+$/, '')} />
      </div>
    </div>
  )
}
function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground shrink-0">{k}</span>
      <span className="text-right break-all">{v}</span>
    </div>
  )
}

/* ── главный компонент ── */
export function ExplorerView() {
  const state = useRawPanelState()
  const tree = useRawPanelTree(state.filters, state.sortConfig)
  const [previewOpen, setPreviewOpen] = useState(true)
  const { companyId } = useCompany()
  // Просмотрщик документа учёта: у смен и ТТН свои модалки, у первички из
  // бухгалтерии не было никакой — документ открывался только в самой 1С.
  const [viewingDocId, setViewingDocId] = useState<string | null>(null)
  // Список вместо дерева осмыслен там, где у файлов есть строка реестра: колонки
  // отбора берутся из неё. У смен и прогонов каналов её нет — там только дерево.
  const listable = tree.flatFiles.some((n) => !!n.typeText)
  const asList = listable && state.viewMode === 'list'

  const currentKey = state.currentPath.join('/')
  const rawItems = tree.fsTree.get(currentKey) ?? []

  // Сортировка: папки сверху, затем файлы; внутри — по sortConfig.
  const items = useMemo(() => {
    const dir = state.sortConfig.direction === 'asc' ? 1 : -1
    const cmp = (a: FsNode, b: FsNode) => {
      if (state.sortConfig.column === 'date') {
        const da = a.doc?.date || a.doc?.loadedAt || ''
        const db = b.doc?.date || b.doc?.loadedAt || ''
        return dir * da.localeCompare(db)
      }
      return dir * a.name.localeCompare(b.name, 'ru')
    }
    const folders = rawItems.filter((n) => n.type === 'folder').sort((a, b) => dir * a.name.localeCompare(b.name, 'ru'))
    const files = rawItems.filter((n) => n.type === 'file').sort(cmp)
    return [...folders, ...files]
  }, [rawItems, state.sortConfig])

  const selected = state.selectedNode
  const selectedFolders = items.filter((n) => n.type === 'folder').length
  const selectedFiles = items.filter((n) => n.type === 'file').length

  function openNode(n: FsNode) {
    if (n.type === 'folder') {
      state.navigateTo(n.path.split('/'))
      state.setSelectedNode(null)
      return
    }
    // Документ учёта открывается своим просмотрщиком: шапка, состав, оплата, проводки.
    if (n.typeText && n.doc?.id) {
      state.setSelectedNode(n)
      setViewingDocId(n.doc.id)
      return
    }
    state.openFile(n)
  }

  const canBack = state.currentPath.length > 0

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      {/* Адресная строка */}
      <div className="flex items-center gap-1 h-11 px-2 bg-card border-b border-border shrink-0">
        <button onClick={() => canBack && state.goUp()} disabled={!canBack}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent disabled:opacity-30" title="Назад">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <button disabled className="flex h-8 w-8 items-center justify-center rounded-md disabled:opacity-30" title="Вперёд">
          <ArrowRight className="h-4 w-4" />
        </button>
        <button onClick={() => canBack && state.goUp()} disabled={!canBack}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent disabled:opacity-30" title="Вверх">
          <ArrowUp className="h-4 w-4" />
        </button>
        <button onClick={tree.handleRefresh}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent" title="Обновить">
          <RotateCw className="h-4 w-4" />
        </button>

        {/* Хлебные крошки */}
        <div className="flex items-center gap-0.5 flex-1 min-w-0 h-8 ml-1 px-2 rounded-md bg-background/70 border border-border overflow-x-auto scrollbar-hide">
          <button onClick={() => state.navigateTo([])}
            className="flex items-center gap-1.5 px-1.5 h-6 rounded hover:bg-accent text-[13px] shrink-0">
            <Home className="h-3.5 w-3.5 text-muted-foreground" />
            Документы
          </button>
          {state.currentPath.map((seg, i) => (
            <span key={i} className="flex items-center shrink-0">
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" />
              <button onClick={() => state.navigateTo(state.currentPath.slice(0, i + 1))}
                className="px-1.5 h-6 rounded hover:bg-accent text-[13px] whitespace-nowrap">
                {seg}
              </button>
            </span>
          ))}
        </div>

        {/* Поиск — на мобиле уже, чтобы не выдавливать крошки */}
        <div className="flex items-center gap-1.5 h-8 w-36 md:w-64 shrink-0 px-2.5 rounded-md bg-background/70 border border-border">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input
            value={state.filters.searchQuery}
            onChange={(e) => state.updateFilter('searchQuery', e.target.value)}
            placeholder={`Поиск${state.currentPath.length ? ' в: ' + state.currentPath[state.currentPath.length - 1] : ''}`}
            className="bg-transparent outline-none text-[13px] w-full placeholder:text-muted-foreground/60"
          />
        </div>
      </div>

      {/* Командная панель — свайп на мобиле без видимого скроллбара */}
      <div className="flex items-center gap-0.5 h-10 px-2 bg-card/60 border-b border-border shrink-0 overflow-x-auto scrollbar-hide">
        <CmdButton icon={Plus} label="Создать" chevron disabled />
        <Sep />
        <CmdButton icon={Scissors} disabled />
        <CmdButton icon={Copy} disabled />
        <CmdButton icon={ClipboardPaste} disabled />
        <CmdButton icon={PencilLine} disabled />
        <CmdButton icon={Share2} disabled />
        <CmdButton icon={Trash2} disabled />
        <Sep />
        <CmdButton icon={ArrowUpDown} label="Сортировать" chevron
          onClick={() => state.toggleSort(state.sortConfig.column === 'name' ? 'date' : 'name')} />
        <CmdButton icon={LayoutList} label={asList ? 'Папками' : 'Списком'}
          disabled={!listable}
          onClick={() => state.setViewMode(asList ? 'tree' : 'list')} />
        <CmdButton icon={MoreHorizontal} />
        <div className="ml-auto" />
        <CmdButton icon={PanelRight} label="Просмотр" onClick={() => setPreviewOpen((v) => !v)} />
      </div>

      {/* Тело: дерево | таблица | превью. Дерево на мобиле скрыто —
          навигация по папкам через крошки и открытие папок в списке. */}
      <div className="flex-1 flex min-h-0">
        {asList ? (
          <FlatDocsView files={tree.flatFiles} sortConfig={state.sortConfig}
            onSort={state.toggleSort} onOpen={openNode} />
        ) : (
        <>
        <div className="hidden md:block w-64 shrink-0 bg-sidebar border-r border-border overflow-y-auto scroll-thin">
          {/* Быстрый доступ */}
          <div className="py-1">
            <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Быстрый доступ</div>
            <button onClick={() => state.navigateTo([])}
              className={cn('flex items-center gap-2 h-7 w-full px-3 text-[13px] hover:bg-sidebar-accent', currentKey === '' && 'bg-primary/25')}>
              <HardDrive className="h-4 w-4 text-blue-400" /> Документы компании
            </button>
          </div>
          <div className="mx-2 my-1 h-px bg-border" />
          <NavTree
            fsTree={tree.fsTree}
            expandedPaths={state.treeState.expandedPaths}
            currentKey={currentKey}
            onToggle={state.toggleExpanded}
            onNavigate={(path) => { state.navigateTo(path.split('/')); if (!state.treeState.expandedPaths.includes(path)) state.toggleExpanded(path) }}
          />
        </div>

        <DetailsList
          items={items}
          selectedPath={selected?.path ?? null}
          onSelect={state.setSelectedNode}
          onOpen={openNode}
          sortConfig={state.sortConfig}
          onSort={state.toggleSort}
        />

        {previewOpen && <PreviewPane node={selected} />}
        </>
        )}
      </div>

      {/* Статус-бар */}
      <div className="flex items-center gap-3 h-6 px-3 bg-card border-t border-border shrink-0 text-[11px] text-muted-foreground">
        <span>Элементов: {items.length}</span>
        {(selectedFolders > 0 || selectedFiles > 0) && (
          <span>{selectedFolders > 0 ? `папок: ${selectedFolders}` : ''}{selectedFolders > 0 && selectedFiles > 0 ? ' · ' : ''}{selectedFiles > 0 ? `файлов: ${selectedFiles}` : ''}</span>
        )}
        {selected && <span className="ml-auto truncate">{selected.name}</span>}
      </div>

      {/* Модалки просмотра документов: localStorage-прототип + серверные (БД) */}
      <ShiftDetailModal shift={state.viewingShift} onClose={() => state.setViewingShift(null)} />
      <DeliveryDetailModal delivery={state.viewingDelivery} onClose={() => state.setViewingDelivery(null)} />
      <ShiftDetailsDialog
        shiftId={state.viewingApiShiftId}
        open={!!state.viewingApiShiftId}
        onClose={() => state.setViewingApiShiftId(null)}
      />
      <ReceiptDetailsModal
        receipt={state.viewingApiReceipt}
        open={!!state.viewingApiReceipt}
        onClose={() => state.setViewingApiReceipt(null)}
      />
      <BookDocDialog companyId={companyId} docId={viewingDocId} onClose={() => setViewingDocId(null)} />
    </div>
  )
}
