import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, User, Menu, Settings, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { CompanySelector } from '@/components/company/CompanySelector'
import { SidebarTrigger } from '@/components/ui/sidebar'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile = false }: HeaderProps) {
  const navigate = useNavigate()
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
      className={`${isMobile ? 'relative' : 'fixed top-0'} left-0 right-0 z-50 mobile-safe-top`}
      style={{
        minHeight: 'var(--header-height)',
        background: 'hsl(215 28% 8%)',
        borderBottom: '1px solid hsl(217 32% 20% / 0.5)',
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.35)',
      }}
    >
      <div className="flex items-center" style={{ minHeight: 'var(--header-height)' }}>
        {/* Logo area — ширина = sidebar */}
        <div
          className="hidden md:flex items-center gap-4 shrink-0 px-4"
          style={{ width: 'var(--sidebar-width, 16rem)' }}
        >
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, hsl(217 91% 55%), hsl(217 91% 45%))',
              boxShadow: '0 4px 16px rgba(0, 0, 0, 0.35)',
            }}
          >
            <span className="text-white font-bold text-base">CL</span>
          </div>
          <div>
            <h1 className="font-semibold text-white text-lg tracking-tight">ClearLedger</h1>
            <p className="text-xs" style={{ color: 'hsl(215 15% 50%)' }}>v0.1.0</p>
          </div>
        </div>

        {/* Mobile: burger */}
        <div className="flex items-center gap-2 md:hidden px-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={onMobileMenuToggle}
            aria-label="Открыть меню"
            className="shrink-0 h-11 w-11 rounded-lg transition-all duration-200"
            style={{
              background: 'hsl(217 32% 15% / 0.8)',
              borderColor: 'hsl(217 32% 25% / 0.5)',
            }}
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
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4" style={{ color: 'hsl(215 15% 50%)' }} />
              <Input
                type="text"
                placeholder="Поиск документов, записей, коннекторов..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-10 w-full pl-10 pr-4 rounded-lg text-sm border-0 placeholder:text-muted-foreground"
                style={{
                  background: 'hsl(217 32% 14% / 0.8)',
                  color: 'hsl(0 0% 90%)',
                }}
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

          {/* User Profile */}
          <div className="shrink-0 ml-auto">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="flex items-center gap-3 px-2 md:px-3 transition-all duration-200 h-10 md:h-11 rounded-lg"
                style={{
                  borderColor: 'hsl(217 32% 22% / 0.3)',
                }}
              >
                <div
                  className="w-8 h-8 md:w-9 md:h-9 rounded-full flex items-center justify-center"
                  style={{
                    background: 'hsl(217 91% 55%)',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.25)',
                    outline: '1px solid hsl(217 32% 25% / 0.5)',
                  }}
                >
                  <User className="w-4 h-4 md:w-5 md:h-5 text-white" />
                </div>
                <div className="hidden lg:flex flex-col items-start">
                  <span className="font-medium text-sm text-white leading-none">Администратор</span>
                  <span className="text-xs mt-1" style={{ color: 'hsl(215 15% 50%)' }}>admin</span>
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-72 p-0"
              style={{
                background: 'hsl(215 28% 8%)',
                borderColor: 'hsl(217 32% 20% / 0.5)',
                boxShadow: '0 8px 32px rgba(0, 0, 0, 0.45)',
              }}
            >
              {/* Header — user info */}
              <div
                className="p-4"
                style={{
                  borderBottom: '1px solid hsl(217 32% 20% / 0.5)',
                  background: 'linear-gradient(135deg, hsl(217 32% 13% / 0.5), hsl(215 28% 8% / 0.5))',
                }}
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center"
                    style={{
                      background: 'hsl(217 91% 55%)',
                      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.25)',
                      outline: '2px solid hsl(217 91% 60% / 0.2)',
                    }}
                  >
                    <User className="w-6 h-6 text-white" />
                  </div>
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="font-semibold text-sm text-white truncate">Администратор</span>
                    <span className="text-xs truncate" style={{ color: 'hsl(215 15% 50%)' }}>
                      admin@clearledger.ru
                    </span>
                    <span className="text-xs font-medium mt-0.5" style={{ color: 'hsl(217 91% 70%)' }}>
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
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-200"
                    style={{ background: 'hsl(217 32% 15% / 0.5)' }}
                  >
                    <Settings className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors duration-200" />
                  </div>
                  <div className="flex flex-col flex-1">
                    <span className="text-sm font-medium">Настройки</span>
                    <span className="text-xs text-muted-foreground">Параметры платформы</span>
                  </div>
                </DropdownMenuItem>
              </div>

              {/* Footer — logout */}
              <div className="p-2" style={{ borderTop: '1px solid hsl(217 32% 20% / 0.5)' }}>
                <DropdownMenuItem
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-200 text-red-400 hover:text-red-300 group"
                >
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-200"
                    style={{ background: 'hsl(0 84% 60% / 0.1)' }}
                  >
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
