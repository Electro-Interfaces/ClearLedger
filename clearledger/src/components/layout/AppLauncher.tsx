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
import { listSsoApps, launcherApps } from '@/services/ssoService'
import { useOpenApp } from '@/hooks/useOpenApp'
import { useCompany } from '@/contexts/CompanyContext'
import { ECOSYSTEM_TITLE } from '@/config/brand'

export function AppLauncher() {
  const { openApp, busy } = useOpenApp()
  const { companyId } = useCompany()

  const q = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const data = q.data
  // Чат, Заявки и Конференция стоят отдельными кнопками в этой же шапке — в списке
  // они были бы тем же входом, названным дважды подряд.
  const apps = data ? launcherApps(data.apps) : []

  // Лаунчер скрыт, пока экосистемный SSO не настроен или показывать нечего.
  if (!isApiEnabled() || !data?.enabled || apps.length === 0) return null

  const cls =
    'relative h-11 px-3 gap-2 rounded-xl border font-medium transition-colors duration-200 '
    // Навигация ПРОСТРАНСТВА (стол, соседний продукт) намеренно тише прикладных
    // кнопок рядом: рамка и цвет текста, без синей заливки. Тот же вид у приложений
    // вне Ядра — web-component <eco-apps> (решение МАГа 27.07.2026).
    + 'border-border bg-transparent text-foreground/80 hover:bg-accent hover:text-foreground'

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
        {apps.map((a) => (
          <DropdownMenuItem
            key={a.code}
            onClick={() => openApp(a)}
            className="gap-2.5 cursor-pointer"
          >
            {busy === a.code
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : a.mode === 'link'
                ? <ExternalLink className="h-4 w-4 text-muted-foreground" />
                : a.mode === 'internal'
                  // Внутренний продукт открывается здесь же — ни ключа, ни внешней ссылки.
                  ? <LayoutGrid className="h-4 w-4 text-primary/70" />
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
