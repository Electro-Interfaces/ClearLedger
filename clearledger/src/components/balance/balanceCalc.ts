/**
 * Расчёты и демо-данные модуля «Баланс ЭЗС». Доменно-агностичные функции баланса
 * (приход − отпуск = потери, декомпозиция технолог./коммерч.) + генератор интервалов
 * со статусами качества (VEE) для drill-down. Заменяется выборкой из L2 BalanceRecord.
 */

export interface SupplierBuy { supplier: string; kwh: number; rub: number }
export type StationSpeed = 'fast' | 'slow'
export interface StationBalance {
  id: string
  name: string
  region: string
  speed: StationSpeed            // быстрая / медленная ЭЗС
  power: number                  // мощность, кВт — для норматива потерь от физики
  meterEzs: number               // показания ПУ ЭЗС (наш счётчик, физ. приход) — для сверки ПУ↔ПУ
  normPct: number                // норматив техн. потерь (рассчитан от физики, см. computeNorm)
  status: 'ok' | 'review' | 'fail'
  purchase: SupplierBuy[]        // покупка по поставщикам (kwh = выставлено/ПУ поставщика)
  release: Record<string, { kwh: number; rub: number }> // по category.id
  unpaid: { kwh: number; rub: number }
}

export const SPEED_META: Record<StationSpeed, string> = { fast: 'Быстрые (DC)', slow: 'Медленные (AC)' }

export type IntervalQuality = 'ok' | 'review' | 'fail'
export interface IntervalRow {
  date: string            // YYYY-MM-DD
  quality: IntervalQuality
  reason: string          // VEE-флаг (пусто для Достоверно)
  estimated: boolean      // оценочное значение (Estimation)
  prihodKwh: number       // приход (ПУ ЭЗС)
  otpuskKwh: number       // отпуск (сессии ПК)
}

