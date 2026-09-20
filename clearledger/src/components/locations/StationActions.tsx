/**
 * Действия по станции: заявка, поручение, разговор — из карточки объекта.
 *
 * Инженер эксплуатации видит беду там, где смотрит: «станция числится рабочей,
 * а молчит девятнадцать дней». Дальше ему нужно не «перейти в другое
 * приложение и найти объект», а сделать три вещи, и все три — про один и тот же
 * объект:
 *
 * - **заявка в Поддержку** — восстановить работоспособность. Сервисная служба,
 *   SLA, наряд, исполнитель;
 * - **поручение в «Трек»** — работа компании, а не ремонт: запросить документы у
 *   поставщика, согласовать вывод в ремонт, подготовить акт;
 * - **разговор в чате** — когда решение ещё не оформлено и нужно спросить людей.
 *
 * Граница между первым и вторым — не формальность. Работа, восстанавливающая
 * работоспособность, — заявка; работа компании вокруг станции — «Трек». Если
 * заявку заводить поручением, сервисная служба её не увидит и SLA не посчитает;
 * если поручение заводить заявкой — реестр заявок перестанет быть реестром
 * отказов. Поэтому кнопки две, а не одна «создать».
 *
 * Привязка везде одна и та же — объект пространства: и заявка, и поручение, и
 * комната чата находятся потом по станции, с какой бы стороны их ни искали.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ListChecks, LifeBuoy, Loader2, MessageCircle } from 'lucide-react'
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
import { useSupportContext } from '@/contexts/SupportContext'
import * as chat from '@/services/chatService'
import { createObjectTicket, listTicketKinds } from '@/services/spaceObjectsService'
import { createTask, listTaskPeople } from '@/services/tasksService'

const ВАЖНОСТЬ = [
  { k: 'low', label: 'Низкая' },
  { k: 'medium', label: 'Обычная' },
  { k: 'high', label: 'Высокая' },
  { k: 'critical', label: 'Критичная — станция стоит' },
]

/** Название станции для заголовка заявки: номер важнее имени, он короче. */
function подпись(station: { name: string; number?: string | null; code?: string | null }) {
  const номер = station.number || station.code
  return номер ? `${номер} · ${station.name}` : station.name
}

