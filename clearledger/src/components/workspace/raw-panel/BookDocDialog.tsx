/**
 * Просмотрщик документа бухгалтерии: шапка, состав, оплата, проводки.
 *
 * Реестр отвечает «что есть», а следующий вопрос всегда «что внутри и чем
 * подтверждено» — до сих пор на него отвечала только сама 1С.
 *
 * Строки показываем ПО ФАКТУ полей: у видов документов состав разный (у реализации
 * номенклатура и количество, у платежа — статья и назначение), и жёсткий набор
 * колонок половине документов оставил бы пустые столбцы, а половине — потерял поля.
 */
import { useQuery } from '@tanstack/react-query'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { getDocCard, type DocCard, type DocLine } from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function ru(date?: string | null) {
  return date ? date.slice(0, 10).split('-').reverse().join('.') : '—'
}

/** Человеческие имена полей строки. Незнакомые показываем как есть — данные важнее словаря. */
const LINE_LABEL: Record<string, string> = {
  name: 'Номенклатура', item: 'Номенклатура', nomenclature: 'Номенклатура',
  qty: 'Кол-во', quantity: 'Кол-во', price: 'Цена', amount: 'Сумма',
  amount_raw: 'Сумма без НДС', vat: 'НДС', vat_rate: 'Ставка', vat_included: 'НДС в сумме',
  kind: 'Тип', unit: 'Ед.', account: 'Счёт', content: 'Содержание',
  article: 'Статья', warehouse: 'Склад', code: 'Код',
}

const NUMERIC = new Set(['qty', 'quantity', 'price', 'amount', 'amount_raw', 'vat'])

function lineValue(key: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (typeof v === 'number') return NUMERIC.has(key) ? money.format(v) : String(v)
  return String(v)
}

function Field({ label, value, wide }: { label: string; value: React.ReactNode; wide?: boolean }) {
  if (value === null || value === undefined || value === '' || value === '—') return null
  return (
    <div className={cn('space-y-0.5', wide && 'col-span-2')}>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm break-words">{value}</div>
    </div>
  )
}

function Section({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h4 className="text-sm font-medium">{title}</h4>
        {note && <span className="text-[11px] text-muted-foreground">{note}</span>}
      </div>
      {children}
    </div>
  )
}

export function BookDocDialog({ companyId, docId, onClose }: {
  companyId: string; docId: string | null; onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['books', 'doc', companyId, docId],
    queryFn: () => getDocCard(companyId, docId!),
    enabled: !!docId,
  })

  return (
    <Dialog open={!!docId} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {q.data ? `${q.data.label} № ${q.data.number || 'б/н'} от ${ru(q.data.date)}` : 'Документ'}
          </DialogTitle>
        </DialogHeader>
        {q.isError ? <QueryError message="Не удалось загрузить документ" onRetry={() => q.refetch()} />
          : !q.data ? <div className="py-8 text-center text-sm text-muted-foreground">Загрузка…</div>
          : <DocBody d={q.data} />}
      </DialogContent>
    </Dialog>
  )
}

function DocBody({ d }: { d: DocCard }) {
  // Колонки состава — объединение ключей всех строк: у видов документов они разные.
  const keys: string[] = []
  for (const line of d.lines as DocLine[]) {
    for (const k of Object.keys(line)) if (!keys.includes(k)) keys.push(k)
  }
  const isInvoice = d.type === 'invoice_out'
  const debt = d.amount - d.paid

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <Field label="Контрагент" value={d.counterparty} wide />
        <Field label="ИНН" value={d.inn} />
        <Field label="Сумма" value={`${money.format(d.amount)} ₽`} />
        <Field label="в т.ч. НДС" value={d.vat ? `${money.format(d.vat)} ₽` : null} />
        <Field label="Статус" value={
          <span className={cn(d.status !== 'Проведён' && 'text-amber-600')}>{d.status}</span>
        } />
        <Field label="Период" value={d.periodStatus === 'closed' ? 'закрыт 🔒' : 'открыт'} />
        <Field label="Договор" value={d.contract ? `№ ${d.contract.number} от ${ru(d.contract.date)}` : null} wide />
        <Field label="Назначение" value={d.operation} wide />
        <Field label="Склад" value={d.warehouse} />
        <Field label="Организация" value={d.organization} wide />
      </div>

      {isInvoice && (
        <div className="rounded-lg border border-border px-3 py-2 text-sm">
          {d.paid > 0
            ? <>Оплачено <span className="font-medium">{money.format(d.paid)} ₽</span>
              {debt > 0.004 && <> · осталось {money.format(debt)} ₽</>}
              {debt <= 0.004 && <> · закрыт полностью</>}</>
            : <span className="text-muted-foreground">Оплаты по этому счёту в регистре нет</span>}
        </div>
      )}

      {d.lines.length > 0 ? (
        <Section title="Состав" note={`строк: ${d.lines.length}`}>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-2 text-left font-normal">№</th>
                  {keys.map((k) => (
                    <th key={k} className={cn('px-3 py-2 font-normal',
                      NUMERIC.has(k) ? 'text-right' : 'text-left')}>{LINE_LABEL[k] ?? k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(d.lines as DocLine[]).map((line, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{i + 1}</td>
                    {keys.map((k) => (
                      <td key={k} className={cn('px-3 py-1.5',
                        NUMERIC.has(k) ? 'text-right tabular-nums' : 'max-w-[280px] truncate')}
                        title={String(line[k] ?? '')}>
                        {lineValue(k, line[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ) : (
        <Section title="Состав">
          <p className="text-sm text-muted-foreground">
            Приехала только шапка: строки выгружены не у всех видов документов.
          </p>
        </Section>
      )}

      {d.payments.length > 0 && (
        <Section title="Оплата" note="из регистра «Оплата счетов»">
          <div className="space-y-1.5">
            {d.payments.map((p, i) => (
              <div key={i} className="flex items-baseline justify-between gap-3 rounded-lg border border-border px-3 py-1.5 text-sm">
                <span className="truncate" title={p.title ?? ''}>{p.title || 'Платёж'}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{ru(p.date)}</span>
                <span className="shrink-0 tabular-nums font-medium">{money.format(p.amount)} ₽</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {d.entries.length > 0 && (
        <Section title="Проводки" note={`${d.entries.length} — то, чем документ отразился в учёте`}>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr className="border-b">
                  <th className="px-3 py-2 text-left font-normal">Дата</th>
                  <th className="px-3 py-2 text-left font-normal">Дт</th>
                  <th className="px-3 py-2 text-left font-normal">Кт</th>
                  <th className="px-3 py-2 text-right font-normal">Сумма</th>
                  <th className="px-3 py-2 text-left font-normal">Содержание</th>
                </tr>
              </thead>
              <tbody>
                {d.entries.map((e, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{ru(e.date)}</td>
                    <td className="px-3 py-1.5 tabular-nums">{e.accountDt || '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums">{e.accountKt || '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.amount)}</td>
                    <td className="px-3 py-1.5 max-w-[320px] truncate text-muted-foreground"
                      title={e.content ?? ''}>{e.content || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <div className="text-[11px] text-muted-foreground">
        Идентификатор в 1С: <span className="font-mono">{d.externalId}</span>
      </div>
    </div>
  )
}
