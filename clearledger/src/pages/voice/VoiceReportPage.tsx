/**
 * «Отчёт за месяц» — ежемесячный отчёт по линии для заказчика (план развития, этап 2):
 * пропущенные, время ответа, решённые с первого звонка и разрезы месяца.
 *
 * Отчёт считает узел (`/stats/monthly`, ContactHub docs/voice-monthly-report.md): экран
 * только показывает его, выпускает новой версией и отдаёт файлом. Выпущенный отчёт —
 * замороженная копия, не выпущенный строится на лету. Месяц и линия — в адресе
 * (`?month=2026-09&line=`): ссылку на отчёт за месяц можно переслать, а вкладка остаётся одна.
 * Номеров звонящих в отчёте нет.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Download, FileCheck2, FileText, Printer } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { скачать } from './exportTable'
import { ЧАСТЬ, процент, сек, число } from './format'
import { Heading, NodeError, Stat } from './parts'

const МЕСЯЦЫ = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const В_МЕСЯЦЕ = ['январе', 'феврале', 'марте', 'апреле', 'мае', 'июне', 'июле', 'августе', 'сентябре', 'октябре', 'ноябре', 'декабре']
const МЕСЯЦА = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const ГОДНЫЙ = /^\d{4}-(0[1-9]|1[0-2])$/

/** «сентябрь 2026» — как узел называет месяц в отчёте. */
const месяцСловами = (m: string) => `${МЕСЯЦЫ[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`

/** Месяцы от `first` до `current`, новые первыми; не больше пяти лет. */
function месяцыОтчёта(first: string | null, current: string) {
  const out: string[] = []
  let y = Number(current.slice(0, 4))
  let mo = Number(current.slice(5, 7))
  const нижний = first && first <= current ? first : current
  while (out.length < 60) {
    const m = `${y}-${String(mo).padStart(2, '0')}`
    out.push(m)
    if (m <= нижний) break
    mo -= 1
    if (mo === 0) { mo = 12; y -= 1 }
  }
  return out
}

/** Дата и время по поясу линии: «02.10.2026 06:00». */
const местное = (iso: string | null | undefined, tz: string) => (iso
  ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: tz }).replace(',', '')
  : '—')

/** Значение показателя в его единице. */
function значение(v: number | null | undefined, unit: voice.MonthlyKpi['unit']) {
  if (unit === '%') return процент(v)
  if (unit === 'с') return сек(v)
  return число(v)
}

// Куда лучше, чтобы показатель двигался: остальные (поступило, AHT, доля КЦ) — без оценки.
const ЛУЧШЕ_МЕНЬШЕ = new Set(['missedPct', 'lostPct', 'asaSec', 'waitP90Sec', 'abandonPct'])
const ЛУЧШЕ_БОЛЬШЕ = new Set(['slPct', 'answered60Pct', 'fcrPct'])
// Первыми — то, что спросит заказчик: пропущенные и ответ в пределах SL.
const ПЕРВЫЕ = ['missedPct', 'slPct']

const ЦВЕТ_ИСХОДА: Record<string, string> = {
  answered_cc: 'bg-chart-1',
  answered_local: 'bg-chart-2',
  forward_answered: 'bg-chart-4',
}
const ОТТЕНКИ_ПРОПУЩЕННЫХ = ['bg-destructive', 'bg-destructive/80', 'bg-destructive/65', 'bg-destructive/50', 'bg-destructive/35', 'bg-destructive/25']

const ОБЯЗАТЕЛЬНЫЕ = ['trunk', 'ari', 'cc', 'db']

// Узел отдаёт HTML для печати без скриптов; открываем его из blob в нашем источнике,
// поэтому на всякий случай запрещаем странице любые скрипты и внешние загрузки.
const ЗАПРЕТ = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:">'
function безСкриптов(html: string) {
  const i = html.search(/<head[^>]*>/i)
  if (i < 0) return ЗАПРЕТ + html
  const конец = html.indexOf('>', i) + 1
  return html.slice(0, конец) + ЗАПРЕТ + html.slice(конец)
}

