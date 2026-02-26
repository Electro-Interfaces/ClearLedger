/**
 * Профили деятельности компаний.
 * Каждый профиль определяет набор категорий, типов документов,
 * шаблонов метаданных и доступных коннекторов.
 */

// ─── Типы ─────────────────────────────────────────────

export type ProfileId = 'fuel' | 'trade' | 'retail' | 'energy' | 'general'

export interface MetadataField {
  key: string
  label: string
  type: 'text' | 'number' | 'date' | 'select' | 'textarea'
  placeholder?: string
  required?: boolean
  options?: string[]         // для type=select
  unit?: string              // "л", "₽", "кг"
}

export interface DocumentType {
  id: string
  label: string
  metadataFields: MetadataField[]
  ocrEnabled?: boolean       // можно ли распознавать OCR
}

export interface SubCategory {
  id: string
  label: string
  documentTypes: DocumentType[]
}

export interface Category {
  id: string
  label: string
  icon: string               // имя иконки lucide
  subcategories: SubCategory[]
}

export interface ConnectorTemplate {
  id: string
  name: string
  type: 'rest' | '1c' | 'email' | 'ftp' | 'webhook' | 'watch-dir' | 'edi' | 'cloud'
  description: string
  defaultInterval: number    // секунды
  targetCategory: string     // в какую категорию попадают данные
}

export interface CompanyProfile {
  id: ProfileId
  label: string
  description: string
  categories: Category[]
  connectorTemplates: ConnectorTemplate[]
}

// ─── Подкатегория для нераспознанных документов ─────

const unclassifiedSubcategory: SubCategory = {
  id: 'unclassified',
  label: 'Нераспознанные',
  documentTypes: [{
    id: 'unclassified-doc',
    label: 'Нераспознанный документ',
    metadataFields: [],
  }],
}

// ─── Общие метаполя (переиспользуемые) ─────────────

const f = {
  docNumber:    { key: 'docNumber', label: 'Номер документа', type: 'text' as const, placeholder: '№' },
  docDate:      { key: 'docDate', label: 'Дата документа', type: 'date' as const, required: true },
  counterparty: { key: 'counterparty', label: 'Контрагент', type: 'text' as const, placeholder: 'Название организации' },
  amount:       { key: 'amount', label: 'Сумма', type: 'number' as const, placeholder: '0.00', unit: '₽' },
  period:       { key: 'period', label: 'Период', type: 'text' as const, placeholder: 'Январь 2026' },
  date:         { key: 'date', label: 'Дата', type: 'date' as const },
  description:  { key: 'description', label: 'Описание', type: 'textarea' as const, placeholder: 'Описание' },
  comment:      { key: 'comment', label: 'Комментарий', type: 'textarea' as const, placeholder: 'Комментарий' },
}

// ─── ПРОФИЛЬ: Топливный бизнес ─────────────────────

