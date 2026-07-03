/**
 * Раздел «Нормализация» для energy-профиля (ЭЗС).
 *
 * Показывает РЕАЛЬНУЮ внутреннюю многослойную БД, организованную под сводные/OLAP:
 *   • модель данных сессий — слои L1→L4, звёздная схема (факт + измерения),
 *     качество нормализации (EnergyNormalizationModel, реальные сессии компании);
 *   • реальный реестр «Энергоснабжение и аренда ЭЗС» (платёжная дисциплина, L1→L2).
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { fmtN } from '@/components/balance/balanceCalc'
import { usePaymentDisciplineSummary } from '@/hooks/useReferences'
import { EnergyNormalizationModel } from './EnergyNormalizationModel'

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </CardContent></Card>
  )
}

/* ── РЕАЛЬНЫЙ блок: нормализация реестра «Энергоснабжение и аренда ЭЗС» (L1→L2) ── */
function ReestrNormalizationBlock() {
  const q = usePaymentDisciplineSummary()
  const s = q.data
  if (!s || (s.l1Raw === 0 && s.settlements === 0)) return null
  const stages = [
    { t: 'Приём L1 (RAW)', d: 'Строки реестра «как есть» (одна строка = одна ЭЗС).', n: s.l1Raw, tone: 'bg-slate-500/15 text-slate-600 dark:text-slate-300' },
    { t: 'Нормализация', d: 'Резолв станции по № ЭЗС, разбор «оплачено по» → статус, основание (договор/разрешение).', n: s.l1Raw, tone: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
    { t: 'L2 (CLEAN)', d: 'Контрагенты, договоры и платёжная дисциплина по ЭЗС → разрезы «Поставщики э/э»/«Аренда».', n: s.l2Clean, tone: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  ]
  return (
    <Card className="border-l-2 border-l-primary"><CardContent className="space-y-3 pt-5">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">Нормализация реестра «Энергоснабжение и аренда ЭЗС»</div>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Записей L1 (RAW)" value={fmtN(s.l1Raw)} />
        <Kpi label="Нормализовано (L2)" value={fmtN(s.l2Clean)} />
        <Kpi label="Записей платёжной дисциплины" value={fmtN(s.settlements)} />
        <Kpi label="ЭЗС охвачено" value={fmtN(s.stationsCovered)} />
      </div>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
        {stages.map((st, i) => (
          <div key={st.t} className="flex flex-1 items-stretch gap-3">
            <div className="flex-1 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{st.t}</span>
                <Badge variant="secondary" className={`text-[10px] ${st.tone}`}>{fmtN(st.n)}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{st.d}</p>
            </div>
            {i < stages.length - 1 && <div className="hidden self-center text-muted-foreground/60 lg:block">→</div>}
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground/70">
        Источник «Реестр энергоснабжения и аренды ЭЗС» → канал «Энергоснабжение и аренда ЭЗС» (загрузка xlsx →
        L1 RAW → нормализация → L2). Витрины «Поставщики э/э» / «Аренда» строятся на L2.
      </p>
    </CardContent></Card>
  )
}

export function EnergyNormalizationView() {
  return (
    <div className="h-full overflow-y-auto">
      {/* Основная витрина: многослойная модель данных сессий ЭЗС (L1→L4 + звёздная схема + качество) */}
      <EnergyNormalizationModel />
      {/* Второй реальный датасет: реестр энергоснабжения/аренды (платёжная дисциплина) */}
      <div className="px-6 pb-8">
        <ReestrNormalizationBlock />
      </div>
    </div>
  )
}
