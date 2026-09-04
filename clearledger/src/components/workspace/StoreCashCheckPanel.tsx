/**
 * «Магазин» → Касса → Сверка «касса ↔ учёт» по сети.
 *
 * Главный экран кассы в центре. Центр остаток кассы NeftoMS сам не видит (он с
 * АЗС), поэтому станция шлёт снимок сверки пакетом cash_state своим тактом.
 * Читается по НАПРАВЛЕНИЮ, а не по величине: касса выше учёта — разбор
 * обязателен; ниже — окно разнесения (уйдёт за такт); сырьё общепита — норма.
 * Само выравнивание делает станция — здесь надзор и приоритет.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitCompareArrows, AlertTriangle, ChevronRight } from 'lucide-react'
import { getStoreCashCheck, type StoreCashCheckStation } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Цвет строки по направлению: разбор — тревога, разнесение — жёлтое, сходится — тихо. */
function цвет(s: StoreCashCheckStation): string {
  if (s.state === 'разбор') return 'text-red-300/90'
  if (s.state === 'разнесение') return 'text-amber-300/80'
  return 'text-emerald-300/70'
}

export function StoreCashCheckPanel() {
  const { company } = useCompany()
  const [станция, setСтанция] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-cash-check', company.id],
    queryFn: () => getStoreCashCheck(),
    refetchInterval: 60_000,
  })
  const детали = useQuery({
    queryKey: ['store-cash-check', company.id, станция],
    queryFn: () => getStoreCashCheck(станция!),
    enabled: станция != null,
  })

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка сверки…</div>
  }
  if (error) {
    return <div className="p-6 text-sm text-destructive">Не удалось загрузить сверку: {(error as Error).message}</div>
  }
  const станции = data?.stations ?? []
  if (станции.length === 0) {
    return (
      <div className="p-6 max-w-2xl">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary shrink-0">
            <GitCompareArrows className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold">Сверка «касса ↔ учёт»</h3>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              Сверок ещё нет: станция шлёт снимок только после того, как начинает
              кормить кассу (после Дня X). Как только агент выпустит первый файл
              справочника, здесь появится строка на каждую АЗС.
            </p>
          </div>
        </div>
      </div>
    )
  }

  const детали_станции = детали.data
  const above_items = детали_станции?.above_items ?? []

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-3">
        <div className="rounded-lg bg-primary/10 p-2 text-primary shrink-0">
          <GitCompareArrows className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Сверка «касса ↔ учёт» по сети</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Касса выше учёта — разбор · ниже — окно разнесения · сырьё общепита — норма.
            Выравнивание делает станция.
          </p>
        </div>
        {data && data.with_above > 0 && (
          <div className="ml-auto flex items-center gap-1.5 rounded-lg border border-red-400/40 bg-red-500/5 px-3 py-1.5 text-xs text-red-300/90">
            <AlertTriangle className="h-3.5 w-3.5" />
            Разбор нужен на {data.with_above} {data.with_above === 1 ? 'станции' : 'станциях'}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border/60 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="text-left font-medium px-3 py-2">Станция</th>
              <th className="text-right font-medium px-3 py-2">Касса выше</th>
              <th className="text-right font-medium px-3 py-2">Нет в кассе</th>
              <th className="text-right font-medium px-3 py-2">Касса ниже</th>
              <th className="text-right font-medium px-3 py-2">Сырьё</th>
              <th className="text-right font-medium px-3 py-2">Без карточки</th>
              <th className="text-right font-medium px-3 py-2">Снято</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {станции.map((s) => (
              <tr
                key={s.station_id}
                onClick={() => setСтанция(станция === s.station_id ? null : s.station_id)}
                className={`border-t border-border/40 cursor-pointer hover:bg-muted/30 ${
                  станция === s.station_id ? 'bg-muted/40' : ''}`}
              >
                <td className="px-3 py-2">
                  <span className={`font-medium ${цвет(s)}`}>{s.name}</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {s.above > 0 ? <span className="text-red-300/90 font-medium">{s.above}</span> : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {s.not_in_cash > 0 ? <span className="text-red-300/90 font-medium">{s.not_in_cash}</span> : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {s.below > 0 ? <span className="text-amber-300/80">{s.below}</span> : '—'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.raw_material || '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.no_card || '—'}</td>
                <td className="px-3 py-2 text-right text-xs text-muted-foreground/70">{когда(s.taken_at)}</td>
                <td className="px-1 text-muted-foreground/50">
                  {s.above > 0 && <ChevronRight className={`h-4 w-4 transition-transform ${
                    станция === s.station_id ? 'rotate-90' : ''}`} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {станция != null && (
        <div className="rounded-lg border border-red-400/30 bg-red-500/[0.03] p-3">
          <div className="text-sm font-medium mb-2">
            Касса выше учёта — что разобрать на станции{' '}
            {станции.find((s) => s.station_id === станция)?.name}
          </div>
          {детали.isLoading ? (
            <div className="text-xs text-muted-foreground">Загрузка позиций…</div>
          ) : above_items.length === 0 ? (
            <div className="text-xs text-muted-foreground">Позиций разбора нет.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="text-left font-normal py-1">Код</th>
                  <th className="text-left font-normal py-1">Наименование</th>
                  <th className="text-right font-normal py-1">В кассе</th>
                  <th className="text-right font-normal py-1">Должно</th>
                  <th className="text-right font-normal py-1">Разница</th>
                </tr>
              </thead>
              <tbody>
                {above_items.map((it, i) => {
                  const разн = (it.in_cash ?? 0) - (it.should_be ?? 0)
                  return (
                    <tr key={i} className="border-t border-border/30">
                      <td className="py-1 tabular-nums text-muted-foreground">{it.ns_code ?? '—'}</td>
                      <td className="py-1">{it.name}</td>
                      <td className="py-1 text-right tabular-nums">{it.in_cash ?? '—'}</td>
                      <td className="py-1 text-right tabular-nums">{it.should_be ?? '—'}</td>
                      <td className="py-1 text-right tabular-nums text-red-300/90">+{разн.toFixed(0)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          <div className="text-[11px] text-muted-foreground/60 mt-2">
            Разбор и выравнивание — на рабочем месте станции: справочник кассы ведёт агент,
            из центра его не правят.
          </div>
        </div>
      )}
    </div>
  )
}
