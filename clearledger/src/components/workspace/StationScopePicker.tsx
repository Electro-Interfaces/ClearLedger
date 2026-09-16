/**
 * Подбор станций ЭЗС для рабочего контура: фасеты слева, список справа.
 *
 * Сеть — шестьсот станций, и выбирать их перебором нельзя: «быстрые на трассе
 * производителя ПСС, у которых не было ни одной зарядки» — обычный рабочий
 * вопрос инженера, а не экзотика. Поэтому паспорт станции (скорость,
 * размещение, производитель, мощность, разъём, состояние, контур) работает
 * фасетами: каждое условие сужает список, счётчик рядом показывает, сколько
 * станций останется, а выбор всё равно остаётся явным — в контур уезжают
 * отмеченные коды, а не «всё, что сейчас на экране».
 *
 * **Условия — это отбор, а не подсказка для поиска.** Пока станции не отмечены
 * руками, в контур уходит всё, что подходит под условия: человек выбирает «wallbox»
 * и ждёт статистику по wallbox, а не список, в котором ещё надо расставить галки.
 * Прежде фасет только сужал показ — отметив пару станций для пробы, человек получал
 * статистику по этой паре и считал это ошибкой счёта (Чурилов, 15.09.2026,
 * поручения №65 и №66).
 *
 * Отметил станцию сам — набор становится поштучным, и условия снова только сужают
 * показ: ручной выбор сильнее автоматического. «Снять выбор» возвращает к отбору
 * условиями.
 *
 * Фасеты живут только здесь: наружу уходит список кодов, который панели уже
 * понимают. Регион — исключение: он часть общего фильтра (`regionIds`) и
 * сужает не только этот список, но и разрезы разделов.
 *
 * Отбор и счётчики — в `@/lib/stationFacets` (там же их проверка).
 */

import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, ListFilter, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { ChargeDimensionStation } from '@/services/analyticsService'
import {
  FACET_GROUPS, codesByFacets, facetValues, matchesFacets, sortStations, stationMeta,
  stationSearchText,
  type FacetGroupDef, type FacetValue, type Facets, type GroupKey, type StationSort,
} from '@/lib/stationFacets'
import { cn } from '@/lib/utils'

const SORTS: { key: StationSort; label: string }[] = [
  { key: 'sessions', label: 'По числу зарядок' },
  { key: 'name', label: 'По названию' },
  { key: 'code', label: 'По коду' },
  { key: 'power', label: 'По мощности' },
]

function FacetGroup({
  group, values, picked, onToggle,
}: {
  group: FacetGroupDef
  values: FacetValue[]
  picked: string[]
  onToggle: (value: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [query, setQuery] = useState('')
  const head = group.head ?? values.length
  // Поиск — только у длинных справочников и только когда искать есть в чём:
  // над списком из пяти значений строка поиска лишняя.
  const ищем = Boolean(group.alpha) && values.length > 8
  const q = query.trim().toLowerCase()
  const найденные = q
    ? values.filter((v) => group.labelOf(v.value).toLowerCase().includes(q))
    : values
  // Выбранное показываем всегда: значение, которое человек отметил, не должно
  // уезжать под «ещё N» — иначе снять его можно только раскрыв список.
  // При поиске показываем всё найденное: прятать половину ответа под «ещё N» —
  // значит заставлять искать дважды.
  const shown = expanded || q
    ? найденные
    : найденные.filter((v, index) => index < head || picked.includes(v.value))
  const hidden = найденные.length - shown.length

  if (values.length === 0) return null

  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="mb-1 flex w-full items-center justify-between gap-2 text-xs font-semibold text-foreground">
        <span>{group.label}</span>
        {picked.length > 0 ? (
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
            {picked.length}
          </span>
        ) : null}
      </legend>
      {ищем ? (
        <div className="relative mb-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={`${group.label.toLocaleLowerCase('ru')} — поиск`}
            aria-label={`Поиск: ${group.label}`}
            className="h-7 pl-7 text-xs" />
        </div>
      ) : null}
      {ищем && q && найденные.length === 0 ? (
        <p className="px-1.5 py-2 text-xs text-muted-foreground">Ничего не нашлось</p>
      ) : null}
      <div className="flex flex-col">
        {shown.map(({ value, count }) => {
          const active = picked.includes(value)
          return (
            <label
              key={value}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-xs',
                'hover:bg-muted/70',
                count === 0 && !active ? 'opacity-50' : null,
              )}
            >
              <Checkbox checked={active} onCheckedChange={() => onToggle(value)} />
              <span className="min-w-0 flex-1 truncate" title={group.labelOf(value)}>
                {group.labelOf(value)}
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{count}</span>
            </label>
          )
        })}
      </div>
      {hidden > 0 || expanded ? (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="self-start rounded px-1.5 py-0.5 text-xs text-primary hover:underline"
        >
          {expanded ? 'Свернуть' : `Ещё ${hidden}`}
        </button>
      ) : null}
    </fieldset>
  )
}

