/**
 * Вкладки проекта ЭЗС — общий набор для быстрого просмотра (диалог) и для
 * полноэкранной работы в разделе.
 *
 * Держать их в двух местах нельзя: карточка — основное рабочее место, и две
 * копии одних и тех же форм разъезжаются на первой же правке.
 *
 *   Работа        — стадия, гейт (обязательные пункты блокируют переход),
 *                   ответственный, следующий шаг, касания;
 *   Паспорт       — данные объекта, право на землю, техприсоединение, план;
 *   Присоединение — заявка → ТУ → договор → мероприятия, план/факт и просрочка;
 *   Оборудование  — потребность проекта: план → заказ → поставка → монтаж;
 *   Документы     — ЕГРН, ТУ, договор, акты; часть пунктов гейта закрывается файлом;
 *   Экономика     — приоритет и окупаемость по фактическим сессиям сети;
 *   Учёт          — договор, объект сети, субсидия, бюджет;
 *   История       — стадии, касания, правки, импорт.
 *
 * Правка любого поля помечает его «ручным»: следующий импорт файла его не тронет.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  Loader2, ExternalLink, Check, Circle, Save, MessageSquarePlus, AlertTriangle,
  Upload, Trash2, Lock, Link as LinkIcon, Plus, Undo2,
} from 'lucide-react'
import { toast } from 'sonner'
import * as chatApi from '@/services/chatService'
import { useSupportContext } from '@/contexts/SupportContext'
import {
  getSiteEvents, getSiteMembers, getSiteEconomics, getProjectContext, getSiteDocs,
  patchSite, moveSiteStage, markSiteGate, waiveSiteGate, addSiteEvent, uploadSiteDoc,
  deleteSiteDoc, downloadSiteDoc, getProjectRoutes,
  saveTechConnection, saveCost, deleteCost, saveEquipment, deleteEquipment,
  linkContract, linkLocation, getProjectKinds, getLocationWorks, startSuccessor,
  getProjectCase, openProjectCase, applyProjectStep, undoProjectStep,
  getSiteParticipants, addSiteParticipant, removeSiteParticipant, registerEquipmentUnit,
  STAGE_META, FUNNEL_STAGES, QUADRANT_META,
  type SiteDetail, type SiteStage, type ProjectContext, type CaseAction,
  type SiteEquipment,
} from '@/services/sitesService'
import { getWarehousesSummary } from '@/services/equipmentService'
import { getContracts, getCounterparties } from '@/services/referenceService'
import { loadLocations } from '@/services/locationService'
import { getObjectTickets, createObjectTicket } from '@/services/spaceObjectsService'

import { ProjectRoadmapTab } from './ProjectRoadmapTab'
import { useOpenProject } from './useOpenProject'
import { formatDate } from '@/lib/formatDate'

export const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const CONTROL_FORMS = ['аренда', 'сервитут', 'разрешение на размещение', 'собственность', 'соглашение с ТЦ']

/** Набор вкладок карточки — один и тот же в диалоге и в полноэкранном режиме. */
export const PROJECT_TABS = [
  { k: 'roadmap', label: 'Схема' },
  { k: 'work', label: 'Работа' },
  { k: 'passport', label: 'Паспорт' },
  { k: 'tp', label: 'Присоединение' },
  { k: 'equipment', label: 'Оборудование' },
  { k: 'docs', label: 'Документы' },
  { k: 'economics', label: 'Экономика' },
  { k: 'accounting', label: 'Учёт' },
  { k: 'history', label: 'История' },
] as const
export type ProjectTabKey = (typeof PROJECT_TABS)[number]['k']

