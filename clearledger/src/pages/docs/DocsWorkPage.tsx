/**
 * Раздел «На мне»: всё, что ждёт лично меня.
 *
 * Визы, поручения и мои документы лежат рядом намеренно. Делить личное по тому,
 * какой движок за ним стоит, бессмысленно: человек приходит с вопросом «что на
 * мне», а не «что у меня в документах и отдельно в поручениях».
 */
import { lazy, Suspense } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Stamp } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Card } from '@/components/ui/card'
import * as docsService from '@/services/docsService'
import { DOC_STATUS } from '@/services/docsService'
import { DocCardPanel } from '@/components/docs/DocCardPanel'
import { useDocsView } from './DocsLayout'

const TasksWorkPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((m) => ({ default: m.TasksWorkPage })))

export function DocsWorkPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs/work')
  const companyId = company?.id ?? ''
  const openId = params.get('doc')

  const acquaintsQ = useQuery({
    queryKey: ['docs-my-acquaints', companyId],
    queryFn: () => docsService.myAcquaints(companyId),
    enabled: !!companyId && view === 'acquaints',
  })
  const approvalsQ = useQuery({
    queryKey: ['docs-my-approvals', companyId],
    queryFn: () => docsService.myApprovals(companyId),
    enabled: !!companyId && view === 'approvals',
  })
  const docsQ = useQuery({
    queryKey: ['docs-mine', companyId],
    queryFn: () => docsService.listDocs(companyId, { limit: 200 }),
    enabled: !!companyId && view === 'mine',
  })

  const open = (id: string) => setParams((p) => {
    const n = new URLSearchParams(p); n.set('doc', id); return n
  }, { replace: true })
  const close = () => setParams((p) => {
    const n = new URLSearchParams(p); n.delete('doc'); return n
  }, { replace: true })

  if (!companyId) return null

  if (openId) {
    return (
      <div className="px-4 py-4">
        <DocCardPanel id={openId} companyId={companyId} onBack={close}
          onChanged={() => {
            qc.invalidateQueries({ queryKey: ['docs-my-approvals', companyId] })
            qc.invalidateQueries({ queryKey: ['docs-mine', companyId] })
          }} />
      </div>
    )
  }

  // Поручения ведёт тот же движок, что и раньше: экран переиспользуется целиком.
  if (view === 'errands') {
    return (
      <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Загрузка…</div>}>
        <TasksWorkPage />
      </Suspense>
    )
  }

  if (view === 'acquaints') {
    const rows = acquaintsQ.data ?? []
    return (
      <div className="space-y-3 px-4 py-4">
        <div>
          <h1 className="text-base font-semibold">Ознакомиться</h1>
          <p className="text-xs text-muted-foreground">
            {acquaintsQ.isLoading ? 'Загрузка…' : `Документов: ${rows.length}`}
          </p>
        </div>
        <Card className="divide-y divide-border/60">
          {rows.map((a) => (
            <button key={a.id} type="button" onClick={() => open(a.doc_id)}
              className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-accent/40">
              <div className="min-w-0">
                <div className="truncate text-sm">{a.doc_title}</div>
                <div className="text-[11px] text-muted-foreground">
                  {a.doc_number ?? 'без номера'}
                </div>
              </div>
              {a.due_at && (
                <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
                  до {a.due_at.slice(0, 10)}
                </span>
              )}
            </button>
          ))}
          {!acquaintsQ.isLoading && rows.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              Ознакомиться не с чем
            </div>
          )}
        </Card>
      </div>
    )
  }

  if (view === 'mine') {
    const docs = docsQ.data?.docs ?? []
    return (
      <div className="space-y-3 px-4 py-4">
        <div>
          <h1 className="text-base font-semibold">Мои документы</h1>
          <p className="text-xs text-muted-foreground">
            {docsQ.isLoading ? 'Загрузка…' : `Всего: ${docs.length}`}
          </p>
        </div>
        <Card className="divide-y divide-border/60">
          {docs.map((d) => (
            <button key={d.id} type="button" onClick={() => open(d.id)}
              className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-accent/40">
              <div className="min-w-0">
                <div className="truncate text-sm">{d.title}</div>
                <div className="text-[11px] text-muted-foreground">
                  {d.reg_number ?? 'без номера'} · {d.kind_name}
                  {d.counterparty_name ? ` · ${d.counterparty_name}` : ''}
                </div>
              </div>
              <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
                {DOC_STATUS[d.status]?.label ?? d.status}
              </span>
            </button>
          ))}
          {!docsQ.isLoading && docs.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              Документов пока нет
            </div>
          )}
        </Card>
      </div>
    )
  }

  const approvals = approvalsQ.data ?? []
  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Ждут моей визы</h1>
        <p className="text-xs text-muted-foreground">
          {approvalsQ.isLoading ? 'Загрузка…' : `Документов: ${approvals.length}`}
        </p>
      </div>
      <Card className="divide-y divide-border/60">
        {approvals.map((a) => (
          <button key={a.id} type="button" onClick={() => open(a.doc_id)}
            className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-accent/40">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm">
                <Stamp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate">{a.doc_title}</span>
              </div>
              <div className="text-[11px] text-muted-foreground">
                {a.doc_number ? `${a.doc_number} · ` : ''}шаг «{a.step_name}»
                {a.mode === 'parallel' ? ' · параллельно' : ''}
              </div>
            </div>
            {a.due_at && (
              <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
                до {a.due_at.slice(0, 10)}
              </span>
            )}
          </button>
        ))}
        {!approvalsQ.isLoading && approvals.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            Виз на вас нет
          </div>
        )}
      </Card>
    </div>
  )
}

export default DocsWorkPage
