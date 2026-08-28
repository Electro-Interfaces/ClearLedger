/**
 * RightDock — правая вспомогательная область «Взаимодействие».
 *
 * Всегда виден тонкий РЕЙЛ на правом краю (иконки Чат / Заявки / Инфо) — это
 * «тап в правой области»: клик разворачивает ДОК с вкладками (mode='dock', без
 * модалки). Хедер сверху открывает то же модалкой (mode='modal') — обе подачи
 * сосуществуют. Десктоп: пристыкованная панель с resize-ручкой (двигает контент).
 * Мобайл: рейла нет (вход из хедера/низа), док при открытии — полноэкранный оверлей.
 *
 * Экосистемной зоны здесь больше нет: переходы между продуктами пространства
 * («Стол», «Приложения») переехали в шапку — вертикальная колонка их дублировала.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import {
  Bot, CalendarDays, HelpCircle, LifeBuoy, ListChecks, Maximize2, MessageCircle, NotebookPen, Video, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useSupportContext, type InteractionSection } from '@/contexts/SupportContext'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useOptionalWorkspace } from '@/contexts/WorkspaceContext'
import { productForMode } from '@/config/productAccess'
import { productForPath } from '@/config/spaceProducts'
import { TicketsPanel } from './InteractionPanels'
import { TasksQuickPanel } from '@/components/tasks/TasksQuickPanel'
import { CalendarDock } from '@/components/docs/CalendarDock'
import { NotesPage } from '@/pages/docs/NotesPage'
import { InfoContextPanel } from '@/components/info/InfoContextPanel'
import { AuditorPanel } from '@/components/auditor/AuditorPanel'
import { useCompany } from '@/contexts/CompanyContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { startMeeting } from '@/services/conferenceService'

type Tab = {
  key: InteractionSection; label: string; icon: typeof MessageCircle
  /** Наверху и акцентом: отсюда работу заводят, а не только смотрят. */
  primary?: boolean
}
const TABS: Tab[] = [
  // Календарь и записная книжка — то, во что заглядывают поверх работы, а не то,
  // ради чего уходят с экрана: «свободен ли четверг» и «записать, пока помню».
  { key: 'calendar', label: 'Календарь', icon: CalendarDays, primary: true },
  { key: 'notes', label: 'Записи', icon: NotebookPen, primary: true },
  { key: 'chat', label: 'Чат', icon: MessageCircle },
  { key: 'tasks', label: 'Трек', icon: ListChecks },
  // «Аудитор» стоит рядом с «Инфо» осознанно: и то, и другое отвечает на вопрос
  // «что здесь происходит», только справка знает продукт, а аудитор — данные.
  { key: 'auditor', label: 'Аудитор', icon: Bot },
  { key: 'tickets', label: 'Поддержка', icon: LifeBuoy },
  { key: 'help', label: 'Инфо', icon: HelpCircle },
]

/** Области, которым в колонке не хватает места: открываются окном сразу, а не
 *  после того, как человек убедится, что в доке они не читаются. */
const MODAL_ONLY: InteractionSection[] = ['tasks']

/** Сколько места области нужно в доке, если она открывается там. Агенту нужна
 *  рабочая ширина: в ответах таблицы и разбор, а не одна строка. */
const MIN_WIDTH_FOR: Partial<Record<InteractionSection, number>> = {
  auditor: 520, notes: 420, chat: 420, calendar: 400,
}

const DOCK_WIDTH_KEY = 'ledger-dock-width'
const MIN_W = 340
const MAX_W = 760

