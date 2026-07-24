/**
 * Лаунчер приложений экосистемы (компонент Ядра). Показывает приложения экосистемы:
 * с единым входом (SSO — открываются без повторного логина) и мосты (`mode=link`,
 * Фаза 0: Plane/Jitsi на общих доменах — открываются по ссылке, вход свой).
 * Мосты видны и без ключа SSO; когда показывать нечего — лаунчер скрыт.
 */
import { LayoutGrid, ExternalLink, KeyRound, Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps } from '@/services/ssoService'
import { useOpenApp, wantsNewTab } from '@/hooks/useOpenApp'
import { ECOSYSTEM_TITLE } from '@/config/brand'

export function AppLauncher() {
  const { open, busy } = useOpenApp()

  const q = useQuery({
    queryKey: ['sso-apps'],
    queryFn: () => listSsoApps(),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const data = q.data

  // Лаунчер скрыт, пока экосистемный SSO не настроен или приложений нет.
  if (!isApiEnabled() || !data?.enabled || data.apps.length === 0) return null

  const cls =
    'relative h-11 px-3 gap-2 rounded-xl transition-all duration-200 font-medium border ' +
    'bg-primary/10 dark:bg-primary/20 hover:bg-primary text-primary dark:text-primary/80 ' +
    'hover:text-white border-primary/30 dark:border-primary/50 hover:border-primary'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className={cls} title="Приложения экосистемы">
          <LayoutGrid className="h-4 w-4" />
          <span className="hidden lg:inline">Приложения</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60 p-1">
        <DropdownMenuLabel className="text-xs text-muted-foreground">{ECOSYSTEM_TITLE}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {data.apps.map((a) => (
          <DropdownMenuItem
            key={a.code}
            onClick={(e) => open(a.code, wantsNewTab(e))}
            onAuxClick={(e) => { if (e.button === 1) open(a.code, true) }}
            className="gap-2.5 cursor-pointer"
          >
            {busy === a.code
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : a.mode === 'link'
                ? <ExternalLink className="h-4 w-4 text-muted-foreground" />
                : <KeyRound className="h-4 w-4 text-primary/70" />}
            <span className="flex-1 truncate">{a.name}</span>
            {/* Мост — приложение спросит свой вход: обещать единый было бы неправдой. */}
            {a.mode === 'link' && (
              <span className="text-[10px] text-muted-foreground shrink-0">вход отдельный</span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
