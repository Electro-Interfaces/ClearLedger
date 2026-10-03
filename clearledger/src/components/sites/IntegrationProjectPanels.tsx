import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { StationScopePicker } from '@/components/workspace/StationScopePicker'
import { getContracts, getCounterparties } from '@/services/referenceService'
import { getProjectCase, openProjectCase, getSiteDocs, downloadSiteDoc, uploadSiteDoc, waiveSiteGate, type SiteDetail, type GateItem } from '@/services/sitesService'
import {
  getIntegration, getIntegrationStations, saveIntegration, confirmIntegration,
  INTEGRATION_DIRECTIONS, INTEGRATION_FORMATS,
  type IntegrationData, type IntegrationSection, type IntegrationScenario,
  type IntegrationDocument, type IntegrationStation, type IntegrationTask, type IntegrationResult,
} from '@/services/projectIntegrationService'
import { ProjectEvidencePicker } from './ProjectEvidencePicker'
import { ProjectDocumentsTrack } from './ProjectDocumentsTrack'

type Props = { site: SiteDetail; companyId: string; onDone: () => Promise<void> }
const selectClass = 'h-10 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const GROUPS: Record<IntegrationSection, { title: string; fields: [string, string][] }> = {
  partner: { title: 'Партнёр и цель', fields: [['name', 'Партнёр'], ['legalEntity', 'Юридическое лицо, ИНН и подписант'], ['purpose', 'Цель интеграции'], ['commercialContact', 'Коммерческий контакт'], ['assessment', 'Масштаб партнёра и пересечение регионов']] },
  commercial: { title: 'Коммерческие условия', fields: [['commission', 'Комиссия / фиксированная плата'], ['calculationBase', 'База расчёта'], ['acquiring', 'Эквайринг'], ['tariffs', 'Правила тарифов'], ['discounts', 'Правила скидок'], ['discountFunding', 'Источник финансирования скидок'], ['settlements', 'Взаиморасчёты и разрешение расхождений'], ['reporting', 'Отчётность']] },
  data: { title: 'Данные, аналитика и бренд', fields: [['outgoing', 'Что передаём'], ['incoming', 'Что получаем'], ['statisticsUse', 'Ограничения использования статистики'], ['sessionHistory', 'История сессий'], ['analytics', 'Аналитика'], ['brand', 'Бренд и отображение'], ['appTransitions', 'Переходы в приложение']] },
  technical: { title: 'Технические параметры и сопровождение', fields: [['systems', 'Системы сторон'], ['protocol', 'Протокол / API'], ['version', 'Версия протокола / API'], ['contacts', 'Технические контакты сторон'], ['responsibilities', 'Распределение ответственности'], ['support', 'Поддержка и прекращение интеграции'], ['access', 'Доступы'], ['security', 'Требования безопасности'], ['acceptanceCriteria', 'Программа тестирования и критерии приёмки']] },
  work: { title: 'Пилот и проверки', fields: [['pilotDecision', 'Решение о пилоте'], ['pilotOutcome', 'Итог пилота'], ['testResults', 'Результаты проверок'], ['launchDate', 'Дата коммерческого запуска']] },
  accounting: { title: 'Связь с контрагентом', fields: [] },
}
const DOC_KINDS: Record<string, string> = { nda: 'NDA', pilot: 'Пилотное соглашение', contract: 'Договор и приложения', stations: 'Перечень ЭЗС', specification: 'Техническое задание', test_program: 'Программа тестирования', test_protocol: 'Протокол тестирования', instruction: 'Инструкция', other: 'Другой документ' }

