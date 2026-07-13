/**
 * ReferenceService — CRUD справочников НСИ (контрагенты, организации, номенклатура, договоры).
 *
 * Dual-mode: localStorage (v0.2) / API (production).
 */

import type {
  Counterparty, Organization, Nomenclature, Contract, Warehouse, BankAccount,
  CounterpartyBalance, ContractScopeType, LocationBrief, CounterpartyLocations,
  LocationContracts, ContractDimensions,
} from '@/types'
import type {
  StationSettlement, PaymentDisciplineSummary, SettlementDetail, SettlementRole,
  EnergyPeriodsSummary, ReestrModel,
} from '@/types/settlement'
import { isApiEnabled, get, post, patch, put, del, upload } from './apiClient'
import {
  counterpartiesKey, organizationsKey, nomenclatureKey, contractsKey,
  warehousesKey, bankAccountsKey, balancesKey,
} from './storage'
import { getItemIDB, setItemIDB } from './idbStorage'
import { nanoid } from 'nanoid'
import { normalizeCounterparty, diceCoefficient } from '@/lib/textUtils'

// ============================================================
// IndexedDB helpers (async, лимит сотни МБ)
// ============================================================

async function loadList<T>(key: string): Promise<T[]> {
  return getItemIDB<T[]>(key, [])
}

async function saveList<T>(key: string, items: T[]): Promise<void> {
  await setItemIDB(key, items)
}

// ============================================================
// Counterparties
// ============================================================

export async function getCounterparties(companyId: string): Promise<Counterparty[]> {
  if (isApiEnabled()) {
    return get<Counterparty[]>('/api/references/counterparties', { company_id: companyId })
  }
  return await loadList<Counterparty>(counterpartiesKey(companyId))
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
  const list = await loadList<Counterparty>(counterpartiesKey(companyId))
  list.push(item)
  await saveList(counterpartiesKey(companyId), list)
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
  const list = await loadList<Counterparty>(counterpartiesKey(companyId))
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(counterpartiesKey(companyId), list)
  return list[idx]
}

export async function deleteCounterparty(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/counterparties/${id}`); return true } catch { return false }
  }
  const list = await loadList<Counterparty>(counterpartiesKey(companyId))
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  await saveList(counterpartiesKey(companyId), filtered)
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

  await saveList(counterpartiesKey(companyId), existing)
  return added
}

// ============================================================
// Organizations
// ============================================================

export async function getOrganizations(companyId: string): Promise<Organization[]> {
  if (isApiEnabled()) {
    return get<Organization[]>('/api/references/organizations', { company_id: companyId })
  }
  return await loadList<Organization>(organizationsKey(companyId))
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
  const list = await loadList<Organization>(organizationsKey(companyId))
  list.push(item)
  await saveList(organizationsKey(companyId), list)
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
  const list = await loadList<Organization>(organizationsKey(companyId))
  const idx = list.findIndex((o) => o.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(organizationsKey(companyId), list)
  return list[idx]
}

export async function deleteOrganization(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/organizations/${id}`); return true } catch { return false }
  }
  const list = await loadList<Organization>(organizationsKey(companyId))
  const filtered = list.filter((o) => o.id !== id)
  if (filtered.length === list.length) return false
  await saveList(organizationsKey(companyId), filtered)
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

  await saveList(organizationsKey(companyId), existing)
  return added
}

// ============================================================
// Nomenclature
// ============================================================

