import { useLocation, useNavigate } from 'react-router-dom'
import { Activity, CalendarDays, LayoutGrid, ListChecks, MessageCircle } from 'lucide-react'
import { useSupportContext } from '@/contexts/SupportContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { cn } from '@/lib/utils'

export function PulseMobileNav({ onMenu }: {
  /** Открыть меню пространства: каталог приложений, разделы и функции Ядра. */
  onMenu?: () => void
} = {}) {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const { openInteraction, closeInteraction, interactionSection } = useSupportContext()
  const trackOn = useDocsApp()
  const apps = pathname === '/pulse' && new URLSearchParams(search).get('view') === 'apps'
  // Человек уже в приложении «Трек» — второй «Трек» окном поверх ему не нужен.
  const inTrack = pathname === '/docs' || pathname.startsWith('/docs/')
  // Пять равных долей и подпись в одну строку по центру (замечание МАГа 07.09.2026:
  // «какая-то как-то всё сжато»). Раньше пункт растягивался по своей подписи, поэтому
  // «Приложения» отъедало место у соседей и всё равно упиралось в край экрана.
  // На телефоне подпись — «Модули»: «Приложения» не влезало в пятую долю даже так и
  // обрезалось многоточием (замечание МАГа 08.09.2026).
  const cls = (active: boolean) => cn(
    'flex min-h-14 min-w-0 flex-1 basis-0 flex-col items-center justify-center gap-1 px-0.5 py-1.5',
    'rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
    active ? 'text-primary font-medium' : 'text-muted-foreground hover:text-foreground')
  const label = 'w-full truncate text-center text-[11px] leading-none'
  return <nav aria-label="Мобильный пульт пространства" className="mobile-safe-bottom fixed inset-x-0 bottom-0 z-50 border-t bg-card md:hidden">
    <div className="flex items-stretch">
      {/* «Пульс» ещё и ЗАКРЫВАЕТ открытое окно связи (замечание МАГа 07.09.2026):
          чат и встречи лежат поверх пульта, и переход по ссылке под ними менял адрес,
          но человек продолжал видеть тот же чат — кнопка выглядела сломанной. */}
      <button type="button" className={cls(pathname === '/pulse' && !apps && !interactionSection)}
        onClick={() => { closeInteraction(); navigate('/pulse') }}><Activity className="size-5" /><span className={label}>Пульс</span></button>
      <button type="button" onClick={() => openInteraction('chat')} className={cls(interactionSection === 'chat')}><MessageCircle className="size-5" /><span className={label}>Чат</span></button>
      {/* Внутри самого «Трека» кнопка не открывает окно поверх того же самого
          (вопрос МАГа 08.09.2026 «то туда, то сюда»): если человек уже на экране
          приложения, она просто закрывает окно связи и оставляет его в работе. */}
      {trackOn && <button type="button"
        onClick={() => { if (inTrack) { closeInteraction(); navigate('/docs/work') } else openInteraction('tasks') }}
        className={cls(interactionSection === 'tasks' || (inTrack && !interactionSection))}><ListChecks className="size-5" /><span className={label}>Трек</span></button>}
      {trackOn && <button type="button" onClick={() => openInteraction('calendar')} className={cls(interactionSection === 'calendar')}><CalendarDays className="size-5" /><span className={label}>Календарь</span></button>}
      {/* «Приложения» открывают меню пространства — там каталог с избранным, разделы
        и функции Ядра (решение МАГа 06.09.2026). Прежний отдельный экран каталога
        и панель плашек поверх работы убраны: три двери в одно и то же. */}
    <button type="button" onClick={() => { closeInteraction(); onMenu?.() }} className={cls(apps)}><LayoutGrid className="size-5" /><span className={label}>Модули</span></button>
    </div>
  </nav>
}
