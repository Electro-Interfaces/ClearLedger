/**
 * BundleService — бизнес-комплекты документов (иерархическая подчинённость).
 *
 * Три ключевых принципа из 1С:УТ:
 * 1. Матрица допустимых пар — не все типы могут быть подчинены друг другу
 * 2. «Создать на основании» — предзаполнение полей из родительского документа
 * 3. Enum ролей — роль определяется по docTypeId, а не свободным текстом
 *
 * Гибридная модель хранения:
 * - subordinate-линки (linkService) хранят структуру дерева
 * - metadata._bundleRootId даёт O(1) проверку принадлежности
 * - metadata._bundleRole — роль из enum BundleRole
 */

import type {
  DataEntry, BundleNode, BundleTree, BundleSuggestion,
  BundleRole, BundleValidation,
} from '@/types'
import { getLinksByType, createLink, removeLink } from './linkService'
import { getEntries, getEntry, updateEntry } from './dataEntryService'
import { normalizeCounterparty, getCounterpartyFromMeta, getDocNumberFromMeta } from '@/lib/textUtils'

// ============================================================
// Улучшение 3: Enum ролей — маппинг docTypeId → BundleRole
// ============================================================

/** Маппинг docTypeId → BundleRole */
const DOC_TYPE_TO_ROLE: Record<string, BundleRole> = {
  // Договоры
  'contract':           'contract',
  // Допсоглашения (в profiles нет отдельного, но может прийти из metadata)
  'addendum':           'addendum',
  // Акты
  'act':                'act',
  'act-work':           'act',
  'act-acceptance':     'act',
  'act-reconciliation': 'act',
  'act-maintenance':    'act',
  'reconciliation-act': 'act',
  'writeoff-act':       'act',
  // Счета
  'invoice':            'invoice',
  'invoice-factura':    'invoice-factura',
  'upd':                'upd',
  // Оплата
  'payment':            'payment',
  'payment-order':      'payment',
  'bank-statement':     'payment',
  'pko':                'payment',
  'rko':                'payment',
  // Накладные
  'waybill':            'waybill',
  'ttn-gsm':            'waybill',
  'torg-12':            'waybill',
  'supply-invoice':     'waybill',
  'return-invoice':     'waybill',
}

/** Определить роль по docTypeId */
export function resolveRole(docTypeId?: string): BundleRole {
  if (!docTypeId) return 'other'
  return DOC_TYPE_TO_ROLE[docTypeId] ?? 'other'
}

/** Русские лейблы для ролей */
export const BUNDLE_ROLE_LABELS: Record<BundleRole, string> = {
  'contract':        'Договор',
  'addendum':        'Допсоглашение',
  'act':             'Акт',
  'invoice':         'Счёт',
  'invoice-factura': 'Счёт-фактура',
  'upd':             'УПД',
  'payment':         'Оплата',
  'waybill':         'Накладная',
  'other':           'Документ',
}

// ============================================================
// Улучшение 1: Матрица допустимых пар (направленная)
// ============================================================

/**
 * SUBORDINATION_RULES: роль родителя → допустимые роли ребёнка.
 * Цепочки как в 1С:УТ:
 *   Договор → {Допсоглашение, Акт, Счёт, СФ, УПД, Оплата, Накладная, Прочее}
 *   Акт → {СФ, Оплата}
 *   Счёт → {Оплата}
 *   СФ → {Оплата}
 *   Накладная → {Акт, СФ}
 */
const SUBORDINATION_RULES: Record<BundleRole, BundleRole[]> = {
  'contract':        ['addendum', 'act', 'invoice', 'invoice-factura', 'upd', 'payment', 'waybill', 'other'],
  'addendum':        ['act', 'invoice', 'invoice-factura', 'upd', 'payment', 'other'],
  'act':             ['invoice-factura', 'payment', 'other'],
  'invoice':         ['payment', 'other'],
  'invoice-factura': ['payment', 'other'],
  'upd':             ['payment', 'other'],
  'payment':         ['other'],
  'waybill':         ['act', 'invoice-factura', 'other'],
  'other':           ['other'],
}

