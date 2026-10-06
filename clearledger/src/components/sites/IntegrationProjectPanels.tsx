import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { StationScopePicker } from '@/components/workspace/StationScopePicker'
import { getContracts, getCounterparties, getCounterpartyContacts, createCounterpartyContact, updateCounterpartyContact, deleteCounterpartyContact, CONTACT_ROLE_LABEL, type CounterpartyContact } from '@/services/referenceService'
import { post } from '@/services/apiClient'
import { getProjectCase, openProjectCase, getSiteDocs, downloadSiteDoc, uploadSiteDoc, waiveSiteGate, getSiteParticipants, getSiteMembers, patchSite, FUNNEL_STAGES, type SiteDetail, type GateItem } from '@/services/sitesService'
import {
  getIntegration, getIntegrationStations, saveIntegration, confirmIntegration,
  LEAD_INITIATORS, LEAD_CONTRACT_KINDS,
  INTEGRATION_DIRECTIONS, INTEGRATION_FORMATS, INTEGRATION_PAYERS, INTEGRATION_MODELS, CONNECT_BASIS, TEST_STATUSES,
  isRetired, reconState, MATCH_KINDS, getPartnerSessions, PARTY_SIDES, type IntegrationParty,
  type IntegrationData, type IntegrationSection, type IntegrationScenario,
  type IntegrationDocument, type IntegrationStation, type IntegrationTask, type IntegrationResult,
  type IntegrationTest, type IntegrationReconciliation, type IntegrationListVersion,
} from '@/services/projectIntegrationService'
import { ProjectEvidencePicker } from './ProjectEvidencePicker'
import { ProjectDocumentsTrack } from './ProjectDocumentsTrack'

type Props = { site: SiteDetail; companyId: string; onDone: () => Promise<void> }
const selectClass = 'h-10 w-full min-w-0 rounded-md border bg-background px-2 text-sm'
const GROUPS: Record<IntegrationSection, { title: string; fields: [string, string][] }> = {
  lead: { title: 'Заявка', fields: [['initiator', 'Инициатор'], ['contractKind', 'Вид предполагаемого договора'], ['payer', 'Кто кому платит'], ['coverage', 'Охват в общих чертах'], ['curatorUserId', 'Технический куратор интеграции']] },
  partner: { title: 'Партнёр и цель', fields: [['name', 'Партнёр'], ['legalEntity', 'Юридическое лицо, ИНН и подписант'], ['purpose', 'Цель интеграции'], ['commercialContact', 'Коммерческий контакт'], ['assessment', 'Масштаб партнёра и пересечение регионов']] },
  settlement: { title: 'Порядок расчётов и учёт', fields: [['period', 'Периодичность расчётов'], ['paymentTerm', 'Срок оплаты'], ['documents', 'Закрывающие документы: отчёт агента, акт, УПД'], ['vat', 'НДС'], ['disputes', 'Порядок сверки и разрешения расхождений'], ['minimums', 'Минимальные платежи и гарантии'], ['penalties', 'Ответственность за просрочку и штрафы'], ['accountingChannel', 'Как сессии партнёра выделяются в учёте: канал оплаты, идентификатор']] },
  commercial: { title: 'Коммерческие условия (общие для сценариев)', fields: [['commission', 'Комиссия / фиксированная плата'], ['calculationBase', 'База расчёта'], ['acquiring', 'Эквайринг'], ['tariffs', 'Правила тарифов'], ['discounts', 'Правила скидок'], ['discountFunding', 'Источник финансирования скидок'], ['settlements', 'Взаиморасчёты и разрешение расхождений'], ['reporting', 'Отчётность']] },
  data: { title: 'Данные, аналитика и бренд', fields: [['outgoing', 'Что передаём'], ['incoming', 'Что получаем'], ['statisticsUse', 'Ограничения использования статистики'], ['sessionHistory', 'История сессий'], ['analytics', 'Аналитика'], ['brand', 'Бренд и отображение'], ['appTransitions', 'Переходы в приложение']] },
  technical: { title: 'Технические параметры и сопровождение', fields: [['systems', 'Системы сторон'], ['protocol', 'Протокол / API'], ['version', 'Версия протокола / API'], ['contacts', 'Технические контакты сторон'], ['responsibilities', 'Распределение ответственности'], ['support', 'Поддержка и прекращение интеграции'], ['access', 'Доступы'], ['security', 'Требования безопасности'], ['acceptanceCriteria', 'Программа тестирования и критерии приёмки'], ['productionAccess', 'Боевые доступы: выданы, тестовые отозваны']] },
  work: { title: 'Пилот и проверки', fields: [['pilotDecision', 'Решение о пилоте'], ['pilotOutcome', 'Итог пилота'], ['testResults', 'Результаты проверок'], ['launchDate', 'Дата коммерческого запуска']] },
  accounting: { title: 'Связь с контрагентом', fields: [] },
}
/** Кто закрывает пункт по регламенту — словами, а не кодом «ОР» (вопрос МАГа 06.10.2026). */
export const ROLE_NAMES: Record<string, string> = {
  'ОР': 'Отдел развития', 'ДР/ГД': 'Директор по развитию / ГД', 'ОЭ': 'Эксплуатация', 'ЮБ': 'Юристы',
  'ФБ': 'Финансы', 'ИТ': 'ИТ-служба', 'Поддержка': 'Поддержка',
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

/**
 * Несохранённые правки разделов в окне пункта. Окно пункта — одна кнопка «Подтвердить
 * выполнение»: она сохраняет всё, что заполнено в окне, и подтверждает пункт. Раньше
 * у каждого раздела была своя «Сохранить», и заполненное, но не сохранённое отдельно,
 * терялось — пункт «никак не заполнить» (замечание МАГа 06.10.2026).
 */
type Pending = { current: Record<string, unknown>; bump?: () => void }
const PendingCtx = createContext<Pending | null>(null)
/** Регистрирует черновик раздела в окне пункта; true — редактор внутри окна пункта.
 *  Соседние блоки окна видят черновик (версия перечня — ещё не сохранённый договор):
 *  смена черновика перерисовывает окно (bump), одинаковый — нет, иначе зациклится. */
function usePending(key: string, value: unknown, initial: unknown): boolean {
  const pending = useContext(PendingCtx)
  useEffect(() => {
    if (!pending) return
    const next = JSON.stringify(value) !== JSON.stringify(initial) ? value : undefined
    if (JSON.stringify(pending.current[key]) === JSON.stringify(next)) return
    if (next === undefined) delete pending.current[key]; else pending.current[key] = next
    pending.bump?.()
  }, [pending, key, value, initial])
  return !!pending
}

function SectionEditor({ section, data, props, onSaved, only }: { section: IntegrationSection; data: IntegrationData; props: Props; onSaved: () => Promise<void>; only?: string[] }) {
  const [draft, setDraft] = useState(data[section])
  const [busy, setBusy] = useState(false)
  const [all, setAll] = useState(false)
  const group = GROUPS[section]
  // Окно пункта показывает поля пункта, а не весь раздел: десять граф «Технических
  // параметров» под пунктом «Руководитель назначен» читались как ошибка (05.10.2026).
  const fields = only && !all ? group.fields.filter(([k]) => only.includes(k)) : group.fields
  const inItem = usePending(section, draft, data[section])
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, [section]: draft }); await onSaved(); toast.success('Данные сохранены. Согласование подтверждается отдельно') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3">
    <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-sm flex-1">{group.title}</h3>
      {only && <button type="button" className="text-xs underline text-muted-foreground" onClick={() => setAll(!all)}>{all ? 'только поля пункта' : 'все поля раздела'}</button>}</div>
    <div className={`grid gap-3 ${fields.length > 1 ? 'sm:grid-cols-2' : ''}`}>{fields.map(([key, label]) => <label key={key} className="block space-y-1 text-sm">{label}
      {key === 'launchDate' ? <Input type="date" value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
        : <Textarea rows={2} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />}
    </label>)}</div>
    {!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить раздел</Button>}
  </section>
}

/** Код станции для человека: у станций чужих сетей кода нет, вместо него UUID — его не показываем. */
const humanCode = (code: string | null | undefined) => (code && !/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(code) ? code : '')

