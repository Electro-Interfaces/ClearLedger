/**
 * Импорт справочников из 1С:Бухгалтерия.
 *
 * Поддерживаемые форматы:
 * 1. EnterpriseData XML (стандарт обмена 1С) — теги <Контрагент>, <Организация>, <ДоговорКонтрагента>, <Номенклатура>
 * 2. JSON (наш формат для REST-коннектора)
 *
 * Стратегия: merge по ИНН+КПП (обновить существующие, добавить новые).
 */

import { XMLParser } from 'fast-xml-parser'
import type { Counterparty, Organization, Nomenclature, Contract, CounterpartyType } from '@/types'
import {
  upsertCounterparties,
  upsertOrganizations,
  upsertNomenclature,
  upsertContracts,
} from './referenceService'
import { nanoid } from 'nanoid'

export interface ImportResult {
  counterparties: { total: number; added: number }
  organizations: { total: number; added: number }
  nomenclature: { total: number; added: number }
  contracts: { total: number; added: number }
  errors: string[]
}

// ============================================================
// Определение формата
// ============================================================

export function detectImportFormat(content: string): 'enterprise-data-xml' | 'json' | 'unknown' {
  const trimmed = content.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json'
  if (trimmed.startsWith('<?xml') || trimmed.startsWith('<')) {
    if (trimmed.includes('EnterpriseData') || trimmed.includes('Контрагент') || trimmed.includes('Организация')) {
      return 'enterprise-data-xml'
    }
  }
  return 'unknown'
}

// ============================================================
// Парсинг EnterpriseData XML
// ============================================================

function ensureArray<T>(val: T | T[] | undefined): T[] {
  if (!val) return []
  return Array.isArray(val) ? val : [val]
}

function str(val: unknown): string {
  if (val === undefined || val === null) return ''
  return String(val).trim()
}

function detectCounterpartyType(node: Record<string, unknown>): CounterpartyType {
  const yul = str(node['ЮридическоеФизическоеЛицо'] || node['ЮрФизЛицо'] || node['Вид'])
  if (yul.includes('Физ') || yul === 'ФизическоеЛицо') return 'ФЛ'
  if (yul.includes('Индивидуальный') || yul === 'ИндивидуальныйПредприниматель') return 'ИП'
  // По умолчанию или если "Юридическое лицо"
  return 'ЮЛ'
}

interface ParsedReferences {
  counterparties: Counterparty[]
  organizations: Organization[]
  nomenclature: Nomenclature[]
  contracts: Contract[]
  errors: string[]
}

