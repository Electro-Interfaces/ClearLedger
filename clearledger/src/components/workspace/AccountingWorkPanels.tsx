/**
 * Экраны «Бухгалтерии», которых до разреза по потокам не было.
 *
 * Три потока живут по разным законам, и главное различие — кто продюсер документа:
 *
 *   НЕФТЕПРОДУКТЫ — документы в БП создаёт САМО расширение TradeLedger.cfe,
 *                   обращаясь к STS напрямую. Ledger идёт параллельно, поэтому
 *                   его экран закрытия — «Контроль загрузки», а не выгрузка.
 *   МАГАЗИН       — пакет «смена→БП» собирает Ledger, и выгрузка здесь реальна.
 *   ОБЩЕПИТ       — едет ТЕМ ЖЕ пакетом, что магазин: одна смена — один файл.
 *                   Своей кнопки выгрузки нет и быть не должно; экран показывает
 *                   разрез этого пакета — блюда, техкарты, комплектации.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, CalendarCheck, CheckCircle2, ChefHat, FileText,
  Fuel, Loader2, ShoppingCart, Users,
} from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { getFuelReadiness } from '@/services/fuel/fuelMappingService'
import { getReconciliationSummary } from '@/services/accountingDocService'
import { getStoreShifts, getBpPackage, getStoreCateringMenu } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const fmtN = (v: number) => (v ?? 0).toLocaleString('ru-RU')

/* ══════════════════════════════════════════════════════════════════════════ */
/*  ПЕРИОД · где стоит закрытие по трём потокам сразу                         */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Экран, с которого начинается рабочий день: три потока одной строкой каждый и
 * список того, что мешает закрыть месяц.
 *
 * Считается по тем же данным, что и рабочие экраны потоков, — своего источника
 * правды тут нет намеренно: расхождение сводки с разделом означало бы, что одна
 * из двух цифр врёт, а какая — выяснять уже некому.
 */
