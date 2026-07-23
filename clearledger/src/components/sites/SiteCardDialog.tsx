/**
 * Карточка площадки банка ЗУ — рабочее место, а не просмотр.
 *
 * Три вкладки по вопросу, на который отвечают:
 *   Работа   — где площадка в воронке, что закрыто на гейте, кто ведёт, что дальше;
 *   Паспорт  — данные объекта (право, техприсоединение, экономика), правятся руками;
 *   История  — стадии, касания, правки, импорт.
 *
 * Правка любого поля помечает его «ручным»: следующий импорт файла его не тронет
 * (см. `manual_fields` в ezs_site_work.py). Перевод стадии при незакрытом гейте
 * не блокируется — предупреждение уходит в историю, решение остаётся за человеком.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2, ExternalLink, Check, Circle, Save, MessageSquarePlus, AlertTriangle, Upload, Trash2, Lock } from 'lucide-react'
import { toast } from 'sonner'
import {
  getSite, getSiteEvents, getSiteMembers, getSiteEconomics, getProjectContext, getSiteDocs,
  patchSite, moveSiteStage, markSiteGate, addSiteEvent, uploadSiteDoc, deleteSiteDoc,
  saveTechConnection, saveCost, deleteCost, saveEquipment, deleteEquipment,
  STAGE_META, FUNNEL_STAGES, QUADRANT_META,
  type SiteDetail, type SiteStage, type ProjectContext,
} from '@/services/sitesService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const TABS = [
  { k: 'work', label: 'Работа' },
  { k: 'passport', label: 'Паспорт' },
  { k: 'tp', label: 'Присоединение' },
  { k: 'equipment', label: 'Оборудование' },
  { k: 'docs', label: 'Документы' },
  { k: 'economics', label: 'Экономика' },
  { k: 'accounting', label: 'Учёт' },
  { k: 'history', label: 'История' },
] as const
type Tab = (typeof TABS)[number]['k']

const CONTROL_FORMS = ['аренда', 'сервитут', 'разрешение на размещение', 'собственность', 'соглашение с ТЦ']

export function SiteCardDialog({ companyId, id, onClose }: {
  companyId: string; id: string; onClose: () => void
}) {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('work')
  const q = useQuery({ queryKey: ['site-detail', companyId, id], queryFn: () => getSite(companyId, id) })
  const s = q.data

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ['site-detail', companyId, id] })
    await qc.invalidateQueries({ queryKey: ['sites-list', companyId] })
    await qc.invalidateQueries({ queryKey: ['sites-overview', companyId] })
    await qc.invalidateQueries({ queryKey: ['site-events', companyId, id] })
    await qc.invalidateQueries({ queryKey: ['site-project', companyId, id] })
    await qc.invalidateQueries({ queryKey: ['site-docs', companyId, id] })
    await qc.invalidateQueries({ queryKey: ['pr-portfolio', companyId] })
    await qc.invalidateQueries({ queryKey: ['pr-tc', companyId] })
  }

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-3xl w-[94vw] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base pr-6 flex flex-wrap items-center gap-2">
            {s?.projectNo && <span className="font-mono text-xs text-muted-foreground">{s.projectNo}</span>}
            {s ? (s.title || s.fullAddress || [s.region, s.city].filter(Boolean).join(', ') || 'Проект') : 'Проект'}
            {s && (
              <span className={`text-[11px] rounded border px-1.5 py-0.5 ${STAGE_META[s.stage]?.cls ?? ''}`}
                title={STAGE_META[s.stage]?.hint}>{s.stageLabel}</span>
            )}
          </DialogTitle>
        </DialogHeader>

        {q.isLoading || !s ? (
          <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : (
          <>
            <div className="inline-flex rounded-md border border-border p-0.5 gap-0.5 w-fit">
              {TABS.map((t) => (
                <button key={t.k} type="button" onClick={() => setTab(t.k)}
                  className={`px-3 py-1 text-xs rounded-[5px] transition-colors ${tab === t.k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {t.label}
                </button>
              ))}
            </div>
            {tab === 'work' && <WorkTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'passport' && <PassportTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'tp' && <TechConnectionTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'equipment' && <EquipmentTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'docs' && <DocsTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'economics' && <EconomicsTab site={s} companyId={companyId} />}
            {tab === 'accounting' && <AccountingTab site={s} companyId={companyId} onDone={refresh} />}
            {tab === 'history' && <HistoryTab site={s} companyId={companyId} />}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

/* ── Вкладка «Работа» ───────────────────────────────────────────────────── */

