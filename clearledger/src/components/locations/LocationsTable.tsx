/**
 * Табличный режим точек обслуживания — для типов с большим числом точек
 * (например 515 ЭЗС РусГидро). Принимает УЖЕ отфильтрованный список (отбор/поиск
 * живут на LocationsPage); здесь — сортировка по столбцам + пагинация. Колонки
 * тянут ключевые поля из metadata.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Trash2, ChevronLeft, ChevronRight, ArrowUpDown, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { deleteLocation } from '@/services/locationService'
import { resolveLocationIcon } from '@/components/locationTypes/locationIcons'
import { LOCATION_STATUS_META, type ServiceLocation } from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'
import { m } from './fleet/locationFleetService'
import { useAllSettlements } from '@/hooks/useReferences'
import {
  stationFlag, paidThroughLabel, ROLE_LABEL,
  type StationFlag, type StationSettlement,
} from '@/types/settlement'

const PAGE_SIZE = 50

// Статус связки HubEx → подпись + цвет бейджа.
const LINK_META: Record<string, { label: string; cls: string }> = {
  ok: { label: 'ok', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  review: { label: 'review', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  conflict: { label: 'conflict', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  no_match: { label: 'no_match', cls: 'bg-muted text-muted-foreground' },
  test: { label: 'test', cls: 'bg-muted text-muted-foreground' },
}

// Операционный статус станции → подпись + цвет (отдельно от жизненного статуса).
const OP_STATUS_META: Record<string, { label: string; cls: string }> = {
  working: { label: 'Работает', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  not_working: { label: 'Не работает', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  on_repair: { label: 'На ремонте', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  maintenance: { label: 'Обслуживание', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  unknown: { label: '—', cls: 'bg-muted text-muted-foreground' },
}

// Сводный индикатор платёжной дисциплины станции (реестр «Договоры и оплаты ЭЗС», energy).
const FLAG_META: Record<StationFlag, { label: string; cls: string; dot: string }> = {
  ok:        { label: 'оплачено',   cls: 'text-emerald-600 dark:text-emerald-400', dot: 'bg-emerald-500' },
  attention: { label: 'внимание',    cls: 'text-amber-600 dark:text-amber-400',     dot: 'bg-amber-500' },
  unpaid:    { label: 'не оплачено', cls: 'text-red-600 dark:text-red-400',         dot: 'bg-red-500' },
  none:      { label: '—',           cls: 'text-muted-foreground',                  dot: 'bg-muted-foreground/30' },
}

type SortKey = 'number' | 'name' | 'region' | 'city' | 'brand' | 'power'

export function LocationsTable({
  locations,
  typeByCode,
  onChanged,
  renderEdit,
  onSelectLocation,
}: {
  /** Уже отфильтрованный список точек (отбор — на LocationsPage). */
  locations: ServiceLocation[]
  typeByCode: Map<string, LocationTypeDef>
  onChanged: () => void
  /** Триггер редактирования (оборачивает строку в LocationEditDialog из страницы). */
  renderEdit: (location: ServiceLocation, child: ReactNode) => ReactNode
  /** Клик по строке → открыть окно станции (cockpit). */
  onSelectLocation?: (location: ServiceLocation) => void
}) {
  const [sort, setSort] = useState<SortKey>('name')
  const [asc, setAsc] = useState(true)
  const [page, setPage] = useState(0)

  // Колонка «Реализация, пред. мес.» показывается, только если хотя бы у одной
  // точки выборки есть это значение (для ЭЗС/энергетики данных нет → скрыта).
  const showSales = useMemo(() => locations.some((l) => m(l, 'salesPrevMonth')), [locations])

  // Индикатор платёжной дисциплины (реестр «Договоры и оплаты ЭЗС», energy/РусГидро):
  // тянем все settlement компании, группируем по точке, флаг — через stationFlag().
  // Колонка появляется только если в компании есть данные реестра (для fuel/ГИГ — скрыта).
  const { data: settlements } = useAllSettlements()
  const settleByLoc = useMemo(() => {
    const map = new Map<string, StationSettlement[]>()
    for (const s of settlements ?? []) {
      const arr = map.get(s.locationId)
      if (arr) arr.push(s); else map.set(s.locationId, [s])
    }
    return map
  }, [settlements])
  const showPayment = (settlements?.length ?? 0) > 0

  const sorted = useMemo(() => {
    const val = (l: ServiceLocation): string | number => {
      switch (sort) {
        case 'number': return m(l, 'number')
        case 'region': return m(l, 'federalSubject')
        case 'city': return m(l, 'cityName')
        case 'brand': return m(l, 'manufacturer')
        case 'power': return Number(m(l, 'maxPowerKw')) || 0
        default: return l.name
      }
    }
    return [...locations].sort((a, b) => {
      const va = val(a), vb = val(b)
      const c = typeof va === 'number' && typeof vb === 'number'
        ? va - vb : String(va).localeCompare(String(vb), 'ru')
      return asc ? c : -c
    })
  }, [locations, sort, asc])

  // Новая выборка (фильтры изменились) → вернуться на первую страницу.
  useEffect(() => { setPage(0) }, [locations])

  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const cur = Math.min(page, pageCount - 1)
  const slice = sorted.slice(cur * PAGE_SIZE, cur * PAGE_SIZE + PAGE_SIZE)

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
      <div className="rounded-md border border-border/50">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[40px]"></TableHead>
              <SortHead k="number" className="w-[90px]">Номер</SortHead>
              <SortHead k="name">Название</SortHead>
              <SortHead k="region" className="hidden md:table-cell">Регион</SortHead>
              <SortHead k="city" className="hidden lg:table-cell">Город</SortHead>
              <SortHead k="brand" className="hidden lg:table-cell">Бренд</SortHead>
              <TableHead className="hidden xl:table-cell">Коннекторы</TableHead>
              <SortHead k="power" className="hidden md:table-cell text-right">кВт</SortHead>
              <TableHead>Статус станции</TableHead>
              {showPayment && <TableHead className="hidden md:table-cell">Оплата</TableHead>}
              {showSales && <TableHead className="hidden lg:table-cell text-right">Реализация, пред. мес.</TableHead>}
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
                <TableRow key={l.id}
                  className={onSelectLocation ? 'cursor-pointer hover:bg-secondary/50' : undefined}
                  onClick={onSelectLocation ? () => onSelectLocation(l) : undefined}>
                  <TableCell><Icon className="h-4 w-4 text-muted-foreground" /></TableCell>
                  <TableCell className="font-mono text-xs font-medium">{m(l, 'number')}</TableCell>
                  <TableCell className="font-medium">{l.name}</TableCell>
                  <TableCell className="hidden md:table-cell text-muted-foreground">{m(l, 'federalSubject')}</TableCell>
                  <TableCell className="hidden lg:table-cell text-muted-foreground">{m(l, 'cityName')}</TableCell>
                  <TableCell className="hidden lg:table-cell text-muted-foreground">{m(l, 'manufacturer') || '—'}</TableCell>
                  <TableCell className="hidden xl:table-cell text-xs text-muted-foreground tabular-nums">{m(l, 'connectorTypes') || '—'}</TableCell>
                  <TableCell className="hidden md:table-cell text-right tabular-nums">{m(l, 'maxPowerKw')}</TableCell>
                  <TableCell>
                    {(() => {
                      const om = OP_STATUS_META[l.operationalStatus || 'unknown'] ?? OP_STATUS_META.unknown
                      return <Badge variant="secondary" className={`text-[10px] ${om.cls}`}>{om.label}</Badge>
                    })()}
                  </TableCell>
                  {showPayment && (
                    <TableCell className="hidden md:table-cell">
                      {(() => {
                        const ss = settleByLoc.get(l.id) ?? []
                        const fm = FLAG_META[stationFlag(ss)]
                        const title = ss.length
                          ? ss.map((s) => `${ROLE_LABEL[s.role]}: ${paidThroughLabel(s)}${s.comment ? ` — ${s.comment}` : ''}`).join('\n')
                          : 'нет данных реестра'
                        return (
                          <span className="inline-flex items-center gap-1.5" title={title}>
                            <span className={`h-2 w-2 rounded-full ${fm.dot}`} />
                            <span className={`text-[10px] ${fm.cls}`}>{fm.label}</span>
                          </span>
                        )
                      })()}
                    </TableCell>
                  )}
                  {showSales && (
                    <TableCell className="hidden lg:table-cell text-right tabular-nums text-muted-foreground">
                      {m(l, 'salesPrevMonth') || '—'}
                    </TableCell>
                  )}
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
                    <div className="flex gap-0.5 justify-end" onClick={(e) => e.stopPropagation()}>
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
                <TableCell colSpan={12 + (showPayment ? 1 : 0) + (showSales ? 1 : 0)} className="text-center text-sm text-muted-foreground py-8">
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
