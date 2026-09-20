/**
 * «Полнота паспортов» — чего не хватает объектам реестра.
 *
 * Пустая графа в карточке выглядит мелочью, пока не окажется, что по этой
 * станции нельзя ни на карту поставить, ни претензию написать, ни свести
 * сессии. Разрез считает пробелы по всему реестру сразу и даёт список: не
 * «данные грязные», а «вот эти 84 станции без координат».
 *
 * Считается на клиенте по уже загруженному справочнику: реестр и так в памяти
 * (его показывает соседний пункт меню), и гонять его на сервер ради подсчёта
 * пустых полей незачем.
 */
import { useMemo, useState } from 'react'
import { AlertTriangle, Check } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { locationValues, type ServiceLocation } from '@/types/location'

const nf = new Intl.NumberFormat('ru-RU')

interface Проверка {
  key: string
  label: string
  hint: string
  плохо: (l: ServiceLocation, v: Record<string, unknown>) => boolean
}

const ПРОВЕРКИ: Проверка[] = [
  {
    key: 'coords', label: 'Нет координат',
    hint: 'объект не встанет на карту и не попадёт в расчёт по районам',
    плохо: (_l, v) => v.latitude == null || v.longitude == null,
  },
  {
    key: 'number', label: 'Нет номера станции',
    hint: 'по номеру сходятся выгрузки заказчика и наши сессии',
    плохо: (_l, v) => !v.stationNumber && !v.number,
  },
  {
    key: 'serial', label: 'Нет заводского номера',
    hint: 'ключ сопоставления по СТО: без него станцию не отличить от однофамильца',
    плохо: (l) => !l.code && !(l.passport as Record<string, unknown> | undefined)?.serialNumber,
  },
  {
    key: 'brand', label: 'Не указан производитель',
    hint: 'разрез по маркам и претензионная работа считаются по нему',
    плохо: (_l, v) => !v.brand && !v.manufacturer,
  },
  {
    key: 'power', label: 'Нет мощности',
    hint: 'без неё станция не делится на быструю и медленную',
    плохо: (_l, v) => v.maxPowerKw == null && v.powerKwt == null,
  },
  {
    key: 'binding', label: 'Нет привязки к источнику',
    hint: 'данные по объекту не приедут сами — ни сессии, ни смены',
    плохо: (l) => (l.sourceBindings?.length ?? 0) === 0,
  },
  {
    key: 'address', label: 'Нет адреса',
    hint: 'выезд бригады и договор аренды опираются на адрес',
    плохо: (l) => !l.address || l.address.trim().length < 5,
  },
]

export function LocationsQuality({ locations, onOpen }: {
  locations: ServiceLocation[]
  onOpen?: (l: ServiceLocation) => void
}) {
  const [выбрана, setВыбрана] = useState<string | null>(null)
  const [поиск, setПоиск] = useState('')

  const итоги = useMemo(() => ПРОВЕРКИ.map((p) => {
    const строки = locations.filter((l) => p.плохо(l, locationValues(l) as Record<string, unknown>))
    return { ...p, count: строки.length, rows: строки }
  }), [locations])

  const активная = итоги.find((i) => i.key === выбрана)
  const строки = useMemo(() => {
    const все = активная?.rows ?? []
    const т = поиск.trim().toLowerCase()
    if (!т) return все
    return все.filter((l) => [l.name, l.code, l.address]
      .some((v) => (v ?? '').toLowerCase().includes(т)))
  }, [активная, поиск])

  const всего = locations.length
  const чистых = locations.filter(
    (l) => !ПРОВЕРКИ.some((p) => p.плохо(l, locationValues(l) as Record<string, unknown>))).length

  return (
    <div className="space-y-4 px-4 py-4 sm:px-6 sm:py-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Полнота паспортов</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Объектов в реестре {nf.format(всего)}, заполнены полностью {nf.format(чистых)}.
          Нажмите на проверку, чтобы увидеть список.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {итоги.map((i) => (
          <button key={i.key} type="button"
            onClick={() => setВыбрана(выбрана === i.key ? null : i.key)}
            className={cn(
              'rounded-lg border bg-card px-3 py-2.5 text-left transition-colors',
              выбрана === i.key ? 'border-primary ring-1 ring-primary/40' : 'border-border/60',
              i.count === 0 && 'opacity-60')}>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {i.count === 0
                ? <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                : <AlertTriangle className="size-3.5 text-amber-600 dark:text-amber-400" />}
              {i.label}
            </div>
            <div className={cn('mt-0.5 text-lg font-semibold tabular-nums',
              i.count > 0 && 'text-amber-600 dark:text-amber-400')}>
              {nf.format(i.count)}
            </div>
            <div className="text-xs text-muted-foreground">{i.hint}</div>
          </button>
        ))}
      </div>

      {активная && (
        <Card>
          <CardContent className="space-y-2 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-sm font-medium">{активная.label}</div>
              <Input value={поиск} onChange={(e) => setПоиск(e.target.value)}
                placeholder="Название, код, адрес…" className="h-7 w-56 text-xs" />
              <span className="text-xs text-muted-foreground">
                строк: {nf.format(строки.length)}
              </span>
              <Button size="sm" variant="ghost" className="ml-auto h-7 text-xs"
                onClick={() => setВыбрана(null)}>Свернуть</Button>
            </div>
            <div className="max-h-[420px] overflow-auto rounded-md border border-border/40">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="p-2 text-left font-medium">Код</th>
                    <th className="p-2 text-left font-medium">Объект</th>
                    <th className="p-2 text-left font-medium">Адрес</th>
                  </tr>
                </thead>
                <tbody>
                  {строки.slice(0, 300).map((l) => (
                    <tr key={l.id}
                      className={cn('border-b border-border/40',
                        onOpen && 'cursor-pointer hover:bg-accent/30')}
                      onClick={() => onOpen?.(l)}>
                      <td className="p-2 font-mono text-xs text-muted-foreground">{l.code}</td>
                      <td className="p-2 font-medium">{l.name}</td>
                      <td className="p-2 text-xs text-muted-foreground">{l.address || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {строки.length > 300 && (
                <p className="p-2 text-center text-xs text-muted-foreground">
                  показаны первые 300 из {nf.format(строки.length)}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