/** Валидация: можно ли добавить ребёнка к родителю */
export function validateSubordination(
  parentDocTypeId?: string,
  childDocTypeId?: string,
): BundleValidation {
  const parentRole = resolveRole(parentDocTypeId)
  const childRole = resolveRole(childDocTypeId)

  const allowed = SUBORDINATION_RULES[parentRole]
  if (!allowed) {
    return { allowed: true } // неизвестная роль → разрешаем (мягкая валидация)
  }

  if (allowed.includes(childRole)) {
    return { allowed: true }
  }

  return {
    allowed: false,
    reason: `${BUNDLE_ROLE_LABELS[childRole]} не может быть подчинён ${BUNDLE_ROLE_LABELS[parentRole]}`,
  }
}

/** Получить допустимые роли ребёнка для данного родителя */
export function getAllowedChildRoles(parentDocTypeId?: string): BundleRole[] {
  const parentRole = resolveRole(parentDocTypeId)
  return SUBORDINATION_RULES[parentRole] ?? []
}

// ============================================================
// Улучшение 2: «Создать на основании» — предзаполнение
// ============================================================

export interface PrefillData {
  title: string
  categoryId: string
  subcategoryId: string
  metadata: Record<string, string>
}

/** Предзаполнение полей нового документа на основании родителя */
export function prefillFromParent(parent: DataEntry): PrefillData {
  const metadata: Record<string, string> = {}

  // Переносим контрагента
  if (parent.metadata.counterparty) metadata.counterparty = parent.metadata.counterparty
  if (parent.metadata._1c_counterparty) metadata._1c_counterparty = parent.metadata._1c_counterparty
  if (parent.metadata.contractor) metadata.contractor = parent.metadata.contractor
  if (parent.metadata.inn) metadata.inn = parent.metadata.inn
  if (parent.metadata.kpp) metadata.kpp = parent.metadata.kpp

  // Номер и дата родительского документа
  const parentNumber = parent.metadata.docNumber || parent.metadata.number || parent.metadata._1c_number || ''
  if (parentNumber) metadata.parentDocNumber = parentNumber
  const parentDate = parent.metadata.docDate || parent.metadata.date || ''
  if (parentDate) metadata.parentDocDate = parentDate

  // Суммы
  if (parent.metadata.amount) metadata.amount = parent.metadata.amount
  if (parent.metadata.amountVat) metadata.amountVat = parent.metadata.amountVat
  if (parent.metadata.currency) metadata.currency = parent.metadata.currency

  // Договор (если родитель — договор, переносим его номер как ссылку)
  const parentRole = resolveRole(parent.docTypeId)
  if (parentRole === 'contract') {
    metadata.contractNumber = parentNumber
    metadata.contractDate = parentDate
  }

  return {
    title: '',
    categoryId: parent.categoryId,
    subcategoryId: parent.subcategoryId,
    metadata,
  }
}

// ============================================================
// Утилиты
// ============================================================

/** Извлекает контрагента из metadata */
function getCounterparty(entry: DataEntry): string {
  return getCounterpartyFromMeta(entry.metadata)
}

/** Извлекает номер документа из metadata/title */
function getDocNumber(entry: DataEntry): string {
  return getDocNumberFromMeta(entry.metadata)
}

/** Дата документа (для сравнения близости) */
function getDocDate(entry: DataEntry): Date | null {
  const raw = entry.metadata.docDate || entry.metadata.date || entry.createdAt
  const d = new Date(raw)
  return isNaN(d.getTime()) ? null : d
}

// ============================================================
// Основные функции
// ============================================================

/** Проверка: запись в комплекте? */
export function isInBundle(entry: DataEntry): boolean {
  return !!entry.metadata._bundleRootId
}

