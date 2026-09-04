/**
 * «Магазин» → Касса → Коды нефтесервера.
 *
 * Код кассы — расходник связки станция × штрихкод, а не свойство товара. Он
 * локален для АЗС, переиспользуется после гашения и живёт в границах, которые
 * нарезает центр. Кончится пул — станция не заведёт новую позицию, и товар с
 * полки не пробьётся: «МАЛО ТОВАРА» при полном ящике.
 *
 * Экран показывает состояние, а не действие. Снять код, перевесить его или
 * погасить может только станция — центр в кассу не пишет никогда.
 */
import { useQuery } from '@tanstack/react-query'
import { Hash, AlertTriangle } from 'lucide-react'
import { getStoreCashCodes } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

/** Полоса запаса: пока номеров вдоволь, она тихая; тревога — с четверти остатка. */
function цветПолосы(свободноДолей: number): string {
  if (свободноДолей < 10) return 'bg-red-500/70'
  if (свободноДолей < 25) return 'bg-amber-500/70'
  return 'bg-emerald-500/60'
}

export function StoreNsCodesPanel() {
  const { company } = useCompany()
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-cash-codes', company.id],
    queryFn: getStoreCashCodes,
    refetchInterval: 120_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка кодов…</div>
  if (error) {
    return <div className="p-6 text-sm text-destructive">Не удалось загрузить коды: {(error as Error).message}</div>
  }
  const станции = data?.stations ?? []

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary shrink-0">
          <Hash className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Коды нефтесервера</h3>
          <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
            Номер, под которым касса знает товар. Он локален для станции и в сетевых
            отчётах не участвует: один и тот же товар на двух АЗС держит разные коды.
            Пул нарезает центр, номер выдаёт станция — и делает это офлайн, пока
            накладная в руках. Кончатся номера — новую позицию завести будет нечем.
          </p>
        </div>
      </div>

      {станции.length === 0 && (
        <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
          Ни одной станции с нарезанным пулом.
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {станции.map((с) => {
          const свободноДолей = с.всего_в_пуле ? Math.round(с.свободно / с.всего_в_пуле * 100) : 0
          return (
            <div key={с.station_id} className="rounded-lg border bg-card p-4">
              <div className="flex items-baseline justify-between gap-2">
                <div className="font-medium">{с.name}</div>
                <div className="font-mono text-xs text-muted-foreground">
                  {с.ns_code_min}–{с.ns_code_max}
                </div>
              </div>

              <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-muted">
                <div className={`h-full ${цветПолосы(свободноДолей)}`}
                     style={{ width: `${Math.min(с.занято_долей, 100)}%` }} />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>занято <b className="text-foreground">{с.занято}</b></span>
                <span>свободно <b className="text-foreground">{с.свободно}</b></span>
                <span>погашено {с.погашено}</span>
                {с.первый != null && <span className="font-mono">в ходу {с.первый}–{с.последний}</span>}
              </div>

              {/* Спящий код держит номер и мешает продать вторую упаковку того же
                  товара. Снимают их на станции — здесь только видно, сколько их. */}
              {с.спящих > 0 && (
                <div className="mt-3 flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <div className="text-muted-foreground">
                    Спящих кодов: <b className="text-foreground">{с.спящих}</b> — привязка
                    активна, а товара за ней нет: ни остатка, ни цены. Номер занят зря, и
                    вторую упаковку того же товара под ним не продать. Снимает станция
                    командой <code className="font-mono">agent nscode-retire</code>.
                  </div>
                </div>
              )}

              {с.вне_пула > 0 && (
                <div className="mt-2 flex gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                  <div className="text-muted-foreground">
                    Вне нарезанного пула: <b className="text-foreground">{с.вне_пула}</b>.
                    Код выдан за границами, которые задал центр, — наследие 1С или
                    ручная привязка. Работать он будет, но в учёт запаса не попадает.
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
        Потолок 5200 — не наша выдумка, а настройка рабочих мест поста: код выше него
        нефтесервер считает услугой с количеством 1000. Поднять границу можно, но это
        правка настроек на постах и полный перелив справочника, а не строчка у нас.
      </div>
    </div>
  )
}