export function RightDock() {
  const {
    interactionSection: section, interactionMode: mode,
    openInteraction, setInteractionMode, closeInteraction, unreadCounts,
  } = useSupportContext()
  const isMobile = useMaxWidth(1024)
  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(DOCK_WIDTH_KEY))
    return saved >= MIN_W && saved <= MAX_W ? saved : 420
  })
  const draggingRef = useRef(false)

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    draggingRef.current = true
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }, [])
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return
      setWidth(Math.min(MAX_W, Math.max(MIN_W, window.innerWidth - e.clientX)))
    }
    const onUp = () => {
      if (!draggingRef.current) return
      draggingRef.current = false
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      localStorage.setItem(DOCK_WIDTH_KEY, String(width))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [width])

  const badgeOf = (key: InteractionSection) =>
    key === 'chat' ? unreadCounts.chat
      : key === 'tasks' ? unreadCounts.tasks
        : key === 'tickets' ? unreadCounts.tickets : 0

  // «Задачи» в рейле — по тому же праву, что и маршрут: иначе вкладка вела бы в 403.
  // «Аудитор» — по включённости продукта: пространство без него не должно показывать
  // вкладку, которая ответит «сервис не настроен».
  const tasksOn = useDocsApp()
  const [confBusy, setConfBusy] = useState(false)

  /** Создать встречу и отдать гостевую ссылку. Тот же вызов, что у кнопки шапки:
   *  второй способ завести конференцию разошёлся бы с первым. */
  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await startMeeting()
      try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
      toast.success('Конференция создана — гостевая ссылка скопирована',
                    { description: m.guest_url })
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg)
        ? 'Видеоконференции не настроены'
        : 'Не удалось создать конференцию')
    } finally {
      setConfBusy(false)
    }
  }
  const { canApp, appName } = useCompany()
  const tabs = TABS
    .filter((t) => (!['tasks', 'calendar', 'notes'].includes(t.key) || tasksOn)
      && (t.key !== 'auditor' || canApp('auditor')))
    // Имя агента — как его назвала компания: рейл, окно и шапка обязаны говорить
    // одинаково, иначе человек ищет в доке «Аудитора», которого в шапке зовут иначе.
    .map((t) => (t.key === 'auditor' ? { ...t, label: appName('auditor', t.label) } : t))

  const dockOpen = !!section && mode === 'dock'

  /** Открыть область из рельсы её собственным способом. Один обработчик на
   *  рельсу и на шапку дока: два разных поведения у одной кнопки — то, из-за
   *  чего человек перестаёт предсказывать интерфейс. */
  const openFromRail = useCallback((key: InteractionSection) => {
    openInteraction(key)
    if (MODAL_ONLY.includes(key)) {
      setInteractionMode('modal')
      return
    }
    const нужно = MIN_WIDTH_FOR[key]
    if (нужно) setWidth((w) => (w < нужно ? нужно : w))
  }, [openInteraction, setInteractionMode])

  // ── Мобайл: рейла нет; при открытии дока — полноэкранный оверлей ──
  if (isMobile) {
    if (!dockOpen) return null
    return createPortal(
      <div className="fixed inset-0 z-50 flex flex-col bg-card mobile-safe-top mobile-safe-bottom">
        <DockHead tabs={tabs} section={section} badgeOf={badgeOf} isMobile
          onTab={openFromRail} onPop={() => setInteractionMode('modal')} onClose={closeInteraction} />
        <DockBody section={section} />
      </div>,
      document.body,
    )
  }

  // ── Десктоп: док (если открыт) + рейл, который виден ВСЕГДА ──
  // Рейл не исчезает при открытом доке: в нём живёт экосистемная зона (стол,
  // приложения, Центр управления), а она должна быть на месте в любом состоянии.
  // Прикладные вкладки при открытом доке уезжают в его шапку — чтобы не двоились.
  return (
    <>
      {dockOpen && (
        <div className="relative flex h-full shrink-0 flex-col border-l border-border/50 bg-card" style={{ width }}>
          <div onMouseDown={onDragStart}
            className="absolute left-0 top-0 z-10 h-full w-1 -translate-x-1/2 cursor-col-resize bg-transparent transition-colors hover:bg-primary/40" />
          <DockHead tabs={tabs} section={section} badgeOf={badgeOf}
            onTab={openFromRail} onPop={() => setInteractionMode('modal')} onClose={closeInteraction} />
          <DockBody section={section} />
        </div>
      )}

      {/* Колонка видна всегда, но занимает место только когда в ней есть кнопки:
          при открытом доке они уезжают в его шапку, и во всю ширину висела бы
          пустая полоса. */}
      <div data-zone="Взаимодействие: встреча, календарь, записи, чат, заявки, инфо"
        data-zone-side
        className={cn('flex h-full shrink-0 flex-col items-center border-l border-border/50 bg-card transition-[width] duration-200',
          dockOpen ? 'w-3' : 'w-[72px] gap-1 py-3')}>
        {!dockOpen && (
          <>
            {/* Конференция — не область, а действие: она создаёт встречу и отдаёт
                гостевую ссылку. Место наверху, потому что её именно начинают. */}
            {canApp('conf') && (
              <button onClick={startConference} disabled={confBusy}
                title="Видеоконференция — создать и скопировать ссылку"
                className={cn(RAIL_PRIMARY, confBusy && 'opacity-60')}>
                <Video className="size-5" />
                <span>Встреча</span>
              </button>
            )}
            {tabs.filter((t) => t.primary).map((t) => (
              <RailButton key={t.key} tab={t} active={section === t.key} badge={badgeOf(t.key)}
                primary onClick={() => openFromRail(t.key)} />
            ))}
            {/* Черта: выше — то, что отсюда заводят, ниже — области, у которых есть
                и кнопка в шапке. */}
            <div className="my-2 h-px w-8 bg-border" role="separator" />
            {tabs.filter((t) => !t.primary).map((t) => (
              <RailButton key={t.key} tab={t} active={section === t.key} badge={badgeOf(t.key)}
                onClick={() => openFromRail(t.key)} />
            ))}
          </>
        )}
      </div>
    </>
  )
}