export default function VoiceReportPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [параметры, setПараметры] = useSearchParams()
  const [выпуск, setВыпуск] = useState(false)
  const [грузим, setГрузим] = useState<'csv' | 'html' | null>(null)

  const линияВАдресе = параметры.get('line') ?? ''
  const список = useQuery({
    queryKey: ['voice-monthly-list', companyId],
    queryFn: () => voice.monthlyList(companyId),
  })
  const опр = useQuery({
    queryKey: ['voice-stats-defs', companyId],
    queryFn: () => voice.statsDefinitions(companyId),
    staleTime: Infinity,
  })

  const месяцы = useMemo(() => (список.data ? месяцыОтчёта(список.data.first, список.data.current) : []), [список.data])
  const изАдреса = параметры.get('month') ?? ''
  const месяц = ГОДНЫЙ.test(изАдреса) && месяцы.includes(изАдреса) ? изАдреса : список.data?.current ?? ''
  const линии = список.data?.lines ?? []
  const линия = линии.some(l => l.lineId === линияВАдресе) ? линияВАдресе : ''

  const отчёт = useQuery({
    queryKey: ['voice-monthly', companyId, месяц, линия],
    queryFn: () => voice.monthlyReport(companyId, месяц, линия || undefined),
    enabled: !!месяц,
    // при смене месяца прежний отчёт остаётся на экране, пока узел собирает новый
    placeholderData: keepPreviousData,
  })
  const r = отчёт.data
  const прежний = отчёт.isPlaceholderData
  const линияОтчёта = r?.lineId ?? (линия || линии[0]?.lineId)
  const выпущены = new Map((список.data?.items ?? []).filter(x => x.lineId === линияОтчёта).map(x => [x.month, x]))

  const пояснение = useMemo(() => {
    const map = new Map((опр.data ?? []).map(d => [d.key, `${d.title}: ${d.formula}`]))
    return (k: string) => map.get(k)
  }, [опр.data])

  function открыть(м: string, л = линия) {
    const p = new URLSearchParams(параметры)
    if (м && м !== список.data?.current) p.set('month', м); else p.delete('month')
    if (л) p.set('line', л); else p.delete('line')
    setПараметры(p, { replace: true })
  }

  const i = месяцы.indexOf(месяц)
  const старше = i >= 0 ? месяцы[i + 1] : undefined
  const новее = i > 0 ? месяцы[i - 1] : undefined

  async function выгрузить(формат: 'csv' | 'html') {
    if (!месяц) return
    // Окно открываем сразу по нажатию: открытое после ответа узла браузер сочтёт всплывающим.
    const окно = формат === 'html' ? window.open('', '_blank') : null
    if (окно) окно.opener = null
    setГрузим(формат)
    try {
      const { blob, имя } = await voice.monthlyExport(companyId, месяц, формат, линия || undefined)
      if (формат === 'html') {
        const страница = new Blob([безСкриптов(await blob.text())], { type: 'text/html;charset=utf-8' })
        if (окно) {
          const url = URL.createObjectURL(страница)
          окно.location.href = url
          setTimeout(() => URL.revokeObjectURL(url), 60_000)
        } else {
          скачать(страница, имя)
        }
      } else {
        скачать(blob, имя)
      }
    } catch (e) {
      окно?.close()
      toast.error(e instanceof Error ? `Выгрузка не удалась: ${e.message}` : 'Выгрузка не удалась')
    } finally {
      setГрузим(null)
    }
  }

  const идёт = r?.status === 'current'
  const нетЗвонков = !!r && !(r.metrics.arrived ?? 0) && !(r.metrics.offered ?? 0)

  return (
    <div className="space-y-4 p-4">
      <Heading имя="Отчёт за месяц"
        подпись="Отчёт по линии для заказчика: пропущенные, время ответа, решённые с первого звонка. Номеров звонящих в нём нет.">
        <Button variant="outline" size="sm" disabled={!r || прежний || !!грузим} onClick={() => void выгрузить('csv')}>
          <Download />{грузим === 'csv' ? 'Готовим…' : 'Скачать для Excel'}
        </Button>
        <Button variant="outline" size="sm" disabled={!r || прежний || !!грузим} onClick={() => void выгрузить('html')}
          title="Страница A4: PDF — печатью из браузера">
          <Printer />{грузим === 'html' ? 'Готовим…' : 'Страница для печати'}
        </Button>
        <Button size="sm" disabled={!r || прежний || идёт} onClick={() => setВыпуск(true)}
          title={идёт ? 'Месяц ещё идёт: выпустить отчёт можно после его конца' : undefined}>
          <FileCheck2 />{r?.status === 'issued' ? 'Выпустить заново' : 'Выпустить'}
        </Button>
      </Heading>

      {список.isLoading && <p role="status" className="text-sm">Читаем отчёты у узла…</p>}
      {список.isError && <NodeError ошибка={список.error} что="прочитать список отчётов" />}

      {!!месяцы.length && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" aria-label="Месяц раньше" disabled={!старше} onClick={() => старше && открыть(старше)}>
              <ChevronLeft />
            </Button>
            <select value={месяц} onChange={e => открыть(e.target.value)} aria-label="Месяц"
              className="h-9 min-w-0 max-w-[min(22rem,70vw)] rounded-md border border-input bg-background px-2 text-sm">
              {месяцы.map(м => {
                const в = выпущены.get(м)
                return (
                  <option key={м} value={м}>
                    {месяцСловами(м)}{м === список.data?.current ? ' · идёт' : в ? ` · выпущен, версия ${в.version}` : ''}
                  </option>
                )
              })}
            </select>
            <Button variant="outline" size="icon" aria-label="Месяц позже" disabled={!новее} onClick={() => новее && открыть(новее)}>
              <ChevronRight />
            </Button>
          </div>
          {линии.length > 1 && (
            <select value={линия || линии[0].lineId} onChange={e => открыть(месяц, e.target.value === линии[0].lineId ? '' : e.target.value)}
              aria-label="Линия" className="h-9 min-w-0 max-w-[min(22rem,70vw)] rounded-md border border-input bg-background px-2 text-sm">
              {линии.map(l => <option key={l.lineId} value={l.lineId}>{l.name || l.lineId}</option>)}
            </select>
          )}
        </div>
      )}

      {(отчёт.isLoading || прежний) && <p role="status" className="text-sm">Узел собирает отчёт…</p>}
      {отчёт.isError && (
        <div className="space-y-2">
          <NodeError ошибка={отчёт.error} что="построить отчёт" />
          {отчёт.error instanceof voice.VoiceError && отчёт.error.status === 400 && (
            <Button variant="outline" size="sm" onClick={() => открыть('')}>Открыть текущий месяц</Button>
          )}
        </div>
      )}

      {r && (
        <div className={cn('space-y-4', прежний && 'pointer-events-none opacity-50')} aria-busy={прежний}>
          <StatusPlate r={r} />
          {нетЗвонков && (
            <EmptyBlock иконка={FileText} текст={`За ${r.title} звонков не было`}
              подсказка="Плитки пустые, но отчёт можно скачать и выпустить — заказчик увидит, что звонков не было." />
          )}
          <Kpis r={r} пояснение={пояснение} />
          {!нетЗвонков && (
            <>
              <Outcomes r={r} />
              <Speed r={r} пояснение={пояснение} />
              <Days r={r} />
              <Hours r={r} />
              <Topics r={r} />
            </>
          )}
          <Reconciliations r={r} />
          <div className="grid gap-4 xl:grid-cols-2">
            {!нетЗвонков && <Callbacks m={r.metrics} пояснение={пояснение} />}
            <Availability r={r} />
          </div>
          <HowCounted r={r} />
        </div>
      )}

      {r && !прежний && (
        <IssueDialog открыт={выпуск} r={r} onClose={() => setВыпуск(false)}
          onIssue={async комментарий => {
            const н = await voice.issueMonthly(companyId, месяц, { comment: комментарий, line: линия || undefined })
            qc.setQueryData(['voice-monthly', companyId, месяц, линия], н)
            await qc.invalidateQueries({ queryKey: ['voice-monthly-list', companyId] })
            toast.success(`Отчёт за ${н.title} выпущен, версия ${н.version}`)
          }} />
      )}
    </div>
  )
}