export function StationScopePicker({
  stations, selected, onChange, regionIds, onRegionsChange, companyId,
}: {
  stations: ChargeDimensionStation[]
  selected: string[]
  onChange: (codes: string[]) => void
  regionIds: string[]
  onRegionsChange: (regions: string[]) => void
  /** Чей контур: условия отбора запоминаются по компании. */
  companyId?: string | null
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<StationSort>('sessions')
  // Вернулся к фильтру — видишь свою выборку, а не всю сеть. «Если возвращаешься
  // к фильтру, то снова в нём все ЭЗС, а не ранее отобранные. Приходится вспоминать,
  // в каком фильтре ты был» (Чурилов, 12.09.2026). Режим снимается одной кнопкой,
  // когда к выборке надо что-то добавить.
  const [onlyPicked, setOnlyPicked] = useState(() => selected.length > 0)
  // Как набран контур: условиями или поштучно. Пришли с готовой выборкой — значит
  // её набирали руками, и переписывать её условиями нельзя.
  const [поштучно, setПоштучно] = useState(() => selected.length > 0)
  // Условия отбора переживают закрытие окна: человек возвращается к той же работе,
  // а не набирает фасеты заново. Хранится по компании — контуры у них разные.
  const ключФасетов = `cl-station-facets-${companyId ?? 'all'}`
  const [localFacets, setLocalFacets] = useState<Facets>(() => {
    try {
      const saved = localStorage.getItem(ключФасетов)
      return saved ? (JSON.parse(saved) as Facets) : {}
    } catch { return {} }
  })
  useEffect(() => {
    try { localStorage.setItem(ключФасетов, JSON.stringify(localFacets)) } catch { /* приватный режим */ }
  }, [ключФасетов, localFacets])

  const selectedSet = useMemo(() => new Set(selected), [selected])
  // Регион живёт в общем фильтре, остальные фасеты — здесь. Для расчётов это
  // один набор: правило сужения одинаковое, разное только место хранения.
  const facets: Facets = useMemo(
    () => ({ ...localFacets, region: regionIds }),
    [localFacets, regionIds],
  )

  // Правило отбора — в `lib/stationFacets` рядом с его проверкой. Поиск в контур не
  // входит: он про «где эта станция», а не про «какие станции беру».
  const контурПоУсловиям = (набор: Facets) => codesByFacets(stations, набор)

  const setFacet = (key: GroupKey, value: string) => {
    if (key === 'region') {
      const регионы = regionIds.includes(value)
        ? regionIds.filter((r) => r !== value)
        : [...regionIds, value]
      onRegionsChange(регионы)
      if (!поштучно) onChange(контурПоУсловиям({ ...localFacets, region: регионы }))
      return
    }
    const picked = localFacets[key] ?? []
    const next: Facets = {
      ...localFacets,
      [key]: picked.includes(value) ? picked.filter((v) => v !== value) : [...picked, value],
    }
    setLocalFacets(next)
    if (!поштучно) onChange(контурПоУсловиям({ ...next, region: regionIds }))
  }

  /** Отметка станции руками: дальше контур набирается поштучно. */
  const отметить = (codes: string[]) => {
    setПоштучно(true)
    onChange(codes)
  }

  /** Снятие выбора возвращает к отбору условиями — иначе выйти из ручного режима
   *  можно было бы только закрыв окно. */
  const снятьВыбор = () => {
    setПоштучно(false)
    onChange(контурПоУсловиям({ ...localFacets, region: regionIds }))
  }

  const снятьУсловия = () => {
    setLocalFacets({})
    onRegionsChange([])
    if (!поштучно) onChange([])
  }

  const searched = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return stations
    return stations.filter((s) => stationSearchText(s).includes(q))
  }, [query, stations])

  const groupValues = useMemo(() => facetValues(searched, facets), [facets, searched])

  const filtered = useMemo(() => sortStations(
    searched.filter((s) => matchesFacets(s, facets))
      .filter((s) => !onlyPicked || selectedSet.has(s.code)),
    sort,
  ), [facets, onlyPicked, searched, selectedSet, sort])

  const shownCodes = useMemo(() => filtered.map((s) => s.code), [filtered])
  // Сколько станций подходит под условия — без учёта поиска и режима «только
  // выбранные»: это и есть контур, когда набор идёт условиями.
  const подУсловиями = useMemo(
    () => stations.filter((s) => matchesFacets(s, facets)).length, [facets, stations])
  const allShownPicked = shownCodes.length > 0 && shownCodes.every((c) => selectedSet.has(c))

  const activeFacets = useMemo(() => {
    const chips: { key: GroupKey; value: string; label: string }[] = []
    for (const group of FACET_GROUPS) {
      for (const value of facets[group.key] ?? []) {
        chips.push({ key: group.key, value, label: `${group.label}: ${group.labelOf(value)}` })
      }
    }
    return chips
  }, [facets])

  // Доля сети в выборке: без неё «выбрано 40» ничего не говорит — сорок станций
  // могут давать и два процента зарядок, и половину сети.
  const totalSessions = useMemo(
    () => stations.reduce((sum, s) => sum + s.sessions, 0), [stations])
  const pickedSessions = useMemo(
    () => stations.filter((s) => selectedSet.has(s.code)).reduce((sum, s) => sum + s.sessions, 0),
    [selectedSet, stations],
  )
  const pickedShare = totalSessions > 0 ? Math.round((pickedSessions / totalSessions) * 100) : 0
  const outOfView = selected.filter((code) => !shownCodes.includes(code)).length

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Найти станцию: название, код, город, улица или производитель"
            className="h-9 pl-8 text-xs"
            aria-label="Поиск станции"
          />
          {query ? (
            <Button
              variant="ghost" size="icon-xs"
              className="absolute right-1 top-1/2 -translate-y-1/2"
              onClick={() => setQuery('')}
              aria-label="Очистить поиск"
            >
              <X />
            </Button>
          ) : null}
        </div>
        <Select value={sort} onValueChange={(value) => setSort(value as StationSort)}>
          <SelectTrigger size="sm" className="w-[190px] text-xs" aria-label="Порядок станций">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORTS.map((option) => (
              <SelectItem key={option.key} value={option.key} className="text-xs">{option.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant={onlyPicked ? 'default' : 'outline'}
          size="sm"
          className="h-9"
          onClick={() => setOnlyPicked((current) => !current)}
          aria-pressed={onlyPicked}
        >
          <ListFilter data-icon="inline-start" />
          Только выбранные
        </Button>
      </div>

      {activeFacets.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {activeFacets.map((chip) => (
            <button
              key={`${chip.key}:${chip.value}`}
              type="button"
              onClick={() => setFacet(chip.key, chip.value)}
              className="inline-flex max-w-[280px] items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/15"
              title={`Снять условие «${chip.label}»`}
            >
              <span className="truncate">{chip.label}</span>
              <X className="size-3 shrink-0" aria-hidden="true" />
            </button>
          ))}
          <Button
            variant="ghost" size="xs" className="h-7"
            onClick={снятьУсловия}
          >
            Снять все условия
          </Button>
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="flex max-h-[240px] flex-col gap-4 overflow-y-auto rounded-lg border bg-muted/20 p-3 lg:max-h-none">
          {FACET_GROUPS.map((group) => (
            <FacetGroup
              key={group.key}
              group={group}
              values={groupValues.get(group.key) ?? []}
              picked={facets[group.key] ?? []}
              onToggle={(value) => setFacet(group.key, value)}
            />
          ))}
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border">
          <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
            <label className="flex cursor-pointer items-center gap-2 text-xs font-medium">
              <Checkbox
                checked={allShownPicked}
                disabled={shownCodes.length === 0}
                onCheckedChange={() => отметить(allShownPicked
                  ? selected.filter((code) => !shownCodes.includes(code))
                  : [...new Set([...selected, ...shownCodes])])}
              />
              {allShownPicked ? 'Снять показанные' : 'Выбрать показанные'}
            </label>
            <span className="text-xs text-muted-foreground">
              Показано: <span className="tabular-nums text-foreground">{filtered.length}</span> из {stations.length}
            </span>
          </div>

          <div className="min-h-[220px] flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 py-10 text-center">
                <p className="text-xs text-muted-foreground">
                  {onlyPicked
                    ? 'Среди выбранных станций нет ни одной, подходящей под условия.'
                    : 'Под эти условия не подходит ни одна станция сети.'}
                </p>
                {activeFacets.length > 0 ? (
                  <Button variant="outline" size="xs" onClick={снятьУсловия}>
                    Снять условия
                  </Button>
                ) : null}
              </div>
            ) : filtered.map((station) => {
              const active = selectedSet.has(station.code)
              const meta = stationMeta(station)
              return (
                <label
                  key={station.code}
                  className={cn(
                    'flex cursor-pointer items-start gap-2.5 border-b px-3 py-2 text-xs last:border-b-0',
                    active ? 'bg-primary/5' : 'hover:bg-muted/50',
                  )}
                >
                  <Checkbox
                    className="mt-0.5"
                    checked={active}
                    onCheckedChange={() => отметить(active
                      ? selected.filter((code) => code !== station.code)
                      : [...selected, station.code])}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{station.name}</span>
                    {meta ? <span className="block text-muted-foreground">{meta}</span> : null}
                  </span>
                  <span className="flex shrink-0 flex-col items-end">
                    <span className="font-mono tabular-nums text-muted-foreground">{station.code}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {station.sessions > 0 ? `${station.sessions.toLocaleString('ru')} зар.` : 'нет зарядок'}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t bg-muted/30 px-3 py-2 text-xs">
            <span className="text-muted-foreground">
              {selected.length === 0 ? (
                'Станции не выбраны — контур охватывает всю сеть.'
              ) : !поштучно ? (
                <>
                  Условия отобрали <span className="font-medium text-foreground">{подУсловиями}</span> станций
                  {' — они и войдут в контур · '}
                  <span className="font-medium text-foreground">{pickedShare}%</span> зарядок сети
                </>
              ) : (
                <>
                  Выбрано <span className="font-medium text-foreground">{selected.length}</span> из {stations.length}
                  {' · '}
                  <span className="font-medium text-foreground">{pickedShare}%</span> зарядок сети
                  {outOfView > 0 ? ` · вне текущего отбора: ${outOfView}` : ''}
                </>
              )}
            </span>
            {selected.length > 0 ? (
              <Button variant="ghost" size="xs" className="h-7" onClick={снятьВыбор}>
                <Check data-icon="inline-start" />
                Снять выбор
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <ChevronDown className="size-3.5 rotate-[-90deg]" aria-hidden="true" />
        {поштучно
          ? 'Контур набран поштучно: условия слева сужают список, но выбор задают галки. «Снять выбор» вернёт отбор по условиям.'
          : 'Условия слева задают контур целиком. Отметьте станции галками, если нужен точечный набор.'}
      </p>
    </div>
  )
}
