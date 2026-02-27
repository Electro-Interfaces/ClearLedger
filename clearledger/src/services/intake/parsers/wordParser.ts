/**
 * Word парсер.
 * .docx — mammoth.js (Open XML).
 * .doc  — ручное извлечение текста из OLE2 Compound Binary.
 */

import type { ExtractResult } from '../extract'

/** OLE2 magic bytes: D0 CF 11 E0 A1 B1 1A E1 */
const OLE2_MAGIC = [0xd0, 0xcf, 0x11, 0xe0]
/** ZIP magic bytes: PK (50 4B) — .docx это ZIP */
const ZIP_MAGIC = [0x50, 0x4b]

export async function parseWord(file: File): Promise<ExtractResult> {
  const arrayBuffer = await file.arrayBuffer()
  const header = new Uint8Array(arrayBuffer, 0, Math.min(4, arrayBuffer.byteLength))

  // .doc (OLE2) — парсим вручную
  if (matchesMagic(header, OLE2_MAGIC)) {
    return parseDocLegacy(arrayBuffer, file.name)
  }

  // .docx (ZIP) или неизвестный — пробуем mammoth
  if (matchesMagic(header, ZIP_MAGIC) || file.name.toLowerCase().endsWith('.docx')) {
    return parseDocx(arrayBuffer)
  }

  // Fallback: пробуем mammoth, если не удалось — OLE2
  try {
    return await parseDocx(arrayBuffer)
  } catch {
    return parseDocLegacy(arrayBuffer, file.name)
  }
}

/** .docx через mammoth.js */
async function parseDocx(arrayBuffer: ArrayBuffer): Promise<ExtractResult> {
  const mammoth = await import('mammoth')
  const result = await mammoth.extractRawText({ arrayBuffer })
  const text = result.value.trim()

  const metadata: Record<string, string> = { '_word.format': 'docx' }

  if (result.messages.length > 0) {
    metadata._wordWarnings = result.messages
      .map((m) => m.message)
      .join('; ')
  }

  metadata._wordCount = String(text.split(/\s+/).filter(Boolean).length)
  return { text, metadata }
}

/**
 * .doc (legacy) — извлечение текста из OLE2 Compound Binary Format.
 *
 * Стратегия:
 * 1. Ищем WordDocument stream в OLE2-контейнере
 * 2. Извлекаем текст как UTF-16LE (основной формат хранения в Word 97-2003)
 * 3. Fallback: сканируем весь файл на читаемые текстовые фрагменты
 */
function parseDocLegacy(arrayBuffer: ArrayBuffer, fileName: string): ExtractResult {
  const bytes = new Uint8Array(arrayBuffer)
  const metadata: Record<string, string> = { '_word.format': 'doc' }

  // Пробуем извлечь текст из Word Document stream (UTF-16LE)
  let text = extractUtf16Text(bytes)

  // Если UTF-16 дал мало текста — пробуем CP1251 (для русских документов)
  if (text.length < 50) {
    const cp1251Text = extractCp1251Text(bytes)
    if (cp1251Text.length > text.length) {
      text = cp1251Text
      metadata['_word.encoding'] = 'cp1251'
    }
  } else {
    metadata['_word.encoding'] = 'utf16le'
  }

  if (text.length === 0) {
    return {
      text: '',
      metadata: {
        ...metadata,
        _extractError: 'Не удалось извлечь текст из .doc файла',
      },
    }
  }

  // Чистим текст
  text = cleanExtractedText(text)
  metadata._wordCount = String(text.split(/\s+/).filter(Boolean).length)
  metadata['_word.source'] = fileName

  return { text, metadata }
}

/**
 * Извлекает текст из бинарного .doc как UTF-16LE.
 * Word 97-2003 хранит текст документа в UTF-16LE в потоке WordDocument.
 */
