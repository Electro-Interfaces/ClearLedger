/**
 * «Выгрузка в БП» — Ledger как продюсер JSON-пакетов «смена→БП ГИГ» (замена
 * TL_ЭкспортБП). Смена → превью пакета (эмиттер /store/bp-package) → анализ
 * состава документов/НСИ + хеш → выгрузка (скачать JSON или в каталог сервера,
 * откуда приёмник TradeLedger.cfe / TL_СопуткаСервис.ОбработатьПакетИзСтроки грузит).
 * Приёмник НЕ меняется. Контракт: русские ключи, дискриминатор Тип, 8 типов
 * (recipe→purchase→retail→production→…→transfer), НСИ-инвариант, ХешПакета.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Download, FolderUp, FileJson, CheckCircle2, AlertTriangle } from 'lucide-react'
import {
  getStoreShifts, getBpPackage, emitBpPackage,
  type ShiftComposite, type BpPackage,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { Button } from '@/components/ui/button'
import { PolicyVatBadge } from '@/components/onec/PolicyVatBadge'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

// Типы документов пакета: подпись + соответствие в БП. Порядок = порядок контракта.
const DOC_TYPES: { key: string; label: string; bp: string }[] = [
  { key: 'recipe', label: 'ТТК (рецептуры)', bp: 'Справочник.СпецификацияНоменклатуры' },
  { key: 'purchase', label: 'Поступления', bp: 'ПоступлениеТоваровУслуг (ПТУ)' },
  { key: 'retail_sale_sidegoods', label: 'Розница', bp: 'ОтчётОРозничныхПродажах (ОРП)' },
  { key: 'production_release', label: 'Выпуск', bp: 'ОтчётПроизводства (модель B — пропуск)' },
  { key: 'inventory', label: 'Инвентаризация', bp: 'ИнвентаризацияТоваров' },
  { key: 'gain', label: 'Оприходование', bp: 'ОприходованиеТоваров' },
  { key: 'writeoff', label: 'Списание', bp: 'СписаниеТоваров' },
  { key: 'transfer', label: 'Перемещение', bp: 'ПеремещениеТоваров' },
  { key: 'return_purchase', label: 'Возврат поставщику', bp: 'КорректировкаПоступления' },
]
const NSI_TYPES = ['Организация', 'Склад', 'Контрагент', 'Договор', 'Номенклатура']

function downloadJson(pkg: BpPackage, sh: ShiftComposite) {
  const blob = new Blob([JSON.stringify(pkg, null, '\t')], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `АЗС${sh.station}_${sh.date}_${(pkg.ИдентификаторПакета || '').slice(0, 8)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

export function BpExportPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  const [key, setKey] = useState<string | null>(null)
  // GAP-2: companyId в ключах — иначе после переключения компании панель до 5 мин
  // показывает смены/пакет ПРЕЖНЕЙ компании из кеша React Query.
  const shiftsQ = useQuery({
    queryKey: ['store-shifts', companyId, dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })
  const pkgQ = useQuery({
    queryKey: ['bp-package', companyId, key],
    queryFn: () => getBpPackage(key!),
    enabled: !!key,
  })
  const emitMut = useMutation({ mutationFn: () => emitBpPackage(key!) })
  // Сбросить выбранную смену при смене компании (ключ смены чужой компании не валиден).
  useEffect(() => { setKey(null) }, [companyId])

  const shift = shiftsQ.data?.shifts.find((s) => s.shift_key === key) ?? null
  const pkg = pkgQ.data ?? null

  const analysis = useMemo(() => {
    if (!pkg) return null
    const docCount: Record<string, number> = {}
    const docSum: Record<string, number> = {}
    for (const d of pkg.Документы) {
      docCount[d.Тип] = (docCount[d.Тип] ?? 0) + 1
      docSum[d.Тип] = (docSum[d.Тип] ?? 0) + (Number(d.СуммаДокумента) || 0)
    }
    const nsiCount: Record<string, number> = {}
    for (const n of pkg.НСИ) nsiCount[n.Тип] = (nsiCount[n.Тип] ?? 0) + 1
    const total = Object.values(docSum).reduce((a, b) => a + b, 0)
    const ready = pkg.Документы.length > 0 && pkg.НСИ.length > 0 && !!pkg.ХешПакета
    return { docCount, docSum, nsiCount, total, ready }
  }, [pkg])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Выгрузка в БП ГИГ</h3>
          <p className="text-xs text-muted-foreground mt-0.5 max-w-3xl">
            Ledger — единый продюсер JSON-пакетов «смена → БП» (замена TL_ЭкспортБП). Приёмник
            <code className="mx-1 text-[11px]">TL_СопуткаСервис.ОбработатьПакетИзСтроки</code>
            не меняется. Выберите смену → анализ состава пакета → скачать JSON или выгрузить в каталог.
          </p>
        </div>
        <PolicyVatBadge className="shrink-0" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(320px,420px)_1fr]">
        {/* Пикер смен */}
        <div className="rounded-lg border border-border/50 overflow-hidden">
          <div className="bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
            Смены {shiftsQ.data ? `(${shiftsQ.data.shifts.length})` : ''}
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {shiftsQ.isLoading && <div className="p-4 text-sm text-muted-foreground">Загрузка смен…</div>}
            {shiftsQ.error && <div className="p-4 text-sm text-red-400/90">Ошибка загрузки смен</div>}
            <table className="w-full text-xs">
              <tbody>
                {shiftsQ.data?.shifts.map((sh) => (
                  <tr
                    key={sh.shift_key}
                    onClick={() => setKey(sh.shift_key)}
                    className={`border-t border-border/30 cursor-pointer ${key === sh.shift_key ? 'bg-accent/40' : 'hover:bg-accent/20'}`}
                  >
                    <td className="px-3 py-1.5 whitespace-nowrap">{sh.date}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">АЗС{sh.station}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-medium">{money(sh.revenue)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground" title="общепит">
                      {sh.obshepit > 0 ? money(sh.obshepit) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Анализ пакета */}
        <div className="min-w-0">
          {!key && (
            <div className="rounded-lg border border-dashed border-border/50 p-8 text-center text-sm text-muted-foreground">
              Выберите смену слева — соберём пакет и покажем состав.
            </div>
          )}
          {key && pkgQ.isLoading && <div className="p-4 text-sm text-muted-foreground">Сборка пакета…</div>}
          {key && pkgQ.error && <div className="p-4 text-sm text-red-400/90">Ошибка сборки пакета</div>}

          {pkg && analysis && shift && (
            <div className="space-y-4">
              {/* KPI + готовность */}
              <div className="grid gap-2.5 grid-cols-2 sm:grid-cols-4">
                <Kpi label="Документов" value={nf(pkg.Документы.length)} />
                <Kpi label="Позиций НСИ" value={nf(pkg.НСИ.length)} />
                <Kpi label="Сумма документов" value={money(analysis.total)} />
                <div className={`rounded-lg border p-3 ${analysis.ready ? 'border-emerald-400/40 bg-emerald-400/5' : 'border-amber-400/40 bg-amber-400/5'}`}>
                  <div className="text-[11px] text-muted-foreground flex items-center gap-1">
                    {analysis.ready
                      ? <><CheckCircle2 className="h-3 w-3 text-emerald-400/80" /> Готов к загрузке</>
                      : <><AlertTriangle className="h-3 w-3 text-amber-400/80" /> Не готов</>}
                  </div>
                  <div className="text-[10px] text-muted-foreground/70 mt-1 font-mono truncate" title={pkg.ХешПакета}>
                    {pkg.ХешПакета ? pkg.ХешПакета.slice(0, 16) + '…' : 'нет хеша'}
                  </div>
                </div>
              </div>

              {/* Действия */}
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={() => downloadJson(pkg, shift)}>
                  <Download className="h-4 w-4 mr-1.5" /> Скачать JSON
                </Button>
                <Button size="sm" variant="outline" onClick={() => emitMut.mutate()} disabled={emitMut.isPending}>
                  <FolderUp className="h-4 w-4 mr-1.5" />
                  {emitMut.isPending ? 'Выгрузка…' : 'Выгрузить в каталог'}
                </Button>
                {emitMut.isSuccess && (
                  <span className="text-xs text-emerald-400/90 flex items-center gap-1">
                    <FileJson className="h-3.5 w-3.5" /> {emitMut.data.file}
                  </span>
                )}
                {emitMut.isError && <span className="text-xs text-red-400/90">Ошибка выгрузки: {(emitMut.error as Error)?.message || 'неизвестно'}</span>}
              </div>

              {/* Состав документов */}
              <div className="overflow-x-auto rounded-lg border border-border/50">
                <table className="w-full text-xs">
                  <thead className="bg-muted/30 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium text-left">Тип документа</th>
                      <th className="px-3 py-2 font-medium text-left">Документ БП</th>
                      <th className="px-3 py-2 font-medium text-right">Кол-во</th>
                      <th className="px-3 py-2 font-medium text-right">Сумма</th>
                    </tr>
                  </thead>
                  <tbody>
                    {DOC_TYPES.filter((t) => analysis.docCount[t.key]).map((t) => (
                      <tr key={t.key} className="border-t border-border/30">
                        <td className="px-3 py-1.5 font-medium">{t.label}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{t.bp}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{nf(analysis.docCount[t.key])}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">
                          {analysis.docSum[t.key] ? money(analysis.docSum[t.key]) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Состав НСИ */}
              <div className="flex flex-wrap gap-2">
                {NSI_TYPES.filter((t) => analysis.nsiCount[t]).map((t) => (
                  <div key={t} className="rounded-md border border-border/50 bg-card/40 px-3 py-1.5 text-xs">
                    <span className="text-muted-foreground">{t}: </span>
                    <span className="font-medium tabular-nums">{nf(analysis.nsiCount[t])}</span>
                  </div>
                ))}
              </div>

              <p className="text-[11px] text-muted-foreground/70">
                Идемпотентность по (Тип + ИсточникUUID): повторная загрузка не плодит дубли. Проведение —
                зона бухгалтера (грузим непроведёнными). Каталог сервера по умолчанию — <code>C:\TL_BP_Export</code>.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  )
}
