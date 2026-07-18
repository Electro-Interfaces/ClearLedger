/**
 * Единый конструктор произвольного разреза (стандарт §5, §6.3) —
 * переиспользуемый строительный блок Слоя 2 «Эксперт»: условия
 * (поле · оператор · значение), объединённые И/ИЛИ, с ЖЁСТКИМ потолком числа
 * условий (ориентир Airtable — не давать строить нечитаемые деревья).
 *
 * Один компонент на все места, где нужен произвольный разрез (глобальный фильтр,
 * разрезы сверки, кастомные срезы дашборда), чтобы «конструктор разреза» выглядел
 * и вёл себя одинаково везде (§6.6 «один жест = один смысл»), а не тремя похожими.
 *
 * `resultCount` — живой результат (§6.3): число подходящих записей показывается
 * ДО применения, чтобы избежать «submit → 0 результатов».
 */
import { nanoid } from 'nanoid'
import { Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export type CutOperator = 'eq' | 'ne' | 'contains' | 'gt' | 'gte' | 'lt' | 'lte'
export type CutLogic = 'and' | 'or'

export interface CutCondition {
  id: string
  field: string
  op: CutOperator
  value: string
}

export interface CutQuery {
  logic: CutLogic
  conditions: CutCondition[]
}

const OPERATORS: { value: CutOperator; label: string }[] = [
  { value: 'eq', label: '=' },
  { value: 'ne', label: '≠' },
  { value: 'contains', label: 'содержит' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
]

export function emptyCutQuery(): CutQuery {
  return { logic: 'and', conditions: [] }
}

export function CutBuilder({
  fields,
  value,
  onChange,
  maxConditions = 10,
  resultCount,
}: {
  fields: { key: string; label: string }[]
  value: CutQuery
  onChange: (q: CutQuery) => void
  maxConditions?: number
  resultCount?: number
}) {
  const atLimit = value.conditions.length >= maxConditions

  function addCondition() {
    if (atLimit) return
    onChange({
      ...value,
      conditions: [
        ...value.conditions,
        { id: nanoid(), field: fields[0]?.key ?? '', op: 'eq', value: '' },
      ],
    })
  }
  function updateCondition(id: string, patch: Partial<CutCondition>) {
    onChange({ ...value, conditions: value.conditions.map((c) => (c.id === id ? { ...c, ...patch } : c)) })
  }
  function removeCondition(id: string) {
    onChange({ ...value, conditions: value.conditions.filter((c) => c.id !== id) })
  }

  return (
    <div className="space-y-2">
      {value.conditions.length > 1 && (
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Объединять условия:</span>
          <div className="inline-flex rounded-md border border-border/60 p-0.5">
            {(['and', 'or'] as CutLogic[]).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => onChange({ ...value, logic: l })}
                className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                  value.logic === l ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {l === 'and' ? 'И (все)' : 'ИЛИ (любое)'}
              </button>
            ))}
          </div>
        </div>
      )}

      {value.conditions.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Условий нет — разрез охватывает все записи. Добавьте условие, чтобы сузить.
        </p>
      )}

      {value.conditions.map((c) => (
        <div key={c.id} className="flex items-center gap-1.5">
          <Select value={c.field} onValueChange={(v) => updateCondition(c.id, { field: v })}>
            <SelectTrigger className="h-8 w-40 text-xs"><SelectValue placeholder="Поле" /></SelectTrigger>
            <SelectContent>
              {fields.map((f) => <SelectItem key={f.key} value={f.key} className="text-xs">{f.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={c.op} onValueChange={(v) => updateCondition(c.id, { op: v as CutOperator })}>
            <SelectTrigger className="h-8 w-28 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {OPERATORS.map((o) => <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input
            value={c.value}
            onChange={(e) => updateCondition(c.id, { value: e.target.value })}
            placeholder="Значение"
            className="h-8 flex-1 text-xs"
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-muted-foreground"
            onClick={() => removeCondition(c.id)}
            aria-label="Удалить условие"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}

      <div className="flex items-center justify-between gap-2 pt-1">
        <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={addCondition} disabled={atLimit}>
          <Plus className="h-3.5 w-3.5" /> Условие
        </Button>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {atLimit && <span className="text-amber-400/80">Достигнут потолок ({maxConditions})</span>}
          {resultCount !== undefined && (
            <span>Подходит записей: <span className="font-medium text-foreground">{resultCount}</span></span>
          )}
        </div>
      </div>
    </div>
  )
}
