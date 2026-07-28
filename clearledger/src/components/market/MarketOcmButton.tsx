/**
 * Загрузка рынка из Open Charge Map — одной кнопкой по всей нашей сети.
 *
 * Область не спрашиваем: рынок нужен там, где стоят наши объекты, и сервер сам берёт
 * прямоугольники по городам сети. «Загрузить всю Россию» было бы и медленно, и вредно —
 * лишние тысячи точек размывают окружение объекта.
 *
 * Ключа нет — кнопка честно говорит об этом и не притворяется рабочей.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, CloudDownload } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCompany } from '@/contexts/CompanyContext'
import { ocmStatus, ocmImportNetwork } from '@/services/marketService'

export function MarketOcmButton() {
  const { companyId } = useCompany()
  const qc = useQueryClient()

  const status = useQuery({
    queryKey: ['ocm-status', companyId],
    queryFn: () => ocmStatus(companyId),
    enabled: !!companyId,
    staleTime: 5 * 60_000,
  })

  const run = useMutation({
    mutationFn: () => ocmImportNetwork(companyId),
    onSuccess: (r) => {
      toast.success(
        `Города: ${r.areas}/${r.cities} · заведено ${r.created}, обновлено ${r.updated}, цен ${r.prices}`,
        { description: r.problems.length ? r.problems.slice(0, 3).join('; ') : undefined },
      )
      qc.invalidateQueries({ queryKey: ['market-sites'] })
      qc.invalidateQueries({ queryKey: ['market-position'] })
      qc.invalidateQueries({ queryKey: ['market-operators'] })
      qc.invalidateQueries({ queryKey: ['market-observations'] })
    },
    onError: (e: Error) => toast.error(e.message || 'Импорт не прошёл'),
  })

  const ready = status.data?.configured === true

  const button = (
    <button type="button" disabled={!ready || run.isPending} onClick={() => run.mutate()}
      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs
                 transition-colors hover:bg-accent disabled:opacity-50">
      {run.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <CloudDownload className="size-3.5" />}
      {run.isPending ? 'Загружаем рынок…' : 'Open Charge Map'}
    </button>
  )

  if (ready) return button
  return (
    <Tooltip>
      <TooltipTrigger asChild><span>{button}</span></TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        Ключ Open Charge Map не настроен. Получите бесплатный ключ на openchargemap.org
        и добавьте `OCM_API_KEY` в окружение стека — кнопка оживёт.
      </TooltipContent>
    </Tooltip>
  )
}
