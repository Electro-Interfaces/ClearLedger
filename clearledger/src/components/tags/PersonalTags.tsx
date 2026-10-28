/**
 * Личные теги: хук, плашки и выбор тегов предмета.
 *
 * Видит их только хозяин (решение МАГа 28.10.2026), поэтому выбор подписан «видите
 * только вы»: иначе человек решит, что пометил встречу для всех участников.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, Tag } from 'lucide-react'
import { toast } from 'sonner'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { TAG_TONES, tagTone, type TagTone } from '@/lib/tagTones'
import * as tagsService from '@/services/tagsService'
import type { PersonalTag } from '@/services/tagsService'
import { usePersonalTags, type PersonalTagsData } from '@/hooks/usePersonalTags'

/** Теги строкой: точка цвета и имя — цвет не единственный носитель. */
export function TagChips({ tags, className }: { tags: PersonalTag[]; className?: string }) {
  if (!tags.length) return null
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      {tags.map((t) => (
        <span key={t.id} className={cn('inline-flex items-center gap-1 rounded border px-1.5 text-xs leading-5 text-foreground', tagTone(t.color).chip)}>
          <span aria-hidden className={cn('size-2 shrink-0 rounded-full', tagTone(t.color).dot)} />
          {t.name}
        </span>
      ))}
    </span>
  )
}

/** Выбор цвета: восемь тонов палитры, у каждого имя для экранного чтения. */
export function TonePicker({ value, onChange }: { value: TagTone; onChange: (t: TagTone) => void }) {
  return (
    <div role="radiogroup" aria-label="Цвет тега" className="flex flex-wrap gap-1.5">
      {TAG_TONES.map((t) => (
        <button key={t.value} type="button" role="radio" aria-checked={value === t.value} aria-label={t.label}
          title={t.label} onClick={() => onChange(t.value)}
          className={cn('grid size-6 place-items-center rounded-full ring-offset-2 ring-offset-popover', t.dot,
            value === t.value && 'ring-2 ring-foreground')}>
          {value === t.value && <Check aria-hidden className="h-3.5 w-3.5 text-white" />}
        </button>
      ))}
    </div>
  )
}

