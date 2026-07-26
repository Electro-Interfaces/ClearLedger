import { Menu, BookText, MessageCircle, Lightbulb } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useGuideMode } from '@/hooks/useGuideMode'
import { UiLevelHeaderButton } from '@/components/common/UiLevelToggle'
import { Button } from '@/components/ui/button'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { HeaderInteractionButtons } from '@/components/layout/HeaderInteractionButtons'
import { APP_VERSION } from '@/config/version'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { useSupportContext } from '@/contexts/SupportContext'
import { useCompany } from '@/contexts/CompanyContext'
import { isCarvedProfile, productForPath } from '@/config/spaceProducts'
import { CompanySelector } from '@/components/company/CompanySelector'
import { AppLauncher } from '@/components/layout/AppLauncher'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile }: HeaderProps) {
  const guide = useGuideMode()
  const { toggleInteraction, unreadCounts } = useSupportContext()
  const { company } = useCompany()
  const { pathname } = useLocation()
  const product = isCarvedProfile(company.profileId) ? productForPath(pathname) : null
  // Универсальный логотип «учёт»: приложение не привязано к топливу/энергии.
  const BrandIcon = BookText

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
            {/* Шапка называет ТЕКУЩИЙ продукт: там, где Учёт разрезан на рабочие места
                («Финансы», «Данные»), надпись «Учёт» врала бы о том, где человек. */}
            <div className="hidden sm:flex flex-col leading-none">
              <h1 className="font-semibold tracking-tight text-foreground text-lg">
                {product ? product.label : `${ECOSYSTEM_BRAND} Учёт`}
              </h1>
              <p className="text-xs text-muted-foreground">
                {product ? ECOSYSTEM_BRAND : `v${APP_VERSION}`}
              </p>
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

          {/* Чат · Заявки · Инфо (+ Конференция) — общий блок продуктов контейнера. */}
          <HeaderInteractionButtons conference />
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
