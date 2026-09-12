/* eslint-disable react-refresh/only-export-components */
/**
 * Оболочка приложения «Конференции».
 *
 * Канон пространства: раздел живёт в левой рельсе, заголовок экрана равен имени
 * пункта — та же геометрия, что у «Трека» и «Пульса». Человек, пришедший
 * оттуда, не должен замечать смены правил.
 *
 * Разделы отвечают на разные вопросы и потому разведены: «Встречи» — с кем
 * говорить сейчас и когда назначено; «История» — что было и чем кончилось;
 * «Записи» — что можно пересмотреть; «Статистика» — сколько времени уходит и на
 * что. Одним списком с фильтрами это не сходится: в историю приходят искать, а
 * в конференции — попасть в один клик.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as conf from '@/services/confService'

export interface ConfView {
  key: string
  path: string
  label: string
  hint: string
}

export const CONF_VIEWS: ConfView[] = [
  { key: 'talks', path: '/conf', label: 'Идут и назначены', hint: 'конференции сейчас и впереди' },
  { key: 'history', path: '/conf/history', label: 'История', hint: 'какие конференции прошли: кто пришёл, сколько шла, о чём договорились' },
  { key: 'records', path: '/conf/records', label: 'Записи', hint: 'конференции, которые можно пересмотреть' },
  { key: 'stats', path: '/conf/stats', label: 'Статистика', hint: 'сколько времени уходит на конференции и с кем' },
]

export function ConfLayout() {
  const { companyId } = useCompany()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const узкий = useMaxWidth(768)
  const [свёрнута, setСвёрнута] = useState(() => {
    try { return localStorage.getItem('conf-rail') === 'closed' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem('conf-rail', свёрнута ? 'closed' : 'open') } catch { /* приватный режим */ }
  }, [свёрнута])

  // Счётчик идущих конференций держим в оболочке: он нужен и в рельсе, и в
  // выпадающем списке на телефоне, а два запроса на одно число — это две
  // разные правды на одном экране.
  const live = useQuery({
    queryKey: ['conf-live', companyId],
    queryFn: () => conf.listLive(companyId),
    refetchInterval: 20_000,
  })
  const зовут = useQuery({
    queryKey: ['conf-meetings', companyId, 'upcoming', ''],
    queryFn: () => conf.listMeetings(companyId, 'upcoming'),
  })
  // В счётчике — идущие плюс приглашения без ответа: и то, и другое требует
  // от человека действия сейчас. Число, которое ничего не требует, перестают
  // замечать через день.
  const идут = (live.data?.live.length ?? 0)
    + (зовут.data?.meetings.filter(в => в.my_response === 'pending' && !в.organizer_is_me).length ?? 0)

  const активный = [...CONF_VIEWS].reverse()
    .find(v => pathname === v.path || pathname.startsWith(`${v.path}/`)) ?? CONF_VIEWS[0]

  const подпись = (v: ConfView) => (v.key === 'talks' && идут ? `${v.label} · ${идут}` : v.label)

  if (узкий) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <nav aria-label="Разделы Конференций"
          className="shrink-0 border-b border-border bg-card p-2">
          <select aria-label="Раздел Конференций" value={активный.path}
            onChange={e => navigate(e.target.value)}
            className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-base">
            {CONF_VIEWS.map(v => (
              <option key={v.key} value={v.path}>{подпись(v)}</option>
            ))}
          </select>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto"
          style={{ paddingBottom: 'calc(var(--pwa-install-height, 0px) + 6rem + env(safe-area-inset-bottom))' }}>
          <Outlet />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0">
      {свёрнута ? (
        <nav aria-label="Разделы Конференций"
          className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
          <button type="button" onClick={() => setСвёрнута(false)}
            title="Развернуть меню раздела" aria-label="Развернуть меню раздела"
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </nav>
      ) : (
        <nav aria-label="Разделы Конференций"
          className="flex w-56 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3">
          <div className="flex items-center justify-end px-1 pb-1">
            <button type="button" onClick={() => setСвёрнута(true)}
              title="Свернуть меню" aria-label="Свернуть меню раздела"
              className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          {CONF_VIEWS.map(v => (
            <button key={v.key} type="button" onClick={() => navigate(v.path)}
              title={v.hint} aria-current={v.key === активный.key ? 'page' : undefined}
              className={cn('flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors',
                v.key === активный.key
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-foreground hover:bg-accent/50')}>
              <span className="min-w-0 flex-1 truncate">{v.label}</span>
              {v.key === 'talks' && идут > 0 && (
                <span className="rounded-full bg-success px-1.5 text-[10px] font-bold leading-4 text-white">
                  {идут}
                </span>
              )}
            </button>
          ))}
        </nav>
      )}
      <div className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}