/** Рендер вкладки по ключу — чтобы вызывающий не знал про внутренние компоненты. */
export function ProjectTabContent({ tab, site, companyId, onDone }: {
  tab: ProjectTabKey; site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  if (tab === 'roadmap') return <ProjectRoadmapTab site={site} companyId={companyId} />
  if (tab === 'work') return <WorkTab site={site} companyId={companyId} onDone={onDone} />
  if (tab === 'passport') return <PassportTab site={site} companyId={companyId} onDone={onDone} />
  if (tab === 'tp') return <TechConnectionTab site={site} companyId={companyId} onDone={onDone} />
  if (tab === 'equipment') return <EquipmentTab site={site} companyId={companyId} onDone={onDone} />
  if (tab === 'docs') return <DocsTab site={site} companyId={companyId} onDone={onDone} />
  if (tab === 'economics') return <EconomicsTab site={site} companyId={companyId} />
  if (tab === 'accounting') return <AccountingTab site={site} companyId={companyId} onDone={onDone} />
  return <HistoryTab site={site} companyId={companyId} />
}

/* ── Ход по маршруту ────────────────────────────────────────────────────── */

/**
 * Причина недоступности — на языке проекта, а не графа.
 *
 * Координатор называет условие кодом вида проекта («new_build»), потому что
 * сравнивает с ним рёбра. В карточке это слово ничего не значит: тот же проект
 * подписан «Новый монтаж» во всех остальных местах экрана.
 */
const PROJECT_KIND_WORDS: Record<string, string> = {
  new_build: 'Новое строительство', relocation: 'Перенос',
  retrofit: 'Модернизация', decommission: 'Демонтаж',
}
function humanReason(reason: string | null | undefined): string {
  let out = reason ?? 'недоступно'
  for (const [code, word] of Object.entries(PROJECT_KIND_WORDS)) {
    out = out.replaceAll(`«${code}»`, `«${word}»`)
  }
  return out
}

/**
 * Где проект стоит по регламенту и что делать дальше.
 *
 * Гейт отвечает на «что заполнено», маршрут — на «чей ход и какая кнопка».
 * Ход ведёт Координатор: там же живут роли, уведомления и просрочки этапов.
 */
/**
 * Что сделает система после нажатия — словами, а не обещанием.
 *
 * «Система выполнит свои шаги сама» человек проверить не может: он подписывается
 * под невидимым эффектом. Уведомление, ветка и заполняемые поля описаны в самой
 * конфигурации ребра — её и пересказываем, поэтому правка маршрута правит и текст.
 */
function effectText(a: CaseAction, defs: Record<string, { label?: string }>): string | null {
  const act = a.action
  if (!act) return null
  if (act.kind === 'notify' && act.text) return `Система разошлёт уведомление: «${act.text}»`
  if (act.kind === 'create_case' && act.title) return `Откроется ветка «${act.title}» — её ведёт своя служба.`
  if (act.kind === 'set_fields') {
    const parts = Object.entries(act.fields ?? {}).map(([code, v]) =>
      `${defs[code]?.label ?? code}: ${v === true ? 'да' : v === false ? 'нет' : String(v)}`)
    if (parts.length) return `Система заполнит — ${parts.join(', ')}.`
  }
  // Эффект есть, но описать его нечем (действие нового типа, пустая конфигурация).
  // Молчание честнее обещания «система выполнит свои шаги сама»: под непроверяемый
  // эффект человек подписываться не должен.
  return null
}

function RoutePanel({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const [picked, setPicked] = useState<CaseAction | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})

  const q = useQuery({
    queryKey: ['site-case', companyId, site.id],
    queryFn: () => getProjectCase(companyId, site.id),
  })
  const state = q.data

  // Маршруты спрашиваем только пока проект не на рельсах: у идущего выбор уже
  // сделан и менять его нечем — лишний запрос в карточку каждого проекта.
  const qRoutes = useQuery({
    queryKey: ['project-routes', companyId],
    queryFn: () => getProjectRoutes(companyId),
    enabled: state != null && !state.exists,
    staleTime: 5 * 60_000,
  })
  const routes = qRoutes.data?.routes ?? []
  const [route, setRoute] = useState<string>('')
  const mOpen = useMutation({
    mutationFn: () => openProjectCase(companyId, site.id, route || undefined),
    onSuccess: async () => { toast.success('Проект встал на маршрут'); await q.refetch() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось открыть маршрут'),
  })
  const mStep = useMutation({
    mutationFn: (a: CaseAction & { branchCaseId?: string }) =>
      applyProjectStep(companyId, site.id, a.id, a.branchCaseId ? {} : form, a.branchCaseId),
    onSuccess: async (r) => {
      setPicked(null); setForm({})
      if (r.funnel && !r.funnel.moved && r.funnel.blocking.length) {
        // Маршрут ушёл вперёд, а воронка держится гейтом — молчать об этом нельзя.
        // Но всплывашка на 15 пунктов не читается: называем три и число остальных,
        // полный список и так лежит в чек-листе гейта на этой же вкладке.
        const b = r.funnel.blocking
        const head = b.slice(0, 3).join('; ')
        toast.warning(
          `Ход выполнен. Воронку держит гейт: ${head}${b.length > 3 ? ` и ещё ${b.length - 3}` : ''}`,
          { description: b.length > 3 ? 'Полный список — в чек-листе согласования ниже.' : undefined })
      } else {
        toast.success('Шаг выполнен')
      }
      await q.refetch(); await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Шаг не выполнен'),
  })
  // Отмена последнего шага — «нажал не ту кнопку». Правила держит Координатор
  // (свой шаг, сутки), поэтому здесь только кнопка и честный текст отказа: он
  // объясняет, чей это был шаг и что делать, если срок вышел.
  const mUndo = useMutation({
    mutationFn: () => undoProjectStep(companyId, site.id),
    onSuccess: async (r) => {
      const u = (r as { undone?: { toName: string; fromName: string } }).undone
      toast.success(u ? `Шаг «${u.toName}» отменён — проект снова на «${u.fromName}»` : 'Шаг отменён')
      await q.refetch(); await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось отменить шаг'),
  })

  const defs = useMemo(
    () => Object.fromEntries((state?.fields ?? []).map((f) => [f.code, f])),
    [state?.fields])

  if (q.isLoading) {
    return <div className="rounded-lg border border-border px-3 py-3 text-sm text-muted-foreground">
      <Loader2 className="inline h-4 w-4 animate-spin mr-2" />Ход проекта…
    </div>
  }
  // Мост не настроен — карточка обязана работать дальше, панель просто молчит о причине.
  if (state?.error) {
    return <div className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
      Ход по маршруту недоступен: {state.error}
    </div>
  }
  // Запрос не дошёл — это НЕ «проект не ведётся». Утверждать факт о проекте,
  // которого мы не прочитали, и предлагать завести его заново — прямой путь ко
  // второму кейсу на том же проекте.
  if (q.isError) {
    return (
      <div className="rounded-lg border border-border px-3 py-3 text-sm space-y-2">
        <div>Ход по маршруту не загрузился: {q.error instanceof Error ? q.error.message : 'нет связи с сервером'}</div>
        <Button size="sm" variant="outline" onClick={() => q.refetch()}>Повторить</Button>
      </div>
    )
  }
  if (!state?.exists) {
    // Выбор маршрута показываем, только если выбирать есть из чего. Один маршрут —
    // это не выбор, а лишний вопрос перед единственной кнопкой.
    const choice = routes.length > 1
    const routeInfo = routes.find((r) => r.code === route) ?? routes.find((r) => r.isDefault)
    return (
      <section className="rounded-lg border border-dashed border-border px-3 py-3 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="text-sm text-muted-foreground">
            Проект ещё не ведётся по маршруту регламента: нет ни ответственного за шаг, ни сроков этапов.
          </div>
          <Button size="sm" className="h-10 sm:h-9 w-full sm:w-auto shrink-0"
            onClick={() => mOpen.mutate()} disabled={mOpen.isPending}>
            {mOpen.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}Вести по маршруту
          </Button>
        </div>
        {/* Список маршрутов не пришёл — молчать нельзя: выбор был, а человек его
            не увидел и решит, что маршрут в системе один. */}
        {qRoutes.data?.error && (
          <p className="text-xs text-muted-foreground">
            Список маршрутов недоступен, проект пойдёт по маршруту по умолчанию: {qRoutes.data.error}
          </p>
        )}
        {choice && (
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">
              По какому маршруту вести. Выбор делается один раз: сменить его у идущего
              проекта нельзя — стадии у каждого маршрута свои.
            </div>
            <Select value={route || routeInfo?.code || ''} onValueChange={setRoute}>
              <SelectTrigger className="h-9"><SelectValue placeholder="Маршрут" /></SelectTrigger>
              <SelectContent>
                {routes.map((r) => (
                  <SelectItem key={r.code} value={r.code}>
                    {r.name}
                    {r.own ? ' · свой' : ''}
                    {r.isDefault ? ' · по умолчанию' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {routeInfo && (
              <div className="text-xs text-muted-foreground">
                {routeInfo.stages} стадий, {routeInfo.links} переходов, редакция {routeInfo.revision}
                {routeInfo.automation ? '' : ' · автоматика выключена'}
              </div>
            )}
          </div>
        )}
      </section>
    )
  }

  // Чужое и ещё не открытое действие показываем погашенным с причиной: пустое место
  // не объясняет менеджеру, чего он ждёт и от кого.
  const open = (state.actions ?? []).filter((a) => a.allowed !== false)
  // Развилка по виду проекта — это два ребра с ОДНОЙ надписью («Взять в работу»
  // в подбор локации и оно же сразу в планирование), из которых условие включает
  // ровно одно. Показать проигравший близнец погашенным значит написать «Взять в
  // работу — не выполнено условие» рядом с работающей кнопкой «Взять в работу».
  // Прячем только такие: кнопка с тем же словом никуда не делась, она под рукой.
  const openVerbs = new Set(open.map((a) => a.verb))
  const blockedActions = (state.actions ?? [])
    .filter((a) => a.allowed === false && !openVerbs.has(a.verb))
  const normal = open.filter((a) => !a.is_discretionary)
  const extra = open.filter((a) => a.is_discretionary)
  // Ведущий шаг стадии — единственный ход вперёд. Их два и больше (развилка формы
  // права) — заливки не получает никто: выбор за человеком, а не за экраном.
  const forward = normal.filter((a) => a.is_positive === true)
  const leadId = forward.length === 1 ? forward[0].id : null
  const need = picked ? [
    ...(picked.requirements?.require ?? []),
    ...(picked.requirements?.optional ?? []),
  ] : []
  const missing = (picked?.requirements?.require ?? []).filter((c) => !(form[c] ?? '').trim())
  // Ветка «выполнена» — это финальная стадия её процесса. Статус ветки равен коду
  // стадии, поэтому сравнение с 'closed' не сработало бы ни разу.
  const openBranches = (state.branches ?? []).filter((b) => !b.stage_is_finish)

  return (
    <section className="rounded-lg border border-border">
      <div data-zone="Ход проекта по маршруту регламента" className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between gap-2">
        <span>Ход по маршруту · {state.stage?.name ?? '—'}</span>
        <div className="flex items-center gap-2">
          {/* «Кейс» — слово Координатора. Человек ведёт проект и номер кейса не
              встретит больше нигде; ему важно, сколько проект стоит на этапе. */}
          <span className="text-xs font-normal text-muted-foreground">
            {state.daysInStage != null && `на этапе ${state.daysInStage} дн.`}
          </span>
          {/* Отмена последнего шага. Кнопка тихая и стоит в шапке, а не среди
              действий маршрута: это исправление опечатки, а не ход по регламенту.
              Показываем всегда, когда проект уже ходил, — кому нельзя, тому
              Координатор ответит, чей это был шаг и почему поздно. */}
          {(state.stages ?? []).some((st) => st.visited_at) && (
            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs font-normal"
              disabled={mUndo.isPending} onClick={() => mUndo.mutate()}
              title="Вернуть проект на предыдущую стадию: доступно автору шага в течение суток. Вехи и отправленные уведомления не отменяются">
              {mUndo.isPending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                : <Undo2 className="h-3.5 w-3.5 mr-1" />}
              Отменить шаг
            </Button>
          )}
        </div>
      </div>

      {/* Полоса стадий: где были, где стоим, что впереди. Пройденное — по журналу
          переходов, а не по месту в списке: возврат на доработку и ветки ломают
          линейность, и «слева значит пройдено» врало бы ровно на срыве. */}
      <div className="px-3 py-2 border-b">
        <div className="flex flex-wrap gap-1">
          {(state.stages ?? []).map((s) => {
            const here = s.code === state.stage?.code
            const seen = !!s.visited_at
            return (
              <span key={s.code}
                title={s.visited_at ? `Пройдена ${new Date(s.visited_at).toLocaleDateString('ru-RU')}` : 'Ещё не проходили'}
                className={`text-[11px] px-1.5 py-0.5 rounded inline-flex items-center gap-1 ${
                  here ? 'bg-primary text-primary-foreground'
                    : seen ? 'bg-muted text-foreground'
                    : 'border border-dashed border-border text-muted-foreground'}`}>
                {seen && !here && <Check className="h-2.5 w-2.5" />}
                {s.name}
              </span>
            )
          })}
        </div>
        {/* Признак не только цветом: сплошное — были, пунктир — впереди. */}
        <div className="mt-1 text-[10px] text-muted-foreground">
          Заливка — стадия пройдена, пунктир — впереди, синим — где стоим сейчас.
        </div>
      </div>

      {/* Маршрут дошёл до ввода, а воронка стоит. Всплывашка в момент нажатия
          гаснет за пять секунд, и назавтра проект выглядит как «Лид», прошедший
          весь регламент, — без единого следа причины. Пока держит, говорим прямо. */}
      {state.funnel && !state.funnel.moved && (state.funnel.blocking?.length ?? 0) > 0 && (
        <div className="px-3 py-2 border-b text-xs text-amber-700 dark:text-amber-400">
          Маршрут дошёл до ввода в эксплуатацию, но проект остаётся на прежней стадии
          воронки: не закрыто обязательных пунктов — {state.funnel.blocking.length}.
          Первые: {state.funnel.blocking.slice(0, 2).join('; ')}. Полный список — в чек-листе ниже.
        </div>
      )}

      {/* Вехи: факт, который возврат на доработку не снимает */}
      {(state.milestones ?? []).some((m) => m.reached_at) && (
        <div className="px-3 py-2 flex flex-wrap items-center gap-2 border-b text-xs">
          {/* Подпись слева: без неё зелёная строка читается как ещё один ряд кнопок.
              Веха — зафиксированный факт, и он не снимается возвратом на доработку. */}
          <span className="text-muted-foreground">Зафиксировано:</span>
          {(state.milestones ?? []).filter((m) => m.reached_at).map((m) => (
            <span key={m.code} className="text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1"
              title={`Отмечено ${new Date(m.reached_at!).toLocaleDateString('ru-RU')}`
                + (m.actor_name ? `, ${m.actor_name}` : '')}>
              <Check className="h-3 w-3" />{m.name}
            </span>
          ))}
        </div>
      )}

      <div className="px-3 py-3 space-y-2">
        {/* Причин у «действий нет» четыре: финальная стадия, нет графа, нет стадии
            под статус, ход ведётся во внешней системе. Первую пересказываем своими
            словами, остальные — поломки настройки, о них надо сказать как есть. Но
            слово «заявка» из Координатора здесь занято заявкой поддержки и заявкой
            на техприсоединение, поэтому переводим его на язык карточки. */}
        {state.readonly && (
          <div className="text-sm text-muted-foreground">
            {state.stage?.name && /финальн/i.test(state.readonlyReason ?? '')
              ? `Маршрут пройден: проект стоит на финальной стадии «${state.stage.name}» — действий больше нет.`
              : (state.readonlyReason ?? '')
                  .replace(/Для заявки/g, 'Для проекта').replace(/Заявка/g, 'Проект')
                  .replace(/заявки/g, 'проекта').replace(/заявка/g, 'проект')}
          </div>
        )}
        {/* Дискреционные действия (отложить, отклонить) стоят отдельной строкой ниже:
            без учёта их фраза «действий нет» печаталась прямо над живыми кнопками. */}
        {!state.readonly && normal.length === 0 && extra.length === 0 && blockedActions.length === 0 && (
          <div className="text-sm text-muted-foreground">
            Сейчас ход за другой службой — доступных вам действий на этой стадии нет.
          </div>
        )}
        <div data-zone="Действия маршрута: чей сейчас шаг" className="flex flex-wrap gap-2">
          {/* Залит ровно один шаг — тот, которым маршрут идёт вперёд. Когда «ТП
              выполнено» и «Отложить» одинаково синие, экран перестаёт отличать
              обычный ход от исключения. На развилке (ДА / ДоРНО / РНР — все ходы
              вперёд) главного нет, и заливать один из них значило бы советовать. */}
          {normal.map((a) => (
            <Button key={a.id} size="sm" variant={a.id === leadId ? 'default' : 'outline'}
              className="h-10 sm:h-9"
              onClick={() => { setPicked(picked?.id === a.id ? null : a); setForm({}) }}>
              {a.verb}
            </Button>
          ))}
          {extra.map((a) => (
            <Button key={a.id} size="sm" variant="ghost"
              onClick={() => { setPicked(picked?.id === a.id ? null : a); setForm({}) }}>
              {a.verb}
            </Button>
          ))}
        </div>

        {blockedActions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {blockedActions.map((a) => (
              <span key={a.id} title={`${humanReason(a.deny_reason)}${openBranches.length ? `. Открыты ветки: ${openBranches.map((b) => b.title).join(', ')}` : ''}`}
                className="text-xs px-2 py-1 rounded border border-dashed border-border text-muted-foreground">
                {a.verb}
                <span className="ml-1 opacity-70">· {humanReason(a.deny_reason)}</span>
                {/* Условие ребра чаще всего держит именно ветка — называем её,
                    иначе «не выполнено условие перехода» указывает в пустоту. */}
                {openBranches.length > 0 && (
                  <span className="ml-1 opacity-70">
                    (открыты ветки: {openBranches.map((b) => b.title).join(', ')})
                  </span>
                )}
              </span>
            ))}
          </div>
        )}

        {/* Параллельные ветки: ОР ∥ ОКС на этапе 3, работы подрядчика. Пока ветка
            открыта, родитель ждёт — значит она обязана быть видна вместе с кнопками. */}
        {(state.branches ?? []).length > 0 && (
          <div data-zone="Параллельные ветки проекта" className="pt-1 space-y-1">
            <div className="text-xs font-medium">Ветки работ</div>
            {(state.branches ?? []).map((b) => {
              const done = !!b.stage_is_finish
              return (
                <div key={b.id} className="flex items-center gap-2 text-xs">
                  {done
                    ? <Check className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    : <span className="h-3 w-3 shrink-0 rounded-full border border-amber-500" />}
                  <span className="truncate">{b.title}</span>
                  <span className="text-muted-foreground shrink-0">
                    {b.stage_name ?? '—'}{b.assignee_name ? ` · ${b.assignee_name}` : ''}
                  </span>
                  {/* Кнопки ветки — здесь же. Ветка держит проект, и отправлять за
                      ней человека в другой продукт значит показать ему тупик. */}
                  {(b.actions ?? []).map((a) => (
                    <Button key={a.id} size="sm" variant="outline"
                      className="h-6 px-2 text-[11px] shrink-0" disabled={mStep.isPending}
                      onClick={() => mStep.mutate({ ...a, branchCaseId: b.id })}>
                      {a.verb}
                    </Button>
                  ))}
                </div>
              )
            })}
            {openBranches.length > 0 && (
              <div className="text-[11px] text-muted-foreground">
                Пока ветка открыта, проект ждёт её закрытия. Ветку ведёт своя служба —
                кнопка рядом с ней закрывает ветку, а не проект.
              </div>
            )}
          </div>
        )}

        {/* Состав: кто ведёт проект в ролях регламента. Пусто — слой ролей выключен,
            и об этом надо сказать прямо, иначе «кнопка есть у всех» выглядит багом. */}
        <div data-zone="Состав участников проекта" className="pt-1 text-xs text-muted-foreground">
          {(state.participants ?? []).length === 0
            ? 'Роли регламента на проект не назначены — действия открыты всем участникам пространства.'
            : <>Ведут проект: {(state.participants ?? [])
                .map((p) => `${p.role_code} — ${p.name}`).join(' · ')}</>}
        </div>

        {picked && (
          <div className="rounded border border-border p-2 space-y-2 bg-muted/30">
            <div className="text-xs text-muted-foreground">
              «{picked.verb}» → стадия «{picked.to_name}»
              {effectText(picked, defs) && <>. {effectText(picked, defs)}</>}
            </div>
            {need.map((code) => {
              const d = defs[code]
              const req = (picked.requirements?.require ?? []).includes(code)
              return (
                <div key={code} className="space-y-1">
                  <label className="text-xs font-medium">
                    {d?.label ?? code}{req && <span className="text-destructive"> *</span>}
                  </label>
                  {/* Поле вводится тем способом, каким оно объявлено в процессе.
                      Способ закупки или вид работ — закрытый список: набранное
                      руками «перемещение» сервер отобьёт по справочнику, и человек
                      узнает об этом только после нажатия. Деньги — числом, иначе
                      на телефоне открывается буквенная клавиатура. */}
                  {d?.field_type === 'textarea' ? (
                    <Textarea rows={2} value={form[code] ?? ''}
                      onChange={(e) => setForm({ ...form, [code]: e.target.value })} />
                  ) : d?.field_type === 'select' && d.options?.length ? (
                    <Select value={form[code] || '__none__'}
                      onValueChange={(v) => setForm({ ...form, [code]: v === '__none__' ? '' : v })}>
                      <SelectTrigger className="h-10 sm:h-8 text-sm"><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-sm">—</SelectItem>
                        {d.options.map((o) => (
                          /* Вид проекта хранится кодом (от него зависят рёбра маршрута),
                             а человеку показываем то же слово, что и везде на экране. */
                          <SelectItem key={o} value={o} className="text-sm">
                            {PROJECT_KIND_WORDS[o] ?? o}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      // Деньги вводим текстом с числовой клавиатурой, а не input[type=number]:
                      // на русской раскладке сумму набирают через запятую, а такое значение
                      // браузер считает невалидным и отдаёт пустую строку — введённое
                      // исчезало, и кнопка гасла без объяснения. Сервер запятую понимает.
                      type={d?.field_type === 'date' ? 'date' : 'text'}
                      inputMode={d?.field_type === 'money' || d?.field_type === 'number' ? 'decimal' : undefined}
                      className="h-10 sm:h-9"
                      value={form[code] ?? ''}
                      onChange={(e) => setForm({ ...form, [code]: e.target.value })} />
                  )}
                  {d?.hint && <div className="text-[11px] text-muted-foreground">{d.hint}</div>}
                </div>
              )
            })}
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={missing.length > 0 || mStep.isPending}
                onClick={() => mStep.mutate(picked)}>
                {mStep.isPending && <Loader2 className="h-4 w-4 animate-spin mr-1" />}Выполнить
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setPicked(null); setForm({}) }}>Отмена</Button>
              {missing.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  Заполните: {missing.map((c) => defs[c]?.label ?? c).join(', ')}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

/**
 * Состав проекта: кто в какой роли регламента.
 *
 * Роль назначается на проект, а не на человека вообще: сотрудник ведёт один объект
 * как ОР и лишь наблюдает за соседним. Приёмщики (ОЭ, ОЦО) — тот же список: приёмка
 * это участие с кнопкой в конце маршрута. Состав уезжает в кейс сразу при назначении,
 * иначе назначенный не увидит своей кнопки до следующего шага.
 */
function PartiesPanel({ site, companyId, onChanged }: {
  site: SiteDetail; companyId: string; onChanged: () => Promise<unknown>
}) {
  const [person, setPerson] = useState('')
  const [role, setRole] = useState('')
  // Уточнение к роли: в ОКС на один проект нужны и энергетик, и проектировщик, и
  // куратор СМР (замечание отдела развития 07.08.2026). Заводить под каждого свою
  // роль регламента нельзя — права маршрута закреплены за службой, а не за
  // специальностью; поэтому людей несколько, служба одна, а кто есть кто — здесь.
  const [note, setNote] = useState('')

  const q = useQuery({
    queryKey: ['site-parties', companyId, site.id],
    queryFn: () => getSiteParticipants(companyId, site.id),
  })
  const members = useQuery({ queryKey: ['site-members', companyId], queryFn: () => getSiteMembers(companyId) })

  const mAdd = useMutation({
    mutationFn: () => addSiteParticipant(companyId, site.id, person, role, note),
    onSuccess: async () => {
      setPerson(''); setRole(''); setNote('')
      toast.success('Роль назначена — человеку ушло письмо')
      await q.refetch(); await onChanged()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось назначить'),
  })
  const mDrop = useMutation({
    mutationFn: (id: string) => removeSiteParticipant(companyId, site.id, id),
    onSuccess: async () => { await q.refetch(); await onChanged() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось снять'),
  })

  const rows = q.data?.participants ?? []

  return (
    <section className="rounded-lg border border-border">
      <div data-zone="Состав проекта: роли регламента" className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
        <span>Кто ведёт проект</span>
        <span className="text-xs font-normal text-muted-foreground">{rows.length} чел.</span>
      </div>
      <div className="p-2 space-y-2">
        {rows.length === 0 && (
          <div className="text-xs text-muted-foreground px-1">
            Роли не назначены. Пока состав пуст, кнопки маршрута открыты всем участникам
            пространства — назначьте хотя бы ОР и ОКС, и каждый увидит свои.
          </div>
        )}
        {rows.map((p) => (
          <div key={p.id} className="flex items-center gap-2 text-sm px-1">
            <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-muted">{p.roleCode}</span>
            <span className="flex-1 truncate">
              {p.name}
              {p.note && <span className="text-muted-foreground"> · {p.note}</span>}
            </span>
            <Button size="icon" variant="ghost" className="h-6 w-6"
              onClick={() => mDrop.mutate(p.id)} disabled={mDrop.isPending} title="Снять с роли">
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Select value={person} onValueChange={setPerson}>
            <SelectTrigger className="h-8 w-56 text-xs"><SelectValue placeholder="Человек" /></SelectTrigger>
            <SelectContent>
              {(members.data ?? []).map((m) => (
                <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger className="h-8 w-64 text-xs"><SelectValue placeholder="Роль по регламенту" /></SelectTrigger>
            <SelectContent>
              {(q.data?.roles ?? []).map((r) => (
                <SelectItem key={r.code} value={r.code}>{r.code} — {r.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="Уточнение: энергетик, проектировщик, куратор СМР"
            className="h-8 w-64 text-xs" />
          <Button size="sm" variant="outline" disabled={!person || !role || mAdd.isPending}
            onClick={() => mAdd.mutate()}>
            {mAdd.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Назначить
          </Button>
        </div>
        <div className="text-xs text-muted-foreground px-1">
          На одну службу можно назначить нескольких человек — например всех, кто ведёт
          проект со стороны ОКС. Каждому уходит письмо с ссылкой на карточку проекта.
        </div>
      </div>
    </section>
  )
}

/* ── Вкладка «Работа» ───────────────────────────────────────────────────── */

export function WorkTab({ site, companyId, onDone }: { site: SiteDetail; companyId: string; onDone: () => Promise<void> }) {
  const qc = useQueryClient()
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
  // Обычный ход — вперёд по цепочке; всё остальное открывается по запросу.
  const [otherStage, setOtherStage] = useState(false)
  // Пометка дубля: номер оригинала собирается в причину архивации.
  const [dupOpen, setDupOpen] = useState(false)
  const [dupNo, setDupNo] = useState('')
  const nextStage = FUNNEL_STAGES[FUNNEL_STAGES.indexOf(site.stage as never) + 1]

  // Стадию передаём аргументом: кнопка «Перевести в …» не может ждать, пока
  // setStage доедет до следующего рендера, иначе уйдёт предыдущее значение.
  const mMove = useMutation({
    // Причину, как и стадию, можно передать аргументом: `setReason` доедет только
    // к следующему рендеру, и кнопка «Пометить дублем» отправила бы пустую причину
    // — ровно та же грабля, из-за которой аргументом передаётся стадия.
    mutationFn: (p?: SiteStage | { to: SiteStage; reason: string }) => {
      const to = typeof p === 'string' ? p : p?.to
      const why = p && typeof p === 'object' ? p.reason : reason
      return moveSiteStage(companyId, site.id, to ?? stage, why || undefined, override)
    },
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
    onSuccess: async (r) => {
      // Сервер может отказать (пункт не с этой стадии) — тогда галочка не появится,
      // и без сообщения это выглядит как поломка интерфейса.
      if (r && r.ok === false) { toast.warning(r.message ?? 'Пункт не отмечен'); return }
      await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось отметить пункт'),
  })
  // Снятие обязательности — решение под подписью, поэтому обоснование спрашиваем
  // прямо в строке пункта, а не диалогом: диалог уводит взгляд с того, что именно
  // человек берёт на себя.
  const [waiveFor, setWaiveFor] = useState<string | null>(null)
  const [waiveWhy, setWaiveWhy] = useState('')
  const mWaive = useMutation({
    mutationFn: (p: { key: string; waived: boolean; reason: string }) =>
      waiveSiteGate(companyId, site.id, p.key, p.waived, p.reason),
    onSuccess: async (_r, p) => {
      setWaiveFor(null); setWaiveWhy('')
      toast.success(p.waived ? 'Обязательность снята' : 'Обязательность возвращена')
      await onDone()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось изменить пункт'),
  })
  const mTouch = useMutation({
    mutationFn: () => addSiteEvent(companyId, site.id, touch, 'touch'),
    onSuccess: async () => { setTouch(''); toast.success('Записано'); await onDone() },
  })

  const overdue = !!due && due < new Date().toISOString().slice(0, 10)

  return (
    <div className="space-y-4">
      <RoutePanel site={site} companyId={companyId} onDone={onDone} />

      <PartiesPanel site={site} companyId={companyId}
        onChanged={() => qc.invalidateQueries({ queryKey: ['site-case', companyId, site.id] })} />

      {/* Гейт текущей стадии */}
      <section className="rounded-lg border border-border">
        <div data-zone="Чек-лист стадии по регламенту" className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
          <span>Чек-лист согласования · стадия «{gate.stageLabel}»</span>
          <span className={`font-mono ${gate.done === gate.total ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>
            {gate.done} / {gate.total}
          </span>
        </div>
        <div className="p-2 space-y-1">
          {gate.items.length === 0 && <div className="text-sm text-muted-foreground px-1 py-1">Для этой стадии проверок нет.</div>}
          {gate.items.map((it) => {
            // Ручной пункт отмечают кликом по всей строке: значок 14 px — цель,
            // в которую на ноутбуке промахиваются, а по тексту кликают первым делом.
            // Автоматический не кликается вовсе — и должен сам сказать, чем закроется,
            // иначе человек жмёт по нему и считает, что система не работает.
            const Row = it.manual ? 'button' : 'div'
            const FIELD_LABELS: Record<string, string> = Object.fromEntries(
              PASSPORT_GROUPS.flatMap((g) => g.fields.map((f) => [
                String(f.k).replace(/[A-Z]/g, (c) => '_' + c.toLowerCase()), f.label])))
            const byFields = (it.fields ?? []).map((f) => FIELD_LABELS[f]).filter(Boolean)
            const source = it.doc ? 'вкладка «Документы»'
              : it.equipment ? 'вкладка «Оборудование»'
              : it.manual ? null
              // Падеж целиком, а не хвост: склейка «графа» + «й» давала «графай».
              : byFields.length ? `граф${byFields.length > 1 ? 'ами' : 'ой'} «${byFields.join('», «')}» в паспорте`
              : 'заполняется в паспорте'
            // Предложить снятие обязательности есть смысл только там, где она есть
            // и мешает: пункт обязателен, не закрыт и не из числа неснимаемых.
            const canOfferWaive = !!site.mayWaive && !!it.waivable && it.required
              && !it.done && !it.waived
            return (
              <div key={it.key}>
                <Row type={it.manual ? 'button' : undefined}
                  disabled={it.manual ? mGate.isPending : undefined}
                  onClick={it.manual ? () => mGate.mutate({ key: it.key, done: !it.done }) : undefined}
                  title={it.manual ? 'Отметить вручную' : `Закроется само: ${source}`}
                  className={`flex w-full items-start gap-2 text-left text-sm px-1 py-1 rounded ${
                    it.manual ? 'hover:bg-muted/60 cursor-pointer' : ''}`}>
                  <span className="shrink-0 mt-0.5">
                    {it.done
                      ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                      : <Circle className={`h-3.5 w-3.5 ${it.manual ? '' : 'text-muted-foreground/50'}`} />}
                  </span>
                  {/* Номер пункта регламента: по нему сверяются с бумагой отдела развития. */}
                  <span className="shrink-0 font-mono text-xs text-muted-foreground mt-0.5 w-8"
                    title={it.phaseLabel ? `Этап ${it.phase}. ${it.phaseLabel}` : undefined}>{it.key}</span>
                  <span className={it.done ? '' : 'text-muted-foreground'}>{it.label}</span>
                  {it.role && <span className="text-xs text-muted-foreground shrink-0 mt-0.5">· {it.role}</span>}
                  {/* Снятая обязательность заменяет «держит переход», а не дописывается
                      рядом: две метки об одном и том же противоречили бы друг другу. */}
                  {it.required && !it.waived && <span className="text-xs text-red-500/80 shrink-0 mt-0.5"
                    title="Пока не закрыт, проект дальше не пойдёт">держит переход</span>}
                  {it.waived && <span className="text-xs text-amber-600 dark:text-amber-400 shrink-0 mt-0.5"
                    title="Пункт обязателен по регламенту, но переход больше не держит — под чьей-то ответственностью">
                    не держит переход</span>}
                  {source && <span className="text-xs text-muted-foreground shrink-0 mt-0.5">— {source}</span>}
                </Row>

                {/* Кто снял обязательность и почему. Строка не прячется под тултип:
                    решение принято за всю компанию, и читать его должно быть видно. */}
                {it.waived && (
                  <div className="ml-6 sm:ml-11 mb-1 flex flex-wrap items-baseline gap-x-2 text-xs text-amber-700 dark:text-amber-400">
                    <span>
                      Обязательность снял{it.waivedBy ? ` ${it.waivedBy}` : 'а система'}
                      {it.waivedAt ? `, ${formatDate(it.waivedAt)}` : ''}
                      {it.waiveReason ? `: ${it.waiveReason}` : ''}
                    </span>
                    {site.mayWaive && (
                      <button type="button"
                        className="underline hover:no-underline max-sm:inline-flex max-sm:min-h-11 max-sm:items-center"
                        disabled={mWaive.isPending}
                        onClick={() => mWaive.mutate({ key: it.key, waived: false, reason: '' })}>
                        вернуть обязательность
                      </button>
                    )}
                  </div>
                )}

                {canOfferWaive && waiveFor !== it.key && (
                  <div className="ml-6 sm:ml-11 mb-1">
                    <button type="button"
                      className="text-xs text-muted-foreground underline hover:no-underline max-sm:inline-flex max-sm:min-h-11 max-sm:items-center"
                      onClick={() => { setWaiveFor(it.key); setWaiveWhy('') }}>
                      снять обязательность под свою ответственность
                    </button>
                  </div>
                )}

                {canOfferWaive && waiveFor === it.key && (
                  <div className="ml-6 sm:ml-11 mb-2 space-y-1 rounded border border-amber-500/40 bg-amber-500/5 p-2">
                    <div className="text-xs text-muted-foreground">
                      Пункт останется в чек-листе невыполненным и будет виден в отчёте.
                      Под решением встанет ваше имя.
                    </div>
                    <Textarea value={waiveWhy} onChange={(e) => setWaiveWhy(e.target.value)}
                      rows={2} placeholder="Почему ждать этот пункт не нужно"
                      className="text-sm" />
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline"
                        disabled={!waiveWhy.trim() || mWaive.isPending}
                        onClick={() => mWaive.mutate({
                          key: it.key, waived: true, reason: waiveWhy.trim(),
                        })}>
                        {mWaive.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />}
                        Снять обязательность
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setWaiveFor(null)}>
                        Отмена
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Перевод стадии.
          В девяти случаях из десяти нужен один и тот же шаг — следующая стадия по
          цепочке. Раньше её выбирали в списке из одиннадцати значений, где рядом
          лежали «Заморожен» и «Архив»: рабочее действие и отказ от проекта выглядели
          одинаково. Теперь вперёд — кнопкой, а прыжок через стадию, пауза и отказ —
          отдельно, по явному запросу. */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div data-zone="Перевод на следующую стадию" className="text-sm font-semibold">Стадия</div>
        {!otherStage && nextStage ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="h-8 text-sm"
              disabled={mMove.isPending}
              onClick={() => { setStage(nextStage); mMove.mutate(nextStage) }}>
              {mMove.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}
              {/* Без предлога: «перевести в «Проработка»» требует падежа, которого
                  у названия стадии нет — а склонять названия справочника нельзя. */}
              Дальше: {STAGE_META[nextStage].label}
            </Button>
            <Input value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="Комментарий к переходу (необязательно)"
              className="h-8 text-sm flex-1 min-w-[220px]" />
            <button type="button" onClick={() => setOtherStage(true)}
              className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
              другая стадия, пауза или отказ
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Select value={stage} onValueChange={(v) => setStage(v as SiteStage)}>
              <SelectTrigger className="h-8 w-[190px] text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {FUNNEL_STAGES.map((st) => (
                  <SelectItem key={st} value={st} className="text-sm">{STAGE_META[st].label}</SelectItem>
                ))}
                {/* Пауза и отказ — не продолжение воронки: отделяем чертой и подписью. */}
                <div className="mt-1 border-t px-2 pb-0.5 pt-1 text-xs uppercase tracking-wide text-muted-foreground">
                  выход из работы
                </div>
                <SelectItem value="on_hold" className="text-sm">{STAGE_META.on_hold.label}</SelectItem>
                <SelectItem value="archive" className="text-sm">{STAGE_META.archive.label}</SelectItem>
              </SelectContent>
            </Select>
            {/* «Обязательна по смыслу» — обещание, которого система не выполняла:
                пустую причину принимала, и проект уходил в архив без объяснения.
                Раз обязательна — значит обязательна, кнопка ждёт текста. */}
            <Input value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder={override ? 'Обоснование обхода — обязательно'
                : stage === 'archive' ? 'Причина отклонения — обязательна'
                : stage === 'on_hold' ? 'Что должно случиться, чтобы вернуть проект в работу'
                : 'Комментарий к переходу'}
              className="h-8 text-sm flex-1 min-w-[220px]" />
            <Button size="sm" variant={stage === 'archive' ? 'destructive' : 'default'}
              className="h-8 text-sm"
              disabled={stage === site.stage || mMove.isPending
                || (stage === 'archive' && !reason.trim()) || (override && !reason.trim())}
              onClick={() => mMove.mutate(undefined)}>
              {mMove.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Перевести
            </Button>
            {nextStage && (
              <button type="button" onClick={() => { setOtherStage(false); setStage(site.stage) }}
                className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                вернуться к обычному ходу
              </button>
            )}
          </div>
        )}
        {/* Задвоенный проект. Удаления у проекта нет и не будет: у него уже есть
            история согласований, гейт и переписка — стереть их значит потерять то,
            ради чего проект и ведут. Дубль уходит из воронки как отказ, но с
            причиной, по которой видно, где оригинал (замечание отдела развития
            06.08.2026). */}
        {site.stage !== 'archive' && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {!dupOpen ? (
              <button type="button" onClick={() => setDupOpen(true)}
                className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                Это дубль другого проекта
              </button>
            ) : (
              <>
                <span className="text-xs text-muted-foreground">Дубль проекта</span>
                <Input value={dupNo} onChange={(e) => setDupNo(e.target.value)}
                  placeholder="ЭЗС-2026-0000" className="h-8 w-[190px] text-sm" />
                <Button size="sm" variant="destructive" className="h-8 text-sm"
                  disabled={!dupNo.trim() || mMove.isPending}
                  onClick={() => mMove.mutate({ to: 'archive', reason: `Дубль проекта ${dupNo.trim()}` })}>
                  Пометить дублем
                </Button>
                <button type="button" onClick={() => { setDupOpen(false); setDupNo('') }}
                  className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                  отмена
                </button>
                <span className="text-xs text-muted-foreground">
                  Проект уйдёт из воронки с причиной; номер и история останутся.
                </span>
              </>
            )}
          </div>
        )}
        {stage !== site.stage && gate.blocking.length > 0 && (
          <div className="flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400">
            <Lock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              Обязательное не закрыто: {gate.blocking.join('; ')}. Пока эти пункты не выполнены,
              двигаться вперёд нельзя.
            </span>
          </div>
        )}
        {stage !== site.stage && gate.blocking.length === 0 && missing.length > 0 && (
          <div className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>Не закрыто (необязательное): {missing.map((m) => m.label).join('; ')}. Перевод возможен — запись останется в истории.</span>
          </div>
        )}
        {blocked && mayOverride && (
          <label className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5" />
            <span>
              Провести в обход обязательных пунктов. Обоснование обязательно — впишите его в
              поле рядом с кнопкой «Перевести»; оно попадёт в историю проекта отдельной записью.
            </span>
          </label>
        )}
        {blocked && !mayOverride && (
          <div className="text-xs text-muted-foreground">
            Обход обязательных пунктов делает администратор компании — попросите его
            или закройте оставшиеся пункты.
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          В стадии с {site.stageSince ?? '—'}
          {site.prevStage ? ` · до этого «${STAGE_META[site.prevStage]?.label ?? site.prevStage}»` : ''}
        </div>
      </section>

      {/* Ответственный и следующий шаг */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div data-zone="Ответственный и следующий шаг" className="text-sm font-semibold">Кто ведёт и что дальше</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <div>
            <Label>Ответственный</Label>
            <Select value={owner || '__none__'} onValueChange={(v) => setOwner(v === '__none__' ? '' : v)}>
              <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="Не назначен" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__" className="text-sm">Не назначен</SelectItem>
                {(members.data ?? []).map((m) => (
                  <SelectItem key={m.id} value={m.id} className="text-sm">{m.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <Label>Следующий шаг</Label>
            <Input value={next} onChange={(e) => setNext(e.target.value)} className="h-8 text-sm"
              placeholder="Например: запросить ТУ у сетевой организации" />
          </div>
          <div>
            <Label>Срок</Label>
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)}
              className={`h-8 text-sm ${overdue ? 'border-red-400/60' : ''}`} />
          </div>
          <div className="flex items-end">
            <Button size="sm" variant="outline" className="h-8 text-sm" disabled={mSave.isPending}
              onClick={() => mSave.mutate()}>
              <Save className="h-3.5 w-3.5 mr-1" />Сохранить
            </Button>
          </div>
          <div className="flex items-end text-xs text-muted-foreground">
            Последнее касание: {fmtDate(site.lastTouchAt) || '—'}
          </div>
        </div>
      </section>

      {/* Касание */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-sm font-semibold">Записать касание</div>
        <div className="flex items-start gap-2">
          <Textarea value={touch} onChange={(e) => setTouch(e.target.value)} rows={2}
            placeholder="Звонок, письмо, встреча — что обсудили и о чём договорились"
            className="text-sm min-h-[52px]" />
          <Button size="sm" className="h-8 text-sm shrink-0" disabled={!touch.trim() || mTouch.isPending}
            onClick={() => mTouch.mutate()}>
            <MessageSquarePlus className="h-3.5 w-3.5 mr-1" />Записать
          </Button>
        </div>
      </section>
    </div>
  )
}

/* ── Вкладка «Паспорт» ──────────────────────────────────────────────────── */

const PASSPORT_GROUPS: { title: string; fields: { k: keyof SiteDetail; label: string; type?: 'number' | 'date' | 'text' | 'area' | 'select' | 'bool'; options?: string[] }[] }[] = [
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
  {
    // Этап 2 чек-листа: что осматривают на площадке. Заодно требования
    // программы субсидирования — по ним площадка либо проходит, либо нет.
    title: 'Условия площадки',
    fields: [
      { k: 'access24x7', label: 'Свободный доступ (24/7)', type: 'bool' },
      { k: 'hasVideo', label: 'Видеонаблюдение', type: 'bool' },
      { k: 'hasMobile', label: 'Сотовая связь', type: 'bool' },
      { k: 'hasInternet', label: 'Проводной интернет (LAN)', type: 'bool' },
      { k: 'hasLighting', label: 'Освещение', type: 'bool' },
      { k: 'parkingSpots', label: 'Парковочных мест', type: 'number' },
      { k: 'subsidyPlanned', label: 'Планируется субсидия', type: 'bool' },
      { k: 'subsidyAmount', label: 'Сумма субсидии, ₽', type: 'number' },
      { k: 'dopService', label: 'Доп. сервис (магазин, кафе, WC)' },
    ],
  },
  {
    // Этап 3 чек-листа: экономика подключения и с кем разговаривали.
    title: 'Экономика и контакты',
    fields: [
      { k: 'inputPriceKwth', label: 'Входная стоимость, ₽/кВт·ч', type: 'number' },
      { k: 'smrCost', label: 'Стоимость СМР, ₽', type: 'number' },
      { k: 'rentCostMonth', label: 'Аренда, ₽/мес', type: 'number' },
      { k: 'longTermContract', label: 'Долгосрочный договор', type: 'bool' },
      { k: 'ownerContact', label: 'Контакт представителя собственника', type: 'area' },
      { k: 'sourceCompany', label: 'Предоставивший ЗУ — компания' },
      { k: 'sourcePerson', label: 'Предоставивший ЗУ — ФИО' },
      { k: 'commissionedOn', label: 'Дата ввода в эксплуатацию', type: 'date' },
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
  // графы чек-листа согласования
  inputPriceKwth: 'input_price_kwth', smrCost: 'smr_cost', longTermContract: 'long_term_contract',
  hasVideo: 'has_video', hasMobile: 'has_mobile', hasInternet: 'has_internet',
  hasLighting: 'has_lighting', access24x7: 'access_24x7', parkingSpots: 'parking_spots',
  subsidyPlanned: 'subsidy_planned', subsidyAmount: 'subsidy_amount',
  commissionedOn: 'commissioned_on', ownerContact: 'owner_contact',
  sourceCompany: 'source_company', sourcePerson: 'source_person',
}

// Булево поле в паспорте: сервер принимает «да»/«нет», хранит true/false.
const BOOL_LABEL = (v: unknown) => (v === true ? 'да' : v === false ? 'нет' : '')

/** Адрес почты в свободном тексте контакта: «Иванов И.И., +7…, ivanov@site.ru». */
const emailIn = (text: string): string | null =>
  text.match(/[\w.+-]+@[\w-]+\.[\w.-]+/)?.[0] ?? null

export function PassportTab({ site, companyId, onDone }: { site: SiteDetail; companyId: string; onDone: () => Promise<void> }) {
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

  // Написать собственнику: комната проекта заводится один раз, дальше переписка
  // живёт в ней. Внешний участник отвечает письмом — ответ приходит сюда же.
  const { openInteraction } = useSupportContext()
  const mMail = useMutation({
    mutationFn: async (email: string) => {
      const rooms = await chatApi.getRooms(false, null, site.locationId ?? undefined)
      const title = `Проект ${site.projectNo ?? site.title ?? ''}`.trim()
      const room = rooms.find((r) => r.name === title)
        ?? await chatApi.createRoom('group', [], title, 'projects', site.locationId ?? null)
      await chatApi.addMailParticipant(room.id, email)
      return room.id
    },
    onSuccess: (roomId) => {
      toast.success('Собеседник добавлен — пишите, ему уйдёт письмо')
      openInteraction('chat', `room:${roomId}`)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось открыть переписку'),
  })

  const val = (k: string) => {
    if (k in draft) return draft[k]
    const v = site[k as keyof SiteDetail]
    if (typeof v === 'boolean') return BOOL_LABEL(v)   // «да»/«нет», а не «true»
    return v === null || v === undefined ? '' : String(v)
  }
  const manual = useMemo(() => new Set(site.manualFields ?? []), [site.manualFields])

  // Графы, которых ждёт гейт текущей стадии: по ним видно, что заполнять сейчас,
  // а не искать нужное среди 55 полей паспорта.
  const wanted = useMemo(() => {
    const map = new Map<string, string>()
    for (const i of site.gate?.items ?? []) {
      // Пункт с послаблением графу не подсвечивает: гейт его больше не ждёт.
      if (i.done || i.waived) continue
      for (const f of i.fields ?? []) map.set(f, i.key)
    }
    return map
  }, [site.gate])
  const wantedCount = wanted.size

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Изменённые поля перестают обновляться из файла — в них истина ваша, а не выгрузки.
          {wantedCount > 0 && (
            <> {' '}Подсвечено то, чего ждёт стадия «{site.stageLabel}»: {wantedCount} графы.</>
          )}
        </p>
        <Button size="sm" className="h-8 text-sm" disabled={!dirty || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Сохранить{dirty ? ` (${Object.keys(draft).length})` : ''}
        </Button>
      </div>

      {PASSPORT_GROUPS.map((g) => (
        <section key={g.title} className="rounded-lg border border-border">
          <div className="px-3 py-1.5 text-sm font-semibold border-b bg-muted/40">{g.title}</div>
          <div className="p-3 grid grid-cols-1 md:grid-cols-3 gap-2">
            {g.fields.map((f) => {
              const key = String(f.k)
              const apiKey = API_FIELD[key] ?? key
              const isManual = manual.has(apiKey)
              const needFor = wanted.get(apiKey)
              return (
                <div key={key} className={`${f.type === 'area' ? 'md:col-span-3' : ''} ${
                  needFor ? '-mx-1 rounded-md bg-amber-400/10 px-1 py-0.5 ring-1 ring-amber-400/40' : ''}`}>
                  <Label>
                    {f.label}
                    {isManual && <span className="ml-1 text-xs text-primary" title="Ведётся вручную, импорт не перезапишет">✎</span>}
                    {needFor && (
                      <span className="ml-1.5 rounded bg-amber-400/20 px-1 text-xs text-amber-700 dark:text-amber-400"
                        title={`Закрывает пункт ${needFor} чек-листа текущей стадии`}>
                        нужно для {needFor}
                      </span>
                    )}
                  </Label>
                  {f.type === 'area' ? (
                    <>
                      <Textarea rows={2} className="text-sm min-h-[46px]" value={val(key)}
                        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} />
                      {/* Переписка с контрагентом идёт из карточки, а не из почтового
                          клиента: в контакте собственника обычно записан адрес, и по
                          нему заводится чат проекта с внешним участником — он отвечает
                          письмом, ответ приходит в тот же чат (замечание 06.08.2026). */}
                      {key === 'ownerContact' && emailIn(val(key)) && (
                        <button type="button" disabled={mMail.isPending}
                          onClick={() => mMail.mutate(emailIn(val(key))!)}
                          className="mt-1 rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground hover:border-primary/60 hover:text-foreground">
                          {mMail.isPending
                            ? <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
                            : <MessageSquarePlus className="mr-1 inline h-3 w-3" />}
                          Написать: {emailIn(val(key))}
                        </button>
                      )}
                    </>
                  ) : f.type === 'select' || f.type === 'bool' ? (
                    <Select value={val(key) || '__none__'}
                      onValueChange={(v) => setDraft((d) => ({ ...d, [key]: v === '__none__' ? '' : v }))}>
                      <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-sm">—</SelectItem>
                        {(f.type === 'bool' ? ['да', 'нет'] : f.options ?? []).map((o) => (
                          <SelectItem key={o} value={o} className="text-sm">{o}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input className="h-8 text-sm" type={f.type === 'date' ? 'date' : 'text'}
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
        <div className="flex items-center gap-3 text-sm">
          {site.lat != null && <span className="font-mono text-muted-foreground">{site.lat}, {site.lon}</span>}
          {site.mapUrl && (
            <a href={site.mapUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              Карта <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}

      <div className="border-t pt-2">
        <button type="button" onClick={() => setShowRaw((v) => !v)} className="text-sm text-muted-foreground hover:text-foreground">
          {showRaw ? '▾' : '▸'} Все поля из файла ({Object.keys(site.raw || {}).length})
        </button>
        {showRaw && (
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(site.raw || {}).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-xs border-b border-border/20 py-0.5">
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

export function TechConnectionTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  useEffect(() => setDraft({}), [ctx.data])
  // Справочник для подсказки по сетевой организации: разрез аналитики строится
  // по её имени, поэтому его нужно писать одинаково.
  const counterparties = useQuery({
    queryKey: ['contract-counterparties', companyId],
    queryFn: () => getCounterparties(companyId),
  })

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
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Срок проекта задаёт присоединение: от заявки до исполнения — от двух месяцев
          до полутора лет при реконструкции сети.
        </p>
        <Button size="sm" className="h-8 text-sm" disabled={!dirty || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
          Сохранить
        </Button>
      </div>

      {tc?.overdue && (
        <div className="flex items-center gap-1.5 rounded border border-red-400/50 bg-red-400/5 px-2 py-1.5 text-xs text-red-600 dark:text-red-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          Срок мероприятий сетевой ({tc.dueDate}) прошёл, отметки об исполнении нет.
        </div>
      )}

      <section className="rounded-lg border border-border p-3 grid grid-cols-1 md:grid-cols-3 gap-2">
        <div>
          <Label>Статус</Label>
          <Select value={val('status', tc?.status) || 'draft'} onValueChange={(v) => set('status', v)}>
            <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {ctx.data.tcStatuses.map((s) => (
                <SelectItem key={s.key} value={s.key} className="text-sm">{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Label>Сетевая организация</Label>
          {/* Подсказка из справочника контрагентов: одна и та же сетевая, записанная
              пятью способами, рассыпает разрез по срокам и стоимости. Свободный ввод
              оставлен — новую организацию заводить прямо здесь никто не запрещает. */}
          <Input className="h-8 text-sm" list="grid-operators"
            value={val('grid_operator', tc?.gridOperator)}
            placeholder="Россети Урал" onChange={(e) => set('grid_operator', e.target.value)} />
          <datalist id="grid-operators">
            {(counterparties.data ?? []).map((c) => <option key={c.id} value={c.name} />)}
          </datalist>
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
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox"
              checked={Boolean(('needs_reconstruction' in draft) ? draft.needs_reconstruction : tc?.needsReconstruction)}
              onChange={(e) => set('needs_reconstruction', e.target.checked)} />
            Нужна реконструкция сети
          </label>
        </div>
        <div className="md:col-span-3">
          <Label>Заметка</Label>
          <Textarea rows={2} className="text-sm min-h-[46px]" value={val('note', tc?.note)}
            onChange={(e) => set('note', e.target.value)} />
        </div>
      </section>

      {/* Паспорт питающей сети — графы AQ–BA банка ЗУ. Приезжают из файла отдела
          развития и до сих пор нигде не показывались: без владельца ТП и запаса
          мощности нельзя ни оценить срок, ни понять, к кому идти за резервом. */}
      <section className="rounded-lg border border-border p-3 space-y-2">
        <div className="text-sm font-semibold">Питающая сеть и деньги ТУ</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <Field2 label="Владелец ТП" v={val('substation_owner', tc?.substationOwner)} on={(v) => set('substation_owner', v)} />
          <Field2 label="Владелец линии" v={val('line_owner', tc?.lineOwner)} on={(v) => set('line_owner', v)} />
          <Field2 label="Трансформатор, кВА" v={val('transformer_kva', tc?.transformerKva)} on={(v) => set('transformer_kva', v)} />
          <Field2 label="Тип линии" v={val('line_type', tc?.lineType)} on={(v) => set('line_type', v)} />
          <Field2 label="Срок заявителя, мес." v={val('applicant_term_months', tc?.applicantTermMonths)} on={(v) => set('applicant_term_months', v)} />
          <div />
          <Field2 label="Стоимость работ, ₽" v={val('works_cost', tc?.worksCost)} on={(v) => set('works_cost', v)} />
          <Field2 label="Итого по ТУ, ₽" v={val('total_cost', tc?.totalCost)} on={(v) => set('total_cost', v)} />
          <div className="flex flex-col justify-end gap-1 pb-1">
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox"
                checked={Boolean(('extra_power_possible' in draft) ? draft.extra_power_possible : tc?.extraPowerPossible)}
                onChange={(e) => set('extra_power_possible', e.target.checked)} />
              Есть запас мощности
            </label>
            <label className="flex items-center gap-1.5 text-sm">
              <input type="checkbox"
                checked={Boolean(('transformer_swap_possible' in draft) ? draft.transformer_swap_possible : tc?.transformerSwapPossible)}
                onChange={(e) => set('transformer_swap_possible', e.target.checked)} />
              Возможна замена трансформатора
            </label>
          </div>
        </div>
      </section>
    </div>
  )
}

export function Field2({ label, v, on, type }: { label: string; v: string; on: (v: string) => void; type?: string }) {
  return (
    <div>
      <Label>{label}</Label>
      <Input className="h-8 text-sm" type={type ?? 'text'} value={v} onChange={(e) => on(e.target.value)} />
    </div>
  )
}

/* ── Вкладка «Оборудование» ─────────────────────────────────────────────── */

export function EquipmentTab({ site, companyId, onDone }: {
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
  /** Позиция, которую сейчас ставим на учёт (мастер открыт). */
  const [register, setRegister] = useState<SiteEquipment | null>(null)

  const setSerial = async (id: string, serial: string) => {
    try {
      await saveEquipment(companyId, site.id, { id, serial_number: serial })
      await ctx.refetch()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось записать номер') }
  }

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
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Потребность проекта, а не склад. Пункт гейта «Оборудование поставлено» закрывается,
          когда все позиции получили статус «Поставлено» или «Смонтировано».
        </p>
        <span className={`text-xs rounded border px-1.5 py-0.5 shrink-0 ${eq.allSupplied ? 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80' : 'border-zinc-500/60 text-zinc-500'}`}>
          {eq.allSupplied ? 'всё поставлено' : 'не всё поставлено'}
        </span>
      </div>

      {/* Две ЭЗС на одной площадке — это ДВЕ станции, а не «объект помощнее»
          (замечание отдела развития 06.08.2026; канон объектов: площадка → точка
          обслуживания → станция → коннектор). Точка одна: адрес, договор и выручка
          общие. Учёт ведётся по каждой станции — свой инвентарный номер,
          амортизация, ремонты и перемещение. Поэтому здесь нужна позиция на
          каждую ЭЗС, а не одна строка с количеством: количество не получит ни
          серийного номера, ни движения. */}
      {(site.plannedEzsCount ?? 0) > 1 && (
        <div className="rounded-md border border-amber-400/40 bg-amber-400/5 px-3 py-2 text-xs">
          На площадке планируется <b>{site.plannedEzsCount} ЭЗС</b> — каждая встаёт на учёт
          отдельной станцией: свой инвентарный номер, амортизация и ремонты; адрес,
          договор и выручка при этом общие для точки.
          {eq.items.length < (site.plannedEzsCount ?? 0) && (
            <> Сейчас заведено позиций: {eq.items.length}. Заведите строку на каждую станцию —
            одна строка с количеством {site.plannedEzsCount} серийные номера не разнесёт.</>
          )}
        </div>
      )}

      {/* px-2 на каждой ячейке: без него «Кол-во» и «Поставщик» читаются как
          «Кол-воПоставщик» — колонки стоят впритык, разделителя нет. */}
      {eq.items.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b">
              <th className="text-left px-2 py-1 font-medium">Оборудование</th>
              <th className="text-right px-2 py-1 font-medium">кВт</th>
              <th className="text-right px-2 py-1 font-medium">Кол-во</th>
              {/* Серийный номер вносит ОКС по ходу СМР: до постановки на учёт
                  его негде было записать (замечание отдела развития 07.08.2026). */}
              <th className="text-left px-2 py-1 font-medium">Серийный №</th>
              <th className="text-left px-2 py-1 font-medium">Поставщик</th>
              <th className="text-left px-2 py-1 font-medium">Поставка</th>
              <th className="text-right px-2 py-1 font-medium">Стоимость</th>
              <th className="text-left px-2 py-1 font-medium">Статус</th>
              <th className="text-left px-2 py-1 font-medium">Учёт</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {eq.items.map((e) => (
              <tr key={e.id} className="border-b border-border/30">
                <td className="px-2 py-1.5">
                  {e.title ?? '—'}
                  {e.manufacturer && <span className="text-muted-foreground"> · {e.manufacturer}</span>}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">{e.powerKwt ?? '—'}</td>
                <td className="px-2 py-1.5 text-right font-mono">{e.qty}</td>
                <td className="px-2 py-1.5">
                  {e.unitId ? (
                    <span className="font-mono text-xs">{e.serialNumber ?? '—'}</span>
                  ) : (
                    // Пишется по месту и сохраняется по уходу из поля: номер диктуют
                    // с площадки по телефону, отдельная форма ради одной строки лишняя.
                    <Input defaultValue={e.serialNumber ?? ''} placeholder="SN-…"
                      className="h-7 w-[150px] text-xs font-mono"
                      onBlur={(ev) => {
                        const v = ev.target.value.trim()
                        if (v !== (e.serialNumber ?? '')) void setSerial(e.id, v)
                      }} />
                  )}
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">{e.supplier ?? '—'}</td>
                <td className={`px-2 py-1.5 font-mono ${e.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                  {e.suppliedDate ? `\u2713 ${e.suppliedDate}` : (e.dueDate ?? '—')}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">{e.price != null ? nf0.format(e.price) : '—'}</td>
                <td className="px-2 py-1.5">
                  <Select value={e.status} onValueChange={(v) => setStatus(e.id, v)}>
                    <SelectTrigger className="h-8 w-[150px] text-sm"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {ctx.data.eqStatuses.map((s) => (
                        <SelectItem key={s.key} value={s.key} className="text-sm">{s.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-2 py-1.5">
                  {e.unitId ? (
                    <span className="text-xs text-emerald-600 dark:text-emerald-400">на учёте</span>
                  ) : (
                    <Button size="sm" variant="outline" className="h-7 text-xs"
                      onClick={() => setRegister(e)}>Принять на учёт</Button>
                  )}
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

      {register && (
        <RegisterUnitDialog site={site} companyId={companyId} item={register}
          onClose={() => setRegister(null)}
          onDone={async () => { setRegister(null); await onDone(); await ctx.refetch() }} />
      )}

      <section className="rounded-lg border border-border p-3 grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="md:col-span-2">
          <Label>Оборудование</Label>
          <Input className="h-8 text-sm" placeholder="Быстрая ЭЗС 150 кВт"
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
          <Button size="sm" className="h-8 text-sm" disabled={busy || !form.title.trim()} onClick={add}>
            Добавить
          </Button>
        </div>
      </section>
    </div>
  )
}

/**
 * Мастер «Принять станцию на учёт».
 *
 * Граница между проектом и парком: проект знает, ЧТО площадке нужно, парк —
 * ЧТО за железка и где она. Пока моста не было, ОКС диктовал серийные номера в
 * переписке, а карточку единицы заводили руками по памяти (замечание отдела
 * развития 07.08.2026).
 *
 * Склад поступления обязателен — это основание постановки на учёт. Сразу следом
 * станция уезжает на площадку: числиться в остатках склада всю стройку она не
 * может, иначе инвентаризация склада не сойдётся с тем, что стоит в поле.
 */
function RegisterUnitDialog({ site, companyId, item, onClose, onDone }: {
  site: SiteDetail; companyId: string; item: SiteEquipment
  onClose: () => void; onDone: () => Promise<void>
}) {
  const [serial, setSerial] = useState(item.serialNumber ?? '')
  const [warehouse, setWarehouse] = useState('')
  const [inv, setInv] = useState('')
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10))
  const [install, setInstall] = useState(true)
  const [busy, setBusy] = useState(false)

  const wh = useQuery({
    queryKey: ['equipment-warehouses', companyId],
    queryFn: () => getWarehousesSummary(companyId),
  })
  const rows = wh.data?.warehouses ?? []

  const submit = async () => {
    setBusy(true)
    try {
      const r = await registerEquipmentUnit(companyId, site.id, item.id, {
        serialNumber: serial.trim(), warehouseId: warehouse,
        inventoryNumber: inv.trim() || undefined, occurredOn: when, install,
      })
      toast.success(r.movedToSite
        ? 'Станция на учёте и числится на площадке'
        : 'Станция принята на учёт — лежит на складе')
      await onDone()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось поставить на учёт')
    } finally { setBusy(false) }
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Принять станцию на учёт</DialogTitle></DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="text-muted-foreground">
            {item.title ?? 'Станция'}{item.manufacturer ? ` · ${item.manufacturer}` : ''}
            {item.powerKwt ? ` · ${item.powerKwt} кВт` : ''}
          </div>
          <div>
            <Label>Серийный номер</Label>
            <Input value={serial} onChange={(e) => setSerial(e.target.value)}
              placeholder="SN-…" className="h-8 text-sm font-mono" />
          </div>
          <div>
            <Label>Склад поступления</Label>
            <Select value={warehouse} onValueChange={setWarehouse}>
              <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="Выберите склад" /></SelectTrigger>
              <SelectContent>
                {rows.map((w) => (
                  <SelectItem key={w.location.id} value={w.location.id} className="text-sm">
                    {w.location.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {rows.length === 0 && !wh.isLoading && (
              <p className="mt-1 text-xs text-muted-foreground">
                Складов нет — их заводят в разделе «Оборудование», вкладка «Склады».
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label>Инвентарный №</Label>
              <Input value={inv} onChange={(e) => setInv(e.target.value)}
                placeholder="из бухгалтерии" className="h-8 text-sm font-mono" />
            </div>
            <div>
              <Label>Дата постановки</Label>
              <Input type="date" value={when} onChange={(e) => setWhen(e.target.value)}
                className="h-8 text-sm" />
            </div>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={install} className="mt-0.5"
              onChange={(e) => setInstall(e.target.checked)} disabled={!site.locationId} />
            <span>
              Станция уже на площадке — сразу перевести из склада на объект.
              {!site.locationId && (
                <span className="block text-xs text-muted-foreground">
                  Точка обслуживания у проекта не заведена: свяжите её на вкладке «Паспорт»,
                  иначе станция останется в остатках склада.
                </span>
              )}
            </span>
          </label>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" disabled={busy || !serial.trim() || !warehouse} onClick={submit}>
            {busy && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}Принять на учёт
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ── Вкладка «Документы» ────────────────────────────────────────────────── */

export function DocsTab({ site, companyId, onDone }: {
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
  const download = async (docId: string, name?: string) => {
    try {
      await downloadSiteDoc(companyId, site.id, docId, name)
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Не удалось открыть файл') }
  }

  const rows = docs.data ?? []
  // Какой документ ждёт гейт именно сейчас — по незакрытым пунктам текущей стадии.
  const docGateHint = (site.gate?.items ?? [])
    .filter((i) => !i.done && !i.waived && i.doc)
    .map((i) => i.label)
    .join('; ')
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-8 w-[220px] text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(ctx.data?.docKinds ?? []).map((k) => (
              <SelectItem key={k.key} value={k.key} className="text-sm">{k.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input ref={fileRef} type="file" hidden onChange={(e) => onPick(e.target.files?.[0] ?? null)} />
        <Button size="sm" variant="outline" className="h-8 text-sm" disabled={busy}
          onClick={() => fileRef.current?.click()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
          Приложить документ
        </Button>
        <span className="text-xs text-muted-foreground ml-auto">
          Часть пунктов гейта закрывается именно документом: договор, ТУ, акт приёмки.
        </span>
      </div>

      {docs.isLoading ? (
        <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : rows.length === 0 ? (
        // Пустая вкладка обязана сказать, чем её наполнить: «Документов пока нет»
        // не подсказывает ни какой документ нужен сейчас, ни что он закроет.
        <div className="py-8 text-center text-sm text-muted-foreground">
          <div>Документов пока нет.</div>
          {docGateHint ? (
            <div className="mt-1 text-sm">
              На стадии «{site.stageLabel}» ждём: {docGateHint}. Выберите тип слева и приложите файл —
              пункт гейта закроется сам.
            </div>
          ) : (
            <div className="mt-1 text-sm">
              Сюда кладут договор на землю, ТУ, акт приёмки — файлы, которыми закрываются пункты гейта.
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border divide-y divide-border/40">
          {rows.map((d) => (
            <div key={d.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="rounded border px-1.5 py-0.5 text-xs text-muted-foreground shrink-0">{d.kindLabel}</span>
              {/* Имя файла — ссылка на сам файл: список документов, который нельзя
                  открыть, бесполезен. */}
              <button type="button" disabled={!d.fileId}
                onClick={() => download(d.id, d.fileName ?? d.title ?? undefined)}
                className="truncate flex-1 text-left hover:underline disabled:no-underline disabled:cursor-default"
                title={d.fileId ? `Скачать ${d.fileName ?? ''}` : 'Файл не приложен'}>
                {d.title || d.fileName || '—'}
              </button>
              <span className="text-xs text-muted-foreground whitespace-nowrap">
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

/**
 * Привязка проекта к записи учёта (договор аренды земли, объект сети).
 *
 * До 28.07.2026 ручки привязки существовали, а пути к ним из интерфейса не было:
 * экран «Ждёт учёта» просил «привязать договор в карточке проекта», а кнопки там
 * не было ни одной. Поиск — по уже заведённым записям: учётный контур наполняется
 * в своих разделах, здесь только связь.
 */
function LinkPicker({ label, options, onPick, pending }: {
  label: string
  options: { id: string; title: string; hint?: string }[]
  onPick: (id: string) => void
  pending: boolean
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const found = useMemo(() => {
    const s = q.trim().toLowerCase()
    const list = s ? options.filter((o) => `${o.title} ${o.hint ?? ''}`.toLowerCase().includes(s)) : options
    return list.slice(0, 20)
  }, [options, q])

  if (!open) {
    return (
      <Button variant="outline" size="sm" className="h-8 text-sm mt-1"
        disabled={pending} onClick={() => setOpen(true)}>
        {pending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <LinkIcon className="h-3.5 w-3.5 mr-1" />}
        {label}
      </Button>
    )
  }
  return (
    <div className="mt-1 rounded-md border border-border p-2 space-y-1">
      <Input autoFocus className="h-8 text-sm" placeholder="Поиск…"
        value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="max-h-48 overflow-y-auto">
        {found.length === 0 && (
          <div className="text-xs text-muted-foreground px-1 py-2">
            Ничего не найдено. Договоры заводят в разделе «Договоры», объекты сети — в Центре управления.
          </div>
        )}
        {found.map((o) => (
          <button key={o.id} type="button" disabled={pending}
            onClick={() => { onPick(o.id); setOpen(false) }}
            className="w-full text-left text-sm px-1 py-1 rounded hover:bg-muted/60">
            {o.title}
            {o.hint && <span className="text-muted-foreground"> · {o.hint}</span>}
          </button>
        ))}
      </div>
      <button type="button" className="text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(false)}>Отмена</button>
    </div>
  )
}

/**
 * Работы на объекте: что с ним делали и что можно завести сейчас.
 *
 * Ключ — объект сети, а не место: после ввода именно он опознаёт станцию, и
 * история «стройка → модернизация → перенос» собирается вокруг него.
 *
 * Новая работа — полноценный проект со своим номером, бюджетом и датой ввода,
 * а не приписка к прежнему. По ФСБУ 26/2020 модернизация действующего объекта —
 * отдельное капвложение со своей датой решения; дату ввода первой стройки
 * стирать нельзя, она факт.
 */
function ObjectWorksSection({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const [kind, setKind] = useState('retrofit')
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  const openProject = useOpenProject()
  const works = useQuery({
    queryKey: ['location-works', companyId, site.locationId],
    queryFn: () => getLocationWorks(companyId, site.locationId as string),
    enabled: !!site.locationId,
  })
  const kinds = useQuery({
    queryKey: ['project-kinds', companyId],
    queryFn: () => getProjectKinds(companyId),
  })
  const mStart = useMutation({
    mutationFn: () => startSuccessor(companyId, site.id, { kind, reason: reason.trim() }),
    onSuccess: async (r) => {
      toast.success(`Заведена работа ${r.projectNo} — ${r.kindLabel}`)
      setOpen(false); setReason('')
      await works.refetch(); await onDone()
      // Сразу открываем новую работу: человек завёл её, чтобы ею заниматься.
      openProject(r.siteId)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось завести работу'),
  })

  // Пока объект не привязан, работать не с чем: станции ещё нет.
  if (!site.locationId) {
    return (
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40">Работы на объекте</div>
        <div className="p-3 text-sm text-muted-foreground">
          Объект сети не привязан — это первая стройка на месте. Модернизацию, перенос
          или демонтаж заводят после ввода станции: они относятся к объекту, а не к месту.
        </div>
      </section>
    )
  }

  const rows = works.data ?? []
  return (
    <section className="rounded-lg border border-border">
      <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
        <span>Работы на объекте</span>
        <span className="font-mono text-muted-foreground">{rows.length}</span>
      </div>
      <div className="p-3 space-y-2">
        {rows.map((w) => {
          const here = w.id === site.id
          return (
            <div key={w.id} className="flex flex-wrap items-center gap-2 text-sm">
              <button type="button" disabled={here} onClick={() => openProject(w.id)}
                className={`font-mono ${here ? '' : 'text-primary hover:underline'}`}>
                {w.projectNo ?? '—'}
              </button>
              <span className={here ? 'font-medium' : ''}>{w.title ?? '—'}</span>
              <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[w.stage]?.cls ?? ''}`}>
                {w.stageLabel}
              </span>
              {w.commissionedOn && <span className="text-muted-foreground">введён {w.commissionedOn}</span>}
              {w.archiveReason && <span className="text-muted-foreground">· {w.archiveReason}</span>}
              {here && <span className="text-xs text-muted-foreground">— открыт сейчас</span>}
            </div>
          )
        })}

        {!open ? (
          <Button size="sm" variant="outline" className="h-8 text-sm" onClick={() => setOpen(true)}>
            <Plus className="h-3.5 w-3.5 mr-1" />Завести работу на объекте
          </Button>
        ) : (
          <div className="rounded-md border border-border p-2 space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <Label>Вид работы</Label>
                <Select value={kind} onValueChange={setKind}>
                  <SelectTrigger className="h-8 w-[220px] text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(kinds.data?.kinds ?? []).filter((k) => k.key !== 'new_build').map((k) => (
                      <SelectItem key={k.key} value={k.key} className="text-sm">{k.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Input className="h-8 text-sm flex-1 min-w-[240px]" value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Основание: что случилось и зачем эта работа" />
              <Button size="sm" className="h-8 text-sm" disabled={mStart.isPending || !reason.trim()}
                onClick={() => mStart.mutate()}>
                {mStart.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Завести
              </Button>
              <button type="button" className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setOpen(false)}>отмена</button>
            </div>
            <p className="text-xs text-muted-foreground">
              Откроется новый проект со стадии «Решение»: место известно из прошлой жизни
              объекта, а бюджет, документы и дата ввода у этой работы свои. Прежний проект
              остаётся как есть — его дата ввода не меняется.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

const TICKET_STATUS: Record<string, string> = {
  new: 'новая', open: 'в работе', in_progress: 'в работе', pending: 'ждёт ответа',
  on_hold: 'приостановлена', resolved: 'решена', closed: 'закрыта', cancelled: 'отменена',
}

/**
 * Заявки поддержки по объекту и кнопка завести новую.
 *
 * Граница проходит здесь и нигде больше: работа меняет состав или положение станции —
 * это проект (блок выше); работа восстанавливает работоспособность — это заявка. Держим
 * оба списка рядом, чтобы замену автомата в щите не заводили проектом-ремонтом: иначе
 * реестр проектов перестанет быть реестром капвложений.
 */
function ObjectTicketsSection({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [priority, setPriority] = useState('medium')
  const tickets = useQuery({
    queryKey: ['object-tickets', companyId, site.locationId],
    queryFn: () => getObjectTickets(companyId, site.locationId as string),
    enabled: !!site.locationId,
    retry: false,
  })
  const mCreate = useMutation({
    mutationFn: () => createObjectTicket(companyId, site.locationId as string,
      { description: text.trim(), priority }),
    onSuccess: async (r) => {
      toast.success(`Заявка ${r.display_number ?? r.number} принята поддержкой`)
      setText(''); setOpen(false); await tickets.refetch()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось завести заявку'),
  })

  if (!site.locationId) return null

  const rows = tickets.data?.tickets ?? []
  return (
    <section className="rounded-lg border border-border">
      <div data-zone="Заявки поддержки по объекту"
        className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
        <span>Заявки поддержки по объекту</span>
        <span className="font-mono text-muted-foreground">
          {tickets.data ? `${tickets.data.open} откр. / ${tickets.data.total}` : '—'}
        </span>
      </div>
      <div className="p-3 space-y-2">
        {tickets.isError && (
          <div className="text-sm text-muted-foreground">
            Поддержка сейчас недоступна — список заявок не получен.
          </div>
        )}
        {!tickets.isError && rows.length === 0 && !tickets.isLoading && (
          <div className="text-sm text-muted-foreground">Заявок по этому объекту нет.</div>
        )}
        {rows.map((t) => (
          <div key={t.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-muted-foreground">{t.number}</span>
            <span>{t.title}</span>
            <span className="text-xs rounded border px-1.5 py-0.5">
              {TICKET_STATUS[t.status] ?? t.status}
            </span>
            <span className="text-xs text-muted-foreground">{t.created_at ? formatDate(t.created_at) : '—'}</span>
          </div>
        ))}

        {!open ? (
          <Button size="sm" variant="outline" className="h-8 text-sm" onClick={() => setOpen(true)}>
            <MessageSquarePlus className="h-3.5 w-3.5 mr-1" />Заявка в поддержку
          </Button>
        ) : (
          <div className="rounded-md border border-border p-2 space-y-2">
            <Textarea className="text-sm" rows={3} value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Что случилось и что нужно сделать — не меньше 10 символов" />
            <div className="flex flex-wrap items-center gap-2">
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger className="h-8 w-[160px] text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low" className="text-sm">низкий</SelectItem>
                  <SelectItem value="medium" className="text-sm">обычный</SelectItem>
                  <SelectItem value="high" className="text-sm">высокий</SelectItem>
                  <SelectItem value="critical" className="text-sm">критичный</SelectItem>
                </SelectContent>
              </Select>
              <Button size="sm" className="h-8 text-sm"
                disabled={mCreate.isPending || text.trim().length < 10}
                onClick={() => mCreate.mutate()}>
                {mCreate.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Завести заявку
              </Button>
              <button type="button" className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setOpen(false)}>отмена</button>
            </div>
            <p className="text-xs text-muted-foreground">
              Заявка уходит в поддержку со сроком по регламенту. Проектом заводят работу,
              которая меняет состав или положение станции; восстановление работоспособности —
              заявка.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

export function AccountingTab({ site, companyId, onDone }: {
  site: SiteDetail; companyId: string; onDone: () => Promise<void>
}) {
  const ctx = useQuery({
    queryKey: ['site-project', companyId, site.id],
    queryFn: () => getProjectContext(companyId, site.id),
  })
  // Списки тянем только когда связи ещё нет — иначе это лишние запросы на каждом
  // открытии вкладки у давно привязанного проекта.
  const contracts = useQuery({
    queryKey: ['contracts', companyId],
    queryFn: () => getContracts(companyId),
    enabled: !ctx.data?.contract,
  })
  const locations = useQuery({
    queryKey: ['locations', companyId],
    queryFn: () => loadLocations(companyId),
    enabled: !ctx.data?.location,
  })
  const mLinkContract = useMutation({
    mutationFn: (contractId: string) => linkContract(companyId, site.id, contractId),
    onSuccess: async () => { toast.success('Договор привязан'); await onDone(); await ctx.refetch() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось привязать договор'),
  })
  const mLinkLocation = useMutation({
    mutationFn: (locationId: string) => linkLocation(companyId, site.id, locationId),
    onSuccess: async () => { toast.success('Объект сети привязан'); await onDone(); await ctx.refetch() },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось привязать объект'),
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
        <div data-zone="Связь с учётом: договор и объект" className="text-sm font-semibold">Записи в учёте</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <div>
            <Label>Договор на землю</Label>
            {d.contract ? (
              <div>№ {d.contract.number} от {d.contract.date}
                {d.contract.basis && <span className="text-muted-foreground"> · {d.contract.basis}</span>}
                {d.contract.validUntil && <span className="text-muted-foreground"> · до {d.contract.validUntil}</span>}
              </div>
            ) : (
              <div>
                <div className="text-amber-600 dark:text-amber-400">
                  не привязан{site.contractStart ? ' — а договор уже подписан' : ''}
                </div>
                <LinkPicker label="Привязать договор" pending={mLinkContract.isPending}
                  onPick={(id) => mLinkContract.mutate(id)}
                  options={(contracts.data ?? []).map((c) => ({
                    id: c.id,
                    title: `№ ${c.number}${c.date ? ` от ${c.date}` : ''}`,
                    hint: c.type,
                  }))} />
              </div>
            )}
          </div>
          <div>
            <Label>Объект сети</Label>
            {d.location ? (
              <div>{d.location.name} <span className="text-muted-foreground">({d.location.code})</span></div>
            ) : (
              <div>
                <div className="text-muted-foreground">не связан — проект ещё не стал станцией</div>
                {/* Пункт регламента 8.8 закрывается именно этой связью: пока кнопки
                    не было, обязательный пункт стадии «В эксплуатации» закрыть было нечем. */}
                <LinkPicker label="Привязать объект сети" pending={mLinkLocation.isPending}
                  onPick={(id) => mLinkLocation.mutate(id)}
                  options={(locations.data ?? []).map((l) => ({
                    id: l.id, title: l.name, hint: l.code,
                  }))} />
              </div>
            )}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Записи в бухгалтерии создаются в своих разделах, здесь — только связь: учётный контур
          не должен наполняться побочным эффектом смены статуса проекта.
        </p>
      </section>

      <ObjectWorksSection site={site} companyId={companyId} onDone={onDone} />

      <ObjectTicketsSection site={site} companyId={companyId} />

      {/* субсидия */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
          <span>Субсидия — соответствие требованиям</span>
          <span className={`font-mono ${sub.eligible ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>
            {sub.done} / {sub.total}
          </span>
        </div>
        <div className="p-3 space-y-1">
          {sub.items.map((i) => (
            <div key={i.key} className="flex items-center gap-2 text-sm">
              {i.done
                ? <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                : <Circle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
              <span className={i.done ? '' : 'text-muted-foreground'}>{i.label}</span>
              {i.value && <span className="text-xs text-muted-foreground">— {i.value}</span>}
            </div>
          ))}
          {sub.obligationUntil && (
            <div className="pt-1 text-xs text-muted-foreground">
              Введён {sub.commissionedOn} · обязательство эксплуатировать до {sub.obligationUntil}
              {' '}({sub.obligationYears} лет)
            </div>
          )}
        </div>
      </section>

      {/* бюджет */}
      <section className="rounded-lg border border-border">
        <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40 flex items-center justify-between">
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
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b">
              <th className="text-left py-1 font-medium">Статья</th>
              <th className="text-left py-1 font-medium">Описание</th>
              <th className="text-right py-1 font-medium">План</th>
              <th className="text-right py-1 font-medium">Факт</th>
              <th className="text-right py-1 font-medium">Отклонение</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {ctx.costs.items.map((c) => {
              const diff = c.fact != null && c.plan != null ? c.fact - c.plan : null
              return (
                <tr key={c.id} className="border-b border-border/30">
                  <td className="py-1.5">
                    {c.kindLabel}
                    {/* Капвложение пойдёт в стоимость объекта (08 → 01), расход
                        периода — нет. При отмене проекта их судьба разная. */}
                    <span className="ml-1 text-xs text-muted-foreground"
                      title={c.capital
                        ? 'Капвложение: войдёт в стоимость объекта, при отмене проекта списывается'
                        : 'Расход периода: в стоимость объекта не входит'}>
                      {c.capital ? '· капвложение' : '· расход периода'}
                    </span>
                  </td>
                  <td className="py-1.5 text-muted-foreground">{c.title ?? '—'}</td>
                  <td className="py-1.5 text-right font-mono">{c.plan != null ? nf0.format(c.plan) : '—'}</td>
                  <td className="py-1.5 text-right font-mono">{c.fact != null ? nf0.format(c.fact) : '—'}</td>
                  <td className={`py-1.5 text-right font-mono ${diff && diff > 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                    {diff != null ? `${diff > 0 ? '+' : ''}${nf0.format(diff)}` : '—'}
                  </td>
                  <td className="py-1.5 text-right">
                    <button type="button" onClick={() => remove(c.id)}
                      className="text-muted-foreground hover:text-red-500"><Trash2 className="h-3.5 w-3.5" /></button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {ctx.costs.items.length > 0 && (
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span>Капвложения: план {nf0.format(ctx.costs.capitalPlan ?? 0)} ₽ · факт {nf0.format(ctx.costs.capitalFact ?? 0)} ₽</span>
          <span>Расходы периода: план {nf0.format(ctx.costs.expensePlan ?? 0)} ₽ · факт {nf0.format(ctx.costs.expenseFact ?? 0)} ₽</span>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <Label>Статья</Label>
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="h-8 w-[190px] text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              {ctx.costKinds.map((k) => <SelectItem key={k.key} value={k.key} className="text-sm">{k.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 min-w-[160px]">
          <Label>Описание</Label>
          <Input className="h-8 text-sm" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="w-[120px]"><Label>План, ₽</Label>
          <Input className="h-8 text-sm" value={plan} onChange={(e) => setPlan(e.target.value)} /></div>
        <div className="w-[120px]"><Label>Факт, ₽</Label>
          <Input className="h-8 text-sm" value={fact} onChange={(e) => setFact(e.target.value)} /></div>
        <Button size="sm" className="h-8 text-sm" disabled={busy || (!plan && !fact)} onClick={add}>Добавить</Button>
      </div>
    </div>
  )
}

/* ── Вкладка «Экономика» ────────────────────────────────────────────────── */

export function EconomicsTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
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
          <div className="text-sm font-semibold">Приоритет</div>
          <span className={`text-xs rounded border px-1.5 py-0.5 ${QUADRANT_META[score.quadrant].cls}`}
            title={QUADRANT_META[score.quadrant].hint}>{QUADRANT_META[score.quadrant].label}</span>
        </div>
        <div className="grid grid-cols-3 gap-3 text-sm">
          <Metric label="Привлекательность" value={score.attract != null ? String(score.attract) : '—'} />
          <Metric label="Исполнимость" value={score.feasible != null ? String(score.feasible) : '—'} />
          <Metric label="Уверенность оценки" value={`${score.confidence}%`}
            warn={score.confidence < 34} />
        </div>
        {score.nearestStationKm != null && (
          <div className={`text-xs ${score.cannibalization ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'}`}>
            До ближайшей нашей станции {score.nearestStationKm} км
            {score.cannibalization ? ' — площадка делит трафик с действующей ЭЗС' : ''}
          </div>
        )}
        {score.unknown.length > 0 && (
          <div className="text-xs text-muted-foreground">
            Не хватает: {score.unknown.join('; ')}
          </div>
        )}
      </section>

      {/* Экономика */}
      {!e.ok ? (
        <div className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
          {e.message ?? 'Расчёт недоступен'}
        </div>
      ) : (
        <section className="rounded-lg border border-border">
          <div className="px-3 py-2 text-sm font-semibold border-b bg-muted/40">
            Оценка экономики — по фактическим сессиям сети
          </div>
          <div className="p-3 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <Metric label="Тариф (факт)" value={`${e.tariff} ₽/кВт·ч`} source={e.sources?.tariff} />
              <Metric label="Входная цена" value={`${e.inputPrice} ₽/кВт·ч`} source={e.sources?.inputPrice} />
              <Metric label="Маржа с кВт·ч" value={`${e.marginPerKwh} ₽`} />
              <Metric label="Аренда" value={`${nf0.format(e.rentMonth ?? 0)} ₽/мес`} source={e.sources?.rent} />
            </div>

            <table className="w-full text-sm">
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

            <div className="text-xs text-muted-foreground">
              Капитальные затраты: {e.capex != null ? `${nf0.format(e.capex)} ₽` : 'не посчитаны'}
            </div>

            <div className="rounded border border-border bg-muted/20 p-2">
              <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Допущения расчёта</div>
              <ul className="space-y-0.5 text-xs text-muted-foreground list-disc pl-4">
                {e.assumptions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

function Metric({ label, value, warn, source }: {
  label: string; value: string; warn?: boolean
  /** Откуда цифра: без этого «в экономике не то, что в паспорте» читается как ошибка. */
  source?: string
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold ${warn ? 'text-amber-600 dark:text-amber-400' : ''}`}>{value}</div>
      {source && <div className="text-[11px] leading-tight text-muted-foreground">{source}</div>}
    </div>
  )
}

/* ── Вкладка «История» ──────────────────────────────────────────────────── */

const KIND_LABEL: Record<string, string> = {
  stage: 'Стадия', touch: 'Касание', note: 'Заметка', edit: 'Правка', import: 'Импорт', gate: 'Гейт',
  doc: 'Документ',
}

export function HistoryTab({ site, companyId }: { site: SiteDetail; companyId: string }) {
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
        <div key={e.id} className="flex gap-2 text-sm border-b border-border/30 pb-1.5">
          <span className="text-xs uppercase tracking-wide text-muted-foreground w-16 shrink-0 pt-0.5">
            {KIND_LABEL[e.kind] ?? e.kind}
          </span>
          <div className="min-w-0 flex-1">
            <div className="break-words">{e.text || '—'}</div>
            <div className="text-xs text-muted-foreground">
              {fmtDate(e.createdAt)}{e.author ? ` · ${e.author}` : ''}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Мелочи ─────────────────────────────────────────────────────────────── */

/**
 * Подпись поля в формах проекта.
 *
 * Был свой Label на 10 px капсом — из-за него раздел читался мельче остального
 * пространства (у ui-Label 14 px). Капс оставили как метку служебного текста, но
 * подняли до 12 px: ниже начинается «мелкий шрифт», о который спотыкается любой,
 * кто сидит с этим экраном полдня.
 */
export function Label({ children }: { children: ReactNode }) {
  return <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">{children}</div>
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

