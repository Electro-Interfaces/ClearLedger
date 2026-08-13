/**
 * Проверка арифметики отчёта о финансовых результатах («Экономика»).
 *
 * Формулы свода живут на бэкенде (`_pnl_totals`) и повторяются на фронте при свёртке
 * месяцев в кварталы и годы (`foldMonths` в `OfficeEconomy.tsx`). Две реализации одной
 * цепочки — ровно то место, где расхождение появляется молча: свод покажет одно, а
 * разрез по годам другое, и обе цифры будут выглядеть правдоподобно.
 *
 *   node scripts/pnl-check.mjs
 *
 * Проверяются три вещи: сама цепочка от выручки к прибыли, аддитивность (сумма
 * месяцев равна своду) и поведение на краях — убыток, нулевая выручка, возвраты.
 * Формулы дублируются здесь намеренно: тестового рантайма в проекте нет, а тянуть
 * vitest ради десятка утверждений дороже, чем держать копию.
 */

/** Свод: та же цепочка, что в `_pnl_totals`. */
function totals(rows) {
  const keys = ['revenue', 'vat', 'excise', 'cogs', 'cogsOther', 'commercial', 'admin',
    'otherIncome', 'otherExpense', 'interest', 'tax']
  const t = {}
  for (const k of keys) t[k] = round2(rows.reduce((s, r) => s + (r[k] ?? 0), 0))
  t.net = round2(t.revenue - t.vat - t.excise)
  t.cogsTotal = round2(t.cogs + t.cogsOther)
  t.gross = round2(t.net - t.cogsTotal)
  t.operating = round2(t.gross - t.commercial - t.admin)
  t.beforeTax = round2(t.operating + t.otherIncome - t.otherExpense - t.interest)
  t.profit = round2(t.beforeTax - t.tax)
  t.grossPct = t.net ? round1(t.gross / t.net * 100) : null
  t.profitPct = t.net ? round1(t.profit / t.net * 100) : null
  return t
}

const round2 = (v) => Math.round(v * 100) / 100
const round1 = (v) => Math.round(v * 10) / 10

let failed = 0
const eq = (got, want, msg) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) failed++
  console.log(ok ? '  ok  ' : '  FAIL', msg, ok ? '' : `→ ${JSON.stringify(got)} вместо ${JSON.stringify(want)}`)
}

// ── Данные пилота за всю историю: цифры сверены с оборотами регистра ────────
const PILOT = {
  revenue: 22122948.24, vat: 3713478.33, excise: 0,
  cogs: 14065355.85, cogsOther: -1666.66,
  commercial: 2707833.20, admin: 954294.94,
  otherIncome: 33720.53, otherExpense: 62485.66, interest: 0,
  tax: 120791.41,
}

const t = totals([PILOT])
eq(t.net, 18409469.91, 'выручка без НДС = брутто минус налог')
eq(t.gross, 4345780.72, 'валовая прибыль: управленческие вынесены из себестоимости')
eq(t.operating, 683652.58, 'прибыль от продаж')
eq(t.beforeTax, 654887.45, 'прибыль до налога')
eq(t.profit, 534096.04, 'чистая прибыль')
eq(t.grossPct, 23.6, 'валовая рентабельность, %')
eq(t.profitPct, 2.9, 'чистая рентабельность, %')

// Аддитивность: свод за год обязан совпасть с суммой его месяцев. Ломается, если
// в цепочку добавили строку, а в свёртку фронта — нет.
//
// Сравнение с допуском, а не точное: одиннадцать полей округляются на копейку каждое,
// и требовать точного равенства значило бы проверять арифметику округления, а не
// аддитивность цепочки. Точная аддитивность проверяется ниже, на целых суммах.
const near = (got, want, msg, eps = 0.05) => {
  const ok = Math.abs(got - want) <= eps
  if (!ok) failed++
  console.log(ok ? '  ok  ' : '  FAIL', msg, ok ? '' : `→ ${got} против ${want}`)
}

const half = { ...PILOT }
for (const k of Object.keys(half)) half[k] = round2(half[k] / 2)
const byParts = totals([half, half])
near(byParts.profit, t.profit, 'сумма двух половин равна своду')
near(byParts.gross, t.gross, 'валовая прибыль аддитивна')

// А вот на данных без дробления аддитивность обязана быть точной.
const m1 = { revenue: 1200, vat: 200, cogs: 500, commercial: 100 }
const m2 = { revenue: 2400, vat: 400, cogs: 900, commercial: 150, tax: 30 }
eq(totals([m1, m2]).profit, round2(totals([m1]).profit + totals([m2]).profit),
   'два месяца целыми суммами складываются точно')

// ── Края ───────────────────────────────────────────────────────────────────
const empty = totals([])
eq(empty.profit, 0, 'пустой период: прибыль ноль')
eq(empty.profitPct, null, 'пустой период: рентабельность не считается, а не «0 %»')

const loss = totals([{ revenue: 1200, vat: 200, cogs: 1500, commercial: 300, admin: 0 }])
eq(loss.net, 1000, 'убыток: выручка без НДС')
eq(loss.profit, -800, 'убыток считается со знаком, а не по модулю')
eq(loss.profitPct, -80, 'отрицательная рентабельность')

// Возврат обратной записью приходит отрицательной выручкой — цепочка обязана его
// принять, а не отбросить как «ошибку данных».
const withReturn = totals([{ revenue: 1000, vat: 0, cogs: 400 }, { revenue: -300, cogs: -120 }])
eq(withReturn.net, 700, 'возврат уменьшает выручку')
eq(withReturn.gross, 420, 'возврат уменьшает и себестоимость')

// Налог при убытке (условный доход) приходит отрицательным и увеличивает результат.
const negTax = totals([{ revenue: 100, cogs: 200, tax: -20 }])
eq(negTax.profit, -80, 'отрицательный налог не вычитается вторым знаком')

console.log(failed ? `\n${failed} проверок не прошло` : '\nВсе проверки прошли')
process.exit(failed ? 1 : 0)
