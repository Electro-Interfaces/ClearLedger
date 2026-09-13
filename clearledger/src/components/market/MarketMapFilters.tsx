/**
 * Фильтры карты рынка: два слоя, и у каждого свои основания для отбора.
 *
 * Чужие точки отбираются по тому, что видно снаружи: класс, оператор, ток, мощность,
 * живость. Свои — по тому, как они работают: состояние и связь, класс скорости,
 * производитель, загрузка порта, доля сорванных зарядок. В этом и смысл отдельного
 * слоя: про свои станции мы знаем то, чего про чужие не знает никто.
 */
import { Layers } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SITE_KIND_LABEL, type MarketOperator } from '@/services/marketService'

export interface MarketFilters {
  showOurs: boolean
  showRivals: boolean
  showIndependent: boolean
  showHome: boolean
  showAttractors: boolean
  kind: string
  operatorId: string
  currentType: string
  minPower: string
  alive: string
}

export interface OurFilters {
  status: string
  speedClass: string
  brand: string
  minPower: string
  load: string
  errors: string
  colorBy: 'status' | 'load' | 'errors' | 'revenue'
}

export const EMPTY_MARKET_FILTERS: MarketFilters = {
  showOurs: true, showRivals: true, showIndependent: true,
  showHome: false, showAttractors: true,
  kind: 'all', operatorId: 'all', currentType: 'all', minPower: 'all', alive: 'all',
}

export const EMPTY_OUR_FILTERS: OurFilters = {
  status: 'all', speedClass: 'all', brand: 'all', minPower: 'all',
  load: 'all', errors: 'all', colorBy: 'status',
}

const STATUS_LABEL: Record<string, string> = {
  working: 'работает',
  no_link: 'нет связи',
  not_working: 'не работает',
  disabled: 'отключена',
  decommissioned: 'выведена',
}

/** Флажок слоя: имя рядом с цветом — цвет один состояние не называет. */
function LayerToggle({ on, onChange, color, label, count }: {
  on: boolean; onChange: (v: boolean) => void
  color: string; label: string; count?: number
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs">
      <input type="checkbox" className="size-4" checked={on}
        onChange={(e) => onChange(e.target.checked)} />
      <i className="size-2 rounded-full" style={{ background: color }} aria-hidden />
      <span>{label}</span>
      {count != null && <span className="tabular-nums text-muted-foreground">{count}</span>}
    </label>
  )
}

export function MarketMapFilters({
  filters, onFilters, our, onOur, operators, brands, statuses, counts,
}: {
  filters: MarketFilters
  onFilters: (v: MarketFilters) => void
  our: OurFilters
  onOur: (v: OurFilters) => void
  operators: MarketOperator[]
  brands: string[]
  statuses: string[]
  counts: { ours: number; rivals: number; independent: number; home: number; attractors: number }
}) {
  const set = (patch: Partial<MarketFilters>) => onFilters({ ...filters, ...patch })
  const setOur = (patch: Partial<OurFilters>) => onOur({ ...our, ...patch })

  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2 text-xs font-semibold">
        <Layers className="size-3.5 text-primary" aria-hidden /> Слои карты
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <LayerToggle on={filters.showOurs} onChange={(v) => set({ showOurs: v })}
          color="#3b82f6" label="наши станции" count={counts.ours} />
        <LayerToggle on={filters.showRivals} onChange={(v) => set({ showRivals: v })}
          color="#ef4444" label="сети конкурентов" count={counts.rivals} />
        <LayerToggle on={filters.showIndependent} onChange={(v) => set({ showIndependent: v })}
          color="#f59e0b" label="независимые точки" count={counts.independent} />
        <LayerToggle on={filters.showHome} onChange={(v) => set({ showHome: v })}
          color="#a78bfa" label="домашние розетки" count={counts.home} />
        <LayerToggle on={filters.showAttractors} onChange={(v) => set({ showAttractors: v })}
          color="#94a3b8" label="точки притяжения" count={counts.attractors} />
      </div>

      <div className="grid gap-2 border-t border-border/60 pt-2 md:grid-cols-2">
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">
            Чужие точки — по тому, что видно снаружи
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Select value={filters.kind} onValueChange={(v) => set({ kind: v })}>
              <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любой вид</SelectItem>
                {Object.entries(SITE_KIND_LABEL).map(([k, label]) => (
                  <SelectItem key={k} value={k}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filters.operatorId} onValueChange={(v) => set({ operatorId: v })}>
              <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая сеть</SelectItem>
                {operators.filter((o) => o.sites > 0).slice(0, 40).map((o) => (
                  <SelectItem key={o.id} value={o.id}>{o.name} · {o.sites}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filters.currentType} onValueChange={(v) => set({ currentType: v })}>
              <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любой ток</SelectItem>
                <SelectItem value="DC">DC</SelectItem>
                <SelectItem value="AC">AC</SelectItem>
                <SelectItem value="LV">LV</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filters.minPower} onValueChange={(v) => set({ minPower: v })}>
              <SelectTrigger className="h-7 w-[140px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая мощность</SelectItem>
                <SelectItem value="22">от 22 кВт</SelectItem>
                <SelectItem value="60">от 60 кВт</SelectItem>
                <SelectItem value="150">от 150 кВт</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filters.alive} onValueChange={(v) => set({ alive: v })}>
              <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Живые и молчащие</SelectItem>
                <SelectItem value="true">Заряжали за 90 дней</SelectItem>
                <SelectItem value="false">Молчат больше 90 дней</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">
            Наши станции — по тому, как они работают
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Select value={our.status} onValueChange={(v) => setOur({ status: v })}>
              <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любое состояние</SelectItem>
                {statuses.map((st) => (
                  <SelectItem key={st} value={st}>{STATUS_LABEL[st] ?? st}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={our.speedClass} onValueChange={(v) => setOur({ speedClass: v })}>
              <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая скорость</SelectItem>
                <SelectItem value="fast">Быстрые</SelectItem>
                <SelectItem value="slow">Медленные</SelectItem>
              </SelectContent>
            </Select>
            <Select value={our.brand} onValueChange={(v) => setOur({ brand: v })}>
              <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любой производитель</SelectItem>
                {brands.slice(0, 40).map((b) => (
                  <SelectItem key={b} value={b}>{b}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={our.load} onValueChange={(v) => setOur({ load: v })}>
              <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая загрузка</SelectItem>
                <SelectItem value="idle">Простаивают (менее 0,3 сессии на порт)</SelectItem>
                <SelectItem value="low">Слабая (менее 1)</SelectItem>
                <SelectItem value="busy">Загруженные (от 2)</SelectItem>
              </SelectContent>
            </Select>
            <Select value={our.errors} onValueChange={(v) => setOur({ errors: v })}>
              <SelectTrigger className="h-7 w-[180px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Любая надёжность</SelectItem>
                <SelectItem value="bad">Срывов больше 30 %</SelectItem>
                <SelectItem value="good">Срывов меньше 10 %</SelectItem>
              </SelectContent>
            </Select>
            <Select value={our.colorBy}
              onValueChange={(v) => setOur({ colorBy: v as OurFilters['colorBy'] })}>
              <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="status">Цвет: состояние</SelectItem>
                <SelectItem value="load">Цвет: загрузка</SelectItem>
                <SelectItem value="errors">Цвет: срывы зарядок</SelectItem>
                <SelectItem value="revenue">Цвет: выручка</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  )
}
