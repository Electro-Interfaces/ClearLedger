/**
 * Лейблы под-навигации рабочего стола (режимы + под-разделы) — для коротких
 * заголовков закладок по имени активного пункта меню.
 *
 * Дублирует подписи меню панелей (`components/workspace/AccountingPanels.tsx`)
 * в компактном виде — только ради названия закладки. Если подпись неизвестна,
 * под-раздел в заголовок не попадает (не критично).
 */
import type { CoreMode } from '@/contexts/WorkspaceContext'
import { STORE_MENU, storeMenu } from './storeCatalog'
import { ACCOUNTING_MENU } from './moduleComponents'
import {
  REV_SALES_MENU, REV_CLIENTS_MENU, REV_ITEMS_MENU, REV_DOCS_MENU,
  BOOKS_LEDGER_MENU, BOOKS_PRIMARY_MENU,
} from './workspaceMenus'

/** Пункты «Бухгалтерии» одной картой: разделы делят общий словарь подписей. */
const ACC_SUBS = Object.fromEntries(ACCOUNTING_MENU.map((m) => [m.key, m.label]))

export const MODE_LABELS: Record<CoreMode, string> = {
  // «Данные» компании без объектов: разделы идут от источника (бухгалтерия клиента),
  // а не от каналов приёма файлов.
  connect: 'Подключения',
  data_sources: 'Источники',
  data_model: 'База пространства',
  data_quality: 'Качество данных',
  // Разделы продукта продаж. `management` — исторический код первого («Сеть» у обоих
  // профилей). Подписи нейтральны: у ЭЗС второй раздел зовётся «Сессии», у «Топлива» —
  // «Аналитика», и заголовок закладки почти всегда берётся по пункту (SUB_LABELS).
  management: 'Сеть',
  sales_sessions: 'Аналитика продаж',
  sales_commerce: 'Коммерция',
  sales_goods: 'Товародвижение',
  sales_help: 'Помощь',
  store_help: 'Помощь',
  // Три раздела «Эксплуатации»; `operations` — код первого («Мониторинг» у energy,
  // «Управленческий» у топливного профиля).
  operations: 'Управленческий',
  ops_equipment: 'Эксплуатация · Оборудование',
  ops_economy: 'Эксплуатация · Хозяйство',
  projects: 'Проекты · Работа',
  projects_analytics: 'Проекты · Аналитика',
  store: 'Магазин',
  store_documents: 'Магазин · Документы',
  store_catering: 'Магазин · Общепит',
  store_stock: 'Магазин · Склад',
  store_cash: 'Магазин · Касса',
  store_catalog: 'Магазин · Каталог',
  store_marking: 'Магазин · Маркировка',
  store_network: 'Магазин · Станции',
  store_1c: 'Магазин · 1С до перехода',
  store_reports: 'Магазин · Отчёты',
  corporate: 'Процессинг',
  marketing: 'Маркетинг',
  financial: 'Финансовый',
  // Разделы «Бухгалтерии»: потоки + сквозное. `accounting` — первый раздел
  // («Нефтепродукты»), исторический код продукта и ключ доступа.
  accounting: 'Бухгалтерия · Нефтепродукты',
  acc_period: 'Бухгалтерия · Период',
  acc_store: 'Бухгалтерия · Магазин',
  acc_food: 'Бухгалтерия · Общепит',
  acc_recon: 'Бухгалтерия · Сверка',
  acc_docs: 'Бухгалтерия · Документы',
  acc_results: 'Бухгалтерия · Итоги',
  tax: 'Налоговый',
  export: 'Выгрузка',
  normalize: 'Нормализация',
  reconcile: 'Сверка',
  // Разделы продуктов компании без объектов: «Реализация» и «Бухгалтерия».
  rev_sales: 'Реализация · Продажи',
  rev_buyers: 'Реализация · Покупатели',
  rev_catalog: 'Реализация · Что продаём',
  rev_papers: 'Реализация · Документы',
  books_ledger: 'Бухгалтерия · Регистр',
  books_primary: 'Бухгалтерия · Документы',
}

