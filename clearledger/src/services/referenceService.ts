/**
 * ReferenceService — CRUD справочников НСИ (контрагенты, организации, номенклатура, договоры).
 *
 * Dual-mode: localStorage (v0.2) / API (production).
 */

import type { Counterparty, Organization, Nomenclature, Contract } from '@/types'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import {
  getItem, setItem,
  counterpartiesKey, organizationsKey, nomenclatureKey, contractsKey,
} from './storage'
import { nanoid } from 'nanoid'
import { normalizeCounterparty, diceCoefficient } from '@/lib/textUtils'

// ============================================================
// localStorage helpers
// ============================================================

function loadList<T>(key: string): T[] {
  return getItem<T[]>(key, [])
}

function saveList<T>(key: string, items: T[]): void {
  setItem(key, items)
}

// ============================================================
// Counterparties
// ============================================================

export async function getCounterparties(companyId: string): Promise<Counterparty[]> {
  if (isApiEnabled()) {
    return get<Counterparty[]>('/api/references/counterparties', { company_id: companyId })
  }
  return loadList<Counterparty>(counterpartiesKey(companyId))
}

export async function getCounterparty(companyId: string, id: string): Promise<Counterparty | undefined> {
  const list = await getCounterparties(companyId)
  return list.find((c) => c.id === id)
}

export async function findCounterpartyByInn(companyId: string, inn: string): Promise<Counterparty | undefined> {
  const list = await getCounterparties(companyId)
  return list.find((c) => c.inn === inn)
}

export async function findCounterpartyByName(
  companyId: string,
  name: string,
  threshold = 0.6,
): Promise<{ counterparty: Counterparty; confidence: number } | undefined> {
  const list = await getCounterparties(companyId)
  const normalized = normalizeCounterparty(name)
  if (!normalized) return undefined

  let best: { counterparty: Counterparty; confidence: number } | undefined
  for (const cp of list) {
    // Точное совпадение по нормализованному имени
    const cpNorm = normalizeCounterparty(cp.name)
    if (cpNorm === normalized) return { counterparty: cp, confidence: 1 }

    // Проверяем алиасы
    for (const alias of cp.aliases) {
      if (normalizeCounterparty(alias) === normalized) return { counterparty: cp, confidence: 1 }
    }

    // Fuzzy match
    const score = diceCoefficient(cpNorm, normalized)
    if (score >= threshold && (!best || score > best.confidence)) {
      best = { counterparty: cp, confidence: score }
    }

    // Fuzzy по алиасам
    for (const alias of cp.aliases) {
      const aliasScore = diceCoefficient(normalizeCounterparty(alias), normalized)
      if (aliasScore >= threshold && (!best || aliasScore > best.confidence)) {
        best = { counterparty: cp, confidence: aliasScore }
      }
    }
  }
  return best
}

