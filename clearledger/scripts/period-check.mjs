/**
 * Проверка арифметики периодов «Реализации» (`components/workspace/OfficeRevenue.tsx`).
 *
 * Считать периоды пришлось на клиенте: календарь в шапке пространства один, а
 * сравнение требует второго отрезка. Первая версия брала локальную полночь и отдавала
 * `toISOString()` — в московском поясе каждая граница уезжала на день назад, и
 * «август» превращался в «31 июля — 30 августа». Ошибка тихая: экран рисовался, цифры
 * были правдоподобными, сравнение — неверным. Отсюда эта проверка.
 *
 *   node scripts/period-check.mjs
 *
 * Формулы дублируются здесь намеренно: тестового рантайма в проекте нет, а тянуть
 * vitest ради семи утверждений дороже, чем держать копию в пятнадцать строк. При
 * правке периодов в панели — править и здесь.
 */
const shiftDays = (iso, days) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const shiftYears = (iso, years) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() + years)
  return d.toISOString().slice(0, 10)
}

const lengthDays = (p) => Math.round((Date.parse(p.to) - Date.parse(p.from)) / 86400000) + 1

const prevPeriod = (p) => {
  const len = lengthDays(p)
  return { from: shiftDays(p.from, -len), to: shiftDays(p.to, -len) }
}

const yearAgo = (p) => ({ from: shiftYears(p.from, -1), to: shiftYears(p.to, -1) })

let failed = 0
const eq = (got, want, msg) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) failed++
  console.log(ok ? '  ok  ' : '  FAIL', msg, ok ? '' : `→ ${JSON.stringify(got)} вместо ${JSON.stringify(want)}`)
}

eq(lengthDays({ from: '2026-08-01', to: '2026-08-31' }), 31, 'август — 31 день')
eq(prevPeriod({ from: '2026-08-01', to: '2026-08-31' }), { from: '2026-07-01', to: '2026-07-31' },
  'предыдущий период: август → июль')
eq(prevPeriod({ from: '2026-01-01', to: '2026-01-31' }), { from: '2025-12-01', to: '2025-12-31' },
  'предыдущий период через границу года')
// Сдвиг на длину периода, а не «на календарный месяц»: у февраля дней меньше, и
// отрезок остаётся той же длины — иначе сравнивались бы разные по размеру периоды.
eq(prevPeriod({ from: '2026-03-01', to: '2026-03-31' }), { from: '2026-01-29', to: '2026-02-28' },
  'предыдущий период — той же длины, а не календарный месяц')
eq(yearAgo({ from: '2026-08-01', to: '2026-08-31' }), { from: '2025-08-01', to: '2025-08-31' },
  'год назад: тот же месяц предыдущего года')
eq(yearAgo({ from: '2024-02-29', to: '2024-02-29' }), { from: '2023-03-01', to: '2023-03-01' },
  '29 февраля в невисокосном году переходит на 1 марта')
eq(shiftDays('2026-08-01', -1), '2026-07-31', 'день до начала периода — для истории «до»')

console.log(failed ? `\n${failed} проверок не прошло` : '\nВсе проверки прошли')
process.exit(failed ? 1 : 0)
