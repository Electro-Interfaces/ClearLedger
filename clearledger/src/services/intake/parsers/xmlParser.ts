/**
 * XML Parser — извлечение данных из 1С XML (CommerceML, EnterpriseData).
 * Парсит XML через fast-xml-parser, извлекает документы и ключевые поля.
 */

import { XMLParser } from 'fast-xml-parser'
import type { ExtractResult } from '../extract'

export async function parseXml(file: File): Promise<ExtractResult> {
  try {
    const raw = await file.text()
    const parser = new XMLParser({
      ignoreAttributes: false,
      attributeNamePrefix: '@_',
      textNodeName: '#text',
      trimValues: true,
    })
    const doc = parser.parse(raw)

    const metadata: Record<string, string> = {}
    const textParts: string[] = []

    // Определяем формат XML
    if (doc['КоммерческаяИнформация'] || doc.CommerceInformation) {
      parseCommerceML(doc['КоммерческаяИнформация'] ?? doc.CommerceInformation, metadata, textParts)
    } else if (doc['v8:EnterpriseData'] || doc.EnterpriseData) {
      parseEnterpriseData(doc['v8:EnterpriseData'] ?? doc.EnterpriseData, metadata, textParts)
    } else if (doc['Файл'] || doc['ФайлОбwormen']) {
      // Формат ФНС (XML счета-фактуры, УПД)
      parseFnsXml(doc['Файл'], metadata, textParts)
    } else {
      // Общий XML — извлекаем все текстовые значения
      parseGenericXml(doc, metadata, textParts, 0)
    }

    // Пробуем извлечь стандартные поля из всего текста
    const fullText = textParts.join('\n')
    extractCommonFields(fullText, raw, metadata)

    return { text: fullText, metadata }
  } catch (err) {
    console.error('XML parse error:', err)
    // Fallback: raw text
    try {
      const text = await file.text()
      return {
        text,
        metadata: { _extractError: `XML парсер: ${String(err)}` },
      }
    } catch {
      return { text: '', metadata: { _extractError: `XML парсер: ${String(err)}` } }
    }
  }
}

// ---- CommerceML (1С: Торговля, УТ, БП) ----

function parseCommerceML(
  root: Record<string, unknown>,
  metadata: Record<string, string>,
  textParts: string[],
) {
  metadata['_xml.format'] = 'CommerceML'

  // Документы
  const docs = getArray(root, 'Документ')
  if (docs.length > 0) {
    metadata['_xml.docsCount'] = String(docs.length)
    for (const doc of docs) {
      const d = doc as Record<string, unknown>
      const num = str(d['Номер'] ?? d['@_Номер'])
      const date = str(d['Дата'] ?? d['@_Дата'])
      const type = str(d['ХозОперация'] ?? d['ТипДокумента'] ?? d['Тип'])
      const sum = str(d['Сумма'])
      const counterparty = str(d['Контрагент']?.toString() ?? extractNested(d, 'Контрагенты', 'Контрагент', 'Наименование'))

      if (type) textParts.push(`Тип: ${type}`)
      if (num) { textParts.push(`Номер: ${num}`); metadata['docNumber'] = num }
      if (date) { textParts.push(`Дата: ${date}`); metadata['docDate'] = date }
      if (sum) { textParts.push(`Сумма: ${sum}`); metadata['amount'] = sum }
      if (counterparty) { textParts.push(`Контрагент: ${counterparty}`); metadata['counterparty'] = counterparty }

      // Товары/строки
      const items = getArray(d, 'Товары', 'Товар')
        .concat(getArray(d, 'Строки', 'Строка'))
      if (items.length > 0) {
        textParts.push(`Позиций: ${items.length}`)
        metadata['_xml.itemsCount'] = String(items.length)
      }
    }
  }

  // Каталог товаров
  const catalog = getArray(root, 'Каталог', 'Товары', 'Товар')
    .concat(getArray(root, 'Классификатор', 'Группы', 'Группа'))
  if (catalog.length > 0) {
    textParts.push(`Товаров в каталоге: ${catalog.length}`)
  }

  // Контрагенты
  const contragents = getArray(root, 'Контрагенты', 'Контрагент')
  for (const c of contragents) {
    const name = str((c as Record<string, unknown>)['Наименование'])
    const inn = str((c as Record<string, unknown>)['ИНН'])
    if (name) textParts.push(`Контрагент: ${name}`)
    if (inn) { textParts.push(`ИНН: ${inn}`); metadata['inn'] = inn }
  }
}

// ---- EnterpriseData (1С: выгрузка данных) ----

function parseEnterpriseData(
  root: Record<string, unknown>,
  metadata: Record<string, string>,
  textParts: string[],
) {
  metadata['_xml.format'] = 'EnterpriseData'

  // Документы различных типов
  const docTypes = [
    'ПриходнаяНакладная', 'РасходнаяНакладная', 'СчётФактура',
    'СчетФактура', 'АктВыполненныхРабот', 'ПлатежноеПоручение',
    'Документ', 'Document',
  ]

  for (const docType of docTypes) {
    const docs = getArray(root, docType)
    if (docs.length === 0) continue

    metadata['_xml.docType'] = docType
    metadata['_xml.docsCount'] = String(docs.length)
    textParts.push(`Тип: ${docType} (${docs.length} шт.)`)

    for (const doc of docs) {
      const d = doc as Record<string, unknown>
      extractDocFields(d, metadata, textParts)
    }
  }

  // Справочники
  const refs = getArray(root, 'Справочник')
    .concat(getArray(root, 'Catalog'))
  if (refs.length > 0) {
    textParts.push(`Справочники: ${refs.length} записей`)
  }
}

