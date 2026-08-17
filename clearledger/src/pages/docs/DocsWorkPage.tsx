/**
 * Раздел «На мне»: всё, что ждёт лично меня.
 *
 * Визы, поручения и мои документы лежат рядом намеренно. Делить личное по тому,
 * какой движок за ним стоит, бессмысленно: человек приходит с вопросом «что на
 * мне», а не «что у меня в документах и отдельно в поручениях».
 */
import { lazy, Suspense, useState, type ReactNode } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { RotateCw, Stamp } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import * as docsService from '@/services/docsService'
import { DOC_STATUS } from '@/services/docsService'
import { DocCardPanel } from '@/components/docs/DocCardPanel'
import { useDocsView } from './DocsLayout'

const TasksWorkPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((module) => ({ default: module.TasksWorkPage })))
const MINE_PAGE_SIZE = 200

export function DocsWorkPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const view = useDocsView('/docs/work')
  const companyId = company?.id ?? ''
  const openId = params.get('doc')
  const [now] = useState(Date.now)

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
  const docsQ = useInfiniteQuery({
    queryKey: ['docs-mine', companyId],
    queryFn: ({ pageParam }) => docsService.listDocs(companyId, {
      mine: true,
      limit: MINE_PAGE_SIZE,
      offset: pageParam,
    }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => (
      lastPage.docs.length < MINE_PAGE_SIZE ? undefined : pages.length * MINE_PAGE_SIZE
    ),
    enabled: !!companyId && view === 'mine',
  })

  const open = (id: string) => setParams((current) => {
    const next = new URLSearchParams(current)
    next.set('doc', id)
    return next
  }, { replace: true })
  const close = () => setParams((current) => {
    const next = new URLSearchParams(current)
    next.delete('doc')
    return next
  }, { replace: true })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['docs-my-approvals', companyId] })
    qc.invalidateQueries({ queryKey: ['docs-my-acquaints', companyId] })
    qc.invalidateQueries({ queryKey: ['docs-mine', companyId] })
  }
  const withDocument = (content: ReactNode) => {
    if (!openId) return content
    return (
      <>
        <div className="h-full min-h-0 overflow-y-auto px-4 py-4 lg:hidden">
          <DocCardPanel id={openId} companyId={companyId} onBack={close} onChanged={refresh} />
        </div>
        <div className="hidden h-full min-h-0 gap-3 lg:grid lg:grid-cols-[minmax(280px,0.66fr)_minmax(520px,1.4fr)]">
          <div className="min-h-0 overflow-y-auto">{content}</div>
          <section aria-label="Открытый документ"
            className="my-4 mr-4 min-h-0 overflow-y-auto rounded-lg border border-border bg-background px-4">
            <DocCardPanel id={openId} companyId={companyId} onBack={close} onChanged={refresh} />
          </section>
        </div>
      </>
    )
  }

  if (!companyId) return null

  if (view === 'errands') {
    return (
      <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Загрузка…</div>}>
        <TasksWorkPage />
      </Suspense>
    )
  }

  if (view === 'acquaints') {
    const rows = acquaintsQ.data ?? []
    return withDocument(
      <QueuePage title="Ознакомиться"
        subtitle={acquaintsQ.isLoading ? 'Загрузка…' : `Документов: ${rows.length}`}>
        {acquaintsQ.isError && (
          <QueueError message={(acquaintsQ.error as Error).message} onRetry={() => acquaintsQ.refetch()} />
        )}
        {!acquaintsQ.isError && (
          <Card className="divide-y divide-border/60">
            {rows.map((item) => (
              <button key={item.id} type="button" onClick={() => open(item.doc_id)}
                aria-current={item.doc_id === openId ? 'true' : undefined}
                className={queueRow(item.doc_id === openId)}>
                <div className="min-w-0">
                  <div className="truncate text-sm">{item.doc_title}</div>
                  <div className="text-[13px] text-muted-foreground">
                    {item.doc_number ?? 'без номера'}
                  </div>
                </div>
                {item.due_at && <DueBadge value={item.due_at} now={now} />}
              </button>
            ))}
            {acquaintsQ.isSuccess && rows.length === 0 && (
              <Empty>Ознакомиться не с чем</Empty>
            )}
          </Card>
        )}
      </QueuePage>,
    )
  }

  if (view === 'mine') {
    const docs = docsQ.data?.pages.flatMap((page) => page.docs) ?? []
    return withDocument(
      <QueuePage title="Мои документы"
        subtitle={docsQ.isLoading ? 'Загрузка…' : `Показано: ${docs.length}`}>
        {docsQ.isError && (
          <QueueError message={(docsQ.error as Error).message} onRetry={() => docsQ.refetch()} />
        )}
        {!docsQ.isError && (
          <Card className="divide-y divide-border/60">
            {docs.map((doc) => (
              <button key={doc.id} type="button" onClick={() => open(doc.id)}
                aria-current={doc.id === openId ? 'true' : undefined}
                className={queueRow(doc.id === openId)}>
                <div className="min-w-0">
                  <div className="truncate text-sm">{doc.title}</div>
                  <div className="text-[13px] text-muted-foreground">
                    {doc.reg_number ?? 'без номера'} · {doc.kind_name}
                    {doc.organization_name ? ` · ${doc.organization_name}` : ''}
                    {doc.counterparty_name ? ` · ${doc.counterparty_name}` : ''}
                  </div>
                </div>
                <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs">
                  {DOC_STATUS[doc.status]?.label ?? doc.status}
                </span>
              </button>
            ))}
            {docsQ.hasNextPage && (
              <div className="p-3 text-center">
                <Button type="button" size="sm" variant="outline"
                  disabled={docsQ.isFetchingNextPage}
                  onClick={() => docsQ.fetchNextPage()}>
                  {docsQ.isFetchingNextPage ? 'Загрузка…' : 'Показать ещё'}
                </Button>
              </div>
            )}
            {docsQ.isSuccess && docs.length === 0 && <Empty>Документов пока нет</Empty>}
          </Card>
        )}
      </QueuePage>,
    )
  }

  const approvals = approvalsQ.data ?? []
  return withDocument(
    <QueuePage title="Ждут моей визы"
      subtitle={approvalsQ.isLoading ? 'Загрузка…' : `Документов: ${approvals.length}`}>
      {approvalsQ.isError && (
        <QueueError message={(approvalsQ.error as Error).message} onRetry={() => approvalsQ.refetch()} />
      )}
      {!approvalsQ.isError && (
        <Card className="divide-y divide-border/60">
          {approvals.map((approval) => (
            <button key={approval.id} type="button" onClick={() => open(approval.doc_id)}
              aria-current={approval.doc_id === openId ? 'true' : undefined}
              className={queueRow(approval.doc_id === openId)}>
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm">
                  <Stamp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{approval.doc_title}</span>
                </div>
                <div className="text-[13px] text-muted-foreground">
                  {approval.doc_number ? `${approval.doc_number} · ` : ''}шаг «{approval.step_name}»
                  {approval.mode === 'parallel' ? ' · параллельно' : ''}
                  {approval.acting_for ? ` · замещаете ${approval.acting_for}` : ''}
                </div>
              </div>
              {approval.due_at && <DueBadge value={approval.due_at} now={now} />}
            </button>
          ))}
          {approvalsQ.isSuccess && approvals.length === 0 && <Empty>Виз на вас нет</Empty>}
        </Card>
      )}
    </QueuePage>,
  )
}

function QueuePage({ title, subtitle, children }: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">{title}</h1>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </div>
      {children}
    </div>
  )
}

function QueueError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
      <div className="text-sm font-medium text-destructive">Очередь не загрузилась</div>
      <div className="mt-1 text-sm text-muted-foreground">{message}</div>
      <Button size="sm" variant="outline" className="mt-3" onClick={onRetry}>
        <RotateCw className="mr-1.5 h-3.5 w-3.5" />Повторить
      </Button>
    </div>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-8 text-center text-sm text-muted-foreground">{children}</div>
}

function queueRow(active: boolean) {
  return cn(
    'flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
    active && 'bg-primary/5',
  )
}

function DueBadge({ value, now }: { value: string; now: number }) {
  const date = new Date(value)
  const overdue = !Number.isNaN(date.getTime()) && date.getTime() < now
  return (
    <span className={cn(
      'shrink-0 rounded-md px-1.5 py-0.5 text-xs',
      overdue ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground',
    )} title={Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')}>
      {overdue ? 'просрочено' : 'до'} {value.slice(0, 10)}
    </span>
  )
}

export default DocsWorkPage