export const STATUS_META: Record<IntervalQuality, { label: string; cls: string }> = {
  ok: { label: 'Достоверно', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  review: { label: 'Подозрительно', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  fail: { label: 'Сбой', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
}

// ─── баланс ─────────────────────────────────────────────────────────────────
export const sumBuy = (s: StationBalance) => ({
  kwh: s.purchase.reduce((a, p) => a + p.kwh, 0),
  rub: s.purchase.reduce((a, p) => a + p.rub, 0),
})
export const sumRelease = (s: StationBalance) => Object.values(s.release).reduce(
  (a, r) => ({ kwh: a.kwh + r.kwh, rub: a.rub + r.rub }), { kwh: 0, rub: 0 })
export const purchaseRate = (s: StationBalance) => { const b = sumBuy(s); return b.kwh > 0 ? b.rub / b.kwh : 0 }
export const lossKwh = (s: StationBalance) => sumBuy(s).kwh - sumRelease(s).kwh
/** Рублёвые потери = объём потерь × ЗАКУПОЧНАЯ цена (себестоимость потерянного). */
export const lossRub = (s: StationBalance) => lossKwh(s) * purchaseRate(s)
export const lossPct = (s: StationBalance) => { const b = sumBuy(s); return b.kwh > 0 ? (lossKwh(s) / b.kwh) * 100 : 0 }
// Технологические потери = норматив, НО не больше фактических потерь (декомпозиция сходится).
export const techLossKwh = (s: StationBalance) => Math.min((s.normPct / 100) * sumBuy(s).kwh, Math.max(0, lossKwh(s)))
export const commLossKwh = (s: StationBalance) => Math.max(0, lossKwh(s) - techLossKwh(s))
export const commPct = (s: StationBalance) => { const b = sumBuy(s); return b.kwh > 0 ? (commLossKwh(s) / b.kwh) * 100 : 0 }
export const overNorm = (s: StationBalance) => lossPct(s) > s.normPct

export const fmtN = (n: number) => Math.round(n).toLocaleString('ru-RU')

// ─── интервалы (suтки) со статусом качества — для drill-down ─────────────────
// Детерминированный псевдо-рандом по (station, day): стабилен между ре-рендерами.
function seeded(a: number, b: number): number {
  const x = Math.sin(a * 127.1 + b * 311.7) * 43758.5453
  return x - Math.floor(x) // 0..1
}

// ─── норматив технологических потерь ОТ ФИЗИКИ (ТЗ §5) ───────────────────────
// Не константа: база по типу (DC-конверсия выше AC-трансформации) + добавка от мощности.
const normBase = (speed: StationSpeed) => (speed === 'fast' ? 2.0 : 1.2)
export function computeNorm(speed: StationSpeed, power: number): number {
  const adj = speed === 'fast' ? Math.min(power / 150, 1) * 1.2 : Math.min(power / 50, 1) * 0.5
  return Math.round((normBase(speed) + adj) * 10) / 10
}
/** Разложение норматива на физические составляющие — для отображения. */
export function normBreakdown(s: StationBalance) {
  const base = normBase(s.speed)
  return {
    total: s.normPct,
    base: { label: s.speed === 'fast' ? 'Базовый DC (конверсия AC→DC)' : 'Базовый AC (трансформация)', pct: base },
    power: { label: `Мощность ${s.power} кВт + кабель`, pct: Math.max(0, Math.round((s.normPct - base) * 10) / 10) },
  }
}

// ─── сверка закупки ПУ ЭЗС ↔ ПУ поставщика (ТЗ §4.1.1) ───────────────────────
export function meterCheck(s: StationBalance) {
  const supplier = sumBuy(s).kwh             // выставлено поставщиком (его ПУ)
  const ezs = s.meterEzs                     // наш ПУ ЭЗС (физ. приход)
  const diff = supplier - ezs                // >0 → поставщик выставил больше нашего счётчика
  const diffPct = ezs > 0 ? (diff / ezs) * 100 : 0
  return { ezs, supplier, diff, diffPct, ok: Math.abs(diffPct) < 0.5 }
}

/** Сгенерировать интервалы (суточные) станции за период с реалистичными статусами VEE. */
export function generateIntervals(s: StationBalance, year: number, month: number): IntervalRow[] {
  const days = new Date(year, month, 0).getDate()
  const idNum = parseInt(s.id, 10) || 1
  const buy = sumBuy(s).kwh, rel = sumRelease(s).kwh
  const avgP = buy / days, avgO = rel / days
  // профиль аномалий по статусу станции
  const failDays = s.status === 'fail' ? 3 : 0
  const reviewDays = s.status === 'fail' ? 2 : s.status === 'review' ? 3 : s.status === 'ok' ? 1 : 0
  const rows: IntervalRow[] = []
  // выбрать дни-аномалии детерминированно
  const order = Array.from({ length: days }, (_, i) => i + 1)
    .sort((d1, d2) => seeded(idNum, d2) - seeded(idNum, d1))
  const failSet = new Set(order.slice(0, failDays))
  const reviewSet = new Set(order.slice(failDays, failDays + reviewDays))
  const FAIL_REASONS = ['пропуск интервала (нет показания ПУ)', 'спайк потребления (×6 к среднему)', 'отрицательный кВт·ч']
  const REVIEW_REASONS = ['застывшее показание ПУ', 'холд < факт (доплата)', 'просрочена поверка ПУ', 'тариф вне НПА']
  for (let d = 1; d <= days; d++) {
    const v = seeded(idNum, d)
    let quality: IntervalQuality = 'ok', reason = '', estimated = false
    let prihod = avgP * (0.85 + v * 0.3)
    let otpusk = avgO * (0.85 + seeded(d, idNum) * 0.3)
    if (failSet.has(d)) {
      quality = 'fail'; reason = FAIL_REASONS[d % FAIL_REASONS.length]
      if (reason.startsWith('пропуск')) { prihod = 0; estimated = true }
      if (reason.startsWith('спайк')) prihod = avgP * 6
    } else if (reviewSet.has(d)) {
      quality = 'review'; reason = REVIEW_REASONS[d % REVIEW_REASONS.length]
      if (reason.startsWith('застывшее')) { estimated = true }
    }
    rows.push({
      date: `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`,
      quality, reason, estimated,
      prihodKwh: Math.round(prihod), otpuskKwh: Math.round(otpusk),
    })
  }
  return rows
}

/** Мок сверки выручки three-way (эквайер ↔ ОФД ↔ ПК) по станции. */
export function revenue3way(s: StationBalance) {
  const base = sumRelease(s).rub
  const idNum = parseInt(s.id, 10) || 1
  const pk = base
  // Большинство станций пробивают все чеки (ОФД=ПК); непробитые — у ~25% (реалистично).
  const ofd = seeded(idNum, 21) > 0.75 ? Math.round(base * (1 - seeded(idNum, 24) * 0.012)) : base
  const acquirer = Math.round(base * (1 - seeded(idNum, 22) * 0.03)) // эквайер минус комиссия/T+1 (БЕЗ холда — холд отдельной строкой)
  return {
    pk, ofd, acquirer,
    diffOfd: pk - ofd,        // ПК vs ОФД (непробитые чеки)
    diffAcq: ofd - acquirer,  // ОФД vs эквайер (комиссия/T+1)
    holdShort: s.unpaid.rub,  // холд < факт (дебиторка) — единственное место холда
  }
}

// ─── §4.1.3: сверка физического отпуска ПУ ЭЗС ↔ данные ПК ────────────────────
// ПК-отпуск (сессии) против ожидаемого по балансу (приход − технологические потери).
// Разрыв сверх норматива = коммерческий небаланс (подозрение к данным ПК).
export function releaseCheck(s: StationBalance) {
  const pk = sumRelease(s).kwh                       // отпуск по данным ПК
  const expected = sumBuy(s).kwh - techLossKwh(s)    // ожидаемый отпуск = приход − технолог. потери
  const gap = expected - pk                          // >0 → ПК отпустил меньше ожидаемого
  const gapPct = expected > 0 ? (gap / expected) * 100 : 0
  return { pk, expected, gap, gapPct, ok: gap <= 0 || gapPct < 0.5 }
}

/** Мок контроля тарификации (полнота начислений) по станции. */
export function tariffCheck(s: StationBalance) {
  const idNum = parseInt(s.id, 10) || 1
  const sessions = 120 + Math.round(seeded(idNum, 31) * 400)
  const noCategory = s.status === 'fail' ? Math.round(sessions * 0.04) : s.status === 'review' ? Math.round(sessions * 0.01) : 0
  const rateMismatch = s.status !== 'ok' ? Math.round(seeded(idNum, 32) * 6) : 0
  return { sessions, noCategory, rateMismatch, ok: noCategory === 0 && rateMismatch === 0 }
}

/** Сводный статус станции = худший из интервальных (производный, не первичный). */
export function rollupStatus(intervals: IntervalRow[]): IntervalQuality {
  if (intervals.some((i) => i.quality === 'fail')) return 'fail'
  if (intervals.some((i) => i.quality === 'review')) return 'review'
  return 'ok'
}

// ─── ДЕМО-ДАННЫЕ ЭЗС ─────────────────────────────────────────────────────────
const SUP_BY_REGION: Record<string, string[]> = {
  'Пермский край': ['ПЕРМЭНЕРГОСБЫТ'],
  'Брянская область': ['АТОМЭНЕРГОСБЫТ'],
  'Приморский край': ['ДЭК', 'ДВЭУК'],
  'Амурская область': ['ДЭК'],
  'Тюменская область': ['ТЮМЕНЬЭНЕРГОСБЫТ'],
}
const REGIONS = Object.keys(SUP_BY_REGION)

const BASE_DEMO: StationBalance[] = [
  { id: '100', name: 'ЭЗС №100 · Пермь, Технопарк', region: 'Пермский край', speed: 'fast', power: 120, meterEzs: 12_350, normPct: 3.0, status: 'ok',
    purchase: [{ supplier: 'ПЕРМЭНЕРГОСБЫТ', kwh: 12_400, rub: 86_800 }],
    release: { ul: { kwh: 5_200, rub: 96_200 }, fl: { kwh: 6_980, rub: 132_620 } },
    unpaid: { kwh: 40, rub: 760 } },
  { id: '535', name: 'ЭЗС №535 · Брянск, пр. Ленина', region: 'Брянская область', speed: 'slow', power: 22, meterEzs: 8_600, normPct: 1.4, status: 'ok',
    purchase: [{ supplier: 'АТОМЭНЕРГОСБЫТ', kwh: 8_600, rub: 60_200 }],
    release: { ul: { kwh: 3_100, rub: 57_350 }, fl: { kwh: 5_330, rub: 101_270 } },
    unpaid: { kwh: 0, rub: 0 } },
  { id: '19', name: 'ЭЗС №19 · Владивосток, Подземный паркинг', region: 'Приморский край', speed: 'fast', power: 150, meterEzs: 10_890, normPct: 3.2, status: 'review',
    purchase: [
      { supplier: 'ДЭК', kwh: 9_800, rub: 71_540 },
      { supplier: 'ДВЭУК', kwh: 1_200, rub: 8_760 },
    ],
    release: { ul: { kwh: 4_050, rub: 76_950 }, fl: { kwh: 6_510, rub: 123_690 } },
    unpaid: { kwh: 180, rub: 3_420 } },
  { id: '267', name: 'ЭЗС №267 · Владивосток, ул. Гамарника', region: 'Приморский край', speed: 'fast', power: 90, meterEzs: 13_980, normPct: 2.7, status: 'fail',
    purchase: [{ supplier: 'ДЭК', kwh: 14_200, rub: 103_660 }],
    release: { ul: { kwh: 5_400, rub: 102_600 }, fl: { kwh: 7_650, rub: 145_350 } },
    unpaid: { kwh: 320, rub: 6_080 } },
]

// Догенерируем парк до ~60 ЭЗС, чтобы демо показывало работу фильтров/сортировки/прокрутки.
function synthStation(i: number): StationBalance {
  const region = REGIONS[i % REGIONS.length]
  const sup = SUP_BY_REGION[region]
  const buyKwh = 4_000 + Math.round(seeded(i, 7) * 16_000)
  const rate = 6.5 + seeded(i, 3) * 2.5
  const lossPctTarget = seeded(i, 11) * 7 // 0..7%
  const relKwh = Math.round(buyKwh * (1 - lossPctTarget / 100))
  const ulShare = 0.35 + seeded(i, 5) * 0.3
  const cities = ['Пермь', 'Брянск', 'Владивосток', 'Благовещенск', 'Тюмень']
  const num = 300 + i
  const status: StationBalance['status'] = lossPctTarget > 5.5 ? 'fail' : lossPctTarget > 3.5 ? 'review' : 'ok'
  const speed: StationSpeed = seeded(i, 13) > 0.35 ? 'fast' : 'slow'
  const power = speed === 'fast' ? 60 + Math.round(seeded(i, 17) * 190) : 7 + Math.round(seeded(i, 17) * 36)
  // знак: изредка наш ПУ показывает БОЛЬШЕ счёта поставщика (двусторонняя сверка)
  const meterGap = Math.round(buyKwh * (status === 'fail' ? 0.012 : status === 'review' ? 0.005 : 0.001) * (0.5 + seeded(i, 19)))
    * (seeded(i, 23) > 0.85 ? -1 : 1)
  return {
    id: String(num), name: `ЭЗС №${num} · ${cities[i % cities.length]}`, region, speed, power,
    meterEzs: buyKwh - meterGap, normPct: computeNorm(speed, power), status,
    purchase: sup.length > 1 && i % 3 === 0
      ? [{ supplier: sup[0], kwh: Math.round(buyKwh * 0.8), rub: Math.round(buyKwh * 0.8 * rate) },
         { supplier: sup[1], kwh: Math.round(buyKwh * 0.2), rub: Math.round(buyKwh * 0.2 * rate) }]
      : [{ supplier: sup[0], kwh: buyKwh, rub: Math.round(buyKwh * rate) }],
    release: {
      ul: { kwh: Math.round(relKwh * ulShare), rub: Math.round(relKwh * ulShare * (rate + 11)) },
      fl: { kwh: Math.round(relKwh * (1 - ulShare)), rub: Math.round(relKwh * (1 - ulShare) * (rate + 12)) },
    },
    unpaid: { kwh: Math.round(seeded(i, 9) * 300), rub: Math.round(seeded(i, 9) * 300 * (rate + 12)) },
  }
}

export const DEMO_EZS: StationBalance[] = [
  ...BASE_DEMO,
  ...Array.from({ length: 56 }, (_, i) => synthStation(i + 1)),
]

// ─── §6: договор поставщика + взаиморасчёты + методология оплаты ──────────────
export type PaymentPolicy = 'no_doc_no_pay' | 'by_ezs_meter' | 'by_release'
export const PAYMENT_POLICY_LABEL: Record<PaymentPolicy, string> = {
  no_doc_no_pay: 'Не платить без документов',
  by_ezs_meter: 'Платить по показаниям ПУ ЭЗС',
  by_release: 'Платить по данным отпуска',
}
export type ContractStatus = 'active' | 'expiring' | 'renewal' | 'amending' | 'terminating'
export const CONTRACT_STATUS_META: Record<ContractStatus, { label: string; cls: string }> = {
  active: { label: 'Действует', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  expiring: { label: 'Истекает', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  renewal: { label: 'На продлении', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  amending: { label: 'Изменение условий', cls: 'bg-violet-500/15 text-violet-600 dark:text-violet-400' },
  terminating: { label: 'Расторжение', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
}
export function supplierContract(s: StationBalance) {
  const sup = s.purchase[0]?.supplier ?? '—'
  const idNum = parseInt(s.id, 10) || 1
  const sv = seeded(idNum, 41)
  const status: ContractStatus = sv > 0.93 ? 'terminating' : sv > 0.85 ? 'expiring'
    : sv > 0.79 ? 'amending' : sv > 0.72 ? 'renewal' : 'active'
  const policies: PaymentPolicy[] = ['no_doc_no_pay', 'by_ezs_meter', 'by_release']
  const accrued = sumBuy(s).rub
  const paid = Math.round(accrued * (status === 'active' ? 0.96 : 0.62))
  return {
    supplier: sup,
    number: `ЭС-${2024 + (idNum % 2)}/${100 + (idNum % 900)}`,
    since: `01.0${1 + (idNum % 9)}.${2024 + (idNum % 2)}`,
    until: `31.12.${2026 + (idNum % 2)}`,
    status,
    paymentPolicy: policies[idNum % 3],
    accrued, paid, debt: accrued - paid,
  }
}

// ─── реестр обращений (claim) к поставщику/ПК/ОФД: §4.1.1, §4.1.3, §4.3 ──────
export type ClaimTarget = 'supplier' | 'pk' | 'ofd'
export type ClaimStatus = 'open' | 'work' | 'resolved' | 'rejected'
export const CLAIM_TARGET_LABEL: Record<ClaimTarget, string> = {
  supplier: 'Поставщик э/э', pk: 'Техподдержка ПК', ofd: 'ОФД',
}
export const CLAIM_STATUS_META: Record<ClaimStatus, { label: string; cls: string }> = {
  open: { label: 'Открыто', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  work: { label: 'В работе', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  resolved: { label: 'Урегулировано', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  rejected: { label: 'Отклонено', cls: 'bg-muted text-muted-foreground' },
}
export interface Claim {
  id: string; target: ClaimTarget; subject: string; amountRub: number
  status: ClaimStatus; opened: string; due: string
}
/** Обращения станции — производны от расхождений: §4.1.1 ПУ↔ПУ, §4.1.3 ПУ↔ПК, §4.3 ОФД/тариф. */
export function stationClaims(s: StationBalance): Claim[] {
  const idNum = parseInt(s.id, 10) || 1
  const out: Claim[] = []
  const mk = (n: number, target: ClaimTarget, subject: string, amount: number, status: ClaimStatus): Claim => ({
    id: `C-${s.id}-${n}`, target, subject, amountRub: Math.round(amount), status,
    opened: `0${1 + (idNum % 9)}.06.2026`, due: `${10 + (idNum % 18)}.06.2026`,
  })
  // §4.1.1 — поставщик выставил больше нашего ПУ (переплата)
  const mc = meterCheck(s)
  if (mc.diff > 0 && mc.diffPct >= 0.5) {
    out.push(mk(1, 'supplier', `Расхождение ПУ ЭЗС ↔ ПУ поставщика ${mc.diffPct.toFixed(1)}%`,
      mc.diff * purchaseRate(s), s.status === 'fail' ? 'open' : 'work'))
  }
  // §4.1.3 — ПК отпустил меньше ожидаемого по балансу (коммерческий небаланс) → техподдержка ПК
  const rc = releaseCheck(s)
  if (rc.gap > 0 && rc.gapPct > 1.5) {
    out.push(mk(2, 'pk', `Небаланс отпуска ПУ ЭЗС ↔ ПК ${rc.gapPct.toFixed(1)}%`,
      rc.gap * purchaseRate(s), s.status === 'fail' ? 'open' : 'work'))
  }
  // §4.3.3 — непробитые чеки (только материальные, > 0.5% выручки) → ОФД
  const rev = revenue3way(s)
  if (rev.diffOfd > 0) out.push(mk(3, 'ofd', 'Непробитые чеки (ПК > ОФД)', rev.diffOfd, 'work'))
  // §4.3.2 — полнота тарификации → техподдержка ПК
  const tar = tariffCheck(s)
  if (tar.noCategory > 0 || tar.rateMismatch > 0) {
    out.push(mk(4, 'pk', `Сессии без корректной тарификации (${tar.noCategory + tar.rateMismatch})`,
      0, s.status === 'fail' ? 'open' : 'resolved'))
  }
  return out
}
/** Кол-во открытых обращений (open+work) по выборке — для KPI сети. */
export function openClaimsCount(stations: StationBalance[]): number {
  return stations.reduce((a, s) => a + stationClaims(s).filter((c) => c.status === 'open' || c.status === 'work').length, 0)
}
