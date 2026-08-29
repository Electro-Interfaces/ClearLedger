/**
 * «Витрина» — правка текстов и цен публичного сайта из пространства.
 *
 * Раньше витрина была кодом: чтобы поменять цену, нужен был программист и
 * пересборка. Теперь разделы лежат данными на сайте, и правит их здесь тот, кто
 * за них отвечает. Хозяин данных остался прежним — сайт: он публичен и должен
 * работать, даже когда пространство лежит.
 *
 * Редактор один на все разделы и строится по самим данным: у продукта свои поля,
 * у вопроса — свои, а формы под каждый раздел устарели бы в тот день, когда на
 * сайте появится шестой. Незнакомый раздел откроется сам собой.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import * as siteService from '@/services/siteService'
import { CONTENT_LABELS, FIELD_LABELS, siteTime } from '@/services/siteService'
import { cn } from '@/lib/utils'

type Json = unknown

/** Одно значение: поле подбирается по типу того, что в нём лежит. */
function ValueField({ value, onChange }: { value: Json; onChange: (v: Json) => void }) {
  if (typeof value === 'boolean') {
    return <Switch checked={value} onCheckedChange={onChange} />
  }
  if (typeof value === 'number') {
    return (
      <Input type="number" value={value}
             onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
    )
  }
  if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
    // Список строк — строкой на элемент: так его правят в любом текстовом поле,
    // и не нужно кнопок «добавить пункт» на каждый перечень.
    return (
      <Textarea
        rows={Math.min(8, Math.max(2, value.length))}
        value={(value as string[]).join('\n')}
        onChange={(e) => onChange(e.target.value.split('\n').filter((s) => s.trim() !== ''))}
      />
    )
  }
  if (Array.isArray(value)) return <ListEditor value={value} onChange={onChange} />
  if (value && typeof value === 'object') {
    return <ObjectEditor value={value as Record<string, Json>} onChange={onChange} />
  }
  const text = value === null || value === undefined ? '' : String(value)
  return text.length > 70 || text.includes('\n')
    ? <Textarea rows={3} value={text} onChange={(e) => onChange(e.target.value)} />
    : <Input value={text} onChange={(e) => onChange(e.target.value)} />
}

function ObjectEditor({ value, onChange }: {
  value: Record<string, Json>
  onChange: (v: Json) => void
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {Object.entries(value).map(([k, v]) => {
        const wide = (v !== null && typeof v === 'object')
          || (typeof v === 'string' && v.length > 70)
        return (
          <div key={k} className={cn(wide && 'sm:col-span-2')}>
            <label className="mb-1 block text-xs text-muted-foreground">{FIELD_LABELS[k] ?? k}</label>
            <ValueField value={v} onChange={(next) => onChange({ ...value, [k]: next })} />
          </div>
        )
      })}
    </div>
  )
}

/** Пустой бланк по образцу соседей: новую запись заводят с теми же полями. */
function blankLike(sample: Json): Json {
  if (Array.isArray(sample)) return []
  if (sample && typeof sample === 'object') {
    return Object.fromEntries(
      Object.entries(sample as Record<string, Json>).map(([k, v]) => [k, blankLike(v)]))
  }
  if (typeof sample === 'number') return 0
  if (typeof sample === 'boolean') return false
  return ''
}

function ListEditor({ value, onChange }: { value: Json[]; onChange: (v: Json) => void }) {
  const replace = (i: number, next: Json) =>
    onChange(value.map((v, j) => (j === i ? next : v)))
  return (
    <div className="space-y-3">
      {value.map((item, i) => (
        <div key={i} className="rounded-md border p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{i + 1}</span>
            <Button variant="ghost" size="sm"
                    onClick={() => onChange(value.filter((_, j) => j !== i))}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <ValueField value={item} onChange={(next) => replace(i, next)} />
        </div>
      ))}
      <Button variant="outline" size="sm"
              onClick={() => onChange([...value, blankLike(value[0] ?? '')])}>
        <Plus className="mr-1 h-3.5 w-3.5" /> Добавить
      </Button>
    </div>
  )
}

export function ShowcaseEditor({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const content = useQuery({
    queryKey: ['site-content', companyId],
    queryFn: () => siteService.getContent(companyId),
    enabled: !!companyId,
  })
  const [key, setKey] = useState<string>('')
  const [draft, setDraft] = useState<Json>(null)

  const keys = content.data?.keys ?? []
  const current = key || keys[0] || ''
  const saved = content.data?.values?.[current]

  // Черновик заводится от прочитанного и живёт, пока не сохранили: перерисовка
  // соседнего запроса не должна стирать набранный текст.
  useEffect(() => {
    setDraft(saved === undefined ? null : structuredClone(saved))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, content.dataUpdatedAt])

  const meta = useMemo(
    () => (content.data?.sections ?? []).find((s) => s.key === current),
    [content.data, current])

  const save = useMutation({
    mutationFn: () => siteService.saveContent(companyId, current, draft),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-content', companyId] })
      toast.success('Раздел сохранён — витрина обновилась')
    },
    onError: (e: Error) => toast.error(e.message || 'Правка не сохранена'),
  })

  const changed = JSON.stringify(draft) !== JSON.stringify(saved ?? null)

  if (content.isLoading) {
    return <p className="py-8 text-center text-muted-foreground">Читаю витрину…</p>
  }
  if (!content.data?.connected) {
    return <p className="py-8 text-center text-muted-foreground">Витрина не прочитана</p>
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[200px_1fr]">
      <nav className="space-y-1">
        {keys.map((k) => (
          <button
            key={k} type="button" onClick={() => setKey(k)}
            className={cn('w-full rounded-md px-3 py-2 text-left text-sm',
              k === current ? 'bg-muted font-medium' : 'hover:bg-muted/50')}
          >
            {CONTENT_LABELS[k] ?? k}
          </button>
        ))}
      </nav>

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            {meta?.updated_at
              ? `Правил: ${meta.updated_by || '—'}, ${siteTime(meta.updated_at)}`
              : 'Ещё не правили'}
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={!changed}
                    onClick={() => setDraft(structuredClone(saved ?? null))}>
              <RotateCcw className="mr-1 h-3.5 w-3.5" /> Вернуть
            </Button>
            <Button size="sm" disabled={!changed || save.isPending}
                    onClick={() => save.mutate()}>
              <Save className="mr-1 h-3.5 w-3.5" />
              {save.isPending ? 'Сохраняю…' : 'Сохранить'}
            </Button>
          </div>
        </div>

        {draft === null
          ? <p className="py-8 text-center text-muted-foreground">Раздел пуст</p>
          : <ValueField value={draft} onChange={setDraft} />}
      </div>
    </div>
  )
}
