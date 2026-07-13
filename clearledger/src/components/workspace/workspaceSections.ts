/**
 * Единый источник разделов рабочей области и их под-разделов.
 *
 * Разделы = виды учёта (Управленческий/Бухгалтерский/…) + «Выгрузка».
 * «Финансовый» и «Налоговый» сняты с витрины 13.07.2026 (пустые заготовки) —
 * панели и типы CoreMode сохранены, вернуть = добавить записи в массив ниже.
 * Под-разделы вычисляются с учётом профиля компании и подключённых модулей —
 * ими пользуются и вертикальное меню-гармошка (`WorkspaceModeSidebar`), и сами
 * панели (`AccountingPanels`), чтобы меню и контент были синхронны.
 */

import type { ComponentType } from 'react'
import { BarChart3, Gauge, BookOpen, FileOutput, ShoppingCart } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import type { CoreMode } from '@/contexts/WorkspaceContext'
import type { CentralMenuItem } from './CentralPanelLayout'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { balanceModuleForProfile } from '@/config/balanceModules'
import { useModuleConnections, isModuleConnected, isComponentEnabled } from '@/services/moduleConnectionService'
import { getModuleComponentDefs } from '@/config/moduleComponents'
import { STORE_MENU } from '@/config/storeCatalog'

/* ── Наборы под-разделов ── */

// Управленческий контур сети АЗС (нефтепродукты)
export const MGMT_MENU: CentralMenuItem[] = [
  { key: 'overview',     label: 'Обзор' },
  { key: 'map',          label: 'Карта' },
  { key: 'channels',     label: 'Каналы продаж' },
  { key: 'online-orders', label: 'Онлайн-заказы' },
  { key: 'transactions', label: 'Операции' },
  { key: 'margin',       label: 'Маржа и цены' },
  { key: 'purchases',    label: 'Поступления' },
  { key: 'tanks',        label: 'Контроль баланса' },
]

// Энергомодули раздела «Управленческий» (демо-витрины, подключаются через каталог).
export const ENERGY_MGMT: CentralMenuItem[] = [
  { key: 'procurement',  label: 'Энергозакупка' },
  { key: 'rent',         label: 'Аренда' },
]
export const ENERGY_MGMT_KEYS = ENERGY_MGMT.map((m) => m.key)

// Анализ зарядных сессий ЭЗС (реальные данные, для energy-профиля).
// Сгруппировано по смыслу (заголовки групп рисует сайдбар по полю group):
//   СЕТЬ — состояние сети (обзор + карта);
//   АНАЛИТИКА СЕССИЙ — агрегаты (Сессии: внутр. табы) + построчный реестр;
//   КОММЕРЦИЯ — цена (тарифы) и клиентские направления (ЮЛ/ФЛ).
export const CHARGE_SESSIONS_MENU: CentralMenuItem[] = [
  { key: 'cs_dashboard',  label: 'Обзор',         group: 'Сеть' },
  { key: 'cs_map',        label: 'Карта',         group: 'Сеть' },
  { key: 'cs_sessions',    label: 'Сессии',        group: 'Аналитика сессий' },
  { key: 'cs_reliability', label: 'Надёжность',    group: 'Аналитика сессий' },
  { key: 'cs_list',        label: 'Реестр сессий', group: 'Аналитика сессий' },
  { key: 'cs_clients',    label: 'Тарифы',        group: 'Коммерция' },
  { key: 'cs_corporate',  label: 'Корпоратив',    group: 'Коммерция' },
  { key: 'cs_retail',     label: 'Частные лица',  group: 'Коммерция' },
]
export const CHARGE_SESSIONS_KEYS = CHARGE_SESSIONS_MENU.map((m) => m.key)

// Меню бухгалтерского (mode=accounting) собирается из включённых компонентов модуля
// (getModuleComponentDefs('accounting')) в useWorkspaceSections — статичного ACC_MENU
// нет. Реальные пункты: Дашборды · Поступления · Смены · Выгрузка в БП · Сверка · Маржа.

