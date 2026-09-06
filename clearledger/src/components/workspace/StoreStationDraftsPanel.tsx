/**
 * «Магазин» → Каталог → Признание со станций.
 *
 * Очередь того, что станции решили сами: карточки нового товара (машина у
 * ворот, связи нет), поставщики, которых ещё нет в сети, и цены по позициям,
 * право на которые отдано станции.
 *
 * Зачем разбирать это здесь, а не на месте. Дедуп возможен только там, где
 * виден справочник всей сети: «ИП Сидоров» с 208-й и «Сидоров И.П.» с 210-й —
 * один человек, а «LD Blue» и «LD Autograph» оказались одним товаром. Пока
 * заводили на местах, на 208 набралось 95 групп дублей, и разбирали их месяц
 * руками. Поэтому станция заводит черновик, а каноном его делает человек здесь.
 *
 * Сопоставляем по ШТРИХКОДУ и только по нему: наименования на станциях
 * расходятся, а нормализация имён даёт ложные пары — то есть новые дубли.
 *
 * Цены в этой очереди не подтверждают: они уже действуют на полке. Это журнал,
 * и нужен он ровно для одного вопроса — «почему у нас Джокер по 90».
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Boxes, Building2, Tag, Link2, PackagePlus, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  getStationDrafts, getDraftCandidates, resolveItemDraft, resolvePartnerDraft,
  resolveNSIProposal,
  type StationItemDraft, type DraftCandidate,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

/** Что именно станция просит исправить — теми же словами, что видит товаровед. */
const FIELD_LABELS: Record<string, string> = {
  name: 'наименование',
  unit: 'единица',
  vat: 'ставка НДС',
  barcode_add: 'добавить штрихкод',
  barcode_remove: 'убрать штрихкод',
}

function money(v: number | null): string {
  return v === null || v === undefined ? '—' : v.toFixed(2)
}

function when(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

/** Карточка черновика товара с кандидатами на сопоставление. */
function ItemDraftCard({ draft, groups, onDone }: {
  draft: StationItemDraft
  groups: { group_id: number; path: string; cash_section: number | null }[]
  onDone: () => void
}) {
  const [note, setNote] = useState('')
  // Группа обязательна по сути: без неё карточка не уедет в кассу — отдел кассы
  // приходит свойством группы. Поле предзаполнено подсказкой по названию,
  // товаровед подтверждает или меняет.
  const [groupId, setGroupId] = useState<number | null>(draft.group_hint?.group_id ?? null)
  const { data: cand } = useQuery({
    queryKey: ['draft-candidates', draft.id, draft.barcodes.join(',')],
    queryFn: () => getDraftCandidates(draft.barcodes),
    enabled: draft.barcodes.length > 0,
  })
  const candidates: DraftCandidate[] = cand?.candidates ?? []

  const resolve = useMutation({
    mutationFn: (body: { action: 'link' | 'create' | 'reject'; item_id?: number }) =>
      resolveItemDraft(draft.id!, {
        ...body, note: note || undefined,
        group_id: body.action === 'create' ? groupId : undefined,
      }),
    onSuccess: (res) => {
      const c = Number(res.collisions ?? 0)
      toast.success(
        res.action === 'reject' ? 'Черновик отклонён'
          : res.action === 'link' ? 'Привязано к карточке сети'
            : 'Заведена новая карточка сети',
        {
          description: c > 0
            ? `Штрихкодов перенесено: ${res.barcodes_linked}. ${c} уже заняты другими карточками — это коллизия справочника, её надо разобрать отдельно.`
            : res.pushed ? 'Станции отправлено задание: она заменит свой черновик каноном.' : undefined,
        },
      )
      onDone()
    },
    onError: (e: Error) => toast.error('Не удалось', { description: e.message }),
  })

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="font-medium">{draft.name}</div>
          <div className="text-xs text-muted-foreground mt-0.5">
            АЗС {draft.station_id} · {draft.unit} · {draft.vat_rate ?? 'ставка не указана'} ·
            заведена {when(draft.created_at)}
            {draft.author ? ` · ${draft.author}` : ''}
          </div>
          <div className="text-xs font-mono mt-1">
            {draft.barcodes.length ? draft.barcodes.join(', ') : <span className="text-red-400/80">без штрихкода</span>}
          </div>
        </div>
      </div>

      {candidates.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs text-muted-foreground mb-1.5">
            В сети уже есть карточка с таким штрихкодом — скорее всего, это она:
          </div>
          <div className="space-y-1.5">
            {candidates.map((c) => (
              <div key={c.item_id} className="flex items-center justify-between gap-3 rounded border border-border/60 bg-background/40 px-3 py-2">
                <div className="min-w-0 text-sm">
                  <div className="truncate">{c.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">
                    {c.barcode} · {c.unit} · {c.vat_rate}
                    {c.barcode_status !== 'active' && ` · штрихкод ${c.barcode_status}`}
                  </div>
                </div>
                <Button size="sm" variant="outline" disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ action: 'link', item_id: c.item_id })}>
                  <Link2 className="h-3.5 w-3.5 mr-1" />Это она
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-muted-foreground">
          Совпадений по штрихкоду в сети нет — похоже, товар действительно новый.
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <select
          className="min-w-[220px] rounded border border-border bg-background px-2 py-1.5 text-sm"
          value={groupId ?? ''}
          onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)}
          title="Товарная группа: от неё зависит отдел кассы, без неё карточка в кассу не уедет"
        >
          <option value="">группа не выбрана</option>
          {groups.map((g) => (
            <option key={g.group_id} value={g.group_id}>
              {g.path}{g.cash_section ? ` · отдел ${g.cash_section}` : ''}
            </option>
          ))}
        </select>
        <input
          className="flex-1 min-w-[160px] rounded border border-border bg-background px-2 py-1.5 text-sm"
          placeholder="примечание к решению (необязательно)"
          value={note} onChange={(e) => setNote(e.target.value)} />
        <Button size="sm" disabled={resolve.isPending || groupId === null}
          title={groupId === null
            ? 'Выберите товарную группу: от неё зависит отдел кассы'
            : 'Завести карточку в сетевом справочнике'}
          onClick={() => resolve.mutate({ action: 'create' })}>
          <PackagePlus className="h-3.5 w-3.5 mr-1" />Завести в сети
        </Button>
        <Button size="sm" variant="ghost" disabled={resolve.isPending}
          onClick={() => resolve.mutate({ action: 'reject' })}>
          <X className="h-3.5 w-3.5 mr-1" />Отклонить
        </Button>
      </div>
    </div>
  )
}

