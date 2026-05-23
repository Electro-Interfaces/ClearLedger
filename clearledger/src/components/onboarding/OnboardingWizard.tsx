/**
 * OnboardingWizard — пошаговый диалог для первого знакомства с ClearLedger.
 *
 * 4 шага: Приветствие → Компания → Первый документ → Готово.
 * Состояние завершения хранится в localStorage.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import {
  Rocket,
  Building2,
  Upload,
  PartyPopper,
  ArrowRight,
  ArrowLeft,
  ChevronRight,
  Inbox,
  BookOpen,
  BarChart3,
  FileText,
  Plug,
} from 'lucide-react'
import { getItem, setItem } from '@/services/storage'
import { cn } from '@/lib/utils'

const ONBOARDING_KEY = 'clearledger-onboarding-done'

export function isOnboardingDone(): boolean {
  return getItem<boolean>(ONBOARDING_KEY, false)
}

export function markOnboardingDone(): void {
  setItem(ONBOARDING_KEY, true)
}

export function resetOnboarding(): void {
  setItem(ONBOARDING_KEY, false)
}

// ---- Steps ----

interface StepProps {
  onNext: () => void
  onPrev?: () => void
  onSkip: () => void
}

function WelcomeStep({ onNext, onSkip }: StepProps) {
  return (
    <>
      <DialogHeader>
        <div className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center bg-primary/10 mb-4">
          <Rocket className="size-8 text-primary" />
        </div>
        <DialogTitle className="text-center text-xl">Добро пожаловать в ClearLedger</DialogTitle>
        <DialogDescription className="text-center">
          Система приёма, классификации и верификации документов для бизнеса.
          Давайте настроим платформу за пару минут.
        </DialogDescription>
      </DialogHeader>

      <div className="grid grid-cols-2 gap-3 my-4">
        {[
          { icon: Upload, title: 'Загрузка', desc: 'PDF, Excel, XML, фото' },
          { icon: FileText, title: 'Классификация', desc: 'Автоматическая по правилам' },
          { icon: Inbox, title: 'Верификация', desc: 'Проверка и подтверждение' },
          { icon: BarChart3, title: 'Аналитика', desc: 'Отчёты и дашборд' },
        ].map(({ icon: Icon, title, desc }) => (
          <div key={title} className="flex items-start gap-2.5 p-3 rounded-lg bg-muted/50">
            <Icon className="size-4 text-primary mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium leading-tight">{title}</p>
              <p className="text-xs text-muted-foreground">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      <DialogFooter className="sm:justify-between">
        <Button variant="ghost" size="sm" onClick={onSkip}>Пропустить</Button>
        <Button onClick={onNext} className="gap-1">
          Начать <ArrowRight className="size-4" />
        </Button>
      </DialogFooter>
    </>
  )
}

function CompanyStep({ onNext, onPrev, onSkip }: StepProps) {
  const { company, companies, setCompanyId } = useCompany()

  return (
    <>
      <DialogHeader>
        <div className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center bg-blue-500/10 mb-4">
          <Building2 className="size-8 text-blue-500" />
        </div>
        <DialogTitle className="text-center text-xl">Выберите компанию</DialogTitle>
        <DialogDescription className="text-center">
          ClearLedger поддерживает мультикомпанейность. Выберите основную компанию для работы.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-2 my-4">
        {companies.map((c) => (
          <button
            key={c.id}
            className={cn(
              'w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left',
              c.id === company.id
                ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
                : 'border-border hover:bg-muted/50',
            )}
            onClick={() => setCompanyId(c.id)}
          >
            <div className={cn(
              'w-10 h-10 rounded-lg flex items-center justify-center shrink-0 text-sm font-bold',
              c.id === company.id ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
            )}>
              {c.name.slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{c.name}</p>
              <p className="text-xs text-muted-foreground">{c.inn || c.id}</p>
            </div>
            {c.id === company.id && (
              <div className="size-5 rounded-full bg-primary flex items-center justify-center shrink-0">
                <svg className="size-3 text-primary-foreground" viewBox="0 0 12 12" fill="none">
                  <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            )}
          </button>
        ))}
      </div>

      <DialogFooter className="sm:justify-between">
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onPrev}><ArrowLeft className="size-4" /></Button>
          <Button variant="ghost" size="sm" onClick={onSkip}>Пропустить</Button>
        </div>
        <Button onClick={onNext} className="gap-1">
          Далее <ArrowRight className="size-4" />
        </Button>
      </DialogFooter>
    </>
  )
}

function UploadStep({ onNext, onPrev, onSkip }: StepProps) {
  const navigate = useNavigate()

  return (
    <>
      <DialogHeader>
        <div className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center bg-green-500/10 mb-4">
          <Upload className="size-8 text-green-500" />
        </div>
        <DialogTitle className="text-center text-xl">Загрузите первый документ</DialogTitle>
        <DialogDescription className="text-center">
          Перетащите файл или выберите из каталога. Поддерживаются PDF, Excel, XML, фото и другие форматы.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-3 my-4">
        <button
          className="w-full flex items-center gap-3 p-4 rounded-lg border border-dashed border-primary/40 bg-primary/5 hover:bg-primary/10 transition-colors text-left"
          onClick={() => { markOnboardingDone(); navigate('/input') }}
        >
          <Upload className="size-5 text-primary shrink-0" />
          <div>
            <p className="text-sm font-medium">Загрузить документы</p>
            <p className="text-xs text-muted-foreground">Откроется страница приёма</p>
          </div>
          <ChevronRight className="size-4 text-muted-foreground ml-auto" />
        </button>

        <button
          className="w-full flex items-center gap-3 p-4 rounded-lg border hover:bg-muted/50 transition-colors text-left"
          onClick={() => { markOnboardingDone(); navigate('/connectors') }}
        >
          <Plug className="size-5 text-muted-foreground shrink-0" />
          <div>
            <p className="text-sm font-medium">Настроить коннектор</p>
            <p className="text-xs text-muted-foreground">1С, API, email — автоматический приём</p>
          </div>
          <ChevronRight className="size-4 text-muted-foreground ml-auto" />
        </button>

        <button
          className="w-full flex items-center gap-3 p-4 rounded-lg border hover:bg-muted/50 transition-colors text-left"
          onClick={() => { markOnboardingDone(); navigate('/references') }}
        >
          <BookOpen className="size-5 text-muted-foreground shrink-0" />
          <div>
            <p className="text-sm font-medium">Заполнить справочники</p>
            <p className="text-xs text-muted-foreground">Контрагенты, номенклатура, склады</p>
          </div>
          <ChevronRight className="size-4 text-muted-foreground ml-auto" />
        </button>
      </div>

      <DialogFooter className="sm:justify-between">
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={onPrev}><ArrowLeft className="size-4" /></Button>
          <Button variant="ghost" size="sm" onClick={onSkip}>Пропустить</Button>
        </div>
        <Button onClick={onNext} className="gap-1">
          Далее <ArrowRight className="size-4" />
        </Button>
      </DialogFooter>
    </>
  )
}

function DoneStep({ onSkip }: StepProps) {
  return (
    <>
      <DialogHeader>
        <div className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center bg-yellow-500/10 mb-4">
          <PartyPopper className="size-8 text-yellow-500" />
        </div>
        <DialogTitle className="text-center text-xl">Всё готово!</DialogTitle>
        <DialogDescription className="text-center">
          ClearLedger настроен. Вы можете начать работу с документами прямо сейчас.
        </DialogDescription>
      </DialogHeader>

      <div className="my-4 p-4 rounded-lg bg-muted/50 space-y-2.5">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Горячие клавиши</p>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="flex items-center gap-2">
            <kbd className="px-1.5 py-0.5 rounded bg-background border text-[11px] font-mono">Ctrl+K</kbd>
            <span className="text-muted-foreground">Поиск</span>
          </div>
          <div className="flex items-center gap-2">
            <kbd className="px-1.5 py-0.5 rounded bg-background border text-[11px] font-mono">?</kbd>
            <span className="text-muted-foreground">Справка</span>
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button onClick={onSkip} className="w-full gap-1">
          Начать работу <ArrowRight className="size-4" />
        </Button>
      </DialogFooter>
    </>
  )
}

// ---- Main Wizard ----

const STEPS = [WelcomeStep, CompanyStep, UploadStep, DoneStep] as const

export function OnboardingWizard({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [step, setStep] = useState(0)

  const handleClose = () => {
    markOnboardingDone()
    onOpenChange(false)
    setStep(0)
  }

  const CurrentStep = STEPS[step]

  return (
    <Dialog open={open} onOpenChange={(val) => { if (!val) handleClose() }}>
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        {/* Progress dots */}
        <div className="flex justify-center gap-1.5 mb-2">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={cn(
                'h-1.5 rounded-full transition-all duration-300',
                i === step ? 'w-6 bg-primary' : i < step ? 'w-1.5 bg-primary/40' : 'w-1.5 bg-muted',
              )}
            />
          ))}
        </div>

        <CurrentStep
          onNext={() => step < STEPS.length - 1 ? setStep(step + 1) : handleClose()}
          onPrev={step > 0 ? () => setStep(step - 1) : undefined}
          onSkip={handleClose}
        />
      </DialogContent>
    </Dialog>
  )
}
