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
import { useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Loader2, ArrowLeft, MapPin, User as UserIcon, CalendarClock } from 'lucide-react'
import {
  getSite, patchSite, STAGE_META, PHASE_META, FUNNEL_STAGES, type SiteDetail,
} from '@/services/sitesService'
import { toast } from 'sonner'
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
  // Вкладка тоже живёт в URL: по ссылке «открыть присоединение» человек попадает
  // на нужную вкладку, а правая панель «Инфо» знает, какой экран сейчас открыт.
  const tab = (params.get('ptab') as ProjectTabKey | null) ?? 'roadmap'
  const setTab = (k: ProjectTabKey) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('ptab', k)
      return next
    }, { replace: true })
  }

  if (!projectId) return <ProjectsListPanel companyId={companyId} />
  return <ProjectWorkspace companyId={companyId} id={projectId} tab={tab} onTab={setTab}
    onBack={() => setProject(null)} />
}

/* ── Рабочий экран проекта ──────────────────────────────────────────────── */

function ProjectWorkspace({ companyId, id, tab, onTab, onBack }: {
  companyId: string; id: string; tab: ProjectTabKey
  onTab: (k: ProjectTabKey) => void; onBack: () => void
}) {
  const qc = useQueryClient()
  // staleTime: 0 — шапка обязана быть свежей. Стадию проекта меняют и с соседних
  // экранов (маршрут, «Разобрать», реестр), а общий кэш держит ответ пять минут:
  // отклонённый проект показывал в шапке «Лид» и «Подбор», пока история на той же
  // странице уже писала «Лид → Архив» (замечание отдела развития 07.08.2026).
  const q = useQuery({
    queryKey: ['site-detail', companyId, id], queryFn: () => getSite(companyId, id),
    staleTime: 0, refetchOnMount: 'always',
  })
  const s = q.data

  const refresh = async () => {
    // `site-roadmap` — вкладка «Схема»: без неё схема маршрута обновится, а
    // прогресс и гейты рядом с ней останутся из кэша.
    for (const key of [['site-detail', companyId, id], ['sites-list', companyId],
                       ['sites-overview', companyId], ['site-events', companyId, id],
                       ['site-project', companyId, id], ['site-docs', companyId, id],
                       ['site-roadmap', companyId, id],
                       ['pr-portfolio', companyId], ['pr-overview', companyId],
                       ['pr-projects', companyId], ['pr-tc', companyId], ['pr-equipment', companyId]]) {
      await qc.invalidateQueries({ queryKey: key })
    }
  }

  const late = useMemo(
    () => !!s?.nextActionDue && s.nextActionDue < today() && s.stage !== 'archive',
    [s],
  )

  // Вкладки с незакрытыми пунктами гейта: пункт-документ ждёт «Документы»,
  // пункт-поставка — «Оборудование», ручной и графовый — «Работу» и «Паспорт».
  const pending = useMemo(() => {
    const set = new Set<ProjectTabKey>()
    for (const i of s?.gate?.items ?? []) {
      if (i.done) continue
      if (i.doc) set.add('docs')
      else if (i.equipment) set.add('equipment')
      else if (i.manual) set.add('work')
      else set.add('passport')
    }
    return set
  }, [s])

  if (q.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  // Запрос отказал — так и говорим. Раньше здесь стояло `isLoading || !s`, и любая
  // ошибка (не тот ключ в ссылке, нет прав, оборвалась сеть) оставляла крутящийся
  // значок навсегда: человек ждал минутами карточку, которая уже не придёт.
  if (q.isError || !s) {
    return (
      <div className="p-4">
        <Card><CardContent className="py-10 text-center text-sm space-y-3">
          <div>Карточка проекта не загрузилась: {q.error instanceof Error ? q.error.message : 'проект не найден'}</div>
          <div className="flex justify-center gap-2">
            <Button size="sm" variant="outline" onClick={() => q.refetch()}>Повторить</Button>
            <Button size="sm" variant="ghost" onClick={onBack}>К списку</Button>
          </div>
        </CardContent></Card>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      {/* Шапка проекта: всё, что нужно знать до открытия вкладок */}
      <div className="flex flex-wrap items-start gap-3">
        <Button variant="ghost" size="sm" className="h-8 px-2 text-sm" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5 mr-1" />К списку
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-muted-foreground">{s.projectNo ?? '—'}</span>
            <h2 className="text-base font-semibold truncate">
              {s.title || s.fullAddress || s.address || [s.region, s.city].filter(Boolean).join(', ') || 'Проект'}
            </h2>
            <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[s.stage]?.cls ?? ''}`}
              title={STAGE_META[s.stage]?.hint}>{s.stageLabel}</span>
            {s.phase && (
              <span className={`text-xs rounded border px-1.5 py-0.5 ${PHASE_META[s.phase]?.cls ?? ''}`}>
                {s.phaseLabel ?? PHASE_META[s.phase]?.label}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground mt-0.5">
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
      <ProjectPhaseStrip current={s.phase ?? undefined} kind={s.kind}
        note={s.kind && s.kind !== 'new_build'
          ? 'Работа на действующем объекте: место известно, подбор площадки не нужен.'
          : 'Подбор места — первый этап этого же проекта, дальше земля, реализация и ввод.'} />

      <NextStepBar site={s} onGoTab={onTab} onPlanStep={async (label) => {
        // Пишем сразу, а не «переносим на вкладку и ждём»: смысл кнопки в том,
        // чтобы шаг оказался в плане одним нажатием. Срок ставит человек — дата
        // без обсуждения была бы выдумкой системы.
        try {
          await patchSite(companyId, id, { next_action: label })
          toast.success('Шаг записан в план — поставьте срок на вкладке «Работа»')
          await refresh(); onTab('work')
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Не удалось записать шаг')
        }
      }} />

      {/* Вкладки. Точка отмечает те, где на этой стадии есть незакрытая работа:
          девять одинаковых кнопок не подсказывают, с какой начинать.

          На телефоне они переносились в три строки и съедали треть первого экрана —
          до содержимого приходилось листать. Поэтому узкий экран прокручивает их в
          одну строку вбок, а широкий по-прежнему показывает все сразу. */}
      <div data-zone="Разделы проекта: точка = есть незакрытое"
        className="-mx-4 px-4 overflow-x-auto sm:mx-0 sm:px-0 sm:overflow-visible">
        <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 sm:flex-wrap">
          {PROJECT_TABS.map((t) => (
            <button key={t.k} type="button" onClick={() => onTab(t.k)}
              title={pending.has(t.k) ? 'Здесь есть незакрытые пункты текущей стадии' : undefined}
              className={`inline-flex shrink-0 items-center gap-1.5 px-3 py-2 sm:py-1.5 text-sm rounded-[5px] transition-colors ${tab === t.k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
              {t.label}
              {pending.has(t.k) && (
                <span className={`h-1.5 w-1.5 rounded-full ${tab === t.k ? 'bg-primary-foreground/80' : 'bg-amber-500'}`} />
              )}
            </button>
          ))}
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <ProjectTabContent tab={tab} site={s} companyId={companyId} onDone={refresh} />
        </CardContent>
      </Card>
    </div>
  )
}