export function StoreStationDraftsPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['station-drafts', company.id],
    queryFn: () => getStationDrafts(),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['station-drafts', company.id] })

  const partner = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'accept' | 'reject' }) =>
      resolvePartnerDraft(id, { action }),
    onSuccess: (res) => {
      toast.success(res.action === 'accept' ? 'Контрагент принят в справочник сети' : 'Отклонён')
      refresh()
    },
    onError: (e: Error) => toast.error('Не удалось', { description: e.message }),
  })

  const proposal = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'accept' | 'reject' }) =>
      resolveNSIProposal(id, { action }),
    onSuccess: (res) => {
      toast.success(res.action === 'accept'
        ? `Правка принята${res.applied ? `: ${res.applied}` : ''}`
        : 'Заявка отклонена')
      refresh()
    },
    onError: (e: Error) => toast.error('Не удалось', { description: e.message }),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка очереди…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить очередь: {(error as Error).message}</div>

  const items = data?.items ?? []
  const partners = data?.partners ?? []
  const prices = data?.prices ?? []
  const proposals = data?.proposals ?? []

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h3 className="text-base font-semibold flex items-center gap-2">
          <Boxes className="h-4 w-4 text-primary" />Признание со станций
        </h3>
        <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
          Станция заводит карточку и поставщика сама, когда товар уже привезли, а связи нет.
          Каноном их делает человек здесь: только в центре виден справочник всей сети, а значит
          видно, что «ИП Сидоров» с 208-й и «Сидоров И.П.» с 210-й — один человек. Сопоставляем
          по штрихкоду: наименования на станциях расходятся, и по ним дедуп даёт ложные пары.
        </p>
      </div>

      <section>
        <div className="text-sm font-medium mb-2">
          Карточки товаров {items.length > 0 && <span className="text-muted-foreground">· {items.length}</span>}
        </div>
        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            Очередь пуста — станции ничего не заводили.
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((d) => (
              <ItemDraftCard key={d.id ?? d.source_uuid} draft={d}
                             groups={data?.groups ?? []} onDone={refresh} />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="text-sm font-medium mb-2 flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          Контрагенты {partners.length > 0 && <span className="text-muted-foreground">· {partners.length}</span>}
        </div>
        {partners.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            Новых поставщиков со станций нет.
          </div>
        ) : (
          <div className="space-y-2">
            {partners.map((p) => (
              <div key={p.id ?? p.source_uuid} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{p.name}</div>
                  <div className="text-xs text-muted-foreground">
                    АЗС {p.station_id} · {p.inn ? `ИНН ${p.inn}` : 'ИНН не указан'}
                    {p.comment && ` · ${p.comment}`}
                    {p.author ? ` · ${p.author}` : ''}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button size="sm" variant="outline" disabled={partner.isPending}
                    onClick={() => partner.mutate({ id: p.id!, action: 'accept' })}>Принять</Button>
                  <Button size="sm" variant="ghost" disabled={partner.isPending}
                    onClick={() => partner.mutate({ id: p.id!, action: 'reject' })}>Отклонить</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Заявки об ошибках в сетевых карточках. Станция их не применяла: канон
          правит центр, и до решения человека карточка остаётся прежней. */}
      <section>
        <div className="text-sm font-medium mb-2 flex items-center gap-2">
          <Tag className="h-4 w-4 text-muted-foreground" />
          Заявки об ошибках в карточках
          {proposals.length > 0 && <span className="text-muted-foreground">· {proposals.length}</span>}
        </div>
        <p className="text-xs text-muted-foreground mb-2 leading-relaxed">
          Ошибку в карточке первым видит тот, кто стоит у полки: не та ставка, кривое название,
          штрихкод, который не сканируется. Заявка ничего не изменила — на станции карточка
          прежняя. Примете — правка ляжет в канон и разъедется по сети обычным обновлением.
        </p>
        {proposals.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            Станции об ошибках не заявляли.
          </div>
        ) : (
          <div className="space-y-2">
            {proposals.map((p) => (
              <div key={p.id} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">
                      {p.item_name ?? p.item_uuid}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      АЗС {p.station_id} · {FIELD_LABELS[p.field] ?? p.field} ·{' '}
                      {p.current ? <>было <span className="line-through">{p.current}</span> · </> : null}
                      должно быть <span className="text-foreground font-medium">{p.proposed}</span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {p.author}{p.comment ? ` · ${p.comment}` : ''} · {when(p.created_at)}
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <Button size="sm" disabled={proposal.isPending}
                      onClick={() => proposal.mutate({ id: p.id, action: 'accept' })}>
                      Принять
                    </Button>
                    <Button size="sm" variant="outline" disabled={proposal.isPending}
                      onClick={() => proposal.mutate({ id: p.id, action: 'reject' })}>
                      Отклонить
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="text-sm font-medium mb-2 flex items-center gap-2">
          <Tag className="h-4 w-4 text-muted-foreground" />Цены, назначенные станциями
        </div>
        <p className="text-xs text-muted-foreground mb-2 leading-relaxed">
          Эти цены уже действуют на полке — подтверждать их не нужно. Журнал отвечает на вопрос
          «почему у нас такая цена»: кто поменял, когда и по какой причине.
        </p>
        {prices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            Станции цен не меняли.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Когда</th>
                  <th className="px-3 py-2 text-left">АЗС</th>
                  <th className="px-3 py-2 text-left">Штрихкод</th>
                  <th className="px-3 py-2 text-right">Было</th>
                  <th className="px-3 py-2 text-right">Стало</th>
                  <th className="px-3 py-2 text-left">Кто</th>
                  <th className="px-3 py-2 text-left">Почему</th>
                </tr>
              </thead>
              <tbody>
                {prices.map((p, i) => (
                  <tr key={`${p.item_uuid}-${p.changed_at}-${i}`} className="border-t border-border/50">
                    <td className="px-3 py-2 whitespace-nowrap">{when(p.changed_at)}</td>
                    <td className="px-3 py-2">{p.station_id}</td>
                    <td className="px-3 py-2 font-mono text-xs">{p.barcode ?? '—'}</td>
                    <td className="px-3 py-2 text-right">{money(p.old_price)}</td>
                    <td className="px-3 py-2 text-right font-medium">{money(p.new_price)}</td>
                    <td className="px-3 py-2">{p.author}</td>
                    <td className="px-3 py-2 text-muted-foreground">{p.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
