/**
 * Шкала отчётных периодов — состояние каждого месяца сразу.
 *
 * Главный ответ на «что у меня по маю, что по июню». Одна цифра затрат ничего
 * не стоит, если неизвестно, на чём она держится: месяц, закрытый документами
 * на девяносто процентов, и месяц без единого документа дают одинаково
 * выглядящую сумму.
 *
 * Процент считается ПО ДОКУМЕНТАМ, а не по «как-нибудь закрытым строкам»: цель
 * это идеально закрытый период, а расчётная сумма — временная подпорка.
 *
 * Клик по месяцу переключает реестр ниже: шкала здесь и навигация, и диагноз.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { getOpsPeriods, type OpsPeriodRow } from '@/services/opsService'
import { formatBucket } from '@/lib/formatDate'

/** Цвет по проценту закрытия. Красный — не украшение: месяц требует работы. */
function tone(pct: number | null): { bar: string; text: string } {
  if (pct === null) return { bar: 'bg-muted', text: 'text-muted-foreground' }
  if (pct >= 90) return { bar: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400' }
  if (pct >= 60) return { bar: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400' }
  if (pct >= 25) return { bar: 'bg-orange-500', text: 'text-orange-600 dark:text-orange-400' }
  return { bar: 'bg-red-500', text: 'text-red-600 dark:text-red-400' }
}

export function OpsPeriodsScale({ current, onPick }: {
  current: string
  onPick: (period: string) => void
}) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['ops-periods', companyId],
    queryFn: () => getOpsPeriods(companyId!, 12, 2),
    enabled: !!companyId,
    // Разворот ожиданий за 14 месяцев — недёшево; в рамках сессии данные не
    // меняются сами по себе, меняет их человек, и он же жмёт «Обновить».
    staleTime: 5 * 60 * 1000,
  })

  if (q.isLoading) {
    return <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-4 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />Разворачиваю ожидания по всем периодам…
    </div>
  }
  if (q.isError || !q.data) return null

  const { periods, avgDocPct } = q.data
  const worstOpen = periods
    .filter((p) => p.status !== 'closed' && p.docPct !== null && p.total > 0)
    .sort((a, b) => (a.docPct ?? 0) - (b.docPct ?? 0))[0]

  return (
    <div data-zone="Состояние отчётных периодов"
      className="space-y-2 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-medium">Закрытие по периодам</span>
        <span className="text-xs text-muted-foreground">
          доля строк, закрытых документами контрагентов
        </span>
        {avgDocPct !== null && (
          <span className={`ml-auto text-sm font-semibold tabular-nums ${tone(avgDocPct).text}`}>
            в среднем {avgDocPct}%
          </span>
        )}
      </div>

      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {periods.map((p) => (
          <PeriodCell key={p.period} row={p} active={p.period === current}
            onPick={() => onPick(p.period)} />
        ))}
      </div>

      {worstOpen && (
        <p className="text-xs text-muted-foreground">
          Слабее всех незакрытых — <b>{formatBucket(worstOpen.period)}</b>: документов
          {' '}{worstOpen.withDoc} из {worstOpen.total}
          {worstOpen.overdue > 0 && `, просрочено ${worstOpen.overdue}`}
          {worstOpen.noBasis > 0 && `, без базы расчёта ${worstOpen.noBasis}`}.
        </p>
      )}
    </div>
  )
}

function PeriodCell({ row, active, onPick }: {
  row: OpsPeriodRow; active: boolean; onPick: () => void
}) {
  const t = tone(row.docPct)
  const empty = row.total === 0
  const title = [
    `${formatBucket(row.period)} — ${row.total} строк на ${fmtN(Math.round(row.totalGross))} ₽`,
    `документами закрыто ${row.withDoc}${row.docMoneyPct !== null ? ` (${row.docMoneyPct}% суммы)` : ''}`,
    row.accrued ? `расчётом ${row.accrued}` : null,
    row.overdue ? `просрочено ${row.overdue}` : null,
    row.noBasis ? `без базы ${row.noBasis}` : null,
    row.status === 'closed' ? 'период закрыт' : null,
  ].filter(Boolean).join('\n')

  return (
    <button type="button" onClick={onPick} title={title}
      className={`min-w-[62px] shrink-0 rounded-md border px-2 py-1.5 text-left transition-colors ${
        active ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/50'}`}>
      <div className="text-[11px] text-muted-foreground">{formatBucket(row.period)}</div>
      <div className={`text-sm font-semibold tabular-nums ${t.text}`}>
        {empty ? '—' : `${row.docPct}%`}
      </div>
      {/* Полоса — тот же процент, но читается боковым зрением: провал видно,
          не вчитываясь в цифры. */}
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full ${t.bar}`} style={{ width: `${row.docPct ?? 0}%` }} />
      </div>
      <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
        {row.status === 'closed' ? <span title="период закрыт">закрыт</span>
          : row.overdue > 0 ? <span className="text-red-600 dark:text-red-400">
              {row.overdue} просроч.</span>
          : <span>{row.total || '—'}</span>}
      </div>
    </button>
  )
}
