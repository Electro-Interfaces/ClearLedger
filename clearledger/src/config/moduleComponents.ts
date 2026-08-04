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
 * ─────────────────────────────────────────────────────────────────────────────
 * БУХГАЛТЕРИЯ РАЗЛОЖЕНА ПО ПОТОКАМ (решение МАГа 04.08.2026)
 *
 * Раньше это были десять пунктов одним уровнем, где рядом стояли вещи из разных
 * миров: журнал топливных смен, сводка ЦБ и эмиттер JSON-пакета. Потоков на самом
 * деле три, и живут они по разным законам:
 *
 *   НЕФТЕПРОДУКТЫ — источник STS, документы в БП создаёт САМО расширение
 *                   (TL_ApiКлиент тянет смены и ТТН напрямую), Ledger здесь
 *                   не продюсер, а контролёр: что доехало, что разошлось;
 *   МАГАЗИН       — источник ЦБ/edge, пакет «смена→БП» строит Ledger
 *                   (services/bp_export.py), приёмник TL_СопуткаСервис;
 *   ОБЩЕПИТ       — тот же пакет, что у магазина, но своя учётная механика:
 *                   ТТК, комплектация блюд, фудкост.
 *
 * Раздел = поток (рельса), группа пункта = стадия (вторая панель): РАБОТА — что
 * набралось за период, ЗАКРЫТИЕ — что уехало в БП и сошлось ли. Сквозное
 * (период, сверка, первичка, итоги) поднято в собственные разделы.
 *
 * `accounting` остаётся кодом ПЕРВОГО раздела («Нефтепродукты»): по нему выданы
 * права, подписан модуль и идут старые ссылки `?mode=accounting`.
 */
import type { ComponentType } from 'react'
import {
  CalendarCheck, Fuel, ShoppingCart, UtensilsCrossed, GitCompare, FileText, BarChart3,
} from 'lucide-react'
import type { CentralMenuItem } from '@/components/workspace/CentralPanelLayout'
import type { ModuleProfile, ModuleStatus } from '@/config/workspaceModules'

export type ComponentKind = 'standard' | 'specialized'

/** Разделы «Бухгалтерии» в левой рельсе; пункты каждого — во второй панели. */
export type AccountingSection =
  | 'acc_period' | 'accounting' | 'acc_store' | 'acc_food'
  | 'acc_recon' | 'acc_docs' | 'acc_results'

export const ACCOUNTING_SECTIONS: {
  mode: AccountingSection; label: string; icon: ComponentType<{ className?: string }>
}[] = [
  { mode: 'acc_period',  label: 'Период',        icon: CalendarCheck },
  { mode: 'accounting',  label: 'Нефтепродукты', icon: Fuel },
  { mode: 'acc_store',   label: 'Магазин',       icon: ShoppingCart },
  { mode: 'acc_food',    label: 'Общепит',       icon: UtensilsCrossed },
  { mode: 'acc_recon',   label: 'Сверка',        icon: GitCompare },
  { mode: 'acc_docs',    label: 'Документы',     icon: FileText },
  { mode: 'acc_results', label: 'Итоги',         icon: BarChart3 },
]

export const ACCOUNTING_MODES: string[] = ACCOUNTING_SECTIONS.map((s) => s.mode)

export interface ModuleComponent {
  id: string                      // стабильный ключ, напр. 'acc_spec_shifts'
  moduleId: string                // владелец-модуль ('accounting')
  label: string
  description: string
  profiles: ModuleProfile[]       // применимость по профилю компании
  kind: ComponentKind             // 'standard' = вкл по умолчанию; 'specialized' = подключаемый
  /** Раздел рельсы, которому принадлежат пункты компонента. Пусто = первый раздел. */
  section?: AccountingSection
  menuItems?: CentralMenuItem[]   // под-разделы, добавляемые в меню модуля (порядок = порядок реестра)
  builderKinds?: string[]         // ExportPacket kinds, разблокируемые компонентом (задел, пока не гейтит)
  status: ModuleStatus            // 'active' | 'demo' | 'planned'
  defaultOn?: boolean             // переопределение дефолта (иначе: standard→on, specialized→off)
}

