/**
 * «Обзор портфеля» — рабочий экран руководителя развития, а не витрина.
 *
 * Отвечает на четыре вопроса и ни на один лишний:
 *   ЧТО ГОРИТ    — просрочки и провалы в ведении, каждая строка кликом ведёт
 *                  в нужный реестр с уже включённым фильтром;
 *   ГДЕ ЗАТЫК    — воронка со сроком стадии и проходимостью; узкое место названо;
 *   КОГДА СТАНЦИИ — прогноз ввода по датам ТП и поставок против факта;
 *   ЧТО ИЗМЕНИЛОСЬ — движение портфеля за 30 и 90 дней.
 *
 * Блок без данных не рисует нули, а честно говорит, чем его наполнить: экран из
 * нулей выглядит работающим и потому опаснее пустого места.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, Download, AlertTriangle, ChevronRight, TrendingUp } from 'lucide-react'
import { toast } from 'sonner'
import { useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import {
  getPortfolioOverview, exportPortfolioXlsx, PHASE_META, STAGE_META,
  type PortfolioOverview,
} from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const money = (v: number) => `${nf0.format(Math.round(v))} ₽`
// Куда ведёт строка «Требует внимания».
const RISK_TARGET: Record<string, { tab: string; hint: string }> = {
  step_overdue: { tab: 'pr_projects', hint: 'реестр проектов, фильтр просрочки' },
  tp_overdue: { tab: 'pr_tp', hint: 'реестр присоединений' },
  eq_overdue: { tab: 'pr_equipment', hint: 'реестр оборудования' },
  stuck_90: { tab: 'pr_projects', hint: 'реестр проектов' },
  no_touch_30: { tab: 'pr_projects', hint: 'реестр проектов' },
  no_owner: { tab: 'pr_projects', hint: 'реестр проектов' },
  no_next: { tab: 'pr_projects', hint: 'реестр проектов' },
}

export function ProjectsPortfolioPanel({ companyId }: { companyId: string }) {
  // Без списка ключей из workspaceSections: тот модуль тянет панели, а панели —
  // его, и на цикле импортов экран уходил в вечную загрузку.
  const [, setTab] = useWorkspaceSubView('pr_portfolio')
  const q = useQuery({
    queryKey: ['pr-overview', companyId],
    queryFn: () => getPortfolioOverview(companyId),
  })
  const d = q.data

  if (q.isLoading || !d) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Портфель проектов</h2>
          <p className="text-xs text-muted-foreground">
            {nf0.format(d.active)} в работе · {nf0.format(d.live)} в эксплуатации ·
            {' '}{nf0.format(d.archived)} отклонено. Срок ввода определяет присоединение, а не стройка.
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs"
          onClick={() => exportPortfolioXlsx(companyId).catch((e) =>
            toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась'))}>
          <Download className="h-3.5 w-3.5 mr-1" />Выгрузить портфель
        </Button>
      </div>

      {/* ЧТО ГОРИТ */}
      <Card className={d.atRisk > 0 ? 'border-amber-400/50' : undefined}>
        <CardContent className="p-0">
          <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
            <AlertTriangle className={`h-3.5 w-3.5 ${d.atRisk > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`} />
            <span className="text-xs font-semibold">Требует внимания</span>
            <span className="text-[11px] text-muted-foreground ml-auto">
              {d.atRisk > 0 ? `${nf0.format(d.atRisk)} проектов со сорванным сроком` : 'сорванных сроков нет'}
            </span>
          </div>
          {d.attention.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              Всё в порядке: сроки соблюдаются, у каждого проекта есть ответственный и следующий шаг.
            </div>
          ) : (
            <div className="divide-y divide-border/40">
              {d.attention.map((a) => (
                <button key={a.key} type="button"
                  onClick={() => setTab(RISK_TARGET[a.key]?.tab ?? 'pr_projects')}
                  className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-muted/40 transition-colors">
                  <span className="font-mono text-sm w-14 shrink-0 text-right">{nf0.format(a.count)}</span>
                  <span className="text-xs flex-1 min-w-0">
                    {a.label}
                    <span className="text-muted-foreground"> — {a.hint}</span>
                  </span>
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ГДЕ ЗАТЫК */}
      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
            <span className="text-xs font-semibold">Воронка: где стоим и куда не проходим</span>
            {d.bottleneck && d.bottleneck.stuck > 0 && (
              <span className="text-[11px] text-amber-700 dark:text-amber-400 ml-auto">
                узкое место — «{d.bottleneck.label}»: {nf0.format(d.bottleneck.stuck)} стоят больше 90 дней
              </span>
            )}
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground border-b">
                <th className="text-left px-3 py-1.5 font-medium">Стадия</th>
                <th className="text-right px-3 py-1.5 font-medium">Сейчас</th>
                <th className="text-right px-3 py-1.5 font-medium">Медиана, дн</th>
                <th className="text-right px-3 py-1.5 font-medium">Проходят дальше</th>
                <th className="text-right px-3 py-1.5 font-medium">Стоят &gt; 90 дн</th>
                <th className="px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {d.funnel.map((f) => {
                const hot = d.bottleneck?.stage === f.stage && f.stuck > 0
                return (
                  <tr key={f.stage} className={`border-b border-border/30 ${hot ? 'bg-amber-500/[0.06]' : ''}`}>
                    <td className="px-3 py-1.5">
                      <span className="inline-flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${STAGE_META[f.stage]?.dot ?? 'bg-zinc-400'}`} />
                        {f.label}
                        <span className={`text-[10px] rounded border px-1 ${PHASE_META[f.phase ?? '']?.cls ?? 'text-muted-foreground'}`}>
                          {PHASE_META[f.phase ?? '']?.label ?? ''}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono">{nf0.format(f.count)}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                      {f.medianDays ? f.medianDays : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                      {f.conversion != null ? `${f.conversion}%` : '—'}
                      {f.visited > 0 && <span className="text-[10px]"> ({f.advanced}/{f.visited})</span>}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono ${f.stuck ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}>
                      {f.stuck || '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {f.count > 0 && (
                        <button type="button" onClick={() => setTab('pr_projects')}
                          className="text-muted-foreground hover:text-foreground"><ChevronRight className="h-3.5 w-3.5" /></button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="px-3 py-2 text-[10px] text-muted-foreground border-t">
            «Проходят дальше» — доля проектов, побывавших на стадии и ушедших вперёд (по истории
            переходов). «Медиана» — сколько стадия занимает по факту, а не сколько числится сейчас.
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* КОГДА СТАНЦИИ */}
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 text-xs font-semibold">Когда ждать станции</div>
            {d.forecast.length === 0 && d.commissioned.length === 0 ? (
              <Empty text="Прогноз строится по срокам техприсоединения и поставки оборудования. Пока эти даты не заполнены в карточках, ждать нечего." />
            ) : (
              <div className="p-3 space-y-2">
                {d.forecast.map((f) => (
                  <Row key={`f-${f.bucket}`} label={f.bucket} value={f.count} tone="plan" />
                ))}
                {d.commissioned.length > 0 && (
                  <>
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground pt-1">Введено фактически</div>
                    {d.commissioned.map((c) => (
                      <Row key={`c-${c.bucket}`} label={c.bucket} value={c.count} tone="fact" />
                    ))}
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ЧТО ИЗМЕНИЛОСЬ */}
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-1.5">
              <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold">Движение за 30 дней</span>
            </div>
            <div className="p-3 grid grid-cols-2 gap-3 text-xs">
              <Metric label="Заведено проектов" value={d.movement.added_30}
                hint={d.movement.added_30 >= d.total ? 'банк загружен одним импортом' : `за 90 дней ${d.movement.added_90}`} />
              <Metric label="Продвинулось по воронке" value={d.movement.moved_30} />
              <Metric label="Ушло в архив" value={d.movement.archived_30} />
              <Metric label="Введено за 90 дней" value={d.movement.live_90} />
              <Metric label="Касаний с собственниками" value={d.movement.touches_30}
                hint={d.movement.touches_30 === 0 ? 'ни одного за месяц' : undefined} />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* КТО ВЕДЁТ */}
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 text-xs font-semibold">Кто ведёт</div>
            <table className="w-full text-xs">
              <tbody>
                {d.owners.map((o) => (
                  <tr key={o.owner} className="border-b border-border/30">
                    <td className="px-3 py-1.5">{o.owner}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{nf0.format(o.projects)}</td>
                    <td className={`px-3 py-1.5 text-right font-mono w-24 ${o.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                      {o.overdue ? `${o.overdue} просроч.` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* ДЕНЬГИ */}
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 text-xs font-semibold">Деньги портфеля</div>
            {d.budget.plan === 0 && d.budget.fact === 0 && d.budget.equipment === 0 ? (
              <Empty text="Бюджет ведётся в карточке проекта: статьи плана и факта на вкладке «Учёт», стоимость оборудования — на вкладке «Оборудование». Пока не заполнено." />
            ) : (
              <div className="p-3 space-y-2 text-xs">
                <Line label="План по статьям" value={money(d.budget.plan)} />
                <Line label="Факт по статьям" value={money(d.budget.fact)} />
                <Line label="Оборудование в заказе" value={money(d.budget.equipment)} />
                <div className="text-[10px] text-muted-foreground pt-1">
                  Бюджет заполнен у {nf0.format(d.budget.sites)} проектов из {nf0.format(d.active)}.
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="px-3 py-6 text-center text-xs text-muted-foreground">{text}</div>
}

function Row({ label, value, tone }: { label: string; value: number; tone: 'plan' | 'fact' }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs w-24 shrink-0">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${tone === 'fact' ? 'bg-emerald-500' : 'bg-blue-500'}`}
          style={{ width: `${Math.min(100, value * 12)}%` }} />
      </div>
      <span className="font-mono text-xs text-muted-foreground w-10 text-right">{nf0.format(value)}</span>
    </div>
  )
}

function Metric({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold leading-tight">{nf0.format(value)}</div>
      {hint && <div className="text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  )
}

export type { PortfolioOverview }
