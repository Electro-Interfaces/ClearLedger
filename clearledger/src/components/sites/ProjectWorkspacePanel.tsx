/**
 * «Проект» — полноэкранная работа с одним проектом.
 *
 * Проект — не карточка справочника: восемь вкладок с таблицами ТП, оборудования,
 * документов и бюджета в модальном окне не помещаются, и работать в нём нельзя.
 * Поэтому у проекта свой экран во всю ширину.
 *
 * Текущий проект живёт в URL (`?project=<id>`): закладка и перезагрузка страницы
 * возвращают на то же место, а переход из любого реестра — это просто ссылка.
 * Пока проект не выбран, экран показывает поиск и последние тронутые проекты.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, ArrowLeft, MapPin, User as UserIcon, CalendarClock } from 'lucide-react'
import { getSite, STAGE_META, PHASE_META } from '@/services/sitesService'
import { PROJECT_TABS, ProjectTabContent, type ProjectTabKey } from './ProjectTabs'
import { ProjectPhaseStrip } from './ProjectPhaseStrip'
import { ProjectsListPanel } from './ProjectsListPanel'

const today = () => new Date().toISOString().slice(0, 10)

export function ProjectWorkspacePanel({ companyId }: { companyId: string }) {
  const [params, setParams] = useSearchParams()
  const projectId = params.get('project') ?? ''
  const setProject = (id: string | null) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      if (id) next.set('project', id)
      else next.delete('project')
      return next
    }, { replace: true })
  }

  // Пункт один: пока проект не выбран — полноценный реестр со всеми фильтрами,
  // выбран — рабочий экран. Отдельный «список» и отдельный «проект» в меню
  // выглядели двумя разными разделами, хотя это один и тот же объект.
  if (!projectId) return <ProjectsListPanel companyId={companyId} />
  return <ProjectWorkspace companyId={companyId} id={projectId} onBack={() => setProject(null)} />
}

/* ── Рабочий экран проекта ──────────────────────────────────────────────── */

function ProjectWorkspace({ companyId, id, onBack }: {
  companyId: string; id: string; onBack: () => void
}) {
  const qc = useQueryClient()
  const [tab, setTab] = useState<ProjectTabKey>('roadmap')
  const q = useQuery({ queryKey: ['site-detail', companyId, id], queryFn: () => getSite(companyId, id) })
  const s = q.data

  const refresh = async () => {
    for (const key of [['site-detail', companyId, id], ['sites-list', companyId],
                       ['sites-overview', companyId], ['site-events', companyId, id],
                       ['site-project', companyId, id], ['site-docs', companyId, id],
                       ['pr-portfolio', companyId], ['pr-overview', companyId],
                       ['pr-projects', companyId], ['pr-tc', companyId], ['pr-equipment', companyId]]) {
      await qc.invalidateQueries({ queryKey: key })
    }
  }

  const late = useMemo(
    () => !!s?.nextActionDue && s.nextActionDue < today() && s.stage !== 'archive',
    [s],
  )

  if (q.isLoading || !s) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="p-4 space-y-3">
      {/* Шапка проекта: всё, что нужно знать до открытия вкладок */}
      <div className="flex flex-wrap items-start gap-3">
        <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5 mr-1" />К списку
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{s.projectNo ?? '—'}</span>
            <h2 className="text-base font-semibold truncate">
              {s.title || s.fullAddress || s.address || [s.region, s.city].filter(Boolean).join(', ') || 'Проект'}
            </h2>
            <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage]?.cls ?? ''}`}
              title={STAGE_META[s.stage]?.hint}>{s.stageLabel}</span>
            {s.phase && (
              <span className={`text-[11px] rounded border px-1.5 py-0.5 ${PHASE_META[s.phase]?.cls ?? ''}`}>
                {s.phaseLabel ?? PHASE_META[s.phase]?.label}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground mt-0.5">
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3 w-3" />{[s.region, s.city, s.address].filter(Boolean).join(', ') || '—'}
            </span>
            <span className="inline-flex items-center gap-1">
              <UserIcon className="h-3 w-3" />{s.ownerName ?? 'ответственный не назначен'}
            </span>
            <span className={`inline-flex items-center gap-1 ${late ? 'text-red-600 dark:text-red-400' : ''}`}>
              <CalendarClock className="h-3 w-3" />
              {s.nextAction ? `${s.nextAction}${s.nextActionDue ? ` · до ${s.nextActionDue}` : ''}` : 'следующий шаг не задан'}
            </span>
            {s.gate && (
              <span className={s.gate.canAdvance ? 'text-emerald-600 dark:text-emerald-400' : ''}>
                гейт {s.gate.done}/{s.gate.total}
                {!s.gate.canAdvance && s.gate.blocking.length > 0 && ` · держит: ${s.gate.blocking[0]}`}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Где проект в жизненном цикле — видно на любой вкладке */}
      <ProjectPhaseStrip current={s.phase ?? undefined}
        note="Подбор площадки — первый этап этого же проекта, дальше земля, реализация и ввод." />

      {/* Вкладки — тот же набор, что в быстром просмотре */}
      <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 flex-wrap">
        {PROJECT_TABS.map((t) => (
          <button key={t.k} type="button" onClick={() => setTab(t.k)}
            className={`px-3 py-1.5 text-xs rounded-[5px] transition-colors ${tab === t.k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
            {t.label}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4">
          <ProjectTabContent tab={tab} site={s} companyId={companyId} onDone={refresh} />
        </CardContent>
      </Card>
    </div>
  )
}

