/**
 * Генерация EnterpriseData XML — стандарт обмена 1С:Бухгалтерия 3.0.
 *
 * Пространство имён: http://v8.1c.ru/edi/edi_stnd/EnterpriseData/1.5
 * Порядок: сначала справочники (Контрагенты, Организации), потом документы.
 */

import type { DataEntry, Counterparty, Organization } from '@/types'
import { mapToOneCDocType, generate1CUuid } from './oneCMapping'
import { getCounterparties, getOrganizations } from './referenceService'
import { getCounterpartyFromMeta } from '@/lib/textUtils'

const NS = 'http://v8.1c.ru/edi/edi_stnd/EnterpriseData/1.5'
const XSI = 'http://www.w3.org/2001/XMLSchema-instance'

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function tag(name: string, value: string, indent = 6): string {
  return `${' '.repeat(indent)}<${name}>${esc(value)}</${name}>`
}

function formatDate(raw: string | undefined): string {
  if (!raw) return new Date().toISOString().slice(0, 10)
  // DD.MM.YYYY → YYYY-MM-DD
  const m = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
  if (m) return `${m[3]}-${m[2]}-${m[1]}`
  // Уже YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  return raw
}

// ============================================================
// Экспорт справочников
// ============================================================

function renderCounterparty(cp: Counterparty): string {
  const lines: string[] = []
  lines.push('    <Контрагент>')
  lines.push(tag('Ссылка', cp.id))
  lines.push(tag('Наименование', cp.shortName || cp.name))
  lines.push(tag('НаименованиеПолное', cp.name))
  lines.push(tag('ИНН', cp.inn))
  if (cp.kpp) lines.push(tag('КПП', cp.kpp))
  const vid = cp.type === 'ФЛ' ? 'ФизическоеЛицо' : cp.type === 'ИП' ? 'ИндивидуальныйПредприниматель' : 'ЮридическоеЛицо'
  lines.push(tag('ЮридическоеФизическоеЛицо', vid))
  lines.push('    </Контрагент>')
  return lines.join('\n')
}

function renderOrganization(org: Organization): string {
  const lines: string[] = []
  lines.push('    <Организация>')
  lines.push(tag('Ссылка', org.id))
  lines.push(tag('Наименование', org.name))
  lines.push(tag('ИНН', org.inn))
  if (org.kpp) lines.push(tag('КПП', org.kpp))
  if (org.ogrn) lines.push(tag('ОГРН', org.ogrn))
  if (org.bankAccount) lines.push(tag('НомерСчета', org.bankAccount))
  if (org.bankBik) lines.push(tag('БИК', org.bankBik))
  lines.push('    </Организация>')
  return lines.join('\n')
}

// ============================================================
// Экспорт документов
// ============================================================

function renderDocument(entry: DataEntry, counterpartyRef?: string, organizationRef?: string): string | null {
  const mapping = mapToOneCDocType(entry.docTypeId)
  if (!mapping) return null

  const meta = entry.metadata
  const docDate = formatDate(meta.docDate || meta.date)
  const docNumber = meta.docNumber || meta.number || entry.id
  const amount = meta.amount || '0'
  const uuid = meta['_1c.guid'] || generate1CUuid()

  const cpRef = counterpartyRef || meta['_ref.counterpartyId'] || ''
  const orgRef = organizationRef || meta['_ref.organizationId'] || ''
  const cpName = meta['_ref.counterpartyName'] || getCounterpartyFromMeta(meta)

  const lines: string[] = []
  lines.push(`    <${mapping.oneCDocType}>`)
  lines.push(tag('Ссылка', uuid))
  lines.push(tag('Дата', docDate))
  lines.push(tag('Номер', docNumber))
  lines.push(tag('СуммаДокумента', amount))

  // Контрагент
  if (cpRef) {
    lines.push('      <Контрагент>')
    lines.push(tag('Ссылка', cpRef, 8))
    if (cpName) lines.push(tag('Наименование', cpName, 8))
    if (meta.inn) lines.push(tag('ИНН', meta.inn, 8))
    lines.push('      </Контрагент>')
  }

  // Организация
  if (orgRef) {
    lines.push('      <Организация>')
    lines.push(tag('Ссылка', orgRef, 8))
    if (meta['_ref.organizationName']) lines.push(tag('Наименование', meta['_ref.organizationName'], 8))
    lines.push('      </Организация>')
  }

  // Дополнительные поля
  if (meta.amountVat || meta.nds) {
    lines.push(tag('СуммаНДС', meta.amountVat || meta.nds || '0'))
  }
  if (meta.currency) {
    lines.push(tag('Валюта', meta.currency))
  }

  // Комментарий / описание
  const comment = meta.verifyComment || entry.title
  lines.push(tag('Комментарий', comment))

  lines.push(`    </${mapping.oneCDocType}>`)
  return lines.join('\n')
}

// ============================================================
// Главная функция экспорта
// ============================================================

export interface EnterpriseDataExportResult {
  xml: string
  documentsExported: number
  counterpartiesExported: number
  organizationsExported: number
}

export async function generateEnterpriseDataXml(
  entries: DataEntry[],
  companyId: string,
): Promise<EnterpriseDataExportResult> {
  // Собираем уникальных контрагентов и организации из записей
  const usedCpIds = new Set<string>()
  const usedOrgIds = new Set<string>()

  for (const e of entries) {
    if (e.metadata['_ref.counterpartyId']) usedCpIds.add(e.metadata['_ref.counterpartyId'])
    if (e.metadata['_ref.organizationId']) usedOrgIds.add(e.metadata['_ref.organizationId'])
  }

  const allCounterparties = await getCounterparties(companyId)
  const allOrganizations = await getOrganizations(companyId)

  const exportedCps = allCounterparties.filter((cp) => usedCpIds.has(cp.id))
  const exportedOrgs = allOrganizations.filter((org) => usedOrgIds.has(org.id))

  // Генерируем XML
  const xmlParts: string[] = []
  xmlParts.push('<?xml version="1.0" encoding="UTF-8"?>')
  xmlParts.push(`<EnterpriseData xmlns="${NS}" xmlns:xsi="${XSI}">`)

  // 1. Справочники — контрагенты
  if (exportedCps.length > 0) {
    xmlParts.push('  <!-- Справочники: Контрагенты -->')
    for (const cp of exportedCps) {
      xmlParts.push(renderCounterparty(cp))
    }
  }

  // 2. Справочники — организации
  if (exportedOrgs.length > 0) {
    xmlParts.push('  <!-- Справочники: Организации -->')
    for (const org of exportedOrgs) {
      xmlParts.push(renderOrganization(org))
    }
  }

  // 3. Документы
  let documentsExported = 0
  xmlParts.push('  <!-- Документы -->')
  for (const entry of entries) {
    const xml = renderDocument(entry)
    if (xml) {
      xmlParts.push(xml)
      documentsExported++
    }
  }

  xmlParts.push('</EnterpriseData>')

  return {
    xml: xmlParts.join('\n'),
    documentsExported,
    counterpartiesExported: exportedCps.length,
    organizationsExported: exportedOrgs.length,
  }
}
