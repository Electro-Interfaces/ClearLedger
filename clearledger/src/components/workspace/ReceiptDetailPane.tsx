/**
 * Разбор одной накладной: сошёлся ли слив с документом и на что смотреть.
 *
 * Претензию поставщику предъявляют по массе: объём «дышит» с температурой, и на
 * станции объём накладной часто вписывают в факт один в один (у ГИГ так в 74%
 * ТТН) — по объёму недолив просто не видно. Поэтому масса первой, объём и
 * плотность ниже как обстоятельства.
 */
import { AlertTriangle, Check } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { DetailPane } from './DetailPane'
import { cn } from '@/lib/utils'
import type { ReceiptAnalysisRow } from '@/services/analyticsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf3 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

const KG = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} кг`)
const L = (v: number | null | undefined) => (v == null ? '—' : `${nf0.format(v)} л`)

function Line({ label, value, tone, hint }: {
  label: string; value: string; tone?: string; hint?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/50 py-1.5 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right">
        <span className={cn('font-mono text-xs', tone)}>{value}</span>
        {hint && <span className="ml-2 text-[11px] text-muted-foreground">{hint}</span>}
      </span>
    </div>
  )
}

function Block({ title, badge, children }: {
  title: string; badge?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <h4 className="text-xs font-semibold">{title}</h4>
        {badge}
      </div>
      <div className="px-3 py-1.5">{children}</div>
    </section>
  )
}

export function ReceiptDetailPane({ row, tolPct, tolKg, onClose }: {
  row: ReceiptAnalysisRow | null
  tolPct: number
  tolKg: number
  onClose: () => void
}) {
  if (!row) {
    return <DetailPane open={false} title="" onClose={onClose}><div /></DetailPane>
  }

  const bad = Math.abs(row.diff_mass_kg) > Math.max(tolKg, row.doc_mass_kg * tolPct)
  const shortfall = row.diff_mass_kg < 0
  const densGap = row.density_doc != null && row.density_fact != null
    ? row.density_fact - row.density_doc : null
  // Объём документа, пересчитанный по фактической плотности: если он близок к
  // фактическому объёму, значит расходится не количество, а именно плотность.
  const docVolByFactDens = row.density_fact ? row.doc_mass_kg / (row.density_fact * 1000) * 1000 : null

  return (
    <DetailPane
      open
      onClose={onClose}
      title={`ТТН ${row.ttn} · ${row.station_name}${row.tank != null ? ` · резервуар №${row.tank}` : ''}`}
      subtitle={
        <>
          {row.fuel_name} · {row.supplier || 'поставщик не указан'}
          {row.date && ` · ${new Date(row.date).toLocaleDateString('ru-RU')}`}
        </>
      }
      badges={
        <Badge variant="outline" className={cn(
          shortfall && bad ? 'border-red-500/40 text-red-400'
            : bad ? 'border-amber-500/40 text-amber-400'
            : 'border-emerald-500/40 text-emerald-400')}>
          {row.klass_title}
        </Badge>
      }
    >
      <Block
        title="Масса — основание претензии"
        badge={bad
          ? <span className="flex items-center gap-1 text-[11px] text-amber-500"><AlertTriangle className="h-3 w-3" />вне допуска</span>
          : <span className="flex items-center gap-1 text-[11px] text-emerald-500"><Check className="h-3 w-3" />в допуске</span>}
      >
        <Line label="По документу" value={KG(row.doc_mass_kg)} />
        <Line label="Принято фактически" value={KG(row.fact_mass_kg)} />
        <Line
          label={shortfall ? 'Недолив' : 'Перелив'}
          value={`${row.diff_mass_kg >= 0 ? '+' : ''}${nf1.format(row.diff_mass_kg)} кг`}
          tone={bad ? (shortfall ? 'text-red-500' : 'text-amber-500') : 'text-muted-foreground'}
          hint={row.diff_pct != null ? `${nf1.format(Math.abs(row.diff_pct))}% от документа` : undefined}
        />
        <Line label="Допуск" value={`${nf1.format(tolPct * 100)}% или ${nf0.format(tolKg)} кг`}
              hint="что больше" />
      </Block>

      <Block title="Объём и плотность — обстоятельства">
        <Line label="Объём по документу" value={L(row.doc_volume_l)} />
        <Line label="Объём принят" value={L(row.fact_volume_l)}
              hint={Math.abs(row.doc_volume_l - row.fact_volume_l) < 0.5
                ? 'совпал с документом до литра — вероятно, вписан из накладной' : undefined} />
        <Line label="Плотность документа" value={row.density_doc != null ? nf3.format(row.density_doc) : '—'} />
        <Line label="Плотность фактическая" value={row.density_fact != null ? nf3.format(row.density_fact) : '—'}
              tone={row.density_mismatch ? 'text-amber-500' : undefined}
              hint={densGap != null ? `${densGap >= 0 ? '+' : ''}${nf3.format(densGap)}` : undefined} />
        {docVolByFactDens != null && (
          <Line label="Объём документа по факт. плотности" value={L(docVolByFactDens)}
                hint={Math.abs(docVolByFactDens - row.fact_volume_l) < Math.abs(row.doc_volume_l - row.fact_volume_l)
                  ? 'ближе к принятому — расходится плотность, а не количество' : undefined} />
        )}
        <Line label="Температура док. / факт"
              value={`${row.temp_doc != null ? nf1.format(row.temp_doc) : '—'}° / ${row.temp_fact != null ? nf1.format(row.temp_fact) : '—'}°`} />
      </Block>

      <div className="rounded-lg border border-dashed px-3 py-2.5 text-[11px] text-muted-foreground">
        {row.klass === 'not_measured'
          ? 'Факт не измерен — приёмка приняла объём накладной как есть. Претензию предъявить нечем: замер при сливе обязателен.'
          : row.klass === 'broken_measure'
            ? 'Замер выглядит неполным: принятая масса заметно меньше документа, но и не ноль. Проверить, дослит ли бензовоз и не прервана ли приёмка.'
            : row.klass === 'shortfall'
              ? 'Недолив за пределами допуска — основание для претензии поставщику. Приложить накладную, акт слива и показания уровнемера до и после.'
              : row.klass === 'surplus'
                ? 'Принято больше документа. Проверить, не попал ли в замер остаток другой поставки и не слили ли в занятый резервуар.'
                : 'Слив сошёлся с документом в пределах допуска.'}
      </div>
    </DetailPane>
  )
}
