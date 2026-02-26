/**
 * EXTRACT — извлечение текста и метаданных из файлов.
 * PDF: pdfjs-dist
 * Email: postal-mime (parsers/emailParser)
 * XML: fast-xml-parser (parsers/xmlParser)
 * Excel: xlsx / SheetJS (parsers/excelParser)
 * CSV: xlsx / SheetJS (parsers/excelParser)
 */

import type { IntakeFileType } from '@/types'
import type { EmailParseResult } from './parsers/emailParser'
import { isApiEnabled, upload } from '../apiClient'

export interface ExtractResult {
  text: string
  metadata: Record<string, string>
}

export interface ExtractResultWithAttachments extends ExtractResult {
  attachments?: Array<{ filename: string; mimeType: string; size: number; content: Uint8Array }>
}

/** Извлечь текст из файла в зависимости от типа */
export async function extractText(
  file: File,
  fileType: IntakeFileType,
): Promise<ExtractResultWithAttachments> {
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
    case 'whatsapp':
      return extractWhatsApp(file)
    case 'telegram':
      return extractTelegram(file)
    case 'text':
      return extractPlainText(file)
    case 'json':
      return extractPlainText(file)
    case 'image':
      return extractImage(file)
    case 'word':
      return extractWord(file)
    default:
      return { text: '', metadata: {} }
  }
}

/** Извлечь текст из вставленного текста */
export function extractFromPaste(text: string): ExtractResult {
  return { text: text.trim(), metadata: {} }
}

// ---- Email (.eml) — postal-mime ----

async function extractEmail(file: File): Promise<ExtractResultWithAttachments> {
  try {
    const { parseEmail } = await import('./parsers/emailParser')
    const result: EmailParseResult = await parseEmail(file)
    return {
      text: result.text,
      metadata: result.metadata,
      attachments: result.attachments,
    }
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

    const fullText = textParts.join('\n')
    const metadata: Record<string, string> = {
      _pdfPages: String(pdf.numPages),
    }
    // Предупреждение если PDF обрезан
    if (pdf.numPages > maxPages) {
      metadata['_pdf.truncated'] = `Обработано ${maxPages} из ${pdf.numPages} страниц`
    }
    // Hint: если текст пустой — возможно скан, нужен OCR
    if (fullText.trim().length === 0 && pdf.numPages > 0) {
      metadata['_pdf.noText'] = 'Текст не извлечён (возможно, скан)'
    }

    return { text: fullText, metadata }
  } catch (err) {
    console.error('PDF extraction error:', err)
    return { text: '', metadata: { _extractError: String(err) } }
  }
}

// ---- Word (.docx) — mammoth.js ----

async function extractWord(file: File): Promise<ExtractResult> {
  try {
    const { parseWord } = await import('./parsers/wordParser')
    return parseWord(file)
  } catch (err) {
    console.error('Word extraction error:', err)
    return { text: '', metadata: { _extractError: `Word: ${String(err)}` } }
  }
}

// ---- Image OCR (server-side or tesseract.js fallback) ----

interface OcrApiResponse {
  text: string
  metadata: Record<string, string>
}

async function extractImageViaApi(file: File): Promise<ExtractResult> {
  const formData = new FormData()
  formData.append('file', file)
  const result = await upload<OcrApiResponse>('/api/ocr', formData)
  return { text: result.text, metadata: { ...result.metadata, _ocrSource: 'server' } }
}

async function extractImage(file: File): Promise<ExtractResult> {
  // Если API доступен — используем серверный OCR (Tesseract CLI, быстрее)
  if (isApiEnabled()) {
    try {
      return await extractImageViaApi(file)
    } catch (err) {
      console.warn('Server OCR failed, falling back to browser:', err)
    }
  }
  // Fallback: browser-side Tesseract.js
  try {
    const { parseImage } = await import('./parsers/ocrParser')
    const result = await parseImage(file)
    return { text: result.text, metadata: { ...result.metadata, _ocrSource: 'browser' } }
  } catch (err) {
    console.error('OCR extraction error:', err)
    return { text: '', metadata: { _ocrError: `OCR: ${String(err)}` } }
  }
}

// ---- WhatsApp (.txt chat export) ----

async function extractWhatsApp(file: File): Promise<ExtractResult> {
  try {
    const { parseWhatsApp } = await import('./parsers/whatsappParser')
    return parseWhatsApp(file)
  } catch (err) {
    console.error('WhatsApp extraction error:', err)
    return extractPlainText(file)
  }
}

// ---- Telegram (result.json export) ----

async function extractTelegram(file: File): Promise<ExtractResult> {
  try {
    const { parseTelegram } = await import('./parsers/telegramParser')
    return parseTelegram(file)
  } catch (err) {
    console.error('Telegram extraction error:', err)
    return extractPlainText(file)
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
