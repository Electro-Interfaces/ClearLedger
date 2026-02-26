import { useState } from 'react'
import type { OcrField } from '@/types'
import { ImagePreview } from '@/components/photo/ImagePreview'
import { OcrResultPanel } from '@/components/photo/OcrResultPanel'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCreateEntry } from '@/hooks/useEntries'

export function PhotoScanPage() {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [saved, setSaved] = useState(false)
  const createEntry = useCreateEntry()

  function handleImageSelected(file: File) {
    const url = URL.createObjectURL(file)
    setImageUrl(url)
    setImageFile(file)
    setSaved(false)
  }

  function handleOcrSave(fields: OcrField[], categoryId: string) {
    const metadata: Record<string, string> = {}
    for (const f of fields) {
      metadata[f.key] = f.value
    }
    const title = metadata.docNumber
      ? `Скан документа №${metadata.docNumber}`
      : imageFile?.name ?? 'Скан документа'

    createEntry.mutate({
      title,
      categoryId,
      subcategoryId: '',
      source: 'photo',
      sourceLabel: 'Фото',
      status: 'recognized',
      fileType: imageFile?.type,
      fileSize: imageFile?.size,
      ocrData: {
        text: '',
        fields,
        confidence: fields.length > 0
          ? Math.round(fields.reduce((s, f) => s + f.confidence, 0) / fields.length)
          : 0,
      },
      metadata,
    })
    setSaved(true)
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Фото / Скан</h1>

      <Tabs defaultValue="upload">
        <TabsList>
          <TabsTrigger value="upload">Загрузить скан</TabsTrigger>
          <TabsTrigger value="history">История</TabsTrigger>
        </TabsList>

        <TabsContent value="upload" className="mt-4">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <ImagePreview
              imageUrl={imageUrl}
              onImageSelected={handleImageSelected}
            />
            <div className="flex flex-col gap-3">
              <OcrResultPanel onSave={handleOcrSave} />
              {saved && (
                <p className="text-sm text-green-500 font-medium">
                  Запись сохранена и добавлена во Входящие
                </p>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <div className="text-muted-foreground flex min-h-[200px] items-center justify-center rounded-md border border-dashed p-8 text-sm">
            История сканов будет отображаться здесь
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
