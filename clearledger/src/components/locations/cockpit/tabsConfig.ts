/**
 * Конфиг вкладок окна станции: 9 вкладок, сгруппированы в 4 смысловые группы.
 * Порядок массива = порядок в шапке; группа задаёт визуальные разделители.
 */
import type { ComponentType } from 'react'
import {
  ClipboardList, Cpu, Plug, Activity,
  FileSignature, Wallet, Truck,
} from 'lucide-react'

export type CockpitGroup = 'object' | 'connection' | 'service' | 'commerce'

export interface CockpitTab {
  value: string
  label: string
  icon: ComponentType<{ className?: string }>
  group: CockpitGroup
}

export const GROUP_META: Record<CockpitGroup, { label: string }> = {
  object: { label: 'Объект' },
  connection: { label: 'Подключение' },
  service: { label: 'Сервис' },
  commerce: { label: 'Коммерция' },
}

export const COCKPIT_TABS: CockpitTab[] = [
  { value: 'passport', label: 'Паспорт', icon: ClipboardList, group: 'object' },
  { value: 'equipment', label: 'Оборудование', icon: Cpu, group: 'object' },
  { value: 'integrations', label: 'Интеграции', icon: Plug, group: 'connection' },
  { value: 'diagnostics', label: 'Статус и диагностика', icon: Activity, group: 'connection' },
  { value: 'contracts', label: 'Договоры', icon: FileSignature, group: 'commerce' },
  { value: 'sales', label: 'Реализация', icon: Wallet, group: 'commerce' },
  { value: 'supply', label: 'Снабжение', icon: Truck, group: 'commerce' },
]

export type CockpitVariant = 'intake' | 'full'
// intake = сырой ввод (левое меню «Точки обслуживания»): только object+connection.
// full = рабочий модуль «Объекты» в Управленческом: все табы.
export const INTAKE_TAB_VALUES = ['passport', 'equipment', 'integrations', 'diagnostics']

/**
 * Вкладки станции для текущего места работы.
 *
 * `allowed` — разрез продукта пространства (`SpaceProduct.objectTabs`): станция одна на
 * всю компанию, но эксплуатации нужны железо и связь, продажам — выручка, финансам —
 * договоры и снабжение, данным — подключённые источники. Не задан — показываем всё.
 */
export function cockpitTabsFor(variant: CockpitVariant = 'full', allowed?: string[]): CockpitTab[] {
  const base = variant === 'intake'
    ? COCKPIT_TABS.filter((t) => INTAKE_TAB_VALUES.includes(t.value))
    : COCKPIT_TABS
  if (!allowed?.length) return base
  const shown = base.filter((t) => allowed.includes(t.value))
  // Пустой разрез оставил бы окно вовсе без вкладок — лучше паспорт, чем ничего.
  return shown.length > 0 ? shown : base.filter((t) => t.value === 'passport')
}
