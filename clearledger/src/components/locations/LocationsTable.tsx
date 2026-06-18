/**
 * Табличный режим точек обслуживания — для типов с большим числом точек
 * (например 515 ЭЗС РусГидро). Поиск + фильтры (тип/регион/владелец) +
 * сортировка по столбцам + пагинация. Колонки тянут ключевые поля из metadata.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Search, Trash2, ChevronLeft, ChevronRight, ArrowUpDown, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { deleteLocation } from '@/services/locationService'
import { resolveLocationIcon } from '@/components/locationTypes/locationIcons'
import { LOCATION_STATUS_META, type ServiceLocation } from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'

const PAGE_SIZE = 50

function m(l: ServiceLocation, k: string): string {
  const v = (l.metadata as Record<string, unknown> | undefined)?.[k]
  return v == null ? '' : String(v)
}

// Статус связки HubEx → подпись + цвет бейджа.
const LINK_META: Record<string, { label: string; cls: string }> = {
  ok: { label: 'ok', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  review: { label: 'review', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  conflict: { label: 'conflict', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  no_match: { label: 'no_match', cls: 'bg-muted text-muted-foreground' },
  test: { label: 'test', cls: 'bg-muted text-muted-foreground' },
}

type SortKey = 'number' | 'code' | 'name' | 'region' | 'city' | 'owner' | 'power'

export function LocationsTable({
  locations,
  typeByCode,
  onChanged,
  renderEdit,
}: {
  locations: ServiceLocation[]
  typeByCode: Map<string, LocationTypeDef>
  onChanged: () => void
  /** Триггер редактирования (оборачивает строку в LocationEditDialog из страницы). */
  renderEdit: (location: ServiceLocation, child: ReactNode) => ReactNode
}) {
  const [q, setQ] = useState('')
  const [typeF, setTypeF] = useState('all')
  const [region, setRegion] = useState('all')
  const [owner, setOwner] = useState('all')
  const [link, setLink] = useState('all')
  const [sort, setSort] = useState<SortKey>('name')
  const [asc, setAsc] = useState(true)
  const [page, setPage] = useState(0)

  const regions = useMemo(
    () => Array.from(new Set(locations.map((l) => m(l, 'federalSubject')).filter(Boolean))).sort(),
    [locations],
  )
  const owners = useMemo(
    () => Array.from(new Set(locations.map((l) => m(l, 'ownerTitle')).filter(Boolean))).sort(),
    [locations],
  )
  const typeCodes = useMemo(
    () => Array.from(new Set(locations.map((l) => l.type))),
    [locations],
  )
  const linkStatuses = useMemo(
    () => Array.from(new Set(locations.map((l) => m(l, 'linkStatus')).filter(Boolean))),
    [locations],
  )

  const filtered = useMemo(() => {
    const qq = q.trim().toLowerCase()
    const out = locations.filter((l) => {
      if (typeF !== 'all' && l.type !== typeF) return false
      if (region !== 'all' && m(l, 'federalSubject') !== region) return false
      if (owner !== 'all' && m(l, 'ownerTitle') !== owner) return false
      if (link !== 'all' && m(l, 'linkStatus') !== link) return false
      if (qq) {
        const hay = [
          m(l, 'number'), l.code, l.name, l.address ?? '', m(l, 'cityName'),
          m(l, 'serialNumber'), m(l, 'ownerTitle'),
        ].join(' ').toLowerCase()
        if (!hay.includes(qq)) return false
      }
      return true
    })
    const val = (l: ServiceLocation): string | number => {
      switch (sort) {
        case 'number': return m(l, 'number')
        case 'code': return l.code
        case 'region': return m(l, 'federalSubject')
        case 'city': return m(l, 'cityName')
        case 'owner': return m(l, 'ownerTitle')
        case 'power': return Number(m(l, 'maxPowerKw')) || 0
        default: return l.name
      }
    }
    out.sort((a, b) => {
      const va = val(a), vb = val(b)
      const c = typeof va === 'number' && typeof vb === 'number'
        ? va - vb : String(va).localeCompare(String(vb), 'ru')
      return asc ? c : -c
    })
    return out
  }, [locations, q, typeF, region, owner, link, sort, asc])

  useEffect(() => { setPage(0) }, [q, typeF, region, owner, link])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const cur = Math.min(page, pageCount - 1)
  const slice = filtered.slice(cur * PAGE_SIZE, cur * PAGE_SIZE + PAGE_SIZE)

  function toggleSort(k: SortKey) {
    if (sort === k) setAsc((v) => !v)
    else { setSort(k); setAsc(true) }
  }

  function handleDelete(l: ServiceLocation) {
    if (deleteLocation(l.id)) {
      toast.success(`Удалена точка «${l.name}»`)
      onChanged()
    }
  }

  const SortHead = ({ k, children, className }: { k: SortKey; children: ReactNode; className?: string }) => (
    <TableHead className={className}>
      <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => toggleSort(k)}>
        {children}
        <ArrowUpDown className={`h-3 w-3 ${sort === k ? 'text-foreground' : 'text-muted-foreground/40'}`} />
      </button>
    </TableHead>
  )

  return (
    <div className="space-y-3">
      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: номер, серийник, название, город, владелец…" className="pl-8 h-9" />
        </div>
        {typeCodes.length > 1 && (
          <Select value={typeF} onValueChange={setTypeF}>
            <SelectTrigger className="h-9 w-[180px]"><SelectValue placeholder="Тип" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все типы</SelectItem>
              {typeCodes.map((c) => (
                <SelectItem key={c} value={c}>{typeByCode.get(c)?.name ?? c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {regions.length > 0 && (
          <Select value={region} onValueChange={setRegion}>
            <SelectTrigger className="h-9 w-[170px]"><SelectValue placeholder="Регион" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все регионы</SelectItem>
              {regions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        {owners.length > 1 && (
          <Select value={owner} onValueChange={setOwner}>
            <SelectTrigger className="h-9 w-[170px]"><SelectValue placeholder="Владелец" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все владельцы</SelectItem>
              {owners.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        {linkStatuses.length > 0 && (
          <Select value={link} onValueChange={setLink}>
            <SelectTrigger className="h-9 w-[160px]"><SelectValue placeholder="Связка HubEx" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Связка: все</SelectItem>
              {linkStatuses.map((s) => (
                <SelectItem key={s} value={s}>{LINK_META[s]?.label ?? s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="text-xs text-muted-foreground">
        Найдено: {filtered.length}{filtered.length !== locations.length && ` из ${locations.length}`}
      </div>

      {/* Таблица */}
      <div className="rounded-md border border-border/50">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[40px]"></TableHead>
              <SortHead k="number" className="w-[90px]">Номер</SortHead>
              <SortHead k="code" className="w-[150px]">Серийник</SortHead>
              <SortHead k="name">Название</SortHead>
              <SortHead k="region" className="hidden md:table-cell">Регион</SortHead>
              <SortHead k="city" className="hidden lg:table-cell">Город</SortHead>
              <SortHead k="owner" className="hidden lg:table-cell">Владелец</SortHead>
              <SortHead k="power" className="hidden md:table-cell text-right">кВт</SortHead>
              <TableHead className="hidden xl:table-cell">Связка HubEx</TableHead>
              <TableHead className="hidden sm:table-cell">Статус</TableHead>
              <TableHead className="w-[70px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {slice.map((l) => {
              const Icon = resolveLocationIcon(typeByCode.get(l.type)?.icon)
              const st = LOCATION_STATUS_META[l.status]
              return (
                <TableRow key={l.id}>
                  <TableCell><Icon className="h-4 w-4 text-muted-foreground" /></TableCell>
                  <TableCell className="font-mono text-xs font-medium">{m(l, 'number')}</TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">{l.code}</TableCell>
                  <TableCell className="font-medium">{l.name}</TableCell>
                  <TableCell className="hidden md:table-cell text-muted-foreground">{m(l, 'federalSubject')}</TableCell>
                  <TableCell className="hidden lg:table-cell text-muted-foreground">{m(l, 'cityName')}</TableCell>
                  <TableCell className="hidden lg:table-cell text-muted-foreground">{m(l, 'ownerTitle')}</TableCell>
                  <TableCell className="hidden md:table-cell text-right tabular-nums">{m(l, 'maxPowerKw')}</TableCell>
                  <TableCell className="hidden xl:table-cell">
                    {(() => {
                      const ls = m(l, 'linkStatus'); const aid = m(l, 'hubexAssetId')
                      if (!ls) return null
                      const lm = LINK_META[ls]
                      return (
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant="secondary" className={`text-[10px] ${lm?.cls ?? ''}`}>{lm?.label ?? ls}</Badge>
                          {aid && <span className="text-xs text-muted-foreground tabular-nums">{aid}</span>}
                        </span>
                      )
                    })()}
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    {st && <Badge variant="secondary" className="text-[10px]">{st.label}</Badge>}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-0.5 justify-end">
                      {renderEdit(l, (
                        <Button variant="ghost" size="icon" className="h-7 w-7">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                      ))}
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive">
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Удалить точку «{l.name}»?</AlertDialogTitle>
                            <AlertDialogDescription>Действие необратимо.</AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Отмена</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(l)}>Удалить</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {slice.length === 0 && (
              <TableRow>
                <TableCell colSpan={11} className="text-center text-sm text-muted-foreground py-8">
                  Ничего не найдено по фильтрам.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Пагинация */}
      {pageCount > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Страница {cur + 1} из {pageCount}</span>
          <div className="flex gap-1">
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={cur === 0}
              onClick={() => setPage(cur - 1)}><ChevronLeft className="h-4 w-4" /></Button>
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={cur >= pageCount - 1}
              onClick={() => setPage(cur + 1)}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}
    </div>
  )
}
