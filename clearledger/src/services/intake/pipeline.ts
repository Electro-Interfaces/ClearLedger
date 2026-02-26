/**
 * Intake Pipeline — оркестратор обработки файлов/текстов.
 * Поток: DETECT → EXTRACT → CLASSIFY → DEDUP → createEntry()
 * Хранение: Source + Extract в IndexedDB (sourceStore), лёгкий DataEntry в localStorage.
 */

import { nanoid } from 'nanoid'
import type { IntakeItem, DataEntry, EntrySource, SourceRecord, ExtractRecord, ExtractedField } from '@/types'
import type { ProfileId } from '@/config/profiles'
import { detectFileType, detectPasteType } from './detect'
import { extractText, extractFromPaste } from './extract'
import { classify } from './classify'
import { computeFingerprint, computeTextHash, checkDuplicate } from './dedup'
import { saveSource, saveExtract } from '@/services/sourceStore'
import { createEntry, getEntries } from '@/services/dataEntryService'

export type PipelineCallback = (item: IntakeItem) => void

interface PipelineOptions {
  companyId: string
  profileId?: ProfileId
  onUpdate: PipelineCallback
}

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
    item.fileType = detectFileType(file)
    opts.onUpdate({ ...item })

    // 2. EXTRACT
    item.stage = 'extract'
    item.progress = 30
    opts.onUpdate({ ...item })

    const extracted = await extractText(file, item.fileType)
    item.extractedText = extracted.text
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
    const existingEntries = getEntries(opts.companyId)
    const dedupResult = checkDuplicate(
      item.fingerprint,
      existingEntries,
      item.classification.metadata,
      item.classification.docTypeId,
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
    const entry = createEntry({
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
        _fingerprint: item.fingerprint,
      },
    })

    item.entryId = entry.id
    item.status = 'done'
    item.progress = 100
    opts.onUpdate({ ...item })
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
    item.progress = 70
    opts.onUpdate({ ...item })

    // DEDUP
    item.stage = 'dedup'
    item.progress = 80
    opts.onUpdate({ ...item })

    item.fingerprint = await computeTextHash(text)
    const existingEntries = getEntries(opts.companyId)
    const dedupResult = checkDuplicate(
      item.fingerprint,
      existingEntries,
      item.classification.metadata,
      item.classification.docTypeId,
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
    const entry = createEntry({
      title: item.classification.title,
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      companyId: opts.companyId,
      source: entrySource,
      sourceLabel: pasteType === 'email' ? 'Email (вставка)' : 'Вставленный текст',
      sourceId,
      metadata: {
        ...item.classification.metadata,
        _fingerprint: item.fingerprint,
      },
    })

    item.entryId = entry.id
    item.status = 'done'
    item.progress = 100
    opts.onUpdate({ ...item })
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

  const entry = createEntry({
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

  return entry
}

function mapFileTypeToSource(fileType: string): EntrySource {
  switch (fileType) {
    case 'pdf': return 'upload'
    case 'image': return 'photo'
    case 'email': return 'email'
    case 'xml': return 'oneC'
    case 'json': return 'telegram'
    case 'text': return 'paste'
    default: return 'upload'
  }
}

/** Конвертировать metadata-ключи в ExtractedField[] для структурированного хранения */
function buildExtractedFields(metadata: Record<string, string>): ExtractedField[] {
  const fields: ExtractedField[] = []
  const knownKeys = ['docNumber', 'docDate', 'amount', 'inn', 'counterparty']
  for (const key of knownKeys) {
    if (metadata[key]) {
      fields.push({
        key,
        value: metadata[key],
        confidence: 70,
        source: 'regex',
      })
    }
  }
  return fields
}
