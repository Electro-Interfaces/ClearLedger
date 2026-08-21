/**
 * «Оплаты» — кассовый факт против ожиданий.
 *
 * «Хозяйство» знало только одну сторону: сколько ДОЛЖНО быть начислено по договорам.
 * Сколько ушло со счёта — не знало вовсе, и вопрос «мы платим больше или меньше
 * должного» оставался без ответа. Здесь рядом стоят обе цифры и их разница.
 *
 * Три решения, за которыми стоит работа человека, а не вкус:
 *
 * 1. Выгрузку принимает сам экран. Ручка была, кнопки не было — и сотрудник,
 *    получивший от заказчика новый файл, не мог сделать ничего. Загрузка стоит там,
 *    где смотрят результат.
 * 2. Годы 2022–2024 отделены от месяцев 2026-го. Начислений за те годы в
 *    пространстве нет, разница по ним не считается, и стоять в одной таблице с
 *    месяцами они не должны: это разная достоверность.
 * 3. Разрез по контрагентам, а не по объектам. Бухгалтерский номер площадки с
 *    объектом сети пока не связан; контрагент — единственный честный ответ на
 *    вопрос «кому мы платим».
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { AlertTriangle, FileUp, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import {
  getOpsPayments, getOpsPaymentsCoverage, getOpsPaymentsParties, uploadOpsPayments,
  type OpsPaymentsPeriod, type OpsPaymentsUploadResult,
} from '@/services/opsService'

const money = (v: number | null | undefined) =>
  !v ? '—' : fmtN(Math.round(v))

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

function periodLabel(period: string, granularity: string): string {
  const [y, m] = period.split('-')
  return granularity === 'year' ? y : `${MONTHS[Number(m) - 1] ?? m} ${y}`
}

const ITEM_LABELS: Record<string, string> = {
  rent: 'Аренда площадки', rent_other: 'Аренда прочего', energy: 'Электроэнергия',
  utilities: 'Коммунальные', maintenance: 'Обслуживание и ТО',
  contractors: 'Подрядчики', tech_connection: 'Техприсоединение',
  assets: 'Основные средства', penalty: 'Штрафы', deposit: 'Обеспечения',
  comms: 'Связь', cleaning: 'Уборка', other: 'Прочее',
}
const itemLabel = (code: string) => ITEM_LABELS[code] ?? code

/** Приём выгрузки: кнопка стоит там же, где смотрят результат. */
function UploadBar({ companyId }: { companyId: string }) {
  const input = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const [result, setResult] = useState<OpsPaymentsUploadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (file: File) => uploadOpsPayments(companyId, file),
    onSuccess: (data) => {
      setResult(data)
      setError(null)
      qc.invalidateQueries({ queryKey: ['ops-payments'] })
      qc.invalidateQueries({ queryKey: ['ops-payments-parties'] })
      qc.invalidateQueries({ queryKey: ['ops-payments-coverage'] })
    },
    onError: (e: unknown) => {
      setResult(null)
      setError(e instanceof Error ? e.message : 'Выгрузку принять не удалось')
    },
  })

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="outline" disabled={mutation.isPending}
          onClick={() => input.current?.click()}>
          {mutation.isPending
            ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Разбираем выгрузку…</>
            : <><FileUp className="mr-2 h-4 w-4" />Загрузить выгрузку списаний</>}
        </Button>
        <span className="text-xs text-muted-foreground">
          Файл .xlsx казначейства. Повторная загрузка того же файла суммы не удвоит.
        </span>
        <input ref={input} type="file" accept=".xlsx" className="sr-only"
          aria-label="Файл выгрузки списаний"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) mutation.mutate(file)
            e.target.value = ''
          }} />
      </div>
      {result && (
        <p className="text-xs text-muted-foreground">
          Принято строк: <b className="text-foreground">{result.saved}</b>
          {' · '}контрагентов опознано: {result.counterparties_matched}
          {result.unknown_items.length > 0 && (
            <> · незнакомые статьи попали в «Прочее»:{' '}
              <span className="text-amber-600 dark:text-amber-500">
                {result.unknown_items.join(', ')}
              </span>
            </>
          )}
        </p>
      )}
      {error && (
        <p className="flex items-center gap-2 text-xs text-destructive">
          <AlertTriangle className="h-3.5 w-3.5" />{error}
        </p>
      )}
    </div>
  )
}

