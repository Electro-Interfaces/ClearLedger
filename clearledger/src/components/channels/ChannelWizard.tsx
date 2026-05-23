import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { ChannelWizardStep1 } from './ChannelWizardStep1'
import { ChannelWizardStep2 } from './ChannelWizardStep2'
import { ChannelWizardStep3 } from './ChannelWizardStep3'
import { createSource } from '@/services/sourceService'
import { createChannel } from '@/services/channelService'
import { toast } from 'sonner'
import type { ChannelTemplate, ScheduleConfig } from '@/types/channel'
import { DEFAULT_SCHEDULE } from '@/types/channel'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ChannelWizard({ open, onOpenChange }: Props) {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [selectedTemplate, setSelectedTemplate] = useState<ChannelTemplate | null>(null)
  const [channelName, setChannelName] = useState('')
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [schedule, setSchedule] = useState<ScheduleConfig>({ ...DEFAULT_SCHEDULE })

  function reset() {
    setStep(1)
    setSelectedTemplate(null)
    setChannelName('')
    setFieldValues({})
    setSchedule({ ...DEFAULT_SCHEDULE })
  }

  function handleTemplateSelect(template: ChannelTemplate) {
    setSelectedTemplate(template)
    setChannelName(template.name)
    setSchedule(template.defaultSchedule)
    // Pre-fill default values from template
    const defaults: Record<string, string> = { ...template.defaultConnection }
    for (const field of template.setupFields) {
      if (field.defaultValue && !defaults[field.key]) {
        defaults[field.key] = field.defaultValue
      }
    }
    setFieldValues(defaults)
  }

  function handleFieldChange(key: string, value: string) {
    setFieldValues((prev) => ({ ...prev, [key]: value }))
  }

  const canNext = useCallback(() => {
    if (step === 1) return selectedTemplate !== null
    if (step === 2) {
      if (!channelName.trim()) return false
      if (!selectedTemplate) return false
      for (const field of selectedTemplate.setupFields) {
        if (field.required && !fieldValues[field.key]?.trim()) return false
      }
      return true
    }
    return true
  }, [step, selectedTemplate, channelName, fieldValues])

  async function handleCreate() {
    if (!selectedTemplate) return

    try {
      // 1. Create source from connection values
      const source = createSource({
        name: `${selectedTemplate.name} — Источник`,
        type: selectedTemplate.sourceType,
        connection: { ...selectedTemplate.defaultConnection, ...fieldValues },
      })

      // 2. Parse station codes from tags field
      const stationCodes: number[] = []
      if (fieldValues.stationCodes) {
        for (const code of fieldValues.stationCodes.split(',')) {
          const num = Number(code.trim())
          if (num > 0) stationCodes.push(num)
        }
      }

      // 3. Create channel
      const channel = createChannel({
        name: channelName,
        sourceIds: [source.id],
        templateId: selectedTemplate.id,
        schedule,
        config: { stationCodes },
      })

      toast.success(`Обработка "${channelName}" создана`)
      onOpenChange(false)
      reset()
      navigate(`/channels/${channel.id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Ошибка создания обработки')
    }
  }

  const STEPS = [
    { num: 1, label: 'Шаблон' },
    { num: 2, label: 'Настройка' },
    { num: 3, label: 'Расписание' },
  ]

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v) }}>
      <DialogContent className="max-w-[650px] max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Новая обработка</DialogTitle>
          {/* Step indicator */}
          <div className="flex items-center gap-2 pt-2">
            {STEPS.map((s, i) => (
              <div key={s.num} className="flex items-center gap-2">
                {i > 0 && <div className={`h-px w-6 ${step >= s.num ? 'bg-primary' : 'bg-border'}`} />}
                <div className={`flex items-center gap-1.5 text-xs ${
                  step === s.num ? 'text-primary font-semibold' : step > s.num ? 'text-muted-foreground' : 'text-muted-foreground/50'
                }`}>
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                    step >= s.num ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                  }`}>{s.num}</span>
                  {s.label}
                </div>
              </div>
            ))}
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto min-h-0 py-4">
          {step === 1 && (
            <ChannelWizardStep1
              selectedId={selectedTemplate?.id ?? null}
              onSelect={handleTemplateSelect}
            />
          )}
          {step === 2 && selectedTemplate && (
            <ChannelWizardStep2
              template={selectedTemplate}
              channelName={channelName}
              onChannelNameChange={setChannelName}
              values={fieldValues}
              onValueChange={handleFieldChange}
            />
          )}
          {step === 3 && (
            <ChannelWizardStep3
              schedule={schedule}
              onScheduleChange={setSchedule}
              connectionValues={fieldValues}
            />
          )}
        </div>

        <DialogFooter className="flex justify-between">
          <div>
            {step > 1 && (
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                <ChevronLeft className="h-4 w-4 mr-1" /> Назад
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => { reset(); onOpenChange(false) }}>Отмена</Button>
            {step < 3 ? (
              <Button onClick={() => setStep(step + 1)} disabled={!canNext()}>
                Далее <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button onClick={handleCreate} disabled={!canNext()}>
                Создать обработку
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
