/**
 * Адаптер преобразования сменного отчёта STS → формат UI (ShiftDetails).
 * Перенесено 1:1 из TradeFrame (реальная структура STS API v2).
 * Вход apiResponse = сырой отчёт { psm, release, sales, receipt, money }.
 */

import type {
  ShiftDetails,
  TankSnapshot,
  FuelSalesItem,
  PaymentSalesItem,
  ReceiptItem,
  CashMovementItem,
  PosInfoItem,
  NozzleReading,
} from '@/types/shift-reports-v2'
import { classifyPayment } from '@/utils/paymentUtils'

export class ShiftReportAdapterV2 {
  static toDetails(apiResponse: any, shiftNumber: number, system: number, station: number, stationName?: string, shiftInfo?: any, tankThreshold = 10): ShiftDetails {
    const posInfo = this.extractPosInfo(apiResponse.psm, shiftNumber)
    const nozzleReadings = this.extractNozzleReadings(apiResponse.psm)
    const tanks = this.extractTanks(apiResponse.release, tankThreshold)
    const { fuelSales, paymentSales } = this.extractSales(apiResponse.sales)
    const salesBreakdown = this.extractSalesBreakdown(apiResponse.sales, nozzleReadings)
    const receipts = this.extractReceipts(apiResponse.receipt)

    const totalRevenue = this.calculateTotalRevenue(paymentSales)
    const totalVolume = this.calculateTotalVolume(fuelSales)
    const transactionCount = 0

    let openedAt = new Date().toISOString()
    let closedAt: string | null = null
    let status: 'open' | 'closed' | 'synchronized' = 'open'
    let operator = 'Не указан'

    if (shiftInfo) {
      openedAt = shiftInfo.dt_open || new Date().toISOString()
      closedAt = shiftInfo.dt_close || null
      status = closedAt ? 'closed' : 'open'
      operator = shiftInfo.operator || 'Не указан'
    } else if (posInfo.length > 0) {
      const openDates = posInfo
        .map(p => p.shiftOpenedAt)
        .filter((d): d is string => d !== undefined)
        .sort()
      if (openDates.length > 0) openedAt = openDates[0]

      const closeDates = posInfo
        .map(p => p.shiftClosedAt)
        .filter((d): d is string => d !== undefined)
      const allClosed = posInfo.every(p => p.shiftClosedAt !== undefined)
      if (allClosed && closeDates.length > 0) closedAt = closeDates.sort().reverse()[0]

      operator = posInfo[0].operator || 'Не указан'
      status = allClosed && closedAt ? 'closed' : 'open'
    }

    const cashMovements = this.extractCashMovements(apiResponse.money, shiftNumber, openedAt, closedAt)

    const result = {
      id: `${system}-${station}-${shiftNumber}`,
      shiftNumber,
      openedAt,
      closedAt,
      status,
      operator,
      posNumber: posInfo[0]?.posNumber || 0,
      shift: shiftNumber,

      totalRevenue,
      totalVolume,
      transactionCount,

      cashRevenue: paymentSales
        .filter(p => p.paymentTypeName.toLowerCase().includes('наличн'))
        .reduce((sum, p) => sum + p.cost, 0),
      cardRevenue: paymentSales
        .filter(p => {
          const name = p.paymentTypeName.toLowerCase()
          return name.includes('карт') || name.includes('сбербанк') || name.includes('сбп') ||
                 name.includes('visa') || name.includes('mastercard') || name.includes('эквайр')
        })
        .reduce((sum, p) => sum + p.cost, 0),
      sbpRevenue: paymentSales
        .filter(p => {
          const name = p.paymentTypeName.toLowerCase()
          return name.includes('мобил') || name.includes('онлайн') || name.includes('online')
        })
        .reduce((sum, p) => sum + p.cost, 0),
      fuelCardRevenue: paymentSales
        .filter(p => p.paymentTypeName.toLowerCase().includes('топливн'))
        .reduce((sum, p) => sum + p.cost, 0),
      corporateCardRevenue: paymentSales
        .filter(p => {
          const name = p.paymentTypeName.toLowerCase()
          return name === 'кр' || name.includes('корпоратив') || name.includes('корп.карт') || name.includes('корп карт')
        })
        .reduce((sum, p) => sum + p.cost, 0),
      otherRevenue: 0,

      hasDiscrepancies: tanks.some(t => t.hasExcessError),
      averageCheck: transactionCount > 0 ? totalRevenue / transactionCount : 0,

      stationCode: station,
      stationName,

      posInfo,
      nozzleReadings,
      tanks,
      receipts,
      fuelSales,
      paymentSales,
      salesBreakdown,
      cashMovements,
      reportCreatedAt: new Date().toISOString(),

      salesRaw: apiResponse.sales || [],
      receiptsRaw: apiResponse.receipt || [],
    } as ShiftDetails

    return result
  }

