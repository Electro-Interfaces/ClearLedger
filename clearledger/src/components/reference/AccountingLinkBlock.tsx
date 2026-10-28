/**
 * «Что знает бухгалтерия» — блок карточки сущности пространства.
 *
 * Та же механика, что в приложении «Бухгалтерия», но в карточке договора: человек,
 * открывший договор, должен видеть сопряжение здесь, а не искать его на другом экране.
 * Логика живёт в сервисе (`accountingSpaceService`) и на сервере — страница «Бухгалтерия»
 * и этот блок читают один ответ.
 *
 * Сопряжение и проверка разделены: «сопряжено» не значит «реквизиты сверены», а правка
 * карточки после сверки делает проверку устаревшей.
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import { getAccountingEntityLinks } from '@/services/accountingSpaceService'

export function AccountingLinkBlock({ entityType = 'contract', id }: {
  entityType?: string
  id: string
}) {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['acct-space-links', companyId, entityType, id],
    queryFn: () => getAccountingEntityLinks(companyId, entityType, id),
    enabled: !!companyId && !!id, staleTime: 60_000,
  })
  const items = q.data?.items ?? []
  return <div className="space-y-2 border-t border-border/50 pt-3">
    <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70">
      Что знает бухгалтерия
    </p>
    {q.isLoading && <p className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />Загружается сопряжение</p>}
    {q.isError && <p role="alert" className="text-xs text-muted-foreground">
      Не удалось получить сопряжение — это ошибка запроса, а не отсутствие сведений.</p>}
    {!q.isLoading && !q.isError && !items.length && <p className="text-xs text-muted-foreground">
      Строки бухгалтерской выгрузки на эту карточку не легли. Выгрузка охватывает свой
      период: отсутствие строки не означает, что договора нет в учёте.</p>}
    {items.map((l) => <div key={l.record_id} className="rounded-md border border-border/50 bg-muted/20 p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{l.status_label}</span>
        <span className={cn('rounded-full px-2 py-0.5',
          l.verification === 'differences' ? 'bg-destructive/10 text-destructive'
            : l.stale ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
              : 'bg-muted text-muted-foreground')}>{l.verification_label}</span>
      </div>
      <p className="mt-1.5">
        {l.source.counterparty || 'контрагент не указан'} · {l.source.contract || 'основание не указано'}
      </p>
      <p className="text-muted-foreground">
        {[l.source.file, l.source.sheet && 'лист ' + l.source.sheet,
          l.source.rows && 'строки ' + l.source.rows,
          l.source.period && 'период ' + l.source.period].filter(Boolean).join(' · ')}
      </p>
      <p className="text-muted-foreground">
        {l.checked_fields.length ? 'сверены поля: ' + l.checked_fields.join(', ') : 'реквизиты не сверялись'}
      </p>
      {!!l.differences.length && <ul className="mt-1 flex flex-col gap-0.5">
        {l.differences.map((d) => <li key={d.field} className="text-destructive">
          {d.label}: в бухгалтерии «{d.source}», здесь «{d.space || '—'}»
        </li>)}
      </ul>}
      {l.stale && <p className="mt-1 text-amber-700 dark:text-amber-400">
        Карточку правили после сверки — проверку нужно повторить.</p>}
    </div>)}
  </div>
}
