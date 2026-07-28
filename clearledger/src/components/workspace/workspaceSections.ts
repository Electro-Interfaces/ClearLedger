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
import { BarChart3, Gauge, BookOpen, FileOutput, ShoppingCart, HardHat, Building2, Megaphone, Sparkles, GitCompare, Activity, Wallet, Boxes, Receipt } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace, type CoreMode } from '@/contexts/WorkspaceContext'
import { modeAllowed } from '@/config/accessModules'
import { carvedModes, isCarvedProfile } from '@/config/spaceProducts'
import type { CentralMenuItem } from './CentralPanelLayout'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { useModuleConnections, isModuleConnected, isComponentEnabled } from '@/services/moduleConnectionService'
import { getModuleComponentDefs } from '@/config/moduleComponents'
import { STORE_MENU } from '@/config/storeCatalog'
import {
  MGMT_MENU, MGMT_MENU_KEYS, ENERGY_MGMT, ENERGY_MGMT_KEYS, OPS_MONITOR_MENU,
  EQUIPMENT_MENU, EQUIPMENT_KEYS, SITES_MENU, SITES_KEYS,
  SITES_WORK_MENU, SITES_ANALYTICS_MENU,
  CHARGE_SESSIONS_MENU, CHARGE_SESSIONS_KEYS,
  SALES_NETWORK_MENU, SALES_SESSIONS_MENU, SALES_COMMERCE_MENU,
  MARKET_MENU, MARKET_KEYS,
} from '@/config/workspaceMenus'
// CHARGE_SESSIONS_MENU здесь не используется — общий список нужен карте прав и роутеру
// панелей; секции собираются из трёх меню разделов.
import { productForMode, productModuleAllowed } from '@/config/productAccess'

/* ── Наборы под-разделов ── */

// Сами списки живут в `config/workspaceMenus.ts` — оттуда же их берёт карта прав
// (`config/productAccess.ts`), чтобы пункт меню и право на него не разъезжались.
// Реэкспорт сохранён: внешние импорты продолжают работать.
export {
  MGMT_MENU, MGMT_MENU_KEYS, ENERGY_MGMT, ENERGY_MGMT_KEYS, OPS_MONITOR_MENU,
  EQUIPMENT_MENU, EQUIPMENT_KEYS, SITES_MENU, SITES_KEYS,
  SITES_WORK_MENU, SITES_ANALYTICS_MENU,
  CHARGE_SESSIONS_MENU, CHARGE_SESSIONS_KEYS,
  SALES_NETWORK_MENU, SALES_SESSIONS_MENU, SALES_COMMERCE_MENU,
  MARKET_MENU, MARKET_KEYS,
}

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
  /** Роль закрыла ВСЕ пункты раздела — показывать его нечем (см. `productAccess.ts`). */
  restricted?: boolean
}

/**
 * Разделы рабочей области для активной компании (реактивно к подключениям модулей).
 */
