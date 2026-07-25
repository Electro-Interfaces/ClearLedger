/**
 * Разбор одной строки журнала резервуара — что произошло с топливом за смену.
 *
 * В таблице строка отвечает на вопрос «сколько», здесь — «сходится ли и почему
 * нет». Поэтому три контроля показаны раздельно и в том виде, в каком их
 * проверяют вручную: арифметика книги — формулой, книга против замера — с ценой
 * расхождения, стык с предыдущей сменой — с названной причиной. Ниже то, чего в
 * таблице нет: накладные смены (подтверждение прихода перед поставщиком), масса
 * (объём «дышит» с температурой, масса нет) и физика замера.
 */
import { AlertTriangle, Check } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { TankLedgerRow } from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf3 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

const L = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} л`)
const KG = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} кг`)

/** Строка «показатель → значение». Значение моноширинное — цифры сравнивают глазами. */
function Line({ label, value, tone, hint, strong }: {
  label: string; value: string; tone?: string; hint?: string; strong?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className={cn('text-xs', strong ? 'font-medium' : 'text-muted-foreground')}>
        {label}
        {hint && <span className="ml-1 text-[10px] text-muted-foreground/70">{hint}</span>}
      </span>
      <span className={cn('shrink-0 text-xs tabular-nums', strong && 'font-medium', tone)}>{value}</span>
    </div>
  )
}

function Block({ title, badge, children }: {
  title: string; badge?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border bg-card p-3">
      <div className="mb-1.5 flex items-center gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        {badge}
      </div>
      {children}
    </section>
  )
}

function Verdict({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
      ok ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
         : 'bg-red-500/10 text-red-600 dark:text-red-400')}>
      {ok ? <Check className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
      {text}
    </span>
  )
}

const BREAK_LABEL: Record<string, string> = {
  delivery: 'слив между сменами', renumber: 'перенумерация', gap: 'пауза между сменами',
  fuel_change: 'смена топлива', book_reset: 'сброс книги', pulled_to_fact: 'списано на станции',
  manual: 'ручная правка', reversal: 'возврат', unexplained: 'требует разбора',
}
/** Причины, за которыми стоит документ или техническое событие, а не потеря топлива. */
const BENIGN = new Set(['delivery', 'renumber', 'gap', 'fuel_change', 'reversal'])