export function AccountingPeriodPanel() {
  const { companyId } = useCompany()
  const { period } = useFilters()
  const { setCoreMode } = useWorkspace()

  const fuel = useQuery({
    queryKey: ['fuel-readiness', companyId, period.from, period.to],
    queryFn: () => getFuelReadiness(period.from, period.to),
  })
  const store = useQuery({
    queryKey: ['store-shifts', companyId, period.from, period.to],
    queryFn: () => getStoreShifts(period.from, period.to),
  })
  const recon = useQuery({
    queryKey: ['reconciliation-summary', companyId],
    queryFn: () => getReconciliationSummary(companyId),
  })

  const shifts = store.data?.shifts ?? []
  const soputka = shifts.reduce((s, r) => s + (r.soputka ?? 0), 0)
  const obshepit = shifts.reduce((s, r) => s + (r.obshepit ?? 0), 0)
  const withFood = shifts.filter((r) => (r.obshepit ?? 0) > 0).length
  const rs = recon.data
  const noOneC = !rs || rs.totalAccDocs === 0

  const loading = fuel.isLoading || store.isLoading

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Статус закрытия</h2>
        <span className="text-xs text-muted-foreground">
          {period.from} — {period.to} · три потока, три способа доставки в БП ГИГ
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Собираем состояние периода…
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          <StreamCard
            icon={Fuel}
            title="Нефтепродукты"
            source="STS → расширение 1С"
            rows={[
              { label: 'Смен собрано', value: fmtN(fuel.data?.shifts.total ?? 0) },
              { label: 'С правками', value: fmtN(fuel.data?.shifts.corrected ?? 0) },
              { label: 'ТТН принято', value: `${fmtN(fuel.data?.receipts.confirmed ?? 0)} из ${fmtN(fuel.data?.receipts.total ?? 0)}` },
            ]}
            alert={(fuel.data?.receipts.pending ?? 0) > 0
              ? `${fmtN(fuel.data!.receipts.pending)} ТТН ждут подтверждения приёмки`
              : undefined}
            action={{ label: 'Контроль загрузки', onClick: () => setCoreMode('accounting', 'recon1c') }}
          />
          <StreamCard
            icon={ShoppingCart}
            title="Магазин"
            source="ЦБ / edge → пакет Ledger"
            rows={[
              { label: 'Смен за период', value: fmtN(store.data?.summary.count ?? 0) },
              { label: 'Выручка сопутки', value: fmtMoney(soputka) },
              { label: 'Возвраты', value: fmtMoney(store.data?.summary.returns ?? 0) },
            ]}
            alert={(store.data?.summary.count ?? 0) === 0
              ? 'За период не загружено ни одной смены'
              : undefined}
            action={{ label: 'Пакет в БП', onClick: () => setCoreMode('acc_store', 'export') }}
          />
          <StreamCard
            icon={ChefHat}
            title="Общепит"
            source="тот же пакет, свой разрез"
            rows={[
              { label: 'Смен с кухней', value: `${fmtN(withFood)} из ${fmtN(shifts.length)}` },
              { label: 'Выручка блюд', value: fmtMoney(obshepit) },
              { label: 'Доля в товарной выручке', value: soputka + obshepit > 0
                ? `${Math.round((obshepit / (soputka + obshepit)) * 100)}%` : '—' },
            ]}
            action={{ label: 'Комплектация в пакете', onClick: () => setCoreMode('acc_food', 'food_release') }}
          />
        </div>
      )}

      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2">
            <CalendarCheck className="h-4 w-4 text-primary" />
            <h3 className={H3}>Что мешает закрыть период</h3>
          </div>
          <ul className="space-y-1.5">
            <Blocker
              done={(fuel.data?.receipts.pending ?? 0) === 0}
              text={(fuel.data?.receipts.pending ?? 0) === 0
                ? 'Все ТТН топлива подтверждены'
                : `${fmtN(fuel.data?.receipts.pending ?? 0)} ТТН топлива не подтверждены — приёмка обязана быть сверена до загрузки`}
              go={() => setCoreMode('accounting', 'ttn')}
            />
            <Blocker
              done={(store.data?.summary.count ?? 0) > 0}
              text={(store.data?.summary.count ?? 0) > 0
                ? `Смены магазина загружены: ${fmtN(store.data!.summary.count)}`
                : 'Смены магазина за период не загружены — проверьте приём данных из ЦБ'}
              go={() => setCoreMode('acc_store', 'cb_load')}
            />
            <Blocker
              done={!noOneC}
              text={noOneC
                ? 'Документы из 1С не загружены — сверить наши факты не с чем'
                : `Сопоставлено с 1С: ${fmtN(rs!.matched)} из ${fmtN(rs!.totalEntries)}; расхождений ${fmtN(rs!.discrepancy)}`}
              go={() => setCoreMode('acc_recon', 'recon_docs')}
            />
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

function StreamCard({ icon: Icon, title, source, rows, alert, action }: {
  icon: typeof Fuel
  title: string
  source: string
  rows: { label: string; value: string }[]
  alert?: string
  action: { label: string; onClick: () => void }
}) {
  return (
    <Card>
      <CardContent className="flex h-full flex-col pt-4">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">{title}</span>
        </div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{source}</p>

        <dl className="mt-3 space-y-1.5">
          {rows.map((r) => (
            <div key={r.label} className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-muted-foreground">{r.label}</dt>
              <dd className="text-sm font-medium tabular-nums">{r.value}</dd>
            </div>
          ))}
        </dl>

        {alert && (
          <p className="mt-3 flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            {alert}
          </p>
        )}

        <Button variant="outline" size="sm" className="mt-auto h-8 w-full justify-between pt-0 text-xs"
          onClick={action.onClick}>
          {action.label}
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </CardContent>
    </Card>
  )
}

