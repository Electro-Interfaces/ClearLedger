import { AlertCircle, AlertTriangle, CheckCircle, Clock3 } from 'lucide-react'

import type { ShiftStatus } from '@/types/shift-reports-v2'

type ShiftStatusTone = 'blue' | 'green' | 'gray' | 'red' | 'amber'

interface ShiftStatusConfig {
  label: string
  tone: ShiftStatusTone
  icon: typeof Clock3
}

function getOpenDurationHours(openedAt: string): number {
  return (Date.now() - new Date(openedAt).getTime()) / (1000 * 60 * 60)
}

export function getShiftStatusConfig(
  status: ShiftStatus,
  openedAt: string,
  hasDiscrepancies = false,
): ShiftStatusConfig {
  if (hasDiscrepancies) {
    return { label: 'Расхождения', tone: 'red', icon: AlertCircle }
  }

  if (status === 'open') {
    if (getOpenDurationHours(openedAt) > 24) {
      return { label: 'Открыта >24ч', tone: 'amber', icon: AlertTriangle }
    }
    return { label: 'Открыта', tone: 'blue', icon: Clock3 }
  }

  if (status === 'synchronized') {
    return { label: 'Закрыта без расхождений', tone: 'green', icon: CheckCircle }
  }

  if (status === 'closed') {
    return { label: 'Закрыта', tone: 'gray', icon: CheckCircle }
  }

  return { label: 'Неизвестно', tone: 'gray', icon: AlertCircle }
}

export function getShiftStatusBadgeClass(tone: ShiftStatusTone): string {
  switch (tone) {
    case 'blue':
      return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-300'
    case 'green':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300'
    case 'red':
      return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300'
    case 'amber':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300'
    case 'gray':
    default:
      return 'bg-secondary text-foreground border-border'
  }
}
