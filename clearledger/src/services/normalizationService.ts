/**
 * NormalizationService — привязка строковых полей к справочникам НСИ.
 *
 * Обогащает metadata ключами _ref.* при нахождении совпадений.
 * Lazy: не перестраиваем старые записи, нормализуем при intake или по запросу.
 */

import type { DataEntry } from '@/types'
import {
  findCounterpartyByInn, findCounterpartyByName,
  findContractsByCounterparty, findOrganizationByInn,
} from './referenceService'
import { getCounterpartyFromMeta } from '@/lib/textUtils'

export interface NormalizationResult {
  enrichment: Record<string, string>
  matchConfidence: number
}

/**
 * Найти контрагента в справочнике по ИНН (точно) или имени (fuzzy).
 * Возвращает enrichment-ключи _ref.counterpartyId, _ref.matchConfidence и т.д.
 */
export async function resolveCounterparty(
  metadata: Record<string, string>,
  companyId: string,
): Promise<NormalizationResult> {
  const enrichment: Record<string, string> = {}
  let confidence = 0

  // 1. Точное сопоставление по ИНН
  const inn = metadata.inn?.trim()
  if (inn) {
    const cp = await findCounterpartyByInn(companyId, inn)
    if (cp) {
      enrichment['_ref.counterpartyId'] = cp.id
      enrichment['_ref.counterpartyName'] = cp.name
      if (cp.kpp) enrichment['_ref.counterpartyKpp'] = cp.kpp
      confidence = 1
      return { enrichment, matchConfidence: confidence }
    }
  }

  // 2. Fuzzy по имени
  const name = getCounterpartyFromMeta(metadata)
  if (name) {
    const result = await findCounterpartyByName(companyId, name)
    if (result) {
      enrichment['_ref.counterpartyId'] = result.counterparty.id
      enrichment['_ref.counterpartyName'] = result.counterparty.name
      if (result.counterparty.kpp) enrichment['_ref.counterpartyKpp'] = result.counterparty.kpp
      if (result.counterparty.inn) enrichment['_ref.counterpartyInn'] = result.counterparty.inn
      confidence = result.confidence
    }
  }

  return { enrichment, matchConfidence: confidence }
}

/**
 * Найти организацию в справочнике по ИНН.
 */
export async function resolveOrganization(
  metadata: Record<string, string>,
  companyId: string,
): Promise<Record<string, string>> {
  const enrichment: Record<string, string> = {}
  const orgInn = metadata.orgInn?.trim() || metadata.organizationInn?.trim()
  if (!orgInn) return enrichment

  const org = await findOrganizationByInn(companyId, orgInn)
  if (org) {
    enrichment['_ref.organizationId'] = org.id
    enrichment['_ref.organizationName'] = org.name
  }
  return enrichment
}

/**
 * Найти договор по номеру или привязке к контрагенту.
 */
export async function resolveContract(
  metadata: Record<string, string>,
  counterpartyId: string | undefined,
  companyId: string,
): Promise<Record<string, string>> {
  const enrichment: Record<string, string> = {}
  if (!counterpartyId) return enrichment

  const contracts = await findContractsByCounterparty(companyId, counterpartyId)
  if (contracts.length === 0) return enrichment

  const contractNum = metadata.contractNumber || metadata.parentDocNumber || metadata.docNumber
  if (contractNum) {
    const exact = contracts.find((c) => c.number === contractNum)
    if (exact) {
      enrichment['_ref.contractId'] = exact.id
      enrichment['_ref.contractNumber'] = exact.number
      if (exact.amountLimit) enrichment['_ref.contractAmountLimit'] = String(exact.amountLimit)
      return enrichment
    }
  }

  // Если один договор — привязываем
  if (contracts.length === 1) {
    enrichment['_ref.contractId'] = contracts[0].id
    enrichment['_ref.contractNumber'] = contracts[0].number
    if (contracts[0].amountLimit) enrichment['_ref.contractAmountLimit'] = String(contracts[0].amountLimit)
  }

  return enrichment
}

/**
 * Полное обогащение записи из справочников.
 */
export async function enrichFromReference(
  entry: DataEntry,
  companyId: string,
): Promise<Record<string, string>> {
  const cpResult = await resolveCounterparty(entry.metadata, companyId)
  const orgEnrich = await resolveOrganization(entry.metadata, companyId)
  const contractEnrich = await resolveContract(
    entry.metadata,
    cpResult.enrichment['_ref.counterpartyId'],
    companyId,
  )

  return {
    ...cpResult.enrichment,
    ...(cpResult.matchConfidence > 0 ? { '_ref.matchConfidence': String(cpResult.matchConfidence) } : {}),
    ...orgEnrich,
    ...contractEnrich,
  }
}
