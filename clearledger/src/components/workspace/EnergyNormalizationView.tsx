/**
 * Энерго-вариант режима «Нормализация» (L1 RAW → L2 CLEAN) для профиля energy (ЭЗС).
 * Демо на данных сети DEMO_EZS: конвейер стадий приёма/разбора/нормализации,
 * правила нормализации (кВт·ч, RFID→клиент, тариф→категория, валюта ₽),
 * журнал нормализации (обработано/расхождения), карточки источников со статусом.
 * Заменяется выборкой из L1 RawBatch → L2 NormalizedRecord. Метрики — моки.
 */
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DEMO_EZS, sumBuy, sumRelease, tariffCheck, fmtN } from '../balance/balanceCalc'
import { usePaymentDisciplineSummary } from '@/hooks/useReferences'

const all = DEMO_EZS

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
        L1 RAW → нормализация → L2). Реальные данные на проде; ниже — демо-модель сетевой нормализации (ПК/эквайер/ОФД).
      </p>
    </CardContent></Card>
  )
}

// ─── агрегаты сети (демо) для расчёта объёмов конвейера ──────────────────────
const buyKwh = all.reduce((a, s) => a + sumBuy(s).kwh, 0)
const relKwh = all.reduce((a, s) => a + sumRelease(s).kwh, 0)
const revenue = all.reduce((a, s) => a + sumRelease(s).rub, 0)
const sessions = all.reduce((a, s) => a + tariffCheck(s).sessions, 0)
const noCategory = all.reduce((a, s) => a + tariffCheck(s).noCategory, 0)
const rateMismatch = all.reduce((a, s) => a + tariffCheck(s).rateMismatch, 0)

// Записи L1 ≈ сессии ПК + суточные показания ПУ + строки эквайера/ОФД (демо-оценка).
const rawSessions = sessions
const rawMeter = all.length * 30            // суточные интервалы ПУ ЭЗС за период
const rawAcquirer = Math.round(sessions * 0.92)
const rawOfd = Math.round(sessions * 0.97)
const rawTotal = rawSessions + rawMeter + rawAcquirer + rawOfd
// Расхождения, не прошедшие нормализацию автоматически (требуют разбора).
const issuesTotal = noCategory + rateMismatch + Math.round(rawMeter * 0.012)
const cleanTotal = rawTotal - issuesTotal

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

function Kpi({ label, value, accent }: { label: string; value: string; accent?: 'warn' | 'danger' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400' : accent === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </CardContent></Card>
  )
}

// ─── стадии конвейера L1 → L2 ────────────────────────────────────────────────
type Stage = { key: string; title: string; desc: string; count: number; tone: 'in' | 'mid' | 'out' }
const STAGES: Stage[] = [
  { key: 'l1', title: 'Приём L1 (RAW)', desc: 'Сырые пакеты источников «как есть»: сессии ПК, показания ПУ, строки эквайера/ОФД.', count: rawTotal, tone: 'in' },
  { key: 'parse', title: 'Разбор', desc: 'Распаковка пакета, схема полей, типизация, контроль обязательных реквизитов.', count: rawTotal, tone: 'mid' },
  { key: 'norm', title: 'Нормализация', desc: 'Единицы кВт·ч, RFID→клиент, тариф→категория, валюта ₽, дедуп по ключу.', count: rawTotal, tone: 'mid' },
  { key: 'l2', title: 'L2 (CLEAN)', desc: 'Нормализованные записи, готовые к разрезам сверки и витринам.', count: cleanTotal, tone: 'out' },
]
const STAGE_TONE: Record<Stage['tone'], string> = {
  in: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
  mid: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  out: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
}

