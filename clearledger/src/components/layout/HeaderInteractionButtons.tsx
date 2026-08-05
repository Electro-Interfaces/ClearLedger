/**
 * Кнопки взаимодействия в шапке: Чат · Заявки · Инфо (+ Конференция там, где она
 * уместна). Общий блок продуктов контейнера — в Учёте и в «Управлении» вход в
 * поддержку выглядит и работает одинаково, а не находится каждый раз заново.
 *
 * Открывают ту же область «Взаимодействие», что и правый рейл (`RightDock`):
 * из шапки — окном, из рейла — доком. Оба состояния живут в `SupportContext`.
 */
import { useState } from 'react'
import { HelpCircle, LifeBuoy, MessageCircle, Video } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { createMeeting } from '@/services/conferenceService'
import { useSupportContext } from '@/contexts/SupportContext'

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

  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await createMeeting()
      window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
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
    // Блок виден и на телефоне: чат, заявки и конференция — то, ради чего человек
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
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('chat')} className={btnCls(interactionSection === 'chat')} title="Чат с поддержкой">
        <MessageCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Чат</span>
        <Badge count={unreadCounts.chat} />
      </Button>
      {/* «Поддержка», а не «Заявки»: за этим словом в пространстве уже стоят две
          другие вещи — заявки сервисной службы компании по её объектам и «Задачи»
          (внутренняя работа). Здесь третье: вопрос поставщику программы. */}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('tickets')} className={btnCls(interactionSection === 'tickets')} title="Поддержка платформы: вопросы и ошибки по программе">
        <LifeBuoy className="h-4 w-4" />
        <span className="hidden lg:inline">Поддержка</span>
        <Badge count={unreadCounts.tickets} />
      </Button>
      {/* «Инфо» — четвёртая кнопка, на телефоне уже теснит имя экрана. Справка
          доступна оттуда же, куда ведёт плитка «Инфо» на столе. */}
      <Button variant="outline" size="sm" onClick={() => toggleInteraction('help')} className={`hidden sm:inline-flex ${btnCls(interactionSection === 'help')}`} title="Инфо (Ctrl+K)">
        <HelpCircle className="h-4 w-4" />
        <span className="hidden lg:inline">Инфо</span>
      </Button>
    </div>
  )
}
