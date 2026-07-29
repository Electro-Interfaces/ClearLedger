/**
 * Ленивая загрузка pdfMake из `public/pdfmake/` (перенос из «Монитора»).
 *
 * Почему не jsPDF, который уже есть в зависимостях: у его встроенных шрифтов нет
 * кириллицы — отчёт получается пустыми квадратами. Существующий рецепт Ledger
 * (`chargeExport`) обходит это снимком DOM, но реестр операций — это десятки тысяч
 * строк, снимком их не выгрузить. pdfMake несёт свой Roboto с кириллицей и умеет
 * многостраничную таблицу, поэтому скрипт и шрифты лежат статикой рядом с бандлом
 * (2 МБ, грузятся только при нажатии «Экспорт в PDF»).
 */
type PdfMakeInstance = {
  vfs: Record<string, string>
  fonts: Record<string, { normal: string; bold: string; italics: string; bolditalics: string }>
  createPdf: (documentDefinition: unknown) => { download: (fileName?: string) => void; open: () => void }
}

declare global {
  interface Window { pdfMake?: PdfMakeInstance }
}

let cached: PdfMakeInstance | null = null
let pending: Promise<PdfMakeInstance> | null = null

function assetUrl(file: string): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`
  return `${base}pdfmake/${file}`
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-pdfmake="${src}"]`)
    if (existing?.dataset.loaded === 'true') return resolve()
    const el = existing ?? document.createElement('script')
    el.addEventListener('load', () => { el.dataset.loaded = 'true'; resolve() }, { once: true })
    el.addEventListener('error', () => reject(new Error(`Не удалось загрузить ${src}`)), { once: true })
    if (!existing) {
      el.src = src
      el.async = true
      el.dataset.pdfmake = src
      document.head.appendChild(el)
    }
  })
}

export async function loadPdfMake(): Promise<PdfMakeInstance> {
  if (cached) return cached
  if (pending) return pending
  pending = (async () => {
    await loadScript(assetUrl('pdfmake.min.js'))
    await loadScript(assetUrl('vfs_fonts.js'))
    if (!window.pdfMake?.createPdf) throw new Error('pdfMake недоступен после загрузки скриптов')
    window.pdfMake.fonts = {
      Roboto: {
        normal: 'Roboto-Regular.ttf', bold: 'Roboto-Medium.ttf',
        italics: 'Roboto-Italic.ttf', bolditalics: 'Roboto-MediumItalic.ttf',
      },
    }
    cached = window.pdfMake
    return cached
  })()
  try {
    return await pending
  } finally {
    pending = null
  }
}
