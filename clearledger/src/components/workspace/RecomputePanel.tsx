import { useEffect, useState } from 'react'
import { CheckCircle2, FileCheck2, LoaderCircle, Lock, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  getStoreRecompute, rebuildStoreDocuments, type StoreRecomputeStatus,
} from '@/services/storeDocumentsService'

const fmt = (value: string | null) =>
  value ? new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : '—'

const money = (n: number) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n) + ' ₽'

const месяц = (freeze: string | null) => {
  if (!freeze) return null
  const [y, m] = freeze.split('-')
  const имена = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
  return `${имена[Number(m)] ?? m} ${y}`
}

/**
 * Пересчёт документов (центр) — мониторинг + пересборка. Показывает по сети,
 * какие смены ждут пересборки представления: станция прислала новый пакет уже
 * ПОСЛЕ сборки реестра (документ задним числом), поэтому себестоимость и остаток
 * в центре устарели. Кнопка «Пересобрать реестр» подтягивает свежий пересчёт
 * агента станции. Полный пересчёт себестоимости делает агент — не центр.
 */
export function RecomputePanel({ stations, heading }: {
  stations: string[]
  heading?: { title: string; subtitle: string }
}) {
  const [data, setData] = useState<StoreRecomputeStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [error, setError] = useState('')

  const load = () => {
    let живо = true
    setLoading(true); setError('')
    getStoreRecompute(stations)
      .then((d) => { if (живо) setData(d) })
      .catch((e) => { if (живо) setError(e instanceof Error ? e.message : 'Не загрузилось') })
      .finally(() => { if (живо) setLoading(false) })
    return () => { живо = false }
  }
  useEffect(load, [stations.join(',')])

  const пересобрать = async () => {
    setRebuilding(true); setError('')
    try {
      await rebuildStoreDocuments()
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Пересборка не удалась')
    } finally {
      setRebuilding(false)
    }
  }

  const ждут = data?.waiting ?? []

  return (
    <div className="p-4 sm:p-5">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <RefreshCw className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">{heading?.title ?? 'Пересчёт документов'}</h2>
            <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
              {heading?.subtitle ?? 'Документ задним числом меняет то, что уже посчитано. Здесь видно, какие смены сети ждут пересборки и что закрыто датой запрета.'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="default" size="sm" onClick={() => void пересобрать()} disabled={rebuilding || loading}>
            {rebuilding ? <LoaderCircle data-icon className="animate-spin" /> : <FileCheck2 data-icon />}
            Пересобрать реестр
          </Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw data-icon className={loading ? 'animate-spin' : ''} />Обновить
          </Button>
        </div>
      </header>

      {error && <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}

      {/* Итоговые метки: когда собран реестр и до какого месяца закрыто */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">Реестр собран</div>
          <div className="mt-1 font-medium tabular-nums">{fmt(data?.rebuilt_at ?? null)}</div>
        </div>
        <div className="rounded-lg border p-3">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><Lock className="size-3" />Дата запрета</div>
          <div className="mt-1 font-medium">
            {месяц(data?.freeze_period ?? null) ?? <span className="text-muted-foreground">не задана</span>}
          </div>
        </div>
        <div className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">Смен в охвате</div>
          <div className="mt-1 font-medium tabular-nums">{data?.shifts_total ?? '—'}</div>
        </div>
      </div>

      {loading && !data ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Проверяю, что ждёт пересборки…
        </div>
      ) : ждут.length === 0 ? (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4">
          <CheckCircle2 className="size-6 shrink-0 text-emerald-500" aria-hidden="true" />
          <div>
            <div className="font-medium text-emerald-600 dark:text-emerald-400">Всё пересобрано</div>
            <div className="text-sm text-muted-foreground">Смен, где данные изменились после сборки реестра, нет — себестоимость и остатки актуальны.</div>
          </div>
        </div>
      ) : (
        <section>
          <h3 className="mb-2 text-sm font-medium">Ждут пересборки · {ждут.length}</h3>
          <p className="mb-3 text-xs text-muted-foreground">
            По этим сменам станция прислала новый пакет уже после сборки реестра — документ пришёл или изменился задним числом. Нажмите «Пересобрать реестр», чтобы себестоимость встала на место.
          </p>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="p-2 text-left font-medium">Смена</th>
                  <th className="p-2 text-left font-medium">АЗС</th>
                  <th className="p-2 text-left font-medium">Закрыта</th>
                  <th className="p-2 text-right font-medium">Докум.</th>
                  <th className="p-2 text-right font-medium">Сумма</th>
                  <th className="p-2 text-left font-medium">Данные пришли</th>
                </tr>
              </thead>
              <tbody>
                {ждут.map((с) => (
                  <tr key={`${с.station_id}-${с.shift_no}`} className="border-b last:border-0">
                    <td className="p-2 font-medium">№ {с.shift_no}</td>
                    <td className="p-2 text-muted-foreground">{с.station_id}</td>
                    <td className="p-2 tabular-nums text-muted-foreground">{fmt(с.closed_at)}</td>
                    <td className="p-2 text-right tabular-nums">{с.documents}</td>
                    <td className="p-2 text-right tabular-nums">{money(с.amount)}</td>
                    <td className="p-2 tabular-nums text-amber-600 dark:text-amber-400">{fmt(с.arrived_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
