/**
 * Лаунчер приложений экосистемы (компонент Ядра). Показывает приложения, доступные
 * через единый вход (SSO), и по клику открывает их без повторного логина. Пока SSO
 * не настроен (нет ключа подписи) или приложений нет — лаунчер скрыт.
 */
import { useState } from 'react'
import { LayoutGrid, ExternalLink, Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
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
import { listSsoApps, authorizeApp } from '@/services/ssoService'
import { useCompany } from '@/contexts/CompanyContext'

export function AppLauncher() {
  const { companyId } = useCompany()
  const [busy, setBusy] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['sso-apps'],
    queryFn: listSsoApps,
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const data = q.data

  // Лаунчер скрыт, пока экосистемный SSO не настроен или приложений нет.
  if (!isApiEnabled() || !data?.enabled || data.apps.length === 0) return null

  async function open(code: string) {
    if (busy) return
    setBusy(code)
    try {
      const url = await authorizeApp(code, companyId)
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Единый вход не настроен' : 'Не удалось открыть приложение')
    } finally {
      setBusy(null)
    }
  }

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
        <DropdownMenuLabel className="text-xs text-muted-foreground">Экосистема ElsyPlus</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {data.apps.map((a) => (
          <DropdownMenuItem key={a.code} onClick={() => open(a.code)} className="gap-2.5 cursor-pointer">
            {busy === a.code
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <ExternalLink className="h-4 w-4 text-muted-foreground" />}
            <span className="flex-1 truncate">{a.name}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