function parseEnterpriseDataXml(content: string): ParsedReferences {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    isArray: (name) => ['Контрагент', 'Организация', 'Номенклатура', 'ДоговорКонтрагента', 'Товар'].includes(name),
  })

  const parsed = parser.parse(content)
  const errors: string[] = []
  const now = new Date().toISOString()

  // Ищем корневой элемент (может быть вложен)
  const root = parsed['EnterpriseData'] || parsed['ОбменДанными'] || parsed['Body'] || parsed

  // ------- Контрагенты -------
  const cpNodes = ensureArray(root['Контрагент'] ?? root['Справочник.Контрагенты'] ?? findDeep(root, 'Контрагент'))
  const counterparties: Counterparty[] = []
  for (const node of cpNodes) {
    const inn = str(node['ИНН'])
    const name = str(node['НаименованиеПолное'] || node['Наименование'] || node['Описание'])
    if (!inn && !name) { errors.push('Контрагент без ИНН и имени — пропущен'); continue }
    counterparties.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '', // будет установлен при upsert
      inn,
      kpp: str(node['КПП']) || undefined,
      name,
      shortName: str(node['Наименование'] || node['НаименованиеСокращённое']) || undefined,
      type: detectCounterpartyType(node as Record<string, unknown>),
      aliases: [],
      createdAt: now,
      updatedAt: now,
    })
  }

  // ------- Организации -------
  const orgNodes = ensureArray(root['Организация'] ?? root['Справочник.Организации'] ?? findDeep(root, 'Организация'))
  const organizations: Organization[] = []
  for (const node of orgNodes) {
    const inn = str(node['ИНН'])
    const name = str(node['НаименованиеПолное'] || node['Наименование'])
    if (!inn && !name) { errors.push('Организация без ИНН и имени — пропущена'); continue }
    organizations.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '',
      inn,
      kpp: str(node['КПП']) || undefined,
      ogrn: str(node['ОГРН'] || node['ОсновнойГосРегНомер']) || undefined,
      name,
      bankAccount: str(node['НомерСчета'] || node['РасчётныйСчёт']) || undefined,
      bankBik: str(node['БИК']) || undefined,
      createdAt: now,
      updatedAt: now,
    })
  }

  // ------- Номенклатура -------
  const nomNodes = ensureArray(root['Номенклатура'] ?? root['Справочник.Номенклатура'] ?? root['Товар'] ?? findDeep(root, 'Номенклатура'))
  const nomenclature: Nomenclature[] = []
  for (const node of nomNodes) {
    const code = str(node['Код'] || node['Артикул'] || node['Code'])
    const name = str(node['НаименованиеПолное'] || node['Наименование'])
    if (!name) continue
    nomenclature.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '',
      code: code || nanoid().slice(0, 8),
      name,
      unit: str(node['КодОКЕИ'] || node['ЕдиницаИзмерения']?.['КодОКЕИ'] || '796'),
      unitLabel: str(node['НаименованиеЕдиницыИзмерения'] || node['ЕдиницаИзмерения']?.['Наименование'] || 'шт'),
      vatRate: parseFloat(str(node['СтавкаНДС'] || node['НДС'] || '20')) || 20,
      createdAt: now,
      updatedAt: now,
    })
  }

  // ------- Договоры -------
  const ctrNodes = ensureArray(root['ДоговорКонтрагента'] ?? root['Справочник.ДоговорыКонтрагентов'] ?? findDeep(root, 'ДоговорКонтрагента'))
  const contracts: Contract[] = []
  for (const node of ctrNodes) {
    const number = str(node['Номер'] || node['НомерДоговора'])
    const counterpartyRef = str(node['Владелец'] || node['Контрагент'] || node['КонтрагентСсылка'])
    const orgRef = str(node['Организация'] || node['ОрганизацияСсылка'])
    contracts.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '',
      number: number || 'б/н',
      date: str(node['Дата'] || node['ДатаНачала'] || node['ДатаДоговора']),
      counterpartyId: counterpartyRef,
      organizationId: orgRef,
      type: str(node['ВидДоговора'] || node['Тип'] || 'Прочее'),
      amountLimit: node['СуммаДоговора'] ? parseFloat(str(node['СуммаДоговора'])) : undefined,
      createdAt: now,
      updatedAt: now,
    })
  }

  return { counterparties, organizations, nomenclature, contracts, errors }
}

/** Рекурсивный поиск ключа в дереве */
function findDeep(obj: Record<string, unknown>, key: string): unknown[] {
  const results: unknown[] = []
  for (const k of Object.keys(obj)) {
    if (k === key) {
      const val = obj[k]
      if (Array.isArray(val)) results.push(...val)
      else if (val) results.push(val)
    } else if (typeof obj[k] === 'object' && obj[k] !== null) {
      results.push(...findDeep(obj[k] as Record<string, unknown>, key))
    }
  }
  return results
}

// ============================================================
// Парсинг JSON
// ============================================================