export async function createCounterparty(
  companyId: string,
  input: Omit<Counterparty, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<Counterparty> {
  if (isApiEnabled()) {
    return post<Counterparty>('/api/references/counterparties', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: Counterparty = {
    id: nanoid(),
    companyId,
    ...input,
    aliases: input.aliases ?? [],
    createdAt: now,
    updatedAt: now,
  }
  const list = loadList<Counterparty>(counterpartiesKey(companyId))
  list.push(item)
  saveList(counterpartiesKey(companyId), list)
  return item
}

export async function updateCounterparty(
  companyId: string,
  id: string,
  updates: Partial<Omit<Counterparty, 'id' | 'companyId' | 'createdAt'>>,
): Promise<Counterparty | undefined> {
  if (isApiEnabled()) {
    return patch<Counterparty>(`/api/references/counterparties/${id}`, updates)
  }
  const list = loadList<Counterparty>(counterpartiesKey(companyId))
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  saveList(counterpartiesKey(companyId), list)
  return list[idx]
}

export async function deleteCounterparty(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/counterparties/${id}`); return true } catch { return false }
  }
  const list = loadList<Counterparty>(counterpartiesKey(companyId))
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  saveList(counterpartiesKey(companyId), filtered)
  return true
}

export async function addCounterpartyAlias(companyId: string, id: string, alias: string): Promise<Counterparty | undefined> {
  const cp = await getCounterparty(companyId, id)
  if (!cp) return undefined
  const normalized = normalizeCounterparty(alias)
  // Проверяем что алиас не дублирует существующие
  const existing = cp.aliases.map(normalizeCounterparty)
  if (existing.includes(normalized) || normalizeCounterparty(cp.name) === normalized) return cp
  return updateCounterparty(companyId, id, { aliases: [...cp.aliases, alias] })
}

export async function mergeCounterparties(
  companyId: string,
  keepId: string,
  removeId: string,
): Promise<Counterparty | undefined> {
  const keep = await getCounterparty(companyId, keepId)
  const remove = await getCounterparty(companyId, removeId)
  if (!keep || !remove) return undefined

  // Объединяем алиасы + имя удаляемого
  const mergedAliases = [...new Set([
    ...keep.aliases,
    ...remove.aliases,
    remove.name,
    ...(remove.shortName ? [remove.shortName] : []),
  ])]

  await deleteCounterparty(companyId, removeId)
  return updateCounterparty(companyId, keepId, { aliases: mergedAliases })
}

/** Массовая замена/добавление контрагентов (для импорта) */
export async function upsertCounterparties(companyId: string, items: Counterparty[]): Promise<number> {
  const existing = await getCounterparties(companyId)
  const byInn = new Map(existing.map((c) => [`${c.inn}:${c.kpp || ''}`, c]))
  let added = 0
  const now = new Date().toISOString()

  for (const item of items) {
    const key = `${item.inn}:${item.kpp || ''}`
    const found = byInn.get(key)
    if (found) {
      // Обновляем существующий
      Object.assign(found, {
        name: item.name,
        shortName: item.shortName || found.shortName,
        type: item.type || found.type,
        kpp: item.kpp || found.kpp,
        aliases: [...new Set([...found.aliases, ...item.aliases])],
        updatedAt: now,
      })
    } else {
      const newItem: Counterparty = {
        ...item,
        id: item.id || nanoid(),
        companyId,
        aliases: item.aliases ?? [],
        createdAt: item.createdAt || now,
        updatedAt: now,
      }
      existing.push(newItem)
      byInn.set(key, newItem)
      added++
    }
  }

  saveList(counterpartiesKey(companyId), existing)
  return added
}

// ============================================================
// Organizations
// ============================================================

export async function getOrganizations(companyId: string): Promise<Organization[]> {
  if (isApiEnabled()) {
    return get<Organization[]>('/api/references/organizations', { company_id: companyId })
  }
  return loadList<Organization>(organizationsKey(companyId))
}

export async function getOrganization(companyId: string, id: string): Promise<Organization | undefined> {
  const list = await getOrganizations(companyId)
  return list.find((o) => o.id === id)
}

export async function findOrganizationByInn(companyId: string, inn: string): Promise<Organization | undefined> {
  const list = await getOrganizations(companyId)
  return list.find((o) => o.inn === inn)
}

export async function createOrganization(
  companyId: string,
  input: Omit<Organization, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<Organization> {
  if (isApiEnabled()) {
    return post<Organization>('/api/references/organizations', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: Organization = { id: nanoid(), companyId, ...input, createdAt: now, updatedAt: now }
  const list = loadList<Organization>(organizationsKey(companyId))
  list.push(item)
  saveList(organizationsKey(companyId), list)
  return item
}

export async function updateOrganization(
  companyId: string,
  id: string,
  updates: Partial<Omit<Organization, 'id' | 'companyId' | 'createdAt'>>,
): Promise<Organization | undefined> {
  if (isApiEnabled()) {
    return patch<Organization>(`/api/references/organizations/${id}`, updates)
  }
  const list = loadList<Organization>(organizationsKey(companyId))
  const idx = list.findIndex((o) => o.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  saveList(organizationsKey(companyId), list)
  return list[idx]
}

export async function deleteOrganization(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/organizations/${id}`); return true } catch { return false }
  }
  const list = loadList<Organization>(organizationsKey(companyId))
  const filtered = list.filter((o) => o.id !== id)
  if (filtered.length === list.length) return false
  saveList(organizationsKey(companyId), filtered)
  return true
}

export async function upsertOrganizations(companyId: string, items: Organization[]): Promise<number> {
  const existing = await getOrganizations(companyId)
  const byInn = new Map(existing.map((o) => [`${o.inn}:${o.kpp || ''}`, o]))
  let added = 0
  const now = new Date().toISOString()

  for (const item of items) {
    const key = `${item.inn}:${item.kpp || ''}`
    const found = byInn.get(key)
    if (found) {
      Object.assign(found, {
        name: item.name,
        ogrn: item.ogrn || found.ogrn,
        bankAccount: item.bankAccount || found.bankAccount,
        bankBik: item.bankBik || found.bankBik,
        updatedAt: now,
      })
    } else {
      const newItem: Organization = {
        ...item,
        id: item.id || nanoid(),
        companyId,
        createdAt: item.createdAt || now,
        updatedAt: now,
      }
      existing.push(newItem)
      byInn.set(key, newItem)
      added++
    }
  }

  saveList(organizationsKey(companyId), existing)
  return added
}

// ============================================================
// Nomenclature
// ============================================================

export async function getNomenclature(companyId: string): Promise<Nomenclature[]> {
  if (isApiEnabled()) {
    return get<Nomenclature[]>('/api/references/nomenclature', { company_id: companyId })
  }
  return loadList<Nomenclature>(nomenclatureKey(companyId))
}

export async function findNomenclatureByCode(companyId: string, code: string): Promise<Nomenclature | undefined> {
  const list = await getNomenclature(companyId)
  return list.find((n) => n.code === code)
}

