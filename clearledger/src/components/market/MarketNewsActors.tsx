/**
 * Профессиональные разрезы новостного потока: участники рынка и их связи.
 *
 * «Маркетинг» — не читалка: новость здесь материал для разбора, а разбор
 * рынка идёт по участникам и тому, кто с кем появляется. Отсюда два вида:
 *
 *   Участники — кто действует на рынке по публикациям: роль из реестра, число
 *     материалов, темы и дата последнего упоминания. Молчание тоже факт: сеть,
 *     о которой полгода ничего, ведёт себя иначе, чем сеть в заголовках.
 *   Связи — пары участников из одних материалов. Это НАБЛЮДЕНИЕ, не утверждение
 *     об отношениях: «Парус электро» и «Росатом» в одном тексте могут быть
 *     поставкой, а могут — двумя абзацами обзора. Поэтому рядом с числом всегда
 *     перечислены материалы, из которых связь сложилась.
 *
 * Роль участника берётся из реестра, а не из текста: оператор остаётся
 * оператором, даже если в материале он назван «компанией». Производителей в
 * реестрах продукта не было вовсе (поле `vendor` у точек пустое у всех записей),
 * поэтому их ведёт отдельный справочник на вкладке «Управление».
 */
import { ArrowLeftRight, Building2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  ACTOR_ROLE_LABEL, ACTOR_ROLE_ORDER, NEWS_TOPIC_LABEL,
  type MarketLink, type MarketParticipant, type MarketNewsTopic,
} from '@/services/marketService'

const дата = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })

function когда(iso: string | null): string {
  if (!iso) return 'даты нет'
  const дней = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (дней <= 0) return 'сегодня'
  if (дней === 1) return 'вчера'
  if (дней < 60) return `${дней} дн назад`
  return дата.format(new Date(iso))
}

export function RoleFilter({ value, counts, onChange }: {
  value: string
  counts: Record<string, number>
  onChange: (v: string) => void
}) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <Button size="sm" variant={value === 'all' ? 'default' : 'outline'} className="h-7 text-xs"
        onClick={() => onChange('all')}>Все роли</Button>
      {ACTOR_ROLE_ORDER.filter((r) => counts[r]).map((r) => (
        <Button key={r} size="sm" variant={value === r ? 'default' : 'outline'} className="h-7 text-xs"
          onClick={() => onChange(value === r ? 'all' : r)}>
          {ACTOR_ROLE_LABEL[r]} {counts[r]}
        </Button>
      ))}
    </span>
  )
}

/** Строка участника: кто, в какой роли, сколько о нём писали и о чём. */
export function ParticipantRow({ p, onNews, onLinks }: {
  p: MarketParticipant
  onNews: (name: string) => void
  onLinks: (name: string) => void
}) {
  const темы = Object.entries(p.byTopic).sort((a, b) => b[1] - a[1]).slice(0, 4)
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{p.name}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs
                           text-muted-foreground">
            <span className="text-primary">{p.roleLabel}</span>
            <span aria-hidden>·</span>
            <span className="tabular-nums">материалов {p.news}</span>
            <span aria-hidden>·</span>
            <span>последний {когда(p.lastAt)}</span>
            {темы.map(([t, n]) => (
              <span key={t}>· {NEWS_TOPIC_LABEL[t as MarketNewsTopic] ?? t} {n}</span>
            ))}
          </span>
        </span>
        <span className="flex items-center gap-2" data-export-ignore>
          <Button size="sm" variant="outline" className="h-7 text-xs"
            onClick={() => onNews(p.name)}>Материалы</Button>
          <Button size="sm" variant="ghost" className="h-7 text-xs"
            onClick={() => onLinks(p.name)}>Связи</Button>
        </span>
      </CardContent>
    </Card>
  )
}

