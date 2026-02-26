/**
 * IntakePage — универсальная страница приёма документов.
 * «Бросай всё сюда» — заменяет upload/photo/manual.
 */

import { useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import type { IntakeItem } from '@/types'
import { processFile, processPaste, forceSaveDuplicate } from '@/services/intake/pipeline'
import { UniversalDropZone } from '@/components/intake/UniversalDropZone'
import { PasteZone } from '@/components/intake/PasteZone'
import { ProcessingQueue } from '@/components/intake/ProcessingQueue'
import { ClassificationPreview } from '@/components/intake/ClassificationPreview'
import { DuplicateWarning } from '@/components/intake/DuplicateWarning'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Upload, ClipboardPaste } from 'lucide-react'

export function IntakePage() {
  const { companyId } = useCompany()
  const queryClient = useQueryClient()
  const [items, setItems] = useState<IntakeItem[]>([])

  const updateItem = useCallback((updated: IntakeItem) => {
    setItems((prev) => {
      const idx = prev.findIndex((i) => i.id === updated.id)
      if (idx === -1) return [...prev, updated]
      const next = [...prev]
      next[idx] = updated
      return next
    })
  }, [])

  const invalidateEntries = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['entries', companyId] })
  }, [queryClient, companyId])

  const handleFiles = useCallback(
    (files: File[]) => {
      for (const file of files) {
        processFile(file, {
          companyId,
          onUpdate: (item) => {
            updateItem(item)
            if (item.status === 'done') invalidateEntries()
          },
        })
      }
    },
    [companyId, updateItem, invalidateEntries],
  )

  const handlePaste = useCallback(
    (text: string) => {
      processPaste(text, {
        companyId,
        onUpdate: (item) => {
          updateItem(item)
          if (item.status === 'done') invalidateEntries()
        },
      })
    },
    [companyId, updateItem, invalidateEntries],
  )

  const handleForceSave = useCallback(
    async (item: IntakeItem) => {
      const entry = await forceSaveDuplicate(item, companyId)
      if (entry) {
        setItems((prev) =>
          prev.map((i) =>
            i.id === item.id
              ? { ...i, status: 'done' as const, entryId: entry.id }
              : i,
          ),
        )
        invalidateEntries()
      }
    },
    [companyId, invalidateEntries],
  )

  const handleDismiss = useCallback((itemId: string) => {
    setItems((prev) => prev.filter((i) => i.id !== itemId))
  }, [])

  const handleClear = useCallback(() => {
    setItems((prev) => prev.filter((i) => i.status === 'processing'))
  }, [])

  const isProcessing = items.some((i) => i.status === 'processing')

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Приём документов</h1>
        <p className="text-muted-foreground mt-1">
          Загрузите файлы или вставьте текст — система автоматически определит тип и классифицирует
        </p>
      </div>

      <Tabs defaultValue="files" className="w-full">
        <TabsList>
          <TabsTrigger value="files" className="gap-1.5">
            <Upload className="size-4" />
            Файлы
          </TabsTrigger>
          <TabsTrigger value="paste" className="gap-1.5">
            <ClipboardPaste className="size-4" />
            Вставка текста
          </TabsTrigger>
        </TabsList>

        <TabsContent value="files" className="mt-4">
          <UniversalDropZone onFiles={handleFiles} disabled={isProcessing} />
        </TabsContent>

        <TabsContent value="paste" className="mt-4">
          <PasteZone onPaste={handlePaste} disabled={isProcessing} />
        </TabsContent>
      </Tabs>

      <ProcessingQueue items={items.filter((i) => i.status === 'processing')} />

      <DuplicateWarning
        items={items}
        onForceSave={handleForceSave}
        onDismiss={handleDismiss}
      />

      <ClassificationPreview items={items} onClear={handleClear} />
    </div>
  )
}
