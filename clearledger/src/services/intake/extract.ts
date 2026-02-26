/**
 * EXTRACT — извлечение текста и метаданных из файлов.
 * PDF: pdfjs-dist
 * Email: postal-mime (parsers/emailParser)
 * XML: fast-xml-parser (parsers/xmlParser)
 * Excel: xlsx / SheetJS (parsers/excelParser)
 * CSV: xlsx / SheetJS (parsers/excelParser)
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
    case 'email':
      return extractEmail(file)
    case 'xml':
      return extractXml(file)
    case 'excel':
      return extractExcel(file)
    case 'csv':
      return extractCsv(file)
    case 'text':
      return extractPlainText(file)
    case 'json':
      return extractPlainText(file)
    case 'image':
      // Фаза 3: OCR (tesseract.js)
      return { text: '', metadata: { _note: 'OCR не подключён (фаза 3)' } }
    case 'word':
      // Фаза 3: mammoth.js
      return { text: '', metadata: { _note: 'Word парсер не подключён (фаза 3)' } }
    default:
      return { text: '', metadata: {} }
  }
}

/** Извлечь текст из вставленного текста */
export function extractFromPaste(text: string): ExtractResult {
  return { text: text.trim(), metadata: {} }
}

// ---- Email (.eml) — postal-mime ----

async function extractEmail(file: File): Promise<ExtractResult> {
  try {
    const { parseEmail } = await import('./parsers/emailParser')
    const result = await parseEmail(file)
    // EmailParseResult extends ExtractResult, attachments хранятся для будущего использования
    return { text: result.text, metadata: result.metadata }
  } catch (err) {
    console.error('Email extraction error:', err)
    return extractPlainText(file)
  }
}

// ---- XML (1С, ФНС) — fast-xml-parser ----

async function extractXml(file: File): Promise<ExtractResult> {
  try {
    const { parseXml } = await import('./parsers/xmlParser')
    return parseXml(file)
  } catch (err) {
    console.error('XML extraction error:', err)
    return extractPlainText(file)
  }
}

// ---- Excel (.xlsx/.xls) — SheetJS ----

async function extractExcel(file: File): Promise<ExtractResult> {
  try {
    const { parseExcel } = await import('./parsers/excelParser')
    return parseExcel(file)
  } catch (err) {
    console.error('Excel extraction error:', err)
    return { text: '', metadata: { _extractError: `Excel: ${String(err)}` } }
  }
}

// ---- CSV — SheetJS (для структурного парсинга) ----

async function extractCsv(file: File): Promise<ExtractResult> {
  try {
    const { parseCsv } = await import('./parsers/excelParser')
    return parseCsv(file)
  } catch (err) {
    console.error('CSV extraction error:', err)
    return extractPlainText(file)
  }
}

// ---- PDF (pdfjs-dist) ----

async function extractPdf(file: File): Promise<ExtractResult> {
  try {
    const pdfjsLib = await import('pdfjs-dist')

    pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/build/pdf.worker.min.mjs',
      import.meta.url,
    ).toString()

    const arrayBuffer = await file.arrayBuffer()
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise
    const textParts: string[] = []

    const maxPages = Math.min(pdf.numPages, 20)
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