export function StationActions({ station, compact }: {
  station: { id: string; name: string; number?: string | null; code?: string | null }
  /** В шапке вкладки кнопки поменьше и без подписей-пояснений. */
  compact?: boolean
}) {
  const { companyId } = useCompany()
  const { openInteraction } = useSupportContext()
  const qc = useQueryClient()
  const [окно, setОкно] = useState<null | 'ticket' | 'errand'>(null)
  const [чатИдёт, setЧатИдёт] = useState(false)

  const имя = useMemo(() => подпись(station), [station])

  // ── заявка в Поддержку ──
  const [заголовок, setЗаголовок] = useState('')
  const [описание, setОписание] = useState('')
  const [важность, setВажность] = useState('medium')
  const [вид, setВид] = useState('')

  // Виды работ заводит Поддержка — свой перечень в Ядре разошёлся бы с её
  // маршрутами на первой же правке процесса.
  const виды = useQuery({
    queryKey: ['ticket-kinds', companyId],
    queryFn: () => listTicketKinds(companyId),
    enabled: окно === 'ticket' && !!companyId,
    staleTime: 10 * 60_000,
    retry: false,
  })

  const заявка = useMutation({
    mutationFn: () => createObjectTicket(companyId, station.id, {
      title: заголовок.trim() || `Работа на станции ${имя}`,
      description: описание.trim(),
      priority: важность,
      type_code: вид || undefined,
    }),
    onSuccess: (r) => {
      toast.success(`Заявка ${r.display_number || r.number} заведена`)
      void qc.invalidateQueries({ queryKey: ['object-tickets', companyId, station.id] })
      закрыть()
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось завести заявку'),
  })

  // ── поручение в «Трек» ──
  const [что, setЧто] = useState('')
  const [кому, setКому] = useState('')
  const [срок, setСрок] = useState('')
  const люди = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => listTaskPeople(companyId),
    enabled: окно === 'errand' && !!companyId,
    staleTime: 5 * 60_000,
  })

  const поручение = useMutation({
    mutationFn: () => createTask({
      companyId,
      title: что.trim(),
      description: описание.trim() || undefined,
      // Привязка к объекту: работа найдётся во вкладке «Трек» этой станции.
      objectId: station.id,
      assigneeId: кому || undefined,
      dueAt: срок ? new Date(срок).toISOString() : undefined,
    }),
    onSuccess: () => {
      toast.success('Поручение поставлено — видно во вкладке «Трек» станции')
      void qc.invalidateQueries({ queryKey: ['location-track', companyId, station.id] })
      закрыть()
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось поставить поручение'),
  })

  function закрыть() {
    setОкно(null)
    setЗаголовок(''); setОписание(''); setВажность('medium'); setВид('')
    setЧто(''); setКому(''); setСрок('')
  }

  // ── разговор по станции ──
  // Сначала ищем уже заведённую группу: вторая комната по той же станции
  // раскалывает обсуждение надвое, и половина людей остаётся в первой.
  const обсудить = async () => {
    setЧатИдёт(true)
    try {
      const комнаты = await chat.getRooms(false, null, station.id, null)
      const есть = комнаты?.[0]
      const room = есть ?? await chat.createRoom(
        'group', [], `Станция ${имя}`, null, station.id, null)
      openInteraction('chat', `room:${room.id}`)
      if (!есть) toast.success('Группа создана — добавьте участников в её составе')
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось открыть разговор')
    } finally {
      setЧатИдёт(false)
    }
  }

  const размер = compact ? 'h-7 text-xs' : ''

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" className={размер}
          onClick={() => { setОкно('ticket'); setЗаголовок(`Работа на станции ${имя}`) }}>
          <LifeBuoy className="mr-1.5 size-3.5" />Заявка в Поддержку
        </Button>
        <Button size="sm" variant="outline" className={размер}
          onClick={() => { setОкно('errand'); setЧто(`По станции ${имя}: `) }}>
          <ListChecks className="mr-1.5 size-3.5" />Поручение в «Трек»
        </Button>
        <Button size="sm" variant="outline" className={размер}
          onClick={() => void обсудить()} disabled={чатИдёт}>
          {чатИдёт ? <Loader2 className="mr-1.5 size-3.5 animate-spin" />
            : <MessageCircle className="mr-1.5 size-3.5" />}
          Обсудить
        </Button>
      </div>

      {/* ── заявка ── */}
      <Dialog open={окно === 'ticket'} onOpenChange={(v) => { if (!v && !заявка.isPending) закрыть() }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Заявка в Поддержку</DialogTitle>
            <DialogDescription>
              Работа, восстанавливающая работоспособность станции. Уйдёт сервисной
              службе со сроком по важности и останется привязанной к этому объекту.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="ticket-title">Заголовок</Label>
              <Input id="ticket-title" value={заголовок}
                onChange={(e) => setЗаголовок(e.target.value)} />
            </div>
            {(виды.data?.types.length ?? 0) > 0 && (
              <div className="space-y-1.5">
                <Label htmlFor="ticket-kind">Вид работы</Label>
                <Select value={вид} onValueChange={setВид}>
                  <SelectTrigger id="ticket-kind">
                    <SelectValue placeholder="Выберите, что нужно сделать" />
                  </SelectTrigger>
                  <SelectContent>
                    {виды.data?.types.map((t) => (
                      <SelectItem key={t.code} value={t.code}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Вид решает маршрут: заявка попадёт к службе, которая эти работы делает.
                </p>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="ticket-prio">Важность</Label>
              <Select value={важность} onValueChange={setВажность}>
                <SelectTrigger id="ticket-prio"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ВАЖНОСТЬ.map((p) => (
                    <SelectItem key={p.k} value={p.k}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ticket-text">Что случилось</Label>
              <Textarea id="ticket-text" rows={5} value={описание}
                onChange={(e) => setОписание(e.target.value)}
                placeholder="Станция числится рабочей, энергии нет с 3 сентября. Проверить питание и связь." />
              <p className="text-xs text-muted-foreground">
                Не короче 10 символов — по этому тексту работает сервисная служба.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={закрыть} disabled={заявка.isPending}>Отмена</Button>
            <Button onClick={() => заявка.mutate()}
              disabled={заявка.isPending || описание.trim().length < 10}>
              {заявка.isPending && <Loader2 className="mr-1.5 size-4 animate-spin" />}
              Завести заявку
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── поручение ── */}
      <Dialog open={окно === 'errand'} onOpenChange={(v) => { if (!v && !поручение.isPending) закрыть() }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Поручение по станции</DialogTitle>
            <DialogDescription>
              Работа компании вокруг станции: запросить документы, согласовать вывод
              в ремонт, подготовить акт. Появится у исполнителя и во вкладке «Трек»
              этой станции.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="errand-title">Что сделать</Label>
              <Input id="errand-title" value={что} onChange={(e) => setЧто(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="errand-who">Кому</Label>
                <Select value={кому} onValueChange={setКому}>
                  <SelectTrigger id="errand-who">
                    <SelectValue placeholder={люди.isLoading ? 'Загрузка…' : 'Выберите человека'} />
                  </SelectTrigger>
                  <SelectContent>
                    {(люди.data?.people ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="errand-due">Срок</Label>
                <Input id="errand-due" type="datetime-local" value={срок}
                  onChange={(e) => setСрок(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="errand-text">Подробности</Label>
              <Textarea id="errand-text" rows={4} value={описание}
                onChange={(e) => setОписание(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={закрыть} disabled={поручение.isPending}>Отмена</Button>
            <Button onClick={() => поручение.mutate()}
              disabled={поручение.isPending || что.trim().length < 3 || !кому}>
              {поручение.isPending && <Loader2 className="mr-1.5 size-4 animate-spin" />}
              Поставить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
