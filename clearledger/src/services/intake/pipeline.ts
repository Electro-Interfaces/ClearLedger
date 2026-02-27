/**
 * Intake Pipeline — оркестратор обработки файлов/текстов.
 * Поток: DETECT → EXTRACT → CLASSIFY → DEDUP → createEntry()
 * Хранение: Source + Extract в IndexedDB (sourceStore), лёгкий DataEntry в localStorage.
 */

import { nanoid } from 'nanoid'
import type { IntakeItem, DataEntry, EntrySource, SourceRecord, ExtractRecord, ExtractedField } from '@/types'
import type { ProfileId } from '@/config/profiles'
import { detectFileType, detectPasteType, refineFileType } from './detect'
import { extractText, extractFromPaste } from './extract'
import { classify } from './classify'
import { computeFingerprint, computeTextHash, checkDuplicate, checkTextDuplicate } from './dedup'
import { saveSource, saveExtract } from '@/services/sourceStore'
import { createEntry, getEntries } from '@/services/dataEntryService'
import { createLink } from '@/services/linkService'
import { logEvent } from '@/services/auditService'

export type PipelineCallback = (item: IntakeItem) => void

interface PipelineOptions {
  companyId: string
  profileId?: ProfileId
  onUpdate: PipelineCallback
  /** Глубина рекурсии email-вложений (по умолчанию 0, макс MAX_EMAIL_DEPTH) */
  _depth?: number
  /** Дополнительные метаданные для inject при сохранении (email parent и т.д.) */
  _extraMeta?: Record<string, string>
}

/** Макс. глубина рекурсии email → attachment → email → ... */
const MAX_EMAIL_DEPTH = 3
/** Макс. размер одного вложения для обработки (10 МБ) */
const MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

