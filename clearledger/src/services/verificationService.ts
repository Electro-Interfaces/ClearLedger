/**
 * VerificationService — 10 проверок сверки с эталонными данными.
 *
 * НЕ замена validationService (форма полей), а дополнение:
 * validation проверяет форму, verification проверяет содержание против эталона.
 */

import type { DataEntry, VerificationCheck, VerificationResult, VerificationOverallStatus } from '@/types'
import {
  findCounterpartyByInn, findCounterpartyByName,
  getCounterparties, getContracts,
} from './referenceService'
import { getEntries } from './dataEntryService'
import { getCounterpartyFromMeta, getDocNumberFromMeta } from '@/lib/textUtils'

/**
 * Проверка ИНН (контрольная сумма). Переиспользуем из validationService.
 */
function isValidInn(inn: string): boolean {
  if (!/^\d{10}$|^\d{12}$/.test(inn)) return false
  const digits = inn.split('').map(Number)
  if (digits.length === 10) {
    const weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    const sum = weights.reduce((acc, w, i) => acc + w * digits[i], 0)
    return (sum % 11) % 10 === digits[9]
  }
  const w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
  const w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
  const sum1 = w1.reduce((acc, w, i) => acc + w * digits[i], 0)
  const sum2 = w2.reduce((acc, w, i) => acc + w * digits[i], 0)
  return (sum1 % 11) % 10 === digits[10] && (sum2 % 11) % 10 === digits[11]
}

/**
 * Запустить 10 проверок и вернуть VerificationResult.
 */
