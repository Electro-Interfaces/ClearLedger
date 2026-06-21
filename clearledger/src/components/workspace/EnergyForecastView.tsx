/**
 * Энерго-вариант режима «Закрытие месяца» (демо на данных сети DEMO_EZS).
 * Прогресс закрытия периода энергопрофиля: выручка факт/план, отпуск кВт·ч,
 * начисленная аренда, % готовности + чек-лист закрытия (сессии ПК / эквайринг T+1 /
 * ОФД-чеки / аренда / эталон billing компании) + блок «Риски / готовность».
 * Язык — ЭНЕРГО (без ОРП/смен/1С/проводок БП). Эталон закрытого периода = биллинг компании.
 * Заменяется выборкой из L2 + статусом разрезов сверки за период.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  DEMO_EZS, sumBuy, sumRelease, lossKwh, fmtN,
  revenue3way, releaseCheck, tariffCheck, supplierContract, openClaimsCount,
} from '../balance/balanceCalc'

const all = DEMO_EZS

function Head({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{title}</h1>
        <Badge variant="secondary" className="text-[10px]">демо-данные</Badge>
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
    </div>
  )
}
function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: 'ok' | 'warn' | 'danger' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400'
    : accent === 'warn' ? 'text-amber-600 dark:text-amber-400'
    : accent === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground/70">{sub}</div>}
    </CardContent></Card>
  )
}

// ── чек-лист закрытия периода (энерго-язык, без 1С/ОРП/проводок БП) ──────────
type CheckTone = 'done' | 'partial' | 'pending'
const CHECK_META: Record<CheckTone, { label: string; cls: string; mark: string }> = {
  done: { label: 'Готово', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400', mark: '✓' },
  partial: { label: 'Частично', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400', mark: '◐' },
  pending: { label: 'Ожидает', cls: 'bg-red-500/15 text-red-600 dark:text-red-400', mark: '○' },
}

export function EnergyForecastView() {
  const stationsN = all.length

  // ── выручка факт / план (план = норматив выручки от отпуска по средней цене сети) ──
  const revenueFact = all.reduce((a, s) => a + sumRelease(s).rub, 0)
  const releaseKwh = all.reduce((a, s) => a + sumRelease(s).kwh, 0)
  const netRate = releaseKwh > 0 ? revenueFact / releaseKwh : 0
  // План периода ≈ выручка по приходу за вычетом нормативных техн. потерь (что должно дойти до сессий).
  const buyKwh = all.reduce((a, s) => a + sumBuy(s).kwh, 0)
  const lossKwhNet = all.reduce((a, s) => a + lossKwh(s), 0)
  const planKwh = buyKwh - lossKwhNet // ожидаемый отпуск = приход − потери
  const revenuePlan = Math.round(planKwh * netRate)
  const revPct = revenuePlan > 0 ? (revenueFact / revenuePlan) * 100 : 0

  // ── аренда начислено (демо: фикс. ставка площадки на ЭЗС, по факту = договор аренды) ──
  const rentPerStation = 18_000
  const rentAccrued = stationsN * rentPerStation

  // ── чек-лист закрытия: каждый пункт сверяется по реальным мок-разрезам DEMO_EZS ──
  // 1. Сессии ПК сверены (физический отпуск ПУ ЭЗС ↔ данные ПК) — releaseCheck
  const pkBad = all.filter((s) => !releaseCheck(s).ok).length
  // 2. Эквайринг сверен T+1 (ОФД ↔ эквайер, комиссия/перенос платежа)
  const acqBad = all.filter((s) => revenue3way(s).diffAcq > 0).length
  // 3. ОФД-чеки полны (ПК ↔ ОФД, непробитые чеки)
  const ofdBad = all.filter((s) => revenue3way(s).diffOfd > 0).length
  // 4. Аренда начислена — все площадки (демо: начисление сформировано по всем ЭЗС)
  const rentDone = stationsN
  // 5. Эталон billing компании получен (закрытый период = биллинг компании, НЕ 1С)
  const billingReceived = Math.round(stationsN * 0.92) // часть площадок ещё без выгрузки биллинга

  const checks: { key: string; title: string; detail: string; ok: number; total: number }[] = [
    { key: 'pk', title: 'Сессии ПК сверены', detail: 'Отпуск ПУ ЭЗС ↔ данные ПК (§4.1.3)', ok: stationsN - pkBad, total: stationsN },
    { key: 'acq', title: 'Эквайринг сверен T+1', detail: 'ОФД ↔ эквайер: комиссия и перенос платежа', ok: stationsN - acqBad, total: stationsN },
    { key: 'ofd', title: 'ОФД-чеки полны', detail: 'ПК ↔ ОФД: непробитые чеки закрыты', ok: stationsN - ofdBad, total: stationsN },
    { key: 'rent', title: 'Аренда начислена', detail: 'Начисление по договорам аренды площадок ЭЗС', ok: rentDone, total: stationsN },
    { key: 'bill', title: 'Эталон billing получен', detail: 'Закрытый период = биллинг компании', ok: billingReceived, total: stationsN },
  ]
  const toneOf = (c: { ok: number; total: number }): CheckTone =>
    c.ok >= c.total ? 'done' : c.ok >= c.total * 0.6 ? 'partial' : 'pending'

  // ── % готовности закрытия = средняя готовность по всем пунктам чек-листа ──
  const readyPct = Math.round(checks.reduce((a, c) => a + (c.total ? c.ok / c.total : 0), 0) / checks.length * 100)

  // ── блок «Риски / готовность» (энерго-язык) ──
  const openClaims = openClaimsCount(all)
  const offTariff = all.reduce((a, s) => a + tariffCheck(s).noCategory, 0)
  const holdReceivable = all.reduce((a, s) => a + s.unpaid.rub, 0)
  const supplierDebt = all.reduce((a, s) => a + supplierContract(s).debt, 0)

  const risks: { title: string; detail: string; level: CheckTone; metric: string }[] = [
    { title: 'Несверенный отпуск ПК',
      detail: 'Станции с расхождением физического отпуска ПУ ЭЗС и данных ПК сверх норматива',
      level: pkBad === 0 ? 'done' : pkBad <= 3 ? 'partial' : 'pending', metric: `${pkBad} ЭЗС` },
    { title: 'Непробитые чеки ОФД',
      detail: 'Станции, где выручка ПК превышает фискализацию ОФД (требуется до-фискализация)',
      level: ofdBad === 0 ? 'done' : ofdBad <= 4 ? 'partial' : 'pending', metric: `${ofdBad} ЭЗС` },
    { title: 'Сессии вне тарифа',
      detail: 'Зарядные сессии без корректной категории/тарифа — выручка может быть занижена',
      level: offTariff === 0 ? 'done' : offTariff <= 20 ? 'partial' : 'pending', metric: `${fmtN(offTariff)} сессий` },
    { title: 'Дебиторка холд < факт',
      detail: 'Незакрытые доплаты по сессиям, где холд эквайринга оказался меньше факта',
      level: holdReceivable === 0 ? 'done' : 'partial', metric: `${fmtN(holdReceivable)} ₽` },
    { title: 'Задолженность поставщикам э/э',
      detail: 'Сальдо по договорам энергоснабжения к урегулированию до закрытия периода',
      level: supplierDebt === 0 ? 'done' : 'partial', metric: `${fmtN(supplierDebt)} ₽` },
    { title: 'Открытые обращения',
      detail: 'Претензии поставщику / техподдержке ПК / ОФД, влияющие на корректность периода',
      level: openClaims === 0 ? 'done' : openClaims <= 5 ? 'partial' : 'pending', metric: `${openClaims} шт.` },
  ]
  const blockers = risks.filter((r) => r.level === 'pending').length
  const readyVerdict = readyPct >= 100 && blockers === 0

  return (
    <div className="space-y-5 px-6 py-6">
      <Head
        title="Закрытие месяца — энергопрофиль"
        subtitle="Прогресс закрытия периода сети ЭЗС: выручка факт/план, отпуск, начисленная аренда, готовность. Эталон закрытого периода — биллинг компании."
      />

      {/* KPI прогресса закрытия */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <Kpi label="Выручка факт, ₽" value={fmtN(revenueFact)} sub={`план ${fmtN(revenuePlan)} ₽`} />
        <Kpi label="Выполнение плана, %" value={`${revPct.toFixed(1)}%`}
          accent={revPct >= 100 ? 'ok' : revPct >= 95 ? 'warn' : 'danger'} />
        <Kpi label="Отпуск, кВт·ч" value={fmtN(releaseKwh)} sub={`приход ${fmtN(buyKwh)} кВт·ч`} />
        <Kpi label="Аренда начислено, ₽" value={fmtN(rentAccrued)} sub={`${stationsN} площадок`} />
        <Kpi label="Готовность закрытия, %" value={`${readyPct}%`}
          accent={readyPct >= 100 ? 'ok' : readyPct >= 80 ? 'warn' : 'danger'} />
      </div>

      {/* Полоса готовности */}
      <Card><CardContent className="pt-5">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-medium">Готовность периода к закрытию</div>
          <Badge
            variant="secondary"
            className={`text-[10px] ${readyVerdict
              ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
              : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'}`}
          >
            {readyVerdict ? 'Готов к закрытию' : `${blockers ? `${blockers} блокирующих` : 'есть незакрытые пункты'}`}
          </Badge>
        </div>
        <Progress value={readyPct} className="h-2" />
        <p className="mt-2 text-[11px] text-muted-foreground/70">
          {readyPct}% пунктов чек-листа закрыто. Период закрывается после сверки сессий ПК, эквайринга T+1,
          полноты ОФД-чеков, начисления аренды и получения эталона billing компании.
        </p>
      </CardContent></Card>

      {/* Чек-лист закрытия периода */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Чек-лист закрытия периода</div>
        <Table><TableHeader><TableRow>
          <TableHead className="w-8 text-center"> </TableHead>
          <TableHead>Контроль</TableHead>
          <TableHead>Что сверяется</TableHead>
          <TableHead className="text-right">Готово ЭЗС</TableHead>
          <TableHead className="text-center">Статус</TableHead>
        </TableRow></TableHeader><TableBody>
          {checks.map((c) => {
            const tone = toneOf(c)
            const m = CHECK_META[tone]
            return (
              <TableRow key={c.key}>
                <TableCell className={`text-center text-base font-semibold ${tone === 'done' ? 'text-emerald-600 dark:text-emerald-400' : tone === 'partial' ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}`}>{m.mark}</TableCell>
                <TableCell className="font-medium">{c.title}</TableCell>
                <TableCell className="text-muted-foreground">{c.detail}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{c.ok} / {c.total}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${m.cls}`}>{m.label}</Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
      </CardContent></Card>

      {/* Риски / готовность (энерго-язык) */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          Риски и готовность
          {blockers > 0
            ? <Badge variant="secondary" className="text-[10px] bg-red-500/15 text-red-600 dark:text-red-400">{blockers} требуют действия</Badge>
            : <Badge variant="secondary" className="text-[10px] bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">критичных нет</Badge>}
        </div>
        <Table><TableHeader><TableRow>
          <TableHead>Риск</TableHead>
          <TableHead>Описание</TableHead>
          <TableHead className="text-right">Метрика</TableHead>
          <TableHead className="text-center">Уровень</TableHead>
        </TableRow></TableHeader><TableBody>
          {risks.map((r) => {
            const m = CHECK_META[r.level]
            const lvl = r.level === 'done' ? 'В норме' : r.level === 'partial' ? 'Внимание' : 'Блокирует'
            return (
              <TableRow key={r.title}>
                <TableCell className="font-medium">{r.title}</TableCell>
                <TableCell className="text-muted-foreground">{r.detail}</TableCell>
                <TableCell className="text-right tabular-nums">{r.metric}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${m.cls}`}>{lvl}</Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
        <p className="mt-3 text-[11px] text-muted-foreground/70">
          Эталон закрытого периода — биллинг компании (не оперативный поток). Незакрытые пункты переносятся
          в reach-back: сверяются с биллингом после получения выгрузки. НДС 22%, налог на прибыль 25% (2026).
        </p>
      </CardContent></Card>
    </div>
  )
}
