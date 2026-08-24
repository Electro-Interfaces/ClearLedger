/**
 * Конфиг вкладок окна станции: 8 вкладок, сгруппированы в 4 смысловые группы.
 * «Оборудование» и «Интеграции» отдельными вкладками не живут — они внутри
 * «Паспорта» (решение МАГа 12.08.2026): это свойства объекта, а не свои экраны.
 * Порядок массива = порядок в шапке; группа задаёт визуальные разделители.
 */
import type { ComponentType } from 'react'
import {
  ClipboardList, Activity, Wrench,
  FileSignature, FolderOpen, Wallet, Truck, MessageCircle, Zap,
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
  // Отпуск ЭЭ за период. Сквозная, как «Чаты»: вопрос «сколько станция отпустила
  // с … по …» задаёт и эксплуатация, и проекты, а «Реализация» — разрез продаж,
  // и денег в ней им видеть не положено.
  { value: 'energy', label: 'Энергия', icon: Zap, group: 'object' },
  { value: 'diagnostics', label: 'Статус и диагностика', icon: Activity, group: 'connection' },
  // Заявки по объекту. Вкладка отрисовывалась модалкой, но кнопки в шапке не было —
  // открыть её было нельзя, и обслуживание объекта из его карточки не смотрелось.
  { value: 'service', label: 'Обслуживание', icon: Wrench, group: 'service' },
  // Документооборот и поручения по объекту. Рядом с «Обслуживанием»: там заявки,
  // здесь бумаги и работа — приказ о выводе в ремонт, акт обследования.
  { value: 'track', label: 'Трек', icon: FolderOpen, group: 'service' },
  { value: 'contracts', label: 'Договоры', icon: FileSignature, group: 'commerce' },
  { value: 'sales', label: 'Реализация', icon: Wallet, group: 'commerce' },
  { value: 'supply', label: 'Снабжение', icon: Truck, group: 'commerce' },
  // Обсуждения объекта: группы чата, привязанные к нему. Сквозная вкладка — как и
  // сам объект, разговоры о нём не принадлежат одному продукту.
  { value: 'chats', label: 'Чаты', icon: MessageCircle, group: 'service' },
]

export type CockpitVariant = 'intake' | 'full'
// intake = сырой ввод (левое меню «Точки обслуживания»): только object+connection.
// full = рабочий модуль «Объекты» в Управленческом: все табы.
export const INTAKE_TAB_VALUES = ['passport', 'energy', 'diagnostics']

/**
 * Вкладки станции. Разреза по продукту больше нет (решение МАГа 12.08.2026):
 * станция — ось работы, направления по ней открываются из любого рабочего места.
 * Прежний разрез `SpaceProduct.objectTabs` прятал оборудование и заявки от того,
 * кто пришёл из «Продаж», и создавал впечатление, что их вовсе нет.
 */
export function cockpitTabsFor(variant: CockpitVariant = 'full', locationType?: string): CockpitTab[] {
  const base = variant === 'intake'
    ? COCKPIT_TABS.filter((t) => INTAKE_TAB_VALUES.includes(t.value))
    : COCKPIT_TABS
  // «Энергия» считает зарядные сессии: у АЗС и офисов ей нечего показать.
  return locationType && locationType !== 'ev_charging'
    ? base.filter((t) => t.value !== 'energy')
    : base
}