export async function getNomenclature(companyId: string): Promise<Nomenclature[]> {
  if (isApiEnabled()) {
    return get<Nomenclature[]>('/api/references/nomenclature', { company_id: companyId })
  }
  return await loadList<Nomenclature>(nomenclatureKey(companyId))
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
  const list = await loadList<Nomenclature>(nomenclatureKey(companyId))
  list.push(item)
  await saveList(nomenclatureKey(companyId), list)
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
  const list = await loadList<Nomenclature>(nomenclatureKey(companyId))
  const idx = list.findIndex((n) => n.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(nomenclatureKey(companyId), list)
  return list[idx]
}

export async function deleteNomenclature(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/nomenclature/${id}`); return true } catch { return false }
  }
  const list = await loadList<Nomenclature>(nomenclatureKey(companyId))
  const filtered = list.filter((n) => n.id !== id)
  if (filtered.length === list.length) return false
  await saveList(nomenclatureKey(companyId), filtered)
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

  await saveList(nomenclatureKey(companyId), existing)
  return added
}

// ============================================================
// Contracts
// ============================================================

export async function getContracts(companyId: string): Promise<Contract[]> {
  if (isApiEnabled()) {
    return get<Contract[]>('/api/references/contracts', { company_id: companyId })
  }
  return await loadList<Contract>(contractsKey(companyId))
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
  const list = await loadList<Contract>(contractsKey(companyId))
  list.push(item)
  await saveList(contractsKey(companyId), list)
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
  const list = await loadList<Contract>(contractsKey(companyId))
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(contractsKey(companyId), list)
  return list[idx]
}

export async function deleteContract(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/contracts/${id}`); return true } catch { return false }
  }
  const list = await loadList<Contract>(contractsKey(companyId))
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  await saveList(contractsKey(companyId), filtered)
  return true
}

// ---- Ось договор↔торговые точки (Фаза 2; требует backend) ----

/** Установить охват договора: company | locations (+ набор точек) | unassigned. */
export async function setContractScope(
  contractId: string, scopeType: ContractScopeType, locationIds: string[] = [],
): Promise<Contract> {
  return put<Contract>(`/api/references/contracts/${contractId}/scope`, { scopeType, locationIds })
}

/** Точки конкретного договора (для scope=locations). */
export async function getContractLocations(contractId: string): Promise<LocationBrief[]> {
  if (!isApiEnabled()) return []
  return get<LocationBrief[]>(`/api/references/contracts/${contractId}/locations`)
}

/** Где работает контрагент — агрегат по его договорам. */
export async function getCounterpartyLocations(counterpartyId: string): Promise<CounterpartyLocations> {
  return get<CounterpartyLocations>(`/api/references/counterparties/${counterpartyId}/locations`)
}

/** Договоры точки: адресные + общекомпанейские. */
export async function getLocationContracts(locationId: string): Promise<LocationContracts> {
  return get<LocationContracts>(`/api/references/locations/${locationId}/contracts`)
}

// ---- Платёжная дисциплина (реестр «Договоры и оплаты ЭЗС», energy) ----

/** Записи платёжной дисциплины станции (для окна станции). */
export async function getLocationSettlements(
  companyId: string, locationId: string,
): Promise<StationSettlement[]> {
  if (!isApiEnabled()) return []
  return get<StationSettlement[]>('/api/references/settlements',
    { company_id: companyId, location_id: locationId })
}

/** Все записи платёжной дисциплины компании (для индикаторов в списке/карте). */
export async function getAllSettlements(companyId: string): Promise<StationSettlement[]> {
  if (!isApiEnabled()) return []
  return get<StationSettlement[]>('/api/references/settlements', { company_id: companyId })
}

/** Агрегат платёжной дисциплины (для витрин «Дебиторка»/«Энергозакупка»). */
export async function getPaymentDisciplineSummary(
  companyId: string,
): Promise<PaymentDisciplineSummary> {
  return get<PaymentDisciplineSummary>('/api/references/payment-discipline/summary',
    { company_id: companyId })
}

/** Детализация платёжной дисциплины (строки: станция×контрагент×договор×оплата). */
export async function getSettlementsDetail(
  companyId: string, role?: SettlementRole,
): Promise<SettlementDetail[]> {
  if (!isApiEnabled()) return []
  const params: Record<string, string> = { company_id: companyId }
  if (role) params.role = role
  return get<SettlementDetail[]>('/api/references/settlements/detail', params)
}

