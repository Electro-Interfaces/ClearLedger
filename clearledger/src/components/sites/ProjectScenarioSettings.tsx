import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Check, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getSiteMembers } from '@/services/sitesService'
import { listProcessTemplates } from '@/services/docsService'
import { getProjectScenarios, prepareScenarioDemo, publishScenario, saveScenarioDraft, type ScenarioDefinition, type ScenarioSettings, type ScenarioStep } from '@/services/projectScenarioService'

const requirements = { done: 'Выполненная работа', approved: 'Согласованный документ', signed: 'Подписанный документ' }
const actions = { discussion: 'Связать обсуждение', decision: 'Зафиксировать решение', file: 'Добавить файл в проект' } as const
const selectClass = 'h-10 w-full rounded-md border bg-background px-3 text-sm'

export function ProjectScenarioSettings({ companyId, onBack, onProject }: { companyId: string; onBack: () => void; onProject: (id: string) => void }) {
  const [kind, setKind] = useState('procurement')
  const q = useQuery({ queryKey: ['project-scenarios', companyId], queryFn: () => getProjectScenarios(companyId), refetchOnWindowFocus: false })
  if (q.isPending) return <p className="p-4 text-sm" role="status">Загрузка сценариев…</p>
  if (q.isError) return <div className="space-y-3 p-4" role="alert"><p>{q.error.message}</p><Button onClick={() => void q.refetch()}>Повторить</Button><Button variant="outline" onClick={onBack}>К проектам</Button></div>
  const selected = q.data.items.find((item) => item.kind === kind) || q.data.items[0]
  if (!selected) return <p className="p-4">Сценарии ещё не настроены.</p>
  return <Editor key={`${companyId}:${selected.kind}:${selected.revision}`} companyId={companyId} state={selected}
    items={q.data.items} canManage={q.data.can_manage} demoAvailable={q.data.demo_available} onProject={onProject} onKind={setKind} onBack={onBack} />
}

