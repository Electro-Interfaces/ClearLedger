/**
 * Плитка показателя: подпись, число, пояснение.
 *
 * До неё в проекте жило полтора десятка почти одинаковых `Kpi`/`Metric` —
 * в каждой витрине своя. Они разошлись в мелочах (отступ, размер подписи,
 * названия тонов), и любое общее изменение приходилось повторять по файлам:
 * так добавление спарклайна в KPI вышло тремя отдельными правками.
 *
 * `accent`/`tone` и `hint`/`sub` — синонимы: переходные, чтобы миграция витрин
 * не требовала переписывать каждый вызов. Для нового кода — `tone` и `hint`.
 */
import type { ReactNode } from "react"

import { TrendSpark } from "@/components/ui/trend-spark"
import { Card, CardContent } from "@/components/ui/card"
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
}) {
  const t = TONE_ALIAS[String(tone ?? accent ?? "")] as Tone | undefined
  const note = hint ?? sub
  const body = (
    <>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-lg font-semibold tabular-nums", t && TONE_CLASS[t])}>{value}</div>
      {note ? <div className="mt-0.5 text-[11px] text-muted-foreground/80">{note}</div> : null}
      {spark ? <TrendSpark values={spark} tone="muted" full className="mt-1.5" /> : null}
      {children}
    </>
  )
  // data-kpi — контракт выгрузки: экспорт читает первых трёх детей плитки.
  return card
    ? <Card className={className}><CardContent data-kpi className="pt-4">{body}</CardContent></Card>
    : <div data-kpi className={cn("min-w-0", className)}>{body}</div>
}
