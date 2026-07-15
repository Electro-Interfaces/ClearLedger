/**
 * Режим «Выгрузка» (профиль energy / РусГидро) — РЕАЛЬНЫЙ контур файловых выгрузок
 * из нормализованной базы (заменил демо-заглушку на DEMO_EZS):
 *   • Реестр сессий (xlsx) — построчно с обеими ценами (розница/договор ЮЛ);
 *   • Реестр к выставлению под УПД (xlsx) — биллинг ЮЛ за месяц, НДС выделен;
 *   • Матрица «станция × месяц» (xlsx) — формат привычного свода «ОБЩАЯ»:
 *     паспорт + помесячные кВт·ч за весь горизонт (сводная → сессии).
 * Цель — закрывающие документы и реестры для учётной системы компании.
 */
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Download, FileSpreadsheet, Loader2, Table2, ReceiptText } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { exportChargeSessionsXlsx, exportMonthlyMatrixXlsx } from '@/services/chargeSessionsService'
import { exportCorporateBillingUpd } from '@/services/corporateService'

/** Последние 18 месяцев для выбора периода выгрузки (значение = 'YYYY-MM'). */
function monthOptions(): { v: string; label: string }[] {
  const out: { v: string; label: string }[] = []
  const d = new Date()
  d.setDate(1)
  for (let i = 0; i < 18; i++) {
    const v = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    out.push({ v, label: `${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}` })
    d.setMonth(d.getMonth() - 1)
  }
  return out
}
const monthRange = (ym: string): { from: string; to: string } => {
  const [y, m] = ym.split('-').map(Number)
  const last = new Date(y, m, 0).getDate()
  return { from: `${ym}-01`, to: `${ym}-${String(last).padStart(2, '0')}` }
}

function ExportCard({ icon: Icon, title, desc, action, busy, onRun, children }: {
  icon: typeof FileSpreadsheet; title: string; desc: string; action: string
  busy: boolean; onRun: () => void; children?: React.ReactNode
}) {
  return (
    <Card><CardContent className="flex h-full flex-col gap-3 pt-5">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary shrink-0" />
        <div className="text-sm font-medium">{title}</div>
      </div>
      <p className="flex-1 text-xs text-muted-foreground">{desc}</p>
      {children}
      <Button size="sm" className="gap-1.5" disabled={busy} onClick={onRun}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
        {action}
      </Button>
    </CardContent></Card>
  )
}

export function EnergyExportView() {
  const { companyId } = useCompany()
  const months = useMemo(monthOptions, [])
  // дефолт — прошлый месяц (закрытый период)
  const [month, setMonth] = useState(months[1]?.v ?? months[0]?.v ?? '')
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, fn: () => Promise<void>, okMsg: string) => {
    setBusy(key)
    try {
      await fn()
      toast.success(okMsg)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Выгрузка не удалась')
    } finally {
      setBusy(null)
    }
  }
  const range = monthRange(month)

  return (
    <div className="space-y-5 px-6 py-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Выгрузка</h1>
          <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Файловые выгрузки из нормализованной базы — реестры и закрывающие документы для
          учётной системы компании. Период месячных выгрузок:
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Select value={month} onValueChange={setMonth}>
            <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent className="max-h-[300px]">
              {months.map((m) => <SelectItem key={m.v} value={m.v} className="text-xs">{m.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">{range.from} — {range.to}</span>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <ExportCard
          icon={FileSpreadsheet}
          title="Реестр зарядных сессий"
          desc="Построчный xlsx за месяц: станция, коннектор, энергия, обе цены (тариф станции и договорной ЮЛ), обе выручки и разница. База для сверки с эквайрингом и ПК."
          action="Выгрузить сессии (xlsx)"
          busy={busy === 'sessions'}
          onRun={() => run('sessions',
            () => exportChargeSessionsXlsx({ companyId, dateFrom: range.from, dateTo: range.to }),
            'Реестр сессий выгружен')}
        />
        <ExportCard
          icon={ReceiptText}
          title="Реестр к выставлению (УПД, ЮЛ)"
          desc="Биллинг корпоративных клиентов за месяц: реестр к выставлению + детализация по сессиям, НДС выделен. Один клиент = один УПД (фильтр — во вкладке «Корпоратив»)."
          action="Выгрузить под УПД (xlsx)"
          busy={busy === 'upd'}
          onRun={() => run('upd',
            () => exportCorporateBillingUpd({ companyId, dateFrom: range.from, dateTo: range.to }),
            'Реестр под УПД выгружен')}
        />
        <ExportCard
          icon={Table2}
          title="Матрица «станция × месяц»"
          desc="Формат привычного свода «ОБЩАЯ»: паспорт станции (Б/У, ZOI-1, регион, класс, инвентарный №) + помесячные кВт·ч за весь горизонт 2024+. Прямая замена ручного Excel-свода."
          action="Выгрузить матрицу (xlsx)"
          busy={busy === 'matrix'}
          onRun={() => run('matrix',
            () => exportMonthlyMatrixXlsx(companyId),
            'Матрица станция×месяц выгружена')}
        />
      </div>

      <p className="text-xs text-muted-foreground/70">
        Экспорт аналитических витрин (Excel/PDF) — кнопками «Экспорт» в разделах «Продажи» и
        «Управленческий»; сводные-шаблоны по сессиям — в «Нормализации» канала сессий.
      </p>
    </div>
  )
}