const fuelProfile: CompanyProfile = {
  id: 'fuel',
  label: 'Топливный бизнес',
  description: 'АЗС, нефтебаза, процессинг, оптовая торговля ГСМ',
  categories: [
    {
      id: 'primary',
      label: 'Первичные документы',
      icon: 'FileText',
      subcategories: [
        {
          id: 'ttn', label: 'ТТН на ГСМ',
          documentTypes: [{
            id: 'ttn-gsm', label: 'Товарно-транспортная накладная',
            ocrEnabled: true,
            metadataFields: [
              f.docNumber, f.docDate, f.counterparty,
              { key: 'fuelGrade', label: 'Марка ГСМ', type: 'select', options: ['АИ-92', 'АИ-95', 'АИ-98', 'ДТ', 'ДТ-З', 'СУГ'] },
              { key: 'volume', label: 'Объём', type: 'number', unit: 'л', placeholder: '0' },
              { key: 'density', label: 'Плотность', type: 'number', placeholder: '0.000' },
              { key: 'mass', label: 'Масса', type: 'number', unit: 'кг', placeholder: '0' },
              { key: 'vehiclePlate', label: 'Гос. номер ТС', type: 'text', placeholder: 'А123БВ77' },
            ],
          }],
        },
        {
          id: 'acts', label: 'Акты',
          documentTypes: [
            {
              id: 'act-acceptance', label: 'Акт приёма-передачи топлива', ocrEnabled: true,
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount,
                { key: 'fuelGrade', label: 'Марка ГСМ', type: 'select', options: ['АИ-92', 'АИ-95', 'АИ-98', 'ДТ', 'ДТ-З'] },
                { key: 'volume', label: 'Объём', type: 'number', unit: 'л' },
              ],
            },
            {
              id: 'act-reconciliation', label: 'Акт сверки', ocrEnabled: true,
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.period, f.amount],
            },
            {
              id: 'act-work', label: 'Акт выполненных работ',
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount],
            },
          ],
        },
        {
          id: 'invoices', label: 'Счета и УПД',
          documentTypes: [
            {
              id: 'invoice', label: 'Счёт на оплату', ocrEnabled: true,
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount],
            },
            {
              id: 'invoice-factura', label: 'Счёт-фактура', ocrEnabled: true,
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount,
                { key: 'nds', label: 'НДС', type: 'number', unit: '₽' },
              ],
            },
            {
              id: 'upd', label: 'Универсальный передаточный документ', ocrEnabled: true,
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount],
            },
          ],
        },
        {
          id: 'contracts', label: 'Договоры',
          documentTypes: [{
            id: 'contract', label: 'Договор',
            metadataFields: [f.docNumber, f.docDate, f.counterparty,
              { key: 'contractType', label: 'Тип договора', type: 'select', options: ['Поставка', 'Аренда', 'Обслуживание', 'Услуги', 'Подряд'] },
              { key: 'validUntil', label: 'Действует до', type: 'date' },
              f.amount,
            ],
          }],
        },
        {
          id: 'quality', label: 'Качество',
          documentTypes: [{
            id: 'passport-quality', label: 'Паспорт качества топлива',
            metadataFields: [f.docNumber, f.docDate,
              { key: 'fuelGrade', label: 'Марка ГСМ', type: 'select', options: ['АИ-92', 'АИ-95', 'АИ-98', 'ДТ', 'ДТ-З'] },
              { key: 'batchNumber', label: 'Номер партии', type: 'text' },
              { key: 'octane', label: 'Октановое число', type: 'number' },
            ],
          }],
        },
        unclassifiedSubcategory,
      ],
    },
    {
      id: 'financial',
      label: 'Финансовый учёт',
      icon: 'Wallet',
      subcategories: [
        {
          id: 'payments', label: 'Платежи и поступления',
          documentTypes: [
            {
              id: 'payment-order', label: 'Платёжное поручение',
              metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount,
                { key: 'purpose', label: 'Назначение платежа', type: 'text' },
              ],
            },
            {
              id: 'bank-statement', label: 'Банковская выписка',
              metadataFields: [f.docDate, f.period,
                { key: 'account', label: 'Расчётный счёт', type: 'text' },
                { key: 'debit', label: 'Дебет', type: 'number', unit: '₽' },
                { key: 'credit', label: 'Кредит', type: 'number', unit: '₽' },
              ],
            },
          ],
        },
        {
          id: 'cash', label: 'Касса',
          documentTypes: [
            {
              id: 'z-report', label: 'Z-отчёт (кассовый)', ocrEnabled: true,
              metadataFields: [f.date,
                { key: 'cashRegister', label: 'Номер ККТ', type: 'text' },
                { key: 'shiftNumber', label: 'Номер смены', type: 'number' },
                { key: 'totalCash', label: 'Наличные', type: 'number', unit: '₽' },
                { key: 'totalCard', label: 'Безналичные', type: 'number', unit: '₽' },
                { key: 'totalAmount', label: 'Итого', type: 'number', unit: '₽' },
              ],
            },
            {
              id: 'receipt', label: 'Кассовый чек',
              metadataFields: [f.date, f.amount],
            },
          ],
        },
        {
          id: 'reconciliation', label: 'Сверки и отчёты',
          documentTypes: [
            {
              id: 'reconciliation-act', label: 'Акт сверки взаиморасчётов', ocrEnabled: true,
              metadataFields: [f.docDate, f.counterparty, f.period, f.amount],
            },
            {
              id: 'financial-report', label: 'Финансовый отчёт',
              metadataFields: [f.period, f.description],
            },
          ],
        },
      ],
    },
    {
      id: 'operational',
      label: 'Операционный учёт',
      icon: 'Activity',
      subcategories: [
        {
          id: 'fuel-deliveries', label: 'Поставки ГСМ',
          documentTypes: [{
            id: 'delivery-record', label: 'Запись о поставке',
            metadataFields: [f.date, f.counterparty,
              { key: 'fuelGrade', label: 'Марка ГСМ', type: 'select', options: ['АИ-92', 'АИ-95', 'АИ-98', 'ДТ', 'ДТ-З', 'СУГ'] },
              { key: 'volume', label: 'Объём', type: 'number', unit: 'л' },
              { key: 'tankNumber', label: '№ резервуара', type: 'text' },
            ],
          }],
        },
        {
          id: 'inventory', label: 'Остатки',
          documentTypes: [{
            id: 'fuel-inventory', label: 'Остатки топлива',
            metadataFields: [f.date,
              { key: 'ai92', label: 'АИ-92', type: 'number', unit: 'л' },
              { key: 'ai95', label: 'АИ-95', type: 'number', unit: 'л' },
              { key: 'ai98', label: 'АИ-98', type: 'number', unit: 'л' },
              { key: 'dt', label: 'ДТ', type: 'number', unit: 'л' },
            ],
          }],
        },
        {
          id: 'shifts', label: 'Смены',
          documentTypes: [{
            id: 'shift-report', label: 'Сменный отчёт АЗС',
            metadataFields: [f.date,
              { key: 'shiftNumber', label: 'Номер смены', type: 'number' },
              { key: 'operator', label: 'Оператор', type: 'text' },
              { key: 'totalSales', label: 'Итого продажи', type: 'number', unit: '₽' },
              { key: 'totalVolume', label: 'Итого объём', type: 'number', unit: 'л' },
            ],
          }],
        },
        {
          id: 'sales', label: 'Продажи',
          documentTypes: [{
            id: 'transaction-register', label: 'Реестр транзакций',
            metadataFields: [f.date, f.period,
              { key: 'transactionCount', label: 'Количество транзакций', type: 'number' },
              { key: 'totalAmount', label: 'Итого', type: 'number', unit: '₽' },
              { key: 'paymentType', label: 'Тип оплаты', type: 'select', options: ['Все', 'Наличные', 'Карта', 'Безнал', 'Бонусы'] },
            ],
          }],
        },
        {
          id: 'metrology', label: 'Метрология',
          documentTypes: [{
            id: 'metrology-protocol', label: 'Протокол поверки ТРК',
            metadataFields: [f.docNumber, f.docDate,
              { key: 'trkNumber', label: '№ ТРК', type: 'text' },
              { key: 'validUntil', label: 'Действительна до', type: 'date' },
              { key: 'result', label: 'Результат', type: 'select', options: ['Годна', 'Не годна'] },
            ],
          }],
        },
      ],
    },
    {
      id: 'hr',
      label: 'Кадры',
      icon: 'Users',
      subcategories: [
        {
          id: 'timesheets', label: 'Табели и путевые',
          documentTypes: [
            { id: 'timesheet', label: 'Табель учёта рабочего времени', metadataFields: [f.period] },
            { id: 'waybill', label: 'Путевой лист', metadataFields: [f.docNumber, f.docDate, { key: 'driver', label: 'Водитель', type: 'text' }, { key: 'vehiclePlate', label: 'Гос. номер', type: 'text' }] },
          ],
        },
      ],
    },
    {
      id: 'legal',
      label: 'Юридические',
      icon: 'Scale',
      subcategories: [
        {
          id: 'licenses', label: 'Лицензии и разрешения',
          documentTypes: [
            { id: 'license', label: 'Лицензия', metadataFields: [f.docNumber, f.docDate, { key: 'validUntil', label: 'Действует до', type: 'date' }, { key: 'licenseType', label: 'Тип', type: 'text' }] },
            { id: 'ecology-doc', label: 'Экологический документ', metadataFields: [f.docNumber, f.docDate, f.description] },
          ],
        },
      ],
    },
    {
      id: 'media',
      label: 'Медиа',
      icon: 'Image',
      subcategories: [
        { id: 'photos', label: 'Фотографии', documentTypes: [{ id: 'photo', label: 'Фотография', metadataFields: [f.date, f.description] }] },
        { id: 'scans', label: 'Сканы', documentTypes: [{ id: 'scan', label: 'Скан документа', ocrEnabled: true, metadataFields: [f.date, f.description] }] },
      ],
    },
  ],
  connectorTemplates: [
    { id: 'c-1c-buh', name: '1C Бухгалтерия', type: '1c', description: 'Документы, справочники, проводки', defaultInterval: 60, targetCategory: 'financial' },
    { id: 'c-1c-unf', name: '1C УНФ', type: '1c', description: 'Управление нашей фирмой', defaultInterval: 60, targetCategory: 'primary' },
    { id: 'c-processing', name: 'Процессинг PTS', type: 'rest', description: 'Транзакции, остатки, смены', defaultInterval: 30, targetCategory: 'operational' },
    { id: 'c-gpn', name: 'ГПН Агрегатор', type: 'rest', description: 'Бонусные карты, транзакции ГПН', defaultInterval: 120, targetCategory: 'operational' },
    { id: 'c-ofd', name: 'ОФД (чеки, Z-отчёты)', type: 'rest', description: 'Онлайн-кассы через API ОФД', defaultInterval: 300, targetCategory: 'financial' },
    { id: 'c-bank', name: 'Банк API', type: 'rest', description: 'Выписки и платежи', defaultInterval: 600, targetCategory: 'financial' },
    { id: 'c-email', name: 'Email (IMAP)', type: 'email', description: 'Входящие документы от контрагентов', defaultInterval: 300, targetCategory: 'primary' },
    { id: 'c-edo', name: 'ЭДО (Диадок/СБИС)', type: 'rest', description: 'Электронный документооборот', defaultInterval: 120, targetCategory: 'primary' },
    { id: 'c-ftp', name: 'FTP/SFTP', type: 'ftp', description: 'Обмен файлами с контрагентами', defaultInterval: 600, targetCategory: 'primary' },
  ],
}

