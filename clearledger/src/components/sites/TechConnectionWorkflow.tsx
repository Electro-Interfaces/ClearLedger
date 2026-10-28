import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Plus, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { get, post, put, upload } from '@/services/apiClient'
import { openAuthAttachment } from '@/lib/authFiles'
import type { TechConnection } from '@/services/sitesService'
import { uploadSiteDoc } from '@/services/sitesService'

type Person = { id: string; name: string }
type Responsibility = { executor?: string | null; controller?: string | null; provider?: string | null; due?: string | null }
type Remark = { id: string; branch: 'application' | 'inspection' | 'supply'; text: string; received: string; due: string | null; resolved: string | null; response: string }
type Stage = { id: string; title: string; contractor: string; due: string | null; done: string | null; notified: string | null; accepted: string | null; executor: string | null; note: string }
type Workflow = {
  process_enabled: boolean; emergency_automation: boolean; design_required: boolean
  scenario: 'new' | 'increase' | 'redistribution'; organization_id: string | null
  supply_mode: 'landlord' | 'direct' | 'via_grid' | 'existing'; supply_contract_id: string | null
  representative: boolean; apartment_building: boolean; personal_data_consent: 'pending' | 'portal' | 'file'
  design_date: string | null; commissioning_date: string | null
  responsibilities: Record<string, Responsibility>; remarks: Remark[]; stages: Stage[]
  reviewed_kinds: string[]; review_note: string; additional_requirements: string[]; archived: boolean
}
type State = {
  autoStartNew: boolean; autoStartedNew: boolean
  profile: { totalKw: number | null; voltageKv: number | null; band: string; applicationForm: string; sourceUrl: string }
  prefill: { field: string; value: unknown; source: string }[]
  process: { items?: Record<string, { id: string; state: string; stage: { name: string }; performer?: { name: string } | null }>; at?: string; error?: string }
  handover: { exists: boolean; docId?: string; done: boolean; canAcknowledge?: boolean; recipients: { id: string; name: string; status: string; readAt: string | null }[] }
  version: number; evidenceToken: string; data: Workflow; scenarios: Record<string, string>; documentKinds: Record<string, string>
  people: Person[]; organizations: Person[]; contracts: Person[]
  kit: { kind: string; label: string; present: boolean; reviewed: boolean }[]
  supplyKit: { kind: string; label: string; present: boolean; reviewed: boolean }[]
  supplyReady: boolean
  sharedDocuments: { id: string; kind: string; name: string; expired: boolean; validUntil: string | null }[]
  missing: string[]; ready: boolean; finalMissing: string[]
  remarks: (Remark & { deadline: string; overdue: boolean })[]
  notifications: Record<string, { at: string }>
}
const selectClass = 'h-9 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
function Choice({ label, value, options, onChange }: { label: string; value?: string | null; options: Person[]; onChange: (v: string) => void }) {
  return <label className="block min-w-0 space-y-1 text-sm"><span>{label}</span><select aria-label={label} className={selectClass} value={value || ''} onChange={e => onChange(e.target.value)}>
    <option value="">Не выбрано</option>{options.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
  </select></label>
}
function Day({ label, value, onChange }: { label: string; value?: string | null; onChange: (v: string | null) => void }) {
  return <label className="block min-w-0 space-y-1 text-sm"><span>{label}</span><Input type="date" value={value || ''} onChange={e => onChange(e.target.value || null)} /></label>
}
const options = (x: Record<string, string>) => Object.entries(x).map(([id, name]) => ({ id, name }))

/** Предметные условия и доказательства ТП. Изменение стадии остаётся в общем маршруте проекта. */
export function TechConnectionWorkflow({ companyId, siteId, tc, onDone, blocked = false }: {
  companyId: string; siteId: string; tc: TechConnection; blocked?: boolean; onDone: () => Promise<void>
}) {
  const client = useQueryClient()
  const key = ['tp-workflow', companyId, siteId, tc.workflowVersion ?? 0]
  const url = `/api/sites/${siteId}/tech-connection`
  const query = useQuery({ queryKey: key, refetchInterval: 15000, queryFn: () => get<State>(`${url}/workflow`, { company_id: companyId }) })
  const [draft, setDraft] = useState<Workflow | null>(null)
  const [version, setVersion] = useState<number | null>(null)
  const [reviewToken, setReviewToken] = useState<string | null>(null)
  const [sharedKind, setSharedKind] = useState('egrul')
  const [validUntil, setValidUntil] = useState<string | null>(null)
  const data = draft ?? query.data?.data
  const change = (patch: Partial<Workflow>) => {
    if (!data) return
    if (version === null) { setVersion(query.data?.version ?? 0); setReviewToken(query.data?.evidenceToken ?? null) }
    setDraft({ ...data, ...patch })
  }
  const refresh = async () => { await client.invalidateQueries({ queryKey: key }); await onDone() }
  const save = useMutation({
    mutationFn: () => put(`${url}/workflow?company_id=${companyId}`, { version: version ?? query.data?.version, evidence_token: reviewToken ?? query.data?.evidenceToken, data }),
    onSuccess: async () => { setDraft(null); setVersion(null); setReviewToken(null); await refresh(); toast.success('Условия и контроль ТП сохранены') },
    onError: e => toast.error(e instanceof Error ? e.message : 'Не удалось сохранить'),
  })
  const fileMutation = useMutation({
    mutationFn: async ({ file, kind, shared }: { file: File; kind: string; shared: boolean }) => {
      if (shared) {
        const fd = new FormData(); fd.append('file', file)
        const qs = new URLSearchParams({ company_id: companyId, organization_id: data!.organization_id!, kind })
        if (validUntil) qs.set('valid_until', validUntil)
        return upload(`${url}/shared-documents?${qs}`, fd)
      }
      return uploadSiteDoc(companyId, siteId, file, kind, file.name)
    },
    onSuccess: async () => { await refresh(); toast.success('Документ загружен') },
    onError: e => toast.error(e instanceof Error ? e.message : 'Не удалось загрузить документ'),
  })
  const fillSource = useMutation({
    mutationFn: () => post<{ applied: unknown[] }>(`${url}/prefill?company_id=${companyId}`, {}),
    onSuccess: async result => { await refresh(); toast.success(result.applied.length ? 'Доступные исходные сведения подставлены' : 'Новых сведений для подстановки нет') },
    onError: e => toast.error(e instanceof Error ? e.message : 'Не удалось подставить сведения'),
  })
  const acknowledge = useMutation({
    mutationFn: () => post(`${url}/acquaint?company_id=${companyId}`, {}),
    onSuccess: async () => { await refresh(); toast.success('Ваше ознакомление подтверждено') },
    onError: e => toast.error(e instanceof Error ? e.message : 'Не удалось подтвердить ознакомление'),
  })
  if (blocked) return <p role="status" className="text-sm text-muted-foreground">Сохраните основные параметры присоединения выше, чтобы продолжить работу с условиями, ответственными и документами.</p>
  if (query.isError) return <div role="alert" className="rounded-lg border p-3 text-sm">Не удалось загрузить условия ТП. <Button variant="outline" onClick={() => void query.refetch()}>Повторить</Button></div>
  if (!query.data || !data) return <div className="h-24 animate-pulse rounded-lg bg-muted" aria-label="Загружаются условия ТП" />
  const state = query.data
  const hasAutomaticRoute = ['direct', 'indirect'].includes(tc.method ?? '') || ['direct', 'via_grid'].includes(data.supply_mode)
  const noRouteHelp = !tc.method
    ? 'Сначала выберите способ подключения выше. Система запустит применимый маршрут после заполнения условий и назначения участников.'
    : 'При оплате электроэнергии арендодателю или по уже заключённому договору отдельный процесс ТП не запускается.'
  const responsibility = (key: string, patch: Responsibility) => change({ responsibilities: { ...data.responsibilities, [key]: { ...data.responsibilities[key], ...patch } } })
  const remark = (id: string, patch: Partial<Remark>) => change({ remarks: data.remarks.map(x => x.id === id ? { ...x, ...patch } : x) })
  const stage = (id: string, patch: Partial<Stage>) => change({ stages: data.stages.map(x => x.id === id ? { ...x, ...patch } : x) })
  const filePicker = (kind: string, shared = false) => <label className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-sm ${draft || fileMutation.isPending ? 'opacity-50' : 'cursor-pointer hover:bg-muted'}`}>
    <Upload className="h-4 w-4" /> Загрузить{shared ? ' PDF' : ''}
    <input type="file" className="sr-only" aria-label={`Загрузить ${state.documentKinds[kind] || kind}${shared ? ' для всех проектов заявителя' : ''}`}
      accept={shared ? '.pdf' : undefined} disabled={!!draft || fileMutation.isPending || (shared && !data.organization_id)}
      onChange={e => { const f = e.target.files?.[0]; if (f) fileMutation.mutate({ file: f, kind, shared }); e.target.value = '' }} />
  </label>
  return <section className="space-y-4 rounded-lg border border-border p-3" aria-label="Условия и контроль техприсоединения">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Условия и контроль техприсоединения</h3>
      <div className="flex gap-2"><Button variant="outline" disabled={!draft || save.isPending} onClick={() => { setDraft(null); setVersion(null); setReviewToken(null) }}>Отменить</Button>
        <Button disabled={!draft || save.isPending} onClick={() => save.mutate()}>{save.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}Сохранить условия</Button></div>
    </div>
    {draft && <p role="status" className="text-sm text-muted-foreground">Есть несохранённые изменения. Сохраните их перед загрузкой документов; комплект ниже соответствует сохранённым условиям.</p>}
    <div className="flex flex-col gap-2 border-b pb-3">
      {state.autoStartNew ? <p role="status" className="text-sm text-muted-foreground">
        {hasAutomaticRoute
          ? 'Система запустит маршрут автоматически после сохранения заявителя и назначения поставщика данных, исполнителя и контролирующего.'
          : noRouteHelp}
      </p> : state.autoStartedNew
        ? <p role="status" className="text-sm text-muted-foreground">Передача работы запущена автоматически. Состояние обновляется по регламенту, заявку в сетевую отправляет исполнитель.</p>
        : <>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={data.process_enabled} onChange={e => change({ process_enabled: e.target.checked })} />Запустить автоматическую передачу работы</label>
          <p className="text-sm text-muted-foreground">На старых карточках процесс не запускается сам, чтобы не передавать уже ведущиеся заявки без проверки. После сохранения служба процессов передаст работу назначенным участникам; отправку заявлений в сетевую отмечает исполнитель.</p>
        </>}
      {state.process.error && <p role="alert" className="text-sm text-destructive">Передача работы ожидает исправления: {state.process.error}</p>}
      {Object.entries(state.process.items || {}).map(([key, item]) => <div key={key} className="text-sm"><strong>{key === 'tp_supply' ? 'Договор со сбытом' : 'Техприсоединение'}:</strong> {item.stage?.name || 'Запуск'} · {item.performer?.name || (item.state === 'done' ? 'завершено' : 'назначение в очереди')}</div>)}
      {state.process.at && <p className="text-xs text-muted-foreground">Состояние на {new Date(state.process.at).toLocaleString('ru-RU')}</p>}
      <p className="text-sm">Профиль комплекта: {state.profile.band}, {state.profile.voltageKv} кВ. Суммарная мощность: {state.profile.totalKw == null ? 'не указана' : `${state.profile.totalKw} кВт`}.</p>
      {state.profile.applicationForm === 'operator' && <a className="text-sm text-primary underline" href={state.profile.sourceUrl} target="_blank" rel="noreferrer">Выбрать форму заявки сетевой организации для этой мощности</a>}
      <Button variant="outline" disabled={!!draft || fillSource.isPending || data.archived} onClick={() => fillSource.mutate()}>Подставить незаполненное из паспорта и договора</Button>
      {state.prefill.length > 0 && <ul className="list-disc pl-5 text-sm">{state.prefill.map(x => <li key={x.field}>{x.source}: {String(x.value)}</li>)}</ul>}
    </div>
    <div className="grid gap-3 md:grid-cols-3">
      <Choice label="Сценарий" value={data.scenario} options={options(state.scenarios)} onChange={v => v && change({ scenario: v as Workflow['scenario'] })} />
      <Choice label="Заявитель" value={data.organization_id} options={state.organizations} onChange={v => change({ organization_id: v || null, reviewed_kinds: [] })} />
      <Choice label="Договор со сбытом" value={data.supply_mode} options={options({ landlord: 'Оплата арендодателю', direct: 'Прямой договор со сбытом', via_grid: 'Через сетевую организацию', existing: 'Уже заключён' })} onChange={v => v && change({ supply_mode: v as Workflow['supply_mode'] })} />
      {data.supply_mode !== 'landlord' && <Choice label="Договор из общего реестра" value={data.supply_contract_id} options={state.contracts} onChange={v => change({ supply_contract_id: v || null })} />}
      <Day label="Срок проектирования" value={data.design_date} onChange={v => change({ design_date: v })} />
      <Day label="Срок ввода" value={data.commissioning_date} onChange={v => change({ commissioning_date: v })} />
      <Choice label="Согласие на обработку данных" value={data.personal_data_consent} options={options({ pending: 'Не подтверждено', portal: 'Подтверждено в личном кабинете сетевой', file: 'Отдельный документ' })} onChange={v => v && change({ personal_data_consent: v as Workflow['personal_data_consent'] })} />
    </div>
    <div className="flex flex-wrap gap-4 text-sm">{([['representative', 'Заявку подаёт представитель'], ['apartment_building', 'Помещение в многоквартирном доме'], ['emergency_automation', 'Есть устройства противоаварийной автоматики'], ['design_required', 'Требуется проектная документация']] as const).map(([k, label]) => <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={data[k]} onChange={e => change({ [k]: e.target.checked })} />{label}</label>)}</div>
    <details><summary className="cursor-pointer text-sm font-medium">Дополнительные требования сетевой организации</summary>
      <div className="mt-2 grid gap-2 md:grid-cols-2">{Object.entries(state.documentKinds).map(([kind, label]) => <label key={kind} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={data.additional_requirements.includes(kind)} onChange={e => change({ additional_requirements: e.target.checked ? [...data.additional_requirements, kind] : data.additional_requirements.filter(x => x !== kind) })} />{label}</label>)}</div>
    </details>
    <div className="space-y-2 border-t pt-3"><h4 className="text-sm font-semibold">Ответственность</h4><p className="text-sm text-muted-foreground">Общие назначения действуют на все шаги. Для отдельного шага можно указать других людей и срок.</p>
      {['default', ...(tc.steps || []).map(x => x.key)].map(k => <details key={k} open={k === 'default' ? true : undefined}><summary className="cursor-pointer py-1 text-sm">{k === 'default' ? 'По всему присоединению' : tc.steps?.find(x => x.key === k)?.label}</summary>
        <div className="grid gap-2 py-2 md:grid-cols-4">{(['executor', 'controller', 'provider'] as const).map((role, i) => <Choice key={role} label={['Исполнитель', 'Контролирующий', 'Поставщик данных'][i]} value={data.responsibilities[k]?.[role]} options={state.people} onChange={v => responsibility(k, { [role]: v || null })} />)}
          <Day label="Плановый срок" value={data.responsibilities[k]?.due} onChange={v => responsibility(k, { due: v })} /></div>
      </details>)}
    </div>
    <div className="space-y-2 border-t pt-3"><h4 className="text-sm font-semibold">Комплект заявки и проверка содержания</h4>
      {state.kit.length === 0 && <p className="text-sm text-muted-foreground">Для выбранного способа заявка на ТП не требуется.</p>}
      {state.kit.map(d => <div key={d.kind} className="flex flex-wrap items-center gap-2 text-sm">
        <span className="min-w-0 flex-1 basis-64">{d.label} · {d.present ? 'приложен' : 'не приложен'}</span>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!d.present} checked={data.reviewed_kinds.includes(d.kind)} onChange={e => change({ reviewed_kinds: e.target.checked ? [...data.reviewed_kinds, d.kind] : data.reviewed_kinds.filter(x => x !== d.kind) })} />Содержание проверено</label>{filePicker(d.kind)}
      </div>)}
      {state.ready ? <p role="status" className="flex items-center gap-1 text-sm"><Check className="h-4 w-4" />Комплект готов. Исполнитель получит уведомление при ближайшей проверке регламента.</p>
        : state.missing.length > 0 && <p className="text-sm text-muted-foreground">Не хватает: {state.missing.join('; ')}.</p>}
      <label className="block space-y-1 text-sm">Комментарий к проверке<Input value={data.review_note} onChange={e => change({ review_note: e.target.value })} /></label>
    </div>
    {state.supplyKit.length > 0 && <div className="flex flex-col gap-2 border-t pt-3"><h4 className="text-sm font-semibold">Комплект для договора со сбытом</h4>
      {state.supplyKit.map(d => <div key={d.kind} className="flex flex-wrap items-center gap-2 text-sm">
        <span className="min-w-0 flex-1 basis-64">{d.label} · {d.present ? 'приложен' : 'не приложен'}</span>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!d.present} checked={data.reviewed_kinds.includes(d.kind)} onChange={e => change({ reviewed_kinds: e.target.checked ? [...new Set([...data.reviewed_kinds, d.kind])] : data.reviewed_kinds.filter(x => x !== d.kind) })} />Проверено для сбыта</label>{filePicker(d.kind)}
      </div>)}
      <p className="text-sm text-muted-foreground">{state.supplyReady ? 'Комплект для сбыта готов к подаче.' : 'После загрузки проверьте содержание документов.'}</p>
    </div>}
    <details className="border-t pt-3"><summary className="cursor-pointer text-sm font-semibold">Общие документы заявителя</summary>
      <p className="my-2 text-sm text-muted-foreground">Администратор загружает один PDF для всех проектов выбранного юрлица. Версии с истёкшим сроком в комплект не засчитываются.</p>
      <div className="grid items-end gap-2 md:grid-cols-3"><Choice label="Вид общего документа" value={sharedKind} options={options({ egrul: 'ЕГРЮЛ', poa: 'Доверенность', tp_consent: 'Согласие на обработку данных', counterparty_card: 'Карточка организации' })} onChange={v => v && setSharedKind(v)} />
        <Day label="Действителен до (если ограничен)" value={validUntil} onChange={setValidUntil} /><div>{filePicker(sharedKind, true)}</div></div>
      {state.sharedDocuments.map(d => <div key={d.id} className="mt-2 flex flex-wrap gap-2 text-sm"><Button variant="link" className="h-auto whitespace-normal p-0 text-left" onClick={() => void openAuthAttachment(`${url}/shared-documents/${d.id}/file?company_id=${companyId}`).catch(e => toast.error(e.message))}>{d.name}</Button><span>{d.expired ? 'Срок истёк' : 'Действует'}{d.validUntil ? ` до ${d.validUntil}` : ''}</span></div>)}
    </details>
    <div className="space-y-3 border-t pt-3"><h4 className="text-sm font-semibold">Замечания сетевой и сбыта</h4>
      {data.remarks.map((r, index) => <fieldset key={r.id} className="space-y-2 border-b pb-3"><legend className="text-sm">Замечание {index + 1}</legend>
        <div className="grid gap-2 md:grid-cols-3"><Choice label="К чему замечание" value={r.branch} options={options({ application: 'Комплект заявки', inspection: 'Приёмка ТУ', supply: 'Договор со сбытом' })} onChange={v => v && remark(r.id, { branch: v as Remark['branch'] })} />
          <Day label="Получено" value={r.received} onChange={v => remark(r.id, { received: v || '' })} /><Day label="Ответить до" value={r.due} onChange={v => remark(r.id, { due: v })} /></div>
        <label className="block text-sm">Содержание<Input value={r.text} onChange={e => remark(r.id, { text: e.target.value })} /></label>
        <label className="block text-sm">Ответ / устранение<Input value={r.response} onChange={e => remark(r.id, { response: e.target.value })} /></label>
        <div className="flex flex-wrap items-end gap-2"><Day label="Замечание снято" value={r.resolved} onChange={v => remark(r.id, { resolved: v })} />
          <Button variant="outline" aria-label={`Удалить замечание ${index + 1}`} onClick={() => change({ remarks: data.remarks.filter(x => x.id !== r.id) })}><Trash2 className="h-4 w-4" /></Button></div>
        {state.remarks.find(x => x.id === r.id)?.overdue && <p className="text-sm text-destructive">Срок ответа истёк</p>}
      </fieldset>)}
      <Button variant="outline" onClick={() => change({ remarks: [...data.remarks, { id: crypto.randomUUID(), branch: 'application', text: '', received: new Date().toLocaleDateString('en-CA'), due: null, resolved: null, response: '' }] })}><Plus className="mr-1 h-4 w-4" />Добавить замечание</Button>
      <p className="text-xs text-muted-foreground">Для досылки документов используется 20 календарных дней из схемы энергетика. Явно указанный срок ответа имеет приоритет.</p>
    </div>
    <div className="space-y-3 border-t pt-3"><h4 className="text-sm font-semibold">Этапы выполнения технических условий</h4>
      {data.stages.map((x, i) => <fieldset key={x.id} className="space-y-2 border-b pb-3"><legend className="text-sm">Этап {i + 1}</legend>
        <label className="block text-sm">Работы<Input value={x.title} onChange={e => stage(x.id, { title: e.target.value })} /></label>
        <div className="grid gap-2 md:grid-cols-3"><label className="block text-sm">Подрядчик / договор<Input value={x.contractor} onChange={e => stage(x.id, { contractor: e.target.value })} /></label>
          <Choice label="Исполнитель этапа" value={x.executor} options={state.people} onChange={v => stage(x.id, { executor: v || null })} /><Day label="Выполнить до" value={x.due} onChange={v => stage(x.id, { due: v })} />
          <Day label="Выполнено" value={x.done} onChange={v => stage(x.id, { done: v })} /><Day label="Сетевая уведомлена" value={x.notified} onChange={v => stage(x.id, { notified: v })} /><Day label="Принято сетевой" value={x.accepted} onChange={v => stage(x.id, { accepted: v })} /></div>
        <label className="block text-sm">Условия / результат<Input value={x.note} onChange={e => stage(x.id, { note: e.target.value })} /></label>
        <Button variant="outline" onClick={() => change({ stages: data.stages.filter(y => y.id !== x.id) })}>Удалить этап</Button>
      </fieldset>)}
      <Button variant="outline" onClick={() => change({ stages: [...data.stages, { id: crypto.randomUUID(), title: '', contractor: '', due: null, done: null, notified: null, accepted: null, executor: null, note: '' }] })}><Plus className="mr-1 h-4 w-4" />Добавить этап ТУ</Button>
    </div>
    <div className="space-y-2 border-t pt-3"><h4 className="text-sm font-semibold">Закрытие и передача документов</h4>
      {state.finalMissing.length > 0 && <p className="text-sm text-muted-foreground">Для закрытия нужны: {state.finalMissing.join('; ')}.</p>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={data.archived} onChange={e => change({ archived: e.target.checked })} />Завершить ТП, закрепить комплект и уведомить контролирующих</label>
      <p className="text-xs text-muted-foreground">Документы остаются в проекте, связанном с объектом. Уведомления отправляются внутри пространства с учётом его политики доставки.</p>
      {state.handover.exists && <div className="flex flex-col gap-2">
        <a className="text-sm text-primary underline" href={`/docs/work?doc=${state.handover.docId}`}>Открыть итоговый комплект и лист ознакомления</a>
        {state.handover.recipients.map(x => <p className="text-sm" key={x.id}>{x.name}: {x.status === 'done' ? `ознакомлен ${x.readAt ? new Date(x.readAt).toLocaleString('ru-RU') : ''}` : 'ожидается ознакомление'}</p>)}
        {state.handover.canAcknowledge && <Button variant="outline" disabled={acknowledge.isPending} onClick={() => acknowledge.mutate()}>Подтверждаю ознакомление с итоговым комплектом</Button>}
      </div>}
      <p className="text-sm">Подтверждено уведомлений: {Object.keys(state.notifications).length}</p>
    </div>
  </section>
}
