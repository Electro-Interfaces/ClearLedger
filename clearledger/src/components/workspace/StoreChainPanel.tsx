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
import { ChevronRight, Download, RadioTower } from 'lucide-react'
import {
  getStoreStations, getStoreChain,
  type StoreStation, type StoreChainItem,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { csvDownload } from './csvDownload'

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
  const показ = useVisible(позиции)
  return (
    <div className="rounded-lg border border-border/50 bg-card/40">
      <button type="button" onClick={() => есть && открыть(!открыта)}
        className={`flex w-full items-baseline gap-3 px-4 py-3 text-left ${есть ? 'cursor-pointer hover:bg-accent/20' : 'cursor-default'}`}>
        <span className="flex-1 text-sm font-medium">
          {есть && <ChevronRight className={`mr-1 inline h-3 w-3 transition-transform ${открыта ? 'rotate-90' : ''}`} />}
          {/* Точка — метка тревоги; без слова рядом она не существует ни для
              скринридера, ни для человека, не различающего красный. */}
          {тревожно && (
            <span className="mr-1 text-red-400/90">
              <span aria-hidden>●</span>
              <span className="sr-only">требует внимания: </span>
            </span>
          )}
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
              {показ.visible.map((п, i) => (
                <tr key={`${п.uuid ?? п.товар}-${i}`} className="border-t border-border/30">
                  <td className="px-3 py-1.5">{п.товар}</td>
                  {деталь && <td className="px-3 py-1.5 text-muted-foreground">{п.деталь ?? '—'}</td>}
                  {/* Ноль и «карточки нет» — разные ответы. У готовой продукции
                      кассы есть номинальный остаток, а в нашем журнале строки
                      нет вовсе: печатая её нулём, экран называл это недостачей. */}
                  {колонки.касса && <td className="px-3 py-1.5 text-right tabular-nums">{п.касса == null ? '—' : число(п.касса)}</td>}
                  {колонки.наш && <td className="px-3 py-1.5 text-right tabular-nums">{п.наш == null ? '—' : число(п.наш)}</td>}
                  {колонки.одинс && <td className="px-3 py-1.5 text-right tabular-nums">{п.одинс == null ? '—' : число(п.одинс)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {/* Раскрытие рендерит не всё разом: у «источники разошлись» на 208
              триста строк, и они разворачивались одним куском. */}
          <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="позиций" />
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

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-chain', company.id, станция],
    queryFn: () => getStoreChain(станция as number),
    enabled: станция !== null,
  })

  const с = data?.snapshot
  const естьКасса = Boolean(с?.касса_доступна)
  const есть1С = Boolean(с?.одинс_есть_снимок)
  // Снимок 1С мог быть снят когда угодно: агент отдаёт последний, какой есть.
  // Сравнивать сегодняшний остаток с прошлонедельной 1С — ровно та ложная
  // тревога, ради которой снимок и делается одним заходом.
  const свежий1С = с?.одинс_снимок_свежий !== false
  const ошибкиОчереди = с?.обмен_ошибки_очереди ?? []
  // Возраст снимка. Цепочка снимается раз в шесть часов, остатки — раз в час,
  // поэтому её числа отстают от всего остального в разделе. Раньше это было
  // сказано только датой, которую никто не вычитал из текущего времени.
  const возраст = с?.снято ? (Date.now() - new Date(с.снято).getTime()) / 3_600_000 : null
  const староват = возраст !== null && возраст >= 12

  const выгрузить = () => csvDownload(
    `цепочка-${станция ?? 'сеть'}-${(с?.снято ?? '').slice(0, 10)}`,
    ['Товар', 'Место', 'Касса', 'У нас', '1С'],
    (data?.разошлись ?? []).map((п) => [
      п.товар, п.деталь ?? '',
      п.касса ?? '', п.наш ?? '', п.одинс ?? '',
    ]))

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
        <h3 className="text-base font-semibold">Цепочка учёта</h3>
        <p className="text-xs text-muted-foreground">
          Товар считают в трёх местах сразу: касса знает, чем торгуют, наш журнал — чем владеем,
          старая 1С осталась переходным контуром и передаёт данные в центральную базу. Снимок
          делает станция одним заходом: сравнивать источники, снятые в разное время, — самый
          простой способ увидеть расхождение там, где его нет.
        </p>
        </div>
        {/* Разговор о расхождении идёт не у экрана: список нужно отдать
            товароведу на станцию или приложить к письму. */}
        {(data?.разошлись?.length ?? 0) > 0 && (
          <button type="button" onClick={выгрузить}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground">
            <Download className="size-3.5" />Выгрузить расхождения
          </button>
        )}
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

      {/* Сбой запроса — не «станция не прислала снимок». Раньше оба случая
          сходились в одну фразу, и отказ центра выглядел как отказ станции. */}
      {!isLoading && error && (
        <div className="rounded-lg border border-red-400/30 bg-red-400/5 p-4 text-xs text-red-300/90">
          Не удалось получить снимок — сбой запроса к центру, а не молчание станции.{' '}
          <button type="button" className="underline underline-offset-2" onClick={() => refetch()}>
            Повторить
          </button>
        </div>
      )}

      {!isLoading && !error && !data?.available && (
        <div className="rounded-lg border border-border/50 bg-card/40 p-4 text-xs text-muted-foreground">
          {data?.detail ?? 'снимка ещё нет'}. Снимок делает агент АЗС — сам каждые шесть часов
          либо по кнопке в рабочем месте станции.
        </div>
      )}

      {с && (
        <>
          <div className={`text-xs ${староват ? 'text-amber-300/90' : 'text-muted-foreground'}`}>
            Снято на станции {когда(с.снято)}
            {возраст !== null && ` (${возраст < 1 ? 'меньше часа назад' : `${Math.round(возраст)} ч назад`})`}
            {' · '}получено центром {когда(data?.received_at)}
            {староват && ' — снимок старше половины суток: остатки станции с тех пор ушли вперёд'}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {/* Позиций у кассы и у нас — разные единицы: касса считает строки
                (один товар живёт под несколькими кодами), мы — карточки. Пока
                на плитке стояли строки, вычитание плиток давало 123 «пропавшие»
                позиции вместо 82 настоящих. */}
            <Звено имя="Касса Нефтесервера" позиций={с.касса_карточек ?? с.касса_позиций}
              остаток={с.касса_остаток} доступно={естьКасса}
              подпись={с.касса_карточек != null
                ? `чем торгуем: карточек в кассе, кодов ${число(с.касса_позиций)}`
                : 'чем торгуем: витрина кассы станции'} />
            <Звено имя="Наш учёт" позиций={с.наш_позиций} остаток={с.наш_остаток}
              доступно подпись="чем владеем: карточка × место хранения" />
            <Звено имя="1С станции" позиций={с.одинс_позиций} остаток={с.одинс_остаток}
              доступно={есть1С && свежий1С}
              подпись={!есть1С ? 'переходный контур: снимка ещё нет'
                : свежий1С ? `переходный контур, снимок от ${когда(с.одинс_снято)}`
                : `снимок 1С устарел (${когда(с.одинс_снято)}) — в сравнение не идёт`} />
            <div className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">Обмен с центральной 1С</div>
              {/* Очередь читается из самой 1С. Если чтение упало, «очередь пуста»
                  — не факт, а незнание: 266 ошибок обмена уже отдавали зелёный. */}
              {ошибкиОчереди.length > 0 ? (
                <>
                  <div className="mt-0.5 text-xl font-semibold text-amber-400/90">не прочитана</div>
                  <div className="text-[11px] text-muted-foreground" title={ошибкиОчереди[0]}>
                    1С ответила ошибкой по {число(ошибкиОчереди.length)} объектам обмена
                  </div>
                </>
              ) : с.обмен_очередь_всего > 0 ? (
                <>
                  {/* Красное — только про неотправленное. Ждущее подтверждения
                      это нормальная работа обмена, а не авария. */}
                  <div className={`mt-0.5 text-xl font-semibold tabular-nums ${
                    с.обмен_не_отправлено > 0 ? 'text-red-400/90' : ''}`}>
                    {число(с.обмен_очередь_всего)}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {с.обмен_не_отправлено > 0
                      ? `регистраций в очереди · не отправлено ${число(с.обмен_не_отправлено)}`
                      : 'регистраций ждёт подтверждения центральной базы · всё отправлено'}
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
                    {/* Причину отказа станция пока не присылает: писать «1С была
                        недоступна» нельзя — она бывает доступна, а падает чтение. */}
                    состояние обмена прочитать не удалось
                    {с.одинс_доступна === false && ' — 1С была недоступна'}
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
              {/* Очередь обмена — одна новость, а не двадцать две. Раньше на
                  каждый объект рисовалась своя тревожная строка, и экран
                  краснел двадцатью двумя одинаковыми записями при нуле
                  неотправленного. */}
              {(с.обмен_очередь ?? []).length > 0 && (
                <Расхождение
                  что="Старая 1С ждёт отправки"
                  сколько={`${с.обмен_очередь.length} объектов · ${число(с.обмен_очередь_всего)} регистраций`}
                  тревожно={с.обмен_не_отправлено > 0}
                  почему={с.обмен_не_отправлено > 0
                    ? 'часть регистраций ещё не отправлена в центральную базу. Это старый обмен 1С, а не очередь рабочего агента'
                    : 'регистрации отправлены и ждут подтверждения центральной базы — нормальная работа старого обмена, а не затор'}
                  деталь="Объект обмена"
                  позиции={с.обмен_очередь.map((q) => ({ товар: q }))}
                  колонки={{ касса: false, наш: false, одинс: false }} />
              )}

              {/* Сходится всё — тоже результат, и он должен читаться. Пустой
                  контейнер под заголовком выглядел как незагрузившийся блок. */}
              {(data?.разошлись?.length ?? 0) === 0 && с.касса_лишних_кодов === 0
                && с.наш_минусов === 0 && (!есть1С || с.одинс_фантомов === 0)
                && (с.обмен_очередь ?? []).length === 0 && (
                <div className="rounded-lg border border-emerald-400/30 bg-emerald-400/5 p-4 text-xs text-emerald-300/90">
                  Расхождений нет: источники сошлись на снимке {когда(с.снято)}.
                  Сверено {[естьКасса && 'касса', 'наш учёт', есть1С && свежий1С && '1С станции']
                    .filter(Boolean).join(', ')}.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
