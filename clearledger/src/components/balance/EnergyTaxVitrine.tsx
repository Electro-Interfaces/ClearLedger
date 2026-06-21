/**
 * Налоговая витрина энергопрофиля (демо на данных сети DEMO_EZS):
 * НДС (ставка 2026 = 22%) и налог на прибыль (ставка 2026 = 25%).
 * Выручка (sumRelease) — с НДС; закупка э/э (sumBuy) и аренда — с НДС на входе.
 * НДС к уплате = начислено с реализации − к вычету с закупок/аренды.
 * Прибыль = выручка без НДС − расходы без НДС; налог = база × 25%.
 * Модуль рабочего стола (раздел «Налоговый»), подключается через каталог.
 * Заменяется выборкой из L2/разрезов и регистров НДС/прибыли 1С.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  DEMO_EZS, sumBuy, sumRelease, supplierContract, fmtN,
  type StationBalance,
} from './balanceCalc'

const all = DEMO_EZS
const VAT_RATE = 0.22   // НДС, ставка 2026
const PROFIT_RATE = 0.25 // налог на прибыль, ставка 2026

// ── налоговая модель станции (всё «с НДС» на входе, очищаем делением на 1+ставку) ──
// Расходы = закупка э/э (по поставщику) + аренда (≈12% от выручки) + прочие опер. (≈4%).
function taxModel(s: StationBalance) {
  const revenueGross = sumRelease(s).rub          // выручка с НДС
  const energyGross = sumBuy(s).rub               // закупка э/э с НДС
  const rentGross = Math.round(revenueGross * 0.12) // аренда площадки с НДС
  const otherGross = Math.round(revenueGross * 0.04) // прочие операционные с НДС
  const expensesGross = energyGross + rentGross + otherGross

  const revenueNet = revenueGross / (1 + VAT_RATE)
  const expensesNet = expensesGross / (1 + VAT_RATE)

  const vatOutput = revenueGross - revenueNet      // НДС начислено с реализации
  const vatInput = expensesGross - expensesNet     // НДС к вычету с закупок/аренды
  const vatPayable = vatOutput - vatInput          // НДС к уплате

  const profitBase = revenueNet - expensesNet      // база налога на прибыль
  const profitTax = Math.max(0, profitBase) * PROFIT_RATE

  return {
    revenueGross, revenueNet, energyGross, rentGross, otherGross,
    expensesGross, expensesNet, vatOutput, vatInput, vatPayable,
    profitBase, profitTax,
  }
}

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
function Kpi({ label, value, accent }: { label: string; value: string; accent?: 'warn' | 'danger' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400' : accent === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </CardContent></Card>
  )
}

export function TaxVitrine() {
  // ── агрегаты по сети ──
  const net = all.reduce((a, s) => {
    const m = taxModel(s)
    a.revenueGross += m.revenueGross
    a.revenueNet += m.revenueNet
    a.expensesNet += m.expensesNet
    a.vatOutput += m.vatOutput
    a.vatInput += m.vatInput
    a.vatPayable += m.vatPayable
    a.profitBase += m.profitBase
    a.profitTax += m.profitTax
    return a
  }, { revenueGross: 0, revenueNet: 0, expensesNet: 0, vatOutput: 0, vatInput: 0, vatPayable: 0, profitBase: 0, profitTax: 0 })

  // долг по налогам поставщикам не путаем — debt берём для контекста взаиморасчётов
  const supplierDebt = all.reduce((a, s) => a + supplierContract(s).debt, 0)

  // ── сводка по регионам (период) ──
  const byRegion = new Map<string, { revenueNet: number; expensesNet: number; vatPayable: number; profitBase: number; profitTax: number }>()
  for (const s of all) {
    const m = taxModel(s)
    const e = byRegion.get(s.region) ?? { revenueNet: 0, expensesNet: 0, vatPayable: 0, profitBase: 0, profitTax: 0 }
    e.revenueNet += m.revenueNet
    e.expensesNet += m.expensesNet
    e.vatPayable += m.vatPayable
    e.profitBase += m.profitBase
    e.profitTax += m.profitTax
    byRegion.set(s.region, e)
  }
  const regionRows = [...byRegion.entries()].sort((a, b) => b[1].profitBase - a[1].profitBase)

  const totalTax = net.vatPayable + net.profitTax

  return (
    <div className="space-y-5 px-6 py-6">
      <Head
        title="Налоговый учёт"
        subtitle="НДС (22%) и налог на прибыль (25%) по сети ЭЗС за период: начисление, вычет, к уплате. Ставки 2026 г."
      />

      {/* ── НДС ── */}
      <div>
        <div className="mb-2 text-sm font-medium">НДС, 22%</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Начислено с реализации, ₽" value={fmtN(net.vatOutput)} />
          <Kpi label="К вычету (закупка/аренда), ₽" value={fmtN(net.vatInput)} />
          <Kpi label="НДС к уплате, ₽" value={fmtN(net.vatPayable)} accent={net.vatPayable > 0 ? 'warn' : undefined} />
          <Kpi label="Выручка с НДС, ₽" value={fmtN(net.revenueGross)} />
        </div>
      </div>

      {/* ── Налог на прибыль ── */}
      <div>
        <div className="mb-2 text-sm font-medium">Налог на прибыль, 25%</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Выручка без НДС, ₽" value={fmtN(net.revenueNet)} />
          <Kpi label="Расходы без НДС, ₽" value={fmtN(net.expensesNet)} />
          <Kpi label="База (прибыль), ₽" value={fmtN(net.profitBase)} accent={net.profitBase <= 0 ? 'danger' : undefined} />
          <Kpi label="Налог на прибыль, ₽" value={fmtN(net.profitTax)} accent={net.profitTax > 0 ? 'warn' : undefined} />
        </div>
      </div>

      {/* ── Сводка налоговой нагрузки по периоду (регионы) ── */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Налоговая нагрузка за период по регионам</div>
        <Table><TableHeader><TableRow>
          <TableHead>Регион</TableHead>
          <TableHead className="text-right">Выручка б/НДС, ₽</TableHead>
          <TableHead className="text-right">Расходы б/НДС, ₽</TableHead>
          <TableHead className="text-right">НДС к уплате, ₽</TableHead>
          <TableHead className="text-right">Прибыль, ₽</TableHead>
          <TableHead className="text-right">Налог 25%, ₽</TableHead>
        </TableRow></TableHeader><TableBody>
          {regionRows.map(([region, e]) => (
            <TableRow key={region}>
              <TableCell className="font-medium">{region}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(e.revenueNet)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.expensesNet)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(e.vatPayable)}</TableCell>
              <TableCell className={`text-right tabular-nums ${e.profitBase <= 0 ? 'text-red-600 dark:text-red-400' : ''}`}>{fmtN(e.profitBase)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(e.profitTax)}</TableCell>
            </TableRow>
          ))}
        </TableBody><TableBody>
          <TableRow className="border-t-2 font-medium">
            <TableCell>Итого по сети</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(net.revenueNet)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(net.expensesNet)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(net.vatPayable)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(net.profitBase)}</TableCell>
            <TableCell className="text-right tabular-nums">{fmtN(net.profitTax)}</TableCell>
          </TableRow>
        </TableBody></Table>
      </CardContent></Card>

      <p className="text-xs text-muted-foreground/70">
        Итого налогов к уплате (НДС + прибыль): {fmtN(totalTax)} ₽. Расходы = закупка э/э + аренда площадок + прочие операционные (с НДС на входе).
        Справочно: сальдо к поставщикам э/э {fmtN(supplierDebt)} ₽. НДС 22% и налог на прибыль 25% — ставки 2026 г.; данные демонстрационные.
      </p>
    </div>
  )
}
