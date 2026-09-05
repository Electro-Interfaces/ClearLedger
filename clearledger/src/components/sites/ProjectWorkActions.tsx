import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useSupportContext } from '@/contexts/SupportContext'
import { createTask } from '@/services/tasksService'
import { getSiteMembers, type SiteDetail } from '@/services/sitesService'
import { ProjectEvidencePicker } from './ProjectEvidencePicker'
import * as work from '@/services/projectWorkspaceService'
import { resolveWorkContext } from '@/services/workContextService'

export function ProjectWorkActions({ site, companyId, initialTitle = '' }: {
  site: SiteDetail; companyId: string; initialTitle?: string
}) {
  const qc = useQueryClient()
  const { openInteraction } = useSupportContext()
  const [mode, setMode] = useState<'task' | 'link' | 'decision' | 'wait' | null>(null)
  const [title, setTitle] = useState(initialTitle)
  const [person, setPerson] = useState(site.ownerUserId ?? '')
  const [due, setDue] = useState('')
  const [onlyUnlinked, setOnlyUnlinked] = useState(true)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState('')
  const [source, setSource] = useState('')
  const [budget, setBudget] = useState('')
  const [watchers, setWatchers] = useState<string[]>([])
  const context = useQuery({ queryKey: ['work-context', companyId, `site:${site.id}`], queryFn: () => resolveWorkContext(companyId, `site:${site.id}`), enabled: !!mode })
  const people = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId), enabled: !!mode })
  const unlinked = useQuery({ queryKey: ['project-unlinked', companyId, search, offset, onlyUnlinked],
    queryFn: () => work.unlinkedWork(companyId, search, offset, onlyUnlinked), enabled: mode === 'link' })
  const refresh = async () => {
    for (const key of ['site-track', 'project-workspace', 'site-detail', 'site-events', 'pr-projects', 'pr-portfolio', 'pr-overview', 'work', 'tasks', 'project-unlinked'])
      await qc.invalidateQueries({ queryKey: [key] })
  }
  const save = useMutation({ mutationFn: async () => {
    if (mode === 'task') return createTask({ companyId, title: title.trim(), assigneeId: person || undefined,
      dueAt: due ? new Date(`${due}T18:00`).toISOString() : undefined, subjectRef: `site:${site.id}`, watcherIds: watchers })
    if (mode === 'decision') {
      const [kind, id] = selected.split(':')
      return work.recordProjectDecision(companyId, site.id, { text: title.trim(),
        source_message_id: source.trim() || undefined, work: id ? { kind: kind as 'doc' | 'task', id } : undefined,
        deadline: due || undefined, budget: budget ? Number(budget) : undefined })
    }
    if (mode === 'wait') return work.setProjectNext(companyId, site.id, { waiting_for: title.trim(), owner_id: person, follow_up: due })
    const [kind, id] = selected.split(':')
    return work.linkProjectWork(companyId, site.id, source.trim() ? { kind: 'message', id: source.trim() } : { kind: kind as 'doc' | 'task', id })
  }, onSuccess: async () => { await refresh(); setMode(null); toast.success('Сохранено в проекте') }, onError: (e) => toast.error(e.message) })
  const chat = useMutation({ mutationFn: () => work.openProjectChat(companyId, site.id),
    onSuccess: (r) => openInteraction('chat', `room:${r.room_id}`), onError: (e) => toast.error(e.message) })
  const open = (value: typeof mode) => { setMode(value); setTitle(value === 'task' ? initialTitle : ''); setSelected(''); setSource(''); setDue(''); setBudget(''); setWatchers([]) }
  const labels = { task: 'Поручить', link: 'Связать существующее', decision: 'Зафиксировать решение', wait: 'Внешнее ожидание' }
  return <>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={chat.isPending} onClick={() => chat.mutate()}>Обсудить</Button>
      <Button size="sm" onClick={() => open('task')}>Поручить</Button>
      <Button size="sm" variant="outline" onClick={() => open('decision')}>Зафиксировать решение</Button>
      <Button size="sm" variant="ghost" onClick={() => open('link')}>Связать существующее</Button>
      <Button size="sm" variant="ghost" onClick={() => open('wait')}>Внешнее ожидание</Button>
    </div>
    <Dialog open={!!mode} onOpenChange={(value) => { if (!value && !save.isPending) setMode(null) }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>{mode ? labels[mode] : ''}</DialogTitle>
          <DialogDescription>{site.projectNo} · {site.title || site.address}</DialogDescription></DialogHeader>
        {mode !== 'link' && <label className="space-y-2 text-sm">{mode === 'task' ? 'Что сделать' : mode === 'wait' ? 'Кого и чего ждём' : 'Принятое решение'}
          <Textarea aria-label={mode === 'task' ? 'Что сделать' : mode === 'wait' ? 'Кого и чего ждём' : 'Принятое решение'} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={mode === 'decision' ? 4000 : 300} /></label>}
        {(mode === 'task' || mode === 'wait') && <label className="space-y-2 text-sm">Ответственный
          <select aria-label="Ответственный" className="flex h-10 w-full rounded-md border bg-background px-3" value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Выберите сотрудника</option>{people.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>{people.isError && <button type="button" className="text-destructive" onClick={() => void people.refetch()}>Ошибка загрузки сотрудников. Повторить</button>}</label>}
        {mode !== 'link' && <label className="space-y-2 text-sm">{mode === 'wait' ? 'Дата следующего контакта' : mode === 'decision' ? 'Новый срок проекта, если изменился' : 'Срок'}
          <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>}
        {mode === 'task' && !!context.data?.suggested_people?.length && <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">Наблюдатели из команды проекта</legend>
          {context.data.suggested_people.map((p) => <label key={p.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={watchers.includes(p.id)} onChange={(e) => setWatchers(e.target.checked ? [...watchers, p.id] : watchers.filter((id) => id !== p.id))} />{p.name}</label>)}
        </fieldset>}
        {mode === 'decision' && <>
          <label className="space-y-2 text-sm">Новый бюджет проекта, ₽<Input type="number" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
          <ProjectEvidencePicker companyId={companyId} siteId={site.id} value={selected} onChange={setSelected} label="Связанная работа" />
        </>}
        {mode === 'link' && <div className="space-y-3">
          <p className="text-sm text-muted-foreground">Выберите задачу или документ. Связь не изменяет права на работу.</p>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyUnlinked} onChange={(e) => { setOnlyUnlinked(e.target.checked); setOffset(0) }} />Только без проекта</label>
          <Input aria-label="Поиск работы без проекта" value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0) }} placeholder="Название или номер" />
          {unlinked.isLoading && <p className="text-sm">Загрузка…</p>}
          {unlinked.isError && <Button variant="outline" onClick={() => void unlinked.refetch()}>Не удалось загрузить. Повторить</Button>}
          <div className="max-h-56 space-y-1 overflow-y-auto">{unlinked.data?.items.map((w) => <label key={`${w.kind}:${w.id}`} className="flex items-start gap-2 rounded p-2 text-sm hover:bg-accent">
            <input type="radio" name="link-work" checked={selected === `${w.kind}:${w.id}`} onChange={() => { setSelected(`${w.kind}:${w.id}`); setSource('') }} />
            <span>{w.key} · {w.title}<span className="block text-xs text-muted-foreground">{w.state_name}</span></span>
          </label>)}</div>
          {unlinked.data && <div className="flex items-center justify-between text-sm"><Button size="sm" variant="ghost" disabled={!offset} onClick={() => setOffset(offset - 40)}>Назад</Button>
            <span>Всего: {unlinked.data.total}</span><Button size="sm" variant="ghost" disabled={offset + 40 >= unlinked.data.total} onClick={() => setOffset(offset + 40)}>Далее</Button></div>}
        </div>}
        <Button disabled={save.isPending || (mode === 'link' ? !selected && !source.trim() : title.trim().length < 3) || (mode === 'wait' && (!person || !due))}
          onClick={() => save.mutate()}>{save.isPending ? 'Сохранение…' : mode ? labels[mode] : 'Сохранить'}</Button>
      </DialogContent>
    </Dialog>
  </>
}
