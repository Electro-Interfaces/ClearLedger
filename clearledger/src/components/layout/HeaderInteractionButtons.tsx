/**
 * Кнопки взаимодействия в шапке: Чат · Задачи · Инфо (+ Конференция там, где она
 * уместна) пилюлями, поддержка поставщика — иконкой следом. Общий блок продуктов
 * контейнера: в Учёте и в «Управлении» он выглядит и работает одинаково, а не
 * находится каждый раз заново.
 *
 * Открывают ту же область «Взаимодействие», что и правый рейл (`RightDock`):
 * из шапки — окном, из рейла — доком. Оба состояния живут в `SupportContext`.
 */
import { useState } from 'react'
import { HelpCircle, LifeBuoy, ListChecks, MessageCircle, Video } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { startMeeting } from '@/services/conferenceService'
import { useSupportContext } from '@/contexts/SupportContext'
import { useTasksApp } from '@/hooks/useTasksApp'

/** Пилюля-кнопка: синий акцент, активное состояние — как у остальных кнопок шапки. */
const btnCls = (active: boolean) =>
  `relative h-11 px-3 gap-2 rounded-xl transition-all duration-200 font-medium border ${
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
  const { interactionSection, toggleInteraction, unreadCounts } = useSupportContext()
  const [confBusy, setConfBusy] = useState(false)
  const tasksOn = useTasksApp()

  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await startMeeting()
      try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
      toast.success('Конференция создана — гостевая ссылка скопирована', { description: m.guest_url })
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
      {conference && (
        <Button variant="outline" size="sm" onClick={startConference} disabled={confBusy} className={btnCls(false)} title="Видеоконференция">
          <Video className="h-4 w-4" />
          <span className="hidden lg:inline">Конференция</span>
        </Button>
      )}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('chat')} className={btnCls(interactionSection === 'chat')} title="Чаты пространства">
        <MessageCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Чат</span>
        <Badge count={unreadCounts.chat} />
      </Button>
      {/* «Задачи» — как чат рядом: кнопка открывает окно «что на мне сейчас», а не
          уводит со страницы. Полноценный трекер (типы, маршруты, чужие задачи, след)
          живёт приложением, и в него ведёт «Все задачи» из этого же окна. Поддержка
          поставщика ушла иконкой ниже: туда ходят редко и по случаю. */}
      {tasksOn && (
        <Button variant="outline" size="sm" onClick={() => toggleInteraction('tasks')} className={btnCls(interactionSection === 'tasks')} title="Задачи: что на мне сейчас">
          <ListChecks className="h-4 w-4" />
          <span className="hidden lg:inline">Задачи</span>
          <Badge count={unreadCounts.tasks} />
        </Button>
      )}
      {/* «Инфо» — четвёртая кнопка, на телефоне уже теснит имя экрана. Справка
          доступна оттуда же, куда ведёт плитка «Инфо» на столе. */}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('help')} className={`hidden sm:inline-flex ${btnCls(interactionSection === 'help')}`} title="Инфо (Ctrl+K)">
        <HelpCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Инфо</span>
      </Button>
      {/* Поддержка поставщика программы — иконкой, в одном ряду с лампочкой и
          режимом работы: обращение редкое, а место в шапке дорогое. */}
      <Button
        variant="ghost"
        size="icon"
        aria-pressed={interactionSection === 'tickets'}
        onClick={() => toggleInteraction('tickets')}
        className={`h-10 w-10 rounded-xl ${interactionSection === 'tickets' ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'}`}
        title="Поддержка платформы: вопросы и ошибки по программе"
      >
        <LifeBuoy className="h-[18px] w-[18px]" />
        <Badge count={unreadCounts.tickets} />
      </Button>
    </div>
  )
}
