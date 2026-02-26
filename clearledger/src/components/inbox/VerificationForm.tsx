import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { StatusBadge } from '@/components/data/StatusBadge'
import { SourceBadge } from '@/components/data/SourceBadge'
import { formatDateTime } from '@/lib/formatDate'
import { Check, Clock, X, AlertCircle, AlertTriangle } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { getSubcategories } from '@/config/categories'
import { validateEntry } from '@/services/validationService'
import type { DataEntry } from '@/types'

export interface VerifyPayload {
  categoryId: string
  subcategoryId: string
  comment?: string
  metadata?: Record<string, string>
}

interface VerificationFormProps {
  entry: DataEntry
  onVerify: (payload: VerifyPayload) => void
  onPostpone: () => void
  onReject: (reason: string) => void
  isLoading?: boolean
}

function getConfidenceBadge(confidence: number) {
  if (confidence >= 90) {
    return <Badge variant="outline" className="border-green-600 text-green-500">{confidence}%</Badge>
  }
  if (confidence >= 70) {
    return <Badge variant="outline" className="border-yellow-600 text-yellow-500">{confidence}%</Badge>
  }
  return <Badge variant="outline" className="border-red-600 text-red-500">{confidence}%</Badge>
}

export function VerificationForm({
  entry,
  onVerify,
  onPostpone,
  onReject,
  isLoading,
}: VerificationFormProps) {
  const { company, effectiveCategories } = useCompany()
  const [comment, setComment] = useState('')
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [categoryId, setCategoryId] = useState(entry.categoryId)
  const [subcategoryId, setSubcategoryId] = useState(entry.subcategoryId)
  const [editedMetadata, setEditedMetadata] = useState<Record<string, string>>(() => ({ ...entry.metadata }))

  const subcategories = getSubcategories(company.profileId, categoryId)
  const metadataEntries = Object.entries(editedMetadata).filter(([k]) => k !== 'rejectReason' && !k.startsWith('_'))
  const systemEntries = Object.entries(editedMetadata).filter(([k]) => k.startsWith('_'))
  const ocrFields = entry.ocrData?.fields ?? []

  // Валидация — вычисляем на лету при изменении metadata
  const validation = useMemo(() => {
    const virtualEntry: DataEntry = { ...entry, metadata: editedMetadata, categoryId, subcategoryId }
    return validateEntry(virtualEntry, company.profileId)
  }, [entry, editedMetadata, categoryId, subcategoryId, company.profileId])

  // Поля с ошибками (для подсветки)
  const fieldIssues = useMemo(() => {
    const map = new Map<string, { severity: 'error' | 'warning'; message: string }>()
    for (const issue of validation.issues) {
      if (!map.has(issue.field) || issue.severity === 'error') {
        map.set(issue.field, { severity: issue.severity, message: issue.message })
      }
    }
    return map
  }, [validation])

  function updateMetaField(key: string, value: string) {
    setEditedMetadata((prev) => ({ ...prev, [key]: value }))
  }

  function handleRejectConfirm() {
    onReject(rejectReason || 'Отклонено менеджером')
    setShowRejectInput(false)
  }

  return (
    <Card className="h-full">
      <CardHeader className="border-b pb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <CardTitle className="text-base flex-1">{entry.title}</CardTitle>
          <StatusBadge status={entry.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 overflow-y-auto">
        {/* Прогресс валидации */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Заполненность</span>
            <span className={`font-medium ${validation.completeness >= 70 ? 'text-green-400' : validation.completeness >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
              {validation.completeness}%
            </span>
          </div>
          <Progress value={validation.completeness} className="h-1.5" />
        </div>

        {/* Категория / Подкатегория */}
        <div className="space-y-3">
          <div className="grid gap-2">
            <Label>Категория</Label>
            <Select value={categoryId} onValueChange={(v) => { setCategoryId(v); setSubcategoryId('') }}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {effectiveCategories.map((cat) => (
                  <SelectItem key={cat.id} value={cat.id}>{cat.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {subcategories.length > 0 && (
            <div className="grid gap-2">
              <Label>Подкатегория</Label>
              <Select value={subcategoryId} onValueChange={setSubcategoryId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Выберите подкатегорию" />
                </SelectTrigger>
                <SelectContent>
                  {subcategories.map((sub) => (
                    <SelectItem key={sub.id} value={sub.id}>{sub.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <Separator />

        {/* Метаданные (редактируемые) с валидацией */}
        {metadataEntries.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">Метаданные</h4>
            <div className="space-y-2">
              {metadataEntries.map(([key, value]) => {
                const issue = fieldIssues.get(key)
                return (
                  <div key={key} className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <Label className="min-w-[100px] text-xs text-muted-foreground capitalize shrink-0">{key}</Label>
                      <Input
                        value={value}
                        onChange={(e) => updateMetaField(key, e.target.value)}
                        className={`flex-1 h-8 text-sm ${issue?.severity === 'error' ? 'border-red-500/50' : issue?.severity === 'warning' ? 'border-yellow-500/50' : ''}`}
                      />
                      {issue && (
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger>
                              {issue.severity === 'error'
                                ? <AlertCircle className="size-4 text-red-400 shrink-0" />
                                : <AlertTriangle className="size-4 text-yellow-400 shrink-0" />}
                            </TooltipTrigger>
                            <TooltipContent>
                              <p className="text-xs">{issue.message}</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Системные поля (read-only) */}
        {systemEntries.length > 0 && (
          <div className="space-y-1.5">
            {systemEntries.map(([key, value]) => (
              <div key={key} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground/60">{key}</span>
                <span className="text-muted-foreground/60 max-w-[60%] truncate">{value}</span>
              </div>
            ))}
          </div>
        )}

        {/* OCR-подсказки */}
        {ocrFields.length > 0 && (
          <>
            <Separator />
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-muted-foreground">OCR результат</h4>
              <div className="space-y-2">
                {ocrFields.map((field) => (
                  <div key={field.key} className="flex items-center gap-2">
                    <Label className="min-w-[100px] text-xs">{field.label}</Label>
                    <Input
                      value={field.value}
                      readOnly
                      className="flex-1 h-8 text-sm"
                    />
                    {getConfidenceBadge(field.confidence)}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        <Separator />

        {/* Информация */}
        <div className="space-y-1.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Источник</span>
            <SourceBadge source={entry.source} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Создан</span>
            <span className="font-medium">{formatDateTime(entry.createdAt)}</span>
          </div>
        </div>

        <Separator />

        {/* Комментарий */}
        <div className="grid gap-2">
          <Label>Комментарий</Label>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Примечание к верификации..."
            rows={2}
          />
        </div>

        {/* Reject input */}
        {showRejectInput && (
          <div className="grid gap-2 p-3 border rounded-lg border-red-500/30 bg-red-500/5">
            <Label className="text-red-400">Причина отклонения</Label>
            <Textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Укажите причину отклонения..."
              rows={2}
              autoFocus
            />
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={handleRejectConfirm}
                disabled={isLoading}
              >
                Подтвердить отклонение
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowRejectInput(false)}
              >
                Отмена
              </Button>
            </div>
          </div>
        )}

        {/* Действия */}
        <div className="flex flex-col gap-2 pt-2">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="w-full">
                  <Button
                    onClick={() => onVerify({ categoryId, subcategoryId, comment: comment || undefined, metadata: editedMetadata })}
                    disabled={isLoading || !validation.isValid}
                    className="w-full bg-green-600 hover:bg-green-700 text-white"
                  >
                    <Check className="size-4" />
                    Верифицировать
                  </Button>
                </span>
              </TooltipTrigger>
              {!validation.isValid && (
                <TooltipContent>
                  <p className="text-xs">Заполните обязательные поля ({validation.issues.filter((i) => i.severity === 'error').length} ошибок)</p>
                </TooltipContent>
              )}
            </Tooltip>
          </TooltipProvider>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={onPostpone}
              disabled={isLoading}
              className="flex-1"
            >
              <Clock className="size-4" />
              Отложить
            </Button>
            <Button
              variant="outline"
              onClick={() => setShowRejectInput(true)}
              disabled={isLoading || showRejectInput}
              className="flex-1 text-red-500 hover:text-red-400 border-red-500/30 hover:bg-red-500/10"
            >
              <X className="size-4" />
              Отклонить
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