// ─── источники L1 ────────────────────────────────────────────────────────────
type SrcStatus = 'ok' | 'warn' | 'idle'
const SRC_STATUS_META: Record<SrcStatus, { label: string; cls: string }> = {
  ok: { label: 'Получено', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  warn: { label: 'С расхождениями', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  idle: { label: 'Ожидание', cls: 'bg-muted text-muted-foreground' },
}
type Source = { name: string; kind: string; records: number; status: SrcStatus; note: string }
const SOURCES: Source[] = [
  { name: 'ПК ezs.rushydro.ru', kind: 'Личный кабинет сети · ручная выгрузка', records: rawSessions, status: 'ok', note: 'Сессии зарядки: кВт·ч, RFID, тариф, время.' },
  { name: 'ПУ ЭЗС (телеметрия)', kind: 'Приборы учёта станций · суточные интервалы', records: rawMeter, status: 'warn', note: 'Часть интервалов без показания — оценка по балансу.' },
  { name: 'Банк-эквайер', kind: 'Выписка эквайринга · реестр операций', records: rawAcquirer, status: 'ok', note: 'Холд/списание, комиссия, T+1 зачисление.' },
  { name: 'ОФД', kind: 'Оператор фискальных данных · чеки', records: rawOfd, status: 'warn', note: 'Сверка с ПК: непробитые чеки помечаются.' },
]

// ─── правила нормализации (L1 → L2) ──────────────────────────────────────────
type Rule = { name: string; from: string; to: string; applied: number; issues: number }
const RULES: Rule[] = [
  { name: 'Нормализация энергии', from: 'Вт·ч / показания ПУ', to: 'кВт·ч (единая единица)', applied: rawMeter + rawSessions, issues: Math.round(rawMeter * 0.012) },
  { name: 'Маппинг RFID → клиент', from: 'UID карты / токен сессии', to: 'Клиент (ЮЛ/ФЛ)', applied: rawSessions, issues: noCategory },
  { name: 'Тариф → категория', from: 'Код тарифа ПК', to: 'Категория ЮЛ/ФЛ', applied: rawSessions, issues: rateMismatch },
  { name: 'Сверка валюты ₽', from: 'Суммы эквайера / ОФД', to: 'Рубли (₽), НДС 22%', applied: rawAcquirer + rawOfd, issues: 0 },
]

export function EnergyNormalizationView() {
  const cleanPct = rawTotal ? (cleanTotal / rawTotal) * 100 : 0
  return (
    <div className="space-y-5 px-6 py-6">
      <Head
        title="Нормализация · энергопрофиль ЭЗС"
        subtitle="Конвейер L1 RAW → L2 CLEAN: приём сырых данных ПК / эквайера / ОФД, разбор и нормализация (кВт·ч, RFID→клиент, тариф→категория, валюта ₽)."
      />

      {/* РЕАЛЬНЫЙ блок реестра (energy) — поверх демо-модели сети */}
      <ReestrNormalizationBlock />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Записей L1 (RAW)" value={fmtN(rawTotal)} />
        <Kpi label="Нормализовано (L2)" value={fmtN(cleanTotal)} />
        <Kpi label="Расхождений на разбор" value={fmtN(issuesTotal)} accent={issuesTotal ? 'warn' : undefined} />
        <Kpi label="Чистота L2, %" value={`${cleanPct.toFixed(1)}%`} accent={cleanPct < 98 ? 'warn' : undefined} />
      </div>

      {/* конвейер стадий */}
      <Card><CardContent className="pt-5">
        <div className="mb-3 text-sm font-medium">Конвейер нормализации</div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
          {STAGES.map((st, i) => (
            <div key={st.key} className="flex flex-1 items-stretch gap-3">
              <div className="flex-1 rounded-lg border bg-muted/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{st.title}</span>
                  <Badge variant="secondary" className={`text-[10px] ${STAGE_TONE[st.tone]}`}>{fmtN(st.count)}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{st.desc}</p>
              </div>
              {i < STAGES.length - 1 && (
                <div className="hidden self-center text-muted-foreground/60 lg:block">→</div>
              )}
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground/70">
          Объёмы L1 = сессии ПК + суточные показания ПУ + строки эквайера/ОФД. Объём приёма ≈ {fmtN(buyKwh)} кВт·ч закупки и {fmtN(relKwh)} кВт·ч отпуска по сети.
        </p>
      </CardContent></Card>

      {/* правила нормализации */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Правила нормализации</div>
        <Table><TableHeader><TableRow>
          <TableHead>Правило</TableHead><TableHead>Из (L1)</TableHead>
          <TableHead>В (L2)</TableHead><TableHead className="text-right">Применено</TableHead>
          <TableHead className="text-center">Расхождений</TableHead>
        </TableRow></TableHeader><TableBody>
          {RULES.map((r) => (
            <TableRow key={r.name}>
              <TableCell className="font-medium">{r.name}</TableCell>
              <TableCell className="text-muted-foreground">{r.from}</TableCell>
              <TableCell className="text-muted-foreground">{r.to}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(r.applied)}</TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className={`text-[10px] ${r.issues ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'}`}>
                  {r.issues ? fmtN(r.issues) : 'чисто'}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
      </CardContent></Card>

      {/* журнал нормализации */}
      <Card><CardContent className="overflow-x-auto pt-5">
        <div className="mb-3 text-sm font-medium">Журнал нормализации</div>
        <Table><TableHeader><TableRow>
          <TableHead>Источник</TableHead><TableHead className="text-right">Принято L1</TableHead>
          <TableHead className="text-right">В L2</TableHead><TableHead className="text-right">Расхождений</TableHead>
          <TableHead className="text-center">Статус</TableHead>
        </TableRow></TableHeader><TableBody>
          {SOURCES.map((src) => {
            const issues = src.status === 'warn' ? Math.max(1, Math.round(src.records * 0.013)) : 0
            return (
              <TableRow key={src.name}>
                <TableCell className="font-medium">{src.name}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtN(src.records)}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(src.records - issues)}</TableCell>
                <TableCell className="text-right tabular-nums">{issues ? fmtN(issues) : '—'}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${SRC_STATUS_META[src.status].cls}`}>{SRC_STATUS_META[src.status].label}</Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
        <p className="mt-3 text-xs text-muted-foreground/70">
          Всего обработано {fmtN(rawTotal)} записей, расхождений {fmtN(issuesTotal)} (на ручной разбор). Выручка сети для контроля валюты ≈ {fmtN(revenue)} ₽ с НДС 22%.
        </p>
      </CardContent></Card>

      {/* карточки источников */}
      <div>
        <div className="mb-3 text-sm font-medium">Источники L1</div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          {SOURCES.map((src) => (
            <Card key={src.name}><CardContent className="pt-4">
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-medium">{src.name}</div>
                <Badge variant="secondary" className={`shrink-0 text-[10px] ${SRC_STATUS_META[src.status].cls}`}>{SRC_STATUS_META[src.status].label}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{src.kind}</div>
              <div className="mt-3 text-lg font-semibold tabular-nums">{fmtN(src.records)}</div>
              <div className="text-[11px] text-muted-foreground">записей принято</div>
              <p className="mt-2 text-xs text-muted-foreground/80">{src.note}</p>
            </CardContent></Card>
          ))}
        </div>
      </div>

      <p className="text-xs text-muted-foreground/70">
        Демо-данные. Конвейер и метрики — моки поверх DEMO_EZS; в проде L1 RawBatch → L2 NormalizedRecord по правилам источника/канала.
      </p>
    </div>
  )
}
