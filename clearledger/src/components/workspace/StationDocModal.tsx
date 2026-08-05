/**
 * Первичный документ станции: шапка, стороны, строки, образы.
 *
 * В 1С любое движение товара оформлено документом, и это не формальность:
 * приёмка, перемещение между станциями, пересчёт и списание — основания
 * материальной ответственности. Реестр отвечает «что было», карточка — «на
 * основании чего и с чем именно», а образ накладной отвечает проверяющему.
 *
 * Учётная запись документа и его бумажное основание — разные вещи: приёмка
 * может быть проведена, а накладной поставщика в системе нет. Поэтому раздел
 * образов виден всегда, даже пустым.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Paperclip, Upload, Trash2, X, FileText, Printer, Save } from 'lucide-react'
import {
  getStoreStationDoc, getStoreDocFiles, uploadStoreDocFile, deleteStoreDocFile,
  saveStoreDocMeta,
} from '@/services/storeService'
import { printStationDoc } from './printStationDoc'
import { fmtMoney } from '@/services/analyticsService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Роль образа: чем именно подтверждается операция. */
const РОЛИ = ['накладная', 'УПД', 'акт', 'опись', 'фото', 'прочее']

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function объём(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function Факт({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="truncate text-sm">{value}</div>
    </div>
  )
}

export function StationDocModal({ packetUuid, index, onClose }: {
  packetUuid: string; index: number; onClose: () => void
}) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [роль, задатьРоль] = useState(РОЛИ[0])
  // Стороны документа правятся здесь: агент передаёт только автора, а
  // перемещение между станциями без двух фамилий — просто запись в журнале.
  const [сдал, задатьСдал] = useState<string | null>(null)
  const [принял, задатьПринял] = useState<string | null>(null)
  const файл = useRef<HTMLInputElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['store-station-doc', company.id, packetUuid, index],
    queryFn: () => getStoreStationDoc(packetUuid, index),
  })
  const docRef = data?.doc_ref
  const { data: образы } = useQuery({
    queryKey: ['store-doc-files', company.id, docRef],
    queryFn: () => getStoreDocFiles(docRef as string),
    enabled: !!docRef,
  })

  const сохранитьСтороны = useMutation({
    mutationFn: () => saveStoreDocMeta(docRef as string, {
      responsible_from: сдал ?? data?.responsible_from ?? '',
      responsible_to: принял ?? data?.responsible_to ?? '',
    }),
    onSuccess: () => {
      toast.success('Стороны документа сохранены')
      qc.invalidateQueries({ queryKey: ['store-station-doc'] })
    },
    onError: (e: Error) => toast.error('Не сохранилось', { description: e.message }),
  })

  const приложить = useMutation({
    mutationFn: (f: File) => uploadStoreDocFile({
      docRef: docRef as string, kind: роль, stationId: data?.station_id, file: f,
    }),
    onSuccess: () => {
      toast.success('Образ приложен')
      qc.invalidateQueries({ queryKey: ['store-doc-files'] })
    },
    onError: (e: Error) => toast.error('Не удалось приложить', { description: e.message }),
  })
  const отвязать = useMutation({
    mutationFn: deleteStoreDocFile,
    onSuccess: () => {
      toast.success('Образ отвязан от документа')
      qc.invalidateQueries({ queryKey: ['store-doc-files'] })
    },
    onError: (e: Error) => toast.error('Не удалось отвязать', { description: e.message }),
  })

  return (
    <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Документ станции"
        className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-border/50 px-5 py-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold">
              {data ? `${data.label} № ${data.number ?? 'б/н'}` : 'Документ станции'}
              {data && <span className="ml-2 font-normal text-muted-foreground">
                АЗС {data.station_id} · {когда(data.doc_date ?? data.received_at)}
              </span>}
            </div>
            {data?.shift_number && (
              <div className="mt-0.5 text-[11px] text-muted-foreground">смена {data.shift_number}</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={!data}
              onClick={() => data && printStationDoc({
                ...data,
                responsible_from: сдал ?? data.responsible_from,
                responsible_to: принял ?? data.responsible_to,
              })}
              title="Печатная форма: акт или накладная с реквизитами и подписями">
              <Printer className="mr-1 h-3.5 w-3.5" />Печать
            </Button>
            <button onClick={onClose} aria-label="Закрыть"
              className="rounded-md p-1 text-muted-foreground hover:bg-accent/30 hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-muted-foreground">Загрузка документа…</div>
        ) : (
          <div className="space-y-4 overflow-auto p-4">
            <div className="grid grid-cols-2 gap-3 rounded-lg border border-border/50 bg-card/40 p-3 sm:grid-cols-4">
              <Факт label="Откуда" value={data.place_from} />
              <Факт label="Куда" value={data.place_to} />
              <Факт label="Контрагент" value={data.counterparty} />
              <Факт label="Договор" value={data.contract} />
              <Факт label="Входящий №" value={data.incoming_number} />
              <Факт label="Основание" value={data.basis} />
              <Факт label="Причина" value={data.reason} />
              <Факт label="Кто оформил" value={data.author} />
              <Факт label="Ответственный" value={data.responsible} />
              <Факт label="Сумма" value={data.amount ? fmtMoney(data.amount) : null} />
              <Факт label="Позиций" value={data.lines.length} />
            </div>

            <div className="overflow-x-auto rounded-lg border border-border/50">
              <table className="w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Товар</th>
                    <th className="px-3 py-2 text-left font-medium">Штрихкод</th>
                    <th className="px-3 py-2 text-right font-medium">Количество</th>
                    <th className="px-3 py-2 text-right font-medium">Цена</th>
                    <th className="px-3 py-2 text-right font-medium">Сумма</th>
                    <th className="px-3 py-2 text-left font-medium">НДС</th>
                    <th className="px-3 py-2 text-right font-medium">Марок</th>
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((l, i) => (
                    <tr key={i} className="border-t border-border/30">
                      <td className="px-3 py-1.5">{l.name}</td>
                      <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{l.barcode ?? '—'}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {nf(l.qty, 3)}
                        {l.qty_expected != null && l.qty_expected !== l.qty && (
                          <span className="ml-1 text-[10px] text-amber-300/90">заявлено {nf(l.qty_expected, 3)}</span>
                        )}
                        {l.qty_book != null && (
                          <span className="ml-1 text-[10px] text-muted-foreground">учёт {nf(l.qty_book, 3)}</span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {l.price != null ? fmtMoney(l.price) : '—'}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {l.amount != null ? fmtMoney(l.amount) : '—'}
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{l.vat_rate ?? '—'}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {l.marks || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.lines.length === 0 && (
                <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                  В документе нет строк — станция прислала только шапку.
                </div>
              )}
            </div>

            <div className="rounded-lg border border-border/50 p-3">
              <div className="mb-2 text-sm font-medium">Стороны документа</div>
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="text-xs">
                  <div className="text-[11px] text-muted-foreground">Сдал / материально ответственный</div>
                  <input value={сдал ?? data.responsible_from ?? ''}
                    onChange={(e) => задатьСдал(e.target.value)}
                    placeholder="фамилия и инициалы"
                    className="mt-1 h-8 w-full rounded-md border border-border/60 bg-background/60 px-2.5 text-xs outline-none focus:border-primary/60" />
                </label>
                <label className="text-xs">
                  <div className="text-[11px] text-muted-foreground">Принял</div>
                  <input value={принял ?? data.responsible_to ?? ''}
                    onChange={(e) => задатьПринял(e.target.value)}
                    placeholder="фамилия и инициалы"
                    className="mt-1 h-8 w-full rounded-md border border-border/60 bg-background/60 px-2.5 text-xs outline-none focus:border-primary/60" />
                </label>
                <div className="flex items-end">
                  <Button size="sm" variant="outline" disabled={сохранитьСтороны.isPending}
                    onClick={() => сохранитьСтороны.mutate()}>
                    <Save className="mr-1 h-3.5 w-3.5" />Сохранить
                  </Button>
                </div>
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
                Агент передаёт автора документа, но не материально ответственного. При передаче
                имущества между станциями подписи двух сторон — не формальность: без них
                непонятно, с кого спрашивать недостачу.
              </p>
            </div>

            <div className="rounded-lg border border-border/50">
              <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-3 py-2">
                <Paperclip className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">Образы документа</span>
                <span className="text-[11px] text-muted-foreground">
                  накладная, УПД, акт, опись — то, что предъявляют при проверке
                </span>
                <div className="ml-auto flex items-center gap-1.5">
                  <select value={роль} onChange={(e) => задатьРоль(e.target.value)}
                    aria-label="Роль образа"
                    className="h-7 rounded-md border border-border/60 bg-background/60 px-2 text-xs outline-none">
                    {РОЛИ.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <input ref={файл} type="file" className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) приложить.mutate(f)
                      e.target.value = ''
                    }} />
                  <Button size="sm" variant="outline" disabled={приложить.isPending}
                    onClick={() => файл.current?.click()}>
                    <Upload className="mr-1 h-3.5 w-3.5" />Приложить
                  </Button>
                </div>
              </div>

              {(образы?.files.length ?? 0) === 0 ? (
                <div className="px-3 py-4 text-xs leading-relaxed text-muted-foreground">
                  Образов нет. Учётная запись документа и его бумажное основание — разные вещи:
                  операция проведена, но предъявить при проверке нечего.
                </div>
              ) : (
                <table className="w-full text-xs">
                  <tbody>
                    {образы!.files.map((f) => (
                      <tr key={f.id} className="border-t border-border/30 first:border-t-0">
                        <td className="px-3 py-1.5">
                          <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            {f.kind}
                          </span>
                        </td>
                        <td className="px-3 py-1.5">
                          <a href={f.url} target="_blank" rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-primary hover:underline">
                            <FileText className="h-3.5 w-3.5" />{f.file_name}
                          </a>
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                          {объём(f.size_bytes)}
                        </td>
                        <td className="px-3 py-1.5 text-muted-foreground">{когда(f.uploaded_at)}</td>
                        <td className="px-3 py-1.5 text-right">
                          <button type="button" onClick={() => отвязать.mutate(f.id)}
                            disabled={отвязать.isPending}
                            title="Отвязать образ от документа (файл в хранилище останется)"
                            className="text-muted-foreground hover:text-red-400/90">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
