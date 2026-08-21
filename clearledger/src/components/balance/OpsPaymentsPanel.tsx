/**
 * «Оплаты» — кассовый факт против ожиданий.
 *
 * «Хозяйство» знало только одну сторону: сколько ДОЛЖНО быть начислено по договорам.
 * Сколько ушло со счёта — не знало вовсе, и вопрос «мы платим больше или меньше
 * должного» оставался без ответа. Здесь рядом стоят обе цифры и их разница.
 *
 * Годы 2022–2024 показаны отдельно и без разницы: начислений за те периоды в
 * пространстве нет, и «минус всё» было бы не расхождением, а отсутствием данных.
 */
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { getOpsPayments, getOpsPaymentsCoverage } from '@/services/opsService'

const money = (v: number | null | undefined) =>
  !v ? '—' : fmtN(Math.round(v))

/** Месяц человеческим видом; год старой выгрузки — годом. */
function periodLabel(period: string, granularity: string): string {
  const [y, m] = period.split('-')
  if (granularity === 'year') return `${y} (год)`
  const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
  return `${months[Number(m) - 1] ?? m} ${y}`
}

const ITEM_LABELS: Record<string, string> = {
  rent: 'Аренда площадки', rent_other: 'Аренда прочего', energy: 'Электроэнергия',
  utilities: 'Коммунальные', maintenance: 'Обслуживание и ТО',
  contractors: 'Подрядчики', tech_connection: 'Техприсоединение',
  assets: 'Основные средства', penalty: 'Штрафы', deposit: 'Обеспечения',
  comms: 'Связь', cleaning: 'Уборка', other: 'Прочее',
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

  if (isLoading) {
    return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div>
  }
  const periods = data?.periods ?? []
  if (!periods.length) {
    return (
      <Card><CardContent className="py-8 text-sm text-muted-foreground">
        Кассовый факт не загружен. Выгрузка списаний принимается ручкой
        <code className="mx-1">POST /api/ops/payments/upload</code>.
      </CardContent></Card>
    )
  }

  // Статьи собираем по всем периодам: у месяца может не быть строки, которая была
  // в прошлом, и колонка не должна из-за этого пропадать.
  const items = Array.from(new Set(periods.flatMap((p) => Object.keys(p.items))))
    .sort((a, b) => (ITEM_LABELS[a] ?? a).localeCompare(ITEM_LABELS[b] ?? b))

  return (
    <div className="space-y-4">
      <Card><CardContent className="flex flex-wrap gap-6 py-4 text-sm">
        <div>
          <div className="text-muted-foreground">Заплачено всего</div>
          <div className="text-lg font-semibold">{money(data?.total_paid)} ₽</div>
        </div>
        <div>
          <div className="text-muted-foreground">Из них капитальные</div>
          <div className="text-lg font-semibold">{money(data?.total_capital)} ₽</div>
        </div>
        {coverage && (
          <div>
            <div className="text-muted-foreground">Объекты выгрузки</div>
            <div className="text-lg font-semibold">
              {coverage.numbers_linked} из {coverage.numbers_total}
            </div>
            <div className="text-xs text-muted-foreground">{coverage.hint}</div>
          </div>
        )}
      </CardContent></Card>

      <Card><CardContent className="overflow-x-auto p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 bg-background">Период</TableHead>
              <TableHead className="text-right">Заплачено</TableHead>
              <TableHead className="text-right">Начислено</TableHead>
              <TableHead className="text-right">Разница</TableHead>
              {items.map((code) => (
                <TableHead key={code} className="text-right whitespace-nowrap">
                  {ITEM_LABELS[code] ?? code}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {periods.map((p) => (
              <TableRow key={`${p.period}-${p.granularity}`}>
                <TableCell className="sticky left-0 bg-background whitespace-nowrap">
                  {periodLabel(p.period, p.granularity)}
                </TableCell>
                <TableCell className="text-right">{money(p.paid)}</TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {p.granularity === 'year' ? '—' : money(p.expected)}
                </TableCell>
                <TableCell className={`text-right ${
                  p.granularity === 'year' ? 'text-muted-foreground'
                    : p.diff > 0 ? 'text-amber-600' : p.diff < 0 ? 'text-emerald-600' : ''}`}>
                  {p.granularity === 'year' ? '—' : money(p.diff)}
                </TableCell>
                {items.map((code) => (
                  <TableCell key={code} className="text-right text-muted-foreground">
                    {money(p.items[code]?.paid)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>

      <p className="text-xs text-muted-foreground">
        Разница считается только по месяцам: у годовых строк старой выгрузки нет
        начислений в пространстве, и сравнивать их не с чем. Положительная разница —
        заплачено больше начисленного, отрицательная — меньше.
      </p>
    </div>
  )
}