/** Получить дерево комплекта для записи */
export async function getBundleTree(
  companyId: string,
  entryId: string,
): Promise<BundleTree | null> {
  const entry = await getEntry(companyId, entryId)
  if (!entry || !entry.metadata._bundleRootId) return null

  const rootId = entry.metadata._bundleRootId
  const allEntries = await getEntries(companyId)
  const entryMap = new Map(allEntries.map((e) => [e.id, e]))

  // Находим все записи комплекта
  const bundleEntries = allEntries.filter((e) => e.metadata._bundleRootId === rootId)
  if (bundleEntries.length === 0) return null

  // Получаем subordinate-линки
  const allSubLinks = await getLinksByType('subordinate')
  const bundleIds = new Set(bundleEntries.map((e) => e.id))

  // Строим children map: parentId → childId[]
  const childrenMap = new Map<string, string[]>()
  for (const link of allSubLinks) {
    if (bundleIds.has(link.sourceEntryId) && bundleIds.has(link.targetEntryId)) {
      const children = childrenMap.get(link.sourceEntryId) ?? []
      children.push(link.targetEntryId)
      childrenMap.set(link.sourceEntryId, children)
    }
  }

  // Рекурсивно строим дерево (с защитой от циклов)
  const visited = new Set<string>()
  function buildNode(id: string, depth: number): BundleNode | null {
    if (visited.has(id)) return null // cycle protection
    visited.add(id)
    const e = entryMap.get(id)
    if (!e) return null
    const childIds = childrenMap.get(id) ?? []
    const children = childIds
      .map((cid) => buildNode(cid, depth + 1))
      .filter((n): n is BundleNode => n !== null)
    return { entry: e, children, depth }
  }

  const rootNode = buildNode(rootId, 0)
  if (!rootNode) return null

  function countNodes(node: BundleNode): number {
    return 1 + node.children.reduce((sum, c) => sum + countNodes(c), 0)
  }

  return { root: rootNode, totalCount: countNodes(rootNode) }
}

/** Создать комплект (документ становится корнем) */
export async function createBundle(
  companyId: string,
  rootEntryId: string,
): Promise<void> {
  const entry = await getEntry(companyId, rootEntryId)
  if (!entry) return
  const role = resolveRole(entry.docTypeId)
  await updateEntry(companyId, rootEntryId, {
    metadata: { ...entry.metadata, _bundleRootId: rootEntryId, _bundleRole: role },
  })
}

/** Добавить документ в комплект как подчинённый */
export async function addToBundle(
  companyId: string,
  parentId: string,
  childId: string,
): Promise<BundleValidation> {
  const parent = await getEntry(companyId, parentId)
  const child = await getEntry(companyId, childId)
  if (!parent || !child) return { allowed: false, reason: 'Документ не найден' }

  // Валидация допустимой пары
  const validation = validateSubordination(parent.docTypeId, child.docTypeId)
  if (!validation.allowed) return validation

  const rootId = parent.metadata._bundleRootId || parentId

  // Создаём subordinate-линк (parent → child)
  await createLink(parentId, childId, 'subordinate')

  // Ставим metadata на child: роль определяется автоматически по docTypeId
  const role = resolveRole(child.docTypeId)
  await updateEntry(companyId, childId, {
    metadata: { ...child.metadata, _bundleRootId: rootId, _bundleRole: role },
  })

  return { allowed: true }
}

/** Убрать документ из комплекта (и всех его потомков).
 *  Если удаляется корень — первый ребёнок становится новым корнем. */