  private static extractPosInfo(psm: any, shiftNumber: number): PosInfoItem[] {
    if (!psm || !psm.total || !Array.isArray(psm.total)) return []
    return psm.total.map((pos: any) => ({
      posNumber: pos.pos || 0,
      shiftNumber: pos.shift || shiftNumber,
      shiftStatus: pos.state || 0,
      shiftOpenedAt: pos.dt_open || undefined,
      shiftClosedAt: pos.dt_close || undefined,
      operator: pos.operator || undefined,
      uptime: undefined,
      lastUpdate: undefined,
    }))
  }

  private static extractNozzleReadings(psm: any): NozzleReading[] {
    if (!psm || !psm.data || !Array.isArray(psm.data)) return []
    return psm.data.map((reading: any) => ({
      pumpNumber: reading.pump || 0,
      nozzle: reading.nozzle || '',
      startCounter: reading.psm_beg || 0,
      endCounter: reading.psm_end || 0,
      volume: parseFloat(reading.release?.volume || '0'),
      amount: parseFloat(reading.release?.amount || '0'),
      price: reading.price || 0,
      cost: parseFloat(reading.release?.cost || '0'),
      fuelCode: reading.service?.service_code || 0,
      fuelName: reading.service?.service_name || 'Неизвестно',
      tankNumber: reading.tank || 0,
      density: reading.density || 0,
    }))
  }

  private static extractTanks(release: any[], threshold = 10): TankSnapshot[] {
    if (!release || !Array.isArray(release)) return []
    return release.map((tank: any) => {
      const volumeBegin = parseFloat(tank.doc_beg?.volume || '0')
      const volumeEnd = parseFloat(tank.doc_end?.volume || '0')
      const volumeReceived = parseFloat(tank.receipt?.volume || '0')
      const volumeDispensed = parseFloat(tank.release?.volume || '0')
      const volumeCalculated = volumeBegin + volumeReceived - volumeDispensed
      const volumeDifference = volumeEnd - volumeCalculated
      return {
        tankNumber: tank.tank || 0,
        fuelCode: tank.service?.service_code || 0,
        fuelName: tank.service?.service_name || 'Неизвестно',
        volumeBegin,
        volumeEnd,
        volumeDispensed,
        volumeReceived,
        volumeCalculated,
        volumeDifference,
        hasExcessError: Math.abs(volumeDifference) > threshold,
        level: tank.level_end,
        temperature: tank.temp_end,
        density: tank.density_end,
        waterLevel: tank.water?.level,
        waterVolume: tank.water?.volume,
      }
    })
  }

  private static extractSales(sales: any[]): { fuelSales: FuelSalesItem[], paymentSales: PaymentSalesItem[] } {
    if (!sales || !Array.isArray(sales)) return { fuelSales: [], paymentSales: [] }
    const fuelSalesMap = new Map<number, FuelSalesItem>()
    const paymentSales: PaymentSalesItem[] = []

    sales.forEach((sale: any) => {
      const paymentTypeName = sale.pay_type?.name || 'Неизвестно'
      const paymentTypeId = sale.pay_type?.id || 0
      let totalCost = 0
      let totalQuantity = 0

      if (sale.fuel && Array.isArray(sale.fuel)) {
        sale.fuel.forEach((fuelItem: any) => {
          const fuelCode = fuelItem.service?.service_code || 0
          const fuelName = fuelItem.service?.service_name || 'Неизвестно'
          const quantity = parseFloat(fuelItem.release?.volume || '0')
          const cost = parseFloat(fuelItem.release?.cost || '0')
          totalCost += cost
          totalQuantity += quantity
          const existing = fuelSalesMap.get(fuelCode)
          if (existing) {
            existing.quantity += quantity
            existing.cost += cost
          } else {
            fuelSalesMap.set(fuelCode, { fuelCode, fuelName, quantity, cost })
          }
        })
      }

      paymentSales.push({ paymentTypeId, paymentTypeName, quantity: totalQuantity, cost: totalCost })
    })

    return { fuelSales: Array.from(fuelSalesMap.values()), paymentSales }
  }

