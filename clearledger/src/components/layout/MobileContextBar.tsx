/**
 * Полоса контекста под шапкой — только на узких экранах.
 *
 * В одну строку телефона шапка не помещается: имя пространства, бургер, кнопки
 * связи, профиль и переключатель компании вместе выдавливали друг друга — на
 * скриншоте МАГа (15.08.2026) переключатель обрезался краем экрана, а бургер
 * наезжал на соседнюю иконку.
 *
 * Поэтому ВЫБОР переезжает строкой ниже, где помещается целиком: организация и юрлицо,
 * каждое появляется только когда есть из чего выбирать.
 *
 * Имени приложения здесь НЕТ. Оно стояло справа в этой же строке и дублировало шапку:
 * на широком экране выходили две подписи одним словом («Бухгалтерия» слева в шапке и она
 * же в полосе), а строка занимала место и ничего не сообщала. Полоса теперь и рисуется
 * только на телефоне (`sm:hidden`) — на десктопе переключатели стоят в шапке, и ей там
 * делать нечего.
 */
import { CompanySelector } from '@/components/company/CompanySelector'
import { OrganizationSelector } from './OrganizationSelector'
import { useCompany } from '@/contexts/CompanyContext'

export function MobileContextBar() {
  const { companies, organizations } = useCompany()

  const manyCompanies = companies.length > 1
  const manyOrgs = (organizations?.length ?? 0) > 1
  // 🔴 Полоса — ТОЛЬКО для телефона, и только ради выбора: в шапке узкого экрана
  // переключатели скрыты, а больше показывать здесь нечего. Имя приложения отсюда
  // убрано — оно и так стоит в шапке слева, и вторая подпись тем же словом занимала
  // строку, ничего не сообщая (замечание МАГа 15.08.2026).
  if (!manyCompanies && !manyOrgs) return null

  return (
    <div data-zone="Контекст работы"
      className="flex shrink-0 items-center gap-2 border-b border-border/50 bg-card/60
                 px-3 py-1.5 sm:hidden">
      {manyCompanies && <CompanySelector />}
      {manyOrgs && <OrganizationSelector />}
    </div>
  )
}
