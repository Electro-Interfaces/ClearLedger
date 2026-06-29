/**
 * Детальный просмотр сменного отчёта АЗС — форма «Детали смены» как в TradePoint
 * (перенос ShiftDetailsModal из TradeFrame 1:1). 5 вкладок: Состав смены ·
 * Состояние резервуаров · Поступления · Расшифровка реализации · Движение наличных.
 *
 * Контракт точки входа сохранён ({shiftId, open, onClose}) — открывается из
 * карточки канала (вкладка «Загружено»). Данные строятся адаптером из сырого
 * отчёта STS (buildShiftDetails).
 */
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { AlertTriangle, Loader2 } from 'lucide-react'
import React from 'react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIsMobile } from '@/hooks/use-mobile'
import { getShiftDetail, type ShiftDetail } from '@/services/fuel/fuelMappingService'
import { buildShiftDetails } from '@/services/fuel/shiftDetailsBuilder'
import { useFuelName } from '@/hooks/useFuelName'
import { isCashOrCard } from '@/utils/paymentUtils'
import { getShiftStatusBadgeClass, getShiftStatusConfig } from './shiftStatus'

export function ShiftDetailsDialog({ shiftId, open, onClose, tankThreshold = 10 }: {
  shiftId: string | null; open: boolean; onClose: () => void
  /** Порог расхождения по резервуару (л) из настроек канала. */
  tankThreshold?: number
}) {
  const isMobile = useIsMobile()
  const { data, isLoading } = useQuery<ShiftDetail>({
    queryKey: ['shift-detail', shiftId],
    queryFn: () => getShiftDetail(shiftId!),
    enabled: !!shiftId && open,
  })

  const fuelName = useFuelName()
  const built = data ? buildShiftDetails(data, tankThreshold, fuelName) : null
  const details = built?.details ?? null

  const thClass = isMobile ? 'px-1 py-1' : 'px-2 py-2'
  const tdClass = isMobile ? 'px-1 py-1' : 'px-3 py-2'

  const formatCurrency = (value: number) =>
    value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽'
  const formatDateTime = (s: string) => format(new Date(s), 'dd.MM.yyyy HH:mm', { locale: ru })

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-[98vw] sm:max-w-[98vw] w-[98vw] h-[95vh] bg-card border-border flex flex-col overflow-hidden">
        <DialogHeader>
          <div className="flex-1 mr-10">
            <DialogTitle className={`${isMobile ? 'text-lg' : 'text-xl'} font-semibold text-foreground flex items-center gap-3`}>
              <span>Детали смены #{details?.shiftNumber ?? ''}</span>
              {details && (() => {
                const status = getShiftStatusConfig(details.status, details.openedAt, details.hasDiscrepancies)
                const StatusIcon = status.icon
                return (
                  <Badge className={`${getShiftStatusBadgeClass(status.tone)} flex items-center gap-1`}>
                    <StatusIcon className="w-3 h-3" />
                    {status.label}
                  </Badge>
                )
              })()}
            </DialogTitle>
            {details?.stationName && (
              <p className={`text-muted-foreground ${isMobile ? 'text-xs' : 'text-sm'} mt-1`}>{details.stationName}</p>
            )}
          </div>
        </DialogHeader>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : !details ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">Не удалось загрузить детали смены</div>
        ) : (
          <div className={`${isMobile ? 'space-y-2' : 'space-y-4'} flex-1 overflow-y-auto`}>
            {/* Баннер приближённых данных (смена без сырого отчёта STS) */}
            {built && !built.exact && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/5 px-3 py-2 text-amber-300/90 text-xs">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>Реализация показана приближённо (по каналам оплаты): смена загружена до сохранения сырого отчёта STS. Переигрaйте период канала для точной формы.</span>
              </div>
            )}

            {/* Основная информация */}
            <div className={`grid grid-cols-1 md:grid-cols-4 ${isMobile ? 'gap-1.5' : 'gap-2'}`}>
              <InfoCard label="Статус" isMobile={isMobile}>
                {(() => {
                  const status = getShiftStatusConfig(details.status, details.openedAt, details.hasDiscrepancies)
                  const StatusIcon = status.icon
                  return (
                    <Badge className={`${getShiftStatusBadgeClass(status.tone)} flex items-center gap-1 w-fit ${isMobile ? 'text-xs' : ''}`}>
                      <StatusIcon className={isMobile ? 'w-2.5 h-2.5' : 'w-3 h-3'} />
                      {status.label}
                    </Badge>
                  )
                })()}
              </InfoCard>
              <InfoCard label="Открыта" isMobile={isMobile}>
                <span className={`text-foreground font-semibold ${isMobile ? 'text-xs' : 'text-sm'}`}>{formatDateTime(details.openedAt)}</span>
              </InfoCard>
              <InfoCard label="Закрыта" isMobile={isMobile}>
                <span className={`text-foreground font-semibold ${isMobile ? 'text-xs' : 'text-sm'}`}>{details.closedAt ? formatDateTime(details.closedAt) : '—'}</span>
              </InfoCard>
              <InfoCard label="Оператор" isMobile={isMobile}>
                <span className={`text-foreground font-semibold ${isMobile ? 'text-xs' : 'text-sm'}`}>{details.operator}</span>
              </InfoCard>
            </div>

            <Tabs defaultValue="composition" className="w-full">
              <TabsList className={`bg-secondary w-full justify-start overflow-x-auto ${isMobile ? 'h-auto' : ''}`}>
                <TabsTrigger value="composition" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>{isMobile ? 'Состав' : 'Состав смены'}</TabsTrigger>
                <TabsTrigger value="tanks" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>{isMobile ? 'Резервуары' : 'Состояние резервуаров'}</TabsTrigger>
                <TabsTrigger value="receipts" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>Поступления</TabsTrigger>
                <TabsTrigger value="sales" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>{isMobile ? 'Реализация' : 'Расшифровка реализации'}</TabsTrigger>
                <TabsTrigger value="cash" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>{isMobile ? 'Наличные' : 'Движение наличных'}</TabsTrigger>
              </TabsList>

              {/* ── Состав смены — Показания счётных механизмов ── */}
              <TabsContent value="composition" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className={`${isMobile ? 'mb-2' : 'mb-4'} text-foreground/80`}>
                  <p className={isMobile ? 'text-xs' : ''}>Смена с {details.openedAt ? formatDateTime(details.openedAt) : '—'} до {details.closedAt ? formatDateTime(details.closedAt) : '—'}</p>
                </div>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className={`w-full border-collapse ${isMobile ? 'text-xs' : 'text-sm'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-left text-foreground border-r-2 border-border`} rowSpan={4}>{isMobile ? 'Топливо' : 'Наименование нефтепродуктов'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={4}>{isMobile ? 'Рез.' : 'N Резервуара'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={4}>{isMobile ? 'Пл.' : 'Плотн кг/м3'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={5}>{isMobile ? 'Показания ТРК' : 'Показание счетных механизмов'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={4}>{isMobile ? 'Цена' : 'Цена за литр руб.'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={4}>{isMobile ? 'Сумма' : 'Сумма, руб.'}</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={2}>{isMobile ? 'Погр.' : 'Погрешность ТРК'}</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>№ ТРК</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>{isMobile ? 'Кон.' : 'на конец смены л'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>{isMobile ? 'Нач.' : 'на начало смены л'}</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>расход</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>{isMobile ? '%' : 'проц.'}</th>
                        <th className={`${thClass} text-center text-foreground`} rowSpan={3}>л</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>л</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>кг</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.fuelSales.map((fuel) => {
                        const tank = details.tanks.find(t => t.fuelCode === fuel.fuelCode)
                        const nozzles = details.nozzleReadings.filter(n => n.fuelCode === fuel.fuelCode)
                        const totalStartCounter = nozzles.reduce((sum, n) => sum + n.startCounter, 0)
                        const totalEndCounter = nozzles.reduce((sum, n) => sum + n.endCounter, 0)
                        const totalVolume = nozzles.reduce((sum, n) => sum + n.volume, 0)
                        const totalAmount = nozzles.reduce((sum, n) => sum + n.amount, 0)
                        const totalCost = nozzles.reduce((sum, n) => sum + n.cost, 0)
                        return (
                          <React.Fragment key={fuel.fuelCode}>
                            {nozzles.map((nozzle, nIdx) => (
                              <tr key={`${fuel.fuelCode}-${nozzle.nozzle}`} className="border-b border-border">
                                {nIdx === 0 ? (
                                  <>
                                    <td className={`${tdClass} text-foreground font-medium border-r-2 border-border`} rowSpan={nozzles.length + 1}>{fuel.fuelName}</td>
                                    <td className={`${tdClass} text-center text-foreground border-r-2 border-border`} rowSpan={nozzles.length + 1}>{tank?.tankNumber || '—'}</td>
                                    <td className={`${tdClass} text-center text-foreground border-r-2 border-border`} rowSpan={1}>{nozzle.density ? nozzle.density.toFixed(1) : '—'}</td>
                                  </>
                                ) : (
                                  <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}></td>
                                )}
                                <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{nozzle.nozzle}</td>
                                <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{nozzle.endCounter.toFixed(2)}</td>
                                <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{nozzle.startCounter.toFixed(2)}</td>
                                <td className={`${tdClass} text-center text-foreground font-medium border-r-2 border-border`}>{nozzle.volume.toFixed(2)}</td>
                                <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{nozzle.amount.toFixed(2)}</td>
                                <td className={`${tdClass} text-center text-foreground font-medium border-r-2 border-border`}>{nozzle.price.toFixed(2)}</td>
                                <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{formatCurrency(nozzle.cost)}</td>
                                <td className={`${tdClass} text-center text-muted-foreground border-r-2 border-border`}>0.00</td>
                                <td className={`${tdClass} text-center text-muted-foreground`}>0.000</td>
                              </tr>
                            ))}
                            <tr className="border-b-2 border-border bg-secondary/50">
                              <td className={`${tdClass} text-foreground font-bold`}>Всего:</td>
                              <td className={`${tdClass} border-r-2 border-border`}></td>
                              <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{totalEndCounter.toFixed(2)}</td>
                              <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{totalStartCounter.toFixed(2)}</td>
                              <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{totalVolume.toFixed(2)}</td>
                              <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{totalAmount.toFixed(2)}</td>
                              <td className={`${tdClass} border-r-2 border-border`}></td>
                              <td className={`${tdClass} text-right text-foreground font-bold border-r-2 border-border`}>{formatCurrency(totalCost)}</td>
                              <td className={`${tdClass} border-r-2 border-border`}></td>
                              <td className={tdClass}></td>
                            </tr>
                          </React.Fragment>
                        )
                      })}
                      <tr className="border-t-2 border-border bg-secondary">
                        <td className={`${tdClass} text-foreground font-bold text-lg`}>ИТОГО:</td>
                        <td className={`${tdClass} border-r-2 border-border`}></td>
                        <td className={`${tdClass} border-r-2 border-border`}></td>
                        <td className={`${tdClass} border-r-2 border-border`}></td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.nozzleReadings.reduce((sum, n) => sum + n.endCounter, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.nozzleReadings.reduce((sum, n) => sum + n.startCounter, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.nozzleReadings.reduce((sum, n) => sum + n.volume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.nozzleReadings.reduce((sum, n) => sum + n.amount, 0).toFixed(2)}</td>
                        <td className={`${tdClass} border-r-2 border-border`}></td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r-2 border-border`}>{formatCurrency(details.nozzleReadings.reduce((sum, n) => sum + n.cost, 0))}</td>
                        <td className={`${tdClass} border-r-2 border-border`}></td>
                        <td className={tdClass}></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 text-xs text-muted-foreground"><p>* Погрешность ТРК недоступна в текущей версии API</p></div>
              </TabsContent>

              {/* ── Расшифровка реализации ── */}
              <TabsContent value="sales" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Расшифровка реализации</h3></div>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className={`w-full border-collapse ${isMobile ? 'text-xs' : 'text-sm'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2} rowSpan={2}>Нефтепродукты, товары</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Прокачка<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>По картам</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Скидка<br/>руб.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>За наличные</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Безнал.<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Всего<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground`} rowSpan={2}>Разница<br/>л.</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>руб.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>руб.</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Код</th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={`${thClass} border-r-2 border-border`}></th>
                        <th className={thClass}></th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.salesBreakdown.map((item, idx) => (
                        <tr key={idx} className="border-b border-border">
                          <td className={`${tdClass} text-foreground font-medium border-r-2 border-border`}>{item.fuelName}</td>
                          <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{item.fuelCode}</td>
                          <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{item.pumpVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{item.cardVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{formatCurrency(item.cardCost)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{item.discountCost.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{item.cashVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{formatCurrency(item.cashCost)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{item.nonCashVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground font-medium border-r-2 border-border`}>{item.totalVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground`}>{item.difference.toFixed(2)}</td>
                        </tr>
                      ))}
                      <tr className="border-t-2 border-border bg-secondary/50">
                        <td className={`${tdClass} text-foreground font-bold`} colSpan={2}>Всего:</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.pumpVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.cardVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r-2 border-border`}>{formatCurrency(details.salesBreakdown.reduce((s, i) => s + i.cardCost, 0))}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.discountCost, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.cashVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r-2 border-border`}>{formatCurrency(details.salesBreakdown.reduce((s, i) => s + i.cashCost, 0))}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.nonCashVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{details.salesBreakdown.reduce((s, i) => s + i.totalVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold`}>{details.salesBreakdown.reduce((s, i) => s + i.difference, 0).toFixed(2)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* Безналичная реализация — динамические колонки по сырым pay_type */}
                <div className="mt-8">
                  <h4 className="text-md font-semibold text-foreground mb-3 text-center">Безналичная реализация</h4>
                  <div className="overflow-x-auto rounded-lg border border-border">
                    {(() => {
                      const salesRaw = details.salesRaw || []
                      const paymentTypesSet = new Map<string, string>()
                      salesRaw.forEach((sale: any) => {
                        const payName = sale.pay_type?.name || ''
                        if (payName && !isCashOrCard(payName)) {
                          const key = payName.toLowerCase().trim()
                          if (!paymentTypesSet.has(key)) paymentTypesSet.set(key, payName)
                        }
                      })
                      const paymentTypes = Array.from(paymentTypesSet.entries())

                      const fuelGroups = new Map<number, { fuelCode: number; fuelName: string; byPayType: Record<string, number> }>()
                      salesRaw.forEach((sale: any) => {
                        const payName = sale.pay_type?.name || ''
                        const payKey = payName.toLowerCase().trim()
                        if (!payName || isCashOrCard(payName)) return
                        sale.fuel?.forEach((fuelItem: any) => {
                          const fuelCode = fuelItem.service?.service_code || 0
                          const fuelName = fuelItem.service?.service_name || 'Неизвестно'
                          const volume = Math.abs(parseFloat(fuelItem.release?.volume || '0'))
                          if (!fuelGroups.has(fuelCode)) fuelGroups.set(fuelCode, { fuelCode, fuelName, byPayType: {} })
                          const group = fuelGroups.get(fuelCode)!
                          group.byPayType[payKey] = (group.byPayType[payKey] || 0) + volume
                        })
                      })
                      const rows = Array.from(fuelGroups.values())

                      const totals: Record<string, number> = {}
                      paymentTypes.forEach(([key]) => { totals[key] = 0 })
                      rows.forEach(row => { paymentTypes.forEach(([key]) => { totals[key] += row.byPayType[key] || 0 }) })
                      const grandTotal = Object.values(totals).reduce((s, v) => s + v, 0)

                      if (paymentTypes.length === 0) return <p className="text-sm text-muted-foreground text-center py-4">Нет данных о безналичной реализации</p>

                      return (
                        <table className="w-full text-sm border-collapse">
                          <thead className="bg-secondary/80">
                            <tr className="border-b-2 border-border">
                              <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Наименование</th>
                              <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Код</th>
                              {paymentTypes.map(([key, name]) => (
                                <th key={key} className={`${thClass} text-center text-foreground border-r-2 border-border`}>{name}<br/>л.</th>
                              ))}
                              <th className={`${thClass} text-center text-foreground`}>ИТОГО б/н<br/>л.</th>
                            </tr>
                          </thead>
                          <tbody className="bg-card">
                            {rows.map((row, idx) => {
                              const rowTotal = paymentTypes.reduce((s, [key]) => s + (row.byPayType[key] || 0), 0)
                              return (
                                <tr key={idx} className="border-b border-border">
                                  <td className={`${tdClass} text-foreground font-medium border-r-2 border-border`}>{row.fuelName}</td>
                                  <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{row.fuelCode}</td>
                                  {paymentTypes.map(([key]) => (
                                    <td key={key} className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{(row.byPayType[key] || 0).toFixed(2)}</td>
                                  ))}
                                  <td className={`${tdClass} text-center text-foreground font-medium`}>{rowTotal.toFixed(2)}</td>
                                </tr>
                              )
                            })}
                            <tr className="border-t-2 border-border bg-secondary/50">
                              <td className={`${tdClass} text-foreground font-bold text-right`} colSpan={2}>Всего:</td>
                              {paymentTypes.map(([key]) => (
                                <td key={key} className={`${tdClass} text-center text-foreground font-bold border-r-2 border-border`}>{totals[key].toFixed(2)}</td>
                              ))}
                              <td className={`${tdClass} text-center text-foreground font-bold`}>{grandTotal.toFixed(2)}</td>
                            </tr>
                          </tbody>
                        </table>
                      )
                    })()}
                  </div>
                </div>
              </TabsContent>

              {/* ── Состояние резервуаров ── */}
              <TabsContent value="tanks" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Состояние резервуаров</h3></div>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className={`w-full border-collapse ${isMobile ? 'text-xs' : 'text-sm'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-left text-foreground border-r-2 border-border`} rowSpan={3}>Наименование<br/>нефте-<br/>продуктов</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>N<br/>Резер-<br/>вуара</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={3}>Плотн.<br/>на<br/>начало<br/>смены<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Книжный остаток<br/>на<br/>начало смены</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Поступление<br/>в т.ч. прокачка</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Расход</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={10}>Остаток на конец смены</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Плотн.<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>Темп<br/>C</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>общий<br/>уров.<br/>см</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>общий<br/>объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>уров.<br/>воды<br/>см</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>объем<br/>воды<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Факт.остаток н/п.</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={2}>расчетн.кн.ост.</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>литры</th>
                        <th className={`${thClass} text-center text-foreground`}>кг</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.tanks.length === 0 ? (
                        <tr><td colSpan={19} className="px-4 py-8 text-center text-muted-foreground">Данные по резервуарам недоступны. На данной торговой точке отсутствуют автоматические уровнемеры или данные не передаются в систему.</td></tr>
                      ) : (
                        details.tanks.map((tank, idx) => (
                          <tr key={idx} className={`border-b border-border ${tank.hasExcessError ? 'bg-destructive/10' : ''}`}
                            title={tank.hasExcessError ? `Расхождение: факт ${tank.volumeEnd.toFixed(2)} л vs расчёт ${tank.volumeCalculated.toFixed(2)} л (Δ ${tank.volumeDifference.toFixed(2)} л)` : undefined}>
                            <td className={`${tdClass} text-foreground font-medium border-r-2 border-border`}>{tank.fuelName}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.tankNumber}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.density ? tank.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{tank.volumeBegin.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{(tank.volumeBegin * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{tank.volumeReceived.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{(tank.volumeReceived * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{tank.volumeDispensed.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{(tank.volumeDispensed * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.density ? tank.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.temperature?.toFixed(1) || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.level?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{tank.volumeEnd.toFixed(2)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.waterLevel?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{tank.waterVolume?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r-2 border-border`}>{tank.volumeEnd.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r-2 border-border`}>{(tank.volumeEnd * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right font-medium border-r-2 border-border ${tank.hasExcessError ? 'text-destructive' : 'text-foreground'}`}>
                              {tank.volumeCalculated.toFixed(2)}
                              {tank.hasExcessError && (
                                <span className="block text-[10px] font-normal">Δ {tank.volumeDifference > 0 ? '+' : ''}{tank.volumeDifference.toFixed(2)} л</span>
                              )}
                            </td>
                            <td className={`${tdClass} text-right text-foreground`}>{(tank.volumeCalculated * (tank.density || 1)).toFixed(2)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </TabsContent>

              {/* ── Поступления ── */}
              <TabsContent value="receipts" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Расшифровка поступлений</h3></div>
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className={`w-full border-collapse ${isMobile ? 'text-xs' : 'text-sm'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Нефтепродукты</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={2}>Поставщик</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>№<br/>Докум.</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} rowSpan={2}>№<br/>рез</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`} colSpan={4}>По документу</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={4}>Фактически</th>
                      </tr>
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Код</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Код</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Плотн<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Масса<br/>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Темп.<br/>°C</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Плотн<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r-2 border-border`}>Масса<br/>кг</th>
                        <th className={`${thClass} text-center text-foreground`}>Темп.<br/>°C</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.receipts.length === 0 ? (
                        <tr><td colSpan={14} className="px-4 py-8 text-center text-muted-foreground">Нет поступлений за период смены</td></tr>
                      ) : (
                        details.receipts.map((receipt, idx) => (
                          <tr key={idx} className="border-b border-border">
                            <td className={`${tdClass} text-foreground border-r-2 border-border`}>{receipt.fuelName}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.fuelCode}</td>
                            <td className={`${tdClass} text-foreground border-r-2 border-border`}>{receipt.supplier || 'Нефтебаза'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>1</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.documentNumber || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.tankNumber}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.volume.toFixed(0)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.density ? receipt.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.amount ? receipt.amount.toFixed(0) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.temperature ? receipt.temperature.toFixed(1) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.actualVolume ? receipt.actualVolume.toFixed(0) : receipt.volume.toFixed(0)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.actualDensity ? receipt.actualDensity.toFixed(4) : (receipt.density ? receipt.density.toFixed(4) : '—')}</td>
                            <td className={`${tdClass} text-center text-foreground border-r-2 border-border`}>{receipt.actualAmount ? receipt.actualAmount.toFixed(0) : (receipt.amount ? receipt.amount.toFixed(0) : '—')}</td>
                            <td className={`${tdClass} text-center text-foreground`}>{receipt.actualTemperature ? receipt.actualTemperature.toFixed(1) : (receipt.temperature ? receipt.temperature.toFixed(1) : '—')}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </TabsContent>

              {/* ── Движение наличных ── */}
              <TabsContent value="cash" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Движение наличных денег</h3></div>
                {(() => {
                  const revenue = details.paymentSales.find(p => p.paymentTypeName.toLowerCase().includes('наличн'))?.cost || 0
                  const openingAmount = details.cashMovements.filter(m => m.operationType === 'closing').reduce((sum, m) => sum + m.amount, 0)
                  const incomeAmount = 0
                  const closingAmount = openingAmount + incomeAmount + revenue
                  const totalIncome = openingAmount + incomeAmount + revenue
                  const toBankAmount = 0
                  const cashOutAmount = 0
                  const totalExpense = toBankAmount + cashOutAmount + closingAmount
                  return (
                    <div className="space-y-1">
                      <CashRow label="Принято по смене" value={formatCurrency(openingAmount)} />
                      <CashRow label="Внесено за смену" value={formatCurrency(incomeAmount)} />
                      <CashRow label="Выручка за смену" value={formatCurrency(revenue)} />
                      <div className="flex justify-between items-center py-2 bg-secondary/30"><span className="text-foreground font-semibold pl-16">Итого:</span><span className="text-foreground font-bold">{formatCurrency(totalIncome)}</span></div>
                      <CashRow label="Сдано в банк" value={formatCurrency(toBankAmount)} />
                      <CashRow label="Выдано наличными" value={formatCurrency(cashOutAmount)} />
                      <CashRow label="Передано по смене" value={formatCurrency(closingAmount)} />
                      <div className="flex justify-between items-center py-2 bg-secondary/30"><span className="text-foreground font-semibold pl-16">Итого:</span><span className="text-foreground font-bold">{formatCurrency(totalExpense)}</span></div>
                    </div>
                  )
                })()}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function InfoCard({ label, isMobile, children }: { label: string; isMobile: boolean; children: React.ReactNode }) {
  return (
    <div className={`bg-secondary/50 rounded-lg ${isMobile ? 'p-1.5' : 'p-2.5'}`}>
      <div className={`text-muted-foreground ${isMobile ? 'text-[10px]' : 'text-xs'} mb-0.5`}>{label}</div>
      <div className={isMobile ? 'mt-0.5' : 'mt-1'}>{children}</div>
    </div>
  )
}

function CashRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center py-2">
      <span className="text-foreground pl-8">{label}</span>
      <span className="text-foreground font-medium">{value}</span>
    </div>
  )
}
