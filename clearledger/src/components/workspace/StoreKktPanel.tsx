/**
 * «Магазин» → Касса → Кассовые смены.
 *
 * Фискальная сторона станции. Всё остальное в приложении посчитано нами: по
 * ленте кассы, по документам смен, по пакетам агента. Здесь — единственная
 * цифра, посчитанная не нами: итог, который сам аппарат записал в фискальную
 * память и отдал в ОФД.
 *
 * Две колонки рядом отвечают на вопрос, который иначе задают по телефону:
 * «пробито» — счётчик поста, возвраты он не вычитает; «фискально» — то, что
 * ушло в ОФД, уже за вычетом. Их разница в норме равна возвращённому за смену.
 *
 * Данные: /api/store/kkt — документ kkt_shift из пакета чеков агента.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RadioTower } from 'lucide-react'
import {
  getStoreStations, getStoreKkt,
  type StoreStation, type StoreKktPost,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

function деньги(v: number | undefined | null): string {
  if (v === undefined || v === null) return '—'
  return v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

/** Расхождение счётчика и фискальной памяти — это возвраты, а не ошибка. */
function разница(п: StoreKktPost): number {
  const пробито = п.ПробитоПоСчётчику ?? 0
  const фискально = п.ФискальныйИтог ?? 0
  if (!пробито) return 0
  return Math.round((пробито - фискально) * 100) / 100
}

export function StoreKktPanel() {
  const { company } = useCompany()
  const [станция, выбрать] = useState<number | null>(null)

  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const станции = (парк?.stations ?? []) as StoreStation[]
  useEffect(() => {
    if (станция === null && станции.length > 0) выбрать(станции[0].station_id)
  }, [станция, станции])

  const { data, isLoading } = useQuery({
    queryKey: ['store-kkt', company.id, станция],
    queryFn: () => getStoreKkt(станция as number),
    enabled: станция !== null,
  })

  const посты = data?.posts ?? []
  const итогВсего = посты.reduce((s, п) => s + (п.ФискальныйИтог ?? 0), 0)
  const возвратВсего = посты.reduce((s, п) => s + (п.Возвращено ?? 0), 0)
  const смен = new Set(посты.map((п) => п.Смена)).size

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Кассовые смены</h3>
        <p className="text-xs text-muted-foreground">
          Итог смены пишет сам кассовый аппарат при её закрытии, и он уже за вычетом возвратов —
          это единственная выручка станции, посчитанная не нами. Корпоративные отпуски чеком не
          пробиваются и сюда не попадают: их видно в «Сменах», и это не расхождение.
        </p>
      </div>

      {станции.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {станции.map((s) => (
            <button key={s.station_id} type="button" onClick={() => выбрать(s.station_id)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs tabular-nums ${
                станция === s.station_id
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
              <RadioTower className="h-3.5 w-3.5" />АЗС {s.station_id}
            </button>
          ))}
        </div>
      )}

      {isLoading && <div className="text-xs text-muted-foreground">Читаем итоги станции…</div>}

      {!isLoading && !data?.available && (
        <div className="rounded-lg border border-border/50 bg-card/40 p-4 text-xs text-muted-foreground">
          Фискальных итогов ещё нет. Их присылает агент станции вместе с чеками при закрытии
          смены — смены, снятые прежней версией агента, итогов не содержат.
        </div>
      )}

      {(data?.devices?.length ?? 0) > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {data!.devices.map((d, i) => (
            <div key={d.РНМ ?? i} className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Пост {d.Пост ?? '—'}</div>
              <div className="mt-0.5 text-sm font-semibold">{d.МодельККТ ?? '—'}</div>
              <div className="text-[11px] text-muted-foreground">РНМ {d.РНМ ?? '—'}</div>
              <div className="text-[11px] text-muted-foreground">заводской {d.ЗаводскойНомер ?? '—'}</div>
            </div>
          ))}
        </div>
      )}

      {посты.length > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Смен в выборке</div>
              <div className="mt-0.5 text-xl font-semibold tabular-nums">{смен}</div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Фискальный итог</div>
              <div className="mt-0.5 text-xl font-semibold tabular-nums">{деньги(итогВсего)}</div>
            </div>
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Возвращено покупателям</div>
              <div className={`mt-0.5 text-xl font-semibold tabular-nums ${возвратВсего > 0 ? 'text-amber-400/90' : ''}`}>
                {деньги(возвратВсего)}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Смена</th>
                  <th className="px-3 py-2 text-left font-medium">Закрыта</th>
                  <th className="px-3 py-2 text-right font-medium">Пост</th>
                  <th className="px-3 py-2 text-left font-medium">Оператор</th>
                  <th className="px-3 py-2 text-right font-medium">Смена ККТ</th>
                  <th className="px-3 py-2 text-right font-medium">Чеков</th>
                  <th className="px-3 py-2 text-right font-medium">Наличными</th>
                  <th className="px-3 py-2 text-right font-medium">Картой</th>
                  <th className="px-3 py-2 text-right font-medium">Возвращено</th>
                  <th className="px-3 py-2 text-right font-medium">Пробито</th>
                  <th className="px-3 py-2 text-right font-medium">Фискально</th>
                  <th className="px-3 py-2 text-right font-medium">Разница</th>
                </tr>
              </thead>
              <tbody>
                {посты.map((п, i) => (
                  <tr key={`${п.Смена}-${п.Пост}-${i}`} className="border-t border-border/30">
                    <td className="px-3 py-1.5 tabular-nums">{п.Смена ?? '—'}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{когда(п.Закрытие ?? п.received_at)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{п.Пост ?? '—'}</td>
                    <td className="px-3 py-1.5">{п.Оператор || <span className="text-muted-foreground">—</span>}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{п.НомерСменыККТ ?? '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{п.ЧековВСмене ?? '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{деньги(п.Наличными)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{деньги(п.Картой)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {(п.Возвращено ?? 0) > 0
                        ? <span className="text-amber-400/90">{деньги(п.Возвращено)}</span>
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{деньги(п.ПробитоПоСчётчику)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{деньги(п.ФискальныйИтог)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {разница(п) ? деньги(разница(п)) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            «Пробито» — счётчик поста, он возвраты не вычитает. «Фискально» — то, что ушло в
            фискальную память и в ОФД, уже за вычетом. Поэтому разница между ними в норме равна
            возвращённой сумме, а не нулю.
          </p>
        </>
      )}
    </div>
  )
}
