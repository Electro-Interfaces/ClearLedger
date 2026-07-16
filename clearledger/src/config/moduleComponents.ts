/**
 * Каталог КОМПОНЕНТОВ для сборки модулей рабочего стола.
 *
 * Модуль (`WorkspaceModuleDef`) — единица подключения к компании; компонент —
 * второй уровень сборки ВНУТРИ подключённого модуля. Компонент вносит под-разделы
 * меню (`menuItems`) и, в перспективе, разблокирует построители выгрузки
 * (`builderKinds`). Два вида: СТАНДАРТНЫЕ (общепринятое ядро, включены по умолчанию)
 * и СПЕЦИАЛИЗИРОВАННЫЕ (подключаются под конкретную компанию).
 *
 * Библиотека компонентов видна в «Каталоги → Компоненты модулей»; сборка модуля
 * под компанию (какие компоненты включены) — в настройке модуля, состояние
 * per-company в `services/moduleConnectionService.ts` (поле `components`).
 *
 * Бухгалтерский модуль (`accounting`) наполнен по идеологии TradeLedger —
 * поток L1 RAW → L2 CLEAN → L3 EXPORT → L4 1C_REF:
 *   стандартные:  Нормализация → Документы 1С → Выгрузка → Сверка с 1С → Периоды
 *   специализир.: Журнал смен · Сопряжение смен · Слив ТТН · Маржинальность · Отчёты
 */
import type { CentralMenuItem } from '@/components/workspace/CentralPanelLayout'
import type { ModuleProfile, ModuleStatus } from '@/config/workspaceModules'

export type ComponentKind = 'standard' | 'specialized'

export interface ModuleComponent {
  id: string                      // стабильный ключ, напр. 'acc_spec_shifts'
  moduleId: string                // владелец-модуль ('accounting')
  label: string
  description: string
  profiles: ModuleProfile[]       // применимость по профилю компании
  kind: ComponentKind             // 'standard' = вкл по умолчанию; 'specialized' = подключаемый
  menuItems?: CentralMenuItem[]   // под-разделы, добавляемые в меню модуля (порядок = порядок реестра)
  builderKinds?: string[]         // ExportPacket kinds, разблокируемые компонентом (задел, пока не гейтит)
  status: ModuleStatus            // 'active' | 'demo' | 'planned'
  defaultOn?: boolean             // переопределение дефолта (иначе: standard→on, specialized→off)
}

