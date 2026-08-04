/**
 * «Магазин» → Маркировка → Проверка на кассе / Связь с ГИС МТ.
 *
 * Одна панель на два пункта, потому что предмет один: чем мы соединены с
 * государственными системами и что каждое соединение даёт. Разрешительный
 * режим — соединение особого рода: единственное, что обязано работать без
 * интернета, потому что решает, продастся ли пачка сигарет прямо сейчас.
 *
 * Экран честности: пока договора и УКЭП нет, ГИС МТ ничего нам не расскажет,
 * и цифры раздела — наш собственный учёт. Врать зелёными галочками тут нельзя:
 * за маркировку штрафуют.
 */
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck, Plug, CheckCircle2, AlertTriangle, MinusCircle } from 'lucide-react'
import { getStoreMarkingIntegrations } from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function StoreMarkingIntegrationsPanel({ view }: { view: 'perm_mode' | 'gismt' }) {
  const { company } = useCompany()
  const { data, isLoading, error } = useQuery({
    queryKey: ['store-marking-integrations', company.id],
    queryFn: getStoreMarkingIntegrations,
    refetchInterval: 120_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка подключений…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить состояние подключений</div>
  if (!data) return null

  if (view === 'perm_mode') {
    const модули = data.modules
    const живых = модули.filter((m) => m.ok).length
    const настроенных = модули.filter((m) => m.configured).length

    return (
      <div className="space-y-4 p-6">
        <div>
          <h3 className="text-base font-semibold">Разрешительный режим</h3>
          <p className="text-xs text-muted-foreground">
            Касса обязана спросить разрешение на продажу каждого маркированного товара, а с
            01.03.2025 на станции обязан стоять локальный модуль «Честного знака», отвечающий без
            сети (ПП РФ №1944). Умер модуль — касса перестаёт продавать табак и пиво.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Модуль отвечает</div>
            <div className={`mt-0.5 text-xl font-semibold tabular-nums ${
              настроенных > 0 && живых < настроенных ? 'text-red-400/90' : ''}`}>
              {живых} из {настроенных || модули.length}
            </div>
            <div className="text-[10px] text-muted-foreground/70">станций с настроенной проверкой</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Маркируемых SKU</div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums">{data.marked_skus}</div>
            <div className="text-[10px] text-muted-foreground/70">их продажа зависит от модуля</div>
          </div>
          <div className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">Товарные группы</div>
            <div className="mt-0.5 text-sm leading-relaxed">
              {Object.values(data.groups).slice(0, 4).join(' · ')}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">АЗС</th>
                <th className="px-3 py-2 text-left font-medium">Модуль</th>
                <th className="px-3 py-2 text-left font-medium">Статус</th>
                <th className="px-3 py-2 text-left font-medium">Версия</th>
                <th className="px-3 py-2 text-left font-medium">Проверен</th>
                <th className="px-3 py-2 text-left font-medium">Адрес</th>
              </tr>
            </thead>
            <tbody>
              {data.modules.map((m) => (
                <tr key={m.station_id} className="border-t border-border/30">
                  <td className="px-3 py-1.5 tabular-nums">{m.station_id}</td>
                  <td className="px-3 py-1.5">
                    {!m.configured
                      ? <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                          <MinusCircle className="h-3.5 w-3.5" />не настроен
                        </span>
                      : m.ok
                        ? <span className="inline-flex items-center gap-1.5 text-emerald-400/90">
                            <CheckCircle2 className="h-3.5 w-3.5" />отвечает
                          </span>
                        : <span className="inline-flex items-center gap-1.5 text-red-400/90">
                            <AlertTriangle className="h-3.5 w-3.5" />молчит
                          </span>}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {m.error ?? m.status ?? (m.configured ? '—' : 'адрес модуля не задан в агенте')}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{m.version ?? '—'}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{когда(m.checked_at)}</td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-muted-foreground">{m.url ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.modules.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              Ни один агент ещё не выходил на связь.
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border/50 bg-card/30 p-3 text-xs leading-relaxed text-muted-foreground">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground">
            <ShieldCheck className="h-4 w-4 text-primary" />Как это работает и что делаем не мы
          </div>
          Проверку кода и блокировку чека выполняет касса Нефтосервер: она спрашивает модуль,
          можно ли продать этот экземпляр, и модуль отвечает из локальной базы блокировок —
          интернет для ответа не нужен, он нужен для обновления базы. Наша зона — чтобы модуль
          был жив, база свежая, а отказы кто-то читал. Агент опрашивает модуль по адресу из
          своего конфига (<code className="font-mono">mark_module_url</code>) и присылает
          состояние вместе с телеметрией: до localhost станции центр иначе не дотянется.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Связь с ГИС МТ и внешними системами</h3>
        <p className="text-xs text-muted-foreground">
          Чем мы подключены к государственным системам, что каждая даёт и чего ей не хватает.
          Пока подключение не оформлено, экраны маркировки живут на собственном учёте — и
          показывают это прямо, а не зелёной галочкой.
        </p>
      </div>

      <div className="space-y-2.5">
        {data.systems.map((с) => (
          <div key={с.key} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Plug className={`h-4 w-4 ${с.connected ? 'text-emerald-400/90' : 'text-muted-foreground'}`} />
              <span className="text-sm font-medium">{с.name}</span>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] ${с.connected
                ? 'border-emerald-400/40 text-emerald-300/90'
                : 'border-border/60 text-muted-foreground'}`}>
                {с.connected ? 'подключено' : 'не подключено'}
              </span>
            </div>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[7rem_1fr]">
              <dt className="text-muted-foreground">Что даёт</dt>
              <dd className="leading-relaxed">{с.gives}</dd>
              <dt className="text-muted-foreground">Что нужно</dt>
              <dd className="leading-relaxed text-muted-foreground">{с.needs}</dd>
              <dt className="text-muted-foreground">Ограничения</dt>
              <dd className="leading-relaxed text-muted-foreground">{с.limits}</dd>
            </dl>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-border/50 bg-card/30 p-3 text-xs leading-relaxed text-muted-foreground">
        <div className="mb-1 font-medium text-foreground">Как это ляжет на офлайн-станцию</div>
        С ГИС МТ говорит центр: у него интернет, УКЭП и договор, а станция за CGNAT и может
        неделю жить без канала. Станция накапливает факты — сканы кодов при приёмке, списании,
        возврате, — и отдаёт их пакетом. Заявления в ГИС МТ (передача владения, вывод из оборота)
        уходят очередью с повторами: канал до ЦРПТ падает, а обязанность остаётся. Единственное
        исключение — разрешительный режим: он живёт на станции, потому что решает, продастся ли
        товар в ближайшую минуту.
      </div>
    </div>
  )
}
