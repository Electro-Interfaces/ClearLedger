import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Save, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import * as docsService from '@/services/docsService'
import type { DocKind, DocKindField } from '@/services/docsService'

type DraftActor = { by: 'user' | 'role' | 'department' | 'head_of' | 'position'; ref: string }
type ConditionOp = (typeof CONDITION_OPS)[number][0]
type DraftCondition = { field: string; op: ConditionOp; value: string }
type DraftStep = {
  code: string
  name: string
  mode: 'serial' | 'parallel'
  quorum: string
  sla_hours: string
  step_kind: 'approve' | 'sign'
  when: DraftCondition | null
  actors: DraftActor[]
}
type DraftKind = Omit<DocKind, 'id' | 'route'> & { route: DraftStep[] }

const FAMILY = [
  ['incoming', 'Входящие'], ['outgoing', 'Исходящие'], ['ord', 'Приказы и распоряжения'],
  ['internal', 'Внутренние'], ['contract', 'Договорные'], ['other', 'Прочие'],
] as const
const SELECT_CLASS = 'h-9 w-full rounded-md border border-input bg-background px-2 text-sm'
// Условие шага. Списки повторяют CONDITION_OPS и CONDITION_CARD_FIELDS из
// server/app/services/doc_approvals.py: что не из этих списков, санитайзер выбросит.
const CONDITION_OPS = [
  ['eq', 'равно'], ['ne', 'не равно'], ['gt', 'больше'], ['gte', 'больше или равно'],
  ['lt', 'меньше'], ['lte', 'меньше или равно'], ['in', 'один из'],
  ['set', 'заполнено'], ['unset', 'не заполнено'],
] as const
const CONDITION_CARD_FIELDS = [
  ['family', 'Поток'], ['kind_code', 'Код вида'], ['direction', 'Направление'],
  ['confidentiality', 'Доступ'], ['counterparty_id', 'Корреспондент'],
  ['object_id', 'Объект'], ['subject_ref', 'Предмет (ссылка)'],
  ['organization_id', 'Наше юрлицо'], ['department_id', 'Подразделение'],
] as const
// Свойства карточки хранят коды, а не подписи: подсказываем, что вводить.
const CONDITION_VALUE_HINT: Record<string, string> = {
  family: FAMILY.map(([code]) => code).join(', '),
  direction: 'none, in, out',
  confidentiality: 'company, private, strict',
}

function hasConditionValue(op: ConditionOp): boolean {
  return op !== 'set' && op !== 'unset'
}

function draftCondition(raw: unknown): DraftCondition | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const field = String(row.field ?? '').trim()
  if (!field) return null
  return {
    field,
    op: CONDITION_OPS.find(([code]) => code === row.op)?.[0] ?? 'eq',
    value: Array.isArray(row.value) ? row.value.map(String).join(', ') : String(row.value ?? ''),
  }
}

function conditionPayload(when: DraftCondition): Record<string, unknown> {
  if (!hasConditionValue(when.op)) return { field: when.field, op: when.op }
  if (when.op === 'in') {
    return {
      field: when.field, op: when.op,
      value: when.value.split(',').map((item) => item.trim()).filter(Boolean),
    }
  }
  return { field: when.field, op: when.op, value: when.value.trim() }
}

function conditionPlaceholder(when: DraftCondition, fields: DocKindField[]): string {
  const hint = CONDITION_VALUE_HINT[when.field]
    ?? (fields.find((field) => fieldCode(field.code) === when.field)?.options ?? []).join(', ')
  if (when.op === 'in') return hint ? `значения через запятую: ${hint}` : 'значения через запятую'
  return hint || 'значение'
}

function emptyKind(): DraftKind {
  return {
    code: '', name: '', description: '', family: 'internal', direction: 'none',
    number_template: '{prefix}-{org}-{yyyy}-{n:04d}', number_scope: 'kind_org_year',
    number_prefix: '', fields: [], route: [], default_case_id: null,
    errand_type_id: null, requires_registration: true, is_active: true, sort_order: 100,
    gate_key: null,
  }
}

