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
  // ── Бухгалтерский · ГИГ — порядок: Дашборды → Поступления → Смены → подготовка к 1С → Маржинальность ──
  {
    id: 'acc_spec_reports', moduleId: 'accounting', kind: 'specialized',
    label: 'Дашборды',
    description: 'Аналитика по сменным отчётам: виды топлива, способы оплаты, поступления ТТН, движение наличных, графики.',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'reports', label: 'Дашборды' }],
  },
  {
    id: 'acc_spec_ttn', moduleId: 'accounting', kind: 'specialized',
    label: 'Поступления',
    description: 'Приёмка топлива (ТТН): журнал с KPI по видам топлива, подтверждение приёмки, корректировка перед 1С, сливы по станциям, себестоимость и закупочные партии (вкладки).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'ttn', label: 'Поступления' }],
    builderKinds: ['purchase_ttn'],
  },
  {
    id: 'acc_spec_shifts', moduleId: 'accounting', kind: 'specialized',
    label: 'Смены',
    description: 'Сменные отчёты STS: журнал + корректировка значений перед выгрузкой в 1С (правки хранятся в L2).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'shifts', label: 'Смены' }],
    builderKinds: ['shift_orp', 'cash_pko'],
  },
  // ── Бухгалтерский · СТАНДАРТНЫЕ (подготовка к 1С — общепринятое) ──
  {
    id: 'acc_std_recon1c', moduleId: 'accounting', kind: 'standard',
    label: 'Сверка с 1С',
    description: 'Готовность к загрузке и разница приложение↔1С: воронка выгрузки пакетов, сверка сумм с проведёнными документами 1С, расхождения.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'recon1c', label: 'Сверка с 1С' }],
  },
  {
    id: 'acc_spec_margin', moduleId: 'accounting', kind: 'specialized',
    label: 'Маржинальность',
    description: 'Маржа по видам товаров и видам оплат.',
    profiles: ['fuel'], status: 'demo', defaultOn: true,
    menuItems: [{ key: 'margin', label: 'Маржинальность' }],
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
