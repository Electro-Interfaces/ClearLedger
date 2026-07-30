/**
 * Резервуары: паспорт вместимости и состояние уровнемеров.
 *
 * Отдельный пункт «Товародвижения», а не вкладка баланса: это про оборудование, и
 * стоит он первым — паспорт и исправность приборов есть основание, на котором
 * считаются баланс, расхождения и ведомость. Пока прибор врёт, расхождение по
 * резервуару не измерено, и разбирать литры нечем.
 *
 * Зачем экран: пока вместимость неизвестна, граница достоверности замера оценивается
 * по книге — а книга на части станций сама завышена, и невозможное показание
 * проходит проверку. Паспорт снимает эту зависимость.
 *
 * Вместимость приходит из самого STS (`/v1/tanks`, поле `volume_max` — то же, что
 * «Ёмкость» в «Мониторе»), поэтому основной путь — кнопка синхронизации, а не ручной
 * ввод. Ручное значение остаётся сильнее источника: его вводят именно тогда, когда
 * источнику по этому резервуару не поверили.
 *
 * Рядом с паспортом показаны оценка по книге и наибольшее показание прибора: по ним
 * видно, где прибор врёт и где книга завышена.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Loader2, RefreshCw, Save } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { GoodsRouteBar } from './GoodsRouteBar'
import {
  getTankSpecs, saveTankSpecs, syncTankSpecsFromSts, type TankSpecRow,
} from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

const SOURCE_META: Record<string, { label: string; cls: string }> = {
  sts: { label: 'из STS', cls: 'border-emerald-500/40 text-emerald-500' },
  manual: { label: 'вручную', cls: 'border-primary/50 text-primary' },
  estimate: { label: 'оценка по книге', cls: 'border-amber-500/40 text-amber-500' },
}

export function TankSpecsPanel({ companyId, stationCodes, standalone }: {
  companyId: string
  stationCodes: number[]
  /** Отдельным пунктом — рисуем маршрут раздела и заголовок сами. */
  standalone?: boolean
}) {
  const qc = useQueryClient()
  /** Правки до сохранения: ключ «код АЗС:резервуар» → введённая вместимость. */
  const [edits, setEdits] = useState<Record<string, string>>({})

  const query = useQuery({
    queryKey: ['tank-specs', companyId],
    queryFn: () => getTankSpecs(),
  })

  const syncMut = useMutation({
    mutationFn: syncTankSpecsFromSts,
    onSuccess: (r) => {
      toast.success(`Вместимость получена из STS: ${r.updated} резервуаров`,
        { description: r.warning ?? (r.skipped ? `${r.skipped} без данных уровнемера` : undefined) })
      qc.invalidateQueries({ queryKey: ['tank-specs'] })
      qc.invalidateQueries({ queryKey: ['tank-ledger'] })
      qc.invalidateQueries({ queryKey: ['tank-ledger-one'] })
    },
    onError: (e) => toast.error('Не удалось получить вместимость из STS',
      { description: e instanceof Error ? e.message : undefined }),
  })

  const saveMut = useMutation({
    mutationFn: (rows: Parameters<typeof saveTankSpecs>[0]) => saveTankSpecs(rows),
    onSuccess: (r) => {
      toast.success(`Паспорт сохранён: ${r.saved} резервуаров`)
      setEdits({})
      qc.invalidateQueries({ queryKey: ['tank-specs'] })
      qc.invalidateQueries({ queryKey: ['tank-ledger'] })
      qc.invalidateQueries({ queryKey: ['tank-ledger-one'] })
    },
    onError: () => toast.error('Не удалось сохранить паспорт'),
  })

  const rows = useMemo(() => {
    const all = query.data?.rows ?? []
    return stationCodes.length ? all.filter((r) => stationCodes.includes(r.station_code)) : all
  }, [query.data, stationCodes])

  const key = (r: TankSpecRow) => `${r.station_code}:${r.tank_number}`
  const dirty = Object.keys(edits).length > 0

  const save = () => {
    const byKey = new Map(rows.map((r) => [key(r), r]))
    const payload = Object.entries(edits).flatMap(([k, v]) => {
      const r = byKey.get(k)
      const num = Number(v.replace(/\s/g, '').replace(',', '.'))
      if (!r || !Number.isFinite(num) || num <= 0) return []
      return [{
        station_id: r.station_id, tank_number: r.tank_number, fuel_name: r.fuel_name,
        nominal_liters: num, usable_liters: num, note: 'введено вручную по паспорту резервуара',
      }]
    })
    if (payload.length === 0) {
      toast.warning('Нечего сохранять: вместимость должна быть числом больше нуля')
      return
    }
    saveMut.mutate(payload)
  }

  const noSpec = rows.filter((r) => !r.usable_liters || r.source === 'estimate').length
  /** Прибор врёт: отдавал больше вместимости или свой предел вместо измерения. */
  const isBroken = (r: TankSpecRow) => r.fact_max > r.fact_limit || r.at_limit > 0
  const broken = useMemo(() => rows.filter(isBroken)
    .sort((a, b) => b.at_limit - a.at_limit), [rows])
  // Сбойные приборы наверх: это работа, которую надо сделать, а не справка.
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const d = Number(isBroken(b)) - Number(isBroken(a))
    return d !== 0 ? d : a.station_code - b.station_code || a.tank_number - b.tank_number
  }), [rows])

  return (
    <div className={cn('space-y-3', standalone && 'p-4')}>
      {standalone && (
        <>
          <GoodsRouteBar
            current="tank-specs"
            counters={{
              'tank-specs': broken.length
                ? { value: broken.length, unit: 'сбой', alarm: true }
                : { value: rows.length, unit: 'рез.' },
            }}
          />
          <div>
            <h2 className="text-base font-semibold">Резервуары и уровнемеры</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Паспортная вместимость и состояние приборов. По этим цифрам отбраковываются
              невозможные показания в контроле баланса и в ведомости инвентаризации.
            </p>
          </div>
        </>
      )}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
        <Button size="sm" className="h-8" onClick={() => syncMut.mutate()} disabled={syncMut.isPending}>
          {syncMut.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
          Получить из STS
        </Button>
        <Button variant="outline" size="sm" className="h-8" onClick={save} disabled={!dirty || saveMut.isPending}>
          {saveMut.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            : <Save className="mr-1.5 h-3.5 w-3.5" />}
          Сохранить{dirty ? ` (${Object.keys(edits).length})` : ''}
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Вместимость приходит из STS (<span className="font-mono">/v1/tanks · volume_max</span>) —
          это та же «Ёмкость», что в «Мониторе». Ручное значение сильнее: его вводят,
          когда прибор врёт и про свою ёмкость тоже.
        </p>
        {noSpec > 0 && (
          <span className="ml-auto flex items-center gap-1.5 text-[11px] text-amber-500">
            <AlertTriangle className="h-3.5 w-3.5" />
            {noSpec} резервуаров без паспорта — граница считается по книге
          </span>
        )}
      </div>

      {/* Список приборов, которым нельзя верить. Это не украшение: пока прибор врёт,
          расхождение по резервуару не измерено, и ни разбор, ни инвентаризация по
          нему невозможны — резервуар надо мерить вручную. */}
      {broken.length > 0 && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5">
          <div className="flex flex-wrap items-center gap-2 border-b border-red-500/20 px-3 py-2">
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <span className="text-sm font-semibold text-red-500">
              Уровнемер врёт: {broken.length} резервуар(ов)
            </span>
            <span className="text-[11px] text-muted-foreground">
              показания в расчёт расхождения не берутся и в ведомость инвентаризации не попадают
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium">АЗС</th>
                  <th className="px-3 py-1.5 text-left font-medium">Рез.</th>
                  <th className="px-3 py-1.5 text-left font-medium">Топливо</th>
                  <th className="px-3 py-1.5 text-right font-medium">Вместимость</th>
                  <th className="px-3 py-1.5 text-right font-medium">Максимум прибора</th>
                  <th className="px-3 py-1.5 text-right font-medium">Испорчено показаний</th>
                  <th className="px-3 py-1.5 text-left font-medium">Что с прибором</th>
                </tr>
              </thead>
              <tbody>
                {broken.map((r) => (
                  <tr key={`b-${key(r)}`} className="border-t border-red-500/15">
                    <td className="px-3 py-1.5 font-medium">{r.station_name}</td>
                    <td className="px-3 py-1.5">№{r.tank_number}</td>
                    <td className="px-3 py-1.5">{r.fuel_name}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {r.usable_liters ? `${nf0.format(r.usable_liters)} л` : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-medium tabular-nums text-red-500">
                      {nf0.format(r.fact_max)} л
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {r.at_limit > 0 ? (
                        <span className="text-red-500">
                          {r.at_limit} из {r.measured}
                          <span className="ml-1 text-[10px] text-muted-foreground">
                            ({Math.round((r.at_limit / Math.max(r.measured, 1)) * 100)}%)
                          </span>
                        </span>
                      ) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                      {r.at_limit > 0
                        ? 'отдаёт предел шкалы вместо измерения — поверка уровнемера'
                        : 'показывал больше, чем входит в резервуар — поверка уровнемера'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {query.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Загрузка паспорта…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          В контуре нет резервуаров со сменными данными
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[1000px] text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">АЗС</th>
                  <th className="px-3 py-2 text-left font-medium">Рез.</th>
                  <th className="px-3 py-2 text-left font-medium">Топливо</th>
                  <th className="px-3 py-2 text-right font-medium">Вместимость, л</th>
                  <th className="px-3 py-2 text-left font-medium">Источник</th>
                  <th className="px-3 py-2 text-right font-medium" title="Наибольший книжный остаток за историю резервуара">
                    Максимум по книге
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="Наибольшее показание уровнемера за историю">
                    Максимум прибора
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="Показание выше этой границы считается невозможным">
                    Граница замера
                  </th>
                  <th className="px-3 py-2 text-left font-medium">Состояние</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => {
                  const k = key(r)
                  const bad = isBroken(r)
                  const src = r.source ? SOURCE_META[r.source] : null
                  return (
                    <tr key={k} className={cn('border-t', bad && 'bg-red-500/5')}>
                      <td className="px-3 py-1.5">{r.station_name}</td>
                      <td className="px-3 py-1.5">№{r.tank_number}</td>
                      <td className="px-3 py-1.5">{r.fuel_name}</td>
                      <td className="px-3 py-1.5 text-right">
                        <Input
                          value={edits[k] ?? (r.usable_liters ? nf0.format(r.usable_liters) : '')}
                          onChange={(e) => setEdits((p) => ({ ...p, [k]: e.target.value }))}
                          placeholder={nf0.format(r.book_max)}
                          className="h-7 w-28 text-right text-xs tabular-nums"
                          aria-label={`Вместимость резервуара №${r.tank_number} на ${r.station_name}`}
                        />
                      </td>
                      <td className="px-3 py-1.5">
                        {edits[k] != null ? (
                          <Badge variant="outline" className="border-primary/50 text-primary">не сохранено</Badge>
                        ) : src ? (
                          <Badge variant="outline" className={src.cls}>{src.label}</Badge>
                        ) : <span className="text-muted-foreground">нет паспорта</span>}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {nf0.format(r.book_max)}
                      </td>
                      <td className={cn('px-3 py-1.5 text-right tabular-nums',
                        bad ? 'font-medium text-red-500' : 'text-muted-foreground')}>
                        {nf0.format(r.fact_max)}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {nf0.format(r.fact_limit)}
                      </td>
                      <td className="px-3 py-1.5 text-[11px]">
                        {bad ? (
                          <span className="text-red-500">
                            {r.at_limit > 0
                              ? `прибор ${r.at_limit} раз отдал предел шкалы`
                              : 'прибор давал больше вместимости'}
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-emerald-500">
                            <Check className="h-3 w-3" />показания в пределах
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-muted-foreground">
            «Граница замера» — вместимость с запасом {((query.data?.sanity_ratio ?? 1.15) * 100 - 100).toFixed(0)}%
            на погрешность и заполнение до горловины. Показание выше неё в расчёт расхождения
            не берётся и в ведомость инвентаризации не попадает: это поломка прибора, а не топливо.
            {broken.length > 0 && ` Сейчас приборов с явным сбоем: ${broken.length}.`}
          </p>
        </>
      )}
    </div>
  )
}
