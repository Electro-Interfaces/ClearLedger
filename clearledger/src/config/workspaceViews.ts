/**
 * Лейблы под-навигации рабочего стола (режимы + под-разделы) — для заголовков
 * закладок вида «Рабочий стол · Финансовый · Дебиторка».
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
    overview: 'Обзор', 'by-station': 'По станциям', 'by-fuel': 'По топливу',
    'by-month': 'По месяцам', channels: 'Каналы продаж', margin: 'Маржа и цены',
    purchases: 'Поступления', tanks: 'Контроль баланса', balance: 'Баланс',
    procurement: 'Энергозакупка', rent: 'Аренда',
    cs_dashboard: 'Обзор сети', cs_map: 'Карта', cs_list: 'Реестр сессий', cs_sessions: 'Сессии', cs_reliability: 'Надёжность', cs_clients: 'Тарифы', cs_corporate: 'Корпоратив', cs_retail: 'Частные лица',
  },
  operations: {
    procurement: 'Энергозакупка', rent: 'Аренда', balance: 'Баланс ЭЗС',
  },
  store: Object.fromEntries(STORE_MENU.map((m) => [m.key, m.label])),
  financial: {
    overview: 'Обзор', cashflow: 'Денежный поток', receivables: 'Дебиторка', payables: 'Кредиторка',
  },
  accounting: {
    overview: 'Обзор',
    shifts: 'Смены', ttn: 'Поступления', margin: 'Маржинальность', reports: 'Дашборды', recon1c: 'Сверка с 1С',
  },
  tax: {
    vat: 'НДС', profit: 'Налог на прибыль', compliance: 'Соответствие',
  },
}

const VALID_MODES = new Set(Object.keys(MODE_LABELS))

export function isCoreMode(v: string | null | undefined): v is CoreMode {
  return !!v && VALID_MODES.has(v)
}

/** Заголовок закладки рабочего стола по режиму и под-разделу. */
export function workspaceTitle(mode: CoreMode, sub?: string | null): string {
  const modeLabel = MODE_LABELS[mode] ?? 'Рабочий стол'
  const subLabel = sub ? SUB_LABELS[mode]?.[sub] : undefined
  return subLabel
    ? `Рабочий стол · ${modeLabel} · ${subLabel}`
    : `Рабочий стол · ${modeLabel}`
}
