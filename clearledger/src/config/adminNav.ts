/**
 * Разделы приложения «Управление» — единый источник для левого меню, маршрутов
 * и заголовка рабочей области (как `config/navigation.ts` у Учёта).
 *
 * Два уровня пространства:
 *  - `eco`     — весь контейнер (несколько организаций, ядро, платформенные сервисы).
 *                Виден только суперадмину-владельцу контейнера.
 *  - `company` — пространство одной организации. Гейт — `canModule('admin', code)`:
 *                роль может дать часть администрирования (только объекты и справочники).
 *
 * В интерфейсе владелец пространства называется **организацией**, а слово «компания»
 * оставлено партнёрам-контрагентам. Коды и поля БД (`company`, `company_id`) не
 * переименованы намеренно: это ключи прав и внешних связей, а не текст на экране.
 *
 * Коды company-разделов совпадают с модулями продукта `admin` в реестре Ядра
 * (`eco_app_modules`) — менять их значит менять права.
 */
import type { ComponentType } from 'react'
import {
  LayoutDashboard, Map, Blocks, Users, History, Settings2,
  KeyRound, MapPin, Library, Building2, Mail, Handshake,
} from 'lucide-react'

export type AdminScope = 'eco' | 'company'

export interface AdminSection {
  /** Код раздела: хвост маршрута и ключ модуля в правах. */
  code: string
  label: string
  /** Подпись в шапке рабочей области — что здесь делают. */
  hint: string
  icon: ComponentType<{ className?: string }>
}

/** Уровень «Экосистема» — контейнер целиком. Только суперадмину. */
export const ecosystemSections: AdminSection[] = [
  // Было восемь пунктов, из них четыре повторяли разделы организации другими словами.
  // Убраны: «Оповещения» (два факта из того же запроса, что и обзор — стали его первым
  // блоком), «Каталог» (секция раздела «Приложения»), «Пользователи» (состав людей — в
  // «Сотрудниках» и «Компаниях», сводно — в «Карте»), «Аудит» (журнал сам переключает
  // охват «организация / весь контейнер»).
  { code: 'overview', label: 'Обзор', hint: 'Что требует внимания, люди, объекты, сервисы, активность', icon: LayoutDashboard },
  { code: 'companies', label: 'Организации', hint: 'Организации контейнера и подключение новых', icon: Building2 },
  { code: 'settings', label: 'Сервисы', hint: 'Единый вход, платформенные сервисы, каталог лаунчера', icon: Settings2 },
]

/** Уровень «Организация» — пространство заказчика. Гейт по модулям роли. */
export const companySections: AdminSection[] = [
  // Свои сотрудники и люди партнёров — разные разделы, а не один список с пометкой:
  // вопросы разные («кому что можно внутри организации» против «какая сторонняя
  // компания допущена и до чего»), и право на них выдаётся по отдельности.
  { code: 'members', label: 'Сотрудники', hint: 'Сотрудники организации — владельца пространства: роли и доступ', icon: Users },
  { code: 'partners', label: 'Компании', hint: 'Сторонние компании с доступом: их люди, роли и объекты', icon: Handshake },
  { code: 'roles', label: 'Роли и доступ', hint: 'Права на продукты пространства и их разделы', icon: KeyRound },
  { code: 'apps', label: 'Приложения', hint: 'Подключённые продукты и их модули; каталог платформы — владельцу контейнера', icon: Blocks },
  { code: 'objects', label: 'Объекты', hint: 'Объекты организации — общие для всех приложений', icon: MapPin },
  { code: 'refs', label: 'Справочники', hint: 'Контрагенты, договоры и оборудование пространства', icon: Library },
  { code: 'map', label: 'Карта', hint: 'Люди, доступы и активность организации', icon: Map },
  { code: 'profile', label: 'Реквизиты', hint: 'Наименование, ИНН, профиль организации', icon: Building2 },
  { code: 'invites', label: 'Приглашения', hint: 'Приглашения по email и ссылки регистрации', icon: Mail },
  { code: 'audit', label: 'Журнал', hint: 'События организации; владельцу контейнера — переключение на все', icon: History },
]

export const adminPath = (scope: AdminScope, code: string) => `/admin/${scope}/${code}`

export function findSection(scope: AdminScope, code: string | undefined): AdminSection | undefined {
  const list = scope === 'eco' ? ecosystemSections : companySections
  return list.find((s) => s.code === code)
}