export async function removeFromBundle(
  companyId: string,
  entryId: string,
): Promise<void> {
  const entry = await getEntry(companyId, entryId)
  if (!entry || !entry.metadata._bundleRootId) return

  const isRoot = entry.metadata._bundleRootId === entryId
  const allSubLinks = await getLinksByType('subordinate')

  // Если удаляем корень и есть дети — reparent
  if (isRoot) {
    const directChildIds = allSubLinks
      .filter((l) => l.sourceEntryId === entryId)
      .map((l) => l.targetEntryId)

    if (directChildIds.length > 0) {
      const newRootId = directChildIds[0]

      // Удаляем линк root → newRoot
      const rootToNewRootLink = allSubLinks.find(
        (l) => l.sourceEntryId === entryId && l.targetEntryId === newRootId,
      )
      if (rootToNewRootLink) await removeLink(rootToNewRootLink.id)

      // Перевешиваем остальных детей root на newRoot
      for (const childId of directChildIds.slice(1)) {
        const oldLink = allSubLinks.find(
          (l) => l.sourceEntryId === entryId && l.targetEntryId === childId,
        )
        if (oldLink) await removeLink(oldLink.id)
        await createLink(newRootId, childId, 'subordinate')
      }

      // Собираем всех оставшихся членов комплекта
      const remaining = new Set<string>()
      async function collectAll(parentId: string) {
        remaining.add(parentId)
        const currentLinks = await getLinksByType('subordinate')
        for (const link of currentLinks) {
          if (link.sourceEntryId === parentId && !remaining.has(link.targetEntryId)) {
            await collectAll(link.targetEntryId)
          }
        }
      }
      await collectAll(newRootId)

      // Batch-обновляем _bundleRootId у всех оставшихся членов
      await Promise.all(
        [...remaining].map(async (memberId) => {
          const member = await getEntry(companyId, memberId)
          if (member) {
            await updateEntry(companyId, memberId, {
              metadata: { ...member.metadata, _bundleRootId: newRootId },
            })
          }
        }),
      )

      // Очищаем metadata старого корня
      const { _bundleRootId, _bundleRole, ...restMeta } = entry.metadata
      await updateEntry(companyId, entryId, { metadata: restMeta })
      return
    }
  }

  // Обычный путь: удаляем ветку (entryId + все потомки)
  const descendants = new Set<string>([entryId])

  function collectDescendants(parentId: string) {
    for (const link of allSubLinks) {
      if (link.sourceEntryId === parentId && !descendants.has(link.targetEntryId)) {
        descendants.add(link.targetEntryId)
        collectDescendants(link.targetEntryId)
      }
    }
  }
  collectDescendants(entryId)

  // Удаляем subordinate-линк от родителя к этому узлу
  const parentLink = allSubLinks.find((l) => l.targetEntryId === entryId)
  if (parentLink) await removeLink(parentLink.id)

  // Удаляем все subordinate-линки потомков
  for (const link of allSubLinks) {
    if (descendants.has(link.sourceEntryId) && descendants.has(link.targetEntryId)) {
      await removeLink(link.id)
    }
  }

  // Batch-очистка bundle-metadata у всех затронутых записей
  await Promise.all(
    [...descendants].map(async (descId) => {
      const desc = await getEntry(companyId, descId)
      if (desc) {
        const { _bundleRootId, _bundleRole, ...restMeta } = desc.metadata
        await updateEntry(companyId, descId, { metadata: restMeta })
      }
    }),
  )
}

/** Переместить к другому родителю внутри комплекта */
export async function reparent(
  companyId: string,
  entryId: string,
  newParentId: string,
): Promise<BundleValidation> {
  const parent = await getEntry(companyId, newParentId)
  const child = await getEntry(companyId, entryId)
  if (!parent || !child) return { allowed: false, reason: 'Документ не найден' }

  // Валидация допустимой пары
  const validation = validateSubordination(parent.docTypeId, child.docTypeId)
  if (!validation.allowed) return validation

  // Удаляем старый subordinate-линк
  const allSubLinks = await getLinksByType('subordinate')
  const oldLink = allSubLinks.find((l) => l.targetEntryId === entryId)
  if (oldLink) await removeLink(oldLink.id)

  // Создаём новый
  await createLink(newParentId, entryId, 'subordinate')
  return { allowed: true }
}

