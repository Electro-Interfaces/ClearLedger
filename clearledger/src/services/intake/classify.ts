/**
 * CLASSIFY — авто-классификация документов.
 * Rule-based: по имени файла, содержимому текста, типу файла.
 * Profile-aware: правила зависят от профиля компании (fuel, trade, retail, energy, general).
 */

import type { IntakeClassification, IntakeFileType } from '@/types'
import type { ProfileId } from '@/config/profiles'
import { getProfile } from '@/config/profiles'

interface ClassifyInput {
  fileName: string
  fileType: IntakeFileType
  text: string
  mimeType: string
  profileId?: ProfileId
}

interface Rule {
  test: (input: ClassifyInput) => boolean
  /** Профили, для которых правило активно. undefined = все профили */
  profiles?: ProfileId[]
  result: Omit<IntakeClassification, 'metadata'> & {
    metaExtractors?: MetaExtractor[]
    /** Маппинг subcategoryId по профилю (если отличается от дефолтного) */
    profileOverrides?: Partial<Record<ProfileId, {
      categoryId?: string
      subcategoryId?: string
      docTypeId?: string
    }>>
  }
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
  // ТТН — только fuel
  {
    test: ({ fileName, text }) =>
      /ттн|ttn|товарн.*транспорт/i.test(fileName) ||
      /товарно-транспортная\s+накладная/i.test(text),
    profiles: ['fuel'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'ttn',
      docTypeId: 'ttn-gsm',
      confidence: 85,
      title: 'ТТН',
    },
  },
  // ТОРГ-12 — только trade
  {
    test: ({ fileName, text }) =>
      /торг.*12|torg.*12/i.test(fileName) ||
      /товарная\s+накладная|торг-12/i.test(text),
    profiles: ['trade'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'torg',
      docTypeId: 'torg-12',
      confidence: 85,
      title: 'ТОРГ-12',
    },
  },
  // Счёт-фактура (до счёта на оплату!) — fuel, trade, energy, general
  {
    test: ({ fileName, text }) =>
      /счёт.*фактур|счет.*фактур|sf/i.test(fileName) ||
      /счёт-фактура|счет-фактура/i.test(text),
    profiles: ['fuel', 'trade', 'energy', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'invoice-factura',
      confidence: 80,
      title: 'Счёт-фактура',
    },
  },
  // УПД — fuel, trade, general
  {
    test: ({ fileName, text }) =>
      /упд|upd|универсальн.*передат/i.test(fileName) ||
      /универсальный\s+передаточный/i.test(text),
    profiles: ['fuel', 'trade', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'upd',
      confidence: 85,
      title: 'УПД',
    },
  },
  // Счёт на оплату — fuel, trade, energy, general
  {
    test: ({ fileName, text }) =>
      /счёт|счет|invoice/i.test(fileName) ||
      /счёт\s*(на\s+оплату|№)/i.test(text) ||
      /счет\s*(на\s+оплату|№)/i.test(text),
    profiles: ['fuel', 'trade', 'energy', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'invoice',
      confidence: 75,
      title: 'Счёт на оплату',
    },
  },
  // Акт сверки — fuel, trade, energy, general
  {
    test: ({ fileName, text }) =>
      /акт.*сверк/i.test(fileName) ||
      /акт\s+сверки/i.test(text),
    profiles: ['fuel', 'trade', 'energy', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-reconciliation',
      confidence: 85,
      title: 'Акт сверки',
    },
  },
  // Акт приёма-передачи — fuel, trade, energy
  {
    test: ({ fileName, text }) =>
      /акт.*при[её]м/i.test(fileName) ||
      /акт\s+(?:приёма|приема)/i.test(text),
    profiles: ['fuel', 'trade', 'energy'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-acceptance',
      confidence: 80,
      title: 'Акт приёма-передачи',
      profileOverrides: {
        energy: { docTypeId: 'act-maintenance' },
      },
    },
  },
  // Акт (общий) — все профили кроме retail
  {
    test: ({ fileName, text }) =>
      /^акт|_акт|акт_/i.test(fileName) ||
      /акт\s+(выполненных|№)/i.test(text),
    profiles: ['fuel', 'trade', 'energy', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-work',
      confidence: 70,
      title: 'Акт',
    },
  },
  // Договор — все профили
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
  // Паспорт качества — только fuel
  {
    test: ({ fileName, text }) =>
      /паспорт.*качеств/i.test(fileName) ||
      /паспорт\s+качества/i.test(text),
    profiles: ['fuel'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'quality',
      docTypeId: 'passport-quality',
      confidence: 85,
      title: 'Паспорт качества',
    },
  },
  // ---- Email-правила ----

