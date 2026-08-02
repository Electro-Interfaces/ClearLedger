/**
 * Детальный просмотр сменного отчёта АЗС — форма «Детали смены» как в TradePoint
 * (перенос ShiftDetailsModal из TradeFrame 1:1). 5 вкладок: Состав смены ·
 * Состояние резервуаров · Поступления · Расшифровка реализации · Движение наличных.
 *
 * Контракт точки входа сохранён ({shiftId, open, onClose}) — открывается из
 * карточки канала (вкладка «Загружено»). Данные строятся адаптером из сырого
 * отчёта STS (buildShiftDetails).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { AlertTriangle, Loader2, Save, RotateCcw, Pencil } from 'lucide-react'
import React, { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DualScrollX } from '@/components/common/DualScrollX'
import { useIsMobile } from '@/hooks/use-mobile'
import {
  getShiftDetail, patchShiftSales, resetShiftSaleOverrides, setShiftCorrectionNote,
  type ShiftDetail, type ShiftSale, type ShiftSaleEdit,
} from '@/services/fuel/fuelMappingService'
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

  const thClass = isMobile ? 'px-1 py-0.5' : 'px-2 py-1'
  const tdClass = isMobile ? 'px-1 py-0.5' : 'px-2 py-1'
  /**
   * Числовая ячейка: ВПРАВО и табличными цифрами. По центру разряды не встают в
   * колонку, и «222 954,71» рядом с «46 800,17» глазом не сравнить — а вся эта
   * таблица существует ради сравнения показаний счётчиков.
   */
  const numCls = `${tdClass} text-right tabular-nums text-foreground`
  /** Разделитель СМЫСЛОВОЙ группы колонок, а не каждой: 14 толстых линий читаются
   *  как сетка Excel и заглушают сами цифры. */
  const sep = 'border-r border-border/60'

  /** Показания счётчиков — ru-RU с разрядами: без пробелов «4146258.96» не читается. */
  const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
                <TabsTrigger value="edit" className={`font-medium data-[state=active]:bg-secondary data-[state=active]:text-foreground data-[state=active]:font-semibold data-[state=active]:shadow-sm ${isMobile ? 'text-xs px-2 py-1.5' : 'px-4 py-2'}`}>Корректировка</TabsTrigger>
              </TabsList>

              {/* ── Состав смены — Показания счётных механизмов ── */}
              <TabsContent value="composition" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className={`${isMobile ? 'mb-2' : 'mb-4'} text-foreground/80`}>
                  <p className={isMobile ? 'text-xs' : ''}>Смена с {details.openedAt ? formatDateTime(details.openedAt) : '—'} до {details.closedAt ? formatDateTime(details.closedAt) : '—'}</p>
                </div>
                <DualScrollX>
                  <table className={`w-max min-w-full border-collapse leading-tight ${isMobile ? 'text-xs' : 'text-[13px]'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-left text-foreground border-r border-border/60`} rowSpan={4}>{isMobile ? 'Топливо' : 'Наименование нефтепродуктов'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={4}>{isMobile ? 'Рез.' : 'N Резервуара'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={4}>{isMobile ? 'Пл.' : 'Плотн кг/м3'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={5}>{isMobile ? 'Показания ТРК' : 'Показание счетных механизмов'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={4}>{isMobile ? 'Цена' : 'Цена за литр руб.'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={4}>{isMobile ? 'Сумма' : 'Сумма, руб.'}</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={2}>{isMobile ? 'Погр.' : 'Погрешность ТРК'}</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>№ ТРК</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>{isMobile ? 'Кон.' : 'на конец смены л'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>{isMobile ? 'Нач.' : 'на начало смены л'}</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>расход</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>{isMobile ? '%' : 'проц.'}</th>
                        <th className={`${thClass} text-center text-foreground`} rowSpan={3}>л</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>л</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>кг</th>
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
                                    <td className={`${tdClass} text-foreground font-medium border-r border-border/60`} rowSpan={nozzles.length + 1}>{fuel.fuelName}</td>
                                    <td className={`${tdClass} text-center text-foreground border-r border-border/60`} rowSpan={nozzles.length + 1}>{tank?.tankNumber || '—'}</td>
                                    <td className={`${tdClass} text-center text-foreground border-r border-border/60`} rowSpan={1}>{nozzle.density ? nozzle.density.toFixed(1) : '—'}</td>
                                  </>
                                ) : (
                                  <td className={`${tdClass} text-center text-foreground border-r border-border/60`}></td>
                                )}
                                <td className={`${tdClass} text-center text-foreground ${sep}`}>{nozzle.nozzle}</td>
                                <td className={numCls}>{nf2.format(nozzle.endCounter)}</td>
                                <td className={`${numCls} ${sep}`}>{nf2.format(nozzle.startCounter)}</td>
                                <td className={`${numCls} font-medium`}>{nf2.format(nozzle.volume)}</td>
                                <td className={`${numCls} ${sep}`}>{nf2.format(nozzle.amount)}</td>
                                <td className={`${numCls} font-medium ${sep}`}>{nf2.format(nozzle.price)}</td>
                                <td className={`${numCls} font-medium ${sep}`}>{formatCurrency(nozzle.cost)}</td>
                                {/* Погрешности в API нет — прочерк, а не выдуманный ноль:
                                    «0.00» читается как измеренная погрешность. */}
                                <td className={`${tdClass} text-right text-muted-foreground/50`}>—</td>
                                <td className={`${tdClass} text-right text-muted-foreground/50`}>—</td>
                              </tr>
                            ))}
                            <tr className="border-b border-border bg-secondary/40">
                              <td className={`${tdClass} text-foreground font-bold`}>Всего:</td>
                              <td className={`${tdClass} ${sep}`}></td>
                              <td className={`${numCls} font-semibold`}>{nf2.format(totalEndCounter)}</td>
                              <td className={`${numCls} font-semibold ${sep}`}>{nf2.format(totalStartCounter)}</td>
                              <td className={`${numCls} font-semibold`}>{nf2.format(totalVolume)}</td>
                              <td className={`${numCls} font-semibold ${sep}`}>{nf2.format(totalAmount)}</td>
                              <td className={`${tdClass} ${sep}`}></td>
                              <td className={`${numCls} font-semibold ${sep}`}>{formatCurrency(totalCost)}</td>
                              <td className={`${tdClass} ${sep}`}></td>
                              <td className={tdClass}></td>
                            </tr>
                          </React.Fragment>
                        )
                      })}
                      <tr className="border-t border-border bg-secondary/70">
                        <td className={`${tdClass} text-foreground font-semibold`}>ИТОГО</td>
                        <td className={tdClass}></td>
                        <td className={`${tdClass} ${sep}`}></td>
                        <td className={`${tdClass} ${sep}`}></td>
                        <td className={`${numCls} font-semibold`}>{nf2.format(details.nozzleReadings.reduce((sum, n) => sum + n.endCounter, 0))}</td>
                        <td className={`${numCls} font-semibold ${sep}`}>{nf2.format(details.nozzleReadings.reduce((sum, n) => sum + n.startCounter, 0))}</td>
                        <td className={`${numCls} font-semibold`}>{nf2.format(details.nozzleReadings.reduce((sum, n) => sum + n.volume, 0))}</td>
                        <td className={`${numCls} font-semibold ${sep}`}>{nf2.format(details.nozzleReadings.reduce((sum, n) => sum + n.amount, 0))}</td>
                        <td className={`${tdClass} ${sep}`}></td>
                        <td className={`${numCls} font-semibold ${sep}`}>{formatCurrency(details.nozzleReadings.reduce((sum, n) => sum + n.cost, 0))}</td>
                        <td className={`${tdClass} ${sep}`}></td>
                        <td className={tdClass}></td>
                      </tr>
                    </tbody>
                  </table>
                </DualScrollX>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Погрешность ТРК не приходит в текущей версии API STS — колонки показаны
                  прочерком, а не нулём: ноль читался бы как измеренная погрешность.
                </p>
                <div className="mt-4 text-xs text-muted-foreground"><p>* Погрешность ТРК недоступна в текущей версии API</p></div>
              </TabsContent>

              {/* ── Расшифровка реализации ── */}
              <TabsContent value="sales" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Расшифровка реализации</h3></div>
                <DualScrollX>
                  <table className={`w-max min-w-full border-collapse leading-tight ${isMobile ? 'text-xs' : 'text-[13px]'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2} rowSpan={2}>Нефтепродукты, товары</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Прокачка<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>По картам</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Скидка<br/>руб.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>За наличные</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Безнал.<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Всего<br/>л.</th>
                        <th className={`${thClass} text-center text-foreground`} rowSpan={2}>Разница<br/>л.</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>руб.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>л.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>руб.</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Код</th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={`${thClass} border-r border-border/60`}></th>
                        <th className={thClass}></th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.salesBreakdown.map((item, idx) => (
                        <tr key={idx} className="border-b border-border">
                          <td className={`${tdClass} text-foreground font-medium border-r border-border/60`}>{item.fuelName}</td>
                          <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{item.fuelCode}</td>
                          <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{item.pumpVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{item.cardVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{formatCurrency(item.cardCost)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{item.discountCost.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{item.cashVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{formatCurrency(item.cashCost)}</td>
                          <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{item.nonCashVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground font-medium border-r border-border/60`}>{item.totalVolume.toFixed(2)}</td>
                          <td className={`${tdClass} text-center text-foreground`}>{item.difference.toFixed(2)}</td>
                        </tr>
                      ))}
                      <tr className="border-t border-border bg-secondary/50">
                        <td className={`${tdClass} text-foreground font-bold`} colSpan={2}>Всего:</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.pumpVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.cardVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r border-border/60`}>{formatCurrency(details.salesBreakdown.reduce((s, i) => s + i.cardCost, 0))}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.discountCost, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.cashVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-right text-foreground font-bold border-r border-border/60`}>{formatCurrency(details.salesBreakdown.reduce((s, i) => s + i.cashCost, 0))}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.nonCashVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{details.salesBreakdown.reduce((s, i) => s + i.totalVolume, 0).toFixed(2)}</td>
                        <td className={`${tdClass} text-center text-foreground font-bold`}>{details.salesBreakdown.reduce((s, i) => s + i.difference, 0).toFixed(2)}</td>
                      </tr>
                    </tbody>
                  </table>
                </DualScrollX>

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
                            <tr className="border-b border-border">
                              <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Наименование</th>
                              <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Код</th>
                              {paymentTypes.map(([key, name]) => (
                                <th key={key} className={`${thClass} text-center text-foreground border-r border-border/60`}>{name}<br/>л.</th>
                              ))}
                              <th className={`${thClass} text-center text-foreground`}>ИТОГО б/н<br/>л.</th>
                            </tr>
                          </thead>
                          <tbody className="bg-card">
                            {rows.map((row, idx) => {
                              const rowTotal = paymentTypes.reduce((s, [key]) => s + (row.byPayType[key] || 0), 0)
                              return (
                                <tr key={idx} className="border-b border-border">
                                  <td className={`${tdClass} text-foreground font-medium border-r border-border/60`}>{row.fuelName}</td>
                                  <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{row.fuelCode}</td>
                                  {paymentTypes.map(([key]) => (
                                    <td key={key} className={`${tdClass} text-center text-foreground border-r border-border/60`}>{(row.byPayType[key] || 0).toFixed(2)}</td>
                                  ))}
                                  <td className={`${tdClass} text-center text-foreground font-medium`}>{rowTotal.toFixed(2)}</td>
                                </tr>
                              )
                            })}
                            <tr className="border-t border-border bg-secondary/50">
                              <td className={`${tdClass} text-foreground font-bold text-right`} colSpan={2}>Всего:</td>
                              {paymentTypes.map(([key]) => (
                                <td key={key} className={`${tdClass} text-center text-foreground font-bold border-r border-border/60`}>{totals[key].toFixed(2)}</td>
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
                <DualScrollX>
                  <table className={`w-max min-w-full border-collapse leading-tight ${isMobile ? 'text-xs' : 'text-[13px]'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-left text-foreground border-r border-border/60`} rowSpan={3}>Наименование<br/>нефте-<br/>продуктов</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>N<br/>Резер-<br/>вуара</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={3}>Плотн.<br/>на<br/>начало<br/>смены<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Книжный остаток<br/>на<br/>начало смены</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Поступление<br/>в т.ч. прокачка</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Расход</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={10}>Остаток на конец смены</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Плотн.<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>Темп<br/>C</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>общий<br/>уров.<br/>см</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>общий<br/>объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>уров.<br/>воды<br/>см</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>объем<br/>воды<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Факт.остаток н/п.</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={2}>расчетн.кн.ост.</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>литры</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>литры</th>
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
                            <td className={`${tdClass} text-foreground font-medium border-r border-border/60`}>{tank.fuelName}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.tankNumber}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.density ? tank.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r border-border/60`}>{tank.volumeBegin.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{(tank.volumeBegin * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r border-border/60`}>{tank.volumeReceived.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{(tank.volumeReceived * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r border-border/60`}>{tank.volumeDispensed.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{(tank.volumeDispensed * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.density ? tank.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.temperature?.toFixed(1) || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.level?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r border-border/60`}>{tank.volumeEnd.toFixed(2)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.waterLevel?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{tank.waterVolume?.toFixed(2) || '—'}</td>
                            <td className={`${tdClass} text-right text-foreground font-medium border-r border-border/60`}>{tank.volumeEnd.toFixed(2)}</td>
                            <td className={`${tdClass} text-right text-foreground border-r border-border/60`}>{(tank.volumeEnd * (tank.density || 1)).toFixed(2)}</td>
                            <td className={`${tdClass} text-right font-medium border-r border-border/60 ${tank.hasExcessError ? 'text-destructive' : 'text-foreground'}`}>
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
                </DualScrollX>
              </TabsContent>

              {/* ── Поступления ── */}
              <TabsContent value="receipts" className={isMobile ? 'mt-2' : 'mt-4'}>
                <div className="mb-4"><h3 className="text-lg font-semibold text-foreground text-center">Расшифровка поступлений</h3></div>
                <DualScrollX>
                  <table className={`w-max min-w-full border-collapse leading-tight ${isMobile ? 'text-xs' : 'text-[13px]'}`}>
                    <thead className="bg-secondary/80">
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Нефтепродукты</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={2}>Поставщик</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>№<br/>Докум.</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} rowSpan={2}>№<br/>рез</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`} colSpan={4}>По документу</th>
                        <th className={`${thClass} text-center text-foreground`} colSpan={4}>Фактически</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Код</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Наименование</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Код</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Плотн<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Масса<br/>кг</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Темп.<br/>°C</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Объем<br/>л</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Плотн<br/>г/см3</th>
                        <th className={`${thClass} text-center text-foreground border-r border-border/60`}>Масса<br/>кг</th>
                        <th className={`${thClass} text-center text-foreground`}>Темп.<br/>°C</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {details.receipts.length === 0 ? (
                        <tr><td colSpan={14} className="px-4 py-8 text-center text-muted-foreground">Нет поступлений за период смены</td></tr>
                      ) : (
                        details.receipts.map((receipt, idx) => (
                          <tr key={idx} className="border-b border-border">
                            <td className={`${tdClass} text-foreground border-r border-border/60`}>{receipt.fuelName}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.fuelCode}</td>
                            <td className={`${tdClass} text-foreground border-r border-border/60`}>{receipt.supplier || 'Нефтебаза'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>1</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.documentNumber || '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.tankNumber}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.volume.toFixed(0)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.density ? receipt.density.toFixed(4) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.amount ? receipt.amount.toFixed(0) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.temperature ? receipt.temperature.toFixed(1) : '—'}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.actualVolume ? receipt.actualVolume.toFixed(0) : receipt.volume.toFixed(0)}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.actualDensity ? receipt.actualDensity.toFixed(4) : (receipt.density ? receipt.density.toFixed(4) : '—')}</td>
                            <td className={`${tdClass} text-center text-foreground border-r border-border/60`}>{receipt.actualAmount ? receipt.actualAmount.toFixed(0) : (receipt.amount ? receipt.amount.toFixed(0) : '—')}</td>
                            <td className={`${tdClass} text-center text-foreground`}>{receipt.actualTemperature ? receipt.actualTemperature.toFixed(1) : (receipt.temperature ? receipt.temperature.toFixed(1) : '—')}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </DualScrollX>
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

              {/* ── Корректировка значений реализации для 1С (слой L2 CLEAN) ── */}
              <TabsContent value="edit" className={isMobile ? 'mt-2' : 'mt-4'}>
                {data && shiftId ? (
                  <SalesEditor
                    key={shiftId}
                    shiftId={shiftId}
                    sales={data.sales}
                    fuelName={fuelName}
                    isMobile={isMobile}
                    thClass={thClass}
                    tdClass={tdClass}
                    note={data.correction_note ?? ''}
                    noteAuthor={data.correction_note_author ?? null}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">Нет данных для корректировки.</p>
                )}
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

// Читаемые подписи каналов оплаты (коды PaymentChannel).
const CHANNEL_LABELS: Record<string, string> = {
  retail_cash: 'Розница (наличные)',
  retail_card: 'Розница (карта)',
  cards: 'Топливные карты',
  online: 'Онлайн-заказы',
  voucher: 'Талоны / ведомость',
  ledger: 'Ведомость',
  writeoff_fuel: 'Списание',
}

/**
 * Редактор значений реализации смены (слой L2 CLEAN). Правит строки FuelShiftSale
 * (канал оплаты × топливо) → PATCH override, переживающий reingest. Значения
 * попадают в документы 1С при пересборке пакетов выгрузки.
 */
function SalesEditor({ shiftId, sales, fuelName, isMobile, thClass, tdClass, note, noteAuthor }: {
  shiftId: string
  sales: ShiftSale[]
  fuelName: (code?: number | null, fallback?: string | null) => string
  isMobile: boolean
  thClass: string
  tdClass: string
  note: string
  noteAuthor: string | null
}) {
  const qc = useQueryClient()
  const [saving, setSaving] = useState(false)
  const keyOf = (s: ShiftSale) => `${s.payment_channel}|${s.fuel_code}`
  const [edits, setEdits] = useState<Record<string, { liters: string; amount: string; discount: string }>>({})
  const [noteText, setNoteText] = useState(note)

  // Инициализация/переинициализация полей из текущих (уже с наложенным override) значений.
  useEffect(() => {
    setEdits(Object.fromEntries(sales.map((s) => [keyOf(s), {
      liters: String(s.liters ?? 0), amount: String(s.amount ?? 0), discount: String(s.discount ?? 0),
    }])))
  }, [sales])

  const anyManual = sales.some((s) => s.is_manual)
  const setField = (key: string, field: 'liters' | 'amount' | 'discount', val: string) =>
    setEdits((prev) => ({ ...prev, [key]: { ...prev[key], [field]: val } }))
  const num = (v: string): number | null => (v.trim() === '' ? null : Number(v))

  const save = async () => {
    setSaving(true)
    try {
      const payload: ShiftSaleEdit[] = sales.map((s) => {
        const e = edits[keyOf(s)] ?? { liters: '', amount: '', discount: '' }
        return {
          payment_channel: s.payment_channel, fuel_code: s.fuel_code,
          liters: num(e.liters), amount: num(e.amount), discount: num(e.discount),
        }
      })
      await patchShiftSales(shiftId, payload)
      if (noteText.trim() !== (note ?? '').trim()) await setShiftCorrectionNote(shiftId, noteText.trim())
      await qc.invalidateQueries({ queryKey: ['shift-detail', shiftId] })
      toast.success('Корректировки сохранены (L2)', {
        description: 'Пересоберите пакеты выгрузки, чтобы обновить документы 1С.',
      })
    } catch {
      toast.error('Не удалось сохранить корректировки', {
        description: 'Смена может быть в закрытом периоде.',
      })
    } finally { setSaving(false) }
  }

  const reset = async () => {
    setSaving(true)
    try {
      await resetShiftSaleOverrides(shiftId)
      setNoteText('')
      await qc.invalidateQueries({ queryKey: ['shift-detail', shiftId] })
      toast.success('Корректировки сброшены к данным STS')
    } catch {
      toast.error('Не удалось сбросить корректировки')
    } finally { setSaving(false) }
  }

  if (sales.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">У смены нет разбивки продаж по каналам оплаты.</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-lg border border-sky-400/30 bg-sky-400/5 px-3 py-2 text-xs text-sky-200/90">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <span>Правьте значения продаж по каналу оплаты × топливо. Корректировки сохраняются в слое L2
          (переживают повторную загрузку из STS) и попадают в документы 1С при пересборке пакетов выгрузки.</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className={`w-max min-w-full border-collapse leading-tight ${isMobile ? 'text-xs' : 'text-[13px]'}`}>
          <thead className="bg-secondary/80">
            <tr className="border-b border-border">
              <th className={`${thClass} text-left text-foreground border-r border-border`}>Канал оплаты</th>
              <th className={`${thClass} text-left text-foreground border-r border-border`}>Топливо</th>
              <th className={`${thClass} text-center text-foreground border-r border-border`}>Литры</th>
              <th className={`${thClass} text-center text-foreground border-r border-border`}>Сумма, ₽</th>
              <th className={`${thClass} text-center text-foreground`}>Скидка, ₽</th>
            </tr>
          </thead>
          <tbody className="bg-card">
            {sales.map((s) => {
              const k = keyOf(s)
              const e = edits[k] ?? { liters: '', amount: '', discount: '' }
              // Правка на уровне поля — только при реальном отличии от STS (устойчиво к ложным override).
              const litChanged = s.src_liters != null && Math.abs(s.src_liters - s.liters) > 0.005
              const amtChanged = s.src_amount != null && Math.abs(s.src_amount - s.amount) > 0.005
              const disChanged = s.src_discount != null && Math.abs(s.src_discount - s.discount) > 0.005
              const rowChanged = litChanged || amtChanged || disChanged
              const inp = (changed: boolean) =>
                `h-7 text-right text-xs ${changed ? 'border-amber-400 ring-1 ring-amber-400/40 bg-amber-50 font-semibold text-amber-700 dark:bg-amber-400/10 dark:text-amber-200' : ''}`
              const was = (v: number) =>
                <div className="mt-0.5 text-right text-[10px] font-medium text-amber-600 dark:text-amber-400">было: {v}</div>
              return (
                <tr key={k} className={`border-b border-border ${rowChanged ? 'bg-amber-50/60 dark:bg-amber-400/[0.06]' : ''}`}>
                  <td className={`${tdClass} text-foreground border-r border-border ${rowChanged ? 'border-l-2 border-l-amber-400' : ''}`}>
                    {CHANNEL_LABELS[s.payment_channel] ?? s.payment_channel}
                    {rowChanged && (
                      <Badge className="ml-1.5 gap-0.5 border-transparent bg-amber-100 text-[10px] font-medium text-amber-700 hover:bg-amber-100 dark:bg-amber-400/15 dark:text-amber-300">
                        <Pencil className="h-2.5 w-2.5" />правка
                      </Badge>
                    )}
                  </td>
                  <td className={`${tdClass} text-foreground border-r border-border`}>{fuelName(s.fuel_code, `код ${s.fuel_code}`)}</td>
                  <td className={`${tdClass} border-r border-border`}>
                    <Input className={inp(litChanged)} inputMode="decimal" value={e.liters}
                      onChange={(ev) => setField(k, 'liters', ev.target.value)} />
                    {litChanged && was(s.src_liters!)}
                  </td>
                  <td className={`${tdClass} border-r border-border`}>
                    <Input className={inp(amtChanged)} inputMode="decimal" value={e.amount}
                      onChange={(ev) => setField(k, 'amount', ev.target.value)} />
                    {amtChanged && was(s.src_amount!)}
                  </td>
                  <td className={tdClass}>
                    <Input className={inp(disChanged)} inputMode="decimal" value={e.discount}
                      onChange={(ev) => setField(k, 'discount', ev.target.value)} />
                    {disChanged && was(s.src_discount!)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {/* Комментарий менеджера — в целом по документу (смене) */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Pencil className="h-3 w-3 text-amber-500" /> Комментарий менеджера по корректировке
          </label>
          {noteAuthor && note.trim() && <span className="text-[10px] text-muted-foreground">· {noteAuthor}</span>}
        </div>
        <textarea
          value={noteText}
          onChange={(ev) => setNoteText(ev.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Причина и суть правок в целом по смене (сохраняется в L2 вместе с корректировками)…"
          className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={save} disabled={saving} className="gap-1">
          <Save className="h-3.5 w-3.5" /> Сохранить корректировки
        </Button>
        <Button size="sm" variant="outline" onClick={reset} disabled={saving || (!anyManual && !noteText.trim())} className="gap-1">
          <RotateCcw className="h-3.5 w-3.5" /> Сбросить к STS
        </Button>
      </div>
    </div>
  )
}
