import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getSiteTrack } from '@/services/sitesService'

export function ProjectEvidencePicker({ companyId, siteId, value, onChange, label = 'Подтверждающая работа' }: {
  companyId: string; siteId: string; value: string; onChange: (value: string) => void; label?: string
}) {
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const records = useQuery({ queryKey: ['site-track', companyId, siteId, 'evidence', search, offset],
    queryFn: () => getSiteTrack(companyId, siteId, { q: search, offset }) })
  const reset = (nextOffset: number) => { setOffset(nextOffset); onChange('') }
  return <div className="space-y-2">
    <Input aria-label={`Поиск: ${label.toLocaleLowerCase('ru')}`} placeholder="Поиск по названию или номеру" value={search} onChange={(e) => { setSearch(e.target.value); reset(0) }} />
    <label className="block space-y-2 text-sm">{label}<select aria-label={label} className="h-10 w-full rounded-md border bg-background px-3" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Выберите поручение или документ проекта</option>{records.data?.items.map((r) => <option key={`${r.kind}:${r.id}`} value={`${r.kind}:${r.id}`}>{r.key} · {r.title} · {r.state_name}</option>)}
    </select></label>
    {records.isPending && <p role="status" className="text-xs text-muted-foreground">Загрузка работы…</p>}
    {records.isError && <Button variant="outline" onClick={() => void records.refetch()}>Не удалось загрузить работу. Повторить</Button>}
    {records.data?.total === 0 && <p className="text-xs text-muted-foreground">Подходящей работы нет.</p>}
    {(records.data?.total ?? 0) > 40 && <div className="flex items-center justify-between text-sm"><Button size="sm" variant="ghost" disabled={!offset} onClick={() => reset(offset - 40)}>Предыдущие</Button><span>{offset + 1}–{Math.min(offset + 40, records.data?.total ?? 0)} из {records.data?.total}</span><Button size="sm" variant="ghost" disabled={offset + 40 >= (records.data?.total ?? 0)} onClick={() => reset(offset + 40)}>Следующие</Button></div>}
  </div>
}
