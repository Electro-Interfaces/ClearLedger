/**
 * «Магазин» → 1С до перехода → Цепочка учёта.
 *
 * Товар считают в трёх местах сразу: касса знает, чем торгуют, журнал агента —
 * чем владеем, старая 1С осталась переходным контуром и передаёт данные в
 * центральную базу. Расходятся они всегда — вопрос в том, где и почему.
 *
 * Снимок делает станция одним заходом и присылает как есть. Центр его НЕ
 * пересчитывает: касса NeftoMS и локальная 1С видны только с АЗС, а сравнение
 * источников, снятых в разные моменты, показывает расхождение там, где его
 * нет, — на этом здесь уже обжигались.
 *
 * Данные: /api/store/chain (edge_service.chain_report), пакет агента kind=chain.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, RadioTower } from 'lucide-react'
import {
  getStoreStations, getStoreChain,
  type StoreStation, type StoreChainItem,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

function число(v: number | undefined | null): string {
  if (v === undefined || v === null) return '—'
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 3 })
}

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

/** Звено цепочки: сколько позиций и остаток. Недоступный источник — прочерк. */
function Звено({ имя, позиций, остаток, доступно, подпись }: {
  имя: string; позиций: number; остаток: number; доступно: boolean; подпись: string
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-[11px] text-muted-foreground">{имя}</div>
      {доступно ? (
        <>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{число(позиций)}</div>
          <div className="text-[11px] text-muted-foreground">
            позиций · остаток {число(остаток)}
          </div>
        </>
      ) : (
        <>
          <div className="mt-0.5 text-xl font-semibold text-amber-400/90">—</div>
          <div className="text-[11px] text-muted-foreground">данных нет</div>
        </>
      )}
      <div className="mt-1.5 text-[11px] text-muted-foreground">{подпись}</div>
    </div>
  )
}

/**
 * Строка расхождения: цифра сверху, карточки под ней.
 *
 * Без списка товаров строка превращается в задание «поищи сам» — товаровед
 * всё равно пойдёт смотреть, кто именно в минусе, и найдёт эти позиции в
 * другом отчёте другой свежести.
 */
