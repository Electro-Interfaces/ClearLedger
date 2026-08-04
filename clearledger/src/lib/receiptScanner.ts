export type ReceiptScanType =
  | 'ean-8' | 'ean-13' | 'upc-a' | 'gtin-14' | 'code-128'
  | 'gs1-datamatrix' | 'gs1-128' | 'tobacco'

export interface ParsedReceiptScan {
  raw: string
  code: string
  productBarcode: string
  type: ReceiptScanType
  markCode: string | null
  checksumValid: boolean | null
}

const AIM_PATTERN = /^\]([A-Za-z])([A-Za-z0-9])/
const CONTROL_EDGES = /^[\x00\x02\x03\t\r\n ]+|[\x00\x02\x03\t\r\n ]+$/g

export function cleanScannerInput(raw: string) {
  const trimmed = raw.replace(CONTROL_EDGES, '')
  return trimmed.replace(AIM_PATTERN, '')
}

export function canonicalMarkCode(raw: string) {
  return cleanScannerInput(raw).replaceAll('<GS>', '\x1d')
}

export function barcodeCandidates(raw: string) {
  const code = cleanScannerInput(raw)
  const result = [code]
  if (/^\d{12}$/.test(code)) result.push(`0${code}`)
  if (/^0\d{12,13}$/.test(code)) result.push(code.slice(1))
  return [...new Set(result.filter(Boolean))]
}

export function sameProductBarcode(left: string | null | undefined, right: string) {
  if (!left) return false
  const rightCodes = new Set(barcodeCandidates(right))
  return barcodeCandidates(left).some((code) => rightCodes.has(code))
}

function gtinBarcode(gtin: string) {
  return gtin.length === 14 && gtin.startsWith('0') ? gtin.slice(1) : gtin
}

function validGtin(code: string) {
  if (![8, 12, 13, 14].includes(code.length) || !/^\d+$/.test(code)) return null
  const body = code.slice(0, -1)
  let sum = 0
  for (let index = body.length - 1, position = 0; index >= 0; index -= 1, position += 1) {
    sum += Number(body[index]) * (position % 2 === 0 ? 3 : 1)
  }
  return (10 - (sum % 10)) % 10 === Number(code.at(-1))
}

export function parseReceiptScan(raw: string): ParsedReceiptScan | null {
  const aim = raw.replace(CONTROL_EDGES, '').match(AIM_PATTERN)?.[0] ?? ''
  const code = cleanScannerInput(raw)
  if (!code) return null

  const gs1 = code.replaceAll('<GS>', '\x1d')
  if (/^01\d{14}/.test(gs1)) {
    const gtin = gs1.slice(2, 16)
    return {
      raw, code, productBarcode: gtinBarcode(gtin),
      type: aim === ']C1' ? 'gs1-128' : 'gs1-datamatrix',
      markCode: code, checksumValid: validGtin(gtin),
    }
  }
  if (/^\d{14}/.test(gs1) && gs1.length >= 21) {
    const gtin = gs1.slice(0, 14)
    return {
      raw, code, productBarcode: gtinBarcode(gtin), type: 'tobacco',
      markCode: code, checksumValid: validGtin(gtin),
    }
  }

  const type: ReceiptScanType = code.length === 8 && /^\d+$/.test(code) ? 'ean-8'
    : code.length === 12 && /^\d+$/.test(code) ? 'upc-a'
      : code.length === 13 && /^\d+$/.test(code) ? 'ean-13'
        : code.length === 14 && /^\d+$/.test(code) ? 'gtin-14'
          : 'code-128'
  return {
    raw, code, productBarcode: gtinBarcode(code), type,
    markCode: null, checksumValid: validGtin(code),
  }
}

export const SCAN_TYPE_LABEL: Record<ReceiptScanType, string> = {
  'ean-8': 'EAN-8', 'ean-13': 'EAN-13', 'upc-a': 'UPC-A', 'gtin-14': 'GTIN-14',
  'code-128': 'Code 128 / внутренний', 'gs1-datamatrix': 'GS1 DataMatrix',
  'gs1-128': 'GS1-128', tobacco: 'табачная маркировка',
}
