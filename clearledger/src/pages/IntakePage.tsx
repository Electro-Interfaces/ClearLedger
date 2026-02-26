/**
 * IntakePage — универсальная страница приёма документов.
 * «Бросай всё сюда» — заменяет upload/photo/manual.
 *
 * Поддерживает параметры:
 * - ?newVersionOf=XXX — загрузка новой версии документа
 */

import { useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import type { IntakeItem } from '@/types'
import { processFile, processPaste, forceSaveDuplicate } from '@/services/intake/pipeline'
import { prepareNewVersionMetadata, finalizeNewVersion } from '@/services/versionService'
import { getEntry, updateEntry } from '@/services/dataEntryService'

/** Макс. файлов, обрабатываемых одновременно */
const MAX_CONCURRENT = 3
import { UniversalDropZone } from '@/components/intake/UniversalDropZone'
import { PasteZone } from '@/components/intake/PasteZone'
import { IntakeQueue } from '@/components/intake/IntakeQueue'
import { ManualEntryForm } from '@/components/manual/ManualEntryForm'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Upload, ClipboardPaste, PenLine, Info } from 'lucide-react'
import { toast } from 'sonner'

export function IntakePage() {
  const { companyId, company } = useCompany()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const newVersionOf = searchParams.get('newVersionOf')
  const [items, setItems] = useState<IntakeItem[]>([])
  const activeCount = useRef(0)
  const pendingQueue = useRef<File[]>([])

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

  /**
   * После сохранения записи — если это новая версия, проставляем metadata и создаём link.
   */
  const handlePostSave = useCallback(async (entryId: string) => {
    if (!newVersionOf) return
    try {
      const versionMeta = await prepareNewVersionMetadata(companyId, newVersionOf)
      const entry = await getEntry(companyId, entryId)
      if (entry) {
        await updateEntry(companyId, entryId, {
          metadata: { ...entry.metadata, ...versionMeta },
        })
        await finalizeNewVersion(companyId, entryId, newVersionOf)
        toast.success(`Создана версия v${versionMeta._version}`)
      }
    } catch {
      // best effort
    }
    invalidateEntries()
  }, [companyId, newVersionOf, invalidateEntries])

  const processNext = useCallback(() => {
    while (activeCount.current < MAX_CONCURRENT && pendingQueue.current.length > 0) {
      const file = pendingQueue.current.shift()!
      activeCount.current++
      processFile(file, {
        companyId,
        profileId: company.profileId,
        onUpdate: (item) => {
          updateItem(item)
          if (item.status === 'done' || item.status === 'error' || item.status === 'duplicate') {
            activeCount.current--
            processNext()
            if (item.status === 'done') {
              if (item.entryId) {
                handlePostSave(item.entryId)
              } else {
                invalidateEntries()
              }
            }
          }
        },
      })
    }
  }, [companyId, company.profileId, updateItem, invalidateEntries, handlePostSave])

  const handleFiles = useCallback(
    (files: File[]) => {
      pendingQueue.current.push(...files)
      processNext()
    },
    [processNext],
  )

  const handlePaste = useCallback(
    (text: string) => {
      processPaste(text, {
        companyId,
        profileId: company.profileId,
        onUpdate: (item) => {
          updateItem(item)
          if (item.status === 'done') {
            if (item.entryId) {
              handlePostSave(item.entryId)
            } else {
              invalidateEntries()
            }
          }
        },
      })
    },
    [companyId, company.profileId, updateItem, invalidateEntries, handlePostSave],
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
        if (newVersionOf) {
          await handlePostSave(entry.id)
        } else {
          invalidateEntries()
        }
      }
    },
    [companyId, invalidateEntries, newVersionOf, handlePostSave],
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
        <h1 className="text-2xl font-bold tracking-tight">
          {newVersionOf ? 'Загрузка новой версии' : 'Приём документов'}
        </h1>
        <p className="text-muted-foreground mt-1">
          {newVersionOf
            ? 'Загрузите исправленную версию документа'
            : 'Загрузите файлы, вставьте текст или создайте запись вручную'}
        </p>
      </div>

      {newVersionOf && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-blue-500/30 bg-blue-500/5 text-sm">
          <Info className="size-4 text-blue-400 shrink-0" />
          <span>Новая версия для записи #{newVersionOf}. После загрузки предыдущая версия будет помечена как устаревшая.</span>
        </div>
      )}

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
          {!newVersionOf && (
            <TabsTrigger value="manual" className="gap-1.5">
              <PenLine className="size-4" />
              Ручной ввод
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="files" className="mt-4">
          <UniversalDropZone onFiles={handleFiles} disabled={isProcessing} />
        </TabsContent>

        <TabsContent value="paste" className="mt-4">
          <PasteZone onPaste={handlePaste} disabled={isProcessing} />
        </TabsContent>

        {!newVersionOf && (
          <TabsContent value="manual" className="mt-4">
            <ManualEntryForm entryType="new" />
          </TabsContent>
        )}
      </Tabs>

      <IntakeQueue
        items={items}
        onForceSave={handleForceSave}
        onDismiss={handleDismiss}
        onClear={handleClear}
      />
    </div>
  )
}
