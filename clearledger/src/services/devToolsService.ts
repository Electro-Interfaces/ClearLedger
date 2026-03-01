/**
 * Dev Tools — ядро.
 * Утилиты для разработки: генерация данных, сброс seed, статистика.
 * Используется только в dev-режиме (import.meta.env.DEV).
 */

import type { EntryStatus } from '@/config/statuses'
import type { DataEntry, DocPurpose, SyncStatus, DocumentLink, AccountingDoc, AccountingDocLine, AccountingDocType } from '@/types'
import { getItem, setItem, removeItem, entriesKey, accountingDocsKey } from './storage'
import { getItemIDB, setItemIDB } from './idbStorage'
import { getEntries, createEntry, seedIfNeeded } from './dataEntryService'
import { getConnectors } from './connectorService'
import { runReconciliation } from './accountingDocService'
import { getAllDocumentTypes } from '@/config/categories'
import { defaultCompanies } from '@/config/companies'
import { resolveRole } from './bundleService'
import { nanoid } from 'nanoid'
import type { ProfileId } from '@/config/profiles'

// ---- Константы ----

const SEED_KEY = 'clearledger-seeded'
const LS_PREFIX = 'clearledger-'

const ALL_STATUSES: EntryStatus[] = ['new', 'recognized', 'verified', 'transferred', 'error']
const ALL_SOURCES: DataEntry['source'][] = [
  'upload', 'photo', 'manual', 'api', 'email', 'oneC', 'whatsapp', 'telegram', 'paste',
]

const SOURCE_LABELS: Record<string, string> = {
  upload: 'Загрузка',
  photo: 'Фото',
  manual: 'Ручной ввод',
  api: 'API',
  email: 'Email',
  oneC: '1С',
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  paste: 'Вставка',
}

const COUNTERPARTIES_BY_PROFILE: Record<string, string[]> = {
  fuel: [
    'ООО "Лукойл"', 'ПАО "Газпром нефть"', 'АО "Роснефть"', 'ООО "Башнефть"',
    'АО "Сургутнефтегаз"', 'ПАО "Татнефть"', 'ООО "ТрансНефть"', 'ООО "Славнефть"',
    'ИП Иванов А.А.', 'ООО "Нефтесервис"',
  ],
  trade: [
    'ООО "ТоргСервис"', 'АО "Мегаполис"', 'ИП Сидоров В.П.', 'ООО "ОптТорг"',
    'ПАО "Магнит"', 'ООО "Дистрибьютор"', 'АО "ТрейдГрупп"', 'ООО "Поставщик Плюс"',
    'ИП Козлова Е.А.', 'ООО "СнабКомплект"',
  ],
  retail: [
    'ООО "Пятёрочка"', 'АО "Дикси"', 'ООО "Лента"', 'ИП Морозова Н.С.',
    'ООО "Фреш Маркет"', 'ПАО "Перекрёсток"', 'ООО "ПродТорг"', 'АО "Ашан"',
    'ИП Белов Д.М.', 'ООО "Розница 24"',
  ],
  energy: [
    'ПАО "РусГидро"', 'ПАО "Россети"', 'АО "Мосэнерго"', 'ООО "ЭнергоСбыт"',
    'ПАО "Интер РАО"', 'АО "ФСК ЕЭС"', 'ООО "ТГК-1"', 'АО "Энергоатом"',
    'ИП Волков С.А.', 'ООО "ЭлектроМонтаж"',
  ],
  general: [
    'ООО "Альфа"', 'АО "Бета Групп"', 'ИП Петров А.И.', 'ООО "Дельта"',
    'ПАО "Гамма"', 'ООО "Консалт Про"', 'АО "Сервис Плюс"', 'ИП Смирнова О.В.',
    'ООО "Стандарт"', 'АО "Партнёр"',
  ],
}

// ---- Утилиты ----

function randomItem<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

function randomDate(daysBack: number): string {
  const now = Date.now()
  const offset = Math.random() * daysBack * 24 * 60 * 60 * 1000
  return new Date(now - offset).toISOString()
}

