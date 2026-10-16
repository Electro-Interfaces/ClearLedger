/**
 * Часы по дням недели — одна форма для часов приёма (правила) и часов работы
 * операторов (паспорт): обе в формате узла `{ days: "mon-fri", from, to, tz }`.
 */
import { Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { ДНИ, дниВ, дниИз, type Часы } from './reception'

export function HoursEditor({ часы, onChange, пусто }: {
  часы: Часы[]
  onChange: (v: Часы[]) => void
  /** что значит пустой список */
  пусто: string
}) {
  const править = (i: number, h: Часы) => onChange(часы.map((x, n) => (n === i ? h : x)))
  return (
    <div className="w-full space-y-2">
      {!часы.length && <p className="text-sm text-muted-foreground">{пусто}</p>}
      {часы.map((h, i) => {
        const дни = дниИз(h.days)
        return (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2">
            <div className="flex gap-0.5" role="group" aria-label="Дни недели">
              {ДНИ.map((д, n) => {
                const вкл = дни.has(n)
                return (
                  <button key={д.code} type="button" aria-pressed={вкл}
                    onClick={() => {
                      const next = new Set(дни)
                      if (вкл) next.delete(n); else next.add(n)
                      if (next.size) править(i, { ...h, days: дниВ(next) })
                    }}
                    className={cn('min-h-8 w-9 rounded-md border text-xs transition-colors',
                      вкл ? 'border-primary bg-primary/10 font-medium text-primary' : 'border-border text-muted-foreground hover:bg-accent/50')}>
                    {д.name}
                  </button>
                )
              })}
            </div>
            <Input value={h.from ?? ''} placeholder="00:00" aria-label="С" inputMode="numeric"
              onChange={e => править(i, { ...h, from: e.target.value || undefined })} className="h-9 w-20 font-mono" />
            <span className="text-muted-foreground">–</span>
            <Input value={h.to ?? ''} placeholder="24:00" aria-label="До" inputMode="numeric"
              onChange={e => править(i, { ...h, to: e.target.value || undefined })} className="h-9 w-20 font-mono" />
            {h.tz && h.tz !== 'Europe/Moscow' && <span className="text-xs text-muted-foreground">{h.tz}</span>}
            <Button variant="ghost" size="icon-xs" aria-label="Убрать часы" title="Убрать часы"
              onClick={() => onChange(часы.filter((_, n) => n !== i))}><X /></Button>
          </div>
        )
      })}
      <Button variant="outline" size="xs" onClick={() => onChange([...часы, { days: 'mon-fri', from: '09:00', to: '18:00' }])}>
        <Plus />Добавить часы
      </Button>
      <p className="text-xs text-muted-foreground">
        Время московское. Ночная смена через полночь — двумя строками: «Пт 20:00–24:00» и «Сб 00:00–08:00».
      </p>
    </div>
  )
}
