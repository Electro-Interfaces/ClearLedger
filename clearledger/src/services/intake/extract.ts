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
    case 'dbf':
      return extractDbf(file)
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

// ---- DBF (dBASE) — SheetJS ----

async function extractDbf(file: File): Promise<ExtractResult> {
  try {
    const { parseExcel } = await import('./parsers/excelParser')
    return parseExcel(file)
  } catch (err) {
    console.error('DBF extraction error:', err)
    return { text: '', metadata: { _extractError: `DBF: ${String(err)}` } }
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

// ---- PDF (pdfjs-dist + OCR fallback для сканов) ----

/** Макс. страниц для OCR (Tesseract.js медленный — ограничиваем) */
const PDF_OCR_MAX_PAGES = 5
/** Масштаб рендера страницы для OCR (2x ≈ 150 DPI для A4) */
const PDF_OCR_SCALE = 2

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

    if (pdf.numPages > maxPages) {
      metadata['_pdf.truncated'] = `Обработано ${maxPages} из ${pdf.numPages} страниц`
    }

    // Если текст пустой — скан, запускаем OCR fallback
    if (fullText.trim().length < 30 && pdf.numPages > 0) {
      const ocrResult = await extractPdfViaOcr(pdf, pdfjsLib)
      if (ocrResult.text.trim().length > 0) {
        return {
          text: ocrResult.text,
          metadata: { ...metadata, ...ocrResult.metadata },
        }
      }
      metadata['_pdf.noText'] = 'Текст не извлечён (скан, OCR не помог)'
    }

    return { text: fullText, metadata }
  } catch (err) {
    console.error('PDF extraction error:', err)
    return { text: '', metadata: { _extractError: String(err) } }
  }
}

/**
 * OCR fallback для PDF-сканов.
 * Рендерит страницы в canvas → Blob → Tesseract.js.
 */
async function extractPdfViaOcr(
  pdf: { numPages: number; getPage: (n: number) => Promise<import('pdfjs-dist').PDFPageProxy> },
  _pdfjsLib: typeof import('pdfjs-dist'),
): Promise<ExtractResult> {
  const ocrPages = Math.min(pdf.numPages, PDF_OCR_MAX_PAGES)
  const metadata: Record<string, string> = {
    '_pdf.ocrUsed': 'true',
    '_pdf.ocrPages': String(ocrPages),
    '_ocrSource': 'browser',
  }

  try {
    const Tesseract = await import('tesseract.js')

    const textParts: string[] = []
    let totalConfidence = 0

    for (let i = 1; i <= ocrPages; i++) {
      const page = await pdf.getPage(i)
      const viewport = page.getViewport({ scale: PDF_OCR_SCALE })

      // Рендерим страницу в canvas (pdfjs v5 требует HTMLCanvasElement)
      const canvas = createFallbackCanvas(viewport.width, viewport.height)

      await page.render({ canvas, viewport }).promise

      // Canvas → Blob → Tesseract
      const blob = await canvasToBlob(canvas)
      if (!blob) continue

      const result = await Promise.race([
        Tesseract.recognize(blob, 'rus+eng', {
          logger: () => { /* suppress */ },
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('OCR таймаут')), 60_000),
        ),
      ])

      const pageText = result.data.text.trim()
      if (pageText) {
        textParts.push(pageText)
        totalConfidence += result.data.confidence
      }
    }

    if (textParts.length > 0) {
      metadata['_ocr.confidence'] = String(Math.round(totalConfidence / textParts.length))
      metadata['_ocr.language'] = 'rus+eng'
    }

    if (pdf.numPages > PDF_OCR_MAX_PAGES) {
      metadata['_pdf.ocrTruncated'] = `OCR: ${ocrPages} из ${pdf.numPages} страниц`
    }

    return { text: textParts.join('\n\n'), metadata }
  } catch (err) {
    console.warn('PDF OCR fallback failed:', err)
    metadata['_ocrError'] = String(err)
    return { text: '', metadata }
  }
}

/** Создаёт обычный canvas как fallback для окружений без OffscreenCanvas */
function createFallbackCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

/** Canvas → Blob (работает и с OffscreenCanvas, и с HTMLCanvasElement) */
async function canvasToBlob(canvas: OffscreenCanvas | HTMLCanvasElement): Promise<Blob | null> {
  if (canvas instanceof OffscreenCanvas) {
    return canvas.convertToBlob({ type: 'image/png' })
  }
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
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
