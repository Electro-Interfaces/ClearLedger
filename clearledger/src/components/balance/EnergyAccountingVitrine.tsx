/**
 * Бухгалтерская витрина энергопрофиля (демо на данных сети DEMO_EZS):
 * «Журнал операций» по биллингу ЭЗС (обезличенно, НЕ 1С-БП) + сводка оборотов по счетам.
 * Проводки строятся из агрегатов DEMO_EZS по учётной модели компании.
 * Ставки 2026: НДС 22%. Заменяется выборкой из L4 (эталон закрытого периода).
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DEMO_EZS, sumBuy, sumRelease, fmtN } from './balanceCalc'

const all = DEMO_EZS
const VAT_RATE = 0.22 // НДС, ставка 2026
const RENT_PER_EZS = 18_000 // аренда площадки под ЭЗС, ₽/мес (демо-норматив)
const ACQUIRING_RATE = 0.018 // эквайринг-комиссия по выручке ФЛ (демо)
const PERIOD = '30.06.2026' // дата проводок периода (демо)

/** Журнальная проводка. */
interface Posting {
  op: string
  dt: string
  kt: string
  rub: number
  note?: string
}

function Head({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{title}</h1>
        <Badge variant="secondary" className="text-[10px]">демо-данные</Badge>
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
      {/* Раздел собран на синтетической модели сети (DEMO_EZS), а не на данных
          компании. Бейджа у заголовка мало: проводки и суммы выглядят как
          настоящие и могут уйти в работу — нужен заметный баннер. */}
      <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
        <strong>Демонстрационные данные.</strong> Бухгалтерский контур для этого профиля
        ещё не подключён к учётной системе: проводки, обороты и суммы ниже —
        иллюстрация модели, а не факт. Не использовать для отчётности и сверок.
      </div>
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

/* ── агрегаты сети из DEMO_EZS ── */
// Выручка зарядки — с НДС (как в release.rub). НДС выделяется обратным счётом.
const revenueGross = all.reduce((a, s) => a + sumRelease(s).rub, 0)
const vatOnRevenue = Math.round(revenueGross - revenueGross / (1 + VAT_RATE))
const revenueNet = revenueGross - vatOnRevenue
// Закупка э/э (себестоимость отпуска) — из purchase.
const energyBuy = all.reduce((a, s) => a + sumBuy(s).rub, 0)
// Аренда площадок — по числу ЭЗС.
const rentCost = all.length * RENT_PER_EZS
// Эквайринг-комиссия — доля выручки ФЛ (карты ФЛ проходят эквайринг).
const flRevenue = all.reduce((a, s) => a + (s.release.fl?.rub ?? 0), 0)
const acquiringFee = Math.round(flRevenue * ACQUIRING_RATE)

/* ── журнал операций (учётная модель компании, обезличенно) ── */
const JOURNAL: Posting[] = [
  { op: 'Выручка по зарядным сессиям (с НДС)', dt: '62', kt: '90.01', rub: revenueGross, note: 'отпуск кВт·ч ЮЛ+ФЛ за период' },
  { op: 'НДС с выручки (22%)', dt: '90.03', kt: '68.02', rub: vatOnRevenue, note: 'обратный счёт от выручки' },
  { op: 'Закупка электроэнергии (себестоимость)', dt: '20', kt: '60', rub: energyBuy, note: 'счета поставщиков э/э' },
  { op: 'Аренда площадок ЭЗС', dt: '20', kt: '60', rub: rentCost, note: `${all.length} ЭЗС × ${fmtN(RENT_PER_EZS)} ₽/мес` },
  { op: 'Комиссия эквайринга', dt: '91', kt: '76', rub: acquiringFee, note: 'удержание банка-эквайера с карт ФЛ' },
]

/* ── сводка оборотов по счетам (Дт/Кт итоги) ── */
function buildTurnovers(postings: Posting[]) {
  const acc = new Map<string, { dt: number; kt: number }>()
  const touch = (code: string) => acc.get(code) ?? acc.set(code, { dt: 0, kt: 0 }).get(code)!
  for (const p of postings) {
    touch(p.dt).dt += p.rub
    touch(p.kt).kt += p.rub
  }
  return [...acc.entries()]
    .map(([code, v]) => ({ code, ...v }))
    .sort((a, b) => a.code.localeCompare(b.code, 'ru'))
}
const ACCOUNT_LABEL: Record<string, string> = {
  '20': 'Основное производство',
  '60': 'Расчёты с поставщиками',
  '62': 'Расчёты с покупателями',
  '68.02': 'НДС',
  '76': 'Расчёты с прочими дебиторами/кредиторами',
  '90.01': 'Выручка',
  '90.03': 'НДС с продаж',
  '91': 'Прочие доходы и расходы',
}

export function AccountingVitrine() {
  const totalPostings = JOURNAL.reduce((a, p) => a + p.rub, 0)
  const turnovers = buildTurnovers(JOURNAL)
  const dtTotal = turnovers.reduce((a, t) => a + t.dt, 0)
  const ktTotal = turnovers.reduce((a, t) => a + t.kt, 0)
  const balanced = dtTotal === ktTotal
  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Журнал операций" subtitle="Проводки по биллингу ЭЗС: выручка зарядки, НДС, закупка э/э, аренда, эквайринг. Обезличенно, по учётной модели компании." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Выручка с НДС, ₽" value={fmtN(revenueGross)} />
        <Kpi label="НДС к уплате (22%), ₽" value={fmtN(vatOnRevenue)} accent="warn" />
        <Kpi label="Закупка э/э, ₽" value={fmtN(energyBuy)} />
        <Kpi label="Проводок в журнале" value={String(JOURNAL.length)} />
      </div>

      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Журнал операций · {PERIOD}</div>
        <Table><TableHeader><TableRow>
          <TableHead className="w-[100px]">Дата</TableHead>
          <TableHead>Операция</TableHead>
          <TableHead className="text-center">Дт</TableHead>
          <TableHead className="text-center">Кт</TableHead>
          <TableHead className="text-right">Сумма, ₽</TableHead>
        </TableRow></TableHeader><TableBody>
          {JOURNAL.map((p, i) => (
            <TableRow key={i}>
              <TableCell className="tabular-nums text-muted-foreground">{PERIOD}</TableCell>
              <TableCell className="font-medium">
                {p.op}
                {p.note ? <div className="text-xs font-normal text-muted-foreground">{p.note}</div> : null}
              </TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className="text-[10px] tabular-nums">{p.dt}</Badge>
              </TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className="text-[10px] tabular-nums">{p.kt}</Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums font-medium">{fmtN(p.rub)}</TableCell>
            </TableRow>
          ))}
          <TableRow>
            <TableCell />
            <TableCell className="font-semibold">Итого по журналу</TableCell>
            <TableCell />
            <TableCell />
            <TableCell className="text-right tabular-nums font-semibold">{fmtN(totalPostings)}</TableCell>
          </TableRow>
        </TableBody></Table>
      </CardContent></Card>

      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          Сводка оборотов по счетам
          <Badge variant="secondary" className={`text-[10px] ${balanced ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400'}`}>
            {balanced ? 'Дт = Кт' : 'дисбаланс'}
          </Badge>
        </div>
        <Table><TableHeader><TableRow>
          <TableHead className="w-[90px]">Счёт</TableHead>
          <TableHead>Наименование</TableHead>
          <TableHead className="text-right">Оборот Дт, ₽</TableHead>
          <TableHead className="text-right">Оборот Кт, ₽</TableHead>
        </TableRow></TableHeader><TableBody>
          {turnovers.map((t) => (
            <TableRow key={t.code}>
              <TableCell className="font-medium tabular-nums">{t.code}</TableCell>
              <TableCell className="text-muted-foreground">{ACCOUNT_LABEL[t.code] ?? '—'}</TableCell>
              <TableCell className="text-right tabular-nums">{t.dt > 0 ? fmtN(t.dt) : '—'}</TableCell>
              <TableCell className="text-right tabular-nums">{t.kt > 0 ? fmtN(t.kt) : '—'}</TableCell>
            </TableRow>
          ))}
          <TableRow>
            <TableCell className="font-semibold">Итого</TableCell>
            <TableCell />
            <TableCell className="text-right tabular-nums font-semibold">{fmtN(dtTotal)}</TableCell>
            <TableCell className="text-right tabular-nums font-semibold">{fmtN(ktTotal)}</TableCell>
          </TableRow>
        </TableBody></Table>
      </CardContent></Card>

      <p className="text-xs text-muted-foreground/70">
        Выручка нетто (без НДС): {fmtN(revenueNet)} ₽; эквайринг с выручки ФЛ ({fmtN(flRevenue)} ₽): {fmtN(acquiringFee)} ₽.
        Проводки по учётной модели компании, демо.
      </p>
    </div>
  )
}
