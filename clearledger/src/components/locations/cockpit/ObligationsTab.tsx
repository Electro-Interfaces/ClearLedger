/**
 * «Обязательства» станции — вся договорная обвязка площадки в одном месте.
 *
 * Реестры «Контрагенты» и «Договоры» смотрят со стороны сделки: с кем мы
 * связаны и на что. Инженер приходит с другой стороны — от станции: чем она
 * обвязана, кто по ней отвечает, что и когда платится, до какого числа
 * гарантия. Данные те же, разрез обратный; поэтому здесь не новый учёт, а
 * сборка по оси объекта.
 *
 * Порядок ролей — не алфавитный и не по сумме: сверху то, из-за чего станция
 * стоит (поставка, сервис, монтаж), ниже то, из-за чего с нами судятся
 * (энергия, аренда). Инженер открывает эту вкладку, когда станция не работает.
 *
 * Пробелы показываем явно. «Условия ответственности не заведены» — это не
 * пустое место в карточке, а причина, по которой претензию сегодня написать
 * нельзя: в ней должен стоять пункт договора и срок.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, CalendarClock, FileSignature, Gauge, Loader2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { getStationObligations, type ObligationContract } from '@/services/opsService'
import { Button } from '@/components/ui/button'
import { LiabilityDialog } from '@/components/locations/LiabilityDialog'
import { ScrollTab } from './shared'

const nf = new Intl.NumberFormat('ru-RU')

const дата = (iso?: string | null) => iso
  ? iso.split('-').reverse().join('.')
  : '—'

const СТАТУС_ОПЛАТЫ: Record<string, { label: string; cls: string }> = {
  paid: { label: 'оплачено', cls: 'text-emerald-600 dark:text-emerald-400' },
  partial: { label: 'частично', cls: 'text-amber-600 dark:text-amber-400' },
  debt: { label: 'долг', cls: 'text-red-600 dark:text-red-400' },
  unknown: { label: 'неизвестно', cls: 'text-muted-foreground' },
}

const РОЛЬ_РАСЧЁТА: Record<string, string> = {
  energy: 'Энергоснабжение', rent: 'Аренда', service: 'Сервис',
}

/** Строка договора: реквизиты, охват, условия и ответственность. */
function Договор({ c, условия, onУсловия }: {
  onУсловия: () => void
  c: ObligationContract
  условия: { costItem: string; periodicity: string; amountGross: number | null
             tariffRub: number | null; payDueDay: number | null
             counterpartyEmail: string | null; note: string | null }[]
}) {
  const истёк = c.validUntil && c.validUntil < new Date().toISOString().slice(0, 10)
  return (
    <div className={cn('space-y-1.5 rounded-md border border-border/50 p-3 text-sm',
      c.isClosed && 'opacity-60')}>
      <div className="flex flex-wrap items-center gap-2">
        <FileSignature className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-medium">{c.number || 'б/н'}</span>
        <span className="text-xs text-muted-foreground">от {дата(c.date)}</span>
        {c.scope === 'company' && (
          <Badge variant="secondary" className="text-[10px]">общий по компании</Badge>
        )}
        {c.locationsCount > 1 && (
          <span className="text-xs text-muted-foreground">
            ещё {nf.format(c.locationsCount - 1)} станц.
          </span>
        )}
        {c.isClosed && <Badge variant="secondary" className="text-[10px]">закрыт</Badge>}
      </div>

      <div className="text-xs text-muted-foreground">
        {c.counterparty ?? '— контрагент не указан'}
        {c.basis && c.basis !== 'договор' && <> · основание: {c.basis}</>}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className={cn(истёк && 'text-red-600 dark:text-red-400')}>
          <CalendarClock className="mr-1 inline size-3" />
          {c.validUntil ? `действует до ${дата(c.validUntil)}` : 'срок не указан'}
          {истёк && ' — истёк'}
        </span>
        {/* Ответственность — то, из-за чего эта вкладка вообще нужна инженеру:
            без срока устранения и санкции претензию писать не на что. */}
        {c.liability ? (
          <span className="text-emerald-600 dark:text-emerald-400">
            устранение {c.liability.fixDays ?? '—'} дн
            {c.liability.penaltyValue
              ? ` · санкция ${nf.format(c.liability.penaltyValue)}${c.liability.penaltyKind === 'per_day_pct' ? ' %/дн' : ' ₽/дн'}`
              : ''}
            {c.liability.warrantyUntil && ` · гарантия до ${дата(c.liability.warrantyUntil)}`}
          </span>
        ) : (c.role === 'supply' || c.role === 'maintenance') && (
          <span className="text-amber-600 dark:text-amber-400">
            условия ответственности не заведены
          </span>
        )}
        {(c.role === 'supply' || c.role === 'maintenance') && (
          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs"
            onClick={onУсловия}>
            {c.liability ? 'Изменить условия' : 'Задать условия'}
          </Button>
        )}
      </div>

      {условия.length > 0 && (
        <div className="space-y-0.5 border-t border-border/40 pt-1.5 text-xs text-muted-foreground">
          {условия.map((t, i) => (
            <div key={i}>
              {t.costItem}
              {t.amountGross != null && ` · ${nf.format(t.amountGross)} ₽`}
              {t.tariffRub != null && ` · ${t.tariffRub} ₽/кВт·ч`}
              {t.periodicity === 'monthly' && ' в месяц'}
              {t.payDueDay != null && ` · платим до ${t.payDueDay} числа`}
              {t.counterpartyEmail && ` · ${t.counterpartyEmail}`}
              {t.note && ` · ${t.note}`}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ObligationsTab({ location }: { location: { id: string } }) {
  const { companyId } = useCompany()
  // Какой договор правим: условия ответственности живут на договоре, а не на
  // станции — правка отсюда меняет их для всех его площадок, и это нормально.
  const [условияДля, setУсловияДля] = useState<ObligationContract | null>(null)
  const q = useQuery({
    queryKey: ['station-obligations', companyId, location.id],
    queryFn: () => getStationObligations(companyId, location.id),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  if (q.isLoading) {
    return <ScrollTab><div className="flex justify-center py-10">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div></ScrollTab>
  }
  if (!q.data?.found) {
    return <ScrollTab>
      <p className="p-4 text-sm text-muted-foreground">Объект не найден в реестре.</p>
    </ScrollTab>
  }

  const d = q.data

  return (
    <ScrollTab>
      <div className="space-y-4 xl:columns-2 xl:space-y-0 xl:[&>*]:mb-4 xl:[&>*]:break-inside-avoid">
        {/* Пробелы сверху: пустая графа в паспорте — это задача, а не оформление. */}
        {d.gaps.length > 0 && (
          <div className="space-y-1 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
            <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
              <AlertTriangle className="size-3.5" />Чего не хватает
            </div>
            {d.gaps.map((g, i) => (
              <div key={i} className="text-xs text-muted-foreground">· {g}</div>
            ))}
          </div>
        )}

        {d.settlements.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Платёжная дисциплина
            </div>
            <div className="flex flex-wrap gap-2">
              {d.settlements.map((s) => {
                const м = СТАТУС_ОПЛАТЫ[s.paymentStatus] ?? СТАТУС_ОПЛАТЫ.unknown
                return (
                  <div key={s.role} className="rounded-md border border-border/50 px-3 py-2 text-sm">
                    <div className="text-xs text-muted-foreground">
                      {РОЛЬ_РАСЧЁТА[s.role] ?? s.role}
                    </div>
                    <div className={cn('text-sm font-medium', м.cls)}>
                      {м.label}
                      {s.paidThrough && (
                        <span className="ml-1 text-xs font-normal text-muted-foreground">
                          по {дата(s.paidThrough)}
                        </span>
                      )}
                    </div>
                    {s.comment && (
                      <div className="max-w-[260px] truncate text-xs text-muted-foreground"
                        title={s.comment}>{s.comment}</div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {d.groups.map((g) => (
          <div key={g.role} className="space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {g.label}
            </div>
            {g.contracts.map((c) => (
              <Договор key={c.id} c={c} условия={g.terms[c.id] ?? []}
                onУсловия={() => setУсловияДля(c)} />
            ))}
          </div>
        ))}

        {d.documents.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Документы площадки
            </div>
            {d.documents.map((doc) => (
              <div key={doc.id} className="rounded-md border border-border/50 p-2 text-sm">
                {doc.number ?? '—'} · {doc.title}
                <span className="ml-2 text-xs text-muted-foreground">{дата(doc.date)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Поверка счётчиков: раздел зарезервирован и честно пуст — данных нет. */}
        <div className="rounded-md border border-dashed border-border/60 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Gauge className="size-3.5" />Счётчик и поверка
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">{d.metering.note}</div>
        </div>

        {!d.groups.length && (
          <p className="text-sm text-muted-foreground">
            По этой станции договоров в реестре нет.
          </p>
        )}
      </div>

      {условияДля && (
        <LiabilityDialog contract={условияДля} open
          onClose={() => setУсловияДля(null)} />
      )}
    </ScrollTab>
  )
}
