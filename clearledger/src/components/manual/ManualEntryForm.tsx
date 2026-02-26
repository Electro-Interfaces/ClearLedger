import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { getSubcategories, getDocumentTypes, type DocumentType } from '@/config/categories'
import { useCompany } from '@/contexts/CompanyContext'
import { useCreateEntry } from '@/hooks/useEntries'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'

const baseSchema = z.object({
  categoryId: z.string().min(1, 'Выберите категорию'),
  subcategoryId: z.string().optional(),
  docTypeId: z.string().optional(),
  title: z.string().min(1, 'Введите заголовок'),
  // Correction
  correctionReason: z.string().optional(),
  // Note
  noteText: z.string().optional(),
  // File attachment
  attachment: z.any().optional(),
}).catchall(z.string().optional())

type FormValues = z.infer<typeof baseSchema>

interface ManualEntryFormProps {
  entryType: 'new' | 'correction' | 'note'
}

const typeLabels: Record<string, string> = {
  new: 'Новая запись',
  correction: 'Корректировка',
  note: 'Примечание',
}

export function ManualEntryForm({ entryType }: ManualEntryFormProps) {
  const { company, categories } = useCompany()
  const createEntry = useCreateEntry()
  const [saved, setSaved] = useState(false)

  const form = useForm<FormValues>({
    resolver: zodResolver(baseSchema),
    defaultValues: {
      categoryId: '',
      subcategoryId: '',
      docTypeId: '',
      title: '',
      correctionReason: '',
      noteText: '',
    },
  })

  const watchCategory = form.watch('categoryId')
  const watchSubcategory = form.watch('subcategoryId')
  const watchDocType = form.watch('docTypeId')
  const subcategories = getSubcategories(company.profileId, watchCategory)
  const documentTypes = getDocumentTypes(company.profileId, watchCategory, watchSubcategory || '')
  const selectedDocType: DocumentType | undefined = documentTypes.find((dt) => dt.id === watchDocType)

  // Reset subcategory and docType when category changes
  useEffect(() => {
    form.setValue('subcategoryId', '')
    form.setValue('docTypeId', '')
  }, [watchCategory, form])

  // Reset docType when subcategory changes
  useEffect(() => {
    form.setValue('docTypeId', '')
  }, [watchSubcategory, form])

  function onSubmit(data: FormValues) {
    // Собираем metadata из динамических полей
    const metadata: Record<string, string> = {}
    if (selectedDocType) {
      for (const mf of selectedDocType.metadataFields) {
        const val = data[mf.key]
        if (val) metadata[mf.key] = val
      }
    }
    if (data.correctionReason) metadata.correctionReason = data.correctionReason
    if (data.noteText) metadata.noteText = data.noteText

    createEntry.mutate({
      title: data.title,
      categoryId: data.categoryId || 'documents',
      subcategoryId: data.subcategoryId || '',
      docTypeId: data.docTypeId || undefined,
      source: 'manual',
      sourceLabel: 'Ручной',
      status: entryType === 'note' ? 'new' : 'new',
      metadata,
    })
    setSaved(true)
    form.reset()
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{typeLabels[entryType]}</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
            {/* Note type: simplified form */}
            {entryType === 'note' ? (
              <>
                <FormField
                  control={form.control}
                  name="title"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Заголовок</FormLabel>
                      <FormControl>
                        <Input placeholder="Заголовок примечания" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="noteText"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Текст примечания</FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="Введите текст примечания..."
                          rows={6}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            ) : (
              <>
                {/* Category */}
                <FormField
                  control={form.control}
                  name="categoryId"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Категория</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="Выберите категорию" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {categories.map((cat) => (
                            <SelectItem key={cat.id} value={cat.id}>
                              {cat.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Subcategory */}
                <FormField
                  control={form.control}
                  name="subcategoryId"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Подкатегория</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                        disabled={!watchCategory}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="Выберите подкатегорию" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {subcategories.map((sub) => (
                            <SelectItem key={sub.id} value={sub.id}>
                              {sub.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Document Type */}
                {documentTypes.length > 0 && (
                  <FormField
                    control={form.control}
                    name="docTypeId"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Тип документа</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                          disabled={!watchSubcategory}
                        >
                          <FormControl>
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Выберите тип документа" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {documentTypes.map((dt) => (
                              <SelectItem key={dt.id} value={dt.id}>
                                {dt.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                {/* Title */}
                <FormField
                  control={form.control}
                  name="title"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Заголовок</FormLabel>
                      <FormControl>
                        <Input placeholder="Название записи" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Dynamic metadata fields from document type */}
                {selectedDocType && selectedDocType.metadataFields.map((mf) => (
                  <div key={mf.key} className="grid gap-2">
                    <Label htmlFor={`meta-${mf.key}`}>
                      {mf.label}
                      {mf.required && <span className="text-destructive ml-1">*</span>}
                    </Label>
                    {mf.type === 'text' && (
                      <Input
                        id={`meta-${mf.key}`}
                        placeholder={mf.placeholder}
                        value={form.watch(mf.key) ?? ''}
                        onChange={(e) => form.setValue(mf.key, e.target.value)}
                      />
                    )}
                    {mf.type === 'number' && (
                      <div className="flex items-center gap-2">
                        <Input
                          id={`meta-${mf.key}`}
                          type="number"
                          placeholder={mf.placeholder ?? '0'}
                          value={form.watch(mf.key) ?? ''}
                          onChange={(e) => form.setValue(mf.key, e.target.value)}
                          className="flex-1"
                        />
                        {mf.unit && <span className="text-sm text-muted-foreground shrink-0">{mf.unit}</span>}
                      </div>
                    )}
                    {mf.type === 'date' && (
                      <Input
                        id={`meta-${mf.key}`}
                        type="date"
                        value={form.watch(mf.key) ?? ''}
                        onChange={(e) => form.setValue(mf.key, e.target.value)}
                      />
                    )}
                    {mf.type === 'select' && (
                      <Select
                        value={form.watch(mf.key) ?? ''}
                        onValueChange={(v) => form.setValue(mf.key, v)}
                      >
                        <SelectTrigger id={`meta-${mf.key}`} className="w-full">
                          <SelectValue placeholder={mf.placeholder ?? 'Выберите...'} />
                        </SelectTrigger>
                        <SelectContent>
                          {mf.options?.map((opt) => (
                            <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                    {mf.type === 'textarea' && (
                      <Textarea
                        id={`meta-${mf.key}`}
                        placeholder={mf.placeholder}
                        rows={3}
                        value={form.watch(mf.key) ?? ''}
                        onChange={(e) => form.setValue(mf.key, e.target.value)}
                      />
                    )}
                  </div>
                ))}

                {/* Correction reason */}
                {entryType === 'correction' && (
                  <FormField
                    control={form.control}
                    name="correctionReason"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Причина корректировки</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Укажите причину корректировки..."
                            rows={3}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
              </>
            )}

            {/* File attachment */}
            <div className="grid gap-2">
              <Label htmlFor="attachment">Вложение</Label>
              <Input
                id="attachment"
                type="file"
                onChange={(e) => {
                  form.setValue('attachment', e.target.files?.[0])
                }}
              />
            </div>

            <Button type="submit" className="mt-2" disabled={createEntry.isPending}>
              {createEntry.isPending ? 'Сохранение...' : 'Сохранить'}
            </Button>
            {saved && (
              <p className="text-sm text-green-500 font-medium">
                Запись сохранена и добавлена во Входящие
              </p>
            )}
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}

