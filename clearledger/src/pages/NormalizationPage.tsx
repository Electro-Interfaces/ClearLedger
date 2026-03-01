/**
 * Страница «Нормализация» — Layer 2: валидация + обогащение + соответствие.
 * Двухуровневая: локальная проверка + аудит TSupport (AI).
 */

import { useState, useCallback } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ClipboardList, ShieldCheck, Sparkles, Scale, Play, Loader2, Bot } from 'lucide-react'
import { toast } from 'sonner'
import { NormalizationKpiCards } from '@/components/normalization/NormalizationKpiCards'
import { NormalizationProgress } from '@/components/normalization/NormalizationProgress'
import { ValidationResultsTable } from '@/components/normalization/ValidationResultsTable'
import { EnrichmentResultsTable } from '@/components/normalization/EnrichmentResultsTable'
import { ComplianceReport } from '@/components/normalization/ComplianceReport'
import { AuditTab, DEMO_AUDIT_RESULT } from '@/components/normalization/AuditTab'
import type { AuditorNormResult } from '@/types'
import {
  useNormalizationSummary,
  useNormalizationState,
  useRunNormalizationPipeline,
  useApplyEnrichment,
} from '@/hooks/useNormalization'

interface ProgressInfo {
  phase: string
  done: number
  total: number
}

