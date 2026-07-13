/**
 * Бухгалтерский срез потока «Сопутка/общепит» (ПОТОК 2). Детальная операционка/
 * аналитика (ассортимент, цены, НСИ, движение) — в разделе «Магазин»; здесь только
 * трубопровод для бухгалтерии: Загрузка из ЦБ → Смены → [Выгрузка в БП] → Сверка.
 * Выгрузка (tab==='export') рендерится напрямую BpExportPanel в AccountingPanel.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Database, ArrowRightLeft, CheckCircle2, XCircle } from 'lucide-react'
import { getStoreShifts, getBpPackageVerify } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { StoreShiftsPanel } from './StoreShiftsPanel'

const nf = (n: number) => new Intl.NumberFormat('ru-RU').format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

type StreamTab = 'cb_load' | 'cb_shifts' | 'cb_recon'

export function AccountingStreamsPanel({ tab, companyId, dateFrom, dateTo }: {
  tab: StreamTab; companyId: string; dateFrom: string; dateTo: string
}) {
  if (tab === 'cb_shifts') return <StoreShiftsPanel companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
  if (tab === 'cb_load') return <CbLoadPanel dateFrom={dateFrom} dateTo={dateTo} />
  return <CbReconPanel dateFrom={dateFrom} dateTo={dateTo} />
}

/* Загрузка из ЦБ — что принято из 1С ЭЛСИ.АЗК за период (сводка ingest). */
function CbLoadPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-shifts', dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" /> Загрузка из ЦБ — сопутка/общепит
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5 max-w-3xl">
          Источник — <b>ЦБ 1С ЭЛСИ.АЗК</b> (<code>azs_centre</code>, АЗС 208), механизм — COM-коннектор
          (<code>com_worker</code>, read-only). Отдельный поток от нефтепродуктов (те грузятся из STS).
          Детальная аналитика загруженного — в разделе «Магазин».
        </p>
      </div>

      {isLoading && <div className="text-sm text-muted-foreground">Загрузка сводки…</div>}
      {error && <div className="text-sm text-red-400/90">Ошибка загрузки сводки</div>}
      {data && (
        <>
          <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              { label: 'Смен загружено', value: nf(data.summary.count), hint: `${data.period.from} – ${data.period.to}` },
              { label: 'Выручка', value: money(data.summary.revenue) },
              { label: 'Приходы (ПТУ)', value: money(data.summary.receipts_amount) },
              { label: 'Инвентаризации', value: nf(data.summary.inventory_docs) },
              { label: 'Перемещения', value: nf(data.summary.transfer_docs) },
              { label: 'Переоценки', value: nf(data.summary.reval_docs) },
            ].map((k) => (
              <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
                <div className="text-[11px] text-muted-foreground">{k.label}</div>
                <div className="text-lg font-semibold tabular-nums mt-0.5">{k.value}</div>
                {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
              </div>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground/70">
            Приняты типы документов ЦБ: ОРП (розница), ПТУ (поступления), ВыпускПродукции + ТТК
            (общепит), ОприходованиеТоваров, инвентаризации/списания/перемещения. Далее — «Смены»,
            «Выгрузка в БП» и «Сверка» этого же потока.
          </p>
        </>
      )}
    </div>
  )
}

/* Сверка сопутки — самосогласованность пакета + готовность к загрузке (по смене). */
function CbReconPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const [key, setKey] = useState<string | null>(null)
  const shiftsQ = useQuery({
    queryKey: ['store-shifts', dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })
  const verifyQ = useQuery({
    queryKey: ['bp-verify', key],
    queryFn: () => getBpPackageVerify(key!),
    enabled: !!key,
  })
  const v = verifyQ.data ?? null

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4 text-muted-foreground" /> Сверка сопутки
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5 max-w-3xl">
          Самосогласованность пакета и готовность к загрузке приёмником: балансы документов,
          полнота НСИ, распознавание ставок НДС (fail-fast), хеш. Байт-точная сверка с эталоном
          TL_ЭкспортБП и проводочная — инструменты <code>bp_compare.py</code> / <code>bp_load_stand.py</code>.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
        <div className="rounded-lg border border-border/50 overflow-hidden">
          <div className="bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
            Смены {shiftsQ.data ? `(${shiftsQ.data.shifts.length})` : ''}
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {shiftsQ.isLoading && <div className="p-4 text-sm text-muted-foreground">Загрузка смен…</div>}
            <table className="w-full text-xs">
              <tbody>
                {shiftsQ.data?.shifts.map((sh) => (
                  <tr key={sh.shift_key} onClick={() => setKey(sh.shift_key)}
                    className={`border-t border-border/30 cursor-pointer ${key === sh.shift_key ? 'bg-accent/40' : 'hover:bg-accent/20'}`}>
                    <td className="px-3 py-1.5 whitespace-nowrap">{sh.date}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">АЗС{sh.station}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-medium">{money(sh.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="min-w-0">
          {!key && (
            <div className="rounded-lg border border-dashed border-border/50 p-8 text-center text-sm text-muted-foreground">
              Выберите смену — прогоним проверки пакета.
            </div>
          )}
          {key && verifyQ.isLoading && <div className="p-4 text-sm text-muted-foreground">Сверка…</div>}
          {key && verifyQ.error && <div className="p-4 text-sm text-red-400/90">Ошибка сверки</div>}
          {v && (
            <div className="space-y-3">
              <div className={`rounded-lg border p-3 flex flex-wrap items-center gap-3 ${v.ok ? 'border-emerald-400/40 bg-emerald-400/5' : 'border-red-400/40 bg-red-400/5'}`}>
                {v.ok
                  ? <span className="text-sm font-medium text-emerald-300/90 flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4" /> Пакет согласован — готов к загрузке</span>
                  : <span className="text-sm font-medium text-red-300/90 flex items-center gap-1.5"><XCircle className="h-4 w-4" /> Есть расхождения</span>}
                <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                  {v.passed}/{v.total} проверок · {v.Документов} док · {v.НСИ} НСИ · хеш {v.ХешПакета.slice(0, 12)}…
                </span>
              </div>
              <div className="overflow-x-auto rounded-lg border border-border/50">
                <table className="w-full text-xs">
                  <tbody>
                    {v.checks.map((c, i) => (
                      <tr key={i} className="border-t border-border/30 first:border-t-0">
                        <td className="px-3 py-1.5 w-6">
                          {c.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400/80" /> : <XCircle className="h-3.5 w-3.5 text-red-400/80" />}
                        </td>
                        <td className={`px-3 py-1.5 ${c.ok ? '' : 'text-red-300/90 font-medium'}`}>{c.Проверка}</td>
                        <td className="px-3 py-1.5 text-right text-muted-foreground tabular-nums">{c.Детали}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
