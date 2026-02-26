import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface InboxNavigationProps {
  currentIndex: number
  total: number
  onPrevious: () => void
  onNext: () => void
}

export function InboxNavigation({ currentIndex, total, onPrevious, onNext }: InboxNavigationProps) {
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={onPrevious}
        disabled={currentIndex <= 0}
      >
        <ChevronLeft className="size-4" />
        Пред.
      </Button>
      <span className="text-sm text-muted-foreground px-2">
        {currentIndex + 1} из {total}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={onNext}
        disabled={currentIndex >= total - 1}
      >
        След.
        <ChevronRight className="size-4" />
      </Button>
    </div>
  )
}
