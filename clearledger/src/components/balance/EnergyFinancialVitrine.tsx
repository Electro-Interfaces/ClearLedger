/**
 * Финансовая витрина энергопрофиля (демо на данных сети DEMO_EZS):
 * денежные потоки (приток/отток/чистый), платёжный календарь предстоящих платежей,
 * дебиторка vs кредиторка. Раздел «Финансовый» рабочего стола.
 * Заменяется выборкой из L2/разрезов + графика платежей казначейства.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DEMO_EZS, sumBuy, sumRelease, supplierContract, fmtN } from './balanceCalc'
import { MetricTile as Kpi } from '@/components/ui/metric-tile'

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
/* ── категории предстоящих платежей (платёжный календарь, на моках) ── */
type PayKind = 'energy' | 'rent' | 'ofd' | 'acquiring'
const PAY_KIND_META: Record<PayKind, { label: string; cls: string }> = {
  energy: { label: 'Энергоснабжение', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  rent: { label: 'Аренда', cls: 'bg-violet-500/15 text-violet-600 dark:text-violet-400' },
  ofd: { label: 'Услуги ОФД', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  acquiring: { label: 'Комиссия эквайринга', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
}
const MONTHS = ['июль', 'август', 'сентябрь']

/* ── Финансовый ── */
export function FinancialVitrine() {
  // денежные потоки сети
  const inflow = all.reduce((a, s) => a + sumRelease(s).rub, 0)                                  // приток = выручка (отпуск)
  const supplierDebt = all.reduce((a, s) => a + supplierContract(s).debt, 0)                     // долг поставщикам э/э
  const buyRub = all.reduce((a, s) => a + sumBuy(s).rub, 0)                                      // закупка э/э (начислено)
  const outflow = buyRub + supplierDebt                                                          // отток = закупка + погашение долга
  const net = inflow - outflow                                                                   // чистый поток
  const receivable = all.reduce((a, s) => a + s.unpaid.rub, 0)                                   // дебиторка (холд<факт)
  const payable = supplierDebt                                                                   // кредиторка (поставщики)

  // ── платёжный календарь: помесячно по типам платежей (моки от агрегатов сети) ──
  // База платежей выводится из объёмов сети, разложена по месяцам коэффициентами сезонности.
  const energyMonthly = buyRub / 3                                                               // среднемесячная закупка э/э
  const rentMonthly = Math.round(all.length * 38_000)                                            // аренда площадок ЭЗС
  const ofdMonthly = Math.round(all.length * 1_700)                                              // обслуживание ОФД
  const acquiringMonthly = Math.round(inflow * 0.018 / 3)                                        // комиссия эквайринга ~1.8%

  const calendar: { month: string; due: string; kind: PayKind; counterparty: string; amount: number }[] = []
  const seasonality = [1.0, 0.94, 1.08]
  MONTHS.forEach((m, i) => {
    const k = seasonality[i]
    calendar.push({ month: m, due: `10.0${7 + i}.2026`, kind: 'energy', counterparty: 'Поставщики э/э (договоры ЭС)', amount: Math.round(energyMonthly * k) })
    calendar.push({ month: m, due: `05.0${7 + i}.2026`, kind: 'rent', counterparty: 'Арендодатели площадок', amount: Math.round(rentMonthly * k) })
    calendar.push({ month: m, due: `15.0${7 + i}.2026`, kind: 'ofd', counterparty: 'ОФД (фискализация чеков)', amount: ofdMonthly })
    calendar.push({ month: m, due: `25.0${7 + i}.2026`, kind: 'acquiring', counterparty: 'Банк-эквайер', amount: Math.round(acquiringMonthly * k) })
  })
  const calendarTotal = calendar.reduce((a, p) => a + p.amount, 0)

  // ── дебиторка vs кредиторка: разложение ──
  // Дебиторка: холд<факт по ЮЛ (доля unpaid пропорц. выручке ЮЛ) vs ФЛ.
  const ulShareNet = (() => {
    const ul = all.reduce((a, s) => a + (s.release.ul?.rub ?? 0), 0)
    const tot = all.reduce((a, s) => a + sumRelease(s).rub, 0)
    return tot > 0 ? ul / tot : 0.5
  })()
  const recUl = Math.round(receivable * ulShareNet)
  const recFl = receivable - recUl

  // Кредиторка: долг поставщикам э/э vs предстоящая аренда (за квартал).
  const rentQuarter = calendar.filter((p) => p.kind === 'rent').reduce((a, p) => a + p.amount, 0)
  const payableTotal = payable + rentQuarter

  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Финансовый: денежные потоки" subtitle="Приток/отток/чистый поток сети, платёжный календарь предстоящих платежей, дебиторка против кредиторки." />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <Kpi label="Приток, ₽" value={fmtN(inflow)} accent="good" />
        <Kpi label="Отток, ₽" value={fmtN(outflow)} accent="warn" />
        <Kpi label="Чистый поток, ₽" value={fmtN(net)} accent={net >= 0 ? 'good' : 'danger'} />
        <Kpi label="Дебиторка, ₽" value={fmtN(receivable)} accent={receivable ? 'warn' : undefined} />
        <Kpi label="Кредиторка, ₽" value={fmtN(payable)} accent={payable ? 'warn' : undefined} />
      </div>

      {/* ── Платёжный календарь ── */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-medium">Платёжный календарь (предстоящие платежи)</div>
          <div className="text-xs text-muted-foreground">Итого за квартал: <span className="font-medium tabular-nums text-foreground">{fmtN(calendarTotal)} ₽</span></div>
        </div>
        <Table><TableHeader><TableRow>
          <TableHead>Месяц</TableHead><TableHead>Срок</TableHead>
          <TableHead>Тип платежа</TableHead><TableHead>Получатель</TableHead>
          <TableHead className="text-right">Сумма, ₽</TableHead>
        </TableRow></TableHeader><TableBody>
          {calendar.map((p, i) => (
            <TableRow key={`${p.kind}-${i}`}>
              <TableCell className="capitalize text-muted-foreground">{p.month}</TableCell>
              <TableCell className="tabular-nums text-muted-foreground">{p.due}</TableCell>
              <TableCell>
                <Badge variant="secondary" className={`text-[10px] ${PAY_KIND_META[p.kind].cls}`}>{PAY_KIND_META[p.kind].label}</Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">{p.counterparty}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(p.amount)}</TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
      </CardContent></Card>

      {/* ── Дебиторка vs Кредиторка ── */}
      <div className="grid gap-3 md:grid-cols-2">
        <Card><CardContent className="pt-5">
          <div className="mb-3 text-sm font-medium">Дебиторка (нам должны)</div>
          <Table><TableBody>
            <TableRow>
              <TableCell className="text-muted-foreground">Холд &lt; факт по ЮЛ (доплата корп.)</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(recUl)} ₽</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="text-muted-foreground">Холд &lt; факт по ФЛ (доплата физлиц)</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(recFl)} ₽</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="font-medium">Итого дебиторка</TableCell>
              <TableCell className="text-right font-semibold tabular-nums text-amber-600 dark:text-amber-400">{fmtN(receivable)} ₽</TableCell>
            </TableRow>
          </TableBody></Table>
        </CardContent></Card>

        <Card><CardContent className="pt-5">
          <div className="mb-3 text-sm font-medium">Кредиторка (мы должны)</div>
          <Table><TableBody>
            <TableRow>
              <TableCell className="text-muted-foreground">Долг поставщикам э/э</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(payable)} ₽</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="text-muted-foreground">Аренда площадок (квартал)</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(rentQuarter)} ₽</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="font-medium">Итого кредиторка</TableCell>
              <TableCell className="text-right font-semibold tabular-nums text-amber-600 dark:text-amber-400">{fmtN(payableTotal)} ₽</TableCell>
            </TableRow>
          </TableBody></Table>
        </CardContent></Card>
      </div>

      <p className="text-xs text-muted-foreground/70">
        Чистый поток = приток (выручка с отпуска) − отток (закупка э/э + погашение долга поставщикам).
        Платёжный календарь и сезонность — заглушка до графика платежей казначейства. НДС 22%, налог на прибыль 25% (2026).
      </p>
    </div>
  )
}
