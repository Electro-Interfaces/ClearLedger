import { Menu, Lightbulb } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useGuideMode } from '@/hooks/useGuideMode'
import { UiLevelHeaderButton } from '@/components/common/UiLevelToggle'
import { Button } from '@/components/ui/button'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { HeaderInteractionButtons } from '@/components/layout/HeaderInteractionButtons'
import { APP_VERSION } from '@/config/version'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { OrganizationSelector } from '@/components/layout/OrganizationSelector'
import { CompanySelector } from '@/components/company/CompanySelector'
import { useCompany } from '@/contexts/CompanyContext'
import { coreAppTitle, isCarvedProfile, productForPath, productLabel } from '@/config/spaceProducts'

interface HeaderProps {
  onMobileMenuToggle?: () => void
  isMobile?: boolean
}

export function Header({ onMobileMenuToggle, isMobile }: HeaderProps) {
  const guide = useGuideMode()
  const { company } = useCompany()
  const { pathname } = useLocation()
  const product = isCarvedProfile(company.profileId) ? productForPath(pathname) : null
  // Приложение Ядра («Чаты», «Управление») называет себя само: продукта у него нет, а
  // надпись «Учёт» в чужом приложении сбивает с толку.
  const coreTitle = product ? null : coreAppTitle(pathname)

  return (
    <header className="mobile-safe-top box-content h-[var(--header-height)] shrink-0
                       border-b border-border/50 bg-card/95 backdrop-blur-xl">
      <div className="flex h-full items-center justify-between gap-2 px-2 sm:gap-3 sm:px-4 md:px-6">
        {/* Левый блок: бургер (моб.) + лого + бренд + свёртка сайдбара */}
        <div className="flex min-w-0 items-center gap-3 md:gap-4">
          {isMobile && (
            <Button variant="ghost" size="icon"
              className="-ml-1 size-11 shrink-0 rounded-xl"
              aria-label="Меню разделов"
              onClick={onMobileMenuToggle}>
              <Menu className="size-6" />
            </Button>
          )}

          {/* Логотип ведёт на рабочий стол ЭКОСИСТЕМЫ (`/`) — наружу, к списку
              приложений. Рабочий стол самого Ledger — `/workspace`.
              На телефоне логотипа нет: он был третьим путём на стол (рядом стояли
              кнопка «Стол» и нижняя навигация), а место занимал в первом ряду. */}
          <Link to="/" title="К рабочему столу экосистемы" className="hidden items-center gap-3 shrink-0 lg:flex">
            {/* Знак пространства, а не иконка продукта. Раньше здесь стоял общий
                глиф книги на синем квадрате — одинаковый у всех компаний, хотя у
                каждой уже есть свой знак: сборка кладёт его в `favicon.svg` по
                бренду стека, и браузер показывает его во вкладке. Шапка и вкладка
                расходились, и заказчик прямо попросил свой знак в левом верхнем
                углу (Чурилов, 21.08.2026). Берём тот же файл — двух источников
                правды о знаке компании быть не должно. */}
            <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt=""
              className="h-11 w-11 shrink-0 rounded-xl shadow-lg" />
            {/* Шапка называет ТЕКУЩИЙ продукт: там, где Учёт разрезан на рабочие места
                («Финансы», «Данные»), надпись «Учёт» врала бы о том, где человек. */}
            <div className="flex flex-col leading-none">
              <div className="font-semibold tracking-tight text-foreground text-lg">
                {product ? productLabel(product, company.profileId)
                  : coreTitle ?? `${ECOSYSTEM_BRAND} Учёт`}
              </div>
              <p className="text-xs text-muted-foreground">
                {product || coreTitle ? ECOSYSTEM_BRAND : `v${APP_VERSION}`}
              </p>
            </div>
          </Link>


        </div>

        {/* Центр: переключатель компании + кнопки взаимодействия.
            Фильтры (период/точки/регионы/типы) переехали в свёрнутый фильтр
            рабочей области — единый фильтр над разделами. */}
        {/* «Стол» и «Приложения» из шапки убраны (решение МАГа 06.08.2026): они
            дублировали пункт «Приложения» в левом меню, который открывает плашки
            прямо в рабочей области. В шапке остаётся выбор организации.
            В пространстве работают ОРГАНИЗАЦИИ (терминология МАГа 15.08.2026) — их и
            выбирают здесь. Оба переключателя скрываются, когда выбирать не из чего. */}
        {/* Распорка: прижимает переключатель, связь и профиль к правому краю. */}
        <div className="flex-1" />

        {/* Правый блок: организация + связь с пространством + режим + профиль */}
        <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
          {/* 🔴 Переключатель организации — В ШАПКЕ, слева от «Конференции».
              Он уезжал отсюда дважды: сначала скрывался при единственной организации,
              потом переехал в полосу под шапкой. Оба раза человек искал его глазами на
              привычном месте и не находил. Место фиксировано (решение МАГа 15.08.2026):
              шапка, перед кнопками связи, во всех приложениях одинаково. */}
          <span className="hidden sm:inline-flex"><CompanySelector /></span>
          {/* Юрлицо ВНУТРИ организации (ООО и ИП одного владельца в одной базе 1С).
              Появляется, только когда их несколько: иначе рядом стояли два похожих
              переключателя с почти одинаковыми названиями. */}
          <span className="hidden sm:inline-flex"><OrganizationSelector /></span>
          {/* Чат · Задачи · Конференция (+ Инфо и поддержка на десктопе) — общий блок продуктов
              контейнера. Стоит справа и на телефоне: это то, ради чего берут трубку. */}
          <HeaderInteractionButtons conference />
          {/* Режим работы: простой ⇄ расширенный. Стоит рядом с лампочкой —
              та объясняет, ГДЕ что находится, этот убирает лишнее с глаз.
              На телефоне иконки нет: угадать в безымянном спидометре «показать
              все функции» невозможно, и он переехал пунктом в меню профиля. */}
          <span className="hidden sm:inline-flex"><UiLevelHeaderButton /></span>
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
