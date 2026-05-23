/**
 * Модальное окно деталей сменного отчёта.
 * 5 вкладок: Состав смены, Резервуары, Поступления, Реализация, Движение наличных.
 * Адаптировано из TradeFrame/ShiftDetailsModal.tsx под данные GIG Fuel Ledger.
 */

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CheckCircle, Clock } from 'lucide-react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import type { ShiftRecord } from '@/services/fuel/types'

interface Props {
  shift: ShiftRecord | null
  onClose: () => void
}

const thClass = 'px-2 py-2 text-xs'
const tdClass = 'px-3 py-2 text-sm'

function fmtDT(d: string) { return format(new Date(d), 'dd.MM.yyyy HH:mm', { locale: ru }) }
function fmtNum(v: number, digits = 2) { return v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }) }
function fmtRub(v: number) { return fmtNum(v) + ' ₽' }

export function ShiftDetailModal({ shift, onClose }: Props) {
  if (!shift) return null
  const raw = shift.raw
  if (!raw) return null

  const statusBadge = shift.status === 'open'
    ? <Badge className="bg-emerald-500/10 text-green-600 border-green-500 flex items-center gap-1"><Clock className="w-3 h-3" />Открыта</Badge>
    : <Badge className="bg-blue-500/10 text-blue-600 border-blue-500 flex items-center gap-1"><CheckCircle className="w-3 h-3" />Закрыта</Badge>

  return (
    <Dialog open={!!shift} onOpenChange={onClose}>
      <DialogContent className="!max-w-none !w-[100vw] !h-[100vh] !rounded-none !border-none !p-4 flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-3">
            Детали смены #{shift.shiftNumber}
            {statusBadge}
          </DialogTitle>
          <p className="text-sm text-muted-foreground">{shift.stationName}</p>
        </DialogHeader>

        <div className="space-y-4 flex-1 overflow-y-auto">
          {/* Основная информация */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-secondary/50 rounded-lg p-2.5">
              <div className="text-xs text-muted-foreground mb-0.5">Статус</div>
              <div className="mt-1">{statusBadge}</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-2.5">
              <div className="text-xs text-muted-foreground mb-0.5">Открыта</div>
              <div className="text-sm font-semibold">{fmtDT(shift.openedAt)}</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-2.5">
              <div className="text-xs text-muted-foreground mb-0.5">Закрыта</div>
              <div className="text-sm font-semibold">{shift.closedAt ? fmtDT(shift.closedAt) : '—'}</div>
            </div>
            <div className="bg-secondary/50 rounded-lg p-2.5">
              <div className="text-xs text-muted-foreground mb-0.5">Итого</div>
              <div className="text-sm font-semibold">{fmtNum(shift.totalVolumeLiters, 0)} л / {fmtRub(shift.totalAmount)}</div>
            </div>
          </div>

          {/* Вкладки */}
          <Tabs defaultValue="composition" className="w-full">
            <TabsList className="bg-secondary w-full justify-start overflow-x-auto">
              <TabsTrigger value="composition" className="px-4 py-2">Состав смены</TabsTrigger>
              <TabsTrigger value="tanks" className="px-4 py-2">Резервуары</TabsTrigger>
              <TabsTrigger value="receipts" className="px-4 py-2">Поступления</TabsTrigger>
              <TabsTrigger value="sales" className="px-4 py-2">Реализация</TabsTrigger>
              <TabsTrigger value="cash" className="px-4 py-2">Движение наличных</TabsTrigger>
            </TabsList>

            {/* ─── Состав смены (ТРК) ──────────────────── */}
            <TabsContent value="composition" className="mt-4">
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full border-collapse text-sm">
                  <thead className="bg-secondary/80">
                    <tr className="border-b-2 border-border">
                      <th className={`${thClass} text-left border-r border-border`}>Топливо</th>
                      <th className={`${thClass} text-center border-r border-border`}>Рез.</th>
                      <th className={`${thClass} text-center border-r border-border`}>Плотн.</th>
                      <th className={`${thClass} text-center border-r border-border`}>№ ТРК</th>
                      <th className={`${thClass} text-center border-r border-border`}>Начало</th>
                      <th className={`${thClass} text-center border-r border-border`}>Конец</th>
                      <th className={`${thClass} text-center border-r border-border`}>Объём, л</th>
                      <th className={`${thClass} text-center border-r border-border`}>Масса, кг</th>
                      <th className={`${thClass} text-center border-r border-border`}>Цена</th>
                      <th className={`${thClass} text-right`}>Сумма, ₽</th>
                    </tr>
                  </thead>
                  <tbody className="bg-card">
                    {(raw.psm?.data ?? []).map((d, i) => (
                      <tr key={i} className="border-b border-border">
                        <td className={`${tdClass} font-medium border-r border-border`}>{d.service.service_name}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{d.tank}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{d.density.toFixed(1)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{d.nozzle}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(d.psm_beg)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(d.psm_end)}</td>
                        <td className={`${tdClass} text-center font-medium border-r border-border`}>{fmtNum(parseFloat(d.release.volume))}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(d.release.amount))}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(d.price)}</td>
                        <td className={`${tdClass} text-right font-medium`}>{fmtRub(parseFloat(d.release.cost))}</td>
                      </tr>
                    ))}
                    {/* Итоги по видам топлива */}
                    {(raw.psm?.total ?? []).map((t, i) => (
                      <tr key={`total-${i}`} className="border-b border-border bg-secondary/50 font-bold">
                        <td className={`${tdClass} border-r border-border`}>{t.service.service_name} — итого</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{t.tank}</td>
                        <td className={`${tdClass} border-r border-border`}></td>
                        <td className={`${tdClass} border-r border-border`}></td>
                        <td className={`${tdClass} border-r border-border`}></td>
                        <td className={`${tdClass} border-r border-border`}></td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(t.release.quantity)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(t.release.cost)}</td>
                        <td className={`${tdClass} border-r border-border`}></td>
                        <td className={`${tdClass} text-right`}>{fmtRub(t.release.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TabsContent>

            {/* ─── Резервуары ───────────────────────────── */}
            <TabsContent value="tanks" className="mt-4">
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full border-collapse text-sm">
                  <thead className="bg-secondary/80">
                    <tr className="border-b-2 border-border">
                      <th className={`${thClass} text-left border-r border-border`}>Топливо</th>
                      <th className={`${thClass} text-center border-r border-border`}>Рез.</th>
                      <th className={`${thClass} text-center border-r border-border`}>Плотн. нач.</th>
                      <th className={`${thClass} text-center border-r border-border`}>Плотн. кон.</th>
                      <th className={`${thClass} text-center border-r border-border`}>Остаток нач., л</th>
                      <th className={`${thClass} text-center border-r border-border`}>Поступление, л</th>
                      <th className={`${thClass} text-center border-r border-border`}>Расход, л</th>
                      <th className={`${thClass} text-center border-r border-border`}>Остаток кон., л</th>
                      <th className={`${thClass} text-center border-r border-border`}>Уровень, см</th>
                      <th className={`${thClass} text-center`}>Вода, л</th>
                    </tr>
                  </thead>
                  <tbody className="bg-card">
                    {(raw.release ?? []).map((r, i) => (
                      <tr key={i} className="border-b border-border">
                        <td className={`${tdClass} font-medium border-r border-border`}>{r.service.service_name}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{r.tank}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{r.density_beg.toFixed(4)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{r.density_end.toFixed(4)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.doc_beg.volume))}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.receipt.volume))}</td>
                        <td className={`${tdClass} text-center font-medium border-r border-border`}>{fmtNum(parseFloat(r.release.volume))}</td>
                        <td className={`${tdClass} text-center font-medium border-r border-border`}>{fmtNum(r.volume_end)}</td>
                        <td className={`${tdClass} text-center border-r border-border`}>{r.level_end}</td>
                        <td className={`${tdClass} text-center`}>{r.water.volume}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TabsContent>

            {/* ─── Поступления (ТТН) ───────────────────── */}
            <TabsContent value="receipts" className="mt-4">
              {(raw.receipt ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">Нет поступлений в этой смене</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full border-collapse text-sm">
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-left border-r border-border`}>ТТН</th>
                        <th className={`${thClass} text-left border-r border-border`}>Топливо</th>
                        <th className={`${thClass} text-center border-r border-border`}>Рез.</th>
                        <th className={`${thClass} text-left border-r border-border`}>Поставщик</th>
                        <th className={`${thClass} text-center border-r border-border`}>Док. объём, л</th>
                        <th className={`${thClass} text-center border-r border-border`}>Док. масса, кг</th>
                        <th className={`${thClass} text-center border-r border-border`}>Факт. объём, л</th>
                        <th className={`${thClass} text-center border-r border-border`}>Факт. масса, кг</th>
                        <th className={`${thClass} text-center border-r border-border`}>Плотн. док.</th>
                        <th className={`${thClass} text-center`}>Дата</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {(raw.receipt ?? []).map((r, i) => (
                        <tr key={i} className="border-b border-border">
                          <td className={`${tdClass} font-semibold border-r border-border`}>{r.ttn}</td>
                          <td className={`${tdClass} border-r border-border`}>{r.service.service_name}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{r.tank}</td>
                          <td className={`${tdClass} border-r border-border`}>{r.base.name}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.doc.volume))}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.doc.amount))}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.fact.volume))}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(r.fact.amount))}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{r.doc.density.toFixed(3)}</td>
                          <td className={`${tdClass} text-center`}>{fmtDT(r.dt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsContent>

            {/* ─── Расшифровка реализации ──────────────── */}
            <TabsContent value="sales" className="mt-4">
              <h3 className="text-base font-semibold text-center mb-3">Расшифровка реализации</h3>
              {(raw.sales ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">Нет данных о реализации</p>
              ) : (
                <div className="space-y-4">
                  {(raw.sales ?? []).map((channel, ci) => (
                    <div key={ci} className="rounded-lg border border-border overflow-hidden">
                      <div className="bg-secondary/80 px-3 py-2 font-medium text-sm">
                        {channel.pay_type.name}
                      </div>
                      <table className="w-full border-collapse text-sm">
                        <thead>
                          <tr className="border-b border-border bg-secondary/30">
                            <th className={`${thClass} text-left border-r border-border`}>Топливо</th>
                            <th className={`${thClass} text-center border-r border-border`}>Объём, л</th>
                            <th className={`${thClass} text-right border-r border-border`}>Сумма, ₽</th>
                            <th className={`${thClass} text-right`}>Скидка, ₽</th>
                          </tr>
                        </thead>
                        <tbody className="bg-card">
                          {(channel.fuel ?? []).map((f, fi) => (
                            <tr key={fi} className="border-b border-border">
                              <td className={`${tdClass} font-medium border-r border-border`}>{f.service.service_name}</td>
                              <td className={`${tdClass} text-center border-r border-border`}>{fmtNum(parseFloat(f.release.volume))}</td>
                              <td className={`${tdClass} text-right border-r border-border`}>{fmtRub(parseFloat(f.release.cost))}</td>
                              <td className={`${tdClass} text-right`}>{fmtNum(f.release.discount)}</td>
                            </tr>
                          ))}
                          <tr className="bg-secondary/50 font-bold">
                            <td className={`${tdClass}`}>Итого</td>
                            <td className={`${tdClass} text-center border-r border-border`}>
                              {fmtNum(channel.fuel.reduce((s, f) => s + parseFloat(f.release.volume), 0))}
                            </td>
                            <td className={`${tdClass} text-right border-r border-border`}>
                              {fmtRub(channel.fuel.reduce((s, f) => s + parseFloat(f.release.cost), 0))}
                            </td>
                            <td className={`${tdClass} text-right`}>
                              {fmtNum(channel.fuel.reduce((s, f) => s + f.release.discount, 0))}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* ─── Движение наличных ───────────────────── */}
            <TabsContent value="cash" className="mt-4">
              <h3 className="text-base font-semibold text-center mb-3">Движение наличных</h3>
              {(raw.money ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">Нет данных о движении наличных</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full border-collapse text-sm">
                    <thead className="bg-secondary/80">
                      <tr className="border-b-2 border-border">
                        <th className={`${thClass} text-left border-r border-border`}>Операция</th>
                        <th className={`${thClass} text-center border-r border-border`}>Рабочее место</th>
                        <th className={`${thClass} text-right`}>Сумма, ₽</th>
                      </tr>
                    </thead>
                    <tbody className="bg-card">
                      {(raw.money ?? []).map((m, i) => (
                        <tr key={i} className="border-b border-border">
                          <td className={`${tdClass} font-medium border-r border-border`}>{m.operation.name}</td>
                          <td className={`${tdClass} text-center border-r border-border`}>{m.pos}</td>
                          <td className={`${tdClass} text-right font-medium`}>{fmtRub(m.volume)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  )
}
