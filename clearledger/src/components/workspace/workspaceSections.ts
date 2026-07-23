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
import { BarChart3, Gauge, BookOpen, FileOutput, ShoppingCart, HardHat } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import type { CoreMode } from '@/contexts/WorkspaceContext'
import type { CentralMenuItem } from './CentralPanelLayout'
import { getWorkspaceModule } from '@/config/workspaceModules'
import { useModuleConnections, isModuleConnected, isComponentEnabled } from '@/services/moduleConnectionService'
import { getModuleComponentDefs } from '@/config/moduleComponents'
import { STORE_MENU } from '@/config/storeCatalog'

/* ── Наборы под-разделов ── */

// Управленческий контур сети АЗС (нефтепродукты). Сгруппировано по смыслу
// (заголовки групп рисует сайдбар по полю group, по образцу ЭЗС):
//   СЕТЬ — состояние сети (обзор + карта);
//   АНАЛИТИКА — реализация (внутр. табы: разрезы/время/динамика/сравнение),
//     построчный реестр, каналы оплаты, онлайн-заказы;
//   КОММЕРЦИЯ — цена (тарифы) и клиентские направления (корпоратив/розница);
//   ТОВАРОДВИЖЕНИЕ — маржа, поступления ТТН, контроль баланса.
export const MGMT_MENU: CentralMenuItem[] = [
  { key: 'overview',       label: 'Обзор',            group: 'Сеть' },
  { key: 'map',            label: 'Карта',            group: 'Сеть' },
  { key: 'fills',          label: 'Реализация',       group: 'Аналитика' },
  { key: 'transactions',   label: 'Реестр операций',  group: 'Аналитика' },
  { key: 'channels',       label: 'Каналы продаж',    group: 'Аналитика' },
  { key: 'online-orders',  label: 'Онлайн-заказы',    group: 'Аналитика' },
  { key: 'fuel-tariffs',   label: 'Тарифы',           group: 'Коммерция' },
  { key: 'fuel-corporate', label: 'Корпоратив',       group: 'Коммерция' },
  { key: 'fuel-retail',    label: 'Частные лица',     group: 'Коммерция' },
  { key: 'margin',         label: 'Маржа и цены',     group: 'Товародвижение' },
  { key: 'purchases',      label: 'Поступления',      group: 'Товародвижение' },
  { key: 'tanks',          label: 'Контроль баланса', group: 'Товародвижение' },
]
export const MGMT_MENU_KEYS = MGMT_MENU.map((m) => m.key)

// Энергомодули раздела «Управленческий» (демо-витрины, подключаются через каталог).
export const ENERGY_MGMT: CentralMenuItem[] = [
  { key: 'procurement',  label: 'Энергозакупка' },
  { key: 'rent',         label: 'Аренда' },
]
export const ENERGY_MGMT_KEYS = ENERGY_MGMT.map((m) => m.key)

// Складской учёт оборудования ЭЗС (energy): станции-железки на складах/в ремонте,
// движения жизненного цикла, ЗИП. Ядро раздела «Управленческий», группа «Оборудование».
export const EQUIPMENT_MENU: CentralMenuItem[] = [
  { key: 'eq_fleet',      label: 'Парк оборудования',  group: 'Оборудование' },
  { key: 'eq_warehouses', label: 'Склады и остатки',   group: 'Оборудование' },
  { key: 'eq_supplies',   label: 'Поставки и возвраты', group: 'Оборудование' },
  { key: 'eq_movements',  label: 'Движения',           group: 'Оборудование' },
  { key: 'eq_spares',     label: 'ЗИП и запчасти',     group: 'Оборудование' },
]
export const EQUIPMENT_KEYS = EQUIPMENT_MENU.map((m) => m.key)

// Банк ЗУ — площадки (земельные участки) под установку ЭЗС: девелоперский
// пайплайн развития сети (МЕСТА, где сеть строится, на стадиях проработка →
// работа → архив). НЕ путать с «Оборудованием» (склад железа). Ядро раздела
// «Управленческий», группа «Площадки».
// Раздел «Проекты» — жизненный цикл ЭЗС от участка до эксплуатации
// (docs/SITES_PROJECT_LIFECYCLE.md). Подбор площадки — первый этап проекта,
// поэтому банк ЗУ живёт здесь же, а не в «Управленческом».
export const SITES_MENU: CentralMenuItem[] = [
  { key: 'pr_portfolio',   label: 'Обзор портфеля',  group: 'Портфель' },
  { key: 'pr_projects',    label: 'Проекты',         group: 'Портфель' },
  { key: 'sites_overview', label: 'Воронка подбора', group: 'Подбор площадок' },
  { key: 'sites_list',     label: 'Банк площадок',   group: 'Подбор площадок' },
  { key: 'sites_priority', label: 'Приоритеты',      group: 'Подбор площадок' },
  { key: 'sites_map',      label: 'Карта',           group: 'Подбор площадок' },
  { key: 'pr_tp',          label: 'Присоединение',   group: 'Реализация' },
  { key: 'pr_equipment',   label: 'Оборудование',    group: 'Реализация' },
  { key: 'pr_accounting',  label: 'Ждёт учёта',      group: 'Реализация' },
]
export const SITES_KEYS = SITES_MENU.map((m) => m.key)