function getAllClearledgerKeys(): string[] {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key?.startsWith(LS_PREFIX)) keys.push(key)
  }
  return keys
}

/** Генерация 10-значного ИНН (случайный) */
function generateInn(): string {
  let inn = ''
  for (let i = 0; i < 10; i++) inn += String(Math.floor(Math.random() * 10))
  return inn
}

// ---- Маппинг docTypeId → AccountingDocType ----

const DOC_TYPE_TO_ACCOUNTING: Record<string, AccountingDocType> = {
  'ttn-gsm': 'receipt',
  'supply-invoice': 'receipt',
  'torg-12': 'receipt',
  'upd': 'receipt',
  'invoice-factura': 'invoice-received',
  'invoice': 'invoice-received',
  'payment': 'payment-out',
  'payment-order': 'payment-out',
  'act-work': 'sales',
  'act-acceptance': 'sales',
  'act-reconciliation': 'reconciliation',
}

// ---- Номенклатура для AccountingDocLine ----

const NOMENCLATURE_POOL = [
  { name: 'Бензин АИ-92', unit: 'л', price: 52.30 },
  { name: 'Бензин АИ-95', unit: 'л', price: 56.80 },
  { name: 'Дизельное топливо', unit: 'л', price: 58.20 },
  { name: 'Масло моторное 5W-40', unit: 'шт', price: 2400 },
  { name: 'Антифриз G12+', unit: 'л', price: 450 },
  { name: 'Фильтр масляный', unit: 'шт', price: 780 },
  { name: 'Услуги по ТО', unit: 'усл', price: 5000 },
  { name: 'Транспортные услуги', unit: 'усл', price: 15000 },
  { name: 'Аренда оборудования', unit: 'мес', price: 25000 },
  { name: 'Канцтовары', unit: 'комп', price: 3200 },
]

function generateLines(totalAmount: number): AccountingDocLine[] {
  const count = randomInt(1, 3)
  const lines: AccountingDocLine[] = []
  let remaining = totalAmount

  for (let i = 0; i < count; i++) {
    const nom = randomItem(NOMENCLATURE_POOL)
    const isLast = i === count - 1
    const lineAmount = isLast ? remaining : Math.round(remaining * (0.3 + Math.random() * 0.4) * 100) / 100
    remaining -= lineAmount
    const qty = Math.max(1, Math.round(lineAmount / nom.price))
    const price = Math.round((lineAmount / qty) * 100) / 100
    const vatRate = randomItem([0, 10, 20])
    const vatAmount = Math.round(lineAmount * vatRate / (100 + vatRate) * 100) / 100

    lines.push({
      nomenclatureName: nom.name,
      quantity: qty,
      price,
      amount: Math.round(lineAmount * 100) / 100,
      vatRate,
      vatAmount,
    })
  }

  return lines
}

// ---- Публичные функции ----

/** Результат генерации документов 1С */
export interface GenerateAccountingDocsResult {
  total: number
  matched: number
  unmatched: number
  discrepancy: number
}

