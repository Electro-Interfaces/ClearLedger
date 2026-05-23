/**
 * Секция аудиторской нормализации (TSupport AI).
 * Сверка с документами 1С по закрытым/выверенным периодам.
 * Сейчас — заглушка с готовым контрактом для подключения.
 */

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Bot, Loader2, ExternalLink, AlertOctagon, AlertTriangle, Info, CheckCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { AuditorNormResult, AuditorNormFinding } from '@/types'

// Заглушка: демо-результат (будет заменён на реальный вызов TSupport)
const DEMO_RESULT: AuditorNormResult = {
  companyId: '',
  status: 'done',
  period: { from: '2025-10-01', to: '2025-12-31' },
  totalChecked: 247,
  matchedCount: 231,
  findings: [
    {
      id: 'af-1',
      severity: 'critical',
      category: 'missing_in_cl',
      title: 'Не найден оригинал: Поступление №456 от 12.11.2025',
      description: 'Документ из 1С (125 400 ₽, ООО «Ромашка») — нет соответствующей записи в ClearLedger',
      detectedAt: new Date().toISOString(),
    },
    {
      id: 'af-2',
      severity: 'warning',
      category: 'amount_mismatch',
      title: 'Расхождение суммы: Акт №89 от 05.12.2025',
      description: 'ClearLedger: 98 500 ₽ → 1С: 98 050 ₽ (разница 450 ₽)',
      entryId: 'e-demo-1',
      detectedAt: new Date().toISOString(),
    },
    {
      id: 'af-3',
      severity: 'info',
      category: 'period_incomplete',
      title: 'Неполный период: декабрь 2025',
      description: 'В 1С зарегистрировано 84 документа, в ClearLedger — 79 (не хватает 5)',
      detectedAt: new Date().toISOString(),
    },
  ],
  verifiedEntries: [],
  enrichmentProposals: [],
  correspondences: [],
  missingEntries: [],
  startedAt: new Date(Date.now() - 120_000).toISOString(),
  finishedAt: new Date().toISOString(),
}

const severityConfig = {
  critical: { icon: AlertOctagon, iconBg: 'hsl(0 84% 60% / 0.15)', iconColor: 'text-red-500', badgeClass: 'border-red-500 text-red-400' },
  warning: { icon: AlertTriangle, iconBg: 'hsl(45 100% 55% / 0.15)', iconColor: 'text-yellow-500', badgeClass: 'border-yellow-500 text-yellow-400' },
  info: { icon: Info, iconBg: 'hsl(217 91% 60% / 0.15)', iconColor: 'text-blue-500', badgeClass: 'border-blue-500 text-blue-400' },
} as const

interface Props {
  localDone: boolean
}

export function AuditorNormSection({ localDone }: Props) {
  const [result, setResult] = useState<AuditorNormResult | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const handleRunAudit = () => {
    setIsRunning(true)
    // Заглушка: имитация вызова TSupport AI
    setTimeout(() => {
      setResult(DEMO_RESULT)
      setIsRunning(false)
    }, 2500)
  }

  return (
    <div className="space-y-4">
      {/* Заголовок секции */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
            style={{ background: 'hsl(280 100% 65% / 0.15)' }}
          >
            <Bot className="size-4 text-purple-500" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Аудит TSupport</h3>
            <p className="text-xs text-muted-foreground">
              Сверка с документами 1С по закрытым периодам (AI)
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/partner/auditor">
            <Button variant="ghost" size="sm" className="gap-1.5 text-xs text-muted-foreground">
              <ExternalLink className="size-3" />
              Аудитор
            </Button>
          </Link>
          <Button
            size="sm"
            variant="outline"
            onClick={handleRunAudit}
            disabled={!localDone || isRunning}
          >
            {isRunning
              ? <Loader2 className="size-3.5 mr-1.5 animate-spin" />
              : <Bot className="size-3.5 mr-1.5" />
            }
            {isRunning ? 'Анализ...' : 'Запросить аудит'}
          </Button>
        </div>
      </div>

      {/* Подсказка: сначала локальная */}
      {!localDone && !result && (
        <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          Сначала выполните локальную нормализацию, затем запросите проверку аудитора
        </div>
      )}

      {/* Результаты аудитора */}
      {result && result.status === 'done' && (
        <div className="space-y-3">
          {/* KPI строка */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              <CheckCircle className="size-4 text-green-500" />
              <span className="text-foreground font-medium">{result.matchedCount}</span>
              <span className="text-muted-foreground">совпало</span>
            </div>
            <span className="text-muted-foreground">из {result.totalChecked} документов 1С</span>
            {result.period && (
              <Badge variant="outline" className="text-xs">
                {result.period.from} — {result.period.to}
              </Badge>
            )}
            {result.findings.length > 0 && (
              <Badge variant="outline" className="text-xs border-red-500 text-red-400">
                {result.findings.length} находок
              </Badge>
            )}
          </div>

          {/* Findings */}
          {result.findings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      )}
    </div>
  )
}

function FindingCard({ finding }: { finding: AuditorNormFinding }) {
  const cfg = severityConfig[finding.severity] || severityConfig.info
  const Icon = cfg.icon

  return (
    <Card>
      <CardContent className="flex items-start gap-3">
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ background: cfg.iconBg }}
        >
          <Icon className={`size-3.5 ${cfg.iconColor}`} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground">{finding.title}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{finding.description}</p>
        </div>
      </CardContent>
    </Card>
  )
}
