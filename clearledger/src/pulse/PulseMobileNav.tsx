import { Link, useLocation } from 'react-router-dom'
import { Activity, CalendarDays, LayoutGrid, ListChecks, MessageCircle } from 'lucide-react'
import { useSupportContext } from '@/contexts/SupportContext'
import { useDocsApp } from '@/hooks/useDocsApp'
import { cn } from '@/lib/utils'

export function PulseMobileNav() {
  const { pathname, search } = useLocation()
  const { openInteraction, interactionSection } = useSupportContext()
  const trackOn = useDocsApp()
  const apps = pathname === '/pulse' && new URLSearchParams(search).get('view') === 'apps'
  const cls = (active: boolean) => cn('flex min-h-14 min-w-12 flex-1 flex-col items-center justify-center gap-1 rounded-md px-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', active ? 'text-primary font-medium' : 'text-muted-foreground hover:text-foreground')
  return <nav aria-label="Мобильный пульт пространства" className="mobile-safe-bottom fixed inset-x-0 bottom-0 z-50 border-t bg-card md:hidden">
    <div className="flex">
      <Link to="/pulse" className={cls(pathname === '/pulse' && !apps && !interactionSection)}><Activity className="size-5" /><span>Пульс</span></Link>
      <button type="button" onClick={() => openInteraction('chat')} className={cls(interactionSection === 'chat')}><MessageCircle className="size-5" /><span>Чат</span></button>
      {trackOn && <button type="button" onClick={() => openInteraction('tasks')} className={cls(interactionSection === 'tasks')}><ListChecks className="size-5" /><span>Трек</span></button>}
      {trackOn && <button type="button" onClick={() => openInteraction('calendar')} className={cls(interactionSection === 'calendar')}><CalendarDays className="size-5" /><span>Встречи</span></button>}
      <Link to="/pulse?view=apps" className={cls(apps)}><LayoutGrid className="size-5" /><span>Приложения</span></Link>
    </div>
  </nav>
}