export async function verifyEntry(
  entry: DataEntry,
  companyId: string,
): Promise<VerificationResult> {
  const checks: VerificationCheck[] = []
  const meta = entry.metadata
  const inn = meta.inn?.trim() || ''
  const counterpartyName = getCounterpartyFromMeta(meta)
  const docNumber = getDocNumberFromMeta(meta)

  // 1. counterparty_known — контрагент найден в справочнике?
  let counterpartyId: string | undefined
  if (inn) {
    const cp = await findCounterpartyByInn(companyId, inn)
    if (cp) {
      counterpartyId = cp.id
      checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'pass', confidence: 100, message: `Контрагент найден: ${cp.name}` })
    } else if (counterpartyName) {
      const fuzzy = await findCounterpartyByName(companyId, counterpartyName)
      if (fuzzy && fuzzy.confidence >= 0.8) {
        counterpartyId = fuzzy.counterparty.id
        checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'pass', confidence: Math.round(fuzzy.confidence * 100), message: `Контрагент найден (fuzzy ${Math.round(fuzzy.confidence * 100)}%): ${fuzzy.counterparty.name}` })
      } else if (fuzzy) {
        counterpartyId = fuzzy.counterparty.id
        checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'warning', confidence: Math.round(fuzzy.confidence * 100), message: `Возможное совпадение: ${fuzzy.counterparty.name}`, suggestion: `Проверьте: ${fuzzy.counterparty.name} (ИНН: ${fuzzy.counterparty.inn})` })
      } else {
        checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'info', confidence: 0, message: 'Контрагент не найден в справочнике' })
      }
    }
  } else if (counterpartyName) {
    const fuzzy = await findCounterpartyByName(companyId, counterpartyName)
    if (fuzzy && fuzzy.confidence >= 0.8) {
      counterpartyId = fuzzy.counterparty.id
      checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'pass', confidence: Math.round(fuzzy.confidence * 100), message: `Контрагент найден: ${fuzzy.counterparty.name}` })
    } else if (fuzzy) {
      checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'warning', confidence: Math.round(fuzzy.confidence * 100), message: `Возможное совпадение: ${fuzzy.counterparty.name}`, suggestion: `Проверьте контрагента` })
    } else {
      checks.push({ field: 'counterparty', checkType: 'counterparty_known', status: 'info', confidence: 0, message: 'Контрагент не найден в справочнике' })
    }
  }

  // 2. inn_checksum — ИНН валиден?
  if (inn) {
    if (isValidInn(inn)) {
      checks.push({ field: 'inn', checkType: 'inn_checksum', status: 'pass', confidence: 100, message: 'ИНН корректен (контрольная сумма совпадает)' })
    } else {
      checks.push({ field: 'inn', checkType: 'inn_checksum', status: 'fail', confidence: 100, message: 'Некорректный ИНН (контрольная сумма не совпадает)', suggestion: 'Проверьте ИНН вручную' })
    }
  }

  // 3. inn_match — ИНН из документа = ИНН в справочнике?
  if (inn && counterpartyId) {
    const cp = await findCounterpartyByInn(companyId, inn)
    if (cp && cp.id === counterpartyId) {
      checks.push({ field: 'inn', checkType: 'inn_match', status: 'pass', confidence: 100, message: 'ИНН совпадает со справочником' })
    } else if (cp) {
      checks.push({ field: 'inn', checkType: 'inn_match', status: 'fail', confidence: 100, message: `ИНН в документе (${inn}) не совпадает с контрагентом в справочнике`, suggestion: 'Проверьте ИНН или контрагента' })
    }
  }

  // 4. kpp_match — КПП совпадает?
  const kpp = meta.kpp?.trim()
  const refKpp = meta['_ref.counterpartyKpp']
  if (kpp && refKpp) {
    if (kpp === refKpp) {
      checks.push({ field: 'kpp', checkType: 'kpp_match', status: 'pass', confidence: 100, message: 'КПП совпадает' })
    } else {
      checks.push({ field: 'kpp', checkType: 'kpp_match', status: 'warning', confidence: 80, message: `КПП (${kpp}) не совпадает со справочником (${refKpp})`, suggestion: 'Возможно изменился КПП' })
    }
  }

  // 5. doc_number_unique — номер+контрагент+тип уже был?
  if (docNumber && entry.docTypeId) {
    const allEntries = await getEntries(companyId)
    const duplicate = allEntries.find((e) =>
      e.id !== entry.id &&
      getDocNumberFromMeta(e.metadata) === docNumber &&
      e.docTypeId === entry.docTypeId &&
      getCounterpartyFromMeta(e.metadata) === counterpartyName &&
      e.metadata._excluded !== 'true',
    )
    if (duplicate) {
      checks.push({ field: 'docNumber', checkType: 'doc_number_unique', status: 'warning', confidence: 90, message: `Документ №${docNumber} уже зарегистрирован (${duplicate.title})`, suggestion: 'Возможен дубликат' })
    } else {
      checks.push({ field: 'docNumber', checkType: 'doc_number_unique', status: 'pass', confidence: 100, message: 'Номер документа уникален' })
    }
  }

  // 6. contract_exists — для актов/счетов: есть ли базовый договор?
  const needsContract = ['act-work', 'act-acceptance', 'invoice', 'invoice-factura', 'upd', 'torg-12', 'supply-invoice'].includes(entry.docTypeId || '')
  if (needsContract && counterpartyId) {
    const contracts = await getContracts(companyId)
    const cpContracts = contracts.filter((c) => c.counterpartyId === counterpartyId)
    if (cpContracts.length > 0) {
      checks.push({ field: 'contract', checkType: 'contract_exists', status: 'pass', confidence: 100, message: `Найден договор: №${cpContracts[0].number}` })
    } else {
      checks.push({ field: 'contract', checkType: 'contract_exists', status: 'warning', confidence: 60, message: 'Договор с контрагентом не найден в справочнике', suggestion: 'Загрузите договор или добавьте в справочники' })
    }
  } else if (needsContract) {
    checks.push({ field: 'contract', checkType: 'contract_exists', status: 'info', confidence: 0, message: 'Контрагент не привязан — проверка договора невозможна' })
  }

  // 7. amount_within_limit — сумма <= лимит договора?
  const amount = parseFloat(meta.amount || '0')
  const contractLimit = parseFloat(meta['_ref.contractAmountLimit'] || '0')
  if (amount > 0 && contractLimit > 0) {
    if (amount <= contractLimit) {
      checks.push({ field: 'amount', checkType: 'amount_within_limit', status: 'pass', confidence: 100, message: `Сумма (${amount}) в пределах лимита договора (${contractLimit})` })
    } else {
      checks.push({ field: 'amount', checkType: 'amount_within_limit', status: 'warning', confidence: 90, message: `Сумма (${amount}) превышает лимит договора (${contractLimit})`, suggestion: 'Проверьте сумму или обновите лимит договора' })
    }
  }

  // 8. date_valid — дата логична?
  const docDate = parseDate(meta.docDate || meta.date)
  if (docDate) {
    const now = new Date()
    const threeYearsAgo = new Date(now)
    threeYearsAgo.setFullYear(now.getFullYear() - 3)

    if (docDate > now) {
      checks.push({ field: 'docDate', checkType: 'date_valid', status: 'fail', confidence: 100, message: 'Дата документа в будущем', suggestion: 'Проверьте дату документа' })
    } else if (docDate < threeYearsAgo) {
      checks.push({ field: 'docDate', checkType: 'date_valid', status: 'fail', confidence: 90, message: 'Дата документа более 3 лет назад', suggestion: 'Проверьте дату документа' })
    } else {
      checks.push({ field: 'docDate', checkType: 'date_valid', status: 'pass', confidence: 100, message: 'Дата документа в допустимом диапазоне' })
    }
  }

  // 9. new_counterparty — первая операция с контрагентом?
  if (counterpartyName && !counterpartyId) {
    const allCp = await getCounterparties(companyId)
    if (allCp.length > 0) {
      // Справочник не пуст, но этого контрагента нет — новый
      checks.push({ field: 'counterparty', checkType: 'new_counterparty', status: 'info', confidence: 100, message: 'Новый контрагент — первая операция', suggestion: 'Рекомендуется добавить контрагента в справочник' })
    }
  }

  // 10. anomaly_amount — сумма аномальная?
  if (amount > 0 && counterpartyName) {
    const allEntries = await getEntries(companyId)
    const sixMonthsAgo = new Date()
    sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6)

    const similar = allEntries.filter((e) => {
      if (e.id === entry.id) return false
      if (getCounterpartyFromMeta(e.metadata) !== counterpartyName) return false
      const eDate = new Date(e.createdAt)
      return eDate >= sixMonthsAgo
    })

    const amounts = similar
      .map((e) => parseFloat(e.metadata.amount || '0'))
      .filter((a) => a > 0)

    if (amounts.length >= 3) {
      amounts.sort((a, b) => a - b)
      const median = amounts[Math.floor(amounts.length / 2)]
      if (amount > median * 3) {
        checks.push({ field: 'amount', checkType: 'anomaly_amount', status: 'warning', confidence: 75, message: `Сумма (${amount}) превышает медиану (${median}) более чем в 3 раза`, suggestion: 'Проверьте сумму документа' })
      } else {
        checks.push({ field: 'amount', checkType: 'anomaly_amount', status: 'pass', confidence: 100, message: 'Сумма в пределах нормы' })
      }
    }
  }

  // Общий скоринг
  const fails = checks.filter((c) => c.status === 'fail').length
  const warnings = checks.filter((c) => c.status === 'warning').length

  let overallStatus: VerificationOverallStatus
  if (fails >= 2) {
    overallStatus = 'rejected'
  } else if (fails >= 1 || warnings >= 3) {
    overallStatus = 'needs_review'
  } else {
    overallStatus = 'approved'
  }

  const totalChecks = checks.length || 1
  const passCount = checks.filter((c) => c.status === 'pass').length
  const overallConfidence = Math.round((passCount / totalChecks) * 100)

  return {
    entryId: entry.id,
    checks,
    overallStatus,
    overallConfidence,
  }
}

function parseDate(raw: string | undefined): Date | null {
  if (!raw) return null
  // DD.MM.YYYY
  const dotMatch = raw.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
  if (dotMatch) {
    const d = new Date(`${dotMatch[3]}-${dotMatch[2]}-${dotMatch[1]}`)
    return isNaN(d.getTime()) ? null : d
  }
  // YYYY-MM-DD
  const d = new Date(raw)
  return isNaN(d.getTime()) ? null : d
}
