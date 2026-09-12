/**
 * Кнопки взаимодействия в шапке: Чат · Трек · Инфо (+ Конференция там, где она
 * уместна) пилюлями, поддержка поставщика — иконкой следом. Общий блок продуктов
 * контейнера: в Учёте и в «Управлении» он выглядит и работает одинаково, а не
 * находится каждый раз заново.
 *
 * Открывают ту же область «Взаимодействие», что и правый рейл (`RightDock`):
 * из шапки — окном, из рейла — доком. Оба состояния живут в `SupportContext`.
 */
import { useState } from 'react'
import {
  Bot, CalendarDays, HelpCircle, LifeBuoy, ListChecks, ListVideo, MessageCircle, Video,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { createMeeting, joinMeeting } from '@/services/confService'
import { useNavigate } from 'react-router-dom'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { isDemoMode } from '@/services/apiClient'
import { useSupportContext } from '@/contexts/SupportContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'

/** Пилюля-кнопка: синий акцент, активное состояние — как у остальных кнопок шапки. */
const btnCls = (active: boolean) =>
  `relative h-11 min-w-11 px-3 gap-2 rounded-xl transition-all duration-200 font-medium border ${
    active
      ? 'bg-primary text-white border-primary'
      : 'bg-primary/10 dark:bg-primary/20 hover:bg-primary text-primary dark:text-primary/80 hover:text-white border-primary/30 dark:border-primary/50 hover:border-primary'
  }`

function Badge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span className="absolute -right-1.5 -top-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
      {count}
    </span>
  )
}

export function HeaderInteractionButtons({ conference = false }: { conference?: boolean }) {
  // Решение МАГа 13.08.2026: чат и «Инфо» сквозные, их видит каждый, кого пустили в
  // пространство (без них человек нем и слеп). Конференция и поддержка поставщика -
  // обычные продукты реестра и показываются только при праве на них: раньше кнопки
  // стояли у всех, и человек с одним выданным приложением видел в шапке четыре чужих.
  const { canApp, appName, companyId } = useCompany()
  const navigate = useNavigate()
  // Как продукт назван в ЭТОМ пространстве: «Аудитор» у аудиторской практики,
  // «Агенты» там, где их несколько и их учат. Надпись живёт в реестре компании,
  // а не в коде кнопки.
  const agentName = appName('auditor', 'Аудитор')
  const { interactionSection, toggleInteraction, unreadCounts } = useSupportContext()
  const [confBusy, setConfBusy] = useState(false)
  const tasksOn = useDocsApp()

  // Быстрый созвон заводится тем же путём, что и назначенный: встреча в
  // календаре плюс строка в журнале «Конференций». Иначе созвон «на ходу»
  // нигде не остаётся, и через день доказать, что он был, нечем.
  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await createMeeting(companyId, { title: '', notify: false })
      await joinMeeting(companyId, m.id)
      try { await navigator.clipboard.writeText(m.guest_url || '') } catch { /* буфер недоступен */ }
      toast.success('Конференция создана — ссылка для участников скопирована',
        { description: m.guest_url || undefined })
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Видеоконференции не настроены' : 'Не удалось создать конференцию')
    } finally {
      setConfBusy(false)
    }
  }

  return (
    // Блок виден и на телефоне: чат, задачи и конференция — то, ради чего человек
    // берёт трубку в руки. Прежде он прятался на md:, и в мобильной шапке от него
    // оставалась одна кнопка чата.
    <div className="flex items-center gap-1.5 pl-1 md:gap-2">
      <div className="hidden h-6 w-px bg-border/50 md:block" />
      {/* Конференция стоит во всех шапках (просьба МАГа 10.09.2026): созвон зовут из
          любого экрана, а не только с рабочего стола. На телефоне её прячем везде,
          кроме стола: шестая кнопка наезжала на бургер и выдавливала профиль за край
          (проверка МАГа 06.09.2026) — там вход остаётся на пульте и в меню профиля. */}
      {canApp('conf') && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={confBusy}
              className={cn(btnCls(false), !conference && 'hidden md:inline-flex')}
              title="Конференции">
              <Video className="h-4 w-4" />
              <span className="hidden lg:inline">Конференция</span>
            </Button>
          </DropdownMenuTrigger>
          {/* Два действия, а не одно: созвониться сейчас и посмотреть, что идёт,
              что назначено и что было. Раньше кнопка умела только заводить новую
              комнату, и вернуться во вчерашний разговор было некуда. */}
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={startConference}>
              <Video className="mr-2 h-4 w-4" />Созвониться сейчас
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate('/conf')}>
              <ListVideo className="mr-2 h-4 w-4" />Все конференции
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {/* Полный календарь: месяц, участники, согласия — работа В календаре, и ей
          нужно окно. Контекстный приёмник «положить дело на день» живёт в правой
          рельсе и открывается доком. */}
      {tasksOn && (
        <Button variant="outline" size="sm" onClick={() => toggleInteraction('calendar')}
          className={btnCls(interactionSection === 'calendar')} title="Календарь пространства">
          <CalendarDays className="h-4 w-4" />
          <span className="hidden lg:inline">Календарь</span>
        </Button>
      )}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('chat')} className={btnCls(interactionSection === 'chat')} title="Чаты пространства">
        <MessageCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Чат</span>
        <Badge count={unreadCounts.chat} />
      </Button>
      {/* «Трек» — как чат рядом: кнопка открывает окно «что на мне сейчас» (визы и
          поручения), а не уводит со страницы. Полноценное рабочее место —
          реестры, маршруты, регламент — живёт приложением, и в него ведёт
          «Открыть Трек» из этого же окна. */}
      {tasksOn && (
        <Button variant="outline" size="sm" onClick={() => toggleInteraction('tasks')} className={btnCls(interactionSection === 'tasks')} title="Трек: что на мне сейчас">
          <ListChecks className="h-4 w-4" />
          <span className="hidden lg:inline">Трек</span>
          <Badge count={unreadCounts.tasks} />
        </Button>
      )}
      {/* «Аудитор» — тот же жест, что чат: кнопка открывает окно, где спрашивают про
          текущий экран. Показывается только там, где продукт включён компании: иначе
          человек звал бы агента, которого в стеке нет. */}
      {!isDemoMode() && canApp('auditor') && (
        <Button variant="outline" size="sm" onClick={() => toggleInteraction('auditor')}
          className={`hidden lg:inline-flex ${btnCls(interactionSection === 'auditor')}`}
          title={`${agentName}: спросить про этот экран`}>
          <Bot className="h-4 w-4" />
          <span className="hidden lg:inline">{agentName}</span>
        </Button>
      )}
      {/* «Инфо» — четвёртая кнопка, на телефоне уже теснит имя экрана. Справка
          доступна оттуда же, куда ведёт плитка «Инфо» на столе. */}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('help')}
        className={btnCls(interactionSection === 'help')} title="Инфо (Ctrl+K)">
        <HelpCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Инфо</span>
      </Button>
      {/* Поддержка поставщика программы — иконкой, в одном ряду с лампочкой и
          режимом работы: обращение редкое, а место в шапке дорогое. */}
      {canApp('support') && (
      <Button
        variant="ghost"
        size="icon"
        aria-pressed={interactionSection === 'tickets'}
        onClick={() => toggleInteraction('tickets')}
        className={`h-11 w-11 rounded-xl ${interactionSection === 'tickets' ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'}`}
        title="Поддержка платформы: вопросы и ошибки по программе"
      >
        <LifeBuoy className="h-[18px] w-[18px]" />
        <Badge count={unreadCounts.tickets} />
      </Button>
      )}
    </div>
  )
}
