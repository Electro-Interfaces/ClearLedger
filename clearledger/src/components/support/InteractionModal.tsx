/**
 * InteractionModal — подача разделов «Взаимодействие» окном (mode='modal').
 *
 * Вызов из ВЕРХНЕГО хедера открывает Чат/Заявки поверх всего (modal={false},
 * кнопки шапки остаются кликабельны). Инфо — modal=true (focus-trap для чтения).
 * Кнопка «закрепить справа» переносит раздел в правый док (setInteractionMode).
 * Чат в окне — полная 3-колоночная раскладка (в отличие от компактного дока).
 */
import { lazy, Suspense, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, PanelRight } from 'lucide-react'
import { useSupportContext } from '@/contexts/SupportContext'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import { useIsMobile } from '@/hooks/use-mobile'

const ChatPanel = lazy(() => import('@/components/chat/ChatPanel').then((m) => ({ default: m.ChatPanel })))
const TicketsPanel = lazy(() => import('./InteractionPanels').then((m) => ({ default: m.TicketsPanel })))
const TasksQuickPanel = lazy(() => import('@/components/tasks/TasksQuickPanel').then((m) => ({ default: m.TasksQuickPanel })))
const CalendarPage = lazy(() => import('@/pages/docs/CalendarPage').then((m) => ({ default: m.CalendarPage })))
const NotesPage = lazy(() => import('@/pages/docs/NotesPage').then((m) => ({ default: m.NotesPage })))
const InfoCenter = lazy(() => import('@/components/info/InfoCenter').then((m) => ({ default: m.InfoCenter })))
const AuditorWorkspace = lazy(() => import('@/pages/AuditorPage').then((m) => ({ default: m.AuditorWorkspace })))

const panelFallback = (
  <div className="flex h-full items-center justify-center">
    <Loader2 className="size-5 animate-spin text-muted-foreground" />
  </div>
)

// Ключ секции остался `tickets` (он в localStorage у людей), а подпись — «Поддержка»:
// это разговор с поставщиком программы, а не заявки компании и не «Трек».
const TITLES: Record<string, string> = {
  chat: 'Чат', tasks: 'Трек', tickets: 'Поддержка', help: 'Инфо', auditor: 'Аудитор',
  calendar: 'Календарь',
  notes: 'Записная книжка',
}

/**
 * Агент в окне из шапки — то же рабочее место, что на странице приложения: рельса
 * разделов слева, содержимое справа. Раздел живёт ЗДЕСЬ, а не в адресе: окно висит
 * поверх рабочего экрана, и менять его адрес значило бы уводить человека с того
 * места, ради которого он агента и позвал.
 */
function AuditorAtHand() {
  const [view, setView] = useState('chat')
  return <AuditorWorkspace view={view} onView={setView} />
}

/**
 * Прямоугольник окна связи на телефоне: от края до края, между шапкой пространства
 * и нижней панелью.
 *
 * Задаём ВСЕ четыре стороны и гасим центрирование. Radix ставит окну `left:50%`,
 * `top:50%` и сдвигает его на половину собственного размера; попытки поправить
 * только высоту и верх ломали горизонталь — окно уезжало то вправо, то влево, а
 * заголовок с крестиком оказывался за краем экрана (правки 07.09.2026).
 */
const MOBILE_WINDOW: React.CSSProperties = {
  left: 0,
  right: 0,
  width: '100%',
  maxWidth: 'none',
  // Сдвиг «на половину себя» Tailwind 4 задаёт ОТДЕЛЬНЫМ свойством `translate`,
  // а не `transform`. Две правки подряд гасили `transform` и не работали: окно
  // так и уезжало влево-вверх (разбор в браузере 07.09.2026 — computed показал
  // `transform: none`, `translate: -50% -50%`).
  transform: 'none',
  translate: 'none',
  top: 'calc(var(--header-height) + env(safe-area-inset-top))',
  bottom: 'calc(3.5rem + env(safe-area-inset-bottom))',
  height: 'auto',
  maxHeight: 'none',
}