function StationListPicker({ scenario, stations, field, value, onChange }: {
  scenario: IntegrationScenario; stations: IntegrationStation[]; field: 'selectedIds' | 'agreedIds' | 'connectedIds' | 'pilotIds'; value: string[]; onChange: (ids: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const [regions, setRegions] = useState<string[]>([])
  const [group, setGroup] = useState('')
  const titles = { selectedIds: 'Выбрано', agreedIds: 'Согласовано', connectedIds: 'Фактически подключено', pilotIds: 'Пилотный перечень' }
  const available = useMemo(() => stations.filter((s) => s.network === scenario.direction)
    .filter((s) => !isRetired(s) || value.includes(s.id))
    .filter((s) => field === 'selectedIds' || (field === 'connectedIds' ? scenario.agreedIds : scenario.selectedIds).includes(s.id)), [stations, scenario, field, value])
  const groups = [...new Set(available.map((s) => s.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru'))
  const filtered = useMemo(() => available.filter((s) => !group || s.group === group)
    .map((s) => { const code = humanCode(s.code); return { ...s, code: s.id, displayCode: code, name: code ? `${s.name} · ${code}` : s.name } }), [available, group])
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

/** Что из сценария показывает окно пункта. На 1.6 «Станции определены» были видны все
 *  четыре перечня, расчёты и версии договора — предмет других стадий (06.10.2026). */
type ScenarioListField = 'selectedIds' | 'agreedIds' | 'connectedIds' | 'pilotIds'
type ScenarioView = { lists: ScenarioListField[]; terms?: boolean; versions?: boolean; marks?: boolean; lockHeader?: boolean }
const FULL_SCENARIO_VIEW: ScenarioView = { lists: ['selectedIds', 'agreedIds', 'connectedIds', 'pilotIds'], terms: true, versions: true, marks: true }

function ScenariosEditor({ data, props, onSaved, compact, view: viewProp }: { data: IntegrationData; props: Props; onSaved: () => Promise<void>; compact?: boolean; view?: ScenarioView }) {
  const view = viewProp ?? (compact ? { lists: [] } : FULL_SCENARIO_VIEW)
  const [rows, setRows] = useState(data.scenarios)
  const [busy, setBusy] = useState(false)
  // В заявке сценарий — это направление и формат; перечни станций и расчёты — позже.
  const catalog = useQuery({ queryKey: ['integration-stations', props.companyId, props.site.id], queryFn: () => getIntegrationStations(props.companyId, props.site.id), enabled: view.lists.length > 0 })
  const change = (id: string, patch: Partial<IntegrationScenario>) => setRows(rows.map((s) => s.id === id ? { ...s, ...patch } : s))
  const changeList = (row: IntegrationScenario, field: 'selectedIds' | 'agreedIds' | 'connectedIds' | 'pilotIds', ids: string[]) => {
    if (field === 'selectedIds') change(row.id, { selectedIds: ids, agreedIds: row.agreedIds.filter((id) => ids.includes(id)), connectedIds: row.connectedIds.filter((id) => ids.includes(id)), pilotIds: row.pilotIds.filter((id) => ids.includes(id)) })
    else if (field === 'agreedIds') change(row.id, { agreedIds: ids, connectedIds: row.connectedIds.filter((id) => ids.includes(id)) })
    else change(row.id, { [field]: ids })
  }
  // Дата и основание подключения живут только у подключённых станций: убранная из
  // перечня станция уносит их с собой, иначе сервер отклонит сохранение.
  const pruned = (list: IntegrationScenario[]) => list.map((s) => ({ ...s,
    connectedMeta: Object.fromEntries(Object.entries(s.connectedMeta || {}).filter(([id]) => s.connectedIds.includes(id))) }))
  const inItem = usePending('scenarios', rows === data.scenarios ? data.scenarios : pruned(rows), data.scenarios)
  const markConnected = (row: IntegrationScenario, at: string, basis: keyof typeof CONNECT_BASIS, ref: string) => {
    const meta = { ...(row.connectedMeta || {}) }
    for (const id of row.connectedIds) if (!meta[id]?.at) meta[id] = { at, basis, ref }
    change(row.id, { connectedMeta: meta })
  }
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, scenarios: pruned(rows) }); await onSaved(); toast.success('Фиксированный состав перечней сохранён') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить перечни') }
    finally { setBusy(false) }
  }
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="text-sm font-semibold">{compact ? 'Сценарий интеграции' : 'Сценарии подключения и перечни ЭЗС'}</h3>
    {compact && <p className="text-xs text-muted-foreground">В заявке — направление и формат. Перечни станций выбираются на «Оценке партнёра» (пункт 1.6), расчёты по сценарию — на «Переговорах».</p>}
    <p className="text-xs text-muted-foreground">Для гибридной или двусторонней интеграции заведите отдельные сценарии по каждому формату и направлению. Новые станции автоматически в перечни не добавляются.</p>
    {catalog.isError && <div role="alert">Перечень станций не загрузился: {catalog.error.message}<Button variant="outline" onClick={() => void catalog.refetch()}>Повторить</Button></div>}
    {rows.map((s) => <div key={s.id} className="rounded-md border p-3 space-y-3">
      {view.lockHeader ? <p className="text-sm font-medium">{scenarioLabel(s)}{s.geography ? <span className="font-normal text-muted-foreground"> · {s.geography}</span> : null}</p> : <>
      <label className="block text-sm">Название сценария<Input value={s.name} onChange={(e) => change(s.id, { name: e.target.value })} /></label>
      <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Направление<select className={selectClass} value={s.direction} onChange={(e) => change(s.id, { direction: e.target.value as IntegrationScenario['direction'], selectedIds: [], agreedIds: [], connectedIds: [], pilotIds: [] })}>{(['outgoing', 'incoming'] as const).map((v) => <option key={v} value={v}>{INTEGRATION_DIRECTIONS[v]}</option>)}</select></label>
        <label className="text-sm">Формат<select className={selectClass} value={s.format} onChange={(e) => change(s.id, { format: e.target.value as IntegrationScenario['format'] })}>{(['information', 'roaming'] as const).map((v) => <option key={v} value={v}>{INTEGRATION_FORMATS[v]}</option>)}</select></label>
        <label className="text-sm">География<Input value={s.geography} onChange={(e) => change(s.id, { geography: e.target.value })} /></label>
        <label className="text-sm">Ограничения<Input value={s.restrictions} onChange={(e) => change(s.id, { restrictions: e.target.value })} /></label></div></>}
      {view.terms && <ScenarioTerms scenario={s} onChange={(patch) => change(s.id, patch)} />}
      {view.lists.length === 0 ? null : catalog.isPending ? <p role="status">Загрузка станций…</p> : view.lists.map((field) => <StationListPicker key={field} scenario={s} field={field} stations={catalog.data || []} value={s[field]} onChange={(ids) => changeList(s, field, ids)} />)}
      {view.lists.length > 0 && <RetiredWarning scenario={s} stations={catalog.data || []} />}
      {view.marks && <ConnectionMarks scenario={s} onMark={(at, basis, ref) => markConnected(s, at, basis, ref)} />}
      {view.versions && <ListVersions scenario={s} saved={data.scenarios.find((x) => x.id === s.id)} data={data} props={props} onSaved={onSaved} />}
      {!view.lockHeader && <Button variant="ghost" onClick={() => setRows(rows.filter((r) => r.id !== s.id))}>Удалить сценарий</Button>}
    </div>)}
    <div className="flex flex-wrap gap-2">{!view.lockHeader && <Button variant="outline" onClick={() => setRows([...rows, { id: crypto.randomUUID(), name: '', direction: 'outgoing', format: 'information', geography: '', restrictions: '', partnerNetwork: '', selectedIds: [], agreedIds: [], connectedIds: [], pilotIds: [], payer: '', model: '' }])}>Добавить сценарий</Button>}
      {!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить сценарии и перечни</Button>}</div>
  </section>
}

export function IntegrationPassport(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  const data = query.data.data
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">Поля заполняются по этапам. Заполнение паспорта не подтверждает согласование.</p>
    <SectionEditor key={`partner:${data.revision}`} section="partner" data={data} props={props} onSaved={refresh} />
    <PartnerContacts data={data} props={props} onSaved={refresh} />
    <LeadEditor key={`lead:${data.revision}`} data={data} props={props} onSaved={refresh} />
    <ScenariosEditor key={`scenarios:${data.revision}`} data={data} props={props} onSaved={refresh} />
    {(['commercial', 'settlement', 'data', 'technical'] as const).map((section) => <SectionEditor key={`${section}:${data.revision}`} section={section} data={data} props={props} onSaved={refresh} />)}
    <p className="text-sm">Руководитель: {props.site.ownerName || 'не назначен'}. Руководитель и внутренняя команда назначаются во вкладке «Работа».</p>
  </div>
}

/** Контакты партнёра для вкладки «Команда». */
export function IntegrationPartnerContacts(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  return <div className="space-y-4">
    <PartnerContacts data={query.data.data} props={props} onSaved={refresh} />
    <ProjectParties data={query.data.data} props={props} onSaved={refresh} />
  </div>
}

/** Другие организации проекта: вендор, подрядчик, консультант — у каждой роль и свои
 *  контакты (МАГ 06.10.2026: «у нас есть Ondor, который обслуживает техническую интеграцию»).
 *  Организация — контрагент пространства, поэтому её люди видны и в «Контрагентах». */
function ProjectParties({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const qc = useQueryClient()
  const parties = data.parties ?? []
  const cps = useQuery({ queryKey: ['counterparties', props.companyId], queryFn: () => getCounterparties(props.companyId) })
  const nameOf = (id: string) => cps.data?.find((c) => c.id === id)?.name ?? '…'
  const [adding, setAdding] = useState(false)
  const [side, setSide] = useState('vendor')
  const [find, setFind] = useState('')
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const q = find.trim().toLowerCase()
  const found = q.length < 2 ? [] : (cps.data ?? []).filter((c) => `${c.name} ${c.inn ?? ''}`.toLowerCase().includes(q)).slice(0, 30)
  const store = async (next: IntegrationParty[], ok: string) => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, parties: next }); await onSaved(); toast.success(ok) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить') } finally { setBusy(false) }
  }
  const close = () => { setAdding(false); setFind(''); setPick('') }
  const add = async (cpId: string) => { await store([...parties, { counterpartyId: cpId, side }], 'Организация добавлена — заведите её контакты'); close() }
  const createAndAdd = async () => {
    setBusy(true)
    try {
      const cp = await post<{ id: string }>('/api/references/counterparties', { company_id: props.companyId, name: find.trim(), inn: '', type: 'ЮЛ', aliases: ['integration'] })
      await qc.invalidateQueries({ queryKey: ['counterparties', props.companyId] })
      setBusy(false); await add(cp.id)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось завести контрагента'); setBusy(false) }
  }
  const choices = found.filter((c) => !parties.some((p) => p.counterpartyId === c.id) && c.id !== data.accounting?.counterpartyId)
  return <section className="space-y-3">
    {parties.map((p) => <PartnerContacts key={p.counterpartyId} data={data} props={props} onSaved={onSaved}
      party={{ cpId: p.counterpartyId, title: `${PARTY_SIDES[p.side] ?? p.side} · ${nameOf(p.counterpartyId)}`, side: p.side,
        onSide: (s) => void store(parties.map((x) => x.counterpartyId === p.counterpartyId ? { ...x, side: s } : x), 'Роль организации изменена'),
        onRemove: () => void store(parties.filter((x) => x.counterpartyId !== p.counterpartyId), 'Организация убрана из проекта') }} />)}
    {!adding
      ? <Button size="sm" variant="outline" onClick={() => setAdding(true)}>Добавить организацию: вендор, подрядчик…</Button>
      : <div className="rounded-lg border p-3 space-y-2">
          <h3 className="font-semibold text-sm">Организация в проекте</h3>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Роль организации" className={`${selectClass} w-48`} value={side} onChange={(e) => setSide(e.target.value)}>
              {Object.entries(PARTY_SIDES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <Input aria-label="Найти организацию" className="h-9 flex-1 min-w-56" placeholder="Название или ИНН, например Ondor" value={find} autoFocus
              onChange={(e) => { setFind(e.target.value); setPick('') }} />
          </div>
          {choices.length > 0 && <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Найденная организация" className={`${selectClass} flex-1 min-w-56`} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Найдено: {choices.length} — выберите</option>
              {choices.map((c) => <option key={c.id} value={c.id}>{c.name}{c.inn ? ` · ИНН ${c.inn}` : ''}</option>)}</select>
            <Button size="sm" disabled={!pick || busy} onClick={() => void add(pick)}>Добавить</Button>
          </div>}
          <div className="flex flex-wrap items-center gap-2">
            {q.length >= 2 && !found.some((c) => c.name.trim().toLowerCase() === q) &&
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void createAndAdd()}>Завести новую: «{find.trim()}»</Button>}
            <Button size="sm" variant="ghost" onClick={close}>Отмена</Button>
          </div>
          <p className="text-xs text-muted-foreground">Организация заводится контрагентом пространства: её контакты видны в «Контрагентах» и в других проектах, где она участвует.</p>
        </div>}
  </section>
}

export function IntegrationWorkPlan(props: Props) {
  const { query, refresh } = useIntegration(props)
  if (!query.data) return <QueryStatus query={query} />
  // Блоки появляются со своей стадией: в заявке пилот, испытания и даты всех этапов
  // только перегружали экран (замечание МАГа 05.10.2026). Уже введённое не прячем.
  const d = query.data.data
  const at = (stage: string) => FUNNEL_STAGES.indexOf(props.site.stage as never) >= FUNNEL_STAGES.indexOf(stage as never)
  const showWork = at('decision') || Object.values(d.work || {}).some(Boolean)
  const showTests = at('construction') || d.tests.length > 0
  return <div className="space-y-4">
    {showWork && <SectionEditor key={d.revision} section="work" data={d} props={props} onSaved={refresh} />}
    {showTests && <TestsEditor key={`tests:${d.revision}`} data={d} props={props} onSaved={refresh} />}
    {!showWork && !showTests && <p className="text-xs text-muted-foreground">Пилот и испытания появятся здесь со своими стадиями.</p>}
  </div>
}

/** Пункты, у которых доказательство — документ (подписанное соглашение, протокол, акт):
 *  поля документа и поручения раскрыты сразу. У остальных — свёрнуты. */
const EVIDENCE_KEYS = new Set(['5.13', '6.14'])

/**
 * Подтверждение пункта: кто и когда подтвердил (при смене данных — подтвердить заново).
 * Одна кнопка вместо «Сохранить» + «Подтвердить»: черновик результата пункту не нужен.
 * Пункт с выполненным требованием к данным подтверждается самими данными — комментарий
 * необязателен; «не применимо» — только у необязательных (замечание МАГа 05.10.2026).
 */
function ResultEditor({ task, props, data, onSaved, onDone }: { task: IntegrationTask; props: Props; data: IntegrationData; onSaved: () => Promise<void>; onDone?: () => void }) {
  const pending = useContext(PendingCtx)
  const [result, setResult] = useState<IntegrationResult>(data.results[task.key] || { comment: '', workRef: '', docId: '', notApplicable: false })
  const [busy, setBusy] = useState(false)
  const [more, setMore] = useState(EVIDENCE_KEYS.has(task.key) || !!result.docId || !!result.workRef)
  const docs = useQuery({ queryKey: ['site-docs', props.companyId, props.site.id], queryFn: () => getSiteDocs(props.companyId, props.site.id), enabled: more })
  const byData = !!task.dataRule && !task.need
  const confirm = async () => {
    setBusy(true)
    let saved = false
    try {
      const next = await saveIntegration(props.companyId, props.site.id, { revision: data.revision, ...(pending?.current ?? {}), results: { ...data.results, [task.key]: { ...result, notApplicable: task.required ? false : result.notApplicable } } })
      saved = true
      if (pending) pending.current = {}
      await confirmIntegration(props.companyId, props.site.id, task.key, next.revision)
      await onSaved(); toast.success(`Пункт ${task.key} подтверждён`); onDone?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось подтвердить')
      // Результат уже записан, отказано только в подтверждении: ревизия на сервере
      // выросла. Без перечитывания следующее действие упрётся в «Карточка изменилась».
      if (saved) await onSaved().catch(() => undefined)
    }
    finally { setBusy(false) }
  }
  return <><section className="rounded-lg border p-3 space-y-3"><h3 className="text-sm font-semibold">Подтверждение пункта {task.key}</h3>
    <label className="block text-sm">{byData ? 'Комментарий — необязательно: подтверждением служат заполненные данные' : result.notApplicable ? 'Причина неприменимости' : task.dataRule ? 'Результат проверки' : 'Результат проверки — обязательно'}
      <Textarea rows={2} value={result.comment} onChange={(e) => setResult({ ...result, comment: e.target.value })} /></label>
    {!task.required && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={result.notApplicable} onChange={(e) => setResult({ ...result, notApplicable: e.target.checked })} />Не применимо к этому сценарию</label>}
    {more ? <>
      <label className="block text-sm">Документ результата<select aria-label="Документ результата" className={selectClass} value={result.docId} onChange={(e) => setResult({ ...result, docId: e.target.value })}><option value="">Не выбран</option>{(docs.data || []).map((d) => <option key={d.id} value={d.id}>{d.title || d.fileName}</option>)}</select></label>
      {docs.isError && <p role="alert">Документы не загрузились: {docs.error.message}</p>}
      <ProjectEvidencePicker companyId={props.companyId} siteId={props.site.id} value={result.workRef} label="Поручение Трека" onChange={(value) => { if (!value || value.startsWith('task:')) setResult({ ...result, workRef: value }); else toast.warning('Выберите поручение. Файл можно выбрать в поле документа результата') }} />
    </> : <button type="button" className="text-xs underline text-muted-foreground" onClick={() => setMore(true)}>приложить документ или поручение</button>}
  </section>
    {/* Закреплена внизу окна: пункт выполняется только ею, а окно длинное */}
    <div className="sticky -bottom-6 z-10 -mx-6 -mb-6 flex flex-wrap items-center gap-3 border-t bg-background px-6 py-3">
      <Button disabled={busy} onClick={() => void confirm()}>Подтвердить выполнение</Button>
      <span className="text-xs text-muted-foreground">Сохранит заполненное в окне и подтвердит пункт {task.key}</span>
    </div>
  </>
}

export function IntegrationChecklist(props: Props) {
  const { query, refresh } = useIntegration(props)
  const pending = useRef<Record<string, unknown>>({}) as Pending
  const [, setPendingTick] = useState(0)
  pending.bump = () => setPendingTick((n) => n + 1)
  const [showAll, setShowAll] = useState(false)
  // Стадия, которую смотрим: по умолчанию текущая, со схемы — выбранная (?pstage=).
  const [params, setParams] = useSearchParams()
  const focus = params.get('pstage')
  const focusItem = params.get('pitem')
  const [viewStage, setViewStage] = useState(focus || props.site.stage)
  // Проект перешёл на следующую стадию — показать её, метку просмотра прежней снять.
  const seenStage = useRef(props.site.stage)
  useEffect(() => {
    if (seenStage.current === props.site.stage) return
    seenStage.current = props.site.stage
    setViewStage(props.site.stage)
    setParams((prev) => { const n = new URLSearchParams(prev); n.delete('pstage'); return n }, { replace: true })
  }, [props.site.stage, setParams])
  const top = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!focus) return
    setViewStage(focus); setShowAll(false)
    top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [focus])
  const [waiving, setWaiving] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  // Открытый пункт живёт в адресе (?pitem=), а не в состоянии: карточка перерисовывается
  // при смене адреса, и окно, открытое ссылкой «открыть пункт» из шапки хода, сразу
  // закрывалось (проверка на боевом 06.10.2026). Закрытие окна снимает метку.
  const editing = (focusItem && query.data?.tasks.find((t) => t.key === focusItem)) || null
  const setEditing = (t: IntegrationTask | null) => setParams((prev) => {
    const n = new URLSearchParams(prev)
    if (t) n.set('pitem', t.key); else n.delete('pitem')
    return n
  }, { replace: true })
  const editingStage = editing?.stage
  // Окно пункта другой стадии (ссылка из шапки хода) — показать его стадию; вид «Все этапы» не сворачиваем.
  useEffect(() => { if (editingStage) setViewStage(editingStage) }, [editingStage])
  if (!query.data) return <QueryStatus query={query} />
  const { data, tasks, gates } = query.data
  const items = new Map<string, GateItem>(gates.flatMap((g) => g.items).map((i) => [i.key, i]))
  // Сценарии окна — с черновиком: выбрали «Без расчётов» — денежные поля исчезают сразу.
  const winScenarios = (pending.current.scenarios as IntegrationScenario[] | undefined) ?? data.scenarios
  const noMoney = winScenarios.length > 0 && winScenarios.every((s) => s.payer === 'none')
  const waive = async (key: string, waived: boolean) => {
    setBusy(true)
    try {
      const res = await waiveSiteGate(props.companyId, props.site.id, key, waived, reason)
      if (res.ok === false) throw new Error(res.message || 'Обязательность не изменена')
      setWaiving(null); setReason(''); await refresh()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось изменить обязательность') }
    finally { setBusy(false) }
  }
  const viewLabel = gates.find((g) => g.stage === viewStage)?.stageLabel ?? viewStage
  const editingItem = editing ? items.get(editing.key) : undefined
  return <section ref={top} className="rounded-lg border p-3 space-y-3 scroll-mt-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-sm">Чек-лист интеграции · {showAll ? 'все этапы' : viewLabel}</h3><Button variant="outline" size="sm" onClick={() => setShowAll(!showAll)}>{showAll ? 'По стадиям' : 'Все этапы'}</Button></div>
    {!showAll && <div className="flex flex-wrap gap-1">{gates.filter((g) => tasks.some((t) => t.stage === g.stage)).map((g) =>
      <button key={g.stage} type="button" onClick={() => setViewStage(g.stage)}
        className={`rounded-full border px-2 py-0.5 text-[11px] ${g.stage === viewStage ? 'bg-primary text-primary-foreground border-primary' : g.stage === props.site.stage ? 'border-primary text-primary' : 'text-muted-foreground'}`}>
        {g.stageLabel}{g.stage === props.site.stage ? ' · сейчас' : ''} {g.done}/{g.total}</button>)}</div>}
    {!showAll && viewStage === props.site.stage && props.site.gate?.canAdvance && tasks.some((t) => t.stage === viewStage) &&
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">
        <span className="flex-1 min-w-48">Все обязательные пункты стадии «{viewLabel}» закрыты — можно переходить дальше.</span>
        <Button size="sm" onClick={() => setParams((prev) => { const n = new URLSearchParams(prev); n.set('pstep', String(Date.now())); return n }, { replace: true })}>Перейти к следующей стадии</Button>
      </div>}
    {!showAll && viewStage !== props.site.stage && <p className="text-xs text-amber-700 dark:text-amber-400">Просмотр стадии «{viewLabel}». Проект сейчас на стадии «{props.site.gate.stageLabel}» — пункты другой стадии можно заполнять заранее, переход делается кнопками маршрута.</p>}
    {tasks.filter((t) => showAll || t.stage === viewStage).map((t) => {
      const item = items.get(t.key)
      return <div key={t.key} className="border-b py-3 space-y-2 last:border-b-0"><div className="flex flex-wrap gap-2 text-sm"><span className="font-mono">{t.key}</span><span className="flex-1 min-w-40">{t.label}</span><span className="text-xs text-muted-foreground" title={`Отвечает по регламенту: ${ROLE_NAMES[t.role] ?? t.role}`}>{ROLE_NAMES[t.role] ?? t.role}</span></div>
        <p className={`text-xs ${item?.needsConfirmation ? 'text-amber-600' : item?.done ? 'text-emerald-600' : 'text-muted-foreground'}`}>{item?.needsConfirmation ? 'Требует повторного подтверждения' : item?.done ? 'Подтверждено' : item?.waived ? 'Обязательность снята' : `${t.required ? 'Обязательный пункт: держит переход' : 'Не подтверждено'}${t.need ? ` · не хватает: ${t.need}` : ''}`}{item?.confirmedBy ? ` · ${item.confirmedBy}` : ''}{item?.confirmedAt ? ` · ${new Date(item.confirmedAt).toLocaleString('ru-RU')}` : ''}</p>
        {data.results[t.key]?.comment && <p className="text-sm whitespace-pre-wrap">{data.results[t.key].comment}</p>}
        <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => setEditing(t)}>Данные и результат</Button>
          {props.site.mayWaive && item?.waivable && !item.done && <Button className="max-w-full h-auto min-h-9 whitespace-normal text-left" variant="ghost" size="sm" disabled={busy} onClick={() => item.waived ? void waive(t.key, false) : setWaiving(t.key)}>{item.waived ? 'Вернуть обязательность' : 'Снять обязательность под свою ответственность'}</Button>}</div>
        {item?.waived && <p className="text-xs text-amber-600">{item.waivedBy} · {item.waiveReason}</p>}
        {waiving === t.key && <div className="space-y-2"><Textarea aria-label="Обоснование снятия обязательности" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Обоснование: под решением будет ваше имя" /><Button disabled={!reason.trim() || busy} onClick={() => void waive(t.key, true)}>Подтвердить снятие обязательности</Button><Button variant="ghost" onClick={() => setWaiving(null)}>Отмена</Button></div>}
      </div>
    })}
    <Dialog open={!!editing} onOpenChange={(open) => { if (!open) { setEditing(null); pending.current = {} } }}><DialogContent className="sm:max-w-4xl w-[96vw] max-h-[90dvh] overflow-y-auto"><DialogHeader><DialogTitle>{editing?.key} · {editing?.label}</DialogTitle></DialogHeader>
      <PendingCtx.Provider value={pending}>
      {editing && <>{editingItem?.done && !editingItem.needsConfirmation
          ? <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">Пункт подтверждён{editingItem.confirmedBy ? ` · ${editingItem.confirmedBy}` : ''}{editingItem.confirmedAt ? ` · ${new Date(editingItem.confirmedAt).toLocaleString('ru-RU')}` : ''}. Изменили данные — подтвердите заново.</p>
          : <p className="text-xs text-muted-foreground">Заполните данные и нажмите «Подтвердить выполнение» внизу: заполненное сохранится, пункт будет подтверждён с вашим именем и датой.</p>}
        {/* 1.3 не повторяет редактор 1.2 (замечание 05.10.2026): сценарии заводятся в 1.2,
            здесь — сводка их форматов. 1.4 — назначение руководителя, а не тех. параметры. */}
        {noMoney && MONEY_KEYS[editing.key]
          ? <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">Во всех сценариях «Без расчётов» — {MONEY_KEYS[editing.key]} не нужны. Нажмите «Подтвердить выполнение» внизу окна.</p>
          : <NeedLine task={tasks.find((x) => x.key === editing.key) ?? editing} item={items.get(editing.key)} />}
        {(ITEM_VIEW[editing.key]?.sections ?? [editing.section, ...(EXTRA_EDITORS[editing.key] || [])])
          .filter((section) => !(noMoney && MONEY_KEYS[editing.key] && section !== 'scenarios')).map((section) => <TaskEditor key={`${section}:${data.revision}`} section={section} data={data} props={props} onSaved={refresh}
          compact={ITEM_VIEW[editing.key]?.compact} scenarioView={ITEM_VIEW[editing.key]?.scenarios} signing={SIGNING_KINDS[editing.key]}
          only={ITEM_VIEW[editing.key]?.fieldsBy?.[section] ?? (section === 'lead' ? ITEM_VIEW[editing.key]?.leadFields : section === (ITEM_VIEW[editing.key]?.sections?.[0] ?? editing.section) ? ITEM_VIEW[editing.key]?.fields : undefined)} />)}
        {ITEM_VIEW[editing.key]?.sections?.length === 0 && !['1.4', '5.12'].includes(editing.key) && <p className="text-sm text-muted-foreground">Отдельных данных у пункта нет: он подтверждается результатом ниже — комментарием, документом или поручением «Трека».</p>}
        {editing.key === '1.4' && <ProjectLeadPicker props={props} onSaved={refresh} />}
        {editing.key === '1.1' && <PartnerContacts data={data} props={props} onSaved={refresh} />}
        {editing.key === '5.12' && <PartnerSessionsRule key={`match:${data.revision}`} data={data} props={props} onSaved={refresh} />}
        <ResultEditor key={`${editing.key}:${data.revision}`} task={editing} props={props} data={data} onSaved={refresh} onDone={() => setEditing(null)} />
      </>}
      </PendingCtx.Provider>
    </DialogContent></Dialog>
  </section>
}

/**
 * Контакты партнёра — люди на его стороне: договор, коммерция, техника/протокол, финансы
 * и сверки, поддержка пользователей. Хранятся в карточке контрагента, а не в проекте:
 * тот же человек нужен и в договорах, и в «Контрагентах», и заводить его дважды значит
 * разойтись в телефоне через месяц. Партнёр ещё не связан с контрагентом — блок
 * предлагает выбрать карточку или завести её по названию партнёра.
 */
const EMPTY_CONTACT = { name: '', position: '', role: 'comm', phone: '', email: '', notes: '' }
type PartyBlock = { cpId: string; title: string; side: string; onSide: (side: string) => void; onRemove: () => void }
function PartnerContacts({ data, props, onSaved, compact, party }: { data: IntegrationData; props: Props; onSaved: () => Promise<void>; compact?: boolean; party?: PartyBlock }) {
  const cpId = party?.cpId || data.accounting?.counterpartyId || ''
  const qc = useQueryClient()
  const contacts = useQuery({ queryKey: ['cp-contacts', cpId], queryFn: () => getCounterpartyContacts(cpId), enabled: !!cpId })
  const cps = useQuery({ queryKey: ['counterparties', props.companyId], queryFn: () => getCounterparties(props.companyId), enabled: !cpId && !compact })
  const [pick, setPick] = useState('')
  const [find, setFind] = useState('')
  const found = find.trim().length < 2 ? [] : (cps.data ?? []).filter((c) => `${c.name} ${c.inn ?? ''}`.toLowerCase().includes(find.trim().toLowerCase())).slice(0, 30)
  const [form, setForm] = useState<typeof EMPTY_CONTACT & { id?: string }>(EMPTY_CONTACT)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const partner = data.partner?.name || ''
  const link = async (id: string) => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, accounting: { ...data.accounting, counterpartyId: id } }); await onSaved(); toast.success('Партнёр связан с контрагентом') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось связать') } finally { setBusy(false) }
  }
  const createAndLink = async () => {
    setBusy(true)
    try {
      const cp = await post<{ id: string }>('/api/references/counterparties', { company_id: props.companyId, name: partner, inn: '', type: 'ЮЛ', aliases: ['integration'] })
      await qc.invalidateQueries({ queryKey: ['counterparties', props.companyId] })
      setBusy(false); await link(cp.id)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось завести контрагента'); setBusy(false) }
  }
  const save = async () => {
    setBusy(true)
    const body = { name: form.name.trim(), position: form.position.trim() || null, role: form.role, phone: form.phone.trim() || null, email: form.email.trim() || null, notes: form.notes.trim() || null }
    try {
      if (form.id) await updateCounterpartyContact(cpId, form.id, body); else await createCounterpartyContact(cpId, body)
      await contacts.refetch(); setForm(EMPTY_CONTACT); setEditing(false); toast.success('Контакт сохранён')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить контакт') } finally { setBusy(false) }
  }
  const remove = async (c: CounterpartyContact) => {
    setBusy(true)
    try { await deleteCounterpartyContact(cpId, c.id); await contacts.refetch() }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось удалить') } finally { setBusy(false) }
  }
  const rows = contacts.data ?? []
  return <section className="rounded-lg border p-3 space-y-2">
    <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-sm flex-1">
        {party ? party.title : `Партнёр${partner ? ` · ${partner}` : ''}`}{rows.length > 0 && <span className="font-normal text-muted-foreground"> · контактов {rows.length}</span>}</h3>
      {party && <select aria-label="Роль организации" className={`${selectClass} w-44`} value={party.side} onChange={(e) => party.onSide(e.target.value)}>
        {Object.entries(PARTY_SIDES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}
      {cpId && !editing && <Button size="sm" variant="outline" onClick={() => { setForm(EMPTY_CONTACT); setEditing(true) }}>Добавить контакт</Button>}
      {party && <Button size="sm" variant="ghost" title="Убрать организацию из проекта: контрагент и его контакты остаются" onClick={party.onRemove}>убрать</Button>}</div>
    {!cpId && (compact
      ? <p className="text-xs text-muted-foreground">Партнёр не связан с контрагентом — контакты заводятся в «Паспорте» после связи.</p>
      : <div className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">Контакты хранятся в карточке контрагента партнёра — их видно и в «Контрагентах», и в договорах. Можно отложить до переговоров.</p>
          <div className="flex flex-wrap gap-2 items-center">
            {partner && <Button size="sm" disabled={busy} onClick={() => void createAndLink()}>Завести контрагента «{partner}»</Button>}
            <Input aria-label="Найти контрагента" className="h-9 max-w-xs" placeholder="или найти существующего: название, ИНН" value={find} onChange={(e) => { setFind(e.target.value); setPick('') }} />
            {found.length > 0 && <select aria-label="Контрагент партнёра" className={`${selectClass} max-w-sm`} value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Найдено: {found.length}{found.length === 30 ? '+' : ''}</option>{found.map((c) => <option key={c.id} value={c.id}>{c.name}{c.inn ? ` · ИНН ${c.inn}` : ''}</option>)}</select>}
            {pick && <Button size="sm" variant="outline" disabled={busy} onClick={() => void link(pick)}>Связать</Button>}
          </div>
        </div>)}
    {cpId && contacts.isLoading && <p className="text-xs text-muted-foreground">Загрузка…</p>}
    {cpId && !contacts.isLoading && rows.length === 0 && !editing && <p className="text-xs text-muted-foreground">Контактов нет. Обычно нужны: договор, коммерция, техника и протокол, финансы и сверки, поддержка пользователей.</p>}
    {rows.length > 0 && <ul className="divide-y text-sm">{rows.map((c) => <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-1.5">
      <span className="rounded border px-1.5 text-[11px] text-muted-foreground">{CONTACT_ROLE_LABEL[c.role] ?? c.role}</span>
      <span className="font-medium">{c.name}</span>{c.position && <span className="text-xs text-muted-foreground">{c.position}</span>}
      {c.phone && <a className="text-xs text-primary hover:underline" href={`tel:${c.phone.replace(/[^\d+]/g, '')}`}>{c.phone}</a>}
      {c.email && <a className="text-xs text-primary hover:underline" href={`mailto:${c.email}`}>{c.email}</a>}
      {!compact && c.notes && <span className="text-xs text-muted-foreground">{c.notes}</span>}
      {!compact && <span className="ml-auto flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => { setForm({ id: c.id, name: c.name, position: c.position ?? '', role: c.role, phone: c.phone ?? '', email: c.email ?? '', notes: c.notes ?? '' }); setEditing(true) }}>изменить</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void remove(c)}>удалить</Button></span>}
    </li>)}</ul>}
    {editing && <div className="rounded-md border p-2 space-y-2">
      <div className="grid gap-2 sm:grid-cols-3">
        <Input aria-label="ФИО контакта" placeholder="ФИО" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input aria-label="Должность контакта" placeholder="Должность" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} />
        <select aria-label="Направление контакта" className={selectClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {Object.entries(CONTACT_ROLE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <Input aria-label="Телефон контакта" placeholder="Телефон" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        <Input aria-label="Почта контакта" placeholder="Почта" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Input aria-label="Заметка" placeholder="Заметка: когда звонить, за что отвечает" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      <div className="flex gap-2"><Button size="sm" disabled={!form.name.trim() || busy} onClick={() => void save()}>Сохранить контакт</Button>
        <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setForm(EMPTY_CONTACT) }}>Отмена</Button></div>
    </div>}
  </section>
}

/** Заявка: инициатор, предполагаемый договор (вид, кто кому платит), охват, тех. куратор. */
function LeadEditor({ data, props, onSaved, only }: { data: IntegrationData; props: Props; onSaved: () => Promise<void>; only?: string[] }) {
  const [draft, setDraft] = useState<Record<string, string>>(data.lead || {})
  const [busy, setBusy] = useState(false)
  const members = useQuery({ queryKey: ['site-members', props.companyId], queryFn: () => getSiteMembers(props.companyId), enabled: !only || only.includes('curatorUserId') })
  const show = (k: string) => !only || only.includes(k)
  const set = (k: string, v: string) => setDraft({ ...draft, [k]: v })
  const inItem = usePending('lead', draft, data.lead || {})
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, lead: draft }); await onSaved(); toast.success('Заявка сохранена') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить заявку') }
    finally { setBusy(false) }
  }
  const pick = (k: string, label: string, opts: Record<string, string>) => <label className="block space-y-1 text-sm">{label}
    <select aria-label={label} className={selectClass} value={draft[k] || ''} onChange={(e) => set(k, e.target.value)}>
      <option value="">Не указано</option>{Object.entries(opts).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="font-semibold text-sm">Заявка</h3>
    <div className={`grid gap-3 ${!only || only.length > 1 ? 'sm:grid-cols-2' : ''}`}>
      {show('initiator') && pick('initiator', 'Инициатор', LEAD_INITIATORS)}
      {show('contractKind') && pick('contractKind', 'Вид предполагаемого договора', LEAD_CONTRACT_KINDS)}
      {show('payer') && pick('payer', 'Кто кому платит', INTEGRATION_PAYERS)}
      {show('curatorUserId') && <label className="block space-y-1 text-sm">Технический куратор интеграции
        <select aria-label="Технический куратор интеграции" className={selectClass} value={draft.curatorUserId || ''} onChange={(e) => set('curatorUserId', e.target.value)}>
          <option value="">Не назначен</option>
          {draft.curatorUserId && !members.data?.some((m) => m.id === draft.curatorUserId) && <option value={draft.curatorUserId}>сотрудник недоступен</option>}
          {(members.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
        <span className="block text-xs text-muted-foreground">Отвечает за протоколы, техническое согласование и доступы — не обязательно руководитель проекта.</span></label>}
      {show('coverage') && <label className="block space-y-1 text-sm sm:col-span-2">Охват в общих чертах
        <Textarea rows={2} value={draft.coverage || ''} placeholder="Регионы и примерное число станций — без выбора станций" onChange={(e) => set('coverage', e.target.value)} /></label>}
    </div>
    {show('contractKind') && <p className="text-xs text-muted-foreground">Ставки, НДС и сроки оплаты — предмет переговоров (пункты 2.2 и 6.2), в заявке не нужны.</p>}
    {!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить заявку</Button>}
  </section>
}

/** 1.4 — руководитель проекта: это «Ответственный» карточки (он отвечает за шаги и получает
 *  напоминания). Роли регламента в «Кто ведёт проект» — отдельный состав: назначенный там
 *  ОР руководителем не становится сам, поэтому его предлагаем назначить одной кнопкой. */
function ProjectLeadPicker({ props, onSaved }: { props: Props; onSaved: () => Promise<void> }) {
  const parties = useQuery({ queryKey: ['site-parties', props.companyId, props.site.id], queryFn: () => getSiteParticipants(props.companyId, props.site.id) })
  const members = useQuery({ queryKey: ['site-members', props.companyId], queryFn: () => getSiteMembers(props.companyId) })
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const assign = async (userId: string) => {
    setBusy(true)
    try { await patchSite(props.companyId, props.site.id, { owner_user_id: userId }); await props.onDone(); await onSaved(); toast.success('Руководитель проекта назначен') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось назначить') }
    finally { setBusy(false) }
  }
  // Один человек бывает на нескольких ролях — кнопка на человека, а не на роль.
  const leads = [...new Map((parties.data?.participants ?? []).filter((p) => p.userId && p.userId !== props.site.ownerUserId).map((p) => [p.userId, p])).values()]
  return <section className="rounded-lg border p-3 space-y-2"><h3 className="font-semibold text-sm">Руководитель проекта</h3>
    <p className="text-sm">Сейчас: {props.site.ownerName ? <b>{props.site.ownerName}</b> : <span className="text-amber-700 dark:text-amber-400">не назначен</span>}</p>
    <p className="text-xs text-muted-foreground">Руководитель — поле «Руководитель проекта» в «Работе» (блок «Кто ведёт и что дальше»). Роли регламента в «Кто ведёт проект» — отдельное назначение: они распределяют кнопки маршрута, но руководителя не задают.</p>
    {leads.length > 0 && <div className="flex flex-wrap gap-2">{leads.map((p) => <Button key={p.id} size="sm" variant="outline" disabled={busy} onClick={() => void assign(p.userId!)}>Назначить руководителем: {p.name} ({p.roleCode})</Button>)}</div>}
    <div className="flex flex-wrap gap-2"><select aria-label="Руководитель проекта" className={`${selectClass} max-w-xs`} value={pick} onChange={(e) => setPick(e.target.value)}>
      <option value="">Другой сотрудник…</option>{(members.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
      <Button size="sm" disabled={!pick || busy} onClick={() => void assign(pick)}>Назначить</Button></div>
  </section>
}

/** Какой подписанный документ закрывает пункт — те же виды, что проверяет сервер. */
const SIGNING_KINDS: Record<string, string[]> = { '4.3': ['pilot', 'nda'], '5.11': ['test_protocol'], '6.6': ['contract'] }

/**
 * Документы интеграции. В окне пункта с подписанием (signing) — только то, что пункт
 * проверяет: вид, название, подписанная версия и подтверждение подписания. Приложенный
 * файл сразу становится подписанной версией новой записи. Раньше было «Приложить файл»,
 * потом «Добавить документ», потом выбор файла в трёх списках — проход 06.10.2026.
 */
function DocumentsEditor({ data, props, onSaved, signing }: { data: IntegrationData; props: Props; onSaved: () => Promise<void>; signing?: string[] }) {
  const [rows, setRows] = useState(data.documents)
  const [busy, setBusy] = useState(false)
  const inItem = usePending('documents', rows, data.documents)
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
    try {
      const doc = await uploadSiteDoc(props.companyId, props.site.id, file, 'other', file.name); await docs.refetch()
      if (signing) {
        setRows([...rows, { id: crypto.randomUUID(), kind: signing[0], title: file.name.replace(/\.[^.]+$/, ''), edition: '', fileDocId: doc.id, agreedDocId: '', signedDocId: doc.id, signingEvidence: '' }])
        toast.success('Файл приложен как подписанная версия. Укажите подтверждение подписания')
      } else toast.success('Файл приложен. Выберите его в нужной редакции документа')
    }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось приложить файл') }
    finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  const kinds = signing ? Object.entries(DOC_KINDS).filter(([k]) => signing.includes(k)) : Object.entries(DOC_KINDS)
  const shown = signing ? rows.filter((d) => signing.includes(d.kind)) : rows
  return <section className="rounded-lg border p-3 space-y-3"><h3 className="font-semibold text-sm">{signing ? 'Подписанный документ' : 'Документы интеграции'}</h3><p className="text-xs text-muted-foreground">{signing ? `Нужна подписанная версия (${kinds.map(([, v]) => v).join(' или ')}) и подтверждение подписания: дата, подписанты, основание.` : 'Файл, согласованная редакция и подписанная версия учитываются отдельно. При подписании укажите дату, подписантов и основание подтверждения.'}</p>
    <input ref={input} className="hidden" type="file" onChange={(e) => void upload(e.target.files?.[0])} /><Button variant="outline" disabled={busy} onClick={() => input.current?.click()}>{signing ? 'Приложить подписанный файл' : 'Приложить файл'}</Button>
    {docs.isError && <div role="alert">Файлы не загрузились: {docs.error.message}<Button onClick={() => void docs.refetch()}>Повторить</Button></div>}
    {shown.map((d) => <div key={d.id} className="rounded border p-3 space-y-3"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">Вид документа<select className={selectClass} value={d.kind} onChange={(e) => change(d.id, { kind: e.target.value })}>{kinds.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label className="text-sm">Название<Input value={d.title} onChange={(e) => change(d.id, { title: e.target.value })} /></label>{!signing && <label className="text-sm">Редакция / номер<Input value={d.edition} onChange={(e) => change(d.id, { edition: e.target.value })} /></label>}</div>
      {(signing ? [['signedDocId', 'Подписанная версия']] as const : [['fileDocId', 'Файл'], ['agreedDocId', 'Согласованная редакция'], ['signedDocId', 'Подписанная версия']] as const).map(([field, label]) => <div key={field} className="flex gap-2 items-end"><label className="flex-1 min-w-0 text-sm">{label}<select className={selectClass} value={d[field]} onChange={(e) => change(d.id, { [field]: e.target.value })}><option value="">Не выбрана</option>{(docs.data || []).map((file) => <option key={file.id} value={file.id}>{file.title || file.fileName}</option>)}</select></label><Button variant="outline" disabled={!d[field]} onClick={() => void downloadSiteDoc(props.companyId, props.site.id, d[field]).catch((e) => toast.error(e.message))}>Скачать</Button></div>)}
      <label className="block text-sm">Подтверждение подписания<Textarea value={d.signingEvidence} onChange={(e) => change(d.id, { signingEvidence: e.target.value })} /></label><Button variant="ghost" onClick={() => setRows(rows.filter((r) => r.id !== d.id))}>Удалить запись документа</Button>
    </div>)}
    <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => setRows([...rows, { id: crypto.randomUUID(), kind: signing?.[0] ?? 'other', title: '', edition: '', fileDocId: '', agreedDocId: '', signedDocId: '', signingEvidence: '' }])}>{signing ? 'Выбрать уже приложенный файл' : 'Добавить документ'}</Button>{!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить редакции документов</Button>}</div>
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
    <PartnerSessionsRule key={`match:${query.data.data.revision}`} data={query.data.data} props={props} onSaved={refresh} />
    <ReconciliationsEditor key={`recon:${query.data.data.revision}`} data={query.data.data} props={props} onSaved={refresh} />
  </section>
}

/* ── Расчёты, испытания, сверки, версии перечней ─────────────────────────────
 * Каждая из этих вещей подтверждается фактом, а не «договорились»: испытание —
 * статусом и сессией, сверка — цифрами двух сторон, перечень — версией,
 * привязанной к подписанному документу, подключение — датой и основанием.
 */

type TaskSection = IntegrationTask['section']
// Пункт чек-листа закрывается данными не одного раздела: комиссию согласуют по
// сценариям и вместе с порядком расчётов, приёмку — протоколом в документах.
/**
 * Что показывать в окне пункта, если раздел по умолчанию ему не подходит.
 * `sections` — разделы окна (пусто — данных у пункта нет, только результат),
 * `fields` — поля первого раздела, относящиеся к пункту (остальные — по кнопке).
 * Карта на фронте: подтверждения пунктов привязаны к разделу на сервере (отпечаток
 * данных), и менять его значило бы сбросить уже подтверждённые пункты.
 */
const ITEM_VIEW: Record<string, { sections?: TaskSection[]; fields?: string[]; leadFields?: string[]; compact?: boolean; scenarios?: ScenarioView; fieldsBy?: Partial<Record<TaskSection, string[]>> }> = {
  '1.6': { scenarios: { lists: ['selectedIds'], lockHeader: true } },
  '2.1': { scenarios: { lists: [] } },
  // 2.2 было ~18 полей трёх разделов: нужны расчёты по сценариям и периодичность (06.10.2026)
  '2.2': { sections: ['scenarios', 'commercial', 'settlement'], fieldsBy: { commercial: ['commission', 'reporting'], settlement: ['period'] }, scenarios: { lists: [], terms: true, lockHeader: true } },
  '2.3': { sections: ['scenarios', 'commercial'], fieldsBy: { commercial: ['tariffs'] }, scenarios: { lists: [], terms: true, lockHeader: true } },
  '6.2': { sections: ['scenarios', 'settlement'], fieldsBy: { settlement: ['period', 'paymentTerm', 'documents', 'vat'] }, scenarios: { lists: [], terms: true, lockHeader: true } },
  '5.3': { scenarios: { lists: ['pilotIds'], lockHeader: true } }, '5.5': { scenarios: { lists: ['pilotIds'], lockHeader: true } },
  '6.6': { scenarios: { lists: ['agreedIds'], versions: true, lockHeader: true } },
  '6.7': { scenarios: { lists: ['agreedIds', 'connectedIds'], versions: true, marks: true, lockHeader: true } },
  // Заявка: кто, зачем, что за интеграция, какой договор, кто отвечает — без протоколов и перечней.
  '1.1': { sections: ['partner', 'lead'], fields: ['name', 'purpose'], leadFields: ['initiator'] },
  '1.2': { sections: ['scenarios', 'lead'], compact: true, leadFields: ['coverage'] },
  '1.3': { sections: ['lead'], leadFields: ['contractKind', 'payer'] },
  '1.4.1': { sections: ['lead'], leadFields: ['curatorUserId'] },
  '1.5': { fields: ['assessment'] }, '4.1': { fields: ['legalEntity'] },
  '1.4': { sections: [] }, '2.8': { sections: [] },
  '2.4': { fields: ['responsibilities', 'support'] }, '3.1': { fields: ['systems', 'protocol', 'version'] },
  '3.4': { fields: ['access', 'security'] }, '3.5': { fields: ['acceptanceCriteria'] }, '3.6': { fields: ['contacts'] },
  '5.1': { fields: ['access'] }, '6.5': { fields: ['support'] }, '6.13': { fields: ['productionAccess'] },
  '2.5': { fields: ['outgoing', 'incoming', 'statisticsUse'] }, '2.6': { fields: ['brand', 'appTransitions'] },
  '2.7': { fields: ['analytics', 'sessionHistory'] }, '3.2': { fields: ['outgoing', 'incoming'] }, '6.4': { fields: ['statisticsUse'] },
  '4.2': { fields: ['pilotDecision'] }, '6.12': { fields: ['launchDate'] },
  // 6.3 требует «Порядок сверки» из расчётов — раньше окно открывало коммерческие условия.
  '6.3': { sections: ['settlement'], fields: ['disputes'] },
  // Проверки на пилоте — это испытания, а не технические параметры.
  // 5.12: правило сессий — свой блок; 8 полей порядка расчётов и дубль «как выделяются» не нужны
  '5.12': { sections: [] },
  // 5.10: из пилота — итог и результаты проверок (решение о пилоте и дата запуска — другие пункты)
  '5.10': { sections: ['tests', 'work'], fieldsBy: { work: ['pilotOutcome', 'testResults'] } },
  '5.6': { sections: ['tests'] }, '5.7': { sections: ['tests'] }, '5.8': { sections: ['tests'] }, '5.9': { sections: ['tests'] },
  // Своих данных нет — подтверждаются результатом.
  '3.3': { sections: [] }, '5.2': { sections: [] }, '5.4': { sections: [] }, '6.1': { sections: [] },
  '6.8': { sections: [] }, '6.9': { sections: [] }, '6.10': { sections: [] }, '6.11': { sections: [] }, '6.15': { sections: [] },
}

/** Что нужно для подтверждения — видно сразу, а не из отказа после нажатия. */
function NeedLine({ task, item }: { task: IntegrationTask; item?: GateItem }) {
  if (item?.done && !item.needsConfirmation) return null
  // У пункта без своих данных пояснение даёт строка «Отдельных данных у пункта нет».
  if (!task.need && ITEM_VIEW[task.key]?.sections?.length === 0 && !['1.4', '5.12'].includes(task.key)) return null
  return task.need
    ? <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">Чтобы подтвердить пункт: {task.need}.</p>
    : task.dataRule
      ? <p className="text-xs text-muted-foreground">Данных для подтверждения достаточно — нажмите «Подтвердить выполнение» внизу окна.</p>
      : <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">Пункт подтверждается результатом проверки: запишите его в поле внизу окна (или приложите документ, поручение).</p>
}

/** Пункты о деньгах: при «Без расчётов» во всех сценариях их поля не нужны (сервер согласен). */
const MONEY_KEYS: Record<string, string> = { '2.2': 'комиссия, отчётность и периодичность расчётов', '2.3': 'цена для чужого клиента и правила тарифов (клиент платит по своему договору)', '6.2': 'порядок расчётов, срок оплаты, документы и НДС', '6.3': 'порядок разрешения расхождений по расчётам' }

const EXTRA_EDITORS: Record<string, TaskSection[]> = {
  '2.2': ['scenarios', 'settlement'], '2.3': ['scenarios'], '6.2': ['scenarios', 'settlement'],
  '5.10': ['work'], '5.11': ['documents'], '6.6': ['scenarios'],
}

function TaskEditor({ section, data, props, onSaved, only, compact, scenarioView, signing }: { section: TaskSection; data: IntegrationData; props: Props; onSaved: () => Promise<void>; only?: string[]; compact?: boolean; scenarioView?: ScenarioView; signing?: string[] }) {
  if (section === 'scenarios') return <ScenariosEditor data={data} props={props} onSaved={onSaved} compact={compact} view={scenarioView} />
  if (section === 'lead') return <LeadEditor data={data} props={props} onSaved={onSaved} only={only} />
  if (section === 'documents') return <DocumentsEditor data={data} props={props} onSaved={onSaved} signing={signing} />
  if (section === 'tests') return <TestsEditor data={data} props={props} onSaved={onSaved} />
  if (section === 'reconciliations') return <ReconciliationsEditor data={data} props={props} onSaved={onSaved} />
  return <SectionEditor section={section} data={data} props={props} onSaved={onSaved} only={only} />
}

const scenarioLabel = (s: IntegrationScenario) => s.name || `${INTEGRATION_DIRECTIONS[s.direction]} · ${INTEGRATION_FORMATS[s.format]}`

function ScenarioTerms({ scenario: s, onChange }: { scenario: IntegrationScenario; onChange: (patch: Partial<IntegrationScenario>) => void }) {
  const money = s.payer && s.payer !== 'none'
  return <fieldset className="grid gap-3 sm:grid-cols-3 rounded-md border p-2"><legend className="text-xs font-medium px-1">Расчёты по сценарию</legend>
    <label className="text-sm">Кто кому платит<select aria-label="Кто кому платит" className={selectClass} value={s.payer || ''} onChange={(e) => onChange({ payer: e.target.value as IntegrationScenario['payer'] })}><option value="">Не определено</option>{Object.entries(INTEGRATION_PAYERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
    {money && <label className="text-sm">Модель расчётов<select aria-label="Модель расчётов" className={selectClass} value={s.model || ''} onChange={(e) => onChange({ model: e.target.value as IntegrationScenario['model'] })}><option value="">Не определена</option>{Object.entries(INTEGRATION_MODELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>}
    {money && <label className="text-sm">Ставка / размер<Input aria-label="Ставка / размер" value={s.rate || ''} onChange={(e) => onChange({ rate: e.target.value })} placeholder="например, 7 % от выручки" /></label>}
    {money && <label className="text-sm">База расчёта<Input aria-label="База расчёта" value={s.base || ''} onChange={(e) => onChange({ base: e.target.value })} placeholder="выручка с НДС, кВт·ч…" /></label>}
    {s.format === 'roaming' && s.payer !== 'none' && <label className="text-sm">Цена для чужого клиента<Input aria-label="Цена для чужого клиента" value={s.clientPrice || ''} onChange={(e) => onChange({ clientPrice: e.target.value })} placeholder="наш розничный тариф, наценка…" /></label>}
    {money && <label className="text-sm">Эквайринг<Input aria-label="Эквайринг" value={s.acquiring || ''} onChange={(e) => onChange({ acquiring: e.target.value })} placeholder="кто принимает оплату и несёт комиссию" /></label>}
  </fieldset>
}

function RetiredWarning({ scenario, stations }: { scenario: IntegrationScenario; stations: IntegrationStation[] }) {
  const byId = new Map(stations.map((s) => [s.id, s]))
  const retired = [...new Set([...scenario.selectedIds, ...scenario.agreedIds, ...scenario.connectedIds])].filter((id) => isRetired(byId.get(id)))
  if (!retired.length) return null
  return <p role="alert" className="text-xs text-amber-700 dark:text-amber-400">
    В перечнях {retired.length} выбывших станций (закрыты или выведены из эксплуатации): {retired.slice(0, 5).map((id) => byId.get(id)?.name || id).join(', ')}{retired.length > 5 ? '…' : ''}. Исключите их из перечня и зафиксируйте новую версию.
  </p>
}

function ConnectionMarks({ scenario, onMark }: { scenario: IntegrationScenario; onMark: (at: string, basis: keyof typeof CONNECT_BASIS, ref: string) => void }) {
  const [at, setAt] = useState(new Date().toISOString().slice(0, 10))
  const [basis, setBasis] = useState<keyof typeof CONNECT_BASIS>('check')
  const [ref, setRef] = useState('')
  const inItem = !!useContext(PendingCtx)
  if (!scenario.connectedIds.length) return null
  const missing = scenario.connectedIds.filter((id) => !scenario.connectedMeta?.[id]?.at)
  if (!missing.length) return <p className="text-xs text-emerald-700 dark:text-emerald-400">Подключение подтверждено датой и основанием у всех {scenario.connectedIds.length} станций</p>
  return <div className="rounded-md border border-amber-500/40 p-2 space-y-2">
    <p className="text-xs">Без даты и основания подключения: {missing.length}. «Подключено» — факт: станция видна у принимающей стороны или по ней прошла сессия.</p>
    <div className="grid gap-2 sm:grid-cols-3">
      <label className="text-xs">Дата подключения<Input aria-label="Дата подключения" type="date" value={at} onChange={(e) => setAt(e.target.value)} /></label>
      <label className="text-xs">Основание<select aria-label="Основание подключения" className={selectClass} value={basis} onChange={(e) => setBasis(e.target.value as keyof typeof CONNECT_BASIS)}>{Object.entries(CONNECT_BASIS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="text-xs">Ссылка: сессия, скриншот, письмо<Input aria-label="Ссылка на подтверждение подключения" value={ref} onChange={(e) => setRef(e.target.value)} /></label>
    </div>
    <Button variant="outline" size="sm" disabled={!at} onClick={() => onMark(at, basis, ref)}>Отметить подключение ({missing.length}){inItem ? '' : ' — затем сохраните перечни'}</Button>
  </div>
}

function ListVersions({ scenario, saved, data, props, onSaved }: { scenario: IntegrationScenario; saved?: IntegrationScenario; data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  // В окне пункта перечень и договор — ещё черновик: фиксация версии сохраняет их вместе
  // с версией одним запросом (раньше: «сохраните сценарии» — а кнопки сохранения нет).
  const pending = useContext(PendingCtx)
  const allDocs = (pending?.current.documents as IntegrationDocument[] | undefined) ?? data.documents
  const [documentId, setDocumentId] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const versions = (data.listVersions.filter((v) => 'version' in v && v.scenarioId === scenario.id) as IntegrationListVersion[]).sort((a, b) => a.version - b.version)
  const last = versions.at(-1)
  const agreed = pending ? scenario.agreedIds : saved?.agreedIds ?? []
  const unsaved = !pending && [...agreed].sort().join() !== [...scenario.agreedIds].sort().join()
  const added = last ? agreed.filter((id) => !last.stationIds.includes(id)).length : 0
  const removed = last ? last.stationIds.filter((id) => !agreed.includes(id)).length : 0
  const docs = allDocs.filter((d) => d.kind === 'stations' || d.kind === 'contract')
  const docTitle = (id: string) => { const d = allDocs.find((x) => x.id === id); return d ? `${d.title || DOC_KINDS[d.kind]}${d.edition ? `, ${d.edition}` : ''}${d.signedDocId ? ' · подписан' : ' · не подписан'}` : 'документ удалён' }
  const fix = async () => {
    setBusy(true)
    try {
      await saveIntegration(props.companyId, props.site.id, { revision: data.revision, ...(pending?.current ?? {}), listVersions: [...data.listVersions, { scenarioId: scenario.id, documentId, note }] })
      if (pending) pending.current = {}
      await onSaved(); toast.success('Версия перечня зафиксирована')
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось зафиксировать версию') }
    finally { setBusy(false) }
  }
  return <div className="rounded-md border p-2 space-y-2">
    <p className="text-xs font-medium">Версии согласованного перечня</p>
    {versions.length === 0 ? <p className="text-xs text-muted-foreground">{agreed.length ? 'Версия не зафиксирована — она нужна для договора (пункт 6.6) и запуска (6.7)' : 'Сначала согласуйте перечень станций'}</p>
      : <ul className="text-xs space-y-1">{versions.map((v) => <li key={v.id}>Версия {v.version} · {v.stationIds.length} ЭЗС · {docTitle(v.documentId)}{v.byName ? ` · ${v.byName}` : ''}{v.at ? `, ${new Date(v.at).toLocaleDateString('ru-RU')}` : ''}{v.note ? ` — ${v.note}` : ''}</li>)}</ul>}
    {last && (added > 0 || removed > 0) && <p role="alert" className="text-xs text-amber-700 dark:text-amber-400">Согласованный перечень изменён после версии {last.version}: +{added} / −{removed}. Зафиксируйте новую версию с допсоглашением.</p>}
    {agreed.length > 0 && (!last || added > 0 || removed > 0) && <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] items-end">
      <label className="text-xs">Документ версии<select aria-label="Документ версии перечня" className={selectClass} value={documentId} onChange={(e) => setDocumentId(e.target.value)}><option value="">Выберите перечень или договор</option>{docs.map((d) => <option key={d.id} value={d.id}>{docTitle(d.id)}</option>)}</select></label>
      <label className="text-xs">Комментарий<Input aria-label="Комментарий к версии перечня" value={note} onChange={(e) => setNote(e.target.value)} placeholder="приложение 1 к договору, допсоглашение №…" /></label>
      <Button size="sm" variant="outline" disabled={busy || unsaved || !documentId} onClick={() => void fix()}>Зафиксировать версию {versions.length + 1} ({agreed.length} ЭЗС)</Button>
    </div>}
    {unsaved && <p className="text-xs text-muted-foreground">Перечень изменён — сохраните сценарии, затем фиксируйте версию.</p>}
    {agreed.length > 0 && docs.length === 0 && <p className="text-xs text-muted-foreground">Добавьте документ «Перечень ЭЗС» или договор во вкладке «Документы».</p>}
  </div>
}

// Типовые испытания по сценарию. Информационный обмен проверяет публикацию, роуминг —
// ещё и запуск, оплату, передачу сессии и её след в учёте.
const TEST_TEMPLATES: Record<'information' | 'roaming', [string, boolean][]> = {
  information: [
    ['Станции, адреса и разъёмы опубликованы у принимающей стороны', true],
    ['Статусы станций обновляются у принимающей стороны', true],
    ['Цены отображаются верно', true],
    ['Снятие станции с публикации доходит до принимающей стороны', false],
  ],
  roaming: [
    ['Авторизация клиента партнёра: токен или карта', true],
    ['Старт и стоп зарядки', true],
    ['Завершённая сессия передана: кВт·ч, длительность, стоимость', true],
    ['Сессия видна в учёте как сессия партнёра', true],
    ['Обрыв связи и недоступность станции обработаны', true],
    ['Обращение клиента передано в поддержку', false],
  ],
}

function TestsEditor({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState<IntegrationTest[]>(data.tests)
  const [busy, setBusy] = useState(false)
  const inItem = usePending('tests', rows, data.tests)
  const change = (id: string, patch: Partial<IntegrationTest>) => setRows(rows.map((x) => x.id === id ? { ...x, ...patch } : x))
  const addTypical = () => {
    const next = [...rows]
    for (const s of data.scenarios) {
      const templates = [...TEST_TEMPLATES.information, ...(s.format === 'roaming' ? TEST_TEMPLATES.roaming : [])]
      for (const [title, required] of templates) {
        if (!next.some((x) => x.scenarioId === s.id && x.title === title)) next.push({ id: crypto.randomUUID(), scenarioId: s.id, title, required, status: 'pending', sessionRef: '', comment: '', docId: '' })
      }
    }
    setRows(next)
  }
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, tests: rows }); await onSaved(); toast.success('Испытания сохранены') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить испытания') }
    finally { setBusy(false) }
  }
  const req = rows.filter((x) => x.required)
  const passed = req.filter((x) => x.status === 'passed' || x.status === 'na').length
  return <section className="rounded-lg border p-3 space-y-3">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-semibold text-sm">Испытания</h3>
      <span className="text-xs text-muted-foreground">обязательных пройдено {passed} из {req.length}{rows.some((x) => x.status === 'failed') ? ' · есть замечания' : ''}</span></div>
    <p className="text-xs text-muted-foreground">Каждая проверка — статус, тестовая сессия и автор. Пункт 5.10 закрывается, когда обязательные пройдены; 5.11 — подписанным протоколом испытаний (в окне пункта 5.11).</p>
    {data.scenarios.length === 0 && <p className="text-xs">Сначала задайте сценарии подключения в паспорте.</p>}
    {rows.map((x) => {
      const scenario = data.scenarios.find((s) => s.id === x.scenarioId)
      return <div key={x.id} className="rounded-md border p-2 space-y-2">
        {/* Типовое испытание называется регламентом — его текст не правят, только своё. */}
        <div className="flex flex-col sm:flex-row sm:items-start gap-2">{x.scenarioId ? <p data-testid="test-title" className="flex-1 text-sm font-medium">{x.title}</p>
          : <Input aria-label="Испытание" className="flex-1 min-w-0" value={x.title} onChange={(e) => change(x.id, { title: e.target.value })} />}
          <label className="flex items-center gap-1 text-xs min-h-9"><input type="checkbox" checked={x.required} onChange={(e) => change(x.id, { required: e.target.checked })} />обязательное</label></div>
        <div className="text-xs text-muted-foreground">{scenario ? scenarioLabel(scenario) : 'Общее для интеграции'}{x.byName ? ` · ${x.status === 'pending' ? 'добавил' : TEST_STATUSES[x.status]}: ${x.byName}${x.at ? `, ${new Date(x.at).toLocaleString('ru-RU')}` : ''}` : ''}</div>
        <div className="grid gap-2 sm:grid-cols-[180px_1fr_1fr_auto] items-end">
          <label className="text-xs">Статус<select aria-label={`Статус: ${x.title}`} className={selectClass} value={x.status} onChange={(e) => change(x.id, { status: e.target.value as IntegrationTest['status'] })}>{Object.entries(TEST_STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="text-xs">Тестовая сессия<Input aria-label={`Тестовая сессия: ${x.title}`} value={x.sessionRef} onChange={(e) => change(x.id, { sessionRef: e.target.value })} placeholder="номер сессии у нас / у партнёра" /></label>
          <label className="text-xs">{x.status === 'failed' ? 'Замечание' : x.status === 'na' ? 'Почему неприменимо' : 'Комментарий'}<Input aria-label={`Комментарий: ${x.title}`} value={x.comment} onChange={(e) => change(x.id, { comment: e.target.value })} /></label>
          <Button variant="ghost" size="sm" onClick={() => setRows(rows.filter((r) => r.id !== x.id))}>Убрать</Button>
        </div>
      </div>
    })}
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={!data.scenarios.length} onClick={addTypical}>Добавить типовые испытания по сценариям</Button>
      <Button variant="outline" onClick={() => setRows([...rows, { id: crypto.randomUUID(), scenarioId: '', title: 'Новое испытание', required: false, status: 'pending', sessionRef: '', comment: '', docId: '' }])}>Своё испытание</Button>
      {!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить испытания</Button>}
    </div>
  </section>
}

const RECON_KINDS = { pilot: 'Пробная по пилоту', monthly: 'Месячная' }
const RECON_STATE = { empty: ['Нет цифр — внесите сессии, кВт·ч и суммы', 'text-muted-foreground'], match: ['Сходится', 'text-emerald-700 dark:text-emerald-400'], resolved: ['Расхождение урегулировано', 'text-sky-700 dark:text-sky-400'], diff: ['Расхождение', 'text-red-600 dark:text-red-400'] } as const

function ReconciliationsEditor({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState<IntegrationReconciliation[]>(data.reconciliations)
  const [busy, setBusy] = useState(false)
  const inItem = usePending('reconciliations', rows, data.reconciliations)
  const docs = useQuery({ queryKey: ['site-docs', props.companyId, props.site.id], queryFn: () => getSiteDocs(props.companyId, props.site.id) })
  const change = (id: string, patch: Partial<IntegrationReconciliation>) => setRows(rows.map((r) => r.id === id ? { ...r, ...patch } : r))
  const add = (kind: IntegrationReconciliation['kind']) => setRows([...rows, { id: crypto.randomUUID(), kind, period: '', resolution: '', docId: '', ours: { sessions: 0, kwh: 0, amount: 0 }, partner: { sessions: 0, kwh: 0, amount: 0 } }])
  const save = async () => {
    setBusy(true)
    try { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, reconciliations: rows }); await onSaved(); toast.success('Сверки сохранены') }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить сверки') }
    finally { setBusy(false) }
  }
  const cols = [['sessions', 'Сессии'], ['kwh', 'кВт·ч'], ['amount', 'Сумма, ₽']] as const
  // «Наш учёт» не вводится руками: он считается по сессиям партнёра из учёта за даты
  // сверки. Руками вводится только сторона партнёра — из его отчёта.
  const fillOurs = async (r: IntegrationReconciliation) => {
    try {
      const res = await getPartnerSessions(props.companyId, props.site.id, r.from, r.to)
      change(r.id, { ours: { ...res.total } })
      toast.success(`Из учёта: ${res.total.sessions} сессий, ${res.total.kwh} кВт·ч, ${res.total.amount} ₽ — сохраните сверку`)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось посчитать сессии') }
  }
  return <section className="rounded-md border p-3 space-y-3 mt-3">
    <h3 className="text-sm font-semibold">Сверки с партнёром</h3>
    <p className="text-xs text-muted-foreground">Цифры двух сторон: сессии — штука в штуку, кВт·ч и деньги — до 0,1 кВт·ч и 1 ₽. Расхождение закрывается только урегулированием с актом. Пробная сверка закрывает пункт 5.13, первая месячная с подписанным актом — 6.14; дальше сверка — регулярная работа «Эксплуатации».</p>
    {rows.map((r) => {
      const [label, cls] = RECON_STATE[reconState(r)]
      return <div key={r.id} className="rounded border p-2 space-y-2">
        <div className="grid gap-2 sm:grid-cols-[200px_1fr_auto] items-end">
          <label className="text-xs">Вид<select aria-label="Вид сверки" className={selectClass} value={r.kind} onChange={(e) => change(r.id, { kind: e.target.value as IntegrationReconciliation['kind'] })}>{Object.entries(RECON_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="text-xs">Период<Input aria-label="Период сверки" value={r.period} onChange={(e) => change(r.id, { period: e.target.value })} placeholder="пилот 01–14.11 / ноябрь 2026" /></label>
          <span className={`text-xs font-medium ${cls}`}>{label}</span>
        </div>
        <div className="grid gap-2 grid-cols-2 sm:grid-cols-[1fr_1fr_auto] items-end">
          <label className="text-xs">С<Input aria-label="Начало периода сверки" type="date" value={r.from || ''} onChange={(e) => change(r.id, { from: e.target.value })} /></label>
          <label className="text-xs">По<Input aria-label="Конец периода сверки" type="date" value={r.to || ''} onChange={(e) => change(r.id, { to: e.target.value })} /></label>
          <Button className="col-span-2 sm:col-span-1" variant="outline" size="sm" disabled={!r.from || !r.to || !data.settlement.matchKind} title={data.settlement.matchKind ? undefined : 'Сначала задайте правило выделения сессий партнёра'}
            onClick={() => void fillOurs(r)}>Наш учёт из сессий</Button>
        </div>
        <div className="overflow-x-auto"><table className="w-full text-xs table-fixed"><thead><tr className="text-muted-foreground text-left"><th className="p-1 font-medium w-24 sm:w-32" />{cols.map(([, l]) => <th key={l} className="p-1 font-medium">{l}</th>)}</tr></thead>
          <tbody>{(['ours', 'partner'] as const).map((side) => <tr key={side}><td className="p-1 whitespace-nowrap">{side === 'ours' ? 'Наш учёт' : 'Отчёт партнёра'}</td>
            {cols.map(([k, l]) => <td key={k} className="p-1"><Input aria-label={`${side === 'ours' ? 'Наш учёт' : 'Отчёт партнёра'}: ${l}`} type="number" min={0} step="any" className="h-9 min-w-0 w-full px-2" value={r[side][k]} onChange={(e) => change(r.id, { [side]: { ...r[side], [k]: e.target.value === '' ? 0 : Number(e.target.value) } })} /></td>)}</tr>)}</tbody></table></div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">Урегулирование расхождения<Textarea aria-label="Урегулирование расхождения" rows={2} value={r.resolution} onChange={(e) => change(r.id, { resolution: e.target.value })} placeholder="что не сошлось и как решили" /></label>
          <label className="text-xs">Акт сверки<select aria-label="Акт сверки" className={selectClass} value={r.docId} onChange={(e) => change(r.id, { docId: e.target.value })}><option value="">Не приложен</option>{(docs.data || []).map((d) => <option key={d.id} value={d.id}>{d.title || d.fileName}</option>)}</select></label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span>{r.byName ? `${r.byName}${r.at ? `, ${new Date(r.at).toLocaleString('ru-RU')}` : ''}` : 'не сохранена'}</span><Button variant="ghost" size="sm" onClick={() => setRows(rows.filter((x) => x.id !== r.id))}>Убрать</Button></div>
      </div>
    })}
    <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => add('pilot')}>Пробная сверка по пилоту</Button><Button variant="outline" onClick={() => add('monthly')}>Месячная сверка</Button>{!inItem && <Button disabled={busy} onClick={() => void save()}>Сохранить сверки</Button>}</div>
  </section>
}

/** Как сессии партнёра находятся в нашем учёте — и проверка правила на живых сессиях. */
function PartnerSessionsRule({ data, props, onSaved }: { data: IntegrationData; props: Props; onSaved: () => Promise<void> }) {
  const [kind, setKind] = useState(data.settlement.matchKind || '')
  const [values, setValues] = useState(data.settlement.matchValues || '')
  const [busy, setBusy] = useState(false)
  // Результат проверки — в кэше запросов: сохранение правила меняет ревизию, и блок
  // перерисовывается заново; локальное состояние терялось вместе с найденными сессиями.
  const qc = useQueryClient()
  const checkKey = ['partner-sessions-check', props.companyId, props.site.id]
  const check = useQuery({ queryKey: checkKey, queryFn: () => getPartnerSessions(props.companyId, props.site.id), enabled: false }).data ?? null
  const dirty = kind !== (data.settlement.matchKind || '') || values !== (data.settlement.matchValues || '')
  usePending('settlement', dirty ? { ...data.settlement, matchKind: kind, matchValues: values } : data.settlement, data.settlement)
  // Проверка идёт по сохранённому правилу: несохранённое сохраняем тут же, одной кнопкой.
  const run = async () => {
    setBusy(true)
    try {
      if (dirty) { await saveIntegration(props.companyId, props.site.id, { revision: data.revision, settlement: { ...data.settlement, matchKind: kind, matchValues: values } }); await onSaved() }
      await qc.fetchQuery({ queryKey: checkKey, queryFn: () => getPartnerSessions(props.companyId, props.site.id), staleTime: 0 })
    }
    catch (e) { qc.removeQueries({ queryKey: checkKey }); toast.error(e instanceof Error ? e.message : 'Проверка не удалась') }
    finally { setBusy(false) }
  }
  const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
  return <section className="rounded-md border p-3 space-y-3 mt-3">
    <h3 className="text-sm font-semibold">Сессии партнёра в учёте</h3>
    <p className="text-xs text-muted-foreground">Без правила сессии партнёра не отличить от остальных, и сверка невозможна. Клиенты партнёра обычно заряжаются под договорным аккаунтом его юрлица — укажите номер аккаунта (или юрлицо, или номера карт) и проверьте на тестовой сессии. Пункт 5.12.</p>
    <div className="grid gap-2 sm:grid-cols-[240px_1fr]">
      <label className="text-xs">Как находить<select aria-label="Как находить сессии партнёра" className={selectClass} value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Не задано</option>{Object.entries(MATCH_KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      <label className="text-xs">Значения — по одному в строке или через запятую<Textarea aria-label="Значения правила сессий партнёра" rows={2} value={values} onChange={(e) => setValues(e.target.value)} placeholder={kind === 'client' ? 'ООО «Партнёр»' : kind === 'card' ? '0123456789' : 'номер аккаунта в АСУиМ'} /></label>
    </div>
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !kind || !values.trim()} onClick={() => void run()}>{dirty ? 'Сохранить и проверить за 90 дней' : 'Проверить за 90 дней'}</Button></div>
    {check && <div className="space-y-1 text-xs" role="status">
      <p className="font-medium">{check.total.sessions ? `Найдено ${nf.format(check.total.sessions)} сессий · ${nf.format(check.total.kwh)} кВт·ч · ${nf.format(check.total.amount)} ₽ (${check.from} — ${check.to})` : `За ${check.from} — ${check.to} сессий по правилу нет: проведите тестовую сессию и проверьте снова`}</p>
      {check.byMonth.length > 0 && <p className="text-muted-foreground">{check.byMonth.map((m) => `${m.month}: ${m.sessions}`).join(' · ')}</p>}
      {check.sample.length > 0 && <ul className="text-muted-foreground">{check.sample.map((s, i) => <li key={i}>{s.at ? new Date(s.at).toLocaleString('ru-RU') : '—'} · {s.station || '—'} · {s.client || s.card || '—'} · {nf.format(s.kwh)} кВт·ч · {nf.format(s.amount)} ₽</li>)}</ul>}
    </div>}
  </section>
}
