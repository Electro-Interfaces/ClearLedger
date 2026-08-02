/**
 * «Полнота данных» (раздел «Управленческий», energy) — каких документов и данных
 * не хватает за заданный период анализа. Наглядно:
 *   • тепловая матрица «вид данных × месяц» (% покрытия, have/expected в тултипе);
 *   • статические виды (договоры/НСИ/сироты) — общий % за период;
 *   • по каждому виду — раскрываемый список недостающего (станция → месяцы),
 *     клик по строке → карточка объекта (StationDrillModal).
 * Период (от/до, из доступных месяцев наблюдений) и регион — селекты.
 * Данные: /api/ops/completeness (services/ops_dashboard.ops_completeness).
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { ChevronDown, ChevronRight, FileWarning } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { getOpsCompleteness, type OpsComplKind } from '@/services/opsService'
import { StationDrillModal } from './OpsCockpit'
import { fmtN } from '@/components/balance/balanceCalc'
import { formatBucket } from '@/lib/formatDate'


/** Цвет ячейки теплокарты по % полноты. */
function heat(pct: number | null): string {
  if (pct == null) return 'bg-muted/30 text-muted-foreground/50'
  if (pct >= 95) return 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
  if (pct >= 70) return 'bg-amber-500/20 text-amber-700 dark:text-amber-400'
  if (pct >= 30) return 'bg-orange-500/25 text-orange-700 dark:text-orange-400'
  return 'bg-red-500/25 text-red-700 dark:text-red-400'
}

/* ── раскрываемый список недостающего по виду данных ── */
function KindDetails({ kind, onOpenStation }: { kind: OpsComplKind; onOpenStation: (id: string) => void }) {
  return (
    <div className="max-h-[340px] overflow-auto rounded-md border border-border/40">
      <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
        <TableHead>№ БУ</TableHead><TableHead>Объект / контрагент</TableHead>
        {kind.monthly && <TableHead>Не хватает за месяцы</TableHead>}
        <TableHead>Комментарий</TableHead>
      </TableRow></TableHeader><TableBody>
        {kind.rows.map((r, i) => (
          <TableRow key={`${r.locationId || r.name}-${i}`}
            className={r.locationId ? 'cursor-pointer hover:bg-muted/40' : ''}
            onClick={() => r.locationId && onOpenStation(r.locationId)}>
            <TableCell className="font-medium tabular-nums whitespace-nowrap">{r.bu || '—'}</TableCell>
            <TableCell className="max-w-[280px] truncate text-xs">
              {r.name}{r.region && <span className="ml-1 text-muted-foreground/70">· {r.region}</span>}
            </TableCell>
            {kind.monthly && (
              <TableCell className="text-xs tabular-nums text-muted-foreground">
                {r.months.map(formatBucket).join(', ')}
              </TableCell>
            )}
            <TableCell className="max-w-[260px] text-xs text-muted-foreground">{r.note}</TableCell>
          </TableRow>
        ))}
      </TableBody></Table>
      {kind.missingCount > kind.rows.length && (
        <p className="px-3 py-1.5 text-[11px] text-muted-foreground/70">Показаны {kind.rows.length} из {kind.missingCount}.</p>
      )}
    </div>
  )
}

