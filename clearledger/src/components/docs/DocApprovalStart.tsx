import { useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { QueryError } from '@/components/common/QueryError'
import { Button } from '@/components/ui/button'
import * as docsService from '@/services/docsService'

export function DocApprovalStart({ companyId, id, trigger, onStarted }: {
  companyId: string; id: string; trigger: ReactNode; onStarted: () => void
}) {
  const [open, setOpen] = useState(false)
  const preview = useQuery({
    queryKey: ['doc-approval-preview', companyId, id],
    queryFn: () => docsService.previewApproval(companyId, id),
    enabled: open, staleTime: 0,
  })
  const start = useMutation({
    mutationFn: () => docsService.startApproval(companyId, id, undefined, preview.data),
    onSuccess: (result) => { toast.success(`Круг ${result.round} запущен`); onStarted() },
  })
  return <ConfirmActionDialog trigger={trigger} title="Маршрут согласования"
    description="Проверьте участников. При запуске текущие реквизиты и файлы войдут в зафиксированный пакет."
    onOpenChange={(value) => { setOpen(value); if (value) start.reset() }}
    confirmLabel="Запустить согласование" pending={start.isPending}
    confirmDisabled={!preview.data || preview.isFetching || preview.isError || !!preview.data.problems.length || start.isError}
    onConfirm={() => start.mutateAsync()}
    content={<div className="max-h-[50dvh] space-y-3 overflow-y-auto">
      {preview.isFetching && <p role="status" className="text-sm text-muted-foreground">Проверяем маршрут…</p>}
      {preview.isError && <QueryError message="Маршрут не загрузился" error={preview.error} onRetry={() => void preview.refetch()} />}
      {preview.data?.steps.map((step) => <div key={step.number} className="space-y-1 border-b pb-3 text-sm">
        <p className="font-medium">{step.number}. {step.name}{step.step_kind === 'sign' ? ' · подписание' : ''}</p>
        <p>{step.people.map((person) => person.name).join(', ') || 'Участники не назначены'}</p>
        <p className="text-xs text-muted-foreground">
          {step.mode === 'parallel' ? 'Параллельно' : 'По очереди'} · требуется {step.quorum === 'all' ? 'решение всех' : step.quorum === 'any' ? 'одно решение' : `решений: ${step.quorum}`}
          {step.sla_hours ? ` · срок ${step.sla_hours} ч с получения задания` : ' · срок не задан'}
        </p>
      </div>)}
      {!!preview.data?.problems.length && <ul role="alert" className="list-inside list-disc text-sm text-destructive">
        {preview.data.problems.map((problem) => <li key={problem}>{problem}</li>)}
      </ul>}
      {start.isError && <p role="alert" className="text-sm text-destructive">{start.error.message}</p>}
      <Button variant="outline" size="sm" disabled={preview.isFetching || start.isPending}
        onClick={async () => { await preview.refetch(); start.reset() }}>Обновить маршрут</Button>
    </div>} />
}
