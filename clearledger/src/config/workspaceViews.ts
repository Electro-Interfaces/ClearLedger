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
  management: 'Продажи',
  operations: 'Управленческий',
  store: 'Магазин',
  financial: 'Финансовый',
  accounting: 'Бухгалтерский',
  tax: 'Налоговый',
  export: 'Выгрузка',
  normalize: 'Нормализация',
  reconcile: 'Сверка',
}

// Подписи под-разделов по режимам (ключ = ключ под-вида в панели).
const SUB_LABELS: Partial<Record<CoreMode, Record<string, string>>> = {
  management: {
    overview: 'Обзор', map: 'Карта', transactions: 'Реестр операций',
    fills: 'Реализация', 'fuel-tariffs': 'Тарифы', 'fuel-corporate': 'Корпоратив', 'fuel-retail': 'Частные лица',
    'by-station': 'По станциям', 'by-fuel': 'По топливу',
    'by-month': 'По месяцам', channels: 'Каналы продаж', 'online-orders': 'Онлайн-заказы', margin: 'Маржа и цены',
    purchases: 'Поступления', tanks: 'Контроль баланса', balance: 'Баланс',
    procurement: 'Энергозакупка', rent: 'Аренда',
    cs_dashboard: 'Обзор сети', cs_map: 'Карта', cs_trend: 'Динамика 2024+', cs_list: 'Реестр сессий', cs_sessions: 'Сессии', cs_reliability: 'Надёжность', cs_clients: 'Тарифы', cs_corporate: 'Корпоратив', cs_retail: 'Частные лица',
  },
  operations: {
    ops_overview: 'Обзор', ops_balance: 'Баланс (факт)', ops_completeness: 'Полнота данных',
    eq_fleet: 'Парк оборудования', eq_warehouses: 'Склады и остатки',
    eq_movements: 'Движения', eq_spares: 'ЗИП и запчасти',
    procurement: 'Энергозакупка', rent: 'Аренда', balance: 'Баланс ЭЗС', contracts: 'Договоры и аренда',
  },
  store: Object.fromEntries(STORE_MENU.map((m) => [m.key, m.label])),
  financial: {
    overview: 'Обзор', cashflow: 'Денежный поток', receivables: 'Дебиторка', payables: 'Кредиторка',
  },
  accounting: {
    shifts: 'Смены', ttn: 'Поступления', margin: 'Маржинальность', reports: 'Дашборды', recon1c: 'Сверка с 1С',
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