  // Email со счётом/актом во вложении или теме
  {
    test: ({ fileType, text }) =>
      fileType === 'email' && /счёт|счет|invoice|акт|act/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      confidence: 60,
      title: 'Email: документ',
      metaExtractors: [...commonExtractors, extractEmailFields],
    },
  },
  // Email общий
  {
    test: ({ fileType }) => fileType === 'email',
    result: {
      categoryId: 'primary',
      subcategoryId: 'unclassified',
      confidence: 30,
      title: 'Email',
      metaExtractors: [extractEmailFields],
    },
  },

  // ---- 1С XML правила ----

  // CommerceML — накладная / поступление
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' &&
      /CommerceML|КоммерческаяИнформация/i.test(text) &&
      /приходн|поступлен|накладн/i.test(text),
    profiles: ['fuel', 'trade', 'general'],
    result: {
      categoryId: 'primary',
      subcategoryId: 'ttn',
      confidence: 75,
      title: '1С: Накладная',
      profileOverrides: {
        trade: { subcategoryId: 'torg' },
      },
    },
  },
  // CommerceML / EnterpriseData — счёт-фактура
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' && /СчётФактура|СчетФактура|счёт-фактур|счет-фактур/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'invoice-factura',
      confidence: 80,
      title: '1С: Счёт-фактура',
    },
  },
  // XML ФНС (УПД, электронные СФ)
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' && /СвСчФакт|ФайлОбмен|format="FNS"|_xml\.format.*FNS/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'invoices',
      docTypeId: 'upd',
      confidence: 85,
      title: 'ФНС: Электронный документ',
    },
  },
  // CommerceML / EnterpriseData — платёжное поручение
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' && /ПлатежноеПоручение|платёжн|платежн/i.test(text),
    result: {
      categoryId: 'financial',
      subcategoryId: 'payments',
      confidence: 75,
      title: '1С: Платёжное поручение',
    },
  },
  // CommerceML / EnterpriseData — акт
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' && /АктВыполненныхРабот|акт\s+выполнен/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'acts',
      docTypeId: 'act-work',
      confidence: 75,
      title: '1С: Акт выполненных работ',
    },
  },
  // XML общий (1С формат, но тип не определён)
  {
    test: ({ fileType, text }) =>
      fileType === 'xml' &&
      /CommerceML|КоммерческаяИнформация|EnterpriseData|v8:/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'unclassified',
      confidence: 40,
      title: '1С: Документ',
    },
  },

  // ---- Excel-правила ----

  // Excel: реестр транзакций / Z-отчёт
  {
    test: ({ fileType, text }) =>
      (fileType === 'excel' || fileType === 'csv') &&
      /транзакц|терминал|z-отчёт|z-отчет|смен.*касс/i.test(text),
    profiles: ['fuel', 'trade', 'retail'],
    result: {
      categoryId: 'operational',
      subcategoryId: 'sales',
      confidence: 65,
      title: 'Реестр транзакций',
      profileOverrides: {
        fuel: { subcategoryId: 'sales' },
        retail: { subcategoryId: 'sales' },
      },
    },
  },
  // Excel: остатки
  {
    test: ({ fileType, text }) =>
      (fileType === 'excel' || fileType === 'csv') &&
      /остат.*резервуар|резервуар.*остат|остат.*ёмкост|остат.*емкост/i.test(text),
    profiles: ['fuel'],
    result: {
      categoryId: 'operational',
      subcategoryId: 'inventory',
      confidence: 70,
      title: 'Остатки в резервуарах',
    },
  },
  // Excel: банковская выписка
  {
    test: ({ fileType, text }) =>
      (fileType === 'excel' || fileType === 'csv') &&
      /дебет.*кредит|кредит.*дебет|сальдо|выписк/i.test(text),
    result: {
      categoryId: 'financial',
      subcategoryId: 'payments',
      confidence: 65,
      title: 'Банковская выписка',
    },
  },

  // ---- Чат-правила ----

  // WhatsApp/Telegram с упоминанием документов (счёт, акт, договор)
  {
    test: ({ fileType, text }) =>
      (fileType === 'whatsapp' || fileType === 'telegram') &&
      /счёт|счет|акт|договор|накладн|оплат|invoice/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'unclassified',
      confidence: 35,
      title: 'Чат: обсуждение документов',
      metaExtractors: [...commonExtractors, extractChatFields],
    },
  },
  // WhatsApp общий
  {
    test: ({ fileType }) => fileType === 'whatsapp',
    result: {
      categoryId: 'media',
      subcategoryId: 'photos',
      confidence: 25,
      title: 'Чат WhatsApp',
      metaExtractors: [extractChatFields],
    },
  },
  // Telegram общий
  {
    test: ({ fileType }) => fileType === 'telegram',
    result: {
      categoryId: 'media',
      subcategoryId: 'photos',
      confidence: 25,
      title: 'Чат Telegram',
      metaExtractors: [extractChatFields],
    },
  },

  // ---- OCR: изображение с текстом документа ----

  // Изображение с распознанным документом (ТТН, счёт, акт)
  {
    test: ({ fileType, text }) =>
      fileType === 'image' && text.length > 50 &&
      /товарно-транспортная|счёт-фактура|счет-фактура|акт\s+(сверки|выполненных|приёма)|упд|универсальный\s+передаточный/i.test(text),
    result: {
      categoryId: 'primary',
      subcategoryId: 'unclassified',
      confidence: 55,
      title: 'Скан документа (OCR)',
    },
  },
  // Изображение с текстом (OCR распознал что-то)
  {
    test: ({ fileType, text }) =>
      fileType === 'image' && text.length > 50,
    result: {
      categoryId: 'primary',
      subcategoryId: 'unclassified',
      confidence: 35,
      title: 'Скан (OCR)',
    },
  },
  // Изображение без текста
  {
    test: ({ fileType }) => fileType === 'image',
    result: {
      categoryId: 'media',
      subcategoryId: 'photos',
      confidence: 40,
      title: 'Фото',
    },
  },
]

