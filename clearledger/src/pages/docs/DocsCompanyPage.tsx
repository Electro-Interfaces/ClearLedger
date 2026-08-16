/**
 * Раздел «Компания»: где стоит работа целиком.
 *
 * То же, что в «На мне», но по всем: доска документов отвечает на вопрос «где
 * застряло согласование и кого ждут», поручения — на вопрос «чем занята
 * компания», приём — на вопрос «что нам прислала головная».
 */
import { lazy, Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { Card } from '@/components/ui/card'
import * as docsService from '@/services/docsService'
import { DocsInboxPanel } from '@/components/docs/DocsInboxPanel'
import { useDocsView } from './DocsLayout'

const TasksCompanyPage = lazy(() => import('@/pages/tasks/TasksWorkPage')
  .then((m) => ({ default: m.TasksCompanyPage })))
const TasksBoardPage = lazy(() => import('@/pages/tasks/TasksBoardPage')
  .then((m) => ({ default: m.TasksBoardPage })))

function Loading() {
  return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
}

export function DocsCompanyPage() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const view = useDocsView('/docs/company')
  const companyId = company?.id ?? ''

  const boardQ = useQuery({
    queryKey: ['docs-board', companyId],
    queryFn: () => docsService.board(companyId),
    enabled: !!companyId && view === 'docs',
  })

  if (!companyId) return null

  if (view === 'errands') {
    return <Suspense fallback={<Loading />}><TasksCompanyPage /></Suspense>
  }
  if (view === 'board') {
    return <Suspense fallback={<Loading />}><TasksBoardPage /></Suspense>
  }
  if (view === 'inbox') {
    return <div className="px-4 py-4"><DocsInboxPanel /></div>
  }

  const columns = boardQ.data?.columns ?? []

  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Документы на доске</h1>
        <p className="text-xs text-muted-foreground">
          Колонка — шаг маршрута согласования. Пусто в колонке значит, что на этом
          шаге никто не стоит.
        </p>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2">
        {columns.map((c) => (
          <div key={c.key} className="w-72 shrink-0">
            <div className="flex items-center justify-between px-1 pb-1.5">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">
                {c.docs.length}
              </span>
            </div>
            <div className="space-y-2">
              {c.docs.map((d) => (
                <Card key={d.id} onClick={() => navigate(`/docs?view=all&doc=${d.id}`)}
                  className="cursor-pointer p-2.5 transition-colors hover:bg-accent/40">
                  <div className="text-[13px]">{d.title}</div>
                  <div className="pt-0.5 text-[11px] text-muted-foreground">
                    {d.reg_number ?? 'без номера'}
                    {d.waiting ? ` · ждут ${d.waiting}` : ''}
                    {d.due_at ? ` · до ${d.due_at.slice(0, 10)}` : ''}
                  </div>
                </Card>
              ))}
              {c.docs.length === 0 && (
                <div className="rounded-md border border-dashed border-border px-2 py-6 text-center text-xs text-muted-foreground">
                  пусто
                </div>
              )}
            </div>
          </div>
        ))}
        {!boardQ.isLoading && columns.length === 0 && (
          <div className="w-full py-10 text-center text-sm text-muted-foreground">
            Согласований пока нет. Маршрут задаётся у вида документа в «Настройке».
          </div>
        )}
      </div>
    </div>
  )
}

export default DocsCompanyPage
