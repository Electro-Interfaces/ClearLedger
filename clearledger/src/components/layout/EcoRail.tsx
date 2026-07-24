/**
 * EcoRail — экосистемная зона правого рельса (компонент Ядра).
 *
 * Одно и то же место во ВСЕХ приложениях контейнера: выход на рабочий стол,
 * переход в соседнее приложение и в Центр управления. Живёт в самом низу рельса,
 * отделённая чертой: прикладные кнопки (Чат/Заявки/Инфо) сверху остаются главными,
 * навигация по экосистеме не спорит с ними за внимание.
 *
 * Для приложений вне Ledger тот же рельс отдаётся Ядром как web-component
 * (`public/eco-rail.js`, подключается одной строкой) — реализация одна, вид общий.
 */
import { LayoutGrid, AppWindow, ShieldCheck, Loader2, ExternalLink, KeyRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
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
import { useCompany } from '@/contexts/CompanyContext'
import { ECOSYSTEM_TITLE } from '@/config/brand'

const btnCls = (active = false) =>
  cn('relative flex w-11 flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] transition-colors',
    active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')

export function EcoRail({ standalone = false }: { standalone?: boolean }) {
  const navigate = useNavigate()
  const { isCompanyAdmin } = useCompany()
  const { open, busy } = useOpenApp()

  const q = useQuery({
    queryKey: ['sso-apps'],
    queryFn: () => listSsoApps(),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const apps = q.data?.enabled ? q.data.apps : []

  return (
    <div className={cn('mt-auto flex w-full flex-col items-center gap-1 pt-2',
      // Внутри рейла взаимодействия зона отделена чертой; отдельным рельсом (Центр
      // управления) черта не нужна — над ней ничего нет.
      !standalone && 'border-t border-border/50')}>
      <button onClick={() => navigate('/')} title="Рабочий стол экосистемы" className={btnCls()}>
        <LayoutGrid className="size-4" />
        <span>Стол</span>
      </button>

      {apps.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button title="Приложения экосистемы" className={btnCls()}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <AppWindow className="size-4" />}
              <span>Прилож.</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="left" align="end" className="w-60 p-1">
            <DropdownMenuLabel className="text-xs text-muted-foreground">{ECOSYSTEM_TITLE}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {apps.map((a) => (
              <DropdownMenuItem
                key={a.code}
                onClick={(e) => open(a.code, wantsNewTab(e))}
                onAuxClick={(e) => { if (e.button === 1) open(a.code, true) }}
                className="cursor-pointer gap-2.5"
              >
                {busy === a.code
                  ? <Loader2 className="size-4 animate-spin" />
                  : a.mode === 'link'
                    ? <ExternalLink className="size-4 text-muted-foreground" />
                    : <KeyRound className="size-4 text-primary/70" />}
                <span className="flex-1 truncate">{a.name}</span>
                {/* Мост — приложение спросит свой вход: обещать единый было бы неправдой. */}
                {a.mode === 'link' && <span className="shrink-0 text-[10px] text-muted-foreground">вход отдельный</span>}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Центр управления — отдельное приложение уровня контейнера, только администраторам. */}
      {isCompanyAdmin && (
        <button onClick={() => navigate('/admin')} title="Центр управления" className={btnCls()}>
          <ShieldCheck className="size-4" />
          <span>Центр</span>
        </button>
      )}
    </div>
  )
}
