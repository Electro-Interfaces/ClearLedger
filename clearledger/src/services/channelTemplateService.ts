/**
 * Шаблоны каналов — пресеты для быстрого создания типовых каналов.
 * Каждый шаблон определяет тип источника, потоки, расписание и поля настройки.
 */

import type { ChannelTemplate, ScheduleConfig } from '@/types/channel'

const manualSchedule: ScheduleConfig = {
  mode: 'manual',
  pauseOnError: true,
  maxRetries: 3,
}

const hourlySchedule: ScheduleConfig = {
  mode: 'interval',
  intervalMinutes: 60,
  activeHoursFrom: '07:00',
  activeHoursTo: '23:00',
  pauseOnError: true,
  maxRetries: 3,
}

export const CHANNEL_TEMPLATES: ChannelTemplate[] = [
  // ─── Торговля ─────────────────────────────────────
  {
    id: 'sts-shifts',
    name: 'Сменные отчёты АЗС',
    description: 'Загрузка сменных отчётов, резервуаров, ТРК и оплат через STS API',
    icon: 'BarChart3',
    category: 'Торговля',
    sourceType: 'rest',
    defaultConnection: {
      url: 'https://pos.autooplata.ru/tms',
      systemCode: '65',
    },
    streams: [
      { docTypeId: 'shift_report', docTypeLabel: 'Сменные отчёты', catalogTemplate: '/Смены/{объект}/{год}-{месяц}/', enabled: true },
      { docTypeId: 'receipt', docTypeLabel: 'ТТН (из смен)', catalogTemplate: '/ТТН/{объект}/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: hourlySchedule,
    setupFields: [
      { key: 'login', label: 'Логин API', type: 'text', required: true, defaultValue: 'UserApi' },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
      { key: 'systemCode', label: 'Код системы', type: 'number', required: true, defaultValue: '65' },
      { key: 'stationCodes', label: 'Коды станций', type: 'tags', required: true, placeholder: 'Введите код и нажмите Enter' },
    ],
  },
  {
    id: 'pos-reports',
    name: 'Кассовые отчёты',
    description: 'Z-отчёты и чеки из POS-систем и ОФД',
    icon: 'Receipt',
    category: 'Торговля',
    sourceType: 'rest',
    defaultConnection: {},
    streams: [
      { docTypeId: 'z_report', docTypeLabel: 'Z-отчёты', catalogTemplate: '/Касса/{объект}/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: manualSchedule,
    setupFields: [
      { key: 'url', label: 'URL API', type: 'text', required: true, placeholder: 'https://...' },
      { key: 'apiKey', label: 'API-ключ', type: 'password', required: true },
    ],
  },

  // ─── Операции ─────────────────────────────────────
  {
    id: 'sts-operations',
    name: 'Операции отпуска (STS)',
    description: 'Индивидуальные транзакции отпуска нефтепродуктов на торговых точках через STS API',
    icon: 'Activity',
    category: 'Торговля',
    sourceType: 'sts-ops',
    defaultConnection: {
      url: 'https://pos.autooplata.ru/tms',
      systemCode: '65',
    },
    streams: [
      { docTypeId: 'sts_transactions', docTypeLabel: 'Операции отпуска', catalogTemplate: '/Операции/{объект}/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: hourlySchedule,
    setupFields: [
      { key: 'login', label: 'Логин API', type: 'text', required: true, defaultValue: 'UserApi' },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
      { key: 'systemCode', label: 'Код системы', type: 'number', required: true, defaultValue: '65' },
      { key: 'stationCodes', label: 'Коды станций', type: 'tags', required: true, placeholder: 'Введите код и нажмите Enter' },
    ],
  },

  // ─── Сверки ───────────────────────────────────────
  {
    id: 'msto-online-orders',
    name: 'Онлайн-заказы (MSTO)',
    description: 'Сверка онлайн-заказов агрегаторов (Яндекс, FuelUp, Benzuber) через MSTO IntegratorService',
    icon: 'Fuel',
    category: 'Сверки',
    sourceType: 'msto',
    defaultConnection: {
      url: 'http://46.229.214.21:3000',
    },
    streams: [
      { docTypeId: 'msto_transactions', docTypeLabel: 'Транзакции онлайн-заказов', catalogTemplate: '/Онлайн-заказы/{объект}/{год}-{месяц}/', enabled: true },
      { docTypeId: 'msto_tariffs', docTypeLabel: 'Тарифы агрегаторов', catalogTemplate: '/Онлайн-заказы/Справочники/', enabled: true },
    ],
    defaultSchedule: hourlySchedule,
    setupFields: [
      { key: 'url', label: 'URL MSTO API', type: 'text', required: true, defaultValue: 'http://46.229.214.21:3000', placeholder: 'http://host:3000' },
      { key: 'login', label: 'Логин', type: 'text', required: true, defaultValue: 'tf-integration' },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
      { key: 'stationCodes', label: 'ID станций MSTO', type: 'tags', required: false, placeholder: '212, 238, 245, 251' },
    ],
  },
  {
    id: 'tradecorp-cards',
    name: 'Корпоративные карты (TradeCorp)',
    description: 'Сверка транзакций по корпоративным картам через процессинг TradeCorp',
    icon: 'CreditCard',
    category: 'Сверки',
    sourceType: 'tradecorp',
    defaultConnection: {
      url: 'https://api.autooplata.ru',
      emitentId: '15',
    },
    streams: [
      { docTypeId: 'corp_transactions', docTypeLabel: 'Транзакции по картам', catalogTemplate: '/Корп-карты/{объект}/{год}-{месяц}/', enabled: true },
      { docTypeId: 'corp_summary', docTypeLabel: 'Сводка по станциям', catalogTemplate: '/Корп-карты/Сводки/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: hourlySchedule,
    setupFields: [
      { key: 'url', label: 'URL TradeCorp API', type: 'text', required: true, defaultValue: 'https://api.autooplata.ru', placeholder: 'https://api.autooplata.ru' },
      { key: 'login', label: 'Логин', type: 'text', required: true },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
      { key: 'emitentId', label: 'ID эмитента', type: 'number', required: true, defaultValue: '15' },
      { key: 'stationNumbers', label: 'Номера станций', type: 'tags', required: false, placeholder: '1, 2, 3, 4' },
    ],
  },

  // ─── Поступления ──────────────────────────────────
  {
    id: 'sts-deliveries',
    name: 'Товарно-транспортные накладные',
    description: 'Загрузка ТТН через STS API или из 1С',
    icon: 'Truck',
    category: 'Поступления',
    sourceType: 'rest',
    defaultConnection: {
      url: 'https://pos.autooplata.ru/tms',
      systemCode: '65',
    },
    streams: [
      { docTypeId: 'delivery', docTypeLabel: 'ТТН', catalogTemplate: '/Поступления/{объект}/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: hourlySchedule,
    setupFields: [
      { key: 'login', label: 'Логин API', type: 'text', required: true, defaultValue: 'UserApi' },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
      { key: 'systemCode', label: 'Код системы', type: 'number', required: true, defaultValue: '65' },
      { key: 'stationCodes', label: 'Коды станций', type: 'tags', required: true, placeholder: 'Введите код и Enter' },
    ],
  },
  {
    id: 'trade-docs',
    name: 'Товарные накладные',
    description: 'ТОРГ-12, УПД через 1С или ЭДО',
    icon: 'Package',
    category: 'Поступления',
    sourceType: '1c',
    defaultConnection: {},
    streams: [
      { docTypeId: 'torg12', docTypeLabel: 'ТОРГ-12', catalogTemplate: '/Накладные/{год}-{месяц}/', enabled: true },
      { docTypeId: 'upd', docTypeLabel: 'УПД', catalogTemplate: '/УПД/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: manualSchedule,
    setupFields: [
      { key: 'url', label: 'URL OData', type: 'text', required: true, placeholder: 'http://server/base/odata/standard.odata' },
      { key: 'login', label: 'Логин 1С', type: 'text', required: true },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
    ],
  },

  // ─── Документооборот ──────────────────────────────
  {
    id: '1c-exchange',
    name: 'Обмен с 1С',
    description: 'Загрузка документов из 1С через OData или файловый обмен',
    icon: 'Database',
    category: 'Документооборот',
    sourceType: '1c',
    defaultConnection: {},
    streams: [
      { docTypeId: 'document', docTypeLabel: 'Документы 1С', catalogTemplate: '/1С/{тип}/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: { mode: 'interval', intervalMinutes: 360, pauseOnError: true, maxRetries: 3 },
    setupFields: [
      { key: 'url', label: 'URL OData / путь обмена', type: 'text', required: true },
      { key: 'login', label: 'Логин', type: 'text', required: true },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
    ],
  },
  {
    id: 'email-inbox',
    name: 'Входящие по email',
    description: 'Счета, акты, УПД из входящей почты (IMAP)',
    icon: 'Mail',
    category: 'Документооборот',
    sourceType: 'email',
    defaultConnection: {},
    streams: [
      { docTypeId: 'email_attachment', docTypeLabel: 'Вложения из писем', catalogTemplate: '/Почта/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: { mode: 'interval', intervalMinutes: 30, pauseOnError: true, maxRetries: 3 },
    setupFields: [
      { key: 'imapHost', label: 'IMAP сервер', type: 'text', required: true, placeholder: 'imap.mail.ru' },
      { key: 'imapPort', label: 'Порт', type: 'number', required: true, defaultValue: '993' },
      { key: 'login', label: 'Email', type: 'text', required: true },
      { key: 'password', label: 'Пароль', type: 'password', required: true },
    ],
  },
  {
    id: 'file-upload',
    name: 'Загрузка файлов',
    description: 'Ручная загрузка Excel, PDF, XML, JSON документов',
    icon: 'Upload',
    category: 'Документооборот',
    sourceType: 'cloud',
    defaultConnection: {},
    streams: [
      { docTypeId: 'uploaded_file', docTypeLabel: 'Загруженные файлы', catalogTemplate: '/Загрузки/{год}-{месяц}/', enabled: true },
    ],
    defaultSchedule: manualSchedule,
    setupFields: [],
  },

  // ─── Ручная настройка ─────────────────────────────
  {
    id: 'custom',
    name: 'Настроить вручную',
    description: 'Выбрать тип источника, потоки и pipeline самостоятельно',
    icon: 'Settings',
    category: 'Прочее',
    sourceType: 'rest',
    defaultConnection: {},
    streams: [],
    defaultSchedule: manualSchedule,
    setupFields: [
      { key: 'sourceType', label: 'Тип источника', type: 'select', required: true, options: [
        { value: 'rest', label: 'REST API' },
        { value: '1c', label: '1С Обмен' },
        { value: 'email', label: 'Email (IMAP)' },
        { value: 'ftp', label: 'FTP/SFTP' },
        { value: 'webhook', label: 'Webhook' },
        { value: 'watch-dir', label: 'Папка' },
        { value: 'edi', label: 'ЭДО (Контур/СБИС)' },
        { value: 'cloud', label: 'Облако' },
        { value: 'sts-ops', label: 'STS Операции (отпуск)' },
        { value: 'msto', label: 'MSTO (онлайн-заказы)' },
        { value: 'tradecorp', label: 'TradeCorp (корп. карты)' },
      ]},
    ],
  },
]

/** Получить шаблоны по категориям */
export function getTemplatesByCategory(): Map<string, ChannelTemplate[]> {
  const map = new Map<string, ChannelTemplate[]>()
  for (const t of CHANNEL_TEMPLATES) {
    if (!map.has(t.category)) map.set(t.category, [])
    map.get(t.category)!.push(t)
  }
  return map
}

/** Найти шаблон по ID */
export function getTemplate(id: string): ChannelTemplate | undefined {
  return CHANNEL_TEMPLATES.find((t) => t.id === id)
}