function useIntegration(props: Props) {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['project-integration', props.companyId, props.site.id], queryFn: () => getIntegration(props.companyId, props.site.id), refetchOnWindowFocus: false })
  const refresh = async () => {
    try {
      const state = await getProjectCase(props.companyId, props.site.id)
      if (state.exists && !state.readonly) await openProjectCase(props.companyId, props.site.id)
    } catch (e) {
      toast.warning(`Данные сохранены, но условия маршрута не обновились: ${e instanceof Error ? e.message : 'повторите обновление маршрута'}`)
    }
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['project-integration', props.companyId, props.site.id] }),
      qc.invalidateQueries({ queryKey: ['site-case', props.companyId, props.site.id] }),
      props.onDone(),
    ])
  }
  return { query, refresh }
}

function QueryStatus({ query }: { query: ReturnType<typeof useIntegration>['query'] }) {
  if (query.isError) return <div role="alert" className="space-y-2"><p>Не удалось загрузить интеграцию: {query.error.message}</p><Button variant="outline" onClick={() => void query.refetch()}>Повторить</Button></div>
  return <p role="status" className="text-sm text-muted-foreground">Загрузка интеграции…</p>
}

function SectionEditor({ section, data, props, onSaved }: { section: IntegrationSection; data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(data[section])
  const [busy, setBusy] = useState(false)
  const group = GROUPS[section]
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, [section]: draft }); await onSaved(); toast.success('Данные сохранены. Согласование подтверждается отдельно') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3">
    <h3 className="font-semibold text-sm">{group.title}</h3>
    <div className="grid gap-3 sm:grid-cols-2">{group.fields.map(([key, label]) => <label key={key} className="block space-y-1 text-sm">{label}
      {key === 'launchDate' ? <Input type="date" value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
        : <Textarea rows={2} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />}
    </label>)}</div>
    <Button disabled={busy} onClick={() => void save()}>Сохранить раздел</Button>
  </section>
}