function draftKind(value?: DocKind): DraftKind {
  if (!value) return emptyKind()
  return {
    ...value,
    fields: value.fields.map((field) => ({ ...field, options: [...(field.options ?? [])] })),
    route: value.route.map((raw, index) => ({
      code: String(raw.code ?? `step_${index + 1}`),
      name: String(raw.name ?? ''),
      mode: raw.mode === 'parallel' ? 'parallel' : 'serial',
      quorum: String(raw.quorum ?? 'all'),
      sla_hours: raw.sla_hours ? String(raw.sla_hours) : '',
      step_kind: raw.step_kind === 'sign' ? 'sign' : 'approve',
      when: draftCondition(raw.when),
      actors: Array.isArray(raw.actors) ? raw.actors.map((actor) => {
        const row = actor as Record<string, unknown>
        const by = ['user', 'role', 'department', 'head_of', 'position'].includes(String(row.by))
          ? String(row.by) as DraftActor['by'] : 'user'
        return { by, ref: String(row.ref ?? '') }
      }) : [],
    })),
  }
}

function fieldCode(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
}

export function DocKindEditor({ companyId, initial, onClose, onSaved }: {
  companyId: string
  initial?: DocKind
  onClose: () => void
  onSaved: () => void
}) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<DraftKind>(() => draftKind(initial))
  const subjectsQ = useQuery({
    queryKey: ['doc-kind-subjects', companyId],
    queryFn: () => docsService.listKindSubjects(companyId),
  })
  const casesQ = useQuery({
    queryKey: ['doc-cases', companyId],
    queryFn: () => docsService.listCases(companyId),
  })
  // Пункты чек-листа проекта — из самого чек-листа, а не вторым списком: они
  // разошлись бы, и вид закрывал бы несуществующий пункт.
  const gateKeys = useQuery({
    queryKey: ['doc-gate-keys', companyId],
    queryFn: () => docsService.listGateKeys(companyId),
    staleTime: 10 * 60 * 1000,
  })
  const save = useMutation({
    mutationFn: () => docsService.saveKind(companyId, {
      ...draft,
      code: draft.code.trim(),
      name: draft.name.trim(),
      description: draft.description?.trim() || null,
      number_prefix: draft.number_prefix.trim(),
      number_template: draft.number_template.trim(),
      fields: draft.fields.filter((field) => field.code.trim() && field.label.trim()).map((field) => ({
        ...field, code: fieldCode(field.code), label: field.label.trim(),
        options: field.type === 'select' ? field.options : undefined,
      })),
      route: draft.route.map((step) => ({
        code: fieldCode(step.code), name: step.name.trim(), mode: step.mode,
        quorum: step.mode === 'parallel' ? step.quorum : 'all',
        required: true, actors: step.actors.filter((actor) => actor.ref),
        ...(step.sla_hours ? { sla_hours: Number(step.sla_hours) } : {}),
        ...(step.step_kind === 'sign' ? { step_kind: 'sign' } : {}),
        ...(step.when ? { when: conditionPayload(step.when) } : {}),
      })),
    }, initial?.id),
    onSuccess: () => {
      toast.success(initial ? 'Вид документа обновлён' : 'Вид документа создан')
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      onSaved()
    },
    onError: (error) => toast.error((error as Error).message),
  })
  const numberWarning = draft.number_scope.includes('org')
    && !draft.number_template.includes('{org')
  const invalidRoute = draft.route.some((step) => !fieldCode(step.code) || !step.name.trim()
    || step.actors.length === 0 || step.actors.some((actor) => !actor.ref)
    || (!!step.when && hasConditionValue(step.when.op) && !step.when.value.trim()))
  const invalidFields = draft.fields.some((field) => !fieldCode(field.code) || !field.label.trim()
    || (field.type === 'select' && !(field.options?.length)))
  const ready = !!draft.code.trim() && !!draft.name.trim() && draft.number_template.includes('{n')
    && !numberWarning && !invalidRoute && !invalidFields
    && subjectsQ.isSuccess && casesQ.isSuccess

  const actorOptions = useMemo(() => {
    const subjects = subjectsQ.data
    return {
      user: subjects?.people ?? [], role: subjects?.roles ?? [],
      department: subjects?.departments ?? [], head_of: subjects?.departments ?? [],
      position: (subjects?.positions ?? []).map((name) => ({ id: name, name })),
    }
  }, [subjectsQ.data])

  const updateField = (index: number, patch: Partial<DocKindField>) => setDraft((current) => ({
    ...current, fields: current.fields.map((field, fieldIndex) => (
      fieldIndex === index ? { ...field, ...patch } : field
    )),
  }))
  const updateStep = (index: number, patch: Partial<DraftStep>) => setDraft((current) => ({
    ...current, route: current.route.map((step, stepIndex) => (
      stepIndex === index ? { ...step, ...patch } : step
    )),
  }))

  return (
    <Card className="space-y-5 border-primary/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{initial ? `Вид «${initial.name}»` : 'Новый вид документа'}</h2>
          <p className="text-xs text-muted-foreground">Изменения действуют только для новых операций; уже выданные номера не переписываются.</p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}><X className="mr-1 h-4 w-4" />Закрыть</Button>
      </div>

      {(subjectsQ.isError || casesQ.isError) && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/30 p-3 text-sm">
          <span>Справочники маршрута не загрузились. Сохранение заблокировано.</span>
          <Button type="button" size="sm" variant="outline" onClick={() => {
            void subjectsQ.refetch(); void casesQ.refetch()
          }}>Повторить</Button>
        </div>
      )}

      <section className="space-y-3" aria-labelledby="kind-main-heading">
        <h3 id="kind-main-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Основное</h3>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Код" id="kind-code"><Input id="kind-code" value={draft.code} disabled={!!initial}
            onChange={(event) => setDraft({ ...draft, code: fieldCode(event.target.value) })} /></Field>
          <Field label="Название" id="kind-name" className="lg:col-span-2"><Input id="kind-name" value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
          <Field label="Порядок" id="kind-sort"><Input id="kind-sort" type="number" value={draft.sort_order}
            onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) || 0 })} /></Field>
          {/* Связь с проектом задаётся данными: какой именно вид считается
              «договором аренды ЗУ», решает делопроизводство компании, и зашивать
              это в наш перечень значило бы требовать релиз ради переименования. */}
          <Field label="Закрывает пункт проекта" id="kind-gate">
            <Select value={draft.gate_key || 'none'}
              onValueChange={(v: string) => setDraft({ ...draft, gate_key: v === 'none' ? null : v })}>
              <SelectTrigger id="kind-gate"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Не закрывает</SelectItem>
                {(gateKeys.data ?? []).map((k) => (
                  <SelectItem key={k.key} value={k.key}>{k.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Поток" id="kind-family"><select id="kind-family" value={draft.family}
            onChange={(event) => setDraft({ ...draft, family: event.target.value })} className={SELECT_CLASS}>
            {FAMILY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
          <Field label="Направление" id="kind-direction"><select id="kind-direction" value={draft.direction}
            onChange={(event) => setDraft({ ...draft, direction: event.target.value })} className={SELECT_CLASS}>
            <option value="none">без направления</option><option value="in">входящий</option><option value="out">исходящий</option>
          </select></Field>
          <label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" checked={draft.requires_registration}
            onChange={(event) => setDraft({ ...draft, requires_registration: event.target.checked })} />Требует регистрации</label>
          <label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" checked={draft.is_active}
            onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} />Активен</label>
          <Field label="Описание" id="kind-description" className="md:col-span-2 lg:col-span-4"><Textarea id="kind-description" rows={2}
            value={draft.description ?? ''} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></Field>
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="kind-number-heading">
        <h3 id="kind-number-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Нумерация</h3>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Префикс" id="kind-prefix"><Input id="kind-prefix" value={draft.number_prefix}
            onChange={(event) => setDraft({ ...draft, number_prefix: event.target.value })} /></Field>
          <Field label="Область счётчика" id="kind-scope"><select id="kind-scope" value={draft.number_scope}
            onChange={(event) => setDraft({ ...draft, number_scope: event.target.value })} className={SELECT_CLASS}>
            <option value="kind">по виду</option><option value="kind_year">по виду и году</option>
            <option value="kind_org">по виду и юрлицу</option><option value="kind_org_year">по виду, юрлицу и году</option>
          </select></Field>
          <Field label="Шаблон номера" id="kind-template" className="md:col-span-2"><Input id="kind-template" value={draft.number_template}
            onChange={(event) => setDraft({ ...draft, number_template: event.target.value })} /></Field>
        </div>
        <p className="text-xs text-muted-foreground">Переменные: {'{prefix}'}, {'{org}'}, {'{yyyy}'}, {'{yy}'}, {'{kind}'}, {'{n:04d}'}.</p>
        {numberWarning && <p role="alert" className="text-xs text-destructive">Для отдельной нумерации по юрлицам добавьте {'{org}'} в видимый номер.</p>}
        {!draft.number_template.includes('{n') && <p role="alert" className="text-xs text-destructive">В шаблоне нет счётчика {'{n}'}.</p>}
      </section>

      <section className="space-y-3" aria-labelledby="kind-fields-heading">
        <div className="flex items-center justify-between gap-2"><h3 id="kind-fields-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Реквизиты карточки</h3>
          <Button type="button" size="sm" variant="outline" onClick={() => setDraft({ ...draft, fields: [...draft.fields,
            { code: `field_${draft.fields.length + 1}`, label: '', type: 'text', required: false }] })}><Plus className="mr-1 h-3.5 w-3.5" />Добавить</Button></div>
        {draft.fields.map((field, index) => (
          <div key={index} className="grid gap-2 rounded-md border p-3 md:grid-cols-[1fr_1.5fr_1fr_auto_auto]">
            <Input aria-label={`Код реквизита ${index + 1}`} value={field.code} onChange={(event) => updateField(index, { code: fieldCode(event.target.value) })} placeholder="код" />
            <Input aria-label={`Название реквизита ${index + 1}`} value={field.label} onChange={(event) => updateField(index, { label: event.target.value })} placeholder="Название" />
            <select aria-label={`Тип реквизита ${index + 1}`} value={field.type} onChange={(event) => updateField(index, { type: event.target.value as DocKindField['type'] })} className={SELECT_CLASS}>
              <option value="text">Строка</option><option value="textarea">Большой текст</option><option value="number">Число</option><option value="date">Дата</option><option value="boolean">Да/нет</option><option value="select">Список</option>
            </select>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={field.required} onChange={(event) => updateField(index, { required: event.target.checked })} />Обязательный</label>
            <Button type="button" size="icon" variant="ghost" aria-label={`Удалить реквизит ${field.label || index + 1}`}
              onClick={() => setDraft({ ...draft, fields: draft.fields.filter((_, itemIndex) => itemIndex !== index) })}><Trash2 className="h-4 w-4" /></Button>
            {field.type === 'select' && <Input className="md:col-span-5" aria-label={`Варианты реквизита ${index + 1}`} value={(field.options ?? []).join(', ')}
              onChange={(event) => updateField(index, { options: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) })} placeholder="Варианты через запятую" />}
          </div>
        ))}
        {draft.fields.length === 0 && <p className="text-sm text-muted-foreground">Дополнительных реквизитов нет.</p>}
      </section>

      <section className="space-y-3" aria-labelledby="kind-route-heading">
        <div className="flex items-center justify-between gap-2"><h3 id="kind-route-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Маршрут согласования</h3>
          <Button type="button" size="sm" variant="outline" disabled={!subjectsQ.isSuccess} onClick={() => setDraft({ ...draft, route: [...draft.route, {
            code: `step_${draft.route.length + 1}`, name: '', mode: 'serial', quorum: 'all', sla_hours: '', step_kind: 'approve', when: null, actors: [{ by: 'user', ref: '' }],
          }] })}><Plus className="mr-1 h-3.5 w-3.5" />Добавить шаг</Button></div>
        {draft.route.map((step, stepIndex) => (
          <div key={stepIndex} className="space-y-3 rounded-md border p-3">
            <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-6">
              <Input aria-label={`Код шага ${stepIndex + 1}`} value={step.code} onChange={(event) => updateStep(stepIndex, { code: fieldCode(event.target.value) })} placeholder="код шага" />
              <Input aria-label={`Название шага ${stepIndex + 1}`} value={step.name} onChange={(event) => updateStep(stepIndex, { name: event.target.value })} placeholder="Юридическая проверка" className="lg:col-span-2" />
              <select aria-label={`Порядок шага ${stepIndex + 1}`} value={step.mode} onChange={(event) => updateStep(stepIndex, { mode: event.target.value as DraftStep['mode'] })} className={SELECT_CLASS}><option value="serial">по очереди</option><option value="parallel">параллельно</option></select>
              <select aria-label={`Назначение шага ${stepIndex + 1}`} value={step.step_kind} onChange={(event) => updateStep(stepIndex, { step_kind: event.target.value as DraftStep['step_kind'] })} className={SELECT_CLASS}><option value="approve">согласование</option><option value="sign">подпись</option></select>
              <Button type="button" size="icon" variant="ghost" aria-label={`Удалить шаг ${step.name || stepIndex + 1}`}
                onClick={() => setDraft({ ...draft, route: draft.route.filter((_, index) => index !== stepIndex) })}><Trash2 className="h-4 w-4" /></Button>
              <Input aria-label={`Срок шага ${stepIndex + 1} в часах`} type="number" min={1} max={8760} value={step.sla_hours} onChange={(event) => updateStep(stepIndex, { sla_hours: event.target.value })} placeholder="SLA, часов" />
              {step.mode === 'parallel' && <select aria-label={`Кворум шага ${stepIndex + 1}`} value={step.quorum} onChange={(event) => updateStep(stepIndex, { quorum: event.target.value })} className={SELECT_CLASS}><option value="all">решение всех</option><option value="any">достаточно одного</option></select>}
            </div>
            <ConditionRow when={step.when} index={stepIndex} fields={draft.fields}
              onChange={(when) => updateStep(stepIndex, { when })} />
            <div className="space-y-2">
              {step.actors.map((actor, actorIndex) => (
                <div key={actorIndex} className="grid gap-2 md:grid-cols-[180px_1fr_auto]">
                  <select aria-label={`Способ назначения ${actorIndex + 1}`} value={actor.by} onChange={(event) => {
                    const actors = step.actors.map((row, index) => index === actorIndex
                      ? { by: event.target.value as DraftActor['by'], ref: '' } : row)
                    updateStep(stepIndex, { actors })
                  }} className={SELECT_CLASS}><option value="user">сотрудник</option><option value="role">роль</option><option value="department">подразделение</option><option value="head_of">руководитель подразделения</option><option value="position">должность</option></select>
                  <select aria-label={`Участник маршрута ${actorIndex + 1}`} value={actor.ref} onChange={(event) => {
                    const actors = step.actors.map((row, index) => index === actorIndex ? { ...row, ref: event.target.value } : row)
                    updateStep(stepIndex, { actors })
                  }} className={SELECT_CLASS}><option value="">выберите</option>{actorOptions[actor.by].map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</select>
                  <Button type="button" size="icon" variant="ghost" aria-label="Удалить участника" disabled={step.actors.length === 1}
                    onClick={() => updateStep(stepIndex, { actors: step.actors.filter((_, index) => index !== actorIndex) })}><Trash2 className="h-4 w-4" /></Button>
                </div>
              ))}
              <Button type="button" size="sm" variant="ghost" onClick={() => updateStep(stepIndex, { actors: [...step.actors, { by: 'user', ref: '' }] })}><Plus className="mr-1 h-3.5 w-3.5" />Участник</Button>
            </div>
          </div>
        ))}
        {draft.route.length === 0 && <p className="text-sm text-muted-foreground">Согласование для этого вида не запускается.</p>}
      </section>

      <section className="space-y-3" aria-labelledby="kind-auto-heading">
        <h3 id="kind-auto-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Автоматизация</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Дело по умолчанию" id="kind-case"><select id="kind-case" value={draft.default_case_id ?? ''} onChange={(event) => setDraft({ ...draft, default_case_id: event.target.value || null })} className={SELECT_CLASS}><option value="">не выбрано</option>{(casesQ.data ?? []).filter((item) => item.status === 'open' || item.id === draft.default_case_id).map((item) => <option key={item.id} value={item.id}>{item.year} · {item.index} · {item.title}</option>)}</select></Field>
          <Field label="Тип поручения по документу" id="kind-errand"><select id="kind-errand" value={draft.errand_type_id ?? ''} onChange={(event) => setDraft({ ...draft, errand_type_id: event.target.value || null })} className={SELECT_CLASS}><option value="">обычное поручение</option>{(subjectsQ.data?.task_types ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
        </div>
      </section>

      <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
        <Button type="button" variant="outline" onClick={onClose}>Отмена</Button>
        <Button type="button" disabled={!ready || save.isPending} onClick={() => save.mutate()}>
          <Save className="mr-1.5 h-4 w-4" />{save.isPending ? 'Сохраняем…' : 'Сохранить вид'}
        </Button>
      </div>
    </Card>
  )
}

function ConditionRow({ when, index, fields, onChange }: {
  when: DraftCondition | null
  index: number
  fields: DocKindField[]
  onChange: (when: DraftCondition | null) => void
}) {
  const kindFields = fields.filter((field) => fieldCode(field.code) && field.label.trim())
  return (
    <div className="space-y-1.5">
      <div className="grid gap-2 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1.5fr)]">
        <select aria-label={`Условие шага ${index + 1}`} value={when?.field ?? ''} className={SELECT_CLASS}
          onChange={(event) => onChange(event.target.value
            ? { field: event.target.value, op: when?.op ?? 'eq', value: when?.value ?? '' }
            : null)}>
          <option value="">условие: выполняется всегда</option>
          <optgroup label="Свойства карточки">
            {CONDITION_CARD_FIELDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </optgroup>
          {kindFields.length > 0 && (
            <optgroup label="Реквизиты вида">
              {kindFields.map((field) => (
                <option key={field.code} value={fieldCode(field.code)}>{field.label}</option>
              ))}
            </optgroup>
          )}
          {/* Реквизит из условия удалили из схемы: показываем код, а не пустой селект. */}
          {when && !CONDITION_CARD_FIELDS.some(([code]) => code === when.field)
            && !kindFields.some((field) => fieldCode(field.code) === when.field) && (
            <option value={when.field}>{when.field} — реквизита нет в схеме</option>
          )}
        </select>
        {when && (
          <select aria-label={`Сравнение в условии шага ${index + 1}`} value={when.op} className={SELECT_CLASS}
            onChange={(event) => onChange({ ...when, op: event.target.value as ConditionOp })}>
            {CONDITION_OPS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        )}
        {when && hasConditionValue(when.op) && (
          <Input aria-label={`Значение условия шага ${index + 1}`} value={when.value}
            placeholder={conditionPlaceholder(when, fields)}
            onChange={(event) => onChange({ ...when, value: event.target.value })} />
        )}
      </div>
      {when && hasConditionValue(when.op) && !when.value.trim() && (
        <p role="alert" className="text-xs text-destructive">Укажите значение — иначе условие потеряется и шаг станет безусловным.</p>
      )}
      {when && <p className="text-xs text-muted-foreground">Шаг попадёт в круг согласования, только если условие выполнено.</p>}
    </div>
  )
}

function Field({ label, id, className = '', children }: {
  label: string
  id: string
  className?: string
  children: ReactNode
}) {
  return <div className={`space-y-1.5 ${className}`}><Label htmlFor={id}>{label}</Label>{children}</div>
}
