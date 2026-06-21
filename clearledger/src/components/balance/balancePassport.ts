/**
 * Блок 4 ТЗ §5 — «цифровой балансовый паспорт» ЭЗС за период (экспорт .xlsx).
 * Структура Табл.2 (Поступление − Полезный отпуск = Потери) + декомпозиция потерь,
 * сверка ПУ↔ПУ и сведения о договоре. Демо-данные.
 */
import * as XLSX from 'xlsx'
import type { BalanceModuleDef } from '@/config/balanceModules'
import {
  sumBuy, sumRelease, lossKwh, lossRub, lossPct, techLossKwh, commLossKwh,
  meterCheck, supplierContract, PAYMENT_POLICY_LABEL, type StationBalance,
} from './balanceCalc'

function download(buf: ArrayBuffer, filename: string) {
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function exportStationPassport(s: StationBalance, mod: BalanceModuleDef, year: number, month: number) {
  const u = mod.unit
  const buy = sumBuy(s), rel = sumRelease(s)
  const periodLabel = new Date(year, month - 1, 1).toLocaleString('ru-RU', { month: 'long', year: 'numeric' })
  const rows: (string | number)[][] = []
  rows.push([`Балансовый паспорт — ${s.name}`])
  rows.push([`Период: ${periodLabel}`])
  rows.push([`Регион: ${s.region}`, `Тип: ${s.speed === 'fast' ? 'Быстрая (DC)' : 'Медленная (AC)'}`, `Мощность: ${s.power} кВт`])
  rows.push([])
  rows.push(['Показатель', u, 'руб'])
  rows.push(['Покупка итого', buy.kwh, buy.rub])
  s.purchase.forEach((p) => rows.push([`  ${p.supplier}`, p.kwh, p.rub]))
  rows.push(['Отпуск итого', rel.kwh, rel.rub])
  mod.categories.forEach((c) => {
    const r = s.release[c.id] ?? { kwh: 0, rub: 0 }
    rows.push([`  ${c.label}`, r.kwh, r.rub])
  })
  rows.push(['  в т.ч. неоплаченная (холд < факт)', s.unpaid.kwh, s.unpaid.rub])
  rows.push(['Потери итого', lossKwh(s), Math.round(lossRub(s))])
  rows.push(['  технологические (норматив)', Math.round(techLossKwh(s)), ''])
  rows.push(['  коммерческие (небаланс)', Math.round(commLossKwh(s)), ''])
  rows.push(['ПОЛЕЗНЫЙ ОТПУСК (Поступление − Потери)', buy.kwh - lossKwh(s), rel.rub])
  rows.push([])
  rows.push(['Потери, %', `${lossPct(s).toFixed(1)}%`, `норматив ${s.normPct}%`])
  const mc = meterCheck(s)
  rows.push(['Сверка ПУ ЭЗС ↔ ПУ поставщика', `${mc.diff > 0 ? '+' : ''}${mc.diff} ${u}`, `${mc.diffPct.toFixed(1)}%`])
  const c = supplierContract(s)
  rows.push(['Договор поставщика', c.number, `сальдо: долг ${c.debt} ₽`])
  rows.push(['Политика оплаты', PAYMENT_POLICY_LABEL[c.paymentPolicy], ''])
  rows.push([])
  rows.push(['Примечание: демонстрационные данные. Норматив потерь — расчётная модель (тип/мощность), требует калибровки по физике станции.'])

  const ws = XLSX.utils.aoa_to_sheet(rows)
  ws['!cols'] = [{ wch: 42 }, { wch: 16 }, { wch: 20 }]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Паспорт')
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as ArrayBuffer
  download(buf, `Балансовый_паспорт_ЭЗС_${s.id}_${year}-${String(month).padStart(2, '0')}.xlsx`)
}
