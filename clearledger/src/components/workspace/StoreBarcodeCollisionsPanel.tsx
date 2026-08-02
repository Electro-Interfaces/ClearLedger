/**
 * «Магазин» → Каталог → Коллизии штрихкодов.
 *
 * Один штрихкод не может принадлежать двум карточкам — и это не формальность.
 * Касса ищет товар по коду; если он привязан к двум позициям, продаётся та,
 * что выгрузилась последней, а вторая «исчезает с полки», хотя лежит на ней.
 * Именно так на 208 появлялись жалобы «товар есть, а пробить нельзя».
 *
 * Претензии копятся сами: из часовых снимков станций и из признания черновиков.
 * Автоматически их не разрешают — оба варианта опасны. Перевесить код молча
 * значит сломать кассу тому товару, который сейчас по нему пробивается; забыть
 * значит оставить второй товар непродаваемым. Поэтому решает человек, и ему
 * нужно видеть цену вопроса: сколько лежит у нынешнего владельца, когда по коду
 * последний раз продавали, сколько за ним кодов кассы.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Barcode, ArrowRightLeft, X, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import {
  getBarcodeCollisions, resolveBarcodeCollision, type BarcodeCollision,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

/** Нормализация имени только для подсказки «похоже на дубль» — не для решений. */
function normName(s: string): string {
  return s.toLowerCase().replace(/[.,\s]+/g, ' ').replace(/\s+/g, ' ').trim()
}

function when(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('ru-RU')
}

function CollisionCard({ c, onDone }: { c: BarcodeCollision; onDone: () => void }) {
  const [note, setNote] = useState('')
  const resolve = useMutation({
    mutationFn: (action: 'move' | 'drop') =>
      resolveBarcodeCollision(c.claim_id, { action, note: note || undefined }),
    onSuccess: (res) => {
      toast.success(
        res.action === 'move' ? `Код ${c.code} передан карточке «${c.claimant_name}»` : 'Претензия снята',
        {
          description: res.action === 'move'
            ? `Прежняя привязка сохранена как историческая — вчерашние чеки останутся читаемыми. Станциям отправлено задание: ${res.pushed_to_stations ?? 0}.`
            : `Код остаётся у «${c.holder_name}».`,
        },
      )
      onDone()
    },
    onError: (e: Error) => toast.error('Не удалось', { description: e.message }),
  })

  const рискованно = c.holder_stock > 0 || c.holder_ns_codes > 0
  // Похоже, что это не спор за код, а две карточки одного товара.
  //
  // На 208 так и оказалось: девять коллизий — это девять блюд, заведённых
  // дважды («Американо 200 мл.» и «Американо 200 мл»). Передавать код тут
  // бессмысленно: он всё равно останется у одного из дублей, а второй
  // продолжит жить своей техкартой с другими нормами списания. Лечится
  // слиянием карточек, а не привязкой штрихкода.
  const похожиНаДубль = normName(c.holder_name) === normName(c.claimant_name)

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Barcode className="h-4 w-4 text-muted-foreground" />
        <span className="font-mono text-sm">{c.code}</span>
        <span className="text-xs text-muted-foreground">· претензия от {when(c.claimed_at)}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded border border-emerald-400/30 bg-emerald-400/5 p-3">
          <div className="text-[10px] uppercase tracking-wide text-emerald-300/70 mb-1">
            Сейчас код у этой карточки
          </div>
          <div className="text-sm font-medium">{c.holder_name}</div>
          <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
            <div>{c.holder_unit} · остаток {c.holder_stock}</div>
            <div>кодов кассы: {c.holder_ns_codes} · продавали {when(c.holder_last_sold)}</div>
          </div>
        </div>

        <div className="rounded border border-amber-400/30 bg-amber-400/5 p-3">
          <div className="text-[10px] uppercase tracking-wide text-amber-300/70 mb-1">
            Претендует
          </div>
          <div className="text-sm font-medium">{c.claimant_name}</div>
          <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
            <div>{c.claimant_unit}
              {c.claimant_source === 'station' && ' · карточка заведена на станции'}</div>
            {c.claim_note && <div className="leading-relaxed">{c.claim_note}</div>}
          </div>
        </div>
      </div>

      {похожиНаДубль && (
        <div className="mt-3 flex items-start gap-2 rounded border border-blue-400/30 bg-blue-400/5 p-2.5 text-xs text-blue-200/80 leading-relaxed">
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            Наименования совпадают с точностью до знаков препинания — похоже, это не спор
            за код, а две карточки одного товара. Передача штрихкода тут ничего не решит:
            он останется у одного из дублей, а второй продолжит жить своей рецептурой.
            Такое лечится слиянием карточек в разделе «Дубли».
          </span>
        </div>
      )}
      {рискованно && (
        <div className="mt-3 flex items-start gap-2 rounded border border-red-400/30 bg-red-400/5 p-2.5 text-xs text-red-200/80 leading-relaxed">
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            У нынешнего владельца код рабочий: остаток {c.holder_stock}, кодов кассы {c.holder_ns_codes}.
            Передача сломает кассу этому товару, пока станция не перевыгрузит ассортимент.
          </span>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <input
          className="flex-1 min-w-[200px] rounded border border-border bg-background px-2 py-1.5 text-sm"
          placeholder="чем решение обосновано (необязательно)"
          value={note} onChange={(e) => setNote(e.target.value)} />
        <Button size="sm" variant="outline" disabled={resolve.isPending}
          onClick={() => resolve.mutate('move')}>
          <ArrowRightLeft className="h-3.5 w-3.5 mr-1" />Передать претенденту
        </Button>
        <Button size="sm" variant="ghost" disabled={resolve.isPending}
          onClick={() => resolve.mutate('drop')}>
          <X className="h-3.5 w-3.5 mr-1" />Оставить как есть
        </Button>
      </div>
    </div>
  )
}

export function StoreBarcodeCollisionsPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['barcode-collisions', company.id],
    queryFn: getBarcodeCollisions,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['barcode-collisions', company.id] })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить список: {(error as Error).message}</div>

  const list = data?.collisions ?? []

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div>
        <h3 className="text-base font-semibold flex items-center gap-2">
          <Barcode className="h-4 w-4 text-primary" />Коллизии штрихкодов
          {list.length > 0 && <span className="text-muted-foreground font-normal">· {list.length}</span>}
        </h3>
        <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
          Один код — одна карточка. Касса ищет товар по штрихкоду, и при двойной привязке
          продаётся та позиция, что выгрузилась последней: вторая «исчезает с полки», хотя
          лежит на ней. Претензии копятся из снимков станций и из признания черновиков —
          автоматически их не разрешают, потому что оба варианта что-то ломают.
        </p>
      </div>

      {list.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Коллизий нет: каждый штрихкод принадлежит одной карточке.
        </div>
      ) : (
        <div className="space-y-3">
          {list.map((c) => <CollisionCard key={c.claim_id} c={c} onDone={refresh} />)}
        </div>
      )}
    </div>
  )
}
