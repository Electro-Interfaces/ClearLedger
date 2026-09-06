/**
 * Отчёт сети на экране — один компонент на все виды.
 *
 * Отчёты уже считались на сервере и уходили файлом из витрины «Отчёты»: чтобы
 * посмотреть оборотку по сети, человек скачивал xlsx и открывал Excel. Для
 * вопроса «что вообще происходит» это дорого: файл нужен, когда цифру несут
 * дальше, а не когда на неё смотрят.
 *
 * Второй панели каждому отчёту не требуется: ответ API самоописателен — несёт
 * заголовок, пояснение, имена колонок и поля строк. Шесть панелей-близнецов
 * разошлись бы между собой за месяц, эта — не может по устройству.
 *
 * Итоги показываем те, что отчёт сам про себя знает (недовоз, НДС к вычету,
 * необъяснённая разница): их набор у каждого свой, поэтому берём по наличию,
 * а не по общему списку.
 */
import { useQuery } from '@tanstack/react-query'
import { Download, Loader2, Printer, Search } from 'lucide-react'
import { PanelViewTabs } from './PanelViewTabs'
import { ViewParamsBar } from './ViewParamsBar'
import { ReportPivot } from './ReportPivot'
import { Input } from '@/components/ui/input'
import { useFilters } from '@/contexts/FilterContext'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { fmtMoney } from '@/services/analyticsService'
import {
  getStoreNetworkReport, открытьЛистТоварногоОтчёта, скачатьОтчётСети,
  type StoreReportData,
} from '@/services/storeService'

const nf = (n: number, d = 0) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Итоги, которые отчёты кладут рядом со строками. Показываем что есть. */
const ИТОГИ: { поле: keyof StoreReportData; метка: string; деньги?: boolean }[] = [
  // Товарный отчёт: те же четыре величины, которыми лист начинается и кончается.
  // «Строк» у него не показываем — их число ни о чём не говорит бухгалтеру.
  { поле: 'opening', метка: 'Остаток на начало', деньги: true },
  { поле: 'incoming_retail', метка: 'Приход (розница)', деньги: true },
  { поле: 'expense', метка: 'Расход (выручка)', деньги: true },
  { поле: 'closing', метка: 'Остаток на конец', деньги: true },
  { поле: 'total', метка: 'Строк' },
  { поле: 'amount', метка: 'Сумма', деньги: true },
  { поле: 'revenue', метка: 'Выручка', деньги: true },
  { поле: 'stock_amount', метка: 'Запас', деньги: true },
  { поле: 'cost_amount', метка: 'Себестоимость', деньги: true },
  { поле: 'shortfall', метка: 'Недовоз', деньги: true },
  { поле: 'surplus', метка: 'Перевоз', деньги: true },
  { поле: 'vat_deductible', метка: 'НДС к вычету', деньги: true },
  { поле: 'vat_unconfirmed', метка: 'НДС без документа', деньги: true },
  { поле: 'unexplained_total', метка: 'Не объяснено', деньги: true },
  { поле: 'violations', метка: 'Нарушений' },
]

// Числовую колонку узнаём по значению, а не по имени поля: имена задаёт
// сервер, и список «какие из них числа» разошёлся бы с ним при первом же
// новом отчёте.
const число = (v: unknown) => typeof v === 'number'

const ячейка = (v: unknown) => {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (typeof v === 'number') return nf(v, Number.isInteger(v) ? 0 : 2)
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}

/**
 * Пресеты периода — те же четыре, что на рабочем месте станции. Меняют ОБЩИЙ
 * контур наверху, а не заводят второй период внутри отчёта: правда о периоде
 * должна быть одна, иначе человек смотрит на цифры и не знает, чей период
 * применён — верхний или местный.
 */
const ПРЕСЕТЫ: { ключ: string; имя: string; дней: number }[] = [
  { ключ: 'today', имя: 'Сегодня', дней: 0 },
  { ключ: '7', имя: 'Неделя', дней: 6 },
  { ключ: '30', имя: 'Месяц', дней: 29 },
  { ключ: '90', имя: 'Квартал', дней: 89 },
]

const день = (d: Date) => d.toISOString().slice(0, 10)

