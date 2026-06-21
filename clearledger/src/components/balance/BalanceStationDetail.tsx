/**
 * Drill-down по объекту баланса (ЭЗС): полоса баланса со стеком потерь, закупка/отпуск,
 * сверка выручки three-way, тарификация и — ключевое по ТЗ §4.3.4 — статус КАЖДОГО
 * временного интервала (Достоверно/Подозрительно/Сбой по VEE-флагам). Демо-данные.
 */
import { useMemo, type ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Download } from 'lucide-react'
import type { BalanceModuleDef } from '@/config/balanceModules'
import {
  STATUS_META, SPEED_META, generateIntervals, rollupStatus, revenue3way, tariffCheck,
  sumBuy, sumRelease, lossKwh, lossRub, lossPct, techLossKwh, commLossKwh, purchaseRate, fmtN,
  normBreakdown, meterCheck, releaseCheck, supplierContract, stationClaims,
  PAYMENT_POLICY_LABEL, CONTRACT_STATUS_META, CLAIM_TARGET_LABEL, CLAIM_STATUS_META,
  type StationBalance,
} from './balanceCalc'
import { exportStationPassport } from './balancePassport'

export function BalanceStationDetail({
  station, mod, year, month, onClose,
}: {
  station: StationBalance | null
  mod: BalanceModuleDef
  year: number
  month: number
  onClose: () => void
}) {
  const intervals = useMemo(
    () => (station ? generateIntervals(station, year, month) : []),
    [station, year, month],
  )
  if (!station) return null
  const u = mod.unit

  const buy = sumBuy(station), rel = sumRelease(station)
  const rollup = rollupStatus(intervals)
  const rate = purchaseRate(station)
  const tech = techLossKwh(station), comm = commLossKwh(station)
  const okN = intervals.filter((i) => i.quality === 'ok').length
  const reviewN = intervals.filter((i) => i.quality === 'review').length
  const failN = intervals.filter((i) => i.quality === 'fail').length
  const estN = intervals.filter((i) => i.estimated).length
  const rev = revenue3way(station)
  const tar = tariffCheck(station)
  const nb = normBreakdown(station)
  const meter = meterCheck(station)
  const release = releaseCheck(station)
  const contract = supplierContract(station)
  const claims = stationClaims(station)

  // доли для стек-бара (от поступления)
  const pct = (x: number) => (buy.kwh > 0 ? Math.max((x / buy.kwh) * 100, 0) : 0)

  return (
    <Dialog open={!!station} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="flex max-h-[88vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="shrink-0 space-y-0.5 border-b border-border/50 px-5 py-3">
          <div className="flex items-start justify-between gap-3 pr-8">
            <div className="min-w-0 space-y-0.5">
              <DialogTitle className="flex flex-wrap items-center gap-2 text-base">
                {station.name}
                <Badge variant="secondary" className={`text-[10px] ${STATUS_META[rollup].cls}`}>{STATUS_META[rollup].label}</Badge>
              </DialogTitle>
              <div className="text-xs text-muted-foreground">{station.region} · {SPEED_META[station.speed]} · {station.power} кВт · норматив {station.normPct}%</div>
            </div>
            <Button variant="outline" size="sm" className="h-8 shrink-0" onClick={() => exportStationPassport(station, mod, year, month)}>
              <Download className="mr-1.5 h-3.5 w-3.5" /> Паспорт
            </Button>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-4 p-5">
            {/* Полоса баланса со стеком потерь */}
            <div className="rounded-lg border border-border/50 p-4">
              <div className="mb-3 grid grid-cols-3 gap-3">
                <Flow label="Поступление" value={`${fmtN(buy.kwh)} ${u}`} />
                <Flow label="Полезный отпуск" value={`${fmtN(rel.kwh)} ${u}`} tone="text-emerald-600 dark:text-emerald-400" />
                <Flow label="Потери" value={`${fmtN(lossKwh(station))} ${u}`} tone="text-red-600 dark:text-red-400"
                  sub={`${lossPct(station).toFixed(1)}% · ${fmtN(lossRub(station))} ₽`} />
              </div>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
                <span style={{ width: `${pct(rel.kwh)}%`, backgroundColor: '#10b981' }} title="Полезный отпуск" />
                <span style={{ width: `${pct(tech)}%`, backgroundColor: '#f59e0b' }} title="Технологические" />
                <span style={{ width: `${pct(comm)}%`, backgroundColor: '#ef4444' }} title="Коммерческие" />
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                <Legend color="#10b981" label="Полезный отпуск" value={`${fmtN(rel.kwh)} ${u}`} />
                <Legend color="#f59e0b" label={`Технологические (≤ ${station.normPct}%)`} value={`${fmtN(tech)} ${u}`} />
                <Legend color="#ef4444" label="Коммерческие (небаланс)" value={`${fmtN(comm)} ${u}`} danger={comm > 0} />
              </div>
              <div className="mt-1.5 text-[11px] text-muted-foreground/70">
                Норматив {nb.total}% (от физики): {nb.base.label} {nb.base.pct}% + {nb.power.label} {nb.power.pct}%
              </div>
            </div>

            {/* Закупка + Отпуск */}
            <div className="grid gap-4 lg:grid-cols-2">
              <Block title="Закупка по поставщикам">
                {station.purchase.map((p) => (
                  <KV key={p.supplier} k={p.supplier} kwh={`${fmtN(p.kwh)} ${u}`} rub={`${fmtN(p.rub)} ₽${p.kwh ? ` · ${(p.rub / p.kwh).toFixed(2)} ₽/${u}` : ''}`} />
                ))}
                <KV k="Итого закупка" kwh={`${fmtN(buy.kwh)} ${u}`} rub={`${fmtN(buy.rub)} ₽ · ${rate.toFixed(2)} ₽/${u}`} bold />
              </Block>
              <Block title="Полезный отпуск по категориям">
                {mod.categories.map((c) => {
                  const r = station.release[c.id] ?? { kwh: 0, rub: 0 }
                  return <KV key={c.id} k={c.label} kwh={`${fmtN(r.kwh)} ${u}`} rub={`${fmtN(r.rub)} ₽${r.kwh ? ` · ${(r.rub / r.kwh).toFixed(2)} ₽/${u}` : ''}`} />
                })}
                <KV k="Итого отпуск" kwh={`${fmtN(rel.kwh)} ${u}`} rub={`${fmtN(rel.rub)} ₽`} bold />
                {station.unpaid.kwh > 0 && (
                  <KV k="в т.ч. неоплаченная (холд < факт)" kwh={`${fmtN(station.unpaid.kwh)} ${u}`} rub={`${fmtN(station.unpaid.rub)} ₽ · дебиторка`} amber />
                )}
              </Block>
            </div>

            {/* Сверка закупки ПУ ЭЗС ↔ ПУ поставщика (§4.1.1) */}
            <Block title="Сверка закупки: ПУ ЭЗС ↔ ПУ поставщика">
              <div className="grid grid-cols-3 gap-3">
                <Metric label="ПУ ЭЗС (наш счётчик)" value={`${fmtN(meter.ezs)} ${u}`} />
                <Metric label="ПУ поставщика (счёт)" value={`${fmtN(meter.supplier)} ${u}`} />
                <Metric label="Расхождение" value={`${meter.diff > 0 ? '+' : ''}${fmtN(meter.diff)} ${u} · ${meter.diffPct.toFixed(1)}%`} danger={!meter.ok} />
              </div>
              <p className={`mt-2 text-[11px] ${meter.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                {meter.ok
                  ? 'Объём закупки подтверждён: показания сходятся (< 0.5%).'
                  : meter.diff > 0
                    ? `Поставщик выставил больше нашего ПУ на ${fmtN(meter.diff)} ${u} — основание для претензии (§4.1.1).`
                    : `Наш ПУ показал больше счёта поставщика на ${fmtN(-meter.diff)} ${u} — уточнить у поставщика (§4.1.1).`}
              </p>
            </Block>

            {/* Сверка отпуска ПУ ЭЗС ↔ данные ПК (§4.1.3) */}
            <Block title="Сверка отпуска: ПУ ЭЗС ↔ данные ПК">
              <div className="grid grid-cols-3 gap-3">
                <Metric label="Ожидаемый отпуск (баланс)" value={`${fmtN(release.expected)} ${u}`} />
                <Metric label="ПК (зарядные сессии)" value={`${fmtN(release.pk)} ${u}`} />
                <Metric label="Небаланс" value={`${release.gap > 0 ? '−' : '+'}${fmtN(Math.abs(release.gap))} ${u} · ${release.gapPct.toFixed(1)}%`} danger={!release.ok} />
              </div>
              <p className={`mt-2 text-[11px] ${release.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                {release.ok
                  ? 'Отпуск ПК соответствует балансу (приход − технолог. потери).'
                  : `ПК отпустил меньше ожидаемого на ${fmtN(release.gap)} ${u} — коммерческий небаланс, разбор с техподдержкой ПК (§4.1.3).`}
              </p>
            </Block>

            {/* Выручка three-way + Тарификация */}
            <div className="grid gap-4 lg:grid-cols-2">
              <Block title="Сверка выручки: эквайер ↔ ОФД ↔ ПК">
                <KV k="ПК (зарядные сессии)" kwh={`${fmtN(rev.pk)} ₽`} rub="расчётная выручка" />
                <KV k="ОФД (фискальные чеки)" kwh={`${fmtN(rev.ofd)} ₽`} rub={rev.diffOfd > 0 ? `−${fmtN(rev.diffOfd)} ₽ непробито` : 'сходится'} amber={rev.diffOfd > 0} />
                <KV k="Банк-эквайер (зачислено)" kwh={`${fmtN(rev.acquirer)} ₽`} rub={`${rev.diffAcq >= 0 ? '−' : '+'}${fmtN(Math.abs(rev.diffAcq))} ₽ комиссия/T+1`} />
                {rev.holdShort > 0 && <KV k="холд < факт (к доплате)" kwh={`${fmtN(rev.holdShort)} ₽`} rub="дебиторка" amber />}
              </Block>
              <Block title="Тарификация — полнота начислений">
                <div className="grid grid-cols-3 gap-2 text-center">
                  <MiniMetric label="Сессий" value={fmtN(tar.sessions)} />
                  <MiniMetric label="Без тарифа" value={fmtN(tar.noCategory)} danger={tar.noCategory > 0} />
                  <MiniMetric label="Вне НПА" value={fmtN(tar.rateMismatch)} danger={tar.rateMismatch > 0} />
                </div>
                <p className={`mt-2 text-[11px] ${tar.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                  {tar.ok ? 'Каждый кВт·ч тарифицирован по актуальному НПА и категории.' : 'Есть сессии без корректной тарификации — разбор через claim.'}
                </p>
              </Block>
            </div>

            {/* Договор поставщика + взаиморасчёты (§6) + Обращения (claim) */}
            <div className="grid gap-4 lg:grid-cols-2">
              <Block title="Договор поставщика + взаиморасчёты">
                <div className="mb-2 flex items-center gap-2 text-sm">
                  <span className="min-w-0 truncate font-medium">{contract.supplier}</span>
                  <Badge variant="secondary" className={`text-[10px] ${CONTRACT_STATUS_META[contract.status].cls}`}>{CONTRACT_STATUS_META[contract.status].label}</Badge>
                </div>
                <KV k={`Договор ${contract.number}`} kwh={contract.since} rub={`до ${contract.until}`} />
                <KV k="Начислено" kwh={`${fmtN(contract.accrued)} ₽`} rub={`оплачено ${fmtN(contract.paid)} ₽`} />
                <KV k="Сальдо (задолженность)" kwh={`${fmtN(contract.debt)} ₽`} rub={contract.debt > 0 ? 'к оплате' : 'нет долга'} amber={contract.debt > 0} />
                <div className="mt-2 text-[11px] text-muted-foreground">
                  Методология оплаты: <span className="text-foreground">{PAYMENT_POLICY_LABEL[contract.paymentPolicy]}</span>
                  <span className="text-muted-foreground/60"> · вариант при отсутствии документов (§6)</span>
                </div>
                {(contract.status === 'amending' || contract.status === 'terminating') && (
                  <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
                    {contract.status === 'amending'
                      ? 'Идёт пересмотр условий договора (в т.ч. по изменению законодательства РФ).'
                      : 'Инициировано расторжение — финальная сверка взаиморасчётов.'}
                  </div>
                )}
              </Block>
              <Block title={`Обращения (claim) · ${claims.length}`}>
                {claims.length === 0 ? (
                  <p className="text-[11px] text-emerald-600 dark:text-emerald-400">Расхождений нет — обращения не требуются.</p>
                ) : (
                  <div className="space-y-1.5">
                    {claims.map((c) => (
                      <div key={c.id} className="flex items-start justify-between gap-2 border-b border-border/20 pb-1.5 text-xs last:border-0 last:pb-0">
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <Badge variant="outline" className="text-[9px]">{CLAIM_TARGET_LABEL[c.target]}</Badge>
                            <Badge variant="secondary" className={`text-[9px] ${CLAIM_STATUS_META[c.status].cls}`}>{CLAIM_STATUS_META[c.status].label}</Badge>
                          </div>
                          <div className="mt-0.5 text-muted-foreground">{c.subject}</div>
                        </div>
                        <div className="shrink-0 text-right tabular-nums">
                          {c.amountRub > 0 && <div>{fmtN(c.amountRub)} ₽</div>}
                          <div className="text-[10px] text-muted-foreground/70">до {c.due}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Block>
            </div>

            {/* Интервалы со статусом качества */}
            <Block title={`Интервалы (сутки) — статус качества · ✓${okN} ⚠${reviewN} ✗${failN}${estN ? ` · оценочных ${estN}` : ''}`}>
              <div className="overflow-hidden rounded-md border border-border/40">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">Дата</th>
                      <th className="px-2 py-1.5 text-left font-medium">Статус</th>
                      <th className="px-2 py-1.5 text-left font-medium">Причина (VEE)</th>
                      <th className="px-2 py-1.5 text-right font-medium">Приход</th>
                      <th className="px-2 py-1.5 text-right font-medium">Отпуск</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intervals.map((iv) => (
                      <tr key={iv.date} className="border-t border-border/20">
                        <td className="px-2 py-1 tabular-nums">{iv.date.slice(8)}.{iv.date.slice(5, 7)}</td>
                        <td className="px-2 py-1">
                          <Badge variant="secondary" className={`text-[9px] ${STATUS_META[iv.quality].cls}`}>{STATUS_META[iv.quality].label}</Badge>
                        </td>
                        <td className="px-2 py-1 text-muted-foreground">
                          {iv.reason}{iv.estimated && <span className="ml-1 italic text-amber-600 dark:text-amber-400">(оценка)</span>}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">{fmtN(iv.prihodKwh)}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{fmtN(iv.otpuskKwh)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground/70">
                Статус — каждому интервалу (VEE: Validation→Estimation→Editing); статус объекта — производный (худший). Правки — сторно-записью.
              </p>
            </Block>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border/50 p-4">
      <div className="mb-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">{title}</div>
      {children}
    </div>
  )
}

function Flow({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone ?? ''}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground/70 tabular-nums">{sub}</div>}
    </div>
  )
}

function Legend({ color, label, value, danger }: { color: string; label: string; value: string; danger?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label} <span className={`tabular-nums ${danger ? 'font-medium text-red-600 dark:text-red-400' : ''}`}>{value}</span>
    </span>
  )
}

function KV({ k, kwh, rub, bold, amber }: { k: string; kwh: string; rub: string; bold?: boolean; amber?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 border-b border-border/20 py-1 text-sm last:border-0 ${bold ? 'font-medium' : ''} ${amber ? 'text-amber-600 dark:text-amber-400' : ''}`}>
      <span className="min-w-0 truncate">{k}</span>
      <span className="shrink-0 text-right tabular-nums">
        <span>{kwh}</span>
        <span className="ml-3 text-xs text-muted-foreground">{rub}</span>
      </span>
    </div>
  )
}

function MiniMetric({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="rounded-md bg-muted/40 py-2">
      <div className={`text-base font-semibold tabular-nums ${danger ? 'text-red-600 dark:text-red-400' : ''}`}>{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  )
}

function Metric({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-sm font-semibold tabular-nums ${danger ? 'text-red-600 dark:text-red-400' : ''}`}>{value}</div>
    </div>
  )
}
