/**
 * Единый источник пунктов левого меню.
 *
 * Раньше массивы были захардкожены в `AppSidebar.tsx`. Вынесены сюда, чтобы
 * и сайдбар, и система вкладок (`config/tabRegistry.ts`) брали лейблы/иконки
 * из одного места — заголовки вкладок получаются автоматически.
 */
import type { ComponentType } from 'react'
import {
  LayoutDashboard, Settings, Upload, FileText,
  Plug, BookOpen, CalendarClock, Link2, Package,
  Landmark, ScrollText, Tag, Layers, GitCompare,
  Library, ShieldCheck, Building2, Building, Boxes, Sparkles, Fuel, RefreshCw,
} from 'lucide-react'

export interface NavItemDef {
  to: string
  icon: ComponentType<{ className?: string }>
  label: string
  /** end=true — точное совпадение маршрута (для «Рабочий стол» / `/`). */
  end?: boolean
}

export const dashboardItem: NavItemDef = { to: '/', icon: LayoutDashboard, label: 'Рабочий стол', end: true }

// Верхний уровень меню
export const mainNavItems: NavItemDef[] = [
  dashboardItem,
  { to: '/objects', icon: Boxes, label: 'Объекты' },
  { to: '/reconciliation', icon: GitCompare, label: 'Разрезы учёта' },
  { to: '/files', icon: FileText, label: 'Документы' },           // первый слой данных (L1 RAW)
  { to: '/contractors', icon: Building2, label: 'Контрагенты' },  // справочник контрагентов (рядом с документами)
  { to: '/intake', icon: Upload, label: 'Загрузка' },             // ручная drag-n-drop загрузка
]

// Раздел «Данные»
export const dataItems: NavItemDef[] = [
  { to: '/organization', icon: Building, label: 'Организация' },
  { to: '/connectors', icon: Plug, label: 'Коннекторы' },
  { to: '/normalization', icon: Sparkles, label: 'Нормализация' },
]

// Раздел «1С» — только для fuel-профиля (ГИГ)
export const oneCItems: NavItemDef[] = [
  { to: '/1c/connection',         icon: Plug,          label: 'Подключение' },
  { to: '/1c/sync',               icon: RefreshCw,     label: 'Синхронизация' },
  { to: '/1c/references',         icon: BookOpen,      label: 'Справочники' },
  { to: '/1c/documents',          icon: FileText,      label: 'Документы' },
  { to: '/1c/periods',            icon: CalendarClock, label: 'Периоды' },
  { to: '/1c/policy',             icon: Landmark,      label: 'Учётная политика' },
  { to: '/1c/posting-templates',  icon: ScrollText,    label: 'Схема проводок' },
  { to: '/1c/prices',             icon: Tag,           label: 'Цены' },
  { to: '/1c/batches',            icon: Layers,        label: 'Партии (FIFO)' },
  { to: '/1c/fuel-mappings',      icon: Fuel,          label: 'Топливо: оплаты' },
  { to: '/1c/mappings',           icon: Link2,         label: 'Маппинги' },
  { to: '/1c/export',             icon: Package,       label: 'Выгрузка' },
]

// Раздел «Настройки»
export const settingsItems: NavItemDef[] = [
  { to: '/settings', icon: Settings, label: 'Параметры' },
  { to: '/catalog', icon: Library, label: 'Каталоги' },
]

// Администрирование (для админа/суперадмина)
export const adminItem: NavItemDef = { to: '/admin', icon: ShieldCheck, label: 'Администрирование' }