// ——— Состояние отчёта ———

function StatusPlate({ r }: { r: voice.MonthlyReport }) {
  if (r.status === 'issued') {
    return (
      <div role="status" className="space-y-0.5 rounded-xl border border-success/40 bg-success/5 p-3 text-sm">
        <p>
          <span className="font-medium">Выпущен {местное(r.issuedAt, r.tz)}</span>, версия {r.version}
          {r.issuedBy && `, ${r.issuedBy}`}.
        </p>
        {r.comment && <p className="text-muted-foreground">Комментарий: {r.comment}</p>}
        <p className="text-xs text-muted-foreground">Выпущенный отчёт не меняется, даже если журнал звонков поправят позже.</p>
      </div>
    )
  }
  if (r.status === 'preliminary') {
    return (
      <div role="status" className="rounded-xl border border-warning/50 bg-warning/5 p-3 text-sm">
        Месяц закончился, отчёт ещё не выпущен. Узел выпустит его сам 2-го числа после 06:00; до выпуска цифры
        могут уточниться (поздние итоги, обратные звонки).
      </div>
    )
  }
  return (
    <div role="status" className="rounded-xl border border-border bg-card p-3 text-sm">
      Текущий месяц, данные на {местное(r.builtAt, r.tz)}. Отчёт выпускается после конца месяца.
    </div>
  )
}