/** Генерация AccountingDoc[] из существующих DataEntry + автозапуск сверки */
export async function generateAccountingDocs(
  companyId: string,
  _profileId: ProfileId,
): Promise<GenerateAccountingDocsResult> {
  const entries = await getItemIDB<DataEntry[]>(entriesKey(companyId), [])
  const accountingEntries = entries.filter((e) => e.docPurpose === 'accounting')

  if (accountingEntries.length === 0) {
    return { total: 0, matched: 0, unmatched: 0, discrepancy: 0 }
  }

  const docs: AccountingDoc[] = []
  const now = new Date().toISOString()

  // ~40% — точное совпадение
  // ~20% — расхождение суммы
  // ~10% — расхождение даты
  // ~15% — без пары (случайные)
  // ~15% entries остаются без пары

  const totalToProcess = Math.round(accountingEntries.length * 0.85) // 85% entries получат пару
  const shuffled = [...accountingEntries].sort(() => Math.random() - 0.5)
  const toProcess = shuffled.slice(0, totalToProcess)

  // Разбивка внутри toProcess
  const exactEnd = Math.round(toProcess.length * 0.47)        // ~40% от всех
  const amountDiscEnd = Math.round(toProcess.length * 0.71)    // ~20% от всех
  const dateDiscEnd = Math.round(toProcess.length * 0.83)      // ~10% от всех
  // остальные ~15% = без пары

  for (let i = 0; i < toProcess.length; i++) {
    const entry = toProcess[i]
    const meta = entry.metadata
    const docTypeId = entry.docTypeId ?? ''
    const accDocType = DOC_TYPE_TO_ACCOUNTING[docTypeId] ?? 'receipt'

    let amount = parseFloat(meta.amount || '0')
    let date = meta.docDate || entry.createdAt.slice(0, 10)
    const docNumber = meta.docNumber || ''
    const counterparty = meta.counterparty || ''
    const inn = meta.inn || ''

    if (i < exactEnd) {
      // Точное совпадение — не меняем ничего
    } else if (i < amountDiscEnd) {
      // Расхождение суммы: ± 2-8%
      const factor = 1 + (Math.random() * 0.06 + 0.02) * (Math.random() > 0.5 ? 1 : -1)
      amount = Math.round(amount * factor * 100) / 100
    } else if (i < dateDiscEnd) {
      // Расхождение даты: ± 4-7 дней
      const dayShift = randomInt(4, 7) * (Math.random() > 0.5 ? 1 : -1)
      const d = new Date(date)
      d.setDate(d.getDate() + dayShift)
      date = d.toISOString().slice(0, 10)
    }
    // После dateDiscEnd — не создаём AccountingDoc для этих entries (они остаются без пары)
    if (i >= dateDiscEnd) continue

    docs.push({
      id: nanoid(),
      companyId,
      externalId: nanoid(),
      docType: accDocType,
      number: docNumber,
      date,
      counterpartyName: counterparty,
      counterpartyInn: inn,
      organizationName: 'ООО "Наша Организация"',
      amount,
      vatAmount: Math.round(amount * 20 / 120 * 100) / 100,
      status1c: randomItem(['Проведён', 'Проведён', 'Проведён', 'Не проведён']),
      lines: generateLines(amount),
      matchStatus: 'pending',
      createdAt: now,
      updatedAt: now,
    })
  }

  // ~15% без пары — случайные AccountingDoc
  const orphanCount = Math.round(accountingEntries.length * 0.15)
  const counterparties = [...new Set(accountingEntries.map((e) => e.metadata.counterparty).filter(Boolean))]

  for (let i = 0; i < orphanCount; i++) {
    const amount = randomInt(5000, 300000)
    const accDocType = randomItem<AccountingDocType>(['receipt', 'invoice-received', 'payment-out', 'sales'])
    const cp = randomItem(counterparties.length > 0 ? counterparties : ['ООО "Неизвестный"'])
    docs.push({
      id: nanoid(),
      companyId,
      externalId: nanoid(),
      docType: accDocType,
      number: `${randomInt(100, 9999)}`,
      date: randomDate(30).slice(0, 10),
      counterpartyName: cp,
      counterpartyInn: generateInn(),
      organizationName: 'ООО "Наша Организация"',
      amount,
      vatAmount: Math.round(amount * 20 / 120 * 100) / 100,
      status1c: 'Проведён',
      lines: generateLines(amount),
      matchStatus: 'pending',
      createdAt: now,
      updatedAt: now,
    })
  }

  // Сохраняем AccountingDocs
  setItem(accountingDocsKey(companyId), docs)

  // Запускаем сверку
  const result = await runReconciliation(companyId)

  return {
    total: docs.length,
    matched: result.matched,
    unmatched: result.unmatched,
    discrepancy: result.discrepancy,
  }
}

/** Удалить seed-флаг и все записи, заново вызвать seedIfNeeded() */
export async function resetSeed(): Promise<void> {
  const { removeItemIDB } = await import('./idbStorage')
  removeItem(SEED_KEY)
  removeItem('clearledger-seeded-v2')
  // Удалить все записи по компаниям из IndexedDB
  for (const company of defaultCompanies) {
    await removeItemIDB(entriesKey(company.id))
  }
  removeItem('clearledger-entry-counter')
  await seedIfNeeded()
}

