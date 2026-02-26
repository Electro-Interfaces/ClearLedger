/**
 * Intake Pipeline — оркестратор обработки файлов/текстов.
 * Поток: DETECT → EXTRACT → CLASSIFY → DEDUP → createEntry()
 */

import { nanoid } from 'nanoid'
import type { IntakeItem, DataEntry, EntrySource } from '@/types'
import { detectFileType, detectPasteType } from './detect'
import { extractText, extractFromPaste } from './extract'
import { classify } from './classify'
import { computeFingerprint, computeTextHash, checkDuplicate } from './dedup'
import { saveBlob } from '@/services/blobStore'
import { createEntry, getEntries } from '@/services/dataEntryService'

export type PipelineCallback = (item: IntakeItem) => void

interface PipelineOptions {
  companyId: string
  onUpdate: PipelineCallback
}

/** Обработать файл через pipeline */
export async function processFile(file: File, opts: PipelineOptions): Promise<IntakeItem> {
  const item: IntakeItem = {
    id: nanoid(),
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

    // 5. SAVE
    item.stage = 'save'
    await saveBlob(item.id, file)

    const source: EntrySource = mapFileTypeToSource(item.fileType)
    const entry = createEntry({
      title: item.classification.title,
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      companyId: opts.companyId,
      source,
      sourceLabel: file.name,
      fileType: file.type,
      fileSize: file.size,
      metadata: {
        ...item.classification.metadata,
        _blobId: item.id,
        _fingerprint: item.fingerprint,
        _confidence: String(item.classification.confidence),
        _sourceType: item.fileType,
        _extractedText: (item.extractedText ?? '').slice(0, 2000), // Ограничиваем для localStorage
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
  const item: IntakeItem = {
    id: nanoid(),
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

    // SAVE
    item.stage = 'save'
    const source: EntrySource = pasteType === 'email' ? 'email' : 'paste'
    const entry = createEntry({
      title: item.classification.title,
      categoryId: item.classification.categoryId,
      subcategoryId: item.classification.subcategoryId,
      docTypeId: item.classification.docTypeId,
      companyId: opts.companyId,
      source,
      sourceLabel: pasteType === 'email' ? 'Email (вставка)' : 'Вставленный текст',
      metadata: {
        ...item.classification.metadata,
        _fingerprint: item.fingerprint,
        _confidence: String(item.classification.confidence),
        _sourceType: pasteType,
        _extractedText: text.slice(0, 2000),
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

  // Сохраняем blob если есть файл
  if (item.file) {
    await saveBlob(item.id, item.file)
  }

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
    metadata: {
      ...item.classification.metadata,
      _blobId: item.file ? item.id : '',
      _fingerprint: item.fingerprint ?? '',
      _confidence: String(item.classification.confidence),
      _duplicateOf: item.duplicateOf?.id ?? '',
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
