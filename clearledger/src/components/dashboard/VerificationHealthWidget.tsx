/**
 * VerificationHealthWidget — виджет здоровья верификации.
 *
 * Показывает stacked bar + counts по _verificationStatus из metadata.
 */

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getEntries } from '@/services/dataEntryService'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ShieldCheck } from 'lucide-react'

interface VerificationCounts {
  approved: number
  needs_review: number
  rejected: number
  unknown: number
  total: number
}

export function VerificationHealthWidget() {
  const { companyId } = useCompany()
  const navigate = useNavigate()

  const { data: entries = [] } = useQuery({
    queryKey: ['entries', companyId],
    queryFn: () => getEntries(companyId),
  })

  const counts = useMemo<VerificationCounts>(() => {
    let approved = 0
    let needs_review = 0
    let rejected = 0
    let unknown = 0

    for (const e of entries) {
      if (e.metadata._excluded === 'true' || e.status === 'archived') continue
      const vs = e.metadata._verificationStatus
      if (vs === 'approved') approved++
      else if (vs === 'needs_review') needs_review++
      else if (vs === 'rejected') rejected++
      else unknown++
    }
    return { approved, needs_review, rejected, unknown, total: approved + needs_review + rejected + unknown }
  }, [entries])

  const pct = (n: number) => counts.total > 0 ? Math.round((n / counts.total) * 100) : 0

  // Только показываем если есть данные
  if (counts.total === 0) return null

  const needsAction = counts.needs_review + counts.rejected

  return (
    <Card style={{ boxShadow: 'var(--shadow-soft)' }}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <ShieldCheck className="size-4" />
          Здоровье верификации
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Stacked bar */}
        <div className="flex h-3 rounded-full overflow-hidden bg-muted">
          {counts.approved > 0 && (
            <div
              className="bg-green-500 transition-all"
              style={{ width: `${pct(counts.approved)}%` }}
            />
          )}
          {counts.needs_review > 0 && (
            <div
              className="bg-yellow-500 transition-all"
              style={{ width: `${pct(counts.needs_review)}%` }}
            />
          )}
          {counts.rejected > 0 && (
            <div
              className="bg-red-500 transition-all"
              style={{ width: `${pct(counts.rejected)}%` }}
            />
          )}
          {counts.unknown > 0 && (
            <div
              className="bg-muted-foreground/30 transition-all"
              style={{ width: `${pct(counts.unknown)}%` }}
            />
          )}
        </div>

        {/* Counts */}
        <div className="space-y-1.5 text-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="size-2.5 rounded-full bg-green-500" />
              <span>Одобрено</span>
            </div>
            <span className="font-medium">{counts.approved} ({pct(counts.approved)}%)</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="size-2.5 rounded-full bg-yellow-500" />
              <span>Требует проверки</span>
            </div>
            <span className="font-medium">{counts.needs_review} ({pct(counts.needs_review)}%)</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="size-2.5 rounded-full bg-red-500" />
              <span>Отклонено</span>
            </div>
            <span className="font-medium">{counts.rejected} ({pct(counts.rejected)}%)</span>
          </div>
        </div>

        {/* Action */}
        {needsAction > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => navigate('/inbox')}
          >
            Обработать {needsAction} {needsAction === 1 ? 'запись' : 'записей'}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
