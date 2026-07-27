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
  LayoutDashboard, Map, Blocks, Users, History, Bell, Settings2,
  KeyRound, MapPin, Library, Building2, Mail,
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
  { code: 'overview', label: 'Обзор', hint: 'Состояние ядра, единый вход, платформенные сервисы', icon: LayoutDashboard },
  { code: 'companies', label: 'Организации', hint: 'Организации контейнера и подключение новых', icon: Building2 },
  { code: 'map', label: 'Карта', hint: 'Люди, доступы и активность всего контейнера', icon: Map },
  { code: 'catalog', label: 'Каталог', hint: 'Продукты экосистемы и их подключение организациям', icon: Blocks },
  { code: 'users', label: 'Пользователи', hint: 'Все учётные записи контейнера', icon: Users },
  { code: 'audit', label: 'Аудит', hint: 'События контейнера', icon: History },
  { code: 'alerts', label: 'Оповещения', hint: 'Что требует внимания владельца контейнера', icon: Bell },
  { code: 'settings', label: 'Настройки', hint: 'Параметры ядра и единого входа', icon: Settings2 },
]

/** Уровень «Организация» — пространство заказчика. Гейт по модулям роли. */
export const companySections: AdminSection[] = [
  { code: 'members', label: 'Сотрудники', hint: 'Кто в пространстве организации и с какой ролью', icon: Users },
  { code: 'roles', label: 'Роли и доступ', hint: 'Права на продукты пространства и их разделы', icon: KeyRound },
  { code: 'apps', label: 'Приложения', hint: 'Какие продукты подключены организации', icon: Blocks },
  { code: 'objects', label: 'Объекты', hint: 'Объекты организации — общие для всех приложений', icon: MapPin },
  { code: 'refs', label: 'Справочники', hint: 'Контрагенты, договоры и оборудование пространства', icon: Library },
  { code: 'map', label: 'Карта', hint: 'Люди, доступы и активность организации', icon: Map },
  { code: 'profile', label: 'Реквизиты', hint: 'Наименование, ИНН, профиль организации', icon: Building2 },
  { code: 'invites', label: 'Приглашения', hint: 'Приглашения по email и ссылки регистрации', icon: Mail },
  { code: 'audit', label: 'Журнал', hint: 'События организации', icon: History },
]

export const adminPath = (scope: AdminScope, code: string) => `/admin/${scope}/${code}`

export function findSection(scope: AdminScope, code: string | undefined): AdminSection | undefined {
  const list = scope === 'eco' ? ecosystemSections : companySections
  return list.find((s) => s.code === code)
}
