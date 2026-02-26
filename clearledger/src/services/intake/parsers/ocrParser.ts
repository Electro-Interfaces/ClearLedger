/**
 * OCR Parser — распознавание текста из изображений через tesseract.js.
 * Поддержка русского языка (rus), lazy-загрузка (~12 МБ модель).
 *
 * Ограничения:
 * - Максимальный размер: 10 МБ (для стабильности в браузере)
 * - Языки: rus + eng
 * - Работает в Web Worker (не блокирует UI)
 */

import type { ExtractResult } from '../extract'

const MAX_OCR_SIZE = 10 * 1024 * 1024 // 10 MB
const OCR_TIMEOUT_MS = 30_000 // 30 секунд

export interface OcrParseResult extends ExtractResult {
  confidence: number
}

export async function parseImage(file: File): Promise<OcrParseResult> {
  if (file.size > MAX_OCR_SIZE) {
    return {
      text: '',
      metadata: { _ocrError: `Файл слишком большой для OCR (${(file.size / 1024 / 1024).toFixed(1)} МБ, лимит 10 МБ)` },
      confidence: 0,
    }
  }

  try {
    const Tesseract = await import('tesseract.js')

    const result = await Promise.race([
      Tesseract.recognize(file, 'rus+eng', {
        logger: () => { /* suppress progress logs */ },
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('OCR таймаут (30 сек.)')), OCR_TIMEOUT_MS),
      ),
    ])

    const text = result.data.text.trim()
    const confidence = Math.round(result.data.confidence)

    const metadata: Record<string, string> = {
      '_ocr.confidence': String(confidence),
      '_ocr.language': 'rus+eng',
    }

    // Извлекаем размеры (если есть)
    if (result.data.hocr) {
      metadata['_ocr.hocr'] = 'available'
    }

    return { text, metadata, confidence }
  } catch (err) {
    console.error('OCR error:', err)
    return {
      text: '',
      metadata: { _ocrError: `OCR: ${String(err)}` },
      confidence: 0,
    }
  }
}
