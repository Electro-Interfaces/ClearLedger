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
    id: 'balance_ezs', label: 'Баланс ЭЗС', section: 'Продажи',
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
    id: 'balance_azs', label: 'Баланс АЗС', section: 'Продажи',
    description: 'Приход (ТТН) − Реализация = Потери по АЗС: естественная убыль, температурная коррекция по плотности, недостача/излишек ТМЦ.',
    profiles: ['fuel'], status: 'planned',
    params: [
      { key: 'norm', label: 'Норма естественной убыли, %' },
      { key: 'density', label: 'Плотность/температура' },
      { key: 'unit', label: 'Единица ресурса', hint: 'л' },
    ],
  },
  {
    id: 'mgmt_pnl', label: 'Управленческий P&L', section: 'Продажи',
    description: 'Выручка / себестоимость / валовая маржа по станциям, топливу, месяцам + структура оплат.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'groupings', label: 'Группировки (станция/топливо/месяц)' },
      { key: 'defaultPeriod', label: 'Период по умолчанию' },
      { key: 'vat', label: 'Ставка НДС, %' },
    ],
  },
  // ── Магазин ──
  {
    id: 'store_module', label: 'Торговый центр (сопутка/общепит)', section: 'Торговый центр',
    description: 'Товароучёт сопутствующих товаров и общепита: коннектор чтения из 1С (ЦБ/станция), управленческая аналитика по ассортименту (продажи, маржа, оборачиваемость, ABC/XYZ), выгрузка пакетов в БП ГИГ. Первый шаг — Ledger как единый продюсер пакетов вместо TL_ЭкспортБП.',
    profiles: ['fuel'], status: 'active',
    params: [
      { key: 'stations', label: 'Станции', hint: '208 (Выборг); далее 5/8/209/210' },
      { key: 'cbConnection', label: 'Подключение ЦБ', hint: 'azs_centre (COM через vpn-gw, read-only)' },
      { key: 'defaultPeriod', label: 'Период по умолчанию' },
      { key: 'parallelReconcile', label: 'Параллельная сверка с текущим каналом', hint: 'вкл — сверять пакеты Ledger ↔ TL_ЭкспортБП' },
    ],
  },
  {
    id: 'ops_closing', label: 'Закрытие месяца', section: 'Продажи',
    description: 'Ежемесячный реестр затрат площадок: что должны были собрать по договорам, что собрали, чем подтверждено. Контрагенты выставляют закрывающие документы не всегда — период закрывается расчётной суммой с пометкой метода, а поздний документ проводится корректировкой следующего месяца.',
    profiles: ['energy'], status: 'active',
    params: [
      { key: 'docDueDay', label: 'Срок документа по умолчанию, число месяца', hint: 'если не задан в условии договора — 10-е' },
      { key: 'costItems', label: 'Статьи затрат', hint: 'аренда и электроэнергия; остальные включаются справочником' },
    ],
  },
  {
    id: 'ops_charges', label: 'Затраты объектов', section: 'Продажи',
    description: 'Матрица «объект × месяц × статья» за квартал и год: сколько потратили по каждой площадке и по компании в целом, какая доля суммы подтверждена документами, а какая посчитана.',
    profiles: ['energy'], status: 'active',
    params: [
      { key: 'defaultRange', label: 'Диапазон по умолчанию', hint: 'квартал / полгода / год' },
    ],
  },
  {
    id: 'ops_docs', label: 'Документы', section: 'Продажи',
    description: 'Входящая первичка контрагентов: акты, УПД, счета и расчёты со сканами. Что пришло, что не привязано ни к одному ожиданию, что ждёт скана. Канал приёма — вручную; почта и ЭДО подключаются отдельно.',
    profiles: ['energy'], status: 'active',
    params: [
      { key: 'docTypes', label: 'Виды документов', hint: 'акт, УПД, счёт, счёт-фактура, расчёт' },
    ],
  },
  {
    id: 'ops_parties', label: 'Контрагенты', section: 'Продажи',
    description: 'Дисциплина предоставления закрывающих документов: кто присылает вовремя, кто с опозданием и на сколько дней, кто молчит. Суммы, число объектов и периодов, контакты для связи — почта, телефон, руководитель.',
    profiles: ['energy'], status: 'active',
    params: [
      { key: 'disciplineTarget', label: 'Целевая дисциплина, %', hint: 'ниже порога контрагент попадает в проблемные' },
    ],
  },
  {
    id: 'procurement', label: 'Энергозакупка', section: 'Продажи',
    description: 'Закупка э/э по поставщикам, ₽/кВт·ч, договоры энергоснабжения, эффективность закупки.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'benchmark', label: 'Бенчмарк цены, ₽/кВт·ч' },
    ],
  },
  {
    id: 'rent', label: 'Аренда', section: 'Продажи',
    description: 'Аренда земли/площадок ЭЗС: договоры и разрешения на размещение, арендодатели (в т.ч. муниципалитеты), статус оплаты «оплачено по», особый порядок (% от выручки/фикс/сервитут), проблемные позиции.',
    profiles: ['energy'], status: 'demo',
    params: [
      { key: 'basisTypes', label: 'Виды основания', hint: 'договор / разрешение / постановление / приказ / сервитут' },
      { key: 'overdueDays', label: 'Порог просрочки, дней' },
    ],
  },
  // ── Управленческий (fuel) ──
  {
    id: 'ops_contracts', label: 'Договоры и аренда', section: 'Управленческий',
    description: 'Хозяйственные отношения компании: реестр договоров (аренда земли и площадок АЗС, поставщики, обслуживание), сроки, платёжная дисциплина.',
    profiles: ['fuel'], status: 'planned',
    params: [
      { key: 'overdueDays', label: 'Порог просрочки, дней' },
    ],
  },
  // «Финансовый» и «Налоговый» сняты с витрины 13.07.2026 (пустые заготовки) —
  // карточки модулей удалены из каталога вместе с разделами (workspaceSections.ts).
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
  // Примечание: разрезы учёта (= разрезы сверки) — ОТДЕЛЬНЫЙ уровень (входной контур),
  // живут в своей секции каталога, а не как модуль рабочего стола.
]

export const PROFILE_LABEL: Record<ModuleProfile, string> = {
  fuel: 'АЗС (топливо)', energy: 'ЭЗС (энергия)', any: 'универсальный',
}

export function getWorkspaceModule(id: string): WorkspaceModuleDef | undefined {
  return WORKSPACE_MODULES.find((m) => m.id === id)
}
