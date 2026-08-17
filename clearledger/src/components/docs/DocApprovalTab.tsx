/**
 * Согласование документа: лист виз и запуск круга.
 *
 * Показываем не «идёт согласование», а поимённо: сколько решили из скольких и
 * кто молчит. Именно этого не хватает в гибридах трекера и документооборота —
 * при параллельных визах документ висит, и непонятно, на ком.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import {
  CheckCircle2, CircleDashed, Clock3, Copy, FileCheck2, PlayCircle, ShieldCheck,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import * as docsService from '@/services/docsService'
import type { DocDetails } from '@/services/docsService'
import { useAuth } from '@/contexts/AuthContext'

const ROW_STATUS: Record<string, { label: string; icon: typeof CheckCircle2 }> = {
  waiting: { label: 'этап ещё не начат', icon: Clock3 },
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
  const commentId = useId()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')

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
  const mine = live.find((r) => r.status === 'pending' && r.can_decide)
  const past = state.rows.filter((r) => r.round !== state.round)
  const canStart = doc.available_actions.includes('start_approval')

  const copyHash = async () => {
    try {
      await navigator.clipboard.writeText(state.snapshot_sha256 ?? '')
      toast.success('Хеш пакета скопирован')
    } catch {
      toast.error('Не удалось скопировать хеш')
    }
  }

  return (
    <div className="space-y-3 pt-3">
      {state.status === 'none' && canStart && (
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

      {state.snapshot && state.snapshot_sha256 && (
        <Card className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-2.5">
              <div className="rounded-md bg-primary/10 p-2 text-primary">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium">Пакет согласования зафиксирован</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Реквизиты и {state.snapshot.files.length} файл(а) · редакция{' '}
                  {state.snapshot.card.current_revision || 'без основного файла'}
                </div>
                <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
                  title={state.snapshot_sha256}>
                  SHA-256 {state.snapshot_sha256}
                </div>
              </div>
            </div>
            <Button size="sm" variant="ghost" onClick={copyHash}>
              <Copy className="mr-1.5 h-3.5 w-3.5" />Копировать хеш
            </Button>
          </div>
          {state.snapshot.files.length > 0 && (
            <div className="mt-3 divide-y divide-border/60 border-t border-border/60">
              {state.snapshot.files.map((file) => (
                <div key={file.id} className="flex items-center justify-between gap-3 py-2 text-xs">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <FileCheck2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{file.file_name}</span>
                    <span className="shrink-0 text-muted-foreground">ред. {file.revision}</span>
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground"
                    title={file.sha256}>{file.sha256.slice(0, 12)}…</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {state.steps.map((s) => (
        <Card key={s.step_no} className={s.active ? 'border-primary/40 p-4' : 'p-4'}>
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
              : s.passed
                ? 'rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-xs text-emerald-700 dark:text-emerald-300'
                : s.active
                  ? 'rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary'
                  : 'rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground'}>
              {s.rejected ? 'возвращён' : s.passed ? 'пройден' : s.active ? 'текущий шаг' : 'ещё не начат'}
              {' · '}{s.decided} из {s.total}
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
                    <span className={r.can_decide ? 'font-medium' : ''}>
                      {approvalPerson(r, user?.id)}
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
          <Label htmlFor={commentId} className="sr-only">Комментарий к визе</Label>
          <Input id={commentId} value={comment} onChange={(e) => setComment(e.target.value)}
            placeholder="Замечание (обязательно при отказе)" className="h-9"
            aria-describedby="approval-reject-hint" />
          <div id="approval-reject-hint" className="text-xs text-muted-foreground">
            Для согласования комментарий необязателен. Для возврата укажите, что исправить.
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={decide.isPending}
              onClick={() => decide.mutate({ id: mine.id, approved: true })}>
              Согласовать
            </Button>
            <Button size="sm" variant="outline" disabled={decide.isPending || !comment.trim()}
              onClick={() => decide.mutate({ id: mine.id, approved: false })}>
              Вернуть с замечанием
            </Button>
          </div>
        </Card>
      )}

      {state.status === 'rejected' && canStart && (
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
                круг {r.round} · {r.step_name} · {approvalPerson(r, user?.id)} ·{' '}
                {ROW_STATUS[r.status]?.label ?? r.status}
                {r.comment ? ` · ${r.comment}` : ''}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function approvalPerson(row: docsService.DocApprovalRow, currentUserId?: string): string {
  const assigned = row.assignee_name || 'Согласующий не найден'
  if (row.decided_by_name && row.decided_by_id !== row.assignee_id) {
    return `${row.decided_by_name} (замещает ${assigned})`
  }
  if (row.decided_by_name) return row.decided_by_name
  if (row.can_decide && row.assignee_id !== currentUserId) {
    return `Вы как заместитель (${assigned})`
  }
  if (row.assignee_id === currentUserId) return `Вы · ${assigned}`
  return assigned
}

export default DocApprovalTab