// ─── ПРОФИЛЬ: Торгово-сервисная компания ───────────

const tradeProfile: CompanyProfile = {
  id: 'trade',
  label: 'Торговля и услуги',
  description: 'Торгово-сервисная компания, B2B/B2C',
  categories: [
    {
      id: 'primary',
      label: 'Первичные документы',
      icon: 'FileText',
      subcategories: [
        {
          id: 'torg', label: 'Товарные накладные',
          documentTypes: [{
            id: 'torg-12', label: 'ТОРГ-12', ocrEnabled: true,
            metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount,
              { key: 'itemsCount', label: 'Кол-во позиций', type: 'number' },
            ],
          }],
        },
        {
          id: 'acts', label: 'Акты',
          documentTypes: [
            { id: 'act-work', label: 'Акт выполненных работ', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
            { id: 'act-reconciliation', label: 'Акт сверки', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.period, f.amount] },
          ],
        },
        {
          id: 'invoices', label: 'Счета',
          documentTypes: [
            { id: 'invoice', label: 'Счёт на оплату', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
            { id: 'invoice-factura', label: 'Счёт-фактура', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount, { key: 'nds', label: 'НДС', type: 'number', unit: '₽' }] },
            { id: 'upd', label: 'УПД', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
          ],
        },
        {
          id: 'contracts', label: 'Договоры',
          documentTypes: [{
            id: 'contract', label: 'Договор',
            metadataFields: [f.docNumber, f.docDate, f.counterparty,
              { key: 'contractType', label: 'Тип', type: 'select', options: ['Поставка', 'Услуги', 'Подряд', 'Аренда', 'Агентский'] },
              { key: 'validUntil', label: 'Действует до', type: 'date' }, f.amount,
            ],
          }],
        },
        unclassifiedSubcategory,
      ],
    },
    {
      id: 'financial',
      label: 'Финансовый учёт',
      icon: 'Wallet',
      subcategories: [
        {
          id: 'payments', label: 'Платежи',
          documentTypes: [
            { id: 'payment-order', label: 'Платёжное поручение', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount, { key: 'purpose', label: 'Назначение', type: 'text' }] },
            { id: 'bank-statement', label: 'Банковская выписка', metadataFields: [f.docDate, f.period, { key: 'account', label: 'Р/С', type: 'text' }] },
          ],
        },
        {
          id: 'cash', label: 'Касса',
          documentTypes: [
            { id: 'pko', label: 'ПКО (приходный кассовый)', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
            { id: 'rko', label: 'РКО (расходный кассовый)', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
            { id: 'advance-report', label: 'Авансовый отчёт', metadataFields: [f.docNumber, f.docDate, { key: 'employee', label: 'Сотрудник', type: 'text' }, f.amount] },
          ],
        },
        {
          id: 'reports', label: 'Отчёты',
          documentTypes: [
            { id: 'financial-report', label: 'Финансовый отчёт', metadataFields: [f.period, f.description] },
          ],
        },
      ],
    },
    {
      id: 'operational',
      label: 'Операционные',
      icon: 'Activity',
      subcategories: [
        {
          id: 'sales', label: 'Продажи',
          documentTypes: [
            { id: 'sales-register', label: 'Реестр продаж', metadataFields: [f.period, { key: 'totalAmount', label: 'Итого', type: 'number', unit: '₽' }] },
          ],
        },
      ],
    },
    {
      id: 'hr',
      label: 'Кадры',
      icon: 'Users',
      subcategories: [
        {
          id: 'timesheets', label: 'Табели',
          documentTypes: [
            { id: 'timesheet', label: 'Табель учёта рабочего времени', metadataFields: [f.period] },
            { id: 'waybill', label: 'Путевой лист', metadataFields: [f.docNumber, f.docDate, { key: 'driver', label: 'Водитель', type: 'text' }] },
          ],
        },
      ],
    },
    {
      id: 'media',
      label: 'Медиа',
      icon: 'Image',
      subcategories: [
        { id: 'photos', label: 'Фотографии', documentTypes: [{ id: 'photo', label: 'Фотография', metadataFields: [f.date, f.description] }] },
        { id: 'scans', label: 'Сканы', documentTypes: [{ id: 'scan', label: 'Скан', ocrEnabled: true, metadataFields: [f.date, f.description] }] },
      ],
    },
  ],
  connectorTemplates: [
    { id: 'c-1c-buh', name: '1C Бухгалтерия', type: '1c', description: 'Документы и справочники', defaultInterval: 60, targetCategory: 'financial' },
    { id: 'c-crm', name: 'CRM', type: 'rest', description: 'Клиенты, сделки, задачи', defaultInterval: 120, targetCategory: 'operational' },
    { id: 'c-bank', name: 'Банк API', type: 'rest', description: 'Выписки, платежи', defaultInterval: 600, targetCategory: 'financial' },
    { id: 'c-edo', name: 'ЭДО (Диадок/СБИС)', type: 'rest', description: 'Электронный документооборот', defaultInterval: 120, targetCategory: 'primary' },
    { id: 'c-ofd', name: 'ОФД', type: 'rest', description: 'Кассовые чеки', defaultInterval: 300, targetCategory: 'financial' },
    { id: 'c-email', name: 'Email (IMAP)', type: 'email', description: 'Входящие документы', defaultInterval: 300, targetCategory: 'primary' },
  ],
}

// ─── ПРОФИЛЬ: Продуктовая сеть ─────────────────────

const retailProfile: CompanyProfile = {
  id: 'retail',
  label: 'Розничная торговля',
  description: 'Продуктовые магазины, розничные сети',
  categories: [
    {
      id: 'primary',
      label: 'Первичные документы',
      icon: 'FileText',
      subcategories: [
        {
          id: 'supply', label: 'Поставки',
          documentTypes: [
            { id: 'supply-invoice', label: 'Приходная накладная', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount, { key: 'itemsCount', label: 'Позиций', type: 'number' }] },
            { id: 'return-invoice', label: 'Возвратная накладная', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount, { key: 'reason', label: 'Причина', type: 'text' }] },
          ],
        },
        {
          id: 'writeoffs', label: 'Списания',
          documentTypes: [
            { id: 'writeoff-act', label: 'Акт списания', metadataFields: [f.docNumber, f.docDate, f.amount, { key: 'reason', label: 'Причина', type: 'select', options: ['Просрочка', 'Бой', 'Недостача', 'Прочее'] }] },
            { id: 'inventory-sheet', label: 'Инвентаризационная опись', metadataFields: [f.docDate, { key: 'section', label: 'Отдел', type: 'text' }] },
          ],
        },
        {
          id: 'contracts', label: 'Договоры',
          documentTypes: [
            { id: 'contract', label: 'Договор поставки', metadataFields: [f.docNumber, f.docDate, f.counterparty, { key: 'validUntil', label: 'Действует до', type: 'date' }] },
          ],
        },
        unclassifiedSubcategory,
      ],
    },
    {
      id: 'compliance',
      label: 'Регуляторные',
      icon: 'ShieldCheck',
      subcategories: [
        {
          id: 'certificates', label: 'Сертификаты',
          documentTypes: [
            { id: 'certificate', label: 'Сертификат/декларация', metadataFields: [f.docNumber, f.docDate, { key: 'product', label: 'Товар', type: 'text' }, { key: 'validUntil', label: 'Действует до', type: 'date' }] },
            { id: 'vet-cert', label: 'Ветеринарное свидетельство (Меркурий)', metadataFields: [f.docNumber, f.docDate, { key: 'product', label: 'Продукция', type: 'text' }, { key: 'mercuryId', label: 'ID Меркурий', type: 'text' }] },
          ],
        },
        {
          id: 'egais', label: 'ЕГАИС / Маркировка',
          documentTypes: [
            { id: 'egais-invoice', label: 'Алкогольная накладная (ЕГАИС)', metadataFields: [f.docNumber, f.docDate, f.counterparty, { key: 'egaisId', label: 'ID ЕГАИС', type: 'text' }] },
            { id: 'marking-doc', label: 'Документ маркировки (Честный ЗНАК)', metadataFields: [f.docNumber, f.docDate, { key: 'markingType', label: 'Тип', type: 'select', options: ['Табак', 'Молочка', 'Вода', 'Прочее'] }] },
          ],
        },
      ],
    },
    {
      id: 'financial',
      label: 'Финансовый учёт',
      icon: 'Wallet',
      subcategories: [
        {
          id: 'payments', label: 'Платежи',
          documentTypes: [
            { id: 'payment-order', label: 'Платёжное поручение', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
          ],
        },
        {
          id: 'cash', label: 'Касса',
          documentTypes: [
            { id: 'z-report', label: 'Z-отчёт', ocrEnabled: true, metadataFields: [f.date, { key: 'cashRegister', label: 'ККТ', type: 'text' }, { key: 'totalAmount', label: 'Итого', type: 'number', unit: '₽' }] },
          ],
        },
      ],
    },
    {
      id: 'operational',
      label: 'Операционные',
      icon: 'Activity',
      subcategories: [
        {
          id: 'pricing', label: 'Цены',
          documentTypes: [
            { id: 'pricelist', label: 'Прайс-лист', metadataFields: [f.date, f.counterparty, { key: 'itemsCount', label: 'Позиций', type: 'number' }] },
          ],
        },
      ],
    },
    {
      id: 'media',
      label: 'Медиа',
      icon: 'Image',
      subcategories: [
        { id: 'photos', label: 'Фотографии', documentTypes: [{ id: 'photo', label: 'Фотография', metadataFields: [f.date, f.description] }] },
        { id: 'scans', label: 'Сканы', documentTypes: [{ id: 'scan', label: 'Скан', ocrEnabled: true, metadataFields: [f.date, f.description] }] },
      ],
    },
  ],
  connectorTemplates: [
    { id: 'c-1c-retail', name: '1C Розница / УТ', type: '1c', description: 'Товародвижение, продажи', defaultInterval: 60, targetCategory: 'operational' },
    { id: 'c-egais', name: 'ЕГАИС', type: 'rest', description: 'Алкогольные накладные', defaultInterval: 120, targetCategory: 'compliance' },
    { id: 'c-mercury', name: 'Меркурий (ВетИС)', type: 'rest', description: 'Ветеринарные свидетельства', defaultInterval: 120, targetCategory: 'compliance' },
    { id: 'c-marking', name: 'Честный ЗНАК', type: 'rest', description: 'Маркировка товаров', defaultInterval: 120, targetCategory: 'compliance' },
    { id: 'c-cash-server', name: 'Кассовый сервер', type: 'rest', description: 'Чеки, Z-отчёты', defaultInterval: 60, targetCategory: 'financial' },
    { id: 'c-edi', name: 'EDI (X5/Магнит)', type: 'edi', description: 'Электронный обмен с сетями', defaultInterval: 300, targetCategory: 'primary' },
    { id: 'c-email', name: 'Email (IMAP)', type: 'email', description: 'Входящие документы', defaultInterval: 300, targetCategory: 'primary' },
  ],
}