/** Таблица периодов. Месяцы знают разницу, годы — нет, и это видно. */
function PeriodTable({ rows, items, withDiff }: {
  rows: OpsPaymentsPeriod[]; items: string[]; withDiff: boolean
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="sticky left-0 bg-background">Период</TableHead>
          <TableHead className="text-right">Заплачено</TableHead>
          {withDiff && <TableHead className="text-right">Начислено</TableHead>}
          {withDiff && <TableHead className="text-right">Разница</TableHead>}
          {items.map((code) => (
            <TableHead key={code} className="whitespace-nowrap text-right">
              {itemLabel(code)}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((p) => (
          <TableRow key={`${p.period}-${p.granularity}`}>
            <TableCell className="sticky left-0 whitespace-nowrap bg-background font-medium">
              {periodLabel(p.period, p.granularity)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{money(p.paid)}</TableCell>
            {withDiff && (
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {money(p.expected)}
              </TableCell>
            )}
            {withDiff && (
              <TableCell className={`text-right tabular-nums ${
                p.diff > 0 ? 'text-amber-600 dark:text-amber-500'
                  : p.diff < 0 ? 'text-emerald-600 dark:text-emerald-500' : ''}`}>
                {p.diff > 0 ? '+' : ''}{money(p.diff)}
              </TableCell>
            )}
            {items.map((code) => (
              <TableCell key={code} className="text-right tabular-nums text-muted-foreground">
                {money(p.items[code]?.paid)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function OpsPaymentsPanel() {
  const { companyId } = useCompany()
  const { data, isLoading } = useQuery({
    queryKey: ['ops-payments', companyId],
    queryFn: () => getOpsPayments(companyId!),
    enabled: !!companyId,
  })
  const { data: coverage } = useQuery({
    queryKey: ['ops-payments-coverage', companyId],
    queryFn: () => getOpsPaymentsCoverage(companyId!),
    enabled: !!companyId,
  })
  const { data: parties } = useQuery({
    queryKey: ['ops-payments-parties', companyId],
    queryFn: () => getOpsPaymentsParties(companyId!, 15),
    enabled: !!companyId,
  })

  if (isLoading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }

  const periods = data?.periods ?? []
  const months = periods.filter((p) => p.granularity === 'month')
  const years = periods.filter((p) => p.granularity === 'year')
  const items = Array.from(new Set(months.flatMap((p) => Object.keys(p.items))))
    .sort((a, b) => itemLabel(a).localeCompare(itemLabel(b)))
  const yearItems = Array.from(new Set(years.flatMap((p) => Object.keys(p.items))))
    .sort((a, b) => itemLabel(a).localeCompare(itemLabel(b)))

  if (!periods.length) {
    return (
      <div className="space-y-4">
        {companyId && <UploadBar companyId={companyId} />}
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Кассовый факт не загружен. Пока его нет, «Хозяйство» показывает только
          ожидания по договорам — сколько должно быть начислено, но не сколько
          заплачено.
        </CardContent></Card>
      </div>
    )
  }

  const overpaid = months.filter((m) => m.diff > 0).length

  return (
    <div className="space-y-5">
      {companyId && <UploadBar companyId={companyId} />}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardContent className="py-4">
          <div className="text-xs text-muted-foreground">Заплачено всего</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{money(data?.total_paid)} ₽</div>
          {data?.source && (
            <div className="mt-1 text-xs text-muted-foreground">
              {data.source.file ?? 'выгрузка'} · {data.source.rows} строк
            </div>
          )}
        </CardContent></Card>
        <Card><CardContent className="py-4">
          <div className="text-xs text-muted-foreground">Из них капитальные</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{money(data?.total_capital)} ₽</div>
          <div className="mt-1 text-xs text-muted-foreground">инвестиции, не расход периода</div>
        </CardContent></Card>
        <Card><CardContent className="py-4">
          <div className="text-xs text-muted-foreground">Месяцев дороже ожидания</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">
            {overpaid} из {months.length}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">заплачено больше начисленного</div>
        </CardContent></Card>
        <Card><CardContent className="py-4">
          <div className="text-xs text-muted-foreground">Объекты выгрузки</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">
            {coverage ? `${coverage.numbers_linked} из ${coverage.numbers_total}` : '—'}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {coverage?.hint ?? 'связано с объектами сети'}
          </div>
        </CardContent></Card>
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold">Помесячно: факт против ожидания</h2>
          <p className="text-xs text-muted-foreground">
            Плюс — заплатили больше начисленного, минус — меньше
          </p>
        </div>
        <Card><CardContent className="overflow-x-auto p-0">
          <PeriodTable rows={months} items={items} withDiff />
        </CardContent></Card>
      </section>

      {years.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold">История по годам</h2>
            <p className="text-xs text-muted-foreground">
              Начислений за эти годы в пространстве нет — сравнивать не с чем
            </p>
          </div>
          <Card><CardContent className="overflow-x-auto p-0">
            <PeriodTable rows={years} items={yearItems} withDiff={false} />
          </CardContent></Card>
        </section>
      )}

      {parties?.rows?.length ? (
        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold">Кому платим больше всего</h2>
            <p className="text-xs text-muted-foreground">
              Пока номера площадок не связаны с объектами, контрагент — главный разрез
            </p>
          </div>
          <Card><CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Контрагент</TableHead>
                  <TableHead className="text-right">Заплачено</TableHead>
                  <TableHead className="text-right">Статей</TableHead>
                  <TableHead className="text-right">Объектов</TableHead>
                  <TableHead>Период</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {parties.rows.map((r) => (
                  <TableRow key={r.name}>
                    <TableCell className="font-medium">
                      {r.name}
                      {!r.known && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          нет в справочнике
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{money(r.paid)}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{r.items}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{r.objects}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {periodLabel(r.first_period, r.first_period.endsWith('-01-01') ? 'year' : 'month')}
                      {' — '}
                      {periodLabel(r.last_period, 'month')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent></Card>
        </section>
      ) : null}
    </div>
  )
}
