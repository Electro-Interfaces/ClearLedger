import { User, Menu, Sun, Moon, BookText, Settings, LogOut, MessageCircle, LifeBuoy, HelpCircle } from 'lucide-react'
import { useNavigate, Link } from 'react-router-dom'
import { useTheme } from '@/hooks/useTheme'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { APP_VERSION } from '@/config/version'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { useSupportContext } from '@/contexts/SupportContext'
import { GlobalFilters } from './GlobalFilters'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile }: HeaderProps) {
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const { company } = useCompany()
  const { user, logout } = useAuth()
  const { interactionSection, toggleInteraction, unreadCounts } = useSupportContext()
  const userName = user?.name ?? 'Пользователь'
  // Универсальный логотип «учёт»: приложение не привязано к топливу/энергии.
  const BrandIcon = BookText

  function handleLogout() {
    logout()
    navigate('/login')
  }

  // Пилюля-кнопка взаимодействия в стиле TradeFrame: синий акцент, активное состояние.
  const btnCls = (active: boolean) =>
    `relative h-11 px-3 gap-2 rounded-xl transition-all duration-200 font-medium border ${
      active
        ? 'bg-primary text-white border-primary'
        : 'bg-primary/10 dark:bg-primary/20 hover:bg-primary text-primary dark:text-primary/80 hover:text-white border-primary/30 dark:border-primary/50 hover:border-primary'
    }`

  return (
    <header className="h-[var(--header-height)] shrink-0 border-b border-border/50 bg-card/95 backdrop-blur-xl">
      <div className="flex h-full items-center justify-between gap-3 px-4 md:px-6">
        {/* Левый блок: бургер (моб.) + лого + бренд + свёртка сайдбара */}
        <div className="flex items-center gap-3 md:gap-4 shrink-0">
          {isMobile && (
            <Button variant="ghost" size="icon" className="shrink-0" onClick={onMobileMenuToggle}>
              <Menu className="h-5 w-5" />
            </Button>
          )}

          <Link to="/" className="flex items-center gap-3 shrink-0">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 shadow-lg">
              <BrandIcon className="h-5 w-5 text-white" />
            </div>
            <div className="hidden sm:flex flex-col leading-none">
              <h1 className="font-semibold tracking-tight text-foreground text-lg">Ledger</h1>
              <p className="text-xs text-muted-foreground">v{APP_VERSION}</p>
            </div>
          </Link>

        </div>

        {/* Центр: глобальные фильтры-пилюли + кнопки взаимодействия */}
        <div className="flex flex-1 items-center justify-center min-w-0 gap-2 px-2">
          <GlobalFilters />

          <div className="hidden md:flex items-center gap-2 pl-1">
            <div className="w-px h-6 bg-border/50" />
            {/* Чат */}
            <Button variant="outline" size="sm" onClick={() => toggleInteraction('chat')} className={btnCls(interactionSection === 'chat')} title="Чат с поддержкой">
              <MessageCircle className="h-4 w-4" />
              <span className="hidden lg:inline">Чат</span>
              {unreadCounts.chat > 0 && (
                <span className="absolute -top-1.5 -right-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                  {unreadCounts.chat}
                </span>
              )}
            </Button>
            {/* Заявки */}
            <Button variant="outline" size="sm" onClick={() => toggleInteraction('tickets')} className={btnCls(interactionSection === 'tickets')} title="Заявки в поддержку">
              <LifeBuoy className="h-4 w-4" />
              <span className="hidden lg:inline">Заявки</span>
              {unreadCounts.tickets > 0 && (
                <span className="absolute -top-1.5 -right-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                  {unreadCounts.tickets}
                </span>
              )}
            </Button>
            {/* Инфо */}
            <Button variant="outline" size="sm" onClick={() => toggleInteraction('help')} className={btnCls(interactionSection === 'help')} title="Инфо (Ctrl+K)">
              <HelpCircle className="h-4 w-4" />
              <span className="hidden lg:inline">Инфо</span>
            </Button>
          </div>
        </div>

        {/* Правый блок: переключатель темы + профиль */}
        <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-10 w-10 rounded-xl text-muted-foreground hover:text-foreground"
            onClick={toggle}
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          >
            {theme === 'dark' ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="flex h-10 items-center gap-3 rounded-xl border-none px-1.5 md:px-2.5 hover:bg-accent"
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary">
                  <User className="h-[18px] w-[18px] text-white" />
                </div>
                <div className="hidden lg:flex flex-col items-start leading-none">
                  <span className="text-sm font-medium text-foreground truncate max-w-[140px]">{userName}</span>
                  <span className="mt-1 text-xs text-muted-foreground truncate max-w-[140px]">{company.name}</span>
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 p-1">
              <div className="border-b border-border/30 px-3 py-2.5">
                <div className="text-sm font-semibold text-foreground truncate">{userName}</div>
                <div className="text-xs text-muted-foreground truncate">{company.name}</div>
              </div>
              <DropdownMenuItem onClick={() => navigate('/settings')} className="gap-2.5 cursor-pointer">
                <Settings className="h-4 w-4 text-muted-foreground" />
                Настройки
              </DropdownMenuItem>
              <DropdownMenuItem onClick={toggle} className="gap-2.5 cursor-pointer">
                {theme === 'dark' ? <Sun className="h-4 w-4 text-muted-foreground" /> : <Moon className="h-4 w-4 text-muted-foreground" />}
                {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleLogout} className="gap-2.5 cursor-pointer text-red-600 dark:text-red-400 focus:text-red-600 dark:focus:text-red-400">
                <LogOut className="h-4 w-4" />
                Выйти
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
