/**
 * Правый край шапки: тема + меню пользователя. Общий для приложений контейнера
 * (Учёт, Управление) — человек не должен искать выход и тему в разных местах,
 * переходя между продуктами пространства.
 *
 * `settingsPath` — куда ведёт пункт «Настройки»; продукт без своих настроек его не
 * показывает (у Управления параметры ядра живут отдельным разделом).
 */
import { Gauge, LogOut, Moon, Settings, Sparkles, Sun, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/hooks/useTheme'
import { useUiLevel } from '@/hooks/useUiLevel'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

export function HeaderUserMenu({ settingsPath }: { settingsPath?: string }) {
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const { isAdvanced, toggle: toggleLevel } = useUiLevel()
  const { company } = useCompany()
  const { user, logout } = useAuth()
  const userName = user?.name ?? 'Пользователь'

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <>
      {/* Ниже sm скрыта: то же переключение есть в меню профиля, а место в шапке
          нужнее названию компании — важнее видеть, в чьих данных работаешь. */}
      <Button
        variant="ghost"
        size="icon"
        className="hidden h-10 w-10 rounded-xl text-muted-foreground hover:text-foreground sm:inline-flex"
        onClick={toggle}
        title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
      >
        {theme === 'dark' ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="flex h-10 items-center gap-3 rounded-xl border-none px-1.5 hover:bg-accent md:px-2.5"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary">
              <User className="h-[18px] w-[18px] text-white" />
            </div>
            <div className="hidden flex-col items-start leading-none lg:flex">
              <span className="max-w-[140px] truncate text-sm font-medium text-foreground">{userName}</span>
              <span className="mt-1 max-w-[140px] truncate text-xs text-muted-foreground">{company.name}</span>
            </div>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56 p-1">
          <div className="border-b border-border/30 px-3 py-2.5">
            <div className="truncate text-sm font-semibold text-foreground">{userName}</div>
            <div className="truncate text-xs text-muted-foreground">{company.name}</div>
          </div>
          {settingsPath && (
            <DropdownMenuItem onClick={() => navigate(settingsPath)} className="gap-2.5 cursor-pointer">
              <Settings className="h-4 w-4 text-muted-foreground" />
              Настройки
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={toggle} className="gap-2.5 cursor-pointer">
            {theme === 'dark' ? <Sun className="h-4 w-4 text-muted-foreground" /> : <Moon className="h-4 w-4 text-muted-foreground" />}
            {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          </DropdownMenuItem>
          {/* Режим экрана — пунктом со словами. В шапке он стоял безымянной
              иконкой-спидометром: угадать по ней, что это «показать все функции»,
              не мог никто. На телефоне из шапки убран совсем. */}
          <DropdownMenuItem onClick={toggleLevel} className="gap-2.5 cursor-pointer">
            {isAdvanced ? <Gauge className="h-4 w-4 text-muted-foreground" /> : <Sparkles className="h-4 w-4 text-muted-foreground" />}
            {isAdvanced ? 'Простой режим' : 'Все функции'}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleLogout} className="gap-2.5 cursor-pointer text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400">
            <LogOut className="h-4 w-4" />
            Выйти
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}
