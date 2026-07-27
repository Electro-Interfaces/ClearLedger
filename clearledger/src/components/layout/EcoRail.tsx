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
import { listSsoApps, launcherApps } from '@/services/ssoService'
import { useOpenApp } from '@/hooks/useOpenApp'
import { useCompany } from '@/contexts/CompanyContext'
import { ECOSYSTEM_TITLE } from '@/config/brand'

const btnCls = (active = false) =>
  cn('relative flex w-11 flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] transition-colors',
    active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')

export function EcoRail({ standalone = false }: { standalone?: boolean }) {
  const navigate = useNavigate()
  const { canApp, companyId } = useCompany()
  const { openApp, busy } = useOpenApp()

  // Каталог спрашиваем всегда: в контейнере API живёт на том же origin, и база
  // VITE_API_URL там пуста — гейтить рельс по isApiEnabled() значило бы прятать
  // навигацию именно в боевом режиме. Нет приложений (или ошибка) — просто нет кнопки.
  const q = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    staleTime: 5 * 60_000,
    retry: false,
  })
  // Чат/Заявки/Инфо живут кнопками выше по рельсу — в списке продуктов они лишние.
  const apps = q.data?.enabled ? launcherApps(q.data.apps) : []

  return (
    <div className={cn('mt-auto flex w-full flex-col items-center gap-1 pt-2',
      // Внутри рейла взаимодействия зона отделена чертой; отдельным рельсом (Центр
      // управления) черта не нужна — над ней ничего нет.
      !standalone && 'border-t border-border/50')}>
      {/* «Стол» переехал в шапку, к «Приложениям» (`DeskButton`): возврат на стол нужен
          так же часто, как переключение продукта, и рядом с ним он заметнее, чем в
          нижней зоне рельса. Здесь остаются переходы между продуктами. */}
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
                onClick={() => openApp(a)}
                className="cursor-pointer gap-2.5"
              >
                {busy === a.code
                  ? <Loader2 className="size-4 animate-spin" />
                  : a.mode === 'link'
                    ? <ExternalLink className="size-4 text-muted-foreground" />
                    : a.mode === 'internal'
                      // Внутренний продукт открывается здесь же — ни ключа, ни внешней ссылки.
                      ? <LayoutGrid className="size-4 text-primary/70" />
                      : <KeyRound className="size-4 text-primary/70" />}
                <span className="flex-1 truncate">{a.name}</span>
                {/* Мост — приложение спросит свой вход: обещать единый было бы неправдой. */}
                {a.mode === 'link' && <span className="shrink-0 text-[10px] text-muted-foreground">вход отдельный</span>}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* «Управление» — такое же приложение пространства: показываем по праву роли,
          а не по признаку «админ компании». */}
      {canApp('admin') && (
        <button onClick={() => navigate('/admin')} title="Управление пространством" className={btnCls()}>
          <ShieldCheck className="size-4" />
          <span>Управл.</span>
        </button>
      )}
    </div>
  )
}
