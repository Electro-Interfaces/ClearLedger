/**
 * Схема маршрута проекта — блок-схема по реальному графу, а не картинка регламента.
 *
 * Стадии и стрелки берутся из того же графа, по которому работают кнопки: правка
 * маршрута правит и схему. Раскрашено по журналу переходов — видно не «где мог бы
 * идти проект», а где он шёл: пройденные рёбра выделены, возвраты на доработку
 * видны отдельной дугой, а не растворяются в общем списке стадий.
 *
 * Рисуем своим SVG. Библиотека раскладки (dagre, reactflow) весит больше самой
 * задачи: маршрут линеен по порядку стадий, а развилки и петли — это дуги сбоку.
 */
import { useMemo } from 'react'
import { Check } from 'lucide-react'
import type { CaseState } from '@/services/sitesService'

/**
 * Части маршрута — схему целиком не охватить взглядом, и её режут по смыслу.
 *
 * Без номеров сознательно: рядом на этой же вкладке идёт лента «Этап 1 … Этап 4»
 * по стадиям воронки, а в чек-листе — номера пунктов регламента («7.5»). Третья
 * нумерация на одном экране заставляла бы гадать, на каком «этапе» проект.
 */
const PHASES: { key: string; title: string; codes: string[] }[] = [
  { key: 'select', title: 'Подбор и согласование локации',
    codes: ['ezs_intake', 'ezs_location', 'ezs_survey', 'ezs_presentation', 'ezs_negotiation'] },
  { key: 'land', title: 'Проработка, решение и право на землю',
    codes: ['ezs_dd', 'ezs_decision', 'ezs_land_form', 'ezs_permit'] },
  { key: 'contract', title: 'Договор и технологическое присоединение',
    codes: ['ezs_contract_draft', 'ezs_contract_approval', 'ezs_contract_sign', 'ezs_tp'] },
  { key: 'build', title: 'Подготовка и производство работ',
    codes: ['ezs_planning', 'ezs_estimate', 'ezs_procurement', 'ezs_contract', 'ezs_works', 'ezs_pnr'] },
  { key: 'accept', title: 'Приёмка и ввод в эксплуатацию',
    codes: ['ezs_oco_pnr', 'ezs_final', 'ezs_handover', 'ezs_acceptance', 'ezs_commissioning',
      'ezs_oco_final', 'ezs_done'] },
  { key: 'stop', title: 'Выходы из маршрута: пауза и отказ',
    codes: ['ezs_hold', 'ezs_rejected'] },
]

const BOX_W = 250
const BOX_H = 46
const GAP_Y = 34          // просвет между блоками — в нём живут стрелка и её подпись
const PAD_L = 170         // слева проходят возвраты на доработку — вместе с подписью
const PAD_R = 300         // справа — переходы через стадию и выходы вбок с подписями
const PAD_TOP = 10

type Stage = NonNullable<CaseState['stages']>[number]
type Link = NonNullable<CaseState['links']>[number]

/** Пройденное ребро — то, которым проект реально шёл (журнал переходов). */
function walkedKeys(path: CaseState['path']): Set<string> {
  return new Set((path ?? []).filter((p) => p.from_code).map((p) => `${p.from_code}→${p.to_code}`))
}

export function ProjectFlowChart({ state }: { state: CaseState }) {
  const stages = state.stages ?? []
  const links = state.links ?? []
  const walked = useMemo(() => walkedKeys(state.path), [state.path])
  const current = state.stage?.code ?? null
  // Сколько раз проект входил в стадию: второй вход — это возврат на доработку,
  // и он объясняет, почему схема «уже пройденная» снова активна.
  const visits = useMemo(() => {
    const m: Record<string, number> = {}
    for (const p of state.path ?? []) m[p.to_code] = (m[p.to_code] ?? 0) + 1
    return m
  }, [state.path])

  if (!stages.length || !links.length) {
    return <div className="text-sm text-muted-foreground">Схема маршрута появится, когда проект встанет на маршрут.</div>
  }

  const byCode = new Map(stages.map((s) => [s.code, s]))
  // Стадии, не попавшие ни в одну часть (граф изменили, а разбивку — нет), не
  // теряем: иначе схема тихо соврёт, что маршрут короче, чем он есть.
  const known = new Set(PHASES.flatMap((p) => p.codes))
  const orphans = stages.filter((s) => !known.has(s.code)).map((s) => s.code)

  return (
    <div className="space-y-3">
      <Legend />
      {PHASES.map((ph) => {
        const codes = ph.codes.filter((c) => byCode.has(c))
        if (!codes.length) return null
        return <PhaseBlock key={ph.key} title={ph.title} codes={codes} byCode={byCode}
          links={links} walked={walked} current={current} visits={visits} />
      })}
      {orphans.length > 0 && (
        <PhaseBlock title="Прочие стадии маршрута" codes={orphans} byCode={byCode}
          links={links} walked={walked} current={current} visits={visits} />
      )}
    </div>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-3 w-5 rounded-sm bg-emerald-500/15 border border-emerald-500" />
        пройдено
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-3 w-5 rounded-sm bg-primary/15 border-2 border-primary" />
        проект здесь
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-3 w-5 rounded-sm border border-dashed border-muted-foreground/60" />
        впереди
      </span>
      <span className="inline-flex items-center gap-1">
        <svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor"
          className="text-emerald-600" strokeWidth="2" /></svg>
        шли этим путём
      </span>
      <span className="inline-flex items-center gap-1">
        <svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor"
          className="text-amber-600" strokeWidth="2" strokeDasharray="4 3" /></svg>
        возврат на доработку
      </span>
    </div>
  )
}

