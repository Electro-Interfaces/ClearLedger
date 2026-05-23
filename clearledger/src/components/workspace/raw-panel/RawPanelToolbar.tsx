import { Search, List, GitBranchPlus, RefreshCw, SlidersHorizontal, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { RawPanelState } from './useRawPanelState'

interface Props {
  state: RawPanelState
  isFetching: boolean
  onRefresh: () => void
}

export function RawPanelToolbar({ state, isFetching, onRefresh }: Props) {
  const { viewMode, setViewMode, filters, updateFilter, setFilterDialogOpen, hasAdvancedFilters, activeFilterCount } = state

  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border/30">
      {/* Search */}
      <div className="relative flex-1">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
        <Input
          value={filters.searchQuery}
          onChange={(e) => updateFilter('searchQuery', e.target.value)}
          placeholder="Поиск..."
          className="h-7 text-xs pl-7"
        />
        {filters.searchQuery && (
          <button
            onClick={() => updateFilter('searchQuery', '')}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 h-4 w-4 flex items-center justify-center rounded hover:bg-accent"
          >
            <X className="h-3 w-3 text-muted-foreground" />
          </button>
        )}
      </div>

      {/* View mode toggle */}
      <div className="flex items-center border border-border/40 rounded-md">
        <Button
          variant={viewMode === 'tree' ? 'secondary' : 'ghost'}
          size="icon"
          className="h-7 w-7 rounded-r-none"
          onClick={() => setViewMode('tree')}
          title="Дерево"
        >
          <GitBranchPlus className="h-3 w-3" />
        </Button>
        <Button
          variant={viewMode === 'list' ? 'secondary' : 'ghost'}
          size="icon"
          className="h-7 w-7 rounded-l-none border-l border-border/40"
          onClick={() => setViewMode('list')}
          title="Список"
        >
          <List className="h-3 w-3" />
        </Button>
      </div>

      {/* Open advanced filter dialog */}
      <Button
        variant={hasAdvancedFilters ? 'secondary' : 'ghost'}
        size="icon"
        className="h-7 w-7 shrink-0 relative"
        onClick={() => setFilterDialogOpen(true)}
        title="Фильтры и аналитика"
      >
        <SlidersHorizontal className="h-3 w-3" />
        {activeFilterCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 h-3.5 min-w-[14px] rounded-full bg-primary text-primary-foreground text-[9px] flex items-center justify-center px-0.5">
            {activeFilterCount}
          </span>
        )}
      </Button>

      {/* Refresh */}
      <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onRefresh} disabled={isFetching} title="Обновить (F5)">
        <RefreshCw className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`} />
      </Button>
    </div>
  )
}
