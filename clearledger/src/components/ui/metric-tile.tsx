/**
 * Плитка показателя пространства — ЕДИНСТВЕННАЯ. Подпись, число, пояснение,
 * при наличии — Δ% к прошлому периоду и ряд под цифрой.
 *
 * До неё в проекте жило полтора десятка почти одинаковых `Kpi`/`Metric` —
 * в каждой витрине своя. Они разошлись в мелочах (отступ, размер подписи,
 * названия тонов), и любое общее изменение приходилось повторять по файлам:
 * так добавление спарклайна в KPI вышло тремя отдельными правками.
 *
 * Вид закреплён по витринам «Продаж» (решение МАГа 04.08.2026): рамка с
 * `bg-card/50`, подпись 11 px капителью, число `text-2xl`, Δ% глифом в правом
 * верхнем углу. Раньше половина пространства рисовала то же самое на `Card` с
 * `text-lg`, и две соседние витрины выглядели продуктами разных команд.
 *
 * `accent`/`tone` и `hint`/`sub` — синонимы: переходные, чтобы миграция витрин
 * не требовала переписывать каждый вызов. Для нового кода — `tone` и `hint`.
 */
import type { ReactNode } from "react"

import { TrendSpark } from "@/components/ui/trend-spark"
import { MetricHint } from "@/components/workspace/analytics/MetricHint"
import { cn } from "@/lib/utils"

type Tone = "success" | "warning" | "danger" | "info"

// Названия тонов, накопившиеся по витринам, — к одному словарю.
const TONE_ALIAS: Record<string, Tone> = {
  success: "success", good: "success", ok: "success",
  warning: "warning", warn: "warning",
  danger: "danger", bad: "danger", error: "danger",
  info: "info",
}

const TONE_CLASS: Record<Tone, string> = {
  success: "text-emerald-600 dark:text-emerald-400",
  warning: "text-amber-600 dark:text-amber-400",
  danger: "text-red-600 dark:text-red-400",
  info: "text-blue-600 dark:text-blue-400",
}

export function MetricTile({
  label, value, hint, sub, tone, accent, spark, card = true, className, children,
  valueClass, delta, deltaTitle, higherIsBetter = true, state, onClick, info,
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  /** Синоним hint (как называлось в витринах). */
  sub?: ReactNode
  tone?: string
  /** Синоним tone. */
  accent?: string
  /** Ряд под цифрой — только там, где экран его уже загрузил. */
  spark?: (number | null)[]
  /** false — плоская плитка в строке метрик, без карточки. */
  card?: boolean
  className?: string
  children?: ReactNode
  /** Доп. класс значения — пороговая раскраска там, где тона не хватает. */
  valueClass?: string
  /** Δ% к прошлому периоду. Абсурдные значения (пустая база) прячутся сами. */
  delta?: number | null
  /** Подсказка на Δ%: с чем сравниваем (период, база). */
  deltaTitle?: string
  /**
   * Куда красить рост. Поток заявок или простой растут — это плохо, и зелёный
   * плюс на таком показателе читался победой (правило «Пульса», PULSE.md §2).
   * `null` — показатель-контекст (объём обращений, число сессий): дельта видна,
   * но не окрашена, потому что ни рост, ни падение сами по себе не оценка.
   */
  higherIsBetter?: boolean | null
  /** Показатель просит внимания (`warn`) или посчитан по устаревшим данным (`stale`). */
  state?: "warn" | "stale"
  /** Плитка — вход в разрез. Рендерится настоящей кнопкой, а не div с onClick. */
  onClick?: () => void
  /** Пояснение «что это значит и как считается» — иконкой ⓘ у подписи. */
  info?: string
}) {
  const t = TONE_ALIAS[String(tone ?? accent ?? "")] as Tone | undefined
  const note = hint ?? sub
  // Пустая база даёт проценты вида «+41 900 %» — цифра без смысла, прячем.
  // Ноль после округления тоже прячем: «▲0.0%» читается как событие, хотя
  // изменения нет, и на телефоне этот шум стоит целой строки.
  const showDelta = delta != null && Math.abs(delta) <= 500 && Math.abs(delta) >= 0.05
  const up = (delta ?? 0) >= 0
  const deltaTone = higherIsBetter == null
    ? "text-muted-foreground"
    : (higherIsBetter ? up : !up)
      ? "text-emerald-600/90 dark:text-emerald-400/90"
      : "text-red-600/90 dark:text-red-400/90"

  const body = (
    <>
      <div className={cn("flex items-start gap-1 text-[11px] uppercase leading-tight tracking-wider text-muted-foreground",
        showDelta && "pr-12")}>
        <span className="line-clamp-2">{label}</span>
        {info && <MetricHint text={info} />}
      </div>
      <div className={cn("mt-1 truncate text-2xl font-semibold leading-tight tabular-nums",
        t && TONE_CLASS[t], valueClass)}>{value}</div>
      {/* Пояснение рендерится всегда: выгрузка читает первых трёх детей плитки
          по индексу, и пропуск строки увёл бы в колонку «пояснение» спарклайн. */}
      <div className="mt-0.5 text-xs text-muted-foreground">{note}</div>
      {showDelta && (
        // База сравнения — на самом проценте: она относится только к нему, а не
        // ко всей строке плиток (у части показателей своего Δ нет вовсе).
        <span title={deltaTitle}
          className={cn("absolute right-3 top-3 text-[11px] font-medium tabular-nums", deltaTone)}>
          {up ? "▲" : "▼"}{Math.abs(delta!).toFixed(1)}%
        </span>
      )}
      {spark ? <TrendSpark values={spark} tone="muted" full className="mt-1.5" /> : null}
      {children}
    </>
  )

  // data-kpi — контракт выгрузки: экспорт читает первых трёх детей плитки.
  if (!card) return <div data-kpi className={cn("relative min-w-0", className)}>{body}</div>

  const tile = (
    <div data-kpi className={cn("relative rounded-xl border bg-card/50 p-3.5 shadow-sm",
      // Альфа-шкала: один класс работает в обеих темах.
      state === "warn" && "border-amber-500/40 bg-amber-500/5",
      // Устаревшие данные — пунктиром, а не прозрачностью: гашение приглушённого
      // текста уводило подпись ниже порога контраста.
      state === "stale" && "border-dashed",
      onClick && "transition-colors hover:border-primary/50 hover:bg-accent/40",
      className)}>{body}</div>
  )
  if (!onClick) return tile
  // Кликабельная плитка — настоящая кнопка: клавиатура и скринридер получают её
  // бесплатно, в отличие от div с onClick.
  return (
    <button type="button" onClick={onClick}
      className="rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {tile}
    </button>
  )
}
