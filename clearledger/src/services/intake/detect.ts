/**
 * DETECT — определение типа входного файла по MIME и расширению.
 */

import type { IntakeFileType } from '@/types'

const EXT_MAP: Record<string, IntakeFileType> = {
  pdf: 'pdf',
  jpg: 'image', jpeg: 'image', png: 'image', tiff: 'image', tif: 'image', webp: 'image', bmp: 'image',
  xlsx: 'excel', xls: 'excel',
  csv: 'csv',
  xml: 'xml',
  eml: 'email', msg: 'email',
  txt: 'text',
  json: 'json',
  dbf: 'dbf',
  doc: 'word', docx: 'word',
}

const MIME_MAP: Record<string, IntakeFileType> = {
  'application/pdf': 'pdf',
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/tiff': 'image',
  'image/webp': 'image',
  'image/bmp': 'image',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
  'application/vnd.ms-excel': 'excel',
  'text/csv': 'csv',
  'application/xml': 'xml',
  'text/xml': 'xml',
  'message/rfc822': 'email',
  'application/vnd.ms-outlook': 'email',
  'text/plain': 'text',
  'application/json': 'json',
  'application/msword': 'word',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
}

/** Определяет тип файла по MIME и/или расширению */
export function detectFileType(file: File): IntakeFileType {
  // Сначала по расширению — более надёжно
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (EXT_MAP[ext]) return EXT_MAP[ext]

  // Потом по MIME
  if (file.type && MIME_MAP[file.type]) return MIME_MAP[file.type]

  return 'unknown'
}

/** Определяет тип вставленного текста */
export function detectPasteType(text: string): 'email' | 'chat' | 'freetext' {
  // Email: наличие заголовков From: / Subject: / Date:
  const emailHeaders = /^(From|Subject|Date|To|Cc):\s/m
  if (emailHeaders.test(text)) return 'email'

  // WhatsApp / Telegram chat format: timestamp + sender
  const chatPattern = /^\[?\d{1,2}[.\/]\d{1,2}[.\/]\d{2,4},?\s+\d{1,2}:\d{2}/m
  if (chatPattern.test(text)) return 'chat'

  return 'freetext'
}
