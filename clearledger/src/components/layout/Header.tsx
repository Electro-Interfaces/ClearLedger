import { Menu, BookText, MessageCircle, LifeBuoy, HelpCircle, Video, Lightbulb } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Link } from 'react-router-dom'
import { useGuideMode } from '@/hooks/useGuideMode'
import { UiLevelHeaderButton } from '@/components/common/UiLevelToggle'
import { Button } from '@/components/ui/button'
import { createMeeting } from '@/services/conferenceService'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { APP_VERSION } from '@/config/version'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { useSupportContext } from '@/contexts/SupportContext'
import { CompanySelector } from '@/components/company/CompanySelector'
import { AppLauncher } from '@/components/layout/AppLauncher'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile }: HeaderProps) {
  const guide = useGuideMode()
  const { interactionSection, toggleInteraction, unreadCounts } = useSupportContext()
  // Универсальный логотип «учёт»: приложение не привязано к топливу/энергии.
  const BrandIcon = BookText

  const [confBusy, setConfBusy] = useState(false)
  async function startConference() {
    if (confBusy) return
    setConfBusy(true)
    try {
      const m = await createMeeting()
      window.open(m.moderator_url, '_blank', 'noopener,noreferrer')
      try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
      toast.success('Конференция создана — гостевая ссылка скопирована', { description: m.guest_url })
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Видеоконференции не настроены' : 'Не удалось создать конференцию')
    } finally {
      setConfBusy(false)
    }
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

          {/* Логотип ведёт на рабочий стол ЭКОСИСТЕМЫ (`/`) — наружу, к списку
              приложений. Рабочий стол самого Ledger — `/workspace`. */}
          <Link to="/" title="К рабочему столу экосистемы" className="flex items-center gap-3 shrink-0">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 shadow-lg">
              <BrandIcon className="h-5 w-5 text-white" />
            </div>
            <div className="hidden sm:flex flex-col leading-none">
              <h1 className="font-semibold tracking-tight text-foreground text-lg">{ECOSYSTEM_BRAND} Учёт</h1>
              <p className="text-xs text-muted-foreground">v{APP_VERSION}</p>
            </div>
          </Link>

        </div>

        {/* Центр: переключатель компании + кнопки взаимодействия.
            Фильтры (период/точки/регионы/типы) переехали в свёрнутый фильтр
            рабочей области — единый фильтр над разделами. */}
        <div className="flex flex-1 items-center justify-center min-w-0 gap-2 px-2">
          <CompanySelector />
          {/* Лаунчер приложений экосистемы (Ядро) — скрыт, если SSO не настроен */}
          <AppLauncher />

          <div className="hidden md:flex items-center gap-2 pl-1">
            <div className="w-px h-6 bg-border/50" />
            {/* Конференция */}
            <Button variant="outline" size="sm" onClick={startConference} disabled={confBusy} className={btnCls(false)} title="Видеоконференция">
              <Video className="h-4 w-4" />
              <span className="hidden lg:inline">Конференция</span>
            </Button>
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

        {/* Правый блок: чат (моб.) + переключатель темы + профиль */}
        <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
          {/* Мобильный вход в чат — на &lt;768px кнопки взаимодействия скрыты (md:flex) */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden relative h-10 w-10 rounded-xl text-muted-foreground hover:text-foreground"
            onClick={() => toggleInteraction('chat')}
            title="Чат"
          >
            <MessageCircle className="h-[18px] w-[18px]" />
            {unreadCounts.chat > 0 && (
              <span className="absolute -top-0.5 -right-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                {unreadCounts.chat}
              </span>
            )}
          </Button>
          {/* Режим работы: простой ⇄ расширенный. Стоит рядом с лампочкой —
              та объясняет, ГДЕ что находится, этот убирает лишнее с глаз. */}
          <UiLevelHeaderButton />
          {/* Обучающая подсветка зон интерфейса — «что здесь есть и за что отвечает». */}
          <Button
            variant="ghost"
            size="icon"
            aria-pressed={guide.on}
            className={`hidden h-10 w-10 rounded-xl sm:inline-flex ${guide.on ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'}`}
            onClick={guide.toggle}
            title={guide.on ? 'Скрыть структуру экрана' : 'Показать структуру экрана'}
          >
            <Lightbulb className="h-[18px] w-[18px]" />
          </Button>
          {/* Тема + меню пользователя — общий блок приложений контейнера. */}
          <HeaderUserMenu settingsPath="/settings" />
        </div>
      </div>
    </header>
  )
}
