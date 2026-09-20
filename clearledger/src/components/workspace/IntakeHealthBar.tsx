/**
 * Состояние выгрузки — полоса над данными эксплуатации.
 *
 * Экраны считают «по последним данным» и честно пишут дату, но человек читает
 * их как «сегодня». 18 сентября файл витрины пришёл, 19 и 20 — нет, и об этом
 * узнали только по странным цифрам (проверка 20.09.2026). Полоса появляется
 * ровно тогда, когда с выгрузкой что-то не так, и молчит, когда всё в порядке:
 * постоянная плашка «данные свежие» через неделю перестаёт читаться.
 *
 * Три беды, и каждая говорит своим языком:
 *
 * - **тишина** — файла нет дольше полутора суток;
 * - **пропавшие поля** — то, что раньше приходило, перестало (с августа из
 *   выгрузки ушли название станции, адрес и номер поста — 43 тыс. строк);
 * - **платежи без сессий** — деньги доехали, а сессия нет.
 */
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CircleSlash } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getIntakeHealth } from '@/services/opsService'

const nf = new Intl.NumberFormat('ru-RU')

const дата = (iso?: string | null) => iso
  ? iso.slice(0, 10).split('-').reverse().join('.')
  : '—'

export function IntakeHealthBar({ compact }: {
  /** В шапке экрана — одной строкой, без подробностей про поля и платежи. */
  compact?: boolean
}) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['intake-health', companyId],
    queryFn: () => getIntakeHealth(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const d = q.data
  if (!d || !d.everLoaded) return null

  const тишина = d.level !== 'ok'
  const поля = d.lostFields ?? []
  const сироты = d.payments?.orphans ?? 0
  if (!тишина && !поля.length && !сироты) return null

  const тревога = d.level === 'alarm'

  return (
    <div className={cn(
      'space-y-1 rounded-md border px-3 py-2 text-xs',
      тревога ? 'border-red-500/40 bg-red-500/5' : 'border-amber-500/30 bg-amber-500/5')}>
      {тишина && (
        <div className={cn('flex items-center gap-1.5 font-medium',
          тревога ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400')}>
          <AlertTriangle className="size-3.5 shrink-0" />
          Выгрузка не приходила {Math.round(d.hours ?? 0)} ч — последняя загрузка{' '}
          {дата(d.lastLoadAt)}, данные по {дата(d.dataThrough)}.
          {' '}Всё, что на экранах, посчитано по этому дню.
        </div>
      )}

      {!compact && поля.length > 0 && (
        <div className="flex items-start gap-1.5 text-muted-foreground">
          <CircleSlash className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Из выгрузки пропало: {поля.map((f) => f.label).join(', ')} — последний раз{' '}
            {дата(поля[0].lastSeen)}, без этих граф {nf.format(поля[0].rowsWithout)} сессий.
            {поля.some((f) => f.field === 'connector_no')
              && ' Без номера поста не собрать разбор по коннекторам.'}
          </span>
        </div>
      )}

      {!compact && сироты > 0 && (
        <div className="flex items-start gap-1.5 text-muted-foreground">
          <CircleSlash className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Платежей без своей сессии: {nf.format(сироты)} на{' '}
            {nf.format(Math.round(d.payments?.orphanAmount ?? 0))} ₽ — оплата пришла,
            а сессия в выгрузку не попала.
          </span>
        </div>
      )}
    </div>
  )
}
