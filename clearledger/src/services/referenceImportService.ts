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
import type { Counterparty, Organization, Nomenclature, Contract, CounterpartyType, Warehouse, BankAccount, WarehouseType } from '@/types'
import {
  upsertCounterparties,
  upsertOrganizations,
  upsertNomenclature,
  upsertContracts,
  upsertWarehouses,
  upsertBankAccounts,
  upsertBalances,
} from './referenceService'
import { nanoid } from 'nanoid'

export interface ImportResult {
  counterparties: { total: number; added: number }
  organizations: { total: number; added: number }
  nomenclature: { total: number; added: number }
  contracts: { total: number; added: number }
  warehouses: { total: number; added: number }
  bankAccounts: { total: number; added: number }
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
  warehouses: Warehouse[]
  bankAccounts: BankAccount[]
  errors: string[]
}

function parseEnterpriseDataXml(content: string): ParsedReferences {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    isArray: (name) => ['Контрагент', 'Организация', 'Номенклатура', 'ДоговорКонтрагента', 'Товар', 'Склад', 'БанковскийСчёт', 'БанковскийСчет'].includes(name),
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

  // ------- Склады -------
  const whNodes = ensureArray(root['Склад'] ?? root['Справочник.Склады'] ?? findDeep(root, 'Склад'))
  const warehouses: Warehouse[] = []
  for (const node of whNodes) {
    const code = str(node['Код'] || node['Code'])
    const name = str(node['Наименование'] || node['НаименованиеПолное'])
    if (!name) continue
    const typeStr = str(node['ТипСклада'] || node['Вид'] || '').toLowerCase()
    let whType: WarehouseType = 'warehouse'
    if (typeStr.includes('азс') || typeStr.includes('станци')) whType = 'station'
    else if (typeStr.includes('офис')) whType = 'office'
    warehouses.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '',
      code: code || nanoid().slice(0, 8),
      name,
      address: str(node['Адрес'] || node['ФактическийАдрес']) || undefined,
      type: whType,
      createdAt: now,
      updatedAt: now,
    })
  }

  // ------- Банковские счета -------
  const baNodes = ensureArray(root['БанковскийСчёт'] ?? root['БанковскийСчет'] ?? root['Справочник.БанковскиеСчета'] ?? findDeep(root, 'БанковскийСчёт'))
  const bankAccounts: BankAccount[] = []
  for (const node of baNodes) {
    const number = str(node['НомерСчета'] || node['Номер'])
    if (!number) continue
    bankAccounts.push({
      id: str(node['Ссылка'] || node['Ref'] || node['@_Ref']) || nanoid(),
      companyId: '',
      number,
      bankName: str(node['Банк'] || node['НаименованиеБанка'] || ''),
      bik: str(node['БИК'] || node['БИКБанка'] || ''),
      corrAccount: str(node['КоррСчёт'] || node['КоррСчет'] || node['КорреспондентскийСчёт']) || undefined,
      currency: str(node['ВалютаДенежныхСредств'] || node['Валюта'] || 'RUB'),
      organizationId: str(node['Владелец'] || node['Организация'] || node['ОрганизацияСсылка']) || undefined,
      createdAt: now,
      updatedAt: now,
    })
  }

  return { counterparties, organizations, nomenclature, contracts, warehouses, bankAccounts, errors }
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

  const warehouses: Warehouse[] = ensureArray(data.warehouses ?? data.sklady).map((w: Record<string, unknown>) => ({
    id: str(w.id || w.ref) || nanoid(),
    companyId: '',
    code: str(w.code || w.kod) || nanoid().slice(0, 8),
    name: str(w.name || w.naimenovanie),
    address: str(w.address || w.adres) || undefined,
    type: (str(w.type || w.vid) || 'warehouse') as WarehouseType,
    createdAt: str(w.createdAt) || now,
    updatedAt: now,
  })).filter((w: Warehouse) => w.name)

  const bankAccounts: BankAccount[] = ensureArray(data.bankAccounts ?? data.bankovskieScheta).map((b: Record<string, unknown>) => ({
    id: str(b.id || b.ref) || nanoid(),
    companyId: '',
    number: str(b.number || b.nomerScheta),
    bankName: str(b.bankName || b.naimenovanieBanka || ''),
    bik: str(b.bik || ''),
    corrAccount: str(b.corrAccount || b.korrSchet) || undefined,
    currency: str(b.currency || b.valuta || 'RUB'),
    organizationId: str(b.organizationId || b.organizaciyaRef) || undefined,
    createdAt: str(b.createdAt) || now,
    updatedAt: now,
  })).filter((b: BankAccount) => b.number)

  return { counterparties, organizations, nomenclature, contracts, warehouses, bankAccounts, errors }
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
        warehouses: { total: 0, added: 0 },
        bankAccounts: { total: 0, added: 0 },
        errors: ['Неизвестный формат файла. Поддерживаются: EnterpriseData XML, JSON.'],
      }
    }
  } catch (err) {
    return {
      counterparties: { total: 0, added: 0 },
      organizations: { total: 0, added: 0 },
      nomenclature: { total: 0, added: 0 },
      contracts: { total: 0, added: 0 },
      warehouses: { total: 0, added: 0 },
      bankAccounts: { total: 0, added: 0 },
      errors: [`Ошибка парсинга: ${err instanceof Error ? err.message : String(err)}`],
    }
  }

  errors.push(...parsed.errors)

  const [cpAdded, orgAdded, nomAdded, ctrAdded, whAdded, baAdded] = await Promise.all([
    parsed.counterparties.length > 0 ? upsertCounterparties(companyId, parsed.counterparties) : 0,
    parsed.organizations.length > 0 ? upsertOrganizations(companyId, parsed.organizations) : 0,
    parsed.nomenclature.length > 0 ? upsertNomenclature(companyId, parsed.nomenclature) : 0,
    parsed.contracts.length > 0 ? upsertContracts(companyId, parsed.contracts) : 0,
    parsed.warehouses.length > 0 ? upsertWarehouses(companyId, parsed.warehouses) : 0,
    parsed.bankAccounts.length > 0 ? upsertBankAccounts(companyId, parsed.bankAccounts) : 0,
  ])

  return {
    counterparties: { total: parsed.counterparties.length, added: cpAdded },
    organizations: { total: parsed.organizations.length, added: orgAdded },
    nomenclature: { total: parsed.nomenclature.length, added: nomAdded },
    contracts: { total: parsed.contracts.length, added: ctrAdded },
    warehouses: { total: parsed.warehouses.length, added: whAdded },
    bankAccounts: { total: parsed.bankAccounts.length, added: baAdded },
    errors,
  }
}