// ---- Chat-специфичные экстракторы ----

function extractChatFields(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  const chatTypeMatch = text.match(/^Чат (WhatsApp|Telegram)/m)
  if (chatTypeMatch) result['_chat.type'] = chatTypeMatch[1].toLowerCase()
  const participantsMatch = text.match(/(\d+) участников?/m)
  if (participantsMatch) result['_chat.participantCount'] = participantsMatch[1]
  const messagesMatch = text.match(/(\d+) сообщений/m)
  if (messagesMatch) result['_chat.messageCount'] = messagesMatch[1]
  return result
}

// ---- Email-специфичные экстракторы ----

function extractEmailFields(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  const subjectMatch = text.match(/^Тема:\s*(.+)$/m)
  if (subjectMatch) result['_email.subject'] = subjectMatch[1].trim()
  const fromMatch = text.match(/^От:\s*(.+)$/m)
  if (fromMatch) result['_email.from'] = fromMatch[1].trim()
  const dateMatch = text.match(/^Дата:\s*(.+)$/m)
  if (dateMatch) result['_email.date'] = dateMatch[1].trim()
  return result
}

/** Получить fallback: подкатегория 'unclassified' в primary */
function getFallback(profileId: ProfileId): { categoryId: string; subcategoryId: string } {
  const profile = getProfile(profileId)
  // Ищем подкатегорию 'unclassified' в категории 'primary'
  const primaryCat = profile.categories.find((c) => c.id === 'primary')
  if (primaryCat?.subcategories.some((s) => s.id === 'unclassified')) {
    return { categoryId: 'primary', subcategoryId: 'unclassified' }
  }
  // Fallback на первую подкатегорию первой категории (если unclassified не найден)
  const firstCat = profile.categories[0]
  if (firstCat && firstCat.subcategories.length > 0) {
    return { categoryId: firstCat.id, subcategoryId: firstCat.subcategories[0].id }
  }
  return { categoryId: 'primary', subcategoryId: 'unclassified' }
}

/** Проверить, что subcategoryId существует в профиле */
function subcategoryExists(profileId: ProfileId, categoryId: string, subcategoryId: string): boolean {
  const profile = getProfile(profileId)
  const cat = profile.categories.find((c) => c.id === categoryId)
  if (!cat) return false
  return cat.subcategories.some((s) => s.id === subcategoryId)
}

/** Классифицировать документ на основе правил и профиля */
export function classify(input: ClassifyInput): IntakeClassification {
  const profileId = input.profileId ?? 'fuel'

  for (const rule of rules) {
    // Проверяем профиль
    if (rule.profiles && !rule.profiles.includes(profileId)) continue
    if (!rule.test(input)) continue

    // Извлекаем метаданные из текста
    const metadata: Record<string, string> = {}
    for (const extractor of (rule.result.metaExtractors ?? commonExtractors)) {
      Object.assign(metadata, extractor(input.text))
    }

    // Применяем profile override
    let { categoryId, subcategoryId, docTypeId } = rule.result
    const override = rule.result.profileOverrides?.[profileId]
    if (override) {
      if (override.categoryId) categoryId = override.categoryId
      if (override.subcategoryId) subcategoryId = override.subcategoryId
      if (override.docTypeId) docTypeId = override.docTypeId
    }

    // Проверяем что subcategory существует в текущем профиле
    if (!subcategoryExists(profileId, categoryId, subcategoryId)) {
      const fallback = getFallback(profileId)
      categoryId = fallback.categoryId
      subcategoryId = fallback.subcategoryId
      docTypeId = undefined
    }

    // Обогащаем title номером и датой если есть
    let title = rule.result.title
    if (metadata.docNumber) title += ` №${metadata.docNumber}`
    if (metadata.docDate) title += ` от ${metadata.docDate}`

    return {
      categoryId,
      subcategoryId,
      docTypeId,
      confidence: rule.result.confidence,
      title,
      metadata,
    }
  }

  // Fallback — не удалось классифицировать
  const metadata: Record<string, string> = {}
  for (const extractor of commonExtractors) {
    Object.assign(metadata, extractor(input.text))
  }

  const fallback = getFallback(profileId)
  return {
    categoryId: fallback.categoryId,
    subcategoryId: fallback.subcategoryId,
    confidence: 20,
    title: input.fileName || 'Неизвестный документ',
    metadata,
  }
}
