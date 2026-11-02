import { useId, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { captureApiContextGuard, get } from '@/services/apiClient'

interface StationOption {
  id: string
  code: string
  name: string
  type: string
  address: string | null
}

interface Props {
  companyId: string
  value: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}

const stationName = (station: StationOption) => [station.code, station.name].filter(Boolean).join(' · ')

/** Выбор связей с реестром для паспорта СМР; состояние оборудования не меняется. */
export function ProjectDismantleStations(props: Props) {
  return <ScopedDismantleStations key={props.companyId} {...props} />
}

function ScopedDismantleStations({ companyId, value, onChange, disabled = false }: Props) {
  const instanceId = useId()
  const [guard] = useState(() => captureApiContextGuard())
  const [stale, setStale] = useState(false)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<string[]>([])
  let current = !stale
  try { guard() } catch { current = false }
  const catalog = useQuery({
    // A fresh mounted editor must not reuse another session's scoped catalog.
    queryKey: ['project-dismantle-stations', companyId, instanceId],
    queryFn: async ({ signal }) => {
      guard()
      try {
        const result = await get<StationOption[]>('/api/locations', { company_id: companyId }, { signal })
        guard()
        return result
      } catch (error) { guard(); throw error }
    },
    enabled: current && (open || value.length > 0),
    retry: false,
  })
  const stations = useMemo(() => (catalog.data ?? []).filter((station) => station.type === 'ev_charging'), [catalog.data])
  const names = useMemo(() => new Map(stations.map((station) => [station.id, stationName(station)])), [stations])
  const filtered = useMemo(() => {
    const term = search.trim().toLocaleLowerCase('ru')
    return stations.filter((station) => `${station.code} ${station.name} ${station.address ?? ''}`.toLocaleLowerCase('ru').includes(term))
  }, [stations, search])
  const picked = useMemo(() => new Set(draft), [draft])

  function canChange() {
    try { guard(); return !disabled } catch { setStale(true); setOpen(false); return false }
  }
  function changeOpen(next: boolean) {
    if (!canChange()) return
    if (next) { setDraft([...new Set(value)]); setSearch('') }
    setOpen(next)
  }

  if (!current) return <Alert><AlertDescription>Сеанс изменился. Откройте карточку заново.</AlertDescription></Alert>
  const loading = catalog.isPending || catalog.isFetching
  return <div className="flex flex-col gap-2">
    <p className="text-sm text-muted-foreground">План демонтажа в паспорте СМР.</p>
    {value.length === 0 ? <p className="text-sm text-muted-foreground">Станции не выбраны</p> : (
      <ul className="flex flex-col gap-1">
        {value.map((id) => <li key={id} className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 break-words">{names.get(id) ?? (catalog.isPending ? 'Загрузка станции…' : 'Станция недоступна в текущем реестре')}</span>
          <Button type="button" size="icon" variant="ghost" className="shrink-0" disabled={disabled}
            aria-label={`Убрать из перечня: ${names.get(id) ?? 'станция'}`}
            onClick={() => { if (canChange()) onChange(value.filter((item) => item !== id)) }}>
            <X />
          </Button>
        </li>)}
      </ul>
    )}
    {catalog.isError && <Alert><AlertDescription className="flex flex-wrap items-center gap-2">
      Не удалось загрузить реестр станций.
      <Button type="button" variant="outline" disabled={disabled} onClick={() => { if (canChange()) void catalog.refetch() }}>Повторить</Button>
    </AlertDescription></Alert>}
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button id="passport-dismantleLocationIds" type="button" variant="outline" className="self-start" disabled={disabled}>
          Выбрать ЭЗС ({value.length})
        </Button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[90dvh] w-[96vw] flex-col gap-3 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>ЭЗС к демонтажу</DialogTitle>
          <DialogDescription>Выберите доступные ЭЗС для плана СМР.</DialogDescription>
        </DialogHeader>
        <Input aria-label="Поиск ЭЗС к демонтажу" placeholder="Номер, название или адрес" value={search} disabled={disabled}
          onChange={(event) => { if (canChange()) setSearch(event.target.value) }} />
        {catalog.isPending ? <div role="status" className="flex flex-col gap-2">
          <span>Загрузка станций…</span><Skeleton className="h-11 w-full" /><Skeleton className="h-11 w-full" />
        </div> : catalog.isError ? (
          <Alert><AlertDescription className="flex flex-wrap items-center gap-2">Не удалось загрузить реестр.
            <Button type="button" variant="outline" disabled={disabled} onClick={() => { if (canChange()) void catalog.refetch() }}>Повторить</Button>
          </AlertDescription></Alert>
        ) : <div className="min-h-0 overflow-y-auto" aria-busy={catalog.isFetching}>
          {filtered.length === 0 ? <p role="status" className="text-sm text-muted-foreground">
            {search.trim() ? 'По запросу станции не найдены. Измените поиск.' : 'В доступном реестре нет ЭЗС.'}
          </p> : (
            <ul className="flex flex-col gap-1">
              {filtered.map((station) => <li key={station.id}>
                <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md p-2 hover:bg-accent">
                  <Checkbox checked={picked.has(station.id)} disabled={disabled || loading}
                    onCheckedChange={(checked) => { if (canChange()) setDraft((ids) => checked === true ? [...new Set([...ids, station.id])] : ids.filter((id) => id !== station.id)) }} />
                  <span className="min-w-0 text-sm"><span className="block break-words">{stationName(station)}</span>
                    {station.address && <span className="block break-words text-muted-foreground">{station.address}</span>}
                  </span>
                </label>
              </li>)}
            </ul>
          )}
        </div>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button type="button" disabled={disabled || loading || catalog.isError}
            onClick={() => { if (canChange()) { onChange(draft); setOpen(false) } }}>Применить выбор ({draft.length})</Button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
}
