/**
 * «Мои кучки» — личная группировка работы: и своих записей, и чужих предметов.
 *
 * Кучка не метка и не проект. Метка живёт в общем справочнике компании и меняет
 * сам предмет: повесив её на чужой документ, человек поменял его для всех.
 * Кучка не трогает предмет ничем — в ней лежит ссылка, и видит её только
 * хозяин. Поэтому в неё можно положить документ, визу и чужое поручение, чего
 * не даёт почти ни один трекер.
 *
 * Кучка не представление. Представление отвечает «всё, что подходит под
 * условие», и пересобирается само; кучка отвечает «то, что я сюда положил», и
 * стоит, пока её не тронули. Оба нужны, и в навигации они рядом — значит
 * различие обязано читаться из подписи, иначе первый же человек заведёт кучку
 * вместо отбора.
 *
 * Кучка ЭКСКЛЮЗИВНА: предмет лежит в одной или ни в одной. Иначе доска по
 * кучкам перестаёт быть доской — карточка висит в трёх колонках, и перенос
 * становится загадкой «переместить или добавить».
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FolderOpen, Loader2, Pencil, Plus, Star, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import { PlacedList } from '@/components/docs/PlacedList'
import * as workService from '@/services/workService'
import { cn } from '@/lib/utils'

/** Отбор, который человек выбирает сверху. `list` — конкретная кучка. */
type Выбор = { kind: 'list'; id: string } | { kind: 'starred' } | { kind: 'loose' }

export function ListsPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const companyId = company?.id ?? ''
  const [выбор, setВыбор] = useState<Выбор>({ kind: 'starred' })
  const [новая, setНовая] = useState('')
  const [заводим, setЗаводим] = useState(false)
  const [переименование, setПереименование] = useState('')

  const q = useQuery({
    queryKey: ['personal-lists', companyId],
    queryFn: () => workService.myLists(companyId),
    enabled: !!companyId,
  })
  const lists = q.data?.lists ?? []
  const текущая = выбор.kind === 'list'
    ? lists.find((l) => l.id === выбор.id) ?? null : null

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['personal-lists', companyId] })
    void qc.invalidateQueries({ queryKey: ['placed', companyId] })
  }

  const create = useMutation({
    mutationFn: () => workService.createList(companyId, новая.trim()),
    onSuccess: (row) => {
      setНовая(''); setЗаводим(false); refresh()
      setВыбор({ kind: 'list', id: row.id })
    },
    onError: (e: Error) => toast.error(e.message || 'Кучка не завелась'),
  })

  const act = useMutation({
    mutationFn: ({ id, data }: {
      id: string; data: Parameters<typeof workService.listAction>[2]
    }) => workService.listAction(companyId, id, data),
    onSuccess: (_r, vars) => {
      setПереименование('')
      if (vars.data.delete) setВыбор({ kind: 'starred' })
      refresh()
    },
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  if (!companyId) return null

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-3xl flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <FolderOpen className="h-4.5 w-4.5 text-primary" />Мои кучки
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Своя группировка работы: сюда можно положить и свою запись, и чужой
          документ или поручение. Видите только вы, и на сам предмет это не
          влияет — срок и состояние остаются общими.
        </p>
      </header>

      {q.isError && (
        <QueryError message="Кучки не загрузились" onRetry={() => void q.refetch()} />
      )}

      <div className="flex flex-wrap items-center gap-1">
        <Чип активен={выбор.kind === 'starred'} onClick={() => setВыбор({ kind: 'starred' })}>
          <Star className="mr-1 h-3 w-3" />Важное
        </Чип>
        {lists.map((l) => (
          <Чип key={l.id} активен={выбор.kind === 'list' && выбор.id === l.id}
            onClick={() => setВыбор({ kind: 'list', id: l.id })}
            подпись={l.count ? String(l.count) : undefined}>
            {l.name}
          </Чип>
        ))}
        <Чип активен={выбор.kind === 'loose'} onClick={() => setВыбор({ kind: 'loose' })}>
          Не разложено
        </Чип>
        {заводим ? (
          <span className="inline-flex items-center gap-1">
            <Input value={новая} autoFocus placeholder="Название кучки"
              onChange={(e) => setНовая(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && новая.trim()) create.mutate()
                if (e.key === 'Escape') { setЗаводим(false); setНовая('') }
              }}
              className="h-7 w-[170px] text-xs" />
            <Button size="sm" className="h-7 px-2 text-xs"
              disabled={!новая.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Завести'}
            </Button>
            <Button size="sm" variant="ghost" className="h-7 px-2"
              onClick={() => { setЗаводим(false); setНовая('') }}>
              <X className="h-3 w-3" />
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
            onClick={() => setЗаводим(true)}>
            <Plus className="mr-1 h-3 w-3" />Новая кучка
          </Button>
        )}
      </div>

      {текущая && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
          {переименование ? (
            <span className="inline-flex items-center gap-1">
              <Input value={переименование} autoFocus className="h-7 w-[170px] text-xs"
                onChange={(e) => setПереименование(e.target.value)} />
              <Button size="sm" className="h-7 px-2 text-xs"
                onClick={() => act.mutate({
                  id: текущая.id, data: { name: переименование.trim() },
                })}>Готово</Button>
              <Button size="sm" variant="ghost" className="h-7 px-2"
                onClick={() => setПереименование('')}><X className="h-3 w-3" /></Button>
            </span>
          ) : (
            <button type="button" onClick={() => setПереименование(текущая.name)}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Pencil className="h-3 w-3" />Переименовать
            </button>
          )}
          {/* Обзор — механика, а не привычка: единственные списки, где «потом»
              не превращается в кладбище, — те, у которых обзор встроен. */}
          <button type="button"
            onClick={() => act.mutate({ id: текущая.id, data: { reviewed: true } })}
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <Check className="h-3 w-3" />Просмотрел
          </button>
          <button type="button"
            onClick={() => act.mutate({ id: текущая.id, data: { delete: true } })}
            title="Кучка исчезнет, работа останется: предметы вернутся в «Не разложено»"
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-red-600 dark:hover:text-red-400">
            <Trash2 className="h-3 w-3" />Удалить кучку
          </button>
          {текущая.stale_days !== null && текущая.stale_days > 13 && (
            <span className="text-amber-600 dark:text-amber-400">
              не открывали {текущая.stale_days} дн.
            </span>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {выбор.kind === 'list' ? (
          <PlacedList companyId={companyId} scope="list" listId={выбор.id}
            onChanged={refresh}
            empty="В этой кучке пусто. Кладут сюда из строки работы — в очереди, в реестре или в «Сегодня»." />
        ) : выбор.kind === 'starred' ? (
          <PlacedList companyId={companyId} scope="starred" onChanged={refresh}
            empty="Ничего не помечено важным. Важность личная: приоритет предмета ставит постановщик, а звезда — вы." />
        ) : (
          <PlacedList companyId={companyId} scope="loose" onChanged={refresh}
            empty="Всё, что вы трогали, разложено по кучкам." />
        )}
      </div>
    </div>
  )
}

function Чип({ активен, подпись, onClick, children }: {
  активен: boolean; подпись?: string; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={активен}
      className={cn('inline-flex items-center rounded-md px-2.5 py-1 text-xs transition-colors',
        активен ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
      {children}
      {подпись && <span className="ml-1.5 tabular-nums opacity-70">{подпись}</span>}
    </button>
  )
}

export default ListsPage
