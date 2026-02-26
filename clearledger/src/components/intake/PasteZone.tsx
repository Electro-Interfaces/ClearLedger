/**
 * PasteZone — textarea для вставки текста (email, чат, произвольный текст).
 */

import { useState } from 'react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { ClipboardPaste, Send } from 'lucide-react'

interface PasteZoneProps {
  onPaste: (text: string) => void
  disabled?: boolean
}

export function PasteZone({ onPaste, disabled }: PasteZoneProps) {
  const [text, setText] = useState('')

  const handleSubmit = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onPaste(trimmed)
    setText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <ClipboardPaste className="size-4" />
        <span>Вставьте текст — email, сообщение из чата, произвольный текст</span>
      </div>

      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Вставьте текст сюда... (Ctrl+Enter для отправки)"
        className="min-h-[120px] resize-y font-mono text-sm"
        disabled={disabled}
      />

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {text.length > 0 ? `${text.length} символов` : 'Email, WhatsApp, Telegram, произвольный текст'}
        </p>
        <Button
          size="sm"
          onClick={handleSubmit}
          disabled={!text.trim() || disabled}
        >
          <Send className="size-4 mr-1" />
          Обработать
        </Button>
      </div>
    </div>
  )
}
