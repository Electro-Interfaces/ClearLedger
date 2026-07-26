/**
 * Разделы приложения «Управление» — единый источник для левого меню, маршрутов
 * и заголовка рабочей области (как `config/navigation.ts` у Учёта).
 *
 * Два уровня пространства:
 *  - `eco`     — весь контейнер (несколько компаний, ядро, платформенные сервисы).
 *                Виден только суперадмину-владельцу контейнера.
 *  - `company` — пространство одной компании. Гейт — `canModule('admin', code)`:
 *                роль может дать часть администрирования (только объекты и справочники).
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
  { code: 'companies', label: 'Компании', hint: 'Пространства контейнера и подключение новых', icon: Building2 },
  { code: 'map', label: 'Карта', hint: 'Люди, доступы и активность всего контейнера', icon: Map },
  { code: 'catalog', label: 'Каталог', hint: 'Продукты экосистемы и их подключение компаниям', icon: Blocks },
  { code: 'users', label: 'Пользователи', hint: 'Все учётные записи контейнера', icon: Users },
  { code: 'audit', label: 'Аудит', hint: 'События контейнера', icon: History },
  { code: 'alerts', label: 'Оповещения', hint: 'Что требует внимания владельца контейнера', icon: Bell },
  { code: 'settings', label: 'Настройки', hint: 'Параметры ядра и единого входа', icon: Settings2 },
]

/** Уровень «Компания» — пространство заказчика. Гейт по модулям роли. */
export const companySections: AdminSection[] = [
  { code: 'members', label: 'Сотрудники', hint: 'Кто в пространстве компании и с какой ролью', icon: Users },
  { code: 'roles', label: 'Роли и доступ', hint: 'Права на продукты пространства и их разделы', icon: KeyRound },
  { code: 'apps', label: 'Приложения', hint: 'Какие продукты подключены компании', icon: Blocks },
  { code: 'objects', label: 'Объекты', hint: 'Объекты компании — общие для всех приложений', icon: MapPin },
  { code: 'refs', label: 'Справочники', hint: 'Организации и оборудование пространства', icon: Library },
  { code: 'map', label: 'Карта', hint: 'Люди, доступы и активность компании', icon: Map },
  { code: 'profile', label: 'Реквизиты', hint: 'Наименование, ИНН, профиль компании', icon: Building2 },
  { code: 'invites', label: 'Приглашения', hint: 'Приглашения по email и ссылки регистрации', icon: Mail },
  { code: 'audit', label: 'Журнал', hint: 'События компании', icon: History },
]

export const adminPath = (scope: AdminScope, code: string) => `/admin/${scope}/${code}`

export function findSection(scope: AdminScope, code: string | undefined): AdminSection | undefined {
  const list = scope === 'eco' ? ecosystemSections : companySections
  return list.find((s) => s.code === code)
}
