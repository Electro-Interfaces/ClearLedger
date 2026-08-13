/**
 * Модель данных бухгалтерии — витрина «Базы пространства» для профиля `office`.
 *
 * Подача повторяет «Нормализацию» сетевых пространств (`EnergyNormalizationModel`):
 * слои приёма L1→L4, звёздная схема (факт с мерами + измерения с кардинальностью и
 * заполнением), качество полей и сведение к справочникам. Отличается предметная
 * область: там факт — зарядная сессия, здесь — проводка регистра.
 *
 * Данные: GET /api/books/model.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, KeyRound, Layers, Ruler, Sparkles, Star } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { MetricTile } from '@/components/ui/metric-tile'
import { getDataModel, type ModelDimension, type ModelLayer } from '@/services/booksService'

const nf = new Intl.NumberFormat('ru-RU')
const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

// Тона слоёв — те же, что у сетевых пространств: приём серый, нормализованное
// зелёное, витрины синие, эталон нейтральный.
const LAYER_TONE: Record<ModelLayer['tone'], { badge: string; border: string }> = {
  raw: { badge: 'bg-slate-500/15 text-slate-600 dark:text-slate-300', border: 'border-l-slate-400/50' },
  clean: { badge: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400', border: 'border-l-emerald-500/60' },
  export: { badge: 'bg-blue-500/15 text-blue-600 dark:text-blue-400', border: 'border-l-blue-500/60' },
  ref: { badge: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400', border: 'border-l-zinc-400/40' },
}

function FillBar({ pct }: { pct: number }) {
  const warn = pct < 80
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full max-w-[120px] overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${warn ? 'bg-amber-500/70' : 'bg-primary/70'}`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      <span className={`w-11 shrink-0 text-right text-xs tabular-nums ${
        warn ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
        {pct.toLocaleString('ru-RU')}%
      </span>
    </div>
  )
}

function DimensionCard({ d }: { d: ModelDimension }) {
  return (
    <Card className="h-full">
      <CardContent className="space-y-2 pt-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">{d.label}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{d.field}</div>
          </div>
          {d.canonical && (
            <Badge variant="outline" className="shrink-0 text-[10px] border-emerald-500/40 bg-emerald-500/5">
              канон
            </Badge>
          )}
        </div>
        <div className="flex items-baseline gap-2 text-xs text-muted-foreground">
          <span className="tabular-nums text-foreground">{nf.format(d.cardinality)}</span>
          значений{d.grain ? ` · ${d.grain}` : ''}
        </div>
        <FillBar pct={d.fill_pct} />
        <div className="space-y-0.5 pt-1">
          {d.members.map((m) => (
            <div key={m.label} className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate text-muted-foreground" title={m.label}>{m.label}</span>
              <span className="tabular-nums">{nf.format(m.count)}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export function OfficeDataModel() {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['books', 'model', companyId],
    queryFn: () => getDataModel(companyId),
    enabled: !!companyId,
  })

  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  const { layers, fact, dimensions, quality } = q.data

  return (
    <div className="space-y-4">
      {/* Слои приёма: путь данных от файла бухгалтерии до эталона закрытого месяца. */}
      <Card>
        <CardContent className="pt-5">
          <div className="mb-3 flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            <div className="text-sm font-medium">Слои данных</div>
            <span className="text-xs text-muted-foreground">
              выгрузка → нормализация → витрины → эталон
            </span>
          </div>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
            {layers.map((l, i) => (
              <div key={l.key} className="flex flex-1 items-stretch gap-3">
                <div className={`flex-1 rounded-lg border border-l-4 bg-card/50 p-3 ${LAYER_TONE[l.tone].border}`}>
                  <Badge variant="outline" className={`mb-1.5 text-[10px] ${LAYER_TONE[l.tone].badge}`}>
                    {l.code}
                  </Badge>
                  <div className="text-sm font-medium">{l.title}</div>
                  <div className="text-[11px] text-muted-foreground">{l.desc}</div>
                  <div className="mt-1 text-lg font-semibold tabular-nums">
                    {/* `status: direct` — слой не материализован, данные приняты
                        прямым импортом. Показывать здесь ноль или единицу значило бы
                        рисовать приём, которого в базе нет. */}
                    {l.status === 'direct'
                      ? <span className="text-sm font-normal text-muted-foreground">прямой импорт</span>
                      : <>
                          {l.records === null ? '—' : nf.format(l.records)}
                          {l.unit && <span className="ml-1 text-[11px] font-normal text-muted-foreground">{l.unit}</span>}
                        </>}
                  </div>
                </div>
                {i < layers.length - 1 && (
                  <ArrowRight className="hidden h-4 w-4 self-center text-muted-foreground/50 lg:block" />
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Факт и его меры — центр звезды. */}
      {fact && (
        <Card>
          <CardContent className="pt-5">
            <div className="mb-3 flex items-center gap-2">
              <Star className="h-4 w-4 text-primary" />
              <div className="text-sm font-medium">Факт: {fact.name}</div>
              <span className="font-mono text-[11px] text-muted-foreground">{fact.table}</span>
            </div>
            <p className="mb-3 text-xs text-muted-foreground">
              Гранулярность — {fact.grain}. Период данных: {fact.period.from} — {fact.period.to}.
            </p>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
              {fact.measures.map((m) => (
                <MetricTile key={m.key} label={`${m.label} · ${m.agg}`}
                  value={m.unit === '₽' ? `${money.format(m.value)} ₽` : nf.format(m.value)} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Измерения — лучи звезды. */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Ruler className="h-4 w-4 text-primary" />
          <div className="text-sm font-medium">Измерения</div>
          <span className="text-xs text-muted-foreground">по чему режется факт</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {dimensions.map((d) => <DimensionCard key={d.key} d={d} />)}
        </div>
      </div>

      {/* Качество: заполнение полей и сведение к справочникам. */}
      {quality && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-5">
              <div className="mb-3 flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-primary" />
                <div className="text-sm font-medium">Заполнение полей</div>
              </div>
              <div className="space-y-2">
                {quality.fields.map((f) => (
                  <div key={f.field} className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm">{f.label}</div>
                      <div className="font-mono text-[10px] text-muted-foreground">
                        {f.field} · {f.role}
                      </div>
                    </div>
                    <FillBar pct={f.fill_pct} />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              <div className="mb-3 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <div className="text-sm font-medium">Сведение к справочникам</div>
                <span className="text-xs text-muted-foreground">L1 → L2</span>
              </div>
              <div className="space-y-2">
                {quality.canonicalization.map((c) => (
                  <div key={c.name} className="rounded-md border p-2">
                    <div className="text-sm">{c.name}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {c.from} → <span className="font-mono">{c.to}</span>
                      {c.members !== null && <> · {nf.format(c.members)} записей</>}
                      {c.coverage_pct !== null && <> · покрытие {c.coverage_pct}%</>}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
