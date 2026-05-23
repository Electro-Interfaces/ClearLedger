import { Calendar, Clock, AlertCircle, FileText, AlertTriangle, X, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { startOfMonth, subDays, format } from 'date-fns'
import type { AdvancedFilters, FilterPreset } from './raw-panel-types'

function today() { return format(new Date(), 'yyyy-MM-dd') }

const PRESETS: FilterPreset[] = [
  { id: 'current-month', label: 'Текущий месяц',
    apply: { dateFrom: format(startOfMonth(new Date()), 'yyyy-MM-dd'), dateTo: today() } },
  { id: 'last-7', label: 'Последние 7 дней',
    apply: { dateFrom: format(subDays(new Date(), 7), 'yyyy-MM-dd'), dateTo: today() } },
  { id: 'unclosed', label: 'Незакрытые',
    apply: { statuses: ['open'] } },
  { id: 'drafts', label: 'Черновики',
    apply: { statuses: ['draft'] } },
  { id: 'issues', label: 'С расхождениями',
    apply: { onlyWithIssues: true } },
]

const ALL_STATUSES = [
  { value: 'open', label: 'Открытые' },
  { value: 'closed', label: 'Закрытые' },
  { value: 'draft', label: 'Черновики' },
  { value: 'posted', label: 'Проведённые' },
]

interface Props {
  filters: AdvancedFilters
  onChange: (filters: AdvancedFilters) => void
  onPreset: (preset: Partial<AdvancedFilters>) => void
  onClear: () => void
  filteredCount: number
  totalCount: number
  /** Dynamic options from data */
  categories: string[]
  docTypes: string[]
  objects: { id: string; name: string }[]
  sources: string[]
}

export function RawPanelFilterTab({
  filters, onChange, onPreset, onClear,
  filteredCount, totalCount,
  categories, docTypes, objects, sources,
}: Props) {
  function set<K extends keyof AdvancedFilters>(key: K, value: AdvancedFilters[K]) {
    onChange({ ...filters, [key]: value })
  }

  function toggleStatus(status: string) {
    const next = filters.statuses.includes(status)
      ? filters.statuses.filter((s) => s !== status)
      : [...filters.statuses, status]
    set('statuses', next)
  }

  return (
    <div className="space-y-5">
      {/* Quick presets */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-2 block">Быстрый доступ</Label>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <Button key={p.id} variant="outline" size="sm" className="text-xs h-7"
              onClick={() => onPreset(p.apply)}>
              {p.id === 'current-month' && <Calendar className="h-3 w-3 mr-1" />}
              {p.id === 'last-7' && <Clock className="h-3 w-3 mr-1" />}
              {p.id === 'unclosed' && <AlertCircle className="h-3 w-3 mr-1" />}
              {p.id === 'drafts' && <FileText className="h-3 w-3 mr-1" />}
              {p.id === 'issues' && <AlertTriangle className="h-3 w-3 mr-1" />}
              {p.label}
            </Button>
          ))}
          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={onClear}>
            <X className="h-3 w-3 mr-1" /> Очистить
          </Button>
        </div>
      </div>

      <Separator />

      {/* Search */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 block">Поиск</Label>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={filters.query}
            onChange={(e) => set('query', e.target.value)}
            placeholder="Номер, название, контрагент..."
            className="pl-9"
          />
        </div>
      </div>

      {/* Date range */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 block">Период</Label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">С</Label>
            <Input type="date" value={filters.dateFrom} onChange={(e) => set('dateFrom', e.target.value)} />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">По</Label>
            <Input type="date" value={filters.dateTo} onChange={(e) => set('dateTo', e.target.value)} />
          </div>
        </div>
      </div>

      <Separator />

      {/* Classification */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 block">Классификация</Label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Категория</Label>
            <Select value={filters.category} onValueChange={(v) => set('category', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все категории</SelectItem>
                {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Тип документа</Label>
            <Select value={filters.docType} onValueChange={(v) => set('docType', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все типы</SelectItem>
                {docTypes.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Binding */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 block">Привязка</Label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Объект</Label>
            <Select value={filters.objectId} onValueChange={(v) => set('objectId', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все объекты</SelectItem>
                {objects.map((o) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Источник</Label>
            <Select value={filters.source} onValueChange={(v) => set('source', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все источники</SelectItem>
                {sources.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <Separator />

      {/* Status checkboxes */}
      <div>
        <Label className="text-xs text-muted-foreground uppercase tracking-wider mb-1.5 block">Статус</Label>
        <div className="flex flex-wrap gap-4">
          {ALL_STATUSES.map((s) => (
            <label key={s.value} className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={filters.statuses.includes(s.value)}
                onCheckedChange={() => toggleStatus(s.value)}
              />
              <span className="text-sm">{s.label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Only with issues */}
      <label className="flex items-center gap-2 cursor-pointer">
        <Checkbox
          checked={filters.onlyWithIssues}
          onCheckedChange={(v) => set('onlyWithIssues', !!v)}
        />
        <span className="text-sm">Только с расхождениями / проблемами</span>
      </label>

      <Separator />

      {/* Result count */}
      <div className="text-sm text-muted-foreground">
        Найдено: <span className="font-semibold text-foreground">{filteredCount}</span> из {totalCount} документов
      </div>
    </div>
  )
}