export const MODULE_COMPONENTS: ModuleComponent[] = [
  // ── Бухгалтерский = ДВА ПОТОКА сменных отчётов → БП (разные источник и выгрузка) ──
  // ПОТОК 1 · НЕФТЕПРОДУКТЫ (источник STS/терминалы → export-packets → 1С)
  {
    id: 'acc_spec_shifts', moduleId: 'accounting', kind: 'specialized',
    label: 'Смены (нефтепродукты)',
    description: 'Сменные отчёты STS: журнал + корректировка значений перед выгрузкой в 1С (правки хранятся в L2).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'shifts', label: 'Смены', group: 'Нефтепродукты' }],
    builderKinds: ['shift_orp', 'cash_pko'],
  },
  {
    id: 'acc_spec_ttn', moduleId: 'accounting', kind: 'specialized',
    label: 'Поступления (топливо)',
    description: 'Приёмка топлива (ТТН): журнал с KPI по видам топлива, подтверждение приёмки, корректировка перед 1С, сливы по станциям, себестоимость и закупочные партии (вкладки).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'ttn', label: 'Поступления', group: 'Нефтепродукты' }],
    builderKinds: ['purchase_ttn'],
  },
  {
    id: 'acc_spec_margin', moduleId: 'accounting', kind: 'specialized',
    label: 'Маржинальность (топливо)',
    description: 'Маржа по видам топлива и видам оплат (FIFO по партиям + бухгалтерская COGS).',
    profiles: ['fuel'], status: 'demo', defaultOn: true,
    menuItems: [{ key: 'margin', label: 'Маржинальность', group: 'Нефтепродукты' }],
  },
  {
    id: 'acc_spec_reports', moduleId: 'accounting', kind: 'specialized',
    label: 'Дашборды (топливо)',
    description: 'Аналитика по сменным отчётам: виды топлива, способы оплаты, поступления ТТН, движение наличных, графики.',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'reports', label: 'Дашборды', group: 'Нефтепродукты' }],
  },
  {
    id: 'acc_spec_cash', moduleId: 'accounting', kind: 'specialized',
    label: 'Касса и инкассация',
    description: 'Журнал инкассаций из money-секции смен (сумма + накоплено с прошлой — основание для РКО в 1С), выдачи наличных, остатки касс по АЗС и дни без инкассации.',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'cash', label: 'Касса и инкассация', group: 'Нефтепродукты' }],
  },
  {
    id: 'acc_std_recon1c', moduleId: 'accounting', kind: 'standard',
    label: 'Сверка с 1С (топливо)',
    description: 'Готовность к загрузке и разница приложение↔1С: воронка выгрузки пакетов, сверка сумм с проведёнными документами 1С, расхождения.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'recon1c', label: 'Выгрузка/Сверка с 1С', group: 'Нефтепродукты' }],
  },
  // ПОТОК 2 · СОПУТКА/ОБЩЕПИТ (источник ЦБ 1С ЭЛСИ.АЗК → bp_export → TL_СопуткаСервис)
  // Бухгалтерский срез: Загрузка → Смены → Выгрузка → Сверка. Детальная операционка/
  // аналитика (ассортимент, цены, НСИ, движение) — в разделе «Магазин».
  {
    id: 'acc_std_cb_load', moduleId: 'accounting', kind: 'standard',
    label: 'Загрузка из ЦБ (сопутка)',
    description: 'Приём сменных данных сопутки/общепита из ЦБ 1С ЭЛСИ.АЗК (COM-коннектор): смены, ОРП, ПТУ, производство, ТТК. Сводка «что загружено за период».',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'cb_load', label: 'Загрузка из ЦБ', group: 'Сопутка' }],
  },
  {
    id: 'acc_std_cb_shifts', moduleId: 'accounting', kind: 'standard',
    label: 'Смены (сопутка)',
    description: 'Сменные отчёты сопутки/общепита как составной документ. Детальная аналитика — в разделе «Магазин».',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'cb_shifts', label: 'Смены', group: 'Сопутка' }],
  },
  {
    id: 'acc_std_export', moduleId: 'accounting', kind: 'standard',
    label: 'Выгрузка в БП (сопутка)',
    description: 'Ledger — продюсер JSON-пакетов «смена→БП ГИГ» (замена TL_ЭкспортБП): превью состава документов/НСИ, хеш, скачать JSON или выгрузить в каталог, откуда грузит TL_СопуткаСервис. Приёмник TradeLedger.cfe не меняется.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'export', label: 'Выгрузка в БП', group: 'Сопутка' }],
    builderKinds: ['recipe', 'purchase', 'retail_sale_sidegoods', 'production_release', 'inventory', 'gain', 'writeoff', 'transfer'],
  },
  {
    id: 'acc_std_cb_recon', moduleId: 'accounting', kind: 'standard',
    label: 'Сверка сопутки',
    description: 'Сверка пакета Ledger с ЦБ-контуром / документами БП (готовность, расхождения). Байт-сверка — инструмент bp_compare.',
    profiles: ['fuel'], status: 'planned',
    menuItems: [{ key: 'cb_recon', label: 'Сверка', group: 'Сопутка' }],
  },
]

export function getComponent(id: string): ModuleComponent | undefined {
  return MODULE_COMPONENTS.find((c) => c.id === id)
}

/** Компоненты модуля, применимые к профилю компании (для меню и для UI сборки). */
export function getModuleComponentDefs(moduleId: string, profileId: string): ModuleComponent[] {
  return MODULE_COMPONENTS.filter(
    (c) => c.moduleId === moduleId &&
      (c.profiles.includes('any') || c.profiles.includes(profileId as ModuleProfile)),
  )
}

/** Дефолт включённости: standard → on; specialized → off (переопределяется `defaultOn`). */
export function defaultComponentEnabled(cmp: ModuleComponent): boolean {
  return cmp.defaultOn ?? (cmp.kind === 'standard')
}
