/**
 * «Продажи» и «Услуги» компании без объектов — ОДИН экран с параметром.
 *
 * Разрезы своих чисел не заводят: и то и другое — те же документы бухгалтерии
 * (`accounting_docs`), только вопрос разный. Поэтому и форма ответа у `/books/sales`
 * и `/books/services` одна, и экран один: две копии разошлись бы в первую же правку,
 * а расхождение цифр между соседними витринами — причина, по которой такие дашборды
 * бросают.
 */
import { useQuery } from '@tanstack/react-query'

import { useCompany } from '@/contexts/CompanyContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { getSlice } from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU')
const qty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

const COPY = {
  sales: {
    title: 'Продажи',
    subtitle: 'Кому и что продаём — по документам реализации бухгалтерии',
    clients: 'Покупатели',
    items: 'Товары',
    itemsHint: 'по сумме отгрузок',
  },
  services: {
    title: 'Услуги',
    subtitle: 'Что оказываем и кому — по актам оказанных услуг',
    clients: 'Заказчики',
    items: 'Виды услуг',
    itemsHint: 'по сумме актов',
  },
} as const

export function SlicePage({ kind }: { kind: 'sales' | 'services' }) {
  const { companyId } = useCompany()
  const copy = COPY[kind]

  const q = useQuery({
    queryKey: ['books', kind, companyId],
    queryFn: () => getSlice(companyId, kind),
    enabled: !!companyId,
  })

  if (!companyId) {
    return <div className="p-6 text-sm text-muted-foreground">Не выбрана организация.</div>
  }
  if (q.isError) {
    return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) {
    return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  }

  const d = q.data
  const avg = d.docs ? d.total / d.docs : 0
  const maxMonth = Math.max(...d.months.map((m) => m.amount), 1)
  // Последние два года: полная история за 5 лет в столбик не читается.
  const months = d.months.slice(-24)

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-xl font-semibold">{copy.title}</h1>
        <p className="text-xs text-muted-foreground mt-0.5">{copy.subtitle}</p>
      </div>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Оборот с НДС" value={money.format(d.total) + ' ₽'}
          hint={`без НДС ${money.format(d.net)} ₽`} />
        <MetricTile label="Документов" value={num.format(d.docs)}
          hint={`средний ${money.format(avg)} ₽`} />
        <MetricTile label={copy.clients} value={num.format(d.clients)} />
        <MetricTile label="НДС" value={money.format(d.vat) + ' ₽'} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Помесячно (последние {months.length} мес.)
          </div>
          {/* Высота столбца — в пикселях: проценты внутри flex без своей высоты
              разворачиваются в ноль, и график становится пустой полосой. */}
          <div className="flex items-end gap-1 h-40 overflow-x-auto">
            {months.map((m) => (
              <div key={m.month} className="flex flex-col items-center gap-1 min-w-[26px] flex-1"
                title={`${m.month}: ${money.format(m.amount)} ₽, документов ${m.docs}`}>
                <div className="w-full rounded-t bg-primary/70"
                  style={{ height: `${Math.max(2, (m.amount / maxMonth) * 128)}px` }} />
                <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                  {m.month.slice(2)}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground border-b">
              {copy.clients} — топ по обороту
            </div>
            <table className="w-full text-sm">
              <tbody>
                {d.topClients.map((c) => (
                  <tr key={c.name} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 max-w-[260px] truncate" title={c.name}>{c.name}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.docs} док.
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                      {money.format(c.amount)} ₽
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground border-b">
              {copy.items} — {copy.itemsHint}
            </div>
            <table className="w-full text-sm">
              <tbody>
                {d.topItems.map((it) => (
                  <tr key={it.name} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 max-w-[260px] truncate" title={it.name}>{it.name}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {it.qty ? qty.format(it.qty) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                      {money.format(it.amount)} ₽
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export const TradePage = () => <SlicePage kind="sales" />
export const ServicesSlicePage = () => <SlicePage kind="services" />