/** Сохранить снимок данных в IndexedDB (полная замена). */
async function saveSnapshot(companyId: string, key: string, data: unknown): Promise<void> {
  const { setItemIDB } = await import('./idbStorage')
  await setItemIDB(`clearledger-${key}-${companyId}`, data)
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

// ============================================================
// Импорт папки выгрузки 1С (множественные JSON-файлы)
// ============================================================

export interface FolderImportResult extends ImportResult {
  documents: { total: number; created: number; updated: number }
  balances: { total: number; imported: number }
  fixedAssets: { total: number; added: number }
  osv: { total: number }
  journal: { total: number }
  chartOfAccounts: { total: number }
  accountingPolicy: { total: number }
  filings: { total: number }
  meta: { exportDate: string; periodFrom: string; periodTo: string; source: string; version?: string } | null
}

export async function import1CExportFiles(companyId: string, files: File[]): Promise<FolderImportResult> {
  const { importAccountingDocs } = await import('./accountingDocService')
  const errors: string[] = []
  const result: FolderImportResult = {
    counterparties: { total: 0, added: 0 },
    organizations: { total: 0, added: 0 },
    nomenclature: { total: 0, added: 0 },
    contracts: { total: 0, added: 0 },
    warehouses: { total: 0, added: 0 },
    bankAccounts: { total: 0, added: 0 },
    documents: { total: 0, created: 0, updated: 0 },
    balances: { total: 0, imported: 0 },
    fixedAssets: { total: 0, added: 0 },
    osv: { total: 0 },
    journal: { total: 0 },
    chartOfAccounts: { total: 0 },
    accountingPolicy: { total: 0 },
    filings: { total: 0 },
    meta: null,
    errors: [],
  }

  for (const file of files) {
    try {
      const text = await readFileAsText(file)
      const data = JSON.parse(text)

      // meta.json — информация о выгрузке
      if (data.exportDate && data.source) {
        result.meta = {
          exportDate: data.exportDate,
          periodFrom: data.periodFrom ?? '',
          periodTo: data.periodTo ?? '',
          source: data.source,
        }
        continue
      }

      // documents.json — учётные документы
      if (data.documents && Array.isArray(data.documents)) {
        const docs = data.documents.map((d: Record<string, unknown>) => ({
          externalId: String(d.externalId ?? ''),
          docType: String(d.docType ?? 'receipt') as import('@/types').AccountingDocType,
          number: String(d.number ?? ''),
          date: String(d.date ?? ''),
          counterpartyName: String(d.counterpartyName ?? ''),
          counterpartyInn: String(d.counterpartyInn ?? ''),
          organizationName: String(d.organizationName ?? ''),
          amount: Number(d.amount ?? 0),
          vatAmount: undefined as number | undefined,
          status1c: String(d.status1c ?? d.posted ? 'Проведён' : 'Не проведён'),
          lines: Array.isArray(d.lines) ? d.lines.map((l: Record<string, unknown>) => ({
            nomenclatureName: String(l.nomenclatureName ?? ''),
            quantity: Number(l.quantity ?? 0),
            price: Number(l.price ?? 0),
            amount: Number(l.amount ?? 0),
            vatRate: Number(l.vatRate ?? 0),
            vatAmount: Number(l.vatAmount ?? 0),
          })) : [],
        }))
        const docResult = await importAccountingDocs(companyId, docs)
        result.documents = { total: docResult.total, created: docResult.created, updated: docResult.updated }
        errors.push(...docResult.errors)
        continue
      }

      // balances.json — сальдо взаиморасчётов
      if (data.balances && Array.isArray(data.balances)) {
        const balanceItems = data.balances.map((b: Record<string, unknown>) => ({
          id: '',
          companyId: '',
          account: String(b.account ?? ''),
          accountName: String(b.accountName ?? ''),
          counterpartyId: String(b.counterpartyId ?? ''),
          counterpartyName: String(b.counterpartyName ?? ''),
          counterpartyInn: String(b.counterpartyInn ?? ''),
          contractId: String(b.contractId ?? '') || undefined,
          contractName: String(b.contractName ?? '') || undefined,
          debitBalance: Number(b.debitBalance ?? 0),
          creditBalance: Number(b.creditBalance ?? 0),
          debitTurnover: Number(b.debitTurnover ?? 0),
          creditTurnover: Number(b.creditTurnover ?? 0),
          netBalance: Number(b.netBalance ?? 0),
          periodFrom: result.meta?.periodFrom ?? '',
          periodTo: result.meta?.periodTo ?? '',
          importedAt: '',
        }))
        const imported = await upsertBalances(companyId, balanceItems)
        result.balances = { total: balanceItems.length, imported }
        continue
      }

      // fixedAssets.json — основные средства
      if (data.fixedAssets && Array.isArray(data.fixedAssets)) {
        const items = data.fixedAssets as Record<string, unknown>[]
        await saveSnapshot(companyId, 'fixedAssets', data.fixedAssets)
        result.fixedAssets = { total: items.length, added: items.length }
        continue
      }

      // osv.json — оборотно-сальдовая ведомость
      if (data.accounts && Array.isArray(data.accounts) && data.periodFrom) {
        await saveSnapshot(companyId, 'osv', data)
        result.osv = { total: (data.accounts as unknown[]).length }
        continue
      }

      // journal.json — проводки
      if (data.entries && Array.isArray(data.entries) && data.periodFrom) {
        await saveSnapshot(companyId, 'journal', data)
        result.journal = { total: (data.entries as unknown[]).length }
        continue
      }

      // chartOfAccounts.json — план счетов
      if (data.chartOfAccounts && Array.isArray(data.chartOfAccounts)) {
        await saveSnapshot(companyId, 'chartOfAccounts', data.chartOfAccounts)
        result.chartOfAccounts = { total: (data.chartOfAccounts as unknown[]).length }
        continue
      }

      // accountingPolicy.json — учётная политика
      if (data.policies && Array.isArray(data.policies)) {
        await saveSnapshot(companyId, 'accountingPolicy', data.policies)
        result.accountingPolicy = { total: (data.policies as unknown[]).length }
        continue
      }

      // filings.json — регламентированная отчётность
      if (data.filings && Array.isArray(data.filings)) {
        await saveSnapshot(companyId, 'filings', data.filings)
        result.filings = { total: (data.filings as unknown[]).length }
        continue
      }

      // Справочники — через существующий importReferences
      const refResult = await importReferences(companyId, text)
      result.counterparties.total += refResult.counterparties.total
      result.counterparties.added += refResult.counterparties.added
      result.organizations.total += refResult.organizations.total
      result.organizations.added += refResult.organizations.added
      result.nomenclature.total += refResult.nomenclature.total
      result.nomenclature.added += refResult.nomenclature.added
      result.contracts.total += refResult.contracts.total
      result.contracts.added += refResult.contracts.added
      result.warehouses.total += refResult.warehouses.total
      result.warehouses.added += refResult.warehouses.added
      result.bankAccounts.total += refResult.bankAccounts.total
      result.bankAccounts.added += refResult.bankAccounts.added
      errors.push(...refResult.errors)

    } catch (err) {
      errors.push(`${file.name}: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  result.errors = errors
  return result
}