export function InteractionModal() {
  const { interactionSection: section, interactionMode: mode, setInteractionMode, closeInteraction } = useSupportContext()
  const isMobile = useIsMobile()
  const aboveMobileNav = isMobile ? MOBILE_WINDOW : undefined
  // Заголовок окна берёт имя продукта у компании — там, где агентов зовут «Агенты»,
  // окно не должно называться «Аудитор».
  const { appName } = useCompany()
  const isOpen = !!section && mode === 'modal'
  // Список окон ЗАКРЫТЫЙ: раздел, которого здесь нет, из шапки просто не открывается —
  // кнопка нажимается, состояние меняется, а окна нет и ошибки тоже. Так и было с
  // «Аудитором» на первом выкате.
  const isPanel = section === 'chat' || section === 'tasks' || section === 'tickets'
    || section === 'auditor' || section === 'calendar' || section === 'notes'

  const DockButton = (
    <button
      onClick={() => setInteractionMode('dock')}
      title="Закрепить справа"
      className="absolute right-11 top-3 z-10 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <PanelRight className="size-4" />
    </button>
  )

  return (
    <>
      {/* Приглушающая подложка под Чат/Заявки (modal={false} не даёт overlay).
          pointer-events-none — клики проходят сквозь, шапка остаётся доступной. */}
      {isPanel && isOpen &&
        createPortal(
          <div className="fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-[2px] pointer-events-none" aria-hidden />,
          document.body,
        )}

      {/* Чат / Заявки — окно поверх экрана. Чат шире (3 колонки: папки+список+переписка) */}
      <Dialog open={isPanel && isOpen} onOpenChange={(o) => { if (!o) closeInteraction() }} modal={false}>
        <DialogContent
          onInteractOutside={(e) => e.preventDefault()}
          // Окно заканчивается НАД нижней панелью: она единственная навигация под
          // пальцем и пропадать не должна (решение МАГа 06.09.2026). Стилем, а не
          // классом: утилиты диалога (`top-[50%]`, `translate-y-[-50%]`, высота)
          // живут в слое utilities и перебивают любой свой класс — окно оставалось
          // во весь экран, сколько его ни правь снаружи.
          style={aboveMobileNav}
          className={
            'p-0 gap-0 bg-card border-border text-foreground shadow-2xl ring-1 ring-black/5 dark:ring-white/10 '
            + 'w-screen max-w-none max-h-none rounded-none overflow-hidden flex flex-col '
            // Нижняя панель не скрывается никогда (решение МАГа 06.09.2026):
            // окно занимает экран до неё, а не поверх неё. Панель — единственная
            // навигация на телефоне, и терять её, открыв чат, нельзя.
            + 'sm:rounded-xl '
            // «Трек» идёт по мерке чата: это тоже рабочее окно, а не сводка —
            // строка задачи несёт номер, проект, стадию, срок и кнопки, и на
            // прежних 5xl всё это ломалось в три этажа.
            // Агент идёт по той же мерке: в ответах таблицы, находки и разбор данных,
            // а рядом — каталог того, о чём вообще можно спросить. На прежних 5xl всё
            // это переносилось по слогам, и окно выглядело уже, чем соседние.
            // Календарь идёт по той же мерке: месяц с встречами и сроками —
            // это сетка, а не список, и на узком окне она перестаёт отвечать на
            // свой вопрос «свободен ли четверг».
            + (section === 'chat' || section === 'tasks' || section === 'auditor'
              || section === 'calendar'
              ? 'sm:w-[96vw] sm:max-w-[1600px] md:h-[92dvh] md:max-h-[92dvh]'
              : 'sm:w-[92vw] sm:max-w-2xl md:h-[70vh] md:max-h-[70vh]')
          }
        >
          {DockButton}
          <DialogHeader className="px-4 py-3 border-b border-border/50 shrink-0 text-left">
            <DialogTitle className="text-foreground text-base">
              {section === 'auditor' ? appName('auditor', TITLES.auditor) : (section ? TITLES[section] : '')}
            </DialogTitle>
            <DialogDescription className="sr-only">Модуль взаимодействия с поддержкой</DialogDescription>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-hidden">
            <Suspense fallback={panelFallback}>
              {section === 'chat' && <ChatPanel />}
              {section === 'tasks' && <TasksQuickPanel />}
              {section === 'calendar' && <CalendarPage />}
              {section === 'notes' && <NotesPage />}
              {section === 'tickets' && <TicketsPanel />}
              {section === 'auditor' && <AuditorAtHand />}
            </Suspense>
          </div>
        </DialogContent>
      </Dialog>

      {/* Инфо — модалка-destination (modal=true): полный центр знания, а не
          страничка «о системе». Дерево слева, статья справа — из шапки человек
          идёт искать сам, поэтому ему нужен весь состав, а не подборка. */}
      <Dialog open={section === 'help' && isOpen} onOpenChange={(o) => { if (!o) closeInteraction() }}>
        <DialogContent style={aboveMobileNav}
          className={'p-0 gap-0 bg-card border-border text-foreground shadow-2xl ring-1 ring-black/5 dark:ring-white/10 '
          + 'w-screen max-w-none max-h-none rounded-none overflow-hidden flex flex-col '
          // Как и у окон связи: на телефоне «Инфо» заканчивается над нижней панелью.

          + 'sm:w-[94vw] sm:max-w-6xl md:h-[88vh] md:max-h-[88vh] sm:rounded-xl'}>
          {DockButton}
          <DialogHeader className="px-4 py-3 border-b border-border/50 shrink-0 text-left">
            <DialogTitle className="text-foreground text-base">Инфо — база знаний и инструкции</DialogTitle>
            <DialogDescription className="sr-only">Знание пространства: инструкции, нормы и документы компании</DialogDescription>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-hidden">
            <Suspense fallback={panelFallback}>
              {section === 'help' && <InfoModalBody />}
            </Suspense>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Тело окна «Инфо»: тот же центр знания, что открывается со стола. */
function InfoModalBody() {
  const { companyId } = useCompany()
  if (!companyId) return null
  return <InfoCenter companyId={companyId} variant="modal" />
}
