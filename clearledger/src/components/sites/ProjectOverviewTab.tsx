import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSupportContext } from '@/contexts/SupportContext'
import { listProcessTemplates } from '@/services/docsService'
import { type SiteDetail } from '@/services/sitesService'
import * as work from '@/services/projectWorkspaceService'
import { ProjectWorkActions } from './ProjectWorkActions'
import { TrackRow } from './ProjectTrackTab'
import { ProjectEvidencePicker } from './ProjectEvidencePicker'

export function ProjectOverviewTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const { openInteraction } = useSupportContext()
  const q = useQuery({ queryKey: ['project-workspace', companyId, site.id], queryFn: () => work.getProjectOverview(companyId, site.id), refetchInterval: 30000 })
  const qc = useQueryClient()
  const clear = useMutation({ mutationFn: () => work.setProjectNext(companyId, site.id, {}), onSuccess: () => qc.invalidateQueries({ queryKey: ['project-workspace', companyId, site.id] }), onError: (e) => toast.error(e.message) })
  if (q.isPending) return <p role="status" className="p-4 text-sm">Загрузка обзора проекта…</p>
  if (q.isError) return <div role="alert" className="space-y-2 p-4"><p>Не удалось загрузить обзор: {q.error.message}</p><Button onClick={() => void q.refetch()}>Повторить</Button></div>
  const data = q.data
  const step = data.scenario?.steps.find((s) => s.code === data.scenario?.stage)
  return <div className="space-y-7">
    <div className="space-y-3"><h2 className="text-lg font-semibold">Работа на сегодня</h2>
      <ProjectWorkActions site={site} companyId={companyId} initialTitle={step?.result} />
      <Link className="inline-block text-sm text-primary underline underline-offset-4" to={`?mode=projects&sub=pr_project&project=${site.id}&ptab=docs`}>Добавить документ</Link>
    </div>
    {(data.target_date || data.budget != null) && <p className="text-sm text-muted-foreground">Срок проекта: {data.target_date || 'не задан'} · Бюджет: {data.budget?.toLocaleString('ru') ?? 'не задан'} ₽</p>}
    <section className="border-y py-4"><h3 className="mb-2 font-medium">Ближайший результат</h3>
      {data.next_work?.unavailable ? <p className="text-sm">Связанная работа недоступна. Обратитесь к её ответственному.</p>
        : data.next_work?.id && data.next_work.kind ? <div><Link className="font-medium text-primary" to={work.projectWorkHref({ id: data.next_work.id, kind: data.next_work.kind })}>{data.next_work.title}</Link>
          <p className="mt-1 text-sm text-muted-foreground">Срок работы: {data.next_work.due_at ? new Date(data.next_work.due_at).toLocaleDateString('ru') : 'не назначен'} · {data.next_work.status === 'done' || data.next_work.status === 'executed' ? 'Результат готов — определите следующий шаг' : 'В работе'}</p></div>
          : data.external_wait ? <div className="text-sm"><p>{data.external_wait.waiting_for}</p><p className="mt-1 text-muted-foreground">{data.external_wait.owner_name} · следующий контакт {data.external_wait.follow_up}</p></div>
            : <p className="text-sm text-muted-foreground">{site.nextAction || 'Выберите работу ниже как следующий результат или укажите внешнее ожидание.'}{site.nextActionDue ? ` · ${site.nextActionDue}` : ''}</p>}
      {(data.next_work || data.external_wait) && <Button className="mt-2" variant="ghost" size="sm" disabled={clear.isPending} onClick={() => clear.mutate()}>Снять следующий шаг</Button>}
      <p className="mt-3 text-sm">{data.work.waiting ? `Обязательных работ, удерживающих маршрут: ${data.work.waiting}` : 'В Треке нет незавершённых работ, удерживающих маршрут.'}</p>
      {site.gate?.blocking.length ? <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">Незакрытые требования этапа: {site.gate.blocking.length}</p> : null}
    </section>
    {!!data.pending_results?.total && <section className="space-y-3"><h3 className="font-medium">Результаты ожидают доставки · {data.pending_results.total}</h3>
      <p className="text-sm text-muted-foreground">Работа завершена в Треке. Обновление приложения обрабатывается отдельно.</p>
      {data.pending_results.items.map((item) => <TrackRow key={`${item.kind}:${item.id}`} item={item} site={site} companyId={companyId} />)}
      {data.pending_results.total > data.pending_results.items.length && <Link className="text-sm text-primary" to={`?mode=projects&sub=pr_project&project=${site.id}&ptab=track&workScope=pending`}>Все ожидающие результаты</Link>}
    </section>}
    <section><div className="mb-3 flex items-center justify-between gap-2"><h3 className="font-medium">Открытая работа · {data.work.total}</h3><Link className="text-sm text-primary" to={`?mode=projects&sub=pr_project&project=${site.id}&ptab=track`}>Вся работа</Link></div>
      <div className="space-y-2">{data.work.items.map((item) => <TrackRow key={`${item.kind}:${item.id}`} item={item} site={site} companyId={companyId} />)}</div>
      {!data.work.items.length && <p className="text-sm text-muted-foreground">Открытых поручений и документов нет. Поставьте работу или свяжите существующую.</p>}
    </section>
    {data.scenario && <ScenarioEditor key={`${site.id}:${data.scenario.stage}`} scenario={data.scenario} site={site} companyId={companyId} />}
    <section><h3 className="mb-3 font-medium">Команда и обсуждения</h3><p className="text-sm text-muted-foreground">Непрочитанных сообщений: {data.unread}</p>
      {data.team.length ? <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">{data.team.map((p) => <li key={`${p.id}:${p.role}`}>{p.name} · {p.role}</li>)}</ul> : <p className="mt-2 text-sm text-muted-foreground">Команда не назначена. Добавьте участников в паспорте проекта.</p>}
      <Link className="mt-2 inline-block text-sm text-primary" to={`?mode=projects&sub=pr_project&project=${site.id}&ptab=chats`}>Обсуждения проекта</Link></section>
    <section><h3 className="mb-3 font-medium">Решения и принятые результаты</h3>
      {!data.events.length && <p className="text-sm text-muted-foreground">Решения ещё не зафиксированы.</p>}
      <ol className="divide-y">{data.events.map((event) => <li key={event.id} className="py-3"><p className="whitespace-pre-wrap text-sm">{event.text}</p><p className="mt-1 text-xs text-muted-foreground">{event.author || 'Участник'} · {new Date(event.at).toLocaleString('ru')}</p>
        {event.changes?.map((change, i) => <div key={i} className="mt-2 flex flex-wrap gap-3 text-sm">
          {change.message_id && change.room_id && <button className="text-primary underline" onClick={() => openInteraction('chat', `room:${change.room_id}:message:${change.message_id}`)}>Сообщение-основание</button>}
          {change.work_ref && <Link className="text-primary underline" to={work.projectWorkHref({ kind: change.work_ref.split(':')[0] as 'doc' | 'task', id: change.work_ref.split(':')[1] })}>Подтверждающая работа</Link>}
          {change.deadline && <span>Срок: {change.deadline.from || 'не задан'} → {change.deadline.to}</span>}{change.budget && <span>Бюджет: {change.budget.from ?? 'не задан'} → {change.budget.to.toLocaleString('ru')} ₽</span>}
        </div>)}
      </li>)}</ol>
    </section>
  </div>
}

function ScenarioEditor({ scenario, site, companyId }: { scenario: work.ProjectScenario; site: SiteDetail; companyId: string }) {
  const qc = useQueryClient()
  const [fields, setFields] = useState(scenario.values)
  const [templates, setTemplates] = useState<Record<string, string | null>>(scenario.templates)
  const presets = useQuery({ queryKey: ['process-templates', companyId], queryFn: () => listProcessTemplates(companyId) })
  const [evidence, setEvidence] = useState('')
  const save = useMutation({ mutationFn: (advance: boolean) => {
    const [kind, id] = evidence.split(':')
    return work.updateProjectScenario(companyId, site.id, { fields, templates, advance, expected_stage: scenario.stage,
      evidence: id ? { kind: kind as 'doc' | 'task', id } : undefined })
  }, onSuccess: () => { for (const key of ['project-workspace', 'work-context', 'site-detail', 'pr-projects', 'pr-portfolio', 'pr-overview']) void qc.invalidateQueries({ queryKey: [key] }); toast.success('Сценарий обновлён') }, onError: (e) => toast.error(e.message) })
  const current = scenario.steps.find((s) => s.code === scenario.stage)
  return <section className="space-y-4"><h3 className="font-medium">{scenario.name} · {current?.name || 'Завершено'}</h3>
    <ol className="flex flex-wrap gap-x-4 gap-y-2 text-sm">{scenario.steps.map((s) => <li key={s.code} aria-current={s.code === scenario.stage ? 'step' : undefined} className={s.code === scenario.stage ? 'font-semibold text-primary' : 'text-muted-foreground'}>{s.name}{scenario.evidence[s.code] ? ' — принято' : ''}</li>)}</ol>
    {site.kind === 'warehouse' && <p className="text-sm text-muted-foreground">Резервы, остатки и первичные документы ведутся в складском учёте. Здесь фиксируются потребность, ответственная работа и её результат.</p>}
    <details className="space-y-3"><summary className="cursor-pointer text-sm text-primary">Поля и настройки сценария</summary>
    <div className="grid gap-3 sm:grid-cols-2">{Object.entries(scenario.fields).map(([key, label]) => <label key={key} className="space-y-2 text-sm">{label}{current?.fields?.includes(key) ? ' *' : ''}
      <Input value={fields[key] || ''} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} /></label>)}</div>
    {current && <label className="block space-y-2 text-sm">Предустановленный сценарий Трека для этапа «{current.name}»
      <select aria-label="Предустановленный сценарий Трека" className="h-10 w-full rounded-md border bg-background px-3" value={templates[current.code] || ''} onChange={(e) => setTemplates({ ...templates, [current.code]: e.target.value || null })}>
        <option value="">Обычное поручение или выбор шаблона вручную</option>{presets.data?.templates.filter((t) => current.requirement === 'done' || t.kind === 'document').map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <span className="block text-xs text-muted-foreground">Шаблон и согласование ведёт Трек. Проект определяет, на каком этапе их использовать.</span>
    </label>}
    <Button variant="outline" size="sm" disabled={save.isPending} onClick={() => save.mutate(false)}>Сохранить поля</Button>
    </details>
    {current && <div className="space-y-3"><p className="text-sm">Обязательный результат: {current.result}. Требуется: {current.requirement === 'signed' ? 'подписанный документ' : current.requirement === 'approved' ? 'согласованный документ' : 'принятая работа'}.</p>
      <ProjectEvidencePicker companyId={companyId} siteId={site.id} value={evidence} onChange={setEvidence} /><Button disabled={!evidence || save.isPending} onClick={() => save.mutate(true)}>Принять результат этапа</Button>
    </div>}
  </section>
}
