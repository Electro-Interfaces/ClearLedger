#!/usr/bin/env bash
# Тянет чартовые компоненты Tremor Raw (Apache-2.0) и переводит их на зависимости
# и токены пространства: src/components/ui/{area,bar,line}-chart.tsx, bar-list.tsx,
# tracker.tsx. Палитра и утилиты живут в src/components/ui/chart-utils.ts — этот
# файл написан нами и скриптом НЕ перезаписывается.
#
# Запускать при обновлении версии компонента у Tremor:
#   bash scripts/adapt-tremor.sh && npx tsc -b
# После прогона глазами сверить changelog компонента — правки ниже привязаны к
# конкретным строкам исходника и могут перестать совпадать.
set -euo pipefail

REPO=https://raw.githubusercontent.com/tremorlabs/tremor/main/src/components
# ADAPT_DST — куда положить результат. Аудит (scripts/audit-canon.py) генерирует
# во временный каталог и сравнивает с рабочим, поэтому проверка ничего не портит.
DST="${ADAPT_DST:-$(cd "$(dirname "$0")/.." && pwd)/src/components/ui}"
mkdir -p "$DST"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

declare -A MAP=(
  [AreaChart]=area-chart.tsx
  [BarChart]=bar-chart.tsx
  [LineChart]=line-chart.tsx
  [ComboChart]=combo-chart.tsx
  [DonutChart]=donut-chart.tsx
  [SparkChart]=spark-chart.tsx
  [BarList]=bar-list.tsx
  [Tracker]=tracker.tsx
  [CategoryBar]=category-bar.tsx
  [ProgressCircle]=progress-circle.tsx
  [Callout]=callout.tsx
)