/** Входящая э/э по месяцам (объёмы/тарифы/стоимость) — витрина «Энергозакупка». */
export async function getEnergyPeriodsSummary(
  companyId: string, months = 24,
): Promise<EnergyPeriodsSummary> {
  if (!isApiEnabled()) {
    return { series: [], suppliers: [], totalKwh: 0, totalCostEst: null,
             stationsWithVolumes: 0, stationsWithTariff: 0, lastPeriod: null }
  }
  return get<EnergyPeriodsSummary>('/api/references/energy-periods/summary',
    { company_id: companyId, months: String(months) })
}

/** Модель нормализации канала реестров (потоки → сопряжение → L2-сущности). */
export async function getReestrModel(companyId: string): Promise<ReestrModel> {
  if (!isApiEnabled()) {
    return { streams: [], entities: [], orphans: [], objectsLinked: 0, objectsTotal: 0 }
  }
  return get<ReestrModel>('/api/references/reestr/model', { company_id: companyId })
}

/** Загрузить файл-таблицу (xlsx) как L1-сырьё источника. Возвращает source_id (SourceFile). */
export async function uploadTableFile(
  companyId: string, file: File,
): Promise<{ source_id: string }> {
  const fd = new FormData()
  fd.append('file', file)
  return upload<{ source_id: string }>(`/api/intake?company_id=${companyId}`, fd)
}

/** Грани договора по разрезам (номенклатура/каналы/…). */
export async function getContractDimensions(contractId: string): Promise<ContractDimensions> {
  if (!isApiEnabled()) return { dimensions: {} }
  return get<ContractDimensions>(`/api/references/contracts/${contractId}/dimensions`)
}

/** Заменить набор элементов разреза dim_type (пусто = снять ограничение). */
export async function setContractDimension(
  contractId: string, dimType: string, refs: string[],
): Promise<ContractDimensions> {
  return put<ContractDimensions>(
    `/api/references/contracts/${contractId}/dimensions/${dimType}`, { refs },
  )
}

/** Обратная навигация: договоры, ограниченные данным элементом разреза. */
export async function getDimensionContracts(
  companyId: string, dimType: string, dimRef: string,
): Promise<Contract[]> {
  if (!isApiEnabled()) return []
  return get<Contract[]>(
    `/api/references/dimensions/${encodeURIComponent(dimType)}/contracts`,
    { ref: dimRef, company_id: companyId },
  )
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

  await saveList(contractsKey(companyId), existing)
  return added
}

// ============================================================
// Warehouses (Склады / АЗС)
// ============================================================

export async function getWarehouses(companyId: string): Promise<Warehouse[]> {
  if (isApiEnabled()) {
    return get<Warehouse[]>('/api/references/warehouses', { company_id: companyId })
  }
  return await loadList<Warehouse>(warehousesKey(companyId))
}