// ---- XML ФНС (электронные счета-фактуры, УПД) ----

function parseFnsXml(
  root: Record<string, unknown> | undefined,
  metadata: Record<string, string>,
  textParts: string[],
) {
  if (!root) return
  metadata['_xml.format'] = 'FNS'

  // Документ ФНС имеет вложенную структуру
  const doc = (root['Документ'] ?? root) as Record<string, unknown>
  const svSchFakt = doc['СвСчФакт'] as Record<string, unknown> | undefined
  const tablSchFakt = doc['ТаблСчФакт'] as Record<string, unknown> | undefined

  if (svSchFakt) {
    const num = str(svSchFakt['@_НомерСчФ'] ?? svSchFakt['НомерСчФ'])
    const date = str(svSchFakt['@_ДатаСчФ'] ?? svSchFakt['ДатаСчФ'])
    if (num) { metadata['docNumber'] = num; textParts.push(`Счёт-фактура №${num}`) }
    if (date) { metadata['docDate'] = date; textParts.push(`Дата: ${date}`) }

    // Продавец
    const seller = svSchFakt['СвПрод'] as Record<string, unknown> | undefined
    if (seller) {
      const name = str(extractNested(seller, 'ИдСв', 'СвЮЛУч', '@_НаимОрг'))
      const inn = str(extractNested(seller, 'ИдСв', 'СвЮЛУч', '@_ИННЮЛ'))
      if (name) { metadata['counterparty'] = name; textParts.push(`Продавец: ${name}`) }
      if (inn) { metadata['inn'] = inn; textParts.push(`ИНН: ${inn}`) }
    }
  }

  if (tablSchFakt) {
    const total = str(tablSchFakt['ВсегоОпл'] as string)
      ?? str((tablSchFakt['ВсегоОпл'] as Record<string, unknown>)?.['@_СтТовБезНДСВсего'])
    if (total) { metadata['amount'] = total; textParts.push(`Сумма: ${total}`) }

    const items = getArray(tablSchFakt, 'СведТов')
    if (items.length > 0) {
      textParts.push(`Позиций: ${items.length}`)
    }
  }
}

// ---- Generic XML ----

function parseGenericXml(
  obj: unknown,
  metadata: Record<string, string>,
  textParts: string[],
  depth: number,
) {
  if (depth > 5 || !obj) return

  if (typeof obj === 'string' || typeof obj === 'number') {
    const val = String(obj).trim()
    if (val.length > 2 && val.length < 200) {
      textParts.push(val)
    }
    return
  }

  if (Array.isArray(obj)) {
    for (const item of obj.slice(0, 50)) {
      parseGenericXml(item, metadata, textParts, depth + 1)
    }
    return
  }

  if (typeof obj === 'object') {
    for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
      if (key.startsWith('@_') || key === '#text') continue
      parseGenericXml(val, metadata, textParts, depth + 1)
    }
  }
}

// ---- Helpers ----

/** Извлечь стандартные поля из текста */
function extractCommonFields(
  text: string,
  raw: string,
  metadata: Record<string, string>,
) {
  // GUID 1С
  const guidMatch = raw.match(/[Gg]uid[>":\s]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i)
  if (guidMatch) metadata['_1c.guid'] = guidMatch[1]

  // ИНН (если ещё не нашли)
  if (!metadata['inn']) {
    const innMatch = text.match(/ИНН[:\s]*(\d{10,12})/)
    if (innMatch) metadata['inn'] = innMatch[1]
  }
}

function str(val: unknown): string {
  if (val === null || val === undefined) return ''
  return String(val).trim()
}

function getArray(obj: Record<string, unknown>, ...path: string[]): unknown[] {
  let current: unknown = obj
  for (const key of path) {
    if (!current || typeof current !== 'object') return []
    current = (current as Record<string, unknown>)[key]
  }
  if (!current) return []
  return Array.isArray(current) ? current : [current]
}

function extractDocFields(
  d: Record<string, unknown>,
  metadata: Record<string, string>,
  textParts: string[],
) {
  const num = str(d['Номер'] ?? d['Number'] ?? d['@_Номер'])
  const date = str(d['Дата'] ?? d['Date'] ?? d['@_Дата'])
  const sum = str(d['СуммаДокумента'] ?? d['Сумма'] ?? d['Amount'])
  const counterparty = str(d['Контрагент'] ?? d['Counterparty'])
  const guid = str(d['Ref'] ?? d['Ссылка'] ?? d['GUID'])

  if (num) { metadata['docNumber'] = num; textParts.push(`№ ${num}`) }
  if (date) { metadata['docDate'] = date; textParts.push(`Дата: ${date}`) }
  if (sum) { metadata['amount'] = sum; textParts.push(`Сумма: ${sum}`) }
  if (counterparty) { metadata['counterparty'] = counterparty; textParts.push(`Контрагент: ${counterparty}`) }
  if (guid) metadata['_1c.guid'] = guid
}

function extractNested(obj: Record<string, unknown>, ...path: string[]): unknown {
  let current: unknown = obj
  for (const key of path) {
    if (!current || typeof current !== 'object') return undefined
    current = (current as Record<string, unknown>)[key]
  }
  return current
}