function DockHead({ tabs, section, badgeOf, isMobile, onTab, onPop, onClose }: {
  tabs: Tab[]
  section: InteractionSection
  badgeOf: (k: InteractionSection) => number
  isMobile?: boolean
  onTab: (k: InteractionSection) => void
  onPop: () => void
  onClose: () => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-1 border-b border-border/50 bg-card px-2 py-1.5">
      {tabs.map((t) => {
        const active = section === t.key
        const badge = badgeOf(t.key)
        return (
          <button key={t.key} onClick={() => onTab(t.key)}
            className={cn('relative inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors',
              active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
            <t.icon className="size-4" />
            <span>{t.label}</span>
            {badge > 0 && (
              <span className="ml-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">{badge}</span>
            )}
          </button>
        )
      })}
      <div className="flex-1" />
      {!isMobile && (
        <button onClick={onPop} title="Открыть окном"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <Maximize2 className="size-4" />
        </button>
      )}
      <button onClick={onClose} title="Закрыть"
        className="inline-flex size-7 max-md:size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
        <X className="size-4" />
      </button>
    </div>
  )
}

/** «Инфо» в доке: контекст берётся из адреса, компания — из активного пространства. */
function InfoDockPanel() {
  const { companyId } = useCompany()
  // Закрытие — именно закрытие: `toggleInteraction` из дока перебросил бы панель в
  // окно, то есть крестик открывал бы другое представление вместо того, чтобы уйти.
  const { closeInteraction } = useSupportContext()
  if (!companyId) return null
  return <InfoContextPanel companyId={companyId} embedded onClose={closeInteraction} />
}

/** Спокойная кнопка рельсы и её акцентный вариант — тот же синий, что у пилюль
 *  шапки: одно значение цвета на всё пространство. */
const RAIL_BASE = 'relative flex min-h-[52px] w-16 flex-col items-center justify-center gap-1 rounded-lg px-1 py-1.5 text-center text-xs leading-tight transition-colors'
const RAIL_PRIMARY = `${RAIL_BASE} border border-primary/30 bg-primary/10 text-primary hover:bg-primary hover:text-white dark:bg-primary/20 dark:border-primary/50`

function RailButton({ tab, active, badge, primary, onClick }: {
  tab: Tab; active: boolean; badge: number; primary?: boolean; onClick: () => void
}) {
  return (
    <button onClick={onClick} title={`${tab.label} — открыть справа`}
      aria-current={active ? 'true' : undefined}
      className={cn(primary ? RAIL_PRIMARY : RAIL_BASE,
        !primary && (active
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'),
        primary && active && 'bg-primary text-white')}>
      <tab.icon className="size-5" />
      <span>{tab.label}</span>
      {badge > 0 && (
        <span className="absolute right-0.5 top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold leading-none text-white">{badge}</span>
      )}
    </button>
  )
}

function DockBody({ section }: { section: InteractionSection }) {
  // Док открыт ИЗ приложения — значит и чаты показываем его: код продукта выводится
  // из активного раздела рабочей области. Верхняя кнопка (модалка) продукт не
  // передаёт и показывает все чаты пространства — это тот же чат, другие предустановки.
  // Вне рабочей области (приложение «Чаты», «Управление») контекста нет — и это
  // нормально: тогда чат просто не сужается до продукта и показывает всё пространство.
  // Продукт берём по МАРШРУТУ, и только потом по активному режиму: режим приходит из
  // ?mode=, а на рабочем столе продукта его в адресе ещё нет — тогда `productForMode`
  // отдавала null, фильтр пропадал, и в «Топливе» рельса показывала чаты «Магазина» и
  // «Процессинга». Маршрут известен всегда.
  const { pathname } = useLocation()
  const ws = useOptionalWorkspace()
  const product = productForPath(pathname)?.code ?? (ws ? productForMode(ws.coreMode) : null)
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      {section === 'chat' && <ChatPanel compact scopeProduct={product} />}
      {/* Док узкий: рельса разрезов и полоса дня туда не помещаются — панель
          показывает разрезы строкой поверх списка. */}
      {section === 'tasks' && <TasksQuickPanel compact />}
      {/* В доке — не второй календарь, а приёмник: сюда бросают дело, и оно
          встаёт на день. Полный месяц с участниками живёт окном из шапки. */}
      {section === 'calendar' && <CalendarDock />}
      {section === 'notes' && <div className="h-full overflow-y-auto"><NotesPage /></div>}
      {/* Аудитор берёт контекст сам (маршрут и параметры адреса) — доку не нужно
          ничего ему передавать, и та же панель работает из шапки. */}
      {section === 'auditor' && <AuditorPanel />}
      {section === 'tickets' && <TicketsPanel />}
      {/* «Инфо» — знание пространства под открытую рабочую область, а не статичный
          текст про один продукт (docs/INFO.md). */}
      {section === 'help' && <InfoDockPanel />}
    </div>
  )
}
