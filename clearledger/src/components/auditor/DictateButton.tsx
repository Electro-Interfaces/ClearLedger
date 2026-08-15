/**
 * Диктовка — кнопка микрофона рядом со строкой ввода.
 *
 * Считает СВОЙ распознаватель стека (`services/asr`, faster-whisper на процессоре ВМ):
 * запись не покидает контейнер компании. Системная диктовка (Win+H) сюда не годится по
 * другой причине — терминал в браузере не текстовое поле, и печатать ей некуда.
 *
 * Профиль `asr` в стеке не включён — кнопка не показывается вовсе: пусть её не будет,
 * чем она будет отвечать «недоступно».
 */
import { useEffect, useRef, useState } from 'react'
import { Loader2, Mic, Square } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { dictate } from '@/services/spaceAuditorService'

/**
 * Запись и распознавание — отдельно от кнопки.
 *
 * Тем же занимается удержание клавиши в мастерской: терминал не текстовое поле, кнопку
 * там жать неудобно, а руки уже на клавиатуре. Логика одна, входов два.
 */
export function useDictation(onText: (text: string) => void) {
  const [state, setState] = useState<'idle' | 'rec' | 'busy'>('idle')
  const recRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  // Уходим со страницы на записи — микрофон надо отпустить, иначе индикатор в браузере
  // висит до перезагрузки вкладки.
  useEffect(() => () => {
    recRef.current?.stream.getTracks().forEach((t) => t.stop())
  }, [])

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data) }
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        setState('busy')
        try {
          const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
          const text = await dictate(blob)
          if (text) onText(text)
          else toast.info('Ничего не разобрал — попробуйте ещё раз')
        } catch (e) {
          toast.error((e as Error).message)
        } finally {
          setState('idle')
        }
      }
      rec.start()
      recRef.current = rec
      setState('rec')
    } catch {
      // Отказ в доступе к микрофону — обычное дело, не ошибка приложения.
      toast.error('Микрофон недоступен: разрешите доступ в браузере')
    }
  }

  const stop = () => recRef.current?.stop()

  return { state, start, stop }
}

export function DictateButton({ onText, disabled, title = 'Продиктовать' }: {
  onText: (text: string) => void
  disabled?: boolean
  title?: string
}) {
  const { state, start, stop } = useDictation(onText)

  return (
    <Button
      size="icon"
      variant={state === 'rec' ? 'default' : 'outline'}
      disabled={disabled || state === 'busy'}
      onClick={() => (state === 'rec' ? stop() : start())}
      title={state === 'rec' ? 'Остановить и распознать' : title}
      className={cn(state === 'rec' && 'animate-pulse')}
    >
      {state === 'busy' ? <Loader2 className="size-4 animate-spin" />
        : state === 'rec' ? <Square className="size-4" />
          : <Mic className="size-4" />}
    </Button>
  )
}