export async function createWarehouse(
  companyId: string,
  input: Omit<Warehouse, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<Warehouse> {
  if (isApiEnabled()) {
    return post<Warehouse>('/api/references/warehouses', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: Warehouse = { id: nanoid(), companyId, ...input, createdAt: now, updatedAt: now }
  const list = await loadList<Warehouse>(warehousesKey(companyId))
  list.push(item)
  await saveList(warehousesKey(companyId), list)
  return item
}

export async function updateWarehouse(
  companyId: string,
  id: string,
  updates: Partial<Omit<Warehouse, 'id' | 'companyId' | 'createdAt'>>,
): Promise<Warehouse | undefined> {
  if (isApiEnabled()) {
    return patch<Warehouse>(`/api/references/warehouses/${id}`, updates)
  }
  const list = await loadList<Warehouse>(warehousesKey(companyId))
  const idx = list.findIndex((w) => w.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(warehousesKey(companyId), list)
  return list[idx]
}

export async function deleteWarehouse(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/warehouses/${id}`); return true } catch { return false }
  }
  const list = await loadList<Warehouse>(warehousesKey(companyId))
  const filtered = list.filter((w) => w.id !== id)
  if (filtered.length === list.length) return false
  await saveList(warehousesKey(companyId), filtered)
  return true
}

export async function upsertWarehouses(companyId: string, items: Warehouse[]): Promise<number> {
  const existing = await getWarehouses(companyId)
  const byCode = new Map(existing.map((w) => [w.code, w]))
  let added = 0
  const now = new Date().toISOString()
  for (const item of items) {
    const found = byCode.get(item.code)
    if (found) {
      if (isApiEnabled()) {
        await patch<Warehouse>(`/api/references/warehouses/${found.id}`, { name: item.name, address: item.address, type: item.type })
      } else {
        Object.assign(found, { name: item.name, address: item.address, type: item.type, updatedAt: now })
      }
    } else {
      if (isApiEnabled()) {
        await post<Warehouse>('/api/references/warehouses', { code: item.code, name: item.name, address: item.address, type: item.type, company_id: companyId })
      } else {
        const newItem: Warehouse = { ...item, id: item.id || nanoid(), companyId, createdAt: item.createdAt || now, updatedAt: now }
        existing.push(newItem)
        byCode.set(newItem.code, newItem)
      }
      added++
    }
  }
  if (!isApiEnabled()) {
    await saveList(warehousesKey(companyId), existing)
  }
  return added
}

// ============================================================
// BankAccounts (Банковские счета)
// ============================================================

export async function getBankAccounts(companyId: string): Promise<BankAccount[]> {
  if (isApiEnabled()) {
    return get<BankAccount[]>('/api/references/bank-accounts', { company_id: companyId })
  }
  return await loadList<BankAccount>(bankAccountsKey(companyId))
}

export async function createBankAccount(
  companyId: string,
  input: Omit<BankAccount, 'id' | 'companyId' | 'createdAt' | 'updatedAt'>,
): Promise<BankAccount> {
  if (isApiEnabled()) {
    return post<BankAccount>('/api/references/bank-accounts', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const item: BankAccount = { id: nanoid(), companyId, ...input, createdAt: now, updatedAt: now }
  const list = await loadList<BankAccount>(bankAccountsKey(companyId))
  list.push(item)
  await saveList(bankAccountsKey(companyId), list)
  return item
}

export async function updateBankAccount(
  companyId: string,
  id: string,
  updates: Partial<Omit<BankAccount, 'id' | 'companyId' | 'createdAt'>>,
): Promise<BankAccount | undefined> {
  if (isApiEnabled()) {
    return patch<BankAccount>(`/api/references/bank-accounts/${id}`, updates)
  }
  const list = await loadList<BankAccount>(bankAccountsKey(companyId))
  const idx = list.findIndex((b) => b.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, updatedAt: new Date().toISOString() }
  await saveList(bankAccountsKey(companyId), list)
  return list[idx]
}

export async function deleteBankAccount(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/references/bank-accounts/${id}`); return true } catch { return false }
  }
  const list = await loadList<BankAccount>(bankAccountsKey(companyId))
  const filtered = list.filter((b) => b.id !== id)
  if (filtered.length === list.length) return false
  await saveList(bankAccountsKey(companyId), filtered)
  return true
}

export async function upsertBankAccounts(companyId: string, items: BankAccount[]): Promise<number> {
  const existing = await getBankAccounts(companyId)
  const byNumber = new Map(existing.map((b) => [b.number, b]))
  let added = 0
  const now = new Date().toISOString()
  for (const item of items) {
    const found = byNumber.get(item.number)
    if (found) {
      const updates = {
        bankName: item.bankName || found.bankName,
        bik: item.bik || found.bik,
        corrAccount: item.corrAccount || found.corrAccount,
        currency: item.currency || found.currency,
        organizationId: item.organizationId || found.organizationId,
      }
      if (isApiEnabled()) {
        await patch<BankAccount>(`/api/references/bank-accounts/${found.id}`, updates)
      } else {
        Object.assign(found, { ...updates, updatedAt: now })
      }
    } else {
      if (isApiEnabled()) {
        await post<BankAccount>('/api/references/bank-accounts', { ...item, company_id: companyId })
      } else {
        const newItem: BankAccount = { ...item, id: item.id || nanoid(), companyId, createdAt: item.createdAt || now, updatedAt: now }
        existing.push(newItem)
        byNumber.set(newItem.number, newItem)
      }
      added++
    }
  }
  if (!isApiEnabled()) {
    await saveList(bankAccountsKey(companyId), existing)
  }
  return added
}

// ============================================================
// Пагинированный поиск (для страницы /1c/references)
// ============================================================

export interface ReferencesPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface RefSearchParams {
  q?: string
  limit?: number
  offset?: number
}

function buildSearchParams(companyId: string, params: RefSearchParams): Record<string, string | number | undefined> {
  return {
    company_id: companyId,
    q: params.q?.trim() || undefined,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  }
}

export async function searchCounterpartiesPaged(
  companyId: string,
  params: RefSearchParams = {},
): Promise<ReferencesPage<Counterparty>> {
  return get<ReferencesPage<Counterparty>>('/api/references/counterparties/search', buildSearchParams(companyId, params))
}

export async function searchOrganizationsPaged(
  companyId: string,
  params: RefSearchParams = {},
): Promise<ReferencesPage<Organization>> {
  return get<ReferencesPage<Organization>>('/api/references/organizations/search', buildSearchParams(companyId, params))
}

export async function searchNomenclaturePaged(
  companyId: string,
  params: RefSearchParams = {},
): Promise<ReferencesPage<Nomenclature>> {
  return get<ReferencesPage<Nomenclature>>('/api/references/nomenclature/search', buildSearchParams(companyId, params))
}

export async function searchWarehousesPaged(
  companyId: string,
  params: RefSearchParams = {},
): Promise<ReferencesPage<Warehouse>> {
  return get<ReferencesPage<Warehouse>>('/api/references/warehouses/search', buildSearchParams(companyId, params))
}

// ============================================================
// Статистика справочников
// ============================================================

export interface ReferenceStats {
  counterparties: number
  organizations: number
  nomenclature: number
  contracts: number
  warehouses: number
  bankAccounts: number
}

export async function getReferenceStats(companyId: string): Promise<ReferenceStats> {
  const [cp, org, nom, ctr, wh, ba] = await Promise.all([
    getCounterparties(companyId),
    getOrganizations(companyId),
    getNomenclature(companyId),
    getContracts(companyId),
    getWarehouses(companyId),
    getBankAccounts(companyId),
  ])
  return {
    counterparties: cp.length,
    organizations: org.length,
    nomenclature: nom.length,
    contracts: ctr.length,
    warehouses: wh.length,
    bankAccounts: ba.length,
  }
}

// ============================================================
// Balances (Сальдо взаиморасчётов)
// ============================================================

export async function getBalances(companyId: string): Promise<CounterpartyBalance[]> {
  if (isApiEnabled()) {
    return get<CounterpartyBalance[]>('/api/references/balances', { company_id: companyId })
  }
  return await loadList<CounterpartyBalance>(balancesKey(companyId))
}

/** Импорт сальдо — полная замена (каждая выгрузка содержит актуальный срез). */
export async function upsertBalances(companyId: string, items: CounterpartyBalance[]): Promise<number> {
  const now = new Date().toISOString()
  const withCompany = items.map((b) => ({
    ...b,
    id: b.id || nanoid(),
    companyId,
    importedAt: now,
  }))
  if (isApiEnabled()) {
    await post<CounterpartyBalance[]>('/api/references/balances/bulk', { items: withCompany, company_id: companyId })
  } else {
    await saveList(balancesKey(companyId), withCompany)
  }
  return withCompany.length
}
