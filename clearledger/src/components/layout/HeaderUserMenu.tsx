/**
 * Правый край шапки: тема + меню пользователя. Общий для приложений контейнера
 * (Учёт, Управление) — человек не должен искать выход и тему в разных местах,
 * переходя между продуктами пространства.
 *
 * `settingsPath` — куда ведёт пункт «Настройки»; продукт без своих настроек его не
 * показывает (у Управления параметры ядра живут отдельным разделом).
 */
import { Camera, CornerDownLeft, Gauge, Loader2, LogOut, Moon, Settings, Sparkles, Sun, Trash2, User } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import * as chat from '@/services/chatService'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/hooks/useTheme'
import { useUiLevel } from '@/hooks/useUiLevel'
import { useSendMode } from '@/hooks/useSendMode'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

export function HeaderUserMenu({ settingsPath }: { settingsPath?: string }) {
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const { isAdvanced, toggle: toggleLevel } = useUiLevel()
  const { byEnter, toggle: toggleSend, hint: sendHint } = useSendMode()
  const { company } = useCompany()
  const { user, logout, refreshMe } = useAuth()
  const userName = user?.name ?? 'Пользователь'
  const photoRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  function handleLogout() {
    logout()
    navigate('/login')
  }

  // Фото профиля живёт в учётной записи и появляется везде, где виден человек:
  // в чате, в составе группы, в ленте. Поэтому и меняется здесь — рядом с именем,
  // а не внутри одного из приложений пространства.
  async function savePhoto(file: File | null) {
    setBusy(true)
    try {
      let url = ''
      if (file) {
        if (!file.type.startsWith('image/')) throw new Error('Нужна картинка')
        url = (await chat.uploadAttachment(file, company.id)).fileUrl
      }
      await chat.updateMe({ avatarUrl: url })
      await refreshMe()
      toast.success(file ? 'Фото профиля обновлено' : 'Фото профиля убрано')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить фото')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <input ref={photoRef} type="file" accept="image/*" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) savePhoto(f) }} />
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
            <div className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-xl bg-primary">
              {user?.avatar_url
                ? <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
                : <User className="h-[18px] w-[18px] text-white" />}
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
          <DropdownMenuItem onClick={() => photoRef.current?.click()} disabled={busy}
            className="gap-2.5 cursor-pointer">
            {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  : <Camera className="h-4 w-4 text-muted-foreground" />}
            {user?.avatar_url ? 'Сменить фото' : 'Добавить фото'}
          </DropdownMenuItem>
          {user?.avatar_url && (
            <DropdownMenuItem onClick={() => savePhoto(null)} disabled={busy}
              className="gap-2.5 cursor-pointer">
              <Trash2 className="h-4 w-4 text-muted-foreground" />
              Убрать фото
            </DropdownMenuItem>
          )}
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
          {/* Чем отправляется сообщение — привычка, а не настройка одного экрана:
              выбор действует и в чате, и в обсуждении задачи. */}
          <DropdownMenuItem onClick={toggleSend} className="gap-2.5 cursor-pointer">
            <CornerDownLeft className="h-4 w-4 text-muted-foreground" />
            <span className="flex flex-col">
              <span>{byEnter ? 'Отправка по Enter' : 'Отправка по Ctrl+Enter'}</span>
              <span className="text-[11px] text-muted-foreground">{sendHint}</span>
            </span>
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