export const MODULE_COMPONENTS: ModuleComponent[] = [
  // ── ПЕРИОД · где стоит закрытие по всем трём потокам сразу ──────────────────
  {
    id: 'acc_period_status', moduleId: 'accounting', kind: 'standard',
    section: 'acc_period',
    label: 'Статус закрытия периода',
    description: 'Один экран на три потока: сколько смен набралось, сколько уехало в БП, что мешает закрыть месяц. Отвечает на вопрос «где я сейчас», с которого начинается рабочий день бухгалтера.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'period_status', label: 'Статус закрытия' }],
  },

  // ── ПОТОК 1 · НЕФТЕПРОДУКТЫ ─────────────────────────────────────────────────
  // Источник STS → терминалы; документы в БП создаёт расширение TradeLedger.cfe
  // САМО, обращаясь к STS напрямую (TL_ApiКлиент). Ledger идёт параллельно: копит
  // те же факты, даёт править их до загрузки и показывает, что реально доехало.
  {
    id: 'acc_spec_shifts', moduleId: 'accounting', kind: 'specialized',
    section: 'accounting',
    label: 'Смены (нефтепродукты)',
    description: 'Сменные отчёты STS: журнал + корректировка значений перед выгрузкой в 1С (правки хранятся в L2).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'shifts', label: 'Смены', group: 'Работа' }],
    builderKinds: ['shift_orp', 'cash_pko'],
  },
  {
    id: 'acc_spec_ttn', moduleId: 'accounting', kind: 'specialized',
    section: 'accounting',
    label: 'Поступления (топливо)',
    description: 'Приёмка топлива (ТТН): журнал с KPI по видам топлива, подтверждение приёмки, корректировка перед 1С, сливы по станциям, себестоимость и закупочные партии (вкладки).',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'ttn', label: 'Поступления (ТТН)', group: 'Работа' }],
    builderKinds: ['purchase_ttn'],
  },
  {
    id: 'acc_spec_cash', moduleId: 'accounting', kind: 'specialized',
    section: 'accounting',
    label: 'Касса и инкассация',
    description: 'Журнал инкассаций из money-секции смен (сумма + накоплено с прошлой — основание для РКО в 1С), выдачи наличных, остатки касс по АЗС и дни без инкассации.',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'cash', label: 'Касса и инкассация', group: 'Работа' }],
  },
  {
    id: 'acc_spec_reports', moduleId: 'accounting', kind: 'specialized',
    section: 'accounting',
    label: 'Дашборды (топливо)',
    description: 'Аналитика по сменным отчётам: виды топлива, способы оплаты, поступления ТТН, движение наличных, графики.',
    profiles: ['fuel'], status: 'active', defaultOn: true,
    menuItems: [{ key: 'reports', label: 'Дашборды', group: 'Работа' }],
  },
  {
    id: 'acc_std_recon1c', moduleId: 'accounting', kind: 'standard',
    section: 'accounting',
    label: 'Контроль загрузки в 1С (топливо)',
    description: 'Что бухгалтер уже загрузил формой TL_Загрузка, а что нет: смены и ТТН нашего контура против документов, появившихся в БП. Не выгрузка — контроль: топливо расширение тянет из STS само.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'recon1c', label: 'Контроль загрузки в 1С', group: 'Закрытие' }],
  },

  // ── ПОТОК 2 · МАГАЗИН (сопутка) ─────────────────────────────────────────────
  // Источник ЦБ 1С ЭЛСИ.АЗК / edge-агент станции → bp_export → TL_СопуткаСервис.
  // Здесь Ledger — продюсер пакета, и «Закрытие» это реальное действие.
  {
    id: 'acc_std_cb_load', moduleId: 'accounting', kind: 'standard',
    section: 'acc_store',
    label: 'Приём данных (магазин)',
    description: 'Что и за какой период загружено из ЦБ ЭЛСИ.АЗК и с локальных баз станций: смены, ОРП, ПТУ, производство, ТТК. В сами базы ничего не пишем.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'cb_load', label: 'Приём данных', group: 'Работа' }],
  },
  {
    id: 'acc_std_cb_shifts', moduleId: 'accounting', kind: 'standard',
    section: 'acc_store',
    label: 'Смены сопутки',
    description: 'Сменные отчёты сопутки как составной документ: выручка, позиции, возвраты, приходы и движения дня. Детальная аналитика ассортимента — в «Магазине».',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'cb_shifts', label: 'Смены сопутки', group: 'Работа' }],
  },
  {
    id: 'acc_std_export', moduleId: 'accounting', kind: 'standard',
    section: 'acc_store',
    label: 'Пакет в БП (магазин и общепит)',
    description: 'Ledger — продюсер JSON-пакетов «смена→БП ГИГ» (замена TL_ЭкспортБП): превью состава документов и НСИ, хеш, скачать JSON или выгрузить в каталог обмена, откуда их забирает TL_СопуткаСервис. Приёмник TradeLedger.cfe не меняется.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'export', label: 'Пакет в БП', group: 'Закрытие' }],
    builderKinds: ['recipe', 'purchase', 'retail_sale_sidegoods', 'production_release', 'inventory', 'gain', 'writeoff', 'transfer'],
  },
  {
    id: 'acc_std_cb_recon', moduleId: 'accounting', kind: 'standard',
    section: 'acc_store',
    label: 'Готовность пакета',
    description: 'Проверки перед загрузкой: балансы документов, полнота НСИ, ставки НДС, хеш. Пока это самосогласованность собственного пакета; сверка с проведёнными документами БП живёт в разделе «Сверка».',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'cb_recon', label: 'Готовность пакета', group: 'Закрытие' }],
  },

  // ── ПОТОК 3 · ОБЩЕПИТ ───────────────────────────────────────────────────────
  // Едет в БП ТЕМ ЖЕ пакетом, что и магазин: одна смена — один файл. Поэтому
  // своей кнопки выгрузки здесь нет и быть не должно (две кнопки на один файл —
  // прямой путь к двойной загрузке). «Закрытие» показывает СВОЙ РАЗРЕЗ пакета:
  // блюда, техкарты, комплектации.
  {
    id: 'acc_food_menu', moduleId: 'accounting', kind: 'standard',
    section: 'acc_food',
    label: 'Блюда и техкарты',
    description: 'Что кухня продала за период и из чего это сделано: фудкост, вклад-маржа, состав порции по ТТК. Себестоимость блюда считается разворотом техкарты.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'food_menu', label: 'Блюда и техкарты', group: 'Работа' }],
  },
  {
    id: 'acc_food_release', moduleId: 'accounting', kind: 'standard',
    section: 'acc_food',
    label: 'Комплектация в пакете',
    description: 'Разрез общепита в пакете смены: какие блюда проданы, покрыты ли они техкартами, какие комплектации соберёт приёмник. Блюдо продаётся строкой ОРП, а себестоимость собирает КомплектацияНоменклатуры (вариант A поверх модели B).',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'food_release', label: 'Комплектация в пакете', group: 'Закрытие' }],
  },

  // ── СКВОЗНОЕ · СВЕРКА ───────────────────────────────────────────────────────
  {
    id: 'acc_recon_docs', moduleId: 'accounting', kind: 'standard',
    section: 'acc_recon',
    label: 'Сверка Ledger ↔ 1С',
    description: 'Наши факты против проведённых документов БП: что сопоставилось, что не доехало, где расходятся суммы. Данные приходят обратным потоком из 1С (COM/OData).',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'recon_docs', label: 'Ledger ↔ 1С' }],
  },
  {
    id: 'acc_recon_diff', moduleId: 'accounting', kind: 'standard',
    section: 'acc_recon',
    label: 'Расхождения',
    description: 'Разбор несовпавших пар: сумма, дата, контрагент, номер. Сопоставление вручную и снятие ложных пар.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'recon_diff', label: 'Расхождения' }],
  },

  // ── СКВОЗНОЕ · ДОКУМЕНТЫ ────────────────────────────────────────────────────
  {
    id: 'acc_docs_1c', moduleId: 'accounting', kind: 'standard',
    section: 'acc_docs',
    label: 'Документы 1С',
    description: 'Первичка, поднятая из БП: ПТУ, ОРП, счета-фактуры, кассовые ордера — с проводками по требованию. То, на чём строится сверка и итоги.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'docs_1c', label: 'Документы 1С' }],
  },
  {
    id: 'acc_docs_parties', moduleId: 'accounting', kind: 'standard',
    section: 'acc_docs',
    label: 'Поставщики и договоры',
    description: 'Контрагенты и договоры, на которые ссылается первичка. ПТУ от поставщика топлива расширение принципиально не создаёт — его бухгалтер вводит руками.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'docs_parties', label: 'Поставщики и договоры' }],
  },

  // ── СКВОЗНОЕ · ИТОГИ (видно только после проводок) ──────────────────────────
  {
    id: 'acc_res_trend', moduleId: 'accounting', kind: 'standard',
    section: 'acc_results',
    label: 'Динамика по месяцам',
    description: 'Помесячный ряд по трём потокам: смены, выручка, документы 1С и непроведённое. Закрытие смотрят по одному месяцу, но понимают его в сравнении — провал виден без арифметики.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'res_trend', label: 'Динамика по месяцам' }],
  },
  {
    id: 'acc_res_margin', moduleId: 'accounting', kind: 'standard',
    section: 'acc_results',
    label: 'Маржа',
    description: 'Маржа трёх потоков рядом, потом две маржи топлива: управленческая по FIFO-партиям (наш расчёт, виден сразу) и бухгалтерская из проводок 90.01/90.02 (появляется после проведения в БП). Расхождение между ними — предмет разговора.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'res_margin', label: 'Маржа' }],
  },
  {
    id: 'acc_res_tax', moduleId: 'accounting', kind: 'standard',
    section: 'acc_results',
    label: 'НДС и прибыль',
    description: 'НДС к уплате и финансовый результат периода по проводкам БП.',
    profiles: ['fuel'], status: 'active',
    menuItems: [{ key: 'res_tax', label: 'НДС и прибыль' }],
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

/** Раздел компонента; пусто = первый раздел («Нефтепродукты», исторический код). */
export const componentSection = (c: ModuleComponent): AccountingSection => c.section ?? 'accounting'

/** Раздел, которому принадлежит пункт меню, — для старых ссылок `?sub=`. */
export function accountingModeForKey(key: string): AccountingSection {
  const owner = MODULE_COMPONENTS.find(
    (c) => c.moduleId === 'accounting' && (c.menuItems ?? []).some((i) => i.key === key))
  return owner ? componentSection(owner) : 'accounting'
}

/** Все пункты «Бухгалтерии» разом — для карты прав и подписей закладок. */
export const ACCOUNTING_MENU: CentralMenuItem[] = MODULE_COMPONENTS
  .filter((c) => c.moduleId === 'accounting')
  .flatMap((c) => c.menuItems ?? [])

export const ACCOUNTING_KEYS = ACCOUNTING_MENU.map((i) => i.key)

/** Дефолт включённости: standard → on; specialized → off (переопределяется `defaultOn`). */
export function defaultComponentEnabled(cmp: ModuleComponent): boolean {
  return cmp.defaultOn ?? (cmp.kind === 'standard')
}

// Ключ пункта — адрес экрана (`?sub=`), маршрут панели и код права разом. Два
// компонента с одним ключом означают, что один из пунктов молча исчезнет из меню
// (его съест dedupeByKey), а право на него будет вести в чужой раздел. Компилятор
// такого не ловит, поэтому проверяем при загрузке модуля в разработке.
if (import.meta.env?.DEV) {
  const seen = new Set<string>()
  for (const key of ACCOUNTING_KEYS) {
    if (seen.has(key)) {
      throw new Error(`moduleComponents: ключ пункта «${key}» встречается дважды — ` +
        'пункт исчезнет из меню, а право уведёт в чужой раздел')
    }
    seen.add(key)
  }
}