export function OpsCompletenessVitrine() {
  const { companyId } = useCompany()
  const rootRef = useRef<HTMLDivElement>(null)
  const [from, setFrom] = useState<string | undefined>(undefined)
  const [to, setTo] = useState<string | undefined>(undefined)
  const [region, setRegion] = useState<string | undefined>(undefined)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [drill, setDrill] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['ops-completeness', companyId, from ?? 'auto', to ?? 'auto', region ?? 'all'],
    queryFn: () => getOpsCompleteness(companyId, from, to, region),
    enabled: !!companyId, staleTime: 60_000,
  })
  const d = q.data
  if (q.isLoading && !d) return <div className="px-6 py-10 text-sm text-muted-foreground">Загрузка полноты данных…</div>
  if (!d || d.months.length === 0) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Нет данных наблюдений — загрузите реестры и сессии.</div>
  }
  const monthly = d.kinds.filter((k) => k.monthly)
  const statics = d.kinds.filter((k) => !k.monthly)
  const missingTotal = d.kinds.reduce((a, k) => a + k.missingCount, 0)
  return (
    <div ref={rootRef} className="space-y-5 px-6 py-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <FileWarning className="h-5 w-5 text-primary" />
            <h1 className="text-xl font-semibold">Полнота данных</h1>
            <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
            <ExportButton title="Полнота данных ЭЗС" getEl={() => rootRef.current} />
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Каких документов и данных не хватает за период анализа — по месяцам и видам.
            Ожидания честные: счета ждём только от станций, которые в месяце работали;
            тарифы — только там, где есть счета. Клик по виду — список недостающего,
            клик по строке — карточка объекта.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={d.from ?? ''} onValueChange={(v) => setFrom(v)}>
            <SelectTrigger className="h-8 w-[120px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent className="max-h-[300px]">
              {d.monthsAll.map((m) => <SelectItem key={m} value={m}>{formatBucket(m)}</SelectItem>)}
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">—</span>
          <Select value={d.to ?? ''} onValueChange={(v) => setTo(v)}>
            <SelectTrigger className="h-8 w-[120px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent className="max-h-[300px]">
              {d.monthsAll.map((m) => <SelectItem key={m} value={m}>{formatBucket(m)}</SelectItem>)}
            </SelectContent>
          </Select>
          {d.regions.length > 0 && (
            <Select value={region ?? '__all'} onValueChange={(v) => setRegion(v === '__all' ? undefined : v)}>
              <SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-[300px]">
                <SelectItem value="__all">Все регионы</SelectItem>
                {d.regions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      {/* Тепловая матрица: помесячные виды данных */}
      <Card><CardContent className="space-y-2 pt-5">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">Покрытие по месяцам</div>
          <span className="text-xs text-muted-foreground/70">
            % станций, по которым данные есть, от ожидаемых · {fmtN(missingTotal)} недостающих позиций за период
          </span>
        </div>
        <div className="overflow-x-auto">
          <Table><TableHeader><TableRow>
            <TableHead className="min-w-[240px]">Вид данных / документ</TableHead>
            {d.months.map((m) => <TableHead key={m} className="text-center">{formatBucket(m)}</TableHead>)}
            <TableHead className="text-center">Итого</TableHead>
            <TableHead className="text-right">Не хватает</TableHead>
          </TableRow></TableHeader><TableBody>
            {monthly.map((k) => (
              <TableRow key={k.key} className="cursor-pointer hover:bg-muted/30"
                onClick={() => setOpen((o) => ({ ...o, [k.key]: !o[k.key] }))}>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    {open[k.key] ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                    <div>
                      <div className="text-sm font-medium">{k.label}</div>
                      <div className="text-[10px] text-muted-foreground/70">{k.doc}</div>
                    </div>
                  </div>
                </TableCell>
                {k.perMonth.map((c) => (
                  <TableCell key={c.period} className="p-1 text-center">
                    <span className={`inline-block min-w-[52px] rounded px-1.5 py-1 text-xs font-medium tabular-nums ${heat(c.pct)}`}
                      title={`${c.have} из ${c.expected}`}>
                      {c.pct != null ? `${Math.round(c.pct)}%` : '—'}
                    </span>
                  </TableCell>
                ))}
                <TableCell className="p-1 text-center">
                  <span className={`inline-block min-w-[52px] rounded px-1.5 py-1 text-xs font-semibold tabular-nums ${heat(k.pct)}`}>
                    {k.pct != null ? `${Math.round(k.pct)}%` : '—'}
                  </span>
                </TableCell>
                <TableCell className={`text-right tabular-nums ${k.missingCount ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                  {k.missingCount ? fmtN(k.missingCount) : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
        </div>
        {monthly.filter((k) => open[k.key]).map((k) => (
          <div key={`det-${k.key}`} className="space-y-1 pt-1">
            <p className="text-xs text-muted-foreground"><b className="text-foreground">{k.label}:</b> {k.hint}</p>
            <KindDetails kind={k} onOpenStation={setDrill} />
          </div>
        ))}
      </CardContent></Card>

      {/* Статические виды: договоры, НСИ, сироты */}
      <Card><CardContent className="space-y-2 pt-5">
        <div className="text-sm font-medium">Договорная база и НСИ (на период)</div>
        <Table><TableHeader><TableRow>
          <TableHead className="min-w-[240px]">Вид данных / документ</TableHead>
          <TableHead className="text-center">Полнота</TableHead>
          <TableHead className="text-right">Не хватает</TableHead>
          <TableHead>Что делать</TableHead>
        </TableRow></TableHeader><TableBody>
          {statics.map((k) => (
            <TableRow key={k.key} className="cursor-pointer hover:bg-muted/30"
              onClick={() => setOpen((o) => ({ ...o, [k.key]: !o[k.key] }))}>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  {open[k.key] ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                  <div>
                    <div className="text-sm font-medium">{k.label}</div>
                    <div className="text-[10px] text-muted-foreground/70">{k.doc}</div>
                  </div>
                </div>
              </TableCell>
              <TableCell className="p-1 text-center">
                <span className={`inline-block min-w-[52px] rounded px-1.5 py-1 text-xs font-semibold tabular-nums ${heat(k.pct)}`}>
                  {k.pct != null ? `${Math.round(k.pct)}%` : '—'}
                </span>
              </TableCell>
              <TableCell className={`text-right tabular-nums ${k.missingCount ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                {k.missingCount ? fmtN(k.missingCount) : '—'}
              </TableCell>
              <TableCell className="max-w-[360px] text-xs text-muted-foreground">{k.hint}</TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
        {statics.filter((k) => open[k.key]).map((k) => (
          <div key={`det-${k.key}`} className="pt-1">
            <KindDetails kind={k} onOpenStation={setDrill} />
          </div>
        ))}
      </CardContent></Card>

      <p className="text-xs text-muted-foreground/70">
        Зелёный ≥95% · жёлтый ≥70% · оранжевый ≥30% · красный &lt;30%. «Подтверждение оплаты» —
        отметка «оплачено по» реестра покрывает месяц; пустая отметка = нет данных об оплате
        (не обязательно долг — запросить подтверждение у ответственного.)
      </p>

      <StationDrillModal locationId={drill} onClose={() => setDrill(null)} />
    </div>
  )
}
