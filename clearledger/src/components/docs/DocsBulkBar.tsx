import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Layers3, X } from 'lucide-react'
import { toast } from 'sonner'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'

type BulkAction = 'assign_responsible' | 'set_due' | 'assign_case' | 'add_label' | 'remove_label'

const ACTION_LABEL: Record<BulkAction, string> = {
  assign_responsible: 'Назначить ответственного', set_due: 'Установить срок',
  assign_case: 'Подшить в дело', add_label: 'Добавить метку', remove_label: 'Снять метку',
}

export function DocsBulkBar({ companyId, selectedIds, onDone, onClear }: {
  companyId: string
  selectedIds: string[]
  onDone: () => void
  onClear: () => void
}) {
  const [action, setAction] = useState<BulkAction>('assign_responsible')
  const [value, setValue] = useState('')
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId], queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const casesQ = useQuery({
    queryKey: ['doc-cases', companyId], queryFn: () => docsService.listCases(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const labelsQ = useQuery({
    queryKey: ['doc-labels', companyId], queryFn: () => docsService.listDocLabels(companyId),
    staleTime: 5 * 60 * 1000,
  })
  const relevantFailed = action === 'assign_responsible' ? peopleQ.isError
    : action === 'assign_case' ? casesQ.isError
      : action === 'add_label' || action === 'remove_label' ? labelsQ.isError : false
  const relevantLoading = action === 'assign_responsible' ? peopleQ.isLoading
    : action === 'assign_case' ? casesQ.isLoading
      : action === 'add_label' || action === 'remove_label' ? labelsQ.isLoading : false
  const run = useMutation({
    mutationFn: () => docsService.bulkDocs(companyId, {
      doc_ids: selectedIds, action,
      ...(action === 'assign_responsible' ? { responsible_id: value } : {}),
      ...(action === 'set_due' ? { due_at: new Date(`${value}T18:00:00`).toISOString() } : {}),
      ...(action === 'assign_case' ? { case_id: value } : {}),
      ...(action === 'add_label' || action === 'remove_label' ? { label_id: value } : {}),
    }),
    onSuccess: (result) => {
      toast.success(`Обновлено: ${result.updated}; без изменений: ${result.unchanged}`)
      onDone()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const options = action === 'assign_responsible' ? (peopleQ.data?.people ?? [])
    : action === 'assign_case' ? (casesQ.data ?? []).filter((item) => item.status === 'open')
      .map((item) => ({ id: item.id, name: `${item.year} · ${item.index} · ${item.title}` }))
      : action === 'add_label' || action === 'remove_label' ? (labelsQ.data?.labels ?? []) : []
  const ready = selectedIds.length > 0 && !!value && !relevantFailed && !relevantLoading

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 p-2" role="region" aria-label="Массовые действия">
      <span className="inline-flex items-center gap-1.5 text-sm font-medium">
        <Layers3 className="h-4 w-4" />Выбрано: {selectedIds.length}
      </span>
      <select value={action} onChange={(event) => { setAction(event.target.value as BulkAction); setValue('') }}
        aria-label="Массовое действие" className="h-9 rounded-md border border-input bg-background px-2 text-sm">
        {Object.entries(ACTION_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
      {action === 'set_due' ? (
        <Input type="date" value={value} onChange={(event) => setValue(event.target.value)}
          aria-label="Новый срок документов" className="h-9 w-44" />
      ) : (
        <select value={value} onChange={(event) => setValue(event.target.value)}
          aria-label="Значение массового действия" disabled={relevantLoading || relevantFailed}
          className="h-9 min-w-56 rounded-md border border-input bg-background px-2 text-sm">
          <option value="">{relevantLoading ? 'загрузка…' : 'выберите значение'}</option>
          {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select>
      )}
      {relevantFailed && (
        <span role="alert" className="text-xs text-destructive">Справочник не загрузился</span>
      )}
      <ConfirmActionDialog
        trigger={<Button type="button" size="sm" disabled={!ready || run.isPending}>Применить</Button>}
        title={`${ACTION_LABEL[action]} для ${selectedIds.length} документов?`}
        description="Пакет выполняется целиком: если хотя бы один документ недоступен или зафиксирован согласованием, изменения не применятся ни к одному."
        confirmLabel="Применить ко всем"
        pending={run.isPending}
        onConfirm={() => run.mutateAsync()}
      />
      <Button type="button" size="sm" variant="ghost" onClick={onClear} disabled={run.isPending}>
        <X className="mr-1 h-4 w-4" />Снять выбор
      </Button>
    </div>
  )
}