/** Обработать файл через pipeline */
export async function processFile(file: File, opts: PipelineOptions): Promise<IntakeItem> {
  const sourceId = nanoid()
  const item: IntakeItem = {
    id: sourceId,
    fileName: file.name,
    file,
    mimeType: file.type,
    size: file.size,
    stage: 'detect',
    progress: 0,
    status: 'processing',
  }
  opts.onUpdate({ ...item })

  try {
    // 1. DETECT
    item.stage = 'detect'
    item.progress = 10
    const baseType = detectFileType(file)
    item.fileType = await refineFileType(file, baseType)
    opts.onUpdate({ ...item })

    // 2. EXTRACT
    item.stage = 'extract'
    item.progress = 30
    opts.onUpdate({ ...item })

    const extracted = await extractText(file, item.fileType)
    item.extractedText = extracted.text
    const emailAttachments = extracted.attachments
    item.progress = 50
    opts.onUpdate({ ...item })

    // 3. CLASSIFY
    item.stage = 'classify'
    item.progress = 60
    opts.onUpdate({ ...item })

    item.classification = classify({
      fileName: file.name,
      fileType: item.fileType,
      text: extracted.text,
      mimeType: file.type,
      profileId: opts.profileId,
    })
    // Мержим метаданные из extract в classify
    if (extracted.metadata) {
      item.classification.metadata = {
        ...item.classification.metadata,
        ...extracted.metadata,
      }
    }
    item.progress = 70
    opts.onUpdate({ ...item })

    // 4. DEDUP
    item.stage = 'dedup'
    item.progress = 80
    opts.onUpdate({ ...item })

    item.fingerprint = await computeFingerprint(file)
    const existingEntries = await getEntries(opts.companyId)
    const dedupResult = checkDuplicate(
      item.fingerprint,
      existingEntries,
      item.classification.metadata,
      item.classification.docTypeId,
      opts.companyId,
    )

    if (dedupResult.isDuplicate) {
      item.duplicateOf = dedupResult.duplicateOf ?? null
      item.status = 'duplicate'
      item.progress = 100
      opts.onUpdate({ ...item })
      return item
    }

    // Level 5: text hash dedup (разный формат файла, одинаковый текст)
    let textHash: string | undefined
    if (extracted.text) {
      const textDedupResult = await checkTextDuplicate(
        extracted.text,
        existingEntries,
        item.fingerprint,
      )
      if (textDedupResult.isDuplicate) {
        item.duplicateOf = textDedupResult.duplicateOf ?? null
        item.status = 'duplicate'
        item.progress = 100
        opts.onUpdate({ ...item })
        return item
      }
      textHash = textDedupResult.textHash
    }

    item.duplicateOf = null
    item.progress = 90
    opts.onUpdate({ ...item })

    // 5. SAVE — Source + Extract в IndexedDB, лёгкий DataEntry в localStorage
    item.stage = 'save'

    const sourceRecord: SourceRecord = {
      id: sourceId,
      blob: file,
      fileName: file.name,
      mimeType: file.type,
      size: file.size,
      fingerprint: item.fingerprint,
      createdAt: new Date().toISOString(),
    }
    await saveSource(sourceRecord)

    const extractFields = buildExtractedFields(item.classification.metadata)
    const extractRecord: ExtractRecord = {
      id: sourceId,
      sourceId,
      fullText: item.extractedText ?? '',
      fields: extractFields,
      classification: {
        categoryId: item.classification.categoryId,
        subcategoryId: item.classification.subcategoryId,
        docTypeId: item.classification.docTypeId,
        confidence: item.classification.confidence,
      },
      extractedAt: new Date().toISOString(),
    }
    await saveExtract(extractRecord)

    const entrySource: EntrySource = mapFileTypeToSource(item.fileType)
    const entry = await createEntry({
      title: item.classification.title,
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      companyId: opts.companyId,
      source: entrySource,
      sourceLabel: file.name,
      fileType: file.type,
      fileSize: file.size,
      sourceId,
      metadata: {
        ...item.classification.metadata,
        ...(opts._extraMeta ?? {}),
        _fingerprint: item.fingerprint,
        ...(textHash ? { _textHash: textHash } : {}),
      },
    })

    item.entryId = entry.id
    item.status = 'done'
    item.progress = 100
    opts.onUpdate({ ...item })

    // Аудит-лог
    logEvent({
      companyId: opts.companyId,
      entryId: entry.id,
      action: 'created',
      details: `Intake: ${file.name}`,
      userName: 'Intake Pipeline',
    })

    // Рекурсивная обработка вложений email (с лимитом глубины и размера)
    const depth = opts._depth ?? 0
    if (item.fileType === 'email' && emailAttachments && emailAttachments.length > 0 && depth < MAX_EMAIL_DEPTH) {
      item.childItems = []
      for (const att of emailAttachments) {
        // Пропускаем слишком большие вложения
        if (att.size > MAX_ATTACHMENT_SIZE) continue

        const attData: BlobPart = att.content instanceof Uint8Array
          ? new Uint8Array(att.content) as unknown as BlobPart
          : att.content as BlobPart
        const attFile = new File(
          [attData],
          att.filename,
          { type: att.mimeType },
        )
        // Передаём metadata связи через _extraMeta (inject в save-фазу)
        const emailMeta = {
          '_email.parentEntryId': entry.id,
          '_email.parentSubject': extracted.metadata['_email.subject'] ?? '',
        }
        const childItem = await processFile(attFile, {
          ...opts,
          _depth: depth + 1,
          _extraMeta: emailMeta,
          onUpdate: (child) => opts.onUpdate(child),
        })
        // Создаём связь email → вложение
        if (childItem.entryId) {
          createLink(entry.id, childItem.entryId, 'email-attachment', att.filename)
          logEvent({
            companyId: opts.companyId,
            entryId: childItem.entryId,
            action: 'created',
            details: `Email вложение: ${att.filename}`,
            userName: 'Intake Pipeline',
          })
        }
        item.childItems.push(childItem)
      }
    }

    return item
  } catch (err) {
    item.status = 'error'
    item.error = err instanceof Error ? err.message : String(err)
    item.progress = 100
    opts.onUpdate({ ...item })
    return item
  }
}