/** Получить все деревья комплектов + одиночные документы */
export async function getAllBundleTrees(
  companyId: string,
  entries: DataEntry[],
): Promise<{ trees: BundleTree[]; orphans: DataEntry[] }> {
  // Собираем уникальные rootId
  const rootIds = new Set<string>()
  for (const e of entries) {
    if (e.metadata._bundleRootId) {
      rootIds.add(e.metadata._bundleRootId)
    }
  }

  // Собираем деревья
  const trees: BundleTree[] = []
  const inBundle = new Set<string>()

  for (const rootId of rootIds) {
    const tree = await getBundleTree(companyId, rootId)
    if (tree) {
      trees.push(tree)
      // Собираем все ID в дереве
      function collectIds(node: BundleNode) {
        inBundle.add(node.entry.id)
        for (const child of node.children) {
          collectIds(child)
        }
      }
      collectIds(tree.root)
    }
  }

  // Одиночные документы — не входят ни в один комплект
  const orphans = entries.filter((e) => !inBundle.has(e.id))

  return { trees, orphans }
}

/** Авто-предложения кандидатов для комплекта */
export async function suggestBundleMembers(
  companyId: string,
  entryId: string,
): Promise<BundleSuggestion[]> {
  const entry = await getEntry(companyId, entryId)
  if (!entry) return []

  const allEntries = await getEntries(companyId)
  const entryCounterparty = normalizeCounterparty(getCounterparty(entry))
  const entryDocNumber = getDocNumber(entry)
  const entryDate = getDocDate(entry)
  const entryRole = resolveRole(entry.docTypeId)

  // Допустимые роли ребёнка для этого документа
  const allowedRoles = SUBORDINATION_RULES[entryRole] ?? []

  const suggestions: BundleSuggestion[] = []

  for (const candidate of allEntries) {
    // Исключения
    if (candidate.id === entryId) continue
    if (candidate.metadata._bundleRootId && candidate.metadata._bundleRootId !== entry.metadata._bundleRootId) continue
    if (candidate.metadata._bundleRootId === entry.metadata._bundleRootId && entry.metadata._bundleRootId) continue
    if (candidate.status === 'archived') continue
    if (candidate.metadata._excluded === 'true') continue
    if (candidate.metadata._isLatestVersion === 'false') continue

    // Улучшение 1: пропускаем кандидатов с недопустимой ролью
    const candRole = resolveRole(candidate.docTypeId)
    if (allowedRoles.length > 0 && !allowedRoles.includes(candRole)) continue

    let score = 0
    const reasons: string[] = []

    // 1. Совпадение контрагента (+40)
    const candCounterparty = normalizeCounterparty(getCounterparty(candidate))
    if (entryCounterparty && candCounterparty && entryCounterparty === candCounterparty) {
      score += 40
      reasons.push('Совпадение контрагента')
    }

    // 2. Ссылка на номер документа (+30)
    const candDocNumber = getDocNumber(candidate)
    if (entryDocNumber && candDocNumber) {
      const entryTitle = entry.title.toLowerCase()
      const candTitle = candidate.title.toLowerCase()
      if (
        candTitle.includes(entryDocNumber.toLowerCase()) ||
        entryTitle.includes(candDocNumber.toLowerCase()) ||
        entryDocNumber === candDocNumber
      ) {
        score += 30
        reasons.push('Ссылка на номер договора')
      }
    }

    // 3. Допустимая пара типов (+15)
    if (allowedRoles.includes(candRole) && candRole !== 'other') {
      score += 15
      reasons.push('Допустимый тип подчинённого')
    }

    // 4. Временная близость (+15 max)
    const candDate = getDocDate(candidate)
    if (entryDate && candDate) {
      const diffDays = Math.abs(entryDate.getTime() - candDate.getTime()) / (1000 * 60 * 60 * 24)
      if (diffDays <= 90) {
        score += 15
        reasons.push('Временная близость')
      } else if (diffDays <= 365) {
        const pts = Math.round(15 * (1 - (diffDays - 90) / 275))
        if (pts > 0) {
          score += pts
          reasons.push('Временная близость')
        }
      }
    }

    // Порог
    if (score >= 40) {
      suggestions.push({ entry: candidate, score, reasons })
    }
  }

  suggestions.sort((a, b) => b.score - a.score)
  return suggestions.slice(0, 10)
}