function extractUtf16Text(bytes: Uint8Array): string {
  const chunks: string[] = []
  let currentChunk = ''

  // Сканируем парами байт (UTF-16LE)
  for (let i = 0; i < bytes.length - 1; i += 2) {
    const code = bytes[i] | (bytes[i + 1] << 8)

    if (isReadableChar(code)) {
      currentChunk += String.fromCharCode(code)
    } else if (currentChunk.length >= 4) {
      // Сохраняем фрагмент если он достаточно длинный
      chunks.push(currentChunk)
      currentChunk = ''
    } else {
      currentChunk = ''
    }
  }

  if (currentChunk.length >= 4) {
    chunks.push(currentChunk)
  }

  // Берём только значимые фрагменты (> 10 символов)
  return chunks
    .filter((c) => c.length > 10 && hasLetters(c))
    .join('\n')
}

/**
 * Извлекает текст из .doc как CP1251 (Windows-1251).
 * Многие русские .doc файлы хранят текст в этой кодировке.
 */
function extractCp1251Text(bytes: Uint8Array): string {
  const chunks: string[] = []
  let currentChunk = ''

  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i]
    const char = decodeCp1251(b)

    if (char !== null) {
      currentChunk += char
    } else if (currentChunk.length >= 4) {
      chunks.push(currentChunk)
      currentChunk = ''
    } else {
      currentChunk = ''
    }
  }

  if (currentChunk.length >= 4) {
    chunks.push(currentChunk)
  }

  return chunks
    .filter((c) => c.length > 10 && hasLetters(c))
    .join('\n')
}

/** Проверяет что символ читаемый (латиница, кириллица, цифры, знаки) */
function isReadableChar(code: number): boolean {
  // ASCII printable
  if (code >= 0x20 && code <= 0x7e) return true
  // Tab, newline, carriage return
  if (code === 0x09 || code === 0x0a || code === 0x0d) return true
  // Кириллица (Unicode: U+0400..U+04FF)
  if (code >= 0x0400 && code <= 0x04ff) return true
  // Знак №
  if (code === 0x2116) return true
  // Кавычки «»
  if (code === 0x00ab || code === 0x00bb) return true
  // Тире —
  if (code === 0x2014 || code === 0x2013) return true
  return false
}

/** Декодирует байт CP1251 → символ или null если не текстовый */
function decodeCp1251(b: number): string | null {
  // ASCII printable
  if (b >= 0x20 && b <= 0x7e) return String.fromCharCode(b)
  // Tab, newline, CR
  if (b === 0x09 || b === 0x0a || b === 0x0d) return String.fromCharCode(b)
  // Кириллица CP1251: 0xC0-0xFF → U+0410-U+044F (А-я)
  if (b >= 0xc0 && b <= 0xff) return String.fromCharCode(0x0410 + (b - 0xc0))
  // Ё = 0xA8 → U+0401, ё = 0xB8 → U+0451
  if (b === 0xa8) return '\u0401'
  if (b === 0xb8) return '\u0451'
  // № = 0xB9
  if (b === 0xb9) return '\u2116'
  return null
}

/** Проверяет что строка содержит буквы (не только цифры/пунктуация) */
function hasLetters(s: string): boolean {
  return /[a-zA-Zа-яА-ЯёЁ]/.test(s)
}

/** Чистит извлечённый текст: убирает мусор, лишние пробелы */
function cleanExtractedText(text: string): string {
  return text
    // Убираем непечатные символы кроме \n\t
    .replace(/[^\S\n\t]+/g, ' ')
    // Схлопываем множественные переводы строк
    .replace(/\n{3,}/g, '\n\n')
    // Убираем строки состоящие только из спецсимволов
    .replace(/^[^a-zA-Zа-яА-ЯёЁ0-9]*$/gm, '')
    // Убираем пустые строки подряд
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** Проверяет magic bytes */
function matchesMagic(header: Uint8Array, magic: number[]): boolean {
  if (header.length < magic.length) return false
  return magic.every((b, i) => header[i] === b)
}