// ─── ПРОФИЛЬ: Энергетика / Инфраструктура ──────────

const energyProfile: CompanyProfile = {
  id: 'energy',
  label: 'Энергетика / Инфраструктура',
  description: 'Энергетические объекты, инженерная инфраструктура',
  categories: [
    {
      id: 'primary',
      label: 'Первичные документы',
      icon: 'FileText',
      subcategories: [
        {
          id: 'acts', label: 'Акты',
          documentTypes: [
            { id: 'act-maintenance', label: 'Акт ТО оборудования', metadataFields: [f.docNumber, f.docDate, { key: 'equipment', label: 'Оборудование', type: 'text' }, { key: 'maintenanceType', label: 'Тип ТО', type: 'select', options: ['Плановое', 'Аварийное', 'Текущее'] }] },
            { id: 'act-work', label: 'Акт выполненных работ', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
            { id: 'defect-sheet', label: 'Дефектная ведомость', metadataFields: [f.docNumber, f.docDate, { key: 'equipment', label: 'Оборудование', type: 'text' }, f.description] },
          ],
        },
        {
          id: 'contracts', label: 'Договоры',
          documentTypes: [
            { id: 'contract', label: 'Договор', metadataFields: [f.docNumber, f.docDate, f.counterparty, { key: 'contractType', label: 'Тип', type: 'select', options: ['Обслуживание', 'Поставка', 'Подряд', 'Аренда'] }, f.amount] },
          ],
        },
        {
          id: 'invoices', label: 'Счета',
          documentTypes: [
            { id: 'invoice', label: 'Счёт на оплату', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
          ],
        },
        unclassifiedSubcategory,
      ],
    },
    {
      id: 'operational',
      label: 'Операционный учёт',
      icon: 'Activity',
      subcategories: [
        {
          id: 'journals', label: 'Журналы',
          documentTypes: [
            { id: 'inspection-journal', label: 'Журнал обходов', metadataFields: [f.date, { key: 'inspector', label: 'Обходчик', type: 'text' }, { key: 'route', label: 'Маршрут', type: 'text' }, f.comment] },
            { id: 'measurement-protocol', label: 'Протокол измерений', metadataFields: [f.docNumber, f.docDate, { key: 'parameter', label: 'Параметр', type: 'text' }, { key: 'value', label: 'Значение', type: 'text' }, { key: 'norm', label: 'Норма', type: 'text' }] },
          ],
        },
        {
          id: 'permits', label: 'Наряды и заявки',
          documentTypes: [
            { id: 'work-permit', label: 'Наряд-допуск', metadataFields: [f.docNumber, f.docDate, { key: 'workType', label: 'Вид работ', type: 'text' }, { key: 'responsible', label: 'Ответственный', type: 'text' }, { key: 'validUntil', label: 'Действует до', type: 'date' }] },
            { id: 'material-request', label: 'Заявка на материалы', metadataFields: [f.docNumber, f.docDate, { key: 'itemsCount', label: 'Позиций', type: 'number' }, f.amount] },
          ],
        },
      ],
    },
    {
      id: 'financial',
      label: 'Финансовый учёт',
      icon: 'Wallet',
      subcategories: [
        {
          id: 'payments', label: 'Платежи',
          documentTypes: [
            { id: 'payment-order', label: 'Платёжное поручение', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] },
          ],
        },
      ],
    },
    {
      id: 'media',
      label: 'Медиа',
      icon: 'Image',
      subcategories: [
        { id: 'photos', label: 'Фотографии', documentTypes: [{ id: 'photo', label: 'Фотография', metadataFields: [f.date, f.description] }] },
        { id: 'scans', label: 'Сканы', documentTypes: [{ id: 'scan', label: 'Скан', ocrEnabled: true, metadataFields: [f.date, f.description] }] },
      ],
    },
  ],
  connectorTemplates: [
    { id: 'c-1c-buh', name: '1C Бухгалтерия', type: '1c', description: 'Документы и справочники', defaultInterval: 60, targetCategory: 'financial' },
    { id: 'c-hubex', name: 'HubEx', type: 'rest', description: 'FSM: заявки, обходы, ТО', defaultInterval: 120, targetCategory: 'operational' },
    { id: 'c-scada', name: 'SCADA / Телеметрия', type: 'rest', description: 'Показания датчиков', defaultInterval: 30, targetCategory: 'operational' },
    { id: 'c-email', name: 'Email (IMAP)', type: 'email', description: 'Входящие документы', defaultInterval: 300, targetCategory: 'primary' },
  ],
}

// ─── ПРОФИЛЬ: Общий (fallback) ─────────────────────

const generalProfile: CompanyProfile = {
  id: 'general',
  label: 'Общий',
  description: 'Универсальный профиль для любого типа деятельности',
  categories: [
    {
      id: 'primary',
      label: 'Первичные документы',
      icon: 'FileText',
      subcategories: [
        { id: 'contracts', label: 'Договоры', documentTypes: [{ id: 'contract', label: 'Договор', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] }] },
        { id: 'acts', label: 'Акты', documentTypes: [{ id: 'act', label: 'Акт', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] }] },
        { id: 'invoices', label: 'Счета', documentTypes: [{ id: 'invoice', label: 'Счёт', ocrEnabled: true, metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] }] },
        unclassifiedSubcategory,
      ],
    },
    {
      id: 'financial',
      label: 'Финансовый учёт',
      icon: 'Wallet',
      subcategories: [
        { id: 'payments', label: 'Платежи', documentTypes: [{ id: 'payment', label: 'Платёж', metadataFields: [f.docNumber, f.docDate, f.counterparty, f.amount] }] },
        { id: 'reports', label: 'Отчёты', documentTypes: [{ id: 'report', label: 'Отчёт', metadataFields: [f.period, f.description] }] },
      ],
    },
    {
      id: 'media',
      label: 'Медиа',
      icon: 'Image',
      subcategories: [
        { id: 'photos', label: 'Фотографии', documentTypes: [{ id: 'photo', label: 'Фотография', metadataFields: [f.date, f.description] }] },
        { id: 'scans', label: 'Сканы', documentTypes: [{ id: 'scan', label: 'Скан', ocrEnabled: true, metadataFields: [f.date, f.description] }] },
      ],
    },
  ],
  connectorTemplates: [
    { id: 'c-1c', name: '1C', type: '1c', description: 'Любая конфигурация 1С', defaultInterval: 60, targetCategory: 'financial' },
    { id: 'c-email', name: 'Email (IMAP)', type: 'email', description: 'Входящие документы', defaultInterval: 300, targetCategory: 'primary' },
    { id: 'c-rest', name: 'REST API', type: 'rest', description: 'Произвольный REST API', defaultInterval: 120, targetCategory: 'primary' },
    { id: 'c-ftp', name: 'FTP/SFTP', type: 'ftp', description: 'Файловый обмен', defaultInterval: 600, targetCategory: 'primary' },
    { id: 'c-webhook', name: 'Webhook', type: 'webhook', description: 'Входящие уведомления', defaultInterval: 0, targetCategory: 'primary' },
    { id: 'c-watch', name: 'Файловая папка', type: 'watch-dir', description: 'Мониторинг директории', defaultInterval: 60, targetCategory: 'primary' },
    { id: 'c-cloud', name: 'Облако (GDrive/YaDisk)', type: 'cloud', description: 'Облачные хранилища', defaultInterval: 300, targetCategory: 'primary' },
  ],
}

// ─── Реестр профилей ───────────────────────────────

export const profiles: Record<ProfileId, CompanyProfile> = {
  fuel: fuelProfile,
  trade: tradeProfile,
  retail: retailProfile,
  energy: energyProfile,
  general: generalProfile,
}

export function getProfile(id: ProfileId): CompanyProfile {
  return profiles[id] ?? profiles.general
}