export function TankShiftDialog({ row, tol, onClose }: {
  row: TankLedgerRow | null
  /** Порог, ниже которого расхождение книги с замером — погрешность прибора. */
  tol: number
  onClose: () => void
}) {
  if (!row) return null

  const ariBad = Math.abs(row.arithmetic_gap) > 0.5
  const expected = row.book_start + row.receipts - row.sales
  const contBad = row.continuity_gap != null && Math.abs(row.continuity_gap) > 0.5
  const factBad = row.fact_gap != null && Math.abs(row.fact_gap) > tol
  const kind = row.continuity_kind ?? (row.fuel_changed ? 'fuel_change' : null)
  const gapPct = row.fact_gap != null && row.sales > 0 ? (row.fact_gap / row.sales) * 100 : null

  const docs = row.receipts_docs ?? []
  const docsSum = docs.reduce((a, d) => a + d.volume, 0)
  const docsMatch = docs.length > 0 && Math.abs(docsSum - row.receipts) <= Math.max(1, row.receipts * 0.02)

  const hasMass = row.mass_start != null || row.mass_end != null || row.fact_mass != null

  return (
    <Dialog open={!!row} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="flex max-h-[85dvh] w-[94vw] max-w-2xl flex-col overflow-hidden border-border bg-card sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-base">
            {row.station_name} · резервуар №{row.tank_number} · {row.fuel_name}
          </DialogTitle>
          <p className="text-xs text-muted-foreground">
            Смена №{row.shift_number}
            {row.opened_at && ` · открыта ${new Date(row.opened_at).toLocaleString('ru-RU')}`}
            {row.closed_at && ` · закрыта ${new Date(row.closed_at).toLocaleString('ru-RU')}`}
          </p>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
          {/* 1. Арифметика книги — счёт внутри смены, обязан сходиться точно. */}
          <Block title="Движение книги за смену"
                 badge={<Verdict ok={!ariBad} text={ariBad ? 'счёт не сходится' : 'счёт сходится'} />}>
            <Line label="Книга на начало" value={L(row.book_start)} />
            <Line label="+ Приход (слив)" value={L(row.receipts)}
                  tone={row.receipts > 0 ? 'text-blue-600 dark:text-blue-400' : undefined} />
            <Line label="− Отпуск через ТРК" value={L(row.sales)} />
            <div className="my-1 border-t" />
            <Line label="= Должно получиться" value={L(expected)} />
            <Line label="Книга на конец (в отчёте)" value={L(row.book_end)} strong />
            {ariBad && (
              <>
                <Line label="Расхождение счёта" value={`${nf1.format(row.arithmetic_gap)} л`} strong
                      tone="text-red-600 dark:text-red-400" />
                <p className="mt-1.5 text-[11px] text-red-600/90 dark:text-red-400/90">
                  Отчёт внутренне противоречив: считать по нему нельзя, пока станция не исправит смену.
                </p>
              </>
            )}
          </Block>

          {/* 2. Книга против замера — предмет инвентаризации. */}
          <Block title="Книга и фактический замер"
                 badge={row.fact_end == null
                   ? <span className="text-[10px] text-muted-foreground">замера нет</span>
                   : <Verdict ok={!factBad} text={factBad
                       ? (row.fact_gap! > 0 ? 'недостача' : 'излишек')
                       : 'в пределах погрешности'} />}>
            <Line label="Факт на начало" hint="замер конца предыдущей смены" value={L(row.fact_start)} />
            <Line label="Книга на конец" value={L(row.book_end)} />
            <Line label="Факт на конец" hint="уровнемер" value={L(row.fact_end)} strong />
            <div className="my-1 border-t" />
            <Line label="Книга − факт" strong
                  value={row.fact_gap == null ? '—'
                    : `${nf0.format(Math.abs(row.fact_gap))} л ${row.fact_gap > 0 ? 'недостача' : 'излишек'}`}
                  tone={!factBad ? 'text-muted-foreground'
                    : row.fact_gap! > 0 ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400'} />
            {gapPct != null && (
              <Line label="Доля от отпуска за смену" value={`${nf1.format(Math.abs(gapPct))} %`} />
            )}
            <p className="mt-1.5 text-[11px] text-muted-foreground/80">
              {row.fact_end == null
                ? 'Уровнемер не дал показание за эту смену — сравнивать не с чем; в инвентаризацию резервуар не берётся.'
                : `Замер — измерение, у него есть погрешность: расхождение до ${nf0.format(tol)} л считаем шумом. Важна не одна смена, а накопление за период: книга к факту сама не подтягивается, пока не проведена инвентаризация.`}
            </p>
          </Block>

          {/* 3. Стык — связь с предыдущей сменой и названная причина разрыва. */}
          <Block title="Стык с предыдущей сменой"
                 badge={row.continuity_gap == null
                   ? <span className="text-[10px] text-muted-foreground">начало периода</span>
                   : <Verdict ok={!contBad && !row.fuel_changed}
                              text={contBad || row.fuel_changed ? (kind ? BREAK_LABEL[kind] ?? 'разрыв' : 'разрыв') : 'сходится'} />}>
            {row.continuity_gap == null ? (
              <p className="text-[11px] text-muted-foreground">
                Первая смена периода по этому резервуару — сверять не с чем.
              </p>
            ) : (
              <>
                <Line label="Конец предыдущей смены" value={L(row.book_start - row.continuity_gap)} />
                <Line label="Начало этой смены" value={L(row.book_start)} strong />
                <Line label="Разрыв" value={`${nf1.format(row.continuity_gap)} л`} strong
                      tone={contBad ? (kind && BENIGN.has(kind)
                        ? 'text-blue-600 dark:text-blue-400'
                        : 'text-amber-600 dark:text-amber-400') : 'text-muted-foreground'} />
                {row.continuity_reason && (
                  <p className={cn('mt-1.5 text-[11px]', kind && BENIGN.has(kind)
                    ? 'text-blue-600/90 dark:text-blue-400/90'
                    : 'text-amber-600/90 dark:text-amber-400/90')}>
                    {row.continuity_reason}
                  </p>
                )}
                {!contBad && !row.fuel_changed && (
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    Книга ведётся непрерывно: начало смены равно концу предыдущей.
                  </p>
                )}
              </>
            )}
          </Block>

          {/* 4. Накладные — то, чем приход подтверждается перед поставщиком. */}
          {(docs.length > 0 || row.receipts > 0) && (
            <Block title="Накладные смены"
                   badge={docs.length === 0
                     ? <span className="text-[10px] text-amber-600 dark:text-amber-400">приход без накладной</span>
                     : <Verdict ok={docsMatch} text={docsMatch ? 'сходится с приходом' : 'расходится с приходом'} />}>
              {docs.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  В резервуар принято {L(row.receipts)}, но накладной за этой сменой не закреплено —
                  подтвердить поставку перед поставщиком нечем.
                </p>
              ) : (
                <>
                  {docs.map((d, i) => (
                    <Line key={`${d.ttn}-${i}`} label={`ТТН ${d.ttn}`} value={L(d.volume)} />
                  ))}
                  <div className="my-1 border-t" />
                  <Line label="Итого по накладным" value={L(docsSum)} strong />
                  <Line label="Принято в резервуар" value={L(row.receipts)} strong />
                  {!docsMatch && (
                    <Line label="Разница" value={`${nf1.format(row.receipts - docsSum)} л`} strong
                          tone="text-amber-600 dark:text-amber-400" />
                  )}
                </>
              )}
            </Block>
          )}

          {/* 5. Масса — объём меняется с температурой, масса нет. */}
          {hasMass && (
            <Block title="Масса, кг">
              <Line label="На начало" value={KG(row.mass_start)} />
              <Line label="+ Приход" value={KG(row.mass_received)} />
              <Line label="− Отпуск" value={KG(row.mass_sales)} />
              <Line label="Книга на конец" value={KG(row.mass_end)} strong />
              <Line label="Факт (замер)" value={KG(row.fact_mass)} strong />
              <p className="mt-1.5 text-[11px] text-muted-foreground/80">
                Объём меняется с температурой, масса — нет. Если расхождение видно в литрах,
                но не в килограммах, дело в температуре, а не в потере топлива.
              </p>
            </Block>
          )}

          {/* 6. Физика замера — контекст, объясняющий часть расхождения. */}
          <Block title="Условия замера">
            <Line label="Плотность на начало / конец"
                  value={`${row.density_beg != null ? nf3.format(row.density_beg) : '—'} / ${row.density_end != null ? nf3.format(row.density_end) : '—'}`} />
            <Line label="Температура на начало / конец"
                  value={`${row.temp_beg != null ? nf1.format(row.temp_beg) : '—'}° / ${row.temp_end != null ? nf1.format(row.temp_end) : '—'}°`} />
            <Line label="Уровень" value={row.level_end != null ? `${nf0.format(row.level_end)} мм` : '—'} />
            <Line label="Подтоварная вода" value={row.water_volume ? L(row.water_volume) : 'нет'}
                  tone={row.water_volume ? 'text-amber-600 dark:text-amber-400' : undefined} />
          </Block>
        </div>
      </DialogContent>
    </Dialog>
  )
}
