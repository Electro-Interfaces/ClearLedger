/**
 * Сервис валидации документов.
 *
 * Проверяет:
 * 1. Обязательные поля (required из MetadataField)
 * 2. Типы полей (date, number)
 * 3. ИНН (контрольная сумма)
 * 4. Юридические правила по docType
 * 5. Полнота заполнения
 */

import type { DataEntry } from '@/types'
import type { ProfileId, MetadataField } from '@/config/profiles'
import { getProfile } from '@/config/profiles'

export interface ValidationIssue {
  field: string
  label: string
  severity: 'error' | 'warning'
  message: string
}

export interface ValidationResult {
  isValid: boolean       // нет errors (warnings OK)
  issues: ValidationIssue[]
  completeness: number   // 0-100% заполненности обязательных полей
}

/**
 * Найти MetadataField[] для конкретного docType в профиле.
 */
function findDocTypeFields(profileId: ProfileId, docTypeId?: string): MetadataField[] {
  if (!docTypeId) return []
  const profile = getProfile(profileId)
  for (const cat of profile.categories) {
    for (const sub of cat.subcategories) {
      for (const dt of sub.documentTypes) {
        if (dt.id === docTypeId) return dt.metadataFields
      }
    }
  }
  return []
}

/**
 * Проверка формата даты (YYYY-MM-DD или DD.MM.YYYY).
 */
function isValidDate(value: string): boolean {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return !isNaN(Date.parse(value))
  if (/^\d{2}\.\d{2}\.\d{4}$/.test(value)) {
    const [d, m, y] = value.split('.')
    return !isNaN(Date.parse(`${y}-${m}-${d}`))
  }
  return false
}

/**
 * Проверка ИНН (10 или 12 цифр с контрольной суммой).
 */
function validateInn(inn: string): boolean {
  if (!/^\d{10}$|^\d{12}$/.test(inn)) return false
  const digits = inn.split('').map(Number)

  if (digits.length === 10) {
    const weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    const sum = weights.reduce((acc, w, i) => acc + w * digits[i], 0)
    return (sum % 11) % 10 === digits[9]
  }

  // 12-значный ИНН
  const w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
  const w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
  const sum1 = w1.reduce((acc, w, i) => acc + w * digits[i], 0)
  const sum2 = w2.reduce((acc, w, i) => acc + w * digits[i], 0)
  return (sum1 % 11) % 10 === digits[10] && (sum2 % 11) % 10 === digits[11]
}

/**
 * Юридические правила по типу документа.
 */
const legalRules: Record<string, { field: string; label: string }[]> = {
  // ТТН: номер + дата + контрагент + объём
  'ttn-gsm': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'volume', label: 'Объём' },
  ],
  // Счёт-фактура: номер + дата + сумма + НДС + контрагент
  'invoice-factura': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'amount', label: 'Сумма' },
    { field: 'nds', label: 'НДС' },
  ],
  // Акт: номер + дата + контрагент
  'act-work': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
  ],
  'act-acceptance': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
  ],
  'act-reconciliation': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
  ],
  // Договор: номер + дата + контрагент
  'contract': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
  ],
  // Паспорт качества: номер + дата + марка
  'passport-quality': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'fuelGrade', label: 'Марка ГСМ' },
  ],
  // Счёт: номер + дата + контрагент + сумма
  'invoice': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'amount', label: 'Сумма' },
  ],
  // УПД
  'upd': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'amount', label: 'Сумма' },
  ],
  // Платёжное поручение
  'payment-order': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'amount', label: 'Сумма' },
  ],
  // ТОРГ-12
  'torg-12': [
    { field: 'docNumber', label: 'Номер документа' },
    { field: 'docDate', label: 'Дата документа' },
    { field: 'counterparty', label: 'Контрагент' },
    { field: 'amount', label: 'Сумма' },
  ],
}

/**
 * Главная функция валидации.
 */
export function validateEntry(entry: DataEntry, profileId: ProfileId): ValidationResult {
  const issues: ValidationIssue[] = []
  const fields = findDocTypeFields(profileId, entry.docTypeId)
  const meta = entry.metadata

  // 1. Обязательные поля из профиля
  const requiredFields = fields.filter((f) => f.required)
  let filledRequired = 0
  for (const field of requiredFields) {
    const value = meta[field.key]?.trim()
    if (!value) {
      issues.push({
        field: field.key,
        label: field.label,
        severity: 'error',
        message: 'Обязательное поле не заполнено',
      })
    } else {
      filledRequired++
    }
  }

  // 2. Проверка типов полей
  for (const field of fields) {
    const value = meta[field.key]?.trim()
    if (!value) continue

    if (field.type === 'date' && !isValidDate(value)) {
      issues.push({
        field: field.key,
        label: field.label,
        severity: 'error',
        message: 'Некорректный формат даты',
      })
    }
    if (field.type === 'number' && isNaN(Number(value))) {
      issues.push({
        field: field.key,
        label: field.label,
        severity: 'error',
        message: 'Значение должно быть числом',
      })
    }
  }

  // 3. ИНН (если есть поле inn в metadata)
  const inn = meta.inn?.trim()
  if (inn && !validateInn(inn)) {
    issues.push({
      field: 'inn',
      label: 'ИНН',
      severity: 'warning',
      message: 'Некорректный ИНН (контрольная сумма не совпадает)',
    })
  }

  // 4. Сумма > 0
  const amount = meta.amount?.trim()
  if (amount && !isNaN(Number(amount)) && Number(amount) <= 0) {
    issues.push({
      field: 'amount',
      label: 'Сумма',
      severity: 'warning',
      message: 'Сумма должна быть больше 0',
    })
  }

  // 5. Юридические правила по docType
  if (entry.docTypeId && legalRules[entry.docTypeId]) {
    for (const rule of legalRules[entry.docTypeId]) {
      const value = meta[rule.field]?.trim()
      // Не дублируем ошибки required-полей
      const alreadyReported = issues.some((i) => i.field === rule.field)
      if (!value && !alreadyReported) {
        issues.push({
          field: rule.field,
          label: rule.label,
          severity: 'error',
          message: `Юридически обязательное поле для ${entry.docTypeId}`,
        })
      }
    }
  }

  // 6. Юридическая полнота для verified-перехода
  if (entry.docTypeId === 'unclassified-doc' || !entry.docTypeId) {
    issues.push({
      field: 'docTypeId',
      label: 'Тип документа',
      severity: 'warning',
      message: 'Тип документа не определён (нераспознанный)',
    })
  }

  // Completeness
  const totalRequired = requiredFields.length || 1
  const completeness = Math.round((filledRequired / totalRequired) * 100)

  return {
    isValid: !issues.some((i) => i.severity === 'error'),
    issues,
    completeness: requiredFields.length === 0 ? 100 : completeness,
  }
}