/** Обработать вставленный текст через pipeline */
export async function processPaste(text: string, opts: PipelineOptions): Promise<IntakeItem> {
  const pasteType = detectPasteType(text)
  const sourceId = nanoid()
  const item: IntakeItem = {
    id: sourceId,
    fileName: pasteType === 'email' ? 'email-paste.txt' : 'pasted-text.txt',
    pastedText: text,
    mimeType: 'text/plain',
    size: new Blob([text]).size,
    stage: 'detect',
    progress: 0,
    status: 'processing',
    fileType: 'text',
  }
  opts.onUpdate({ ...item })

  try {
    // EXTRACT
    item.stage = 'extract'
    item.progress = 30
    opts.onUpdate({ ...item })

    const extracted = extractFromPaste(text)
    item.extractedText = extracted.text
    item.progress = 50
    opts.onUpdate({ ...item })

    // CLASSIFY
    item.stage = 'classify'
    item.progress = 60
    opts.onUpdate({ ...item })

    item.classification = classify({
      fileName: item.fileName,
      fileType: 'text',
      text: extracted.text,
      mimeType: 'text/plain',
      profileId: opts.profileId,
    })
    // Мержим метаданные из extract в classify (как в processFile)
    if (extracted.metadata) {
      item.classification.metadata = {
        ...item.classification.metadata,
        ...extracted.metadata,
      }
    }
    item.progress = 70
    opts.onUpdate({ ...item })

    // DEDUP
    item.stage = 'dedup'
    item.progress = 80
    opts.onUpdate({ ...item })

    const pasteTextHash = await computeTextHash(text)
    item.fingerprint = pasteTextHash
    const existingEntries = await getEntries(opts.companyId)
    const dedupResult = checkDuplicate(
      pasteTextHash,
      existingEntries,
      item.classification.metadata,
      item.classification.docTypeId,
      opts.companyId,
    )

    if (dedupResult.isDuplicate) {
      item.duplicateOf = dedupResult.duplicateOf ?? null
      item.status = 'duplicate'
      item.progress = 100
      opts.onUpdate({ ...item })
      return item
    }

    item.duplicateOf = null
    item.progress = 90
    opts.onUpdate({ ...item })

    // SAVE — для текста нет blob, но сохраняем extract
    // Для paste fingerprint уже textHash (computeTextHash), сохраняем как _textHash тоже
    item.stage = 'save'

    // Для вставленного текста создаём Source с текстовым blob
    const textBlob = new Blob([text], { type: 'text/plain' })
    const sourceRecord: SourceRecord = {
      id: sourceId,
      blob: textBlob,
      fileName: item.fileName,
      mimeType: 'text/plain',
      size: textBlob.size,
      fingerprint: item.fingerprint,
      createdAt: new Date().toISOString(),
    }
    await saveSource(sourceRecord)

    const extractFields = buildExtractedFields(item.classification.metadata)
    const extractRecord: ExtractRecord = {
      id: sourceId,
      sourceId,
      fullText: text,
      fields: extractFields,
      classification: {
        categoryId: item.classification.categoryId,
        subcategoryId: item.classification.subcategoryId,
        docTypeId: item.classification.docTypeId,
        confidence: item.classification.confidence,
      },
      extractedAt: new Date().toISOString(),
    }
    await saveExtract(extractRecord)

    const entrySource: EntrySource = pasteType === 'email' ? 'email' : 'paste'
    const entry = await createEntry({
      title: item.classification.title,
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      companyId: opts.companyId,
      source: entrySource,
      sourceLabel: pasteType === 'email' ? 'Email (вставка)' : 'Вставленный текст',
      fileType: 'text/plain',
      fileSize: textBlob.size,
      sourceId,
      metadata: {
        ...item.classification.metadata,
        ...(opts._extraMeta ?? {}),
        _textHash: pasteTextHash,
      },
    })

    item.entryId = entry.id
    item.status = 'done'
    item.progress = 100
    opts.onUpdate({ ...item })

    // Аудит-лог
    logEvent({
      companyId: opts.companyId,
      entryId: entry.id,
      action: 'created',
      details: `Intake paste: ${pasteType}`,
      userName: 'Intake Pipeline',
    })

    return item
  } catch (err) {
    item.status = 'error'
    item.error = err instanceof Error ? err.message : String(err)
    item.progress = 100
    opts.onUpdate({ ...item })
    return item
  }
}

