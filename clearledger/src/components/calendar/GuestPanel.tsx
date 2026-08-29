/**
 * Внешние участники встречи и материалы, открытые им явно.
 *
 * Главное здесь — предпросмотр. Приглашение само по себе не открывает ничего, и
 * человек должен видеть ТОЧНЫЙ список того, что уйдёт наружу, до того как
 * нажмёт «позвать». Иначе состав встречи молча становится списком доступа: позвал
 * подрядчика обсудить договор — отдал ему договор.
 *
 * Каждый материал сохраняет собственные права: для документа заводится обычная
 * гостевая ссылка. Отзыв её не отменяет встречу, отмена встречи не отзывает её —
 * это разные решения, и связывать их значило бы отбирать доступ там, где никто
 * этого не просил.
 *
 * Токен приглашения виден один раз — в ответе на приглашение. Дальше он живёт
 * только у гостя, и «покажите ещё раз» отвечается новой ссылкой, а не старой.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Eye, FileText, Loader2, Trash2, UserPlus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SearchPicker } from '@/components/tasks/SearchPicker'
import * as workService from '@/services/workService'
import * as docsService from '@/services/docsService'
import { cn } from '@/lib/utils'

const ОТВЕТ_СЛОВОМ: Record<string, string> = {
  pending: 'не ответил', accepted: 'будет',
  declined: 'не будет', tentative: 'может быть',
}

export function GuestPanel({ companyId, eventId, title }: {
  companyId: string
  eventId: string
  title: string
}) {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [ссылка, setСсылка] = useState<{ email: string; url: string } | null>(null)

  const q = useQuery({
    queryKey: ['event-guests', companyId, eventId],
    queryFn: () => workService.eventGuests(companyId, eventId),
    enabled: !!eventId,
  })
  const обновить = () => qc.invalidateQueries({ queryKey: ['event-guests', companyId, eventId] })

  // Документы для выбора материала: только зарегистрированные — наружу уходит
  // номер, и черновик показывать нечем.
  const docsQ = useQuery({
    queryKey: ['docs-for-material', companyId],
    queryFn: () => docsService.listDocs(companyId, { limit: 100 }),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  const позвать = useMutation({
    mutationFn: () => workService.inviteGuest(companyId, eventId, {
      email: email.trim(), name: name.trim() || undefined,
    }),
    onSuccess: (r) => {
      setEmail(''); setName('')
      setСсылка({ email: r.email, url: `${window.location.origin}/invite/${r.token}` })
      void обновить()
    },
    onError: (e: Error) => toast.error(e.message || 'Не позвалось'),
  })

  const отозвать = useMutation({
    mutationFn: (id: string) => workService.revokeGuest(companyId, eventId, id),
    onSuccess: () => { toast.success('Приглашение отозвано'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не отозвалось'),
  })

  const открыть = useMutation({
    mutationFn: (docId: string) =>
      workService.openMaterial(companyId, eventId, `doc:${docId}`),
    onSuccess: () => { toast.success('Материал открыт гостям'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не открылось'),
  })

  const закрыть = useMutation({
    mutationFn: (id: string) => workService.closeMaterial(companyId, eventId, id),
    onSuccess: () => { toast.success('Материал закрыт, ссылка отозвана'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не закрылось'),
  })

  const гости = q.data?.guests ?? []
  const материалы = q.data?.materials ?? []

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Внешние участники
      </h3>

      {/* Предпросмотр: что именно увидит человек снаружи. Показываем ДО того,
          как позвали, а не после. */}
      <div className="rounded border border-dashed border-border bg-muted/30 p-2 text-xs">
        <p className="flex items-center gap-1.5 font-medium">
          <Eye className="h-3.5 w-3.5" />Гостю будут доступны
        </p>
        <ul className="mt-1 space-y-0.5 text-muted-foreground">
          <li>· название встречи: «{title}»</li>
          <li>· время и место, повестка и ссылка на видеовстречу</li>
          {материалы.map((m) => <li key={m.id}>· {m.title}</li>)}
          {материалы.length === 0 && <li>· материалы не открыты</li>}
        </ul>
        <p className="mt-1 text-muted-foreground/80">
          Состав встречи и календари сотрудников гостю не видны.
        </p>
      </div>

      {гости.length > 0 && (
        <ul className="space-y-1">
          {гости.map((g) => (
            <li key={g.id} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="min-w-[10rem] flex-1 truncate">
                {g.name || g.email}
              </span>
              <span className={cn('text-muted-foreground',
                g.response === 'accepted' && 'text-emerald-600 dark:text-emerald-400',
                g.response === 'declined' && 'text-muted-foreground line-through')}>
                {ОТВЕТ_СЛОВОМ[g.response] ?? g.response}
              </span>
              {g.proposed_starts_at && (
                <span className="text-amber-600 dark:text-amber-400">
                  предложил {new Date(g.proposed_starts_at).toLocaleString('ru-RU', {
                    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
                  })}
                </span>
              )}
              <Button size="sm" variant="ghost" className="h-7 px-1.5"
                title="Отозвать приглашение" disabled={отозвать.isPending}
                onClick={() => отозвать.mutate(g.id)}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        <Input value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="почта@партнёра.ру" className="h-8 w-[200px] text-xs" />
        <Input value={name} onChange={(e) => setName(e.target.value)}
          placeholder="имя (необязательно)" className="h-8 w-[160px] text-xs" />
        <Button size="sm" variant="outline" className="h-8 px-2 text-xs"
          disabled={!email.includes('@') || позвать.isPending}
          onClick={() => позвать.mutate()}>
          {позвать.isPending
            ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            : <UserPlus className="mr-1 h-3.5 w-3.5" />}
          Позвать
        </Button>
      </div>

      {ссылка && (
        <div className="rounded border border-amber-500/40 bg-amber-500/[0.06] p-2 text-xs">
          <p className="font-medium">Ссылка для {ссылка.email}</p>
          <p className="mt-0.5 text-muted-foreground">
            Видна один раз. Отправьте её сами — почтой или как удобно.
          </p>
          <div className="mt-1 flex items-center gap-1.5">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-1.5 py-1">
              {ссылка.url}
            </code>
            <Button size="sm" variant="ghost" className="h-7 px-1.5"
              onClick={() => {
                void navigator.clipboard.writeText(ссылка.url)
                toast.success('Скопировано')
              }}>
              <Copy className="h-3.5 w-3.5" />
            </Button>
          </div>
          <Button size="sm" variant="ghost" className="mt-1 h-7 px-1.5 text-xs"
            onClick={() => setСсылка(null)}>Скрыть</Button>
        </div>
      )}

      <div className="space-y-1.5 border-t border-border pt-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Материалы
        </p>
        {материалы.map((m) => (
          <div key={m.id} className="flex items-center gap-2 text-xs">
            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{m.title}</span>
            <Button size="sm" variant="ghost" className="h-7 px-1.5"
              title="Закрыть материал и отозвать его ссылку"
              disabled={закрыть.isPending}
              onClick={() => закрыть.mutate(m.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
        <SearchPicker
          items={(docsQ.data?.docs ?? [])
            .filter((d) => d.reg_number)
            .map((d) => ({ id: d.id, name: d.title, hint: d.reg_number }))}
          value="" onChange={(id) => открыть.mutate(id)}
          placeholder="Открыть документ гостям"
          searchPlaceholder="Название или номер…"
          className="w-full" loading={docsQ.isLoading} />
        <p className="text-[11px] text-muted-foreground">
          Только зарегистрированные: наружу уходит номер. Каждый материал
          открывается отдельно и сохраняет собственные права.
        </p>
      </div>
    </div>
  )
}

export default GuestPanel
