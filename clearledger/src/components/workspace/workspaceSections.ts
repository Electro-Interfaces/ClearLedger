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
import { BarChart3, Gauge, BookOpen, FileOutput, HardHat, Building2, Megaphone, Sparkles, GitCompare, Activity, Wallet, Boxes, Receipt, Truck } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace, type CoreMode } from '@/contexts/WorkspaceContext'
import { modeAllowed } from '@/config/accessModules'
import { carvedModes, isCarvedProfile } from '@/config/spaceProducts'
import type { CentralMenuItem } from './CentralPanelLayout'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { useModuleConnections, isModuleConnected, isComponentEnabled } from '@/services/moduleConnectionService'
import { getModuleComponentDefs } from '@/config/moduleComponents'
import { STORE_SECTIONS, storeMenu } from '@/config/storeCatalog'
import {
  MGMT_MENU, MGMT_MENU_KEYS, ENERGY_MGMT, ENERGY_MGMT_KEYS, OPS_MONITOR_MENU,
  EQUIPMENT_MENU, EQUIPMENT_KEYS, SITES_MENU, SITES_KEYS,
  SITES_WORK_MENU, SITES_ANALYTICS_MENU,
  CHARGE_SESSIONS_MENU, CHARGE_SESSIONS_KEYS,
  SALES_NETWORK_MENU, SALES_SESSIONS_MENU, SALES_COMMERCE_MENU,
  FUEL_NETWORK_MENU, FUEL_ANALYTICS_MENU, FUEL_COMMERCE_MENU, FUEL_GOODS_MENU,
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
  FUEL_NETWORK_MENU, FUEL_ANALYTICS_MENU, FUEL_COMMERCE_MENU, FUEL_GOODS_MENU,
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

  // Первый раздел продукта продаж — «Сеть» у обоих профилей: у energy это ЭЗС-меню,
  // у топливного — обзор и карта сети АЗС (остальные его пункты живут в разделах
  // «Аналитика», «Коммерция» и «Товародвижение», см. workspaceMenus).
  const fuelSales = on('mgmt_pnl')
  const mgmtItems: CentralMenuItem[] = isEnergy
    ? SALES_NETWORK_MENU
    : (fuelSales ? FUEL_NETWORK_MENU : [])
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

  // Продукт продаж разложен на разделы у обоих профилей: у ЭЗС «Сеть» — состояние и
  // деньги сети, «Сессии» — как заряжают, «Коммерция» — кто платит и по какой цене;
  // у «Топлива» (fuel) — «Сеть», «Аналитика», «Коммерция», «Товародвижение».
  // В левой рельсе это пункты, их содержимое — во второй панели.
  const sales: WorkspaceSection = { mode: 'management', label: 'Сеть',
    icon: BarChart3, items: mgmtItems, connected: mgmtItems.length > 0 }
  const salesSessionItems = isEnergy ? SALES_SESSIONS_MENU : (fuelSales ? FUEL_ANALYTICS_MENU : [])
  const salesSessions: WorkspaceSection = { mode: 'sales_sessions',
    label: isEnergy ? 'Сессии' : 'Аналитика',
    icon: Activity, items: salesSessionItems, connected: salesSessionItems.length > 0 }
  const salesCommerceItems = isEnergy ? SALES_COMMERCE_MENU : (fuelSales ? FUEL_COMMERCE_MENU : [])
  const salesCommerce: WorkspaceSection = { mode: 'sales_commerce', label: 'Коммерция',
    icon: Wallet, items: salesCommerceItems, connected: salesCommerceItems.length > 0 }
  // «Товародвижение» — только у топливного профиля: топливо это товар, у ЭЗС товара нет.
  const salesGoodsItems = !isEnergy && fuelSales ? FUEL_GOODS_MENU : []
  const salesGoods: WorkspaceSection = { mode: 'sales_goods', label: 'Товародвижение',
    icon: Truck, items: salesGoodsItems, connected: salesGoodsItems.length > 0 }
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
  // Магазин разложен на пять разделов рельсы (решение МАГа 29.07.2026): «Торговля» —
  // деньги и спрос, «Склад» — остаток и движение, «Закрытие» — чем закрыт день и что
  // уехало в бухгалтерию, «Каталог» — карточка товара, «Маркировка» — что мы должны
  // государству. Раньше это были 25 пунктов одним списком с гармошкой заголовков.
  const storeSections: WorkspaceSection[] = STORE_SECTIONS.map((sec) => ({
    mode: sec.mode, label: sec.label, icon: sec.icon,
    items: storeOn ? storeMenu(sec.mode) : [], connected: storeOn,
  }))
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
  // Разделы продукта «Данные» — у ОБОИХ профилей: без них рабочее место открывается
  // панелью нормализации, которой нет в меню, а право `data:normalize` указывает в
  // пустоту. Под-меню у обеих панелей своё (каналы/разрезы) — items здесь не нужны.
  // Раньше топливный профиль их не получал: считалось, что те же панели живут
  // страницами Учёта (`/normalization`, `/reconciliation`). После разреза Учёта у
  // розницы нет — страницы осиротели, а «Данные» открывались без единого раздела.
  const normalize: WorkspaceSection = { mode: 'normalize', label: 'Нормализация', icon: Sparkles, items: [], connected: true }
  const reconcile: WorkspaceSection = { mode: 'reconcile', label: 'Сверка', icon: GitCompare, items: [], connected: true }

  // Порядок разделов: топливный профиль (ГИГ) — Продажи → Магазин → Управленческий →
  // Бухгалтерский (порядок МАГа 13.07.2026); energy (РусГидро, без магазина) — как было.
  const all = isEnergy
    ? [sales, salesSessions, salesCommerce, corporate, marketing,
       projects, projectsAnalytics, ops, opsEquipment, opsEconomy,
       storeSections[0], acc, exp, normalize, reconcile]
    : [sales, salesSessions, salesCommerce, salesGoods, ...storeSections, ops, acc, exp,
       normalize, reconcile]
  // Права на пункты продукта режутся ЗДЕСЬ, а не в меню: тот же массив читают панели
  // (`AccountingPanels`), и урезать его в одном месте — значит не показать закрытый
  // пункт ни в гармошке, ни в контенте. Гейт есть только у продуктов разреза: там код
  // пункта однозначен (`config/productAccess.ts`), в цельном Учёте коды разделов
  // пересекаются между видами учёта, и права остаются на уровне разделов, как были.
  if (!isCarvedProfile(company.profileId)) return all
  return all.map((s) => {
    const app = productForMode(s.mode)
    if (!app || !s.items.length) return s
    const items = s.items.filter((i) => productModuleAllowed(app, i.key, canModule, company.profileId))
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
  // Legacy-ключи Учёта (`management`, `store`, `accounting`) — только для профиля без
  // разреза. У разрезанного права выдаются ключами продуктов (`sales`, `shop`), и
  // старый гейт закрывал разделы любому, кому назначили роль: рельс раздел показывал,
  // а вторая панель приходила пустой. Права разделов здесь уже проверены
  // `productModuleAllowed` (см. useWorkspaceSections).
  const legacyGate = !isCarvedProfile(company.profileId)
  return useWorkspaceSections()
    .filter((s) => !legacyGate || modeAllowed(s.mode, companyModules))
    .filter((s) => (lockedModes ? lockedModes.includes(s.mode) : !carved.has(s.mode)))
}

/** Убрать дубли пунктов меню по ключу (на случай пересечения menuItems компонентов). */
function dedupeByKey(items: CentralMenuItem[]): CentralMenuItem[] {
  const seen = new Set<string>()
  return items.filter((i) => (seen.has(i.key) ? false : (seen.add(i.key), true)))
}