export function NetworkReportPanel({ kind, dateFrom, dateTo, stations }: {
  kind: string
  dateFrom: string
  dateTo: string
  stations?: number[]
}) {
  const [скачивается, скачивать] = useState(false)
  const отчёт = useQuery({
    queryKey: ['network-report', kind, dateFrom, dateTo, stations],
    queryFn: () => getStoreNetworkReport(kind, { dateFrom, dateTo, stations }),
  })

  const { setPeriod } = useFilters()
  const [подача, сменитьПодачу] = useState<'list' | 'pivot'>('list')
  const [поиск, искать] = useState('')
  // Черновик произвольного периода: набирается в полях и применяется кнопкой,
  // как в диалоге «Настройка периода» 1С и в шапке отчёта станции. Применять на
  // каждое нажатие нельзя — первый же клик по «с» перезапросил бы отчёт за
  // полураскрытый диапазон.
  const [чС, поставитьС] = useState('')
  const [чПо, поставитьПо] = useState('')
  useEffect(() => { поставитьС(dateFrom ?? ''); поставитьПо(dateTo ?? '') }, [dateFrom, dateTo])

  const пресет = (дней: number) => {
    const по = new Date()
    const с = new Date()
    с.setDate(с.getDate() - дней)
    setPeriod({ from: день(с), to: день(по) })
  }

  const показать = () => {
    if (чС && чПо) setPeriod({ from: чС, to: чПо })
  }
  const черновикИной = (чС !== (dateFrom ?? '')) || (чПо !== (dateTo ?? ''))

  const д = отчёт.data
  const все = д?.rows ?? []
  // Бланк (товарный отчёт) узнаём по виду строк: у него порядок строк и есть
  // документ, поэтому ни сводной, ни поиска по нему быть не должно —
  // отфильтровав лист, человек получит не документ, а его обрывок.
  const бланк = все.some((r) => r.kind)
  // Поиск фильтрует только показанное на экране. На печатный лист и в книгу он
  // не влияет: там документ, и обрезанный документ — не документ.
  const строки = поиск.trim()
    ? все.filter((r) => Object.values(r).some(
        (v) => String(v ?? '').toLowerCase().includes(поиск.trim().toLowerCase())))
    : все
  const показ = useVisible(строки)

  const печатать = () => {
    открытьЛистТоварногоОтчёта({ dateFrom, dateTo, stations })
  }

  const скачать = async () => {
    скачивать(true)
    try {
      await скачатьОтчётСети(kind, { dateFrom, dateTo, stations, format: 'xlsx' })
    } finally {
      скачивать(false)
    }
  }

  if (отчёт.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Считаем по сети…</div>
  }
  if (отчёт.error) {
    return (
      <div className="p-6 text-sm text-red-400/90">
        Отчёт не собрался: {(отчёт.error as Error).message}
      </div>
    )
  }
  if (!д) return null

  const итоги = ИТОГИ.filter(({ поле }) => typeof д[поле] === 'number')

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{д.title}</h3>
          {д.about && (
            <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              {д.about}
            </p>
          )}
          {/* Контур отчёта — рядом с заголовком, а не только в верхнем фильтре:
              иначе человек смотрит на цифры и не знает, за какой они период и
              по какой станции. Период и область задаются наверху, здесь их
              видно применёнными. */}
          <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="rounded border border-border/60 bg-muted/40 px-1.5 py-0.5">
              {dateFrom && dateTo ? `${dateFrom} — ${dateTo}` : 'период не задан'}
            </span>
            <span className="rounded border border-border/60 bg-muted/40 px-1.5 py-0.5">
              {!stations?.length ? 'вся сеть'
                : stations.map((s) => `АЗС №${s}`).join(', ')}
            </span>
            {kind === 'goods-report' && (stations?.length ?? 0) !== 1 && (
              <span className="text-amber-500">
                лист сдают за одну АЗС — выберите станцию в «Области учёта»,
                иначе документы точек сложены вместе
              </span>
            )}
          </p>
        </div>
        {/* Товарный отчёт сдают листом с подписью, а не таблицей: печать
            стоит первой — в Excel такой отчёт уносят, чтобы посмотреть, а
            печатают, чтобы отчитаться. Лист тот же, что печатает станция. */}
        {kind === 'goods-report' && (
          <Button variant="outline" size="sm" className="ml-auto h-8 gap-1.5 text-xs"
            onClick={печатать}>
            <Printer className="h-3.5 w-3.5" />
            Печать листа
          </Button>
        )}
        <Button variant="outline" size="sm"
          className={`h-8 gap-1.5 text-xs${kind === 'goods-report' ? '' : ' ml-auto'}`}
          onClick={скачать} disabled={скачивается}>
          {скачивается
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Download className="h-3.5 w-3.5" />}
          Выгрузить в Excel
        </Button>
      </div>

      {итоги.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {итоги.map(({ поле, метка, деньги }) => (
            <div key={поле} className="rounded-lg border border-border/50 bg-card/40 p-3">
              <div className="text-[11px] text-muted-foreground">{метка}</div>
              <div className="mt-0.5 text-lg font-semibold tabular-nums">
                {деньги ? fmtMoney(д[поле] as number) : nf(д[поле] as number)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Уровень 4 «Параметры»: период теми же пресетами, что на станции, и
          поиск по уже посчитанным строкам. Период меняет общий контур наверху —
          второй правды о периоде в приложении быть не должно. */}
      <ViewParamsBar>
        <span className="flex items-center gap-1">
          {ПРЕСЕТЫ.map((п) => (
            <Button key={п.ключ} variant="outline" size="sm" className="h-7 px-2 text-xs"
              onClick={() => пресет(п.дней)}>
              {п.имя}
            </Button>
          ))}
        </span>
        {/* Произвольный период — теми же двумя полями и кнопкой «Показать», что
            в шапке отчёта станции. Подпись перед полем, а не над ним: строка
            остаётся строкой. */}
        <span className="flex items-center gap-1.5 text-xs">
          <label className="flex items-center gap-1">
            с
            <Input type="date" value={чС} onChange={(e) => поставитьС(e.target.value)}
              className="h-7 w-36 text-xs" />
          </label>
          <label className="flex items-center gap-1">
            по
            <Input type="date" value={чПо} onChange={(e) => поставитьПо(e.target.value)}
              className="h-7 w-36 text-xs" />
          </label>
          <Button size="sm" className="h-7 px-3 text-xs"
            variant={черновикИной ? 'default' : 'outline'}
            onClick={показать} disabled={!чС || !чПо}>
            Показать
          </Button>
        </span>

        <span className="flex items-center gap-1.5">
          <Search className="size-3.5 text-muted-foreground" />
          <Input value={поиск} onChange={(e) => искать(e.target.value)}
            placeholder="поиск по строкам" className="h-7 w-52 text-xs" />
          {поиск && (
            <span className="text-[11px] text-muted-foreground">
              {строки.length} из {все.length}
            </span>
          )}
        </span>
      </ViewParamsBar>

      {/* Уровень 3 «Вид»: список и сводная — те же две подачи, что у отчётов
          станции. У бланка подача одна: сводить документ нельзя. */}
      {!бланк && (
        <PanelViewTabs
          tabs={[{ k: 'list', label: 'Список' }, { k: 'pivot', label: 'Сводная' }]}
          value={подача} onChange={(k) => сменитьПодачу(k as 'list' | 'pivot')} />
      )}

      {подача === 'pivot' && !бланк ? (
        <ReportPivot fields={д.fields} columns={д.columns} rows={строки} />
      ) : (
      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              {д.columns.map((c, i) => (
                <th key={i} className="whitespace-nowrap px-3 py-2 text-left font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {показ.visible.map((строка, ri) => {
              // Вид строки несут только отчёты-бланки: итог выделяем полужирным,
              // раздел и остаток — курсивом на заливке, сноску печатаем во всю
              // ширину. Экран обязан читаться так же, как лист на бумаге.
              const вид = строка.kind as string | undefined
              if (вид === 'сноска') {
                return (
                  <tr key={ri} className="border-t border-border/30">
                    <td colSpan={д.fields.length}
                      className="px-3 py-2 text-[11px] italic text-muted-foreground">
                      {ячейка(строка[д.fields[0]])}
                    </td>
                  </tr>
                )
              }
              const класс = вид === 'итог'
                ? 'bg-muted/40 font-semibold'
                : вид === 'раздел' || вид === 'остаток'
                  ? 'bg-muted/20 italic font-medium'
                  : 'hover:bg-accent/20'
              return (
                <tr key={ri} className={`border-t border-border/30 ${класс}`}>
                  {д.fields.map((f, ci) => (
                    <td key={ci}
                      className={`px-3 py-1.5 ${число(строка[f]) ? 'text-right tabular-nums' : ''}`}>
                      {ячейка(строка[f])}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
        {строки.length > 300 && (
          <ShowMore {...показ} onMore={показ.more} onAll={показ.all} />
        )}
        {строки.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            За выбранный период и контур строк нет.
          </div>
        )}
      </div>
      )}
    </div>
  )
}
