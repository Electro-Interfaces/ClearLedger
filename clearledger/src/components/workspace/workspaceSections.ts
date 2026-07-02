/**
 * Единый источник разделов рабочей области и их под-разделов.
 *
 * Разделы = виды учёта (Управленческий/Финансовый/Бухгалтерский/Налоговый) + «Выгрузка».
 * Под-разделы вычисляются с учётом профиля компании и подключённых модулей —
 * ими пользуются и вертикальное меню-гармошка (`WorkspaceModeSidebar`), и сами
 * панели (`AccountingPanels`), чтобы меню и контент были синхронны.
 */

import type { ComponentType } from 'react'
import { BarChart3, Landmark, BookOpen, Receipt, FileOutput } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import type { CoreMode } from '@/contexts/WorkspaceContext'
import type { CentralMenuItem } from './CentralPanelLayout'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { balanceModuleForProfile } from '@/config/balanceModules'
import { useModuleConnections, isModuleConnected, isComponentEnabled } from '@/services/moduleConnectionService'
import { getModuleComponentDefs } from '@/config/moduleComponents'

/* ── Наборы под-разделов ── */

// Управленческий контур сети АЗС (нефтепродукты)
export const MGMT_MENU: CentralMenuItem[] = [
  { key: 'overview',   label: 'Обзор' },
  { key: 'channels',   label: 'Каналы продаж' },
  { key: 'margin',     label: 'Маржа и цены' },
  { key: 'purchases',  label: 'Поступления' },
  { key: 'tanks',      label: 'Топливный баланс' },
]

// Энергомодули раздела «Управленческий» (демо-витрины, подключаются через каталог).
export const ENERGY_MGMT: CentralMenuItem[] = [
  { key: 'procurement',  label: 'Энергозакупка' },
  { key: 'rent',         label: 'Аренда' },
]
export const ENERGY_MGMT_KEYS = ENERGY_MGMT.map((m) => m.key)

// Анализ зарядных сессий ЭЗС (реальные данные, для energy-профиля).
export const CHARGE_SESSIONS_MENU: CentralMenuItem[] = [
  { key: 'cs_overview',   label: 'Сессии: обзор' },
  { key: 'cs_stations',   label: 'По станциям' },
  { key: 'cs_connectors', label: 'По коннекторам' },
  { key: 'cs_time',       label: 'Время и загрузка' },
  { key: 'cs_clients',    label: 'Клиенты и тарифы' },
  { key: 'cs_reliability', label: 'Надёжность' },
  { key: 'cs_dynamics',   label: 'Динамика (тренд)' },
  { key: 'cs_compare',    label: 'Сравнение периодов' },
]
export const CHARGE_SESSIONS_KEYS = CHARGE_SESSIONS_MENU.map((m) => m.key)

export const FIN_MENU: CentralMenuItem[] = [
  { key: 'overview',    label: 'Обзор' },
  { key: 'cashflow',    label: 'Денежный поток' },
  { key: 'receivables', label: 'Дебиторка' },
  { key: 'payables',    label: 'Кредиторка' },
]

export const ACC_MENU: CentralMenuItem[] = [
  { key: 'overview',  label: 'Обзор' },
  { key: 'documents', label: 'Документы 1С' },
  { key: 'export',    label: 'Очередь выгрузки' },
  { key: 'periods',   label: 'Периоды' },
]

export const TAX_MENU: CentralMenuItem[] = [
  { key: 'vat',        label: 'НДС' },
  { key: 'profit',     label: 'Налог на прибыль' },
  { key: 'compliance', label: 'Соответствие' },
]

/* ── Разделы ── */

export interface WorkspaceSection {
  mode: CoreMode
  label: string
  icon: ComponentType<{ className?: string }>
  /** Под-разделы (гармошка). Пусто → раздел без под-меню (цельная витрина/выгрузка). */
  items: CentralMenuItem[]
  /** Подключён ли раздел компании (иначе панель покажет пустое состояние). */
  connected: boolean
}

/**
 * Разделы рабочей области для активной компании (реактивно к подключениям модулей).
 */
export function useWorkspaceSections(): WorkspaceSection[] {
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const { conn } = useModuleConnections()
  const on = (id: string) => {
    const m = getWorkspaceModule(id)
    return m ? isModuleConnected(conn, m, company.profileId) : false
  }

  // Управленческий — динамически из подключённых модулей (топливный P&L + энергомодули + баланс).
  const balMod = balanceModuleForProfile(company.profileId)
  const mgmtItems: CentralMenuItem[] = [
    ...(on('mgmt_pnl') ? MGMT_MENU : []),
    ...(isEnergy ? CHARGE_SESSIONS_MENU : []),
    ...ENERGY_MGMT.filter((m) => on(m.key)),
    ...(balMod && on(balMod.id) ? [{ key: 'balance', label: balMod.navLabel }] : []),
  ]

  const finOn = isEnergy ? on('fin_energy') : on('financial')
  const accOn = isEnergy ? on('acc_energy') : on('accounting')
  const taxOn = isEnergy ? on('tax_energy') : on('tax')

  // Бухгалтерский (fuel) — меню собирается из включённых компонентов модуля под компанию.
  // energy остаётся цельной витриной (у acc_energy нет компонентов в реестре).
  const accItems: CentralMenuItem[] = !isEnergy && accOn
    ? dedupeByKey(
        getModuleComponentDefs('accounting', company.profileId)
          .filter((c) => isComponentEnabled(conn, c, company.profileId))
          .flatMap((c) => c.menuItems ?? []),
      )
    : []

  return [
    { mode: 'management', label: 'Управленческий', icon: BarChart3,  items: mgmtItems, connected: mgmtItems.length > 0 },
    { mode: 'financial',  label: 'Финансовый',     icon: Landmark,   items: !isEnergy && finOn ? FIN_MENU : [], connected: finOn },
    { mode: 'accounting', label: 'Бухгалтерский',  icon: BookOpen,   items: accItems, connected: accOn },
    { mode: 'tax',        label: 'Налоговый',      icon: Receipt,    items: !isEnergy && taxOn ? TAX_MENU : [], connected: taxOn },
    { mode: 'export',     label: 'Выгрузка',       icon: FileOutput, items: [], connected: true },
  ]
}

/** Убрать дубли пунктов меню по ключу (на случай пересечения menuItems компонентов). */
function dedupeByKey(items: CentralMenuItem[]): CentralMenuItem[] {
  const seen = new Set<string>()
  return items.filter((i) => (seen.has(i.key) ? false : (seen.add(i.key), true)))
}
