/**
 * «Статистика» — сколько времени уходит на конференции и на что.
 *
 * Считаем по состоявшимся конференциим, а не по назначенным встречам: назначить
 * можно что угодно, а конференция либо был, либо нет. Числа даём без оценок:
 * «шесть часов у Иванова» — это факт, а не приговор, и что с ним делать,
 * решает руководитель, а не интерфейс.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3 } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import * as conf from '@/services/confService'
import { EmptyBlock } from './EmptyBlock'
import { длительность, предмет } from './format'

const ПЕРИОДЫ: { days: number; name: string }[] = [
  { days: 7, name: 'Неделя' },
  { days: 30, name: 'Месяц' },
  { days: 90, name: 'Квартал' },
]

export default function ConfStatsPage() {
  const { companyId } = useCompany()
  const [дней, setДней] = useState(30)
  const стат = useQuery({
    queryKey: ['conf-stats', companyId, дней],
    queryFn: () => conf.stats(companyId, дней),
  })
  const д = стат.data

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-headline mr-auto text-lg font-semibold">Статистика</h1>
        <div className="flex gap-1 rounded-md border border-border p-0.5">
          {ПЕРИОДЫ.map(п => (
            <button key={п.days} type="button" onClick={() => setДней(п.days)}
              aria-pressed={дней === п.days}
              className={`min-h-8 rounded px-3 text-sm transition-colors ${
                дней === п.days ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50'}`}>
              {п.name}
            </button>
          ))}
        </div>
      </div>

      {стат.isLoading && <p role="status" className="text-sm">Считаем…</p>}
      {!стат.isLoading && d0(д) && (
        <EmptyBlock иконка={BarChart3} текст="За этот период конференций не было"
          подсказка="Считаются состоявшиеся конференции: назначенная, но не начатая сюда не попадает." />
      )}

      {д && д.total > 0 && (
        <>
          <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-border pb-4">
            <Показатель имя="Конференций" значение={String(д.total)} />
            <Показатель имя="Общее время" значение={длительность(д.seconds) ?? '—'} />
            <Показатель имя="С записью" значение={String(д.with_recording)} />
            {д.unmeasured > 0 && (
              <Показатель имя="Время не считалось" значение={String(д.unmeasured)} />
            )}
          </div>

          <section className="space-y-1">
            <h2 className="text-sm font-medium">Кто участвовал</h2>
            <p className="text-xs text-muted-foreground">
              Считается вход через пространство: время конференции засчитывается всем,
              кто в ней был. Конференции, закрытые по сроку, а не людьми, во время
              не идут — их конец поставлен правилом, а не тем, когда разошлись.
            </p>
            {д.people.map(ч => (
              <div key={ч.user_id} className="flex items-baseline gap-2 border-b border-border/60 py-2 text-sm last:border-0">
                <span className="min-w-0 flex-1 truncate">{ч.name}</span>
                <span className="text-muted-foreground">{ч.meetings}</span>
                <span className="w-24 text-right font-mono text-xs">
                  {длительность(ч.seconds) ?? '—'}
                </span>
              </div>
            ))}
          </section>

          <section className="space-y-1">
            <h2 className="text-sm font-medium">О чём говорили</h2>
            <p className="text-xs text-muted-foreground">
              Разрез по предмету: конференция о документе или поручении «Трека» знает,
              к чему он относится. Конференция без предмета попадает в «без привязки».
            </p>
            {д.subjects.map(п => {
              const пред = предмет(п.subject_ref)
              return (
                <div key={п.subject_ref || 'none'}
                  className="flex items-baseline gap-2 border-b border-border/60 py-2 text-sm last:border-0">
                  <span className="min-w-0 flex-1 truncate">
                    {пред ? пред.имя : 'без привязки'}
                    {п.subject_ref && (
                      <span className="ml-2 font-mono text-xs text-muted-foreground">
                        {п.subject_ref}
                      </span>
                    )}
                  </span>
                  <span className="text-muted-foreground">{п.meetings}</span>
                  <span className="w-24 text-right font-mono text-xs">
                    {длительность(п.seconds) ?? '—'}
                  </span>
                </div>
              )
            })}
          </section>
        </>
      )}
    </div>
  )
}

function d0(д?: conf.ConfStats) {
  return !!д && д.total === 0
}

function Показатель({ имя, значение }: { имя: string; значение: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{имя}</p>
      <p className="font-headline text-xl font-semibold">{значение}</p>
    </div>
  )
}
