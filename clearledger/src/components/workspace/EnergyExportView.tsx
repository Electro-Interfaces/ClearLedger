/**
 * Энерго-вариант режима «Выгрузка» (раздел рабочего стола, профиль energy / РусГидро).
 * Демо на данных сети DEMO_EZS. Два слоя:
 *   • Документы (L3) — подготовленные к выгрузке закрывающие документы зарядных сессий
 *     (Акт об оказании услуг зарядки, Счёт ЮЛ, Реестр зарядных сессий, Счёт-фактура)
 *     со статусом готов / выгружен.
 *   • Данные — проводки/реестр к выгрузке + выгрузка в учётную систему компании.
 * ЦЕЛЬ выгрузки = «учётная система компании» клиента (НЕ 1С БП ГИГ, НЕ топливные счета).
 * Заменяется реальным экспортом L3 → коннектор учётной системы. Суммы — заглушки до интеграции.
 */
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DEMO_EZS, sumRelease, sumBuy, tariffCheck, fmtN } from '../balance/balanceCalc'

const all = DEMO_EZS

function Head({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{title}</h1>
        <Badge variant="secondary" className="text-[10px]">демо-данные</Badge>
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
    </div>
  )
}
function Kpi({ label, value, accent }: { label: string; value: string; accent?: 'warn' | 'danger' | 'ok' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400'
    : accent === 'warn' ? 'text-amber-600 dark:text-amber-400'
      : accent === 'ok' ? 'text-emerald-600 dark:text-emerald-400'
        : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </CardContent></Card>
  )
}

