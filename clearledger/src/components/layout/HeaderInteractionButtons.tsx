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
import { Bot, HelpCircle, LifeBuoy, ListChecks, MessageCircle, Video } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { startMeeting } from '@/services/conferenceService'
import { useSupportContext } from '@/contexts/SupportContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { useCompany } from '@/contexts/CompanyContext'

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
  const { canApp } = useCompany()
  const { interactionSection, toggleInteraction, unreadCounts } = useSupportContext()
  const [confBusy, setConfBusy] = useState(false)
  const tasksOn = useDocsApp()

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
      {conference && canApp('conf') && (
        <Button variant="outline" size="sm" onClick={startConference} disabled={confBusy}
          className={btnCls(false)} title="Видеоконференция">
          <Video className="h-4 w-4" />
          <span className="hidden lg:inline">Конференция</span>
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
      {canApp('auditor') && (
        <Button variant="outline" size="sm" onClick={() => toggleInteraction('auditor')}
          className={`hidden lg:inline-flex ${btnCls(interactionSection === 'auditor')}`}
          title="Аудитор: спросить про этот экран">
          <Bot className="h-4 w-4" />
          <span className="hidden lg:inline">Аудитор</span>
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