// Анализ зарядных сессий ЭЗС (реальные данные, для energy-профиля).
// Сгруппировано по смыслу (заголовки групп рисует сайдбар по полю group):
//   СЕТЬ — состояние сети (обзор + карта);
//   АНАЛИТИКА СЕССИЙ — агрегаты (Сессии: внутр. табы) + построчный реестр;
//   КОММЕРЦИЯ — цена (тарифы) и клиентские направления (ЮЛ/ФЛ).
export const CHARGE_SESSIONS_MENU: CentralMenuItem[] = [
  { key: 'cs_dashboard',  label: 'Обзор',         group: 'Сеть' },
  { key: 'cs_map',        label: 'Карта',         group: 'Сеть' },
  { key: 'cs_trend',      label: 'Динамика 2024+', group: 'Сеть' },
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
  // «Управленческий» (mode=operations) — энергозакупка/аренда (реальные реестры).
  const mgmtItems: CentralMenuItem[] = [
    ...(on('mgmt_pnl') ? MGMT_MENU : []),
    ...(isEnergy ? CHARGE_SESSIONS_MENU : []),
  ]
  // «Управленческий» у ГИГ (fuel) = хозяйственные отношения компании (договоры/аренда),
  // не баланс (концепт МАГа 13.07.2026): контроль топлива уже живёт в «Продажах»,
  // «Баланс АЗС» из этого раздела убран. У energy — энергозакупка/аренда/баланс ЭЗС.
  // Меню «Управленческого» (energy) — три группы:
  //   МОНИТОРИНГ — ядро раздела (не отключаемое): светофор проблем + энергобаланс + полнота;
  //   ОБОРУДОВАНИЕ — складской контур железа (тоже ядро);
  //   ХОЗЯЙСТВО — подключаемые модули денежного контура площадок (энергозакупка,
  //   аренда) + витрина баланса ЭЗС.
  const energyOps = ENERGY_MGMT.filter((m) => on(m.key))
    .map((m) => ({ ...m, group: 'Хозяйство' }))
  const opsItems: CentralMenuItem[] = [
    ...(isEnergy
      ? [
          { key: 'ops_overview', label: 'Обзор', group: 'Мониторинг' },
          { key: 'ops_balance', label: 'Баланс (факт)', group: 'Мониторинг' },
          { key: 'ops_completeness', label: 'Полнота данных', group: 'Мониторинг' },
          ...EQUIPMENT_MENU,
        ]
      : []),
    ...energyOps,
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

  const sales: WorkspaceSection = { mode: 'management', label: 'Продажи',        icon: BarChart3,    items: mgmtItems, connected: mgmtItems.length > 0 }
  // «Проекты» — стройка сети: от подбора участка до ввода станции в эксплуатацию.
  // Только у energy: у топливного профиля своего девелоперского контура нет.
  const projects: WorkspaceSection = { mode: 'projects', label: 'Проекты', icon: HardHat,
    items: isEnergy ? SITES_MENU : [], connected: isEnergy }
  const ops: WorkspaceSection   = { mode: 'operations', label: 'Управленческий', icon: Gauge,        items: opsItems, connected: opsItems.length > 0 }
  const store: WorkspaceSection = { mode: 'store',      label: 'Магазин',        icon: ShoppingCart, items: storeOn ? STORE_MENU : [], connected: storeOn }
  const acc: WorkspaceSection   = { mode: 'accounting', label: 'Бухгалтерский',  icon: BookOpen,     items: accItems, connected: accOn }
  const exp: WorkspaceSection   = { mode: 'export',     label: 'Выгрузка',       icon: FileOutput,   items: [], connected: true }

  // Порядок разделов: топливный профиль (ГИГ) — Продажи → Магазин → Управленческий →
  // Бухгалтерский (порядок МАГа 13.07.2026); energy (РусГидро, без магазина) — как было.
  return isEnergy
    ? [sales, projects, ops, store, acc, exp]
    : [sales, store, ops, acc, exp]
}

/** Убрать дубли пунктов меню по ключу (на случай пересечения menuItems компонентов). */
function dedupeByKey(items: CentralMenuItem[]): CentralMenuItem[] {
  const seen = new Set<string>()
  return items.filter((i) => (seen.has(i.key) ? false : (seen.add(i.key), true)))
}
