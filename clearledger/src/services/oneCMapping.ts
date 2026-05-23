/**
 * Маппинг docTypeId → тип документа 1С:Бухгалтерия.
 *
 * Определяет какой объект EnterpriseData создавать для каждого типа документа ClearLedger.
 */

/** Тип объекта EnterpriseData для 1С:БП 3.0 */
export type OneCDocType =
  | 'ПоступлениеТоваровУслуг'
  | 'СчетФактураПолученный'
  | 'ПлатежноеПоручение'
  | 'ДоговорКонтрагента'

export interface OneCMappingResult {
  oneCDocType: OneCDocType
  oneCDocLabel: string
}

const DOC_TYPE_MAP: Record<string, OneCMappingResult> = {
  // Накладные и акты → ПоступлениеТоваровУслуг
  'ttn-gsm':           { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'torg-12':           { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'supply-invoice':    { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'act-work':          { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'act-acceptance':    { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'upd':               { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },
  'waybill':           { oneCDocType: 'ПоступлениеТоваровУслуг', oneCDocLabel: 'Поступление товаров и услуг' },

  // Счёт-фактура → СчетФактураПолученный
  'invoice-factura':   { oneCDocType: 'СчетФактураПолученный',   oneCDocLabel: 'Счёт-фактура полученный' },

  // Платёжное поручение → ПлатежноеПоручение
  'payment-order':     { oneCDocType: 'ПлатежноеПоручение',      oneCDocLabel: 'Платёжное поручение' },
  'payment':           { oneCDocType: 'ПлатежноеПоручение',      oneCDocLabel: 'Платёжное поручение' },
  'pko':               { oneCDocType: 'ПлатежноеПоручение',      oneCDocLabel: 'Приходный кассовый ордер' },
  'rko':               { oneCDocType: 'ПлатежноеПоручение',      oneCDocLabel: 'Расходный кассовый ордер' },

  // Договор → ДоговорКонтрагента (справочник)
  'contract':          { oneCDocType: 'ДоговорКонтрагента',       oneCDocLabel: 'Договор контрагента' },
}

/**
 * Получить тип документа 1С:БП по docTypeId ClearLedger.
 * Возвращает undefined для типов, не имеющих прямого маппинга.
 */
export function mapToOneCDocType(docTypeId?: string): OneCMappingResult | undefined {
  if (!docTypeId) return undefined
  return DOC_TYPE_MAP[docTypeId]
}

/** Генерация 1С-совместимого UUID */
export function generate1CUuid(): string {
  return crypto.randomUUID()
}
