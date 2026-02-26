import { useState } from 'react'
import type { OcrField } from '@/types'
import { useCompany } from '@/contexts/CompanyContext'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const MOCK_OCR_FIELDS: OcrField[] = [
  { key: 'docNumber', label: 'Номер документа', value: '245', confidence: 95 },
  { key: 'date', label: 'Дата', value: '25.02.2026', confidence: 88 },
  { key: 'counterparty', label: 'Контрагент', value: 'ООО ЛукОйл', confidence: 72 },
  { key: 'amount', label: 'Сумма', value: '458 200 \u20BD', confidence: 96 },
]

function getConfidenceBadge(confidence: number) {
  if (confidence >= 90) {
    return (
      <Badge variant="outline" className="border-green-600 text-green-500">
        {confidence}%
      </Badge>
    )
  }
  if (confidence >= 70) {
    return (
      <Badge variant="outline" className="border-yellow-600 text-yellow-500">
        {confidence}%
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-red-600 text-red-500">
      {confidence}%
    </Badge>
  )
}

interface OcrResultPanelProps {
  onSave: (fields: OcrField[], categoryId: string) => void
}

export function OcrResultPanel({ onSave }: OcrResultPanelProps) {
  const { categories } = useCompany()
  const [fields, setFields] = useState<OcrField[]>(MOCK_OCR_FIELDS)
  const [categoryId, setCategoryId] = useState('')

  function handleFieldChange(key: string, newValue: string) {
    setFields((prev) =>
      prev.map((f) => (f.key === key ? { ...f, value: newValue } : f))
    )
  }

  function handleSave() {
    onSave(fields, categoryId)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Результаты распознавания</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {fields.map((field) => (
          <div key={field.key} className="grid gap-2">
            <Label htmlFor={`ocr-${field.key}`}>{field.label}</Label>
            <div className="flex items-center gap-2">
              <Input
                id={`ocr-${field.key}`}
                value={field.value}
                onChange={(e) => handleFieldChange(field.key, e.target.value)}
                className="flex-1"
              />
              {getConfidenceBadge(field.confidence)}
            </div>
          </div>
        ))}

        <div className="grid gap-2 pt-2">
          <Label htmlFor="ocr-category">Категория</Label>
          <Select value={categoryId} onValueChange={setCategoryId}>
            <SelectTrigger id="ocr-category" className="w-full">
              <SelectValue placeholder="Выберите категорию" />
            </SelectTrigger>
            <SelectContent>
              {categories.map((cat) => (
                <SelectItem key={cat.id} value={cat.id}>
                  {cat.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button onClick={handleSave} className="mt-2">
          Подтвердить и сохранить
        </Button>
      </CardContent>
    </Card>
  )
}
