/**
 * «Контрагенты» — кто как с нами работает и по какому телефону звонить.
 *
 * Без этой таблицы «контрагент не присылает документы» остаётся ощущением.
 * С ней это список имён с контактами, суммами и числом молчащих периодов.
 *
 * Сортировка по деньгам, а не по проценту: молчащий контрагент на двести тысяч
 * важнее аккуратного на пятьсот рублей. Столбец «нет контакта» — отдельная
 * дырка: требовать документы не с кого, пока в карточке пусто.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { AlertTriangle, Loader2, Mail, Phone } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { getOpsCounterparties, type OpsCounterpartyRow } from '@/services/opsService'
import { MetricTile as Kpi } from '@/components/ui/metric-tile'

const money = (v: number) => fmtN(Math.round(v))

/** Цвет дисциплины. Порог 90 — не «отлично», а «период закрывается без нас». */
const disciplineTone = (pct: number | null) =>
  pct === null ? 'text-muted-foreground'
    : pct >= 90 ? 'text-emerald-600 dark:text-emerald-400'
    : pct >= 60 ? 'text-amber-600 dark:text-amber-400'
    : 'text-red-600 dark:text-red-400'

export function OpsCounterpartiesPanel() {
  const { companyId } = useCompany()
  const [months, setMonths] = useState(12)
  const [onlyProblem, setOnlyProblem] = useState(false)

  const q = useQuery({
    queryKey: ['ops-counterparties', companyId, months],
    queryFn: () => {
      const d = new Date()
      d.setDate(1)
      d.setMonth(d.getMonth() - 1)
      const to = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
      d.setMonth(d.getMonth() - (months - 1))
      const from = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
      return getOpsCounterparties(companyId!, from, to)
    },
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return <div className="flex justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.isError || !q.data) {
    return <div className="p-6 text-sm text-red-600 dark:text-red-400">
      Не удалось загрузить дисциплину контрагентов. Обновите страницу.
    </div>
  }

  const d = q.data
  const rows = onlyProblem
    ? d.rows.filter((r) => r.missing > 0 || (r.onTimePct ?? 100) < 60)
    : d.rows

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <select value={months} onChange={(e) => setMonths(Number(e.target.value))}
          className="h-9 rounded-md border border-border bg-background px-2 text-sm">
          <option value={3}>За квартал</option>
          <option value={6}>За полгода</option>
          <option value={12}>За год</option>
        </select>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={onlyProblem}
            onChange={(e) => setOnlyProblem(e.target.checked)}
            className="h-4 w-4 rounded border-border" />
          только проблемные
        </label>
        <span className="ml-auto text-xs text-muted-foreground">
          {d.from.slice(0, 7)} — {d.to.slice(0, 7)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Контрагентов" value={fmtN(d.totals.counterparties)} />
        <Kpi label="Ожиданий" value={fmtN(d.totals.expected)}
          sub={`${money(d.totals.gross)} ₽`} />
        <Kpi label="Документов получено" value={fmtN(d.totals.delivered)}
          sub={d.totals.expected
            ? `${Math.round(d.totals.delivered / d.totals.expected * 100)}% ожиданий` : undefined}
          tone={d.totals.delivered ? 'ok' : undefined} />
        <Kpi label="Не прислали в срок" value={fmtN(d.totals.missing)}
          tone={d.totals.missing ? 'bad' : undefined} />
      </div>

      {d.totals.noContact > 0 && (
        <Card className="border-amber-500/30"><CardContent className="flex items-start gap-2 pt-4 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <span>
            У <b>{d.totals.noContact}</b> контрагентов в карточке нет ни почты, ни телефона —
            требовать документы не с кого. Контакты заполняются в реестре контрагентов
            или прямо в условии договора.
          </span>
        </CardContent></Card>
      )}

      <Card><CardContent className="p-0">
        {/* Узкий экран: карточки. Десять колонок в телефон не влезают, а
            горизонтальная прокрутка прячет как раз контакты. */}
        <div className="divide-y divide-border sm:hidden">
          {rows.map((r) => (
            <div key={r.counterpartyId ?? r.name} className="space-y-1 p-3 text-sm">
              <div className="flex items-start justify-between gap-2">
                <span className="font-medium">{r.name}</span>
                <span className={`shrink-0 tabular-nums ${disciplineTone(r.onTimePct)}`}>
                  {r.onTimePct ?? '—'}%
                </span>
              </div>
              <div className="text-xs text-muted-foreground">
                {money(r.gross)} ₽ · ожиданий {r.expected} · не прислал {r.missing}
              </div>
              <Contacts row={r} />
            </div>
          ))}
        </div>

        <div className="hidden overflow-x-auto sm:block">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Контрагент</TableHead>
              <TableHead className="text-right">Сумма</TableHead>
              <TableHead className="text-right">Ожиданий</TableHead>
              <TableHead className="text-right">Вовремя</TableHead>
              <TableHead className="text-right">С опозданием</TableHead>
              <TableHead className="text-right">Не прислал</TableHead>
              <TableHead className="text-right">Дисциплина</TableHead>
              <TableHead>Контакты</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.counterpartyId ?? r.name}>
                  <TableCell className="max-w-[260px]">
                    <div className="truncate font-medium" title={r.name}>{r.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {r.objects > 0 && `объектов ${r.objects} · `}
                      периодов {r.periods}
                      {r.inn && ` · ИНН ${r.inn}`}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{money(r.gross)}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.expected}</TableCell>
                  <TableCell className="text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                    {r.onTime || '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-amber-600 dark:text-amber-400">
                    {r.late || '—'}
                    {r.avgLateDays !== null && (
                      <span className="ml-1 text-xs" title="среднее опоздание">
                        +{r.avgLateDays}д
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-red-600 dark:text-red-400">
                    {r.missing || '—'}
                  </TableCell>
                  <TableCell className={`text-right font-medium tabular-nums ${disciplineTone(r.onTimePct)}`}
                    title="доля ожиданий, закрытых документом в срок">
                    {r.onTimePct === null ? '—' : `${r.onTimePct}%`}
                  </TableCell>
                  <TableCell><Contacts row={r} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent></Card>

      <p className="text-xs text-muted-foreground">
        «Вовремя» — документ пришёл не позже срока из условия договора. Опоздание
        считается от этого срока, а не от даты документа: акт можно выписать первым
        числом, а прислать через два месяца.
      </p>
    </div>
  )
}

function Contacts({ row }: { row: OpsCounterpartyRow }) {
  if (!row.email && !row.phone) {
    return <span className="text-xs text-amber-600 dark:text-amber-400">контакта нет</span>
  }
  return (
    <div className="space-y-0.5 text-xs">
      {row.email && (
        <a href={`mailto:${row.email}`} className="flex items-center gap-1 hover:underline">
          <Mail className="h-3 w-3 shrink-0" />
          <span className="truncate">{row.email}</span>
        </a>
      )}
      {row.phone && (
        <a href={`tel:${row.phone}`} className="flex items-center gap-1 hover:underline">
          <Phone className="h-3 w-3 shrink-0" />{row.phone}
        </a>
      )}
      {row.director && (
        <div className="truncate text-muted-foreground" title={row.director}>{row.director}</div>
      )}
    </div>
  )
}
