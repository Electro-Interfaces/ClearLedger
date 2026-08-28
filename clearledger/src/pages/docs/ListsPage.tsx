/**
 * Личная раскладка: подборка, «Важное», «Отложено».
 *
 * Подборка не метка и не проект. Метка живёт в общем справочнике компании и меняет
 * сам предмет: повесив её на чужой документ, человек поменял его для всех.
 * Подборка не трогает предмет ничем — в ней лежит ссылка, и видит её только
 * хозяин. Поэтому в неё можно положить документ, визу и чужое поручение, чего
 * не даёт почти ни один трекер.
 *
 * Подборка не представление. Представление отвечает «всё, что подходит под
 * условие», и пересобирается само; подборка — «то, что я сюда положил», и стоит,
 * пока её не тронули. Оба нужны, и в навигации они рядом — значит различие
 * обязано читаться из подписи.
 *
 * Подборка ЭКСКЛЮЗИВНА: предмет лежит в одной или ни в одной. Иначе доска по
 * подборкам перестаёт быть доской — карточка висит в трёх колонках, и перенос
 * становится загадкой «переместить или добавить».
 *
 * Сами подборки стоят пунктами раздела, а не вкладками внутри этого экрана: личная
 * группировка не должна лежать на уровень глубже, чем работа компании.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  Check, EyeOff, FolderOpen, Loader2, MoreHorizontal, Pencil, Plus, Star,
  Trash2, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { QueryError } from '@/components/common/QueryError'
import { useCompany } from '@/contexts/CompanyContext'
import { PlacedList } from '@/components/docs/PlacedList'
import * as workService from '@/services/workService'

/** Что показываем: свои подборки, помеченное важным или спрятанное до даты. */
export type ListsMode = 'lists' | 'starred' | 'deferred'

const ЗАГОЛОВКИ: Record<ListsMode, { title: string; hint: string }> = {
  lists: {
    title: 'Подборки',
    hint: 'Своя группировка работы: сюда кладут и свою запись, и чужой документ '
      + 'или поручение. Видите только вы, и на сам предмет это не влияет — срок '
      + 'и состояние остаются общими.',
  },
  starred: {
    title: 'Важное',
    hint: 'Помеченное лично вами. Важность личная и приоритет предмета не '
      + 'меняет: приоритет ставит постановщик, и поднять его у чужой визы никто '
      + 'не вправе.',
  },
  deferred: {
    title: 'Отложено',
    hint: 'Спрятано только у вас и до названной даты. Срок компании шёл всё это '
      + 'время и не менялся; просроченное спрятать нельзя вовсе.',
  },
}

