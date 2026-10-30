import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { get } from '@/services/apiClient'

interface StationOption {
  id: string
  code: string
  name: string
  type: string
  address: string | null
}

const stationName = (station: StationOption) => [station.code, station.name].filter(Boolean).join(' · ')

/** Выбор связей с объектами реестра; план демонтажа не меняет их состояние. */
export function ProjectDismantleStations({ companyId, value, onChange }: {
  companyId: string; value: string[]; onChange: (ids: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<string[]>([])
  const catalog = useQuery({
    queryKey: ['project-dismantle-stations', companyId],
    queryFn: () => get<StationOption[]>('/api/locations', { company_id: companyId }),
    enabled: open || value.length > 0,
  })
  const stations = useMemo(() => (catalog.data ?? []).filter((station) => station.type === 'ev_charging'), [catalog.data])
  const names = useMemo(() => new Map(stations.map((station) => [station.id, stationName(station)])), [stations])
  const filtered = useMemo(() => {
    const term = search.trim().toLocaleLowerCase('ru')
    return stations.filter((station) => `${station.code} ${station.name} ${station.address ?? ''}`.toLocaleLowerCase('ru').includes(term))
  }, [stations, search])
  const picked = useMemo(() => new Set(draft), [draft])

  return <div className="flex flex-col gap-2">
    {value.length === 0 ? <p className="text-sm text-muted-foreground">Станции не выбраны</p> : (
      <ul className="flex flex-col gap-1">
        {value.map((id) => <li key={id} className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 break-words">{names.get(id) ?? (catalog.isPending ? 'Загрузка станции…' : 'Станция недоступна в текущем реестре')}</span>
          <Button type="button" size="icon" variant="ghost" className="shrink-0"
            aria-label={`Убрать из перечня: ${names.get(id) ?? 'станция'}`} onClick={() => onChange(value.filter((item) => item !== id))}>
            <X className="size-4" />
          </Button>
        </li>)}
      </ul>
    )}
    {catalog.isError && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm">
      Не удалось загрузить реестр станций.
      <Button type="button" variant="outline" onClick={() => void catalog.refetch()}>Повторить</Button>
    </div>}
    <Button id="passport-dismantleLocationIds" type="button" variant="outline" className="self-start"
      onClick={() => { setDraft([...value]); setSearch(''); setOpen(true) }}>Выбрать ЭЗС ({value.length})</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex max-h-[90dvh] w-[96vw] flex-col gap-3 sm:max-w-2xl">
        <DialogHeader><DialogTitle>ЭЗС к демонтажу</DialogTitle></DialogHeader>
        <Input aria-label="Поиск ЭЗС к демонтажу" placeholder="Номер, название или адрес" value={search} onChange={(event) => setSearch(event.target.value)} />
        {catalog.isPending ? <p role="status">Загрузка станций…</p> : catalog.isError ? (
          <div role="alert" className="flex items-center gap-2 text-sm">Не удалось загрузить реестр.
            <Button type="button" variant="outline" onClick={() => void catalog.refetch()}>Повторить</Button>
          </div>
        ) : <div className="min-h-0 overflow-y-auto">
          {filtered.length === 0 ? <p className="text-sm text-muted-foreground">Станции не найдены</p> : (
            <ul className="flex flex-col gap-1">
              {filtered.map((station) => <li key={station.id}>
                <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md p-2 hover:bg-accent">
                  <Checkbox checked={picked.has(station.id)} onCheckedChange={(checked) => setDraft((ids) => checked === true ? [...new Set([...ids, station.id])] : ids.filter((id) => id !== station.id))} />
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
          <Button type="button" disabled={catalog.isPending || catalog.isError} onClick={() => { onChange(draft); setOpen(false) }}>Применить выбор ({draft.length})</Button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
}
