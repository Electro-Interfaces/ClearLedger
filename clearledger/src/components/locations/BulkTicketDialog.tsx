/**
 * Заявки пачкой — по отобранным на витрине станциям.
 *
 * Зачем. На пилоте 291 станция молчит дольше недели, и открытая заявка есть у
 * одиннадцати. Разница не в том, что людям лень: чтобы завести работу по
 * каждой, надо открыть 280 карточек — значит не будет сделано вовсе. Отбор на
 * витрине уже сделан («молчат больше недели и никем не взяты»), остаётся
 * превратить его в работу одним действием.
 *
 * Почему с подтверждением и списком. Заявка — не пометка у себя: она уходит
 * живым людям со сроком. Человек должен увидеть, по каким именно станциям
 * заводит и сколько их, до нажатия, а не в отчёте после. Пачка ограничена
 * полусотней по той же причине — список, который нельзя окинуть взглядом, не
 * подтверждают, а пролистывают.
 *
 * Ошибка по одной станции не отменяет остальные: приложение может не знать
 * объект, заведённый после последней проекции. Отчёт приходит построчно.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  createObjectTicketsBulk, listTicketKinds,
} from '@/services/spaceObjectsService'

/** Сколько станций человек ещё способен проверить глазами перед отправкой. */
export const ПАЧКА_МАКСИМУМ = 50

const ВАЖНОСТЬ = [
  { k: 'low', label: 'Низкая' },
  { k: 'medium', label: 'Обычная' },
  { k: 'high', label: 'Высокая' },
  { k: 'critical', label: 'Критичная — станции стоят' },
]

export function BulkTicketDialog({ stations, open, onClose }: {
  stations: { id: string; name: string; number?: string | null }[]
  open: boolean
  onClose: () => void
}) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [заголовок, setЗаголовок] = useState('')
  const [описание, setОписание] = useState('')
  const [важность, setВажность] = useState('high')
  const [вид, setВид] = useState('')

  const виды = useQuery({
    queryKey: ['ticket-kinds', companyId],
    queryFn: () => listTicketKinds(companyId),
    enabled: open && !!companyId,
    staleTime: 10 * 60_000,
    retry: false,
  })

  const пачка = useMutation({
    mutationFn: () => createObjectTicketsBulk(companyId, {
      object_ids: stations.slice(0, ПАЧКА_МАКСИМУМ).map((s) => s.id),
      description: описание.trim(),
      title: заголовок.trim() || undefined,
      priority: важность,
      type_code: вид || undefined,
    }),
    onSuccess: (r) => {
      if (r.createdCount) {
        toast.success(`Заведено заявок: ${r.createdCount}`)
        void qc.invalidateQueries({ queryKey: ['network-open-work', companyId] })
      }
      // Молчать про неудачи нельзя: человек решит, что работа заведена по всем.
      if (r.failedCount) {
        toast.error(`Не удалось по ${r.failedCount}: ${r.failed[0]?.error ?? ''}`)
      }
      if (!r.failedCount) закрыть()
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось завести заявки'),
  })

  function закрыть() {
    пачка.reset()
    setЗаголовок(''); setОписание(''); setВажность('high'); setВид('')
    onClose()
  }

  const берём = stations.slice(0, ПАЧКА_МАКСИМУМ)
  const отчёт = пачка.data

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !пачка.isPending) закрыть() }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Заявки по {берём.length} станциям</DialogTitle>
          <DialogDescription>
            Один текст уйдёт по каждой станции отдельной заявкой — со своим номером,
            сроком и привязкой к объекту. Сервисная служба увидит их как обычные заявки.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {stations.length > ПАЧКА_МАКСИМУМ && (
            <p className="flex items-center gap-1.5 rounded-md bg-amber-500/10 p-2 text-xs text-amber-600 dark:text-amber-400">
              <AlertTriangle className="size-3.5 shrink-0" />
              Отобрано {stations.length}; за раз заводим первые {ПАЧКА_МАКСИМУМ} —
              остальные следующей пачкой.
            </p>
          )}

          {/* Список виден до нажатия: человек подтверждает адреса, а не число. */}
          <div className="max-h-28 overflow-y-auto rounded-md border border-border/50 p-2 text-xs">
            {берём.map((s) => (
              <span key={s.id} className="mr-2 inline-block text-muted-foreground">
                {s.number ? `${s.number} · ` : ''}{s.name};
              </span>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {(виды.data?.types.length ?? 0) > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="bulk-kind">Вид работы</Label>
                <Select value={вид} onValueChange={setВид}>
                  <SelectTrigger id="bulk-kind">
                    <SelectValue placeholder="Выберите, что нужно сделать" />
                  </SelectTrigger>
                  <SelectContent>
                    {виды.data?.types.map((t) => (
                      <SelectItem key={t.code} value={t.code}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="bulk-prio">Важность</Label>
              <Select value={важность} onValueChange={setВажность}>
                <SelectTrigger id="bulk-prio"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ВАЖНОСТЬ.map((p) => (
                    <SelectItem key={p.k} value={p.k}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="bulk-title">Заголовок</Label>
            <Input id="bulk-title" value={заголовок}
              onChange={(e) => setЗаголовок(e.target.value)}
              placeholder="Пусто — подставим «Работа на объекте: <станция>»" />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="bulk-text">Что проверить</Label>
            <Textarea id="bulk-text" rows={4} value={описание}
              onChange={(e) => setОписание(e.target.value)}
              placeholder="Станция числится рабочей, зарядок нет больше недели. Проверить питание, связь и состояние коннекторов." />
            <p className="text-xs text-muted-foreground">
              Не короче 10 символов — по этому тексту работает сервисная служба.
            </p>
          </div>

          {/* Отчёт остаётся на экране, пока есть неудачи: иначе человек уйдёт,
              считая, что работа заведена по всем станциям отбора. */}
          {отчёт && отчёт.failedCount > 0 && (
            <div className="max-h-32 overflow-y-auto rounded-md border border-red-500/30 p-2 text-xs">
              <div className="mb-1 font-medium text-red-600 dark:text-red-400">
                Заведено {отчёт.createdCount}, не удалось {отчёт.failedCount}:
              </div>
              {отчёт.failed.map((f) => (
                <div key={f.objectId} className="text-muted-foreground">
                  {f.name ?? f.objectId} — {f.error}
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={закрыть} disabled={пачка.isPending}>
            {отчёт ? 'Закрыть' : 'Отмена'}
          </Button>
          <Button onClick={() => пачка.mutate()}
            disabled={пачка.isPending || описание.trim().length < 10 || !берём.length}>
            {пачка.isPending && <Loader2 className="mr-1.5 size-4 animate-spin" />}
            Завести {берём.length} заявок
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