function StationListPicker({ scenario, stations, field, value, onChange }: {
  scenario: IntegrationScenario; stations: IntegrationStation[]; field: 'selectedIds' | 'agreedIds' | 'connectedIds' | 'pilotIds'; value: string[]; onChange: (ids: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const [regions, setRegions] = useState<string[]>([])
  const [group, setGroup] = useState('')
  const titles = { selectedIds: 'Выбрано', agreedIds: 'Согласовано', connectedIds: 'Фактически подключено', pilotIds: 'Пилотный перечень' }
  const available = useMemo(() => stations.filter((s) => s.network === scenario.direction)
    .filter((s) => field === 'selectedIds' || (field === 'connectedIds' ? scenario.agreedIds : scenario.selectedIds).includes(s.id)), [stations, scenario, field])
  const groups = [...new Set(available.map((s) => s.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru'))
  const filtered = useMemo(() => available.filter((s) => !group || s.group === group)
    .map((s) => ({ ...s, code: s.id, displayCode: s.code, name: `${s.name} · ${s.code}` })), [available, group])
  const exportList = () => {
    const rows = [['ID', 'Код', 'Станция', 'Регион', 'Город'], ...value.map((id) => {
      const s = stations.find((item) => item.id === id)
      return [id, s?.code || '', s?.name || 'Нет в текущем справочнике', s?.region || '', s?.city || '']
    })]
    const csv = '\uFEFF' + rows.map((r) => r.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(';')).join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = `integration-${scenario.id}-${field}.csv`; link.click(); URL.revokeObjectURL(url)
  }
  return <div className="space-y-2">
    <div className="flex flex-wrap gap-2 items-center"><Button className="max-w-full h-auto min-h-11 whitespace-normal text-left" variant="outline" onClick={() => { setDraft(value); setOpen(true) }}>{titles[field]}: {value.length} · просмотр и выбор</Button>
      <Button variant="ghost" disabled={!value.length} onClick={exportList}>Выгрузить перечень</Button></div>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="sm:max-w-5xl w-[96vw] max-h-[92dvh] overflow-y-auto"><DialogHeader><DialogTitle>{titles[field]} · {scenario.name || INTEGRATION_DIRECTIONS[scenario.direction]}</DialogTitle></DialogHeader>
      <p className="text-xs text-muted-foreground">Фильтр действует только здесь. Отметки сохраняются при смене условий. Сохранение перечня не подключает станции.</p>
      <label className="text-sm">Группа / сеть<select aria-label="Группа / сеть" className={selectClass} value={group} onChange={(e) => setGroup(e.target.value)}><option value="">Все группы</option>{groups.map((g) => <option key={g}>{g}</option>)}</select></label>
      <div className="min-h-0 h-[min(58dvh,620px)] flex flex-col"><StationScopePicker stations={filtered} selected={draft} onChange={setDraft} regionIds={regions} onRegionsChange={setRegions} explicitSelection persistFacets={false} groupRegions showSessionStats={false} /></div>
      <p className="text-xs text-muted-foreground">За пределами текущего списка также сохранено: {draft.filter((id) => !filtered.some((s) => s.id === id)).length}</p>
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button><Button onClick={() => { onChange(draft); setOpen(false) }}>Применить выбор ({draft.length})</Button></div>
    </DialogContent></Dialog>
  </div>
}

function ScenariosEditor({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState(data.scenarios)
  const [busy, setBusy] = useState(false)
  const catalog = useQuery({ queryKey: ['integration-stations', props.companyId, props.site.id], queryFn: () => getIntegrationStations(props.companyId, props.site.id) })
  const change = (id: string, patch: Partial<IntegrationScenario>) => setRows(rows.map((s) => s.id === id ? { ...s, ...patch } : s))
  const changeList = (row: IntegrationScenario, field: 'selectedIds' | 'agreedIds' | 'connectedIds' | 'pilotIds', ids: string[]) => {
    if (field === 'selectedIds') change(row.id, { selectedIds: ids, agreedIds: row.agreedIds.filter((id) => ids.includes(id)), connectedIds: row.connectedIds.filter((id) => ids.includes(id)), pilotIds: row.pilotIds.filter((id) => ids.includes(id)) })
    else if (field === 'agreedIds') change(row.id, { agreedIds: ids, connectedIds: row.connectedIds.filter((id) => ids.includes(id)) })
    else change(row.id, { [field]: ids })
  }
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, scenarios: rows }); await onSaved(); toast.success('Фиксированный состав перечней сохранён') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить перечни') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="text-sm font-semibold">Сценарии подключения и перечни ЭЗС</h3>
    <p className="text-xs text-muted-foreground">Для гибридной или двусторонней интеграции заведите отдельные сценарии по каждому формату и направлению. Новые станции автоматически в перечни не добавляются.</p>
    {catalog.isError && <div role="alert">Перечень станций не загрузился: {catalog.error.message}<Button variant="outline" onClick={() => void catalog.refetch()}>Повторить</Button></div>}
    {rows.map((s) => <div key={s.id} className="rounded-md border p-3 space-y-3">
      <label className="block text-sm">Название сценария<Input value={s.name} onChange={(e) => change(s.id, { name: e.target.value })} /></label>
      <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Направление<select className={selectClass} value={s.direction} onChange={(e) => change(s.id, { direction: e.target.value as IntegrationScenario['direction'], selectedIds: [], agreedIds: [], connectedIds: [], pilotIds: [] })}>{(['outgoing', 'incoming'] as const).map((v) => <option key={v} value={v}>{INTEGRATION_DIRECTIONS[v]}</option>)}</select></label>
        <label className="text-sm">Формат<select className={selectClass} value={s.format} onChange={(e) => change(s.id, { format: e.target.value as IntegrationScenario['format'] })}>{(['information', 'roaming'] as const).map((v) => <option key={v} value={v}>{INTEGRATION_FORMATS[v]}</option>)}</select></label>
        <label className="text-sm">География<Input value={s.geography} onChange={(e) => change(s.id, { geography: e.target.value })} /></label>
        <label className="text-sm">Ограничения<Input value={s.restrictions} onChange={(e) => change(s.id, { restrictions: e.target.value })} /></label></div>
      {catalog.isPending ? <p role="status">Загрузка станций…</p> : (['selectedIds', 'agreedIds', 'connectedIds', 'pilotIds'] as const).map((field) => <StationListPicker key={field} scenario={s} field={field} stations={catalog.data || []} value={s[field]} onChange={(ids) => changeList(s, field, ids)} />)}
      <Button variant="ghost" onClick={() => setRows(rows.filter((r) => r.id !== s.id))}>Удалить сценарий</Button>
    </div>)}
    <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => setRows([...rows, { id: crypto.randomUUID(), name: '', direction: 'outgoing', format: 'information', geography: '', restrictions: '', partnerNetwork: '', selectedIds: [], agreedIds: [], connectedIds: [], pilotIds: [] }])}>Добавить сценарий</Button>
      <Button disabled={busy} onClick={() => void save()}>Сохранить сценарии и перечни</Button></div>
  </section>
}

export function IntegrationPassport(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  const data = query.data.data
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">Поля заполняются по этапам. Заполнение паспорта не подтверждает согласование.</p>
    <SectionEditor key={`partner:${data.revision}`} section="partner" data={data} props={props} onSaved={refresh} />
    <ScenariosEditor key={`scenarios:${data.revision}`} data={data} props={props} onSaved={refresh} />
    {(['commercial', 'data', 'technical'] as const).map((section) => <SectionEditor key={`${section}:${data.revision}`} section={section} data={data} props={props} onSaved={refresh} />)}
    <p className="text-sm">Руководитель: {props.site.ownerName || 'не назначен'}. Руководитель и внутренняя команда назначаются во вкладке «Работа».</p>
  </div>
}

export function IntegrationWorkPlan(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  return <div className="space-y-4"><SectionEditor key={query.data.data.revision} section="work" data={query.data.data} props={props} onSaved={refresh} />
    <PhaseDates key={`dates:${query.data.data.revision}`} props={props} state={query.data} onSaved={refresh} /></div>
}

function PhaseDates({ props, state, onSaved }: { props: Props; state: NonNullable<ReturnType<typeof useIntegration>['query']['data']>; onSaved: () => Promise<void> }) {
  const [dates, setDates] = useState(state.data.dates)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: state.data.revision, dates }); await onSaved(); toast.success('Плановые даты сохранены') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить даты') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="font-semibold text-sm">Плановые даты этапов</h3>
    {state.phases.map((p) => <div key={p.code} className="grid gap-2 sm:grid-cols-3 items-end"><span className="text-sm">{p.label}</span>{(['start', 'end'] as const).map((f) => <label key={f} className="text-xs">{f === 'start' ? 'Начало' : 'Окончание'}<Input aria-label={`${p.label}: ${f === 'start' ? 'начало' : 'окончание'}`} type="date" value={dates[p.code]?.[f] || ''} onChange={(e) => setDates({ ...dates, [p.code]: { ...(dates[p.code] || { start: '', end: '' }), [f]: e.target.value } })} /></label>)}</div>)}
    <Button disabled={busy} onClick={() => void save()}>Сохранить план этапов</Button>
  </section>
}

function ResultEditor({ task, props, data, onSaved }: { task: IntegrationTask; props: Props; data: IntegrationData; onSaved: () => Promise<void> }) {
  const [result, setResult] = useState<IntegrationResult>(data.results[task.key] || { comment: '', workRef: '', docId: '', notApplicable: false })
  const [busy, setBusy] = useState(false)
  const docs = useQuery({ queryKey: ['site-docs', props.companyId, props.site.id], queryFn: () => getSiteDocs(props.companyId, props.site.id) })
  const save = async (confirm: boolean) => {
    setBusy(true)
    try {
      const saved = await saveIntegration(props.companyId, props.site.id, { revision: data.revision, results: { ...data.results, [task.key]: result } })
      if (confirm) await confirmIntegration(props.companyId, props.site.id, task.key, saved.revision)
      await onSaved(); toast.success(confirm ? 'Выполнение подтверждено с автором и датой' : 'Результат сохранён без подтверждения')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить результат') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="text-sm font-semibold">Результат пункта {task.key}</h3>
    <label className="block text-sm">Результат проверки / комментарий / причина неприменимости<Textarea rows={3} value={result.comment} onChange={(e) => setResult({ ...result, comment: e.target.value })} /></label>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={result.notApplicable} onChange={(e) => setResult({ ...result, notApplicable: e.target.checked })} />Не применимо к этому сценарию</label>
    <label className="block text-sm">Документ результата<select aria-label="Документ результата" className={selectClass} value={result.docId} onChange={(e) => setResult({ ...result, docId: e.target.value })}><option value="">Не выбран</option>{(docs.data || []).map((d) => <option key={d.id} value={d.id}>{d.title || d.fileName}</option>)}</select></label>
    {docs.isError && <p role="alert">Документы не загрузились: {docs.error.message}</p>}
    <ProjectEvidencePicker companyId={props.companyId} siteId={props.site.id} value={result.workRef} label="Поручение Трека" onChange={(value) => { if (!value || value.startsWith('task:')) setResult({ ...result, workRef: value }); else toast.warning('Выберите поручение. Файл можно выбрать в поле документа результата') }} />
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void save(false)}>Сохранить результат</Button><Button disabled={busy} onClick={() => void save(true)}>Подтвердить выполнение</Button></div>
  </section>
}

export function IntegrationChecklist(props: Props) {
  const { query, refresh } = useIntegration(props)
  const [editing, setEditing] = useState<IntegrationTask | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [waiving, setWaiving] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  if (!query.data) return <QueryStatus query={query} />
  const { data, tasks, gates } = query.data
  const items = new Map<string, GateItem>(gates.flatMap((g) => g.items).map((i) => [i.key, i]))
  const waive = async (key: string, waived: boolean) => {
    setBusy(true)
    try {
      const res = await waiveSiteGate(props.companyId, props.site.id, key, waived, reason)
      if (res.ok === false) throw new Error(res.message || 'Обязательность не изменена')
      setWaiving(null); setReason(''); await refresh()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось изменить обязательность') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-sm">Чек-лист интеграции · {props.site.gate.stageLabel}</h3><Button variant="outline" size="sm" onClick={() => setShowAll(!showAll)}>{showAll ? 'Текущий этап' : 'Все этапы'}</Button></div>
    {tasks.filter((t) => showAll || t.stage === props.site.stage).map((t) => {
      const item = items.get(t.key)
      return <div key={t.key} className="border-b py-3 space-y-2 last:border-b-0"><div className="flex flex-wrap gap-2 text-sm"><span className="font-mono">{t.key}</span><span className="flex-1 min-w-40">{t.label}</span><span className="text-muted-foreground">{t.role}</span></div>
        <p className={`text-xs ${item?.needsConfirmation ? 'text-amber-600' : item?.done ? 'text-emerald-600' : 'text-muted-foreground'}`}>{item?.needsConfirmation ? 'Требует повторного подтверждения' : item?.done ? 'Подтверждено' : item?.waived ? 'Обязательность снята' : t.required ? 'Обязательный пункт: держит переход' : 'Не подтверждено'}{item?.confirmedBy ? ` · ${item.confirmedBy}` : ''}{item?.confirmedAt ? ` · ${new Date(item.confirmedAt).toLocaleString('ru-RU')}` : ''}</p>
        {data.results[t.key]?.comment && <p className="text-sm whitespace-pre-wrap">{data.results[t.key].comment}</p>}
        <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => setEditing(t)}>Данные и результат</Button>
          {props.site.mayWaive && item?.waivable && !item.done && <Button className="max-w-full h-auto min-h-9 whitespace-normal text-left" variant="ghost" size="sm" disabled={busy} onClick={() => item.waived ? void waive(t.key, false) : setWaiving(t.key)}>{item.waived ? 'Вернуть обязательность' : 'Снять обязательность под свою ответственность'}</Button>}</div>
        {item?.waived && <p className="text-xs text-amber-600">{item.waivedBy} · {item.waiveReason}</p>}
        {waiving === t.key && <div className="space-y-2"><Textarea aria-label="Обоснование снятия обязательности" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Обоснование: под решением будет ваше имя" /><Button disabled={!reason.trim() || busy} onClick={() => void waive(t.key, true)}>Подтвердить снятие обязательности</Button><Button variant="ghost" onClick={() => setWaiving(null)}>Отмена</Button></div>}
      </div>
    })}
    <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}><DialogContent className="sm:max-w-4xl w-[96vw] max-h-[90dvh] overflow-y-auto"><DialogHeader><DialogTitle>{editing?.key} · {editing?.label}</DialogTitle></DialogHeader>
      {editing && <><p className="text-xs text-muted-foreground">Связанные данные сохраняются в паспорте. Их заполнение само по себе не подтверждает пункт.</p>
        {editing.section === 'scenarios' ? <ScenariosEditor key={`scenarios:${data.revision}`} data={data} props={props} onSaved={refresh} />
          : editing.section === 'documents' ? <DocumentsEditor key={`docs:${data.revision}`} data={data} props={props} onSaved={refresh} />
          : <SectionEditor key={`${editing.section}:${data.revision}`} section={editing.section} data={data} props={props} onSaved={refresh} />}
        {editing.key === '2.6' && <PhaseDates key={`dates:${data.revision}`} props={props} state={query.data} onSaved={refresh} />}
        {editing.key === '1.4' && <p className="text-sm">Назначьте руководителя в «Работе»; сейчас: {props.site.ownerName || 'не назначен'}.</p>}
        <ResultEditor key={`${editing.key}:${data.revision}`} task={editing} props={props} data={data} onSaved={refresh} />
      </>}
    </DialogContent></Dialog>
  </section>
}

function DocumentsEditor({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState(data.documents)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const docs = useQuery({ queryKey: ['site-docs', props.companyId, props.site.id], queryFn: () => getSiteDocs(props.companyId, props.site.id) })
  const change = (id: string, patch: Partial<IntegrationDocument>) => setRows(rows.map((d) => d.id === id ? { ...d, ...patch } : d))
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, documents: rows }); await onSaved(); toast.success('Редакции документов сохранены') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить документы') }
    finally { setBusy(false) }
  }
  const upload = async (file?: File) => {
    if (!file) return
    setBusy(true)
    try { await uploadSiteDoc(props.companyId, props.site.id, file, 'other', file.name); await docs.refetch(); toast.success('Файл приложен. Выберите его в нужной редакции документа') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось приложить файл') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="font-semibold text-sm">Документы интеграции</h3><p className="text-xs text-muted-foreground">Файл, согласованная редакция и подписанная версия учитываются отдельно. При подписании укажите дату, подписантов и основание подтверждения.</p>
    <input ref={input} className="hidden" type="file" onChange={(e) => void upload(e.target.files?.[0])} /><Button variant="outline" disabled={busy} onClick={() => input.current?.click()}>Приложить файл</Button>
    {docs.isError && <div role="alert">Файлы не загрузились: {docs.error.message}<Button onClick={() => void docs.refetch()}>Повторить</Button></div>}
    {rows.map((d) => <div key={d.id} className="rounded border p-3 space-y-3"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Вид документа<select className={selectClass} value={d.kind} onChange={(e) => change(d.id, { kind: e.target.value })}>{Object.entries(DOC_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="text-sm">Название<Input value={d.title} onChange={(e) => change(d.id, { title: e.target.value })} /></label><label className="text-sm">Редакция / номер<Input value={d.edition} onChange={(e) => change(d.id, { edition: e.target.value })} /></label></div>
      {([['fileDocId', 'Файл'], ['agreedDocId', 'Согласованная редакция'], ['signedDocId', 'Подписанная версия']] as const).map(([field, label]) => <div key={field} className="flex gap-2 items-end"><label className="flex-1 min-w-0 text-sm">{label}<select className={selectClass} value={d[field]} onChange={(e) => change(d.id, { [field]: e.target.value })}><option value="">Не выбрана</option>{(docs.data || []).map((file) => <option key={file.id} value={file.id}>{file.title || file.fileName}</option>)}</select></label><Button variant="outline" disabled={!d[field]} onClick={() => void downloadSiteDoc(props.companyId, props.site.id, d[field]).catch((e) => toast.error(e.message))}>Скачать</Button></div>)}
      <label className="block text-sm">Подтверждение подписания<Textarea value={d.signingEvidence} onChange={(e) => change(d.id, { signingEvidence: e.target.value })} /></label><Button variant="ghost" onClick={() => setRows(rows.filter((r) => r.id !== d.id))}>Удалить запись документа</Button>
    </div>)}
    <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => setRows([...rows, { id: crypto.randomUUID(), kind: 'other', title: '', edition: '', fileDocId: '', agreedDocId: '', signedDocId: '', signingEvidence: '' }])}>Добавить документ</Button><Button disabled={busy} onClick={() => void save()}>Сохранить редакции документов</Button></div>
  </section>
}

export function IntegrationDocuments(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  return <div className="space-y-4"><DocumentsEditor key={query.data.data.revision} data={query.data.data} props={props} onSaved={refresh} /><ProjectDocumentsTrack {...props} /></div>
}

export function IntegrationAccountingFields(props: Props) {
  const { query, refresh } = useIntegration(props)
  const counterparties = useQuery({ queryKey: ['counterparties', props.companyId], queryFn: () => getCounterparties(props.companyId) })
  const contracts = useQuery({ queryKey: ['contracts', props.companyId], queryFn: () => getContracts(props.companyId) })
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState('')
  const [pickedContracts, setPickedContracts] = useState<string[]>([])
  useEffect(() => { setPickedContracts(query.data?.data.contractIds || []) }, [query.data?.data.contractIds])
  useEffect(() => { setPicked(query.data?.data.accounting.counterpartyId || '') }, [query.data?.data.accounting.counterpartyId])
  if (!query.data) return <QueryStatus query={query} />
  const save = async () => {
    if (!query.data) return
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: query.data.data.revision, accounting: { counterpartyId: picked }, contractIds: pickedContracts }); await refresh() }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить связь') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3">
    <h3 className="text-sm font-semibold">Связи с учётной системой</h3>
    <label className="block text-sm">Контрагент<select className={selectClass} value={picked} onChange={(e) => setPicked(e.target.value)}><option value="">Не связан</option>{(counterparties.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
    <fieldset className="max-h-64 overflow-auto space-y-2"><legend className="text-sm font-medium">Договоры проекта</legend>{(contracts.data || []).map((c) => <label key={c.id} className="flex gap-2 text-sm"><input type="checkbox" checked={pickedContracts.includes(c.id)} onChange={(e) => setPickedContracts(e.target.checked ? [...pickedContracts, c.id] : pickedContracts.filter((id) => id !== c.id))} />{c.number} · {c.date} · {c.type}</label>)}</fieldset>
    {(counterparties.isError || contracts.isError) && <p role="alert">Не удалось загрузить справочник учётной системы</p>}
    <Button disabled={busy || counterparties.isLoading || contracts.isLoading || counterparties.isError || contracts.isError} onClick={() => void save()}>Сохранить связи</Button>
  </section>
}
