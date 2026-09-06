import { upload } from './apiClient'

export interface DocumentText {
  text: string
  sheets?: Array<{ name: string; rows: string[][] }>
  truncated?: boolean
}

export async function readDocumentText(file: File, ocr = false): Promise<DocumentText> {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension === 'docx') {
    const mammoth = await import('mammoth')
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() })
    return { text: result.value.slice(0, 200000), truncated: result.value.length > 200000 }
  }
  if (extension === 'xlsx' || extension === 'xls') {
    const xlsx = await import('xlsx')
    const book = xlsx.read(await file.arrayBuffer(), { type: 'array', sheetRows: 201 })
    let truncated = book.SheetNames.length > 10
    const sheets = book.SheetNames.slice(0, 10).map((name) => {
      const raw = xlsx.utils.sheet_to_json<string[]>(book.Sheets[name], { header: 1, defval: '', raw: false })
      if (raw.length > 200 || raw.some((row) => row.length > 50) || book.Sheets[name]['!fullref']) truncated = true
      return { name, rows: raw.slice(0, 200).map((row) => row.slice(0, 50).map(String)) }
    })
    return { text: sheets.map((sheet) => `${sheet.name}\n${sheet.rows.map((row) => row.join('\t')).join('\n')}`).join('\n\n'), sheets, truncated }
  }
  if (extension === 'pdf') {
    const pdfjs = await import('pdfjs-dist')
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).href
    const document = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise
    try {
      const pages = []
      for (let pageNumber = 1; pageNumber <= Math.min(document.numPages, 20); pageNumber++) {
        const content = await (await document.getPage(pageNumber)).getTextContent()
        pages.push(content.items.map((item) => 'str' in item ? item.str : '').join(' '))
      }
      const text = pages.join('\n\n')
      if (text.trim()) return { text, truncated: document.numPages > 20 }
    } finally { await document.destroy() }
  }
  if (extension === 'txt') return { text: (await file.text()).slice(0, 200000), truncated: file.size > 200000 }
  if (ocr && (extension === 'pdf' || file.type.startsWith('image/'))) {
    const form = new FormData()
    form.append('file', file)
    const result = await upload<{ text: string }>('/api/ocr', form)
    return { text: result.text }
  }
  throw new Error('Текст не извлечён. Реквизиты можно заполнить вручную.')
}

export function suggestDocumentFields(fileName: string, text: string) {
  const number = text.match(/(?:№|исх\.?\s*(?:№)?)\s*([\p{L}\d][\p{L}\d/–—-]{0,79})/iu)?.[1] ?? ''
  const date = text.match(/\b(\d{2})[./](\d{2})[./](\d{4})\b/)
  const iso = date ? `${date[3]}-${date[2]}-${date[1]}` : ''
  return { title: fileName.replace(/\.[^.]+$/, ''), externalNumber: number,
    externalDate: iso && !Number.isNaN(Date.parse(iso)) && new Date(iso).toISOString().slice(0, 10) === iso ? iso : '' }
}
