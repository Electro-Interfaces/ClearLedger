/**
 * «Что знает бухгалтерия» — блок карточки сущности пространства.
 *
 * Та же механика, что в приложении «Бухгалтерия», но в карточке договора,
 * контрагента или площадки: человек, открывший карточку, должен видеть сверку
 * здесь, а не искать её на другом экране. Логика живёт в сервисе и на сервере —
 * страница «Бухгалтерия» и этот блок читают одну сводку; подписи берутся из
 * общей отметки, второй копии правил здесь нет.
 *
 * Три оси показаны раздельно: сопряжение (опознана ли строка выгрузки), проверка
 * (что сверено с выгрузкой и что не сверялось — с причиной) и свежесть (правили
 * ли карточку после сверки). Свежесть видна и при расхождениях: это разные оси.
 * «Сопряжено» не значит «реквизиты сверены», и ни одно из этого не значит, что
 * проверен весь договор — сервер так и отвечает `entity_verified: false`.
 */
import { AlertTriangle, Loader2, RefreshCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  MARK_LABEL, recheckLine, полеRU, сравнение, дата,
} from '@/lib/accountingMark'
import { useAccountingMark } from '@/hooks/useAccountingMarks'
import { AccountingMark } from './AccountingMark'
import type { AccountingEntityType, AccountingLinkSummary } from '@/services/accountingSpaceService'

const ЗАГОЛОВОК = 'text-[11px] font-semibold uppercase tracking-widest text-muted-foreground/70'

export function AccountingLinkBlock({ entityType = 'contract', id }: {
  entityType?: AccountingEntityType
  id: string
}) {
  const { summary, state, loading, error, refetch } = useAccountingMark(entityType, id)
  return <div className="space-y-2 border-t border-border/50 pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className={ЗАГОЛОВОК}>Что знает бухгалтерия</p>
      {!loading && !error && <AccountingMark state={state} summary={summary} />}
    </div>

    {loading && <p className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />Загружается сверка с бухгалтерией</p>}

    {error && <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>Не удалось получить сверку — это ошибка запроса, а не отсутствие сведений.</span>
      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => void refetch()}>Повторить</Button>
    </div>}

    {!loading && !error && !summary && <p className="text-xs text-muted-foreground">
      Сведений по этой карточке сервер не вернул. {MARK_LABEL.no_source} — выгрузка охватывает
      свой период, и отсутствие строки не означает, что договора нет в учёте.</p>}

    {!loading && !error && summary && <Детали s={summary} />}
  </div>
}

