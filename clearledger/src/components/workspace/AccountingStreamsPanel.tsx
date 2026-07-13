/**
 * Бухгалтерский срез потока «Сопутка/общепит» (ПОТОК 2). Детальная операционка/
 * аналитика (ассортимент, цены, НСИ, движение) — в разделе «Магазин»; здесь только
 * трубопровод для бухгалтерии: Загрузка из ЦБ → Смены → [Выгрузка в БП] → Сверка.
 * Выгрузка (tab==='export') рендерится напрямую BpExportPanel в AccountingPanel.
 */
import { useQuery } from '@tanstack/react-query'
import { Database, ArrowRightLeft, ExternalLink } from 'lucide-react'
import { getStoreShifts } from '@/services/storeService'
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
  return <CbReconPanel />
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

/* Сверка сопутки — задел (готовность + инструмент bp_compare). */
function CbReconPanel() {
  return (
    <div className="p-6 space-y-4">
      <h3 className="text-base font-semibold flex items-center gap-2">
        <ArrowRightLeft className="h-4 w-4 text-muted-foreground" /> Сверка сопутки
      </h3>
      <div className="rounded-lg border border-amber-400/40 bg-amber-400/5 p-4 text-sm space-y-2">
        <p className="font-medium">Задел — параллельная сверка потока сопутки.</p>
        <p className="text-muted-foreground">
          Сверка пакета Ledger с текущим ЦБ-контуром и документами БП (состав/суммы/проводки)
          до совпадения 1:1 — гейт перед переключением источника на Ledger.
        </p>
        <ul className="text-xs text-muted-foreground list-disc pl-5 space-y-1">
          <li>Байт-точная сверка одной смены — инструмент <code>scripts/bp_compare.py</code> (эталон TL_ЭкспортБП ↔ наш пакет).</li>
          <li>Проводочная сверка — загрузка пакета на БП-стенд <code>scripts/bp_load_stand.py --provodki</code>.</li>
          <li>UI параллельной сверки за период — планируется (backend <code>/store/bp-package/compare</code>).</li>
        </ul>
      </div>
      <p className="text-[11px] text-muted-foreground/70 flex items-center gap-1">
        <ExternalLink className="h-3 w-3" /> Готовность пакета видна на вкладке «Выгрузка в БП» (индикатор + хеш).
      </p>
    </div>
  )
}