type DocStatus = 'ready' | 'exported'
const DOC_STATUS_META: Record<DocStatus, { label: string; cls: string }> = {
  ready: { label: 'Готов', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  exported: { label: 'Выгружен', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
}

interface DocRow {
  kind: string          // вид документа
  number: string        // номер
  party: string         // получатель / контрагент
  period: string        // период
  amountRub: number     // сумма с НДС
  status: DocStatus
}

// ─── L3: подготовленные закрывающие документы зарядных сессий ─────────────────
function buildDocs(): DocRow[] {
  const period = 'Май 2026'
  // ЮЛ-выручка и ЮЛ-объём по сети — основа Актов/Счетов/Счетов-фактур корпоративным клиентам.
  const ulRub = all.reduce((a, s) => a + (s.release.ul?.rub ?? 0), 0)
  const flRub = all.reduce((a, s) => a + (s.release.fl?.rub ?? 0), 0)
  const totalRub = ulRub + flRub
  const sessions = all.reduce((a, s) => a + tariffCheck(s).sessions, 0)
  // Несколько корпоративных контрагентов делят ЮЛ-объём (демо-распределение).
  const corp = [
    { name: 'ООО «Логистик-Транс»', share: 0.42 },
    { name: 'ООО «ГринФлит»', share: 0.31 },
    { name: 'АО «Городские перевозки»', share: 0.27 },
  ]
  const docs: DocRow[] = []
  corp.forEach((c, i) => {
    const sum = Math.round(ulRub * c.share)
    docs.push({ kind: 'Акт об оказании услуг зарядки', number: `АКТ-2026-${String(140 + i).padStart(4, '0')}`, party: c.name, period, amountRub: sum, status: i === 0 ? 'exported' : 'ready' })
    docs.push({ kind: 'Счёт ЮЛ', number: `СЧ-2026-${String(312 + i).padStart(4, '0')}`, party: c.name, period, amountRub: sum, status: 'ready' })
    docs.push({ kind: 'Счёт-фактура', number: `СФ-2026-${String(208 + i).padStart(4, '0')}`, party: c.name, period, amountRub: sum, status: i === 0 ? 'exported' : 'ready' })
  })
  // Реестр зарядных сессий — единый сводный документ на весь период (ЮЛ + ФЛ).
  docs.push({ kind: 'Реестр зарядных сессий', number: `РЗС-2026-05`, party: `Сводный · ${fmtN(sessions)} сессий`, period, amountRub: totalRub, status: 'ready' })
  return docs
}

// ─── Данные: строки реестра к выгрузке (проводки учётной системы компании) ────
interface LedgerRow {
  account: string       // счёт учётной системы КОМПАНИИ (не план счетов БП)
  name: string          // наименование операции
  kwh: number           // объём, кВт·ч
  amountRub: number     // сумма с НДС
  vatRub: number        // в т.ч. НДС 22%
}
function buildLedger(): LedgerRow[] {
  const relRub = all.reduce((a, s) => a + sumRelease(s).rub, 0)
  const relKwh = all.reduce((a, s) => a + sumRelease(s).kwh, 0)
  const buyRub = all.reduce((a, s) => a + sumBuy(s).rub, 0)
  const buyKwh = all.reduce((a, s) => a + sumBuy(s).kwh, 0)
  const ulRub = all.reduce((a, s) => a + (s.release.ul?.rub ?? 0), 0)
  const ulKwh = all.reduce((a, s) => a + (s.release.ul?.kwh ?? 0), 0)
  const flRub = all.reduce((a, s) => a + (s.release.fl?.rub ?? 0), 0)
  const flKwh = all.reduce((a, s) => a + (s.release.fl?.kwh ?? 0), 0)
  const vat = (rub: number) => Math.round(rub - rub / 1.22) // НДС 22% (2026), выделенный из суммы с НДС
  return [
    { account: 'REV-EV-UL', name: 'Выручка от зарядки · ЮЛ (корп. клиенты)', kwh: ulKwh, amountRub: ulRub, vatRub: vat(ulRub) },
    { account: 'REV-EV-FL', name: 'Выручка от зарядки · ФЛ (частные)', kwh: flKwh, amountRub: flRub, vatRub: vat(flRub) },
    { account: 'COGS-ENERGY', name: 'Закупка электроэнергии у поставщиков', kwh: buyKwh, amountRub: buyRub, vatRub: vat(buyRub) },
    { account: 'NET-RESULT', name: 'Валовый результат (выручка − закупка)', kwh: relKwh - buyKwh, amountRub: relRub - buyRub, vatRub: 0 },
  ]
}

type Layer = 'docs' | 'data'

export function EnergyExportView() {
  const [layer, setLayer] = useState<Layer>('docs')
  const docs = useMemo(buildDocs, [])
  const ledger = useMemo(buildLedger, [])

  const docsReady = docs.filter((d) => d.status === 'ready').length
  const docsExported = docs.filter((d) => d.status === 'exported').length
  const ledgerRub = ledger.find((r) => r.account === 'REV-EV-UL')!.amountRub
    + ledger.find((r) => r.account === 'REV-EV-FL')!.amountRub
  const ledgerVat = ledger.reduce((a, r) => a + r.vatRub, 0)

  const onExport = () => {
    toast.success('Передано в учётную систему компании', {
      description: `${docsReady} документ(ов) и реестр на ${fmtN(ledgerRub)} ₽ поставлены в очередь выгрузки (демо-режим).`,
    })
  }

  return (
    <div className="space-y-5 px-6 py-6">
      <Head
        title="Выгрузка в учётную систему"
        subtitle="Слой L3: закрывающие документы зарядных сессий и реестр проводок → выгрузка в учётную систему компании-оператора сети ЭЗС."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Документов готово" value={String(docsReady)} accent={docsReady ? 'warn' : 'ok'} />
        <Kpi label="Документов выгружено" value={String(docsExported)} accent="ok" />
        <Kpi label="К выгрузке (выручка), ₽" value={fmtN(ledgerRub)} />
        <Kpi label="в т.ч. НДС 22%, ₽" value={fmtN(ledgerVat)} />
      </div>

      {/* Переключатель слоёв */}
      <div className="inline-flex rounded-lg border bg-muted/40 p-1 text-sm">
        <button
          type="button"
          onClick={() => setLayer('docs')}
          className={`rounded-md px-4 py-1.5 font-medium transition-colors ${layer === 'docs' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          Документы (L3)
        </button>
        <button
          type="button"
          onClick={() => setLayer('data')}
          className={`rounded-md px-4 py-1.5 font-medium transition-colors ${layer === 'data' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
        >
          Данные (реестр проводок)
        </button>
      </div>

      {layer === 'docs' ? (
        <Card><CardContent className="overflow-x-auto pt-5">
          <div className="mb-3 text-sm font-medium">Подготовленные документы</div>
          <Table><TableHeader><TableRow>
            <TableHead>Вид документа</TableHead>
            <TableHead>Номер</TableHead>
            <TableHead>Получатель</TableHead>
            <TableHead>Период</TableHead>
            <TableHead className="text-right">Сумма с НДС, ₽</TableHead>
            <TableHead className="text-center">Статус</TableHead>
          </TableRow></TableHeader><TableBody>
            {docs.map((d) => (
              <TableRow key={`${d.kind}-${d.number}`}>
                <TableCell className="font-medium">{d.kind}</TableCell>
                <TableCell className="tabular-nums text-muted-foreground">{d.number}</TableCell>
                <TableCell>{d.party}</TableCell>
                <TableCell className="text-muted-foreground">{d.period}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(d.amountRub)}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${DOC_STATUS_META[d.status].cls}`}>{DOC_STATUS_META[d.status].label}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
          <p className="mt-3 text-xs text-muted-foreground/70">
            Документы формируются по данным зарядных сессий (ПК) и сверенной выручке. Выгрузка — на вкладке «Данные».
          </p>
        </CardContent></Card>
      ) : (
        <Card><CardContent className="overflow-x-auto pt-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-medium">Реестр проводок к выгрузке</div>
            <Button size="sm" onClick={onExport}>Выгрузить в учётную систему компании</Button>
          </div>
          <Table><TableHeader><TableRow>
            <TableHead>Счёт</TableHead>
            <TableHead>Операция</TableHead>
            <TableHead className="text-right">кВт·ч</TableHead>
            <TableHead className="text-right">Сумма с НДС, ₽</TableHead>
            <TableHead className="text-right">в т.ч. НДС 22%, ₽</TableHead>
          </TableRow></TableHeader><TableBody>
            {ledger.map((r) => (
              <TableRow key={r.account}>
                <TableCell className="font-medium tabular-nums">{r.account}</TableCell>
                <TableCell>{r.name}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(r.kwh)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(r.amountRub)}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{r.vatRub ? fmtN(r.vatRub) : '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
          <p className="mt-3 text-xs text-muted-foreground/70">
            Цель выгрузки — учётная система компании-оператора сети (ERP/бухгалтерия клиента), не сторонняя 1С.
            Счета условные (REV/COGS), маппинг на план счетов компании — при подключении коннектора.
          </p>
        </CardContent></Card>
      )}
    </div>
  )
}
