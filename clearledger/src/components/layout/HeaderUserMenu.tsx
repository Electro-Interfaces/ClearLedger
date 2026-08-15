/**
 * Профиль в правом краю шапки — единая точка «всё про меня» во всём пространстве.
 *
 * Один компонент на приложения контейнера И на рабочий стол: раньше у стола была
 * своя шапка с голой кнопкой «Выйти», и человек, привыкший открывать профиль
 * иконкой, на столе её не находил (замечание МАГа 15.08.2026).
 *
 * Подача — как в ElsyPlus Monitor: аватар кнопкой, в меню сначала кто ты
 * (имя, почта, роль), затем действия с подписью, что каждое делает, и выход
 * отдельным блоком внизу. Подпись у пункта не украшение: «Уведомления» и
 * «Настройки» без неё одинаково непонятны с первого раза.
 *
 * `settingsPath` — куда ведёт «Настройки»; продукт без своих настроек его не
 * показывает (у Управления параметры ядра живут отдельным разделом).
 */
import { useState } from 'react'
import { Bell, Bot, LogOut, Moon, RefreshCw, Sun, User, Video } from 'lucide-react'
import { toast } from 'sonner'
import { startMeeting } from '@/services/conferenceService'
import { useSupportContext } from '@/contexts/SupportContext'
import { APP_BUILD, APP_VERSION, applyUpdate } from '@/lib/appUpdate'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/hooks/useTheme'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

/** Пункт меню: действие, а под ним — что оно делает. */
function MenuRow({ icon: Icon, title, note, danger, onSelect, disabled }: {
  icon: typeof User
  title: string
  note: string
  danger?: boolean
  disabled?: boolean
  onSelect: (e: Event | React.MouseEvent) => void
}) {
  return (
    <DropdownMenuItem
      disabled={disabled}
      onClick={onSelect}
      className={`group cursor-pointer gap-3 rounded-xl px-3 py-2.5 ${
        danger ? 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400' : ''
      }`}
    >
      <span className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${
        danger ? 'bg-red-500/10' : 'bg-muted'
      }`}>
        <Icon className={`size-4 ${danger ? '' : 'text-muted-foreground'}`} />
      </span>
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="text-sm font-medium">{title}</span>
        <span className={`truncate text-xs ${danger ? 'opacity-80' : 'text-muted-foreground'}`}>
          {note}
        </span>
      </span>
    </DropdownMenuItem>
  )
}

export function HeaderUserMenu({ settingsPath }: { settingsPath?: string }) {
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()
  const { canApp } = useCompany()
  const { user, logout } = useAuth()
  const { toggleInteraction } = useSupportContext()
  const [confBusy, setConfBusy] = useState(false)

  const userName = user?.name ?? 'Пользователь'
  // 🔴 Профиль НЕ называет организацию.
  //
  // Здесь стояло имя активной организации, и выходило «Администратор · ПРОМИЗОЛ СПБ» —
  // будто человек принадлежит одной организации. Он работает со многими сразу, а какая
  // выбрана сейчас — говорит переключатель в шапке. Профиль отвечает на другой вопрос:
  // кто я и что могу.
  const roleLabel = user?.is_superadmin ? 'Суперадминистратор' : 'Участник пространства'

  // Та же механика, что у кнопки в шапке: создаём встречу и кладём гостевую
  // ссылку в буфер — приглашать можно сразу, не заходя в приложение.
  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await startMeeting()
      try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
      toast.success('Конференция создана — ссылка скопирована', { description: m.guest_url })
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg)
        ? 'Видеоконференции не настроены' : 'Не удалось создать конференцию')
    } finally {
      setConfBusy(false)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {/* Аватар квадратом в цвете пространства и с обводкой: на тёмном фоне
            шапки безрамочная иконка сливалась с соседними кнопками связи. */}
        <Button
          variant="ghost"
          aria-label="Профиль и настройки"
          className="flex h-11 items-center gap-3 rounded-xl px-1 hover:bg-transparent md:px-1.5"
        >
          <span className="flex size-10 items-center justify-center overflow-hidden rounded-xl
                           bg-primary ring-2 ring-primary/40">
            {user?.avatar_url
              ? <img src={user.avatar_url} alt="" className="size-full object-cover" />
              : <User className="size-5 text-white" />}
          </span>
          <span className="hidden flex-col items-start leading-none xl:flex">
            <span className="max-w-[140px] truncate text-sm font-medium text-foreground">
              {userName}
            </span>
            <span className="mt-1 max-w-[140px] truncate text-xs text-muted-foreground">
              {roleLabel}
            </span>
          </span>
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-72 p-0">
        {/* Кто вошёл: имя, почта, роль. Первый вопрос к профилю — «я это я?», и
            особенно на общем компьютере в офисе. */}
        <div className="flex items-center gap-3 border-b border-border/40 p-4">
          <span className="flex size-12 shrink-0 items-center justify-center overflow-hidden
                           rounded-xl bg-primary">
            {user?.avatar_url
              ? <img src={user.avatar_url} alt="" className="size-full object-cover" />
              : <User className="size-6 text-white" />}
          </span>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-semibold text-foreground">{userName}</span>
            <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
            <span className="mt-0.5 truncate text-xs font-medium text-primary">{roleLabel}</span>
          </div>
        </div>

        <div className="p-2">
          {settingsPath && (
            <MenuRow icon={User} title="Профиль" note="Личные данные и пароль"
              onSelect={() => navigate(settingsPath)} />
          )}
          <MenuRow
            icon={theme === 'dark' ? Sun : Moon}
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
            note="Переключить оформление"
            onSelect={(e) => { (e as React.MouseEvent).preventDefault?.(); toggle() }} />
          {settingsPath && (
            <MenuRow icon={Bell} title="Уведомления" note="Что и куда присылать"
              onSelect={() => navigate(`${settingsPath}?tab=notifications`)} />
          )}
          {/* Конференция и «Аудитор» ушли сюда из мобильной шапки: четыре кнопки
              подряд выдавливали профиль за край экрана. На десктопе они остаются
              кнопками — там место есть. */}
          {canApp('conf') && (
            <MenuRow icon={Video} title="Конференция" note="Создать встречу и скопировать ссылку"
              disabled={confBusy} onSelect={() => void startConference()} />
          )}
          {canApp('auditor') && (
            <MenuRow icon={Bot} title="Аудитор" note="Спросить про этот экран"
              onSelect={() => toggleInteraction('auditor')} />
          )}
          {/* Версия здесь, а не мелкой строкой в подвале: это первое, что
              спрашивают, когда «у меня выглядит иначе». Рядом — способ обновиться. */}
          <MenuRow icon={RefreshCw} title="Проверить обновления"
            note={`Версия ${APP_VERSION} · сборка ${APP_BUILD}`}
            onSelect={() => void applyUpdate()} />
        </div>

        <div className="border-t border-border/40 p-2">
          <MenuRow icon={LogOut} title="Выйти" note="Завершить сеанс" danger
            onSelect={handleLogout} />
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