/** Пара участников и материалы, из которых связь сложилась. */
export function LinkRow({ l, onNews }: { l: MarketLink; onNews: (name: string) => void }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <button type="button" className="text-sm font-semibold hover:text-primary hover:underline"
            onClick={() => onNews(l.a.name)}>{l.a.name}</button>
          <ArrowLeftRight className="size-3.5 text-muted-foreground" aria-hidden />
          <button type="button" className="text-sm font-semibold hover:text-primary hover:underline"
            onClick={() => onNews(l.b.name)}>{l.b.name}</button>
          <span className="text-xs text-muted-foreground">
            {l.a.roleLabel} ↔ {l.b.roleLabel}
          </span>
          <span className="ml-auto text-xs tabular-nums text-muted-foreground">
            вместе в {l.news} материалах
          </span>
        </div>
        {/* Связь показывает, из чего собрана: иначе число — утверждение без основания. */}
        <ul className="space-y-0.5">
          {l.examples.map((e) => (
            <li key={e.title} className="truncate text-xs text-muted-foreground">
              {e.publishedAt ? `${дата.format(new Date(e.publishedAt))} · ` : ''}{e.title}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/** Справочник участников: производители, сервис, ведомства, энергетика. */
export function ActorsAdmin({ actors, loading, onPatch, onRescan, rescanning, rescanResult }: {
  actors: { id: string; name: string; kind: string; kindLabel: string; aliases: string[]
            confirmed: boolean; mentions: number }[]
  loading: boolean
  onPatch: (id: string, body: Record<string, unknown>) => void
  onRescan: () => void
  rescanning: boolean
  rescanResult: { news: number; added: number } | undefined
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-medium">Участники рынка вне реестров</span>
          <span className="text-xs text-muted-foreground">
            сети и приложения ведутся своими реестрами; здесь производители, сервис,
            ведомства и энергетика
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2" data-export-ignore>
          <Button size="sm" variant="outline" className="h-7 text-xs" disabled={rescanning}
            onClick={onRescan}>
            {rescanning
              ? <><Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />Перечитываем…</>
              : 'Перечитать упоминания'}
          </Button>
          {rescanResult && (
            <span className="text-xs text-muted-foreground">
              просмотрено материалов {rescanResult.news}, новых упоминаний {rescanResult.added}
            </span>
          )}
        </div>
        {loading && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Загружаем справочник…
          </p>
        )}
        {!loading && actors.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Справочник пуст. Производителей оборудования в реестрах продукта нет —
            их имена приходят из новостей, заведите первых здесь.
          </p>
        )}
        {actors.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b
                                     border-border py-2 text-xs last:border-0">
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">{a.name}</span>
              <span className="text-muted-foreground">
                {a.kindLabel}
                {a.aliases.length > 0 ? ` · пишут также: ${a.aliases.join(', ')}` : ''}
              </span>
            </span>
            <span className="tabular-nums text-muted-foreground">упоминаний {a.mentions}</span>
            <Select value={a.kind} onValueChange={(v) => onPatch(a.id, { kind: v })}>
              <SelectTrigger className="h-7 w-[220px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries({
                  vendor: 'производитель оборудования', service: 'сервис и монтаж',
                  state: 'государство и регулятор', utility: 'энергетика и сети',
                  other: 'прочее',
                }).map(([k, label]) => <SelectItem key={k} value={k}>{label}</SelectItem>)}
              </SelectContent>
            </Select>
            {!a.confirmed && (
              <Button size="sm" variant="outline" className="h-7 text-xs"
                onClick={() => onPatch(a.id, { confirmed: true })}>Подтвердить</Button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

/** Пустое состояние разрезов: объясняет, чего не хватает, а не просто молчит. */
export function NoActors({ kind }: { kind: 'participants' | 'links' }) {
  return (
    <p className="flex items-start gap-2 p-2 text-sm text-muted-foreground">
      <Building2 className="mt-0.5 size-4 shrink-0" aria-hidden />
      {kind === 'participants'
        ? 'Участники не распознаны. Они берутся из реестра сетей и приложений и из справочника на вкладке «Управление»; после правки справочника нажмите «Перечитать упоминания».'
        : 'Связей пока нет: они появляются, когда в одном материале названы хотя бы двое. Пополните справочник участников и перечитайте упоминания.'}
    </p>
  )
}
