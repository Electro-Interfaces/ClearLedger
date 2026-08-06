/**
 * «Пульс» → «Экран дня» → «Пороги»: с какого места считать, что пора вмешаться.
 *
 * Порог — это мнение о норме, и оно принадлежит компании, а не коду: 19%
 * пропущенных звонков одной сети катастрофа, другой — обычный вторник. Раньше
 * все пороги были зашиты в правилах, и спор «это плохо?» решал разработчик.
 *
 * Экран живёт рядом с тем, что регулирует: руководитель видит карточку на
 * экране дня и тут же правит порог, не уходя в «Управление».
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getPulseTargets, savePulseTargets, type PulseTarget } from './pulseService'
import { PulseError, PulseLoading } from './parts'

export function TargetsView() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['pulse-targets', company.id],
    queryFn: () => getPulseTargets(company.id),
  })
  // Черновик правок: сохраняем пачкой, а не по каждому нажатию клавиши —
  // иначе на каждую цифру уходил бы запрос и пересчёт экрана дня.
  const [draft, setDraft] = useState<Record<string, string>>({})
  useEffect(() => { setDraft({}) }, [q.data])

  const save = useMutation({
    mutationFn: (values: Record<string, number | null>) =>
      savePulseTargets(company.id, values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pulse-targets', company.id] })
      qc.invalidateQueries({ queryKey: ['pulse-day', company.id] })
      setDraft({})
      toast.success('Пороги сохранены — экран дня пересчитан')
    },
    onError: () => toast.error('Не удалось сохранить пороги — попробуйте ещё раз'),
  })

  if (q.isLoading) return <PulseLoading what="порогов" />
  if (q.isError) return <PulseError what="пороги эскалаций" onRetry={() => q.refetch()} />

  const items = q.data?.items ?? []
  const sections = [...new Set(items.map((i) => i.section))]
  const dirty = Object.keys(draft).length > 0

  const submit = () => {
    const values: Record<string, number | null> = {}
    for (const [key, raw] of Object.entries(draft)) {
      const n = Number(String(raw).replace(',', '.'))
      values[key] = raw.trim() === '' || Number.isNaN(n) ? null : n
    }
    save.mutate(values)
  }

  const row = (t: PulseTarget) => {
    const value = draft[t.key] ?? String(t.value)
    const changed = draft[t.key] !== undefined
    return (
      <div key={t.key} className="flex items-start gap-3 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="text-[13px]">{t.label}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">{t.hint}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Input value={value} inputMode="decimal"
            aria-label={t.label}
            onChange={(e) => setDraft((d) => ({ ...d, [t.key]: e.target.value }))}
            className={cn('h-9 w-24 text-right tabular-nums sm:h-8',
              changed && 'border-primary/50')} />
          <span className="w-6 text-[11px] text-muted-foreground">{t.unit}</span>
          {/* Возврат к предложенному — отдельным действием: иначе «как было»
              приходилось помнить наизусть. */}
          <Button variant="ghost" size="sm" className="h-9 w-9 p-0 sm:h-8 sm:w-8"
            title={`Вернуть предложенное: ${t.default} ${t.unit}`}
            aria-label={`Вернуть предложенное значение для «${t.label}»`}
            disabled={!t.is_custom && !changed}
            onClick={() => setDraft((d) => ({ ...d, [t.key]: '' }))}>
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <p className="max-w-2xl text-xs text-muted-foreground">
          Экран дня молчит, пока показатель не перешагнул порог. Значения ниже —
          предложенные; меняйте под свою сеть. Пустое поле возвращает предложенное.
        </p>
        <Button size="sm" className="h-9 shrink-0 sm:h-8" disabled={!dirty || save.isPending}
          onClick={submit}>
          Сохранить
        </Button>
      </div>

      {sections.map((section) => (
        <section key={section} className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/60">
            {section}
          </h2>
          <Card className="py-0">
            <CardContent className="divide-y divide-border/40 p-0">
              {items.filter((i) => i.section === section).map(row)}
            </CardContent>
          </Card>
        </section>
      ))}
    </div>
  )
}