// ——— Главное ———

function Kpis({ r, пояснение }: { r: voice.MonthlyReport; пояснение: (k: string) => string | undefined }) {
  const порядок = [...r.kpis].sort((a, b) => {
    const ia = ПЕРВЫЕ.indexOf(a.key)
    const ib = ПЕРВЫЕ.indexOf(b.key)
    return (ia < 0 ? ПЕРВЫЕ.length : ia) - (ib < 0 ? ПЕРВЫЕ.length : ib)
  })
  const прошлый = r.previous?.month ? В_МЕСЯЦЕ[Number(r.previous.month.slice(5, 7)) - 1] : null
  return (
    <section aria-label="Главное" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {порядок.map(k => <KpiTile key={k.key} k={k} прошлый={прошлый} пояснение={пояснение(k.key)} />)}
    </section>
  )
}

function KpiTile({ k, прошлый, пояснение }: { k: voice.MonthlyKpi; прошлый: string | null; пояснение?: string }) {
  const разница = k.value != null && k.previous != null ? k.value - k.previous : null
  const оценка = разница == null || разница === 0 ? null
    : ЛУЧШЕ_МЕНЬШЕ.has(k.key) ? (разница < 0 ? 'лучше' : 'хуже')
      : ЛУЧШЕ_БОЛЬШЕ.has(k.key) ? (разница > 0 ? 'лучше' : 'хуже') : null
  const сдвиг = разница == null ? null
    : k.unit === '%' ? `${Math.abs(Math.round(разница * 10) / 10).toLocaleString('ru-RU')} п. п.`
      : k.unit === 'с' ? сек(Math.abs(разница)) : число(Math.abs(разница))
  return (
    <div title={пояснение} className={cn('space-y-1 rounded-xl border bg-card p-3',
      k.met === false ? 'border-destructive/40' : 'border-border')}>
      <p className="text-xs text-muted-foreground">{k.title}</p>
      <p className="font-headline text-2xl font-semibold tabular-nums">{значение(k.value, k.unit)}</p>
      {прошлый && (
        <p className="text-xs text-muted-foreground">
          в {прошлый}: {значение(k.previous, k.unit)}
          {сдвиг && разница !== 0 && (
            <span className={cn('ml-1', оценка === 'лучше' && 'text-success', оценка === 'хуже' && 'text-destructive')}>
              {разница! > 0 ? '↑' : '↓'} {сдвиг}
            </span>
          )}
        </p>
      )}
      {k.target && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">норма {k.target.op === 'lt' ? '<' : '≥'} {значение(k.target.value, k.unit)}</span>
          {k.met === true && <span className="text-success">выполнена</span>}
          {k.met === false && <span className="text-destructive">не выполнена</span>}
          {k.target.stub && (
            <span title={k.target.source} className="rounded border border-border px-1 text-[11px] leading-4 text-muted-foreground">заглушка</span>
          )}
        </p>
      )}
    </div>
  )
}

