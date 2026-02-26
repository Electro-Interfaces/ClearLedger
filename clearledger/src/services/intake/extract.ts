/**
 * EXTRACT — извлечение текста и метаданных из файлов.
 * Фаза 1: PDF (pdfjs-dist), текст (as-is).
 * Фаза 2: Email (postal-mime), XML (fast-xml-parser).
 * Фаза 3: OCR (tesseract.js), Excel (xlsx).
 */

import type { IntakeFileType } from '@/types'

export interface ExtractResult {
  text: string
  metadata: Record<string, string>
}

/** Извлечь текст из файла в зависимости от типа */
export async function extractText(
  file: File,
  fileType: IntakeFileType,
): Promise<ExtractResult> {
  switch (fileType) {
    case 'pdf':
      return extractPdf(file)
    case 'text':
    case 'csv':
      return extractPlainText(file)
    case 'image':
      // Фаза 3: OCR. Пока возвращаем пустой текст
      return { text: '', metadata: { _note: 'OCR не подключён (фаза 3)' } }
    case 'xml':
      // Фаза 2: XML. Пока возвращаем сырой текст
      return extractPlainText(file)
    case 'email':
      // Фаза 2: Email парсер. Пока возвращаем сырой текст
      return extractPlainText(file)
    case 'excel':
      // Фаза 3: Excel. Пока возвращаем placeholder
      return { text: '', metadata: { _note: 'Excel парсер не подключён (фаза 3)' } }
    case 'json':
      return extractPlainText(file)
    default:
      return { text: '', metadata: {} }
  }
}

/** Извлечь текст из вставленного текста */
export function extractFromPaste(text: string): ExtractResult {
  return { text: text.trim(), metadata: {} }
}

// ---- PDF Extraction (pdfjs-dist) ----

async function extractPdf(file: File): Promise<ExtractResult> {
  try {
    const pdfjsLib = await import('pdfjs-dist')

    // Настраиваем worker
    pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/build/pdf.worker.min.mjs',
      import.meta.url,
    ).toString()

    const arrayBuffer = await file.arrayBuffer()
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise
    const textParts: string[] = []

    const maxPages = Math.min(pdf.numPages, 20) // Ограничение для больших PDF
    for (let i = 1; i <= maxPages; i++) {
      const page = await pdf.getPage(i)
      const content = await page.getTextContent()
      const pageText = content.items
        .map((item) => ('str' in item ? item.str : ''))
        .join(' ')
      textParts.push(pageText)
    }

    return {
      text: textParts.join('\n'),
      metadata: {
        _pdfPages: String(pdf.numPages),
      },
    }
  } catch (err) {
    console.error('PDF extraction error:', err)
    return { text: '', metadata: { _extractError: String(err) } }
  }
}

// ---- Plain Text ----

async function extractPlainText(file: File): Promise<ExtractResult> {
  try {
    const text = await file.text()
    return { text, metadata: {} }
  } catch {
    return { text: '', metadata: { _extractError: 'Не удалось прочитать текст' } }
  }
}