function Editor({ companyId, state, items, canManage, demoAvailable, onProject, onKind, onBack }: {
  companyId: string; state: ScenarioSettings; items: ScenarioSettings[]; canManage: boolean
  demoAvailable: boolean; onProject: (id: string) => void
  onKind: (kind: string) => void; onBack: () => void
}) {
  const qc = useQueryClient()
  const initial = state.draft || state.published
  const [definition, setDefinition] = useState<ScenarioDefinition>(() => structuredClone(initial))
  const dirty = JSON.stringify(definition) !== JSON.stringify(initial)
  const people = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })
  const templates = useQuery({ queryKey: ['process-templates', companyId], queryFn: () => listProcessTemplates(companyId) })
  const demo = useMutation({ mutationFn: () => prepareScenarioDemo(companyId), onSuccess: (value) => onProject(value.site_id) })
  const save = useMutation({ mutationFn: (publish: boolean) => publish
    ? publishScenario(companyId, state.kind, state.revision)
    : saveScenarioDraft(companyId, state.kind, state.revision, definition),
  onSuccess: (value) => {
    qc.setQueryData<Awaited<ReturnType<typeof getProjectScenarios>>>(['project-scenarios', companyId],
      (old) => old ? { ...old, items: old.items.map((item) => item.kind === value.kind ? value : item) } : old)
  } })
  const changeStep = (index: number, change: Partial<ScenarioStep>) => setDefinition((value) => ({
    ...value, steps: value.steps.map((step, i) => i === index ? { ...step, ...change } : step),
  }))
  const move = (index: number, delta: number) => setDefinition((value) => {
    const steps = [...value.steps]
    ;[steps[index], steps[index + delta]] = [steps[index + delta], steps[index]]
    return { ...value, steps }
  })
  return <div className="mx-auto w-full max-w-4xl space-y-6 p-3 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold">Сценарии проектов</h2><p className="mt-1 text-sm text-muted-foreground">Этапы, результаты и настройки работы с Чатом и Треком.</p></div>
      <Button variant="outline" disabled={dirty || save.isPending} onClick={onBack}>К проектам</Button>
    </div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-2 text-sm">Вид работ<select className={selectClass} value={state.kind} disabled={dirty || save.isPending} onChange={(e) => onKind(e.target.value)}>
        {items.map((item) => <option key={item.kind} value={item.kind}>{item.published.name}</option>)}
      </select></label>
      <div className="self-end text-sm"><p>Для новых проектов: версия {state.version}</p><p className="mt-1 text-muted-foreground">{state.draft ? 'Есть сохранённый черновик' : 'Черновик ещё не создан'}</p></div>
    </div>
    <p className="text-sm text-muted-foreground">Действующие проекты сохраняют свою версию. Сначала сохраните правки в черновик и проверьте готовность, затем опубликуйте их для новых проектов.</p>
    {!canManage && <p className="text-sm">Настройки доступны для просмотра. Изменения публикует администратор компании.</p>}
    <fieldset disabled={!canManage || save.isPending} className="min-w-0 space-y-6">
      <label className="block space-y-2 text-sm">Название сценария<Input value={definition.name} maxLength={120} onChange={(e) => setDefinition({ ...definition, name: e.target.value })} /></label>
      <section className="space-y-3"><h3 className="font-medium">Сведения для работы</h3>
        <div className="grid gap-3 sm:grid-cols-2">{Object.entries(definition.fields).map(([code, label]) => <label key={code} className="space-y-1 text-sm">Название поля
          <Input aria-label={`Название поля ${label}`} value={label} maxLength={120} onChange={(e) => setDefinition({ ...definition, fields: { ...definition.fields, [code]: e.target.value } })} />
        </label>)}</div>
        <Button variant="outline" size="sm" disabled={Object.keys(definition.fields).length >= 30} onClick={() => setDefinition({ ...definition, fields: { ...definition.fields, [`field_${Date.now()}`]: 'Новое поле' } })}>Добавить поле</Button>
      </section>
      <section className="space-y-3"><h3 className="font-medium">Последовательность этапов</h3>
        <ol className="divide-y border-y">{definition.steps.map((step, index) => <li key={step.code} className="py-3">
          <details open={definition.steps.length === 1 || undefined}>
            <summary className="cursor-pointer py-1 text-sm font-medium">{index + 1}. {step.name} · {requirements[step.requirement]}</summary>
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-2 text-sm">Название этапа<Input value={step.name} maxLength={120} onChange={(e) => changeStep(index, { name: e.target.value })} /></label>
                <label className="space-y-2 text-sm">Подтверждение результата<select className={selectClass} value={step.requirement} onChange={(e) => changeStep(index, { requirement: e.target.value as ScenarioStep['requirement'] })}>
                  {Object.entries(requirements).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select></label></div>
              <label className="block space-y-2 text-sm">Ожидаемый результат<Input value={step.result} maxLength={300} onChange={(e) => changeStep(index, { result: e.target.value })} /></label>
              <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-2 text-sm">Исполнитель по умолчанию<select className={selectClass} value={step.responsible_id || ''} onChange={(e) => changeStep(index, { responsible_id: e.target.value || null })}>
                <option value="">Ответственный проекта</option>{people.data?.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
                {step.responsible_id && !people.data?.some((person) => person.id === step.responsible_id) && <option value={step.responsible_id}>Сотрудник недоступен</option>}
              </select></label>
                <label className="space-y-2 text-sm">Срок новой работы, календарных дней<Input type="number" min={1} max={365} value={step.due_days ?? ''} onChange={(e) => changeStep(index, { due_days: e.target.value ? Number(e.target.value) : null })} /></label></div>
              <label className="block space-y-2 text-sm">Шаблон Трека<select className={selectClass} value={step.template_id || ''} onChange={(e) => changeStep(index, { template_id: e.target.value || null })}>
                <option value="">Выбрать при постановке работы</option>{templates.data?.templates.filter((template) => step.requirement === 'done' || template.kind === 'document').map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
                {step.template_id && !templates.data?.templates.some((template) => template.id === step.template_id && (step.requirement === 'done' || template.kind === 'document')) && <option value={step.template_id}>Шаблон недоступен для этапа</option>}
              </select></label>
              <fieldset className="space-y-2"><legend className="mb-2 text-sm">Обязательные сведения перед принятием результата</legend>
                <div className="flex flex-wrap gap-x-5 gap-y-3">{Object.entries(definition.fields).map(([code, label]) => <label key={code} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={step.fields.includes(code)} onChange={(e) => changeStep(index, { fields: e.target.checked ? [...step.fields, code] : step.fields.filter((key) => key !== code) })} />{label}</label>)}</div>
              </fieldset>
              <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" aria-label={`Поднять этап ${step.name}`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp className="size-4" />Выше</Button>
                <Button size="sm" variant="outline" aria-label={`Опустить этап ${step.name}`} disabled={index === definition.steps.length - 1} onClick={() => move(index, 1)}><ArrowDown className="size-4" />Ниже</Button>
                <Button size="sm" variant="outline" aria-label={`Убрать этап ${step.name}`} disabled={definition.steps.length === 1} onClick={() => setDefinition({ ...definition, steps: definition.steps.filter((s) => s.code !== step.code) })}><Trash2 className="size-4" />Убрать этап</Button></div>
            </div>
          </details>
        </li>)}</ol>
        <Button size="sm" variant="outline" disabled={definition.steps.length >= 30} onClick={() => setDefinition({ ...definition, steps: [...definition.steps, { code: `step_${Date.now()}`, name: 'Новый этап', result: 'Результат работы принят', requirement: 'done', fields: [], responsible_id: null, template_id: null, due_days: null }] })}>Добавить этап</Button>
      </section>
      <fieldset className="space-y-3"><legend className="mb-3 font-medium">Действия приложения в Чате</legend>{Object.entries(actions).map(([code, label]) => <label key={code} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={definition.message_actions.includes(code as keyof typeof actions)} onChange={(e) => setDefinition({ ...definition, message_actions: e.target.checked ? [...definition.message_actions, code as keyof typeof actions] : definition.message_actions.filter((value) => value !== code) })} />{label}</label>)}</fieldset>
    </fieldset>
    {(people.isError || templates.isError) && <div role="alert" className="text-sm"><p>Не удалось загрузить сотрудников или шаблоны. Сохранённые настройки остаются на месте.</p><Button variant="outline" size="sm" onClick={() => { void people.refetch(); void templates.refetch() }}>Повторить загрузку</Button></div>}
    <section className="space-y-3 border-t pt-5"><h3 className="font-medium">Готовность сохранённого сценария</h3>
      {dirty && <p className="text-sm">Сохраните черновик, чтобы проверить текущие правки.</p>}
      <ul className="space-y-2">{state.readiness.checks.map((check) => <li key={check.key} className={`flex items-start gap-2 text-sm ${check.ok ? '' : 'text-destructive'}`}>{check.ok ? <Check className="mt-0.5 size-4 shrink-0" /> : <X className="mt-0.5 size-4 shrink-0" />}<span>{check.message}</span></li>)}</ul>
      <p className="text-sm text-muted-foreground">Проверяются подключения приложений и выбранные сотрудники и шаблоны. Внешние поставщики и учётные системы проверяются при выполнении работы.</p>
    </section>
    {save.isError && <div role="alert" className="space-y-2 text-sm text-destructive"><p>{save.error.message}</p><Button variant="outline" size="sm" onClick={() => {
      setDefinition(structuredClone(initial)); save.reset()
      void qc.invalidateQueries({ queryKey: ['project-scenarios', companyId] })
    }}>Отменить правки и обновить</Button></div>}
    {canManage && <div className="flex flex-wrap gap-2 border-t pt-4">
      <Button variant={dirty ? 'default' : 'outline'} disabled={save.isPending || !dirty && !!state.draft} onClick={() => save.mutate(false)}>{save.isPending ? 'Сохранение…' : 'Сохранить черновик'}</Button>
      <Button variant={dirty ? 'outline' : 'default'} disabled={save.isPending || dirty || !state.draft || !state.readiness.ready} onClick={() => save.mutate(true)}>Опубликовать для новых проектов</Button>
      {dirty && <Button variant="outline" disabled={save.isPending} onClick={() => setDefinition(structuredClone(initial))}>Отменить правки</Button>}
    </div>}
    {!!state.history.length && <details className="border-t pt-4"><summary className="cursor-pointer text-sm">Предыдущие версии · {state.history.length}</summary><ol className="mt-3 space-y-3">{[...state.history].reverse().map((version) => <li key={version.version} className="text-sm"><p className="font-medium">Версия {version.version} · {version.definition.name}</p><p className="mt-1 text-muted-foreground">{version.definition.steps.map((step) => step.name).join(' → ')}</p></li>)}</ol></details>}
    {demoAvailable && <section className="space-y-3 border-t pt-4"><h3 className="font-medium">Учебная закупка</h3><p className="text-sm text-muted-foreground">Подготовит проект, трёх вымышленных сотрудников, обсуждение и пять работ с документами. Повторное нажатие откроет тот же пример и сохранит достигнутый результат.</p>
      <Button variant="outline" disabled={dirty || save.isPending || demo.isPending} onClick={() => demo.mutate()}>{demo.isPending ? 'Подготовка примера…' : 'Открыть учебную закупку'}</Button>
      {demo.isError && <p role="alert" className="text-sm text-destructive">{demo.error.message}</p>}
    </section>}
  </div>
}
