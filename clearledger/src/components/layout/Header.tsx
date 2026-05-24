import { User, Menu, Sun, Moon, Fuel } from 'lucide-react'
import { useNavigate, Link } from 'react-router-dom'
import { useTheme } from '@/hooks/useTheme'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { GlobalFilters } from './GlobalFilters'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile }: HeaderProps) {
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()

  return (
    <header className="h-[var(--header-height)] shrink-0 border-b border-border/50 bg-card backdrop-blur-xl">
      <div className="flex h-full items-center px-4 gap-3">
        {isMobile && (
          <Button variant="ghost" size="icon" className="shrink-0" onClick={onMobileMenuToggle}>
            <Menu className="h-5 w-5" />
          </Button>
        )}

        <Link to="/" className="flex items-center gap-2.5 shrink-0">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary/10 border border-primary/20">
            <Fuel className="h-4 w-4 text-primary" />
          </div>
          <div className="flex flex-col leading-none">
            <span className="font-bold text-sm tracking-tight">GIG Fuel Ledger</span>
            <span className="text-[10px] text-muted-foreground font-medium">ГазИнвестГрупп</span>
          </div>
        </Link>

        {/* Глобальные фильтры менеджера — компания, точки, типы документов */}
        <div className="flex-1 flex justify-center min-w-0 px-4">
          <GlobalFilters />
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <User className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => navigate('/settings')}>
              Настройки
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