function Расхождение({ что, сколько, почему, тревожно, деталь, позиции, колонки }: {
  что: string; сколько: string; почему: string; тревожно?: boolean
  деталь?: string; позиции: StoreChainItem[]
  колонки: { касса: boolean; наш: boolean; одинс: boolean }
}) {
  const [открыта, открыть] = useState(false)
  const есть = позиции.length > 0
  return (
    <div className="rounded-lg border border-border/50 bg-card/40">
      <button type="button" onClick={() => есть && открыть(!открыта)}
        className={`flex w-full items-baseline gap-3 px-4 py-3 text-left ${есть ? 'cursor-pointer hover:bg-accent/20' : 'cursor-default'}`}>
        <span className="flex-1 text-sm font-medium">
          {есть && <ChevronRight className={`mr-1 inline h-3 w-3 transition-transform ${открыта ? 'rotate-90' : ''}`} />}
          {тревожно && <span className="mr-1 text-red-400/90">●</span>}
          {что}
        </span>
        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">{сколько}</span>
      </button>
      <p className="px-4 pb-3 text-xs text-muted-foreground">{почему}</p>
      {открыта && есть && (
        <div className="overflow-x-auto border-t border-border/40">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Товар</th>
                {деталь && <th className="px-3 py-2 text-left font-medium">{деталь}</th>}
                {колонки.касса && <th className="px-3 py-2 text-right font-medium">Касса</th>}
                {колонки.наш && <th className="px-3 py-2 text-right font-medium">У нас</th>}
                {колонки.одинс && <th className="px-3 py-2 text-right font-medium">1С</th>}
              </tr>
            </thead>
            <tbody>
              {позиции.map((п, i) => (
                <tr key={`${п.uuid ?? п.товар}-${i}`} className="border-t border-border/30">
                  <td className="px-3 py-1.5">{п.товар}</td>
                  {деталь && <td className="px-3 py-1.5 text-muted-foreground">{п.деталь ?? '—'}</td>}
                  {колонки.касса && <td className="px-3 py-1.5 text-right tabular-nums">{число(п.касса ?? 0)}</td>}
                  {колонки.наш && <td className="px-3 py-1.5 text-right tabular-nums">{число(п.наш ?? 0)}</td>}
                  {колонки.одинс && <td className="px-3 py-1.5 text-right tabular-nums">{число(п.одинс ?? 0)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function StoreChainPanel() {
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
    queryKey: ['store-chain', company.id, станция],
    queryFn: () => getStoreChain(станция as number),
    enabled: станция !== null,
  })

  const с = data?.snapshot
  const естьКасса = Boolean(с?.касса_доступна)
  const есть1С = Boolean(с?.одинс_есть_снимок)

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Цепочка учёта</h3>
        <p className="text-xs text-muted-foreground">
          Товар считают в трёх местах сразу: касса знает, чем торгуют, наш журнал — чем владеем,
          старая 1С осталась переходным контуром и передаёт данные в центральную базу. Снимок
          делает станция одним заходом: сравнивать источники, снятые в разное время, — самый
          простой способ увидеть расхождение там, где его нет.
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

      {isLoading && <div className="text-xs text-muted-foreground">Читаем последний снимок станции…</div>}

      {!isLoading && !data?.available && (
        <div className="rounded-lg border border-border/50 bg-card/40 p-4 text-xs text-muted-foreground">
          {data?.detail ?? 'снимка ещё нет'}. Снимок делает агент АЗС — сам каждые шесть часов
          либо по кнопке в рабочем месте станции.
        </div>
      )}

      {с && (
        <>
          <div className="text-xs text-muted-foreground">
            Снято на станции {когда(с.снято)} · получено центром {когда(data?.received_at)}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Звено имя="Касса Нефтесервера" позиций={с.касса_позиций} остаток={с.касса_остаток}
              доступно={естьКасса} подпись="чем торгуем: витрина кассы станции" />
            <Звено имя="Наш учёт" позиций={с.наш_позиций} остаток={с.наш_остаток}
              доступно подпись="чем владеем: журнал станции, наш источник истины" />
            <Звено имя="1С станции" позиций={с.одинс_позиций} остаток={с.одинс_остаток}
              доступно={есть1С}
              подпись={есть1С ? `переходный контур, снимок от ${когда(с.одинс_снято)}` : 'переходный контур: снимка ещё нет'} />
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Обмен с центральной 1С</div>
              {с.обмен_очередь_всего > 0 ? (
                <>
                  <div className="mt-0.5 text-xl font-semibold tabular-nums text-red-400/90">
                    {число(с.обмен_очередь_всего)}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    регистраций ждёт · не отправлено {число(с.обмен_не_отправлено)}
                  </div>
                </>
              ) : с.обмен_отправлено || с.обмен_принято ? (
                <>
                  <div className="mt-0.5 text-xl font-semibold text-emerald-400/90">очередь пуста</div>
                  <div className="text-[11px] text-muted-foreground">
                    отправлено {число(с.обмен_отправлено)} · получено {число(с.обмен_принято)}
                  </div>
                </>
              ) : (
                <>
                  <div className="mt-0.5 text-xl font-semibold text-amber-400/90">—</div>
                  <div className="text-[11px] text-muted-foreground">
                    состояние обмена читается из 1С, а она была недоступна
                  </div>
                </>
              )}
            </div>
          </div>

          <div>
            <h4 className="mb-1 text-sm font-medium">Что не сходится</h4>
            <p className="mb-2 text-xs text-muted-foreground">
              Не всё здесь — поломка: часть расхождений это нормальная работа переходного
              периода. Тревожные помечены. Строка раскрывается до карточек из этого же снимка.
            </p>
            <div className="space-y-2">
              {(data?.разошлись?.length ?? 0) > 0 && (
                <Расхождение что="Источники разошлись по карточке"
                  сколько={`${data!.разошлись!.length} позиций`} тревожно
                  почему="одна и та же карточка числится по-разному у кассы, у нас и в 1С. Считается нетто по карточке: построчно 1С показывает товар, которого нет"
                  позиции={data!.разошлись!}
                  колонки={{ касса: естьКасса, наш: true, одинс: есть1С }} />
              )}
              {с.касса_лишних_кодов > 0 && (
                <Расхождение что="Товар под несколькими кодами кассы"
                  сколько={`${с.касса_лишних_кодов} лишних строк на ${data?.много_кодов?.length ?? 0} карточках`}
                  почему="одна карточка пробивается под разными кодами — остаток и продажи по ней размазаны, и «сколько продали» приходится складывать вручную"
                  деталь="Строк кассы" позиции={data?.много_кодов ?? []}
                  колонки={{ касса: true, наш: false, одинс: false }} />
              )}
              {с.наш_минусов > 0 && (
                <Расхождение что="Минусовой остаток у нас" сколько={`${с.наш_минусов} позиций`} тревожно
                  почему="продали больше, чем приняли: приход не проведён или пришёл с отрицательным стартовым остатком из 1С"
                  деталь="Место" позиции={data?.минусы ?? []}
                  колонки={{ касса: естьКасса, наш: true, одинс: есть1С }} />
              )}
              {есть1С && с.одинс_фантомов > 0 && (
                <Расхождение что="Фантомные карточки в 1С" сколько={`${с.одинс_фантомов} карточек`}
                  почему="строки регистра ненулевые, а сумма по ним ноль: цена и штрихкод там измерения, и приход по одной цене не гасит списание по другой. Читать остаток 1С построчно нельзя — только нетто по карточке"
                  деталь="Строк регистра" позиции={data?.фантомы ?? []}
                  колонки={{ касса: false, наш: false, одинс: false }} />
              )}
              {(с.обмен_очередь ?? []).map((q, i) => (
                <Расхождение key={i} что="Старая 1С ждёт отправки" сколько={q} тревожно
                  почему="регистрация изменения ещё не снята: часть записей может быть не отправлена, часть уже передана, но не очищена подтверждением. Это старый обмен 1С, а не очередь рабочего агента"
                  позиции={[]} колонки={{ касса: false, наш: false, одинс: false }} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
