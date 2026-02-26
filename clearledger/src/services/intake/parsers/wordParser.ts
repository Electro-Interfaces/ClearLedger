/**
 * Word (.docx) парсер — mammoth.js.
 * Извлекает текст из .docx файлов.
 */

import type { ExtractResult } from '../extract'

export async function parseWord(file: File): Promise<ExtractResult> {
  const mammoth = await import('mammoth')
  const arrayBuffer = await file.arrayBuffer()

  // Извлекаем raw text (без HTML)
  const result = await mammoth.extractRawText({ arrayBuffer })
  const text = result.value.trim()

  const metadata: Record<string, string> = {}

  if (result.messages.length > 0) {
    metadata._wordWarnings = result.messages
      .map((m) => m.message)
      .join('; ')
  }

  // Подсчитаем базовую статистику
  const words = text.split(/\s+/).filter(Boolean).length
  metadata._wordCount = String(words)

  return { text, metadata }
}