function WorkTab({ site, companyId, onDone }: { site: SiteDetail; companyId: string; onDone: () => Promise<void> }) {
  const [stage, setStage] = useState<SiteStage>(site.stage)
  const [reason, setReason] = useState('')
  const [owner, setOwner] = useState(site.ownerUserId ?? '')
  const [next, setNext] = useState(site.nextAction ?? '')
  const [due, setDue] = useState(site.nextActionDue ?? '')
  const [touch, setTouch] = useState('')

  useEffect(() => {
    setStage(site.stage); setOwner(site.ownerUserId ?? '')
    setNext(site.nextAction ?? ''); setDue(site.nextActionDue ?? '')
  }, [site])

  const members = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })
  const gate = site.gate
  const missing = gate.items.filter((i) => !i.done)

  const [override, setOverride] = useState(false)
  const [blocked, setBlocked] = useState<string[] | null>(null)
  const [mayOverride, setMayOverride] = useState(false)

  const mMove = useMutation({
    mutationFn: () => moveSiteStage(companyId, site.id, stage, reason || undefined, override),
    onSuccess: async (r) => {
      setMayOverride(!!r.mayOverride)
      if (!r.moved && r.blocked) {
        // Обязательные пункты гейта держат переход — это не ошибка сети, а правило.
        setBlocked(r.blocking ?? [])
        toast.warning(r.message ?? 'Переход заблокирован гейтом')
        return
      }
      setBlocked(null); setOverride(false); setReason('')
      toast.success(r.overridden ? 'Стадия изменена в обход гейта — запись в истории'
                                 : 'Стадия изменена')
      await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось сменить стадию'),
  })
  const mSave = useMutation({
    mutationFn: () => patchSite(companyId, site.id, {
      owner_user_id: owner || null, next_action: next || null, next_action_due: due || null,
    }),
    onSuccess: async () => { toast.success('Сохранено'); await onDone() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось сохранить'),
  })
  const mGate = useMutation({
    mutationFn: (p: { key: string; done: boolean }) => markSiteGate(companyId, site.id, p.key, p.done),
    onSuccess: async () => { await onDone() },
  })
  const mTouch = useMutation({
    mutationFn: () => addSiteEvent(companyId, site.id, touch, 'touch'),
    onSuccess: async () => { setTouch(''); toast.success('Записано'); await onDone() },
  })

  const overdue = !!due && due < new Date().toISOString().slice(0, 10)

  return (
    <div className="space-y-4">
      {/* Гейт текущей стадии */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40 flex items-center justify-between">
          <span>Гейт стадии «{gate.stageLabel}»</span>
          <span className={`font-mono ${gate.done === gate.total ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>
            {gate.done} / {gate.total}
          </span>
        </div>
        <div className="p-2 space-y-1">
          {gate.items.length === 0 && <div className="text-xs text-muted-foreground px-1 py-1">Для этой стадии проверок нет.</div>}
          {gate.items.map((it) => (
            <div key={it.key} className="flex items-center gap-2 text-xs px-1 py-0.5">
              {it.manual ? (
                <button type="button" disabled={mGate.isPending}
                  onClick={() => mGate.mutate({ key: it.key, done: !it.done })}
                  className="shrink-0 text-muted-foreground hover:text-foreground">
                  {it.done ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" /> : <Circle className="h-3.5 w-3.5" />}
                </button>
              ) : (
                <span className="shrink-0">
                  {it.done ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" /> : <Circle className="h-3.5 w-3.5 text-muted-foreground" />}
                </span>
              )}
              <span className={it.done ? '' : 'text-muted-foreground'}>{it.label}</span>
              {it.required && <span className="text-[10px] text-red-500/80" title="Обязательно для перехода">обязательно</span>}
              {it.doc && <span className="text-[10px] text-muted-foreground">— вкладка «Документы»</span>}
              {!it.manual && !it.doc && <span className="text-[10px] text-muted-foreground">— из полей паспорта</span>}
            </div>
          ))}
        </div>
      </section>

      {/* Перевод стадии */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-xs font-semibold">Стадия</div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={stage} onValueChange={(v) => setStage(v as SiteStage)}>
            <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {FUNNEL_STAGES.map((st) => (
                <SelectItem key={st} value={st} className="text-xs">{STAGE_META[st].label}</SelectItem>
              ))}
              <SelectItem value="on_hold" className="text-xs">{STAGE_META.on_hold.label}</SelectItem>
              <SelectItem value="archive" className="text-xs">{STAGE_META.archive.label}</SelectItem>
            </SelectContent>
          </Select>
          <Input value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={stage === 'archive' ? 'Причина отклонения (обязательна по смыслу)' : 'Комментарий к переходу'}
            className="h-8 text-xs flex-1 min-w-[220px]" />
          <Button size="sm" className="h-8 text-xs" disabled={stage === site.stage || mMove.isPending}
            onClick={() => mMove.mutate()}>
            {mMove.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Перевести
          </Button>
        </div>
        {stage !== site.stage && gate.blocking.length > 0 && (
          <div className="flex items-start gap-1.5 text-[11px] text-red-600 dark:text-red-400">
            <Lock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              Обязательное не закрыто: {gate.blocking.join('; ')}. Пока эти пункты не выполнены,
              двигаться вперёд нельзя.
            </span>
          </div>
        )}
        {stage !== site.stage && gate.blocking.length === 0 && missing.length > 0 && (
          <div className="flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>Не закрыто (необязательное): {missing.map((m) => m.label).join('; ')}. Перевод возможен — запись останется в истории.</span>
          </div>
        )}
        {blocked && mayOverride && (
          <label className="flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-amber-400">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5" />
            <span>
              Провести в обход гейта под мою ответственность. Нужно обоснование — оно попадёт в
              историю проекта отдельной записью.
            </span>
          </label>
        )}
        {blocked && !mayOverride && (
          <div className="text-[11px] text-muted-foreground">
            Обход обязательных пунктов доступен администратору компании.
          </div>
        )}
        <div className="text-[11px] text-muted-foreground">
          В стадии с {site.stageSince ?? '—'}
          {site.prevStage ? ` · до этого «${STAGE_META[site.prevStage]?.label ?? site.prevStage}»` : ''}
        </div>
      </section>

      {/* Ответственный и следующий шаг */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-xs font-semibold">Кто ведёт и что дальше</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <div>
            <Label>Ответственный</Label>
            <Select value={owner || '__none__'} onValueChange={(v) => setOwner(v === '__none__' ? '' : v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Не назначен" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__" className="text-xs">Не назначен</SelectItem>
                {(members.data ?? []).map((m) => (
                  <SelectItem key={m.id} value={m.id} className="text-xs">{m.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <Label>Следующий шаг</Label>
            <Input value={next} onChange={(e) => setNext(e.target.value)} className="h-8 text-xs"
              placeholder="Например: запросить ТУ у сетевой организации" />
          </div>
          <div>
            <Label>Срок</Label>
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)}
              className={`h-8 text-xs ${overdue ? 'border-red-400/60' : ''}`} />
          </div>
          <div className="flex items-end">
            <Button size="sm" variant="outline" className="h-8 text-xs" disabled={mSave.isPending}
              onClick={() => mSave.mutate()}>
              <Save className="h-3.5 w-3.5 mr-1" />Сохранить
            </Button>
          </div>
          <div className="flex items-end text-[11px] text-muted-foreground">
            Последнее касание: {fmtDate(site.lastTouchAt) || '—'}
          </div>
        </div>
      </section>

      {/* Касание */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-xs font-semibold">Записать касание</div>
        <div className="flex items-start gap-2">
          <Textarea value={touch} onChange={(e) => setTouch(e.target.value)} rows={2}
            placeholder="Звонок, письмо, встреча — что обсудили и о чём договорились"
            className="text-xs min-h-[52px]" />
          <Button size="sm" className="h-8 text-xs shrink-0" disabled={!touch.trim() || mTouch.isPending}
            onClick={() => mTouch.mutate()}>
            <MessageSquarePlus className="h-3.5 w-3.5 mr-1" />Записать
          </Button>
        </div>
      </section>
    </div>
  )
}

/* ── Вкладка «Паспорт» ──────────────────────────────────────────────────── */

const PASSPORT_GROUPS: { title: string; fields: { k: keyof SiteDetail; label: string; type?: 'number' | 'date' | 'text' | 'area' | 'select'; options?: string[] }[] }[] = [
  {
    title: 'Объект',
    fields: [
      { k: 'cadastralNo', label: 'Кадастровый номер' },
      { k: 'region', label: 'Регион' },
      { k: 'city', label: 'Город' },
      { k: 'address', label: 'Адрес' },
      { k: 'installPlace', label: 'Место установки' },
      { k: 'placeKind', label: 'Тип места', type: 'select', options: ['город', 'трасса'] },
      { k: 'lat', label: 'Широта', type: 'number' },
      { k: 'lon', label: 'Долгота', type: 'number' },
      { k: 'areaM2', label: 'Площадь, м²', type: 'number' },
    ],
  },
  {
    title: 'Право на землю',
    fields: [
      { k: 'owner', label: 'Собственник' },
      { k: 'controlForm', label: 'Форма контроля', type: 'select', options: CONTROL_FORMS },
      { k: 'landCategory', label: 'Категория земель' },
      { k: 'permittedUse', label: 'Вид разрешённого использования' },
      { k: 'encumbrances', label: 'Обременения', type: 'area' },
      { k: 'rentRate', label: 'Ставка аренды, ₽/мес', type: 'number' },
      { k: 'contractStart', label: 'Договор с', type: 'date' },
      { k: 'contractEnd', label: 'Договор по', type: 'date' },
    ],
  },
  {
    title: 'Техприсоединение',
    fields: [
      { k: 'freePowerNum', label: 'Свободная мощность, кВт', type: 'number' },
      { k: 'distanceToTpM', label: 'Расстояние до ТП, м', type: 'number' },
      { k: 'tpCost', label: 'Стоимость ТП, ₽', type: 'number' },
      { k: 'tpTermMonths', label: 'Срок мероприятий, мес.', type: 'number' },
      { k: 'techConnType', label: 'Тип присоединения' },
      { k: 'connectionCost', label: 'Итого затраты на подключение, ₽', type: 'number' },
    ],
  },
  {
    title: 'План и участники',
    fields: [
      { k: 'plannedEzsCount', label: 'ЭЗС к установке, шт', type: 'number' },
      { k: 'plannedPowerKwt', label: 'Мощность к установке, кВт', type: 'number' },
      { k: 'supplier', label: 'Поставщик' },
      { k: 'contractor', label: 'Подрядчик' },
      { k: 'tuStatus', label: 'Статус согласования / ТУ', type: 'area' },
      { k: 'comment', label: 'Комментарий', type: 'area' },
    ],
  },
]

// camelCase карточки → snake_case API.
const API_FIELD: Record<string, string> = {
  cadastralNo: 'cadastral_no', installPlace: 'install_place', placeKind: 'place_kind',
  areaM2: 'area_m2', controlForm: 'control_form', landCategory: 'land_category',
  permittedUse: 'permitted_use', rentRate: 'rent_rate', contractStart: 'contract_start',
  contractEnd: 'contract_end', freePowerNum: 'free_power_num', distanceToTpM: 'distance_to_tp_m',
  tpCost: 'tp_cost', tpTermMonths: 'tp_term_months', techConnType: 'tech_conn_type',
  connectionCost: 'connection_cost', plannedEzsCount: 'planned_ezs_count',
  plannedPowerKwt: 'planned_power_kwt', tuStatus: 'tu_status', fullAddress: 'full_address',
  mapUrl: 'map_url', rentCostMonth: 'rent_cost_month', dopService: 'dop_service',
  archiveReason: 'archive_reason',
}

function PassportTab({ site, companyId, onDone }: { site: SiteDetail; companyId: string; onDone: () => Promise<void> }) {
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [showRaw, setShowRaw] = useState(false)
  useEffect(() => setDraft({}), [site])

  const dirty = Object.keys(draft).length > 0
  const m = useMutation({
    mutationFn: () => patchSite(companyId, site.id, Object.fromEntries(
      Object.entries(draft).map(([k, v]) => [API_FIELD[k] ?? k, v === '' ? null : v]))),
    onSuccess: async (r) => {
      setDraft({})
      toast.success(r.changed.length ? `Сохранено полей: ${r.changed.length}` : 'Изменений нет')
      await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось сохранить'),
  })

  const val = (k: string) => {
    if (k in draft) return draft[k]
    const v = site[k as keyof SiteDetail]
    return v === null || v === undefined ? '' : String(v)
  }
  const manual = useMemo(() => new Set(site.manualFields ?? []), [site.manualFields])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Изменённые поля перестают обновляться из файла — в них истина ваша, а не выгрузки.
        </p>
        <Button size="sm" className="h-8 text-xs" disabled={!dirty || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Сохранить{dirty ? ` (${Object.keys(draft).length})` : ''}
        </Button>
      </div>

      {PASSPORT_GROUPS.map((g) => (
        <section key={g.title} className="rounded-lg border border-border">
          <div className="px-3 py-1.5 text-xs font-semibold border-b bg-muted/40">{g.title}</div>
          <div className="p-3 grid grid-cols-1 md:grid-cols-3 gap-2">
            {g.fields.map((f) => {
              const key = String(f.k)
              const isManual = manual.has(API_FIELD[key] ?? key)
              return (
                <div key={key} className={f.type === 'area' ? 'md:col-span-3' : ''}>
                  <Label>
                    {f.label}
                    {isManual && <span className="ml-1 text-[9px] text-primary" title="Ведётся вручную, импорт не перезапишет">✎</span>}
                  </Label>
                  {f.type === 'area' ? (
                    <Textarea rows={2} className="text-xs min-h-[46px]" value={val(key)}
                      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} />
                  ) : f.type === 'select' ? (
                    <Select value={val(key) || '__none__'}
                      onValueChange={(v) => setDraft((d) => ({ ...d, [key]: v === '__none__' ? '' : v }))}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-xs">—</SelectItem>
                        {(f.options ?? []).map((o) => <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input className="h-8 text-xs" type={f.type === 'date' ? 'date' : 'text'}
                      inputMode={f.type === 'number' ? 'decimal' : undefined}
                      value={val(key)} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} />
                  )}
                </div>
              )
            })}
          </div>
        </section>
      ))}

      {(site.lat != null || site.mapUrl) && (
        <div className="flex items-center gap-3 text-xs">
          {site.lat != null && <span className="font-mono text-muted-foreground">{site.lat}, {site.lon}</span>}
          {site.mapUrl && (
            <a href={site.mapUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              Карта <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}

      <div className="border-t pt-2">
        <button type="button" onClick={() => setShowRaw((v) => !v)} className="text-xs text-muted-foreground hover:text-foreground">
          {showRaw ? '▾' : '▸'} Все поля из файла ({Object.keys(site.raw || {}).length})
        </button>
        {showRaw && (
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(site.raw || {}).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[11px] border-b border-border/20 py-0.5">
                <span className="text-muted-foreground shrink-0 max-w-[45%] truncate" title={k}>{k}</span>
                <span className="break-words">{v}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Вкладка «Присоединение» ────────────────────────────────────────────── */

function TechConnectionTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  useEffect(() => setDraft({}), [ctx.data])

  const m = useMutation({
    mutationFn: () => saveTechConnection(companyId, site.id, draft),
    onSuccess: async () => { setDraft({}); toast.success('Сохранено'); await onDone() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось сохранить'),
  })

  if (ctx.isLoading || !ctx.data) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const tc = ctx.data.techConnection
  const val = (k: string, fallback: unknown) =>
    (k in draft ? draft[k] : (fallback ?? '')) as string
  const set = (k: string, v: string | boolean) => setDraft((d) => ({ ...d, [k]: v }))
  const dirty = Object.keys(draft).length > 0

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Срок проекта задаёт присоединение: от заявки до исполнения — от двух месяцев
          до полутора лет при реконструкции сети.
        </p>
        <Button size="sm" className="h-8 text-xs" disabled={!dirty || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Сохранить
        </Button>
      </div>

      {tc?.overdue && (
        <div className="flex items-center gap-1.5 rounded border border-red-400/50 bg-red-400/5 px-2 py-1.5 text-[11px] text-red-600 dark:text-red-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          Срок мероприятий сетевой ({tc.dueDate}) прошёл, отметки об исполнении нет.
        </div>
      )}

      <section className="rounded-lg border border-border p-3 grid grid-cols-1 md:grid-cols-3 gap-2">
        <div>
          <Label>Статус</Label>
          <Select value={val('status', tc?.status) || 'draft'} onValueChange={(v) => set('status', v)}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {ctx.data.tcStatuses.map((s) => (
                <SelectItem key={s.key} value={s.key} className="text-xs">{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Label>Сетевая организация</Label>
          <Input className="h-8 text-xs" value={val('grid_operator', tc?.gridOperator)}
            placeholder="Россети Урал" onChange={(e) => set('grid_operator', e.target.value)} />
        </div>
        <Field2 label="№ заявки" v={val('application_no', tc?.applicationNo)} on={(v) => set('application_no', v)} />
        <Field2 label="Дата заявки" type="date" v={val('application_date', tc?.applicationDate)} on={(v) => set('application_date', v)} />
        <Field2 label="Мощность, кВт" v={val('power_kwt', tc?.powerKwt)} on={(v) => set('power_kwt', v)} />
        <Field2 label="№ ТУ" v={val('specs_no', tc?.specsNo)} on={(v) => set('specs_no', v)} />
        <Field2 label="Дата ТУ" type="date" v={val('specs_date', tc?.specsDate)} on={(v) => set('specs_date', v)} />
        <Field2 label="Класс напряжения" v={val('voltage', tc?.voltage)} on={(v) => set('voltage', v)} />
        <Field2 label="№ договора ТП" v={val('contract_no', tc?.contractNo)} on={(v) => set('contract_no', v)} />
        <Field2 label="Дата договора ТП" type="date" v={val('contract_date', tc?.contractDate)} on={(v) => set('contract_date', v)} />
        <Field2 label="Стоимость, ₽" v={val('cost', tc?.cost)} on={(v) => set('cost', v)} />
        <Field2 label="Срок мероприятий (план)" type="date" v={val('due_date', tc?.dueDate)} on={(v) => set('due_date', v)} />
        <Field2 label="Исполнено (факт)" type="date" v={val('done_date', tc?.doneDate)} on={(v) => set('done_date', v)} />
        <div className="flex items-end">
          <label className="flex items-center gap-1.5 text-xs">
            <input type="checkbox"
              checked={Boolean(('needs_reconstruction' in draft) ? draft.needs_reconstruction : tc?.needsReconstruction)}
              onChange={(e) => set('needs_reconstruction', e.target.checked)} />
            Нужна реконструкция сети
          </label>
        </div>
        <div className="md:col-span-3">
          <Label>Заметка</Label>
          <Textarea rows={2} className="text-xs min-h-[46px]" value={val('note', tc?.note)}
            onChange={(e) => set('note', e.target.value)} />
        </div>
      </section>
    </div>
  )
}

function Field2({ label, v, on, type }: { label: string; v: string; on: (v: string) => void; type?: string }) {
  return (
    <div>
      <Label>{label}</Label>
      <Input className="h-8 text-xs" type={type ?? 'text'} value={v} onChange={(e) => on(e.target.value)} />
    </div>
  )
}

/* ── Вкладка «Оборудование» ─────────────────────────────────────────────── */

function EquipmentTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  const [form, setForm] = useState({
    title: '', manufacturer: '', power_kwt: '', connectors: '',
    qty: '1', supplier: '', price: '', due_date: '',
  })
  const [busy, setBusy] = useState(false)

  const add = async () => {
    if (!form.title.trim()) return
    setBusy(true)
    try {
      await saveEquipment(companyId, site.id, { ...form, status: 'planned' })
      setForm({ title: '', manufacturer: '', power_kwt: '', connectors: '', qty: '1',
                supplier: '', price: '', due_date: '' })
      await onDone(); await ctx.refetch()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось добавить') }
    finally { setBusy(false) }
  }
  const setStatus = async (id: string, status: string) => {
    // Дату проставляет система: статус без даты бесполезен для сроков.
    const today = new Date().toISOString().slice(0, 10)
    const extra = status === 'supplied' ? { supplied_date: today }
      : status === 'installed' ? { installed_date: today }
      : status === 'ordered' ? { order_date: today } : {}
    try {
      await saveEquipment(companyId, site.id, { id, status, ...extra })
      await onDone(); await ctx.refetch()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось изменить') }
  }
  const remove = async (id: string) => {
    try { await deleteEquipment(companyId, site.id, id); await onDone(); await ctx.refetch() }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось удалить') }
  }

  if (ctx.isLoading || !ctx.data) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const eq = ctx.data.equipment
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Потребность проекта, а не склад. Пункт гейта «Оборудование поставлено» закрывается,
          когда все позиции получили статус «Поставлено» или «Смонтировано».
        </p>
        <span className={`text-[11px] rounded border px-1.5 py-0.5 shrink-0 ${eq.allSupplied ? 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' : 'border-zinc-500/60 text-zinc-500'}`}>
          {eq.allSupplied ? 'всё поставлено' : 'не всё поставлено'}
        </span>
      </div>

      {eq.items.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b">
              <th className="text-left py-1 font-medium">Оборудование</th>
              <th className="text-right py-1 font-medium">кВт</th>
              <th className="text-right py-1 font-medium">Кол-во</th>
              <th className="text-left py-1 font-medium">Поставщик</th>
              <th className="text-left py-1 font-medium">Поставка</th>
              <th className="text-right py-1 font-medium">Стоимость</th>
              <th className="text-left py-1 font-medium">Статус</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {eq.items.map((e) => (
              <tr key={e.id} className="border-b border-border/30">
                <td className="py-1.5">
                  {e.title ?? '—'}
                  {e.manufacturer && <span className="text-muted-foreground"> · {e.manufacturer}</span>}
                </td>
                <td className="py-1.5 text-right font-mono">{e.powerKwt ?? '—'}</td>
                <td className="py-1.5 text-right font-mono">{e.qty}</td>
                <td className="py-1.5 text-muted-foreground">{e.supplier ?? '—'}</td>
                <td className={`py-1.5 font-mono ${e.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                  {e.suppliedDate ? `\u2713 ${e.suppliedDate}` : (e.dueDate ?? '—')}
                </td>
                <td className="py-1.5 text-right font-mono">{e.price != null ? nf0.format(e.price) : '—'}</td>
                <td className="py-1.5">
                  <Select value={e.status} onValueChange={(v) => setStatus(e.id, v)}>
                    <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {ctx.data.eqStatuses.map((s) => (
                        <SelectItem key={s.key} value={s.key} className="text-xs">{s.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
                <td className="py-1.5 text-right">
                  <button type="button" onClick={() => remove(e.id)}
                    className="text-muted-foreground hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="rounded-lg border border-border p-3 grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="md:col-span-2">
          <Label>Оборудование</Label>
          <Input className="h-8 text-xs" placeholder="Быстрая ЭЗС 150 кВт"
            value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
        </div>
        <Field2 label="Производитель" v={form.manufacturer} on={(v) => setForm((f) => ({ ...f, manufacturer: v }))} />
        <Field2 label="Мощность, кВт" v={form.power_kwt} on={(v) => setForm((f) => ({ ...f, power_kwt: v }))} />
        <Field2 label="Разъёмы" v={form.connectors} on={(v) => setForm((f) => ({ ...f, connectors: v }))} />
        <Field2 label="Кол-во" v={form.qty} on={(v) => setForm((f) => ({ ...f, qty: v }))} />
        <Field2 label="Поставщик" v={form.supplier} on={(v) => setForm((f) => ({ ...f, supplier: v }))} />
        <Field2 label="Стоимость, ₽" v={form.price} on={(v) => setForm((f) => ({ ...f, price: v }))} />
        <Field2 label="Плановая поставка" type="date" v={form.due_date} on={(v) => setForm((f) => ({ ...f, due_date: v }))} />
        <div className="flex items-end">
          <Button size="sm" className="h-8 text-xs" disabled={busy || !form.title.trim()} onClick={add}>
            Добавить
          </Button>
        </div>
      </section>
    </div>
  )
}

/* ── Вкладка «Документы» ────────────────────────────────────────────────── */

function DocsTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState('other')
  const [busy, setBusy] = useState(false)
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  const docs = useQuery({
    queryKey: ['site-docs', companyId, site.id],
    queryFn: () => getSiteDocs(companyId, site.id),
  })

  const onPick = async (f: File | null) => {
    if (!f) return
    setBusy(true)
    try {
      await uploadSiteDoc(companyId, site.id, f, kind, f.name)
      toast.success('Документ приложен')
      await onDone()
      await docs.refetch()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось загрузить')
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const remove = async (docId: string) => {
    try {
      await deleteSiteDoc(companyId, site.id, docId)
      await onDone(); await docs.refetch()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось удалить') }
  }

  const rows = docs.data ?? []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(ctx.data?.docKinds ?? []).map((k) => (
              <SelectItem key={k.key} value={k.key} className="text-xs">{k.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input ref={fileRef} type="file" hidden onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
        <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy}
          onClick={() => fileRef.current?.click()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
          Приложить документ
        </Button>
        <span className="text-[11px] text-muted-foreground ml-auto">
          Часть пунктов гейта закрывается именно документом: договор, ТУ, акт приёмки.
        </span>
      </div>

      {docs.isLoading ? (
        <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : rows.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">Документов пока нет.</div>
      ) : (
        <div className="rounded-lg border border-border divide-y divide-border/40">
          {rows.map((d) => (
            <div key={d.id} className="flex items-center gap-2 px-3 py-2 text-xs">
              <span className="rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground shrink-0">{d.kindLabel}</span>
              <span className="truncate flex-1" title={d.title ?? d.fileName ?? ''}>{d.title || d.fileName || '—'}</span>
              <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                {d.stageLabel ?? ''}{d.uploadedBy ? ` · ${d.uploadedBy}` : ''} {fmtDate(d.createdAt)}
              </span>
              <button type="button" onClick={() => remove(d.id)}
                className="text-muted-foreground hover:text-red-500 shrink-0" title="Удалить">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Вкладка «Учёт» ─────────────────────────────────────────────────────── */

function AccountingTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  if (ctx.isLoading || !ctx.data) {
    return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }
  const d = ctx.data
  const sub = d.subsidy

  return (
    <div className="space-y-3">
      {/* связи с учётом */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-xs font-semibold">Записи в учёте</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div>
            <Label>Договор на землю</Label>
            {d.contract ? (
              <div>№ {d.contract.number} от {d.contract.date}
                {d.contract.basis && <span className="text-muted-foreground"> · {d.contract.basis}</span>}
                {d.contract.validUntil && <span className="text-muted-foreground"> · до {d.contract.validUntil}</span>}
              </div>
            ) : (
              <div className="text-amber-600 dark:text-amber-400">
                не привязан{site.contractStart ? ' — а договор уже подписан' : ''}
              </div>
            )}
          </div>
          <div>
            <Label>Объект сети</Label>
            {d.location ? (
              <div>{d.location.name} <span className="text-muted-foreground">({d.location.code})</span></div>
            ) : (
              <div className="text-muted-foreground">не связан — проект ещё не стал станцией</div>
            )}
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Записи в бухгалтерии создаются в своих разделах, здесь — только связь: учётный контур
          не должен наполняться побочным эффектом смены статуса проекта.
        </p>
      </section>

      {/* субсидия */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40 flex items-center justify-between">
          <span>Субсидия — соответствие требованиям</span>
          <span className={`font-mono ${sub.eligible ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>
            {sub.done} / {sub.total}
          </span>
        </div>
        <div className="p-3 space-y-1">
          {sub.items.map((i) => (
            <div key={i.key} className="flex items-center gap-2 text-xs">
              {i.done
                ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                : <Circle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
              <span className={i.done ? '' : 'text-muted-foreground'}>{i.label}</span>
              {i.value && <span className="text-[11px] text-muted-foreground">— {i.value}</span>}
            </div>
          ))}
          {sub.obligationUntil && (
            <div className="pt-1 text-[11px] text-muted-foreground">
              Введён {sub.commissionedOn} · обязательство эксплуатировать до {sub.obligationUntil}
              {' '}({sub.obligationYears} лет)
            </div>
          )}
        </div>
      </section>

      {/* бюджет */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40 flex items-center justify-between">
          <span>Бюджет проекта</span>
          <span className="font-mono text-muted-foreground">
            план {nf0.format(d.costs.planTotal)} ₽ · факт {nf0.format(d.costs.factTotal)} ₽
          </span>
        </div>
        <BudgetEditor site={site} companyId={companyId} ctx={d} onDone={onDone} />
      </section>
    </div>
  )
}

function BudgetEditor({ site, companyId, ctx, onDone }: {
  site: SiteDetail; companyId: string; ctx: ProjectContext; onDone: () => Promise<void>
}) {
  const [kind, setKind] = useState('tp')
  const [title, setTitle] = useState('')
  const [plan, setPlan] = useState('')
  const [fact, setFact] = useState('')
  const [busy, setBusy] = useState(false)

  const add = async () => {
    if (!plan && !fact) return
    setBusy(true)
    try {
      await saveCost(companyId, site.id, { kind, title: title || null, plan, fact })
      setTitle(''); setPlan(''); setFact('')
      await onDone()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось сохранить') } finally { setBusy(false) }
  }
  const remove = async (id: string) => {
    try { await deleteCost(companyId, site.id, id); await onDone() }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось удалить') }
  }

  return (
    <div className="p-3 space-y-2">
      {ctx.costs.items.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground border-b">
              <th className="text-left py-1 font-medium">Статья</th>
              <th className="text-left py-1 font-medium">Описание</th>
              <th className="text-right py-1 font-medium">План</th>
              <th className="text-right py-1 font-medium">Факт</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {ctx.costs.items.map((c) => (
              <tr key={c.id} className="border-b border-border/30">
                <td className="py-1.5">{c.kindLabel}</td>
                <td className="py-1.5 text-muted-foreground">{c.title ?? '—'}</td>
                <td className="py-1.5 text-right font-mono">{c.plan != null ? nf0.format(c.plan) : '—'}</td>
                <td className="py-1.5 text-right font-mono">{c.fact != null ? nf0.format(c.fact) : '—'}</td>
                <td className="py-1.5 text-right">
                  <button type="button" onClick={() => remove(c.id)}
                    className="text-muted-foreground hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label>Статья</Label>
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {ctx.costKinds.map((k) => <SelectItem key={k.key} value={k.key} className="text-xs">{k.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 min-w-[160px]">
          <Label>Описание</Label>
          <Input className="h-8 text-xs" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="w-[120px]"><Label>План, ₽</Label>
          <Input className="h-8 text-xs" value={plan} onChange={(e) => setPlan(e.target.value)} /></div>
        <div className="w-[120px]"><Label>Факт, ₽</Label>
          <Input className="h-8 text-xs" value={fact} onChange={(e) => setFact(e.target.value)} /></div>
        <Button size="sm" className="h-8 text-xs" disabled={busy || (!plan && !fact)} onClick={add}>Добавить</Button>
      </div>
    </div>
  )
}

/* ── Вкладка «Экономика» ────────────────────────────────────────────────── */

function EconomicsTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const q = useQuery({
    queryKey: ['site-economics', companyId, site.id],
    queryFn: () => getSiteEconomics(companyId, site.id),
  })
  if (q.isLoading) return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  const d = q.data
  if (!d) return null
  const { economics: e, score } = d

  return (
    <div className="space-y-3">
      {/* Приоритет */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold">Приоритет</div>
          <span className={`text-[11px] rounded border px-1.5 py-0.5 ${QUADRANT_META[score.quadrant].cls}`}
            title={QUADRANT_META[score.quadrant].hint}>{QUADRANT_META[score.quadrant].label}</span>
        </div>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <Metric label="Привлекательность" value={score.attract != null ? String(score.attract) : '—'} />
          <Metric label="Исполнимость" value={score.feasible != null ? String(score.feasible) : '—'} />
          <Metric label="Уверенность оценки" value={`${score.confidence}%`}
            warn={score.confidence < 34} />
        </div>
        {score.nearestStationKm != null && (
          <div className={`text-[11px] ${score.cannibalization ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}>
            До ближайшей нашей станции {score.nearestStationKm} км
            {score.cannibalization ? ' — площадка делит трафик с действующей ЭЗС' : ''}
          </div>
        )}
        {score.unknown.length > 0 && (
          <div className="text-[11px] text-muted-foreground">
            Не хватает: {score.unknown.join('; ')}
          </div>
        )}
      </section>

      {/* Экономика */}
      {!e.ok ? (
        <div className="rounded-lg border border-border p-3 text-xs text-muted-foreground">
          {e.message ?? 'Расчёт недоступен'}
        </div>
      ) : (
        <section className="rounded-lg border border-border">
          <div className="px-3 py-2 text-xs font-semibold border-b bg-muted/40">
            Оценка экономики — по фактическим сессиям сети
          </div>
          <div className="p-3 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <Metric label="Тариф (факт)" value={`${e.tariff} ₽/кВт·ч`} />
              <Metric label="Входная цена" value={`${e.inputPrice} ₽/кВт·ч`} />
              <Metric label="Маржа с кВт·ч" value={`${e.marginPerKwh} ₽`} />
              <Metric label="Аренда" value={`${nf0.format(e.rentMonth ?? 0)} ₽/мес`} />
            </div>

            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground border-b">
                  <th className="text-left py-1 font-medium">Сценарий</th>
                  <th className="text-right py-1 font-medium">кВт·ч/мес</th>
                  <th className="text-right py-1 font-medium">Выручка</th>
                  <th className="text-right py-1 font-medium">Маржа/мес</th>
                  <th className="text-right py-1 font-medium">Окупаемость</th>
                </tr>
              </thead>
              <tbody>
                {([['Базовый (медиана сети)', e.base], ['Хороший (верхняя четверть)', e.good]] as const).map(([label, sc]) => (
                  <tr key={label} className="border-b border-border/30">
                    <td className="py-1.5">{label}</td>
                    <td className="py-1.5 text-right font-mono">{nf0.format(sc?.kwhMonth ?? 0)}</td>
                    <td className="py-1.5 text-right font-mono">{nf0.format(sc?.revenueMonth ?? 0)} ₽</td>
                    <td className="py-1.5 text-right font-mono">{nf0.format(sc?.marginMonth ?? 0)} ₽</td>
                    <td className="py-1.5 text-right font-mono">
                      {sc?.paybackMonths != null ? `${nf0.format(sc.paybackMonths)} мес` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="text-[11px] text-muted-foreground">
              Капитальные затраты: {e.capex != null ? `${nf0.format(e.capex)} ₽` : 'не посчитаны'}
            </div>

            <div className="rounded border border-border bg-muted/20 p-2">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Допущения расчёта</div>
              <ul className="space-y-0.5 text-[11px] text-muted-foreground list-disc pl-4">
                {e.assumptions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold ${warn ? 'text-amber-600 dark:text-amber-400' : ''}`}>{value}</div>
    </div>
  )
}

/* ── Вкладка «История» ──────────────────────────────────────────────────── */

const KIND_LABEL: Record<string, string> = {
  stage: 'Стадия', touch: 'Касание', note: 'Заметка', edit: 'Правка', import: 'Импорт', gate: 'Гейт',
}

function HistoryTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const q = useQuery({
    queryKey: ['site-events', companyId, site.id],
    queryFn: () => getSiteEvents(companyId, site.id),
  })
  if (q.isLoading) return <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  const rows = q.data ?? []
  if (rows.length === 0) return <div className="py-8 text-center text-sm text-muted-foreground">Событий пока нет.</div>
  return (
    <div className="space-y-1.5">
      {rows.map((e) => (
        <div key={e.id} className="flex gap-2 text-xs border-b border-border/30 pb-1.5">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground w-16 shrink-0 pt-0.5">
            {KIND_LABEL[e.kind] ?? e.kind}
          </span>
          <div className="min-w-0 flex-1">
            <div className="break-words">{e.text || '—'}</div>
            <div className="text-[10px] text-muted-foreground">
              {fmtDate(e.createdAt)}{e.author ? ` · ${e.author}` : ''}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Мелочи ─────────────────────────────────────────────────────────────── */

function Label({ children }: { children: ReactNode }) {
  return <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">{children}</div>
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

export { nf0 }