  /**
   * Детализация реализации по топливу и способам оплаты.
   * Прокачка = 0 (АЗС-система не выводит её в этой форме).
   * Разница = Всего − (cash + card + nonCash) — балансовая проверка.
   */
  private static extractSalesBreakdown(sales: any[], _nozzleReadings: NozzleReading[]): any[] {
    if (!sales || !Array.isArray(sales)) return []
    const breakdownMap = new Map<number, any>()

    sales.forEach((sale: any) => {
      const paymentTypeRaw: string = sale.pay_type?.name || ''
      const payKey = paymentTypeRaw.toLowerCase().trim()
      const category = classifyPayment(paymentTypeRaw)

      if (sale.fuel && Array.isArray(sale.fuel)) {
        sale.fuel.forEach((fuelItem: any) => {
          const fuelCode = fuelItem.service?.service_code || 0
          const fuelName = fuelItem.service?.service_name || 'Неизвестно'
          const volume = parseFloat(fuelItem.release?.volume || '0')
          const cost = parseFloat(fuelItem.release?.cost || '0')
          const discount = parseFloat(fuelItem.release?.discount || '0')

          if (!breakdownMap.has(fuelCode)) {
            breakdownMap.set(fuelCode, {
              fuelCode, fuelName,
              pumpVolume: 0, cardVolume: 0, cardCost: 0, discountCost: 0,
              cashVolume: 0, cashCost: 0, corporateVolume: 0, corporateCost: 0,
              nonCashVolume: 0, totalVolume: 0, difference: 0,
              byPayType: {} as Record<string, { displayName: string; category: string; volume: number; cost: number; discount: number }>,
            })
          }

          const breakdown = breakdownMap.get(fuelCode)

          if (payKey) {
            if (!breakdown.byPayType[payKey]) {
              breakdown.byPayType[payKey] = { displayName: paymentTypeRaw, category, volume: 0, cost: 0, discount: 0 }
            }
            breakdown.byPayType[payKey].volume += volume
            breakdown.byPayType[payKey].cost += cost
            breakdown.byPayType[payKey].discount += discount
          }

          switch (category) {
            case 'cash':
              breakdown.cashVolume += volume
              breakdown.cashCost += cost
              breakdown.discountCost += discount
              breakdown.totalVolume += volume
              break
            case 'card':
              breakdown.cardVolume += volume
              breakdown.cardCost += cost
              breakdown.discountCost += discount
              breakdown.totalVolume += volume
              break
            case 'corporate':
            case 'fuel_card':
              breakdown.corporateVolume += volume
              breakdown.corporateCost += cost
              breakdown.nonCashVolume += volume
              breakdown.discountCost += discount
              breakdown.totalVolume += volume
              break
            case 'coupon':
            case 'online':
            case 'other':
            default:
              breakdown.nonCashVolume += volume
              breakdown.discountCost += discount
              breakdown.totalVolume += volume
              break
          }
        })
      }
    })

    breakdownMap.forEach((breakdown) => {
      breakdown.pumpVolume = 0
      breakdown.difference = breakdown.totalVolume - (breakdown.cashVolume + breakdown.cardVolume + breakdown.nonCashVolume)
    })

    return Array.from(breakdownMap.values())
  }

  private static extractReceipts(receipts: any[]): ReceiptItem[] {
    if (!receipts || !Array.isArray(receipts)) return []
    return receipts.map((receipt: any, index: number) => ({
      id: `receipt-${receipt.shift}-${receipt.tank}-${index}`,
      datetime: receipt.dt || new Date().toISOString(),
      tankNumber: receipt.tank || 0,
      fuelCode: receipt.service?.service_code || 0,
      fuelName: receipt.service?.service_name || 'Неизвестно',
      volume: parseFloat(receipt.doc?.volume || '0'),
      amount: parseFloat(receipt.doc?.amount || '0'),
      density: receipt.doc?.density || undefined,
      temperature: receipt.doc?.temp || undefined,
      actualVolume: parseFloat(receipt.fact?.volume || receipt.doc?.volume || '0'),
      actualAmount: parseFloat(receipt.fact?.amount || receipt.doc?.amount || '0'),
      actualDensity: receipt.fact?.density || receipt.doc?.density || undefined,
      actualTemperature: receipt.fact?.temp || receipt.doc?.temp || undefined,
      documentNumber: receipt.ttn || undefined,
      supplier: receipt.base?.name || undefined,
    }))
  }

  /**
   * Движение наличных. API не возвращает dt для записей money — проставляем
   * даты по типу операции: opening → openedAt, прочее → closedAt.
   */
  private static extractCashMovements(
    money: any[],
    shiftNumber: number,
    openedAt?: string,
    closedAt?: string | null,
  ): CashMovementItem[] {
    if (!money || !Array.isArray(money)) return []
    const filtered = money.filter((item: any) => item.shift === shiftNumber)
    const fallbackDt = openedAt || new Date().toISOString()
    const endDt = closedAt || fallbackDt

    const result: CashMovementItem[] = []
    filtered.forEach((item: any, index: number) => {
      const operationId = item.operation?.id || 0
      const operationType = this.mapOperationType(operationId)
      if (operationType === null) return
      result.push({
        id: `money-${item.shift}-${item.pos}-${index}`,
        datetime: operationType === 'opening' ? fallbackDt : endDt,
        operationType,
        amount: item.volume || 0,
        description: item.operation?.name || 'Неизвестная операция',
        posNumber: item.pos,
      })
    })
    return result
  }

  private static mapOperationType(operationId: number): 'income' | 'expense' | 'opening' | 'closing' | null {
    switch (operationId) {
      case 0:
      case 1: return 'opening'
      case 2: return 'expense'
      case 3: return 'income'
      case 4: return null
      case 5: return null
      case 6: return null
      case 7: return 'closing'
      default: return null
    }
  }

  private static calculateTotalRevenue(paymentSales: PaymentSalesItem[]): number {
    return paymentSales.reduce((sum, sale) => sum + sale.cost, 0)
  }

  private static calculateTotalVolume(fuelSales: FuelSalesItem[]): number {
    return fuelSales.reduce((sum, sale) => sum + sale.quantity, 0)
  }
}

export default ShiftReportAdapterV2
