/**
 * «Магазин» → Склад → Возвраты.
 *
 * Возврат — два разных события под одним словом, и путать их нельзя:
 *
 *   - ОТ ПОКУПАТЕЛЯ. Товар вернулся на полку, деньги ушли из кассы. Он живёт
 *     чеком: касса пробивает возврат отдельным фискальным документом, и разбор
 *     идёт по нему — когда, что, на сколько. Отдельного документа станция не
 *     заводит.
 *   - ПОСТАВЩИКУ. Товар уехал со станции, и это документ: брак, пересорт,
 *     истёкший срок. Его заводят на АЗС, он двигает остаток и уходит в
 *     бухгалтерию отдельным пакетом.
 *
 * Поэтому экран не один список, а два: сверху деньги, отданные покупателям,
 * снизу товар, отданный поставщику. Свести их в одну таблицу значит сложить
 * выручку с отгрузкой.
 */
import { useQuery } from '@tanstack/react-query'
import { Undo2, QrCode } from 'lucide-react'
import { StationDocsBlock } from './StationDocsBlock'
import { getStoreCheques, type StoreCheque } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'

const nf = (n: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)

function время(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export function StoreReturnsPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const { company } = useCompany()

  // Возвраты покупателей берём из чеков: своего документа у них нет, и заводить
  // его значило бы переписывать то, что касса уже пробила фискально.
  const { data, isLoading } = useQuery({
    queryKey: ['store-returns-cheques', company.id, dateFrom, dateTo],
    queryFn: () => getStoreCheques({ dateFrom, dateTo, onlyReturns: true, limit: 5000 }),
  })

  const возвраты = data?.cheques ?? []
  const сумма = возвраты.reduce((s: number, c: StoreCheque) => s + Math.abs(c.total), 0)
  const позиций = возвраты.reduce((s: number, c: StoreCheque) => s + c.positions, 0)

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Возвраты</h3>
        <p className="text-xs text-muted-foreground">
          Возврат от покупателя — деньги из кассы и товар обратно на полку, он живёт чеком.
          Возврат поставщику — товар со станции по браку, пересорту или сроку, он живёт
          документом. Это разные события, поэтому и списка два.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Kpi label="Возвратов покупателям" value={nf(возвраты.length)}
             hint="чеков возврата за период" />
        <Kpi label="Отдано покупателям" value={fmtMoney(сумма)} />
        <Kpi label="Позиций вернулось" value={nf(позиций)} hint="штук по чекам возврата" />
      </div>

      <div className="rounded-lg border border-border/50">
        <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-3 py-2">
          <Undo2 className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">Возвраты покупателей</span>
          <span className="text-[11px] text-muted-foreground">по чекам кассы</span>
        </div>
        {isLoading ? (
          <div className="px-3 py-4 text-xs text-muted-foreground">Загрузка чеков возврата…</div>
        ) : возвраты.length === 0 ? (
          <div className="px-3 py-4 text-xs text-muted-foreground">
            За период покупатели ничего не возвращали. Пусто здесь — это хорошая новость,
            а не отсутствие данных: чеки за период дошли, возвратных среди них нет.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Время</th>
                  <th className="px-3 py-2 text-left font-medium">АЗС</th>
                  <th className="px-3 py-2 text-right font-medium">Смена</th>
                  <th className="px-3 py-2 text-right font-medium">Чек</th>
                  <th className="px-3 py-2 text-right font-medium">ФД</th>
                  <th className="px-3 py-2 text-left font-medium">Что вернули</th>
                  <th className="px-3 py-2 text-right font-medium">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {возвраты.map((c: StoreCheque) => (
                  <tr key={c.id} className="border-t border-border/30">
                    <td className="whitespace-nowrap px-3 py-1.5">{время(c.at)}</td>
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.station_id}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.shift_number}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{c.number}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.fiscal_number ?? '—'}
                    </td>
                    <td className="max-w-[320px] truncate px-3 py-1.5"
                        title={c.lines.map((l) => l.name).join(', ')}>
                      {c.lines.map((l) => l.name).join(', ') || '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-medium text-amber-300/90">
                      {fmtMoney(Math.abs(c.total))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <StationDocsBlock kind="return_purchase" dateFrom={dateFrom} dateTo={dateTo}
                        title="Возвраты поставщику" />

      {/* Маркированное: возврат кода — не то же, что возврат штуки. Пока агент
          только возит коды в пакете, а в оборот их вводит бухгалтерия; сказать
          об этом надо здесь, иначе экран выглядит полным, а обязанность
          остаётся невыполненной. */}
      <div className="flex items-start gap-3 rounded-lg border border-dashed border-border/50 p-4">
        <QrCode className="mt-0.5 h-4 w-4 text-muted-foreground" />
        <div className="text-xs text-muted-foreground">
          <span className="text-foreground">Маркированный товар.</span> Возврат такого товара —
          это не «плюс одна штука к остатку», а повторный ввод кода в оборот в «Честном знаке».
          Коды станция присылает в самом документе возврата (видно по клику на строку), но в
          оборот их пока вводят руками. Автоматическая подача в ГИС МТ — в разделе
          «Маркировка».
        </div>
      </div>
    </div>
  )
}