export function useWorkspaceSections(): WorkspaceSection[] {
  const { company, canModule } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const { conn } = useModuleConnections()
  const on = (id: string) => {
    const m = getWorkspaceModule(id)
    return m ? isModuleConnected(conn, m, company.profileId) : false
  }

  // Первый раздел «Продаж»: у топливного профиля — весь его P&L, у energy — «Сеть»
  // (остальные пункты ЭЗС-продаж живут в разделах «Сессии» и «Коммерция»).
  // «Управленческий» (mode=operations) — энергозакупка/аренда (реальные реестры).
  const mgmtItems: CentralMenuItem[] = [
    ...(on('mgmt_pnl') ? MGMT_MENU : []),
    ...(isEnergy ? SALES_NETWORK_MENU : []),
  ]
  // «Эксплуатация» (energy) разложена на три раздела продукта: «Мониторинг» — что с
  // сетью и её данными, «Оборудование» — склад железа, «Хозяйство» — деньги площадок
  // (энергозакупка и аренда, подключаемые модули). У ГИГ (fuel) раздел один и остаётся
  // «Управленческим»: там это хозяйственные отношения компании (договоры/аренда), не
  // баланс (концепт МАГа 13.07.2026) — контроль топлива живёт в «Продажах».
  const energyOps = ENERGY_MGMT.filter((m) => on(m.key))
  const opsItems: CentralMenuItem[] = [
    ...(isEnergy ? OPS_MONITOR_MENU : []),
    ...(!isEnergy && on('ops_contracts') ? [{ key: 'contracts', label: 'Договоры и аренда' }] : []),
    // «Баланс ЭЗС» (демо-витрина BalanceVitrine на DEMO_EZS) убран — реальный
    // пообъектный баланс живёт в «Мониторинг → Баланс (факт)» (ops_balance).
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

  // «Продажи» разложены на три раздела продукта (energy): «Сеть» — состояние и деньги
  // сети, «Сессии» — как заряжают, «Коммерция» — кто платит и по какой цене. В левой
  // рельсе это три пункта, их содержимое — во второй панели. У топливного профиля
  // раздел один и называется по продукту.
  const sales: WorkspaceSection = { mode: 'management', label: isEnergy ? 'Сеть' : 'Продажи',
    icon: BarChart3, items: mgmtItems, connected: mgmtItems.length > 0 }
  const salesSessions: WorkspaceSection = { mode: 'sales_sessions', label: 'Сессии',
    icon: Activity, items: isEnergy ? SALES_SESSIONS_MENU : [], connected: isEnergy }
  const salesCommerce: WorkspaceSection = { mode: 'sales_commerce', label: 'Коммерция',
    icon: Wallet, items: isEnergy ? SALES_COMMERCE_MENU : [], connected: isEnergy }
  // «Проекты» — стройка сети: от подбора участка до ввода станции в эксплуатацию.
  // Только у energy: у топливного профиля своего девелоперского контура нет.
  // Два раздела на один продукт: «Работа» — где ведут дела, «Аналитика» — где
  // смотрят сводку. В левой рельсе это два пункта, их содержимое — во второй панели.
  const projects: WorkspaceSection = { mode: 'projects', label: 'Работа', icon: HardHat,
    items: isEnergy ? SITES_WORK_MENU : [], connected: isEnergy }
  const projectsAnalytics: WorkspaceSection = { mode: 'projects_analytics', label: 'Аналитика',
    icon: BarChart3, items: isEnergy ? SITES_ANALYTICS_MENU : [], connected: isEnergy }
  const ops: WorkspaceSection = { mode: 'operations', label: isEnergy ? 'Мониторинг' : 'Управленческий',
    icon: Gauge, items: opsItems, connected: opsItems.length > 0 }
  const opsEquipment: WorkspaceSection = { mode: 'ops_equipment', label: 'Оборудование',
    icon: Boxes, items: isEnergy ? EQUIPMENT_MENU : [], connected: isEnergy }
  // «Хозяйство» — подключаемые модули: нет ни одного включённого, раздела нет.
  const opsEconomy: WorkspaceSection = { mode: 'ops_economy', label: 'Хозяйство',
    icon: Receipt, items: isEnergy ? energyOps : [], connected: energyOps.length > 0 }
  const store: WorkspaceSection = { mode: 'store',      label: 'Магазин',        icon: ShoppingCart, items: storeOn ? STORE_MENU : [], connected: storeOn }
  // Процессинг и Маркетинг — продукты в подключении (решение МАГа
  // 28.07.2026): свои экраны ещё не сделаны, а коммерческие разделы вернулись в
  // «Продажи». Меню у них нет — рабочая область показывает заставку.
  const corporate: WorkspaceSection = { mode: 'corporate', label: 'Процессинг',
    icon: Building2, items: [], connected: isEnergy }
  // «Маркетинг» получил первый рабочий раздел — рынок вокруг сети (docs/MARKET.md).
  const marketing: WorkspaceSection = { mode: 'marketing', label: 'Рынок',
    icon: Megaphone, items: isEnergy ? MARKET_MENU : [], connected: isEnergy }
  const acc: WorkspaceSection   = { mode: 'accounting', label: 'Бухгалтерский',  icon: BookOpen,     items: accItems, connected: accOn }
  const exp: WorkspaceSection   = { mode: 'export',     label: 'Выгрузка',       icon: FileOutput,   items: [], connected: true }
  // Разделы продукта «Данные» (energy): без них рабочее место открывалось панелью
  // нормализации, но в меню её пункта не было, а право `data:normalize` указывало в
  // пустоту. Под-меню у обеих панелей своё (каналы/разрезы) — items здесь не нужны.
  // У топливного профиля разреза нет: там те же панели живут страницами Учёта
  // (`/normalization`, `/reconciliation`), и вторые пункты дали бы дубль.
  const normalize: WorkspaceSection = { mode: 'normalize', label: 'Нормализация', icon: Sparkles, items: [], connected: true }
  const reconcile: WorkspaceSection = { mode: 'reconcile', label: 'Сверка', icon: GitCompare, items: [], connected: true }

  // Порядок разделов: топливный профиль (ГИГ) — Продажи → Магазин → Управленческий →
  // Бухгалтерский (порядок МАГа 13.07.2026); energy (РусГидро, без магазина) — как было.
  const all = isEnergy
    ? [sales, salesSessions, salesCommerce, corporate, marketing,
       projects, projectsAnalytics, ops, opsEquipment, opsEconomy,
       store, acc, exp, normalize, reconcile]
    : [sales, store, ops, acc, exp]
  // Права на пункты продукта режутся ЗДЕСЬ, а не в меню: тот же массив читают панели
  // (`AccountingPanels`), и урезать его в одном месте — значит не показать закрытый
  // пункт ни в гармошке, ни в контенте. Гейт есть только у продуктов разреза: там код
  // пункта однозначен (`config/productAccess.ts`), в цельном Учёте коды разделов
  // пересекаются между видами учёта, и права остаются на уровне разделов, как были.
  if (!isCarvedProfile(company.profileId)) return all
  return all.map((s) => {
    const app = productForMode(s.mode)
    if (!app || !s.items.length) return s
    const items = s.items.filter((i) => productModuleAllowed(app, i.key, canModule))
    return items.length === s.items.length ? s : { ...s, items, restricted: items.length === 0 }
  })
}

/**
 * Разделы, уместные в ТЕКУЩЕЙ оболочке и доступные ролью.
 *
 * В продукте пространства (`/finance`, `/operations`, …) — только его разделы; в Учёте —
 * все, кроме ушедших в продукты (`carvedModes`, см. `config/spaceProducts.ts`). Иначе один
 * и тот же экран открывался бы двумя путями. У топливного профиля разрез выключен, и Учёт
 * остаётся прежним.
 */
export function useVisibleSections(): WorkspaceSection[] {
  const { company, companyModules } = useCompany()
  const { lockedModes } = useWorkspace()
  const carved = carvedModes(company.profileId)
  return useWorkspaceSections()
    .filter((s) => modeAllowed(s.mode, companyModules))
    .filter((s) => (lockedModes ? lockedModes.includes(s.mode) : !carved.has(s.mode)))
}

/** Убрать дубли пунктов меню по ключу (на случай пересечения menuItems компонентов). */
function dedupeByKey(items: CentralMenuItem[]): CentralMenuItem[] {
  const seen = new Set<string>()
  return items.filter((i) => (seen.has(i.key) ? false : (seen.add(i.key), true)))
}