export function TagPicker({ companyId, targetRef }: { companyId: string; targetRef: string }) {
  const qc = useQueryClient()
  const { tags, tagsOf } = usePersonalTags(companyId)
  const висят = tagsOf(targetRef)
  const [имя, setИмя] = useState('')
  const [тон, setТон] = useState<TagTone>('blue')
  const ключ = ['personal-tags', companyId]

  const повесить = useMutation({
    mutationFn: (ids: string[]) => tagsService.assignTags(companyId, targetRef, ids),
    // Сразу на экране: тег — движение руки, ждать сервера ради галочки незачем.
    onMutate: async (ids) => {
      await qc.cancelQueries({ queryKey: ключ })
      const было = qc.getQueryData<PersonalTagsData>(ключ)
      if (было) qc.setQueryData<PersonalTagsData>(ключ, { ...было, links: { ...было.links, [targetRef]: ids } })
      return { было }
    },
    onError: (e, _ids, ctx) => {
      if (ctx?.было) qc.setQueryData(ключ, ctx.было)
      toast.error((e as Error).message || 'Не удалось поставить тег')
    },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ключ }) },
  })
  const завести = useMutation({
    mutationFn: () => tagsService.createTag(companyId, имя.trim(), тон),
    onSuccess: (t) => {
      setИмя('')
      повесить.mutate([...висят.map((x) => x.id), t.id])
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось завести тег'),
  })
  const переключить = (id: string) => {
    const есть = висят.some((t) => t.id === id)
    повесить.mutate(есть ? висят.filter((t) => t.id !== id).map((t) => t.id) : [...висят.map((t) => t.id), id])
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="h-auto min-h-8 flex-wrap justify-start gap-1 py-1"
          aria-label={висят.length ? `Мои теги: ${висят.map((t) => t.name).join(', ')}` : 'Поставить мой тег'}>
          <Tag aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {висят.length ? <TagChips tags={висят} /> : <span>Мои теги</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 space-y-3 p-3">
        <div>
          <p className="text-sm font-medium">Мои теги</p>
          <p className="text-xs text-muted-foreground">Видите только вы: у остальных встреча и поручение не меняются.</p>
        </div>
        {tags.length > 0 && (
          <ul className="max-h-56 space-y-0.5 overflow-y-auto">
            {tags.map((t) => {
              const есть = висят.some((x) => x.id === t.id)
              return (
                <li key={t.id}>
                  <button type="button" aria-pressed={есть} onClick={() => переключить(t.id)}
                    className="flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-accent">
                    <span aria-hidden className={cn('size-2.5 shrink-0 rounded-full', tagTone(t.color).dot)} />
                    <span className="min-w-0 flex-1 truncate">{t.name}</span>
                    {есть && <Check aria-hidden className="h-4 w-4 text-primary" />}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <form className="space-y-2 border-t border-border pt-3"
          onSubmit={(e) => { e.preventDefault(); if (имя.trim()) завести.mutate() }}>
          <Input value={имя} onChange={(e) => setИмя(e.target.value)} maxLength={40}
            placeholder="Новый тег, например «Клиент Х»" aria-label="Имя нового тега" />
          <TonePicker value={тон} onChange={setТон} />
          <Button type="submit" size="sm" className="w-full" disabled={!имя.trim() || завести.isPending}>
            <Plus aria-hidden className="mr-1 h-4 w-4" />Завести и поставить
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  )
}

/** Мои теги в личных настройках: переименовать, перекрасить, удалить, завести. */
export function TagsManager({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { tags, links } = usePersonalTags(companyId)
  const [имя, setИмя] = useState('')
  const [тон, setТон] = useState<TagTone>('blue')
  const [удалить, setУдалить] = useState<string | null>(null)
  const обновить = () => qc.invalidateQueries({ queryKey: ['personal-tags', companyId] })
  const изменить = useMutation({
    mutationFn: (v: { id: string; name?: string; color?: TagTone; delete?: boolean }) =>
      tagsService.updateTag(companyId, v.id, v),
    onSuccess: () => { void обновить() },
    onError: (e) => { toast.error((e as Error).message || 'Не удалось изменить тег'); void обновить() },
  })
  const завести = useMutation({
    mutationFn: () => tagsService.createTag(companyId, имя.trim(), тон),
    onSuccess: () => { setИмя(''); void обновить() },
    onError: (e) => toast.error((e as Error).message || 'Не удалось завести тег'),
  })
  const сколько = (id: string) => Object.values(links).filter((ids) => ids.includes(id)).length

  return (
    <div className="space-y-3">
      {tags.length === 0 && <p className="text-xs text-muted-foreground">Тегов пока нет. Заведите здесь или прямо в карточке встречи и поручения.</p>}
      <ul className="space-y-2">
        {tags.map((t) => (
          <li key={t.id} className="space-y-1.5 rounded-lg border border-border p-2">
            <div className="flex items-center gap-2">
              <span aria-hidden className={cn('size-3 shrink-0 rounded-full', tagTone(t.color).dot)} />
              <Input defaultValue={t.name} maxLength={40} aria-label={`Имя тега ${t.name}`} className="h-8"
                onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== t.name) изменить.mutate({ id: t.id, name: v }) }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground" title="На скольких предметах стоит">{сколько(t.id)}</span>
              {удалить === t.id ? (
                <span className="flex shrink-0 items-center gap-1">
                  <Button size="xs" variant="destructive" onClick={() => { setУдалить(null); изменить.mutate({ id: t.id, delete: true }) }}>Удалить</Button>
                  <Button size="xs" variant="ghost" onClick={() => setУдалить(null)}>Нет</Button>
                </span>
              ) : (
                <Button size="xs" variant="ghost" onClick={() => setУдалить(t.id)}
                  aria-label={`Удалить тег ${t.name}`} title="Тег снимется со всех встреч и поручений, сами они не изменятся">Удалить</Button>
              )}
            </div>
            <TonePicker value={t.color} onChange={(c) => изменить.mutate({ id: t.id, color: c })} />
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (имя.trim()) завести.mutate() }}>
        <Input value={имя} onChange={(e) => setИмя(e.target.value)} maxLength={40} className="h-8 min-w-40 flex-1"
          placeholder="Новый тег" aria-label="Имя нового тега" />
        <TonePicker value={тон} onChange={setТон} />
        <Button type="submit" size="sm" disabled={!имя.trim() || завести.isPending}>
          <Plus aria-hidden className="mr-1 h-4 w-4" />Завести
        </Button>
      </form>
    </div>
  )
}
