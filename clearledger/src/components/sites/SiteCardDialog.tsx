/**
 * Быстрый просмотр проекта в диалоге.
 *
 * Полноценная работа идёт в разделе «Проект» на всю ширину: в модальном окне
 * восемь вкладок с таблицами и формами не помещаются. Отсюда — кнопка «Открыть
 * в разделе», которая переносит тот же проект в рабочий экран.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2, Maximize2 } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { getSite, STAGE_META } from '@/services/sitesService'
import { PROJECT_TABS, ProjectTabContent, type ProjectTabKey } from './ProjectTabs'

export function SiteCardDialog({ companyId, id, onClose }: {
  companyId: string; id: string; onClose: () => void
}) {
  const qc = useQueryClient()
  const [, setSearchParams] = useSearchParams()
  const [, setTab] = useWorkspaceSubView('pr_portfolio')
  const [tab, setLocalTab] = useState<ProjectTabKey>('work')
  const q = useQuery({ queryKey: ['site-detail', companyId, id], queryFn: () => getSite(companyId, id) })
  const s = q.data

  const refresh = async () => {
    for (const key of [['site-detail', companyId, id], ['sites-list', companyId],
                       ['sites-overview', companyId], ['site-events', companyId, id],
                       ['site-project', companyId, id], ['site-docs', companyId, id],
                       ['pr-portfolio', companyId], ['pr-overview', companyId],
                       ['pr-tc', companyId], ['pr-equipment', companyId]]) {
      await qc.invalidateQueries({ queryKey: key })
    }
  }

  /** Тот же проект, но на всю ширину — в разделе «Проект». */
  const openFull = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('project', id)
      next.set('sub', 'pr_project')
      return next
    }, { replace: true })
    setTab('pr_project')
    onClose()
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-3xl w-[94vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base pr-6 flex flex-wrap items-center gap-2">
            {s?.projectNo && <span className="font-mono text-xs text-muted-foreground">{s.projectNo}</span>}
            {s ? (s.title || s.fullAddress || [s.region, s.city].filter(Boolean).join(', ') || 'Проект') : 'Проект'}
            {s && (
              <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage]?.cls ?? ''}`}
                title={STAGE_META[s.stage]?.hint}>{s.stageLabel}</span>
            )}
            <Button variant="outline" size="sm" className="h-7 text-xs ml-auto mr-4" onClick={openFull}>
              <Maximize2 className="h-3.5 w-3.5 mr-1" />Открыть в разделе
            </Button>
          </DialogTitle>
        </DialogHeader>

        {q.isLoading || !s ? (
          <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <>
            <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 w-fit flex-wrap">
              {PROJECT_TABS.map((t) => (
                <button key={t.k} type="button" onClick={() => setLocalTab(t.k)}
                  className={`px-3 py-1 text-xs rounded-[5px] transition-colors ${tab === t.k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t.label}
                </button>
              ))}
            </div>
            <ProjectTabContent tab={tab} site={s} companyId={companyId} onDone={refresh} />
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
