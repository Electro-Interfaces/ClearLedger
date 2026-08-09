/**
 * «Магазин» → 1С до перехода → Почему уходим.
 *
 * Соседние экраны раздела показывают расхождения по отдельности. Этот отвечает
 * на вопрос, ради которого переход и затевается: что в старой 1С сломано
 * сегодня и что из этого у нас уже не воспроизводится.
 *
 * Болезни 1С не гасятся нашей работой. Дубль, который мы разобрали у себя, в 1С
 * остаётся до Дня X — поэтому в строке стоят обе величины, а не «разобрано».
 *
 * Данные: /api/store/cure (store_cure.compare).
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, Minus } from 'lucide-react'
import { getStoreCure } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

const nf = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

/** Сколько времени прошло — словами: «снято 28.07» само по себе не тревожит. */
function возраст(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const часов = (Date.now() - d.getTime()) / 3_600_000
  if (часов < 1) return 'меньше часа назад'
  if (часов < 36) return `${Math.round(часов)} ч назад`
  return `${Math.round(часов / 24)} дн. назад`
}

function Сторона({ имя, подпись, снято, строки }: {
  имя: string; подпись: string; снято: string | null | undefined
  строки: { label: string; value: string }[]
}) {
  const стар = возраст(снято)
  const давно = snapshotOld(снято)
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-4">
      <div className="text-sm font-medium">{имя}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{подпись}</div>
      <div className={`mt-1 text-[11px] ${давно ? 'text-amber-300/90' : 'text-muted-foreground'}`}>
        снято {когда(снято)}{стар && ` · ${стар}`}
      </div>
      <dl className="mt-3 space-y-1">
        {строки.map((с) => (
          <div key={с.label} className="flex items-baseline justify-between gap-3 text-xs">
            <dt className="text-muted-foreground">{с.label}</dt>
            <dd className="tabular-nums">{с.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Срез старше трёх суток — уже не «сейчас», и это должно быть видно. */
function snapshotOld(iso: string | null | undefined): boolean {
  if (!iso) return false
  const d = new Date(iso)
  return !Number.isNaN(d.getTime()) && Date.now() - d.getTime() > 3 * 24 * 3_600_000
}

export function StoreCurePanel() {
  const { company } = useCompany()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-cure', company.id],
    queryFn: () => getStoreCure(208),
  })

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Сверяем нашу базу с 1С…</div>
  }
  if (error) {
    return (
      <div className="space-y-2 p-6">
        <h3 className="text-base font-semibold">Почему уходим из 1С</h3>
        <div className="text-sm text-red-400/90">
          Не удалось получить сверку — сбой запроса, а не отсутствие данных.{' '}
          <button type="button" className="underline underline-offset-2" onClick={() => refetch()}>
            Повторить
          </button>
        </div>
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Почему уходим из 1С</h3>
        <p className="text-xs text-muted-foreground">
          Соседние экраны показывают расхождения по одному. Здесь они собраны в один ответ:
          что в старой 1С сломано сегодня и что из этого у нас уже не воспроизводится.
          Разобранный нами дубль болезнь 1С не гасит — там он останется до Дня X.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Сторона имя="Старая 1С станции"
          подпись="локальная база 208: срез снимает задание со станции"
          снято={data.onec.срез}
          строки={[
            { label: 'Карточек в справочнике', value: nf(data.onec.карточек) },
            { label: 'Из них помечено на удаление', value: nf(data.onec.помеченных) },
            { label: 'Карточек с остатком', value: nf(data.onec.карточек_с_остатком) },
            { label: 'Остаток по регистру', value: nf(data.onec.остаток) },
          ]} />
        <Сторона имя="Наша база"
          подпись="журнал станции: снимок остатков приезжает раз в час"
          снято={data.ours.снято}
          строки={[
            { label: 'Карточек в каталоге сети', value: nf(data.ours.карточек_каталога) },
            { label: 'Карточек с остатком', value: nf(data.ours.карточек_с_остатком) },
            { label: 'Строк (карточка × место)', value: `${nf(data.ours.строк)} на ${data.ours.мест} местах` },
            { label: 'Остаток', value: nf(data.ours.остаток) },
          ]} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Остатки двух сторон вычитать нельзя: их сняли в разное время и в разных единицах учёта —
        у 1С измерениями регистра служат цена и штрихкод, у нас карточка и место хранения.
        Позиционное сравнение на один момент делает «Цепочка учёта».
      </p>

      <div>
        <h4 className="mb-2 text-sm font-medium">Что болит в 1С и как это у нас</h4>
        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Болезнь</th>
                <th className="px-3 py-2 text-right font-medium">В 1С</th>
                <th className="px-3 py-2 text-right font-medium">У нас</th>
                <th className="px-3 py-2 text-left font-medium">Что с этим</th>
              </tr>
            </thead>
            <tbody>
              {data.diseases.map((д) => (
                <tr key={д.key} className="border-t border-border/30 align-top">
                  <td className="px-3 py-2">
                    <div className="flex items-baseline gap-1.5">
                      {/* Состояние — значком И словом: цвет один смысл нести не может */}
                      {д.cured === true ? (
                        <Check className="mt-0.5 size-3.5 shrink-0 text-emerald-400/90" aria-hidden />
                      ) : д.cured === false ? (
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-400/90" aria-hidden />
                      ) : (
                        <Minus className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      )}
                      <span>
                        {д.name}
                        <span className="ml-1 text-[11px] text-muted-foreground">
                          {д.cured === true ? '· у нас не бывает'
                            : д.cured === false ? '· есть и у нас'
                            : '· сравнить не с чем'}
                        </span>
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {д.onec == null ? '—' : nf(д.onec)}
                    <div className="text-[11px] font-normal text-muted-foreground">{д.onec_hint}</div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {д.ours == null ? '—' : nf(д.ours)}
                    <div className="text-[11px] font-normal text-muted-foreground">{д.ours_hint}</div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{д.how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium">Чем лечим</h4>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Инвентаризаций станции</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums">{nf(data.treatment.инвентаризаций)}</div>
            <div className="text-[11px] text-muted-foreground">
              последняя {когда(data.treatment.последняя_инвентаризация)}
            </div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Карточек признано со станций</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums">
              {nf(data.treatment.признано_карточек)}
              <span className="text-sm font-normal text-muted-foreground"> из {nf(data.treatment.черновиков_всего)}</span>
            </div>
            <div className="text-[11px] text-muted-foreground">черновик станции стал сетевой карточкой</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Групп дублей разобрано</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums">
              {nf(data.treatment.разобрано_групп)}
              <span className="text-sm font-normal text-muted-foreground"> из {nf(data.treatment.групп_в_контуре)}</span>
            </div>
            <div className="text-[11px] text-muted-foreground">решение принято — в 1С дубль остаётся</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Минусов у нас</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums text-amber-400/90">
              {nf(data.diseases.find((д) => д.key === 'negatives')?.ours ?? 0)}
            </div>
            <div className="text-[11px] text-muted-foreground">закрываются инвентаризацией</div>
          </div>
        </div>
      </div>
    </div>
  )
}