for c in "${!MAP[@]}"; do
  curl -fsS "$REPO/$c/$c.tsx" -o "$TMP/$c.tsx"
  sed -E \
    -e '/^"use client"$/d' \
    -e 's| tremor-id="tremor-raw"||g' \
    `# зависимости проекта вместо зависимостей Tremor` \
    -e 's|"@remixicon/react"|"lucide-react"|' \
    -e 's|RiArrowLeftSLine|ChevronLeft|g' \
    -e 's|RiArrowRightSLine|ChevronRight|g' \
    -e 's|import \* as HoverCardPrimitives from "@radix-ui/react-hover-card"|import { HoverCard as HoverCardPrimitives } from "radix-ui"|' \
    -e 's|import \{ cx \} from "\.\./\.\./utils/cx"|import { cn } from "@/lib/utils"|' \
    -e 's|\bcx\(|cn(|g' \
    -e 's|from "\.\./\.\./utils/(chartColors\|getYAxisDomain\|hasOnlyOneValueForKey\|focusRing)"|from "./chart-utils"|' \
    -e 's|from "\.\./\.\./hooks/useOnWindowResize"|from "./chart-utils"|' \
    `# тултип наружу: экран переопределяет формат значения, не переписывая разметку` \
    -e 's%^export \{ (Area|Bar|Line)Chart%export { ChartTooltip, \1Chart%' \
    `# recharts 3: label у тултипа приходит string | number | undefined, а не string` \
    -e 's%^  label: string$%  label?: string | number%' \
    -e 's%React\.useRef<string \| undefined>\(undefined\)%React.useRef<string | number | undefined>(undefined)%' \
    `# в tsconfig.app типов node нет` \
    -e 's|NodeJS\.Timeout|ReturnType<typeof setInterval>|g' \
    `# verbatimModuleSyntax: типы импортируются только как type` \
    -e 's|^import \{ tv, VariantProps \}|import { tv, type VariantProps }|' \
    -e 's|^  AvailableChartColorsKeys,$|  type AvailableChartColorsKeys,|' \
    `# recharts 3 берёт активный сектор из состояния подсказки, пропа activeIndex у Pie` \
    `# больше нет: сектор подсвечивается по наведению, выделение кликом отпало.` \
    -e '/^              activeIndex=\{activeIndex\}$/d' \
    `# палитра интерфейса вместо серых Tailwind` \
    -e 's|(group-hover:\|hover:)?text-gray-900 dark:\1text-gray-50|\1text-foreground|g' \
    -e 's|text-gray-900 dark:text-gray-50|text-foreground|g' \
    -e 's|text-gray-700 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-50|text-muted-foreground hover:bg-muted hover:text-foreground|g' \
    -e 's|text-gray-700 dark:text-gray-300|text-muted-foreground|g' \
    -e 's|text-gray-400 dark:text-gray-600|text-muted-foreground/60|g' \
    -e 's|hover:bg-gray-100 dark:hover:bg-gray-800|hover:bg-muted|g' \
    -e 's|hover:bg-gray-50 dark:hover:bg-gray-900|hover:bg-muted/60|g' \
    -e 's|bg-white dark:bg-gray-950|bg-popover|g' \
    -e 's|border-gray-200 dark:border-gray-800|border-border|g' \
    -e 's|stroke-gray-200 stroke-1 dark:stroke-gray-800|stroke-border stroke-1|g' \
    -e 's|fill-gray-500 dark:fill-gray-500|fill-muted-foreground|g' \
    -e 's|fill-gray-800 text-sm font-medium dark:fill-gray-200|fill-foreground text-sm font-medium|g' \
    -e 's|stroke-white dark:stroke-gray-950|stroke-card|g' \
    `# курсор подсказки: у Tremor серый хардкодом (на тёмной теме — светящаяся черта).` \
    `# классом, чтобы цвет жил там же, где остальная палитра компонента.` \
    -e 's|cursor=\{\{ stroke: "#d1d5db", strokeWidth: 1 \}\}|cursor={{ className: "stroke-border", strokeWidth: 1 }}|' \
    -e 's|cursor=\{\{ fill: "#d1d5db", opacity: "0.15" \}\}|cursor={{ className: "fill-muted", opacity: "0.4" }}|' \
    `# BarList: полоса — акцент пространства` \
    -e 's|bg-blue-200 dark:bg-blue-900|bg-primary/25|g' \
    -e 's|group-hover:bg-blue-300 dark:group-hover:bg-blue-800|group-hover:bg-primary/35|g' \
    `# Tracker: подсказка — поверхность popover, пустой блок — приглушённый` \
    -e 's|text-white dark:text-gray-900|text-popover-foreground|g' \
    -e 's|bg-gray-900 dark:bg-gray-50|bg-popover border border-border|g' \
    -e 's|bg-gray-400 dark:bg-gray-400|bg-muted-foreground/40|g' \
    `# ProgressCircle и Callout: статусы — на токенах, приглушённо (канон: цвет несёт смысл)` \
    -e 's|stroke-blue-200 dark:stroke-blue-500/30|stroke-primary/20|' \
    -e 's|stroke-blue-500 dark:stroke-blue-500|stroke-primary|' \
    -e 's|stroke-gray-200 dark:stroke-gray-500/40|stroke-muted-foreground/20|' \
    -e 's|stroke-gray-500 dark:stroke-gray-500|stroke-muted-foreground|' \
    -e 's|stroke-yellow-200 dark:stroke-yellow-500/30|stroke-warning/20|' \
    -e 's|stroke-yellow-500 dark:stroke-yellow-500|stroke-warning|' \
    -e 's|stroke-red-200 dark:stroke-red-500/30|stroke-error/20|' \
    -e 's|stroke-red-500 dark:stroke-red-500|stroke-error|' \
    -e 's|stroke-emerald-200 dark:stroke-emerald-500/30|stroke-success/20|' \
    -e 's|stroke-emerald-500 dark:stroke-emerald-500|stroke-success|' \
    -e 's|"text-blue-900 dark:text-blue-400"|"text-primary"|' \
    -e 's|"bg-blue-50 dark:bg-blue-950/70"|"bg-primary/10"|' \
    -e 's|"text-emerald-900 dark:text-emerald-500"|"text-success"|' \
    -e 's|"bg-emerald-50 dark:bg-emerald-950/70"|"bg-success/10"|' \
    -e 's|"text-red-900 dark:text-red-500"|"text-error"|' \
    -e 's|"bg-red-50 dark:bg-red-950/70"|"bg-error/10"|' \
    -e 's|"text-yellow-900 dark:text-yellow-500"|"text-warning"|' \
    -e 's|"bg-yellow-50 dark:bg-yellow-950/70"|"bg-warning/10"|' \
    -e 's|"text-gray-900 dark:text-gray-400"|"text-foreground"|' \
    -e 's|"bg-gray-100 dark:bg-gray-800/70"|"bg-muted"|' \
    `# CategoryBar: маркер обводится цветом карточки, DonutChart: подпись в центре` \
    -e 's|"ring-white dark:ring-gray-950"|"ring-card"|' \
    -e 's|className="fill-gray-700 dark:fill-gray-300"|className="fill-foreground"|' \
    "$TMP/$c.tsx" > "$DST/${MAP[$c]}"

  # Подписи делений. recharts красит текст тика цветом `stroke` оси (CartesianAxis:
  # `fill: stroke`), а Tremor ставит stroke="" — на светлой теме текст падает на
  # браузерный дефолт (чёрный) и это незаметно, на тёмной он сливается с фоном.
  # currentColor + text-* вместо fill-*: класс на <g> задаёт color, тик его берёт.
  perl -0777 -pi -e '
    s/stroke=""(?=\n\s+className=\{cn\()/stroke="currentColor"/g;
    s/"fill-muted-foreground",/"text-muted-foreground",/g;

    # CategoryBar тянет собственный Tooltip Tremor (проп content). Второй тултип
    # в проекте не заводим — переводим на составной shadcn, он уже везде.
    s{import \{ Tooltip \} from "\.\./Tooltip/Tooltip"}
     {import { Tooltip, TooltipTrigger, TooltipContent } from "./tooltip"};
    s{<Tooltip asChild content=\{marker\.tooltip\}>(.*?)</Tooltip>}
     {<Tooltip>\n                  <TooltipTrigger asChild>$1</TooltipTrigger>\n                  <TooltipContent>{marker.tooltip}</TooltipContent>\n                </Tooltip>}s;
  ' "$DST/${MAP[$c]}"

  echo "${MAP[$c]}: $(wc -l < "$DST/${MAP[$c]}") строк"
done

# Чужая палитра в наших файлах = правило выше перестало совпадать с исходником.
echo "— остатки чужой палитры (должно быть пусто):"
grep -nE '(gray|blue|white|emerald|red|amber)-[0-9]|bg-white|text-white|#[0-9a-fA-F]{6}|@remixicon|utils/cx|tremor-id' \
  "${MAP[@]/#/$DST/}" || echo "  чисто"