/** Полная очистка всех clearledger-* ключей в localStorage */
export function clearAllData(): void {
  for (const key of getAllClearledgerKeys()) {
    removeItem(key)
  }
}

// ---- Типы документов, которые могут быть подчинены договору ----

const SUBORDINATE_DOC_TYPES = [
  'ttn-gsm', 'act-acceptance', 'act-reconciliation', 'act-work',
  'invoice', 'invoice-factura', 'upd', 'supply-invoice', 'torg-12',
]

const LINKS_KEY = 'clearledger-links'

/** Генерация N записей с рандомными данными + бандлы */
export async function generateEntries(
  companyId: string,
  profileId: ProfileId,
  count: number = 50,
): Promise<DataEntry[]> {
  const docTypes = getAllDocumentTypes(profileId)
  if (docTypes.length === 0) return []

  const counterparties = COUNTERPARTIES_BY_PROFILE[profileId] ?? COUNTERPARTIES_BY_PROFILE.general
  // Берём 4-6 контрагентов для концентрации документов
  const activeCounterparties = counterparties.slice(0, Math.min(6, counterparties.length))

  const created: DataEntry[] = []

  // Шаг 1: генерируем записи, назначая контрагентов из ограниченного пула
  for (let i = 0; i < count; i++) {
    const dt = randomItem(docTypes)
    const source = randomItem(ALL_SOURCES)
    const status = randomItem(ALL_STATUSES)
    const docNumber = `${randomInt(100, 9999)}`
    const amount = `${randomInt(1000, 500000)}`
    const createdAt = randomDate(30)
    const docDate = new Date(createdAt).toISOString().slice(0, 10)

    const purposeRoll = Math.random()
    const docPurpose: DocPurpose = purposeRoll < 0.8 ? 'accounting' : purposeRoll < 0.9 ? 'reference' : 'context'

    let syncStatus: SyncStatus = 'not_applicable'
    if (docPurpose === 'accounting') {
      const syncRoll = Math.random()
      syncStatus = syncRoll < 0.4 ? 'not_applicable' : syncRoll < 0.6 ? 'pending' : syncRoll < 0.8 ? 'exported' : syncRoll < 0.95 ? 'confirmed' : 'rejected_1c'
    }

    const entry = await createEntry({
      title: `${dt.label} №${docNumber}`,
      categoryId: dt.categoryId,
      subcategoryId: dt.subcategoryId,
      docTypeId: dt.id,
      companyId,
      status,
      docPurpose,
      syncStatus,
      source,
      sourceLabel: SOURCE_LABELS[source] ?? source,
      metadata: {
        docNumber,
        docDate,
        counterparty: randomItem(activeCounterparties),
        amount,
        inn: generateInn(),
      },
    })

    // Перезаписываем createdAt для рандомизации даты
    const entries = await getItemIDB<DataEntry[]>(entriesKey(companyId), [])
    const idx = entries.findIndex((e) => e.id === entry.id)
    if (idx !== -1) {
      entries[idx].createdAt = createdAt
      entries[idx].updatedAt = createdAt
      await setItemIDB(entriesKey(companyId), entries)
    }

    created.push(entry)
  }

  // Шаг 2: создаём бандлы (Договор → подчинённые документы)
  await buildBundles(companyId, created)

  return created
}

