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
  Library, ShieldCheck, Building2, Building, Boxes, Sparkles, Fuel, RefreshCw, LineChart,
  Cable, Bell, Blocks, KeyRound,
} from 'lucide-react'

export interface NavItemDef {
  to: string
  icon: ComponentType<{ className?: string }>
  label: string
  /** end=true — точное совпадение маршрута (для «Рабочий стол» / `/`). */
  end?: boolean
}

export const dashboardItem: NavItemDef = { to: '/workspace', icon: LayoutDashboard, label: 'Рабочий стол', end: true }

// Верхний уровень меню
export const mainNavItems: NavItemDef[] = [
  dashboardItem,
  { to: '/objects', icon: Boxes, label: 'Объекты' },
  // Чат — универсальный сервис экосистемы (плитка на рабочем столе + встроенная кнопка
  // «Чат с поддержкой» в шапке), а не раздел учёта: из меню приложения убран.
  { to: '/reconciliation', icon: GitCompare, label: 'Разрезы учёта' },
  { to: '/files', icon: FileText, label: 'Документы' },           // первый слой данных (L1 RAW)
  { to: '/contractors', icon: Building2, label: 'Контрагенты' },  // справочник контрагентов (рядом с документами)
  { to: '/intake', icon: Upload, label: 'Загрузка' },             // ручная drag-n-drop загрузка
]

// Раздел «Данные» — работа с самими данными. Трубы (коннекторы, каталог типов)
// переехали в приложение «Подключения»: настройка связи и её состояние должны
// жить в одном месте, иначе про подключение говорят в трёх экранах сразу.
export const dataItems: NavItemDef[] = [
  { to: '/organization', icon: Building, label: 'Организация' },
  { to: '/metrika', icon: LineChart, label: 'Яндекс.Метрика' },
  { to: '/normalization', icon: Sparkles, label: 'Нормализация' },
]

// Приложение «Подключения» — внешний контур пространства. Пути односегментные не для
// красоты: код права страницы = первый сегмент (`pageCode`), и `/connect/notify` дал бы
// всем разделам один ключ `connect`.
export const connectItems: NavItemDef[] = [
  { to: '/connections', icon: Cable, label: 'Состояние' },
  { to: '/connectors', icon: Plug, label: 'Коннекторы' },
  // Источники (реквизиты доступа к внешним системам) были достижимы только
  // глубокими ссылками из каталога и карточки коннектора — при том что меню
  // обещало их пунктом «Источники и коннекторы».
  { to: '/sources', icon: KeyRound, label: 'Источники' },
  { to: '/catalog', icon: Library, label: 'Каталог типов' },
  { to: '/notifications', icon: Bell, label: 'Оповещения' },
  { to: '/apps', icon: Blocks, label: 'Приложения и модули' },
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

// Раздел «Настройки». «Каталоги» здесь не дублируем: каталог типов живёт в
// «Подключениях» (/catalog), а дубль пути с другой подписью перетирал navByPath.
export const settingsItems: NavItemDef[] = [
  { to: '/settings', icon: Settings, label: 'Параметры' },
]

/**
 * Все пункты по пути — из этого словаря продукты пространства (`config/spaceProducts.ts`)
 * собирают своё левое меню, не заводя вторых определений тех же страниц.
 */
export const navByPath: Record<string, NavItemDef> = Object.fromEntries(
  [...mainNavItems, ...dataItems, ...connectItems, ...oneCItems, ...settingsItems].map((i) => [i.to, i]),
)

// Администрирование вынесено из меню Ledger в отдельное приложение «Центр управления»
// (плитка на рабочем столе экосистемы, свой shell AdminLayout). Пункта в сайдбаре нет.
// Определение оставлено для обратной ссылки; в навигации Ledger не используется.
export const adminItem: NavItemDef = { to: '/admin', icon: ShieldCheck, label: 'Центр управления' }
