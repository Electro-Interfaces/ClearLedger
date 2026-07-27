/**
 * Пункты меню разделов рабочей области — чистые данные, без React и контекстов.
 *
 * Вынесены из `components/workspace/workspaceSections.ts`, чтобы карта прав
 * (`config/productAccess.ts`) могла строиться из тех же списков, которыми рисуется
 * меню: право на пункт и сам пункт обязаны совпадать по коду, иначе матрица доступа
 * показывает то, чего в интерфейсе нет. Хук разделов эти массивы реэкспортирует —
 * старые импорты из `workspaceSections` продолжают работать.
 */
import type { CentralMenuItem } from '@/components/workspace/CentralPanelLayout'

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

// Мониторинг сети ЭЗС — ядро «Эксплуатации» (не отключается каталогом модулей).
export const OPS_MONITOR_MENU: CentralMenuItem[] = [
  { key: 'ops_overview',     label: 'Обзор',          group: 'Мониторинг' },
  { key: 'ops_balance',      label: 'Баланс (факт)',  group: 'Мониторинг' },
  { key: 'ops_completeness', label: 'Полнота данных', group: 'Мониторинг' },
]

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
// работа → архив). НЕ путать с «Оборудованием» (склад железа).
// Раздел «Проекты» — жизненный цикл ЭЗС от участка до эксплуатации
// (docs/SITES_PROJECT_LIFECYCLE.md). Подбор площадки — первый этап проекта,
// поэтому банк ЗУ живёт здесь же, а не в «Управленческом».
export const SITES_MENU: CentralMenuItem[] = [
  { key: 'pr_portfolio',   label: 'Обзор портфеля',  group: 'Портфель' },
  { key: 'pr_project',     label: 'Проекты',         group: 'Портфель' },
  { key: 'sites_overview', label: 'Воронка подбора', group: 'Этап проекта · Подбор площадки' },
  { key: 'sites_list',     label: 'Банк площадок',   group: 'Этап проекта · Подбор площадки' },
  { key: 'sites_priority', label: 'Приоритеты',      group: 'Этап проекта · Подбор площадки' },
  { key: 'sites_map',      label: 'Карта',           group: 'Этап проекта · Подбор площадки' },
  { key: 'pr_tp',          label: 'Присоединение',   group: 'Этап проекта · Реализация' },
  { key: 'pr_equipment',   label: 'Оборудование',    group: 'Этап проекта · Реализация' },
  { key: 'pr_accounting',  label: 'Ждёт учёта',      group: 'Связь с учётом' },
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
  { key: 'cs_abcxyz',     label: 'ABC-XYZ станций', group: 'Сеть' },
  { key: 'cs_sessions',    label: 'Сессии',        group: 'Аналитика сессий' },
  { key: 'cs_reliability', label: 'Надёжность',    group: 'Аналитика сессий' },
  { key: 'cs_list',        label: 'Реестр сессий', group: 'Аналитика сессий' },
  { key: 'cs_clients',    label: 'Тарифы',        group: 'Коммерция' },
  { key: 'cs_corporate',  label: 'Корпоратив',    group: 'Коммерция' },
  { key: 'cs_retail',     label: 'Частные лица',  group: 'Коммерция' },
]
export const CHARGE_SESSIONS_KEYS = CHARGE_SESSIONS_MENU.map((m) => m.key)

// Продукты, выделенные из «Продаж» (решение МАГа 27.07.2026): работа с юрлицами и
// маркетинг — отдельные рабочие места со своими людьми, а не вкладки коммерции.
export const CORP_MENU: CentralMenuItem[] = [
  { key: 'cs_clients',    label: 'Тарифные планы', group: 'Коммерция' },
  { key: 'cs_corporate',  label: 'Юрлица',         group: 'Коммерция' },
  { key: 'cs_retail',     label: 'Частные лица',   group: 'Коммерция' },
]
export const CORP_KEYS = CORP_MENU.map((m) => m.key)

export const MARKETING_MENU: CentralMenuItem[] = [
  { key: 'cs_abcxyz',  label: 'ABC-XYZ станций', group: 'Сегментация' },
  { key: 'cs_trend',   label: 'Динамика 2024+',  group: 'Сегментация' },
]
export const MARKETING_KEYS = MARKETING_MENU.map((m) => m.key)
