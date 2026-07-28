/**
 * Лейблы под-навигации рабочего стола (режимы + под-разделы) — для коротких
 * заголовков закладок по имени активного пункта меню.
 *
 * Дублирует подписи меню панелей (`components/workspace/AccountingPanels.tsx`)
 * в компактном виде — только ради названия закладки. Если подпись неизвестна,
 * под-раздел в заголовок не попадает (не критично).
 */
import type { CoreMode } from '@/contexts/WorkspaceContext'
import { STORE_MENU } from './storeCatalog'

export const MODE_LABELS: Record<CoreMode, string> = {
  // Три раздела «Продаж». `management` — исторический код первого: у сети ЭЗС это
  // «Сеть», у топливного профиля — весь его раздел «Продажи».
  management: 'Продажи',
  sales_sessions: 'Продажи · Сессии',
  sales_commerce: 'Продажи · Коммерция',
  // Три раздела «Эксплуатации»; `operations` — код первого («Мониторинг» у energy,
  // «Управленческий» у топливного профиля).
  operations: 'Управленческий',
  ops_equipment: 'Эксплуатация · Оборудование',
  ops_economy: 'Эксплуатация · Хозяйство',
  projects: 'Проекты · Работа',
  projects_analytics: 'Проекты · Аналитика',
  store: 'Магазин',
  corporate: 'Процессинг',
  marketing: 'Маркетинг',
  financial: 'Финансовый',
  accounting: 'Бухгалтерский',
  tax: 'Налоговый',
  export: 'Выгрузка',
  normalize: 'Нормализация',
  reconcile: 'Сверка',
}

// Подписи под-разделов по режимам (ключ = ключ под-вида в панели).
const SUB_LABELS: Partial<Record<CoreMode, Record<string, string>>> = {
  // Подписи те же, что в меню (`SITES_MENU`): хлебная крошка и пункт меню должны
  // называться одинаково, иначе человек не понимает, где он оказался.
  projects: {
    pr_project: 'Проекты', pr_projects: 'Проекты', sites_list: 'Площадки',
    pr_tp: 'Присоединение', pr_equipment: 'Оборудование', sites_map: 'Карта',
  },
  projects_analytics: {
    pr_portfolio: 'Обзор', sites_overview: 'Воронка', sites_priority: 'Приоритеты',
    pr_budget: 'Бюджет', pr_accounting: 'Ждёт учёта',
  },
  management: {
    overview: 'Обзор', map: 'Карта', transactions: 'Реестр операций',
    fills: 'Реализация', 'fuel-tariffs': 'Тарифы', 'fuel-corporate': 'Корпоратив', 'fuel-retail': 'Частные лица',
    'by-station': 'По станциям', 'by-fuel': 'По топливу',
    'by-month': 'По месяцам', channels: 'Каналы продаж', 'online-orders': 'Онлайн-заказы', margin: 'Маржа и цены',
    purchases: 'Поступления', tanks: 'Контроль баланса', balance: 'Баланс',
    procurement: 'Энергозакупка', rent: 'Аренда',
    cs_dashboard: 'Обзор', cs_map: 'Карта', cs_trend: 'Динамика 2024+',
    cs_abcxyz: 'ABC-XYZ станций', cs_reliability: 'Надёжность',
  },
  sales_sessions: {
    cs_breakdown: 'Разрезы', cs_time: 'Время и загрузка', cs_dynamics: 'Тренд и YoY',
    cs_compare: 'Сравнение периодов', cs_list: 'Реестр сессий',
    cs_sessions: 'Разрезы',  // старая ссылка ?sub=cs_sessions
  },
  sales_commerce: {
    cs_clients: 'Тарифы', cs_corporate: 'Корпоратив',
    cs_retail: 'Частные лица', cs_segments: 'Сегменты и когорты',
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
    mk_map: 'Карта рынка', mk_sites: 'Точки рынка',
    mk_operators: 'Операторы', mk_observations: 'Наблюдения',
  },
  store: Object.fromEntries(STORE_MENU.map((m) => [m.key, m.label])),
  financial: {
    overview: 'Обзор', cashflow: 'Денежный поток', receivables: 'Дебиторка', payables: 'Кредиторка',
  },
  accounting: {
    shifts: 'Смены', ttn: 'Поступления', margin: 'Маржинальность', reports: 'Дашборды', cash: 'Касса и инкассация', recon1c: 'Сверка с 1С',
    cb_load: 'Загрузка из ЦБ', cb_shifts: 'Смены сопутки', export: 'Выгрузка в БП', cb_recon: 'Сверка сопутки',
  },
  tax: {
    vat: 'НДС', profit: 'Налог на прибыль', compliance: 'Соответствие',
  },
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