export function ListsPage({ mode = 'lists' }: { mode?: ListsMode }) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const companyId = company?.id ?? ''
  const [новая, setНовая] = useState('')
  const [заводим, setЗаводим] = useState(false)
  const [переименование, setПереименование] = useState('')
  const [правим, setПравим] = useState<string | null>(null)
  const [имя, setИмя] = useState('')

  const q = useQuery({
    queryKey: ['personal-lists', companyId],
    queryFn: () => workService.myLists(companyId),
    enabled: !!companyId,
  })
  const lists = q.data?.lists ?? []
  const выбрана = mode === 'lists' ? params.get('list') : null
  const текущая = lists.find((l) => l.id === выбрана) ?? null

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['personal-lists', companyId] })
    void qc.invalidateQueries({ queryKey: ['placed', companyId] })
  }
  const открыть = (id: string | null) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', 'lists')
    if (id) n.set('list', id)
    else n.delete('list')
    return n
  }, { replace: true })

  const create = useMutation({
    mutationFn: () => workService.createList(companyId, новая.trim()),
    onSuccess: (row) => { setНовая(''); setЗаводим(false); refresh(); открыть(row.id) },
    onError: (e: Error) => toast.error(e.message || 'Подборка не завелась'),
  })

  const act = useMutation({
    mutationFn: ({ id, data }: {
      id: string; data: Parameters<typeof workService.listAction>[2]
    }) => workService.listAction(companyId, id, data),
    onSuccess: (_r, vars) => {
      setПереименование('')
      if (vars.data.delete) открыть(null)
      refresh()
    },
    onError: (e: Error) => toast.error(e.message || 'Не получилось'),
  })

  if (!companyId) return null

  const шапка = текущая
    ? { title: текущая.name, hint: ЗАГОЛОВКИ.lists.hint }
    : ЗАГОЛОВКИ[mode]
  const Значок = mode === 'starred' ? Star : mode === 'deferred' ? EyeOff : FolderOpen

  return (
    <div className="flex h-full min-h-0 w-full max-w-5xl flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Значок className="h-4.5 w-4.5 text-primary" />{шапка.title}
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">{шапка.hint}</p>
      </header>

      {q.isError && (
        <QueryError message="Подборки не загрузились" onRetry={() => void q.refetch()} />
      )}

      {/* Действия над выбранной подборкой. Обзор здесь же: единственные личные
          списки, где «потом» не превращается в кладбище, — те, у которых он
          встроен в продукт, а не оставлен привычке. */}
      {текущая && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
          {переименование ? (
            <span className="inline-flex items-center gap-1">
              <Input value={переименование} autoFocus className="h-8 w-[170px] text-xs"
                onChange={(e) => setПереименование(e.target.value)} />
              <Button size="sm" className="h-8 px-2 text-xs"
                onClick={() => act.mutate({
                  id: текущая.id, data: { name: переименование.trim() },
                })}>Готово</Button>
              <Button size="sm" variant="ghost" className="h-8 px-2"
                onClick={() => setПереименование('')}><X className="h-3 w-3" /></Button>
            </span>
          ) : (
            <button type="button" onClick={() => setПереименование(текущая.name)}
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Pencil className="h-3 w-3" />Переименовать
            </button>
          )}
          <button type="button"
            onClick={() => act.mutate({ id: текущая.id, data: { reviewed: true } })}
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <Check className="h-3 w-3" />Просмотрел
          </button>
          <button type="button"
            onClick={() => act.mutate({ id: текущая.id, data: { delete: true } })}
            title="Подборка исчезнет, работа останется: предметы вернутся в «Не разложено»"
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-red-600 dark:hover:text-red-400">
            <Trash2 className="h-3 w-3" />Удалить подборку
          </button>
          {текущая.stale_days !== null && текущая.stale_days > 13 && (
            <span className="text-amber-600 dark:text-amber-400">
              не открывали {текущая.stale_days} дн.
            </span>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {mode === 'starred' ? (
          <PlacedList companyId={companyId} scope="starred" onChanged={refresh}
            empty="Ничего не помечено важным. Звезда личная: приоритет предмета ставит постановщик, а важность для себя — вы." />
        ) : mode === 'deferred' ? (
          <PlacedList companyId={companyId} scope="deferred" onChanged={refresh}
            empty="Ничего не отложено." />
        ) : текущая ? (
          <PlacedList companyId={companyId} scope="list" listId={текущая.id}
            onChanged={refresh}
            empty="В этой подборке пусто. Кладут сюда из строки работы — в очереди, в реестре или в «Сегодня»." />
        ) : (
          <Обзор lists={lists} loading={q.isLoading} companyId={companyId}
            onOpen={открыть} onChanged={refresh}
            заводим={заводим} setЗаводим={setЗаводим}
            новая={новая} setНовая={setНовая}
            create={() => create.mutate()} creating={create.isPending}
            правим={правим} setПравим={setПравим} имя={имя} setИмя={setИмя}
            act={(id, data) => act.mutate({ id, data })} />
        )}
      </div>
    </div>
  )
}

/** Список подборок, когда ни одна не выбрана: завести новую и посмотреть, что
 *  вообще не разложено. */
function Обзор({
  lists, loading, companyId, onOpen, onChanged, заводим, setЗаводим, новая,
  setНовая, create, creating, правим, setПравим, имя, setИмя, act,
}: {
  lists: workService.PersonalListRow[]
  loading: boolean
  companyId: string
  onOpen: (id: string) => void
  onChanged: () => void
  заводим: boolean
  setЗаводим: (v: boolean) => void
  новая: string
  setНовая: (v: string) => void
  create: () => void
  creating: boolean
  правим: string | null
  setПравим: (v: string | null) => void
  имя: string
  setИмя: (v: string) => void
  act: (id: string, data: Parameters<typeof workService.listAction>[2]) => void
}) {
  return (
    <div className="space-y-4">
      <div>
        {заводим ? (
          <div className="flex items-center gap-1.5">
            <Input value={новая} autoFocus placeholder="Название подборки"
              onChange={(e) => setНовая(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && новая.trim()) create()
                if (e.key === 'Escape') { setЗаводим(false); setНовая('') }
              }}
              className="h-8 w-[220px] text-sm" />
            <Button size="sm" className="h-8 px-3 text-xs"
              disabled={!новая.trim() || creating} onClick={create}>
              {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Завести'}
            </Button>
            <Button size="sm" variant="ghost" className="h-8 px-2"
              onClick={() => { setЗаводим(false); setНовая('') }}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" className="h-8 px-3 text-xs"
            onClick={() => setЗаводим(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />Новая подборка
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 px-1 py-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Смотрим подборки…
        </div>
      ) : lists.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          {lists.map((l) => (
            <div key={l.id}
              className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0 hover:bg-muted/40">
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              {правим === l.id ? (
                <span className="flex flex-1 items-center gap-1.5">
                  <Input value={имя} autoFocus className="h-8 max-w-[240px] text-sm"
                    onChange={(e) => setИмя(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && имя.trim()) {
                        act(l.id, { name: имя.trim() })
                        setПравим(null)
                      }
                      if (e.key === 'Escape') setПравим(null)
                    }} />
                  <Button size="sm" className="h-8 px-2 text-xs" disabled={!имя.trim()}
                    onClick={() => { act(l.id, { name: имя.trim() }); setПравим(null) }}>
                    Готово
                  </Button>
                  <Button size="sm" variant="ghost" className="h-8 px-2"
                    onClick={() => setПравим(null)}><X className="h-3 w-3" /></Button>
                </span>
              ) : (
                <button type="button" onClick={() => onOpen(l.id)}
                  className="flex-1 truncate text-left text-sm">
                  {l.name}
                </button>
              )}
              {l.stale_days !== null && l.stale_days > 13 && правим !== l.id && (
                <span className="shrink-0 text-xs text-amber-600 dark:text-amber-400">
                  не открывали {l.stale_days} дн.
                </span>
              )}
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {l.count}
              </span>
              {/* Правка там, где подборка лежит: заходить внутрь ради
                  переименования — лишний шаг, которого нет ни у кого. */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" variant="ghost" className="h-8 shrink-0 px-2"
                    title={`Что сделать с подборкой «${l.name}»`}>
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuItem onClick={() => { setИмя(l.name); setПравим(l.id) }}>
                    <Pencil className="mr-2 h-3.5 w-3.5" />Переименовать
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => act(l.id, { reviewed: true })}>
                    <Check className="mr-2 h-3.5 w-3.5" />Просмотрел
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => act(l.id, { delete: true })}>
                    <Trash2 className="mr-2 h-3.5 w-3.5" />
                    Удалить подборку
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}
        </div>
      ) : !заводим && (
        // Пустота ведёт за руку: рассказ о том, что кнопка где-то есть, — не
        // пустое состояние, а отговорка.
        <div className="rounded-lg border border-border px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            Подборок пока нет. В подборку кладут что угодно: свою запись, чужое
            поручение, документ на визе.
          </p>
          <Button size="sm" className="mt-3 h-8 px-3 text-xs"
            onClick={() => setЗаводим(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />Завести первую
          </Button>
        </div>
      )}

      {lists.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Удаление подборки не трогает работу: предметы вернутся в «Не разложено».
        </p>
      )}

      <section>
        <h2 className="mb-1.5 text-sm font-medium text-foreground">Не разложено</h2>
        <p className="mb-1.5 text-xs text-muted-foreground">
          То, что вы уже трогали — брали в день или помечали, — но никуда не положили.
        </p>
        <PlacedList companyId={companyId} scope="loose" onChanged={onChanged}
          empty="Пусто: всё, что трогали, разложено." />
      </section>
    </div>
  )
}

export default ListsPage