// Подписи под-разделов по режимам (ключ = ключ под-вида в панели).
const SUB_LABELS: Partial<Record<CoreMode, Record<string, string>>> = {
  // Подписи те же, что в меню (`SITES_MENU`): хлебная крошка и пункт меню должны
  // называться одинаково, иначе человек не понимает, где он оказался.
  projects: {
    pr_project: 'Проекты', pr_projects: 'Проекты', sites_list: 'Площадки',
    pr_plan: 'План работ',
    pr_tp: 'Присоединение', pr_equipment: 'Оборудование', sites_map: 'Карта',
  },
  projects_analytics: {
    pr_portfolio: 'Обзор', sites_overview: 'Воронка', sites_priority: 'Приоритеты',
    pr_budget: 'Бюджет', pr_accounting: 'Ждёт учёта',
  },
  // Подписи двух профилей лежат в одном режиме: коды не пересекаются, а старые
  // закладки «Топлива» (все 12 пунктов жили под `management`) продолжают
  // подписываться правильно — даже когда пункт уехал в свой раздел.
  management: {
    overview: 'Обзор', map: 'Карта', transactions: 'Реестр операций',
    fills: 'Реализация', 'fuel-tariffs': 'Тарифы', 'fuel-corporate': 'Корпоратив', 'fuel-retail': 'Частные лица',
    'by-station': 'По станциям', 'by-fuel': 'По топливу',
    'by-month': 'По месяцам', channels: 'Каналы продаж', 'online-orders': 'Онлайн-заказы',
    coupons: 'Купоны', margin: 'Маржа и цены',
    purchases: 'Поступления', intake: 'Приёмка и сливы', tanks: 'Контроль баланса',
    'tank-specs': 'Резервуары',
    variances: 'Расхождения', inventory: 'Инвентаризация', balance: 'Баланс',
    pumps: 'Загрузка ТРК', abcxyz: 'ABC-XYZ', visits: 'Визиты', clients: 'Клиенты и когорты',
    procurement: 'Энергозакупка', rent: 'Аренда',
    cs_dashboard: 'Обзор', cs_map: 'Карта', cs_trend: 'Динамика 2024+',
    cs_abcxyz: 'ABC-XYZ станций', cs_reliability: 'Надёжность',
  },
  sales_sessions: {
    cs_breakdown: 'Разрезы', cs_time: 'Время и загрузка', cs_dynamics: 'Тренд и YoY',
    cs_compare: 'Сравнение периодов', cs_list: 'Реестр сессий',
    cs_sessions: 'Разрезы',  // старая ссылка ?sub=cs_sessions
    fills: 'Реализация', visits: 'Визиты', transactions: 'Реестр операций',
    channels: 'Каналы продаж', 'online-orders': 'Онлайн-заказы', coupons: 'Купоны',
  },
  sales_commerce: {
    cs_clients: 'Тарифы', cs_corporate: 'Корпоратив',
    cs_retail: 'Частные лица', cs_segments: 'Сегменты и когорты',
    cs_payments: 'Платежи и чеки',
    'fuel-tariffs': 'Тарифы', 'fuel-corporate': 'Корпоратив', 'fuel-retail': 'Частные лица',
    clients: 'Клиенты и когорты',
  },
  sales_goods: {
    // `shifts` совпадает с ключом «Бухгалтерского» намеренно: подпись берётся из
    // карты СВОЕГО раздела, а переход между продуктами по одному ключу запрещён.
    shifts: 'Сменные отчёты',
    margin: 'Маржа и цены', purchases: 'Поступления', intake: 'Приёмка и сливы',
    tanks: 'Контроль баланса', variances: 'Расхождения', inventory: 'Инвентаризация',
  },
  store_help: {
    'help-start': 'Торговля', 'help-stock': 'Склад и движение',
    'help-catalog': 'Каталог и рецептуры', 'help-marking': 'Маркировка',
    'help-closing': 'Закрытие периода', 'help-docs': 'Документы компании',
  },
  sales_help: {
    'help-start': 'Как работать', 'help-goods': 'Товародвижение',
    'help-money': 'Цены и клиенты', 'help-norms': 'Нормы и учёт',
    'help-docs': 'Документы компании',
  },
  operations: {
    ops_overview: 'Обзор', ops_balance: 'Баланс (факт)', ops_completeness: 'Полнота данных',
    balance: 'Баланс ЭЗС', contracts: 'Договоры и аренда',
  },
  ops_equipment: {
    eq_fleet: 'Парк оборудования', eq_warehouses: 'Склады и остатки',
    eq_supplies: 'Поставки и возвраты',
    eq_movements: 'Движения', eq_spares: 'ЗИП и запчасти',
  },
  ops_economy: { procurement: 'Энергозакупка', rent: 'Аренда' },
  marketing: {
    mk_position: 'Позиция', mk_map: 'Карта рынка', mk_sites: 'Точки рынка',
    mk_operators: 'Операторы', mk_observations: 'Наблюдения',
  },
  store: Object.fromEntries(STORE_MENU.map((m) => [m.key, m.label])),
  store_documents: Object.fromEntries(storeMenu('store_documents').map((m) => [m.key, m.label])),
  store_catering: Object.fromEntries(storeMenu('store_catering').map((m) => [m.key, m.label])),
  store_stock: Object.fromEntries(storeMenu('store_stock').map((m) => [m.key, m.label])),
  store_cash: Object.fromEntries(storeMenu('store_cash').map((m) => [m.key, m.label])),
  store_catalog: Object.fromEntries(storeMenu('store_catalog').map((m) => [m.key, m.label])),
  store_marking: Object.fromEntries(storeMenu('store_marking').map((m) => [m.key, m.label])),
  store_network: Object.fromEntries(storeMenu('store_network').map((m) => [m.key, m.label])),
  store_1c: Object.fromEntries(storeMenu('store_1c').map((m) => [m.key, m.label])),
  store_reports: Object.fromEntries(storeMenu('store_reports').map((m) => [m.key, m.label])),
  financial: {
    overview: 'Обзор', cashflow: 'Денежный поток', receivables: 'Дебиторка', payables: 'Кредиторка',
  },
  // Подписи пунктов «Бухгалтерии» — из самого каталога компонентов: меню и заголовок
  // закладки обязаны называться одинаково, а второго списка для этого не нужно.
  accounting: ACC_SUBS,
  acc_period: ACC_SUBS,
  acc_store: ACC_SUBS,
  acc_food: ACC_SUBS,
  acc_recon: ACC_SUBS,
  acc_docs: ACC_SUBS,
  acc_results: ACC_SUBS,
  tax: {
    vat: 'НДС', profit: 'Налог на прибыль', compliance: 'Соответствие',
  },
  // Пункты офисных продуктов — из тех же списков, что рисуют меню.
  rev_sales: Object.fromEntries(REV_SALES_MENU.map((m) => [m.key, m.label])),
  rev_buyers: Object.fromEntries(REV_CLIENTS_MENU.map((m) => [m.key, m.label])),
  rev_catalog: Object.fromEntries(REV_ITEMS_MENU.map((m) => [m.key, m.label])),
  rev_papers: Object.fromEntries(REV_DOCS_MENU.map((m) => [m.key, m.label])),
  books_ledger: Object.fromEntries(BOOKS_LEDGER_MENU.map((m) => [m.key, m.label])),
  books_primary: Object.fromEntries(BOOKS_PRIMARY_MENU.map((m) => [m.key, m.label])),
}

const VALID_MODES = new Set(Object.keys(MODE_LABELS))

export function isCoreMode(v: string | null | undefined): v is CoreMode {
  return !!v && VALID_MODES.has(v)
}

/** Короткий заголовок закладки: конечный пункт меню или раздел верхнего уровня. */
export function workspaceTitle(mode: CoreMode, sub?: string | null): string {
  const modeLabel = MODE_LABELS[mode] ?? 'Рабочий стол'
  const subLabel = sub ? SUB_LABELS[mode]?.[sub] : undefined
  return subLabel ?? modeLabel
}
