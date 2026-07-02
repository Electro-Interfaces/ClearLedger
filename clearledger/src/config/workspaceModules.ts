/**
 * Каталог ПОДКЛЮЧАЕМЫХ МОДУЛЕЙ рабочего стола. Библиотека того, что можно подключить
 * к разделам рабочего стола (Управленческий/Финансовый/…) и настроить под организацию.
 * Состояние подключения+параметров per-company — в services/moduleConnectionService.ts.
 * Связано с config/balanceModules.ts (баланс = частный модуль, id совпадают).
 */
export type ModuleProfile = 'fuel' | 'energy' | 'any'
export type ModuleStatus = 'active' | 'demo' | 'planned'

export interface ModuleParam {
  key: string                     // стабильный ключ (по нему модуль читает значение)
  label: string                   // подпись в форме настройки
  hint?: string                   // подсказка/плейсхолдер
}

export interface WorkspaceModuleDef {
  id: string
  label: string
  description: string
  section: string                 // раздел рабочего стола, куда подключается
  profiles: ModuleProfile[]       // применимость по профилю компании
  status: ModuleStatus
  params: ModuleParam[]           // параметры, настраиваемые под организацию
}

export const WORKSPACE_MODULES: WorkspaceModuleDef[] = [
  // ── Управленческий ──
  {
    id: 'balance_ezs', label: 'Баланс ЭЗС', section: 'Управленческий',
    description: 'Поступление − Полезный отпуск = Потери по ЭЗС: технолог./коммерч. потери, сверки ПУ↔ПУ и ПУ↔ПК, договоры+взаиморасчёты, обращения, паспорт.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'norm', label: 'Норматив потерь, %', hint: 'пусто = расчёт от физики (тип/мощность)' },
      { key: 'unit', label: 'Единица ресурса', hint: 'кВт·ч' },
      { key: 'categories', label: 'Категории отпуска', hint: 'ЮЛ, ФЛ' },
      { key: 'etalon', label: 'Источник эталона (закрытый период)', hint: '1С / billing РусГидро' },
    ],
  },
  {
    id: 'balance_azs', label: 'Баланс АЗС', section: 'Управленческий',
    description: 'Приход (ТТН) − Реализация = Потери по АЗС: естественная убыль, температурная коррекция по плотности, недостача/излишек ТМЦ.',
    profiles: ['fuel'], status: 'planned',
    params: [
      { key: 'norm', label: 'Норма естественной убыли, %' },
      { key: 'density', label: 'Плотность/температура' },
      { key: 'unit', label: 'Единица ресурса', hint: 'л' },
    ],
  },
  {
    id: 'mgmt_pnl', label: 'Управленческий P&L', section: 'Управленческий',
    description: 'Выручка / себестоимость / валовая маржа по станциям, топливу, месяцам + структура оплат.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'groupings', label: 'Группировки (станция/топливо/месяц)' },
      { key: 'defaultPeriod', label: 'Период по умолчанию' },
      { key: 'vat', label: 'Ставка НДС, %' },
    ],
  },
  {
    id: 'procurement', label: 'Энергозакупка', section: 'Управленческий',
    description: 'Закупка э/э по поставщикам, ₽/кВт·ч, договоры энергоснабжения, эффективность закупки.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'benchmark', label: 'Бенчмарк цены, ₽/кВт·ч' },
    ],
  },
  {
    id: 'rent', label: 'Аренда', section: 'Управленческий',
    description: 'Аренда земли/площадок ЭЗС: договоры и разрешения на размещение, арендодатели (в т.ч. муниципалитеты), статус оплаты «оплачено по», особый порядок (% от выручки/фикс/сервитут), проблемные позиции.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'basisTypes', label: 'Виды основания', hint: 'договор / разрешение / постановление / приказ / сервитут' },
      { key: 'overdueDays', label: 'Порог просрочки, дней' },
    ],
  },
  // ── Финансовый ──
  {
    id: 'fin_energy', label: 'Финансовый учёт', section: 'Финансовый',
    description: 'Денежные потоки, дебиторка/кредиторка, платёжный календарь по сети ЭЗС.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'currency', label: 'Валюта' },
      { key: 'calendarHorizon', label: 'Горизонт платёжного календаря' },
    ],
  },
  {
    id: 'financial', label: 'Финансовый учёт', section: 'Финансовый',
    description: 'Денежные потоки, дебиторская/кредиторская задолженность, платёжный календарь.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'chart', label: 'План счетов' },
      { key: 'periodization', label: 'Периодизация' },
      { key: 'currency', label: 'Валюта' },
    ],
  },
  // ── Бухгалтерский ──
  {
    id: 'acc_energy', label: 'Бухгалтерский учёт', section: 'Бухгалтерский',
    description: 'Журнал операций и проводки по учётной модели компании (биллинг ЭЗС).',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'chart', label: 'План счетов' },
      { key: 'target', label: 'Учётная система компании' },
    ],
  },
  {
    id: 'accounting', label: 'Бухгалтерский учёт (1С)', section: 'Бухгалтерский',
    description: 'Подготовка документов для 1С: журнал БП, очередь выгрузки L3, периоды, эталонные проводки, учётная политика, партии FIFO.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'base', label: 'База 1С' },
      { key: 'postingTemplates', label: 'Шаблоны проводок' },
    ],
  },
  // ── Налоговый ──
  {
    id: 'tax_energy', label: 'Налоговый учёт', section: 'Налоговый',
    description: 'НДС (22%), налог на прибыль (25%) по сети ЭЗС.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'vatRate', label: 'Ставка НДС, %' },
      { key: 'profitRate', label: 'Ставка налога на прибыль, %' },
    ],
  },
  {
    id: 'tax', label: 'Налоговый учёт', section: 'Налоговый',
    description: 'НДС, налог на прибыль, контроль соответствия.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'vatRate', label: 'Ставка НДС, %' },
      { key: 'regime', label: 'Налоговый режим' },
    ],
  },
  // Примечание: разрезы учёта (= разрезы сверки) — ОТДЕЛЬНЫЙ уровень (входной контур),
  // живут в своей секции каталога, а не как модуль рабочего стола.
]

export const PROFILE_LABEL: Record<ModuleProfile, string> = {
  fuel: 'АЗС (топливо)', energy: 'ЭЗС (энергия)', any: 'универсальный',
}

export function getWorkspaceModule(id: string): WorkspaceModuleDef | undefined {
  return WORKSPACE_MODULES.find((m) => m.id === id)
}
