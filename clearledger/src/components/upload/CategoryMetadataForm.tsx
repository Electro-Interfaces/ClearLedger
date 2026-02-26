import { useState, useMemo } from 'react'
import { useCompany } from '@/contexts/CompanyContext'
import { getSubcategories, getDocumentTypes } from '@/config/categories'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export interface CategoryMetadata {
  categoryId: string
  subcategoryId: string
  docTypeId: string
  date: string
  notes: string
}

interface CategoryMetadataFormProps {
  onSubmit: (data: CategoryMetadata) => void
  disabled?: boolean
}

export function CategoryMetadataForm({
  onSubmit,
  disabled,
}: CategoryMetadataFormProps) {
  const { company, categories } = useCompany()
  const [categoryId, setCategoryId] = useState('')
  const [subcategoryId, setSubcategoryId] = useState('')
  const [docTypeId, setDocTypeId] = useState('')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [notes, setNotes] = useState('')

  const subcategories = useMemo(
    () => getSubcategories(company.profileId, categoryId),
    [company.profileId, categoryId],
  )

  const documentTypes = useMemo(
    () => getDocumentTypes(company.profileId, categoryId, subcategoryId),
    [company.profileId, categoryId, subcategoryId],
  )

  function handleCategoryChange(value: string) {
    setCategoryId(value)
    setSubcategoryId('')
    setDocTypeId('')
  }

  function handleSubcategoryChange(value: string) {
    setSubcategoryId(value)
    setDocTypeId('')
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!categoryId) return
    onSubmit({ categoryId, subcategoryId, docTypeId, date, notes })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Метаданные</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="grid gap-2">
            <Label htmlFor="category">Категория</Label>
            <Select value={categoryId} onValueChange={handleCategoryChange}>
              <SelectTrigger id="category" className="w-full">
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

          <div className="grid gap-2">
            <Label htmlFor="subcategory">Подкатегория</Label>
            <Select
              value={subcategoryId}
              onValueChange={handleSubcategoryChange}
              disabled={!categoryId}
            >
              <SelectTrigger id="subcategory" className="w-full">
                <SelectValue placeholder="Выберите подкатегорию" />
              </SelectTrigger>
              <SelectContent>
                {subcategories.map((sub) => (
                  <SelectItem key={sub.id} value={sub.id}>
                    {sub.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {documentTypes.length > 0 && (
            <div className="grid gap-2">
              <Label htmlFor="docType">Тип документа</Label>
              <Select value={docTypeId} onValueChange={setDocTypeId}>
                <SelectTrigger id="docType" className="w-full">
                  <SelectValue placeholder="Выберите тип" />
                </SelectTrigger>
                <SelectContent>
                  {documentTypes.map((dt) => (
                    <SelectItem key={dt.id} value={dt.id}>
                      {dt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="grid gap-2">
            <Label htmlFor="date">Дата</Label>
            <Input
              id="date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="notes">Примечание</Label>
            <Textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Дополнительная информация..."
              rows={3}
            />
          </div>

          <Button type="submit" disabled={!categoryId || disabled}>
            Загрузить
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
