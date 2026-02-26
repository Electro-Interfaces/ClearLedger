import { useCallback, useState } from 'react'
import type { UploadItem } from '@/types'
import { DropZone } from '@/components/upload/DropZone'
import {
  CategoryMetadataForm,
  type CategoryMetadata,
} from '@/components/upload/CategoryMetadataForm'
import { UploadQueue } from '@/components/upload/UploadQueue'
import { useCreateEntry } from '@/hooks/useEntries'

let nextId = 1

export function UploadPage() {
  const [queue, setQueue] = useState<UploadItem[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const createEntry = useCreateEntry()

  const handleFilesAdded = useCallback((files: File[]) => {
    const newItems: UploadItem[] = files.map((file) => ({
      id: String(nextId++),
      file,
      categoryId: '',
      subcategoryId: '',
      progress: 0,
      status: 'pending' as const,
    }))
    setQueue((prev) => [...prev, ...newItems])
  }, [])

  const handleRemove = useCallback((id: string) => {
    setQueue((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const handleSubmit = useCallback(
    (meta: CategoryMetadata) => {
      const pendingItems = queue.filter((item) => item.status === 'pending')

      // Assign metadata to all pending items
      setQueue((prev) =>
        prev.map((item) =>
          item.status === 'pending'
            ? {
                ...item,
                categoryId: meta.categoryId,
                subcategoryId: meta.subcategoryId,
              }
            : item
        )
      )

      // Simulate upload for pending items
      setIsUploading(true)

      setQueue((prev) =>
        prev.map((item) =>
          item.status === 'pending'
            ? {
                ...item,
                categoryId: meta.categoryId,
                subcategoryId: meta.subcategoryId,
                status: 'uploading' as const,
              }
            : item
        )
      )

      const pendingIds = pendingItems.map((item) => item.id)

      pendingIds.forEach((id, index) => {
        const delay = index * 400
        const file = pendingItems[index].file

        // Progress steps
        const steps = [20, 45, 70, 90, 100]
        steps.forEach((progress, stepIdx) => {
          setTimeout(() => {
            setQueue((prev) =>
              prev.map((item) =>
                item.id === id
                  ? {
                      ...item,
                      progress,
                      status: progress === 100 ? 'done' : 'uploading',
                    }
                  : item
              )
            )

            // При 100% — создаём запись в storage
            if (progress === 100) {
              createEntry.mutate({
                title: file.name,
                categoryId: meta.categoryId,
                subcategoryId: meta.subcategoryId,
                docTypeId: meta.docTypeId || undefined,
                source: 'upload',
                sourceLabel: 'Загрузка',
                fileType: file.type,
                fileSize: file.size,
                metadata: {
                  date: meta.date,
                  ...(meta.notes ? { notes: meta.notes } : {}),
                },
              })
            }

            // Check if all done
            if (
              stepIdx === steps.length - 1 &&
              index === pendingIds.length - 1
            ) {
              setIsUploading(false)
            }
          }, delay + (stepIdx + 1) * 300)
        })
      })
    },
    [queue, createEntry]
  )

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Загрузка файлов</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <DropZone onFilesAdded={handleFilesAdded} />
        </div>
        <div>
          <CategoryMetadataForm
            onSubmit={handleSubmit}
            disabled={
              isUploading || queue.filter((i) => i.status === 'pending').length === 0
            }
          />
        </div>
      </div>

      <UploadQueue items={queue} onRemove={handleRemove} />
    </div>
  )
}
