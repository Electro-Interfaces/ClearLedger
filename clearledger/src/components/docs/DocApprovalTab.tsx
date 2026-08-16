/**
 * Согласование документа: лист виз и запуск круга.
 *
 * Показываем не «идёт согласование», а поимённо: сколько решили из скольких и
 * кто молчит. Именно этого не хватает в гибридах трекера и документооборота —
 * при параллельных визах документ висит, и непонятно, на ком.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { CheckCircle2, CircleDashed, PlayCircle, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'
import { useAuth } from '@/contexts/AuthContext'

const ROW_STATUS: Record<string, { label: string; icon: typeof CheckCircle2 }> = {
  pending: { label: 'ждём', icon: CircleDashed },
  approved: { label: 'согласовано', icon: CheckCircle2 },
  rejected: { label: 'отказано', icon: XCircle },
  skipped: { label: 'снято', icon: CircleDashed },
}

export function DocApprovalTab({ doc, companyId, onChanged }: {
  doc: DocDetails
  companyId: string
  onChanged: () => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')

  const peopleQ = useQuery({
    queryKey: ['doc-people', companyId],
    queryFn: () => docsService.myApprovals(companyId),
    enabled: false,
  })
  void peopleQ

  const start = useMutation({
    mutationFn: () => docsService.startApproval(companyId, doc.id),
    onSuccess: (r) => { toast.success(`Круг ${r.round}: виз ${r.approvals}`); onChanged() },
    onError: (e) => toast.error((e as Error).message),
  })

  const decide = useMutation({
    mutationFn: (v: { id: string; approved: boolean }) =>
      docsService.decideApproval(companyId, v.id, v.approved, comment.trim() || undefined),
    onSuccess: (r) => {
      toast.success(r.returned ? 'Документ возвращён автору' : 'Виза поставлена')
      setComment('')
      qc.invalidateQueries({ queryKey: ['docs-my-approvals', companyId] })
      onChanged()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const state = doc.approval
  const live = state.rows.filter((r) => r.round === state.round)
  const mine = live.find((r) => r.status === 'pending' && r.assignee_id === user?.id)
  const past = state.rows.filter((r) => r.round !== state.round)

  return (
    <div className="space-y-3 pt-3">
      {state.status === 'none' && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">Согласование не запускалось</div>
            <div className="text-xs text-muted-foreground">
              Круг соберётся по маршруту вида документа. Роли и подразделения
              разворачиваются в конкретных людей в момент запуска.
            </div>
          </div>
          <Button size="sm" onClick={() => start.mutate()} disabled={start.isPending}>
            <PlayCircle className="mr-1.5 h-4 w-4" />Запустить
          </Button>
        </Card>
      )}

      {state.steps.map((s) => (
        <Card key={s.step_no} className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium">
              {s.step_no}. {s.name}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {s.mode === 'parallel' ? 'параллельно' : 'по очереди'}
                {s.quorum !== 'all' && `, кворум ${s.quorum}`}
              </span>
            </div>
            <span className={s.rejected
              ? 'rounded-md bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive'
              : 'rounded-md bg-muted px-1.5 py-0.5 text-xs'}>
              решили {s.decided} из {s.total}
            </span>
          </div>
          <div className="mt-2 space-y-1">
            {live.filter((r) => r.step_no === s.step_no).map((r) => {
              const meta = ROW_STATUS[r.status] ?? ROW_STATUS.pending
              const Icon = meta.icon
              return (
                <div key={r.id} className="flex items-start gap-2 text-[13px]">
                  <Icon className={r.status === 'approved'
                    ? 'mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600'
                    : r.status === 'rejected'
                      ? 'mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive'
                      : 'mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground'} />
                  <div className="min-w-0">
                    <span className={r.assignee_id === user?.id ? 'font-medium' : ''}>
                      {r.assignee_id === user?.id ? 'вы' : 'согласующий'}
                    </span>
                    <span className="text-muted-foreground"> · {meta.label}</span>
                    {r.due_at && r.status === 'pending' && (
                      <span className="text-muted-foreground">
                        {' '}· до {r.due_at.slice(0, 10)}
                      </span>
                    )}
                    {r.comment && <div className="text-muted-foreground">{r.comment}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      ))}

      {mine && (
        <Card className="space-y-2 p-4">
          <div className="text-sm font-medium">Ваша виза по шагу «{mine.step_name}»</div>
          <Input value={comment} onChange={(e) => setComment(e.target.value)}
            placeholder="Замечание (обязательно при отказе)" className="h-9" />
          <div className="flex gap-2">
            <Button size="sm" disabled={decide.isPending}
              onClick={() => decide.mutate({ id: mine.id, approved: true })}>
              Согласовать
            </Button>
            <Button size="sm" variant="outline" disabled={decide.isPending}
              onClick={() => decide.mutate({ id: mine.id, approved: false })}>
              Вернуть с замечанием
            </Button>
          </div>
        </Card>
      )}

      {state.status === 'rejected' && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="text-sm">
            Документ возвращён автору. Исправьте и запустите новый круг —
            прошлые визы останутся в истории.
          </div>
          <Button size="sm" variant="outline" onClick={() => start.mutate()}
            disabled={start.isPending}>
            Запустить круг {state.round + 1}
          </Button>
        </Card>
      )}

      {past.length > 0 && (
        <Card className="p-4">
          <div className="text-xs font-medium text-muted-foreground">Прошлые круги</div>
          <div className="mt-1.5 space-y-1">
            {past.map((r) => (
              <div key={r.id} className="text-[13px] text-muted-foreground">
                круг {r.round} · {r.step_name} · {ROW_STATUS[r.status]?.label ?? r.status}
                {r.comment ? ` · ${r.comment}` : ''}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

export default DocApprovalTab