// ——— Куда ушли звонки и скорость ответа ———

function Outcomes({ r }: { r: voice.MonthlyReport }) {
  let пропущенный = 0
  const части = r.outcomes.map(o => ({
    ...o,
    цвет: ЦВЕТ_ИСХОДА[o.key] ?? (o.key.startsWith('missed_')
      ? ОТТЕНКИ_ПРОПУЩЕННЫХ[Math.min(пропущенный++, ОТТЕНКИ_ПРОПУЩЕННЫХ.length - 1)] : 'bg-border'),
  }))
  const всего = r.metrics.arrived ?? 0
  return (
    <section aria-label="Куда ушли звонки" className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Куда ушли звонки</h2>
      {!!всего && (
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-border" aria-hidden="true">
          {части.filter(x => x.count).map(x => <div key={x.key} className={x.цвет} style={{ width: `${(x.count / всего) * 100}%` }} />)}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full max-w-2xl text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="whitespace-nowrap py-1 font-normal">Исход</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Звонков</th>
              <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">% от поступивших</th></tr>
          </thead>
          <tbody>
            {части.map(x => (
              <tr key={x.key} className="border-t border-border/60">
                <td className="py-1.5"><span className="inline-flex items-center gap-2"><i className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', x.цвет)} />{x.title}</span></td>
                <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(x.count)}</td>
                <td className="w-36 py-1.5 text-right tabular-nums text-muted-foreground">{процент(x.pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Пропущено всего {число(r.metrics.missed)} ({процент(r.metrics.missedPct)}), из них перезвонили и дозвонились — {число(r.metrics.missedReached)}.
        Звонки, пришедшие переводом с другой линии, сюда не входят.
      </p>
    </section>
  )
}

function Speed({ r, пояснение }: { r: voice.MonthlyReport; пояснение: (k: string) => string | undefined }) {
  if (!r.answeredWithin?.length) return null
  return (
    <section aria-label="Скорость ответа" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Скорость ответа</h2>
      <p className="text-xs text-muted-foreground" title={пояснение('slPct')}>
        Доля — как у SL: от поставленных в очередь без коротких отказов (положили трубку быстрее {r.params.shortAbandonSec ?? '—'} с).
      </p>
      <ul className="max-w-2xl space-y-1.5">
        {r.answeredWithin.map(x => (
          <li key={x.sec} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2 text-sm">
            <span className={cn(x.sec === r.params.slaTargetSec && 'font-medium')}>быстрее {x.sec} с</span>
            <span className="h-2 overflow-hidden rounded-full bg-border" aria-hidden="true">
              <span className="block h-full rounded-full bg-chart-1" style={{ width: `${Math.min(100, x.pct ?? 0)}%` }} />
            </span>
            <span className="w-28 whitespace-nowrap text-right tabular-nums">{процент(x.pct)} <span className="text-muted-foreground">({число(x.answered)})</span></span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ——— По дням и по часам ———

const выходной = (date: string) => { const d = new Date(`${date}T12:00:00Z`).getUTCDay(); return d === 0 || d === 6 }

function Columns({ ряды, подпись }: {
  ряды: { key: string; метка: string; всего: number; пропущено: number; бледно?: boolean; подсказка: string }[]
  подпись: (i: number) => boolean
}) {
  const наибольшее = Math.max(1, ...ряды.map(x => x.всего))
  return (
    <>
      <div className="flex h-40 items-end gap-0.5" aria-hidden="true">
        {ряды.map(x => (
          <div key={x.key} title={x.подсказка} className={cn('flex h-full min-w-1 flex-1 flex-col justify-end', x.бледно && 'opacity-55')}>
            <div className="rounded-t-sm bg-chart-1" style={{ height: `${((x.всего - x.пропущено) / наибольшее) * 100}%` }} />
            <div className="bg-destructive" style={{ height: `${(x.пропущено / наибольшее) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="flex gap-0.5 text-[10px] leading-3 text-muted-foreground" aria-hidden="true">
        {ряды.map((x, i) => <span key={x.key} className="min-w-1 flex-1 text-center">{подпись(i) ? x.метка : ''}</span>)}
      </div>
      <ul className="flex flex-wrap gap-x-4 text-xs">
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-chart-1" />не пропущено</li>
        <li className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm bg-destructive" />пропущено</li>
      </ul>
    </>
  )
}

function Days({ r }: { r: voice.MonthlyReport }) {
  const ряды = r.days.map(d => ({
    key: d.date, метка: String(Number(d.date.slice(8, 10))), всего: d.metrics.arrived ?? 0, пропущено: d.metrics.missed ?? 0,
    бледно: выходной(d.date),
    подсказка: `${Number(d.date.slice(8, 10))} ${МЕСЯЦА[Number(d.date.slice(5, 7)) - 1]}: поступило ${d.metrics.arrived ?? 0}, пропущено ${d.metrics.missed ?? 0}`,
  }))
  return (
    <section aria-label="По дням" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">По дням</h2>
      <Columns ряды={ряды} подпись={i => ряды.length <= 16 || i % 2 === 0} />
      <p className="text-xs text-muted-foreground">Выходные — светлее. День без звонков — нулевой столбик.</p>
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground">Таблица по дням</summary>
        <div className="overflow-x-auto">
          <table className="mt-1 w-full min-w-[46rem] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                {['Дата', 'Поступило', 'Отвечено', 'Пропущено', '%', 'SL', 'ASA', 'Брошено', 'FCR', 'AHT'].map((h, i) => (
                  <th key={h} className={cn('py-1 font-normal', i && 'text-right')}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {r.days.map(d => (
                <tr key={d.date} className={cn('border-t border-border/60', выходной(d.date) && 'text-muted-foreground')}>
                  <td className="py-1">{Number(d.date.slice(8, 10))} {МЕСЯЦА[Number(d.date.slice(5, 7)) - 1]}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{число(d.metrics.arrived ?? 0)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{число(d.metrics.answered ?? 0)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{число(d.metrics.missed ?? 0)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{процент(d.metrics.missedPct)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{процент(d.metrics.slPct)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{сек(d.metrics.asaSec)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{процент(d.metrics.abandonPct)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{процент(d.metrics.fcrPct)}</td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">{сек(d.metrics.ahtSec)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

function Hours({ r }: { r: voice.MonthlyReport }) {
  const ряды = r.hours.map(h => ({
    key: String(h.hour), метка: String(h.hour), всего: h.metrics.arrived ?? 0, пропущено: h.metrics.missed ?? 0,
    подсказка: `${h.hour}:00–${h.hour + 1}:00: поступило ${h.metrics.arrived ?? 0}, пропущено ${h.metrics.missed ?? 0}`,
  }))
  return (
    <section aria-label="По часам суток" className="space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">По часам суток</h2>
      <p className="text-xs text-muted-foreground">Весь месяц по часу звонка ({r.tz}): видно, в какие часы не хватает людей.</p>
      <Columns ряды={ряды} подпись={i => i % 3 === 0} />
    </section>
  )
}

// ——— Темы, обратные звонки ———

function Topics({ r }: { r: voice.MonthlyReport }) {
  return (
    <section aria-label="По темам" className="min-w-0 space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">По темам</h2>
      {!r.topics.length ? <p className="text-sm text-muted-foreground">Тем за месяц нет: в итогах звонков тему не записывали.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="whitespace-nowrap py-1 font-normal">Тема (код итога)</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Отвечено</th>
                <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">AHT</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">FCR</th>
                <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Переводы</th></tr>
            </thead>
            <tbody>
              {r.topics.map(t => (
                <tr key={t.topic} className="border-t border-border/60">
                  <td className="min-w-[9rem] break-all py-1.5 font-mono text-xs">{t.topic}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(t.metrics.answered)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{сек(t.metrics.ahtSec)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{процент(t.metrics.fcrPct)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{процент(t.metrics.transferPct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Callbacks({ m, пояснение }: { m: voice.Metrics; пояснение: (k: string) => string | undefined }) {
  return (
    <section aria-label="Обратные звонки" className="min-w-0 space-y-3 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Обратные звонки</h2>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Stat имя="Предложено" значение={число(m.callbackOffered)} пояснение={пояснение('callbackOffered')} />
        <Stat имя="Выбрали" значение={число(m.callbackAccepted)} пояснение={пояснение('callbackAccepted')} />
        <Stat имя="Поставлено" значение={число(m.callbackCreated)} пояснение={пояснение('callbackCreated')} />
        <Stat имя="Исполнено" значение={число(m.callbackExecuted)} пояснение={пояснение('callbackExecuted')} />
        <Stat имя="Дозвонились" значение={число(m.callbackReached)} пояснение={пояснение('callbackReached')} />
        <Stat имя="Просрочено" значение={число(m.callbackOverdue)} пояснение={пояснение('callbackOverdue')}
          тон={(m.callbackOverdue ?? 0) > 0 ? 'warning' : undefined} />
        <Stat имя="Пропущенным перезвонили" значение={число(m.missedReached)} пояснение={пояснение('missedReached')} />
      </div>
    </section>
  )
}

// ——— Сверка и работа узла ———

function Reconciliations({ r }: { r: voice.MonthlyReport }) {
  const сверки = r.reconciliations ?? []
  const день = (iso?: string) => (iso ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', timeZone: r.tz }) : '—')
  return (
    <section aria-label="Сверка с оператором связи" className="min-w-0 space-y-2 rounded-xl border border-border bg-card p-4">
      <h2 className="font-headline text-base font-semibold">Сверка с оператором связи</h2>
      {!сверки.length ? (
        <p className="text-sm text-muted-foreground">За месяц сверок с детализацией оператора связи не было.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="whitespace-nowrap py-1 font-normal">Период</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">У оператора</th>
                <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Совпало</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Нет у узла</th>
                <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Нет у оператора</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Длительность</th></tr>
            </thead>
            <tbody>
              {сверки.map(с => (
                <tr key={с.id} className="border-t border-border/60">
                  <td className="whitespace-nowrap py-1.5">{день(с.period?.from)} – {день(с.period?.to)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.carrierRows)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.matched)}</td>
                  <td className={cn('whitespace-nowrap py-1.5 pl-3 text-right tabular-nums', (с.onlyCarrier ?? 0) > 0 && 'font-medium text-destructive')}>{число(с.onlyCarrier)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.onlyNode)}</td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(с.durationMismatch)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">«Нет у узла» — звонок есть в детализации оператора, но узел его не видел: это потеря.</p>
    </section>
  )
}

function Availability({ r }: { r: voice.MonthlyReport }) {
  const a = r.availability
  return (
    <section aria-label="Работа узла" className="min-w-0 space-y-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="mr-auto font-headline text-base font-semibold">Работа узла</h2>
        <Link to="/voice/health" className="text-xs text-primary underline-offset-2 hover:underline">Состояние узла</Link>
      </div>
      {!a ? <p className="text-sm text-muted-foreground">Журнала состояния узла за месяц нет.</p> : (
        <>
          <p className="text-sm">Перезапусков узла: {число(a.restarts)}.</p>
          <table className="w-full max-w-md text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="whitespace-nowrap py-1 font-normal">Обязательная часть</th><th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Не работала</th>
                <th className="whitespace-nowrap py-1 pl-3 text-right font-normal">Раз</th></tr>
            </thead>
            <tbody>
              {ОБЯЗАТЕЛЬНЫЕ.filter(p => p in a.downMin).map(p => (
                <tr key={p} className="border-t border-border/60">
                  <td className="py-1.5">{ЧАСТЬ[p] ?? p}</td>
                  <td className={cn('whitespace-nowrap py-1.5 pl-3 text-right tabular-nums', a.downMin[p] > 0 && 'text-destructive')}>
                    {a.downMin[p] ? сек(a.downMin[p] * 60) : 'ни разу'}
                  </td>
                  <td className="whitespace-nowrap py-1.5 pl-3 text-right tabular-nums">{число(a.downs?.[p] ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.status === 'current' && a.until && <p className="text-xs text-muted-foreground">По {местное(a.until, r.tz)}.</p>}
        </>
      )}
    </section>
  )
}

function HowCounted({ r }: { r: voice.MonthlyReport }) {
  const п = r.params
  return (
    <details className="rounded-xl border border-border bg-card p-4 text-sm">
      <summary className="cursor-pointer font-medium">Как считали</summary>
      <div className="space-y-1.5 pt-2 text-muted-foreground">
        <p>
          Цель SL линии — {п.slaTargetSec ?? '—'} с; окно FCR — {п.fcrWindowMin ?? '—'} мин; короткий отказ — до {п.shortAbandonSec ?? '—'} с;
          срок обратного звонка — {сек(п.callbackDueSec)}; порог тревоги SL — {процент(п.alertSlPct)}.
        </p>
        <p>Пропущено — звонок закончился, ни разу не соединившись с человеком: оператором контакт-центра, сотрудником или переадресацией.</p>
        <p>Нормы с пометкой «заглушка» не из договора: сверим их с приложениями к договору 451083.</p>
        <p>Месяц — календарный, время местное по поясу линии ({r.tz}). Прошлый месяц для сравнения — его выпущенная версия, иначе посчитанный сейчас.</p>
      </div>
    </details>
  )
}

// ——— Выпуск ———

function IssueDialog({ открыт, r, onClose, onIssue }: {
  открыт: boolean
  r: voice.MonthlyReport
  onClose: () => void
  onIssue: (комментарий: string | undefined) => Promise<void>
}) {
  const [текст, setТекст] = useState('')
  const [идёт, setИдёт] = useState(false)
  const заново = r.status === 'issued'
  const т = текст.trim()
  const годен = заново ? т.length >= 3 : !т || т.length >= 3

  async function выпустить() {
    if (!годен) return
    setИдёт(true)
    try {
      await onIssue(т || undefined)
      setТекст('')
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Отчёт не выпущен')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <Dialog open={открыт} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{заново ? 'Выпустить заново' : 'Выпустить'} отчёт за {r.title}</DialogTitle>
          <DialogDescription>
            Узел пересчитает показатели месяца по журналу и сохранит отчёт версией {(r.version ?? 0) + 1}.
            Выпущенный отчёт не меняется, даже если журнал поправят позже.
          </DialogDescription>
        </DialogHeader>
        <label className="block space-y-1 text-xs text-muted-foreground">
          <span className="block">Комментарий{заново ? ' — зачем выпуск заново' : ' (необязательно)'}</span>
          <Textarea value={текст} onChange={e => setТекст(e.target.value)} maxLength={500} rows={3}
            placeholder={заново ? 'Например: учли сверку с детализацией оператора связи' : 'Например: отчёт для заказчика за сентябрь'} />
        </label>
        {!годен && !!т && <p className="text-xs text-destructive">Комментарий — от 3 знаков.</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={выпустить} disabled={!годен || идёт}>{идёт ? 'Выпускаем…' : заново ? 'Выпустить заново' : 'Выпустить'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