// «Магазин» (mode=store) — товароучёт сопутки/общепита: полная целевая карта
// (коннектор, аналитика, товары/НСИ, движение, Честный Знак, выгрузка в БП).
// Меню задаётся data-driven в config/storeCatalog.ts (STORE_MENU).

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

  // «Продажи» (mode=management) — аналитика продаж: топливный P&L + сессии ЭЗС.
  // «Управленческий» (mode=operations) — энергозакупка/аренда/баланс (перенесено из management).
  const balMod = balanceModuleForProfile(company.profileId)
  const mgmtItems: CentralMenuItem[] = [
    ...(on('mgmt_pnl') ? MGMT_MENU : []),
    ...(isEnergy ? CHARGE_SESSIONS_MENU : []),
  ]
  // «Управленческий» у ГИГ (fuel) = хозяйственные отношения компании (договоры/аренда),
  // не баланс (концепт МАГа 13.07.2026): контроль топлива уже живёт в «Продажах»,
  // «Баланс АЗС» из этого раздела убран. У energy — энергозакупка/аренда/баланс ЭЗС.
  const energyOps = ENERGY_MGMT.filter((m) => on(m.key))
  const opsItems: CentralMenuItem[] = [
    // Кокпит решений (energy) — ядро раздела, не отключаемый модуль: обзор ситуации
    // (светофор проблем + рабочие списки) и пообъектный энергобаланс
    // (вход по счетам vs отпуск по сессиям vs собственные нужды станции).
    ...(isEnergy && energyOps.length > 0
      ? [
          { key: 'ops_overview', label: 'Обзор' },
          { key: 'ops_balance', label: 'Баланс (факт)' },
          { key: 'ops_completeness', label: 'Полнота данных' },
        ]
      : []),
    ...energyOps,
    ...(!isEnergy && on('ops_contracts') ? [{ key: 'contracts', label: 'Договоры и аренда' }] : []),
    ...(balMod && on(balMod.id) && isEnergy ? [{ key: 'balance', label: balMod.navLabel }] : []),
  ]

  const storeOn = on('store_module')
  const accOn = isEnergy ? on('acc_energy') : on('accounting')

  // Бухгалтерский (fuel) — меню собирается из включённых компонентов модуля под компанию.
  // energy остаётся цельной витриной (у acc_energy нет компонентов в реестре).
  const accItems: CentralMenuItem[] = !isEnergy && accOn
    ? dedupeByKey(
        getModuleComponentDefs('accounting', company.profileId)
          .filter((c) => isComponentEnabled(conn, c, company.profileId))
          .flatMap((c) => c.menuItems ?? []),
      )
    : []

  const sales: WorkspaceSection = { mode: 'management', label: 'Продажи',        icon: BarChart3,    items: mgmtItems, connected: mgmtItems.length > 0 }
  const ops: WorkspaceSection   = { mode: 'operations', label: 'Управленческий', icon: Gauge,        items: opsItems, connected: opsItems.length > 0 }
  const store: WorkspaceSection = { mode: 'store',      label: 'Магазин',        icon: ShoppingCart, items: storeOn ? STORE_MENU : [], connected: storeOn }
  const acc: WorkspaceSection   = { mode: 'accounting', label: 'Бухгалтерский',  icon: BookOpen,     items: accItems, connected: accOn }
  const exp: WorkspaceSection   = { mode: 'export',     label: 'Выгрузка',       icon: FileOutput,   items: [], connected: true }

  // Порядок разделов: топливный профиль (ГИГ) — Продажи → Магазин → Управленческий →
  // Бухгалтерский (порядок МАГа 13.07.2026); energy (РусГидро, без магазина) — как было.
  return isEnergy
    ? [sales, ops, store, acc, exp]
    : [sales, store, ops, acc, exp]
}

/** Убрать дубли пунктов меню по ключу (на случай пересечения menuItems компонентов). */
function dedupeByKey(items: CentralMenuItem[]): CentralMenuItem[] {
  const seen = new Set<string>()
  return items.filter((i) => (seen.has(i.key) ? false : (seen.add(i.key), true)))
}