function Детали({ s }: { s: AccountingLinkSummary }) {
  const сопряжение = Object.entries(s.matching.by_status)
    .filter(([, n]) => n)
    .map(([k, n]) => (s.matching.labels?.[k as keyof typeof s.matching.labels] ?? k) + ': ' + n)
  const сверено = s.verification.compared_fields ?? []
  const несверено = s.verification.unchecked_fields ?? []
  return <div className="flex flex-col gap-2 text-xs">
    {s.state_note && <p className="text-muted-foreground">{s.state_note}</p>}

    {/* Ось сопряжения — отдельной строкой: она отвечает «опознана ли запись»,
        а не «сверены ли реквизиты». */}
    <Строка label="Сопряжение" value={сопряжение.length
      ? сопряжение.join(' · ') + ' (строк источника ' + s.records + ')'
      : 'строк выгрузки на эту карточку нет'} />

    {/* Ось проверки — доказательствами, а не галочкой: что с чем сравнили и чем
        это кончилось. Снимок наших полей сверкой не является и показан отдельно. */}
    <div>
      <p className="text-muted-foreground">Сверено с выгрузкой:</p>
      {сверено.length
        ? <ul className="mt-0.5 flex flex-col gap-0.5">
            {сверено.map((f) => {
              // «Сравнивать нечего» — не конфликт: красным не красим.
              const и = сравнение(f)
              return <li key={f.field} className={и.tone === 'bad' ? 'text-destructive' : undefined}>
                {полеRU(f)} — {и.text}
                {f.evidence?.file && <span className="text-muted-foreground"> (источник: {f.evidence.file}
                  {f.evidence.rows ? ', строки ' + f.evidence.rows : ''})</span>}
              </li>
            })}
          </ul>
        : <p>ничего — реквизиты не сверялись</p>}
    </div>

    {!!несверено.length && <div>
      <p className="text-muted-foreground">Не сверялись:</p>
      <ul className="mt-0.5 flex flex-col gap-0.5">
        {несверено.map((f) => <li key={f.field}>
          {полеRU(f)}{f.reason ? <span className="text-muted-foreground"> — {f.reason}</span> : null}
        </li>)}
      </ul>
    </div>}

    {s.verification.snapshot_basis && <p className="text-muted-foreground">{s.verification.snapshot_basis}</p>}

    {/* Повторная сверка — отдельное свидетельство. Непринятый прогон говорит
        именно это, а не «сверки не было». */}
    {!!recheckLine(s.verification.recheck) && <p className={cn('text-muted-foreground',
      s.verification.recheck && !s.verification.recheck.applicable && 'text-amber-700 dark:text-amber-400')}>
      {recheckLine(s.verification.recheck)}</p>}

    {!!s.differences.length && <ul className="flex flex-col gap-0.5">
      {s.differences.map((d) => <li key={d.field} className="flex items-start gap-1.5 text-destructive">
        <AlertTriangle className="mt-0.5 size-3 shrink-0" />
        <span>{d.label}: в бухгалтерии «{d.source}», здесь «{d.space || '—'}»</span>
      </li>)}
    </ul>}

    {/* Ось свежести. Сервер выставляет её параллельно состоянию — в том числе при
        расхождениях, поэтому блок стоит отдельно, а не вместо расхождений. */}
    {s.freshness.stale && <p className="flex items-start gap-1.5 text-amber-700 dark:text-amber-400">
      <RefreshCcw className="mt-0.5 size-3 shrink-0" />
      <span>Карточку правили после сверки — проверку нужно повторить
        {s.freshness.stale_records > 1 ? ' (устаревших строк: ' + s.freshness.stale_records + ')' : ''}.</span>
    </p>}
    {(s.freshness.checked_at || s.freshness.rechecked_at) && <p className="text-muted-foreground">
      {s.freshness.checked_at && <>Сверено {дата(s.freshness.checked_at)}
        {s.freshness.checked_at_basis ? ' — ' + s.freshness.checked_at_basis : ''}. </>}
      {s.freshness.rechecked_at && <>Повторная сверка {дата(s.freshness.rechecked_at)}. </>}
      {s.freshness.baseline}
    </p>}

    {/* Источник: без файла и даты отметка — чьё-то слово. */}
    {s.sources.length
      ? <div className="flex flex-col gap-0.5 text-muted-foreground">
          {s.sources.map((src) => <span key={src.record_id}>
            {[src.file || 'файл не указан', src.sheet && 'лист ' + src.sheet,
              src.rows && 'строки ' + src.rows, src.period && 'период ' + src.period,
              src.as_of && 'данные на ' + дата(src.as_of)].filter(Boolean).join(' · ')}
          </span>)}
        </div>
      : <p className="text-muted-foreground">Источник не указан: строки выгрузки на карточку не легли.</p>}

    {/* Сводка по договорам у контрагента и площадки. Их собственная проверка этим
        не подтверждается — сказано словами, а не оставлено на догадку. */}
    {s.scope !== 'self' && s.aggregate && <div className="flex flex-col gap-1 rounded-md border border-border/50 bg-muted/20 p-2">
      <p className="font-medium">Договоров: {s.aggregate.contracts_total} ·
        со сведениями бухгалтерии {s.aggregate.with_source} ·
        без сведений {s.aggregate.without_source}</p>
      {!!Object.keys(s.aggregate.by_state).length && <p className="text-muted-foreground">
        {Object.entries(s.aggregate.by_state).filter(([, n]) => n)
          .map(([k, n]) => (MARK_LABEL[k as keyof typeof MARK_LABEL] ?? k) + ': ' + n).join(' · ')}</p>}
      <p className="text-muted-foreground">{s.scope_label
        || 'Отметка собрана из договоров; сама карточка отдельно не сверялась.'}</p>
      {!!s.aggregate.contracts.length && <ul className="flex flex-col gap-0.5">
        {s.aggregate.contracts.map((c) => <li key={c.id} className="flex flex-wrap items-center gap-1.5">
          <span>№ {c.number || '—'} от {c.date || '—'}</span>
          <AccountingMark compact state={c.state} />
        </li>)}
      </ul>}
    </div>}

    {/* Чего выгрузка не содержит — словами сервера: признака проведения в 1С нет,
        первичные документы не предоставлены. */}
    {s.disclaimer && <p className="text-muted-foreground">{s.disclaimer}</p>}
  </div>
}

function Строка({ label, value }: { label: string; value: string }) {
  return <p><span className="text-muted-foreground">{label}: </span>{value}</p>
}