export async function createNomenclature(
  companyId: string,
  input: Omit<Nomenclature, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<Nomenclature> {
  if (isApiEnabled()) {
    return post<Nomenclature>('/api/references/nomenclature', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: Nomenclature = { id: nanoid(), companyId, ...input, createdAt: now, updatedAt: now }
  const list = loadList<Nomenclature>(nomenclatureKey(companyId))
  list.push(item)
  saveList(nomenclatureKey(companyId), list)
  return item
}

export async function updateNomenclature(
  companyId: string,
  id: string,
  updates: Partial<Omit<Nomenclature, 'id' | 'companyId' | 'createdAt'>>,
): Promise<Nomenclature | undefined> {
  if (isApiEnabled()) {
    return patch<Nomenclature>(`/api/references/nomenclature/${id}`, updates)
  }
  const list = loadList<Nomenclature>(nomenclatureKey(companyId))
  const idx = list.findIndex((n) => n.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  saveList(nomenclatureKey(companyId), list)
  return list[idx]
}

export async function deleteNomenclature(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/nomenclature/${id}`); return true } catch { return false }
  }
  const list = loadList<Nomenclature>(nomenclatureKey(companyId))
  const filtered = list.filter((n) => n.id !== id)
  if (filtered.length === list.length) return false
  saveList(nomenclatureKey(companyId), filtered)
  return true
}

export async function upsertNomenclature(companyId: string, items: Nomenclature[]): Promise<number> {
  const existing = await getNomenclature(companyId)
  const byCode = new Map(existing.map((n) => [n.code, n]))
  let added = 0
  const now = new Date().toISOString()

  for (const item of items) {
    const found = byCode.get(item.code)
    if (found) {
      Object.assign(found, { name: item.name, unit: item.unit, unitLabel: item.unitLabel, vatRate: item.vatRate, updatedAt: now })
    } else {
      const newItem: Nomenclature = {
        ...item, id: item.id || nanoid(), companyId, createdAt: item.createdAt || now, updatedAt: now,
      }
      existing.push(newItem)
      byCode.set(item.code, newItem)
      added++
    }
  }

  saveList(nomenclatureKey(companyId), existing)
  return added
}

// ============================================================
// Contracts
// ============================================================

export async function getContracts(companyId: string): Promise<Contract[]> {
  if (isApiEnabled()) {
    return get<Contract[]>('/api/references/contracts', { company_id: companyId })
  }
  return loadList<Contract>(contractsKey(companyId))
}

export async function getContract(companyId: string, id: string): Promise<Contract | undefined> {
  const list = await getContracts(companyId)
  return list.find((c) => c.id === id)
}

export async function findContractByNumber(companyId: string, number: string): Promise<Contract | undefined> {
  const list = await getContracts(companyId)
  return list.find((c) => c.number === number)
}

export async function findContractsByCounterparty(companyId: string, counterpartyId: string): Promise<Contract[]> {
  const list = await getContracts(companyId)
  return list.filter((c) => c.counterpartyId === counterpartyId)
}

export async function createContract(
  companyId: string,
  input: Omit<Contract, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<Contract> {
  if (isApiEnabled()) {
    return post<Contract>('/api/references/contracts', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: Contract = { id: nanoid(), companyId, ...input, createdAt: now, updatedAt: now }
  const list = loadList<Contract>(contractsKey(companyId))
  list.push(item)
  saveList(contractsKey(companyId), list)
  return item
}

export async function updateContract(
  companyId: string,
  id: string,
  updates: Partial<Omit<Contract, 'id' | 'companyId' | 'createdAt'>>,
): Promise<Contract | undefined> {
  if (isApiEnabled()) {
    return patch<Contract>(`/api/references/contracts/${id}`, updates)
  }
  const list = loadList<Contract>(contractsKey(companyId))
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  saveList(contractsKey(companyId), list)
  return list[idx]
}

export async function deleteContract(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/contracts/${id}`); return true } catch { return false }
  }
  const list = loadList<Contract>(contractsKey(companyId))
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  saveList(contractsKey(companyId), filtered)
  return true
}

export async function upsertContracts(companyId: string, items: Contract[]): Promise<number> {
  const existing = await getContracts(companyId)
  const byId = new Map(existing.map((c) => [c.id, c]))
  let added = 0
  const now = new Date().toISOString()

  for (const item of items) {
    if (item.id && byId.has(item.id)) {
      const found = byId.get(item.id)!
      Object.assign(found, {
        number: item.number,
        date: item.date,
        counterpartyId: item.counterpartyId,
        organizationId: item.organizationId,
        type: item.type,
        amountLimit: item.amountLimit,
        updatedAt: now,
      })
    } else {
      const newItem: Contract = {
        ...item, id: item.id || nanoid(), companyId, createdAt: item.createdAt || now, updatedAt: now,
      }
      existing.push(newItem)
      byId.set(newItem.id, newItem)
      added++
    }
  }

  saveList(contractsKey(companyId), existing)
  return added
}

// ============================================================
// Статистика справочников
// ============================================================

export interface ReferenceStats {
  counterparties: number
  organizations: number
  nomenclature: number
  contracts: number
}

export async function getReferenceStats(companyId: string): Promise<ReferenceStats> {
  const [cp, org, nom, ctr] = await Promise.all([
    getCounterparties(companyId),
    getOrganizations(companyId),
    getNomenclature(companyId),
    getContracts(companyId),
  ])
  return {
    counterparties: cp.length,
    organizations: org.length,
    nomenclature: nom.length,
    contracts: ctr.length,
  }
}
