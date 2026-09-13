/**
 * Фильтры карты рынка: два слоя, и у каждого свои основания для отбора.
 *
 * Чужие точки отбираются по тому, что видно снаружи: класс, оператор, ток, мощность,
 * живость. Свои — по тому, как они работают: состояние и связь, класс скорости,
 * производитель, загрузка порта, доля сорванных зарядок. В этом и смысл отдельного
 * слоя: про свои станции мы знаем то, чего про чужие не знает никто.
 */
import { useState } from 'react'
import { ChevronDown, ChevronUp, Layers } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SITE_KIND_LABEL, type MarketOperator } from '@/services/marketService'

export interface MarketFilters {
  showOurs: boolean
  showRivals: boolean
  /**
   * Наши же станции, как их видит внешний реестр. По умолчанию выключены: свой
   * слой показывает те же объекты по нашим данным — полнее и точнее, — а две
   * точки одного объекта разного цвета читаются как две разные станции.
   */
  showOursOnMarket: boolean
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
  showOursOnMarket: false, showHome: false, showAttractors: true,
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
/**
 * Переключатель слоя карты.
 *
 * У каждого слоя есть пояснение: названия вроде «независимые точки» и «точки
 * притяжения» понятны тому, кто знает, как устроен приём выгрузки, и загадочны
 * всем остальным. Пояснение живёт в подсказке при наведении и в строке под
 * слоями — вопрос «а что это вообще» не должен требовать похода к разработчику
 * (замечание МАГа 13.09.2026).
 */
function LayerToggle({ on, onChange, color, label, count, hint }: {
  on: boolean; onChange: (v: boolean) => void
  color: string; label: string; count?: number; hint: string
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs" title={hint}>
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
  counts: { ours: number; rivals: number; independent: number; home: number
            attractors: number; oursOnMarket: number }
}) {
  const set = (patch: Partial<MarketFilters>) => onFilters({ ...filters, ...patch })
  const setOur = (patch: Partial<OurFilters>) => onOur({ ...our, ...patch })

  // Блок занимает треть экрана, а нужен не всё время: выбрал разрез — дальше
  // смотришь карту. Поэтому раздел открывается СВЁРНУТЫМ: первое, зачем сюда
  // заходят, — это карта, а не настройка слоёв (МАГ, 13.09.2026).
  //
  // Свёрнутый заголовок продолжает отвечать, что включено, иначе сворачивание
  // превратило бы настройки в скрытое состояние: человек видел бы на карте не все
  // точки и не понимал почему.
  const [открыт, setОткрыт] = useState(false)
  const применено = [
    filters.kind !== 'all', filters.operatorId !== 'all', filters.currentType !== 'all',
    filters.minPower !== 'all', filters.alive !== 'all',
    our.status !== 'all', our.speedClass !== 'all', our.brand !== 'all',
    our.load !== 'all', our.errors !== 'all',
  ].filter(Boolean).length

  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={() => setОткрыт((v) => !v)}
          aria-expanded={открыт}
          className="flex items-center gap-1.5 font-semibold hover:text-primary">
          <Layers className="size-3.5 text-primary" aria-hidden />
          Слои и фильтры карты
          {открыт ? <ChevronUp className="size-3.5" aria-hidden />
            : <ChevronDown className="size-3.5" aria-hidden />}
        </button>
        {!открыт && (
          <span className="text-muted-foreground">
            {[
              filters.showOurs && `наши ${counts.ours}`,
              filters.showRivals && `чужие сети ${counts.rivals}`,
              filters.showIndependent && `одиночные ${counts.independent}`,
              filters.showOursOnMarket && `наши в реестре ${counts.oursOnMarket}`,
              filters.showHome && `розетки ${counts.home}`,
            ].filter(Boolean).join(' · ') || 'все слои выключены'}
            {применено > 0 && ` · фильтров применено: ${применено}`}
          </span>
        )}
      </div>
      {открыт && (
      <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <LayerToggle on={filters.showOurs} onChange={(v) => set({ showOurs: v })}
          color="#3b82f6" label="наши станции" count={counts.ours}
          hint="Объекты нашей сети из нашего же реестра, с нашими показателями работы" />
        <LayerToggle on={filters.showRivals} onChange={(v) => set({ showRivals: v })}
          color="#ef4444" label="чужие сети" count={counts.rivals}
          hint="Точки, у которых в выгрузке указан оператор — то есть за ними стоит сеть. Наши из этого слоя исключены" />
        <LayerToggle on={filters.showIndependent} onChange={(v) => set({ showIndependent: v })}
          color="#f59e0b" label="одиночные зарядки" count={counts.independent}
          hint="Публичные зарядки без указанного владельца: кто-то поставил и открыл для всех, сети за ними нет. В предложении территории они есть, в сравнении сетей — нет" />
        <LayerToggle on={filters.showOursOnMarket}
          onChange={(v) => set({ showOursOnMarket: v })}
          color="#3b82f6" label="наши в реестре рынка" count={counts.oursOnMarket}
          hint="Наши же станции, найденные во внешней выгрузке: так нас видит водитель в чужом приложении. Свой слой показывает те же объекты полнее" />
        <LayerToggle on={filters.showHome} onChange={(v) => set({ showHome: v })}
          color="#a78bfa" label="домашние розетки" count={counts.home}
          hint="Бытовые розетки у домов: рынком не считаются, в доли не входят" />
        <LayerToggle on={filters.showAttractors} onChange={(v) => set({ showAttractors: v })}
          color="#94a3b8" label="места притяжения" count={counts.attractors}
          hint="Торговые центры, парковки, АЗС — места, куда приезжают не заряжаться, но где зарядка была бы кстати. В выгрузке рынка их нет: она содержит только зарядки" />
      </div>

      {/* Одна строка вместо похода к разработчику: что за слои и почему числа
          такие. Числа — по видимой области карты, а не по всей стране. */}
      <p className="text-xs text-muted-foreground">
        Числа — по видимому куску карты. Сеть определяется по тому, указан ли у точки
        оператор; без него публичная зарядка считается одиночной. Источник ведёт
        отдельной записью каждый пост, а не площадку: в 79 местах их от двух до
        одиннадцати в одной координате — это не дубли, а соседние посты.
        {counts.attractors === 0 && ' Мест притяжения в выгрузке нет — она содержит только зарядки.'}
      </p>

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
                <SelectItem value="status">Кольцо: состояние</SelectItem>
                <SelectItem value="load">Кольцо: загрузка</SelectItem>
                <SelectItem value="errors">Кольцо: срывы зарядок</SelectItem>
                <SelectItem value="revenue">Кольцо: выручка</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {/* Разрез ушёл в кольцо, потому что заливка занята принадлежностью:
              наша станция синяя всегда, иначе выключенный объект серого цвета
              теряется среди чужих точек. */}
          <p className="text-xs text-muted-foreground">
            Наши станции всегда залиты синим — это принадлежность. Выбранный
            показатель показан кольцом вокруг точки и словами в подсказке.
          </p>
        </div>
      </div>
      </>
      )}
    </div>
  )
}