export function NormalizationPage() {
  const { data: summary } = useNormalizationSummary()
  const { data: state } = useNormalizationState()
  const runPipeline = useRunNormalizationPipeline()
  const applyEnrichment = useApplyEnrichment()

  const [progress, setProgress] = useState<ProgressInfo | null>(null)
  const [auditResult, setAuditResult] = useState<AuditorNormResult | null>(null)
  const [isAuditing, setIsAuditing] = useState(false)

  const handleRunAudit = useCallback(() => {
    setIsAuditing(true)
    // Заглушка: имитация вызова TSupport AI
    setTimeout(() => {
      setAuditResult(DEMO_AUDIT_RESULT)
      setIsAuditing(false)
      toast.success('Аудит TSupport завершён', {
        description: `Проверено ${DEMO_AUDIT_RESULT.totalChecked} документов 1С, ${DEMO_AUDIT_RESULT.findings.length} находок`,
      })
    }, 2500)
  }, [])

  const handleRun = useCallback(() => {
    setProgress({ phase: 'preparing', done: 0, total: 0 })
    runPipeline.mutate(
      (phase, done, total) => setProgress({ phase, done, total }),
      {
        onSuccess: (result) => {
          const s = result.summary
          toast.success('Нормализация завершена', {
            description: `Проверено ${s.totalEntries} записей: ${s.validPercent}% валидных, ${s.complianceFindings} находок`,
          })
        },
        onError: () => {
          toast.error('Ошибка при нормализации')
        },
        onSettled: () => setProgress(null),
      },
    )
  }, [runPipeline])

  const validationResults = state?.validationResults ?? []
  const enrichmentResults = state?.enrichmentResults ?? []
  const complianceFindings = state?.complianceFindings ?? []
  const issuesCount = validationResults.reduce((s, r) => s + r.errorCount + r.warningCount, 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Нормализация</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Валидация, обогащение из справочников и контроль соответствия
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={handleRunAudit}
            disabled={isAuditing || validationResults.length === 0}
          >
            {isAuditing
              ? <Loader2 className="size-4 mr-2 animate-spin" />
              : <Bot className="size-4 mr-2" />
            }
            {isAuditing ? 'Анализ...' : 'Аудит TSupport'}
          </Button>
          <Button
            onClick={handleRun}
            disabled={runPipeline.isPending}
          >
            {runPipeline.isPending
              ? <Loader2 className="size-4 mr-2 animate-spin" />
              : <Play className="size-4 mr-2" />
            }
            {runPipeline.isPending ? 'Выполняется...' : 'Запустить нормализацию'}
          </Button>
        </div>
      </div>

      {/* Progress */}
      {progress && (
        <NormalizationProgress
          phase={progress.phase}
          done={progress.done}
          total={progress.total}
        />
      )}

      {/* KPI */}
      {summary && <NormalizationKpiCards summary={summary} />}

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview" className="gap-1.5">
            <ClipboardList className="size-4" />
            Обзор
          </TabsTrigger>
          <TabsTrigger value="validation" className="gap-1.5">
            <ShieldCheck className="size-4" />
            Валидация
            {issuesCount > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{issuesCount}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="enrichment" className="gap-1.5">
            <Sparkles className="size-4" />
            Обогащение
          </TabsTrigger>
          <TabsTrigger value="compliance" className="gap-1.5">
            <Scale className="size-4" />
            Соответствие
            {summary && summary.criticalFindings > 0 && (
              <Badge variant="destructive" className="ml-1 text-xs">{summary.criticalFindings}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="audit" className="gap-1.5">
            <Bot className="size-4" />
            Аудит
            {auditResult && (auditResult.findings.length + auditResult.enrichmentProposals.length + auditResult.missingEntries.length) > 0 && (
              <Badge variant="outline" className="ml-1 text-xs border-purple-500 text-purple-400">
                {auditResult.findings.length + auditResult.enrichmentProposals.length + auditResult.missingEntries.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <OverviewTab summary={summary} lastRunAt={state?.summary?.lastRunAt} />
        </TabsContent>

        <TabsContent value="validation" className="mt-4">
          <ValidationResultsTable results={validationResults} />
        </TabsContent>

        <TabsContent value="enrichment" className="mt-4">
          <EnrichmentResultsTable
            results={enrichmentResults}
            onApply={(entryId, enrichment) => applyEnrichment.mutate({ entryId, enrichment })}
            isPending={applyEnrichment.isPending}
          />
        </TabsContent>

        <TabsContent value="compliance" className="mt-4">
          <ComplianceReport findings={complianceFindings} />
        </TabsContent>

        <TabsContent value="audit" className="mt-4">
          <AuditTab result={auditResult} isAuditing={isAuditing} localDone={validationResults.length > 0} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ---- Таб Обзор ----

/** Горизонтальный бар с цветом */
function StatBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-bold text-foreground">{value} <span className="text-xs text-muted-foreground font-normal">/ {max}</span></span>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  )
}

function OverviewTab({
  summary,
  lastRunAt,
}: {
  summary?: ReturnType<typeof useNormalizationSummary>['data']
  lastRunAt?: string
}) {
  if (!summary || summary.validatedCount === 0) {
    return (
      <div className="text-center py-16 space-y-2">
        <p className="text-lg font-medium text-muted-foreground">Нормализация ещё не запускалась</p>
        <p className="text-sm text-muted-foreground">
          Нажмите «Запустить нормализацию» для проверки качества данных
        </p>
      </div>
    )
  }

  const validCount = Math.round(summary.validPercent * summary.totalEntries / 100)
  const enrichedCount = summary.enrichedCount

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Левая колонка — прогресс-бары */}
        <div className="space-y-4">
          <StatBar label="Валидные записи" value={validCount} max={summary.totalEntries} color="hsl(120 100% 40%)" />
          <StatBar label="Обогащение из НСИ" value={enrichedCount} max={summary.totalEntries} color="hsl(280 100% 65%)" />
          <StatBar
            label="Без проблем"
            value={summary.totalEntries - summary.issuesCount}
            max={summary.totalEntries}
            color="hsl(217 91% 60%)"
          />
        </div>

        {/* Правая колонка — итоги */}
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Всего записей</p>
            <p className="text-2xl font-bold text-foreground">{summary.totalEntries}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Ожидают проверки</p>
            <p className="text-2xl font-bold text-blue-500">{summary.pendingCount}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Проблемы</p>
            <p className="text-2xl font-bold text-yellow-500">{summary.issuesCount}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Находки</p>
            <p className="text-2xl font-bold text-red-500">{summary.complianceFindings}</p>
          </div>
        </div>
      </div>

      {lastRunAt && (
        <p className="text-xs text-muted-foreground">
          Последний запуск: {new Date(lastRunAt).toLocaleString('ru-RU')}
        </p>
      )}
    </div>
  )
}
