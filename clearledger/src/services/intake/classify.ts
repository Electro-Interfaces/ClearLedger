/**
 * CLASSIFY — авто-классификация документов.
 * Rule-based: по имени файла, содержимому текста, типу файла.
 */

import type { IntakeClassification, IntakeFileType } from '@/types'

interface ClassifyInput {
  fileName: string
  fileType: IntakeFileType
  text: string
  mimeType: string
}

interface Rule {
  test: (input: ClassifyInput) => boolean
  result: Omit<IntakeClassification, 'metadata'> & { metaExtractors?: MetaExtractor[] }
}

type MetaExtractor = (text: string) => Record<string, string>

// ---- Regex экстракторы полей ----

function extractDocNumber(text: string): Record<string, string> {
  const match = text.match(/(?:№|номер|N)\s*([А-Яа-яA-Za-z0-9\/-]{1,30})/i)
  return match ? { docNumber: match[1].trim() } : {}
}

function extractDocDate(text: string): Record<string, string> {
  const match = text.match(/(\d{2}[.\/-]\d{2}[.\/-]\d{4})/)
  return match ? { docDate: match[1] } : {}
}

function extractAmount(text: string): Record<string, string> {
  const match = text.match(/(?:итого|сумма|к\s*оплате|всего)[:\s]*(\d[\d\s,.]*)\s*(?:руб|₽)?/i)
  if (match) {
    const val = match[1].replace(/\s/g, '').replace(',', '.')
    return { amount: val }
  }
  return {}
}

function extractInn(text: string): Record<string, string> {
  const match = text.match(/ИНН\s*(\d{10,12})/)
  return match ? { inn: match[1] } : {}
}

function extractCounterparty(text: string): Record<string, string> {
  const match = text.match(/(?:ООО|АО|ИП|ПАО|ЗАО|ОАО)\s*[«"]?([^»"\n]{3,50})/i)
  return match ? { counterparty: match[0].trim() } : {}
}

const commonExtractors: MetaExtractor[] = [
  extractDocNumber,
  extractDocDate,
  extractAmount,
  extractInn,
  extractCounterparty,
]

// ---- Правила классификации (по приоритету) ----

const rules: Rule[] = [
  // ТТН
  {
    test: ({ fileName, text }) =>
      /ттн|ttn|товарн.*транспорт/i.test(fileName) ||
      /товарно-транспортная\s+накладная/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'ttn',
      docTypeId: 'ttn-gsm',
      confidence: 85,
      title: 'ТТН',
    },
  },
  // Счёт-фактура (до счёта на оплату!)
  {
    test: ({ fileName, text }) =>
      /счёт.*фактур|счет.*фактур|sf/i.test(fileName) ||
      /счёт-фактура|счет-фактура/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'invoice-factura',
      confidence: 80,
      title: 'Счёт-фактура',
    },
  },
  // УПД
  {
    test: ({ fileName, text }) =>
      /упд|upd|универсальн.*передат/i.test(fileName) ||
      /универсальный\s+передаточный/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'upd',
      confidence: 85,
      title: 'УПД',
    },
  },
  // Счёт на оплату
  {
    test: ({ fileName, text }) =>
      /счёт|счет|invoice/i.test(fileName) ||
      /счёт\s*(на\s+оплату|№)/i.test(text) ||
      /счет\s*(на\s+оплату|№)/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'invoice',
      confidence: 75,
      title: 'Счёт на оплату',
    },
  },
  // Акт сверки
  {
    test: ({ fileName, text }) =>
      /акт.*сверк/i.test(fileName) ||
      /акт\s+сверки/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-reconciliation',
      confidence: 85,
      title: 'Акт сверки',
    },
  },
  // Акт приёма-передачи
  {
    test: ({ fileName, text }) =>
      /акт.*при[её]м/i.test(fileName) ||
      /акт\s+(?:приёма|приема)/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-acceptance',
      confidence: 80,
      title: 'Акт приёма-передачи',
    },
  },
  // Акт (общий)
  {
    test: ({ fileName, text }) =>
      /^акт|_акт|акт_/i.test(fileName) ||
      /акт\s+(выполненных|№)/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-work',
      confidence: 70,
      title: 'Акт',
    },
  },
  // Договор
  {
    test: ({ fileName, text }) =>
      /договор|contract/i.test(fileName) ||
      /договор\s+(№|поставки|аренды|оказания)/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'contracts',
      docTypeId: 'contract',
      confidence: 80,
      title: 'Договор',
    },
  },
  // Паспорт качества
  {
    test: ({ fileName, text }) =>
      /паспорт.*качеств/i.test(fileName) ||
      /паспорт\s+качества/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'quality',
      docTypeId: 'passport-quality',
      confidence: 85,
      title: 'Паспорт качества',
    },
  },
  // Изображения → медиа/фото (fallback для image)
  {
    test: ({ fileType }) => fileType === 'image',
    result: {
      categoryId: 'primary',
      subcategoryId: 'ttn',
      confidence: 40,
      title: 'Скан документа',
    },
  },
]

/** Классифицировать документ на основе правил */
export function classify(input: ClassifyInput): IntakeClassification {
  for (const rule of rules) {
    if (rule.test(input)) {
      // Извлекаем метаданные из текста
      const metadata: Record<string, string> = {}
      for (const extractor of (rule.result.metaExtractors ?? commonExtractors)) {
        Object.assign(metadata, extractor(input.text))
      }

      // Обогащаем title номером и датой если есть
      let title = rule.result.title
      if (metadata.docNumber) title += ` №${metadata.docNumber}`
      if (metadata.docDate) title += ` от ${metadata.docDate}`

      return {
        categoryId: rule.result.categoryId,
        subcategoryId: rule.result.subcategoryId,
        docTypeId: rule.result.docTypeId,
        confidence: rule.result.confidence,
        title,
        metadata,
      }
    }
  }

  // Fallback — не удалось классифицировать
  const metadata: Record<string, string> = {}
  for (const extractor of commonExtractors) {
    Object.assign(metadata, extractor(input.text))
  }

  return {
    categoryId: 'primary',
    subcategoryId: 'ttn',
    confidence: 20,
    title: input.fileName || 'Неизвестный документ',
    metadata,
  }
}
