/**
 * «Магазин» → Маркировка → Коды на остатке.
 *
 * Поэкземплярный учёт: какими кодами мы владеем, откуда каждый пришёл и куда
 * ушёл. Это наша сторона правды — то, что предъявляется, если ГИС МТ скажет,
 * что код всё ещё числится за нами.
 *
 * Продажи здесь нет намеренно: выбытие продажей закрывает касса через ОФД, и
 * заявить его второй раз означало бы вывести код из оборота дважды.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X, Barcode } from 'lucide-react'
import {
  getStoreMarkCodes, getStoreStations,
  type StoreMarkCode, type StoreStation,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

const ВЫБЫТИЕ: Record<string, string> = {
  writeoff: 'списание',
  return_supplier: 'возврат поставщику',
  transfer: 'перемещение',
  production_release: 'производство',
}

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU',
    { day: '2-digit', month: '2-digit', year: '2-digit' })
}

/** Код длинный и нечитаемый целиком: показываем GTIN и хвост серийника. */
function коротко(код: string): string {
  if (код.length <= 24) return код
  return `${код.slice(0, 18)}…${код.slice(-4)}`
}

export function StoreMarkCodesPanel() {
  const { company } = useCompany()
  const [запрос, задатьЗапрос] = useState('')
  const [статус, задатьСтатус] = useState<string | null>(null)
  const [станция, выбрать] = useState<number | null>(null)

  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const станции = (парк?.stations ?? []) as StoreStation[]

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-mark-codes', company.id, станция, статус, запрос],
    queryFn: () => getStoreMarkCodes({ stationId: станция, status: статус ?? undefined, q: запрос }),
  })

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Коды на остатке</h3>
        <p className="text-xs text-muted-foreground">
          Какими кодами маркировки мы владеем: откуда пришёл каждый и куда ушёл. Приход — сканы
          DataMatrix и коды из УПД, выбытие — списания, возвраты, перемещения, производство.
          Продажи здесь нет: её закрывает касса через ОФД, и второй раз код выводить нельзя.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input value={запрос} onChange={(e) => задатьЗапрос(e.target.value)}
            placeholder="Код, GTIN или товар" aria-label="Поиск по кодам маркировки"
            className="h-8 w-full rounded-md border border-border/60 bg-background/60 pl-8 pr-8 text-xs outline-none placeholder:text-muted-foreground/70 focus:border-primary/60" />
          {запрос && (
            <button type="button" onClick={() => задатьЗапрос('')} aria-label="Очистить поиск"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {(['в обороте', 'выбыл'] as const).map((с) => (
          <button key={с} type="button" onClick={() => задатьСтатус(статус === с ? null : с)}
            aria-pressed={статус === с}
            className={`rounded-full border px-2.5 py-0.5 text-[11px] ${статус === с
              ? 'border-primary/60 bg-primary/15 text-foreground'
              : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
            {с} <span className="tabular-nums opacity-70">{data?.by_status?.[с] ?? 0}</span>
          </button>
        ))}

        {станции.length > 1 && станции.map((s) => (
          <button key={s.station_id} type="button"
            onClick={() => выбрать(станция === s.station_id ? null : s.station_id)}
            className={`rounded-md border px-2 py-1 text-xs tabular-nums ${станция === s.station_id
              ? 'border-primary/60 bg-primary/10 text-foreground'
              : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
            АЗС {s.station_id}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Собираем коды…</div>
      ) : error ? (
        <div className="text-sm text-red-400/90">Не удалось получить реестр кодов</div>
      ) : !data || data.codes.length === 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-dashed border-border/50 p-5">
          <Barcode className="mt-0.5 h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm">Кодов пока нет</div>
            <div className="text-xs text-muted-foreground">
              Коды появляются здесь из приёмок: станция сканирует DataMatrix при поступлении, и
              они уезжают в центр вместе с документом. Пока маркированное принимают без
              сканирования, поэкземплярного учёта у нас не будет — только у государства.
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Код</th>
                  <th className="px-3 py-2 text-left font-medium">GTIN</th>
                  <th className="px-3 py-2 text-left font-medium">Товар</th>
                  <th className="px-3 py-2 text-left font-medium">АЗС</th>
                  <th className="px-3 py-2 text-left font-medium">Пришёл</th>
                  <th className="px-3 py-2 text-left font-medium">Откуда</th>
                  <th className="px-3 py-2 text-left font-medium">Статус</th>
                  <th className="px-3 py-2 text-left font-medium">Ушёл</th>
                </tr>
              </thead>
              <tbody>
                {data.codes.map((c: StoreMarkCode) => (
                  <tr key={c.код} className="border-t border-border/30">
                    <td className="px-3 py-1.5 font-mono text-[11px]" title={c.код}>{коротко(c.код)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.gtin ?? '—'}</td>
                    <td className="max-w-[280px] truncate px-3 py-1.5" title={c.name ?? ''}>{c.name ?? '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.station_id ?? '—'}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">
                      {когда(c.received_at)}
                      {c.receipt_doc && <span className="ml-1.5 text-[10px]">№ {c.receipt_doc}</span>}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground">{c.источник}</td>
                    <td className={`px-3 py-1.5 ${c.status === 'выбыл' ? 'text-muted-foreground' : 'text-emerald-400/90'}`}>
                      {c.status}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground">
                      {c.gone_at
                        ? `${ВЫБЫТИЕ[c.gone_kind ?? ''] ?? c.gone_kind} · ${когда(c.gone_at)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.truncated && (
            <p className="text-[11px] text-amber-300/80">
              Показаны первые {data.limit} кодов — уточните поиск, чтобы увидеть нужный.
            </p>
          )}
        </>
      )}

      <p className="text-[10px] text-muted-foreground/60">
        Что здесь пока нельзя увидеть: числится ли код за нами в ГИС МТ. Для этого нужен доступ к
        True API — до него реестр показывает только нашу сторону, и расхождение с государством
        обнаружится не здесь, а при проверке.
      </p>
    </div>
  )
}