function PhaseBlock({ title, codes, byCode, links, walked, current, visits }: {
  title: string; codes: string[]; byCode: Map<string, Stage>; links: Link[]
  walked: Set<string>; current: string | null; visits: Record<string, number>
}) {
  const idx = new Map(codes.map((c, i) => [c, i]))
  const y = (i: number) => PAD_TOP + i * (BOX_H + GAP_Y)
  const height = PAD_TOP * 2 + codes.length * BOX_H + (codes.length - 1) * GAP_Y
  const width = PAD_L + BOX_W + PAD_R
  const cx = PAD_L + BOX_W / 2
  const hasCurrent = codes.includes(current ?? '')

  // Рёбра этой части: внутренние рисуем линиями, уходящие наружу — короткой
  // стрелкой вбок с именем стадии-цели. Без этого часть выглядела бы тупиком.
  const inner: Link[] = []
  const outgoing: Link[] = []
  for (const l of links) {
    if (!idx.has(l.from_code)) continue
    if (idx.has(l.to_code)) inner.push(l)
    else outgoing.push(l)
  }

  return (
    <section className={`rounded-lg border ${hasCurrent ? 'border-primary/50 bg-primary/[0.03]' : 'border-border'}`}>
      <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
        <span className="text-sm font-semibold">{title}</span>
        {hasCurrent && <span className="text-xs text-primary ml-auto">проект здесь</span>}
      </div>
      {/* Схема шире экрана на узком мониторе — прокручиваем её, а не страницу. */}
      <div className="p-2 overflow-x-auto">
        {/* role="img" прячет содержимое SVG от экранного диктора целиком, поэтому
            весь смысл схемы обязан уместиться в подпись: какие стадии, что пройдено
            и где проект стоит. Иначе незрячий читатель получит только заголовок. */}
        <svg width={width} height={height} className="max-w-none" role="img"
          aria-label={`Схема маршрута, ${title}. ${codes.map((c) => {
            const s = byCode.get(c)!
            return `${s.name} — ${c === current ? 'проект здесь' : s.visited_at ? 'пройдено' : 'впереди'}`
          }).join('; ')}.`}>
          <defs>
            <marker id="fc-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5"
              orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L7,3.5 L0,7 z" fill="currentColor" />
            </marker>
          </defs>

          {inner.map((l, k) => {
            const a = idx.get(l.from_code)!
            const b = idx.get(l.to_code)!
            const done = walked.has(`${l.from_code}→${l.to_code}`)
            const back = b < a
            // Возврат, которым реально ходили, остаётся янтарным, а не зеленеет:
            // «проект вернули на доработку» — это и есть смысл, который надо видеть,
            // а не то, что ребро когда-то сработало.
            // Прозрачность к подписям не применяем: `text-muted-foreground/50` на
            // белом даёт контраст 2:1 при норме 4.5:1 — текст на схеме перестаёт
            // читаться у всех, а не только у слабовидящих.
            const cls = back ? 'text-amber-600 dark:text-amber-500'
              : done ? 'text-emerald-600 dark:text-emerald-500'
              : 'text-muted-foreground'
            const full = l.verb
            const label = full.length > 22 ? full.slice(0, 21) + '…' : full
            if (b === a + 1) {
              // Соседи — прямая стрелка вниз, подпись рядом с ней. Между теми же
              // двумя стадиями рёбер бывает несколько («Договор подряда подписан»
              // и «Работы начаты»): подписи разводим по строкам, иначе они лягут
              // друг на друга и не прочитается ни одна.
              const nth = inner.filter((o, j) => o.from_code === l.from_code && o.to_code === l.to_code && j < k).length
              const y1 = y(a) + BOX_H, y2 = y(b)
              return (
                <g key={k} className={cls}>
                  {nth === 0 && (
                    <line x1={cx} y1={y1} x2={cx} y2={y2 - 2} stroke="currentColor"
                      strokeWidth={done ? 2 : 1.2} markerEnd="url(#fc-arrow)" />
                  )}
                  <text x={cx + 6} y={(y1 + y2) / 2 + 3 + nth * 11} className="fill-current text-[10px]">
                    {label}
                    {/* Обрезанную подпись должно быть чем прочитать целиком. */}
                    {label !== full && <title>{full}</title>}
                  </text>
                </g>
              )
            }
            // Через стадию — дуга справа; назад — дуга слева
            const x0 = back ? PAD_L : PAD_L + BOX_W
            const off = back ? -(30 + (k % 3) * 14) : (40 + (k % 3) * 16)
            const y1 = y(a) + BOX_H / 2, y2 = y(b) + BOX_H / 2
            const d = `M ${x0} ${y1} C ${x0 + off} ${y1}, ${x0 + off} ${y2}, ${x0} ${y2}`
            return (
              <g key={k} className={cls}>
                <path d={d} fill="none" stroke="currentColor" strokeWidth={done ? 2 : 1.2}
                  strokeDasharray={back ? '4 3' : undefined} markerEnd="url(#fc-arrow)" />
                {/* Подпись — у начала дуги, а не в её середине: в середине она
                    ложится на боковые подписи соседних стадий. */}
                <text x={back ? x0 + off - 4 : x0 + off + 4} y={y1 + (y2 > y1 ? 16 : -8)}
                  textAnchor={back ? 'end' : 'start'} className="fill-current text-[10px]">
                  {label}
                  {label !== full && <title>{full}</title>}
                </text>
              </g>
            )
          })}

          {outgoing.map((l, k) => {
            const a = idx.get(l.from_code)!
            const done = walked.has(`${l.from_code}→${l.to_code}`)
            const cls = done ? 'text-emerald-600 dark:text-emerald-500' : 'text-muted-foreground'
            // Из одной стадии наружу ведут два-три ребра (отказ, пауза, следующая
            // часть). Разводим их по своим строкам: наложенные подписи читаются
            // как одна строка-каша, из которой не понять, куда что ведёт.
            const nth = outgoing.filter((o, j) => o.from_code === l.from_code && j < k).length
            const total = outgoing.filter((o) => o.from_code === l.from_code).length
            const yy = y(a) + BOX_H / 2 + (nth - (total - 1) / 2) * 15
            const x1 = PAD_L + BOX_W
            const target = byCode.get(l.to_code)?.name ?? l.to_code
            const label = `${l.verb} → ${target}`
            return (
              <g key={`o${k}`} className={cls}>
                <line x1={x1} y1={yy} x2={x1 + 26} y2={yy} stroke="currentColor"
                  strokeWidth={done ? 2 : 1.2} markerEnd="url(#fc-arrow)" />
                <text x={x1 + 30} y={yy + 3} className="fill-current text-[10px]">
                  {label.length > 46 ? label.slice(0, 45) + '…' : label}
                  {label.length > 46 && <title>{label}</title>}
                </text>
              </g>
            )
          })}

          {codes.map((code, i) => {
            const s = byCode.get(code)!
            const isCurrent = code === current
            const isDone = !!s.visited_at && !isCurrent
            const again = (visits[code] ?? 0) > 1
            return (
              <g key={code}>
                <rect x={PAD_L} y={y(i)} width={BOX_W} height={BOX_H} rx="6"
                  className={isCurrent ? 'fill-primary/10 stroke-primary'
                    : isDone ? 'fill-emerald-500/10 stroke-emerald-500'
                    : 'fill-transparent stroke-muted-foreground/40'}
                  strokeWidth={isCurrent ? 2 : 1}
                  strokeDasharray={!isDone && !isCurrent ? '5 4' : undefined} />
                <text x={PAD_L + 12} y={y(i) + (s.visited_at ? 20 : 27)}
                  className={`fill-current text-[12px] ${isCurrent ? 'font-semibold' : isDone ? '' : 'text-muted-foreground'}`}>
                  {s.name.length > 30 ? s.name.slice(0, 29) + '…' : s.name}
                  {s.name.length > 30 && <title>{s.name}</title>}
                </text>
                {s.visited_at && (
                  <text x={PAD_L + 12} y={y(i) + 34} className="fill-current text-[10px] text-muted-foreground">
                    {isCurrent ? 'проект здесь' : 'пройдено'} · {new Date(s.visited_at).toLocaleDateString('ru-RU')}
                    {again && ` · заходов: ${visits[code]}`}
                  </text>
                )}
                {isDone && (
                  <foreignObject x={PAD_L + BOX_W - 26} y={y(i) + 12} width="18" height="18">
                    <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-500" />
                  </foreignObject>
                )}
              </g>
            )
          })}
        </svg>
      </div>
    </section>
  )
}