/* ── «Что сейчас и что дальше» ──────────────────────────────────────────── */

// Куда идти закрывать пункт: гейт называет задачу, но не место, где её закрывают.
// Человек читал «держит: Акт о техприсоединении» и искал, куда его положить.
const GATE_TAB: Record<string, ProjectTabKey> = {
  doc: 'docs', equipment: 'equipment', manual: 'work',
}

/**
 * Строка-навигатор: стадия, что осталось закрыть и куда за этим идти.
 *
 * Полоса этапов отвечает «где я», а этот блок — «что делать сейчас». Без него
 * человек на девятой стадии из одиннадцати видел набор вкладок и не понимал,
 * с какой начинать: чек-лист лежал на вкладке «Работа», а держащий пункт
 * закрывался на «Документах».
 */
function NextStepBar({ site, onGoTab, onPlanStep }: {
  site: SiteDetail; onGoTab: (k: ProjectTabKey) => void
  /** Положить шаг регламента в план работы (поле «Следующий шаг» вкладки «Работа»). */
  onPlanStep?: (label: string) => void
}) {
  const gate = site.gate
  if (!gate) return null
  const nextStage = FUNNEL_STAGES[FUNNEL_STAGES.indexOf(site.stage as never) + 1]
  const nextLabel = nextStage ? STAGE_META[nextStage]?.label : null
  const open = (gate.items ?? []).filter((i) => !i.done)
  const blocking = open.filter((i) => i.required)
  const lead = blocking[0] ?? open[0]
  const leadTab = lead ? GATE_TAB[lead.doc ? 'doc' : lead.equipment ? 'equipment' : lead.manual ? 'manual' : 'field'] : undefined

  return (
    <div data-zone="Что делать сейчас" className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">Сейчас: {site.stageLabel}</span>
        {gate.canAdvance ? (
          <span className="text-emerald-600 dark:text-emerald-400">
            всё обязательное закрыто{nextLabel ? ` — дальше «${nextLabel}»` : ''}
          </span>
        ) : (
          <span className="text-muted-foreground">
            осталось закрыть <span className="text-foreground">{blocking.length || open.length}</span> из {gate.total}
            {nextLabel ? `, дальше «${nextLabel}»` : ''}
          </span>
        )}
      </div>
      {lead && (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground">
          <span>Ближайший шаг: {lead.label}</span>
          <button type="button"
            onClick={() => onGoTab(leadTab ?? 'work')}
            className="rounded border border-border px-1.5 py-0.5 text-xs hover:border-primary/60 hover:text-foreground">
            {lead.doc ? 'Приложить документ'
              : lead.equipment ? 'Открыть оборудование'
              : lead.manual ? 'Отметить в чек-листе' : 'Заполнить в паспорте'}
          </button>
          {!lead.manual && !lead.doc && !lead.equipment && (
            <button type="button" onClick={() => onGoTab('passport')}
              className="rounded border border-border px-1.5 py-0.5 text-xs hover:border-primary/60 hover:text-foreground">
              Открыть паспорт
            </button>
          )}
          {/* Мост «регламент → план»: ближайший шаг известен, а в план он попадал
              только перепечаткой руками. Кнопка кладёт его в «Следующий шаг»
              карточки, откуда его берёт план работы по датам. */}
          {!site.nextAction && (
            <button type="button" onClick={() => onPlanStep?.(lead.label)}
              className="rounded border border-border px-1.5 py-0.5 text-xs hover:border-primary/60 hover:text-foreground">
              Запланировать
            </button>
          )}
        </div>
      )}
    </div>
  )
}