function parseJsonImport(content: string): ParsedReferences {
  const data = JSON.parse(content)
  const errors: string[] = []
  const now = new Date().toISOString()

  // Формат: { counterparties: [...], organizations: [...], ... }
  // или массив с полем `_type`
  const counterparties: Counterparty[] = ensureArray(data.counterparties ?? data.kontragenty).map((c: Record<string, unknown>) => ({
    id: str(c.id || c.ref) || nanoid(),
    companyId: '',
    inn: str(c.inn),
    kpp: str(c.kpp) || undefined,
    name: str(c.name || c.fullName || c.naimenovanie),
    shortName: str(c.shortName || c.naimenovanieSokr) || undefined,
    type: (str(c.type || c.vid) || 'ЮЛ') as CounterpartyType,
    aliases: Array.isArray(c.aliases) ? c.aliases.map(String) : [],
    createdAt: str(c.createdAt) || now,
    updatedAt: now,
  })).filter((c: Counterparty) => c.inn || c.name)

  const organizations: Organization[] = ensureArray(data.organizations ?? data.organizacii).map((o: Record<string, unknown>) => ({
    id: str(o.id || o.ref) || nanoid(),
    companyId: '',
    inn: str(o.inn),
    kpp: str(o.kpp) || undefined,
    ogrn: str(o.ogrn) || undefined,
    name: str(o.name || o.fullName || o.naimenovanie),
    bankAccount: str(o.bankAccount || o.raschetnySchet) || undefined,
    bankBik: str(o.bankBik || o.bik) || undefined,
    createdAt: str(o.createdAt) || now,
    updatedAt: now,
  })).filter((o: Organization) => o.inn || o.name)

  const nomenclature: Nomenclature[] = ensureArray(data.nomenclature ?? data.nomenklatura).map((n: Record<string, unknown>) => ({
    id: str(n.id || n.ref) || nanoid(),
    companyId: '',
    code: str(n.code || n.kod) || nanoid().slice(0, 8),
    name: str(n.name || n.naimenovanie),
    unit: str(n.unit || n.kodOKEI || '796'),
    unitLabel: str(n.unitLabel || n.edinica || 'шт'),
    vatRate: typeof n.vatRate === 'number' ? n.vatRate : parseFloat(str(n.vatRate || n.stavkaNDS || '20')) || 20,
    createdAt: str(n.createdAt) || now,
    updatedAt: now,
  })).filter((n: Nomenclature) => n.name)

  const contracts: Contract[] = ensureArray(data.contracts ?? data.dogovory).map((c: Record<string, unknown>) => ({
    id: str(c.id || c.ref) || nanoid(),
    companyId: '',
    number: str(c.number || c.nomer) || 'б/н',
    date: str(c.date || c.data),
    counterpartyId: str(c.counterpartyId || c.kontragentRef),
    organizationId: str(c.organizationId || c.organizaciyaRef),
    type: str(c.type || c.vid || 'Прочее'),
    amountLimit: typeof c.amountLimit === 'number' ? c.amountLimit : undefined,
    createdAt: str(c.createdAt) || now,
    updatedAt: now,
  }))

  return { counterparties, organizations, nomenclature, contracts, errors }
}

// ============================================================
// Главная функция импорта
// ============================================================

export async function importReferences(companyId: string, content: string): Promise<ImportResult> {
  const format = detectImportFormat(content)
  const errors: string[] = []

  let parsed: ParsedReferences
  try {
    if (format === 'enterprise-data-xml') {
      parsed = parseEnterpriseDataXml(content)
    } else if (format === 'json') {
      parsed = parseJsonImport(content)
    } else {
      return {
        counterparties: { total: 0, added: 0 },
        organizations: { total: 0, added: 0 },
        nomenclature: { total: 0, added: 0 },
        contracts: { total: 0, added: 0 },
        errors: ['Неизвестный формат файла. Поддерживаются: EnterpriseData XML, JSON.'],
      }
    }
  } catch (err) {
    return {
      counterparties: { total: 0, added: 0 },
      organizations: { total: 0, added: 0 },
      nomenclature: { total: 0, added: 0 },
      contracts: { total: 0, added: 0 },
      errors: [`Ошибка парсинга: ${err instanceof Error ? err.message : String(err)}`],
    }
  }

  errors.push(...parsed.errors)

  const [cpAdded, orgAdded, nomAdded, ctrAdded] = await Promise.all([
    parsed.counterparties.length > 0 ? upsertCounterparties(companyId, parsed.counterparties) : 0,
    parsed.organizations.length > 0 ? upsertOrganizations(companyId, parsed.organizations) : 0,
    parsed.nomenclature.length > 0 ? upsertNomenclature(companyId, parsed.nomenclature) : 0,
    parsed.contracts.length > 0 ? upsertContracts(companyId, parsed.contracts) : 0,
  ])

  return {
    counterparties: { total: parsed.counterparties.length, added: cpAdded },
    organizations: { total: parsed.organizations.length, added: orgAdded },
    nomenclature: { total: parsed.nomenclature.length, added: nomAdded },
    contracts: { total: parsed.contracts.length, added: ctrAdded },
    errors,
  }
}

/** Прочитать файл как текст */
export function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('Не удалось прочитать файл'))
    reader.readAsText(file, 'utf-8')
  })
}
