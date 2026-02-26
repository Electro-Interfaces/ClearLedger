import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, User, Menu, Settings, LogOut, Sun, Moon } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useTheme } from '@/hooks/useTheme'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { CompanySelector } from '@/components/company/CompanySelector'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile = false }: HeaderProps) {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const { theme, toggle: toggleTheme } = useTheme()
  const [searchQuery, setSearchQuery] = useState('')

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
    } else {
      navigate('/search')
    }
  }

  return (
    <header
      className={`${isMobile ? 'relative' : 'fixed top-0'} left-0 right-0 z-50 mobile-safe-top border-b bg-card`}
      style={{
        minHeight: 'var(--header-height)',
        boxShadow: 'var(--shadow-medium)',
      }}
    >
      <div className="flex items-center" style={{ minHeight: 'var(--header-height)' }}>
        {/* Logo area — ширина = sidebar */}
        <div
          className="hidden md:flex items-center gap-4 shrink-0 px-4"
          style={{ width: 'var(--sidebar-width, 16rem)' }}
        >
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center bg-primary"
            style={{ boxShadow: 'var(--shadow-soft)' }}
          >
            <span className="text-primary-foreground font-bold text-base">CL</span>
          </div>
          <div>
            <h1 className="font-semibold text-foreground text-lg tracking-tight">ClearLedger</h1>
            <p className="text-xs text-muted-foreground">v0.3.1</p>
          </div>
        </div>

        {/* Mobile: burger */}
        <div className="flex items-center gap-2 md:hidden px-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={onMobileMenuToggle}
            aria-label="Открыть меню"
            className="shrink-0 h-11 w-11 rounded-lg transition-all duration-200 bg-secondary"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </div>

        {/* Content area — выровнена с рабочей областью */}
        <div className="flex-1 flex items-center gap-3 px-4 md:px-6 lg:px-8 min-w-0">
          {/* Company Selector */}
          <div className="shrink-0">
            <CompanySelector />
          </div>

          {/* Search — растягивается на всю ширину */}
          <form onSubmit={handleSearch} className="hidden md:flex flex-1 min-w-0">
            <div className="relative w-full">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Поиск документов, записей, коннекторов..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-10 w-full pl-10 pr-4 rounded-lg text-sm border-0 bg-secondary placeholder:text-muted-foreground"
              />
            </div>
          </form>

          {/* Mobile search icon */}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/search')}
            className="md:hidden h-9 w-9 rounded-lg ml-auto"
          >
            <Search className="h-4 w-4" />
          </Button>

          {/* Theme toggle */}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="h-9 w-9 rounded-lg shrink-0"
            aria-label={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          {/* User Profile */}
          <div className="shrink-0 ml-auto">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="flex items-center gap-3 px-2 md:px-3 transition-all duration-200 h-10 md:h-11 rounded-lg"
              >
                <div
                  className="w-8 h-8 md:w-9 md:h-9 rounded-full flex items-center justify-center bg-primary"
                  style={{ boxShadow: 'var(--shadow-soft)' }}
                >
                  <User className="w-4 h-4 md:w-5 md:h-5 text-primary-foreground" />
                </div>
                <div className="hidden lg:flex flex-col items-start">
                  <span className="font-medium text-sm text-foreground leading-none">Администратор</span>
                  <span className="text-xs mt-1 text-muted-foreground">admin</span>
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-72 p-0"
              style={{ boxShadow: 'var(--shadow-large)' }}
            >
              {/* Header — user info */}
              <div className="p-4 border-b bg-muted/30">
                <div className="flex items-center gap-3">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center bg-primary"
                    style={{ boxShadow: 'var(--shadow-soft)' }}
                  >
                    <User className="w-6 h-6 text-primary-foreground" />
                  </div>
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="font-semibold text-sm truncate">Администратор</span>
                    <span className="text-xs text-muted-foreground truncate">
                      admin@clearledger.ru
                    </span>
                    <span className="text-xs font-medium mt-0.5 text-primary">
                      Администратор
                    </span>
                  </div>
                </div>
              </div>

              {/* Menu items */}
              <div className="p-2">
                <DropdownMenuItem
                  onClick={() => navigate('/settings')}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-200 group"
                >
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-secondary">
                    <Settings className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors duration-200" />
                  </div>
                  <div className="flex flex-col flex-1">
                    <span className="text-sm font-medium">Настройки</span>
                    <span className="text-xs text-muted-foreground">Параметры платформы</span>
                  </div>
                </DropdownMenuItem>
              </div>

              {/* Footer — logout */}
              <div className="p-2 border-t">
                <DropdownMenuItem
                  onClick={() => { logout(); navigate('/login') }}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-200 text-destructive group"
                >
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-destructive/10">
                    <LogOut className="h-4 w-4" />
                  </div>
                  <div className="flex flex-col flex-1">
                    <span className="text-sm font-medium">Выйти</span>
                    <span className="text-xs opacity-60">Завершить сеанс</span>
                  </div>
                </DropdownMenuItem>
              </div>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        </div>
      </div>
    </header>
  )
}
