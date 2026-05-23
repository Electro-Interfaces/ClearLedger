/**
 * Прогресс-бар нормализации — показывается во время работы pipeline.
 */

import { Progress } from '@/components/ui/progress'

const phaseLabels: Record<string, string> = {
  preparing: 'Подготовка',
  validation: 'Валидация',
  enrichment: 'Обогащение',
  compliance: 'Соответствие',
}

interface Props {
  phase: string
  done: number
  total: number
}

export function NormalizationProgress({ phase, done, total }: Props) {
  const isPreparing = phase === 'preparing' || total === 0
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  const label = phaseLabels[phase] || phase

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">
          {isPreparing ? 'Подготовка...' : `${label}: ${done} / ${total}`}
        </span>
        {!isPreparing && <span className="text-muted-foreground">{percent}%</span>}
      </div>
      <Progress value={isPreparing ? undefined : percent} className={isPreparing ? 'animate-pulse' : ''} />
    </div>
  )
}