/** Создаёт бандлы из сгенерированных записей: договоры становятся корнями */
async function buildBundles(companyId: string, created: DataEntry[]) {
  const entries = await getItemIDB<DataEntry[]>(entriesKey(companyId), [])
  const entryMap = new Map(entries.map((e) => [e.id, e]))
  const links = getItem<DocumentLink[]>(LINKS_KEY, [])

  // Группируем созданные записи по контрагенту
  const byCounterparty = new Map<string, DataEntry[]>()
  for (const e of created) {
    const cp = e.metadata.counterparty || ''
    if (!cp) continue
    const arr = byCounterparty.get(cp)
    if (arr) arr.push(e)
    else byCounterparty.set(cp, [e])
  }

  for (const [, cpEntries] of byCounterparty) {
    // Ищем договоры в этой группе
    const contracts = cpEntries.filter((e) => e.docTypeId === 'contract')
    if (contracts.length === 0) continue

    // Подчинённые документы (не договоры, допустимые типы)
    const subordinates = cpEntries.filter((e) =>
      e.docTypeId !== 'contract' && SUBORDINATE_DOC_TYPES.includes(e.docTypeId ?? ''),
    )

    // Для каждого договора берём 2-5 подчинённых
    let subIdx = 0
    for (const contract of contracts) {
      const contractEntry = entryMap.get(contract.id)
      if (!contractEntry) continue

      // Помечаем договор как корень бандла
      contractEntry.metadata = {
        ...contractEntry.metadata,
        _bundleRootId: contract.id,
        _bundleRole: 'contract',
      }

      const childCount = Math.min(randomInt(2, 5), subordinates.length - subIdx)
      for (let i = 0; i < childCount; i++) {
        const child = subordinates[subIdx + i]
        if (!child) break
        const childEntry = entryMap.get(child.id)
        if (!childEntry) continue

        const role = resolveRole(child.docTypeId)

        // Помечаем ребёнка
        childEntry.metadata = {
          ...childEntry.metadata,
          _bundleRootId: contract.id,
          _bundleRole: role,
        }

        // Создаём subordinate-линк
        links.push({
          id: nanoid(),
          sourceEntryId: contract.id,
          targetEntryId: child.id,
          type: 'subordinate',
          createdAt: new Date().toISOString(),
        })
      }
      subIdx += childCount
    }
  }

  // Сохраняем обновлённые записи и линки
  await setItemIDB(entriesKey(companyId), entries)
  setItem(LINKS_KEY, links)
}

/** Статистика хранилища */
export interface StorageStats {
  totalKeys: number
  totalSizeKB: number
  entriesByCompany: Record<string, number>
  connectorsByCompany: Record<string, number>
}

export async function getStorageStats(): Promise<StorageStats> {
  const keys = getAllClearledgerKeys()
  let totalSize = 0
  for (const key of keys) {
    const val = localStorage.getItem(key)
    if (val) totalSize += key.length + val.length
  }

  const entriesByCompany: Record<string, number> = {}
  const connectorsByCompany: Record<string, number> = {}

  for (const company of defaultCompanies) {
    const entries = await getEntries(company.id)
    if (entries.length > 0) entriesByCompany[company.id] = entries.length
    const connectors = await getConnectors(company.id)
    if (connectors.length > 0) connectorsByCompany[company.id] = connectors.length
  }

  // Кастомные компании из localStorage
  for (const key of keys) {
    if (key.startsWith('clearledger-entries-')) {
      const cid = key.replace('clearledger-entries-', '')
      if (!(cid in entriesByCompany)) {
        const entries = await getEntries(cid)
        if (entries.length > 0) entriesByCompany[cid] = entries.length
      }
    }
  }

  return {
    totalKeys: keys.length,
    totalSizeKB: Math.round((totalSize * 2) / 1024), // UTF-16
    entriesByCompany,
    connectorsByCompany,
  }
}

/** Массовая смена статуса всех записей компании */
export async function setAllStatuses(companyId: string, status: EntryStatus): Promise<number> {
  const entries = await getItemIDB<DataEntry[]>(entriesKey(companyId), [])
  const now = new Date().toISOString()
  let changed = 0
  for (const entry of entries) {
    if (entry.status !== status) {
      entry.status = status
      entry.updatedAt = now
      changed++
    }
  }
  if (changed > 0) await setItemIDB(entriesKey(companyId), entries)
  return changed
}

/** Удаление всех записей одной компании */
export async function deleteAllEntries(companyId: string): Promise<number> {
  const entries = await getEntries(companyId)
  const count = entries.length
  const { removeItemIDB } = await import('./idbStorage')
  await removeItemIDB(entriesKey(companyId))
  return count
}
