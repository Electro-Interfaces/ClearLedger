/**
 * «Магазин» → Станции → Хранение сырья.
 *
 * Пакет станции остаётся в базе как есть (L1) — из него можно переиграть
 * разбор, и это правило проекта. Но снимок остатков приходит каждый час и
 * весит около полумегабайта: одна станция откладывает треть гигабайта в месяц,
 * а нужен из них ровно последний.
 *
 * Экран показывает, чем занято хранилище, и прореживает историю снимков:
 * остаётся самый свежий за каждый день. Документы и смены не трогаются
 * вовсе — это первичка, из которой построен учёт.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Database, Trash2, Eye } from 'lucide-react'
import {
  getStoreStorage, cleanupStoreStorage, getStoreDocFilesSummary,
  storeDocFilesArchiveUrl, type StoreStorageCleanup,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

function объём(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} ГБ`
}

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU',
    { day: '2-digit', month: '2-digit', year: '2-digit' })
}

export function StoreStoragePanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [дней, задатьДней] = useState(14)
  const [телеметрия, задатьТелеметрию] = useState(90)
  const [оценка, задатьОценку] = useState<StoreStorageCleanup | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-storage', company.id],
    queryFn: getStoreStorage,
  })
  // Образы первички считаем отдельно от сырья: сырьё прореживают, а
  // первичный документ обязан храниться пять лет (ФЗ-402).
  const { data: образы } = useQuery({
    queryKey: ['store-doc-files-summary', company.id],
    queryFn: getStoreDocFilesSummary,
  })

  const чистка = useMutation({
    mutationFn: cleanupStoreStorage,
    onSuccess: (r) => {
      задатьОценку(r)
      if (!r.dry_run) {
        toast.success(`Удалено снимков: ${r.snapshots} · освобождено ${объём(r.bytes)}`)
        qc.invalidateQueries({ queryKey: ['store-storage'] })
        qc.invalidateQueries({ queryKey: ['store-exchange'] })
      }
    },
    onError: (e: Error) => toast.error('Чистка не выполнена', { description: e.message }),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Считаем хранилище…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить размеры хранилища</div>
  if (!data) return null

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Хранение сырья</h3>
        <p className="text-xs text-muted-foreground">
          Пакет станции хранится как есть — из него можно переиграть разбор. Но снимок остатков
          приходит каждый час и весит около полумегабайта, а нужен из них последний. Документы и
          смены — первичка учёта, они не прореживаются.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Database className="h-3.5 w-3.5" />Всего сырья
          </div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{объём(data.total_bytes)}</div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">След телеметрии</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{data.heartbeats.rows}</div>
          <div className="text-[10px] text-muted-foreground/70">
            записей с {когда(data.heartbeats.oldest)}
          </div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Станций в хранилище</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{data.stations.length}</div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Вид пакета</th>
              <th className="px-3 py-2 text-right font-medium">Пакетов</th>
              <th className="px-3 py-2 text-right font-medium">Объём</th>
              <th className="px-3 py-2 text-left font-medium">Самый старый</th>
              <th className="px-3 py-2 text-left font-medium">Самый свежий</th>
              <th className="px-3 py-2 text-left font-medium">Хранение</th>
            </tr>
          </thead>
          <tbody>
            {data.kinds.map((k) => (
              <tr key={k.kind} className="border-t border-border/30">
                <td className="px-3 py-1.5">{k.label}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{k.packets}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{объём(k.bytes)}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{когда(k.oldest)}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{когда(k.newest)}</td>
                <td className="px-3 py-1.5 text-muted-foreground">
                  {k.keep
                    ? 'первичка — храним всё'
                    : <span className="text-amber-300/90">прореживается до одного в день</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-border/50 bg-card/30 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">Образы первичных документов</span>
          <span className="text-[11px] text-muted-foreground">
            накладные, УПД, акты и описи — хранятся {образы?.retention_years ?? 5} лет и не прореживаются
          </span>
          <a href={storeDocFilesArchiveUrl({})} className="ml-auto text-xs text-primary hover:underline"
             title="Скачать все образы пачкой: zip с файлами и описью">
            выгрузить пачкой
          </a>
        </div>
        {(образы?.total?.files ?? 0) === 0 ? (
          <div className="text-xs text-muted-foreground">
            Образов ещё нет. Документ без бумажного основания существует в учёте, но при
            проверке предъявить нечего.
          </div>
        ) : (
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <span className="text-muted-foreground">Файлов{' '}
              <span className="font-medium tabular-nums text-foreground">{образы!.total.files}</span>
            </span>
            <span className="text-muted-foreground">Документов{' '}
              <span className="font-medium tabular-nums text-foreground">{образы!.total.docs}</span>
            </span>
            <span className="text-muted-foreground">Объём{' '}
              <span className="font-medium tabular-nums text-foreground">{объём(образы!.total.bytes)}</span>
            </span>
            <span className="text-muted-foreground">Самый старый{' '}
              <span className="tabular-nums text-foreground">{когда(образы!.total.oldest)}</span>
            </span>
            {образы!.kinds.length > 0 && (
              <span className="text-muted-foreground">
                {образы!.kinds.map((k) => `${k.kind}: ${k.files}`).join(' · ')}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border/50 bg-card/30 p-3">
        <div className="mb-2 text-sm font-medium">Проредить историю</div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs">
            <div className="text-[11px] text-muted-foreground">Снимки старше, дней</div>
            <input type="number" min={3} value={дней}
              onChange={(e) => задатьДней(Number(e.target.value))}
              className="mt-1 h-8 w-24 rounded-md border border-border/60 bg-background/60 px-2 text-xs tabular-nums outline-none focus:border-primary/60" />
          </label>
          <label className="text-xs">
            <div className="text-[11px] text-muted-foreground">Телеметрию хранить, дней</div>
            <input type="number" min={7} value={телеметрия}
              onChange={(e) => задатьТелеметрию(Number(e.target.value))}
              className="mt-1 h-8 w-24 rounded-md border border-border/60 bg-background/60 px-2 text-xs tabular-nums outline-none focus:border-primary/60" />
          </label>
          <Button size="sm" variant="outline" disabled={чистка.isPending}
            onClick={() => чистка.mutate({
              thin_after_days: дней, heartbeat_days: телеметрия, dry_run: true,
            })}>
            <Eye className="mr-1 h-3.5 w-3.5" />Посчитать
          </Button>
          <Button size="sm" variant="destructive"
            disabled={чистка.isPending || !оценка || оценка.snapshots + оценка.heartbeats === 0}
            onClick={() => чистка.mutate({
              thin_after_days: дней, heartbeat_days: телеметрия, dry_run: false,
            })}>
            <Trash2 className="mr-1 h-3.5 w-3.5" />Удалить
          </Button>
        </div>

        {оценка && (
          <div className="mt-2.5 rounded-md border border-border/50 bg-background/40 p-2.5 text-xs">
            {оценка.dry_run ? 'Под правило попадает: ' : 'Удалено: '}
            <span className="tabular-nums font-medium">{оценка.snapshots}</span> снимков
            {' '}({объём(оценка.bytes)}) и{' '}
            <span className="tabular-nums font-medium">{оценка.heartbeats}</span> записей телеметрии.
            {оценка.dry_run && оценка.snapshots + оценка.heartbeats > 0 && (
              <span className="text-muted-foreground"> Данные станции восстановить неоткуда —
                удаление необратимо.</span>
            )}
          </div>
        )}

        <p className="mt-2 text-[10px] text-muted-foreground/70">
          Остаётся самый свежий снимок каждой станции за каждый день. Снимок документов учёта не
          порождает, поэтому отчёты от чистки не меняются. Выполняет администратор компании.
        </p>
      </div>
    </div>
  )
}