/** Принудительно сохранить дубликат */
export async function forceSaveDuplicate(
  item: IntakeItem,
  companyId: string,
): Promise<DataEntry | null> {
  if (!item.classification) return null

  const sourceId = nanoid()

  // Сохраняем source
  if (item.file) {
    const fingerprint = item.fingerprint ?? ''
    const sourceRecord: SourceRecord = {
      id: sourceId,
      blob: item.file,
      fileName: item.fileName,
      mimeType: item.mimeType,
      size: item.size,
      fingerprint,
      createdAt: new Date().toISOString(),
    }
    await saveSource(sourceRecord)
  } else if (item.pastedText) {
    const textBlob = new Blob([item.pastedText], { type: 'text/plain' })
    const sourceRecord: SourceRecord = {
      id: sourceId,
      blob: textBlob,
      fileName: item.fileName,
      mimeType: 'text/plain',
      size: textBlob.size,
      fingerprint: item.fingerprint ?? '',
      createdAt: new Date().toISOString(),
    }
    await saveSource(sourceRecord)
  }

  // Сохраняем extract
  const extractFields = buildExtractedFields(item.classification.metadata)
  const extractRecord: ExtractRecord = {
    id: sourceId,
    sourceId,
    fullText: item.extractedText ?? item.pastedText ?? '',
    fields: extractFields,
    classification: {
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      confidence: item.classification.confidence,
    },
    extractedAt: new Date().toISOString(),
  }
  await saveExtract(extractRecord)

  const source: EntrySource = item.file
    ? mapFileTypeToSource(item.fileType ?? 'unknown')
    : 'paste'

  const entry = await createEntry({
    title: item.classification.title,
    categoryId: item.classification.categoryId,
    subcategoryId: item.classification.subcategoryId,
    docTypeId: item.classification.docTypeId,
    companyId,
    source,
    sourceLabel: item.fileName,
    fileType: item.mimeType,
    fileSize: item.size,
    sourceId,
    metadata: {
      ...item.classification.metadata,
      _fingerprint: item.fingerprint ?? '',
      ...(item.duplicateOf?.id ? { _duplicateOf: item.duplicateOf.id } : {}),
    },
  })

  // Аудит-лог
  logEvent({
    companyId,
    entryId: entry.id,
    action: 'created',
    details: `Дубликат сохранён: ${item.fileName}${item.duplicateOf?.id ? ` (оригинал: ${item.duplicateOf.id})` : ''}`,
    userName: 'Intake Pipeline',
  })

  // Связь с оригиналом (дубликат)
  if (item.duplicateOf?.id) {
    createLink(item.duplicateOf.id, entry.id, 'duplicate')
  }

  return entry
}

function mapFileTypeToSource(fileType: string): EntrySource {
  switch (fileType) {
    case 'pdf': return 'upload'
    case 'image': return 'photo'
    case 'email': return 'email'
    case 'xml': return 'oneC'
    case 'telegram': return 'telegram'
    case 'whatsapp': return 'whatsapp'
    case 'json': return 'upload'
    case 'text': return 'paste'
    default: return 'upload'
  }
}

/** Конвертировать metadata-ключи в ExtractedField[] для структурированного хранения */
function buildExtractedFields(metadata: Record<string, string>): ExtractedField[] {
  const fields: ExtractedField[] = []
  const regexKeys = ['docNumber', 'docDate', 'amount', 'inn', 'counterparty']
  for (const key of regexKeys) {
    if (metadata[key]) {
      fields.push({
        key,
        value: metadata[key],
        confidence: 70,
        source: 'regex',
      })
    }
  }
  // Email-поля (из парсера)
  const parserKeys = [
    '_email.from', '_email.to', '_email.subject', '_email.date', '_email.messageId',
    '_1c.guid', '_xml.format', '_xml.docType',
  ]
  for (const key of parserKeys) {
    if (metadata[key]) {
      fields.push({
        key,
        value: metadata[key],
        confidence: 95,
        source: 'parser',
      })
    }
  }
  return fields
}
