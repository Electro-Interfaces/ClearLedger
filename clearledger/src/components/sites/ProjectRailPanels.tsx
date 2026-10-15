/**
 * Контекстные инструменты рельсы для «Проектов»: «Сейчас» и «Шаг».
 *
 * Рельса пространства одинакова на любом экране (встреча, чат, Трек), а менеджеру
 * нужна помощь в ТОМ месте, где он стоит: какой проект открыт, на каком этапе,
 * чего не хватает (просьба отдела развития 14.10.2026). Контекст берётся из
 * адреса: раздел `pr_project`, `project` и `ptab`. В реестре проект не открыт —
 * тогда «Сейчас» показывает мои проекты, где горит или нет шага, и выбранный
 * открывается здесь же, через контекст дока `site:<id>`.
 *
 * Своего API нет: «Шаг» — те же `setProjectNext` и `createTask`, что у вкладки
 * «Обзор», чтобы ближайший результат, план работы и обзор говорили одно.
 */
import { useMemo, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useSupportContext } from '@/contexts/SupportContext'
import { createTask } from '@/services/tasksService'
import { getProjects, getSite, getSiteMembers, STAGE_META, type ProjectRow } from '@/services/sitesService'
import * as work from '@/services/projectWorkspaceService'
import { todayKey } from '@/lib/personalDay'
import { useOpenProject } from './useOpenProject'

/** Где стоит человек: в «Проектах» ли он и какой проект открыт. */
export function useProjectRailContext(): { projectId: string | null; tab: string | null } | null {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const sub = params.get('sub')
  const inProjects = (pathname.startsWith('/projects') || params.get('mode') === 'projects')
    && (sub === 'pr_project' || sub === 'sites_list')
  if (!inProjects) return null
  return { projectId: params.get('project'), tab: params.get('ptab') }
}

/** Проект, о котором говорит панель: открытый в адресе или выбранный в рельсе. */
function useRailProject() {
  const ctx = useProjectRailContext()
  const { interactionContext } = useSupportContext()
  const picked = interactionContext?.startsWith('site:') ? interactionContext.slice(5) : null
  return { ctx, siteId: ctx?.projectId || picked }
}

