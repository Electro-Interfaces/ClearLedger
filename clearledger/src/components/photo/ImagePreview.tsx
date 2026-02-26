import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, ZoomIn, ZoomOut, RotateCw } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const ACCEPTED_IMAGE_TYPES: Record<string, string[]> = {
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png': ['.png'],
  'image/webp': ['.webp'],
}

interface ImagePreviewProps {
  imageUrl: string | null
  onImageSelected: (file: File) => void
}

export function ImagePreview({ imageUrl, onImageSelected }: ImagePreviewProps) {
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        setZoom(1)
        setRotation(0)
        onImageSelected(acceptedFiles[0])
      }
    },
    [onImageSelected]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_IMAGE_TYPES,
    maxSize: 50 * 1024 * 1024,
    multiple: false,
  })

  function handleZoomIn() {
    setZoom((prev) => Math.min(prev + 0.5, 3))
  }

  function handleZoomOut() {
    setZoom((prev) => Math.max(prev - 0.5, 1))
  }

  function handleRotate() {
    setRotation((prev) => (prev + 90) % 360)
  }

  if (!imageUrl) {
    return (
      <Card
        {...getRootProps()}
        className={cn(
          'flex min-h-[400px] cursor-pointer flex-col items-center justify-center gap-3 border-2 border-dashed p-10 transition-colors',
          isDragActive
            ? 'border-primary bg-primary/5'
            : 'border-muted-foreground/25 hover:border-muted-foreground/50'
        )}
      >
        <input {...getInputProps()} />
        <Upload
          className={cn(
            'size-10',
            isDragActive ? 'text-primary' : 'text-muted-foreground'
          )}
        />
        <div className="text-center">
          <p className="text-sm font-medium">
            Перетащите изображение сюда или нажмите для выбора
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            JPG, PNG, WebP — до 50 МБ
          </p>
        </div>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col overflow-hidden">
      <div className="border-b px-3 py-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="size-8" onClick={handleZoomIn}>
            <ZoomIn className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" onClick={handleZoomOut}>
            <ZoomOut className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" onClick={handleRotate}>
            <RotateCw className="size-4" />
          </Button>
          <span className="text-muted-foreground ml-2 text-xs">
            {Math.round(zoom * 100)}%
          </span>
        </div>
      </div>
      <div className="flex min-h-[400px] items-center justify-center overflow-auto bg-black/20 p-4">
        <img
          src={imageUrl}
          alt="Предпросмотр"
          className="max-h-[600px] object-contain transition-transform duration-200"
          style={{
            transform: `scale(${zoom}) rotate(${rotation}deg)`,
          }}
        />
      </div>
    </Card>
  )
}
