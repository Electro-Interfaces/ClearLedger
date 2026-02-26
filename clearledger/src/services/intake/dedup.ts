/**
 * DEDUP — дедупликация документов.
 * 5 уровней проверки (от точного к нечёткому):
 * 1. SHA-256 содержимого файла → 100%
 * 2. Email Message-ID → 100% (фаза 2)
 * 3. 1С GUID → 100% (фаза 2)
 * 4. Семантический ключ (docType + номер + дата + контрагент) → 95%
 * 5. Текстовый hash нормализованного текста → 90%
 */

import type { DataEntry } from '@/types'

export interface DedupResult {
  isDuplicate: boolean
  duplicateOf?: { id: string; title: string }
  fingerprint: string
}

/** Вычислить SHA-256 hash файла */
export async function computeFingerprint(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Вычислить hash для текста (нормализованный) */
export async function computeTextHash(text: string): Promise<string> {
  const normalized = text
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
  const encoder = new TextEncoder()
  const data = encoder.encode(normalized)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return 'txt-' + hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Построить семантический ключ для дедупликации */
function buildSemanticKey(
  metadata: Record<string, string>,
  docTypeId?: string,
  companyId?: string,
): string | null {
  const parts: string[] = []
  // Namespace по компании — один и тот же номер документа от разных контрагентов != дубль
  if (companyId) parts.push(companyId)
  if (docTypeId) parts.push(docTypeId)
  if (metadata.docNumber) parts.push(metadata.docNumber.trim())
  if (metadata.docDate) parts.push(metadata.docDate.trim())
  if (metadata.counterparty) parts.push(metadata.counterparty.trim().toLowerCase())

  // Нужно минимум 3 значимых поля (без companyId) для семантической дедупликации
  const significantParts = parts.length - (companyId ? 1 : 0)
  if (significantParts < 3) return null
  return 'sem-' + parts.join('|')
}

/** Проверить дубликат среди существующих записей */
export function checkDuplicate(
  fingerprint: string,
  entries: DataEntry[],
  metadata?: Record<string, string>,
  docTypeId?: string,
  companyId?: string,
): DedupResult {
  // 1. Прямое совпадение fingerprint (SHA-256)
  // Защита: пустой fingerprint не должен матчить (оба файла без хеша ≠ дубль)
  if (fingerprint) {
    for (const entry of entries) {
      if (entry.metadata._fingerprint && entry.metadata._fingerprint === fingerprint) {
        return {
          isDuplicate: true,
          duplicateOf: { id: entry.id, title: entry.title },
          fingerprint,
        }
      }
    }
  }

  // 2. Email Message-ID — точное совпадение
  if (metadata?.['_email.messageId']) {
    const messageId = metadata['_email.messageId']
    for (const entry of entries) {
      if (entry.metadata['_email.messageId'] && entry.metadata['_email.messageId'] === messageId) {
        return {
          isDuplicate: true,
          duplicateOf: { id: entry.id, title: entry.title },
          fingerprint,
        }
      }
    }
  }

  // 3. 1С GUID — точное совпадение
  if (metadata?.['_1c.guid']) {
    const guid = metadata['_1c.guid']
    for (const entry of entries) {
      if (entry.metadata['_1c.guid'] && entry.metadata['_1c.guid'] === guid) {
        return {
          isDuplicate: true,
          duplicateOf: { id: entry.id, title: entry.title },
          fingerprint,
        }
      }
    }
  }

  // 4. Семантический ключ (с namespace по компании)
  if (metadata) {
    const semanticKey = buildSemanticKey(metadata, docTypeId, companyId)
    if (semanticKey) {
      for (const entry of entries) {
        const entryKey = buildSemanticKey(entry.metadata, entry.docTypeId, entry.companyId)
        if (entryKey && entryKey === semanticKey) {
          return {
            isDuplicate: true,
            duplicateOf: { id: entry.id, title: entry.title },
            fingerprint,
          }
        }
      }
    }
  }

  return { isDuplicate: false, fingerprint }
}

/**
 * Level 5: Текстовый hash — ловит одинаковый контент в разных форматах
 * (PDF и DOCX с идентичным текстом, но разный SHA-256 файлов).
 * Вызывается отдельно, т.к. async (нужен crypto.subtle).
 */
export async function checkTextDuplicate(
  extractedText: string,
  entries: DataEntry[],
  fingerprint: string,
): Promise<DedupResultExt> {
  // Текст должен быть достаточно длинным (>100 символов) для осмысленного сравнения
  const normalized = extractedText.replace(/\s+/g, ' ').trim()
  if (normalized.length < 100) {
    return { isDuplicate: false, fingerprint }
  }

  const textHash = await computeTextHash(extractedText)

  for (const entry of entries) {
    if (entry.metadata._textHash && entry.metadata._textHash === textHash) {
      return {
        isDuplicate: true,
        duplicateOf: { id: entry.id, title: entry.title },
        fingerprint,
      }
    }
  }

  return { isDuplicate: false, fingerprint, textHash }
}

/** Расширенный результат dedup с текстовым хешом */
export interface DedupResultExt extends DedupResult {
  textHash?: string
}