const dayShift = (days: number) => todayKey(new Date(Date.now() + days * 86400_000))
const ru = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T12:00`).toLocaleDateString('ru') : '')

function useNearest(companyId: string, siteId: string) {
  const site = useQuery({ queryKey: ['site-detail', companyId, siteId], queryFn: () => getSite(companyId, siteId) })
  const overview = useQuery({ queryKey: ['project-workspace', companyId, siteId], queryFn: () => work.getProjectOverview(companyId, siteId) })
  const o = overview.data
  const s = site.data
  // Тот же порядок, что у шапки проекта и плана работы: работа → ожидание → ручной шаг.
  const label = o?.next_work?.title || o?.external_wait?.waiting_for || s?.nextAction || null
  const date = o?.next_work?.due_at?.slice(0, 10) || o?.external_wait?.follow_up || s?.nextActionDue || null
  const done = ['done', 'executed', 'cancelled', 'archived'].includes(o?.next_work?.status ?? '')
  return { site, overview, label, date: done ? null : date, done }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="space-y-1.5"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>{children}</section>
}

function Busy() {
  return <div className="flex justify-center py-10"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
}

/* ── «Сейчас» ─────────────────────────────────────────────────────────── */

export function ProjectNowPanel() {
  const { companyId } = useCompany()
  const { ctx, siteId } = useRailProject()
  if (!companyId) return null
  if (!ctx) return <p className="p-4 text-sm text-muted-foreground">Подсказка работает в разделе «Проекты»: откройте реестр или проект.</p>
  return <div className="h-full overflow-y-auto p-4">
    {siteId ? <ProjectNow companyId={companyId} siteId={siteId} fromRegistry={!ctx.projectId} />
      : <MyHotProjects companyId={companyId} />}
  </div>
}

function ProjectNow({ companyId, siteId, fromRegistry }: { companyId: string; siteId: string; fromRegistry: boolean }) {
  const { openInteraction } = useSupportContext()
  const openProject = useOpenProject()
  const { site, overview, label, date, done } = useNearest(companyId, siteId)
  if (site.isPending || overview.isPending) return <Busy />
  if (site.isError) return <p className="text-sm">Проект не загрузился: {site.error.message}</p>
  const s = site.data
  const meta = STAGE_META[s.stage]
  const late = !!date && date < todayKey()
  const blocking = s.gate?.blocking.map((key) => s.gate.items.find((i) => i.key === key)?.label ?? key) ?? []
  const unknown = s.decision?.unknown ?? []
  return <div className="space-y-5">
    {fromRegistry && <button className="text-sm text-primary underline-offset-4 hover:underline" onClick={() => openInteraction('now')}>← Мои проекты</button>}
    <div>
      <div className="font-mono text-xs text-muted-foreground">{s.projectNo}</div>
      <div className="font-medium">{s.title}</div>
      <div className="mt-1 text-sm"><span className="font-medium">{meta?.label ?? s.stageLabel}</span>
        {meta?.hint && <span className="text-muted-foreground"> — {meta.hint}</span>}</div>
    </div>

    <Section title="Ближайший результат">
      {label ? <p className="text-sm">{label}</p> : <p className="text-sm text-amber-700 dark:text-amber-300">Шаг не записан — проект выпадает из плана работы.</p>}
      {done && <p className="text-sm text-muted-foreground">Результат готов — определите следующий шаг.</p>}
      {date && <p className={late ? 'text-sm font-medium text-red-600 dark:text-red-400' : 'text-sm text-muted-foreground'}>
        {late ? `Просрочено: ${ru(date)}` : `Срок: ${ru(date)}`}</p>}
      {label && !date && !done && <p className="text-sm text-muted-foreground">Срок не назначен.</p>}
      <Button size="sm" className="mt-1" onClick={() => openInteraction('step', `site:${siteId}`)}>
        {label && !done ? 'Обновить шаг' : 'Записать шаг'}</Button>
    </Section>

    {s.stage === 'on_hold' && <Section title="Пауза">
      <p className="text-sm">{s.holdUntil ? `Пересмотреть ${ru(s.holdUntil)}${s.holdUntil < todayKey() ? ' — срок прошёл' : ''}` : 'Дата пересмотра не задана.'}</p>
      {s.exitText && <p className="text-sm text-muted-foreground">{s.exitText}</p>}
    </Section>}

    {s.gate && s.gate.total > 0 && <Section title={`Требования этапа · ${s.gate.done} из ${s.gate.total}`}>
      {blocking.length ? <ul className="list-disc space-y-0.5 pl-5 text-sm">{blocking.slice(0, 6).map((b) => <li key={b}>{b}</li>)}</ul>
        : <p className="text-sm text-muted-foreground">Обязательное закрыто — этап можно двигать.</p>}
      {blocking.length > 6 && <p className="text-xs text-muted-foreground">и ещё {blocking.length - 6}</p>}
    </Section>}

    {unknown.length > 0 && <Section title="Для решения не хватает">
      <p className="text-sm">{unknown.join(', ')}</p>
    </Section>}

    {!!overview.data?.work.waiting && <p className="text-sm text-muted-foreground">Обязательных работ в Треке держат маршрут: {overview.data.work.waiting}</p>}
    {fromRegistry && <Button size="sm" variant="outline" onClick={() => openProject(siteId)}>Открыть проект</Button>}
  </div>
}

/** Реестр: проект не открыт — показываем мои проекты, где сейчас нужна рука. */
function MyHotProjects({ companyId }: { companyId: string }) {
  const { user } = useAuth()
  const { openInteraction } = useSupportContext()
  const q = useQuery({ queryKey: ['pr-next-steps', companyId], queryFn: () => getProjects(companyId, {}) })
  const today = todayKey()
  const groups = useMemo(() => {
    // «Мои» — по имени ответственного: в строке реестра приезжает именно оно (как в плане работы).
    const mine = (q.data ?? []).filter((p) => p.ownerName === user?.name && p.stage !== 'archive' && !p.closedOn)
    const by = (a: ProjectRow, b: ProjectRow) => (a.nextActionDue ?? '9999').localeCompare(b.nextActionDue ?? '9999')
    return [
      { title: 'Просрочено', items: mine.filter((p) => p.nextActionDue && p.nextActionDue < today).sort(by) },
      { title: 'Сегодня', items: mine.filter((p) => p.nextActionDue === today) },
      { title: 'Шаг не записан', items: mine.filter((p) => !(p.nextAction ?? '').trim() && p.stage !== 'on_hold') },
    ]
  }, [q.data, user?.name, today])
  if (q.isPending) return <Busy />
  const total = groups.reduce((a, g) => a + g.items.length, 0)
  return <div className="space-y-5">
    <p className="text-sm text-muted-foreground">Ваши проекты, где нужна рука. Выберите проект — подсказка и запись шага откроются здесь, без перехода.</p>
    {!total && <p className="text-sm">Просроченного нет, у всех ваших проектов шаг записан.</p>}
    {groups.filter((g) => g.items.length).map((g) => <Section key={g.title} title={`${g.title} · ${g.items.length}`}>
      <ul className="divide-y rounded-md border">{g.items.slice(0, 30).map((p) => <li key={p.id}>
        <button className="w-full px-3 py-2 text-left hover:bg-accent" onClick={() => openInteraction('now', `site:${p.siteId}`)}>
          <div className="text-sm">{p.projectNo ?? p.title}{p.nextActionDue ? ` · ${ru(p.nextActionDue)}` : ''}</div>
          <div className="truncate text-xs text-muted-foreground">{(p.nextAction ?? '').trim() || p.title || p.site?.address}</div>
        </button></li>)}</ul>
      {g.items.length > 30 && <p className="text-xs text-muted-foreground">Показаны первые 30 — полный список в «Плане работ».</p>}
    </Section>)}
  </div>
}

/* ── «Шаг» ────────────────────────────────────────────────────────────── */

export function ProjectStepPanel() {
  const { companyId } = useCompany()
  const { ctx, siteId } = useRailProject()
  if (!companyId) return null
  if (!ctx) return <p className="p-4 text-sm text-muted-foreground">Запись шага работает в разделе «Проекты».</p>
  if (!siteId) return <div className="p-4"><MyHotProjects companyId={companyId} /></div>
  return <div className="h-full overflow-y-auto p-4"><StepForm key={siteId} companyId={companyId} siteId={siteId} /></div>
}

function StepForm({ companyId, siteId }: { companyId: string; siteId: string }) {
  const qc = useQueryClient()
  const { user } = useAuth()
  const { openInteraction } = useSupportContext()
  const { site, label, date } = useNearest(companyId, siteId)
  const people = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })
  const [mode, setMode] = useState<'wait' | 'task'>('wait')
  const [text, setText] = useState('')
  const [due, setDue] = useState(dayShift(3))
  const [person, setPerson] = useState('')
  const who = person || site.data?.ownerUserId || user?.id || ''
  const save = useMutation({
    mutationFn: async () => {
      if (mode === 'wait') return work.setProjectNext(companyId, siteId, { waiting_for: text.trim(), owner_id: who, follow_up: due })
      // Поручение становится ближайшим результатом: его срок и уходит в план работы.
      const task = await createTask({ companyId, title: text.trim(), assigneeId: who || undefined,
        dueAt: new Date(`${due}T18:00`).toISOString(), subjectRef: `site:${siteId}` })
      return work.setProjectNext(companyId, siteId, { work: { kind: 'task', id: task.id } })
    },
    onSuccess: async () => {
      for (const key of ['project-workspace', 'site-detail', 'site-events', 'site-track', 'pr-projects', 'pr-next-steps', 'pr-park-plan', 'sites-list', 'tasks'])
        await qc.invalidateQueries({ queryKey: [key] })
      toast.success('Шаг записан')
      setText('')
      openInteraction('now', `site:${siteId}`)
    },
    onError: (e) => toast.error(e.message),
  })
  if (site.isPending) return <Busy />
  const s = site.data
  const chip = (days: number, title: string) => <button type="button" onClick={() => setDue(dayShift(days))}
    className={`rounded-md border px-2 py-1 text-xs ${due === dayShift(days) ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent'}`}>{title}</button>
  return <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (text.trim() && due && who) save.mutate() }}>
    <div>
      <div className="font-mono text-xs text-muted-foreground">{s?.projectNo}</div>
      <div className="font-medium">{s?.title}</div>
      <p className="mt-1 text-sm text-muted-foreground">Сейчас: {label ? `${label}${date ? ` · ${ru(date)}` : ''}` : 'шаг не записан'}</p>
    </div>
    <div className="inline-flex rounded-md border p-0.5">
      {([['wait', 'Жду ответа'], ['task', 'Сделать / поручить']] as const).map(([k, t]) =>
        <button key={k} type="button" onClick={() => setMode(k)}
          className={`rounded px-2.5 py-1 text-sm ${mode === k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}>{t}</button>)}
    </div>
    <label className="block space-y-1 text-sm">
      <span>{mode === 'wait' ? 'Чего ждём и от кого' : 'Что сделать'}</span>
      <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={300} autoFocus
        placeholder={mode === 'wait' ? 'Ответ собственника по условиям аренды' : 'Направить запрос ТУ в сетевую компанию'} />
    </label>
    <div className="space-y-1 text-sm">
      <span>{mode === 'wait' ? 'Когда выйти на связь' : 'Срок'}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {chip(1, 'Завтра')}{chip(3, 'Через 3 дня')}{chip(7, 'Через неделю')}
        <Input type="date" className="h-8 w-[150px]" value={due} min={todayKey()} onChange={(e) => setDue(e.target.value)} />
      </div>
    </div>
    <label className="block space-y-1 text-sm">
      <span>{mode === 'wait' ? 'Кто следит' : 'Исполнитель'}</span>
      <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={who} onChange={(e) => setPerson(e.target.value)}>
        {!people.data?.some((p) => p.id === who) && who && <option value={who}>{who === user?.id ? user?.name : 'Ответственный проекта'}</option>}
        {people.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
    <Button type="submit" disabled={!text.trim() || !due || !who || save.isPending}>{save.isPending ? 'Сохраняю…' : 'Записать шаг'}</Button>
    <p className="text-xs text-muted-foreground">Шаг станет ближайшим результатом проекта и встанет в «План работы» на эту дату.</p>
  </form>
}