function Blocker({ done, text, go }: { done: boolean; text: string; go: () => void }) {
  return (
    <li>
      <button onClick={go}
        className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent/40">
        {done
          ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />}
        <span className={cn('flex-1', done && 'text-muted-foreground')}>{text}</span>
        <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
      </button>
    </li>
  )
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  НЕФТЕПРОДУКТЫ · контроль загрузки в 1С                                    */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Топливо в БП попадает не отсюда: расширение TradeLedger.cfe тянет смены и ТТН
 * из STS API напрямую (TL_ApiКлиент) и создаёт документы у себя. Поэтому здесь
 * не выгрузка, а контроль — что бухгалтер уже загрузил формой TL_Загрузка, а что
 * ещё нет.
 *
 * Прежний экран показывал воронку пакетов draft→queued→sent→acked. Она не
 * двигалась и двигаться не могла: очередь `/export-packets/queue` реализована, но
 * из расширения к ней никто не обращается. Рисовать процесс, которого нет, —
 * худшее, что может делать экран закрытия периода.
 */
export function FuelLoadControlPanel() {
  const { companyId } = useCompany()
  const { period } = useFilters()
  const nav = useNavigate()

  const readiness = useQuery({
    queryKey: ['fuel-readiness', companyId, period.from, period.to],
    queryFn: () => getFuelReadiness(period.from, period.to),
  })
  const recon = useQuery({
    queryKey: ['reconciliation-summary', companyId],
    queryFn: () => getReconciliationSummary(companyId),
  })

  const rs = recon.data
  const noOneC = !rs || rs.totalAccDocs === 0
  const r = readiness.data

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Контроль загрузки в 1С</h2>
        <span className="text-xs text-muted-foreground">
          {period.from} — {period.to} · что уже в БП ГИГ, а что ещё нет
        </span>
      </div>

      <Card>
        <CardContent className="pt-4">
          <p className="text-xs leading-relaxed text-muted-foreground">
            Топливо расширение <span className="font-medium text-foreground">TradeLedger.cfe</span> забирает
            из STS само и создаёт документы в БП по кнопке бухгалтера («Обновить» → «Загрузить выбранные» →
            «Провести»). Ledger в этой цепочке — второй счёт: он копит те же факты, даёт править их
            до загрузки и показывает, сошлось ли в итоге.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Смен за период" value={fmtN(r?.shifts.total ?? 0)}
          hint={`${fmtN(r?.shifts.corrected ?? 0)} с ручными правками`} />
        <Metric label="ТТН подтверждено" value={fmtN(r?.receipts.confirmed ?? 0)}
          hint={`из ${fmtN(r?.receipts.total ?? 0)} за период`} />
        <Metric label="ТТН ждут проверки" value={fmtN(r?.receipts.pending ?? 0)}
          tone={(r?.receipts.pending ?? 0) > 0 ? 'warn' : undefined}
          hint="приёмка сверяется до загрузки" />
        <Metric label="Отклонено при приёмке" value={fmtN(r?.receipts.rejected ?? 0)}
          tone={(r?.receipts.rejected ?? 0) > 0 ? 'bad' : undefined}
          hint="разобрать с поставщиком" />
      </div>

      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            <h3 className={H3}>Сошлось ли с 1С</h3>
          </div>
          {noOneC ? (
            <EmptyLesson
              title="Документы из 1С ещё не поднимались"
              body="Сверять наши смены и ТТН не с чем: в базе нет ни одного документа БП ГИГ.
                    Документы приходят обратным потоком — синхронизацией по COM или OData; после неё
                    здесь появится построчная разница сумм."
              action={{ label: 'Настроить синхронизацию 1С', onClick: () => nav('/1c/connections') }}
            />
          ) : (
            <div className="grid gap-2 sm:grid-cols-3">
              <Metric label="Сопоставлено с документами БП" value={fmtN(rs!.matched)} tone="good" />
              <Metric label="Наших фактов без пары" value={fmtN(rs!.unmatchedEntry)}
                tone={rs!.unmatchedEntry > 0 ? 'warn' : undefined} hint="не загружено либо не найдено" />
              <Metric label="Расхождения сумм" value={fmtN(rs!.discrepancy)}
                tone={rs!.discrepancy > 0 ? 'bad' : undefined} hint="отличие свыше 1%" />
            </div>
          )}
          {!noOneC && (
            <Button variant="outline" size="sm" className="mt-3 h-8 gap-1.5 text-xs"
              onClick={() => nav('/1c/documents')}>
              Открыть документы 1С <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  ОБЩЕПИТ · разрез пакета                                                   */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Что из пакета смены относится к кухне: проданные блюда, их техкарты и
 * комплектации, которые соберёт приёмник.
 *
 * Кнопки выгрузки здесь нет намеренно — файл один на смену, и уезжает он из
 * «Магазина». Две кнопки на один файл кончаются двойной загрузкой.
 */
export function CateringPackagePanel() {
  const { companyId } = useCompany()
  const { period } = useFilters()
  const { setCoreMode } = useWorkspace()
  const [shiftKey, setShiftKey] = useState<string | null>(null)

  const shifts = useQuery({
    queryKey: ['store-shifts', companyId, period.from, period.to],
    queryFn: () => getStoreShifts(period.from, period.to),
  })
  const catering = useQuery({
    queryKey: ['store-catering', companyId, period.from, period.to],
    queryFn: () => getStoreCateringMenu(period.from, period.to),
  })

  // Смены с кухней: по остальным разрез пуст, и предлагать их незачем.
  const foodShifts = useMemo(
    () => (shifts.data?.shifts ?? []).filter((s) => (s.obshepit ?? 0) > 0),
    [shifts.data],
  )
  const active = shiftKey ?? foodShifts[0]?.shift_key ?? null

  const pkg = useQuery({
    queryKey: ['bp-package', companyId, active],
    queryFn: () => getBpPackage(active!),
    enabled: !!active,
  })

  const docs = pkg.data?.Документы ?? []
  const releases = docs.filter((d) => d.Тип === 'production_release')
  const recipes = docs.filter((d) => d.Тип === 'recipe')
  const dishes = (releases[0]?.ВыпускБлюд as { Наименование?: string; Количество?: number; Сумма?: number }[] | undefined) ?? []
  const uncovered = (catering.data?.dishes ?? []).filter((d) => d.cost === null)

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Комплектация в пакете</h2>
        <span className="text-xs text-muted-foreground">
          разрез общепита в пакете смены · выгрузка — общая, в разделе «Магазин»
        </span>
        <Button variant="ghost" size="sm" className="ml-auto h-7 gap-1 text-xs"
          onClick={() => setCoreMode('acc_store', 'export')}>
          Перейти к пакету <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>

      {foodShifts.length === 0 ? (
        <EmptyLesson
          title="За период нет смен с кухней"
          body="Блюда не продавались либо смены ещё не загружены. Разрез общепита строится из того же
                пакета, что уезжает в БП: пока в нём нет продаж блюд, комплектовать нечего."
          action={{ label: 'Проверить приём данных', onClick: () => setCoreMode('acc_store', 'cb_load') }}
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {foodShifts.slice(0, 24).map((s) => (
              <button key={s.shift_key} onClick={() => setShiftKey(s.shift_key)}
                className={cn('rounded-md border px-2.5 py-1 text-xs transition-colors',
                  s.shift_key === active
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'border-border text-muted-foreground hover:bg-accent/40')}>
                {s.date} · АЗС {s.station}
                <span className="ml-1.5 tabular-nums text-[10px] opacity-70">{fmtMoney(s.obshepit)}</span>
              </button>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label="Блюд в выпуске" value={fmtN(dishes.length)}
              hint="строк ВыпускБлюд в пакете" />
            <Metric label="Техкарт в пакете" value={fmtN(recipes.length)}
              tone={recipes.length === 0 && dishes.length > 0 ? 'bad' : undefined}
              hint="без ТТК приёмник не соберёт блюдо" />
            <Metric label="Блюд без себестоимости" value={fmtN(uncovered.length)}
              tone={uncovered.length > 0 ? 'warn' : undefined}
              hint="за период, по данным меню" />
          </div>

          <Card>
            <CardContent className="pt-4">
              <div className="mb-3 flex items-center gap-2">
                <ChefHat className="h-4 w-4 text-primary" />
                <h3 className={H3}>Что соберёт приёмник</h3>
              </div>
              {pkg.isLoading ? (
                <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Собираем пакет смены…
                </div>
              ) : dishes.length === 0 ? (
                <p className="py-4 text-sm text-muted-foreground">
                  В пакете этой смены выпуска блюд нет.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">Блюдо</th>
                      <th className="py-1.5 text-right font-medium">Количество</th>
                      <th className="py-1.5 text-right font-medium">Сумма</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dishes.map((d, i) => (
                      <tr key={`${d.Наименование}-${i}`} className="border-b border-border/30">
                        <td className="py-1.5">{d.Наименование ?? '—'}</td>
                        <td className="py-1.5 text-right tabular-nums">{fmtN(d.Количество ?? 0)}</td>
                        <td className="py-1.5 text-right tabular-nums">{fmtMoney(d.Сумма ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
                Блюдо продаётся строкой ОРП как товар, а себестоимость собирает
                КомплектацияНоменклатуры: Дт 41.02 блюдо ← Кт 41.02 ингредиенты. Порядок документов
                у бухгалтера — Комплектация, затем ОРП, затем Разукомплектация по возвратам.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  ДОКУМЕНТЫ · мост на первичку и контрагентов                               */
/* ══════════════════════════════════════════════════════════════════════════ */

/**
 * Первичка и контрагенты живут собственными страницами пространства (`/1c/documents`,
 * `/contractors`) — это полноценные реестры с фильтрами и карточками, и копировать их
 * в рабочую область нечестно: получилось бы два места с одними данными.
 *
 * Раздел объясняет, что где лежит, и отдаёт цифру периода, ради которой сюда заходят.
 */
export function AccountingDocsBridge({ kind }: { kind: 'docs' | 'parties' }) {
  const { companyId } = useCompany()
  const nav = useNavigate()
  const recon = useQuery({
    queryKey: ['reconciliation-summary', companyId],
    queryFn: () => getReconciliationSummary(companyId),
  })
  const total = recon.data?.totalAccDocs ?? 0

  if (kind === 'parties') {
    return (
      <div className="space-y-5 p-4">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold">Поставщики и договоры</h2>
          <span className="text-xs text-muted-foreground">контрагенты, на которых ссылается первичка</span>
        </div>
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-primary" />
              <h3 className={H3}>Где это ведётся</h3>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Контрагенты и договоры — функция пространства: их видят и продажи, и снабжение,
              поэтому реестр один на все рабочие места. Отсюда — прямой вход в него.
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Отдельно про топливо: поступление от поставщика (ПТУ) расширение
              <span className="font-medium text-foreground"> не создаёт принципиально</span> —
              этот документ бухгалтер вводит в БП руками, и в нашей сверке его пары не будет.
            </p>
            <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs"
              onClick={() => nav('/finance/contractors')}>
              Открыть контрагентов <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold">Документы 1С</h2>
        <span className="text-xs text-muted-foreground">первичка, поднятая из БП ГИГ</span>
      </div>
      {total === 0 ? (
        <EmptyLesson
          title="Документов из 1С пока нет"
          body="Реестр наполняется обратным потоком: синхронизация поднимает из БП ГИГ шапки документов —
                ПТУ, ОРП, кассовые ордера, счета-фактуры, — а проводки подтягиваются по требованию к
                конкретному документу. На этих данных стоят и сверка, и итоги периода."
          action={{ label: 'Настроить синхронизацию 1С', onClick: () => nav('/1c/connections') }}
        />
      ) : (
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" />
              <h3 className={H3}>Поднято из БП</h3>
            </div>
            <div className="text-3xl font-semibold tabular-nums">{fmtN(total)}</div>
            <p className="text-xs text-muted-foreground">
              документов в базе; фильтры по типу, периоду и статусу сверки — в самом реестре.
            </p>
            <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs"
              onClick={() => nav('/1c/documents')}>
              Открыть реестр документов <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ── Общие мелочи ─────────────────────────────────────────────────────────── */

const TONE: Record<string, string> = {
  good: 'text-emerald-600 dark:text-emerald-400',
  warn: 'text-amber-600 dark:text-amber-400',
  bad: 'text-red-500',
}

function Metric({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: 'good' | 'warn' | 'bad'
}) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('mt-0.5 text-xl font-bold tabular-nums', tone && TONE[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

/**
 * Пустое состояние, которое учит: почему пусто, чем наполняется и что нажать.
 * «Нет данных» здесь недопустимо — половина разделов честно пуста до первой
 * синхронизации с 1С, и человек должен понимать, что система не сломана.
 */
function EmptyLesson({ title, body, action }: {
  title: string; body: string; action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-card/30 p-5">
      <div className="max-w-prose">
        <div className="text-sm font-medium">{title}</div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{body}</p>
        {action && (
          <Button variant="outline" size="sm" className="mt-3 h-8 gap-1.5 text-xs" onClick={action.onClick}>
            {action.label} <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}
